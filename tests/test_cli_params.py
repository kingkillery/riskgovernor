import json
from decimal import Decimal

import pytest

from riskgovernor.cli import format_report, main
from riskgovernor.governor import Governor
from riskgovernor.ledger import Ledger
from riskgovernor.params import MissingConfigError, ParamStore

from tests.test_policy import make_policy

POLICY = {
    "unit": "u",
    "scale": "1",
    "gates": {"floor": "75", "max_consecutive_losses": 3, "max_drawdown": "30"},
    "strategies": [
        {
            "id": "a",
            "config_files": ["a.json"],
            "command": "run {episode} {config} {note_arg}",
            "recovery": {
                "params": {"max_loss": "1"},
                "size_param": "max_profit",
                "cap": "2",
            },
        },
        {"id": "b", "command": "run {episode} b"},
        {"id": "c", "command": "run {episode} c"},
    ],
}


# -- ParamStore ---------------------------------------------------------


def test_apply_updates_only_listed_keys(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"keep": 1, "max_profit": "0"}), encoding="utf-8")
    written = ParamStore(tmp_path).apply({"a.json": {"max_profit": "2"}})
    assert written == ["a.json"]
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {
        "keep": 1,
        "max_profit": "2",
    }


def test_apply_validates_before_writing_anything(tmp_path):
    (tmp_path / "a.json").write_text('{"max_profit": "0"}', encoding="utf-8")
    store = ParamStore(tmp_path)
    with pytest.raises(MissingConfigError):
        store.apply({"a.json": {"max_profit": "2"}, "gone.json": {"x": 1}})
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {
        "max_profit": "0"
    }


def test_apply_dry_run_writes_nothing(tmp_path):
    (tmp_path / "a.json").write_text('{"max_profit": "0"}', encoding="utf-8")
    store = ParamStore(tmp_path)
    assert store.apply({"a.json": {"max_profit": "2"}}, dry_run=True) == []
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {
        "max_profit": "0"
    }


def test_apply_rejects_non_object_config(tmp_path):
    (tmp_path / "a.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        ParamStore(tmp_path).apply({"a.json": {"max_profit": "2"}})


# -- report formatting --------------------------------------------------


def test_format_report_halt_and_headroom():
    policy = make_policy(floor=Decimal("75"))
    decision = Governor(policy).decide(
        Ledger.from_dict({"episodes": [{"id": 1, "net": "1", "strategy": "a"}]}),
        equity=Decimal("74"),
    )
    text = format_report(decision, policy)
    assert "VERDICT: HALT (equity below floor)" in text
    assert "floor headroom: -1.00" in text


def test_format_report_standard_lists_options():
    policy = make_policy()
    decision = Governor(policy).decide(
        Ledger.from_dict({"episodes": [{"id": 1, "net": "1", "strategy": "a"}]})
    )
    text = format_report(decision, policy)
    assert "VERDICT: STANDARD" in text
    assert "[1]" in text and "[3]" in text


# -- CLI ----------------------------------------------------------------


def setup(tmp_path, rows):
    (tmp_path / "policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
    (tmp_path / "ledger.json").write_text(json.dumps({"episodes": rows}), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps({"keep": True, "max_profit": "0"}), encoding="utf-8")
    return str(tmp_path / "policy.json"), str(tmp_path / "ledger.json")


def test_cli_recovery_writes_config_and_prints_command(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "-1", "strategy": "c"}])
    code = main(["--policy", policy, "--ledger", ledger, "--equity", "100"])
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT: RECOVERY a" in out
    assert "wrote a.json" in out
    assert "run 2 a.json" in out
    data = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert data["max_profit"] == "1"
    assert data["keep"] is True


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "-1", "strategy": "c"}])
    code = main(["--policy", policy, "--ledger", ledger, "--equity", "100", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "dry-run" in out
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))["max_profit"] == "0"


def test_cli_halt_on_floor(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "1", "strategy": "a"}])
    code = main(["--policy", policy, "--ledger", ledger, "--equity", "70"])
    assert code == 0
    assert "VERDICT: HALT (equity below floor)" in capsys.readouterr().out


def test_cli_json_output(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "1", "strategy": "a"}])
    code = main(["--policy", policy, "--ledger", ledger, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["verdict"] == "STANDARD"
    assert set(payload["commands"]) == {"a", "b", "c"}


def test_cli_missing_config_exits_1(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "-1", "strategy": "c"}])
    (tmp_path / "a.json").unlink()
    code = main(["--policy", policy, "--ledger", ledger, "--equity", "100"])
    assert code == 1
    assert "missing parameter file" in capsys.readouterr().err


def test_cli_bad_equity_exits_1(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "1", "strategy": "a"}])
    code = main(["--policy", policy, "--ledger", ledger, "--equity", "abc"])
    assert code == 1
    assert "not numeric" in capsys.readouterr().err


def test_cli_missing_ledger_warns_but_proceeds(tmp_path, capsys):
    (tmp_path / "policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
    code = main(["--policy", str(tmp_path / "policy.json"), "--ledger", str(tmp_path / "nope.json")])
    captured = capsys.readouterr()
    assert code == 0
    assert "not found; treating as empty" in captured.err
    assert "VERDICT: STANDARD" in captured.out


def test_cli_corrupt_ledger_is_refused_not_emptied(tmp_path, capsys):
    (tmp_path / "policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
    (tmp_path / "ledger.json").write_text("{not json", encoding="utf-8")
    code = main(["--policy", str(tmp_path / "policy.json"), "--ledger", str(tmp_path / "ledger.json")])
    captured = capsys.readouterr()
    assert code == 1
    assert "not valid JSON" in captured.err


def test_cli_fresh_empty_ledger_prints_no_warning(tmp_path, capsys):
    (tmp_path / "policy.json").write_text(json.dumps(POLICY), encoding="utf-8")
    (tmp_path / "ledger.json").write_text('{"episodes": []}', encoding="utf-8")
    code = main(["--policy", str(tmp_path / "policy.json"), "--ledger", str(tmp_path / "ledger.json")])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert "VERDICT: STANDARD" in captured.out


def test_corrupt_config_writes_nothing(tmp_path):
    (tmp_path / "a.json").write_text('{"max_profit": "0"}', encoding="utf-8")
    (tmp_path / "b.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        ParamStore(tmp_path).apply(
            {"a.json": {"max_profit": "2"}, "b.json": {"max_profit": "2"}}
        )
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {
        "max_profit": "0"
    }


def test_dry_run_still_validates_content(tmp_path):
    (tmp_path / "a.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        ParamStore(tmp_path).apply({"a.json": {"x": 1}}, dry_run=True)


def test_param_store_read(tmp_path):
    (tmp_path / "a.json").write_text('{"x": 1}', encoding="utf-8")
    assert ParamStore(tmp_path).read("a.json") == {"x": 1}


def test_format_report_no_floor_set_and_untagged_notes():
    policy = make_policy()
    decision = Governor(policy).decide(
        Ledger.from_dict({"episodes": [{"id": 1, "net": "-1"}]}), equity=Decimal("100")
    )
    text = format_report(decision, policy)
    assert "no floor set" in text
    assert "note:" in text


def test_cli_params_root_is_used_for_config_lookup(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "-1", "strategy": "c"}])
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "a.json").write_text(json.dumps({"keep": True, "max_profit": "0"}), encoding="utf-8")
    (tmp_path / "a.json").unlink()
    code = main(
        ["--policy", policy, "--ledger", ledger, "--equity", "100", "--params-root", str(cfg)]
    )
    assert code == 0
    data = json.loads((cfg / "a.json").read_text(encoding="utf-8"))
    assert data["max_profit"] == "1" and data["keep"] is True


def test_cli_recovery_json_output(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "-1", "strategy": "c"}])
    code = main(["--policy", policy, "--ledger", ledger, "--equity", "100", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["verdict"] == "RECOVERY"
    assert payload["strategy"] == "a"
    assert payload["overrides"]["max_profit"] == "1"
    assert payload["written"] == ["a.json"]


def test_cli_non_object_policy_exits_cleanly(tmp_path, capsys):
    (tmp_path / "policy.json").write_text("[1, 2]", encoding="utf-8")
    (tmp_path / "ledger.json").write_text("{}", encoding="utf-8")
    code = main(
        ["--policy", str(tmp_path / "policy.json"), "--ledger", str(tmp_path / "ledger.json")]
    )
    assert code == 1
    assert "cannot load policy" in capsys.readouterr().err


def test_cli_duplicate_strategy_ids_exit_cleanly(tmp_path, capsys):
    (tmp_path / "policy.json").write_text(
        '{"strategies": [{"id": "a"}, {"id": "a"}]}', encoding="utf-8"
    )
    (tmp_path / "ledger.json").write_text("{}", encoding="utf-8")
    code = main(
        ["--policy", str(tmp_path / "policy.json"), "--ledger", str(tmp_path / "ledger.json")]
    )
    assert code == 1
    assert "duplicate strategy ids" in capsys.readouterr().err


def test_cli_policy_without_strategies_exits_cleanly(tmp_path, capsys):
    (tmp_path / "policy.json").write_text('{"strategies": []}', encoding="utf-8")
    (tmp_path / "ledger.json").write_text("{}", encoding="utf-8")
    code = main(
        ["--policy", str(tmp_path / "policy.json"), "--ledger", str(tmp_path / "ledger.json")]
    )
    assert code == 1
    assert "no strategies" in capsys.readouterr().err


def test_cli_demo_needs_no_files(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = main(["demo"])
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT: STANDARD" in out
    assert out.count("VERDICT: RECOVERY") >= 2
    assert "VERDICT: HALT (3 consecutive losses)" in out
    assert "VERDICT: HALT (equity below floor)" in out
    assert "overrides used: 1" in out
    assert "set base_stake = 25" in out          # streak-2 halving is visible
    assert "riskgovernor init" in out            # points at the next step
    assert list(tmp_path.iterdir()) == []        # truly zero files written


def test_cli_init_scaffolds_a_working_setup(tmp_path, capsys):
    code = main(["init", str(tmp_path)])
    assert code == 0
    for name in ("policy.json", "ledger.json", "steady.json",
                 "defensive.json", "aggressive.json"):
        assert (tmp_path / name).exists(), name
    capsys.readouterr()

    code = main(["decide", "--policy", str(tmp_path / "policy.json"),
                 "--ledger", str(tmp_path / "ledger.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT: STANDARD" in out
    assert "[3] python my_runner.py 1 aggressive.json" in out


def test_cli_init_refuses_to_clobber_without_force(tmp_path, capsys):
    main(["init", str(tmp_path)])
    capsys.readouterr()
    code = main(["init", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("skipped") == 5
    assert "wrote" not in out

    code = main(["init", str(tmp_path), "--force"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("wrote") == 5


def test_cli_bare_flags_still_mean_decide(tmp_path, capsys):
    policy, ledger = setup(tmp_path, [{"id": 1, "net": "1", "strategy": "a"}])
    code = main(["--policy", policy, "--ledger", ledger, "--json"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "STANDARD"


def test_cli_no_arguments_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "demo" in out and "init" in out and "decide" in out