from decimal import Decimal

from riskgovernor.ledger import Episode, Ledger, to_decimal


def test_to_decimal_rejects_bool_and_garbage():
    assert to_decimal(True) is None
    assert to_decimal(None) is None
    assert to_decimal("nope") is None
    assert to_decimal(3) == Decimal(3)
    assert to_decimal("1.5") == Decimal("1.5")


def test_episode_reads_alternate_keys():
    ep = Episode.from_dict(
        {"n": 4, "net": "-1", "family": "glacier", "note": "x", "rounds": 40}
    )
    assert ep.number == 4
    assert ep.net == Decimal("-1")
    assert ep.strategy == "glacier"
    assert ep.meta == {"rounds": 40}


def test_episode_round_trip_preserves_unknown_keys():
    raw = {"n": 4, "net": "-0.5", "family": "glacier", "rounds": 40, "note": "x"}
    out = Episode.from_dict(raw).to_dict()
    assert out["rounds"] == 40
    assert out["net"] == "-0.5"


def test_ledger_remembers_rows_key_and_extra_meta():
    led = Ledger.from_dict({"goal": "x", "rounds": [{"n": 1, "net": "1"}]})
    assert led.rows_key == "rounds"
    rebuilt = led.to_dict()
    assert rebuilt["goal"] == "x"
    assert rebuilt["rounds"][0]["id"] == 1


def test_ledger_from_dict_accepts_bare_list():
    led = Ledger.from_dict([{"id": 1, "net": "2"}])
    assert len(led) == 1 and led.cumulative() == Decimal(2)


def test_ledger_from_path_tolerates_missing_and_corrupt(tmp_path):
    assert not Ledger.from_path(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert not Ledger.from_path(bad)


def test_metrics():
    led = Ledger.from_dict(
        {"episodes": [{"id": 1, "net": "5"}, {"id": 2, "net": "-1"}, {"id": 3, "net": "-2"}]}
    )
    assert led.cumulative() == Decimal(2)
    assert led.peak() == Decimal(5)
    assert led.drawdown() == Decimal(3)
    assert led.loss_streak() == 2
    assert led.next_number() == 4


def test_unparseable_net_breaks_streak():
    led = Ledger.from_dict(
        {"episodes": [{"id": 1, "net": "-1"}, {"id": 2, "net": None}, {"id": 3, "net": "-1"}]}
    )
    assert led.loss_streak() == 1


def test_override_row_breaks_streak_and_is_auditable():
    led = Ledger.from_dict(
        {"episodes": [{"id": i, "net": "-1"} for i in (1, 2, 3)]}
    )
    assert led.loss_streak() == 3
    led.record_override("operator reset", operator="alice")
    assert led.loss_streak() == 0
    assert led.override_count() == 1
    assert led.overrides()[0].meta["operator"] == "alice"
    assert led.overrides()[0].is_override


def test_last_numbered_skips_bookkeeping_rows():
    led = Ledger.from_dict(
        {"episodes": [{"id": 7, "net": "-1", "strategy": "a"}, {"id": "RESET", "net": "0"}]}
    )
    assert led.last_numbered.number == 7
    assert led.last_strategy == "a"
    assert led.next_number() == 8


def test_save_round_trips(tmp_path):
    led = Ledger.from_dict({"episodes": [{"id": 1, "net": "-2", "strategy": "a"}]})
    path = led.save(tmp_path / "led.json")
    again = Ledger.from_path(path)
    assert again.last_net == Decimal(-2)
    assert again.last_strategy == "a"


def test_to_decimal_rejects_non_finite():
    assert to_decimal("nan") is None
    assert to_decimal("NaN") is None
    assert to_decimal("inf") is None
    assert to_decimal("-Infinity") is None
    assert to_decimal(Decimal("NaN")) is None
    assert to_decimal("1.5") is not None


def test_nan_net_breaks_streak_instead_of_crashing():
    led = Ledger.from_dict(
        {"episodes": [
            {"id": 1, "net": "-1"},
            {"id": 2, "net": "nan"},
            {"id": 3, "net": "-1"},
        ]}
    )
    assert led.loss_streak() == 1
    assert led.drawdown() == Decimal(2)


def test_ledger_iteration_and_indexing():
    led = Ledger.from_dict({"episodes": [{"id": 1, "net": "1"}, {"id": 2, "net": "-1"}]})
    assert [e.number for e in led] == [1, 2]
    assert not led[0].is_loss and led[1].is_loss