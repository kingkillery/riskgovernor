import pytest

from decimal import Decimal

from riskgovernor.policy import Gates, RecoverySpec, RiskPolicy, Strategy


def _recovery() -> RecoverySpec:
    return RecoverySpec(
        params={"max_loss": "1"},
        size_param="max_profit",
        cap=Decimal("2"),
        stake_param="base_stake",
        stake_base="50",
        stake_halved="25",
    )


def make_policy(**gate_kwargs) -> RiskPolicy:
    return RiskPolicy(
        strategies=[
            Strategy(
                id="a",
                config_files=["a.json"],
                command="run {episode} {config} {note_arg}",
                recovery=_recovery(),
            ),
            Strategy(
                id="b",
                config_files=["b.json"],
                command="run {episode} b",
                recovery=_recovery(),
            ),
            Strategy(
                id="c",
                config_files=["c.json"],
                command="run {episode} c",
                recovery=_recovery(),
            ),
        ],
        gates=Gates(**gate_kwargs),
    )


def test_rotation_wraps_in_declared_order():
    policy = make_policy()
    assert policy.next_strategy("a") == ("b", True)
    assert policy.next_strategy("b") == ("c", True)
    assert policy.next_strategy("c") == ("a", True)


def test_rotation_reports_unknown_predecessor():
    policy = make_policy()
    assert policy.next_strategy("zzz") == ("a", False)
    assert policy.next_strategy(None) == ("a", False)


def test_recovery_sizing_caps_the_target():
    spec = RecoverySpec(size_param="max_profit", cap=Decimal("2"))
    assert spec.build(loss=Decimal("-5"), streak=0)["max_profit"] == "2"


def test_recovery_sizing_uses_loss_below_cap():
    spec = RecoverySpec(size_param="max_profit", cap=Decimal("2"))
    assert Decimal(spec.build(loss=Decimal("-1.5"), streak=0)["max_profit"]) == Decimal("1.5")


def test_recovery_sizing_without_cap_uses_raw_loss():
    spec = RecoverySpec(size_param="max_profit")
    assert Decimal(spec.build(loss=Decimal("-3.25"), streak=0)["max_profit"]) == Decimal("3.25")


def test_recovery_halves_stake_once_streak_reaches_threshold():
    spec = RecoverySpec(
        stake_param="base_stake", stake_base="50", stake_halved="25", halve_at_streak=2
    )
    assert spec.build(loss=Decimal("-1"), streak=1)["base_stake"] == "50"
    assert spec.build(loss=Decimal("-1"), streak=2)["base_stake"] == "25"
    assert spec.build(loss=Decimal("-1"), streak=5)["base_stake"] == "25"


def test_recovery_static_params_always_applied():
    spec = RecoverySpec(params={"max_loss": "1", "max_rounds": 15})
    out = spec.build(loss=Decimal("-1"), streak=0)
    assert out["max_loss"] == "1" and out["max_rounds"] == 15


def test_policy_json_round_trip(tmp_path):
    policy = make_policy(floor=Decimal("75"), max_consecutive_losses=3)
    other = RiskPolicy.from_path(policy.save(tmp_path / "p.json"))
    assert other.ids == ["a", "b", "c"]
    assert other.gates.floor == Decimal("75")
    assert other.strategy("a").recovery.cap == Decimal("2")
    assert other.strategy("a").recovery.stake_halved == "25"


def test_command_rendering_and_none_when_untemplated():
    policy = make_policy()
    command = policy.command_for(policy.strategy("a"), episode=9, mode="recovery", streak=1)
    assert command == 'run 9 a.json --note "a recovery streak=1"'

    policy.strategies[1].command = None
    assert policy.command_for(policy.strategy("b"), episode=9, mode="standard", streak=0) is None


def test_gates_round_trip():
    gates = Gates.from_dict({"floor": "5000", "max_consecutive_losses": 3, "max_drawdown": "2000"})
    assert gates.floor == Decimal("5000")
    assert gates.max_consecutive_losses == 3
    assert gates.to_dict()["max_drawdown"] == "2000"
    assert Gates.from_dict({}).floor is None
    assert Gates.from_dict(None).max_consecutive_losses is None


def test_duplicate_strategy_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate strategy ids"):
        RiskPolicy.from_dict({"strategies": [{"id": "a"}, {"id": "b"}, {"id": "a"}]})


def test_non_object_policy_is_rejected():
    with pytest.raises(ValueError, match="must be a JSON object"):
        RiskPolicy.from_dict([{"id": "a"}])