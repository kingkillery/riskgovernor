"""Declarative risk policy: gates, strategy rotation, recovery sizing, commands.

A policy is plain data. It can be built in Python or loaded from JSON, which
means a governed strategy can be reviewed, diffed and version-controlled
independently of the code that acts on it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .ledger import to_decimal


@dataclass
class Gates:
    """Hard stops, evaluated in a fixed order before any recommendation.

    ``None`` disables an individual gate. ``equity``-dependent gates are
    skipped when no equity is supplied, so a governor can still be used
    offline (backtests, audits) without a live balance.
    """

    floor: Decimal | None = None
    max_consecutive_losses: int | None = None
    max_drawdown: Decimal | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "Gates":
        raw = raw or {}
        streak = raw.get("max_consecutive_losses")
        return cls(
            floor=to_decimal(raw.get("floor")),
            max_consecutive_losses=None if streak is None else int(streak),
            max_drawdown=to_decimal(raw.get("max_drawdown")),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.floor is not None:
            out["floor"] = str(self.floor)
        if self.max_consecutive_losses is not None:
            out["max_consecutive_losses"] = self.max_consecutive_losses
        if self.max_drawdown is not None:
            out["max_drawdown"] = str(self.max_drawdown)
        return out


@dataclass
class RecoverySpec:
    """Parameter overrides applied to a strategy for a recovery episode.

    * ``size_param`` is set to ``min(|loss|, cap)`` so the recovery target is
      sized to the loss that triggered it, instead of being a fixed constant.
    * ``stake_param`` is set to ``stake_base``, or ``stake_halved`` once the
      streak reaches ``halve_at_streak`` (de-risk as losses accumulate).
    * ``params`` holds static overrides applied verbatim.
    """

    params: dict[str, Any] = field(default_factory=dict)
    size_param: str | None = None
    cap: Decimal | None = None
    stake_param: str | None = None
    stake_base: Any = None
    stake_halved: Any = None
    halve_at_streak: int = 2

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "RecoverySpec | None":
        if not raw:
            return None
        return cls(
            params=dict(raw.get("params") or {}),
            size_param=raw.get("size_param"),
            cap=to_decimal(raw.get("cap")),
            stake_param=raw.get("stake_param"),
            stake_base=raw.get("stake_base"),
            stake_halved=raw.get("stake_halved"),
            halve_at_streak=int(raw.get("halve_at_streak", 2)),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"params": dict(self.params)}
        if self.size_param is not None:
            out["size_param"] = self.size_param
        if self.cap is not None:
            out["cap"] = str(self.cap)
        if self.stake_param is not None:
            out["stake_param"] = self.stake_param
            out["stake_base"] = self.stake_base
            out["stake_halved"] = self.stake_halved
            out["halve_at_streak"] = self.halve_at_streak
        return out

    def build(self, *, loss: Decimal, streak: int) -> dict[str, Any]:
        """Resolve the concrete parameter overrides for one recovery episode."""
        out = dict(self.params)
        if self.size_param:
            amount = abs(loss)
            if self.cap is not None:
                amount = min(amount, self.cap)
            # str() keeps the original precision of whichever operand won.
            out[self.size_param] = str(amount)
        if self.stake_param and self.stake_base is not None:
            halve = self.stake_halved is not None and streak >= self.halve_at_streak
            out[self.stake_param] = self.stake_halved if halve else self.stake_base
        return out


@dataclass
class Strategy:
    """One member of the rotation.

    ``config_files`` are the parameter files this strategy drives; recovery
    overrides are written to all of them. ``command`` is a template describing
    how an operator should launch it -- the governor prints commands, it never
    runs them.
    """

    id: str
    config_files: list[str] = field(default_factory=list)
    recovery: RecoverySpec | None = None
    command: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Strategy":
        return cls(
            id=str(raw["id"]),
            config_files=[str(f) for f in (raw.get("config_files") or [])],
            recovery=RecoverySpec.from_dict(raw.get("recovery")),
            command=raw.get("command"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id}
        if self.config_files:
            out["config_files"] = list(self.config_files)
        if self.recovery is not None:
            out["recovery"] = self.recovery.to_dict()
        if self.command is not None:
            out["command"] = self.command
        return out


@dataclass
class RiskPolicy:
    """Ordered strategies plus the gates that can halt them."""

    strategies: list[Strategy]
    gates: Gates = field(default_factory=Gates)
    note_template: str = "{strategy} {mode} streak={streak}"
    unit: str = ""
    scale: Decimal = Decimal(1)
    indent: int = 1

    # -- construction ----------------------------------------------------
    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RiskPolicy":
        if not isinstance(raw, dict):
            raise ValueError("policy must be a JSON object")
        strategies = [Strategy.from_dict(s) for s in (raw.get("strategies") or [])]
        ids = [s.id for s in strategies]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate strategy ids: {sorted(ids)}")
        return cls(
            strategies=strategies,
            gates=Gates.from_dict(raw.get("gates")),
            note_template=raw.get("note_template") or cls.note_template,
            unit=raw.get("unit", "") or "",
            scale=to_decimal(raw.get("scale")) or Decimal(1),
            indent=int(raw.get("indent", 1)),
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "RiskPolicy":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategies": [s.to_dict() for s in self.strategies],
            "gates": self.gates.to_dict(),
            "note_template": self.note_template,
            "unit": self.unit,
            "scale": str(self.scale),
            "indent": self.indent,
        }

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=1) + "\n", encoding="utf-8")
        return p

    # -- lookups ---------------------------------------------------------
    @property
    def ids(self) -> list[str]:
        return [s.id for s in self.strategies]

    def strategy(self, strategy_id: str | None) -> Strategy | None:
        for s in self.strategies:
            if s.id == strategy_id:
                return s
        return None

    def next_strategy(self, current: str | None) -> tuple[str, bool]:
        """Return ``(next_id, known)``; rotation wraps in declared order.

        ``known`` is False when ``current`` is not part of the rotation, in
        which case the first strategy is chosen. The caller is expected to
        surface that rather than hide it: an unknown predecessor means the
        ledger is missing strategy tags, and a silent guess is how a "never
        repeat the losing strategy" rule quietly stops holding.
        """
        ids = self.ids
        if not ids:
            raise ValueError("policy declares no strategies")
        if current in ids:
            return ids[(ids.index(current) + 1) % len(ids)], True
        return ids[0], False

    # -- commands --------------------------------------------------------
    def note_text(self, strategy_id: str, *, episode: int, mode: str, streak: int) -> str:
        return self.note_template.format(
            episode=episode, strategy=strategy_id, mode=mode, streak=streak
        )

    def command_for(
        self,
        strategy: Strategy,
        *,
        episode: int,
        mode: str,
        streak: int,
    ) -> str | None:
        """Render the operator command for one strategy, or None if untemplated."""
        if not strategy.command:
            return None
        note = self.note_text(strategy.id, episode=episode, mode=mode, streak=streak)
        return strategy.command.format(
            episode=episode,
            strategy=strategy.id,
            mode=mode,
            streak=streak,
            note=note,
            note_arg=f'--note "{note}"',
            config=strategy.config_files[0] if strategy.config_files else "",
            configs=" ".join(strategy.config_files),
        )