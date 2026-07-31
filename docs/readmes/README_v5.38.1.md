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
