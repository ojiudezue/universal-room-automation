> **REV 2.5 operator rulings (2026-09-30, from the 4 build reviews):** (1) house-state Sleep is used ONLY to choose night lights on entry; exit-skip, covers, fans and every other `is_sleep_mode_active` consumer stay on the clock (fixes review B M-1 covers-open-all-night and review D 07:30 lights-stay-on). (2) The manual-change hold stays ON by default in every room — declared in the invariant/README. (3) A room with its master Automation switch off skips the Away leave-on turn-off.

> **REV 2.4 (operator, 2026-09-30):** Weather-adjusted outdoor illuminance tier added to darkness fallback (Slice B′). Order: room lux → borrowed lux → operator-configured outdoor light sensor (integration-level Global Sensors, visible pre-fill from `illuminance`-platform entities) → sun elevation → False. New integration keys `CONF_OUTDOOR_LIGHT_SENSOR` + `CONF_OUTDOOR_DARK_LUX` (default 400, rung-2 config). Same `CONF_LIGHT_DARK_USE_SUN_FALLBACK` kill switch (label renamed) disables tiers 3 AND 4. No silent runtime discovery — the darkness code reads ONLY the configured field. No Sun2 dependency.
>
> **REV 2.3.2 (orchestrator, 2026-09-29):** D7 walk-through rooms is DROPPED from this build — the operator said no new timers, and REV 2.3's D7 still needs a 15 s exit cap. It was ranked lowest and droppable. Revive on operator request.

# PLANNING — Room Dialog Cleanup: Lighting Roles + Role-vs-Inventory Sweep

Card: ROOM-LIGHTING-SETUP-REDESIGN-1 (kanban.data.yaml:30559)
Author: Oji Udezue (planner)  Date: 2026-09-29
Deploy: HELD for operator.
Tier: **2-DB** (three framing-disjoint reviews) + **Tier-3 per-site mutation** on D2 (light hold), D3 (room-light switch), all URA light-emitters, and both `is_dark` sites.

## Changelog

### REV 2.3.1 — 2026-09-29 (operator clarification: vacancy applies to unautomated lights; hold ends on empty)
Operator 2026-09-29: "Even unautomated lights can be turned off after the occupancy timeout." Folded into D1 exit semantics and D2 hold lifetime. See new **"Vacancy rule"** section below Non-goals. New D2 tests: (a) unautomated hand-on light off at vacancy, (b) leave-on carve-out stays on, (c) hold cleared when room counts as empty. Verified today's exit path already unions `LIGHTS ∪ NIGHT_LIGHTS` at `actuator_reconciler.py:109`, consistent with the operator rule.

### REV 2.3 — 2026-09-29 (post REV 2 + REV 2.2 re-review)
Addresses `docs/reviews/code-review/plan_review_room_dialog_cleanup_lighting.md` findings R2-1..R2-6. Body edits, not banners.
- **R2-1 (emitter completeness + cross-coordinator self-write mark):** enumerated every URA light-writer with verdicts; introduced `URA_WRITE_CONTEXT_ID` shared stamp so the D2 listener never treats a URA-issued change as manual. See new "URA light-writer inventory" section.
- **R2-2 (drop `CONF_LIGHT_EXIT_WAIT_S`):** removed from every body site (prior-art table, consumer table, D1 field 7, D7, knob table). D7 rewritten against existing `CONF_OCCUPANCY_TIMEOUT` (const.py:398) with a per-room walk-through fraction, no new timer. Prior-art table row updated to "REUSE `CONF_OCCUPANCY_TIMEOUT`; NO new timer".
- **R2-3 (D0 counts stale/unavailable lux too):** D0 broadened. Freshness judged by **availability only** (`state in ('unavailable','unknown')`); NEVER by `last_updated` age (dark night = legitimate 0 for hours). Orchestrator measurement 2026-09-29 22:2x noted (Garage B `sensor.garage_b_protect_sensor_illuminance` unavailable at probe time; 24 dark-only rooms with lux, 1 currently unavailable; 2 no-sensor rooms confirmed).
- **R2-4 (real key name):** `CONF_LUX_ENTITY` → `CONF_ILLUMINANCE_SENSOR` (const.py:862). No pre-existing freshness helper found for lux (today's `is_dark` at automation.py:933 takes a raw float with no freshness check); freshness gate in `is_dark_effective` is NEW and availability-only.
- **R2-5 (D3 on-set = entry set):** D3 turn_on set = today's resolver `effective_entry_set()` (LIGHTS + night lights in day mode per automation.py:1051-1054), NOT `CONF_LIGHTS`.
- **R2-6 (D4 Away rewrite per REV 2.2):** D4 body rewritten. Only lights in `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` are turned off on Away, and only when the per-room `CONF_AWAY_TURN_OFF_LEAVE_ON` boolean is True (default True; kill-switch OFF preserves today). No new house-wide Away actuation. Boolean added to producer/consumer + knob tables. Tests: empty leave-on list ⇒ boolean is inert; boolean False ⇒ Away leaves exempt lights on. Boot-settle + no-flap tests narrowed to this action. **Precedence with D2 manual hold: Away wins over a manual hold, but ONLY for leave-on lights AND ONLY when `CONF_AWAY_TURN_OFF_LEAVE_ON=True`** (operator explicitly opted the exempt list into the Away sweep). Everywhere else, hold vetoes URA.
- **F6 completion (Security delegate composition):** SecurityDelegateLightsSwitch (`switch.py:4941`) is a security-tier override that takes lights over during alarms/security events — enumerated in the writer table with verdict "**exempt** from D2 hold (security supersedes user intent)"; when it releases, `light_policy_oracle` clears any hold it accidentally noted via a `release()` call at the end of the delegate window.

### REV 2 — 2026-09-29
F1-F13 fixes.

### REV 1 — 2026-09-29
Initial plan.

## Operator anchor
"Room dialog is the absolute core of URA. Right now it's a power-user mess. Features are mature so turning back to refinement is good discipline." — 2026-09-29.

## Design rule (keep)
Devices and Sensors steps ONLY **enumerate + classify**. Every **role** lives in its **behaviour step**, with pickers restricted to `LIGHTS ∪ NIGHT_LIGHTS ∪ ALERT_LIGHTS ∪ currently-stored value`, from in-flight options — never from `entry.options[CONF_LIGHTS]` alone.

## Falsifiable invariant
**Every room behaves identically until the operator changes a role, EXCEPT the declared darkness change: `turn_on_if_dark` rooms with no usable lux (no sensor, or sensor `unavailable`/`unknown`) start using sun position (P0 operator intent, per-room kill-switch available).** Discriminators:
1. Room with `turn_on_if_dark` + `CONF_ILLUMINANCE_SENSOR` available: unchanged.
2. Room with `turn_on_if_dark` + no sensor OR sensor unavailable: previously never lit; post-cycle lights at dusk. Intended.
3. Room without `turn_on_if_dark` AND without new keys: unchanged.
4. Resolver-equivalence: `effective_entry_set(cfg)` == today's set when new role lists are absent.

## Non-goals
- No new lighting effects.
- No changes to fan / cover / climate / notification behaviour beyond D8 relocation.
- **No new per-room Number/Select entities** (config-flow fields only); sole new entity is `switch.<room>_lights` (D3).
- **No new timers.** Reuse `CONF_OCCUPANCY_TIMEOUT`.
- No stored-data migration; absent new keys = today's behaviour.
- No dashboarding / load-shedding coupling.

## Vacancy rule (operator clarification 2026-09-29 — REV 2.3.1)
**Every light physically present in the room is a candidate for the vacancy turn-off, regardless of whether it appears in the on-entry picker.** The exit sweep set is:

  `vacancy_off_set = (CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS) \ CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`

This matches today's exit union at `actuator_reconciler.py:109` (verified) and extends it explicitly to lights turned on by hand that are NOT in `CONF_LIGHTS_ON_ENTRY`. A hand-switched light in an otherwise unautomated room does NOT stay on forever — after `CONF_OCCUPANCY_TIMEOUT` the room counts as empty and the sweep runs. The only carve-out is `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`.

**D2 hold lifetime — bounded by occupancy.** A manual-hold protects a person's change while the room is occupied. **When the room counts as empty, the hold is cleared** and the normal vacancy off applies. The hold does NOT persist across vacancy. The `manual_off_cooldown` (turning a light OFF by hand while occupied) still applies for its window because it protects the OFF choice against re-triggering entry, and by construction a re-triggering entry happens only while the room is occupied again. Concretely:
- Enter room, turn light ON by hand → `manual_on_hold` set.
- Room stays occupied → hold suppresses vacancy off attempts within this occupancy episode.
- Room transitions to empty (occupancy_timeout elapsed, no motion) → hold cleared, `vacancy_off_set` sweep runs, light off (unless in leave-on).
- Next entry: normal automation resumes.

This applies at BOTH exit sites (automation.py exit + actuator_reconciler.py exit union).

---

## Institutional context verified

### Design docs / prior planning
- `CLAUDE.md`, `docs/QUALITY_CONTEXT.md` (#7 stale data, #22 enum, #23 mode gate, #34 default drift, #53 emitter-miss, #63 concept-split).
- Adjacency `ROOM-DIALOGS-USABILITY-SWEEP-1` (shipped, commit `58464918d`).
- Memory: `feedback_config_first_before_code`, `feedback_label_style_guide`, `feedback_extend_existing_never_rebuild`, `feedback_marginal_benefit_pushback`, `feedback_no_restart_during_sleep`, `feedback_parent_entry_reload_watchdog_hazard`, `project_house_zones_vs_hvac_zones`.

### Code surveyed
- `config_flow.py` room path (1439/1536/1570/1717/1779; edit path 1862-2918); `VERSION=1` at :748; `async_step_migration` at :3063 integration-only; `__init__.py` has no `async_migrate_entry`.
- `automation.py`: `is_dark` :933 (`None`⇒False, no freshness check), entry ctrl :1031, entry-union `LIGHTS ∪ NIGHT_LIGHTS` day-mode :1051-1054, sleep-mode clock :903-916, sleep gate :1018-1027, legacy switch fallback :1282-1320, fan hold delegators :210-355.
- `actuator_reconciler.py`: second `is_dark` :794, entry-action :748-813, **exit union `LIGHTS ∪ NIGHT_LIGHTS`** :109 (backs the Vacancy rule above), fan self-write discrimination :628-630, manual_mode Guard 2 :496.
- `switch.py`: `ManualModeSwitch` :5199, `SecurityDelegateLightsSwitch` :4941.
- `coordinator.py`: AI-rule conflict union :1225-1236.
- `binary_sensor_control_attrs.py:28`; `aggregation.py:1428` (alert read), `aggregation.py:1468-1487` (alert emitter).
- `domain_coordinators/hvac.py:5700-5720` (night-lights reader).
- `domain_coordinators/notification_manager.py:2378-2460` (alert flash + restore).
- `domain_coordinators/safety.py:2502`, `domain_coordinators/security.py:1622` (direct `light.turn_on` service calls).
- `domain_coordinators/fan_policy_oracle.py` (reference pattern).
- `const.py`: CONF_ILLUMINANCE_SENSOR :862, CONF_LIGHTS :870, CONF_LIGHT_CAPABILITIES :870, CONF_AUTO/MANUAL_DEVICES :882-888, CONF_NIGHT_LIGHTS :897-907, CONF_ENTRY/EXIT_LIGHT_ACTION + ILLUMINANCE_THRESHOLD/BRIGHTNESS/TRANSITION :915-920, LIGHT_ACTION_* :923-927, CONF_ALERT_LIGHTS :99-100, CONF_OCCUPANCY_TIMEOUT :398.

### Prior-art scan — REUSE / BUILD

| Piece | REUSE / BUILD | Cite |
|---|---|---|
| Room lux + `is_dark` | REUSE (extend to fallback wrapper) | `automation.py:933`, `actuator_reconciler.py:794` |
| Lux entity key | REUSE `CONF_ILLUMINANCE_SENSOR` | `const.py:862` |
| Sun-position dark fallback | BUILD (thin) | HA `sun.sun.elevation`; new `is_dark_effective()` |
| Lux freshness | BUILD (availability-only) | No pre-existing helper; NEW |
| Borrow another room's lux (P1) | BUILD | new `CONF_LIGHT_DARK_LUX_SOURCE` |
| Night lights role | REUSE key, MOVE picker | `CONF_NIGHT_LIGHTS` `const.py:897` |
| Per-light entry/dark-only/leave-on-when-empty | BUILD additive (ABSENT=today) | new `CONF_LIGHTS_ON_ENTRY`, `CONF_LIGHTS_ON_ENTRY_DARK_ONLY`, `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` |
| Alert lights ride-along | REUSE, MOVE picker | `CONF_ALERT_LIGHTS` `const.py:99` |
| Light exit-wait | REUSE `CONF_OCCUPANCY_TIMEOUT` (const.py:398); **NO new timer** | operator ruling |
| Vacancy-off set (all lights minus leave-on) | REUSE today's exit union | `actuator_reconciler.py:109` |
| Per-light feature summary | READ live | `state.attributes['supported_color_modes']` + room-level `CONF_LIGHT_CAPABILITIES` |
| Light manual-hold ledger (D2) | REUSE PATTERN, BUILD module | `fan_policy_oracle.py`; NO existing light hold |
| URA-write context stamp | BUILD | new module-level `URA_WRITE_CONTEXT_ID`; every URA light-writer stamps `context=Context(id=URA_WRITE_CONTEXT_ID)` |
| Room-light switch (D3) | REUSE `switch.py` platform | new `RoomLightsSwitch` |
| House-state awareness (D4) | REUSE HouseState + sleep clock | precedence in D4 |
| Slots (D5) | EXTEND `const.py:898-907` | fixed 3 slots |
| Scenes (D6) | BUILD | config-flow fields |
| Walk-through (D7) | REUSE `CONF_OCCUPANCY_TIMEOUT` fraction; **no new timer** | operator ruling |

---

## URA light-writer inventory (R2-1)

Every code path that calls `light.turn_on` / `light.turn_off` inside URA. All URA writers stamp `Context(id=URA_WRITE_CONTEXT_ID + <writer_tag>)`. The D2 `state_changed` listener filters out any change whose `event.context.id` matches — URA-issued, not manual.

| # | Writer | File:line | Verdict |
|---|---|---|---|
| 1 | RoomAutomation entry action | `automation.py:1031` | **Respects hold** (consult before emit); URA-stamped |
| 2 | RoomAutomation exit / vacancy | `automation.py` exit path | Respects hold (but hold cleared on empty per Vacancy rule); URA-stamped |
| 3 | ActuatorReconciler entry-action | `actuator_reconciler.py:748-813` | Respects hold; URA-stamped |
| 4 | ActuatorReconciler exit-union | `actuator_reconciler.py:109` | Respects hold (post-empty); URA-stamped |
| 5 | Notification alert flash | `notification_manager.py:2378-2460` | **Exempt**; URA-stamped so restore does not open a hold |
| 6 | Aggregation alert emitter | `aggregation.py:1468-1487` | **Exempt**; URA-stamped |
| 7 | Safety emit | `safety.py:2502` | **Exempt**; URA-stamped |
| 8 | Security emit | `security.py:1622` | **Exempt**; URA-stamped |
| 9 | SecurityDelegateLightsSwitch | `switch.py:4941` | **Exempt**; on release calls `oracle.release(room)` |
| 10 | RoomLightsSwitch (D3, NEW) | `switch.py` (new) | Counts as manual via explicit `oracle.note_manual()`; URA-stamped so listener does NOT double-record |

**Discriminator test (R2-1):** an alert flash on a light in `CONF_LIGHTS` opens NO manual hold — subsequent entry/exit fire normally.

Additional emitters surfaced during build are added to this table with a verdict before the build lands.

---

## Producer / Consumer map (REV 2.3 — complete)

| Key | Producer | Consumers | Post-cycle |
|---|---|---|---|
| `CONF_LIGHTS` | Devices step `config_flow.py:1755, 2003` | `automation.py:1051-1054`, `actuator_reconciler.py:109, 748-813`, `coordinator.py:1225-1236`, `hvac.py:5700-5720` | UNCHANGED |
| `CONF_NIGHT_LIGHTS` | MOVE → Lighting step | `automation.py` night apply, `actuator_reconciler.py:109`, `coordinator.py:1231`, `hvac.py:5700-5720`, `binary_sensor_control_attrs.py:28` | picker moves; key unchanged |
| `CONF_NIGHT_LIGHT_*_BRIGHTNESS/COLOR` | MOVE → Lighting step | night apply | keys unchanged |
| `CONF_ALERT_LIGHTS` | MOVE → Lighting step | `aggregation.py:1428, 1468-1487`, `notification_manager.py:2378-2460` | picker moves; COLOR stays in Notifications |
| `CONF_AUTO_DEVICES`/`CONF_MANUAL_DEVICES`/legacy switches | MOVE → behaviour Auto/Manual sub-block | `actuator_reconciler.py` (12 refs), `automation.py:1282-1320`, `coordinator.py:1225-1236` | pickers move; keys unchanged |
| `CONF_ENTRY_LIGHT_ACTION`/`CONF_EXIT_LIGHT_ACTION` | Lighting step | `automation.py:1031`, `actuator_reconciler.py:748-813` | PRESERVED as GLOBAL fallback |
| `CONF_ILLUMINANCE_THRESHOLD` | Lighting step (config-flow field) | `automation.py:933`, `actuator_reconciler.py:794` | UNCHANGED |
| `CONF_ILLUMINANCE_SENSOR` | Sensors step (existing) | `is_dark_effective()` both sites | UNCHANGED; availability-checked in resolver |
| `CONF_LIGHTS_ON_ENTRY` (NEW) | Lighting step | `automation.py` entry, `actuator_reconciler.py` entry, `coordinator.py` AI-rule union | ABSENT = today |
| `CONF_LIGHTS_ON_ENTRY_DARK_ONLY` (NEW) | Lighting step | same | ABSENT = today |
| `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` (NEW) | Lighting step | `automation.py` exit, `actuator_reconciler.py:109` exit union, D4 Away sweep | ABSENT = today (empty carve-out) |
| `CONF_LIGHT_DARK_LUX_SOURCE` (NEW, P1) | Lighting step | `is_dark_effective()` both sites | ABSENT = today |
| `CONF_LIGHT_DARK_USE_SUN_FALLBACK` (NEW, F1 kill-switch) | Lighting step | `is_dark_effective()` | default TRUE |
| `CONF_AWAY_TURN_OFF_LEAVE_ON` (NEW, REV 2.2) | Lighting step; enabled only when leave-on non-empty | `automation.py` exit (Away branch), `actuator_reconciler.py` exit union | default TRUE; inert when leave-on empty |
| `CONF_LIGHT_MANUAL_ON_HOLD_S`/`_OFF_COOLDOWN_S` (NEW, D2) | Lighting step (config-flow) | `light_policy_oracle` | ABSENT = module const default |
| `CONF_LIGHTS_GUEST_MODE` (NEW, D4) | Lighting step | entry/exit path | default `normal` = today |
| `CONF_ROOM_WALK_THROUGH` + `_DWELL_S` (NEW, D7) | Lighting step | entry/exit; reuses `CONF_OCCUPANCY_TIMEOUT` | default False |

---

## Deliverables

### D0 — Blast-radius probe (measure before build)
**Scope:** Read-only script over `/Users/okosisi/ha-config/.storage/core.config_entries` (Samba mount) enumerating URA room entries; for each: `entry_light_action`, `CONF_ILLUMINANCE_SENSOR` set? (Y/N), and — via live read of the sensor's `state` — whether it is `unavailable`/`unknown`. **AFFECTED** if `turn_on_if_dark` AND (no sensor OR sensor currently `unavailable`/`unknown`).

**Kill-switch:** `CONF_LIGHT_DARK_USE_SUN_FALLBACK` per-room, default TRUE. Off ⇒ preserves `is_dark(None)=False`.

**Freshness rule (R2-3):** availability-only. `state in ('unavailable', 'unknown')` ⇒ unusable. `last_updated` age is NEVER used — a dark night can legitimately hold a fresh 0.

**Prior measurement (2026-09-29 22:2x):** 24 dark-only rooms with lux (1 currently unavailable: Garage B `sensor.garage_b_protect_sensor_illuminance`); 2 no-sensor rooms. Combined AFFECTED = 3 today; fluctuates as sensors drop/return.

**Acceptance:** `docs/planning/AUDIT_sun_fallback_blast_radius.md` committed with the AFFECTED list. Operator sign-off gates D1 build.

### D1 — Lighting step
**Fields (in order):**
1. Read-only: per-light lines from `state.attributes['supported_color_modes']`; one room-level line from `CONF_LIGHT_CAPABILITIES`.
2. `CONF_LIGHTS_ON_ENTRY`.
3. `CONF_LIGHTS_ON_ENTRY_DARK_ONLY` (subset).
4. `CONF_NIGHT_LIGHTS` (moved).
5. `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`.
6. `CONF_ALERT_LIGHTS` (moved).
7. `CONF_ILLUMINANCE_THRESHOLD` (unchanged; config-flow int).
8. `CONF_LIGHT_DARK_LUX_SOURCE` (optional entity).
9. `CONF_LIGHT_DARK_USE_SUN_FALLBACK` (bool, default TRUE).
10. `CONF_AWAY_TURN_OFF_LEAVE_ON` (bool, default TRUE — REV 2.2; **greyed/inert when field 5 empty**).

Picker `include_entities` = `LIGHTS ∪ NIGHT_LIGHTS ∪ ALERT_LIGHTS ∪ currently-stored value`, from in-flight flow state.

**Exit semantics (REV 2.3.1):** the vacancy-off set is `(CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS) \ CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`. The on-entry picker does NOT restrict what gets turned off — hand-switched lights are swept too. Field 5 is the only carve-out. Help text on field 2 says so.

**`is_dark_effective(cfg, hass)` order:**
1. Read entity `cfg[CONF_ILLUMINANCE_SENSOR]`. If state not `unavailable`/`unknown`, compare to `CONF_ILLUMINANCE_THRESHOLD`.
2. Else read `cfg[CONF_LIGHT_DARK_LUX_SOURCE]` if set; same availability check.
3. Else if `CONF_LIGHT_DARK_USE_SUN_FALLBACK`: `sun.sun.attributes['elevation']` < `SUN_DARK_ELEVATION_DEG` (module const, default -6.0, civil dusk).
4. Else: False (preserves today).

Wired at BOTH `automation.py:933` and `actuator_reconciler.py:794`.

**Acceptance:**
- Verify: options-flow shows the 10 fields; Devices no longer shows Night Lights / role pickers; Notifications no longer shows Alert Lights picker (color stays).
- Test: **resolver-equivalence** — `effective_entry_set(cfg)` matches today for 3 fixtures.
- Test: F5 round-trip — night light NOT in `CONF_LIGHTS` saves and reloads without dropping.
- Test: **R2-3 discriminator** — no-sensor + `turn_on_if_dark` + sun<-6° ⇒ True; sensor `unavailable` ⇒ True; sensor=`5`, threshold=`50` ⇒ True via lux; sensor=`500`, threshold=`50` ⇒ False.
- Test: kill-switch OFF ⇒ False in all fall-through cases.
- Live: D0 AFFECTED rooms light at dusk; kill-switch OFF reverts.

### D2 — Respect manual light changes
**Verified:** no existing light hold ledger. Related: `ManualModeSwitch` (Guard 2 `actuator_reconciler.py:496`), `SecurityDelegateLightsSwitch` (`switch.py:4941`), fan self-write discrimination (`actuator_reconciler.py:628-630`).

**Scope:** New `light_policy_oracle.py` mirroring `fan_policy_oracle.py`: per-room `asyncio.Lock`; `manual_off_cooldown_until`, `manual_on_hold_until`; consult→emit→note; `note_manual(room, kind)` explicit; `release(room)` clears (used by Security delegate on release AND by the vacancy transition, REV 2.3.1).

**Every URA-issued `light.turn_on/off` stamps `Context(id=URA_WRITE_CONTEXT_ID + <writer_tag>)`.** D2 `state_changed` listener (filter: `entity_id in CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`, from `RoomAutomation.async_added_to_hass`) inspects `event.context.id`: URA-stamped ⇒ ignore; else ⇒ open hold.

**Hold lifetime (REV 2.3.1):** `manual_on_hold` is bounded by occupancy — on the room's transition to empty (occupancy_timeout elapsed) the oracle calls `release(room)` and the vacancy sweep runs. `manual_off_cooldown` still applies for its window (it protects the OFF against re-triggering entry; re-entry re-arms occupancy).

**Composition:**
- `ManualModeSwitch`: unchanged veto; disjunctive with the light hold.
- `SecurityDelegateLightsSwitch`: security override; writes exempt via URA-stamp; on release calls `oracle.release(room)`.
- Fan self-write pattern upgraded to context-id form for lights (cross-coordinator writes require context-id, R2-1). Fan side unchanged this cycle.

**Knobs:** `CONF_LIGHT_MANUAL_ON_HOLD_S` (default 3600, capped by occupancy), `CONF_LIGHT_MANUAL_OFF_COOLDOWN_S` (default 900) — config-flow fields; module const defaults.

**Acceptance:**
- Test: external ON while occupied ⇒ vacancy off suppressed WITHIN this occupancy episode; on transition to empty, hold cleared and sweep off (REV 2.3.1 test (c)).
- Test: external OFF while occupied ⇒ next entry within cooldown skips re-trigger.
- Test: `manual_mode=ON` + light hold ⇒ both block; disabling one keeps the other.
- Test: D3 toggle ⇒ marked manual via `note_manual()` (not via listener).
- Test: URA entry write ⇒ NOT marked manual (URA-stamp filtered).
- **Test (R2-1 discriminator):** alert flash on entity in `CONF_LIGHTS` ⇒ NO hold opened.
- Test: Security delegate seize + release ⇒ no residual hold.
- **Test (REV 2.3.1 (a)):** light NOT in `CONF_LIGHTS_ON_ENTRY`, turned on by hand, room empties → light off (vacancy sweep covers non-entry lights).
- **Test (REV 2.3.1 (b)):** same light additionally in `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` → stays on after empty.
- **Test (REV 2.3.1 (c)):** `manual_on_hold` active, occupancy transition to empty → hold cleared, light off (unless in leave-on).
- **Per-site mutation (Tier 3):** neuter each of the 10 URA writers in turn — specific test fails per writer.
- Live: `sensor.<room>_light_manual_hold_remaining_s` reflects hold; entry/exit honour it; hold clears on empty.

### D3 — URA room-light switch
**Scope:** `switch.<room>_lights` per room. `turn_on` → `oracle.actuate` → apply current-slot brightness/colour to **`effective_entry_set()`** (LIGHTS + night lights in day-mode per `automation.py:1051-1054`; R2-5), NOT `CONF_LIGHTS`. `turn_off` → `oracle.actuate` → all room lights off (i.e. `vacancy_off_set` ignoring leave-on, because the operator explicitly said off). Both call `oracle.note_manual()`.

Distinct entity from `ManualModeSwitch` and `SecurityDelegateLightsSwitch`.

**Acceptance:**
- Verify: entity exists per room; state = "any room light on".
- Test: `turn_on` set equals `effective_entry_set()` for current mode (day vs sleep).
- Test: `turn_off` clears every room light regardless of leave-on (explicit operator intent).
- Test: toggling sets the hold ledger via `note_manual`.
- Test: no entity_id collision with manual_mode or security-delegate.
- Live: Lovelace toggle honours hold on subsequent presence changes.

### D4 — House-state awareness (REV 2.2 rewrite)
**Precedence:** `is_sleep_mode_active` (clock, `automation.py:903-916`) OR HouseState=Sleep ⇒ Sleep semantics. Disagreement ⇒ Sleep wins.

**Semantics:**
- **HouseState=Away (REV 2.2):** turn off ONLY entities in `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`, and ONLY when per-room `CONF_AWAY_TURN_OFF_LEAVE_ON=True` (default True). Boot-settle: skip within 60s (module const) of `homeassistant_started`. Precedence vs D2 hold: **Away wins over a manual hold for the leave-on list when the boolean is True**; elsewhere hold vetoes URA.
- **HouseState=Sleep OR sleep-clock:** only `CONF_NIGHT_LIGHTS` may turn on at entry; others left on only per `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` if already on.
- **HouseState=Guest:** `CONF_LIGHTS_GUEST_MODE`: `normal` (default), `off`, `night_lights_only`.

**Acceptance:**
- Test: Away + True + non-empty leave-on ⇒ leave-on off; others untouched.
- Test: Away + True + **empty** leave-on ⇒ inert.
- Test: Away + False ⇒ Away leaves exempt on.
- Test: Away + True + leave-on light under manual hold ⇒ Away wins.
- Test: no-flap — Home→Away→Home within 5s ⇒ no double emit.
- Test: boot-settle — Away pulse within 60s of start suppressed.
- Test: Sleep matrix; Guest × 3.
- Live: Away with leave-on=`[light.porch]` and True ⇒ `light.porch` off; others unaffected.

### D5 — Time-of-day slots
Fixed 3 slots: Day / Evening / Sleep. Per-slot `brightness_pct` + `color_kelvin` = config-flow fields. Boundaries per-room time fields (defaults sunset / sleep-clock window).
**Acceptance:** injected-clock tests per slot; live check colour at known time.

### D6 — Scenes per slot
Optional `CONF_LIGHT_SCENE_DAY`/`_EVENING`/`_SLEEP` config-flow entity_ids (scene domain). When set, entry calls `scene.turn_on` instead of computing brightness/colour.
**Acceptance:** injected clock; scene set for Evening + clock in Evening ⇒ scene called; brightness path skipped.

### D7 — Walk-through rooms (droppable, no new timer)
Reuses `CONF_OCCUPANCY_TIMEOUT` (`const.py:398`).
- `CONF_ROOM_WALK_THROUGH` (bool, default False).
- `CONF_ROOM_WALK_THROUGH_DWELL_S` (int, default 5) — MINIMUM entry dwell to trigger lights (threshold, not timeout).
- When True, exit uses `min(CONF_OCCUPANCY_TIMEOUT, 15s module const cap)`.

**Acceptance:** entry dwell < threshold ⇒ no lights; exit fires faster when True. Live: hallway lights off soon after vacancy.
**Drop criteria:** if D2 or D8 grow, drop and re-card WALK-THROUGH-ROOMS-1.

### D8 — Role-vs-inventory sweep + strings
1. Sweep every `async_step_*` in `config_flow.py:1862-2918` covering `EntitySelector`, `cv.multi_select`, boolean toggles. Explicit: Night Lights, Alert Lights, Auto-On/Off Devices, Auto-Off-Only Devices, Auto Devices, Manual Devices, Auto Switches, Manual Switches.
2. NO stored-data migration. Absent new keys ⇒ today's behaviour.
3. Strings updated in `strings.json` + `translations/en.json`.

**Acceptance:** resolver-equivalence for all four sets when new keys absent; options round-trip preserves values outside `CONF_LIGHTS`; live grep confirms role sets match pre-cycle.

---

## Knob-rung summary

| Knob | Rung | Reason |
|---|---|---|
| `SUN_DARK_ELEVATION_DEG` | module const | safety bound |
| `CONF_ILLUMINANCE_THRESHOLD` | config-flow field | unchanged |
| Light manual hold / cooldown | config-flow + module const default | fan-oracle parallel |
| D5 slot brightness / colour / boundaries | config-flow | one writer per value |
| D6 scenes | config-flow | structural |
| D7 walk-through bool + entry dwell | config-flow | structural (no new timer) |
| D7 walk-through exit cap (15s) | module const | safety cap |
| D4 Away boot-settle window | module const | safety window |
| `CONF_AWAY_TURN_OFF_LEAVE_ON` | config-flow | operator opt-in |
| `URA_WRITE_CONTEXT_ID` | module const | cross-coordinator self-write mark |

Zero inline literals. **Only new entity this cycle: `switch.<room>_lights` (D3).**

---

## Tier + review plan

- **Tier 2-DB** three framing-disjoint reviews:
  - **A** correctness + resolver-equivalence + edge cases (D1, D4, D5-D8, Vacancy rule).
  - **B** async / lifecycle / race / restart (D2 oracle, D3, D4 boot-settle, D2 listener + context-id filter, hold-clear-on-empty).
  - **C** cross-coordinator ripple + writer inventory + HouseState precedence + Sleep-clock precedence + hold-vs-Away precedence.
- **Tier-3 per-site mutation** on: D2 (all 10 writers in inventory), D3, both `is_dark` sites, AND the vacancy hold-clear seam.
- **Plan review (Tier 2-DB) on REV 2.3.1:** ONE adversarial pass; reviewer re-greps writer inventory, verifies `CONF_ILLUMINANCE_SENSOR` name, verifies `CONF_LIGHT_EXIT_WAIT_S` fully removed, verifies R2-6 D4 rewrite, verifies REV 2.3.1 exit-set formula matches `actuator_reconciler.py:109`.
- **Live validation:** D0 operator sign-off BEFORE D1 build. README validation table records D0 AFFECTED list (incl. Garage B when its sensor is unavailable) + one kill-switch-off room + one Away leave-on test + one hand-on-vacancy-off test (REV 2.3.1 (a)).

---

## Zone / House dialog cleanup — problem list (separate cards)

**Zone (`ZONE-DIALOGS-CLEANUP-1` exists, kanban.data.yaml:30571):** enumeration vs role blur; HVAC-zone vs house-zone label ambiguity; presence sources mixed with presence behaviour; duplicated room-level fields without override semantics.

**House (needs new `HOUSE-DIALOGS-CLEANUP-1`):** flat surface for notifications / quiet-hours / guest / person / device_tracker; energy tier knobs mixed with schedules; nerd-word labels; reload-hazard warnings not surfaced.

---

## Deferred / not done
- D5 slot count > 3.
- Adaptive-lighting integration.
- Zone / House dialog cleanups.
- D7 walk-through droppable per criteria.
- Stored-data migration (F4).
- Lux `last_updated` freshness helper (availability-only per R2-3).
