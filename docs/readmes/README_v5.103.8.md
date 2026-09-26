# v5.103.8 — HVAC Conditioning-Demand Knobs & Away-Attribution Legibility

**Cards:** HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 + HVAC-AWAY-ATTRIBUTION-LEGIBILITY-1
(absorbs HVAC-COAST-OBSERVABILITY-1). **Tier 2 additive.**

## Problem

The v5.103.7 arc left three observability gaps around HVAC conditioning
demand and away-attribution:

1. Per-room HVAC vacancy tail-hold (day/night) was governed by module
   constant tables (`ROOM_TYPE_HVAC_HOLD[_NIGHT]`) with no operator-
   accessible per-room override — a round-1 knob was dropped in F5
   because it had no UI. Operators needed a per-room override without
   editing code.
2. `binary_sensor.<room>_hvac_occupied` shipped disabled-by-default and
   without an "established" attr — invisible for the ~43 existing rooms.
3. When a zone was forced to `preset=away` via one of the 11 URA-side
   emission sites, the operator had no legible way from the dashboard
   to answer *why* — reason was buried in the activity log only for the
   S1 path.
4. Energy-constraint (`coast` / `shed`) dwell was not observable — the
   `"10 · Mode"` sensor showed the mode but not how long it had been
   there.
5. `sensor.py:13797`'s `energy_coast` bool coincidentally equalled
   `energy_constraint_mode == "coast"` — a Bug Class #63 hazard.

## Solution

Additive. No behavior change to trust logic; only new attrs + a new
options-flow surface + a one-shot registry migration + a chokepoint
reason capture.

### Deliverables

| # | What | Where | Rung |
|---|---|---|---|
| D1/D2 | Per-room `CONF_HVAC_VACANCY_HOLD[_NIGHT]` reintroduced with UI. Blank → falls through to `ROOM_TYPE_HVAC_HOLD[_NIGHT]` table (never coerced to 0). Form-level `night >= day` validator + runtime clamp (with one-shot log). | `const.py`, `config_flow.py:async_step_climate`, `strings.json`, `translations/en.json`, `hvac_zones.py:_effective_hvac_hold_seconds` (extended signature, no second branch) | Config/options flow |
| D1/D2 hygiene | F5 leftover imports + stale comment deleted in `hvac_zones.py`. | `hvac_zones.py` | — |
| D3 | `HVACOccupiedBinarySensor._attr_entity_registry_enabled_default = True` + one-shot registry migration (`_enable_hvac_occupied_entities_one_shot`) that clears `disabled_by` for every pre-existing `binary_sensor.*_hvac_occupied` on the CM entry. Idempotent via `hvac_occupied_registry_enable_migration_done` sentinel. USER-disabled entities respected. | `binary_sensor.py:768`, `__init__.py` (helper + call site next to `_migrate_hvac_zone_entry_dwell_to_zero`) | Module const |
| D4 | `established` attr on the D2 entity, reading `is_zone_hvac_established(zone_id)` for the room's zone. | `binary_sensor.py:HVACOccupiedBinarySensor.extra_state_attributes` | — |
| D5 | `retreat_reason` attr on `HVACZonePresetSensor` — reads D6 cache; `unknown` sentinel when no write captured. | `sensor.py:HVACZonePresetSensor.extra_state_attributes` | — |
| D6 | Reason captured **inside** the chokepoint `emit_set_preset_mode` (`hvac_setpoint.py`) on **both** success paths (initial + retry). Keyed by `zone_id` into `hvac._last_reason_by_zone[zone_id] = (reason, ts)`. Covers ALL 11 URA-side preset-write sites automatically (Bug Class #53 prevention). Vocabulary committed as `HVAC_PRESET_REASONS: Final[frozenset]` in `const.py` — 6 S1 ladder + 9 static site literals (incl. the A-MED-4 fixup's `soft_nudge_preset_restore` at `hvac_override.py:4632`, which now passes `zone_id=` + `reason=`) + 2 dynamic `_auto_return(trigger=...)` values (`lease_expiry`, `stale_boot_release`) + `unknown`. B1 fixup: the initial build listed 3 phantom trigger literals (`excursion_return`/`_timeout`/`_settled`) that exist nowhere in the codebase — replaced with the real live triggers. | `hvac_setpoint.py:_capture_preset_reason`, `hvac.py` fields, `hvac_override.py:4632`, `const.py:HVAC_PRESET_REASONS` | Module const |
| D6-hydrate | Boot hydration from `ura_activity_log` (`action='preset_change'`, one row per zone, most recent). S1-path only (see P3 scope). Non-fatal on failure. | `hvac.py:_hydrate_last_reason_by_zone` | — |
| D7 | `energy_constraint_since` + `energy_constraint_duration_s` attrs on existing "10 · Mode" sensor (`HVACModeSensor`). Coordinator tracks `_energy_constraint_mode_since` at every `_handle_energy_constraint` transition. Sensor is now `RestoreEntity`: on `async_added_to_hass`, if the HVAC coordinator has NOT yet received any `EnergyConstraint` (i.e. still in its init state — the real restart window before the Energy Coordinator republishes), seed BOTH the restored `_energy_constraint_mode` AND `_energy_constraint_mode_since`. When the first live `_handle_energy_constraint` arrives, its transition-in stamp naturally resumes-if-same (no reset, dwell continues) or resets-if-different. A-MED-3 fixup: the initial build compared the restored mode against the still-`"normal"` init value at `async_added_to_hass`, which would ALWAYS have missed a real coast/shed restart — the exact case the feature exists for. **No new sensor.** | `hvac.py:get_mode_attrs`, `hvac.py:_handle_energy_constraint`, `sensor.py:HVACModeSensor` | — |
| D8 | Inline comment at `sensor.py:13797` naming `energy_coast` as the OverrideArrester's cached bool (`hvac_override.py:6596`), distinct from the live `energy_constraint_mode == "coast"` (Bug Class #63 coincidental equality). No behavioral change. | `sensor.py` | — |

### Operator placement table (Numbers Get Knobs)

| Knob | Rung | Home | Why |
|---|---|---|---|
| `CONF_HVAC_VACANCY_HOLD` | 2 (config/options flow) | Room options → "Climate & Fans" step → "Climate Backstop" section | Per-deployment structure; infrequent tune |
| `CONF_HVAC_VACANCY_HOLD_NIGHT` | 2 (config/options flow) | Same | Per-deployment structure; infrequent tune |
| `ROOM_TYPE_HVAC_HOLD[_NIGHT]` (defaults) | 1 (module const) | `const.py` | Safety-adjacent baseline; change should require review |
| `HVAC_PRESET_REASONS` | 1 (module const) | `const.py` | Enum-like vocabulary; adding a new reason literal is a code change |

### Falsifiable invariant

An operator can answer *"why is zone_N at preset X?"* from live UI alone:
- `sensor.ura_hvac_zone_preset_zone_N.attrs.retreat_reason` names a
  member of `HVAC_PRESET_REASONS`, matching the exact `reason=` string
  passed at the last write within one HVAC tick.
- `sensor.ura_hvac_coordinator_mode.attrs.energy_constraint_mode` +
  `energy_constraint_since` + `energy_constraint_duration_s` show
  current EC state and how long it has held.

### P3 restart-safety scope (honored, do not overpromise)

- S1-path reasons **survive restart** via ledger hydration from
  `ura_activity_log`.
- Non-S1 reasons show `retreat_reason='unknown'` after restart until
  the next write on that zone repopulates the cache. This is legibly
  missing, not silently wrong.
- Extending the chokepoint to log a durable `preset_write` row on
  every success is explicitly a separate cycle — not in this build.

### D3 bulk-enable note

The `_attr_entity_registry_enabled_default = True` flip only affects
entities created **after** the flip. The one-shot migration
`_enable_hvac_occupied_entities_one_shot` walks the entity registry
and clears `disabled_by` for every pre-existing
`binary_sensor.*_hvac_occupied` on the URA platform, EXCEPT those
disabled by the user (`RegistryEntryDisabler.USER` — respected).
Idempotent via `hvac_occupied_registry_enable_migration_done` on the
CM entry (precedent: `_zero_migration_done`).

## Live validation (prospective — to be filled in post-deploy)

- [ ] `binary_sensor.<room>_hvac_occupied` visible + enabled for every
      URA room; `established` attr matches
      `is_zone_hvac_established(zone_id)`.
- [ ] Set `CONF_HVAC_VACANCY_HOLD=300` on ONE room via the options
      flow; that room's `hvac_vacancy_hold_s` attr reports 300 while
      sibling rooms still report their room-type default.
- [ ] Try to submit `day=600, night=300` in the form: rejected with
      `hvac_hold_night_below_day`.
- [ ] After next S1 preset change on any zone,
      `sensor.ura_hvac_zone_preset_zone_N.attrs.retreat_reason` matches
      the reason from the activity_log details_json.
- [ ] After next EC transition to `coast`,
      `sensor.ura_hvac_coordinator_mode.attrs.energy_constraint_since`
      is populated and `duration_s` increments each tick.
- [ ] After HA restart mid-coast, `since` restores from the pre-restart
      transition ts (resume-if-same).

## Live Validation — Validated 2026-09-25 (write-back)

Deployed 2026-09-17 22:16 CDT. Evidence gathered read-only from the HA recorder (7 days, from 09-18 04:12 CDT), the URA DB `ura_activity_log`, and `.storage/core.config_entries`. Times are CDT unless marked Z.

| # | Criterion | Verdict | Observed evidence |
|---|---|---|---|
| 1 | `binary_sensor.<room>_hvac_occupied` visible and enabled for every room; `established` matches zone establishment | **PASS** (presence), equality not independently computed | 43 `binary_sensor.*_hvac_occupied` entities are recording states for 43 URA rooms (disabled entities do not record). The CM option `hvac_occupied_registry_enable_migration_done: True`. `established` is present on all 43: 40 `True`, 3 `False` (Garage A, Garage B, Patio — `source: idle`; these rooms have no `climate_entity`). The value was not compared against `is_zone_hvac_established()` directly, because that is an internal function. |
| 2 | Per-room `CONF_HVAC_VACANCY_HOLD=300` on one room is reflected in `hvac_vacancy_hold_s` | **NOT-EXERCISED** | Only Jaya Bedroom carries overrides (`hvac_vacancy_hold: 60`, `_night: 1800`, entry modified 09-19 23:03Z). These equal the bedroom table defaults (`ROOM_TYPE_HVAC_HOLD` 60 / `_NIGHT` 1800), so the reading is non-discriminating: the attribute reads 60 by day and 1800 at night, the same as Master Bedroom. |
| 3 | The form rejects `day=600, night=300` with `hvac_hold_night_below_day` | **IN-SUITE-ONLY** | This needs a live options-form submission, which was not performed. |
| 4 | `retreat_reason` matches the activity-log reason for the last S1 write | **PASS** | zone_3: `sensor.ura_hvac_coordinator_hvac_zone_preset_zone_3` has `retreat_reason: house_state_transition`, `retreat_reason_at: 2026-09-26T02:09:27.975425Z`, and the activity row at `02:09:27.975444Z` has `reason: house_state_transition`. zone_2: `energy_shed_cap_reached` at `00:32:57.817249Z`, matching the row at `00:32:57.817280Z`. zone_1 shows `soft_nudge_preset_restore`, a non-S1 path that has no activity row by design. |
| 5 | On an EC transition to `coast`, `energy_constraint_since` is populated and `duration_s` increments | **PASS** | `sensor.ura_hvac_coordinator_mode` went to `coast` at 09-18 16:00:50 with `energy_constraint_since: 2026-09-18T21:00:36Z`; `energy_constraint_duration_s` rose 160 → 1134 at a ~30 s cadence. Each of the 8 daily coast entries (16:00) and returns to normal (20:00) from 09-18 to 09-25 carries a fresh `since` stamp. |
| 6 | After a restart mid-coast, `since` resumes (resume-if-same) | **PASS ×2** | 09-18 restart (stop 16:07:32): `since` stayed `21:00:36Z`, duration 404 → 636 after boot. 09-25 restart (stop 18:05:35): `since` stayed `21:00:43Z`, duration 7470 → 7722. The same resume behaviour holds for `normal` across the 09-25 20:38/20:52 CM entity reloads. |

**Method + limits.** Criteria 2 and 3 need operator UI actions that have not happened. Dismissed boot transients: `not_initialized`/`unavailable` rows on the Mode sensor during restarts and CM reloads. **Verdicts: 4 PASS · 1 NOT-EXERCISED · 1 IN-SUITE-ONLY · 0 FAIL.**

## Explicitly NOT in this cycle

- `CONF_HVAC_ZONE_ENTRY_DWELL` removal (P5) — separate cycle.
- Durable `preset_write` activity row on every success (P3) — separate
  cycle.
- No new coast sensor (P7) — attrs on existing "10 · Mode".
- No redirect / deprecation of `sensor.py:13797 energy_coast` (P8) —
  distinct semantics documented in place.

## Tests

`quality/tests/test_v5_103_8_hvac_knobs_and_obs.py` — 9 mutation-anchored tests:
- `_coerce_hold_override` blank/None/negative → None; explicit 0 preserved.
- Resolver honours `override_day` / `override_night` (mutation: strip branch → RED).
- Blank falls through to table (mutation: coerce blank → 0 → RED).
- Monotonicity clamp raises night to day (mutation: strip clamp → RED).
- `HVAC_PRESET_REASONS` frozenset present with required vocabulary
  (mutation: strip a reason → RED).
- Every `reason="..."` literal in `emit_set_preset_mode(...)` calls is
  in the frozenset (targeted grep re-enumeration).
- `_capture_preset_reason` populates `hvac._last_reason_by_zone`
  (mutation: neuter helper → RED).
- Missing manager / zero zone_id are no-ops (never-crash contract).

Plus test-fixture updates for:
- `test_zzz_hvac_conditioning_demand.py`: `test_per_room_override_conf_removed_f5`
  renamed to `test_per_room_override_conf_reintroduced_v5_103_8`;
  `test_d3_defaults_and_tables_present` updated to expect the CONFs
  present again.
- `test_bathroom_exhaust_intelligence_cycle.py:test_d5_d8_cross_field_validator`:
  add the two new CONF names to the AST-exec globals dict.
