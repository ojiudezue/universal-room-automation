# v4.6.9 — Dashboard Sensor Sweep (Deferred Sensors)

**Version:** 4.6.9 (planning, 2026-05-23)
**Status:** Ready to build
**Predecessor:** v4.6.8 EC TOU rate reconciliation
**Successor:** v4.7.0 Appliance Coordinator (per `PLANNING_v4.7.x_APPLIANCE_COORDINATOR_v3.md`)
**Effort estimate:** ~12-16h (5 sensors across 4 coordinators; mostly attribute population, no new state machines)
**Priority:** HIGH — directly unblocks the URA PWA v6.0 dashboard from rendering placeholder em-dashes on the Home, Energy, HVAC, Safety, and Security tabs. Predecessor to "big dashboard push" (PWA D11, controls go live).

## Goal

Surface the **5 sensors the URA Dashboard PWA v6.0 currently renders as `—`** because the backend doesn't emit them. After this cycle the Home tab's Routine awareness + Security cards populate, the Energy tab's "URA · recent energy decisions" timeline populates, the HVAC tab's "URA intent" card explains its reasoning, and the Safety tab's events timeline shows recent rows (not just a count).

This is not new feature work — it's **closing the contract** between coordinators that already make these decisions internally and the dashboard that already has the hook wiring to display them.

## Tier classification

**Tier 2 — Feature cycle, NOT Tier 2-DB.**

- Does NOT touch `database.py` DAO definitions (all 5 sensors read in-memory coordinator state).
- Does NOT migrate ≥3 callers to a new DAO.
- Does NOT change payload shape of persisted events.
- Does NOT add behavioral test infra against real schemas.

Standard Tier 2: two parallel reviewers with different framings (per CLAUDE.md):
- **Reviewer A — correctness + sensor populator coverage + Bug #29 (every status branch has a populator).** Walks each new sensor's state machine; verifies `extra_state_attributes` shape stability matches the published PWA hook contract.
- **Reviewer B — async/lifecycle + Bug #19 (untracked tasks) + Bug #22 (StrEnum) + observation-mode gating + PWA contract flatness.** No nested-dict-of-nested-dict in attrs; ISO 8601 strings; no Decimal; no `"—"`/`"N/A"` as state value.

## PWA hook contract

Same contract as v4.7.x v3 plan §"Dashboard Hooks". Repo: `~/Code/ura-dashboard-pwa/`. Hook layer: `src/data/useUraSensor.ts`. Every sensor below specifies the consuming hook.

---

## Deliverables (5)

### D1: `sensor.ura_presence_coordinator_next_state` — Routine awareness next-state prediction

**What:** Surface the Routine Awareness coordinator's next-state prediction + confidence as a first-class sensor. The model (introduced in v4.6.0 Routine Awareness) already computes predicted next house state; D1 only emits.

**Files:** `domain_coordinators/regime_detector.py` (likely owns the model output), `sensor.py` (registration), `coordinator_telemetry_const.py` (entity key constant).

**Sensor:**
- **Entity ID:** `sensor.ura_presence_coordinator_next_state`
- **State:** predicted house state — one of `home_day | home_night | away | sleep | guest | vacation | unknown`
- **Hook:** `useUraSensorState`
- **Attributes:**
  - `confidence: float` (0.0–1.0)
  - `predicted_at_iso: str` (ISO 8601, UTC)
  - `model: str` (model id / version, e.g. `routine_v1`)
  - `current_state: str` (current house state, for cross-check)
  - `transition_eta_minutes: int | null` (estimated minutes until transition; null if unknown)

**Bug-class prevention:** #22 (StrEnum for state vocabulary), #29 (populator covers null model output), #14 (config staleness — model parameters re-read on options change).

**Acceptance:**
- **Verify:** Sensor exists post-restart; reports current model's best guess.
- **Sensor:** `extra_state_attributes.confidence` parses via `useUraSensorAttrs<{confidence: number, predicted_at_iso: string, model: string, current_state: string, transition_eta_minutes: number | null}>`.
- **Test:** `test_next_state_populator_with_high_confidence`, `test_next_state_populator_with_null_model_output`, `test_next_state_attrs_shape_flat`, `test_predicted_at_iso_is_utc_serializable`.
- **Live:** PWA Home tab's "Routine awareness" card shows next state + confidence within 1 HA-WebSocket tick after sensor write.

### D2: `sensor.ura_security_coordinator_aggregator` — Locks + cameras roll-up

**What:** Single sensor that rolls up the user's HA `lock.*` + `camera.*` entities into a security overview. Security coordinator already tracks per-device state for its policy decisions; D2 exposes the aggregate.

**Files:** `domain_coordinators/security.py`, `sensor.py`, `coordinator_telemetry_const.py`.

**Sensor:**
- **Entity ID:** `sensor.ura_security_coordinator_aggregator`
- **State:** overall status — `armed | disarmed | partial | alert` (computed from per-device states + observation-mode flag)
- **Hook:** `useUraSensorState`
- **Attributes:**
  - `locks_total: int`
  - `locks_locked: int`
  - `locks_unlocked: int`
  - `locks_jammed: int` (sum of jammed/unknown)
  - `cameras_total: int`
  - `cameras_streaming: int`
  - `cameras_idle: int`
  - `cameras_offline: int`
  - `last_state_change_iso: str` (most recent lock or camera state change)

**Bug-class prevention:** #22 (StrEnum for overall status), #29, #23 (observation-mode gates dispatch; sensor still computes regardless).

**Acceptance:**
- **Verify:** With current install (N locks, M cameras), sensor reports correct counts; toggling a lock updates within 1 tick.
- **Sensor:** Flat attrs, all ints + one ISO string. PWA `useUraSensorAttrs<SecurityAggregatorAttrs>` parses cleanly.
- **Test:** `test_aggregator_with_all_locks_locked_all_cameras_streaming`, `test_aggregator_with_jammed_lock_reports_alert`, `test_aggregator_with_no_locks_no_cameras_reports_disarmed`, `test_aggregator_attrs_shape_flat`.
- **Live:** PWA Home tab's "Security" card shows real lock/camera counts + status badge.

### D3: `sensor.ura_energy_coordinator_recent_decisions` — Decision stream timeline

**What:** Emit the Energy Coordinator's most-recent N decisions as a sensor attribute (state = count). Energy coordinator already logs decisions to `anomaly_log` and to internal in-memory ring buffers; D3 surfaces the ring as an entity.

**Files:** `domain_coordinators/energy.py`, `sensor.py`, `coordinator_telemetry_const.py`.

**Sensor:**
- **Entity ID:** `sensor.ura_energy_coordinator_recent_decisions`
- **State:** number of decisions emitted in the last 24h (int)
- **Hook:** `useUraSensorInt` (state) + `useUraSensorAttrs<RecentDecisionsAttrs>` (attrs)
- **Attributes:**
  - `decisions: list[{ timestamp_iso: str, action: str, reason: str, tou_period: str, target_entity: str | null }]` — last 20 decisions, newest first
  - `last_action_at_iso: str | null` (most recent decision's timestamp, or null if buffer empty)

**Bug-class prevention:** #29 (populator covers empty buffer), #25 (cap list at 20 — bounded), #22 (StrEnum `tou_period`).

**Acceptance:**
- **Verify:** Sensor populates within 1 tick of any EC decision; old entries roll off at 20.
- **Sensor:** `decisions` attribute is `list[dict]` with stable keys; each entry's `timestamp_iso` is ISO 8601 UTC.
- **Test:** `test_recent_decisions_empty_buffer_reports_zero`, `test_recent_decisions_caps_at_20`, `test_recent_decisions_attrs_shape_flat`, `test_recent_decisions_timestamp_iso_utc`.
- **Live:** PWA Energy tab's "URA · recent energy decisions" timeline shows the most recent 20 decisions with timestamps.

### D4: HVAC pre-cool/pre-heat attribute enrichment

**What:** The existing `sensor.ura_hvac_coordinator_hvac_pre_cool_likelihood` (and pre_heat equivalent if present) already returns a percentage state. D4 enriches its `extra_state_attributes` with the **why**: solar forecast peak, outside-temp delta forecast, anchor TOU window, prior-day baseline comparison.

**Files:** `domain_coordinators/hvac_predict.py`, `domain_coordinators/hvac.py`, `sensor.py`.

**Sensor (enrichment — existing entity ID):**
- **Entity ID:** `sensor.ura_hvac_coordinator_hvac_pre_cool_likelihood` (existing)
- **State:** unchanged (likelihood %)
- **Hook:** `useUraSensorInt` + `useUraSensorAttrs<HvacIntentAttrs>` (attrs enriched)
- **Attributes (NEW or expanded):**
  - `forecast_peak_outside_f: float | null` — peak outside temp forecast for today, °F
  - `forecast_peak_time_iso: str | null` — when peak hits, ISO 8601
  - `anchor_period: str` — TOU period the pre-action is anchored to (`peak | mid_peak`)
  - `anchor_starts_in_minutes: int | null`
  - `solar_intent: str | null` — `harvest | export | passthrough | unknown`
  - `prior_day_at_this_hour_f: float | null` — baseline comparison datum

**Bug-class prevention:** #11 (timezone — all timestamps UTC), #22 (anchor_period StrEnum), #8 (forecast dict guards).

**Acceptance:**
- **Verify:** Attributes populate when forecast available; null when forecast stale/missing.
- **Sensor:** Flat attrs; no Decimal; null where data missing (not `"—"` / `"unknown"` strings).
- **Test:** `test_intent_attrs_when_forecast_present`, `test_intent_attrs_when_forecast_stale_returns_nulls`, `test_intent_attrs_shape_flat`.
- **Live:** PWA HVAC tab's "URA intent" card shows pre-cool likelihood AND the reasoning (forecast peak temp + time + anchor period). The "Solar/forecast intent surfacing deferred" comment is removed from the PWA in a follow-up.

### D5: `sensor.ura_safety_coordinator_recent_events` — Activity row aggregator

**What:** Existing `sensor.ura_safety_coordinator_safety_events_summary` returns a count + `last_event_at`. D5 adds a NEW sensor that returns the actual recent rows so the PWA Safety timeline can render them.

**Files:** `domain_coordinators/safety.py`, `sensor.py`, `coordinator_telemetry_const.py`.

**Sensor:**
- **Entity ID:** `sensor.ura_safety_coordinator_recent_events`
- **State:** count of events in last 24h (int)
- **Hook:** `useUraSensorInt` + `useUraSensorAttrs<RecentEventsAttrs>`
- **Attributes:**
  - `events: list[{ timestamp_iso: str, type: str, room: str | null, severity: str }]` — last 20 events, newest first
  - `last_event_at_iso: str | null` (mirror of existing `last_event_at` but ISO normalized)
  - `severity_breakdown: { info: int, advisory: int, alert: int, critical: int }`

**Bug-class prevention:** #29 (populator with empty + populated buffer), #22 (StrEnum for severity), #25 (cap at 20), #21 (datetime parse from DB via `parse_datetime`).

**Acceptance:**
- **Verify:** Sensor populates from existing safety-coordinator event tracking; rows reflect the last 24h.
- **Sensor:** `events` is `list[dict]` with stable keys; flat shape; severity is a known string.
- **Test:** `test_recent_events_empty_returns_zero_state`, `test_recent_events_caps_at_20`, `test_recent_events_severity_breakdown_sums_match`, `test_recent_events_attrs_shape_flat`.
- **Live:** PWA Safety tab's events row shows real timestamps + types instead of just a count.

---

## Implementation order

```
D1 (Presence) ─┐
D2 (Security) ─┤
D3 (Energy)   ─┼─ parallelizable; touch different files; ship as one v4.6.9
D4 (HVAC)     ─┤
D5 (Safety)   ─┘
```

Build order within each deliverable: const → coordinator method → sensor entity → tests. Run pytest after each deliverable to catch cross-impacts early.

## Ship plan

Single deploy: **v4.6.9** with all 5 sensors. Don't fragment — the PWA renders them all on the Home, Energy, HVAC, Safety tabs simultaneously, so a partial ship leaves cosmetic gaps the user already finds annoying.

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| PWA contract drift — attribute key rename breaks PWA tabs | MEDIUM | Published table above is canonical; PWA tab port (separate cycle) reads exactly these keys |
| Routine Awareness model output volatility — confidence swings degrade UX | LOW | D1 sensor reflects whatever model produces; if swings are bad that's a v4.7+ model fix, not a sensor problem |
| Decision-stream buffer growth past 20 — memory creep | LOW | Hard cap in coordinator; bounded list-of-dicts |
| Safety events row data shape from `safety_events_summary` differs from what `recent_events` should emit | LOW | D5 reads from coordinator's in-memory event tracker, NOT from the summary sensor. Source-of-truth = coordinator state |

## Live-validation checklist

After v4.6.9 deploy + PWA reload:

1. Home tab → "Routine awareness" card shows non-`—` next state + confidence value.
2. Home tab → "Security" card shows non-`—` lock count + camera count + status badge color.
3. Energy tab → "URA · recent energy decisions" timeline has ≥ 1 row (or `last_action_at_iso: null` if today has no decisions yet — still not a `—`).
4. HVAC tab → "URA intent" card shows pre-cool likelihood AND a forecast peak / anchor reason line.
5. Safety tab → events row count matches `safety_events_summary` AND shows recent row timestamps.
6. Playwright binding-audit (`scripts/playwright-binding-audit.mjs` in PWA repo) reports the 5 corresponding labels as LIVE (not DASH).
7. `pytest quality/tests/` passes; Tier 2 review docs filed per cycle.

## Out of scope (v4.6.9)

- PWA-side controls wiring (D11 — `useCallService` in tabs). Separate cycle.
- Solcast forecast wiring (v4.7.x forecaster — referenced in Energy tab's "Solar — solcast vs actual" card; pre-existing deferral).
- Activity log full row stream from DB (D5 reads coordinator in-memory tracking; full DB stream is a future "diagnostic stream" cycle).
- Refactor of existing `safety_events_summary` — that sensor stays; D5 adds the recent-events sensor alongside.

## References

- `PLANNING_v4.7.x_APPLIANCE_COORDINATOR_v3.md` §"Dashboard Hooks" — same PWA hook contract pattern
- `~/Code/ura-dashboard-pwa/src/data/useUraSensor.ts` — hook contract
- `~/Code/ura-dashboard-pwa/src/components/tabs/Home.tsx:670, 692` — deferred-sensor markers consumed by D1, D2
- `~/Code/ura-dashboard-pwa/src/components/tabs/Energy.tsx:494` — D3 consumer
- `~/Code/ura-dashboard-pwa/src/components/tabs/HVAC.tsx:365` — D4 consumer
- `~/Code/ura-dashboard-pwa/src/components/tabs/Safety.tsx:402` — D5 consumer
- `docs/QUALITY_CONTEXT.md` v7.2 — bug-class taxonomy
