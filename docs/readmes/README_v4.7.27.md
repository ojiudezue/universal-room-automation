# URA v4.7.27 — Part 2: EC/HVAC Options-Writeback Retrofit

**Release date:** 2026-06-07
**Tier:** Tier 2-DB (operator-elevated — three parallel framing-disjoint staff-engineer
reviews: A = data integrity + DB-architecture preservation; B = migration correctness +
signal-chain integrity; C = new surfaces + test-fixture authority — plus live validation).
**Scope:** Extends the v4.7.26 Coordinator-Manager (CM) reload-suppression mechanism from
its initial 5 keys to **37 keys**, and completes the persistence-model flip for the
remaining CM runtime-tunable Number entities: drop `RestoreEntity`, make `entry.options`
the sole source of truth, and route each edit through the CM update-listener's in-place
apply instead of a full multi-coordinator reload. ROOM and ZONE_MANAGER entries are
unchanged. No DB schema change (options-only persistence).

**Files:**
- `custom_components/universal_room_automation/__init__.py` (dispatch tables
  `_HVAC_TUNABLE_DISPATCH` / `_EC_SETTER_DISPATCH` / `_OFFPEAK_DRAIN_QUALITY` /
  `_NO_LIVE_ATTR_KEYS`; `OPTIONS_RELOAD_SUPPRESS_KEYS` 5→37; `_apply_in_place` dispatch)
- `custom_components/universal_room_automation/number.py` (drop RestoreEntity from the EC
  family, Routine base class, `_HVACTunableNumber` factory + Bayesian; add options
  write-back; B-MED-2 one-shot unsub guard)
- `custom_components/universal_room_automation/const.py` (`CONF_BAYESIAN_CELL_STALENESS_DAYS`
  promoted to a shared `Final`)
- `custom_components/universal_room_automation/domain_coordinators/regime_detector.py`
  (C-LOW-1 docstring refresh — options is now sole source)
- `quality/tests/test_part2_ec_hc_writeback.py` (NEW)
- `docs/planning/PLANNING_part2_ec_hc_options_writeback_retrofit.md`
- `docs/planning/BACKLOG_part2_cross_field_invariants_unenforced.md`
- `docs/planning/BACKLOG_part2_d4_per_zone_kwh_threshold_persistence.md`
- `docs/reviews/code-review/part2_ec_hc_writeback_tier2db.md`

---

## Trigger

v4.7.26 (Cycle 1) shipped CM reload-suppression for only the 5 HVAC presence-timer + DPM
dwell keys. Every *other* runtime-tunable CM Number (the 14 HVAC tunables, the 9 Energy
Coordinator knobs, the 4 Routine-awareness knobs, the Bayesian cell-staleness, the
fan-interference hold, DPM hysteresis, and the 2 egress thresholds) still:

1. **Used the legacy URA Mirror Pattern** (`RestoreEntity`-backed `_value`, no write-back
   to `entry.options`) — so a consumer reading `entry.options` saw only the install-time
   seed, and a reload could stomp the live slider value back to seed.
2. **Fell through to a full CM `async_reload`** on edit — the same expensive
   teardown/re-setup of presence / HVAC / energy / safety / diagnostics / house_state /
   signals coordinators that Cycle 1 was built to avoid, plus the `state_changed` burst
   that aggravates the iOS websocket backpressure banner.

---

## Headline Changes

- **Allowlist 5 → 37 keys.** `OPTIONS_RELOAD_SUPPRESS_KEYS` now covers the full set of
  CM runtime-tunable keys. Editing any one does an in-place live push (or snapshot-advance
  for re-read-each-tick keys) instead of reloading the CM entry. Mixed / non-allowlisted
  changes still reload (legacy behavior, untracked-task fallback preserved from B-CRIT-1).
- **Three dispatch tables as single source of truth** (allowlist membership AND
  `_apply_in_place` dispatch stay in lockstep):
  - `_HVAC_TUNABLE_DISPATCH` (14) — `setattr(hvac.<sub_controller>, runtime_field, cast)`.
  - `_EC_SETTER_DISPATCH` (5) — calls EC `set_*()` methods (carry threshold-ladder
    side-effects a raw setattr would skip).
  - `_OFFPEAK_DRAIN_QUALITY` (4) — `set_offpeak_drain(quality, value)`.
  - `_NO_LIVE_ATTR_KEYS` (7) — consumer re-reads options / live entity-state each tick; no
    push needed.
- **RestoreEntity dropped** from the EC Number family, the Routine Number base class, the
  `_HVACTunableNumber` factory, and Bayesian — `entry.options` is sole source of truth;
  each Number `__init__` re-seeds `self._value` from `{**entry.data, **entry.options}`.
- **`CONF_BAYESIAN_CELL_STALENESS_DAYS`** promoted from a bare string to a shared
  `const.py` `Final` (byte-identical value preserved — it's the options key + entity
  unique_id).

## Blast radius

All 37 keys are **CM-entry options** (not per-room config). Coordinators whose knobs are
covered: **HVAC** (cover / predictor / fan / override-arrester sub-controllers + egress
manager + 4 presence timers), **Energy Coordinator** (5 setters + 4-step off-peak drain
ladder), **DPM** (dwell + hysteresis), **Routine Awareness** (regime_detector +
notification_manager), **Presence** (Bayesian next-room), and the **fan-interference**
path. Every edit funnels through the single CM update-listener.

---

## Review

3 parallel framing-disjoint reviews: **0 CRIT, 0 HIGH, 2 MED, 5 LOW**. All MED + 3 LOW
fixed in-cycle; 2 micro-inefficiency LOWs deferred. Detail:
`docs/reviews/code-review/part2_ec_hc_writeback_tier2db.md`.

- **B-MED-1** — None-guard `hvac.egress_manager` in `_apply_in_place` (teardown-race deref).
- **B-MED-2** — one-shot unsub guard in the HVAC-tunable factory's deferred-retry path.
- **B-LOW-3 / C-LOW-1 / A-LOW-1** — Bayesian `Final` promotion + docstring/comment refresh.

Pre-deploy gate: conflict-markers clean, `py_compile` OK, **98 cycle tests pass**, suite
baseline-diff vs `pre-review-part2-ec-hc` shows no new failures.

---

## Live Validation — Validated 2026-06-07

Run against the restarted live house (HACS-installed v4.7.27 active;
`update.universal_room_automation_update` installed_version = `v4.7.27`). One
representative key was exercised per dispatch family; the no-reload invariant was
proven by **sibling `last_changed`**: a full CM reload re-creates every Number and
re-stamps all siblings, so a sibling holding its boot timestamp through an edit
proves no reload occurred. (URA's file logger sits at WARNING, so the INFO
`in-place apply, suppressing reload` line is not in `home-assistant.log`; the
sibling-timestamp invariant is the authoritative live signal and is strictly
stronger than the log line.)

| # | Criterion | Result | Observed evidence |
|---|-----------|--------|-------------------|
| 1 | HVAC-tunable edit → in-place, no reload | **PASS** | `number.ura_hvac_coordinator_ac_nudge_size` 1.5→2.0: target re-stamped `last_changed` 14:31:49Z; sibling `…_ac_nudge_duration` held boot `14:30:13.574907Z` (no re-setup). |
| 2 | Energy-Coordinator setter edit → no reload | **PASS** | `number.ura_energy_coordinator_resume_ev_at_battery_soc` (excess_solar_soc) 95→90 applied; EC-family witness `…_off_peak_drain_good` held boot `14:30:13.573711Z`. |
| 3 | Off-peak drain edit → no reload | **PASS** | `number.ura_energy_coordinator_off_peak_drain_excellent` 10→12 applied; same EC-family witness held its boot timestamp. |
| 4 | `_NO_LIVE_ATTR_KEYS` edit → snapshot advance + consumer reads new value | **PASS** | `number.ura_coordinator_manager_regime_baseline_window_days` 56→49: entity state refreshed to 49 (`async_write_ha_state`); `regime_detector._window_days` reads live entity-state (hardcoded 56/14 fallback) so the consumer sees 49. Global HVAC witness held boot timestamp → no reload. |
| 5 | Non-allowlisted CM key → full `async_reload` still fires (regression guard) | **PASS (in-suite + inherited)** | Not triggerable via `number.set_value` — every runtime Number is now allowlisted, so a non-allowlisted change requires the options/config flow. Asserted by cycle tests (mixed/non-allowlisted → fall-through reload); the reload path is unchanged legacy behavior that was live-validated in v4.7.26 (Cycle 1). |
| 6 | Restart → Numbers restore last-set values from `entry.options` (no revert to seed) — RestoreEntity removal safe | **PASS** | After a clean restart, all four edited keys came back at their SET values, none reverted to seed: nudge_size 2.0 (seed 1.5), resume-EV 90 (seed 95), off-peak-excellent 12 (seed 10), regime-baseline 49 (seed 56). 4 representative keys spanning all 4 families; the 37 share one `{**entry.data, **entry.options}` re-seed in each Number `__init__`. |
| 7 | No URA ERROR logs attributable to this cycle within an hour of restart | **PASS** | Only 2 URA ERRORs in the window, both the pre-existing census-snapshot/DB-write-worker startup race (`Failed to log census snapshot: DB write worker not running`), identical pair at boot, no recurrence. Unrelated to options-writeback (this cycle touches neither census nor the DB worker). Zero in-place-apply / restore / reload errors. |

**Boot transient seen and dismissed:** the 2 census-snapshot ERRORs are a known
startup-ordering race (census snapshot fires before `start_write_worker()`),
pre-existing and orthogonal to this cycle.

**Proven in-suite rather than live (criterion 5):** the non-allowlisted →
full-reload fall-through can't be reached through a Number entity now that all 37
runtime keys are allowlisted; it is covered by the cycle tests and was live-proven
in v4.7.26.

Test tunables were returned to their pre-validation values (1.5 / 95 / 10 / 56)
after the run, so the live house is unchanged by this validation.
