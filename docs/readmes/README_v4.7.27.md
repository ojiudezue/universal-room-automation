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

## Live Validation (prospective — to be confirmed post-restart)

- **Live:** Edit ONE HVAC-tunable Number (e.g. AC nudge size) via the UI. Confirm an INFO
  log `CM in-place apply` naming only that key, and NO CM coordinator re-setup
  (sibling Numbers keep their boot `last_changed`). No full reload.
- **Live:** Edit ONE Energy Coordinator Number (e.g. fill-priority SOC). Confirm the EC
  setter side-effect ran (in-place apply INFO names the key; value reflected on the live
  coordinator attr) and no reload.
- **Live:** Edit ONE off-peak drain knob. Confirm `set_offpeak_drain(quality, value)`
  applied in place, no reload.
- **Live:** Edit ONE `_NO_LIVE_ATTR_KEYS` knob (e.g. regime baseline window). Confirm the
  listener advances the snapshot, the entity state refreshes, and the consumer
  (`regime_detector._window_days`) reads the new value — no reload.
- **Live:** Edit a NON-allowlisted CM key (or a mix). Confirm a full `async_reload` still
  fires (regression guard).
- **Live:** Restart HA. Confirm all 37 Numbers restore their last-set values from
  `entry.options` (no revert to seed), proving RestoreEntity removal is safe.
- **Live:** No URA ERROR logs attributable to this cycle within an hour of restart.
