# Plan review #1 (COMPLETENESS) — PLANNING_hvac_w1c_thermostat_profiles.md

Reviewer: ura-reviewer, Tier-3 plan review #1 (completeness / independent re-enumeration). Read-only, `develop` @ 30f9981ae, 2026-09-30.
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely first (incl. §10 C1–C29). Nothing below re-asserts a §10 claim.

**Verdict: REVISE.** The inventory the plan calls "exhaustive" misses 1 write site, ~20 manual-string readers, the one ZoneState setpoint producer, the Carrier-freshness reload loop, the existing URA-write ring, and every line number in §A/§C is stale.

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| 1 | HIGH | **Missed write site: boot excursion audit NUDGE preset restore.** It is not in A1–A13. It appears only as a *read* in B4. It is a real `emit_set_preset_mode` write (a named-preset pin), so on Generic/ecobee it is exactly the kind of write the P2 invariant forbids. | `hvac_excursion.py:1177` in `async_startup_excursion_audit` (`:1079`) |
| 2 | HIGH | **B-inventory covers ~8 of ~30 `"manual"` readers.** Missed: the primary override detector in `_handle_climate_change` (into-manual / within-manual / "temp changed but not manual → Ignore"), the preset-window passthrough, the startup-audit stale-override scan, the latch discharge predicate, the D2d S4 snapshot guard, the nudge-restore / cancel paths, the `_auto_return` HIGH-1 skip (C26, live), S1 lockout discharge, and resume-then-pin. On ecobee (`preset_mode` is None, audit L18) the `:3619` branch makes a person's setpoint change **silently ignored**. That is the core W1-C failure, and it lives at a site the plan does not list. The P1 deliverable-4 lint ("no raw `preset_mode == \"manual\"` outside the strategy") will therefore fail against the plan's own scope. | `hvac_override.py:1318, 2571, 2987-2991, 3472, 3568-3619, 4748-4749, 6060-6120`; `hvac_excursion.py:662-686`; `hvac.py:3377`; `hvac_setpoint.py:378/405/409/582` |
| 3 | HIGH | **The single-setpoint producer is missing.** `ZoneState` ingests only `target_temp_high/low`. For ecobee in `cool` these are null (audit L18: `temperature` 76, high/low null), so every downstream reader goes blind: fan temperature logic, cover occupied-close delta, the predict/override setpoint math and the sensor attrs. The plan inventories writes and manual reads but not this ONE producer, which is where a `setpoint_shape` normalisation must land. (Other readers without a single-setpoint row: `hvac_predict.py` has 34 high/low reads and `hvac_override.py` has 41.) | `hvac_zones.py:102-103, 615-616`; consumers `hvac_fans.py:842`, `hvac_covers.py:638-641`, `sensor.py:12844` |
| 4 | HIGH | **`_last_sent` extension changes semantics. The plan's non-goal says it will not.** `_record_sent` REPLACES the whole per-entity dict, so any write clears every verb. Recording `set_temperature` or `set_hvac_mode` would therefore wipe the `set_preset_mode` record that two paths rely on: the S1 no-op (`hvac_strategy.py:189-197`) and the D5 away-edge fallback, a consumer the plan does not list (`hvac.py:4780-4784` `_zone_away_edge`). That puts the P1 byte-identity invariant at risk. There is a second problem. The plan's REUSE row for Generic person-change (D4) uses `_last_sent`, which holds last-value-only and is **lost on every call for a registry miss** (Generic is returned uncached, `:257-258`). The existing mechanism is the 4-deep URA setpoint ring `recent_ura_setpoints`, and the plan does not cite it. That is a prior-art miss that would produce a duplicate record (Bug Class #63 risk). | `hvac_strategy.py:146-152, 254-258`; `hvac_setpoint.py:71-102`; `hvac_const.py:530` `ARRESTER_URA_WRITE_RING_DEPTH` |
| 5 | HIGH | **Carrier freshness / reload loop is not in the inventory.** `_check_carrier_freshness` runs every cycle over ALL zones' climate entities, regardless of platform. A stale non-Carrier zone would try to reload `ha_carrier`, or raise the "found 0 ha_carrier entries … ambiguous entry" NM (House 2 has no ha_carrier). §F lists only the constants and config fields, not this consumer. It must be profile-gated. | `hvac.py:2166`, `:7339-7420`, `:7640-7660` |
| 6 | MEDIUM | **Every §A/§C line number is stale** (copied from state-of-play, not "verified on develop today"). The actual locations are: A1 `hvac.py:3638`, A2 `:2591`, A13 `:4131`; A3 `hvac_override.py:4515`, A4 `:4712/4783`, A5 `:5128/5250/5289/5403`, A6 `:5735`, A7 `:6017/6040/6087` (three calls: the INFO-1 person-restore at `:6017` is a distinct path), A8 `:7267/7296`, A9 `:7739/7762`; A10 `hvac_excursion.py:708`; A11 `hvac_predict.py:1106/1131/1440/1784/1870/1887`; A12 `hvac_egress.py:721/827/848`; C1 `hvac_override.py:224`, C2 `:264`. | grep `emit_set_*` |
| 7 | MEDIUM | **Optimizer write path to climate is omitted.** `OPTIMIZER_ALLOWED_DOMAINS_DEVICE` includes `climate` (L2+ actuation). It is a dynamic-domain path, so the P1 AST lint on literal `"climate"` cannot see it. State-of-play §4.2 lists it, but the plan's A table does not. | `const.py:3692-3694`; state-of-play §4.2 `optimization.py` |
| 8 | MEDIUM | **Timing inventory §C is incomplete.** Carrier-tuned values the plan does not list: `HVAC_FAST_PATH_MIN_INTERVAL_S` 60 / `_MAX_WRITES_PER_ZONE_PER_HOUR` 6 / `_MAX_RUNS…` 30 (commented as a Carrier cloud call-rate bound), `AC_NUDGE_RESTORE_SETTLE_DELAY_S` 180 (late cloud-poll clobber), `OVERRIDE_RECONNECT_GRACE_S` 30 (Carrier cloud-flap), `AC_RESET_OUTCOME_*_SETTLE_S` 60/150 (kW actuation lag), `EXCURSION_LEASE_SLACK_S` 30, `LAST_SENT_TOLERANCE_F` 0.5, `ARRESTER_URA_WRITE_RING_DEPTH` 4. There is also no `retry_interval` constant in `hvac_setpoint.py` to back C6, so C6 is unanchored. | `hvac_const.py:530, 669, 755-804, 1053-1067`; `hvac_excursion.py:74`; `hvac_strategy.py:53` |
| 9 | MEDIUM | **Carrier-only attribute in immune-hold sunset is not inventoried.** `next_activity_time` parsing ("Bryant/Carrier") drives the immune-hold sunset. B3 names TAO/immune only generically. On ecobee the attribute is absent, so the sunset silently degrades to the 4 h cap. | `hvac_override.py:694-700, 4052-4064` |
| 10 | MEDIUM | **D4 relies on a comfort table that does not exist.** It says "setpoint write matching the target preset's numbers from the operator's per-zone comfort table already used for Carrier presets". No such per-zone table exists: Carrier preset setpoints live on the thermostat. The closest are the house-scope seasonal baselines `CONF_HVAC_BASELINE_{SEASON}_{HOME,SLEEP}_COOL`, which are not per-zone and have no away/heat. This is a REUSE claim without a source, and Open Question 2 only half-covers it. | `hvac_const.py:1166-1215` |
| 11 | MEDIUM | **The new ecobee write verbs are ungoverned.** `select.select_option` and `button.press` go outside the `climate` domain, so three things do not cover them: the W1-A funnel/`climate_write` ledger, the AST completeness lint, and the AI-rule refusal (`coordinator.py:1127`, climate only). P3's acceptance criterion ("3 `climate_write` rows, verb `select.select_option`") needs a funnel extension that is not a deliverable. Resolving the `…_clear_hold` / `…_current_mode` siblings by slug suffix (D5) contradicts registry-resolution discipline: they should be resolved via the climate entity's `device_id`. | `hvac_setpoint.py` funnels; `coordinator.py:1122-1135` |
| 12 | LOW | CPR §14 hand-off item 1 (brand-scope `S10_PRESET_RANGE_MIN_INTERVAL_S` / `_MIN_SPACING_S` / `_SWITCH_RESOLUTION_TIMEOUT_S`) is not carried. These constants do not exist in code yet, so the plan should record that it inherits the item. | `PLANNING_hvac_enable_custom_preset_ranges.md:965-972` |
| 13 | LOW | **ZoneState / S1 on a preset-less entity is not traced.** `preset_mode` is None on ecobee, so `hold_preset` returns `FAILED no_presets_supported` every tick. The plan's D4 "hold_preset falls back to setpoints" changes existing Generic semantics (today the *caller* is told to fall back, and S1 at `hvac.py:3656-3661` treats FAILED as non-applied). That flip needs its own row. | `hvac_strategy.py:184-186`; `hvac.py:3648-3661` |

## Ecobee-HomeKit semantics vs `AUDIT_house2_ecobee_inspection_2026_09_30.md`
- The plan matches the audit on these points: modes off/heat/cool/heat_cool, no `preset_modes`, a single setpoint in cool, the select home/sleep/away, Clear Hold, and no equipment telemetry.
- The plan's person-change design depends on the select, but the audit shows the select's state as `unknown`. D0 must gate on the select being readable, and the plan should state what classification applies while it is `unknown`.
- B1 on ecobee is ambiguous. The enforcer's job is to *force* `heat_cool`, and the live ecobee sits in `cool`. "B1 gated on live mode" does not say whether URA ever moves the ecobee into `heat_cool`, and that choice decides whether the P3 invariant ("no high/low while mode ≠ heat_cool") is ever exercised. This is flagged for reviewer #2's lane.
- Humidity target / `fan_modes`: URA writes neither (grep shows no climate `set_fan_mode` / `set_humidity`), so they are out of scope. The plan should say so.

## Parked-plan triggers
- No parked deliverable elsewhere names ecobee, Nest, generic or per-brand except the card itself (`kanban.data.yaml:1975`, trigger already fired) and the CPR §14 hand-off (finding 12).
- `HVAC-WRITE-CONFIRMATION-ORACLE-1` (parked) is brand-specific in substance: it asks which feed confirms a write. The plan should record that W1-C does not fire it, or fold it into a profile capability.

## Must-fix before build dispatch
Findings 1–5 (HIGH): add the missed write site, the full manual-reader list, the ZoneState single-setpoint producer, the `_last_sent` / ring reconciliation (including the `_zone_away_edge` consumer), and the Carrier freshness gate to the inventory, with P1/P2 deliverables. Refresh all line numbers (6). Findings 7–11 should be resolved in the plan text.

---

## REV 2 re-review (2026-09-30)

**Verdict: REVISE.** Two new HIGHs, both introduced by REV 2's own fixes. Every original finding is otherwise closed.

### Verification of findings 1–13
| # | Status | Evidence |
|---|---|---|
| 1 | CLOSED | A14 = `hvac_excursion.py:1177` (plan L96) |
| 2 | CLOSED | §B has 14 rows. I re-ran the grep with a wider pattern (single quotes, `in (...)`, `!=`). The only extra hits are `hvac_override.py:188`, which is inside B14's classifier, and comment lines at `:376, 2513, 5104, 5344, 5348` and `hvac_egress.py:679`. No thermostat-manual code site is missing. `hvac_fans.py:712` and the `triggered_by="manual"` calls are unrelated. |
| 3 | CLOSED | §G, P2 |
| 4 | PARTIAL | Records are now kept per verb and `_last_sent` is not extended to new verbs, which is correct. `_zone_away_edge` is covered in §J. The ring reuse, however, created new finding R2-1 below. |
| 5 | CLOSED | §H, P2 |
| 6 | CLOSED | Spot-checked 10 line numbers against my greps: A1 3638, A2 2591, A3 4515, A5 ×4, A7 ×3, A10 708, A12 ×3, A13 4131, C1 224, C2 264. All correct. |
| 7 | CLOSED | A15 |
| 8 | CLOSED, with a LOW | C6–C12 are added. C7 and C8 cite `hvac_const.py:755-804`, but the actual lines are `:677` (`OVERRIDE_RECONNECT_GRACE_S`) and `:942/:954` (`AC_RESET_OUTCOME_*`). |
| 9 | CLOSED | §I |
| 10 | NOT CLOSED | See R2-2 below. |
| 11 | CLOSED | Ecobee select/button writes now go through a second funnel exception with ledger `verb="{domain}.{service}"`. The lint and the AI-rule refusal are both extended. Siblings are resolved via `device_id` (P3 item 5). |
| 12 | CLOSED | CPR hand-off is carried. `HVAC-WRITE-CONFIRMATION-ORACLE-1` is folded in as `has_write_confirmation_feed`. |
| 13 | CLOSED | The `GenericStrategy.hold_preset` change is now explicit (changelog L15). |

### New findings introduced by REV 2
| # | Sev | Finding | Evidence |
|---|---|---|---|
| R2-1 | HIGH | **Widening the ring entry to `(low, high, single)` silently breaks Carrier echo matching.** Both ring consumers unpack exactly two values, `e_low, e_high = entry`, inside `except (TypeError, ValueError): continue`. A 3-tuple raises ValueError, so every URA write is skipped and the classifier returns `MANUAL_CHANGE_HUMAN`. URA's own echoes would then be booked as human (the pre-v5.103.17 false-override and lockout class), with no exception raised. This also breaks the P1 byte-identity invariant. **Repro:** a Carrier nudge writes 70/78, the echo arrives 20 s later (after the 15 s temp suppression has expired) as manual 70/78, the ring holds `(70.0, 78.0, None)`, the unpack fails and the echo is classified HUMAN. The plan must name both unpack sites and the boot seed, or keep a separate single-setpoint ring. | `hvac_override.py:205`, `:4232`; seed `hvac.py:6075-6084`; producer `hvac_setpoint.py:86-89, 486` |
| R2-1b | MEDIUM | **The new `person_change_match_window_s` window has no timestamp to measure against.** Ring entries carry no time; the ring is depth-4 only. The plan must add a timestamp to each entry, which also changes the arity (same hazard as R2-1), or drop the window. "Carrier default 900 s" changes today's pure depth-4 semantics, so it is not byte-identical. | `hvac_setpoint.py:86-89`; plan L29, L189, L231 |
| R2-2 | HIGH | **Fabricated REUSE again, for the ecobee hold fallback.** `CONF_HVAC_ZONE_<STATE>_HIGH/LOW` does not exist anywhere in the code. The per-zone fields that do exist are the DPM ranges `CONF_ZONE_DYNAMIC_PRESET_{COOL,MILD,HOT,EXTREME}_{HOME,SLEEP}_{LOW,HIGH}`. They are weather-bucketed, cover HOME and SLEEP only (no AWAY), and are owned by CPR. The P3 fallback "Home/Sleep/Away" therefore has no Away source, and REV 2's "No fabricated REUSE" claim (L16) is false. The plan should cite the real constants, rule on the Away source and bucket selection, or mark this as BUILD. | `energy_const.py:657-666+`; plan L16, L305 |
| R2-3 | LOW | Plan L161 says `_last_sent` "must NOT gain cross-verb clearing". It already has it: `_record_sent` replaces the whole per-entity dict (`hvac_strategy.py:149`). This is harmless while only one verb is recorded. The plan should state "keep current behaviour; single verb", or a builder may "fix" it. | `hvac_strategy.py:146-149` |

### Must-fix before build
R2-1 (name the unpack sites and the boot seed, or use a separate ring), R2-2 (real constants plus an Away/bucket ruling, or BUILD). Also fix R2-1b and the C7/C8 line numbers.

---

## REV 3 final pass (2026-09-30)

**Verdict: READY.** One MEDIUM and two LOW edits remain. They are text-only and can be folded in at build dispatch without another review round.

| Check | Result | Evidence |
|---|---|---|
| Pair-ring untouched; its readers and boot seed named correctly | PASS | `hvac_override.py:205` and `:4232` unpack pairs; boot seed `hvac.py:6075-6084`; producer `hvac_setpoint.py:86-89` / `:486`. REV 3 keeps entries as `(low, high)`, and timestamps plus the window go only on the new ring (N4, R2-1b). |
| New names do not collide with existing ones | PASS | No existing code matches `recent_ura_single*`, `*select*` rings, `ECOBEE_*`, `_URA_SELECT*` or `_URA_SINGLE*`. |
| Ecobee holds with no dependence on config fields that don't exist | PASS | `CONF_HVAC_ZONE_*` appears only inside the banner's "premise was wrong" note. Ecobee holds go through `select.<x>_current_mode`; a true-Generic profile gets `feature_unavailable("hold")` plus a Repair (L208, L333). |
| C7/C8 line numbers | PASS | `hvac_const.py:677`, `:942`, `:954` |
| N1 suppression call sites exist at the cited lines | PASS for all 19 cited | All 19 are verified `suppress(` calls. |

### Remaining (non-blocking)
| # | Sev | Item | Evidence |
|---|---|---|---|
| R3-1 | MEDIUM | **N1's suppression list is incomplete.** It is missing 3 of the 22 `suppress(` calls: `hvac_override.py:7294` (S8 cancel-nudge preset), `:7734` and `:7761` (S9 boot ramp audit). The suppression store is now in the P1 byte-identity equality set, so the builder needs the full list. The golden test would probably catch the gap, but the list is likely to be used as the scope. | grep `(\_override_arrester\|self)\.suppress\(` across `domain_coordinators/*.py` |
| R3-2 | LOW | The N4 line "Boot seed updated in the same P2 commit" is ambiguous. It should say that a NEW seed is added for the single-setpoint ring and that the pair seed `hvac.py:6075-6084` is not modified. | plan L10 |
| R3-3 | LOW | The plan names the accessor two ways: `recent_ura_single_setpoints` (L10) and `recent_ura_single_setpoints_for` (L261). Pick one. | plan L10, L261 |
