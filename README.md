# riskgovernor

[![CI](https://github.com/kingkillery/riskgovernor/actions/workflows/ci.yml/badge.svg)](https://github.com/kingkillery/riskgovernor/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/riskgovernor.svg)](https://pypi.org/project/riskgovernor/)
[![Python](https://img.shields.io/pypi/pyversions/riskgovernor.svg)](https://pypi.org/project/riskgovernor/)

Deterministic bankroll risk governance: hard gates, strategy rotation, and
loss-sized recovery, expressed as pure data plus a pure decision function.

The governor answers exactly one question — *what should the next episode be,
given what has already happened?* — and it answers it the same way every time.
It never places an order. It prints a command for a human to approve.

![riskgovernor demo](docs/demo.gif)

*Seventy-eight seconds: the problem, the model, and the demo — narrated.*
[Silent master](docs/demo.mp4) · [**with voiceover**](docs/demo-voiced.mp4)

## 30-second start

```console
$ pip install riskgovernor
$ riskgovernor demo
```

`demo` needs no files and walks through every verdict in order — STANDARD,
RECOVERY, both HALTs, and what an override looks like. When you want your
own setup:

```console
$ riskgovernor init                 # writes policy.json, ledger.json, config stubs
$ riskgovernor decide --policy policy.json --ledger ledger.json
```

Three commands, zero reading required. The rest of this README is what's
underneath.

```console
$ riskgovernor decide --policy policy.json --ledger ledger.json --equity 0.00015414
--- RISK GOVERNOR ---
last episode:   38
last net:       -3.04 uBTC
last strategy:  plan1
streak:         1
drawdown:       3.04 uBTC
cumulative:     -2.65 uBTC
peak:           0.39 uBTC
equity:         154.14 uBTC
floor headroom: 79.14 uBTC
overrides used: 0

VERDICT: RECOVERY glacier
  set target = 9800
  set side = UNDER
  set max_loss = 0.00000150
  set max_rounds = 40
  set max_profit = 0.00000200
  set base_stake = 0.00000050
  py -3.13 run_single_round.py 39 s12_glacier.json --note "R39 glacier recovery streak=1"
  wrote s12_glacier.json (recovery spec)
```

## Why this exists

Most risk rules live inside the thing they are supposed to constrain. The
position sizer sits in the strategy, the drawdown limit sits in the bot, and
the first time the rule is inconvenient somebody comments it out.

This package separates the two. The governor is a pure function of
`(ledger, equity, policy)`, so it can be reviewed, diffed, unit-tested and
replayed against history without touching a live account. Execution stays in
whatever runner you already have.

## Install

Pure standard library, no dependencies.

```console
pip install riskgovernor        # from PyPI
pip install -e ".[dev]"         # from a checkout, with test deps
```

## The verdict table

Evaluated in order; the first match wins.

| # | Condition | Verdict |
|---|-----------|---------|
| 1 | equity below `gates.floor` | `HALT` |
| 2 | loss streak at `gates.max_consecutive_losses` | `HALT` |
| 3 | drawdown at `gates.max_drawdown` | `HALT` |
| 4 | last episode's net was negative | `RECOVERY` — rotate strategy, size to the loss |
| 5 | otherwise | `STANDARD` — offer every strategy |

Gate 1 is skipped when no equity is supplied, so the same code runs offline.

`RECOVERY` rotates forward through the declared strategy order and wraps. With
two or more strategies it never re-selects the one that just lost. A
single-strategy policy cannot avoid doing so — the governor flags it as a
degenerate rotation in `notes` rather than pretending otherwise. `STANDARD`
deliberately chooses nothing: it lists the options and leaves the call to the
operator.

## The ledger

An ordered list of episodes. JSON, with the usual file conventions.

```json
{
  "episodes": [
    {"id": 37, "net": "0.000000389793877560", "strategy": "glacier"},
    {"id": 38, "net": "-0.000003041134348000", "strategy": "plan1",
     "note": "R38 plan1 standard streak=0"}
  ]
}
```

- `id` may be any JSON value, but only **numeric** ids are episodes. Anything
  else (`"RESET"`, `"OVERRIDE"`, `"P1"`) is bookkeeping: it never becomes the
  "last episode", and a zero-net row ends a loss streak by construction.
- `net` is a decimal string. Unparseable values break the streak rather than
  being silently treated as zero.
- Unknown keys survive a load/save round trip, and the original rows key
  (`rounds`, `episodes`, `rows`) is preserved.
- `net`, `result` and `pnl` are all accepted as the result key.

`save()` writes the canonical schema: row ids become `id` (a ledger read as
`n` is re-emitted as `id`) and `note` is materialised on every row. Content is
preserved; spelling is not. Don't point `save()` at a ledger another tool
still reads by its own key names.

**Record the strategy on every row.** This is the one field the governor
cannot reconstruct. If it is missing, `RECOVERY` falls back to the first
strategy in the rotation and says so in `notes` — it does not guess silently.

## The policy

Plain JSON, so the risk rules can be reviewed on their own.

```json
{
  "unit": "USD",
  "scale": "1",
  "note_template": "E{episode} {strategy} {mode} streak={streak}",
  "gates": {
    "floor": "5000",
    "max_consecutive_losses": 3,
    "max_drawdown": "2000"
  },
  "strategies": [
    {
      "id": "core",
      "config_files": ["core.json"],
      "command": "python run_strategy.py {episode} {config} {note_arg}",
      "recovery": {
        "params": { "max_loss": "100", "max_rounds": 15 },
        "size_param": "max_profit",
        "cap": "200",
        "stake_param": "base_stake",
        "stake_base": "50",
        "stake_halved": "25",
        "halve_at_streak": 2
      }
    }
  ]
}
```

Strategy order **is** the rotation order.

`recovery` describes what a recovery episode looks like:

- `params` — static overrides, applied verbatim.
- `size_param` / `cap` — that parameter is set to `min(|loss|, cap)`, so the
  recovery target is sized to the loss that triggered it rather than being a
  fixed constant.
- `stake_param` / `stake_base` / `stake_halved` / `halve_at_streak` — the stake
  is cut once losses accumulate. De-risk on the way down, don't double up.

Command templates may use `{episode}`, `{strategy}`, `{mode}`, `{streak}`,
`{config}`, `{configs}`, `{note}` and `{note_arg}`.

### Units

Every number in the policy — gates, caps, recovery params — and every
`--equity` value is in **ledger units**: the same units as the ledger's `net`
values. `scale` and `unit` are presentation only and never participate in a
comparison. Keep them consistent; a `floor` written in display units against a
ledger in base units will read as a floor 10^6 times too high.

## Overrides are recorded, never silent

`HALT` is a hard stop, and the honest failure mode is not that the gate is
wrong — it is that a human overrides it. So overrides get their own row:

```python
governor.override(ledger, "resuming after review", operator="alice")
ledger.override_count()   # 1
ledger.overrides()        # the full audit trail
```

The count is printed on every run. A rising number is the signal that a
threshold is set wrong or that someone is chasing losses — which is exactly
the thing the streak gate exists to catch. Record it; never clear it quietly.

## Writing recovery parameters

`ParamStore` applies resolved overrides to JSON config files, updating only the
keys it was given and preserving everything else:

```python
from riskgovernor import Governor, ParamStore

governor = Governor(policy)
decision = governor.decide(ledger, equity=equity)

updates = governor.recovery_overrides(decision, ledger)   # {file: {key: value}}
ParamStore("configs").apply(updates)                      # {} for non-recovery verdicts
```

Every target file is read and validated **before** anything is written, so a
missing, corrupt or malformed file leaves all files untouched — a
partly-applied spec cannot land on disk.

## What this is not

- **Not an executor.** It prints commands. Approval is a separate step.
- **Not a strategy.** It has no view on whether your edge is real. Gates bound
  damage; they do not create profit. A negative-expectancy process governed
  perfectly is still negative-expectancy.
- **Not coupled to any market.** Nothing here knows what an episode is.

## Design notes

**Strategy identity belongs in the ledger.** An earlier version of the
predecessor script inferred "which strategy ran last" by globbing output files
in the working directory. That worked until a runner archived several rounds
into one directory, at which point the first filename to match a pattern won
and the governor recommended re-running the strategy that had just lost —
silently violating its own core rule. Persisted state beats sniffed state.
The artifact-scanning version in that script has since been made
recency-ordered, which is the best available repair when the ledger carries no
tag; in this package, the ledger is simply authoritative.

**Pure decision function.** No clock, no filesystem, no randomness. The same
inputs produce the same verdict, so behaviour can be pinned by tests and
replayed against history.

## Development

```console
python -m pytest tests -q
```

74 tests cover ledger parsing and metric derivation (including NaN and
non-finite rejection), gate ordering and precedence, rotation and recovery
sizing, config-file preservation and failure atomicity, policy validation,
and the CLI end to end.

## Origin

Extracted from a bankroll protocol built for a dice-betting automation. The
protocol did its job — floors held, streaks halted, the audit trail was
complete — and the underlying expectation was still negative, which is why
that part stayed where it was and this part was generalised instead.

## Licence

MIT.