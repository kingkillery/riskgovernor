# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-19

### Added

- `Ledger`: append-only episode record with derived metrics — loss streak,
  running peak, drawdown, cumulative. Non-finite and unparseable nets break a
  streak instead of poisoning it. Unknown keys and the original rows-key
  spelling survive a round trip. Bookkeeping rows (`RESET`/`OVERRIDE`) are the
  auditable record of every gate bypass.
- `RiskPolicy`: declarative JSON policy — ordered hard gates (equity floor,
  consecutive-loss streak, drawdown), strategy rotation, loss-sized recovery
  specs (`min(|loss|, cap)`), streak-triggered stake halving, and command
  templates. Duplicate strategy ids are rejected at load.
- `Governor`: pure decision function over `(ledger, equity, policy)` with a
  fixed verdict order — HALT gates first, then RECOVERY (rotate away from the
  loser, size to the loss), then STANDARD (offer everything, choose nothing).
  Single-strategy recovery is flagged as degenerate rather than silently
  claiming to rotate.
- `ParamStore`: applies resolved overrides to JSON configs, validating every
  target before writing anything, so a missing or corrupt file leaves all
  files untouched.
- CLI with three subcommands: `demo` (zero-config guided tour of every
  verdict), `init` (scaffolds policy, ledger and config stubs), and `decide`
  (verdict + optional recovery config write, `--dry-run`, `--json`,
  `--equity`, `--params-root`). Bare flags are treated as `decide`.
- Packaging: `py.typed`, MIT licence, console script, pytest config.
- CI: test matrix on Python 3.9–3.13 plus a build/`twine check` job; a
  tag-triggered publish workflow using PyPI trusted publishing.
- 74 tests.

[0.1.0]: https://github.com/kingkillery/riskgovernor/releases/tag/v0.1.0