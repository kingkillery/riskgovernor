"""Append-only episode ledger and the risk metrics derived from it.

The ledger is the single source of truth for the governor: every decision is a
pure function of ``(ledger, equity, policy)``. There is no hidden state, no
filesystem sniffing and no clock dependence.

Canonical episode schema (JSON)::

    {"id": 12, "net": "-0.00000304", "strategy": "plan1", "note": "..."}

``id`` may be any JSON value, but only numeric ids count as real episodes.
Non-numeric ids (``"RESET"``, ``"OVERRIDE"``, ...) are bookkeeping rows: they
break a loss streak but never become the "last episode".

Unknown keys on a row are preserved verbatim through a load/save round trip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator

# Bookkeeping rows that explicitly override a gate rather than record a result.
OVERRIDE_IDS = ("RESET", "OVERRIDE")

_ID_KEYS = ("id", "n", "episode")
_NET_KEYS = ("net", "result", "pnl")
_STRATEGY_KEYS = ("strategy", "family")
_ROWS_KEYS = ("episodes", "rounds", "rows")


def to_decimal(value: Any) -> Decimal | None:
    """Coerce a JSON-ish value to ``Decimal``; ``None`` when absent or unparseable.

    ``bool`` is rejected explicitly, because ``True`` would otherwise coerce
    to ``1`` and silently look like a real result. NaN and infinities are
    rejected too: they parse successfully, but they poison every later
    comparison.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


@dataclass
class Episode:
    """One realized episode: a trade, a round, a session leg."""

    id: Any = None
    net: Decimal | None = None
    strategy: str | None = None
    note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    # -- classification --------------------------------------------------
    @property
    def number(self) -> int | None:
        """The episode number, or ``None`` for bookkeeping rows."""
        if isinstance(self.id, bool) or not isinstance(self.id, (int, float)):
            return None
        return int(self.id)

    @property
    def is_loss(self) -> bool:
        return self.net is not None and self.net < 0

    @property
    def is_override(self) -> bool:
        """True for rows that explicitly cleared a gate."""
        return isinstance(self.id, str) and self.id.strip().upper() in OVERRIDE_IDS

    # -- (de)serialisation -----------------------------------------------
    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Episode":
        rest = dict(raw)
        episode = cls()
        for key in _ID_KEYS:
            if key in rest:
                episode.id = rest.pop(key)
                break
        for key in _NET_KEYS:
            if key in rest:
                episode.net = to_decimal(rest.pop(key))
                break
        for key in _STRATEGY_KEYS:
            if key in rest:
                episode.strategy = rest.pop(key)
                break
        episode.note = rest.pop("note", "") or ""
        episode.meta = rest
        return episode

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.meta)
        out["id"] = self.id
        out["net"] = None if self.net is None else str(self.net)
        if self.strategy is not None:
            out["strategy"] = self.strategy
        out["note"] = self.note
        return out


class Ledger:
    """An ordered collection of episodes plus derived risk metrics."""

    def __init__(
        self,
        episodes: Iterable[Episode] | None = None,
        *,
        meta: dict[str, Any] | None = None,
        rows_key: str = "episodes",
    ) -> None:
        self.episodes: list[Episode] = list(episodes or ())
        self.meta: dict[str, Any] = dict(meta or {})
        self.rows_key = rows_key

    # -- construction ----------------------------------------------------
    @classmethod
    def from_dict(cls, data: Any) -> "Ledger":
        """Build a ledger from a dict, a bare list of rows, or garbage.

        The rows key is remembered so that ``to_dict`` round-trips the original
        spelling (``rounds`` stays ``rounds``).
        """
        if isinstance(data, list):
            return cls(Episode.from_dict(r) for r in data if isinstance(r, dict))
        if not isinstance(data, dict):
            return cls()
        meta = dict(data)
        rows: list[Any] | None = None
        rows_key = "episodes"
        for key in _ROWS_KEYS:
            if isinstance(meta.get(key), list):
                rows_key = key
                rows = meta.pop(key)
                break
        episodes = [Episode.from_dict(r) for r in (rows or []) if isinstance(r, dict)]
        return cls(episodes, meta=meta, rows_key=rows_key)

    @classmethod
    def from_path(cls, path: str | Path) -> "Ledger":
        """Load a ledger from disk.

        A missing, unreadable, corrupt or non-object file yields an empty
        ledger rather than raising: the governor must be able to report
        "no data" as a first-class state.
        """
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return cls()

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.meta)
        out[self.rows_key] = [e.to_dict() for e in self.episodes]
        return out

    def save(self, path: str | Path, *, indent: int = 1) -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=indent) + "\n", encoding="utf-8")
        return p

    def append(self, episode: Episode) -> Episode:
        self.episodes.append(episode)
        return episode

    # -- container protocol ----------------------------------------------
    def __len__(self) -> int:
        return len(self.episodes)

    def __iter__(self) -> Iterator[Episode]:
        return iter(self.episodes)

    def __getitem__(self, index: int) -> Episode:
        return self.episodes[index]

    def __bool__(self) -> bool:
        return bool(self.episodes)

    # -- lookups ---------------------------------------------------------
    @property
    def last_numbered(self) -> Episode | None:
        """The most recent episode with a numeric id."""
        for episode in reversed(self.episodes):
            if episode.number is not None:
                return episode
        return None

    @property
    def last_net(self) -> Decimal | None:
        last = self.last_numbered
        return last.net if last is not None else None

    @property
    def last_strategy(self) -> str | None:
        last = self.last_numbered
        return last.strategy if last is not None else None

    def next_number(self) -> int:
        last = self.last_numbered
        return (last.number or 0) + 1 if last is not None else 1

    # -- metrics ---------------------------------------------------------
    def loss_streak(self) -> int:
        """Trailing consecutive losses, counting every row kind.

        A row with an unparseable net breaks the streak, so a zero-net
        override row ends it by construction.
        """
        streak = 0
        for episode in reversed(self.episodes):
            if not episode.is_loss:
                break
            streak += 1
        return streak

    def cumulative(self) -> Decimal:
        """Sum of every parseable net."""
        return sum(
            (e.net for e in self.episodes if e.net is not None), start=Decimal(0)
        )

    def peak(self) -> Decimal:
        """Running maximum of cumulative net.

        Rows without a parseable net are skipped, so a corrupt mid-ledger row
        is invisible to every metric, not just this one.
        """
        cumulative = Decimal(0)
        peak = Decimal(0)
        for episode in self.episodes:
            if episode.net is None:
                continue
            cumulative += episode.net
            if cumulative > peak:
                peak = cumulative
        return peak

    def drawdown(self) -> Decimal:
        """Peak-to-current decline of cumulative net, in ledger units.

        Rows without a parseable net are skipped; see ``peak``.
        """
        cumulative = Decimal(0)
        peak = Decimal(0)
        for episode in self.episodes:
            if episode.net is None:
                continue
            cumulative += episode.net
            if cumulative > peak:
                peak = cumulative
        return peak - cumulative

    # -- overrides -------------------------------------------------------
    def overrides(self) -> list[Episode]:
        """Every row that explicitly cleared a gate (the bypass audit trail)."""
        return [e for e in self.episodes if e.is_override]

    def override_count(self) -> int:
        return len(self.overrides())

    def record_override(
        self,
        reason: str,
        *,
        id: str = "OVERRIDE",
        operator: str | None = None,
    ) -> Episode:
        """Append a zero-net bookkeeping row that clears the loss streak.

        Overrides are recorded, never silent. ``overrides()`` is the audit
        trail of every time a gate was knowingly bypassed, which is the signal
        that a threshold is set wrong or the operator is chasing.
        """
        episode = Episode(id=id, net=Decimal(0), note=reason)
        if operator:
            episode.meta["operator"] = operator
        return self.append(episode)