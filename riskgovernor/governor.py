"""The governor: a deterministic decision engine over (ledger, equity, policy).

Verdicts are evaluated in a fixed order and the first match wins:

1. ``HALT``     -- equity below the floor
2. ``HALT``     -- loss streak at or above the limit
3. ``HALT``     -- drawdown at or above the limit
4. ``RECOVERY`` -- the last episode lost, so rotate strategy and size to the loss
5. ``STANDARD`` -- otherwise, offer every strategy and let the operator choose

The governor never executes anything. It recommends, and it prints the exact
command for a human to approve. That separation is the point: the engine can be
audited and unit-tested without touching a live account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from .ledger import Ledger
from .policy import RiskPolicy, Strategy


class Verdict(str, Enum):
    """What the governor recommends doing next."""

    HALT = "HALT"
    RECOVERY = "RECOVERY"
    STANDARD = "STANDARD"


@dataclass
class Metrics:
    """A snapshot of everything the verdict depends on."""

    last_episode: int | None
    last_net: Decimal | None
    last_strategy: str | None
    streak: int
    drawdown: Decimal
    cumulative: Decimal
    peak: Decimal
    next_episode: int
    overrides: int

    @classmethod
    def from_ledger(cls, ledger: Ledger) -> "Metrics":
        last = ledger.last_numbered
        return cls(
            last_episode=last.number if last is not None else None,
            last_net=ledger.last_net,
            last_strategy=ledger.last_strategy,
            streak=ledger.loss_streak(),
            drawdown=ledger.drawdown(),
            cumulative=ledger.cumulative(),
            peak=ledger.peak(),
            next_episode=ledger.next_number(),
            overrides=ledger.override_count(),
        )


@dataclass
class Decision:
    """A verdict plus everything needed to act on it."""

    verdict: Verdict
    metrics: Metrics
    equity: Decimal | None = None
    strategy: str | None = None
    reason: str | None = None
    notes: list[str] = field(default_factory=list)
    overrides: dict[str, Any] = field(default_factory=dict)
    config_files: list[str] = field(default_factory=list)
    commands: dict[str, str] = field(default_factory=dict)

    @property
    def halted(self) -> bool:
        return self.verdict is Verdict.HALT

    @property
    def needs_operator_choice(self) -> bool:
        return self.verdict is Verdict.STANDARD and len(self.commands) > 1

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe view, used by the CLI's ``--json`` output."""
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "strategy": self.strategy,
            "notes": list(self.notes),
            "overrides": {
                k: (None if v is None else str(v)) for k, v in self.overrides.items()
            },
            "config_files": list(self.config_files),
            "commands": dict(self.commands),
            "metrics": {
                "last_episode": self.metrics.last_episode,
                "last_net": None if self.metrics.last_net is None else str(self.metrics.last_net),
                "last_strategy": self.metrics.last_strategy,
                "streak": self.metrics.streak,
                "drawdown": str(self.metrics.drawdown),
                "cumulative": str(self.metrics.cumulative),
                "peak": str(self.metrics.peak),
                "next_episode": self.metrics.next_episode,
                "overrides": self.metrics.overrides,
            },
            "equity": None if self.equity is None else str(self.equity),
        }


class Governor:
    """Turns a ledger and an optional equity into a :class:`Decision`."""

    def __init__(self, policy: RiskPolicy) -> None:
        self.policy = policy

    # -- gates -----------------------------------------------------------
    def _gate_halt(self, metrics: Metrics, equity: Decimal | None) -> tuple[bool, str | None]:
        """Return ``(halted, reason)`` for the ordered hard stops."""
        gates = self.policy.gates

        if equity is not None and gates.floor is not None and equity < gates.floor:
            return True, "equity below floor"

        if (
            gates.max_consecutive_losses is not None
            and metrics.streak >= gates.max_consecutive_losses
        ):
            return True, f"{metrics.streak} consecutive losses"

        if gates.max_drawdown is not None and metrics.drawdown >= gates.max_drawdown:
            return True, "give-back limit reached"

        return False, None

    # -- decision --------------------------------------------------------
    def decide(self, ledger: Ledger, equity: Decimal | None = None) -> Decision:
        """Evaluate the verdict table; the first matching rule wins."""
        policy = self.policy
        metrics = Metrics.from_ledger(ledger)

        halted, reason = self._gate_halt(metrics, equity)
        if halted:
            return Decision(
                verdict=Verdict.HALT,
                metrics=metrics,
                equity=equity,
                reason=reason,
            )

        if metrics.last_net is not None and metrics.last_net < 0:
            return self._recovery(metrics, equity)

        return self._standard(metrics, equity)

    def _recovery(self, metrics: Metrics, equity: Decimal | None) -> Decision:
        policy = self.policy
        strategy_id, known = policy.next_strategy(metrics.last_strategy)
        spec = policy.strategy(strategy_id)

        notes: list[str] = []
        if not known:
            notes.append(
                f"last strategy {metrics.last_strategy!r} not in rotation; "
                f"defaulted to {strategy_id!r}"
            )
        if not metrics.last_strategy:
            notes.append("ledger carries no strategy tag; rotation may not be honoured")
        if strategy_id == metrics.last_strategy:
            notes.append(
                "rotation re-selected the strategy that just lost "
                "(single-strategy policy); recovery is degenerate"
            )

        overrides: dict[str, Any] = {}
        if spec is not None and spec.recovery is not None:
            overrides = spec.recovery.build(loss=metrics.last_net, streak=metrics.streak)

        commands: dict[str, str] = {}
        if spec is not None:
            command = policy.command_for(
                spec,
                episode=metrics.next_episode,
                mode="recovery",
                streak=metrics.streak,
            )
            if command:
                commands[spec.id] = command

        return Decision(
            verdict=Verdict.RECOVERY,
            metrics=metrics,
            equity=equity,
            strategy=strategy_id,
            notes=notes,
            overrides=overrides,
            config_files=list(spec.config_files) if spec is not None else [],
            commands=commands,
        )

    def _standard(self, metrics: Metrics, equity: Decimal | None) -> Decision:
        commands: dict[str, str] = {}
        for spec in self.policy.strategies:
            command = self.policy.command_for(
                spec,
                episode=metrics.next_episode,
                mode="standard",
                streak=metrics.streak,
            )
            if command:
                commands[spec.id] = command
        return Decision(
            verdict=Verdict.STANDARD,
            metrics=metrics,
            equity=equity,
            commands=commands,
        )

    # -- helpers ---------------------------------------------------------
    def recovery_overrides(
        self, decision: Decision, ledger: Ledger
    ) -> dict[str, dict[str, Any]]:
        """Map ``{config_file: {param: value}}`` for a RECOVERY decision.

        Empty for any other verdict, so a caller can pass every decision
        through the same write path.
        """
        if decision.verdict is not Verdict.RECOVERY or not decision.overrides:
            return {}
        return {name: dict(decision.overrides) for name in decision.config_files}

    def override(self, ledger: Ledger, reason: str, *, operator: str | None = None) -> None:
        """Record an operator bypass of a HALT, in the ledger, visibly."""
        ledger.record_override(reason, operator=operator)