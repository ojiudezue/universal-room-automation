# PLANNING — Room Dialog Cleanup: Lighting Roles + Role-vs-Inventory Sweep

Card: ROOM-LIGHTING-SETUP-REDESIGN-1 (kanban.data.yaml:30559)
Author: Oji Udezue (planner)  Date: 2026-09-29
Deploy: HELD for operator.
Tier: **2 overall** (D8 migration and D2 hold semantics elevate). D3 (URA room-light switch) is Tier 2 on its own; D2/D3 pair reviewed together with framings (A) correctness + edge cases, (B) async/lifecycle/race, (C) migration byte-identity.

## Operator anchor
"Room dialog is the absolute core of URA. Right now it's a power-user mess. Features are mature so turning back to refinement is good discipline." — 2026-09-29.

## Design rule (keep)
Devices and Sensors steps ONLY **enumerate + classify** (incl. auto-detected features). Every **role** ("which ones should URA do X with") lives in its **behaviour step**, with pickers restricted to entities enumerated upstream. This exposes the existing violations we are moving.

## Falsifiable invariant (Tier-2 anchor)
After migration, **every room behaves identically until the operator changes a role**. Falsification observable: for any room, diff of (a) actuation-decisions log and (b) rendered options-flow schema pre- vs post-deploy shows only key-name renames and (allowed) newly-defaulted keys; no behaviour delta on entry/exit/vacancy, night-mode, alert, or manual-hold paths.

Discriminating observation: a room configured today with `night_lights=[X,Y]`, `entry_light_action=turn_on_if_dark`, `manual_devices=[Z]` still turns on the same set at entry, and still routes Z through manual on the first post-restart entry. A room with none of these keys shows the new pickers empty with the same defaults.

## Non-goals
- No new lighting effects (colour cycling, animations, adaptive-lighting integration).
- No changes to alert-light behaviour (only relocation to the Lighting step; ride-along).
- No changes to fan / cover / climate / notification steps beyond D8 role-vs-inventory relocation, if any is found.
- No dashboarding work; strings.json/translations updated only for renamed/moved fields.
- No load-shedding or energy-tier coupling (out of scope; separate cards).

---

## Institutional context verified

### Design docs / prior planning
- `CLAUDE.md` — "Numbers Get Knobs", "Institutional Context First", "Config-First", "Marginal-benefit pushback", "Extend existing never rebuild", plan-review tiering, prior-art scan rule (all applied below).
- `docs/QUALITY_CONTEXT.md` — bug classes #7 (stale data source), #22 (enum mismatch), #23 (observation-mode gating), #34 (options-flow default drift), #53 (computed-but-not-consumed), #63 (coincidental-equality masking concept split). D8 migration is the classic #34 surface.
- Adjacency card `ROOM-DIALOGS-USABILITY-SWEEP-1` — wording-only sweep, already shipped/held (climate strings merged, commit `58464918d`). This card is structural, not wording. Wording touch-ups here are limited to fields that move.
- No prior planning doc found on light manual-hold. Fan manual-hold is the reference design (see D2).

### Code surveyed end-to-end during scoping
- `custom_components/universal_room_automation/config_flow.py` — all `async_step_*` room path (:1439 room_setup → :1536 room_class → :1570 sensors_confirm → :1717 devices_confirm → :1779 room_summary; edit path :1862 sensors → :1970 devices → :2079 night_light_detail → :2112 cover_behavior → :2193 automation_behavior → :2246 chaining → :2630 climate → :2797 fan_speeds → :2824 sleep_protection → :2863 energy → :2918 notifications).
- `custom_components/universal_room_automation/automation.py` — `is_dark` :933, entry-light controller :1031, fan manual-hold ledger :210-355 (delegates to `fan_policy_oracle`).
- `custom_components/universal_room_automation/const.py` — CONF_LIGHTS :870, CONF_LIGHT_CAPABILITIES :870, CONF_AUTO_DEVICES/MANUAL_DEVICES :884-885, CONF_NIGHT_LIGHTS + brightness/colour block :897-907, CONF_ENTRY_LIGHT_ACTION / EXIT_LIGHT_ACTION / ILLUMINANCE_THRESHOLD / LIGHT_BRIGHTNESS_PCT / LIGHT_TRANSITION_ON/OFF :915-920, LIGHT_ACTION_* enum :923-927, CONF_ALERT_LIGHTS :99-100.
- `custom_components/universal_room_automation/domain_coordinators/fan_policy_oracle.py` — the reference oracle for manual-hold semantics; INV-FLA claim (fan-layer authority) documents the per-room lock + consult→emit→note pattern that D2/D3 must mirror if a light hold is introduced.
- `custom_components/universal_room_automation/actuator_reconciler.py`, `switch.py`, `coordinator.py` — verify no reader hard-codes any CONF_* being renamed (see D8 producer/consumer table).
- `strings.json` / `translations/en.json` — labels/descriptions for every step touched.

### Prior-art scan — REUSE vs BUILD per proposed piece

| Proposed piece | REUSE / BUILD | Cite |
|---|---|---|
| Room lux read + is_dark() | REUSE | `automation.py:933` `is_dark()`; `STATE_ILLUMINANCE` feed at `:1031` |
| Sun position dark fallback | BUILD (thin) | No sun.sun read in room-lights path. HA `sun.sun` + `sun_state` attribute; wrap in `automation.py::is_dark_effective()` reading room-lux first, then sun. |
| Borrow another room's lux sensor (P1) | REUSE feed | `CONF_LUX_ENTITY` already selectable per room (see `config_flow.py` sensors step); D1 lighting step exposes an optional override picker that writes a new `CONF_LIGHT_DARK_LUX_SOURCE` consumed by `is_dark_effective()`. |
| Night lights role (already exists) | REUSE key | `CONF_NIGHT_LIGHTS` at `const.py:897`; MOVE the picker from Devices (`config_flow.py:2010`) to the Lighting behaviour step. Storage key unchanged. |
| Entry / exit / dark-only per-light role pickers | BUILD (additive) | Today a single global `CONF_ENTRY_LIGHT_ACTION` enum governs ALL room lights; new per-light role lists override the global (see D1 migration). |
| "Leave on when empty" exceptions list | BUILD | New `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: list[entity_id]`; consumed by the exit path (extend `_run_exit_light_action`). |
| Alert lights (ride-along) | REUSE | `CONF_ALERT_LIGHTS` `const.py:99`; MOVE the picker from Notifications step (`config_flow.py:3034`) to a small "alert" block in the Lighting step. Notifications step keeps the alert-COLOR knob. |
| One wait time (+ optional night) | REUSE | Exit-vacancy wait already exists in automation behaviour. Consolidate to a single `CONF_LIGHT_EXIT_WAIT_S` + optional `CONF_LIGHT_EXIT_WAIT_NIGHT_S`; deprecate any duplicates found in the sweep. |
| Read-only per-light feature summary | REUSE | `CONF_LIGHT_CAPABILITIES` `const.py:870`; already auto-detected. Render inline in the step description (HA config-flow `description_placeholders`). |
| Light manual-hold ledger (D2) | REUSE PATTERN, BUILD MODULE | `fan_policy_oracle.py:1-40` INV-FLA + `automation.py:210-355` delegating properties. Verified: **no existing light manual-hold** (grep `manual_hold` returns fan sites only). If D2 is greenlit → BUILD `light_policy_oracle` mirroring `fan_policy_oracle`. |
| URA room-light switch (D3) | REUSE platform | `switch.py` already hosts per-room switches; add one `RoomLightsSwitch` per room. Its `async_turn_on/off` routes through `light_policy_oracle.actuate()` and marks the change as manual (D2 hook). |
| House-state awareness (D4) | REUSE | HouseState + presence/guest already gate other coordinators. Verify current lighting reads (grep `HOUSE_STATE_` in `automation.py`). If gap: extend entry/exit path to consult HouseState (Away → all off, Sleep → night lights only, Guest → per-room override list). |
| Time-of-day brightness / colour (D5) | REUSE + EXTEND | `const.py:898-901` night-light day/sleep block; extend to N named slots (default: Day / Evening / Sleep) with brightness+colour per slot. |
| Scenes per slot (D6) | BUILD | Optional `CONF_LIGHT_SCENE_<SLOT>: scene_entity`; when set, entry action calls `scene.turn_on` instead of computing brightness/colour. |
| Walk-through rooms (D7, droppable) | BUILD | New per-room boolean `CONF_ROOM_WALK_THROUGH` + shortened exit wait; feeds `_run_exit_light_action`. |

### Memory bodies pulled
- `feedback_config_first_before_code` — D1's darkness knob (borrowed lux) is a picker, not code; D5 brightness is knob-tier (module const → operator entity ladder as appropriate).
- `feedback_label_style_guide` — plain labels, ≤3 words; no "hysteresis", "provenance", etc.
- `feedback_configurability_clarity` — named-bucket dropdowns for role, not raw numbers.
- `feedback_extend_existing_never_rebuild` — CONF_NIGHT_LIGHTS / CONF_ALERT_LIGHTS / CONF_LIGHT_CAPABILITIES all reused; deltas are additive.
- `feedback_do_robust_fix_not_bandaid_and_card` — migration is done inline, not carded.
- `feedback_marginal_benefit_pushback` — D7 walk-through is droppable if scope crowds; D6 scenes gated on D5 shipping first.

---

## Producer / Consumer map for every moved or renamed key

D8 correctness depends on this table being complete. Reviewer re-runs each grep.

| Config key | Producer (writer) | Current consumer(s) | Post-cycle action |
|---|---|---|---|
| `CONF_NIGHT_LIGHTS` | Devices step `config_flow.py:2010` | `automation.py` entry/exit path + `_run_night_light_*` | MOVE producer to Lighting step; key unchanged; consumers untouched. |
| `CONF_NIGHT_LIGHT_*_BRIGHTNESS/COLOR` | night_light_detail step `:2079-2101` | `automation.py` night-light apply | MOVE producer into Lighting step (fold sub-step in); keys unchanged for now (D5 renames later). |
| `CONF_ALERT_LIGHTS` | Notifications step `:3034` | Alert-lighting emitter in automation / notifications | MOVE picker to Lighting step; keep COLOR knob in Notifications; key unchanged. |
| `CONF_AUTO_DEVICES` / `CONF_MANUAL_DEVICES` | Devices step `:2065` | `actuator_reconciler.py`, `automation.py` | MOVE role pickers to a new "Auto/Manual" sub-block in behaviour step; keep enumeration (raw entity list) in Devices only if still needed after D8 sweep, else drop. Full consumer grep required in D8. |
| `CONF_AUTO_SWITCHES` / `CONF_MANUAL_SWITCHES` | Devices step (legacy) | Same as above (legacy) | Same treatment; legacy keys preserved by migration. |
| `CONF_ENTRY_LIGHT_ACTION` / `CONF_EXIT_LIGHT_ACTION` | Automation behaviour step | `automation.py:1031` entry controller + exit controller | Preserved as GLOBAL fallback; new per-light role lists override when non-empty. |
| `CONF_ILLUMINANCE_THRESHOLD` | Automation behaviour step | `automation.py:933 is_dark()` | Preserved; darkness fallback order documented in D1 (room lux → sun position → borrowed lux). |
| `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` (NEW) | Lighting step | Exit path (extend `_run_exit_light_action`) | New; default empty ⇒ no behaviour change. |
| `CONF_LIGHT_DARK_LUX_SOURCE` (NEW, P1) | Lighting step | `is_dark_effective()` (new wrapper around `is_dark`) | New; default None ⇒ existing lux path unchanged. |
| `CONF_LIGHT_EXIT_WAIT_S` / `_NIGHT_S` | Lighting step | Exit vacancy timer | Consolidate any duplicate wait knobs found in D8. |

**Migration rule (applies to every MOVE row):** storage key is unchanged; only the step that renders the picker moves. Options-flow readers must be enumerated pre-deploy — if any reader keys off "step position" rather than "config key", that reader is broken and gets fixed inline (Bug Class #34 hazard).

---

## Deliverables

### D1 — Lighting step: role pickers + one wait + read-only feature summary; darkness fallback
**Scope:** New / restructured behaviour sub-step "Lighting" (extracted from the current global automation-behaviour step). Fields, in order:
1. Read-only description block: bulleted per-light summary (from `CONF_LIGHT_CAPABILITIES`): `light.foo — brightness+colour`.
2. `CONF_LIGHTS_ON_ENTRY: list[entity_id]` — picker limited to enumerated `CONF_LIGHTS`.
3. `CONF_LIGHTS_ON_ENTRY_DARK_ONLY: list[entity_id]` — subset of the above.
4. `CONF_NIGHT_LIGHTS: list[entity_id]` (moved).
5. `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY: list[entity_id]` — "exceptions" for exit.
6. Alert-lights ride-along: `CONF_ALERT_LIGHTS` picker (moved).
7. `CONF_LIGHT_EXIT_WAIT_S: int` (seconds) — knob rung: **operator entity (Number)** — legitimate tuning knob.
8. `CONF_LIGHT_EXIT_WAIT_NIGHT_S: int | None` — optional override.
9. `CONF_ILLUMINANCE_THRESHOLD: int` — knob rung: **operator entity (Number)**. Config-flow shows current live value.
10. `CONF_LIGHT_DARK_LUX_SOURCE: entity_id | None` (P1) — borrow another room's lux; **config-flow picker only** (not an entity).
11. Sun-position darkness fallback: **module constant** `SUN_DARK_ELEVATION_DEG = -6.0` (civil dusk) in `const.py` — knob rung: **module constant** (safety/coverage bound; changing it should require review).

Darkness evaluation order (`is_dark_effective`): (a) room lux if `CONF_LUX_ENTITY` present and fresh, else (b) borrowed lux if `CONF_LIGHT_DARK_LUX_SOURCE` set and fresh, else (c) sun.elevation < `SUN_DARK_ELEVATION_DEG`. "Fresh" = the same staleness rule already applied to room lux (Bug Class #7).

**Acceptance:**
- Verify: opening a room's options flow shows the Lighting step with the fields above; Devices step no longer renders Night Lights or role pickers.
- Verify: per-light feature summary lists every entity in `CONF_LIGHTS` with its capability.
- Sensor: `binary_sensor.<room>_is_dark` (extend existing if present, otherwise add) reflects `is_dark_effective()`.
- Test: `test_is_dark_effective` covers 3 branches (lux fresh, lux stale + sun below, lux stale + sun above).
- Live: on a room with sun below horizon and lux entity `unavailable`, entry action fires the "dark" branch; on a room with lux=200 and threshold=100, does not.

### D2 — Respect manual light changes
**Prerequisite verification (do FIRST):** grep the tree for any light manual-hold. Confirmed absent (`Grep 'manual|hold|override' automation.py` returns fan sites only; `switch.py`, `actuator_reconciler.py` show only fan/hvac hold refs). Verdict: **BUILD, mirroring fan design.**
**Scope:** New `light_policy_oracle.py` mirroring `fan_policy_oracle.py`: per-room `asyncio.Lock`, `manual_off_cooldown_until`, `manual_on_hold_until`, consult→emit→note pattern. RoomAutomation gains `_light_manual_off_until` / `_light_manual_on_until` @property delegators. Every URA-issued `light.turn_on` / `light.turn_off` in `automation.py` wraps in `async with oracle.actuate(...)`. Wall-switch / physical / HA-issued light state changes are captured via `state_changed` listener (already present for other purposes; extend) and call `oracle.note_external_change()`, setting the appropriate hold.
**Knobs:** `CONF_LIGHT_MANUAL_ON_HOLD_S` (default 3600), `CONF_LIGHT_MANUAL_OFF_COOLDOWN_S` (default 900). Rung: **module const** for defaults, **operator entity** for per-room override (matches fan pattern).
**Acceptance:**
- Test: turning on a light externally while the room is empty prevents the next vacancy exit from turning it off, until hold expires.
- Test: turning off a light externally while occupied prevents the next entry from re-triggering it, until cooldown expires.
- Live: manually toggle a room light; observe `sensor.<room>_light_manual_hold_remaining_s` (new) is non-zero; verify entry/exit path respects it.

### D3 — URA room-light switch
**Scope:** One `switch.<room>_lights` per room. `turn_on` → oracle.actuate → apply the room's current-slot brightness/colour to `CONF_LIGHTS_ON_ENTRY`; `turn_off` → oracle.actuate → turn off all room lights. Both are counted as MANUAL by D2 (they DO update the hold ledger — this is the "mediated" semantics the operator specified).
**Acceptance:**
- Verify: `switch.<room>_lights` exists per room; state reflects "any light on".
- Test: toggling the switch sets the manual-hold ledger (unlike direct HA-issued lights, which set only for external changes — the URA switch is explicitly operator intent).
- Live: toggle the switch from Lovelace; entry/exit path treats subsequent presence changes as manual for the hold duration.

### D4 — House-state awareness for lights
**Verification first:** grep `HOUSE_STATE_` in `automation.py` and `actuator_reconciler.py`. Gap enumeration goes into the plan-review pass.
**Scope:** Extend entry/exit path: HouseState=Away ⇒ all room lights off (ignore role pickers); Sleep ⇒ only `CONF_NIGHT_LIGHTS` may turn on, everything else respects "leave on when empty" only if already on; Guest ⇒ per-room `CONF_LIGHTS_GUEST_MODE` (new, default = "normal"; alt values "off" / "night_lights_only") governs.
**Acceptance:** Test the 3x3 matrix (Home/Away/Sleep × entry/exit/nothing). Live: transition HouseState to Sleep; entry to a non-night-light room activates night lights only.

### D5 — Time-of-day brightness / colour slots
**Scope:** Extend `const.py:898-907` night-light day/sleep block into a slotted table: Day / Evening / Sleep (default 3 slots). Per-slot `brightness_pct` and `color_kelvin`. Slot boundaries default to `sun_below_horizon` and `bedtime` (already known). Applies to entry action.
**Knobs:** Slot boundaries = **operator entity (time)**. Per-slot brightness/colour = **operator entity (Number/Select)**. Slot names = module const (fixed set).
**Acceptance:** Test that entry action at 14:00 uses Day, at 20:00 uses Evening, at 23:30 uses Sleep. Live: verify colour_kelvin matches.

### D6 — Scenes per slot (pair with D5)
**Scope:** Optional `CONF_LIGHT_SCENE_DAY / _EVENING / _SLEEP: scene_entity | None`. When set for the current slot, entry action calls `scene.turn_on` instead of computing brightness+colour.
**Acceptance:** With a scene set for Evening, entry at 20:00 calls the scene service; brightness/colour path skipped. Live: HA logbook shows the scene call.

### D7 — Walk-through rooms (droppable)
**Scope:** New `CONF_ROOM_WALK_THROUGH: bool` (default False). When True, `CONF_LIGHT_EXIT_WAIT_S` is bypassed and exit fires immediately on vacancy; also entry action is gated by a minimum-dwell (default 5s) to avoid flashing on pass-through.
**Knobs:** Bool + one dwell number. Rung: **config-flow field** (structural per-room).
**Acceptance:** Test both bypass paths. Live: hallway configured walk-through — lights off within seconds of vacancy.
**DROP CRITERIA:** If build-time reveals D2 or D8 required more churn than budgeted, D7 is dropped and re-carded.

### D8 — Role-vs-inventory sweep of other room steps + one-time migration
**Scope:**
1. **Enumerate ALL role-vs-inventory violations** across every room step in `config_flow.py` (not just the ones the operator called out). Method: grep for `EntitySelector` inside every `async_step_*` handler in the room path; each usage that is a role picker (rather than a pure inventory picker) is a violation candidate. Deliverable: table with `step`, `field`, `verdict` (KEEP as inventory / MOVE to behaviour step). Known candidates from initial scoping:
   - `CONF_NIGHT_LIGHTS` in Devices → move (D1).
   - `CONF_AUTO_DEVICES` / `CONF_MANUAL_DEVICES` / `CONF_AUTO_SWITCHES` / `CONF_MANUAL_SWITCHES` in Devices → move to behaviour "Auto/Manual" sub-block.
   - `CONF_ALERT_LIGHTS` in Notifications → move to Lighting (D1).
   - Fans / Humidity fans / Covers / Manual switches: verify each; likely already inventory-only (empirical during sweep).
2. **One-time migration** in `config_flow.py` `async_step_migration` (already exists at `:3063`). For every existing room entry: keys unchanged; only step-membership changes. No default value drift (Bug Class #34).
3. Strings updates for every moved / renamed field in `strings.json` + `translations/en.json`.

**Acceptance (D8 is the falsifiable-invariant load):**
- Test: for a fixture of 3 pre-migration room entries covering (a) all light features on, (b) night-only, (c) empty defaults — post-migration in-memory options dict is BYTE-IDENTICAL for every KEY; only surfaced STEP for each key differs.
- Test: each moved key still round-trips through options flow save → load → save.
- Live: reload each room config entry; diff `.storage/core.config_entries` before/after — no change to `options` other than newly-added defaulted keys.
- Sensor: `sensor.<room>_config_schema_version` increments once; further reloads do not touch it (idempotent).

---

## Knob-rung summary

| Number | Rung | Reason |
|---|---|---|
| `SUN_DARK_ELEVATION_DEG` | module const | safety/coverage bound; changes should require review |
| `CONF_ILLUMINANCE_THRESHOLD` | operator Number (per room) | legit day-to-day tuning |
| `CONF_LIGHT_EXIT_WAIT_S` / `_NIGHT_S` | operator Number (per room) | legit tuning |
| `CONF_LIGHT_MANUAL_ON_HOLD_S` / `_OFF_COOLDOWN_S` | module const default + operator Number per room | matches fan-oracle precedent |
| Slot brightness / colour (D5) | operator Number/Select per room per slot | routine tuning |
| Slot boundaries (D5) | operator time entities per house (or per room override) | routine tuning |
| `CONF_ROOM_WALK_THROUGH` + dwell (D7) | config-flow field | structural per-room |
| `CONF_LIGHT_SCENE_<SLOT>` (D6) | config-flow field | structural per-room |

Every proposed number has a name; zero inline literals.

---

## Tier + review plan

- **Overall Tier 2** with the D2+D3 pair reviewed jointly (**two framing-disjoint reviews**): A = correctness + oracle-hold edge cases, B = async / lifecycle / race / restart resilience. If D2 uncovers cross-coordinator ripple (e.g., HVAC light coupling — unlikely) elevate to Tier 2-DB.
- **D8 migration** gets a third focused review: **C = migration byte-identity + strings** — reviewer reproduces the byte-identity test locally against a captured fixture from live `.storage/core.config_entries`.
- **Plan review before build:** ONE adversarial pass (Tier 2). Reviewer re-runs the four institutional greps in this doc, re-enumerates the D8 role-vs-inventory violation candidates, and challenges the "no light manual-hold exists today" assertion.
- **Live validation post-deploy:** the D1/D2/D3/D4/D8 acceptance "Live" bullets are the sprint contract; results write back into `README_v<version>.md` per the standing rule.

---

## Zone / House dialog cleanup — problem list (for separate cards)

Not in this cycle. Enumerated here so the operator can card them adjacent to `ZONE-DIALOGS-CLEANUP-1` (already exists at kanban.data.yaml:30571) and a new HOUSE-DIALOGS-CLEANUP card.

**Zone dialog (recurring problems):**
- Enumeration vs role blur: zone dialog exposes climate/HVAC role pickers next to raw entity lists; same rule as rooms would clarify (inventory step + behaviour step).
- HVAC-zone vs house-zone confusion in labels (memory `project_house_zones_vs_hvac_zones`) — labels do not disambiguate.
- Presence-source pickers mixed with presence-behaviour toggles.
- Redundant fields duplicated from room-level (should be zone-only or documented as override).

**House dialog (recurring problems):**
- Notifications, quiet-hours, guest mode, and person / device_tracker inventories all live in a flat surface; needs the same enumerate-vs-behaviour split.
- Energy / EC / EVSE tier knobs on the same page as household schedule knobs — separate steps.
- Names / labels heavy on nerd words ("substrate", "tier", "provenance") per `feedback_label_style_guide`.
- Reload-hazard warnings not surfaced (parent-entry reload = watchdog stall — memory `feedback_parent_entry_reload_watchdog_hazard`).

Recommendation: one card per dialog, each following this document's structure (design rule + role-vs-inventory sweep + migration + falsifiable invariant).

---

## Deferred / not done
- Multi-slot count > 3 in D5 (fixed to Day/Evening/Sleep this cycle).
- Adaptive-lighting integration (out of scope; separate card if operator wants).
- Zone / House dialog cleanups (listed above; separate cards).
- D7 walk-through may be dropped if D2 or D8 grows; if dropped, re-card as WALK-THROUGH-ROOMS-1.
