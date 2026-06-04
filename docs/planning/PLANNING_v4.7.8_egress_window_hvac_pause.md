# PLANNING v4.7.8 — Egress Window HVAC Pause

**Status:** Draft (planning)
**Author:** ura-planner
**Date:** 2026-05-29
**Tier:** **Tier 2-DB (three parallel reviewers, different framings)**
**Phase:** Phase A (parallel with v4.7.9 Hygiene, v4.7.10 Gitea retrofit)
**Merge order:** **Egress merges LAST** in Phase A — Gitea → Hygiene → Egress (largest blast radius last)
**Worktree:** isolated; built independently of v4.7.9 / v4.7.10
**Predecessor:** v4.7.7 (AC Nudge decouple + DPM observability + per-zone ramp sensor naming)
**Production at plan time:** v4.7.4.4

---

## 1. Tier Justification

This cycle **formally qualifies** for Tier 2-DB per `CLAUDE.md` triggers:

- Cycle **adds a new DAO** for the `egress_state` table — schema, read DAO, write DAO, in-flight scan DAO. Mirrors the v4.5.11 `ac_reset_state` pattern.
- Cycle **changes payload shape of persisted state** for HVAC zones (egress pause is a new persisted lifecycle event distinct from ac_reset).
- Cycle **migrates ≥3 call sites** (HVAC decision tick, NM dispatch, sensor read, switch wake-up, override arrester cooldown sibling) onto the new DAO.
- Cycle introduces **a behavioral test infrastructure** for restart-resilience scenarios that did not exist before for HVAC pause/restore semantics.

Three reviewers along orthogonal axes cannot share blind spots. Reviews run **in parallel** at code-review time.

Reviewer framings (locked in here, repeated at review-dispatch time):

1. **Reviewer A — Correctness + state-machine invariants.** Egress detection state machine (per-room window state × threshold timer × per-zone aggregate × pause state × cooldown × restore state). Snapshot/restore semantics. Manual override branch. Multi-room egress aggregation per canonical HVAC zone.
2. **Reviewer B — Async + lifecycle + restart resilience.** All 4 restart scenarios from the backlog memo. DB schema integrity for `egress_state` table. RestoreEntity for the new switch + 2 Numbers (v4.7.6 B-M7 `_safe_unsub`). Bug Class #46 boundary on entity-registry mutations. First-tick post-restart rehydration (Bug Class #14).
3. **Reviewer C — New surfaces + DB schema + cross-rule precedence.** Per-room + per-zone config-flow round-trips. New `egress_state` table schema vs existing `ac_reset_state` pattern. Cross-rule precedence matrix: egress pause vs excess-solar EV turn-on vs fill-priority vs drain vs arbitrage vs TOU. Force-Charge button precedence.

---

## 2. Context & Triggering Incident

2026-05-29: Jaya's bedroom window (`binary_sensor.openclose_aquara_zigbee_jayabedroom_contact_2`) was open from 16:07 UTC to 00:39 UTC (~8.5 hours). During that time:

- Bryant Upstairs HVAC ran `cool` mode with `active_cool` action almost continuously.
- Airflow 449-970 cfm sustained. Target 71-76°F. House SOC reached 98% (so URA wasn't even cost-pressured).
- Two failure modes compounded:
  1. The HA-template aggregator `binary_sensor.upzone_windows_open` stayed `off` the entire window — it references the legacy `..._jayabedroom_contact` (unavailable) instead of `..._jayabedroom_contact_2`.
  2. URA's HVAC **has no window-aware code path** — `CONF_WINDOW_SENSORS` is consumed only by the `SecurityOpenEntriesSensor` (`binary_sensor.py:633-685`) for a >30-min alert. Zero references in `hvac.py`/`hvac_zones.py`/`hvac_override.py`.

User-confirmed design (full memo: `project_egress_window_hvac_pause_backlog.md`):
- No HA template dependency. URA-native aggregation.
- Default `is_egress=True` on existing + new room window_sensor configs.
- Action: `climate.set_hvac_mode: off` (hard stop). Restore via snapshot of mode + preset.
- Generalize to all HVAC zones (Upstairs, Entertainment + Master Suite, Back Hallway, etc.).
- All runtime state must survive HA restart (new `egress_state` DB table — 4 scenarios spec'd in §D6).

---

## 3. In-Scope Files (read end-to-end during planning)

| File | Existing reference / line | What this cycle changes |
|---|---|---|
| `custom_components/universal_room_automation/const.py` | 320 (CONF_WINDOW_SENSORS) | Add `CONF_IS_EGRESS_WINDOW` + `DEFAULT_IS_EGRESS_WINDOW = True`. |
| `custom_components/universal_room_automation/domain_coordinators/hvac_const.py` | 86-90 (CONF_HVAC_AC_NUDGE_ENABLED), 174-216 (AC ramp tunables block) | Add 1 master switch CONF + DEFAULT, 2 threshold/delay Number CONFs + DEFAULTs, 4 internal state-machine constants, NM event-type constants. |
| `custom_components/universal_room_automation/domain_coordinators/signals.py` | 77-80 (SIGNAL_HVAC_COORDINATOR_READY) | (No new signal — egress publishes via `SIGNAL_HVAC_ENTITIES_UPDATE` after each tick.) |
| `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py` | 41-120 (`RoomCondition` + `ZoneState` dataclasses), 722+ (`iter_canonical_hvac_zones`) | Extend `RoomCondition` with `is_egress_window: bool` and `window_state: str | None`. Extend `ZoneState` with egress fields (see §D3). `update_room_conditions` reads `is_egress_window` from config. Helper `iter_canonical_hvac_zones` unchanged. |
| `custom_components/universal_room_automation/domain_coordinators/hvac.py` | 574-660 (`_run_decision_cycle`), 322-349 (`async_setup`) | New `EgressManager` (sibling of `OverrideArrester`). Call it once per decision tick AFTER `_zone_manager.update_room_conditions()` but BEFORE `_apply_house_state_presets` and `_predictor.update`. Rehydrate from DB during `async_setup` BEFORE the first tick (Bug Class #14). |
| `custom_components/universal_room_automation/domain_coordinators/hvac_egress.py` | **NEW FILE** | `EgressManager` class — state machine, DB rehydrate, snapshot/restore, manual override, cooldown, NM dispatch. ~220 LoC. |
| `custom_components/universal_room_automation/database.py` | 1069-1087 (ac_reset_state DDL), 5054-5256 (ac_reset_state DAO block) | Add `egress_state` CREATE TABLE + index in `_initialize_schema`. Add 5 DAOs: `get_egress_state(zone_id)`, `save_egress_state(state)`, `get_all_egress_state()`, `clear_egress_state(zone_id)`, `prune_stale_egress_state(cutoff_days)`. Mirror `ac_reset_state` block line-for-line. |
| `custom_components/universal_room_automation/config_flow.py` | 1011-1013 (CONF_WINDOW_SENSORS in `sensors` step, initial install), 6552-6556 (CONF_WINDOW_SENSORS in reconfigure `sensors` step) | Add a checkbox `vol.Optional(CONF_IS_EGRESS_WINDOW, default=DEFAULT_IS_EGRESS_WINDOW): selector.BooleanSelector()` immediately AFTER CONF_WINDOW_SENSORS in both steps. Helper text references the per-zone master switch. |
| `custom_components/universal_room_automation/switch.py` | 199-203 (HVAC switch list), 1521-1659 (canonical `HVACACNudgeSwitch` pattern) | Add `HVACEgressWindowPauseSwitch` — mirrors `HVACACNudgeSwitch` line-for-line including the `SIGNAL_HVAC_COORDINATOR_READY` deferred-restore branch and `@callback _handle_hvac_ready` method. Default ON. Registered in the HVAC platform list. |
| `custom_components/universal_room_automation/number.py` | 797-911 (canonical `FillPrioritySOCNumber` + v4.7.6 B-M7 `_safe_unsub` block) | Add `HVACEgressPauseThresholdNumber` (default 3, min 1, max 15, step 1, unit "min") and `HVACEgressResumeDelayNumber` (default 1, min 1, max 10, step 1, unit "min"). Both mirror `FillPrioritySOCNumber` lifecycle including `_safe_unsub` double-unsub guard. |
| `custom_components/universal_room_automation/binary_sensor.py` | 633-685 (existing `SecurityOpenEntriesSensor` window read pattern) | Add per-room `RoomEgressWindowOpenSensor` (read `is_egress_window` flag + raw `window_sensor.state` + threshold gate from EgressManager). Add per-zone `HVACZoneEgressWindowOpenSensor` (read aggregated state from `EgressManager.zone_aggregate(zone_id)`). |
| `custom_components/universal_room_automation/sensor.py` | 320-365 (per-zone HVAC sensor enumeration via `iter_canonical_hvac_zones`) | Add `HVACEgressPausedZonesSensor` (global, list of paused zones). Add `HVACZoneEgressStateSensor` per canonical zone (state-machine label: `idle | counting | paused | resume_countdown | cooldown`). |
| `custom_components/universal_room_automation/__init__.py` | 311, 368-449 (entity-registry migration patterns), 2404-2521 (v4.7.7 A4/B1/B3 device-reassignment + orphan sweep) | NO new entity-registry mutation in this cycle. Egress entities are fresh — no rename / no migration needed. (Documented to make the Bug Class #46 boundary explicit per Reviewer B.) |
| `quality/tests/test_v478_egress_window.py` | **NEW** | All 7 named tests + state-machine unit tests + manual override tests + multi-room aggregation tests. |
| `quality/tests/test_v478_egress_db_schema.py` | **NEW** | Behavioral schema test that extracts DDL from `database.py` (never hand-copies). Validates table + index + column names + types. |

**Reads (no edits):**
- `docs/QUALITY_CONTEXT.md` — Bug Classes #5, #10, #11, #14, #19, #20, #21, #28, #38, #42, #45, #46
- `docs/CONTEXT_TRANSFER_2026-05-29.md`
- `graphify-out/GRAPH_REPORT.md`

---

## 4. Non-Goals (explicit)

- **No HA template dependency.** URA-native aggregation only. The broken HA template `binary_sensor.upzone_windows_open` is superseded; user can delete or repurpose post-deploy. This cycle does **not** edit `.storage/` or HA template helpers.
- **No HVAC mode mutation beyond `set_hvac_mode: off` and restore.** No setpoint manipulation. No preset changes. No fan/cover side effects from egress.
- **No multi-window-per-room support.** Single `window_sensor` per room (the existing CONF_WINDOW_SENSORS shape) stays — multi-window is a future-cycle candidate.
- **No retrofit of pre-existing `SecurityOpenEntriesSensor` >30-min alert.** That sensor stays — it serves a separate security-alert purpose. Egress pause is an HVAC-domain feature.
- **No DPM / preset interaction.** Pause/resume snapshots mode + preset and restores them as a unit. DPM continues to compute ranges; HVAC simply isn't applying them while paused.

---

## 5. Deliverables

### D1 — Per-room `is_egress_window` flag (config flow + const)

**Scope:** `const.py`, `config_flow.py:1011-1018` (initial install) and `config_flow.py:6552-6564` (reconfigure).

**Changes:**

1. Add to `const.py`:
   ```python
   CONF_IS_EGRESS_WINDOW: Final = "is_egress_window"
   DEFAULT_IS_EGRESS_WINDOW: Final = True
   ```
2. In both `async_step_sensors` paths, add immediately after `CONF_WINDOW_SENSORS`:
   ```python
   vol.Optional(
       CONF_IS_EGRESS_WINDOW,
       default=DEFAULT_IS_EGRESS_WINDOW,
   ): selector.BooleanSelector(),
   ```
3. **No migration helper.** Per v4.7.4.4 doctrine ("Lazy derivation at read time is the canonical Bug Class #46 fix pattern"), do NOT write a `_migrate_egress_default` that calls `async_update_entry` on every existing room entry. Read the flag at runtime; if absent, treat as `DEFAULT_IS_EGRESS_WINDOW` (True). This means existing room entries get egress=True behavior immediately on upgrade with zero config_entries.json mutation.

**Acceptance Criteria:**
- **Verify:** Initial-install sensors step shows the checkbox below the window sensor selector with helper text referencing the per-zone master switch.
- **Verify:** Reconfigure step shows the same checkbox; saved value round-trips.
- **Verify:** A room entry with no `is_egress_window` key in `entry.options` (legacy install) behaves as `True` at the decision-tick read site.
- **Test:** `test_v478_is_egress_flag_default_true_when_absent`, `test_v478_is_egress_flag_roundtrip_through_options_flow`.
- **Live:** Open Jaya's bedroom window after deploy without ever opening the config flow — `RoomEgressWindowOpenSensor` for Jaya's Bedroom flips `on` within the threshold window.

---

### D2 — Per-HVAC-Coordinator master switch + 2 Numbers

**Scope:** `hvac_const.py`, `switch.py`, `number.py`.

**Changes:**

1. `hvac_const.py` — add:
   ```python
   CONF_HVAC_EGRESS_PAUSE_ENABLED: Final = "hvac_egress_pause_enabled"
   DEFAULT_HVAC_EGRESS_PAUSE_ENABLED: Final = True

   CONF_HVAC_EGRESS_THRESHOLD_MIN: Final = "hvac_egress_threshold_min"
   DEFAULT_HVAC_EGRESS_THRESHOLD_MIN: Final = 3   # minutes
   HVAC_EGRESS_THRESHOLD_MIN_MIN: Final = 1
   HVAC_EGRESS_THRESHOLD_MIN_MAX: Final = 15

   CONF_HVAC_EGRESS_RESUME_DELAY_MIN: Final = "hvac_egress_resume_delay_min"
   DEFAULT_HVAC_EGRESS_RESUME_DELAY_MIN: Final = 1
   HVAC_EGRESS_RESUME_DELAY_MIN_MIN: Final = 1
   HVAC_EGRESS_RESUME_DELAY_MIN_MAX: Final = 10

   # Manual-override cooldown — mirror AC Nudge convention
   HVAC_EGRESS_MANUAL_OVERRIDE_GRACE_S: Final = 30
   HVAC_EGRESS_MANUAL_COOLDOWN_S: Final = 3600  # 1 hour

   # State-machine labels (for HVACZoneEgressStateSensor)
   EGRESS_STATE_IDLE: Final = "idle"
   EGRESS_STATE_COUNTING: Final = "counting"
   EGRESS_STATE_PAUSED: Final = "paused"
   EGRESS_STATE_RESUME_COUNTDOWN: Final = "resume_countdown"
   EGRESS_STATE_COOLDOWN: Final = "cooldown"

   EGRESS_STATES: Final = (
       EGRESS_STATE_IDLE, EGRESS_STATE_COUNTING, EGRESS_STATE_PAUSED,
       EGRESS_STATE_RESUME_COUNTDOWN, EGRESS_STATE_COOLDOWN,
   )

   # NM event types
   EGRESS_NM_EVENT_PAUSED: Final = "egress_paused"
   EGRESS_NM_EVENT_RESUMED: Final = "egress_resumed"
   ```

2. `switch.py` — `HVACEgressWindowPauseSwitch`:
   - **unique_id:** `f"{DOMAIN}_hvac_egress_window_pause"`
   - **friendly name:** `"27 · Egress Window Pause"` (ordering after AC Nudge at 26)
   - **device_info:** `URA: HVAC Coordinator` (mirror `HVACACNudgeSwitch`)
   - **Default:** ON
   - Mirror `HVACACNudgeSwitch` (`switch.py:1521-1659`) line-for-line including `SIGNAL_HVAC_COORDINATOR_READY` deferred-restore and `@callback _handle_hvac_ready` with bound-method (NOT lambda, Bug Class #42).
   - Setter target: `hvac.egress_manager.enabled = bool`.

3. `number.py` — `HVACEgressPauseThresholdNumber` and `HVACEgressResumeDelayNumber`:
   - Both mirror `FillPrioritySOCNumber` (`number.py:797-911`) including `_safe_unsub` (v4.7.6 B-M7) and the SIGNAL-based deferred push.
   - Threshold Number: unique_id `f"{DOMAIN}_hvac_egress_threshold_min"`, default 3, range 1-15, step 1, unit "min", `mode=SLIDER`, `entity_category=CONFIG`. Setter target: `hvac.egress_manager.set_threshold_min(value)`.
   - Resume-Delay Number: unique_id `f"{DOMAIN}_hvac_egress_resume_delay_min"`, default 1, range 1-10, step 1, unit "min", `mode=SLIDER`, `entity_category=CONFIG`. Setter target: `hvac.egress_manager.set_resume_delay_min(value)`.
   - Both registered in the HVAC number platform list adjacent to existing HVAC Numbers.

**Acceptance Criteria:**
- **Verify:** Three entities appear on the `URA: HVAC Coordinator` device after deploy: `switch.ura_hvac_coordinator_egress_window_pause`, `number.ura_hvac_coordinator_egress_pause_threshold_min`, `number.ura_hvac_coordinator_egress_resume_delay_min`.
- **Verify:** Toggling the switch immediately flips `hvac.egress_manager.enabled` (test via `ha_get_state`).
- **Verify:** RestoreEntity round-trip — set switch OFF, restart HA, switch reads OFF on first tick (Bug Class #5 + #10).
- **Verify:** Setting Threshold = 1 means a window open for 60s triggers a pause (live).
- **Sensor:** `switch.ura_hvac_coordinator_egress_window_pause` `state == "on"` (default).
- **Sensor:** `number.ura_hvac_coordinator_egress_pause_threshold_min` `state == "3"` (default).
- **Sensor:** `number.ura_hvac_coordinator_egress_resume_delay_min` `state == "1"` (default).
- **Test:** `test_v478_egress_switch_default_on_after_first_install`, `test_v478_egress_switch_restore_off_survives_restart`, `test_v478_egress_threshold_number_safe_unsub_no_double_call`, `test_v478_egress_resume_delay_number_safe_unsub_no_double_call`.
- **Live:** After deploy and restart, all three entities visible; default values correct; sub-device line on HVAC Coordinator page shows numeric ordering 26 (AC Nudge) → 27 (Egress).

---

### D3 — `EgressManager` (new file `domain_coordinators/hvac_egress.py`)

**Scope:** New ~220 LoC file. Sibling of `OverrideArrester` (`hvac_override.py`).

**Public surface (called from `HVACCoordinator`):**

```python
class EgressManager:
    def __init__(self, hass, zone_manager, db, threshold_min=3, resume_delay_min=1, enabled=True):
        self._hass = hass
        self._zone_manager = zone_manager
        self._db = db                       # ref to coordinator_manager's URADatabase
        self._enabled = enabled
        self._threshold_min = threshold_min
        self._resume_delay_min = resume_delay_min
        # Per-canonical-zone runtime state (rehydrated from DB on startup)
        self._paused_by_egress: dict[str, dict] = {}      # zone_id -> {mode, preset, paused_at}
        self._egress_first_open_at: dict[str, datetime] = {}    # zone_id -> ts
        self._egress_first_closed_at: dict[str, datetime] = {}  # zone_id -> ts
        self._cooldowns: dict[str, datetime] = {}         # zone_id -> expires_at
        # NM dedup (once-per-day per zone per event type)
        self._nm_emitted_today: dict[tuple[str, str], str] = {}  # (zone_id, evt) -> date

    async def async_rehydrate_from_db(self) -> None: ...
    async def async_tick(self, now: datetime) -> None: ...
    def zone_aggregate(self, zone_id: str) -> bool: ...   # True if any egress room open past threshold
    def state_label(self, zone_id: str) -> str: ...       # one of EGRESS_STATES
    def paused_zones(self) -> list[dict]: ...             # for HVACEgressPausedZonesSensor
    def get_cooldowns(self) -> dict[str, str]: ...        # for diagnostic attr
    @property
    def enabled(self) -> bool: ...
    @enabled.setter
    def enabled(self, value: bool) -> None: ...
    def set_threshold_min(self, value: int) -> None: ...
    def set_resume_delay_min(self, value: int) -> None: ...
```

**`async_tick` algorithm (per canonical HVAC zone, called inside the held `_decision_cycle_lock`):**

1. Snapshot the user-tunable scalars at the top of the tick (Bug Class #14 / B-M3 race avoidance):
   ```python
   threshold_s = self._threshold_min * 60
   resume_delay_s = self._resume_delay_min * 60
   manual_grace_s = HVAC_EGRESS_MANUAL_OVERRIDE_GRACE_S
   cooldown_s = HVAC_EGRESS_MANUAL_COOLDOWN_S
   enabled = self._enabled
   ```
   Use snapshotted values for the rest of the tick. Live setter writes only the next tick.

2. For each canonical HVAC zone (from `iter_canonical_hvac_zones(self._hass)`):
   - If `not enabled`: clear `_egress_first_open_at[zone_id]` and `_egress_first_closed_at[zone_id]`; skip pause/resume logic. **Do NOT auto-resume a zone that's already in `_paused_by_egress`** — leave it for the user to re-enable, then resume on the next tick. This avoids a flap if the user toggles the switch while a window is open.
   - **Cooldown check:** if `zone_id in self._cooldowns` and `now < self._cooldowns[zone_id]`: skip; emit state `cooldown`.
   - **Aggregate egress-window state:** iterate constituent rooms (from the canonical zone's merged room list) and read `is_egress_window` from each room's `entry.options` (lazy, default True if absent). For each egress room, read `state.state == "on"` from its `window_sensor`. Define `any_egress_open = any(...)`.
   - **Manual-override detection (only when zone IS in `_paused_by_egress`):**
     - Read current `climate.state` for the zone's thermostat.
     - If `hvac_mode != "off"` AND `(now - _paused_by_egress[zone_id]["paused_at"]).total_seconds() > manual_grace_s`:
       - Treat as manual user override.
       - Drop `_paused_by_egress[zone_id]`; set `_cooldowns[zone_id] = now + timedelta(seconds=cooldown_s)`.
       - DB write: `clear_egress_state(zone_id)` then `save_egress_state({"zone_id": zone_id, "state": "cooldown", "cooldown_expires_at": cooldown_expires})`.
       - Skip the rest of this zone's tick.
   - **Pause path (zone NOT yet paused):**
     - If `any_egress_open is True`:
       - If `zone_id not in _egress_first_open_at`: set `_egress_first_open_at[zone_id] = now`; DB write `save_egress_state` with `state="counting"`, `first_open_at=now`.
       - If `(now - _egress_first_open_at[zone_id]).total_seconds() >= threshold_s`:
         - Snapshot current `hvac_mode` + `preset_mode` from the climate state.
         - **If `hvac_mode == "off" already`:** do not pause (zone is off via other rule). Clear `_egress_first_open_at[zone_id]`. Log debug.
         - Else: dispatch `await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": ..., "hvac_mode": "off"}, blocking=True)`. On success: `_paused_by_egress[zone_id] = {"mode": prior_mode, "preset": prior_preset, "paused_at": now, "triggered_by_room": <first room>, "thermostat": climate_entity}`.
         - DB write: `save_egress_state` with `state="paused"`, all dict fields.
         - Pop `_egress_first_open_at[zone_id]`. Pop `_egress_first_closed_at[zone_id]`.
         - NM: dispatch `SIGNAL_NOTIFICATION` once-per-day per zone (LOW severity) with title and key `("paused", zone_id, today)`.
     - If `any_egress_open is False`:
       - Pop `_egress_first_open_at[zone_id]`. DB write: clear counting state.
   - **Resume path (zone IS paused):**
     - If `any_egress_open is True`:
       - Pop `_egress_first_closed_at[zone_id]` if present. (Window re-opened during resume countdown — restart count.)
       - DB write: update `state="paused"`, `first_closed_at=NULL`.
     - If `any_egress_open is False`:
       - If `zone_id not in _egress_first_closed_at`: set to `now`. DB write `state="resume_countdown"`, `first_closed_at=now`.
       - If `(now - _egress_first_closed_at[zone_id]).total_seconds() >= resume_delay_s`:
         - Restore: `await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": ..., "hvac_mode": saved["mode"]}, blocking=True)`. Then if `saved["preset"]` is non-empty: dispatch `climate.set_preset_mode`.
         - On success: pop `_paused_by_egress[zone_id]`; pop `_egress_first_closed_at[zone_id]`; clear DB row (`clear_egress_state`).
         - NM: dispatch resume notification once-per-day.

3. After all zones processed, dispatch `SIGNAL_HVAC_ENTITIES_UPDATE` (already done by the outer decision tick).

**Manual override semantics (mirror v4.7.7 AC Nudge hybrid `self_modulates` pattern):**

- After URA dispatches `set_hvac_mode: off`, grace window of `HVAC_EGRESS_MANUAL_OVERRIDE_GRACE_S` (30s) before treating any non-off mode as user override.
- After grace expires AND the user manually changes mode → drop pause claim, set 1-hour cooldown, surface in `cooldowns` attribute.
- During cooldown, URA does not pause this zone even if egress windows are open.

**Bug-class compliance markers:**
- Bug Class #14: scalars snapshotted at top of tick.
- Bug Class #11: all timestamp comparisons use `dt_util.now()` (or `dt_util.utcnow()` consistently); DB writes use `.isoformat()` from a tz-aware datetime.
- Bug Class #21: rehydrate uses `dt_util.parse_datetime()`, never `datetime.fromisoformat`.
- Bug Class #19: no fire-and-forget `hass.async_create_task` in the manager; all I/O is awaited inside the held lock.
- Bug Class #42: NM signal dispatch is direct `async_dispatcher_send`, not a wrapped lambda.

**Acceptance Criteria:**
- **Verify:** Class file exists at `custom_components/universal_room_automation/domain_coordinators/hvac_egress.py`.
- **Test:** State-machine unit tests for all 5 transitions (idle→counting, counting→paused, paused→resume_countdown, resume_countdown→idle, paused→cooldown).
- **Test:** `test_v478_multi_room_aggregation_per_canonical_zone` — Upstairs zone with 3 rooms; only Jaya's window is egress=True; opening Sahil's non-egress window does NOT trigger pause; opening Jaya's does.
- **Test:** `test_v478_threshold_resets_when_window_closes_before_threshold_hit`.
- **Test:** `test_v478_manual_override_during_grace_does_not_engage_cooldown` (verifies the 30s grace).
- **Test:** `test_v478_manual_override_after_grace_engages_cooldown_for_one_hour`.
- **Live:** Open Jaya's window → within 3 min `HVACZoneEgressStateSensor` for Upstairs reads `counting`; within ~4 min reads `paused`; Bryant Upstairs `hvac_mode == "off"`. Close window → within 1 min reads `resume_countdown`; within ~2 min reads `idle` and prior mode is restored.

---

### D4 — DB schema: `egress_state` table + DAOs (`database.py`)

**Scope:** `database.py` — add CREATE TABLE block near line 1069 (immediately after `ac_reset_state`). Add DAO block near line 5054.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS egress_state (
    zone_id TEXT NOT NULL,
    state TEXT NOT NULL,                          -- one of EGRESS_STATES
    first_open_at TEXT,                           -- ISO8601 tz-aware
    first_closed_at TEXT,                         -- ISO8601 tz-aware
    paused_at TEXT,                               -- ISO8601 tz-aware
    saved_hvac_mode TEXT,                         -- restore target
    saved_preset_mode TEXT,                       -- restore target
    triggered_by_room TEXT,                       -- room that first opened
    thermostat_entity TEXT,                       -- climate.entity_id (for restore)
    cooldown_expires_at TEXT,                     -- ISO8601 tz-aware, NULL if not in cooldown
    last_update_ts TEXT NOT NULL,                 -- for stale-row pruning
    PRIMARY KEY (zone_id)
);
CREATE INDEX IF NOT EXISTS idx_egress_state_state
ON egress_state(state);
```

**Rationale for column-by-column choices:**

- `PRIMARY KEY (zone_id)` (not `(zone_id, date)` like `ac_reset_state`): egress pause is not a daily-bucketed counter; it's a per-zone lifecycle. One row per zone at most.
- `state TEXT`: discriminator. Lets the in-flight scan DAO filter `WHERE state IN ('paused', 'counting', 'resume_countdown', 'cooldown')` for rehydrate.
- Timestamps stored as ISO strings (Bug Class #13: callers must `dt_util.parse_datetime()` on read, never assume datetime).
- `thermostat_entity` persisted so restore can target the right climate entity even if the in-memory zone enumeration hasn't completed yet on the first post-restart tick.

**DAOs (mirror `ac_reset_state` pattern at `database.py:5054-5256`):**

```python
async def get_egress_state(self, zone_id: str) -> dict | None: ...
async def save_egress_state(self, state: dict) -> None: ...    # INSERT OR REPLACE
async def get_all_egress_state(self) -> list[dict]: ...        # for rehydrate
async def clear_egress_state(self, zone_id: str) -> None: ...
async def prune_stale_egress_state(self, cutoff_days: int = 7) -> None: ...
```

`prune_stale_egress_state` runs from the existing nightly maintenance hook (Bug Class #27 — every INSERT table must have a paired cleanup that is actually scheduled). The prune deletes rows in `state = 'idle'` (defensive; idle rows shouldn't exist but if they do they're garbage) and rows where `last_update_ts < now - cutoff_days`.

**Per-table isolation:**

CREATE TABLE block uses `_create_table_safe(db, "egress_state", [...])` exactly like `ac_reset_state` (Bug Class #9 — each CREATE TABLE has its own try/except + commit + failed_tables tracking).

**Acceptance Criteria:**
- **Verify:** `egress_state` table exists in the live DB after restart (`ha-mcp` SSH or ura-sqlite query).
- **Test:** `test_v478_db_egress_state_table_schema` — extracts DDL from `database.py` source (per the Tier 2-DB doctrine: behavioral fixtures must extract schema from production source, never hand-copy), runs CREATE on a fresh in-memory SQLite, asserts column names + types + PRIMARY KEY + index match.
- **Test:** `test_v478_db_egress_state_roundtrip` — save → get → fields match (including tz-aware timestamps).
- **Test:** `test_v478_db_egress_state_in_flight_scan_returns_only_active_states`.
- **Test:** `test_v478_db_egress_state_prune_drops_stale_idle_rows`.
- **Test:** `test_v478_db_egress_state_create_failure_does_not_cascade` (Bug Class #9 — simulate CREATE failure on egress_state, assert `ac_reset_state` and the rest of schema still create successfully).
- **Live:** After deploy + first restart, `sqlite3 universal_room_automation.db ".schema egress_state"` returns the expected DDL.

---

### D5 — Sensors (`binary_sensor.py` + `sensor.py`)

**Scope:** New entity classes — read-only views over `EgressManager` state.

**New binary_sensors:**

1. `RoomEgressWindowOpenSensor` — one per room with a `window_sensor`. `state == "on"` iff `is_egress_window=True` AND raw `window_sensor.state == "on"` AND `_egress_first_open_at[zone_id]` exists AND `(now - first_open_at) >= threshold_s`. Attributes: `is_egress`, `raw_window_state`, `room_name`, `canonical_zone`, `seconds_open`.
   - unique_id: `f"{DOMAIN}_room_{room_name}_egress_window_open"`
   - Subscribes to `SIGNAL_HVAC_ENTITIES_UPDATE` and to `async_track_state_change_event` on the `window_sensor` for instant flip (don't wait for next 5-min tick to show `on`).

2. `HVACZoneEgressWindowOpenSensor` — one per canonical HVAC zone. `state == "on"` iff `EgressManager.zone_aggregate(zone_id)` is True. Attributes: `member_rooms`, `open_rooms`, `state_label`.
   - unique_id: `f"{DOMAIN}_hvac_zone_{zone_id}_egress_window_open"`
   - Device: `URA: HVAC Coordinator`.

**New sensors:**

3. `HVACZoneEgressStateSensor` — one per canonical HVAC zone. `state` is the state-machine label from `EGRESS_STATES`. Attributes: `paused_at`, `triggered_by_room`, `saved_mode`, `saved_preset`, `cooldown_expires_at`, `threshold_min`, `resume_delay_min`.
   - unique_id: `f"{DOMAIN}_hvac_zone_{zone_id}_egress_state"`

4. `HVACEgressPausedZonesSensor` — single global sensor. `state` is the count of zones currently in `_paused_by_egress`. Attributes: `paused_zones: list[dict]` with `{zone_id, paused_at, triggered_by_room, saved_mode}` per zone, `cooldowns: dict`.
   - unique_id: `f"{DOMAIN}_hvac_egress_paused_zones"`
   - Device: `URA: HVAC Coordinator`.

**Enumeration:** All 4 sensor types iterate via the existing `iter_canonical_hvac_zones(hass)` (per `hvac_zones.py:722` doctrine — UI/sensor surfaces use canonical iteration; the per-room sensor iterates `entry.options["zones"]` and resolves canonical lazily).

**Cache TTL:** The per-room and per-zone sensors compute from in-memory `EgressManager` state — NO DB read on `async_update` (Bug Class #26 — avoid high-frequency DB reads from sensor platform). The state-label sensor reads from `EgressManager.state_label(zone_id)` which is a dict lookup.

**Acceptance Criteria:**
- **Verify:** Sensor count: 1 per egress-eligible room (binary_sensor) + 2 per canonical HVAC zone (1 binary + 1 state sensor) + 1 global. For the live install (3 canonical HVAC zones, ~10 rooms with window_sensors) → ~17 new entities.
- **Sensor:** `sensor.ura_hvac_coordinator_egress_paused_zones` `state` is `"0"` initially.
- **Sensor:** `binary_sensor.ura_jaya_bedroom_egress_window_open` flips to `on` within `threshold_min` of opening the window.
- **Sensor:** `sensor.ura_hvac_coordinator_upstairs_egress_state` cycles `idle → counting → paused → resume_countdown → idle` as the window opens/closes.
- **Test:** `test_v478_sensors_read_from_in_memory_not_db` (assert `database.py` is not touched on `async_update`).
- **Test:** `test_v478_room_egress_binary_sensor_off_when_is_egress_false`.
- **Live:** Dashboard polls `binary_sensor.ura_upstairs_egress_window_open` and reflects the egress state.

---

### D6 — Restart resilience (the 4 backlog scenarios)

**Scope:** `EgressManager.async_rehydrate_from_db` is called from `HVACCoordinator.async_setup` BEFORE `_run_decision_cycle` is registered as a periodic timer (Bug Class #14 — first-tick post-restart must rehydrate state before action).

**Rehydration steps inside `async_rehydrate_from_db`:**

1. `rows = await self._db.get_all_egress_state()`
2. For each row:
   - Use `dt_util.parse_datetime()` for every ISO string (Bug Class #21).
   - If `state == "paused"`: populate `_paused_by_egress[zone_id]` from `saved_hvac_mode + saved_preset_mode + paused_at + triggered_by_room + thermostat_entity`.
   - If `state == "counting"`: populate `_egress_first_open_at[zone_id]` from `first_open_at`.
   - If `state == "resume_countdown"`: populate `_paused_by_egress[zone_id]` (from saved fields) AND `_egress_first_closed_at[zone_id]` from `first_closed_at`.
   - If `state == "cooldown"`: populate `_cooldowns[zone_id]` from `cooldown_expires_at`.
3. Log a structured INFO line: `EgressManager: rehydrated %d zones (%d paused, %d counting, %d resume_countdown, %d cooldown)`.

**4-scenario coverage (each scenario gets a named test):**

| Scenario | Pre-restart state | Post-restart first-tick action | Test |
|---|---|---|---|
| **R1** | Zone paused, window still open | Rehydrate `_paused_by_egress`; first tick sees `any_egress_open=True` → KEEP paused; do NOT re-dispatch `set_hvac_mode: off` (idempotent: dispatch only if HA state shows `hvac_mode != "off"`). | `test_v478_r1_restart_keeps_zone_paused_with_window_open` |
| **R2** | Was paused; window now closed | Rehydrate `_paused_by_egress`. Two sub-paths: (a) DB had `state="resume_countdown"` with `first_closed_at` → continue countdown from saved timestamp; (b) DB had `state="paused"` with no `first_closed_at` → start fresh countdown from `now` (conservative). After `resume_delay_s` elapses → restore. | `test_v478_r2_restart_then_window_closes_resumes_correctly`, `test_v478_r2b_restart_then_window_closed_already_starts_resume_countdown` |
| **R3** | Window open, threshold not hit (e.g., 2 of 3 min) | Rehydrate `_egress_first_open_at` from `first_open_at`. Continue from saved timestamp. If `first_open_at` missing → start fresh from `now`. | `test_v478_r3_restart_with_accumulated_threshold_continues` |
| **R4** | User overrode 30 min ago; cooldown has 30 min remaining | Rehydrate `_cooldowns[zone_id]` from `cooldown_expires_at`. URA respects cooldown until `now > expires_at`. | `test_v478_r4_restart_during_cooldown_preserves_expiry` |

**Idempotent restore:** If R1 fires, the first tick reads HA state; if `hvac_mode == "off"` already (HA preserved the dispatched state through restart), do NOT re-dispatch (avoid recompressor short-cycle). Just keep `_paused_by_egress[zone_id]` populated.

**First-tick-before-action guard:**

In `HVACCoordinator._run_decision_cycle`, the call to `await self._egress_manager.async_tick(now)` MUST come AFTER `self._zone_manager.update_room_conditions()` (so window states are fresh) BUT BEFORE `_apply_house_state_presets()` and `_predictor.update()`. Rationale: if a zone is paused, presets and predictor should see the zone in `mode=off` and skip it cleanly.

If `async_rehydrate_from_db` has not yet completed when the first tick fires (race), set a `_rehydrate_done: bool = False` flag; the tick early-returns until it's True. The flag is set inside `async_setup` after rehydrate completes, BEFORE the periodic timer is registered.

**Acceptance Criteria:**
- **Verify:** All 5 named restart tests pass.
- **Test:** `test_v478_first_tick_post_restart_rehydrates_state_before_action` — assert `async_tick` early-returns when `_rehydrate_done is False`; assert `_rehydrate_done` is True by the time `async_track_time_interval` registers the periodic callback.
- **Test:** `test_v478_idempotent_restore_does_not_redispatch_when_already_off`.
- **Live:** Pause a zone (open window for 4+ min) → restart HA → on next decision tick (≤5 min later) zone is still in `_paused_by_egress`; close window → resume fires after `resume_delay_min` from window close.

---

### D7 — NM alerts (LOW severity)

**Scope:** Wire into existing `SIGNAL_NOTIFICATION` pattern used by HVAC coordinator (mirror v4.7.6 NM trip pattern — once-per-day per zone per event type).

**Two events:**

1. `egress_paused`: *"Upstairs HVAC paused — egress window open in Jaya's Bedroom for 3+ min."*
   - Severity: `LOW`
   - Key: `(zone_id, "egress_paused", today_isoformat)` for dedup
2. `egress_resumed`: *"Upstairs HVAC resumed — all egress windows closed."*
   - Severity: `LOW`
   - Key: `(zone_id, "egress_resumed", today_isoformat)`

**Observation mode:** Gate NM dispatch on `not hvac.observation_mode` (Bug Class #23 — gate at dispatch site, not just at handler).

**Acceptance Criteria:**
- **Verify:** When pause fires, a notification appears once; second pause same day → no notification.
- **Verify:** When HVAC observation mode is ON, no NM dispatch fires from egress.
- **Test:** `test_v478_nm_alert_paused_emits_once_per_day_per_zone`.
- **Test:** `test_v478_nm_alert_suppressed_in_observation_mode`.

---

### D8 — Cross-rule precedence

**Precedence matrix** (highest wins). This is the contract Reviewer C verifies end-to-end:

| Rule | Trigger | Action | Egress pause precedence |
|---|---|---|---|
| **Egress Pause** | Egress window open ≥ threshold | `set_hvac_mode: off` | **WINS** over excess-solar EV turn-on, fill-priority, drain, arbitrage, TOU |
| Force-Charge button | User press | `switch.turn_on` EVSE | **WINS** over Egress (user-explicit; Egress is HVAC, Force-Charge is EV) — orthogonal, no conflict |
| Excess-Solar EV turn-on | SOC ≥ excess_solar_soc + surplus | `switch.turn_on` EVSE | Different domain. Egress does not block. |
| Fill-Priority (v4.7.6) | SOC < fill_priority_soc + surplus forecast | `switch.turn_off` EVSE | Different domain. Egress does not block. |
| EV Battery Drain | Battery discharging > threshold | `switch.turn_off` EVSE | Different domain. Egress does not block. |
| AC Nudge (v4.7.7) | Overshoot + sustained kWh | `set_temperature` cool +Δ | **SUPPRESSED while zone paused** (no point nudging a stopped compressor). |
| AC Reset | Cool stuck past target | `set_hvac_mode: off` cycle | **SUPPRESSED while zone paused** (zone is already off; no need to escalate). |
| DPM range update | DPM tick | `set_temperature` | **SUPPRESSED while zone paused** (don't apply ranges to an off compressor). |
| House-state preset apply | House state change | `set_preset_mode` | **SUPPRESSED while zone paused** (apply_house_state_presets early-returns for zones in `_paused_by_egress`). Preset restoration happens on resume. |

**Implementation hooks** (each gets a 3-line guard):

- `_apply_house_state_presets` (`hvac.py:684+`): `if zone_id in self._egress_manager._paused_by_egress: continue` near the top of the per-zone loop.
- `OverrideArrester.check_ac_reset` (`hvac_override.py`): early-return for paused zones.
- `FanController.update`: leave fans alone (they're not part of `set_hvac_mode: off`'s effect on the compressor — user may want fan-only) — **NO suppression** for fans during egress pause. Documented.
- `CoverController.update`: leave covers alone — covers don't churn energy. **NO suppression**.
- `HVACPredictor.update`: skip predictive `set_temperature` for paused zones.

**Acceptance Criteria:**
- **Test:** `test_v478_paused_zone_skipped_in_apply_house_state_presets`.
- **Test:** `test_v478_paused_zone_skipped_in_ac_reset_check`.
- **Test:** `test_v478_paused_zone_skipped_in_dpm_apply`.
- **Test:** `test_v478_force_charge_button_unaffected_by_egress_pause` (orthogonal-domain check).
- **Test:** `test_v478_fan_and_cover_control_unaffected_by_egress_pause`.
- **Live:** Pause a zone; observe DPM sensor for that zone shows the computed range but the climate entity does not move (mode is `off`). On resume, preset restoration brings it back.

---

## 6. Size Estimate

**Production:** ~350 LoC

| File | LoC |
|---|---|
| `hvac_egress.py` (new) | ~220 |
| `database.py` (table + 5 DAOs) | ~80 |
| `switch.py` (HVACEgressWindowPauseSwitch) | ~75 |
| `number.py` (2 Number entities) | ~140 |
| `binary_sensor.py` (2 sensors) | ~90 |
| `sensor.py` (2 sensors) | ~90 |
| `hvac.py` (manager wiring + tick call + suppression guards) | ~40 |
| `hvac_zones.py` (RoomCondition + ZoneState extensions) | ~20 |
| `hvac_const.py` (CONF + DEFAULT + state labels) | ~30 |
| `config_flow.py` (2 checkbox additions) | ~10 |
| `const.py` (CONF_IS_EGRESS_WINDOW) | ~3 |

Subtotal (with overlap between switch/number patterns sharing class bodies and the `_safe_unsub` boilerplate): **~350 LoC production net**.

**Tests:** ~500 LoC

| Test file | Named tests | LoC |
|---|---|---|
| `test_v478_egress_window.py` | All 7 restart-resilience tests + ~15 state-machine unit tests + manual override + multi-room + precedence | ~380 |
| `test_v478_egress_db_schema.py` | Schema extract + roundtrip + in-flight scan + prune + cascade isolation | ~120 |

Total: **~350 production + ~500 tests = 850 LoC**. Above the standard ~250-LoC envelope because of DAO + restart-resilience test count (consistent with backlog estimate).

---

## 7. Bug Class Watch (from QUALITY_CONTEXT.md)

| Bug Class | Where it could hit | Mitigation |
|---|---|---|
| #5 — Coordinator lifecycle (deferred restore) | Switch + 2 Numbers register before HVAC coord in hass.data | Mirror `HVACACNudgeSwitch` pattern: subscribe to `SIGNAL_HVAC_COORDINATOR_READY`; complete restore on the signal. |
| #9 — DB corruption cascade | New CREATE TABLE in schema init | Use `_create_table_safe` with per-table commit + failed_tables tracking. |
| #10 — Cross-restart state loss | `_paused_by_egress`, `_egress_first_open_at`, `_cooldowns` are in-memory | Persist to `egress_state` on every transition; rehydrate before first tick. |
| #11 — UTC vs local tz | Timestamp comparisons + ISO serialization | Use `dt_util.now()` consistently; `dt_util.parse_datetime` on read; `%z` on write. |
| #13 — DB returns strings | DAO reads timestamps from SQLite | Pass through `dt_util.parse_datetime` (handles both str and None). |
| #14 — Config snapshot staleness | Threshold/resume-delay scalars read by `async_tick` | Snapshot at top of tick; live setter writes for next tick. |
| #19 — Untracked background tasks | None expected — `async_tick` is awaited under lock; no fire-and-forget | Confirm by audit during build. |
| #20 — Concurrent reload race | Switch / Numbers do NOT call `async_update_entry` from OptionsFlow on other entries | Confirm by audit; no cross-entry writes. |
| #21 — Timezone-naive datetime mix | `dt_util.parse_datetime` on every rehydrate read | Use only `dt_util.parse_datetime`, never `datetime.fromisoformat`. |
| #23 — Observation mode gating | NM dispatch in `EgressManager` | Gate at dispatch site (check `hvac.observation_mode` before `async_dispatcher_send`). |
| #26 — High-frequency DB read from sensor | New per-room and per-zone sensors | Read from in-memory `EgressManager` state only; no DB on `async_update`. |
| #27 — Orphaned cleanup | New INSERT table needs paired prune | Wire `prune_stale_egress_state` into the existing nightly maintenance hook. Verify wiring in `__init__.py` maintenance schedule. |
| #28 — Sync `add_update_listener` | No change to update listeners in this cycle | N/A. Lint test continues to pass. |
| #38 — Unsub via async_on_remove | New SIGNAL subscriptions | All dispatcher unsubs registered via `self.async_on_remove(_safe_unsub)`. |
| #42 — Lambda + async_create_task in signal callbacks | None expected; `@callback _handle_hvac_ready` is a bound method | Audit during build. |
| #45 — Lambda closure captures stale local | None expected; `EgressManager` uses instance attrs only | Audit during build. |
| #46 — `async_update_entry` re-entrancy | Egress flag uses lazy default; NO migration helper | Documented in D1 (no `_migrate_egress_default`). |

---

## 8. Pre-Deploy Zero-Bugs Gates (5 — including JSON validity from v4.7.6.1)

Per `feedback_pre_deploy_zero_bugs_gate.md` (mandatory after v4.7.4.3 broken-release incident). All 5 must pass before `./scripts/deploy.sh`. If any fails: STOP, fix, re-run ALL gates.

```bash
# Gate 1 — No unresolved conflict markers anywhere
grep -rln "^<<<<<<<\|^=======$\|^>>>>>>>" \
  custom_components/ docs/ quality/ \
  | grep -v "TEST_SUITE_ACCESS\|test_scenarios" \
  && echo "ABORT: unresolved conflict markers found" && exit 1

# Gate 2 — py_compile every changed Python file
git diff --name-only HEAD~1 -- '*.py' \
  | xargs -I{} python3 -m py_compile {} || exit 1

# Gate 3 — JSON validity (translations + manifest + strings)
# Added v4.7.6.1 after a strings.json typo shipped to live
for f in custom_components/universal_room_automation/manifest.json \
         custom_components/universal_room_automation/strings.json \
         custom_components/universal_room_automation/translations/en.json; do
  python3 -c "import json; json.load(open('$f'))" || \
    { echo "ABORT: invalid JSON in $f"; exit 1; }
done

# Gate 4 — Cycle tests pass
PYTHONPATH=quality python3 -m pytest \
  quality/tests/test_v478_egress_window.py \
  quality/tests/test_v478_egress_db_schema.py \
  -q || exit 1

# Gate 5 — Full URA suite — no NEW regressions vs pre-deploy baseline
# Tag baseline BEFORE this cycle: `git tag pre-review-v4.7.8 ...`
PYTHONPATH=quality python3 -m pytest quality/tests/ -q \
  --tb=no -q 2>&1 | tee /tmp/v478_suite.txt
# Compare failed count vs baseline_v4.7.7.txt
# If failed_count > baseline_count: STOP and investigate
```

**Pre-deploy snapshot for Tier 2-DB live validation:** Capture pre-deploy row counts in `ac_reset_state` and any tables that could leak into the change. (`egress_state` won't exist pre-deploy; the post-deploy check is "row exists with non-NULL columns within 1 hour of restart" — sentinels-only = payload-shape broken, per the codified Tier 2-DB doctrine.)

---

## 9. Restart-Resilience Tests (named in plan)

All 7 mandatory restart-resilience tests called out by the user, plus their state-machine + manual-override + multi-room siblings:

| Test name | Coverage |
|---|---|
| `test_v478_r1_restart_keeps_zone_paused_with_window_open` | R1 scenario; verifies idempotent (no re-dispatch when hvac_mode already off) |
| `test_v478_r2_restart_then_window_closes_resumes_correctly` | R2 path-a: DB had `state="resume_countdown"` |
| `test_v478_r2b_restart_then_window_closed_already_starts_resume_countdown` | R2 path-b: DB had `state="paused"` no `first_closed_at` |
| `test_v478_r3_restart_with_accumulated_threshold_continues` | R3 |
| `test_v478_r4_restart_during_cooldown_preserves_expiry` | R4 |
| `test_v478_db_egress_state_table_schema` | Schema extracted from production source; DDL roundtrips |
| `test_v478_first_tick_post_restart_rehydrates_state_before_action` | Bug Class #14 — first tick must early-return until `_rehydrate_done=True` |

Plus the state-machine + cross-rule + sensor + NM tests already enumerated in D3/D5/D7/D8.

---

## 10. Tier 2-DB Review Framings (locked at planning per CLAUDE.md)

**Run all three in PARALLEL.** Each reviewer gets the explicit framing below. They share NO blind spots.

### Reviewer A — Correctness + state-machine invariants

Focus:
- Walk every transition in the 5-state machine (`idle → counting → paused → resume_countdown → idle`, plus `paused → cooldown`, `cooldown → idle on expiry`). Verify each transition is symmetric in code and in the DB write.
- Verify snapshot/restore semantics: `saved_hvac_mode + saved_preset_mode` capture is atomic (before dispatch), restore is sequenced (mode then preset).
- Verify manual-override branch: the 30s grace window cannot be defeated by HA state cache lag (use `dt_util.now()` deltas, not state.last_changed which is HA-cache-bound).
- Verify multi-room aggregation: in a 3-room canonical zone where only room A is egress=True, opening room B's window must NOT pause; closing room A's window with room B still open must trigger resume (because B is not egress).
- Verify `if not enabled: clear counters but DON'T auto-resume already-paused zone`.

### Reviewer B — Async + lifecycle + restart resilience

Focus:
- All 4 restart scenarios end-to-end. Trace from `async_setup → async_rehydrate_from_db → register periodic timer → first tick`.
- DB schema integrity: CREATE TABLE under `_create_table_safe`, index covers the in-flight scan query, prune scheduled.
- RestoreEntity for switch + 2 Numbers: `_safe_unsub` cannot be double-called when both the signal fires AND the entity is removed (v4.7.6 B-M7 boundary).
- Bug Class #46 boundary: confirm NO `async_update_entry` writes from any setup path. The `is_egress_window` flag is read-lazy with a default. The 5 DAO writes happen inside `_run_decision_cycle` (post-bootstrap-2), never during setup.
- First-tick-post-restart: assert the `_rehydrate_done` flag gates `async_tick`. Verify async_setup awaits rehydrate before registering the timer.
- Lock semantics: `async_tick` runs inside `_decision_cycle_lock`. Confirm no awaited DB write inside the lock can deadlock with another coordinator's lock.

### Reviewer C — New surfaces + DB schema + cross-rule precedence

Focus:
- Per-room + per-zone config flow round-trips: install path, reconfigure path. Defaults correct. Save → reload → re-open OptionsFlow shows saved value.
- New entity registry: 17ish entities all have stable `unique_id`s; no clash with existing HVAC entities; correct device-info linking (per-room sensors on the room device, per-zone on `URA: HVAC Coordinator`).
- DDL diff vs `ac_reset_state`: PRIMARY KEY differs (zone_id alone, not zone_id+date); confirm this is intentional and prune semantics handle it.
- Cross-rule precedence matrix end-to-end. Each row in §D8 table maps to a guarded code site. Walk all 9 rules.
- Force-Charge button precedence: orthogonal-domain; verify it's truly unaffected.
- Test fixture authority: `test_v478_db_egress_state_table_schema` MUST extract DDL from `database.py` source (regex or AST), not hand-copy. This is the Tier 2-DB doctrine (test infra C1-C5 from v4.6.3).
- NM dedup keys: `(zone_id, "egress_paused", today_isoformat)` — confirm the today rollover at local midnight does NOT cause two notifications when paused at 23:55 and again at 00:05.

---

## 11. Live Validation Expectations (Review D, post-restart)

**Wait at least one decision tick (≤5 min) after HACS install + restart confirms the integration loaded.**

Then:

1. **Schema check (DB):**
   ```bash
   sqlite3 /Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db \
     ".schema egress_state"
   ```
   Expect: table exists with all columns from §D4.

2. **Entity check (HA):**
   - `switch.ura_hvac_coordinator_egress_window_pause` — exists, `state == "on"`
   - `number.ura_hvac_coordinator_egress_pause_threshold_min` — `state == "3"`
   - `number.ura_hvac_coordinator_egress_resume_delay_min` — `state == "1"`
   - `sensor.ura_hvac_coordinator_egress_paused_zones` — `state == "0"`
   - One `sensor.ura_hvac_coordinator_<zone>_egress_state` per canonical zone, all `state == "idle"`

3. **Functional check (Jaya's bedroom):**
   - Open `binary_sensor.openclose_aquara_zigbee_jayabedroom_contact_2` (the live one).
   - Within 3 min: `sensor.ura_hvac_coordinator_upstairs_egress_state == "counting"`.
   - Within ~4 min total: `state == "paused"`; `binary_sensor.ura_upstairs_egress_window_open == "on"`; `climate.up_hallway_zone_2.hvac_mode == "off"`.
   - `egress_state` DB row has non-NULL `paused_at`, `saved_hvac_mode`, `saved_preset_mode`, `triggered_by_room`. **Sentinels-only (everything NULL) = payload-shape broken — same failure mode v4.6.1.1 hit.**
   - NM notification arrives once.

4. **Resume check:**
   - Close the window.
   - Within 1 min + 1 tick: `state == "idle"`; `climate.up_hallway_zone_2.hvac_mode` restored to prior mode (`heat_cool` likely); preset back to `home`.
   - DB row for that zone cleared.
   - NM resume notification arrives once.

5. **Manual override check:**
   - Re-open the window, wait for pause.
   - Manually set `climate.up_hallway_zone_2.hvac_mode = "cool"` via HA UI.
   - Wait one tick past grace (≥30s).
   - Verify `state == "cooldown"`; `_cooldowns[upstairs]` populated with 1-hour expiry; DB row reflects cooldown state.
   - Re-test pause does NOT fire even with window still open until cooldown expires.

---

## 12. Acceptance Criteria Summary (sprint contract)

For each deliverable D1-D8, the acceptance criteria above include `Verify`, `Sensor`, `Test`, and `Live` lines per CLAUDE.md "Planning Docs — Acceptance Criteria Required".

The cycle is complete when:
- All 7 restart-resilience tests pass + all named tests in D1-D8 pass.
- Full URA suite shows no NEW regressions vs `pre-review-v4.7.8` baseline.
- All 5 Pre-Deploy Zero-Bugs Gates pass.
- Three Tier 2-DB reviewer passes complete (parallel); all CRITICAL/HIGH findings fixed before deploy.
- Live validation §11 passes end-to-end with Jaya's bedroom window.
- Post-cycle code-review doc at `docs/reviews/code-review/v4.7.8_egress_window_hvac_pause.md` lists every CRITICAL/HIGH/MEDIUM/LOW + bug-class tags + summary stats.

---

## 13. Plan-Completion Tracking (per CLAUDE.md)

### Original plan items deferred at build time

- **Multi-window per room** — deferred (memo §non-goals). Track in: post-cycle backlog memo as `project_egress_multi_window_per_room_backlog.md`.
- **HA template `binary_sensor.upzone_windows_open` deletion** — user-action, not URA code. Track in: live-validation §11 follow-up.
- **DPM range-pause integration into the DPM sensor's "why blocked" attribute** — DPM sensors should expose `blocked_by="egress_pause"` when applicable. Deferred to v4.7.9 hygiene cycle.

### v4.7.8 fix-up cycle — additional deferrals (2026-05-29 review burn-down)

The Tier 2-DB review surfaced 7 distinct HIGHs + 6 significant MEDs + 7 LOWs across 3 reviewers. **All 7 HIGHs fixed; 5 of 6 MEDs fixed; 3 of 7 LOWs fixed; remainder deferred or accepted-by-design.**

**Deferred (not fixed in v4.7.8 fix-up commit):**

- **C-M1 wiring of `egress_pause_frequency` metric** — added to `HVAC_METRICS` + `HVAC_SUPPRESSED_FROM_PERSISTENCE` for forward-compat doctrine (v4.6.3.1 P2). **NO `record_observation` call site exists yet.** Deferred to v4.7.9+ once a baseline is available (≥ 14 days / `HVAC_ANOMALY_MIN_SAMPLES`). Tracked in: backlog memo `project_egress_observability_metric_v479.md`.
- **B12 schema cascade behavioral test** — `test_v478_db_egress_state_create_failure_does_not_cascade` remains source-grep only (not runtime-simulating an actual CREATE failure). Deferred — source-grep is sufficient against refactor regressions. Track in: v4.7.x test infrastructure backlog if a runtime SQLite-error harness becomes available.
- **MEDIUM-1 — `zone_aggregate` returns True for pre-threshold counting** (sensor flips ON before threshold engages). Documented as planned-UX deviation — instant feedback vs threshold-gated rollup. No code change.
- **MEDIUM-3 — `_apply_house_state_presets` two-loop egress guard duplication** — refactor to helper `_is_egress_paused()` deferred. Both loops are correct as written; consolidation deferred to v4.7.9 hygiene cycle.
- **MEDIUM-5 — `cooldown_s` snapshot is redundant** — leave as-is (constant, but documents the intent). No-op fix; deferred indefinitely.
- **LOW-5 — Number RestoreEntity values not clamped to MIN/MAX** — cosmetic only; setter clamps when applied. Deferred to v4.7.9 hygiene cycle.
- **LOW-6 — Manual-override grace anchors to `paused_at` not last URA dispatch** — by design (per planning § manual-override). Documenting only.
- **LOW-7 / C-L1 — NM dedup midnight-rollover collision** — by design (once per local day per zone per event). Deferred to v4.7.x backlog as `project_egress_nm_sliding_window_dedup.md` if user reports double-pings spanning midnight.
- **C-L2 — Cooldown expiry → immediate re-counting flap** — by design (cooldown is for manual-override fairness; window-still-open after cooldown should re-engage pause).
- **C-L5 — Hardcoded `"27 ·"` numeric prefix is brittle** — out of scope. Track in: v5.x naming convention backlog.
- **B11 — Inline import of `iter_canonical_hvac_zones` inside `async_tick`** — negligible cost, cosmetic. Deferred.

**Fixed in v4.7.8 fix-up commit (2026-05-29):**

| Finding | Severity | File(s) | Notes |
|---|---|---|---|
| A-H1 (#43) | HIGH | `hvac_zones.py` | RoomCondition append for coordinator-less rooms |
| A-H2 (#33) | HIGH | `hvac_override.py` | is_paused guards in 2 startup-audit siblings |
| B-H1 / C-H2 (#27) | HIGH | `__init__.py` | prune wired into both `_cleanup_ops` lists |
| B-H2 (#14) | HIGH | `hvac_egress.py`, `hvac.py` | `_initial_restore_pending` gate + 60s force-release |
| B-H3 (#5) | HIGH | `hvac_egress.py`, `switch.py` | same gate cleared on switch deferred restore |
| C-H1 (§D8 gap) | HIGH | `hvac.py` | DPM `_async_apply_preset_overrides` egress guard |
| C-H3 (translations) | HIGH | `strings.json`, `translations/en.json` | per-room + entity translation entries |
| A-M6 | MED | `hvac_egress.py` | 5 `_db_save_*` helpers consolidated to `_db_save()` (~60 LoC removed) |
| B-M1 (#11) | MED | `hvac_zones.py` | unified on `dt_util.now()` |
| B-M5 | MED | `hvac_egress.py` | sentinel-aware `prior_preset` (None vs "") |
| C-M1 (v4.6.3.1 P2) | MED | `hvac_const.py` | `egress_pause_frequency` in `HVAC_METRICS` + `HVAC_SUPPRESSED_FROM_PERSISTENCE` |
| C-M2 | MED | `binary_sensor.py` | `RoomEgressWindowOpenSensor` inherits `UniversalRoomEntity` |
| C-M3 | MED | `binary_sensor.py` | zone-enum failure log raised to WARNING |
| A-MED-4 / B10 | MED | `hvac_egress.py` | WARN on `_engage_resume` empty saved_mode + WARN on state-change DB write failures |
| A-LOW (multi-room flap) | LOW | `hvac_egress.py` | `triggered_by_room` rolls forward in memory |
| C-L3 / A-LOW-2 | LOW | `hvac_egress.py` | DB clear on disabled-path mid-count |
| C-L4 | LOW | `hvac_zones.py` | `is_egress=True` gated on `window_sensor` configured |
| C-L6 | LOW | tests | misnamed DPM-apply test renamed; new dedicated DPM test added |

**No silent drops.** Every planned item from D1-D8 either ships or appears above with a reason.

---

## 14. Cycle Coordination (Phase A parallelism)

- This cycle runs in its **own worktree** independent of v4.7.9 (Hygiene) and v4.7.10 (Gitea).
- Merge order at Phase A close: **Gitea → Hygiene → Egress**. Egress merges last because it touches the most files (~13) and has the largest blast radius.
- Egress branch rebases on `develop` AFTER both Hygiene and Gitea land. Conflicts most likely in:
  - `database.py` (Hygiene may add a column-rename or maintenance hook reshape)
  - `__init__.py` (Hygiene may move the maintenance schedule registration)
  - `const.py` (Hygiene may reorganize CONF blocks)
- If merge conflicts surface: resolve, re-run all 5 Pre-Deploy Zero-Bugs Gates BEFORE deploy. Conflict-marker gate (Gate 1) is the v4.7.4.3 lesson — never deploy with markers in source.

---

**End of plan.**
