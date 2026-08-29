---
name: ura-config-and-flags
description: URA configuration-axis atlas — where the 288 CONF_* constants live, per-room vs zone-manager vs coordinator-manager scope, Number/Switch/Select entities vs config-flow form fields ("Number Fields = Form Fields" trap), production vs experimental/observation/shadow flags, clamp relationships, and the how-to-add checklist. Load when proposing a new CONF_*/sensor/Number/Switch/Select/Button, answering "does URA already have X", migrating a config key, editing config_flow / const / number / switch / select / button, or writing the "Institutional context verified" section. Not for dashboard work (`ha-dashboard`) or new sensor logic (`homeassistant_coding`).
---

# ura-config-and-flags

Verified 2026-07-02 against `develop` @ v5.7.2. Line numbers drift; re-run the
one-liners in **Provenance and maintenance** at the bottom before quoting
anything.

## When NOT to use this skill

| You want to... | Use instead |
|---|---|
| Build a Lovelace dashboard / card layout | `ha-dashboard` |
| Write derived-logic (template sensors, coordinators, integration internals) | `homeassistant_coding` |
| Ship a release / run acceptance | `deploy` |
| Capture a decision to the vibememo trail | `vibememo` |
| Add architecture diagrams post-feature | `documenter` |

This skill is the **config-surface atlas + change-control checklist**. It does
not teach HA integration internals; it teaches URA's specific conventions.

## Vocabulary (define once)

| Term | Meaning in URA |
|---|---|
| **Config entry** | HA persistent record. URA has FIVE `CONF_ENTRY_TYPE` values (`const.py:50-54`): `integration`, `room`, `zone`, `zone_manager`, `coordinator_manager`. |
| **Config flow** | First-time setup UI. Lives in `config_flow.py` -- **there is NO `options_flow.py`**. Options flow is the `UniversalRoomAutomationOptionsFlow` class at `config_flow.py:2232`. |
| **Options flow** | Post-setup reconfiguration UI, same file. Its steps are the **canonical source of truth** for what's user-tunable at runtime. |
| **Config-flow form field** | A `vol.Required(CONF_X)` inside an `async_step_*` schema. UI-only. NOT a Home Assistant entity. |
| **Number Field** | The operator's shorthand for "config-flow form field of NumberSelector type". Do NOT confuse with the Number platform. See "Number Fields = Form Fields" trap below. |
| **Number entity** | An entity on the `number` platform (`number.py`, 26 classes). Appears as `number.ura_...` in HA, gets a device row, RestoreEntity-persisted. |
| **Switch entity** | `switch.py`, 40 classes. Boolean runtime toggles (`switch.ura_...`). |
| **Select entity** | `select.py`, 9 classes. Enum runtime choices. |
| **Button entity** | `button.py`, 18 classes. Fire-and-forget actions (resets, one-shot commands). |
| **Options-flow section** | HA `section()` helper that visually groups + collapses fields (`config_flow.py:36`, `:1889`, `:1919`, `:3204`, `:4717`). Cosmetic only, but flattening (`user_input.pop("section_name", None)`) is required on submit (`config_flow.py:4385-4388`). |
| **Compile-time constant** | Module-level `Final` at bottom of `const.py`. Intentionally NOT a CONF_* so it cannot be misconfigured (see `const.py:1528-1533` boot-storm gate). |
| **Restore-entity persistence** | HA's mechanism to survive restart via `RestoreEntity` mixin. Only Number/Switch/Select entities can use it; config-flow fields persist via the entry itself. |
| **Options as source of truth** | The v4.7.25 pattern: options flow is authoritative; entities push a live attr on options-update signal. RestoreEntity is dropped once options-write-back is in place. |

## Ground-truth facts (verify with commands in Provenance section)

- `CONF_*` count in `const.py`: **288** (2026-07-02).
- `const.py` = 1,980 lines. `config_flow.py` = 8,889 lines. `number.py` = 2,923.
  `switch.py` = 4,378. `select.py` = 790.
- Config entry types (5): `integration`, `room`, `zone`, `zone_manager`,
  `coordinator_manager` (`const.py:50-54`).
- Options-flow class starts at `config_flow.py:2232`
  (`UniversalRoomAutomationOptionsFlow`).
- **No separate `options_flow.py`** -- do not search for one.
- Optimizer risk-level enum (`const.py:1561-1566`): `advisory` <
  `shadow` (DEFAULT) < `reversible_device` < `propose_config` <
  `immediate_config` < `unbounded`. `L1 shadow` is the standing safe default.
- Live config source: Samba mount at
  `/Users/ojiudezue/ha-config/.storage/core.config_entries` (mount command:
  see CLAUDE.md "Data Source Verification" -- copy verbatim).

## The `const.py` domain map

Ordered by file position. Read the whole neighborhood before proposing a
sibling constant. Each header is a `# === v<N> ...` band.

| Line | Section | Scope | What lives here |
|---|---|---|---|
| 47-57 | v3.0.0 Entry type constants | Integration | `ENTRY_TYPE_*`, `CONF_ENTRY_TYPE`, `CONF_INTEGRATION_ENTRY_ID` |
| 60-77 | v3.1.0 Aggregation & zones | Zone | `CONF_ZONE`, `CONF_ZONE_NAME`, `CONF_ZONE_ROOMS`, outdoor / shared-space flags |
| 79-152 | v3.3.1 Music following | Room/Zone | Room player, zone player mode/entity, water leak, alert-light color RGB |
| 154-230 | v3.2.0 Person tracking | Integration | `CONF_TRACKED_PERSONS`, decay/confidence distances, retention days |
| 233-305 | v3.1.6 Energy setup | Integration | Solar/grid/battery/whole-house sensors, rates, coverage-rating labels, HVAC-direction enum |
| 310-321 | Step 1: Basic setup (room) | Room | `CONF_ROOM_NAME`, `CONF_ROOM_TYPE`, `CONF_AREA_ID`, timeouts, guest-room fields |
| 332-479 | Step 2: Sensors (room) | Room | Motion/mmwave/occupancy substrate, `CONF_SCANNER_AREAS`, `CONF_DISABLE_CAMERA_PRESENCE`, all fan-recheck knobs (`CONF_FAN_RECHECK_*`), adjacency |
| 480-524 | Step 3: Devices (room) | Room | Cover behavior, timing modes |
| 525-585 | Step 4: Automation behavior | Room | Cover/open/close timing, automation chaining |
| 586-631 | Step 5: Climate & fans | Room | `CONF_HVAC_COORDINATION_ENABLED`, `CONF_FAN_CONTROL_ENABLED`, `CONF_HUMIDITY_FAN_*`, bathroom-exhaust unification |
| 632-643 | Step 6: Sleep protection | Room | `CONF_SLEEP_PROTECTION_ENABLED` |
| 644-650 | Step 7: Energy monitoring | Room | Per-room energy sensors |
| 651-660 | Step 8: Notifications | Room | Per-room notification overrides |
| 662-668 | Integration-level (shared) | Integration | Cross-cutting shared defaults |
| 670-741 | Default values | -- | Timers, thresholds |
| 743-808 | State keys | -- | Coordinator-data dict keys (NOT CONF_*) |
| 810-836 | Attribute keys | -- | Entity attribute names |
| 838-843 | Device info | -- | `MANUFACTURER`, `MODEL` |
| 906-919 | Database | -- | DB filename, schema constants |
| 921-953 | Comfort & energy thresholds | -- | Numeric thresholds |
| 955-979 | v3.5.0 Camera census | Coordinator (camera) | Census intervals, thresholds |
| 981-998 | v3.5.1 Perimeter alerting & zone aggregation | Zone | Perimeter alert config |
| 1000-1018 | v3.5.2 Transit validation | Integration | Transit validator thresholds |
| 1020-1106 | v3.6.0 Domain coordinators | Coordinator Manager | `CONF_DOMAIN_COORDINATORS_ENABLED`, per-coordinator `_ENABLED` toggles |
| 1108-1113 | v3.6.19 Music following hardening | Coordinator | Music hardening tuning |
| 1115-1162 | v4.6.3 Anomaly sensitivity D10 | Coordinator | Anomaly thresholds |
| 1165-1182 | v3.6.24 Music following tuning | Coordinator | Music tuning knobs |
| 1185-1321 | v3.6.29 Notification Manager | Coordinator (NM) | `CONF_NM_*` channel toggles, quiet hours, cooldowns, digests |
| 1324-1356 | v3.12.0 M3 AI NL rules | Coordinator | AI-rule schema |
| 1359-1486 | v3.10.1 Census v2 event-driven fusion | Coordinator (camera) | Census-v2 tuning |
| 1489-1492 | v3.22.0 Cross-coordinator signal response | Coordinator Manager | Signal-response toggles (all default OFF) |
| 1495-1527 | v4.6.2 D5/D6 Routine awareness | Coordinator (routine) | Routine detection config |
| 1529-1544 | Cold-boot away-actuation storm gate | -- | **INTENTIONALLY compile-time.** No CONF_*, no Number entity, for failsafe reasons. Do NOT propose exposing these. |
| 1546-1763 | Optimization coordinator Phase 1 (planning-doc label "v4.7.34") | Coordinator (optimization) | `OPTIMIZER_LEVEL_*` enum, allowlists, outcome tags, quiet-hours clamps. **The label is the planning name; the optimizer actually shipped on the v5.x line — v5.0.0-v5.2.1 rolled back 2026-06-09 for DB write-flood, then re-deployed at v5.3.0 in L1 Shadow.** |
| 1766-1945 | Phase 2 LLM Tier-2 (planning-doc label "v4.7.35") | Coordinator (optimization) | LLM-provider-agnostic config, soft clamps. Same shipped-as-v5.x caveat. |
| 1948-1980 | Routine-Awareness next-state forecaster | Coordinator (routine) | Forecaster thresholds |

Empirical rule: constants added AFTER a version band are appended at the
band's tail, NOT inserted mid-band. When adding, find the correct band and
append; do not scatter siblings across bands.

**Identity / fusion / cameras config surface:** `switch.ura_name_people_at_doors` (runtime kill), `egress_identity_enabled` (options default), `FACE_MATCH_WINDOW_S`, `EGRESS_FACE_UNION_TTL_S`, `CENSUS_USE_NEW_RESOLVER`, `FRIGATE_CROSS_HOST_CORROBORATION_ENABLED`, `CAMERA_AUTOENABLE_DRY_RUN` — semantics in `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` §3, §5.3.

## Config-entry scope: per-room vs zone vs zone_manager vs coordinator_manager vs integration

Ask this question FIRST when adding a CONF_*: "which entry type stores this?"
The answer determines which options-flow step edits it and which entity class
constructs itself from it.

| Scope | Entry type | Options-flow steps (`config_flow.py:...`) | Rule of thumb |
|---|---|---|---|
| Room | `ENTRY_TYPE_ROOM` | `async_step_basic_setup:7299`, `sensors:7439`, `devices:7556`, `options_lighting:7721`, `options_covers:7800`, `climate:7927` | Any knob that varies per physical room (motion sensors, HVAC entity, occupancy timeout, alert lights). |
| Zone | `ENTRY_TYPE_ZONE` | Zone steps not itemized here; see `manage_zones:6344` and `zone_config_menu:6478` | Rare -- zones mostly configured via zone_manager. |
| Zone manager | `ENTRY_TYPE_ZONE_MANAGER` | `manage_zones:6344`, `zone_rooms:6528`, `zone_media:6739`, `zone_hvac:6816`, `zone_energy:6916`, `zone_persons:6993`, `zone_cameras:7046`, `zone_dynamic_preset:7097` | Anything that groups rooms into a zone or affects zone-aggregate behavior. |
| Coordinator manager | `ENTRY_TYPE_COORDINATOR_MANAGER` | `coordinator_presence:3014`, `coordinator_safety:3305`, `coordinator_energy:3420`, `coordinator_hvac:4279`, `coordinator_hvac_settings:4297`, `hvac_dynamic_preset:4809`, `hvac_baseline_presets:5074`, `coordinator_security:5334`, `coordinator_music_following:5465`, `coordinator_notifications:5601`, `coordinator_notifications_persons:5715`, `coordinator_notifications_quiet:5814`, `coordinator_notifications_cooldowns:5866`, `coordinator_toggles:5916`, `signal_responses:5957`, `coordinator_optimization:6026` | Any cross-cutting policy, per-coordinator toggle, or signal-response wiring. |
| Integration | `ENTRY_TYPE_INTEGRATION` | `integration_config:635`, `energy_setup:729`, `global_sensors:2605`, `energy_sensors:2656`, `person_tracking:2746`, `camera_census:2801`, `perimeter_alerting:2915`, `domain_coordinators:2980`, `default_notifications:6287` | Anything global (grid rates, tracked persons, alert channels). |

## Number Fields = Form Fields -- the phrasing trap

Operator-coined 2026-06-02 after a hotfix (v4.7.17.3) was cancelled mid-build
over a misread. Whenever a plan says "add a Number field for X":

| "Number field" | Concrete artifact | Where |
|---|---|---|
| Almost always | `vol.Required(CONF_X, default=Y): NumberSelector(...)` inside an `async_step_*` schema | `config_flow.py` |
| Only if the plan EXPLICITLY says "on the Number platform" / "as a Number entity" | New `class UraXNumber(RestoreEntity, NumberEntity)` in `number.py`, registered via `async_setup_entry` | `number.py` |

Default assumption: config-flow form field. To promote to a Number entity you
need explicit justification (frequency of change, dashboard exposure, live
attribute needs, cross-coordinator visibility). See v4.7.25 "presence timer
knobs" cycle for the canonical justification pattern (three timers went to
Number entities so dashboards could show + adjust without opening options).

## Production vs experimental / observation / shadow flags

URA uses a small vocabulary of "not-yet-live" gates. Learn the difference so a
proposed "add a CONF_X_ENABLED default False" doesn't collide with the shipped
convention.

| Flag style | Meaning | Where |
|---|---|---|
| `CONF_*_ENABLED = "..._enabled"` default False | Feature-flagged production capability. Off until operator flips. Example: `CONF_FAN_RECHECK_ENABLED` (`const.py:399`), `CONF_ROOM_FAN_RECHECK_ENABLED` (`const.py:405`), `CONF_SLEEP_PROTECTION_ENABLED` (`const.py:633`). |
| Optimizer risk level (Select) | Six-step ladder: `advisory` / `shadow` (DEFAULT) / `reversible_device` / `propose_config` / `immediate_config` / `unbounded` (`const.py:1561-1566`). Governs how much autonomy the optimizer has; the same field, escalated. |
| `OPTIMIZER_OUTCOME_SHADOW = "shadow_dry_run"` (`const.py:1755`) | Outcome tag for shadow decisions -- for the DB row, NOT a config axis. |
| `OPTIMIZER_OUTCOME_QUIET_CLAMPED = "quiet_hours_clamped"` (`const.py:1757`) | Outcome tag for a clamp-suppressed action. |
| Compile-time-only constant | Deliberately NOT exposed. Example: cold-boot away-actuation storm gate (`const.py:1529-1533`). The comment explicitly says why: "the gate has the strongest possible 'can never suppress forever' guarantee (Predicate B failsafe)." Do NOT propose CONF_*-ifying these without a Tier-3 review. |
| Kill-switch | For observation-only diagnostics; single boolean at cycle root. Example: fan-interference feature (`const.py:382`) is "kill-switched" as a unit; individual sub-knobs are not exposed. |

Anti-pattern: adding a second `_ENABLED` flag alongside an existing one. The
2026-05-31 `CONF_FAN_INTERFERENCE_GATE_ENABLED` note (`const.py:384`) folded
gate into the existing flag rather than splitting. When in doubt: extend, do
not multiply.

## Clamp relationships

Whenever two knobs are ordered (X <= Y always), the clamp lives IN CODE, not
in the config surface. Reviewers look for these; forgetting the clamp is a
CRITICAL finding.

Canonical clamp pattern: v4.7.25 HVAC presence-timer knobs -- the
energy-saving vacancy delay must always <= the normal vacancy delay,
bidirectional (raising the lower clamps up, lowering the upper clamps down).
This is enforced in `number.py` inside the Number entities' `async_set_native_value`
paths (v4.7.25 shipped 3 timers as Number entities + a 4th reset Button; see
MEMORY.md "v4.7.25 presence timer knobs live"). The knobs are Number entities,
not CONF_* -- do NOT grep `const.py` for them.

To find every clamp in the tree in one pass:

```bash
grep -RnE 'min\(|max\(|clamp' custom_components/universal_room_automation/number.py \
  custom_components/universal_room_automation/domain_coordinators/hvac.py \
  | grep -vE '^\s*#' | head -40
```

Rule: if you introduce a knob whose safe range depends on another knob, write
the clamp WITH the same commit and add a bidirectional test
(`quality/tests/`) covering (low->high, high->low).

## Persistence semantics -- pick ONE and document

| Storage mode | Survives restart? | Best for | Cost |
|---|---|---|---|
| Config entry `entry.options[CONF_X]` | Yes | Anything an operator changes < weekly. **Default choice.** | Requires an options-flow step edit. |
| Number/Switch/Select entity + `RestoreEntity` | Yes (from state cache) | Rapid dashboard use, live attributes. RestoreEntity comes back as `unavailable`->`OFF` after boot; guard against poisoning (see Envoy-boot incident, MEMORY.md). | RestoreEntity boot-poisoning bug class; more surface. |
| Number/Switch/Select entity + options-flow write-back (v4.7.25 pattern) | Yes | The v4.7.25 pattern retrofit: options is source of truth; entity pushes live attr on options-update signal; RestoreEntity dropped. | Two-way sync needs a dispatcher signal. |
| Module-level `Final` in `const.py` | Yes (compile-time) | Failsafes that must never be misconfigured. | Requires deploy to change. |

Reload-suppression implication (see MEMORY.md "CM reload-suppression cycle
stack"): touching `entry.options` at runtime CAN cascade into a config-entry
reload. URA's Coordinator-Manager reload-suppression protects against this,
but only for allowlisted keys. When adding a CONF_* you edit at runtime, check
the allowlist -- otherwise you can trigger an unwanted reload storm. The
allowlist grew across v4.7.26 → v4.7.27; the specific "5 → 37" growth figure is **unverified in this fix pass** — re-verify via `grep -c '"' <(sed -n '/OPTIONS_RELOAD_SUPPRESS_KEYS = frozenset/,/})/p' custom_components/universal_room_automation/__init__.py)` before quoting. If your key isn't in there, you must add it
or route writes through the options flow (which is properly suppressed).

## HOW TO ADD a config axis -- executable checklist

Run these in order. Each step yields a REUSED-or-NEW verdict that must appear
in the planning doc's "Institutional context verified" section (mandatory per
CLAUDE.md).

### Step 1 -- Grep `const.py` for the domain

```bash
# Replace <keyword> with your proposed name's semantic root (e.g. "fan_recheck", "guest").
grep -nE 'CONF_.*<keyword>' custom_components/universal_room_automation/const.py
# Also look for the SEMANTIC neighbor -- what surrounds the same feature?
grep -nE '<keyword>' custom_components/universal_room_automation/const.py | head -20
```

Verdict: **REUSED `CONF_X` at `const.py:NNN`** OR **NEW because grep of const.py returns 0 hits for <keyword>.**

### Step 2 -- Grep `config_flow.py` for the step + selector

```bash
grep -nE 'CONF_<KEYWORD>|<keyword>' custom_components/universal_room_automation/config_flow.py | head -20
grep -nE 'async def async_step_' custom_components/universal_room_automation/config_flow.py | head -80
```

Identify which existing `async_step_*` should host the new field. **If none
fits, do NOT create a new step without design justification** -- prefer a new
`section()` inside an existing step.

Verdict: **REUSED step `async_step_X` at `config_flow.py:NNN`** OR **NEW step because <reason>.**

### Step 3 -- Grep the platforms

```bash
for plat in number switch select button binary_sensor sensor; do
  echo "=== $plat.py ==="
  grep -nE 'CONF_<KEYWORD>|<keyword>' custom_components/universal_room_automation/${plat}.py | head -5
done
```

Verdict: for each platform, **REUSED entity `class UraX` at `X.py:NNN`** OR **NEW because <reason>.** Especially call out whether you are adding a config-flow form field (default) or a Number entity (needs justification -- see "Number Fields = Form Fields" trap above).

### Step 4 -- Grep the coordinators

```bash
grep -RnE 'CONF_<KEYWORD>|<keyword>' custom_components/universal_room_automation/domain_coordinators/ | head -20
grep -RnE 'CONF_<KEYWORD>|<keyword>' custom_components/universal_room_automation/*.py | head -20
```

Verdict: name every consumer file. If more than one coordinator will read the
new key, plan the signal dispatch (see `domain_coordinators/signals.py`).

### Step 5 -- Read the coordinator design doc

If the change touches a coordinator, read `docs/Coordinator/<NAME>.md`
end-to-end. Do NOT skim.

### Step 6 -- Check planning-doc backlog

```bash
grep -l -iE '<keyword>' docs/planning/*.md | head -10
grep -l -iE '<keyword>' docs/BACKLOG.md docs/TECH_DEBT.md docs/QUALITY_CONTEXT.md 2>/dev/null
```

Read filenames + summaries of any hits. Somebody may have already planned
this and set the naming convention.

### Step 7 -- Check MEMORY.md bodies (not just index)

```bash
grep -l -iE '<keyword>' ~/.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/*.md | head -10
```

Read the full body for any file that matches -- the MEMORY.md index is
truncated (see the WARNING at the bottom of MEMORY.md); short summaries can
be misleading.

### Step 8 -- Cross-check the live entry

```bash
# From the Samba mount (see CLAUDE.md "Data Source Verification" for mount command)
python3 -c "import json; d=json.load(open('/Users/ojiudezue/ha-config/.storage/core.config_entries')); \
  [print(e.get('title'), e.get('data',{}).get('entry_type'), sorted(e.get('options',{}).keys())[:20]) \
    for e in d['data']['entries'] if e.get('domain')=='universal_room_automation']"
```

Confirms the live entries actually have (or lack) the sibling keys you're
proposing. Do not skip -- this catches "we already have it" claims.

Fallback if mount is stale/down: `mcp__home-assistant__ha_get_state` on a
sentinel entity (e.g. `sensor.ura_presence_coordinator_presence_house_state`)
to prove the coordinator is alive; then `ha_get_integration
universal_room_automation` for entry-level state. If BOTH mount and MCP are
down, stop and surface the gap.

### Step 9 -- Decide storage + persistence

Pick from the table in "Persistence semantics" above. State the choice
explicitly in the planning doc. If Number/Switch/Select, decide RestoreEntity
vs options-flow write-back (default: **options-flow write-back**, per v4.7.25).

### Step 10 -- Reload-suppression implication

If the new CONF_* will be written at runtime (any path other than options
flow), confirm it is in the CM reload-suppression allowlist. Grep:

```bash
grep -RnE 'reload_suppr|allowlist|RELOAD_ALLOW' \
  custom_components/universal_room_automation/domain_coordinators/ | head -10
```

If not covered, either (a) add it to the allowlist and add a regression
test, or (b) route writes exclusively through the options flow.

### Step 11 -- Clamp check

If the new knob has an ordered relationship to an existing knob, write the
clamp in code (both directions) and add a test at
`quality/tests/test_<coordinator>.py` covering both extremes and the inversion.

### Step 12 -- Institutional-context verified block

Populate the mandatory planning-doc section with every REUSED/NEW verdict
above. Cite `file:line`. If any step returned zero hits, quote the exact
grep + surface list so the reviewer can spot-check.

## Cheat sheet: common questions with fastest lookup

| Question | One-liner |
|---|---|
| Does `CONF_X` exist? | `grep -nE '^CONF_.*X' custom_components/universal_room_automation/const.py` |
| Which options-flow step edits it? | `grep -nE 'CONF_X' custom_components/universal_room_automation/config_flow.py` then look upward for nearest `async def async_step_...`. |
| Is there a Number entity for it? | `grep -nE 'CONF_X' custom_components/universal_room_automation/number.py` |
| Who reads it? | `grep -RnE 'CONF_X' custom_components/universal_room_automation/` |
| Is it in a `section()`? | Find the step, then look upward in the schema for `section(...)`. Flatten happens in `async_step_*` at `user_input.pop("<section>", None)`. |
| Is it clamped against another knob? | `grep -RnE 'CONF_X' custom_components/universal_room_automation/number.py custom_components/universal_room_automation/domain_coordinators/*.py \| grep -E 'min\|max\|clamp'` |
| Is it a shadow / observation flag? | `grep -nE 'CONF_X' custom_components/universal_room_automation/const.py` then read surrounding `# ---` band. |
| Is it in the reload-suppression allowlist? | See Step 10 grep above. |

## Provenance and maintenance

Re-run before quoting numeric facts:

```bash
# CONF_* count (was 288 on 2026-07-02)
grep -c '^CONF_' custom_components/universal_room_automation/const.py

# Entry types (was 5 on 2026-07-02)
grep -nE '^ENTRY_TYPE_' custom_components/universal_room_automation/const.py

# Options-flow class location (was config_flow.py:2232 on 2026-07-02)
grep -n 'class UniversalRoomAutomationOptionsFlow' custom_components/universal_room_automation/config_flow.py

# Options-flow step index
grep -nE 'async def async_step_' custom_components/universal_room_automation/config_flow.py

# Entity classes per platform
grep -cE '^class .*(Number|Switch|Select|Button)Entity' \
  custom_components/universal_room_automation/number.py \
  custom_components/universal_room_automation/switch.py \
  custom_components/universal_room_automation/select.py \
  custom_components/universal_room_automation/button.py

# Version bands in const.py
grep -nE '^# =====' custom_components/universal_room_automation/const.py

# Config-flow step bands in const.py
grep -nE '^# ---' custom_components/universal_room_automation/const.py

# Optimizer risk-level enum (should be 6 values)
grep -nE '^OPTIMIZER_LEVEL_' custom_components/universal_room_automation/const.py

# HA section() usage in config flow
grep -nE 'section\(' custom_components/universal_room_automation/config_flow.py
```

If any of these return a different shape than described above, this skill is
stale -- update the "Ground-truth facts" and domain map sections before
relying on them.

Related repo policy: `CLAUDE.md` -> "Institutional Context First",
"Configurability Clarity", "Fix LOWs In-Cycle", "Number Fields = Form Fields",
"Review Protocol -- TIERED BY SCOPE". This skill implements the executable
half of those rules for the config surface; it does NOT replace them.
