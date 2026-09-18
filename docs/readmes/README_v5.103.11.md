# v5.103.11 — EC pre_cool vestige retired + assistive room vacancy-hold labels

**Cards:** `EC-SOLAR-CLASS-DAYTIME-FORECAST-PROVENANCE-1` (D1) + folded vacancy-hold UX (D2) · Tier 2-DB (3 framing-disjoint reviews + fix-up + orchestrator mutation-verify).

## D1 — Delete the EC `pre_cool` vestige, preserve the principle
A git-blame trace showed the EC constraint `pre_cool` branch (energy.py) was born phase-blind in v3.7/v3.9, missed the June 2026 phase-fix its sibling coast branch got, was superseded by the v5.7.1 predictor banking (Path A), and never deleted. Producer/consumer (run twice, + Reviews A & B independently): its outputs are inert-except-harmful — the −2°F offset was never applied (`compute_energy_offset` has zero callers), and `mode="pre_cool"` only *blocked* Path A (the real afternoon banking) via the `!= "normal"` gate.
- **Deleted** the branch → the off-peak/low-SOC window falls through to `normal`; the misleading 9pm `pre_cool` label is gone and Path A is unblocked in its 10am–2pm window.
- **Tombstoned** (kept, config-key-safe) `CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET` + default + the read; **removed** its now-dead config-flow field (a dial that did nothing) and marked its strings "(retired — no effect)".
- **Principle preserved** (KEEP+DOCUMENT): Path A is *surplus-only*, so a hot-forecast day with low morning SOC gets no pre-cool — the "anticipatory off-peak *grid* pre-cool" idea is parked on card `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` (phase-aware, reuse `summer_peak_ahead`; measure-first).

## D2 — Assistive room vacancy-hold day/night fields
The per-room hold fields carried no guidance. Now the `data_description` help text states **"0 = disabled (hallways/circulation); typical: bedrooms ~1 min day / 30 min night, common ~1/15, closets & baths ~5-10 min night; night below day is rejected here, a blank night is auto-clamped up at runtime."** Field stays **blank when unset** (the review-caught fix: a prefilled suggested-value would have *persisted on any submit* and silently pinned the room against the room-type table). Free typed override preserved; `step=30`.

## Review ledger
A (D1 delete) SHIP; B (D1 integration/restart) SHIP — both independently confirmed the offset was already dead and Path A unblocks cleanly. C (D2) FIX-REQUIRED, converged with B on the persist-on-submit bug (C1). Fix-up: blank-when-unset + guidance-in-text, real schema-driving test, clamp-text reword, retired the dead offset field, restore allowlist (`pre_cool`→`normal`), doc drift. Orchestrator independently mutation-verified the C1 fix (re-adding the fallthrough REDs 3 tests).

## Validated 2026-09-18 (post-restart, running v5.103.11)

| Criterion | Result | Observed / evidence |
|---|---|---|
| EC no longer emits `pre_cool` | **PASS** | `sensor.ura_energy_coordinator_hvac_constraint` = `normal` (reason "normal conditions"); `sensor.ura_hvac_coordinator_mode.energy_constraint_mode` = `normal`. `pre_cool` is now unreachable by construction (branch deleted) — code-guaranteed, corroborated live. |
| Path A (real banking) healthy + eligible | **PASS** | `pre_cool_active = false` at `normal` mode (no surplus at this hour); Path A gate now sees `normal` in off-peak windows (unblocked). |
| Zero URA ERROR on boot | **PASS** | system-log ERROR filter for `universal_room_automation` = 0 entries. |
| Vacancy-hold: blank-when-unset + guidance text; explicit/0 preserved | **PASS (in-suite)** | Proven by the schema-driving test `test_hvac_vacancy_hold_ui_defaults.py` (9/9) — orchestrator mutation-verified (re-adding the type-default fallthrough REDs the unset-blank + explicit-0 tests). Config-flow rendering is not a live entity-state surface; validated in-suite by design. |
| Retired offset dial removed; current room holds untouched | **PASS** | offset config-flow field removed from the options schema (merged); CONF/read tombstoned (stored entries safe); D2 touched only display/text, not stored per-room values, so effective holds are unchanged by construction. |

Boot-only transient dismissed: none new for this cycle (standard Envoy/Bermuda/boot-settle WARNINGs unchanged from prior restarts).

## Rollback
`git revert` the merge, or (D1) the tombstoned constant means no stored-entry breakage on revert.
