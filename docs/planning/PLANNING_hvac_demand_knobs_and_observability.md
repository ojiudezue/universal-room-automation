# PLANNING — HVAC Conditioning-Demand Knobs & Away-Attribution Legibility (revised post plan-review)

**Cards:** HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 + HVAC-AWAY-ATTRIBUTION-LEGIBILITY-1. **Absorbs** HVAC-COAST-OBSERVABILITY-1.
**Post-ship gap** for v5.103.7. **Tier 2** (two framing-disjoint reviews). This revision addresses plan-review P1-P10.

---

## Institutional context verified (revised)

### Prior art — REUSE-vs-BUILD verdict

| Piece | Verdict | Existing at |
|---|---|---|
| Per-room HVAC hold value | REUSED tables | `const.py:1203 ROOM_TYPE_HVAC_HOLD`, `:1214 ROOM_TYPE_HVAC_HOLD_NIGHT`, defaults `:1197/:1201` |
| Effective-hold resolver | REUSED + **EXTEND SIGNATURE** | `hvac_zones.py:837 _effective_hvac_hold_seconds(room_type, house_state)` — today does NOT read per-entry options; D1/D2 will pass in the per-room override. F5 leftovers at `:524-527` (stale comment) + `:528-536` (dead imports of `CONF_ROOM_TYPE`, `ROOM_TYPE_HVAC_HOLD*`, defaults) get cleaned in the SAME PR — no second resolution branch |
| Per-room hold CONF (reintroduce with UI) | REINTRODUCE | Round-1 `CONF_HVAC_VACANCY_HOLD[_NIGHT]` dropped per F5 note `const.py:1227-1233`. `CONF_FAN_VACANCY_HOLD` (`const.py:971`) is precedent for the NAME but ALSO has no UI — do NOT copy its inertness |
| **ROOM options step (P1 fix)** | REUSED — extend | `config_flow.py:11419 async_step_climate` (the reconfigure "Climate & Fans" step in the **room** options flow; menu entry `"climate"` at `:3422`). **NOT** `async_step_coordinator_hvac_settings` at `:5836`, which is the house-wide CM step (holds `CONF_HVAC_ZONE_ENTRY_DWELL`). The per-room resolver reads `entry.options` of the ROOM config entry (`hvac_zones.py:549 merged = {**entry.data, **entry.options}` in the room-name/entry-meta scan) — that is exactly the entry `async_step_climate` writes to |
| Strings for the new fields (P9) | ADD | `strings.json` — precedent labels/descriptions live at `:1165/:1197` for the CM entry-dwell knob. Room `climate` step already has a strings block; add two localizable labels + descriptions |
| D2 entity | REUSED | `binary_sensor.py:745 HVACOccupiedBinarySensor` (default-disabled at `:768`; attrs at `:822-896`) |
| **D3 registry migration (P6 fix)** | ADD one-shot migration | Precedent: `__init__.py:697` `..._migration_done` flag. There are ~43 existing `binary_sensor.<room>_hvac_occupied` entities that are currently disabled — `_attr_entity_registry_enabled_default=True` only affects entities created AFTER the flip. A one-shot registry pass enables the existing ones; recorder cost ~43 binary sensors is one-line-acceptable |
| Zone-established check | REUSED | `hvac_zones.py:939 is_zone_hvac_established(zone_id)` |
| Zone preset sensor | REUSED | `sensor.py:12697 HVACZonePresetSensor` — parent "55 · HVAC Zone Preset ..." |
| Preset-change reason ladder | REUSED | `hvac.py:2273-2306` (S1 ladder — 6 values) |
| **Preset-write chokepoint (P2 fix)** | REUSED — hook here | `hvac_setpoint.py:241 emit_set_preset_mode(..., reason: str = "")`. All 11 URA-side preset-write sites already pass `reason=`: `hvac.py:2360` (S1), `hvac_egress.py:795`, `hvac_override.py:3547/4113/4632/5833/6237`, `hvac_excursion.py:667/1131`, `hvac_predict.py:1029/1549`. **Capture reason IN THE CHOKEPOINT keyed by zone** — hooking only the S1 site leaves the other 10 sites stale (Bug Class #53). |
| **Full reason vocabulary (P4)** | ENUMERATE | The falsifiable invariant covers ALL emitted values, not just S1's 6. Complete set to enumerate/document below. |
| Durable log of preset changes | REUSED **partial** | `action='preset_change'` rows written only at `hvac.py:2397` (S1 path); the chokepoint's `_log_deferred_write` only fires on DEFERRAL. See P3 scoping below |
| Coast/shed value | REUSED | `hvac.py:660 energy_constraint_mode`; producer `signals.py:253-256 SIGNAL_ENERGY_CONSTRAINT / EnergyConstraint.mode` |
| **Coast surface (P7 fix)** | REUSED — extend existing | `sensor.py:12089` `"10 · Mode"` (`HVACCoordinatorModeSensor`); `hvac.py:4364 get_mode_attrs` already exposes `energy_constraint_mode` + `energy_offset`. **Do NOT create a new sensor.** Add `energy_constraint_since` + `energy_constraint_duration_s` attrs to this sensor, RestoreEntity on it |
| **`energy_coast` bool at sensor.py:13797 (P8 fix)** | KEEP + DOCUMENT | This is the **override manager's** own bool (`hvac_override.py:6596` set by `update_energy_state` from `:2242`), with 2 live trust consumers (`hvac_override.py:2028/3171`) + test at `test_cycle_e_observability.py:42/553`. `energy_coast == (energy_constraint_mode == "coast")` today is a Bug Class #63 coincidental-equality assumption; the two have distinct semantics (override-manager-cached vs live signal). Do NOT redirect. Document the distinction inline |
| **D5-tombstone `CONF_HVAC_ZONE_ENTRY_DWELL` (P5 fix)** | NOT DEAD — DROP FROM PLAN | Live surfaces: `number.py:417-494` (Number entity + options write-back), `button.py:843-860`, `config_flow.py:5873/:6424`, `strings.json:1165/:1197`, `hvac.py:42/:174/:466`, live consumer `hvac.py:2058`, migration `__init__.py:684`. Removed from this plan; card separately as a multi-surface entity-removal cycle |
| Entity-name convention | REUSED | `_attr_has_entity_name = True` + `"NN · Name"` (e.g. `sensor.py:12089`, `:12712`) |

### Design docs / planning consulted
- `docs/Coordinator/HVAC.md` (preset ladder, D5 duty, coast/shed).
- v5.103.7 ship notes: F5 drop rationale, F6 D2 disabled-default note.
- `AUDIT_hvac_duty_cycle_protection_2026_09_17` — coast is the gating condition for `runtime_exceeded`.
- QUALITY_CONTEXT #34 (module-vs-function DOMAIN), #53 (computed-but-not-consumed / one-missed-site), #63 (coincidental equality masks a concept split).

### Code locations surveyed end-to-end
`const.py:1190-1233`, `binary_sensor.py:745-896`, `sensor.py:12080-12100, 12697-12793, 13780-13810`, `hvac.py:655-663, 2260-2412, 4360-4400`, `hvac_zones.py:515-540, 820-870, 930-1010`, `hvac_setpoint.py:230-320`, `config_flow.py:3410-3428, 5836-5900, 11419-11470`, `__init__.py:680-710`.

---

## Falsifiable invariant (P4-revised, complete vocabulary)

An operator answering "why is zone_N at preset X?" from the **live UI alone** can:
1. Identify one of the following reason values as the last-write reason (via the chokepoint-captured cache surfaced on the zone preset sensor):
   - **S1 ladder (6):** `stale_occupancy`, `vacant_past_grace`, `runtime_exceeded`, `pre_arrival`, `house_state_transition`, `comfort_delay_active` — from `hvac.py:2273-2306`.
   - **Site reasons (9)** passed to `emit_set_preset_mode(reason=...)` at:
     `hvac_egress.py:795`, `hvac_override.py:3547`, `hvac_override.py:4113`, `hvac_override.py:4632`, `hvac_override.py:5833`, `hvac_override.py:6237`, `hvac_excursion.py:667`, `hvac_excursion.py:1131`, `hvac_predict.py:1029`, `hvac_predict.py:1549` (the actual reason strings passed at each site are captured during build — the invariant is on the COMPLETE 15+ set including the S1 six).
   - Plus `unknown` iff no write has been captured since the cache was last cleared (first-boot pre-hydration window only).
2. Identify current energy constraint state as one of `{normal, pre_cool, pre_heat, coast, shed}` from the existing `"10 · Mode"` sensor attrs, with `energy_constraint_since` and `energy_constraint_duration_s` visible.

**Falsifier:** any state where a preset-write has occurred and the sensor's `retreat_reason` disagrees with the reason argument that was passed to `emit_set_preset_mode` on that write, OR any state where `energy_constraint_mode` transitions and the sensor's `since`/`duration_s` do not reflect that transition within one HVAC tick.

**Vocabulary-completeness sub-invariant:** the build enumerates every literal `reason=` string passed at the 11 sites and commits it into a `HVAC_PRESET_REASONS: Final[frozenset]` in const.py; any future PR adding a new site with a reason string outside that set fails a mutation test.

---

## Deliverables (revised) — placement + restart-safety

| # | Deliverable | Level | Mechanism | Config flow (exact) | User-friendly label | Restart-safe? (why) |
|---|---|---|---|---|---|---|
| D1 | Per-room HVAC vacancy hold (day) — reintroduce `CONF_HVAC_VACANCY_HOLD` with UI | Room | Room options-flow field (structural, Rung 2) | **`config_flow.py:11419 async_step_climate`** (ROOM options step, menu entry `"climate"` at `:3422`) — schema addition | strings.json label "HVAC vacancy hold (day, seconds — blank uses the room-type default)" | YES — `entry.options` persisted by HA. Read at `hvac_zones.py:549 merged = {**entry.data, **entry.options}` and threaded into an extended `_effective_hvac_hold_seconds(room_type, house_state, override_day=None, override_night=None)`. blank/None → fall through to table |
| D2 | Per-room HVAC vacancy hold (night) — `CONF_HVAC_VACANCY_HOLD_NIGHT` | Room | Same room step | Same room step | strings.json label "HVAC vacancy hold (night, seconds — blank uses the room-type default)" | YES — same rationale. **Monotonicity (P10):** form validator rejects when BOTH day+night supplied and `night < day`; resolver ALSO clamps `night = max(night, day)` post-resolution and logs once on clamp. blank/None → table (never coerce to 0 — 0 is the legitimate hallway never-hold at `const.py:1207/:1225`) |
| D1/D2 hygiene | Clean F5 leftovers | Room-scoped code | Delete stale imports `hvac_zones.py:528-536` (`CONF_ROOM_TYPE`, `ROOM_TYPE_HVAC_HOLD*`, defaults) and stale comment `:524-527`; extend the sole resolver instead of adding a branch | n/a | n/a | YES — deletion only |
| D3 | D2 entity enable-by-default **+ one-shot registry migration** (P6 fix) | Room | Flip `_attr_entity_registry_enabled_default = True` at `binary_sensor.py:768` **AND** add `_hvac_occupied_registry_enable_migration_done` one-shot in `__init__.py` following the `:697 ..._migration_done` precedent — walks entity registry, sets `disabled_by = None` on every existing `binary_sensor.*_hvac_occupied` | n/a | (existing per-room entity) | YES — flip only affects new entities; migration flag is persisted in entry data so it fires exactly once. Recorder cost ~43 binary sensors accepted |
| D4 | `established` attr on D2 | Room | New attr in `HVACOccupiedBinarySensor.extra_state_attributes` reading `zm.is_zone_hvac_established(zone_id_for_room)` (`hvac_zones.py:939`) | n/a | attr `established` (bool) | YES — re-derived every read |
| D5 | `retreat_reason` attr on `HVACZonePresetSensor` | Zone | Read D6's chokepoint-captured cache | n/a | attr `retreat_reason` on "55 · HVAC Zone Preset ..." | Restart-safety: **see P3 scoping below** |
| D6 | Reason capture at the chokepoint (P2 fix) | House (HVAC) | Capture the `reason` param INSIDE `emit_set_preset_mode` (`hvac_setpoint.py:241`) on successful (non-deferred) writes, keyed by `zone_id`. Store in an `hvac._last_reason_by_zone: dict[str, tuple[str, datetime]]` reachable from the sensor. Covers ALL 11 sites automatically — no per-caller wiring | n/a | n/a | See P3 |
| D6-hydrate | Boot hydration of the reason cache (P3-scoped) | House (HVAC) | On HVAC coordinator setup, `SELECT zone, details_json->>'$.reason', ts FROM ura_activity_log WHERE coordinator='hvac' AND action='preset_change' ORDER BY ts DESC` grouped by zone (one row per zone). ONLY the S1 path writes `action='preset_change'` today (`hvac.py:2397`) | n/a | n/a | See P3 |
| D7 | Coast/shed observability — **attrs on existing "10 · Mode" sensor** (P7 fix) | House | Extend `HVACCoordinatorModeSensor` (`sensor.py:12080-12100`) to add attrs `energy_constraint_since` (iso ts) + `energy_constraint_duration_s` (int). Values fed from `hvac.energy_constraint_mode` transition tracker (add a `_energy_constraint_mode_since` on the coordinator, updated in the same site that assigns `_energy_constraint_mode`). `energy_constraint_mode` + `energy_offset` are ALREADY exposed via `hvac.py:4364 get_mode_attrs` | n/a — attribute additions on existing entity | (existing) "10 · Mode" | **YES via RestoreEntity on the mode sensor**: persist last observed `energy_constraint_mode` + `since` ts; on restart, if the live mode equals the restored mode, resume the duration from `since`; if it differs, reset `since` to now. Without RestoreEntity, `duration_s` zeros out mid-coast on every restart |
| D8 | Document the distinct semantics of `sensor.py:13797 energy_coast` (P8 fix) | House | Inline comment at `sensor.py:13797` explaining it is `override_manager.energy_coast` (`hvac_override.py:6596`), a cached bool distinct from the live `energy_constraint_mode == "coast"`; consumers `hvac_override.py:2028/:3171` + test `test_cycle_e_observability.py:42/:553` are the reason it stays. NO redirect, NO deprecation | n/a | n/a | YES — no behavioral change |

### P3 decision — D5/D6 restart-safety scope (explicit)

**Chosen scope:** *"S1-path reasons survive restart via ledger hydration; other-site reasons show `unknown` on the affected zone until the next preset write on that zone repopulates the cache."*

Rationale:
- The chokepoint writes durable ledger rows only via `_log_deferred_write` (on deferral, not on success), and `action='preset_change'` durable rows are written only at `hvac.py:2397` in the S1 path. Hydrating other-site reasons durably would require extending the chokepoint to log every successful write — that is **explicit scope growth** we are declining in this cycle.
- Alternative (declined): extend `emit_set_preset_mode` to also log a durable `preset_write` activity row on every success. Rejected here because it doubles activity_log volume for a marginal restart-window benefit (typical restart << typical zone quiet time between writes; the next write in that zone repopulates within the same house-state transition). Card the extension separately if the operator finds `unknown` post-restart annoying in practice.
- **Acceptance criterion for D5 is scoped to match:** post-restart, a zone whose LAST write went through the S1 ladder shows the correct S1 reason; a zone whose last write went through egress/excursion/predict/override may show `unknown` until the next write — that state is legibly `unknown`, not a stale wrong value.

---

## Files touched

- `custom_components/universal_room_automation/const.py` — reintroduce `CONF_HVAC_VACANCY_HOLD`, `CONF_HVAC_VACANCY_HOLD_NIGHT`; add `HVAC_PRESET_REASONS: Final[frozenset]`; update F5 note.
- `custom_components/universal_room_automation/config_flow.py:11419 async_step_climate` — add the two optional int fields + form-level night≥day validator.
- `custom_components/universal_room_automation/strings.json` — new field labels/descriptions in the room climate step (P9).
- `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py` — delete F5 leftover imports+comment (`:524-536`); extend `_effective_hvac_hold_seconds` signature; pass per-entry overrides from the room-name/entry-meta scan; clamp night≥day post-resolution, log once on clamp.
- `custom_components/universal_room_automation/binary_sensor.py:745-896` — flip default-enabled (D3); add `established` attr (D4).
- `custom_components/universal_room_automation/__init__.py` — one-shot `_hvac_occupied_registry_enable_migration_done` (D3 migration).
- `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py:241` — capture `reason` on successful preset writes into `hvac._last_reason_by_zone` (D6).
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — add `_last_reason_by_zone` + boot hydration from `ura_activity_log` (D6-hydrate, S1-scope); add `_energy_constraint_mode_since` tracker updated wherever `_energy_constraint_mode` is assigned (D7 backing).
- `custom_components/universal_room_automation/sensor.py:12080-12100 HVACCoordinatorModeSensor` — add `energy_constraint_since` + `energy_constraint_duration_s` attrs + RestoreEntity (D7); add `retreat_reason` attr to `HVACZonePresetSensor` at `:12729` (D5); inline comment at `:13797` on the distinct `energy_coast` semantics (D8).
- Tests under `quality/tests/` per acceptance criteria.

**Explicitly NOT touched by this cycle:** `CONF_HVAC_ZONE_ENTRY_DWELL` and its live surfaces (P5). Card separately.

---

## Acceptance criteria (discriminating)

### D1/D2 — per-room hold knobs
- **Verify:** Setting `CONF_HVAC_VACANCY_HOLD=300` on one room via `async_step_climate` makes `binary_sensor.<room>_hvac_occupied.attrs.hvac_vacancy_hold_s == 300` **only for that room**; sibling rooms still report their room-type default. Discriminator: a house-wide implementation (the P1 error) would change every room.
- **Verify (blank fall-through):** unset value → attr shows the room-type-table value (60 for bedroom day, 1800 for bedroom night). Discriminator: coercing blank to 0 would show 0 (invalid — 0 is hallway-only).
- **Verify (monotonicity, P10):** form save with `day=600, night=300` returns a form error; form save with `day=600, night=600` succeeds; form save with only night supplied and `night < table[room_type]_day` triggers the resolver's clamp-and-log-once path (not a form error, because day is table-default).
- **Test:** `test_effective_hold_prefers_entry_options_over_room_type_table`; `test_effective_hold_clamps_night_up_to_day`; `test_effective_hold_blank_falls_through_not_zero`.
- **Live:** after restart, options-flow values persist and the attr reflects them.

### D3 — enable-by-default + migration
- **Verify:** For a fresh room entry, `sensor.<room>_hvac_occupied` is present and enabled without operator action.
- **Verify (migration, P6):** for the ~43 existing rooms, after boot with the new version, every pre-existing `binary_sensor.<room>_hvac_occupied` has `disabled_by is None`; the migration flag on the integration entry is set; a second boot does not re-run the migration.
- **Test:** `test_hvac_occupied_registry_migration_one_shot`.

### D4 — established attr
- **Sensor:** `sensor.<room>_hvac_occupied.attrs.established == True` iff `zm.is_zone_hvac_established(zone_id)` returns True for the room's zone. Discriminator: unestablished zones today are silent — post-fix the attr distinguishes them.
- **Test:** `test_hvac_occupied_established_attr_reflects_zone_manager`.

### D5/D6 — retreat_reason at the chokepoint
- **Verify (chokepoint coverage, P2):** After any of the 11 preset-write sites fires, `sensor.ura_hvac_zone_preset_zone_N.attrs.retreat_reason` matches the exact string passed as `reason=` to that call within one HVAC tick. Discriminator: hooking only S1 would leave the other 10 stale — the test suite parametrises across every site.
- **Verify (vocabulary completeness, P4):** every literal `reason=` string across the 11 sites is a member of `HVAC_PRESET_REASONS`. A mutation test that introduces a new reason string not in the frozenset FAILS.
- **Verify (restart-safe S1 scope, P3):** stop HA with zone in S1-emitted `runtime_exceeded`, restart → sensor still reports `retreat_reason == "runtime_exceeded"`. Stop HA with a zone whose last write came from `hvac_excursion.py:667`, restart → sensor reports `unknown` (NOT a stale wrong value) until the next write on that zone; discriminator distinguishes the scoped-restart-safety from silent-wrong.
- **Test:** `test_reason_captured_at_chokepoint_for_every_site` (parametrised over the 11 sites); `test_reason_cache_hydrates_s1_only_from_activity_log_at_boot`; `test_non_s1_reason_shows_unknown_after_restart_until_rewrite`.
- **Live:** cross-check three most recent S1 preset changes in DB vs live sensor attrs.

### D7 — coast/shed on the existing Mode sensor
- **Sensor:** `sensor.ura_hvac_coordinator_mode` state (existing) unchanged; `attrs.energy_constraint_mode` already present; **NEW** attrs `energy_constraint_since` (iso) and `energy_constraint_duration_s` (int) match the current-tick delta.
- **Verify (RestoreEntity):** simulate an EC coast transition, restart HA mid-coast, `since` restores to the pre-restart transition timestamp and `duration_s` continues (not reset to 0). If the restored mode differs from the current live mode, `since` resets to now — the sensor never shows a stale `since` for a mode the coordinator is not in.
- **Test:** `test_mode_sensor_energy_constraint_since_and_duration`; `test_mode_sensor_restores_since_when_mode_unchanged`; `test_mode_sensor_resets_since_when_mode_differs`.
- **Live:** during the next TOU peak, observe transition to `coast`; check D5 `retreat_reason=runtime_exceeded` co-occurs on any duty-forced-away zone.

### D8 — documentation-only
- **Verify:** inline comment at `sensor.py:13797` names both surfaces + cites `hvac_override.py:6596/:2028/:3171` and the test file. No behavioral change. `energy_coast` remains truthy under its own semantics.

---

## Gap analysis — verdict: **right-sized after revision**

- Deferred (unchanged): per-zone away-cause rollup; CM-flow for room-type default tables; aggression-posture control; global feature kill-switch.
- Dropped from this plan (P5): D9 `CONF_HVAC_ZONE_ENTRY_DWELL` removal — carded separately.
- Added by revision: strings.json (P9), registry migration (P6), reason vocabulary constant + mutation test (P4), monotonicity clamp+log at the resolver + form validator (P10), F5-leftover cleanup, explicit P3 scope statement.
- Collapsed by revision (P7): new coast sensor → attrs on existing "10 · Mode" sensor.
- Reframed by revision (P8): `energy_coast` supersession → documented distinct semantics.

---

## Restart-safety summary

- **D1/D2:** persisted via `entry.options`. Safe.
- **D3 flip:** entity-registry per-user persisted; safe. **D3 migration:** one-shot flag on the integration entry; safe and idempotent.
- **D4 (`established`):** re-derived; safe.
- **D5/D6 (chokepoint reason capture):** cache is transient. Hydration covers the S1 path only (P3 chosen scope). Non-S1 sites show `unknown` until next write on that zone — legibly missing, not silently wrong.
- **D7 (`since`/`duration_s`):** RestoreEntity on the existing "10 · Mode" sensor persists last mode + since ts; resume-if-same, reset-if-different discipline.
- **D8:** doc-only; no state.

---

## Non-goals (explicit, revised)

- Not fixing D5 duty-cycle occupancy-blindness — HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1.
- Not changing `ROOM_TYPE_HVAC_HOLD` tables — Rung-1 review-gated.
- Not building the per-zone away-cause rollup — deferred.
- Not building a CM-flow for room-type default tables — deferred.
- Not touching the reason ladder (`hvac.py:2273-2306`) — this cycle READS reason.
- Not adding a global feature kill-switch.
- **Not removing `CONF_HVAC_ZONE_ENTRY_DWELL` in this cycle** (P5) — separate cycle.
- **Not extending `emit_set_preset_mode` to log a durable `preset_write` row on every success** (P3) — separate cycle if operator finds post-restart `unknown` annoying in practice.
- **Not creating a new coast sensor** (P7) — attrs on existing "10 · Mode".
- **Not redirecting or deprecating `sensor.py:13797 energy_coast`** (P8) — distinct semantics documented in place.

---

## Tier justification

**Tier 2, two framing-disjoint reviews:**
- **Reviewer A — correctness + restart-safety:** chokepoint captures reason on success (not just deferral); the 11 sites are all covered by the same hook; `HVAC_PRESET_REASONS` mutation test truly fails on an unlisted new reason; D3 migration is one-shot; D7 RestoreEntity resume-if-same / reset-if-different is implemented (not just persisted).
- **Reviewer B — schema fidelity + prior-art / no-regression:** re-grep every consumer of `_effective_hvac_hold_seconds` for the extended signature (no site skips the override branch — Bug Class #53); reintroduced CONF names match the F5-dropped originals byte-for-byte; F5-leftover cleanup at `hvac_zones.py:524-536` has zero downstream consumers; the two `energy_coast` surfaces are not silently unified; `CONF_HVAC_ZONE_ENTRY_DWELL` and its 8 live surfaces are untouched.

Not elevated to Tier 2-DB: no cross-coordinator ripple, no strategy change, no shared-primitive write. If Reviewer B's re-grep surfaces any hidden consumer of the resolver that bypasses the override branch, elevate.
