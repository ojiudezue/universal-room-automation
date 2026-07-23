# PLANNING — Reconcile-on-Return (D2 of Offline-Actuator Visibility + Recovery)

**Status:** DESIGN ONLY — awaiting operator sign-off before build
**Tier (recommended):** **Tier 3** (4 framing-disjoint reviews incl. adversarial-completeness pass D) — see §5 for elevation rationale
**Predecessor:** D1 ("actuator visibility") — SHIPPED. `UnavailableEntitiesSensor` now spans
inputs + actuators with structured `details[]`, `category`, `reason`
(`sensor.py:1623-1730`).
**Backlog entry:** `docs/BACKLOG.md` — "Offline-actuator visibility + recovery (Tier 1 + Tier 2), 2026-06-30"
**Trigger:** AV Closet light didn't auto-on at entry and didn't auto-off at exit because the
Shelly relay was `unavailable` / `restored:true` during the whole occupancy window. When the
relay came back, it stayed stuck in whatever state it had been left in until the next
occupancy event.

---

## Revision — 2026-07-03

A performance / bug-class review triggered by the 2026.7.0 event-loop-load incident
surfaced four gaps in the original design. This revision adds them as first-class
deliverables and elevates the review tier from **Tier 2-DB → Tier 3**. The additions:

1. **Per-room cross-entity coalesce window** guarding the boot-settle release storm
   (v4.7.19 boot-away-actuation-storm shape; June 2026 Optimization-Coordinator
   write-flood precedent). See D2.7 + §3.9.
2. **Explicit zero-DB-writes-per-reconcile invariant** — all telemetry via the existing
   batched activity-log path. See D2.8 + §2 (MUST-NEVER list).
3. **Reconciler-owned unsub list re-registered inside the subscription-rebuild hook**
   (Bug Class #50 hardening). See D2.9 + §3.7 update.
4. **Branch-table completeness / parity test** elevated from review recommendation to a
   MANDATORY gating acceptance criterion (Bug Class #53 self-risk — the resolver is a new
   "consume the desired state" site and a missing cell = silent no-op). See D2.10 + §4
   gate note.

Guard count moves from six (original invariant) to **ten** (see §2). Everything below
remains **DESIGN-ONLY / awaiting operator sign-off** — the additions do NOT imply
approval or build authorization.

## Revision — 2026-07-04

Adds **D2.11 — Flap detector + quarantine**: a chronically flaky actuator (canary: the
AV-closet Shelly1PMGen3, flagged in project memory as flaky hardware) must not burn
reconciles forever and must become a VISIBLE signal, not silent retries. This closes the
gap that the flat per-hour cap (`RECONCILE_MAX_PER_HOUR`, guard 5) leaves open — the cap
throttles but does not surface the problem, and does not stop attempting service calls
against a device that will never stabilize. D2.11 keyed on availability transitions (not
reconciles) so it is MORE sensitive than the 6/hr cap and trips first. See D2.11 + §3.11.
Diagnostic surface extended (§3.5) to add `reason: "flapping"` on the D1 sensor. Guard
count moves from ten to **eleven** (see §2). RAM-only state (no restart persistence,
consistent with the existing no-snapshot invariant). Everything below remains
**DESIGN-ONLY / awaiting operator sign-off**.

## Revision — 2026-07-04 (observability + control surface)

Adds **D2.12 — Observability & control surface**: exposes the reconciler as a first-class
operator-facing surface without adding new automation knobs beyond what URA's existing
patterns already sanction. Specifically:

1. A per-room **`Auto-Recovery` switch** (default ON, `RestoreEntity`) that gates whether
   the reconciler acts at all for that room — a NEW guard clause in the §2 invariant.
   This is the recount driver: guard count moves from **eleven → twelve**.
2. Two NEW diagnostic sensors — per-room `RoomReconcileSensor` (mirroring
   `AutomationHealthSensor` at `sensor.py:2079`) and house-wide `ReconcileHealthSensor`
   (mirroring `MusicFollowingHealthSensor` at `sensor.py:5762`) — for one-glance
   observability. The per-room sensor exposes a `would_reconcile` attribute — the
   resolver's computed desired target for every currently-SKIPPED entity — so the
   operator can preview reconcile behavior BEFORE flipping `Auto-Recovery` back ON
   (this is the safe-rollout lever; see item 4 below and §6 for why a coordinator-style
   observation-mode switch was REJECTED as a per-room mechanism).
3. A collapsed `reconcile_advanced` section in the ROOM reconfigure flow with a NAMED-
   BUCKET `flap_sensitivity` dropdown (relaxed / normal / aggressive) that maps to the
   D2.11 const triples (`RECONCILE_FLAP_THRESHOLD/WINDOW/STABILITY`). No new per-knob
   Number entities — per operator "Configurability Clarity" + "Number Fields = Form
   Fields" rules.
4. Manual dry-run rollout path documented: `Auto-Recovery` OFF while watching
   `would_reconcile` = per-room preview mode. Replaces the rejected per-room
   observation-mode switch.

D2.12 does NOT raise the tier — the new surfaces (RestoreEntity switch + options-flow
round-trip) are absorbed by the existing Reviewer C framing (see §5). Everything below
remains **DESIGN-ONLY / awaiting operator sign-off**.

---

## 1. Institutional context verified

This is the mandatory proof-of-work. Every proposed surface below is annotated REUSED
(with `file:line`) or NEW (with justification). Greps + reads were run this session.

### 1.1 Greps run + results

| Question | Grep / read | Finding |
|---|---|---|
| Does an actuator-availability **tracker / reconcile primitive** already exist? | `rg "reconcile\|actuator_availability\|on_actuator_available\|track_actuator"` across the integration | **None.** Only hits are an unrelated comment in `presence.py:2998` ("reconciled on next inference tick") and two minified frontend bundles. **NEW** — must be built. |
| Does an availability-transition listener already exist for the configured actuator set (`lights`/`night_lights`/`alert_lights`/`fans`/`humidity_fans`/`covers`/`climate_entity`)? | `rg "async_track_state_change_event"` across integration | 15 sites — all subscribe to **input** entities (motion/mmwave/occupancy/camera/safety/security/perimeter). The `OccupancySubstrate` model (`domain_coordinators/occupancy_substrate.py:265-285`) is the **canonical reuse target** for "one listener subscribed to N entities, single unsub tracked (Bug Class #38)". **NEW** for actuators; **REUSED** pattern. |
| Where does `_get_unavailable_entities` enumerate the actuator config keys? | Read `sensor.py:1623-1730` (D1) | `_ACTUATOR_LIST_KEYS = ("lights","night_lights","alert_lights","fans","humidity_fans","covers")`, `_ACTUATOR_SINGLE_KEYS = ("climate_entity",)`. **REUSED** as the authoritative "what is an actuator?" definition — the reconciler must read the same set. |
| Where is "is_dark" computed? | `automation.py:566` `is_dark(illuminance)` | Pure function on `RoomAutomation`. **REUSED.** |
| Where is the lights entry/exit intent computed/applied? | `automation.py:631` `_control_lights_entry`, `:699` `_control_lights_exit`, `:757` `_turn_on_regular_lights`, `:798` `_turn_on_night_lights`, `:866` `_turn_off_non_night_lights` | The branches encode the full desired state: sleep-mode → night lights only; non-sleep entry → regular lights if `is_dark` and action ∈ {TURN_ON, TURN_ON_IF_DARK}; exit → off if `CONF_EXIT_LIGHT_ACTION == TURN_OFF`. **REUSED** via a thin intent-resolver — see §3.2. Also the **branch-table parity source of truth** for D2.10. |
| Where is fan intent computed? | `automation.py:1542` `handle_temperature_based_fan_control` (CONF_FANS) | Threshold + hysteresis + speed bucket + sleep-policy + vacancy-hold. **REUSED** by calling the helper after reconcile so the room's own logic decides. Also parity source for D2.10 fan cells. |
| Manual-override surfaces | `coordinator.py:1310 _is_automation_enabled`, `:1322 _is_climate_automation_enabled`, `:1329 _is_cover_automation_enabled`, `:1336 _is_ai_automation_enabled`, `:1352 _is_override_occupied`, `:1356 _is_override_vacant`, `:1313 manual_mode` short-circuit | `manual_mode == ON` disables ALL automation. The two override switches force the occupancy state. **REUSED — these are the authoritative override gates the reconciler MUST consult.** |
| Cold-boot settle gate | `presence.py:1354` `_boot_settle_done`, `:1904 _release_boot_settle`, `const.py:1537 BOOT_SETTLE_TIMEOUT_SECONDS=60`. Released by Predicate A (first real input) or Predicate B (`EVENT_HOMEASSISTANT_STARTED` / timeout). Reload path (`hass.is_running == True`) is born already-released. | **REUSED** — gate the reconciler on `presence_coordinator._boot_settle_done`. This is also the prior-art rule that says "don't actuate during the boot storm" (v4.7.21). Post-release **grace window** + **coalesce** added in §3.9 (D2.7). |
| Actuator config keys | `const.py:99 CONF_ALERT_LIGHTS`, `:481 CONF_LIGHTS`, `:483 CONF_FANS`, `:484 CONF_HUMIDITY_FANS`, `:485 CONF_COVERS`, `:509 CONF_NIGHT_LIGHTS`, `:587 CONF_CLIMATE_ENTITY` | **REUSED.** D2 scope below trims this set (no covers, no climate). |
| Activity log + last-action surfaces | `coordinator.py:2643 set_last_action`, `coordinator.py:433/2214/2671 activity_logger` | **REUSED** — every reconcile call logs through `set_last_action(...)` + activity logger so it appears in `LastAutomationTriggerSensor` and the activity feed. **The activity logger is the ONLY telemetry path (batched); no synchronous DAO write per reconcile — see D2.8.** |
| Batched activity-log write path (zero-write invariant target) | Read `coordinator.py:2214, 2671`, `activity_logger` batching | **REUSED** as the sole telemetry sink. Confirms the invariant that reconcile events never take the synchronous DB path that the June 2026 write-flood exercised. |
| Subscription-rebuild hook (Bug Class #50) | `_async_update_subscriptions` (rebuild hook that clobbered `OccupancySubstrate` prior to v4.7.24) | **REUSED** — reconciler's listener MUST be re-registered inside the same hook (see §3.7 update / D2.9). |
| Existing per-room `RestoreEntity + SwitchEntity` prior art for `Auto-Recovery` (D2.12) | `switch.py:3405 AutomationSwitch`, `:3507 ClimateAutomationSwitch`, `:3542 CoverAutomationSwitch` | **REUSED PATTERN.** `AutoRecoverySwitch` is a straight sibling — `UniversalRoomEntity + SwitchEntity + RestoreEntity`, default ON, restore-on-startup via `async_get_last_state`. This is a SEPARATE per-room switch from the master `AutomationSwitch` (which drives `_is_automation_enabled`/`manual_mode`) — it is reconcile-specific. |
| Per-room diagnostic sensor prior art for `RoomReconcileSensor` (D2.12) | `sensor.py:2079 AutomationHealthSensor` | **REUSED PATTERN.** Same per-room device attach + `extra_state_attributes` shape. |
| House-wide aggregation-sensor prior art for `ReconcileHealthSensor` (D2.12) | `sensor.py:5762 MusicFollowingHealthSensor` (AggregationEntity) | **REUSED PATTERN.** Same house-wide roll-up shape. |
| Collapsed reconfigure-section idiom for `reconcile_advanced` (D2.12) | `config_flow.py:3204 fan_recheck_advanced`, `:4329 presence_timing`, `:525 async_step_reconfigure` | **REUSED PATTERN.** Add `reconcile_advanced` as a collapsed `section(...)` in the ROOM reconfigure step. |
| Coordinator-scoped observation-mode switches (why per-room reconcile observation was REJECTED, D2.12) | `PresenceObservationModeSwitch`, `SafetyObservationModeSwitch` and siblings — all coordinator-scoped, not per-room | **REJECTED** as a per-room mechanism. The dry-run lever is instead the manual `Auto-Recovery`-OFF + `would_reconcile` attribute pattern (see §6 out-of-scope note). |
| Room-device toggle prior art explicitly EXCLUDED from this cycle (D2.12) | `const.py:591 CONF_FAN_CONTROL_ENABLED`, `:604 CONF_HUMIDITY_FAN_CONTROL_ENABLED` | **OUT OF SCOPE.** Per-room `FanControlSwitch` / `HumidityControlSwitch` symmetry cycle is a SEPARATE backlog item; not part of reconcile-on-return. See §6.9. |

### 1.2 Prior planning docs consulted

| Doc | Use |
|---|---|
| `docs/planning/PLANNING_cold_boot_away_actuation_storm_mitigation.md` | Boot-settle gate design — REUSED as the boot-window guard AND cited by D2.7 (post-release storm shape). |
| `docs/planning/PLANNING_occupancy_substrate_unification.md` (read excerpt via source) | Canonical listener-registration pattern — REUSED in §3.3 + §3.7 update. |
| `docs/planning/PLANNING_v4.7.22*` (fan recheck Mode-2) | Confirms there is no existing "post-pause re-assert" code that would collide. |
| `docs/BACKLOG.md` — "Offline-actuator visibility + recovery" entry | Source of D1/D2/D3 scoping and operator constraints. |
| June 2026 Optimization-Coordinator write-flood memo (`project_optimizer_db_write_flood_incident_2026_06_09.md`) | Cited by D2.8 as the reason the zero-DB-write invariant is a hard rule. |

### 1.3 Memory bodies consulted

`MEMORY.md` index — no prior memo for an actuator-availability tracker or reconciler.
v4.7.21 boot-storm settle entry consulted (gate semantics). v5.0.0-v5.2.1 optimizer
write-flood memo consulted for D2.8 rationale. Silent-actuator-failure + AV-closet
flaky-Shelly memo (`project_session_pickup_2026_07_02.md`) consulted for D2.11 rationale
(the canary device that motivates the flap detector). Operator feedback memos
`feedback_configurability_clarity.md` ("named-bucket dropdowns + plain-English helper
text over runtime Number entities for technical primitives") and
`feedback_plan_phrasing_number_fields.md` ("Number fields in URA plans = config_flow
NumberSelector form fields, NOT platform Number entities") consulted for D2.12 —
`flap_sensitivity` is a NAMED-BUCKET config-flow dropdown, NOT a Number entity.

### 1.4 Design docs read

- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` (room-coordinator surface)
- `docs/Coordinator/PRESENCE_COORDINATOR.md` (boot-settle gate ownership)
- `docs/QUALITY_CONTEXT.md` Bug Class #34 (function-local imports), Bug Class #38 (listener-unsub leaks),
  Bug Class #50 (substrate sub clobbered by rebuild), **Bug Class #53 (computed-but-not-consumed) — cited for D2.10**, Bug Class #52 (unavailable→OFF restore poisoning — cited for D2.11 no-persist rationale AND for the D2.12 `AutoRecoverySwitch` RestoreEntity guard) — all relevant to listener lifecycle + branch-table completeness + quarantine restart behavior + switch-restore correctness.

### 1.5 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/sensor.py:1610-1731` — D1 actuator enumeration (extended in D2.11 with `reason: "flapping"`; cross-referenced from D2.12 `RoomReconcileSensor`).
- `custom_components/universal_room_automation/sensor.py:2079` — `AutomationHealthSensor` (D2.12 `RoomReconcileSensor` sibling).
- `custom_components/universal_room_automation/sensor.py:5762` — `MusicFollowingHealthSensor` (D2.12 `ReconcileHealthSensor` sibling).
- `custom_components/universal_room_automation/switch.py:3405, 3507, 3542` — `AutomationSwitch` / `ClimateAutomationSwitch` / `CoverAutomationSwitch` (D2.12 `AutoRecoverySwitch` siblings).
- `custom_components/universal_room_automation/config_flow.py:525, 3204, 4329` — `async_step_reconfigure` + collapsed section idiom (D2.12 `reconcile_advanced`).
- `custom_components/universal_room_automation/automation.py:560-900, 1540-1660` — light + fan intent (branch-table parity source for D2.10).
- `custom_components/universal_room_automation/coordinator.py:1300-1360, 2140-2200, 2640-2700` — override / manual_mode / skip-first / set_last_action / activity_logger (batched sink for D2.8).
- `custom_components/universal_room_automation/domain_coordinators/presence.py:1340-2030` — boot-settle gate.
- `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py:240-320` — canonical listener + boot-settle handshake + rebuild-hook pattern (D2.9).

---

## 2. Falsifiable invariant

**On every actuator state transition `unavailable → available`, URA re-asserts the room's
CURRENTLY-COMPUTED desired state for that single entity, iff ALL of the following hold:

1. the entity is a member of the room's configured `lights` / `night_lights` / `alert_lights`
   / `fans` / `humidity_fans` set (scope: lights + fans **only**);
2. `_is_automation_enabled()` is True (i.e. `manual_mode` is OFF) AND, for fans, no per-domain
   automation switch disables fan control;
3. `presence._boot_settle_done` is True (cold-boot window closed) AND the **post-boot-settle
   grace window** (`RECONCILE_POST_BOOT_GRACE_SECONDS`, D2.7) has elapsed;
4. the per-entity reconcile debounce window has elapsed (no re-assert within
   `RECONCILE_DEBOUNCE_SECONDS` of the entity's prior available→unavailable→available cycle);
5. the per-entity reconcile cooldown has elapsed (no more than `RECONCILE_MAX_PER_HOUR`
   reconciles for the same entity within a rolling hour);
6. the room has an *active* automation intent (occupancy known) — `_skip_first_automation`
   is False AND `coordinator.data` is populated;
7. **[D2.7] the per-room coalesce window** (`RECONCILE_COALESCE_WINDOW_SECONDS`) has elapsed
   OR the entity is the first available-transition of a new window: multiple actuators in a
   single room that reconnect within the window collapse into **one** resolver pass over
   the union of their entity_ids (never N independent passes);
8. **[D2.11] the entity is NOT in the flapping quarantine set** — i.e. it has not exceeded
   `RECONCILE_FLAP_THRESHOLD` availability transitions within `RECONCILE_FLAP_WINDOW_SECONDS`,
   OR — if it previously entered quarantine — it has since remained continuously `available`
   for `RECONCILE_FLAP_STABILITY_SECONDS` and been released via the stability path (never
   via a bare timer auto-release);
9. **[D2.12] the room's per-room `Auto-Recovery` switch (`switch.<room>_auto_recovery`)
   is ON.** This is a SEPARATE gate from clause 2's `_is_automation_enabled()` /
   `manual_mode` — it is reconcile-specific, restore-on-startup, defaults ON, and lets the
   operator suppress reconcile per-room without disabling the room's other automation.
   When OFF, the resolver STILL computes `would_reconcile` (visible on the D2.12
   `RoomReconcileSensor`) but no service call is dispatched — this is the manual dry-run
   / safe-rollout mechanism (§6.8 documents why a coordinator-style observation-mode
   switch was rejected as a per-room mechanism).

The reconciler MUST NEVER:

- read a stored stale snapshot of "what we last asked for" — desired state is recomputed live;
- touch `covers` or `climate_entity` — out of scope (see §6);
- send a service call to an entity whose state is still `unavailable`/`unknown`;
- emit more than one reconcile per `(entity_id, available-event)` (idempotent per transition);
- **[D2.8] perform any synchronous DB write on the reconcile path** — all telemetry MUST route
  through the existing batched activity-log sink (`coordinator.activity_logger`). Zero DAO
  `INSERT`/`UPDATE`/`DELETE` per reconcile event. (Cited: June 2026 Optimization-Coordinator
  write-flood, HACS rolled back v5.0.0-v5.2.1.);
- **[D2.9] lose its listener across a subscription rebuild** — the reconciler's unsub list is
  re-armed inside `_async_update_subscriptions` (Bug Class #50);
- **[D2.10] silently no-op on a legitimate cell of the branch table** — `resolve_desired_state`
  returning `None` on any `{occupied × sleep × dark × exit-action}` cell where the canonical
  handler WOULD have acted is a defect, not a design choice (Bug Class #53 self-risk);
- **[D2.11] reconcile — or attempt any service call against — an entity that is currently
  flagged `flapping`.** A quarantined entity is only released via the stability-window path
  (§3.11); a bare timer auto-release is FORBIDDEN because it would re-admit a dying device.
  A still-flaky device stays quarantined indefinitely and remains visible on the D1 sensor;
- **[D2.12] dispatch a service call when the room's `Auto-Recovery` switch is OFF** —
  the resolver may still COMPUTE `would_reconcile` for observability, but the reconcile
  path MUST short-circuit before any `_safe_service_call` invocation. Also: the
  `AutoRecoverySwitch` restore path MUST NOT coerce an `unavailable` last-state to OFF
  (Bug Class #52 guard) — an unrecoverable last-state falls back to the default (ON);
- double-actuate when D2 racing with an organic occupancy change is the source of the
  intent — the canonical `_control_lights_entry`/`_control_lights_exit` and
  `handle_temperature_based_fan_control` paths remain the only writers, with the reconciler
  invoking them in a *restricted* per-entity form (see §3.4).**

**Guard count:** twelve (six original + four added in the 2026-07-03 revision + one added
in the 2026-07-04 revision for the D2.11 flap quarantine + one added in the 2026-07-04
observability revision for the D2.12 per-room `Auto-Recovery` switch).

Every reconcile MUST log: `reconciled <entity_id> to <state> because <reason> (room=<room>, t=<iso>)`
and is surfaced on a diagnostic attribute (§3.5) so a wrong restore is greppable.

### 2.1 Reviewer D falsifiable invariant (Tier 3)

Reviewer D's sole job is to break this single statement, enumerating the **entire**
invariant surface (including pre-existing code, not just the diff):

> **Under ANY boot / batch-reconnect / house-state condition, the reconciler performs
> ZERO synchronous DB writes per event AND issues AT MOST ONE resolver pass per room
> per `RECONCILE_COALESCE_WINDOW_SECONDS` window AND NEVER actuates during boot-settle
> (or its post-release grace window) AND NEVER reconciles — or attempts a service call
> against — a flapping (quarantined) entity except via the stability-window release
> path (§3.11) AND NEVER dispatches a service call for a room whose `Auto-Recovery`
> switch is OFF (D2.12), while STILL computing `would_reconcile` for that room's
> observability sensor.**

Every flagged leak must come with a concrete, legal-config reachable repro (values +
state that trigger it — e.g. "12 Shelly relays across 5 rooms reconnect within 500ms of
`_boot_settle_done` release → N resolver passes, event loop saturated for X ms"; or
"AV-closet Shelly flaps 5×/90s → not quarantined because window rounded to whole
seconds"; or "room `Auto-Recovery` OFF + reconnect → `would_reconcile` populates but a
stray egress site still dispatches `light.turn_on`").

---

## 3. Design

### 3.1 Ownership

A **per-room `ActuatorReconciler`** owned by `UniversalRoomCoordinator` (one instance per
room entry). Per-room (not coordinator-global) because the override/manual_mode gates and
the intent (lights/fans) are per-room, and because actuator config is per-room. This mirrors
the existing per-room ownership of `RoomAutomation`.

Built in `UniversalRoomCoordinator.async_setup` AFTER the room's actuator config is read;
torn down in `async_teardown` (single unsub list stored — see §3.7 update for the D2.9
rebuild-hook re-arm).

### 3.2 Intent resolver — REUSE, do NOT re-derive

Add a thin **`resolve_desired_state(entity_id) -> DesiredState | None`** helper on the
reconciler that computes the LIVE desired state for ONE entity by consulting the SAME
inputs the entry/exit handlers use. It does NOT call them (they actuate over the full
set + log entry/exit events); it READS:

- `coordinator.data[STATE_OCCUPIED]` (current occupancy)
- `coordinator.data[STATE_ILLUMINANCE]` → `RoomAutomation.is_dark(...)` (`automation.py:566`)
- `RoomAutomation.is_sleep_mode_active()`
- `config[CONF_LIGHTS]`, `config[CONF_NIGHT_LIGHTS]`, `config[CONF_ALERT_LIGHTS]`,
  `config[CONF_FANS]`, `config[CONF_HUMIDITY_FANS]`
- For fans: `config[CONF_FAN_CONTROL_ENABLED]`, `CONF_FAN_TEMP_THRESHOLD`,
  `coordinator.data[STATE_TEMPERATURE]`, and `_is_hvac_managing_fans()` defer-rule
  (`automation.py:1556-1558`).
- Branch table (lights only — fans add the temperature/speed dimension):
  - sleep + entity ∈ `night_lights` → `on` (night brightness/color)
  - sleep + entity ∉ `night_lights` → `off`
  - non-sleep + occupied + `is_dark` + `action ∈ {TURN_ON, TURN_ON_IF_DARK}` → `on`
  - non-sleep + occupied + action == `TURN_ON` (no dark gate) → `on`
  - non-sleep + vacant + `CONF_EXIT_LIGHT_ACTION == TURN_OFF` → `off`
  - otherwise → `None` (no opinion → don't reconcile)

`None` is critical: when URA has no opinion (e.g. light action is NONE, or no occupancy
data yet), the reconciler MUST NOT touch the entity. **BUT** — per D2.10, `None` is only
legitimate for cells where the canonical entry/exit handler would ALSO have no opinion.
A `None` on a cell where the handler WOULD have acted is a defect and must be caught by
the parity test.

**D2.12 note.** The resolver's computed decision is exposed as the `would_reconcile`
attribute on `RoomReconcileSensor` (§3.5) for every currently-SKIPPED entity — including
entities skipped because `Auto-Recovery` is OFF, or the entity is quarantined
(D2.11), or is still `unavailable`. The `would_reconcile` shape is
`{entity_id: desired_state}` (only entities with a non-`None` desired). This is the
observability substrate for the manual dry-run rollout path (§6.8).

**Why a thin resolver vs reusing the entry/exit handlers directly:** the handlers operate
on the **whole** light/fan set with their own logging ("Room entry automation: Turned on
N lights"). On a single-entity reconnect we want to actuate **only** that entity (the rest
of the set is fine), and we want a different log line ("reconciled <entity> because
<reason>"). Calling the full handler would also race with itself if multiple entities in
the same room come back near-simultaneously — the resolver + coalesce (§3.9) let us
collapse them.

### 3.3 Listener — REUSE OccupancySubstrate pattern

One `async_track_state_change_event(hass, entity_ids, handler)` per room, where
`entity_ids` is the union of all light + fan config keys for that room. The unsub is
stored on the reconciler's own list `_unsub_reconciler_listeners` (Bug Class #38) and
re-armed inside the subscription-rebuild hook (§3.7 update, Bug Class #50).

**Filter inside the handler** (NOT in the subscription) to detect the
`unavailable → available` transition: `old.state in UNAVAILABLE_STATES and
new.state not in UNAVAILABLE_STATES and new.state != "unknown"`. Filtering in-handler
keeps the listener count = N (per Bug Class #50 — periodic resubscription rebuilds can
clobber a more clever subscription). The same handler feeds the D2.11 flap detector
(§3.11) — every availability edge is recorded to the per-entity rolling window BEFORE the
guard chain runs, so entering quarantine can suppress the very same event that triggers
it.

### 3.4 Reconcile path

```
on (old=unavailable, new=available):
  _flap_record_transition(entity_id)                        # D2.11: record edge FIRST
  if _flap_should_quarantine(entity_id):
      _flap_enter_quarantine(entity_id)                     # sets flapping flag; visible on D1 sensor
      return                                                # do NOT reconcile
  if entity_id in _flapping: return                         # already quarantined; wait for stability path
  # D2.12: compute would_reconcile FIRST (visible even when guards fail below)
  desired_preview = resolver.resolve_desired_state(entity_id)
  _record_would_reconcile(entity_id, desired_preview)       # RoomReconcileSensor attr
  if not _auto_recovery_switch_on(): return                 # D2.12 guard 9 — short-circuit, no service call
  if guard_fails: return  (see invariant §2 list — includes coalesce guard §3.9)
  # coalesce: enqueue entity into room's pending set, arm timer if not armed
  _enqueue_pending(entity_id)
  # when coalesce timer fires:
  for entity_id in pending_set:
      desired = resolver.resolve_desired_state(entity_id)
      if desired is None: continue
      current = hass.states.get(entity_id).state
      if current == desired.state and not desired.has_params_to_apply:
          log "reconcile NO-OP <entity> (already <state>)"
          continue
      await _safe_service_call(domain, service, payload)   # reuse automation._safe_service_call
      coordinator.set_last_action("reconcile", f"reconciled {entity_id} to {desired.state} ({reason})", [entity_id])
      coordinator.activity_logger.log(coordinator="room", action="reconcile_on_return", ...)   # BATCHED path only (D2.8)
      _record_reconcile(entity_id, dt_util.utcnow(), desired.state, reason)   # in-memory ring, no DB
```

Debounce + rate-cap (per-entity rolling deque of timestamps) drops noisy flappers.
Coalesce (per-room) collapses a batch reconnect into one resolver pass (§3.9). The flap
detector + quarantine (§3.11) sits above all of the above — a quarantined entity never
reaches the coalesce queue. The D2.12 `Auto-Recovery` guard sits BETWEEN the flap check
and the coalesce enqueue — computing `would_reconcile` unconditionally (for
observability) but suppressing the service call when the switch is OFF.

### 3.5 Diagnostics — make it greppable

Extend `UnavailableEntitiesSensor` extra_state_attributes (`sensor.py:1716-1730`) with:

- `reconciles_today: int` — count of reconciles this room executed today (resets at midnight).
- `recent_reconciles: list[dict]` — bounded ring of last ~10
  `{entity_id, ts_iso, desired_state, reason, result}` entries.
- `reconcile_debounced_count: int` — how many transitions were suppressed by debounce/rate-cap
  (so we can spot a flapping device).
- `reconcile_coalesced_count: int` — how many available-transitions were folded into a
  batch pass (D2.7 telemetry).
- **[D2.11] `flapping_entities: list[dict]`** — currently-quarantined actuators, shape
  `{entity_id, since_iso, transition_count_at_entry}`. Empty list = healthy.
- **[D2.11] `reason: "flapping"`** — added to the existing per-actuator `details[]`
  reason enum on the D1 sensor (`sensor.py:1623-1730`) alongside `offline_since_restart`,
  `device_unreachable`, `entity_missing`, `state_unknown`. When present, the detail
  entry carries `transition_count` and `since` so a flapping actuator is grep-visible
  next to the offline ones.

**[D2.12] Two NEW dedicated diagnostic sensors** (do NOT bloat `UnavailableEntitiesSensor`
further):

- **`RoomReconcileSensor`** (per-room, NEW) — prior art
  `AutomationHealthSensor` (`sensor.py:2079`). State = reconciles today (int).
  `extra_state_attributes`:
  - `last_reconcile: iso8601 | None`
  - `reconciles_today: int`
  - `coalesced_count: int` — cumulative since boot.
  - `last_skip_reason: str | None` — one of `boot_settle` / `debounce` / `rate_cap` /
    `flapping` / `auto_recovery_off` / `no_data` / `manual_mode` / `not_actuator` /
    `no_opinion`.
  - `would_reconcile: dict[entity_id, desired_state]` — the resolver's computed target
    for every currently-SKIPPED entity in this room (flapping / quarantined / still
    unavailable / auto-recovery-off / in-debounce). Populated LIVE on every availability
    edge (§3.4 path). This is the folded-in "what it would do" — replaces the rejected
    per-room observation-mode switch (§6.8).
  - **Do NOT duplicate `flapping_entities`** — that list lives on `UnavailableEntitiesSensor`
    (D2.11). Cross-reference by pointing operators at `sensor.<room>_unavailable_entities`
    for the flapping detail.

- **`ReconcileHealthSensor`** (house-wide aggregation, NEW) — prior art
  `MusicFollowingHealthSensor` (`sensor.py:5762`, `AggregationEntity`). State = total
  reconciles today across all rooms (int). `extra_state_attributes`:
  - `total_reconciles_today: int`
  - `rooms_with_quarantined_actuators: int`
  - `top_flappers: list[dict]` — top-N `{entity_id, room, transition_count}` sorted
    descending. One-glance dashboard tile.
  - `rooms_with_auto_recovery_off: list[str]` — visibility on which rooms are in dry-run.

This is the operator's "greppability" surface: a wrong restore is one `extra_state_attributes`
read away, the activity log carries the durable trail, and a chronically flaky actuator
is a first-class entry on the same sensor that already surfaces offline actuators.

### 3.6 Constants (NEW — propose to add to `const.py`)

| Constant | Value | Justification |
|---|---|---|
| `RECONCILE_DEBOUNCE_SECONDS` | 15 | Suppresses fast flap (WiFi roam). Picked an order-of-magnitude under typical occupancy hold times so we don't accidentally suppress a legitimate reconnect. NEW — no equivalent debounce constant exists for actuator reconciles. |
| `RECONCILE_MAX_PER_HOUR` | 6 | Per-entity rolling cap. NEW. |
| `RECONCILE_RING_SIZE` | 10 | Diagnostic ring bound. NEW. |
| `RECONCILE_COALESCE_WINDOW_SECONDS` | 2.5 | **NEW (D2.7).** Per-room cross-entity window: after the first available-transition arrives, wait this many seconds collecting siblings, then run ONE resolver pass over the union. Tunable — value chosen to be longer than a typical multi-relay WiFi-recovery burst (~500-1500ms observed on the Shelly fleet) but well under `RECONCILE_DEBOUNCE_SECONDS`. |
| `RECONCILE_POST_BOOT_GRACE_SECONDS` | 10 | **NEW (D2.7).** After `_boot_settle_done` flips True, delay reconciler arming this many seconds so entities completing their unavailable→available transition in the trailing edge of boot don't all fire simultaneously. |
| `RECONCILE_FLAP_THRESHOLD` | 4 | **NEW (D2.11).** Per-entity availability-transition count that trips quarantine within `RECONCILE_FLAP_WINDOW_SECONDS`. Keyed on transitions (not reconciles) so it's MORE sensitive than the blunt 6/hr reconcile cap and trips first — the cap only throttles; the quarantine surfaces the problem AND stops attempting service calls against a dying device. Value 4 chosen to be one above the "brief WiFi roam" shape (typically 1-2 transitions) but below the 5-6 range where a genuinely dying radio starts thrashing. Also = **`normal` bucket default** for the D2.12 `flap_sensitivity` dropdown. |
| `RECONCILE_FLAP_WINDOW_SECONDS` | 120 | **NEW (D2.11).** Rolling window over which `RECONCILE_FLAP_THRESHOLD` transitions accumulate. 120s is short enough that a burst of thrashing trips before the hourly cap could mask it, and long enough that a single WiFi glitch + reconnect (~1-3 edges over a few seconds) does not falsely quarantine. |
| `RECONCILE_FLAP_STABILITY_SECONDS` | 600 | **NEW (D2.11).** Continuous-`available` duration (zero transitions) required to release from quarantine. 10 min ≫ 2 min entry window makes the enter/exit hysteresis inherent — an entity cannot oscillate in and out of quarantine. Release is stability-proven, NOT bare-timer: on the release, run EXACTLY ONE reconcile pass (state may be stale from the quarantine period), then resume normal debounce + hourly-cap behavior. If the entity never stabilizes it stays quarantined INDEFINITELY and remains visible to the operator. |
| `RECONCILE_FLAP_SENSITIVITY_BUCKETS` | dict | **NEW (D2.12).** Named-bucket triples the `flap_sensitivity` config-flow dropdown maps to. NOT operator-facing raw seconds. Defaults: `relaxed = (THRESHOLD=6, WINDOW=180, STABILITY=900)`, `normal = (THRESHOLD=4, WINDOW=120, STABILITY=600)` (= D2.11 defaults, source of truth), `aggressive = (THRESHOLD=3, WINDOW=90, STABILITY=450)`. If the room has no per-room override the D2.11 defaults apply as-is (i.e. `normal`); when the operator picks a bucket, the room's reconciler uses that triple. NO per-knob Number entities — per operator "Configurability Clarity" + "Number Fields = Form Fields" rules. |
| `UNAVAILABLE_STATES` | reuse existing | `_UNAVAILABLE_STATES` already exists in `occupancy_substrate.py` — **REUSE** by promoting to `const.py` or importing. |

No new CONF_* raw-seconds knob for the flap primitives (per operator rules). The only
new operator-facing controls are:

- **`switch.<room>_auto_recovery`** (D2.12) — per-room `RestoreEntity + SwitchEntity`,
  default ON, prior art `AutomationSwitch` (`switch.py:3405`) /
  `ClimateAutomationSwitch` (`switch.py:3507`) / `CoverAutomationSwitch`
  (`switch.py:3542`). SEPARATE from the master `AutomationSwitch` — reconcile-specific.
- **`reconcile_advanced` collapsed section** in the ROOM reconfigure flow (D2.12) —
  prior art `fan_recheck_advanced` (`config_flow.py:3204`), `presence_timing`
  (`config_flow.py:4329`), added via `async_step_reconfigure` (`config_flow.py:525`).
  Contains ONE field: `flap_sensitivity: SelectSelector(relaxed / normal / aggressive)`
  that maps to `RECONCILE_FLAP_SENSITIVITY_BUCKETS`. Const defaults remain source of
  truth; the dropdown overrides the bucket. Not a Number entity.

If we discover a need for further per-room disable levers (e.g. temporarily suspend
reconcile-on-return without touching Auto-Recovery), we add on demand. Keeping the
surface minimal per the operator's "small, fail-safe, additive" constraint.

### 3.7 Lifecycle / cleanup (Bug Class #38 + Bug Class #50)

- Reconciler owns its **own** unsub list: `_unsub_reconciler_listeners: list[Callable]`
  (SEPARATE from other coordinator listener lists — do not co-mingle).
- Reconciler held on `coordinator._actuator_reconciler` (or similar named slot).
- `async_teardown` calls `reconciler.async_teardown()` before the room coordinator unloads;
  `async_teardown` drains `_unsub_reconciler_listeners`.
- **Bug Class #50 hardening (D2.9):** the reconciler's listener registration is invoked
  from inside the same `_async_update_subscriptions` (or equivalent per-room rebuild hook)
  that rebuilds the room's other listeners. A subscription rebuild — options-flow save,
  periodic signal-subscription refresh — MUST NOT silently orphan the reconciler's
  listener. The rebuild hook drains `_unsub_reconciler_listeners` first, then re-arms.
  Regression guard test (D2.9) invokes the rebuild hook and asserts the listener is still
  wired.
- **Flap-quarantine state is RAM-ONLY (D2.11).** `_flap_windows: dict[str, deque[float]]`
  and `_flapping: dict[str, dict]` live on the reconciler instance; nothing is persisted
  across restart. Consistent with the doc's no-snapshot invariant (§2) and specifically
  avoids Bug Class #52 (unavailable→OFF RestoreEntity poisoning). Post-restart, a
  still-flaky device re-detects within one `RECONCILE_FLAP_WINDOW_SECONDS` window; a
  recovered device reconciles normally on its first `unavailable → available` edge.
- **`AutoRecoverySwitch` restore (D2.12).** On `async_added_to_hass`, `async_get_last_state`
  is consulted; if last-state is `"on"` or `"off"` the switch adopts it; if last-state is
  `unavailable` / `unknown` / `None` the switch falls back to the default (ON) — this is
  the Bug Class #52 guard (do NOT coerce unavailable → OFF). `would_reconcile` on the
  D2.12 `RoomReconcileSensor` populates regardless of switch state; only the service-call
  dispatch is gated. The switch itself is NOT persisted through any DAO — RestoreEntity
  is the sole persistence path.

### 3.8 Imports (Bug Class #34)

All imports at module top of the new file. No function-local imports of dispatcher /
event helpers (the v4.7.20.1 hotfix lesson).

### 3.9 Boot-settle release storm mitigation (D2.7 — coalesce + grace)

**The gap the original design missed.** The invariant gated on `_boot_settle_done`, but
was silent on what happens at the INSTANT it flips. Real-world shape (from the 2026.7.0
event-loop-load incident + June 2026 write-flood precedent + v4.7.19 boot-away-actuation-
storm):

1. A WiFi / router event knocks ~20-40 Shelly relays offline mid-boot.
2. Recovery brings them back over ~500-2000ms while URA is still inside boot-settle.
3. `_boot_settle_done` flips True. Per-entity debounce does NOT throttle N distinct
   entities firing simultaneously (debounce is per `entity_id`, not per room / per system).
4. N reconcilers arm within a single tick, each schedules a resolver pass + service call.
5. Event loop saturates → other coordinators starve → watchdog risk (precedent: June
   2026 optimizer write-flood → HACS rolled back v5.0.0-v5.2.1).

**Mitigation — TWO layered mechanisms:**

**Primary — per-room cross-entity coalesce window.** When the FIRST actuator in a room
reconnects, arm a `RECONCILE_COALESCE_WINDOW_SECONDS` timer and enqueue the entity into
that room's `_pending_reconcile: set[str]`. Every additional actuator in the same room
that reconnects before the timer fires is added to the set (`reconcile_coalesced_count`
increments). When the timer fires, run **one** `resolve_desired_state` pass across the
union of the set. Result: 1 resolver pass + at most 1 service call per configured actuator
domain per room per window, no matter how many entities reconnected. This is the primary
mechanism — always on.

**Secondary — post-boot-settle grace window.** After `_boot_settle_done` flips True, wait
`RECONCILE_POST_BOOT_GRACE_SECONDS` before the reconciler starts accepting available
transitions as reconcile triggers. Available transitions that arrive during the grace
window are ignored (not enqueued) — the next organic occupancy change will drive normal
actuation, or a subsequent flap will trigger reconcile once the grace has elapsed.

Both values live in `const.py` as tunable constants (§3.6). Together they turn the
worst-case boot storm from `O(N)` service calls into `O(rooms with reconnects) service
calls with a bounded upper wall-clock of one coalesce window per room.

### 3.10 Zero-DB-write invariant (D2.8)

Reconcile events emit **zero synchronous DB writes.** All telemetry — activity log,
last-action, diagnostic ring — routes through paths that are either in-memory
(`_record_reconcile`, ring on the sensor's extra_state_attributes) or the existing
**batched** `coordinator.activity_logger` sink. There is no per-event `INSERT` / `UPDATE`
/ `DELETE` on the reconcile hot path.

**Why this is a hard invariant, not a recommendation.** June 2026: the Optimization
Coordinator (v5.0.0-v5.2.1) persisted findings one-by-one each cycle
(`optimization.py:691`). Per-boot-unavailable-room compounding sensor-health emissions
saturated the DB write queue. Core writes starved. Watchdog restarted the house. HACS
rolled back to v4.7.33. Reconcile-on-Return is a per-entity availability trigger that
could fire dozens of times during exactly the network-event scenarios this feature is
designed for — a synchronous DAO write per reconcile would rebuild the write-flood
failure mode.

Enforcement: D2.8 acceptance criteria include a static-analysis test that greps the new
module for direct `database.` DAO imports / calls, AND a behavioral test that instruments
the batched sink and asserts zero non-batched writes during a 20-reconcile burst.

### 3.11 Flap detector + quarantine (D2.11)

**The gap the flat per-hour cap left open.** `RECONCILE_MAX_PER_HOUR = 6` (guard 5)
throttles a flapping actuator to at most six reconcile attempts per hour, but it (a) does
not surface the problem — the operator sees quiet suppression, not a signal — and (b)
still allows six pointless service calls per hour against a device that will never
stabilize. The AV-closet Shelly1PMGen3 (project memory: flaky hardware, recurring
canary) is the exact device class that motivates a first-class quarantine mechanism.

**Enter quarantine.** Every `unavailable ↔ available` edge on a tracked actuator is
appended to a per-entity rolling window `_flap_windows[entity_id]: deque[float]` (edge
timestamps). BEFORE the guard chain runs, the handler prunes entries older than
`RECONCILE_FLAP_WINDOW_SECONDS` and evaluates: `len(window) >= RECONCILE_FLAP_THRESHOLD`.
On breach the entity is marked `flapping` (`_flapping[entity_id] = {"since": now,
"transition_count_at_entry": len(window)}`), the reconcile pipeline SHORT-CIRCUITS
(quarantined entity never reaches the coalesce queue, never dispatches a service call),
and the entity appears on the D1 diagnostic sensor (§3.5) with `reason: "flapping"` plus
its transition count and `since` timestamp. The threshold is keyed on transitions (not
reconciles) so quarantine trips FIRST — before the 6/hr reconcile cap could mask the
device as merely "throttled".

**Dequarantine — stability-proven only, NOT bare-timer.** The reconciler tracks
per-quarantined-entity `_flap_last_transition_ts[entity_id]`. On every subsequent
availability edge the timestamp is updated (and the entity STAYS quarantined). Only when
the entity has remained continuously `available` for `RECONCILE_FLAP_STABILITY_SECONDS`
(600s / 10 min, zero transitions in that window) is it eligible for release. On release:
clear the `flapping` flag, purge the flap window (fresh start), run EXACTLY ONE reconcile
pass (state may be stale from the quarantine period), then resume normal debounce +
hourly-cap behavior. If the entity never stabilizes it stays quarantined INDEFINITELY
and remains visible on the D1 sensor for the operator to act on (replace the radio, fix
the AP, etc.). **There is NO bare-timer auto-release** — that would re-admit a dying
device and reintroduce the exact silent-retry failure this deliverable is designed to
close.

**Cycle time / hysteresis.** Quarantine dwell is at minimum
`RECONCILE_FLAP_STABILITY_SECONDS` — the "stopped flapping → reconciled + back to
normal" wall-clock. Hysteresis is inherent because the exit window (600s zero-edge
observation) is FIVE TIMES the entry window (120s rolling): the entity cannot oscillate
in and out of quarantine on the same physical fault.

**Restart resilience.** State is RAM-ONLY (`_flap_windows`, `_flapping`,
`_flap_last_transition_ts` all live on the reconciler instance; nothing persisted). This
is consistent with the doc's existing no-snapshot invariant (§2) and specifically avoids
Bug Class #52 (`unavailable → OFF` RestoreEntity poisoning). Post-restart:
- A still-flaky device will re-accumulate `RECONCILE_FLAP_THRESHOLD` transitions within
  one `RECONCILE_FLAP_WINDOW_SECONDS` window and be re-quarantined — expected latency
  well under 3 minutes for a device thrashing at the observed AV-closet rate.
- A recovered device reconciles normally on its first `unavailable → available` edge.

**State machine (per entity):**

```
STATE: healthy (default)
  on availability edge:
    append edge to window; prune > FLAP_WINDOW_SECONDS
    if len(window) >= FLAP_THRESHOLD:
       -> quarantined
    else:
       proceed to guard chain (invariant §2 clauses 1-9)

STATE: quarantined
  on availability edge:
    update last_transition_ts
    (entity stays quarantined; short-circuit before guard chain)
  on timer tick (or on next available edge check):
    if now - last_transition_ts >= FLAP_STABILITY_SECONDS AND entity currently available:
       -> healthy, purge window, run ONE reconcile pass, then normal debounce
    else:
       stay quarantined
```

**Why NOT reuse the debounce or hourly-cap counter for this.** Debounce is per-edge
suppression (window ~15s, single-shot); the hourly cap is a throttle that still permits
attempts. Neither surfaces the entity to the operator, and neither stops service-call
attempts. D2.11 is a strictly stronger primitive scoped to devices that fail the
"transient" definition — it does not replace either of them, it sits above them.

---

## 4. Deliverables + Acceptance Criteria

**Gating note:** D2.7 (coalesce + grace), D2.8 (zero DB writes), D2.9 (rebuild-hook
re-arm), and D2.10 (branch-table parity) are **CORE, not optional.** All four must pass
their acceptance criteria before deploy — no partial ship. D2.11 (flap detector +
quarantine) is a first-class deliverable added in the 2026-07-04 revision; it does not
carry the "no partial ship" CORE tag but its acceptance criteria must all pass before
deploy — the invariant now depends on it (guard 8, §2). D2.12 (observability + control
surface) is a first-class deliverable added in the 2026-07-04 observability revision; it
does not carry CORE but its acceptance criteria must all pass before deploy — the
invariant depends on guard 9 (`Auto-Recovery` switch, §2). See §5 for review framing.

### D2.1 — `ActuatorReconciler` class + listener registration

Create `custom_components/universal_room_automation/actuator_reconciler.py` with the
class, the intent resolver, the debounce + rate-cap state, and the diagnostic ring.
Owner: `UniversalRoomCoordinator` (`coordinator.py` setup/teardown wiring).

**Acceptance criteria**
- **Verify:** for every room with at least one configured light or fan, `coordinator._actuator_reconciler` is non-None after setup.
- **Verify:** exactly **one** unsub appended for the actuator state-change subscription per room (single subscription, N entities). Inspect via test instrumentation.
- **Test:** `test_actuator_reconciler_setup_subscribes_once` — assert listener count delta = 1 after `async_setup`.
- **Test:** `test_actuator_reconciler_async_teardown_releases_listener` — Bug Class #38 regression guard.
- **Test:** `test_intent_resolver_returns_none_when_action_is_NONE` — no-opinion case.

### D2.2 — Guard set enforcement (invariant §2)

Each guard from the invariant has an explicit unit test that proves the reconciler does
NOT fire when that guard fails.

**Acceptance criteria**
- **Test:** `test_reconcile_skipped_when_manual_mode_on` — `switch.<room>_manual_mode == on` → no service call emitted.
- **Test:** `test_reconcile_skipped_during_boot_settle` — `presence._boot_settle_done == False` → no service call.
- **Test:** `test_reconcile_skipped_within_debounce_window` — second transition inside `RECONCILE_DEBOUNCE_SECONDS` → suppressed; `reconcile_debounced_count` increments.
- **Test:** `test_reconcile_respects_per_hour_cap` — > `RECONCILE_MAX_PER_HOUR` events → cap engaged.
- **Test:** `test_reconcile_skipped_when_no_data_yet` — `coordinator.data == {}` (pre-first-refresh) → no service call.
- **Test:** `test_reconcile_does_not_touch_covers_or_climate` — populate `covers` + `climate_entity`, fire reconnect → no calls go to those domains.
- **Test:** `test_reconcile_skipped_when_entity_is_flapping` — entity in `_flapping` set → no coalesce enqueue, no service call (guard 8, D2.11).
- **Test:** `test_reconcile_skipped_when_auto_recovery_off` — `switch.<room>_auto_recovery == off` → no service call (guard 9, D2.12); `would_reconcile` still populates on `RoomReconcileSensor`.

### D2.3 — Live re-assert path (lights + fans)

Happy path: a light flips `unavailable → on`; occupancy True; dark True; action TURN_ON_IF_DARK → `light.turn_on` is dispatched to JUST that entity (not the whole light set).

**Acceptance criteria**
- **Test:** `test_light_reconcile_turns_on_when_room_is_occupied_and_dark` — single `light.turn_on` call with `entity_id == [reconciled_id]` (NOT the full `CONF_LIGHTS`).
- **Test:** `test_light_reconcile_turns_off_when_room_is_vacant` — exit action == TURN_OFF and the entity is `on` → `light.turn_off` for just that entity.
- **Test:** `test_light_reconcile_uses_night_brightness_when_in_sleep_mode` — sleep mode + entity ∈ `night_lights` → `brightness_pct` matches `CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS`.
- **Test:** `test_fan_reconcile_respects_hvac_managed_defer` — when `_is_hvac_managing_fans()` is True, the resolver returns None (don't fight HVAC's fan control).
- **Test:** `test_fan_reconcile_off_when_vacant_or_below_threshold` — mirrors `handle_temperature_based_fan_control` decision.

### D2.4 — Diagnostics surface

Extend `UnavailableEntitiesSensor.extra_state_attributes` (`sensor.py:1716-1730`) with
`reconciles_today`, `recent_reconciles`, `reconcile_debounced_count`,
`reconcile_coalesced_count`, and (D2.11) `flapping_entities`. Read from the coordinator's
reconciler (None-safe — sensor degrades gracefully if reconciler is None on a room with
no light/fan config). Also extend the existing per-actuator `details[]` reason enum with
`"flapping"` alongside `offline_since_restart` / `device_unreachable` / `entity_missing` /
`state_unknown`.

**Acceptance criteria**
- **Sensor:** `sensor.<room>_unavailable_entities` extra_state_attributes contains the five new keys; `recent_reconciles` shape matches `[{"entity_id","ts_iso","desired_state","reason","result"}]`; `flapping_entities` shape matches `[{"entity_id","since_iso","transition_count_at_entry"}]`.
- **Test:** `test_diagnostic_attrs_present_after_one_reconcile` — exercise reconcile once, assert ring contains one entry with correct keys.
- **Test:** `test_diagnostic_attrs_degrade_gracefully_when_no_actuators_configured` — room with no lights/fans → attrs present but reconciler is None, `reconciles_today=0`.

### D2.5 — Observability (log line)

Every reconcile emits a single INFO log line:
`reconciled <entity_id> to <state> because <reason> (room=<room>, t=<iso>)`.

**Acceptance criteria**
- **Test:** `test_reconcile_emits_canonical_log_line` — caplog captures the line with the exact prefix `reconciled `.
- **Live:** post-deploy, on the next genuine WiFi event that takes a Shelly/Sonoff relay offline + back, run `grep "reconciled " home-assistant.log` and confirm one line per reconcile.

### D2.6 — Live validation (post-deploy)

Recorded back into `README_v<version>.md` per the URA write-back rule.

**Live criteria (to populate in the README post-restart):**
- **Live:** every room with `lights` configured shows `reconciles_today` attribute available on the existing diagnostic sensor (initial value 0).
- **Live:** simulate the AV-closet failure mode: reload the Shelly config entry (or use the operator's WiFi-bounce path) → the Shelly transitions `unavailable → available` → `sensor.av_closet_unavailable_entities.recent_reconciles` shows one entry within 30s.
- **Live:** verify the room's light state matches `is_occupied AND is_dark` after the reconcile (greppable from `home-assistant.log` "reconciled " line + `light.<av_closet>.state`).
- **Live:** with `switch.<room>_manual_mode` ON, induce a reconnect → confirm NO reconcile entry appears and the light stays in its physical state.
- **Live [D2.7]:** simulate a batch reconnect (≥3 room actuators, ≤2s apart) → `reconcile_coalesced_count` increments by (N-1); exactly one resolver pass observed in the log per room per window.
- **Live [D2.8]:** during a 10-minute post-restart window with induced reconnects, the batched activity-log write-rate stays within the pre-deploy baseline (no per-reconcile spike).
- **Live [D2.12]:** `switch.<room>_auto_recovery` visible per-room, defaults ON, survives restart (Bug Class #52 guard — an `unavailable` last-state falls back to ON, not OFF). Flip OFF → next reconnect populates `sensor.<room>_room_reconcile.would_reconcile` but emits no service call; flip ON → next reconnect reconciles normally. `sensor.house_reconcile_health` shows the room in `rooms_with_auto_recovery_off` while OFF.

### D2.7 — Boot-settle release storm mitigation (coalesce + grace) — **CORE**

Implement the per-room cross-entity coalesce window and the post-boot-settle grace
window described in §3.9. Both mechanisms land together — coalesce is primary, grace is
the belt-and-braces backstop for the trailing edge of boot.

**Acceptance criteria**
- **Verify:** `RECONCILE_COALESCE_WINDOW_SECONDS` and `RECONCILE_POST_BOOT_GRACE_SECONDS` exist in `const.py` at proposed defaults (2.5s, 10s), tunable.
- **Verify:** per-room `_pending_reconcile: set[str]` and single coalesce timer live on the reconciler; timer is idempotently armed by the first available-transition in a window and disarmed after the resolver pass.
- **Test:** `test_batch_reconnect_collapses_to_one_resolver_pass` — fire 5 `unavailable→available` events for 5 entities in one room within 500ms → exactly ONE resolver pass; `reconcile_coalesced_count` increments by 4.
- **Test:** `test_coalesce_is_per_room_not_global` — two rooms each get a batch → two independent resolver passes, not one merged pass.
- **Test:** `test_post_boot_grace_suppresses_trailing_transitions` — flip `_boot_settle_done` True, fire a reconnect within `RECONCILE_POST_BOOT_GRACE_SECONDS` → no reconcile emitted; fire another after grace expires → reconcile fires.
- **Test:** `test_boot_storm_release_shape` — simulate 20 entities across 5 rooms reconnecting within 1s of boot-settle release → at most 5 resolver passes total (one per room), no event-loop stall > 100ms in the test harness.
- **Live:** during the next real WiFi event, `reconcile_coalesced_count` on affected rooms > 0 and the log shows one resolver pass per room per window.

### D2.8 — Zero-DB-writes-per-reconcile invariant — **CORE**

Enforce that a reconcile event performs no synchronous DB writes; all telemetry routes
through the batched `coordinator.activity_logger` sink. This is an invariant (§2 clause
7), not a performance target.

**Acceptance criteria**
- **Verify:** `actuator_reconciler.py` imports no `database.` DAO module. Static grep test asserts absence.
- **Verify:** every telemetry write on the reconcile path is a call to `coordinator.activity_logger.log(...)` or `coordinator.set_last_action(...)` — no direct `.execute(...)` / DAO method calls.
- **Test:** `test_reconcile_module_does_not_import_database_daos` — AST/grep test asserts no `from ...database` and no `import database` in the new module.
- **Test:** `test_reconcile_burst_no_synchronous_db_writes` — instrument the DB layer with a synchronous-write spy; drive 20 reconciles in quick succession; assert spy count = 0. Batched activity-log entries are permitted (and observed separately).
- **Test:** `test_reconcile_telemetry_routes_through_batched_activity_logger` — assert `coordinator.activity_logger.log` is called once per reconcile.
- **Live:** as in D2.6 D2.8 live criterion — write-rate stays within pre-deploy baseline during induced reconnect burst.

### D2.9 — Reconciler unsub list + subscription-rebuild re-arm (Bug Class #50) — **CORE**

The reconciler owns a separate `_unsub_reconciler_listeners` list and its registration is
invoked from inside `_async_update_subscriptions` (or the equivalent per-room rebuild
hook), so a rebuild cannot silently orphan the listener.

**Acceptance criteria**
- **Verify:** `_unsub_reconciler_listeners` is a distinct attribute on the reconciler, not co-mingled with other coordinator unsub lists.
- **Verify:** the room coordinator's subscription-rebuild hook drains `_unsub_reconciler_listeners` and calls `reconciler.async_register_listeners()` (or equivalent) as part of the rebuild.
- **Test:** `test_reconciler_listener_survives_subscription_rebuild` — assert listener count before and after `_async_update_subscriptions` is equal; a `unavailable→available` event fired after the rebuild still triggers reconcile. This is the direct Bug Class #50 regression guard for this cycle.
- **Test:** `test_reconciler_listener_survives_options_flow_reload_simulation` — mimic an options-flow save that triggers a rebuild; reconcile still fires post-rebuild.
- **Test:** `test_reconciler_async_teardown_drains_all_unsubs` — teardown leaves `_unsub_reconciler_listeners == []`.

### D2.10 — Branch-table parity test (Bug Class #53 self-risk) — **CORE, GATING**

`resolve_desired_state` is itself a new "consume the desired state" site — the exact
computed-but-not-consumed class D2 is designed to eliminate. A missing cell of the
`{occupied × sleep × dark × exit-action}` cross-product returns `None` and silently
no-ops the reconcile. Elevate this from "reviewer recommendation" to a MANDATORY gating
truth-table test.

**Acceptance criteria**
- **Verify:** the resolver's branch table is documented as a truth table (in code or docstring) enumerating every combination of `{occupied ∈ {T,F}} × {sleep ∈ {T,F}} × {is_dark ∈ {T,F}} × {entry_action ∈ {TURN_ON, TURN_ON_IF_DARK, NONE}} × {exit_action ∈ {TURN_OFF, NONE}} × {entity ∈ night_lights ∈ {T,F}}`.
- **Test:** `test_resolver_branch_table_parity_with_canonical_handlers` — a data-driven test that, for EVERY cell of the truth table, drives BOTH (a) the resolver and (b) a fake room with the canonical `_control_lights_entry` / `_control_lights_exit` / night-lights branches, and asserts the resolver's decision agrees with the canonical handler's decision for THAT entity. A `None` from the resolver is only accepted for cells where the canonical handler ALSO would not act on the entity.
- **Test:** `test_resolver_fan_branch_table_parity_with_temperature_handler` — same, for the fan cross-product `{occupied × sleep × temp-above-threshold × hvac_managing_fans × fan_control_enabled}` vs `handle_temperature_based_fan_control`.
- **Test:** `test_resolver_none_on_no_data_is_intentional` — the `None`-on-no-data cell is asserted separately (the ONLY legitimate all-`None` cell).
- **Gate:** this test is gating for deploy. A single disagreement between resolver and canonical handler in a legal cell blocks ship.

### D2.11 — Flap detector + quarantine

Implement the per-entity flap detector, the RAM-only quarantine flag, the
stability-window release path, and the D1-sensor `reason: "flapping"` surface described
in §3.11. Guards the reconciler against burning cycles on a chronically flaky actuator
(canary: AV-closet Shelly1PMGen3) and turns silent retries into a first-class visible
signal.

**Acceptance criteria**
- **Verify:** `RECONCILE_FLAP_THRESHOLD` (4), `RECONCILE_FLAP_WINDOW_SECONDS` (120), and `RECONCILE_FLAP_STABILITY_SECONDS` (600) exist in `const.py` at proposed defaults, tunable.
- **Verify:** per-entity `_flap_windows: dict[str, deque[float]]`, `_flapping: dict[str, dict]`, and `_flap_last_transition_ts: dict[str, float]` live on the reconciler instance; none is persisted (not written to `.storage`, not routed through any DAO). RAM-only.
- **Verify:** `UnavailableEntitiesSensor` `details[]` includes `"flapping"` in its documented reason enum and carries `transition_count` + `since` when present; `extra_state_attributes` exposes `flapping_entities`.
- **Test:** `test_flap_enters_quarantine_at_threshold_within_window` — fire 4 `unavailable ↔ available` transitions within 120s → entity flagged `flapping`; `flapping_entities` on the D1 sensor lists it; `reason: "flapping"` present on its `details[]` row.
- **Test:** `test_flap_zero_reconcile_service_calls_while_flagged` — while entity is in `_flapping`, drive 10 additional availability edges → assert exactly ZERO `_safe_service_call` invocations for that entity across the entire burst.
- **Test:** `test_flap_release_requires_stability_window_not_bare_timer` — quarantine an entity; advance clock by `RECONCILE_FLAP_STABILITY_SECONDS - 1` with a single transition mid-window → entity STAYS quarantined (window resets). Advance by full `RECONCILE_FLAP_STABILITY_SECONDS` with zero transitions → released.
- **Test:** `test_flap_release_runs_exactly_one_reconcile_pass` — on release, assert exactly ONE reconcile pass runs (state may be stale) and normal debounce + hourly-cap behavior resumes afterward.
- **Test:** `test_flap_hysteresis_no_oscillation` — the 600s exit window vs the 120s entry window makes it structurally impossible to oscillate; assert an entity released via the stability path does not immediately re-quarantine on a single follow-up edge.
- **Test:** `test_flap_state_not_persisted_across_restart` — simulate reconciler teardown + fresh construction; assert `_flap_windows`, `_flapping`, and `_flap_last_transition_ts` are all empty on the new instance (no `.storage` read, no DAO read). Consistent with the no-snapshot invariant and Bug Class #52 avoidance.
- **Test:** `test_flap_window_pruning_rolling` — edges older than `RECONCILE_FLAP_WINDOW_SECONDS` are pruned before threshold evaluation; assert an entity flapping at exactly 3 edges / 60s indefinitely never quarantines (below threshold).
- **Test:** `test_flap_detector_records_edge_before_guard_chain` — a boot-settle-suppressed transition still contributes to `_flap_windows` (recorded first); the entity can enter quarantine BEFORE the grace window elapses if its behavior warrants it.
- **Live:** AV-closet Shelly1PMGen3 as the natural canary. When it thrashes on the next observed WiFi event, `sensor.av_closet_unavailable_entities` shows the entity in `flapping_entities` with `reason: "flapping"`, `transition_count`, and `since`; grep the log for `reconciled <av_closet>` and confirm ZERO reconcile lines while quarantined.
- **Live:** after the AV-closet stabilizes for ≥10 continuous minutes, confirm the `flapping_entities` list clears for that entity AND exactly one reconcile line appears in the log at release time.

### D2.12 — Observability & control surface

Implement the per-room `Auto-Recovery` switch (guard 9), the two new dedicated diagnostic
sensors (`RoomReconcileSensor` + `ReconcileHealthSensor`), the `reconcile_advanced`
collapsed reconfigure section with the `flap_sensitivity` named-bucket dropdown, and the
`would_reconcile` observability attribute that powers the manual dry-run rollout path.
All pieces REUSE existing URA patterns (prior art cited inline; see §1.1 additions and
§3.6).

**Acceptance criteria**
- **Verify:** `switch.<room>_auto_recovery` present per-room. Class = `AutoRecoverySwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity)`. Default = ON. Prior art: `AutomationSwitch` (`switch.py:3405`), `ClimateAutomationSwitch` (`switch.py:3507`), `CoverAutomationSwitch` (`switch.py:3542`). SEPARATE from the master `AutomationSwitch` and from `manual_mode`.
- **Verify:** `sensor.<room>_room_reconcile` (`RoomReconcileSensor`) exists per-room. Prior art `AutomationHealthSensor` (`sensor.py:2079`). State = `reconciles_today` (int). `extra_state_attributes` shape: `{last_reconcile, reconciles_today, coalesced_count, last_skip_reason, would_reconcile: {entity_id: desired_state}}`.
- **Verify:** `sensor.house_reconcile_health` (`ReconcileHealthSensor`) exists house-wide. Prior art `MusicFollowingHealthSensor` (`sensor.py:5762`, `AggregationEntity`). Attributes: `total_reconciles_today`, `rooms_with_quarantined_actuators`, `top_flappers`, `rooms_with_auto_recovery_off`.
- **Verify:** `RoomReconcileSensor` does NOT duplicate `flapping_entities` — it cross-references `sensor.<room>_unavailable_entities` (D2.11) instead.
- **Verify:** `reconcile_advanced` section appears in the ROOM reconfigure flow as a collapsed `section(...)` (prior art `fan_recheck_advanced` at `config_flow.py:3204`, `presence_timing` at `config_flow.py:4329`, wired via `async_step_reconfigure` at `config_flow.py:525`). Contains ONE field: `flap_sensitivity: SelectSelector([relaxed, normal, aggressive])`. Default = `normal`. NO per-knob Number entities.
- **Verify:** `flap_sensitivity` maps to `RECONCILE_FLAP_SENSITIVITY_BUCKETS` triples; when unset the D2.11 defaults apply (`normal`). Const defaults remain source of truth.
- **Test:** `test_auto_recovery_switch_off_suppresses_reconcile` — switch OFF → drive availability transition → assert zero `_safe_service_call` invocations AND `would_reconcile[entity_id]` is populated on `RoomReconcileSensor`.
- **Test:** `test_auto_recovery_switch_on_reconciles_normally` — switch ON (default) → drive availability transition → assert normal reconcile path exercised.
- **Test:** `test_room_reconcile_sensor_shape` — verify state + all five attributes present; `would_reconcile` shape is `{entity_id: str}` for skipped entities only.
- **Test:** `test_reconcile_health_sensor_aggregates_across_rooms` — three rooms with mixed reconcile counts + one quarantined + one Auto-Recovery OFF → assert aggregated fields.
- **Test:** `test_flap_sensitivity_maps_to_const_triple` — set flow to `relaxed` → assert reconciler reads (6, 180, 900); `normal` → (4, 120, 600); `aggressive` → (3, 90, 450).
- **Test:** `test_auto_recovery_switch_restores_across_restart` — switch OFF → teardown + fresh construction → assert switch is OFF post-restart (Bug Class #52 guard: an `unavailable` last-state does NOT coerce to OFF, it falls back to the default ON; verify that path with a separately-instrumented test).
- **Test:** `test_auto_recovery_switch_unavailable_last_state_falls_back_to_on` — simulate `async_get_last_state()` returning `unavailable` → switch adopts default ON. Bug Class #52 regression guard.
- **Test:** `test_would_reconcile_populated_for_quarantined_entity` — entity in `_flapping` → `RoomReconcileSensor.would_reconcile[entity_id]` still populated (skipped for `flapping`, not for `no_opinion`); `last_skip_reason == "flapping"`.
- **Live:** as in D2.6 D2.12 live criterion — switch visible + defaults ON + survives restart + dry-run preview works.

---

## 5. Review tier

**Recommendation: Tier 3 (4 framing-disjoint reviews incl. adversarial-completeness D + live validation + README write-back).**

**Elevation from Tier 2-DB → Tier 3 (2026-07-03 revision).** The four guards added on
this revision push the change past the standing Tier-2-DB bar for three reasons that map
directly to the CLAUDE.md Tier 3 triggers:

1. **The change now threads reconcile logic through a boot-time state transition that
   is consumed by many actuator sites** (per-entity listener × N actuators × N rooms).
   D2.10 exists precisely because the resolver is a new "consume the desired state"
   site — a Bug Class #53 shape. One missing cell of the branch table = silent no-op
   on a legitimate reconcile. That's the "one missed path" failure mode Tier 3 targets.
2. **Regression-prone in an area with two prior incidents.** v4.7.19 boot-away-actuation-
   storm and June 2026 optimizer write-flood are both directly adjacent to the failure
   modes D2.7 and D2.8 defend against. Standing policy says default to elevating when a
   small surgical fix could silently break a sibling path.
3. **Safety-adjacent path.** A stale actuator left in the wrong state — a fan spinning
   in a bedroom at 3am, a bright light on during sleep — is not just a comfort defect,
   it's a trust-in-the-system defect. Cost of a missed framing > cost of a fourth
   reviewer.

**D2.12 does NOT raise the tier further.** The new surfaces (per-room RestoreEntity
switch, two dedicated diagnostic sensors, one collapsed config-flow section with a
named-bucket dropdown) are all absorbed by the existing Reviewer C framing — they are
new surfaces that must round-trip through options-flow + RestoreEntity, which is exactly
what Reviewer C's Tier-3 framing was already scoped to prove. See the extended Review C
bullet below.

**The four framings (one MUST be the adversarial completeness pass D):**

- **A — Correctness + edge cases (local).** Intent resolver branch table vs the live entry/exit
  handlers (every cell of {occupied×sleep×dark×action} must agree — this is the D2.10 gate).
  `None` semantics (no-opinion). Idempotency per `(entity, available-event)`. Arithmetic
  of debounce / rate-cap / coalesce timers. **D2.11 flap-window arithmetic** (rolling
  prune, threshold at exactly N edges, stability window zero-transition check).
  **D2.12 `flap_sensitivity` bucket mapping arithmetic** (each of the three buckets
  produces the intended triple; unset defaults to D2.11 constants).
- **B — Integration / state-machine integrity + async / lifecycle.** Listener registration /
  teardown (Bug Class #38), rebuild-hook re-arm (Bug Class #50, D2.9), interaction with
  `_skip_first_automation`, race between reconcile and a real occupancy change firing the
  canonical handler within the same tick, coalesce timer interaction with room teardown /
  reload, restart resilience (no persisted state — must work after a restart with zero
  memory of pre-restart reconciles). **D2.11 quarantine state machine** (healthy →
  quarantined → healthy transitions; release runs exactly one pass then re-enters normal
  guard chain; RAM-only across restart). **D2.12 `Auto-Recovery` switch integration**
  (guard 9 short-circuits between flap check and coalesce enqueue; `would_reconcile`
  populates unconditionally; no double-actuation when switch flips ON mid-window).
  Byte-identical behavior on the no-op path (nothing to reconcile → nothing changes).
- **C — Test authority via REAL per-site source mutation + new-surface round-trip.**
  Not aggregate monkeypatch: edit production source to bypass/neuter ONE load-bearing
  site at a time (the coalesce timer arm, the boot-settle gate check, the
  `activity_logger.log` call in place of a direct DAO write, the resolver's branch-table
  cells, **the flap-threshold check, the stability-window release gate**, **the D2.12
  `Auto-Recovery` guard-9 short-circuit, the `would_reconcile` populate call, the
  `flap_sensitivity` bucket lookup**), run the suite, confirm a SPECIFIC test fails,
  then restore. A site whose bypass leaves the suite green is untested = unacceptable.
  **New-surface round-trip:** additionally, prove that each D2.12 surface round-trips
  correctly — the `Auto-Recovery` switch survives options-flow save + restart with the
  Bug Class #52 guard (unavailable last-state → default ON); the `reconcile_advanced`
  section renders in the reconfigure flow and its `flap_sensitivity` value is read on
  the next reconciler invocation; the two new sensors register on the correct devices
  (per-room vs house-wide). Explicitly required for D2.7 (coalesce), D2.8 (zero DB
  writes), D2.9 (rebuild-hook re-arm), D2.10 (each row of the truth table), D2.11 (flap
  threshold + stability release), and D2.12 (guard 9 + would_reconcile populate + bucket
  mapping + RestoreEntity round-trip + config-flow round-trip).
- **D — Adversarial completeness / diff-blind.** Sole job: state the cycle's load-bearing
  invariant in falsifiable form (§2.1) and BREAK it. D re-enumerates the ENTIRE invariant
  surface, INCLUDING pre-existing code, not just the diff. Every flagged leak must come
  with a concrete, legal-config reachable repro. Particular focus: any egress site that
  bypasses the coalesce (D2.7), any code path that could take a synchronous DB write on
  a reconcile event (D2.8), any subscription rebuild path that could orphan the reconciler
  listener (D2.9), any branch-table cell where the resolver returns `None` but the
  canonical handler would have acted (D2.10), **any code path that could actuate — or
  attempt a service call against — a quarantined entity, or any bare-timer release
  path that could re-admit a flapping device (D2.11), any egress site that could
  dispatch a service call while `Auto-Recovery` is OFF, any path that could leave
  `would_reconcile` stale or empty when the operator is using it for dry-run preview,
  and any `AutoRecoverySwitch` restore path that could coerce an `unavailable`
  last-state to OFF (D2.12, Bug Class #52).**

Run A, B, C, D in PARALLEL — different framings can't share blind spots.

**Fix CRITICAL/HIGH from any review before deploy.** Re-verify after fix-up. If fix-up
was substantial, re-run D's completeness enumeration (a fix can reveal an N+1th site).

**Orchestrator independent verification before ship — MANDATORY.** Do not trust reviewer
summaries. Before deploy, the orchestrator personally re-greps every reconcile egress
site, every DB-adjacent call in the new module, every code path that could dispatch a
service call for a `_flapping` entity or an `Auto-Recovery`-OFF room, and re-runs a real
source mutation on the coalesce timer + the zero-write invariant + the quarantine
short-circuit + the guard-9 short-circuit.

**Operator checkpoint BEFORE deploy** (not just before build). Tier 3 changes touch the
highest-blast-radius live behavior; surface the final review outcome + the D2.10
truth-table proof and D2.8 zero-write proof and D2.11 quarantine-short-circuit proof and
D2.12 Auto-Recovery-off-suppression proof and get explicit go.

**Pre-review baseline tag (mandatory):** `git tag pre-review-v<version>` before any review fixes.

---

## 6. Out of scope (explicit)

1. **Covers** (`CONF_COVERS`). Re-asserting cover position on reconnect is dangerous
   (moving blinds while someone is near them; fighting a physical lock; missing the
   "covers stuck in egress hold" state). Will need its own design — likely guarded by
   the existing cover-automation switch + an explicit operator opt-in. Tracked in
   BACKLOG.md under the same entry for a future cycle.
2. **`CONF_CLIMATE_ENTITY`.** Setpoint / HVAC mode re-assert on reconnect is high-risk
   (fighting Better Thermostat, undoing a user setpoint, energizing during a load-shed
   window). HVAC has its own override + override-arrester machinery (`hvac_override.py`)
   that any climate-reconcile must integrate with — a separate cycle.
3. **D3 — Reload-as-recovery** (`homeassistant.reload_config_entry` on detected device
   unavailable). Operator idea; design first; not part of D2. Per-entry, rate-limited,
   opt-in.
4. **Coordinator-global batch reconcile on `EVENT_HOMEASSISTANT_STARTED`.** The
   boot-settle release + post-boot grace + coalesce already prevent a storm; we do not
   need a sweep. If demand emerges, design separately and re-tier.
5. **Operator-facing CONF_* to disable the reconciler per-room via YAML/config-entry
   data.** None added — D2.12 exposes the per-room `Auto-Recovery` switch instead, which
   is the correct URA idiom (RestoreEntity switch, mirrors `AutomationSwitch` /
   `ClimateAutomationSwitch` / `CoverAutomationSwitch`). Keeps the surface minimal per
   the operator's "small, fail-safe, additive" constraint and the v4.7.25 lesson about
   over-knob-ifying.
6. **Persisted memory of pre-restart reconciles.** Explicitly forbidden by the invariant
   — desired state is recomputed LIVE every time, never read from a snapshot. Extends to
   D2.11 flap-quarantine state (RAM-only; §3.11) and to D2.12 `RoomReconcileSensor`
   ring/`would_reconcile` (RAM-only; recomputed on next availability edge post-restart).
7. **Bare-timer auto-release from D2.11 quarantine.** Deliberately out of scope — the
   only release path is stability-proven (`RECONCILE_FLAP_STABILITY_SECONDS` continuous
   available). A timer-based auto-release would re-admit a dying device.
8. **Per-room reconcile observation-mode / shadow switch (D2.12 REJECTED).** A per-room
   `ReconcileObservationModeSwitch` was CONSIDERED and REJECTED. Observation mode is a
   COORDINATOR-level concept in URA — every existing observation switch
   (`PresenceObservationModeSwitch`, `SafetyObservationModeSwitch`, and siblings) is
   scoped to a coordinator, not to a room. Adding a per-room observation switch would
   invert that pattern and create a new class of switch nobody else has. The safe
   rollout lever is instead the manual dry-run pattern: flip `Auto-Recovery` OFF, watch
   `sensor.<room>_room_reconcile.would_reconcile` to preview what the reconciler WOULD
   do, then flip `Auto-Recovery` ON when confident. Documented here so a future reader
   does not re-propose the rejected shape.
9. **Per-room fan / humidity room-device toggles — STALE, corrected 2026-07-22.**
   This §6.9 previously claimed the operator-facing per-room switches did not exist.
   That was already stale when this plan was written: `RoomComfortFanControlSwitch`
   (switch.py:4599) and `RoomHumidityFanControlSwitch` (switch.py:4614) shipped in
   v5.6.0 (D6 bathroom-exhaust cycle) on the shared `_RoomBooleanOptionSwitch` base
   (switch.py:4546). The audit
   `docs/planning/AUDIT_fan_humidity_toggle_symmetry.md` (2026-07-22) verified this
   and identified the actual defects (HIGH per-toggle full-ROOM-reload and MEDIUM
   restore-precedence), both fixed by the fan/humidity toggle-symmetry cycle
   (build/fan-humidity-toggle-fix). Reconcile-on-return remains out of scope for
   those knobs; D2.12 still adds ONLY the reconcile-specific `Auto-Recovery` switch.
   Anchor drift for the CONF sites: `CONF_FAN_CONTROL_ENABLED` = `const.py:603`,
   `CONF_HUMIDITY_FAN_CONTROL_ENABLED` = `const.py:616` (the `:591 / :604` lines
   above have drifted since this plan was written).

---

## 7. Sequencing / build order

Post-revision, the build order is:

1. **D2.1** — reconciler class scaffold + per-room ownership wiring.
2. **D2.9** — unsub list + rebuild-hook re-arm wired BEFORE the listener is armed
   in anger (Bug Class #50 hardened from day one, not retrofitted).
3. **D2.2** — guard set (all twelve clauses of §2), including boot-settle + coalesce +
   grace + flap-quarantine + Auto-Recovery guards.
4. **D2.7** — coalesce + grace (core, lands with D2.2 so the invariant is honored on
   first arm).
5. **D2.11** — flap detector + quarantine (lands with D2.2 / D2.7 so guard 8 is honored
   from first arm; sits above coalesce in the pipeline).
6. **D2.12** — `Auto-Recovery` switch + `RoomReconcileSensor` + `ReconcileHealthSensor` +
   `reconcile_advanced` collapsed section + `flap_sensitivity` bucket dropdown +
   `would_reconcile` populate call. Lands with D2.2 / D2.11 so guard 9 is honored from
   first arm and dry-run preview is available for the pre-deploy operator checkpoint.
7. **D2.8** — zero-DB-writes invariant + static + behavioral tests (invariant enforced
   from first commit that adds a telemetry line).
8. **D2.10** — branch-table parity test (**gating** — no deploy until every cell agrees
   with the canonical handler).
9. **D2.3** — happy-path live re-assert (lights + fans) exercised through the coalesce
   pipeline.
10. **D2.4 / D2.5** — diagnostics surface + canonical log line.
11. **D2.6** — live validation post-deploy + README write-back.

D2.7, D2.8, D2.9, D2.10 are **CORE, not optional.** No partial ship: if any of the four
regresses its acceptance criteria at fix-up time, hold the deploy. D2.11 (flap detector +
quarantine) and D2.12 (observability + control surface) are first-class deliverables
whose acceptance criteria must all pass before deploy (guards 8 and 9 depend on them)
but do not carry the CORE "no partial ship" tag.

---

## 8. Plan completion tracking template (to fill at cycle close)

Per CLAUDE.md "Plan Completion Tracking" — at cycle close, account for every D2.x item:
shipped, deferred (with reason), or dropped (with reason).

| Item | Status | Notes |
|---|---|---|
| D2.1 ActuatorReconciler + listener | | |
| D2.2 Guard set tests (twelve clauses) | | |
| D2.3 Live re-assert path | | |
| D2.4 Diagnostics surface | | |
| D2.5 Canonical log line | | |
| D2.6 Live validation write-back | | |
| D2.7 Boot-settle release storm mitigation (coalesce + grace) — CORE | | |
| D2.8 Zero-DB-writes-per-reconcile invariant — CORE | | |
| D2.9 Reconciler unsub list + rebuild-hook re-arm — CORE | | |
| D2.10 Branch-table parity test — CORE, GATING | | |
| D2.11 Flap detector + quarantine | | |
| D2.12 Observability & control surface (Auto-Recovery switch + RoomReconcileSensor + ReconcileHealthSensor + reconcile_advanced section + flap_sensitivity bucket + would_reconcile) | | |
