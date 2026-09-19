"""JSON parameter store: apply resolved overrides to strategy config files.

Deliberately narrow. It loads a JSON file, updates only the keys it was told
to update, and writes it back. Every other key is preserved verbatim, which
matters when the configs are shared with tooling the governor knows nothing
about.

The store refuses to write anything if any target file is missing, so a
partially-applied recovery spec can never end up on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


class MissingConfigError(FileNotFoundError):
    """Raised when one or more strategy parameter files are absent."""

    def __init__(self, names: Iterable[str]) -> None:
        self.names = list(names)
        super().__init__("missing parameter file(s): " + ", ".join(self.names))


class ParamStore:
    """Reads and updates JSON parameter files rooted at ``root``."""

    def __init__(self, root: str | Path = ".", *, indent: int = 1) -> None:
        self.root = Path(root)
        self.indent = indent

    def path(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else self.root / p

    def read(self, name: str) -> dict[str, Any]:
        data = json.loads(self.path(name).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{name}: expected a JSON object")
        return data

    def missing(self, names: Iterable[str]) -> list[str]:
        return [n for n in names if not self.path(n).exists()]

    def apply(
        self,
        updates: Mapping[str, Mapping[str, Any]],
        *,
        dry_run: bool = False,
    ) -> list[str]:
        """Apply ``{filename: {key: value}}``; return the files written.

        Every target is read and validated before anything is written, so a
        missing or corrupt file leaves all files untouched. ``dry_run``
        performs the same validation and writes nothing.
        """
        missing = self.missing(updates.keys())
        if missing:
            raise MissingConfigError(missing)

        parsed: dict[str, dict[str, Any]] = {}
        for name, values in updates.items():
            config = json.loads(self.path(name).read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError(f"{name}: expected a JSON object")
            parsed[name] = dict(config)
            parsed[name].update(values)

        if dry_run:
            return []
        written: list[str] = []
        for name, updated in parsed.items():
            self.path(name).write_text(
                json.dumps(updated, indent=self.indent) + "\n", encoding="utf-8"
            )
            written.append(name)
        return written