"""Zero-config onboarding: ``riskgovernor demo`` and ``riskgovernor init``.

The fastest way to understand the governor is to watch it decide, so ``demo``
builds a policy and a series of ledgers in memory and prints every verdict in
order, narrated. Nothing touches disk.

``init`` scaffolds the same kind of files on disk — a policy, an empty ledger
and config stubs — so a new user's second command just works.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .governor import Governor
from .ledger import Ledger, to_decimal
from .policy import RiskPolicy
from .report import format_report

DEMO_POLICY: dict[str, Any] = {
    "unit": "USD",
    "scale": "1",
    "note_template": "E{episode} {strategy} {mode} streak={streak}",
    "gates": {"floor": "5000", "max_consecutive_losses": 3, "max_drawdown": "2000"},
    "strategies": [
        {
            "id": "steady",
            "config_files": ["steady.json"],
            "command": "python my_runner.py {episode} {config} {note_arg}",
            "recovery": {
                "params": {"max_loss": "100", "max_rounds": 15},
                "size_param": "max_profit",
                "cap": "200",
                "stake_param": "base_stake",
                "stake_base": "50",
                "stake_halved": "25",
                "halve_at_streak": 2,
            },
        },
        {
            "id": "defensive",
            "config_files": ["defensive.json"],
            "command": "python my_runner.py {episode} {config} {note_arg}",
            "recovery": {
                "params": {"max_loss": "100", "max_rounds": 40},
                "size_param": "max_profit",
                "cap": "200",
                "stake_param": "base_stake",
                "stake_base": "50",
                "stake_halved": "25",
                "halve_at_streak": 2,
            },
        },
        {
            "id": "aggressive",
            "config_files": ["aggressive.json"],
            "command": "python my_runner.py {episode} {config} {note_arg}",
            "recovery": {
                "params": {"max_loss": "100", "max_rounds": 15},
                "size_param": "max_profit",
                "cap": "200",
                "stake_param": "base_stake",
                "stake_base": "50",
                "stake_halved": "25",
                "halve_at_streak": 2,
            },
        },
    ],
}

# (narration, episodes, equity or None, override_after_ledger)
SCENARIOS: list[tuple[str, list[dict[str, Any]], str | None, bool]] = [
    (
        "1. A fresh session. Nothing has happened, so every strategy is on the\n"
        "   table and the choice is yours:",
        [],
        None,
        False,
    ),
    (
        "2. Episode 1 ran 'steady' and lost 120. The governor rotates AWAY from\n"
        "   the loser, halves nothing yet, and sizes the recovery to the loss\n"
        "   (min(120, cap=200) = 120):",
        [{"id": 1, "net": "-120", "strategy": "steady"}],
        None,
        False,
    ),
    (
        "3. Episode 2 ran 'defensive' and lost 80. Two losses in a row: rotation\n"
        "   moves on AND the stake is halved for the recovery (25, not 50):",
        [
            {"id": 1, "net": "-120", "strategy": "steady"},
            {"id": 2, "net": "-80", "strategy": "defensive"},
        ],
        None,
        False,
    ),
    (
        "4. A third consecutive loss trips the streak gate. Hard stop:",
        [
            {"id": 1, "net": "-120", "strategy": "steady"},
            {"id": 2, "net": "-80", "strategy": "defensive"},
            {"id": 3, "net": "-100", "strategy": "aggressive"},
        ],
        None,
        False,
    ),
    (
        "5. Separately, equity below the floor halts everything, whatever the\n"
        "   ledger says. Gate 1 always wins:",
        [{"id": 1, "net": "50", "strategy": "steady"}],
        "4900",
        False,
    ),
    (
        "6. After a halt an operator may override - recorded, never silent.\n"
        "   The streak clears, but the last episode still lost, so the next\n"
        "   move is a recovery - and the override count is on the record:",
        [
            {"id": 1, "net": "-120", "strategy": "steady"},
            {"id": 2, "net": "-80", "strategy": "defensive"},
            {"id": 3, "net": "-100", "strategy": "aggressive"},
        ],
        None,
        True,
    ),
]


def run_demo() -> int:
    """Print every verdict in order. No files are read or written."""
    policy = RiskPolicy.from_dict(DEMO_POLICY)
    governor = Governor(policy)

    print("riskgovernor demo - every verdict, in order. Nothing touches disk.")
    print()
    for caption, episodes, equity, override in SCENARIOS:
        ledger = Ledger.from_dict({"episodes": episodes})
        if override:
            ledger.record_override("operator resumed after review")
        decision = governor.decide(ledger, equity=to_decimal(equity))
        print(caption)
        print()
        print(format_report(decision, policy))
        print()

    print("That's the whole model: gates halt, losses rotate, recovery is sized")
    print("to the loss, and overrides are on the record.")
    print()
    print("Next: `riskgovernor init` writes a working setup to disk, then")
    print("`riskgovernor decide --policy policy.json --ledger ledger.json`.")
    return 0


SCAFFOLD_CONFIGS: dict[str, dict[str, Any]] = {
    "steady.json": {"base_stake": "50", "max_loss": "100", "max_profit": "0", "max_rounds": 15},
    "defensive.json": {"base_stake": "50", "max_loss": "100", "max_profit": "0", "max_rounds": 40},
    "aggressive.json": {"base_stake": "50", "max_loss": "100", "max_profit": "0", "max_rounds": 15},
}

SCAFFOLD_LEDGER: dict[str, Any] = {"episodes": []}


def write_scaffold(
    target: str | Path, *, force: bool = False
) -> tuple[list[str], list[str]]:
    """Write policy, ledger and config stubs into ``target``.

    Existing files are skipped unless ``force``. Returns ``(created, skipped)``.
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)

    payloads: dict[str, Any] = {
        "policy.json": DEMO_POLICY,
        "ledger.json": SCAFFOLD_LEDGER,
        **SCAFFOLD_CONFIGS,
    }
    created: list[str] = []
    skipped: list[str] = []
    for name, payload in payloads.items():
        path = target / name
        if path.exists() and not force:
            skipped.append(name)
            continue
        path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        created.append(name)
    return created, skipped