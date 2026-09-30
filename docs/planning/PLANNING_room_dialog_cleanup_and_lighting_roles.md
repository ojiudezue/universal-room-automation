> **REV 2.1 (2026-09-29):** operator ruling — no new light timers; CONF_LIGHT_EXIT_WAIT_S removed everywhere in this plan (use the leave-on-when-empty role for per-light exemption). This line overrides any mention of a light wait / exit wait knob below.

# PLANNING — Room Dialog Cleanup: Lighting Roles + Role-vs-Inventory Sweep

Card: ROOM-LIGHTING-SETUP-REDESIGN-1 (kanban.data.yaml:30559)
Author: Oji Udezue (planner)  Date: 2026-09-29
Deploy: HELD for operator.
Tier: **2-DB** (three framing-disjoint reviews). D2 (light manual-hold oracle) + D3 (URA room-light switch) additionally get **Tier-3 per-site mutation drills** because the failure mode is one missed emitter (Bug Class #53). Both `is_dark` call sites (automation.py + actuator_reconciler.py) get per-site mutation as well.

## Changelog

### REV 2 — 2026-09-29 (post plan-review)
Addresses `docs/reviews/code-review/plan_review_room_dialog_cleanup_lighting.md` findings 1-13 + orchestrator rulings.
- **F1 (invariant / sun fallback):** invariant restated to declare the sun-fallback change explicitly (operator P0 intent, not a breach). New **D0 blast-radius probe** — enumerate the exact affected rooms from `.storage/core.config_entries` and add a cheap per-room kill-switch.
- **F2 (second `is_dark` site):** `actuator_reconciler.py:794` added to D1/D2/D4 and the producer/consumer table; per-site mutation covers both sites.
- **F3 (incomplete consumer map):** added `hvac.py:5700-5720`, `coordinator.py:1225-1236`, `binary_sensor_control_attrs.py:28`, `aggregation.py:1428`, `actuator_reconciler.py` (12 refs), `automation.py:1282-1320` (legacy switch fallback). Per-light role lists must be plumbed into the reconciler entry path AND the AI-rule conflict union.
- **F4 (migration wrong anchor / under-defined):** dropped stored-data migration and the schema-version sensor. New keys ABSENT ⇒ today's behaviour. Invariant proof is a **resolver-equivalence test**, not byte-identity. No seeding of `CONF_LIGHTS_ON_ENTRY := CONF_LIGHTS`.
- **F5 (pickers dropping saved values):** `include_entities` built from `LIGHTS ∪ NIGHT_LIGHTS ∪ ALERT_LIGHTS ∪ current stored value`, sourced from **in-flight** options state, not `entry.options`. New pattern; round-trip test mandatory.
- **F6 (D2 prior-art too narrow):** D2 now composes with `ManualModeSwitch` (`switch.py:5199`, reconciler Guard 2 at `actuator_reconciler.py:496`) and `SecurityDelegateLightsSwitch` (`switch.py:4941`), and reuses fan self-write discrimination (`actuator_reconciler.py:628-630`). Listener named: `state_changed` filter on `entity_id in CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS` registered from `RoomAutomation.async_added_to_hass` (mirror of the fan hook). D3 explicitly is NOT `manual_mode`.
- **F7 (per-light feature summary data source):** rendered from live `state.attributes['supported_color_modes']`. Room-level `CONF_LIGHT_CAPABILITIES` (basic/brightness/full) shown as one summary line.
- **F8 (light wait knob):** SEPARATE key `CONF_LIGHT_EXIT_WAIT_S`, default 0 (no extra delay); **never folded into `CONF_OCCUPANCY_TIMEOUT`**.
- **F9 (D4 overlap):** precedence defined vs `is_sleep_mode_active` (`automation.py:903-916`); Away action gets a boot-settle gate + no-flap test; Guest values enumerated.
- **F10 (knob-ladder bloat):** per orchestrator ruling, **config-flow fields are the default**; the only NEW entity in this cycle is `switch.<room>_lights` (D3). No new per-room `Number` entities. Existing `CONF_ILLUMINANCE_THRESHOLD` stays a config-flow field.
- **F11 (acceptance not discriminating):** D5 tests inject the clock (no wall-clock coupling). Added the "no-lux, `turn_on_if_dark`, after-dusk" discriminator test (the exact case F1 flagged).
- **F12 (D8 sweep method):** sweep covers every edit-path step `config_flow.py:1862-2918`, includes `cv.multi_select` and boolean toggles, and enumerates Auto-On/Off, Auto-Off-Only, Auto and Manual Devices explicitly.
- **F13 (tier):** upgraded to Tier 2-DB with three framings; D2/D3 + both `is_dark` sites get Tier-3 per-site mutation.

### REV 1 — 2026-09-29
Initial plan.

## Operator anchor
"Room dialog is the absolute core of URA. Right now it's a power-user mess. Features are mature so turning back to refinement is good discipline." — 2026-09-29.

## Design rule (keep)
Devices and Sensors steps ONLY **enumerate + classify** (incl. auto-detected features). Every **role** ("which ones should URA do X with") lives in its **behaviour step**, with pickers restricted to entities enumerated upstream. Filter source: **`LIGHTS ∪ NIGHT_LIGHTS ∪ ALERT_LIGHTS ∪ currently-stored value`**, from in-flight options — never from `entry.options[CONF_LIGHTS]` alone (F5).

## Falsifiable invariant (Tier-2-DB anchor)
**Every room behaves identically until the operator changes a role, EXCEPT the declared darkness change: `turn_on_if_dark` rooms with NO lux sensor start using sun position (P0 operator intent).** Discriminating observations:
1. A room with `entry_light_action=turn_on_if_dark` AND `CONF_LUX_ENTITY` set: unchanged behaviour.
2. A room with `entry_light_action=turn_on_if_dark` AND no lux sensor: **previously never turned lights on** (F1: `is_dark(None)=False`); post-cycle turns lights on after dusk. This is intended.
3. Any room with no `turn_on_if_dark` role AND no new keys set: unchanged behaviour.
4. Resolver-equivalence: for every existing room, `effective_entry_set(cfg)` == today's set when the new role lists are absent.

## Non-goals
- No new lighting effects (colour cycling, animations, adaptive-lighting).
- No changes to alert-light behaviour beyond relocation (color knob stays in Notifications).
- No changes to fan / cover / climate / notification steps beyond D8 role-vs-inventory relocation.
- No new per-room `Number`/`Select` entities (config-flow fields only); the sole new entity is `switch.<room>_lights` (D3).
- No stored-data migration; absent new keys = today's behaviour.
- No dashboarding work.
- No load-shedding or energy-tier coupling.

---

## Institutional context verified

### Design docs / prior planning
- `CLAUDE.md` — Institutional Context First, Config-First, Numbers Get Knobs, Marginal-benefit pushback, Extend existing never rebuild, plan-review tiering, prior-art scan.
- `docs/QUALITY_CONTEXT.md` — bug classes #7 (stale data source), #22 (enum mismatch), #23 (observation-mode gating), #34 (options-flow default drift), #53 (computed-but-not-consumed — the D2/D3 emitter-miss hazard), #63 (coincidental-equality masking concept split).
- Adjacency `ROOM-DIALOGS-USABILITY-SWEEP-1` — wording-only sweep, already shipped (commit `58464918d`). This card is structural.
- Memory: `feedback_config_first_before_code`, `feedback_label_style_guide`, `feedback_configurability_clarity`, `feedback_extend_existing_never_rebuild`, `feedback_marginal_benefit_pushback`, `feedback_parent_entry_reload_watchdog_hazard`, `feedback_no_restart_during_sleep`, `project_house_zones_vs_hvac_zones`.

### Code surveyed end-to-end
- `config_flow.py` room path: room_setup :1439 → room_class :1536 → sensors_confirm :1570 → devices_confirm :1717 → room_summary :1779; edit path: sensors :1862 → devices :1970 → night_light_detail :2079 → cover_behavior :2112 → automation_behavior :2193 → chaining :2246 → climate :2630 → fan_speeds :2797 → sleep_protection :2824 → energy :2863 → notifications :2918. `ConfigFlow.VERSION = 1` at :748. `async_step_migration` at :3063 is **integration-entry** (not room migration); `__init__.py` has no `async_migrate_entry` — confirms no stored-data migration path exists to hook (F4).
- `automation.py`: `is_dark` :933-937 (returns False on None lux!), entry-light controller :1031, legacy AUTO/MANUAL_SWITCHES fallback :1282-1320, clock-based `is_sleep_mode_active` :903-916, sleep-mode entry gate :1018-1027, fan manual-hold ledger + delegators :210-355.
- `actuator_reconciler.py`: SECOND `is_dark` site :794, entry-action + night-light path :748-813, union `LIGHTS ∪ NIGHT_LIGHTS` :109, fan self-write discrimination :628-630, manual_mode Guard 2 :496.
- `switch.py`: `ManualModeSwitch` :5199, `SecurityDelegateLightsSwitch` :4941.
- `coordinator.py`: AI-rule conflict union of LIGHTS/NIGHT_LIGHTS/AUTO_DEVICES/AUTO_SWITCHES :1225-1236.
- `binary_sensor_control_attrs.py:28`: `control_night_lights` attr.
- `aggregation.py:1428`: `CONF_ALERT_LIGHTS` read (options→data fallback).
- `domain_coordinators/hvac.py:5700-5720`: `CONF_NIGHT_LIGHTS` reader.
- `domain_coordinators/fan_policy_oracle.py:1-40`: INV-FLA — reference pattern for D2 light oracle (per-room asyncio.Lock, consult→emit→note, self-write discrimination).
- `const.py`: CONF_LIGHTS :870, CONF_LIGHT_CAPABILITIES :870 (room-level enum basic/brightness/full :891-893), CONF_AUTO/MANUAL_DEVICES + legacy SWITCHES :882-888, CONF_NIGHT_LIGHTS + brightness/colour :897-907, CONF_ENTRY_LIGHT_ACTION/EXIT/ILLUMINANCE_THRESHOLD/BRIGHTNESS/TRANSITION :915-920, LIGHT_ACTION_* :923-927, CONF_ALERT_LIGHTS :99-100, CONF_OCCUPANCY_TIMEOUT :398 (**not** a light key; must not be repurposed — F8).
- `strings.json` / `translations/en.json` — labels for every step touched.

### Prior-art scan — REUSE / BUILD

| Piece | REUSE / BUILD | Cite |
|---|---|---|
| Room lux + `is_dark` | REUSE (extend to fallback wrapper) | `automation.py:933`, `actuator_reconciler.py:794` |
| Sun-position dark fallback | BUILD (thin) | HA `sun.sun` `elevation` attr; new `is_dark_effective()` |
| Borrow another room's lux (P1) | REUSE feed + new config-flow field | `CONF_LUX_ENTITY` existing; new `CONF_LIGHT_DARK_LUX_SOURCE` |
| Night lights role | REUSE key, MOVE picker | `CONF_NIGHT_LIGHTS` `const.py:897`; move producer from Devices `config_flow.py:2010` to Lighting step |
| Per-light entry / dark-only / leave-on-when-empty roles | BUILD (additive keys, ABSENT = today) | New `CONF_LIGHTS_ON_ENTRY`, `CONF_LIGHTS_ON_ENTRY_DARK_ONLY`, `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`; consumed by BOTH `automation.py` entry/exit and `actuator_reconciler.py` |
| Alert lights ride-along | REUSE, MOVE picker | `CONF_ALERT_LIGHTS` `const.py:99`; move from Notifications `:3034` |
| One light exit wait | BUILD (new, default 0) | `CONF_LIGHT_EXIT_WAIT_S`; **never** `CONF_OCCUPANCY_TIMEOUT` (F8) |
| Per-light feature summary | READ live | `state.attributes['supported_color_modes']` + one line for room-level `CONF_LIGHT_CAPABILITIES` (F7) |
| Light manual-hold ledger (D2) | REUSE PATTERN, BUILD module | `fan_policy_oracle.py`; verified NO existing light hold. Composes with `ManualModeSwitch` (F6). |
| Room-light switch (D3) | REUSE `switch.py` platform | new `RoomLightsSwitch` per room; distinct from `ManualModeSwitch` (F6) |
| House-state awareness (D4) | REUSE HouseState + `is_sleep_mode_active` | precedence defined in D4 (F9) |
| Time-of-day slots (D5) | EXTEND `const.py:898-907` | fixed set: Day / Evening / Sleep |
| Scenes per slot (D6) | BUILD | `CONF_LIGHT_SCENE_<SLOT>` config-flow fields |
| Walk-through (D7) | BUILD | `CONF_ROOM_WALK_THROUGH` + dwell |

---

## Producer / Consumer map (REV 2 — complete)

Every reader of every touched key. Reviewers re-grep.

| Key | Producer (writer) | Consumers | Post-cycle |
|---|---|---|---|
| `CONF_LIGHTS` (unchanged) | Devices step `config_flow.py:1755, 2003` | `automation.py:1053-1054`, `actuator_reconciler.py:109, 748-813`, `coordinator.py:1225-1236`, `hvac.py:5700-5720` union readers | UNCHANGED |
| `CONF_NIGHT_LIGHTS` | MOVE producer → Lighting step | `automation.py` night-light apply, `actuator_reconciler.py:109` exit union, `coordinator.py:1231`, `hvac.py:5700-5720`, `binary_sensor_control_attrs.py:28` | picker moves; key unchanged |
| `CONF_NIGHT_LIGHT_*_BRIGHTNESS/COLOR` | MOVE → Lighting step (fold `night_light_detail` in) | `automation.py` night-light apply | keys unchanged |
| `CONF_ALERT_LIGHTS` | MOVE → Lighting step | `aggregation.py:1428`, alert emitter | picker moves; COLOR knob stays in Notifications |
| `CONF_AUTO_DEVICES` / `CONF_MANUAL_DEVICES` / legacy `CONF_AUTO_SWITCHES` / `CONF_MANUAL_SWITCHES` | MOVE → new behaviour "Auto/Manual" sub-block | `actuator_reconciler.py` (12 refs), `automation.py:1282-1320`, `coordinator.py:1225-1236` | pickers move; keys unchanged; legacy preserved |
| `CONF_ENTRY_LIGHT_ACTION` / `CONF_EXIT_LIGHT_ACTION` | Lighting step | `automation.py:1031`, `actuator_reconciler.py:748-813` | PRESERVED as GLOBAL fallback; per-light lists override when non-empty |
| `CONF_ILLUMINANCE_THRESHOLD` | Lighting step (config-flow field, NOT Number) | `automation.py:933`, `actuator_reconciler.py:794` | UNCHANGED (F10) |
| `CONF_LIGHTS_ON_ENTRY` (NEW) | Lighting step | `automation.py` entry, `actuator_reconciler.py` entry-action, `coordinator.py` AI-rule union | ABSENT = today (F4) |
| `CONF_LIGHTS_ON_ENTRY_DARK_ONLY` (NEW) | Lighting step | Same as above | ABSENT = today |
| `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` (NEW) | Lighting step | `automation.py` exit, `actuator_reconciler.py` exit | ABSENT = today |
| `CONF_LIGHT_DARK_LUX_SOURCE` (NEW, P1) | Lighting step | `is_dark_effective()` (both sites) | ABSENT = today (lux-only) |
| `CONF_LIGHT_EXIT_WAIT_S` (NEW) | Lighting step | exit vacancy timer (both sites) | ABSENT = 0 (no extra delay) |
| `CONF_LIGHT_DARK_USE_SUN_FALLBACK` (NEW, F1 kill-switch) | Lighting step | `is_dark_effective()` | default TRUE; per-room OFF disables sun fallback |
| `CONF_LIGHT_MANUAL_ON_HOLD_S` / `_OFF_COOLDOWN_S` (NEW, D2) | Lighting step (config-flow) | `light_policy_oracle` | ABSENT = module const default |

**Every emitter of `light.turn_on` / `light.turn_off` in the tree must consult the oracle (D2).** Emitters enumerated (Tier-3 per-site mutation applies): `automation.py` entry, `automation.py` exit, `actuator_reconciler.py:748-813` entry-action, `actuator_reconciler.py` exit-union reconciliation. Any additional emitter surfaced during build gets the same wrap.

---

## Deliverables

### D0 — Sun-fallback blast-radius probe (measure before build)
**Scope:** Read-only script against `/Users/okosisi/ha-config/.storage/core.config_entries` (Samba mount). Enumerate every URA room entry and report:
- `entry_light_action` value
- `CONF_LUX_ENTITY` set? (Y/N)
- Verdict: **AFFECTED** if `turn_on_if_dark` AND no lux entity — this room starts turning lights on at dusk when D1 ships. Report the list to operator BEFORE D1 build starts.

**Kill-switch (cheap, included):** `CONF_LIGHT_DARK_USE_SUN_FALLBACK` per-room boolean, default TRUE. Off ⇒ preserves today's `is_dark(None)=False` behaviour for that room.

**Acceptance:** `docs/planning/AUDIT_sun_fallback_blast_radius.md` committed with the room list. Operator reviews before D1 build dispatch.

### D1 — Lighting step: role pickers + one wait + darkness fallback
**Scope:** New behaviour sub-step "Lighting". Fields in order:
1. Read-only description: per-light lines from `state.attributes['supported_color_modes']` (F7); one line for room-level `CONF_LIGHT_CAPABILITIES`.
2. `CONF_LIGHTS_ON_ENTRY` (multi entity_id).
3. `CONF_LIGHTS_ON_ENTRY_DARK_ONLY` (subset).
4. `CONF_NIGHT_LIGHTS` (moved).
5. `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`.
6. `CONF_ALERT_LIGHTS` (moved).
7. `CONF_LIGHT_EXIT_WAIT_S` (new, default 0; config-flow int).
8. `CONF_ILLUMINANCE_THRESHOLD` (config-flow int; unchanged).
9. `CONF_LIGHT_DARK_LUX_SOURCE` (optional entity_id; borrow lux).
10. `CONF_LIGHT_DARK_USE_SUN_FALLBACK` (bool, default True — F1 kill-switch).

Picker `include_entities` = `LIGHTS ∪ NIGHT_LIGHTS ∪ ALERT_LIGHTS ∪ currently-stored value`, sourced from **in-flight** flow state (F5).

`is_dark_effective(cfg, state)` evaluation order:
1. Room `CONF_LUX_ENTITY` if fresh → threshold compare.
2. Else `CONF_LIGHT_DARK_LUX_SOURCE` if set and fresh → threshold compare.
3. Else if `CONF_LIGHT_DARK_USE_SUN_FALLBACK`: `sun.sun` elevation < `SUN_DARK_ELEVATION_DEG` (module const, default -6.0, civil dusk).
4. Else: preserve today's `is_dark(None)=False`.

Wired at BOTH `automation.py:933` and `actuator_reconciler.py:794` (F2).

**Knob-rung:** `SUN_DARK_ELEVATION_DEG` = module const; all per-room knobs = config-flow fields (F10).

**Acceptance:**
- Verify: options flow shows Lighting step with the 10 fields; Devices no longer shows Night Lights / role pickers; Notifications no longer shows Alert Lights picker (color knob remains).
- Test: **resolver-equivalence** — `effective_entry_set(cfg)` matches today's set for a fixture of 3 configs (all-features, night-only, empty). Absent new keys ⇒ identical set.
- Test: **F5 round-trip** — a room with a night-light entity NOT in `CONF_LIGHTS` saves and reloads without dropping it.
- Test: **discriminator (F11)** — no-lux room with `turn_on_if_dark`, sun elevation < -6° ⇒ `is_dark_effective` returns True (previously False).
- Test: same room with `CONF_LIGHT_DARK_USE_SUN_FALLBACK=False` ⇒ returns False (kill-switch honoured).
- Live: check D0's AFFECTED list post-deploy — those rooms should light at dusk; kill-switch OFF reverts.

### D2 — Respect manual light changes
**Verified:** no existing light manual-hold ledger. Related: `ManualModeSwitch` (`switch.py:5199`, Guard 2 `actuator_reconciler.py:496`), `SecurityDelegateLightsSwitch` (`switch.py:4941`), fan self-write discrimination (`actuator_reconciler.py:628-630`).

**Scope:** New `light_policy_oracle.py` mirroring `fan_policy_oracle.py`: per-room `asyncio.Lock`; `manual_off_cooldown_until`, `manual_on_hold_until`; consult→emit→note. `RoomAutomation._light_manual_on/off_until` @property delegators mirror `_fan_manual_*_until`.

**Every URA-issued `light.turn_on/off` wraps `async with oracle.actuate(...)`** at the four enumerated emitter sites (see producer/consumer map). Emitter list is reviewed by Tier-3 completeness pass (D adversarial).

**External-change listener:** `state_changed` filtered on `entity_id in CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`, registered from `RoomAutomation.async_added_to_hass` (mirror of fan hook). Reuses fan self-write discrimination (F6): a state change within the actuate window is NOT external.

**Composition with `ManualModeSwitch` (F6):** `manual_mode=ON` remains its own veto (Guard 2 at reconciler); the light hold is a SECOND, shorter-lived veto. They compose disjunctively (either blocks URA-issued change). D3's `switch.<room>_lights` is a URA-issued action routed through the oracle — it is NOT `manual_mode`.

**Knobs:** `CONF_LIGHT_MANUAL_ON_HOLD_S` (default 3600), `CONF_LIGHT_MANUAL_OFF_COOLDOWN_S` (default 900) — config-flow fields (F10); module const defaults.

**Acceptance:**
- Test: external ON while empty ⇒ next vacancy skips off until hold expires.
- Test: external OFF while occupied ⇒ next entry skips re-trigger until cooldown expires.
- Test: `manual_mode=ON` + light hold ⇒ both block; disabling one keeps the other.
- Test: URA-issued write via D3 switch ⇒ marked manual (intentional).
- Test: URA-issued write via entry path ⇒ NOT marked manual (self-write discrimination).
- **Per-site mutation drill (Tier 3):** neuter each of the 4 emitters in turn — a specific test must fail per site. If a site's neuter leaves the suite green, that site is untested.
- Live: `sensor.<room>_light_manual_hold_remaining_s` reflects hold; entry/exit honour it.

### D3 — URA room-light switch
**Scope:** `switch.<room>_lights` per room. `turn_on` → oracle.actuate → apply current slot's brightness/colour to `CONF_LIGHTS_ON_ENTRY` (or `CONF_LIGHTS` if empty). `turn_off` → oracle.actuate → all room lights off. Both count as manual per D2 (operator intent). Distinct from `ManualModeSwitch`; distinct from `SecurityDelegateLightsSwitch`.

**Acceptance:**
- Verify: entity exists per room; state = "any room light on".
- Test: toggling sets the hold ledger.
- Test: entity_id namespace does not collide with `ManualModeSwitch` or security-delegate switch.
- Live: Lovelace toggle → entry/exit path respects the hold.

### D4 — House-state awareness for lights
**Verification first:** grep `HOUSE_STATE_` in `automation.py` + `actuator_reconciler.py`; enumerate current usage. Findings feed the plan-review pass.

**Precedence (F9):** `is_sleep_mode_active` (clock-based, `automation.py:903-916`) OR HouseState=Sleep ⇒ Sleep semantics apply. If they disagree, **Sleep wins** (the safer / dimmer state).

**Semantics:**
- HouseState=Away: all room lights off. Boot-settle gate: skip the first N seconds after `homeassistant_started` (default 60s; module const) to avoid restart-transient Away pulses (memory: no-restart-during-sleep).
- HouseState=Sleep OR sleep-clock: only `CONF_NIGHT_LIGHTS` may turn on at entry; existing lights left on only per `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`.
- HouseState=Guest: `CONF_LIGHTS_GUEST_MODE` per-room enum, values: `normal` (default; no change), `off` (all off), `night_lights_only` (as Sleep). Config-flow field.

**Acceptance:**
- Test: 3x3 matrix (Home/Away/Sleep × entry/exit/no-change) + Guest × 3 values.
- Test: no-flap — HouseState oscillation Home→Away→Home within 5s does NOT emit two turn-off cycles.
- Test: boot-settle — Away pulse within 60s of `homeassistant_started` is suppressed.
- Live: transition to Sleep; non-night-light room activates only night lights.

### D5 — Time-of-day brightness / colour slots
**Scope:** Extend `const.py:898-907` into a slotted table with a **fixed** set of 3 slots: Day / Evening / Sleep. Per-slot `brightness_pct` and `color_kelvin` are config-flow fields (F10). Slot boundaries: config-flow time fields per room with sensible defaults (sunset for Evening onset, existing `is_sleep_mode_active` window for Sleep).

**Acceptance:**
- Test: with injected clock (F11 — no wall-clock coupling), entry at "Day" fixture uses Day values, "Evening" uses Evening, "Sleep" uses Sleep. Use `freezegun` or dependency-injected `now()`.
- Live: verify colour_kelvin at a known time matches expected slot.

### D6 — Scenes per slot
**Scope:** Optional `CONF_LIGHT_SCENE_DAY` / `_EVENING` / `_SLEEP` (config-flow entity_id, scene domain). When set for current slot, entry action calls `scene.turn_on` instead of computing brightness+colour.
**Acceptance:** Test with injected clock: scene set for Evening + clock in Evening ⇒ `scene.turn_on` called; brightness path skipped. Live: HA logbook shows scene call.

### D7 — Walk-through rooms (droppable)
**Scope:** `CONF_ROOM_WALK_THROUGH` (bool, default False; config-flow) + `CONF_ROOM_WALK_THROUGH_DWELL_S` (int, default 5). True ⇒ exit fires immediately on vacancy (bypass `CONF_LIGHT_EXIT_WAIT_S`); entry gated by dwell to avoid flashing on pass-through.
**Acceptance:** Test both branches. Live: hallway walk-through → lights off within seconds of vacancy.
**Drop criteria:** If D2 or D8 grow beyond budget, drop D7 and re-card WALK-THROUGH-ROOMS-1.

### D8 — Role-vs-inventory sweep + strings
**Scope:**
1. **Sweep method (F12):** grep every `async_step_*` in the edit path `config_flow.py:1862-2918`. For each field: is it an inventory picker (KEEP) or a role picker (MOVE to behaviour step)? Coverage MUST include `cv.multi_select` fields and boolean toggles, not just `EntitySelector`. Explicit candidates from scope: Night Lights, Alert Lights, Auto-On/Off Devices, Auto-Off-Only Devices, Auto Devices, Manual Devices, Auto Switches, Manual Switches.
2. **NO stored-data migration (F4).** New keys absent = today's behaviour. No `async_migrate_entry`; no schema-version sensor.
3. Strings updated in `strings.json` + `translations/en.json` for every moved field.

**Acceptance:**
- Test (invariant load-bearing, F4/F11): **resolver-equivalence** — for a fixture of live-shaped room configs, `effective_entry_set`, `effective_exit_set`, `effective_night_set`, `effective_alert_set` are IDENTICAL to pre-cycle behaviour when new keys are absent.
- Test: options flow round-trips saved values (F5) without dropping night/alert entities that live outside `CONF_LIGHTS`.
- Live: reload each room config entry; observe log lines confirm role sets match pre-cycle by grep.

---

## Knob-rung summary (REV 2)

| Number / knob | Rung | Reason |
|---|---|---|
| `SUN_DARK_ELEVATION_DEG` | module const | safety bound; changes require review |
| `CONF_ILLUMINANCE_THRESHOLD` | config-flow field | unchanged; no new Number entity (F10) |
| `CONF_LIGHT_EXIT_WAIT_S` | config-flow field | operator-settable per room, infrequent tuning |
| `CONF_LIGHT_MANUAL_ON_HOLD_S` / `_OFF_COOLDOWN_S` | config-flow field + module const default | matches fan pattern; no Number entity |
| D5 slot brightness / colour / boundaries | config-flow field | one writer per value (F10) |
| D6 slot scenes | config-flow field | structural |
| D7 walk-through bool + dwell | config-flow field | structural |
| D4 Away boot-settle window | module const | safety window |

Every proposed number is named; zero inline literals. **Only new entity this cycle: `switch.<room>_lights` (D3).**

---

## Tier + review plan

- **Tier 2-DB** — three framing-disjoint reviews (F13):
  - **A — Correctness + edge cases + resolver-equivalence** (D1, D4, D5, D6, D7, D8).
  - **B — Async / lifecycle / race / restart resilience** (D2 oracle, D3 switch, D4 boot-settle, D2 listener registration).
  - **C — Cross-coordinator ripple + consumer completeness** (reconciler entry-action path, AI-rule conflict union, night/alert independent sets, HouseState precedence vs sleep-clock).
- **Tier-3 per-site mutation** overlaid on D2 + D3 + both `is_dark` sites: neuter each of the 4 light emitters and both `is_dark` call sites in turn; a specific test must fail per site.
- **Plan review (Tier 2-DB):** ONE adversarial plan-review pass on REV 2. Reviewer re-greps producer/consumer table, re-enumerates emitter sites, and confirms F1-F13 addressed.
- **Live validation:** D0 blast-radius operator sign-off BEFORE D1 build. Post-deploy, README validation table records observed behaviour on the D0 AFFECTED list plus a representative kill-switch-off room.

---

## Zone / House dialog cleanup — problem list (separate cards)

Not in this cycle.

**Zone dialog (card `ZONE-DIALOGS-CLEANUP-1` exists at kanban.data.yaml:30571):**
- Enumeration vs role blur; role pickers next to raw inventories.
- HVAC-zone vs house-zone label ambiguity (memory `project_house_zones_vs_hvac_zones`).
- Presence sources mixed with presence behaviour.
- Duplicated room-level fields without override semantics stated.

**House dialog (needs new card `HOUSE-DIALOGS-CLEANUP-1`):**
- Notifications, quiet-hours, guest mode, person / device_tracker inventories on one flat surface — same enumerate-vs-behaviour split.
- Energy / EC / EVSE tier knobs on the same page as household schedule knobs; separate steps.
- Nerd-word labels ("substrate", "tier", "provenance") violate `feedback_label_style_guide`.
- Reload-hazard warnings not surfaced (parent-reload → watchdog stall).

Recommendation: card each dialog following this document's structure (design rule + role-vs-inventory sweep + resolver-equivalence invariant + no-migration principle).

---

## Deferred / not done
- Multi-slot count > 3 in D5 (fixed set this cycle).
- Adaptive-lighting integration (out of scope).
- Zone / House dialog cleanups (separate cards).
- D7 walk-through droppable per criteria.
- Stored-data migration (deliberately not done per F4 — no schema-version sensor, no `async_migrate_entry`).

## D0 RESULTS (orchestrator, 2026-09-29, read-only .storage/core.config_entries)

43 room entries. Rooms with entry_light_action = turn_on_if_dark AND no illuminance_sensor (the only rooms the sun fallback changes): **2** — Up Guestbedroom Closet, Guest Bedroom 2 Hallway (both have lights configured). Today their lights never turn on at entry (is_dark(None) = False); with the sun fallback they turn on after dusk. Small, guest-wing blast radius.

**Light wait (F8) — RULED 2026-09-29 (operator): NO extra timers.** "I think the architecture means I can exempt some light from the occupancy time out. Yes? But I don't want to add an extra timer(s)." Resolution: DROP CONF_LIGHT_EXIT_WAIT_S and any other new light timer. Per-light exemption from the occupancy timeout = the D1 "Leave on when the room empties" role picker (those lights are never turned off at vacancy; everything else goes off when the room counts as empty, as today). House-state rules (e.g. Away all off) still apply to exempt lights. Prior text below kept for history: Orchestrator recommendation: NO separate light wait; one plainly labelled 'Room counts as empty after' setting (the existing occupancy timeout) drives lights; night difference handled by roles (Sleep night lights), not a second timer; decouple the sensor-trust window (2x occupancy timeout, coordinator.py:3959/4358) internally as a separate card. Builder must not build CONF_LIGHT_EXIT_WAIT_S until the operator rules.
