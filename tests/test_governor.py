from decimal import Decimal

from riskgovernor.governor import Governor, Metrics, Verdict
from riskgovernor.ledger import Ledger
from riskgovernor.policy import Gates, RecoverySpec, RiskPolicy, Strategy

from tests.test_policy import make_policy

def ledger(*rows) -> Ledger:
    return Ledger.from_dict({"episodes": list(rows)})


def test_standard_offers_every_strategy():
    decision = Governor(make_policy()).decide(
        ledger({"id": 1, "net": "1", "strategy": "a"})
    )
    assert decision.verdict is Verdict.STANDARD
    assert set(decision.commands) == {"a", "b", "c"}
    assert decision.strategy is None
    assert decision.metrics.next_episode == 2
    assert not decision.halted


def test_standard_with_empty_ledger_is_episode_one():
    decision = Governor(make_policy()).decide(Ledger())
    assert decision.verdict is Verdict.STANDARD
    assert decision.metrics.next_episode == 1
    assert decision.metrics.last_episode is None


def test_recovery_rotates_away_from_the_losing_strategy():
    decision = Governor(make_policy()).decide(
        ledger({"id": 1, "net": "-1", "strategy": "a"})
    )
    assert decision.verdict is Verdict.RECOVERY
    assert decision.strategy == "b"
    assert decision.config_files == ["b.json"]


def test_recovery_sizes_target_to_the_loss():
    decision = Governor(make_policy()).decide(
        ledger({"id": 1, "net": "-1.5", "strategy": "a"})
    )
    assert Decimal(decision.overrides["max_profit"]) == Decimal("1.5")


def test_recovery_caps_target_at_the_cap():
    decision = Governor(make_policy()).decide(
        ledger({"id": 1, "net": "-" + "9" * 6, "strategy": "c"})
    )
    assert decision.verdict is Verdict.RECOVERY
    assert decision.strategy == "a"
    assert decision.overrides["max_profit"] == "2"


def test_recovery_halves_stake_at_streak_two():
    decision = Governor(make_policy()).decide(
        ledger(
            {"id": 1, "net": "-1", "strategy": "a"},
            {"id": 2, "net": "-1", "strategy": "b"},
        )
    )
    assert decision.strategy == "c"
    assert decision.overrides["base_stake"] == "25"


def test_untagged_ledger_is_flagged_not_silently_guessed():
    decision = Governor(make_policy()).decide(ledger({"id": 1, "net": "-1"}))
    assert decision.strategy == "a"
    assert any("not in rotation" in n for n in decision.notes)
    assert any("no strategy tag" in n for n in decision.notes)


def test_halt_on_floor():
    decision = Governor(make_policy(floor=Decimal("75"))).decide(
        ledger({"id": 1, "net": "1"}), equity=Decimal("70")
    )
    assert decision.verdict is Verdict.HALT
    assert decision.reason == "equity below floor"


def test_floor_gate_is_skipped_without_equity():
    decision = Governor(make_policy(floor=Decimal("75"))).decide(
        ledger({"id": 1, "net": "1"})
    )
    assert decision.verdict is Verdict.STANDARD


def test_halt_on_loss_streak():
    rows = [{"id": i, "net": "-1", "strategy": "a"} for i in (1, 2, 3)]
    decision = Governor(make_policy(max_consecutive_losses=3)).decide(ledger(*rows))
    assert decision.verdict is Verdict.HALT
    assert decision.reason == "3 consecutive losses"


def test_halt_on_drawdown():
    decision = Governor(make_policy(max_drawdown=Decimal("5"))).decide(
        ledger({"id": 1, "net": "10"}, {"id": 2, "net": "-9"})
    )
    assert decision.verdict is Verdict.HALT
    assert decision.reason == "give-back limit reached"


def test_floor_gate_takes_precedence_over_streak():
    rows = [{"id": i, "net": "-1", "strategy": "a"} for i in (1, 2, 3)]
    decision = Governor(
        make_policy(floor=Decimal("75"), max_consecutive_losses=3)
    ).decide(ledger(*rows), equity=Decimal("70"))
    assert decision.reason == "equity below floor"


def test_override_clears_the_streak_halt_and_is_counted():
    rows = [{"id": i, "net": "-1", "strategy": "a"} for i in (1, 2, 3)]
    book = ledger(*rows)
    governor = Governor(make_policy(max_consecutive_losses=3))
    assert governor.decide(book).halted

    governor.override(book, "operator reset", operator="alice")

    assert not governor.decide(book).halted
    assert governor.decide(book).metrics.overrides == 1


def test_recovery_overrides_map_to_every_config_file():
    governor = Governor(make_policy())
    decision = governor.decide(ledger({"id": 1, "net": "-1", "strategy": "a"}))
    assert governor.recovery_overrides(decision, Ledger()) == {
        "b.json": {"max_loss": "1", "max_profit": "1", "base_stake": "50"}
    }


def test_recovery_overrides_empty_for_non_recovery():
    governor = Governor(make_policy())
    decision = governor.decide(ledger({"id": 1, "net": "1", "strategy": "a"}))
    assert governor.recovery_overrides(decision, Ledger()) == {}


def test_metrics_snapshot_matches_ledger():
    book = ledger({"id": 1, "net": "5", "strategy": "a"}, {"id": 2, "net": "-2", "strategy": "b"})
    metrics = Metrics.from_ledger(book)
    assert metrics.last_episode == 2
    assert metrics.last_strategy == "b"
    assert metrics.peak == Decimal(5)
    assert metrics.drawdown == Decimal(2)
    assert metrics.cumulative == Decimal(3)
    assert metrics.next_episode == 3


def test_decision_serialises_to_json_safe_dict():
    decision = Governor(make_policy()).decide(
        ledger({"id": 1, "net": "-1", "strategy": "a"})
    )
    payload = decision.to_dict()
    assert payload["verdict"] == "RECOVERY"
    assert payload["overrides"]["max_profit"] == "1"
    assert payload["metrics"]["next_episode"] == 2


def test_single_strategy_recovery_is_flagged_as_degenerate():
    policy = RiskPolicy(
        strategies=[
            Strategy(
                id="only",
                config_files=["o.json"],
                command="run {episode} {config}",
                recovery=RecoverySpec(size_param="max_profit", cap=Decimal("2")),
            )
        ],
    )
    decision = Governor(policy).decide(ledger({"id": 1, "net": "-1", "strategy": "only"}))
    assert decision.verdict is Verdict.RECOVERY
    assert decision.strategy == "only"
    assert any("degenerate" in n for n in decision.notes)


def test_needs_operator_choice_only_for_multi_option_standard():
    governor = Governor(make_policy())
    standard = governor.decide(ledger({"id": 1, "net": "1", "strategy": "a"}))
    assert standard.needs_operator_choice

    halted = Governor(make_policy(max_consecutive_losses=1)).decide(
        ledger({"id": 1, "net": "-1"})
    )
    assert not halted.needs_operator_choice

    single = Governor(
        RiskPolicy(strategies=[Strategy(id="only", command="run {episode}")])
    ).decide(ledger({"id": 1, "net": "1", "strategy": "only"}))
    assert single.verdict is Verdict.STANDARD
    assert not single.needs_operator_choice