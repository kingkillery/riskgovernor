"""Command-line entry point.

    python -m riskgovernor --policy policy.json --ledger ledger.json --equity 0.000154

Prints a state block and a verdict. On a RECOVERY verdict it writes the
resolved parameter overrides to the strategy's config files (unless
``--dry-run``) and then prints the command for an operator to approve.

The CLI never launches a strategy. Recommendation and execution are separate
on purpose.

Units: every numeric in the policy (gates, caps, recovery params) and every
``--equity`` value is expressed in *ledger units* -- the same units as the
ledger's ``net`` values. ``policy.scale`` and ``policy.unit`` affect display
only and never participate in a comparison.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from typing import Any

from .governor import Decision, Governor, Verdict
from .ledger import Ledger, to_decimal
from .params import MissingConfigError, ParamStore
from .policy import RiskPolicy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="riskgovernor",
        description="Decide the next governed action from a ledger and a policy.",
    )
    parser.add_argument("--policy", required=True, help="policy JSON path")
    parser.add_argument("--ledger", required=True, help="ledger JSON path")
    parser.add_argument(
        "--equity",
        default=None,
        metavar="N",
        help=(
            "current equity in LEDGER units (the same units as net values), "
            "not display units; gates needing it are skipped when omitted"
        ),
    )
    parser.add_argument(
        "--params-root",
        default=None,
        help="directory holding strategy config files (default: ledger's directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print everything, write no config files",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="emit JSON instead of text"
    )
    return parser


def _fmt(value: Decimal | None, scale: Decimal, unit: str) -> str:
    if value is None:
        return "unavailable"
    text = f"{value * scale:.2f}"
    return f"{text} {unit}".strip()


def format_report(decision: Decision, policy: RiskPolicy) -> str:
    """Human-readable state block plus verdict."""
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        policy = RiskPolicy.from_path(args.policy)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"error: cannot load policy {args.policy!r}: {exc}", file=sys.stderr)
        return 1
    if not policy.strategies:
        print("error: policy declares no strategies", file=sys.stderr)
        return 1

    ledger = Ledger.from_path(args.ledger)
    if not ledger:
        print(f"warning: ledger {args.ledger!r} is empty or unreadable", file=sys.stderr)

    equity = None
    if args.equity is not None:
        equity = to_decimal(args.equity)
        if equity is None:
            print(f"error: --equity {args.equity!r} is not numeric", file=sys.stderr)
            return 1

    governor = Governor(policy)
    decision = governor.decide(ledger, equity=equity)

    written: list[str] = []
    if decision.verdict is Verdict.RECOVERY and decision.overrides:
        root = args.params_root or str(ledger_path_parent(args.ledger))
        store = ParamStore(root, indent=policy.indent)
        try:
            written = store.apply(
                governor.recovery_overrides(decision, ledger),
                dry_run=args.dry_run,
            )
        except MissingConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.as_json:
        payload: dict[str, Any] = decision.to_dict()
        payload["written"] = written
        payload["dry_run"] = bool(args.dry_run)
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(decision, policy))
        if decision.verdict is Verdict.RECOVERY and decision.overrides:
            if args.dry_run:
                print("  (dry-run: no files written)")
            for name in written:
                print(f"  wrote {name} (recovery spec)")

    return 0


def ledger_path_parent(ledger_path: str):
    from pathlib import Path

    return Path(ledger_path).parent


if __name__ == "__main__":
    raise SystemExit(main())