# URA v5.38.1 — Hotfix: or-chain defeats the clear-checkbox ('' options override)

Found in v5.38.0 live validation: Master Suite chip tripped "water leak detected" on
the Master Bathroom sensor the operator CLEARED — because two readers used
`options.get(K) or data.get(K)`, which treats the clear-checkbox's explicit `''`
options override as absent and falls through to the stale entry.data value.

Fix: presence-aware reads (`K in options → options[K]` else `data.get(K)`) at BOTH
leak readers — the new #12 chip (aggregation.py ~:4417) and the pre-existing
alert-manager path (~:1092, which meant leak NOTIFICATIONS also still honored cleared
sensors). Sweep confirmed no other clearable-field or-chains exist. Regression test
pins the presence-aware shape + count.

Lesson recorded: `{**data, **options}` merges honor `''`; `or`-chains do not — the
clear mechanism's consumers must be presence-aware or merge-style.

## Live Validation
- H1: clean boot; Master Suite chip OFF (cleared sensor genuinely ignored); Back
  Hallway remains OFF.

### Validated 2026-07-30 (~21:34 CDT, verified fresh boot 21:31)
| # | Result | Evidence |
|---|---|---|
| H1 | **PASS** | Both zone safety chips OFF on the away-setback house (Master Suite no longer trips on the CLEARED bathroom sensor; Back Hallway clean). Fresh boot verified by entity timestamps ≥ boot; zero URA errors. |

Ops note: one ha_restart call returned success without actually restarting (v5.38.1 sat
on disk unloaded for ~10 min; diagnosis chased a phantom code bug). Discipline: verify
restarts by boot signature (new PERSON INIT log + entity restamps), not the call result.
