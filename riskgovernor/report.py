"""Human-readable rendering of a :class:`~riskgovernor.governor.Decision`."""

from __future__ import annotations

from decimal import Decimal

from .governor import Decision, Verdict
from .policy import RiskPolicy


def _fmt(value: Decimal | None, scale: Decimal, unit: str) -> str:
    if value is None:
        return "unavailable"
    text = f"{value * scale:.2f}"
    return f"{text} {unit}".strip()


def format_report(decision: Decision, policy: RiskPolicy) -> str:
    """The state block plus verdict, as printed by the CLI."""
    m = decision.metrics
    scale = policy.scale
    unit = policy.unit

    lines = ["--- RISK GOVERNOR ---"]
    lines.append(f"last episode:   {m.last_episode if m.last_episode is not None else 'n/a'}")
    lines.append(f"last net:       {_fmt(m.last_net, scale, unit)}")
    lines.append(f"last strategy:  {m.last_strategy or 'untagged'}")
    lines.append(f"streak:         {m.streak}")
    lines.append(f"drawdown:       {_fmt(m.drawdown, scale, unit)}")
    lines.append(f"cumulative:     {_fmt(m.cumulative, scale, unit)}")
    lines.append(f"peak:           {_fmt(m.peak, scale, unit)}")

    if decision.equity is None:
        lines.append(f"equity:         unavailable ({unit or 'no unit'})")
        lines.append("floor headroom: unknown")
    else:
        lines.append(f"equity:         {_fmt(decision.equity, scale, unit)}")
        floor = policy.gates.floor
        if floor is None:
            lines.append("floor headroom: no floor set")
        else:
            lines.append(f"floor headroom: {_fmt(decision.equity - floor, scale, unit)}")

    lines.append(f"overrides used: {m.overrides}")

    for note in decision.notes:
        lines.append(f"note:           {note}")

    lines.append("")
    if decision.verdict is Verdict.HALT:
        lines.append(f"VERDICT: HALT ({decision.reason})")
    elif decision.verdict is Verdict.RECOVERY:
        lines.append(f"VERDICT: RECOVERY {decision.strategy}")
        for key, value in decision.overrides.items():
            lines.append(f"  set {key} = {value}")
        for strategy_id, command in decision.commands.items():
            lines.append(f"  {command}")
    else:
        lines.append("VERDICT: STANDARD")
        for index, (strategy_id, command) in enumerate(decision.commands.items(), 1):
            lines.append(f"  [{index}] {command}")

    return "\n".join(lines)
