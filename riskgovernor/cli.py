"""Command-line entry point.

Three subcommands:

    riskgovernor demo                       zero-config guided tour
    riskgovernor init [DIR]                 scaffold a working setup
    riskgovernor decide --policy ... --ledger ...

``decide`` prints a state block and a verdict. On a RECOVERY verdict it writes
the resolved parameter overrides to the strategy's config files (unless
``--dry-run``) and then prints the command for an operator to approve.

Bare flags are treated as ``decide`` arguments, so
``riskgovernor --policy p.json --ledger l.json`` keeps working.

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
from pathlib import Path
from typing import Any

from . import quickstart
from .governor import Governor, Verdict
from .ledger import Ledger, to_decimal
from .params import MissingConfigError, ParamStore
from .policy import RiskPolicy
from .report import format_report

SUBCOMMANDS = ("demo", "init", "decide")


def _normalise(argv: list[str]) -> list[str]:
    """Prepend ``decide`` when the first argument is a bare flag."""
    if not argv or argv[0] in ("-h", "--help") or argv[0] in SUBCOMMANDS:
        return argv
    if argv[0].startswith("-"):
        return ["decide", *argv]
    return argv


def _add_decide_args(parser: argparse.ArgumentParser) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="riskgovernor",
        description="Decide the next governed action from a ledger and a policy.",
        epilog=(
            "Try `riskgovernor demo` for a zero-config tour, or "
            "`riskgovernor init` to scaffold a working setup."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    demo = sub.add_parser("demo", help="guided tour: no files, no setup")
    demo.set_defaults(func=run_demo_command)

    init = sub.add_parser("init", help="scaffold policy.json, ledger.json and configs")
    init.add_argument("dir", nargs="?", default=".", help="target directory (default: .)")
    init.add_argument("--force", action="store_true", help="overwrite existing files")
    init.set_defaults(func=run_init_command)

    decide = sub.add_parser("decide", help="print the verdict for a ledger")
    _add_decide_args(decide)
    decide.set_defaults(func=run_decide_command)

    return parser


def run_demo_command(args: argparse.Namespace) -> int:
    return quickstart.run_demo()


def run_init_command(args: argparse.Namespace) -> int:
    created, skipped = quickstart.write_scaffold(args.dir, force=args.force)
    for name in created:
        print(f"wrote {name}")
    for name in skipped:
        print(f"skipped {name} (already exists; use --force to overwrite)")
    print()
    print("Next:")
    prefix = "" if args.dir == "." else f"{args.dir}/"
    print(f"  riskgovernor decide --policy {prefix}policy.json --ledger {prefix}ledger.json")
    return 0


def run_decide_command(args: argparse.Namespace) -> int:
    try:
        policy = RiskPolicy.from_path(args.policy)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"error: cannot load policy {args.policy!r}: {exc}", file=sys.stderr)
        return 1
    if not policy.strategies:
        print("error: policy declares no strategies", file=sys.stderr)
        return 1

    ledger_path = Path(args.ledger)
    if ledger_path.exists():
        try:
            ledger = Ledger.from_dict(json.loads(ledger_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            print(f"error: ledger {args.ledger!r} is not valid JSON: {exc}", file=sys.stderr)
            return 1
    else:
        # A missing ledger is a first-class state (fresh session), not an
        # error; a corrupt one is refused rather than silently treated as
        # empty, because every metric would reset.
        ledger = Ledger()
        print(f"warning: ledger {args.ledger!r} not found; treating as empty", file=sys.stderr)

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
        root = args.params_root or str(Path(args.ledger).parent)
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    parser = build_parser()
    args = parser.parse_args(_normalise(argv))
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())