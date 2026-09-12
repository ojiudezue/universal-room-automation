# AUDIT — URA first-run / onboarding complexity (ONBOARDING-SIMPLIFY-1)

**Date:** 2026-09-12 · **Card:** ONBOARDING-SIMPLIFY-1 · **Status:** audit (pre-plan)
**Goal (operator):** URA is moving to a second house; first-time setup is arcane. Cut cognitive
complexity AND required tasks of the initial steps/forms by **≥50%**, with a **much more assistive
stance** (auto-detect / sane-default / progressive-disclosure over asking).

This doc is (a) the documented path, (b) a verification of what is genuinely required vs merely
presented, (c) simplification proposals engineered to the ≥50% target. It is the planning basis for
ONBOARDING-SIMPLIFY-1; it proposes, it does not change code.

## The setup journey, step by step (in the order you actually hit it)

> Plain-language walkthrough. Each step says **when** it happens, **what it asks**, and how heavy it
> is. Field-by-field evidence is in section (A) below.

**STEP 0 · Install** — HA → Settings → Devices & Services → Add Integration → "Universal Room
Automation". No form yet; HA just launches URA's setup flow.

**STEP 1 · Set up the HOUSE (🏠 Home) — THE mandatory first run, happens immediately.** Two screens:
- **1a. House basics & defaults** (`integration_config`) — *11 fields, only 1 required.* In plain
  terms: "tell URA about the house's environment (outside temp/humidity/weather/solar sensors), who
  lives here (tracked persons), how to reach you (notify service/target/level), and **your electricity
  rate** (the one required field)." Everything except the rate is optional.
- **1b. House energy meters** (`energy_setup`) — *4 fields, all optional.* Whole-house + standalone
  device power/energy meters.
- → URA creates the **"🏠 Home"** entry; the Coordinator Manager is auto-created behind the scenes
  (no form). **The mandatory setup ends here — you now have a working house.**

**STEP 2 · Add a ROOM — the logical next thing, but OPTIONAL and a *separate re-entered flow*.** When:
you re-open URA's config and choose **"Add Room"** from the menu (rooms are never part of the first
ribbon). This is the heavy one — a chain of up to ~13 screens, but **only 2 fields are required**
(room name + room type); the rest default:
- **2a. Room identity** (`room_setup`) — name, type (9 presets that auto-set the occupancy timeout),
  area, shared-space, occupancy timing.
- **2b. Sensors** (`sensors`) — *14 entity pickers* (motion / mmWave / occupancy / cameras / temp /
  humidity / lux / doors / windows / leak). At least one occupancy source required. **This is the
  hardest screen for a non-expert — every field is a raw entity-ID hunt.**
- **2c. Devices** (`devices`) — *12* (lights, night-lights, fans, covers, switches, + internal
  fan-recheck toggles).
- **2d+ feature screens** (shown in sequence, some only if relevant): night-light detail (if night
  lights), cover behavior (if covers), entry/exit light actions, an **automation-chaining menu**, an
  **AI-rules menu**, **climate (21 fields — the heaviest form, full of fan/humidity tuning
  constants)**, fan speeds (if fans), sleep protection, per-room energy, notifications → **room is
  created.**

**STEP 3 · Enable the COORDINATORS (the "smarts") — OPTIONAL, a separate journey again.** When: you
open the **Coordinator Manager** entry's Options (note: "Add Coordinator" in the add-menu just
redirects here — you can't create one from the menu). ~11 sections — presence, safety, security,
**energy (~89 fields!)**, HVAC, music-following, notifications, volume, routing, signal-responses,
optimization. All optional/advanced; this is expert territory, not part of getting a working house.

**Where the load actually is:** the mandatory part (the house) is light — 2 screens, 1 required field.
The weight is all in the *optional* room flow (≈10-13 screens, ~77-95 fields, but only 2 required) and
the *optional* coordinator Options (energy alone ~89 fields). So "first run is arcane" is really two
problems: (i) even the light house step uses jargon/entity-pickers it could auto-detect, and (ii) the
room flow buries 2 real decisions under ~90 presented-but-optional fields. The fix (section C) is
assistive auto-detection + progressive disclosure, not cutting capability.

## Institutional context verified
- **Traced end-to-end** (read-only): `custom_components/universal_room_automation/config_flow.py`
  (all `async_step_*` in the first-run chain), `__init__.py` setup path, `const.py` field defs.
- **Key structural facts confirmed in source:** `__init__.py:956-1003` auto-creates the Coordinator
  Manager entry programmatically → setup presents **no** forms; 100% of first-run load is in
  `config_flow.py`. The post-integration menu (`async_step_post_integration_setup:945`) creates the
  entry before the menu renders → **adding a room is a separate re-entered flow**, not continuous.
- **Existing assistive prior art to REUSE (not build):** `config_flow.py` already has
  `_get_area_entities(area_id, domain, device_class)` (area→entity discovery with device-registry
  fallback) — today used only for light pre-population. This is the lever for auto-suggesting a
  room's whole sensor/device set. Room-type already auto-derives `OCCUPANCY_TIMEOUT`
  (`room_setup:1134`, `ROOM_TYPE_TIMEOUTS`).

## What is MANDATORY on first run vs OPTIONAL (operator-clarified 2026-09-12)

**The literal first run sets up the HOUSE entity (🏠 Home) — not a room.** On install with no
existing entry, `async_step_user:668` routes straight to `integration_config` (house-level sensors +
rate + notify), then `energy_setup`, then `async_create_entry(title="🏠 Home")`. That is the entire
**mandatory** first run: **2 forms, 15 fields, 1 required** — a working House entity with the
Coordinator Manager auto-created behind it (`__init__.py:956-1003`, no form).

**Adding a room is OPTIONAL and a SEPARATE, re-entered flow.** The post-integration menu
(`post_integration_setup:945`) creates the House entry *before* it renders, so rooms are never part
of the first-run ribbon — the operator re-opens the flow later and picks "add room" from
`entry_type_select`. So the audit has two distinct simplification targets with different stakes:
- **The mandatory first run (House entity)** — already light (15 fields / 1 required) but can be made
  near-trivial and assistive (P6). This is what *every* install hits.
- **The optional per-room flow** — where the real bloat lives (77-95 fields / 10-13 screens). Not
  mandatory, but every operator who wants automation does it, one room at a time.

## (A) Documented first-run path + form inventory

### Phase 1 — the HOUSE entity (🏠 Home) = the MANDATORY first run (2 forms, 15 fields, **1 required**)
| step | fields | required |
|---|---|---|
| `integration_config:814` | 11 (outside temp/humidity/weather/solar, tracked persons, retention, transition window, **electricity rate**, 3 notify fields) | **ELECTRICITY_RATE** |
| `energy_setup:908` | 4 (whole-house + device power/energy meters) | 0 |

### Phase 2 — add a ROOM (OPTIONAL, separate re-entered flow; minimal path: 8 forms + 2 menus, **77 fields, 2 required**; all branches: 95 fields)
| step | #fields | required | notes |
|---|---|---|---|
| `entry_type_select:681` | menu | — | add_room / add_zone / add_coordinator |
| `room_setup:1110` | 8 (+1 if zones exist) | **ROOM_NAME, ROOM_TYPE** | also AREA_ID, shared-space×3, occupancy timeout(s)/debounce(ms) |
| `sensors:1241` | 14 | 0 (≥1 occupancy source enforced `:1246`) | **every field a raw entity-ID picker**; `ROOM_CAMERAS` has NO domain filter (`:1304`) |
| `devices:1349` | 12 | 0 | incl. 3 fan-recheck internals + ADJACENT_ROOMS |
| `night_light_detail:1458` ⟐ | 4 | 0 | only if NIGHT_LIGHTS set |
| `cover_behavior:1491` ⟐ | 11 | 0 | only if COVERS set; 5-mode open × time-source × offsets |
| `automation_behavior:1572` | 6 | 0 | entry/exit light actions + dark threshold |
| `init_automation_chaining:1625` | menu + sub-steps | 0 | interrupts linear flow |
| `init_ai_rules:1722` | menu; `ai_rule_add` has 2 required if used | 0 | NL rule parsed by AI |
| `climate:2009` | **21** (2 collapsible sections) | 0 | heaviest form; fan-interference + humidity-spike **tuning constants** |
| `fan_speeds:2171` ⟐ | 3 | 0 | only if FAN_CONTROL_ENABLED |
| `sleep_protection:2198` | 6 | 0 | sleep window + fan policy |
| `energy:2237` | 4 | 0 | per-room meters + rate override |
| `notifications:2292` → create_entry | 6 | 0 | per-room notify override + alert lights |

### Phase 3 — enable coordinators (separate opt-in Options flow, NOT linear)
`add_coordinator` aborts with `coordinator_use_options:696`. Coordinators live in the Coordinator
Manager Options flow (`init:2813`, ~11 sections). **`coordinator_energy:3840` is ~89 fields** — the
single largest surface in the codebase; `coordinator_presence:3434` ~18; `coordinator_hvac:5224`
large. All optional/advanced.

### Totals a first-time operator traverses
| goal | mandatory? | screens | total fields | **required** |
|---|---|---|---|---|
| **House entity (🏠 Home) — the first run** | **YES** | 2 | 15 | **1** (`ELECTRICITY_RATE`) |
| one room (minimal) | optional | 8 forms + 2 menus | **77** | **2** (`ROOM_NAME`, `ROOM_TYPE`) |
| one room (all branches) | optional | 11 forms + 2 menus | **95** | 2 (+2 if an AI rule) |
| coordinators | optional (separate Options flow) | ~11 sections | 130+ (energy ~89) | ~0 |

**Mandatory first run = the House entity: 2 screens, 15 fields, 1 required.** Reaching one working
*room* (optional) adds ~10-13 more screens and ~77-95 fields, of which only 2 more are required. The
3 genuinely-required inputs across the whole house+room journey are `ELECTRICITY_RATE`, `ROOM_NAME`,
`ROOM_TYPE` (+ ≥1 occupancy sensor per room).

## (B) Complexity verification — the load is PRESENTATION, not DECISIONS

The decisive finding: **the genuine decision set is ~3-4 inputs; the other ~90 fields are
optional-with-defaults that HA renders anyway.** HA's form engine shows every `vol.Optional` field
inline — the operator must visually parse and scroll past ~92 fields, most of which are:
1. **Raw entity-ID pickers (~9 across sensors/devices/climate)** — the hardest thing for a
   non-expert; `ROOM_CAMERAS` lists the entire entity space (no domain filter).
2. **Tuning constants mis-placed as setup fields** — the `climate` step's humidity-fan
   EMA-alpha/base/per-min/cap, `BLE_HOLD_CAP_ENABLED`, `COMFORT_FAN_AWAY_VETO_ENABLED`. These are
   Numbers-Get-Knobs rung-1/3 values, not first-run decisions.
3. **Durations in inconsistent units** — seconds / milliseconds / minutes / hour-0-23.
4. **Enum selects assuming domain knowledge** — 5 cover open-modes, fan sleep policy, baseline mode.
5. **Two mid-flow menus** that break the linear rhythm with no "just continue" affordance.

So the problem is **not** "too many required decisions" — it is **too much presented surface + raw
entity hunting + tuning knobs on the setup path + a broken (re-entered, menu-interrupted) flow.**
That diagnosis is what makes a ≥50% cut achievable without losing capability: almost everything cut
from first-run still exists, just relocated to post-setup tuning.

## (C) Simplification proposals — engineered to ≥50%, assistive stance

**North star: first-run shows you the 3 decisions that matter, auto-detects the rest from the
room's AREA, and lets you tune everything later.** Ship as additive flow changes (the full-control
path stays in Options), so no capability is lost — only deferred.

**P1 — Progressive disclosure: an "Essential" first-run, "Advanced" deferred (biggest lever).**
Split room creation into an **Essentials** path (name, type, area, confirm auto-detected sensors +
devices) that goes straight to `create_entry`, and move EVERYTHING else (climate tuning, cover
scheduling, fan-recheck internals, sleep protection, automation chaining, AI rules, per-room
energy/notify overrides, night-light detail) behind a single "Advanced / tune later" entry in the
room's Options flow. Target: **first room = 3-4 screens, ~8-12 visible fields** (vs 10-13 / 77-95).

**P2 — Area-first + auto-suggest (the "much more assistive" core).** Ask `AREA_ID` FIRST, then:
(a) default `ROOM_NAME` to the area name; (b) **auto-populate** MOTION/OCCUPANCY/TEMPERATURE/
HUMIDITY/ILLUMINANCE sensors + LIGHTS/COVERS/FANS from entities assigned to that area via the
EXISTING `_get_area_entities` helper + device_class; (c) the operator **confirms a pre-filled set**
instead of hunting entity IDs. Scope every remaining picker to the area (domain+area-filtered
selectors) so the list is short. This converts ~9 raw pickers into confirm-the-guess — the single
biggest cognitive win.

**P3 — Room-type presets drive feature enables, not just timeouts.** Extend the existing
room-type→timeout default so `ROOM_TYPE` also sets sane feature toggles (bathroom → humidity fan on
+ wet-room; bedroom → sleep protection on; closet → short timeout). The operator picks ONE type and
inherits a coherent config instead of flipping booleans.

**P4 — Relocate tuning constants off the setup path (Numbers-Get-Knobs compliance).** The
humidity-fan EMA/base/per-min/cap, fan-recheck booleans, BLE-hold-cap, cover offsets, fan-speed
temps are tuning — expose as live Number/Switch entities (the pattern already exists) or an Advanced
options section, NOT first-run form fields. `climate` first-run collapses to one toggle ("manage
climate/fans in this room?") + optional `CLIMATE_ENTITY`.

**P5 — Fix the broken flow shape.** Make room creation continuous from the integration setup (don't
create-and-exit before the menu), and remove the two mid-flow menus from the essential path (defer
chaining + AI rules to Options). One linear ribbon, no re-entry, no menu interruptions.

**P6 — Assistive integration first-run.** Only `ELECTRICITY_RATE` is required; auto-detect the
`WEATHER_ENTITY` (HA almost always has one) and derive outside temp/humidity from it; defer
solar/persons/meters to "add energy later." Integration first-run → ~1-2 visible fields.

**P7 — End on a confirmation summary, not a form.** "Set up <room>: N sensors, M lights, occupancy
timeout X (from type). Tune anything in Options." The operator sees a result, not another form.

### Target vs today (acceptance criteria for ONBOARDING-SIMPLIFY-1)
| metric | today | target | 
|---|---|---|
| screens to one working room | 10-13 | **≤4** |
| visible fields to one working room | 77-95 | **≤~12** (≥85% fewer presented) |
| raw entity-ID pickers the operator fills | ~9 | **0 hunted** (confirm auto-detected) |
| required decisions | 3 | 3 (unchanged — already minimal) |
| tuning constants on setup path | ~15+ | **0** (relocated to Numbers/Advanced) |
| mid-flow menu interruptions | 2 | 0 on essentials |

**Verify (discriminating):** a fresh install reaching one functioning room in ≤4 screens where the
sensor/device steps arrive PRE-FILLED from the area (operator edits only corrections); "Advanced"
options flow still exposes 100% of today's fields (no capability lost); regression: an existing
room's saved config round-trips unchanged through the new flow.

## Auto-detect design — the critical piece (researched + cited, 2026-09-12)

The assist is only trustworthy if it doesn't confidently suggest the WRONG entity (e.g. a switch's
internal chip-temperature instead of the room's climate sensor). Researched against HA developer
docs, user docs, and the community forum. **Do the resolution in the custom-component REGISTRY layer,
not Jinja** — `entity_category` is not reliably exposed to templates, but is authoritative on the
registry entry.

**Area resolution (entity overrides device).** Use
`entity_registry.async_entries_for_area(reg, area_id)` — it applies the real precedence: an entity's
own `area_id` wins; if absent it inherits the device's effective area
(`device_registry.async_get_effective_area_id`). Naive "group by device area" misses entity-level
overrides. [core entity_registry.py; home-assistant.io/template-functions/area_entities]

**The primary guard against the chip-temp footgun: `entity_category is None`.** HA marks auxiliary
readings — a relay's internal temperature, RSSI, MAC, uptime — as `EntityCategory.DIAGNOSTIC`
("diagnostics of a device ... for example a sensor showing RSSI", developer Entity docs). A room's
real temperature sensor is a non-categorized (primary) entity. **Keep only `entity_category is None`
(excludes both DIAGNOSTIC and CONFIG)** — this is the single highest-value filter. Also exclude
`disabled_by`/`hidden_by` not None and helper/template/group platforms.

**Bucket by domain + live `device_class`** (read from state attributes, the reliable runtime value;
`device_class` can be mis-inherited from the parent device — core #88504 — so it's a ranking input,
not an oracle): temperature/humidity/illuminance → `sensor`; motion/occupancy, door/window →
`binary_sensor`; lights/fans/covers by domain.

**When >1 survives in a bucket: RANK, never auto-pick — always operator-confirm.** Ladder:
(1) entity with its own `area_id` set > device-inherited; (2) a sensor whose `device_id` is **NOT
shared with an actuator** (the chip-temp lives on the relay's device; a dedicated climate sensor is
usually its own device) > one that is; (3) name/`original_name` NOT matching a denylist
{device temperature, internal, chip, cpu, core temp, rssi, uptime, battery} — the backstop for
integrations that mis-mark internal temps as primary; (4) enabled-by-default > manually-enabled;
(5) deterministic `entity_id` sort.

**So the chip-temp example is handled three-deep:** `entity_category=diagnostic` exclusion (primary);
if a sloppy integration left it `None`, the device-shared-with-actuator deprioritization catches it;
and the name denylist is the final backstop — and even then the operator confirms a *ranked* list,
so a wrong guess is a visible correction, not a silent mistake.

**Pitfalls checklist (carry into acceptance tests):** exclude diagnostic/config; override-aware area
resolution; name denylist backstop; deprioritize actuator-shared sensors; exclude disabled/hidden;
de-dup `_2`/duplicate legs by device_id+device_class (URA already lives with the Frigate `_2`
hazard); filter helpers; device_class is a ranking input not truth; make empty/no-area results
**legible** ("found N entities in this area — assign the area in HA if this looks short") not silent.

**Sources:** developers.home-assistant.io/docs/core/entity (EntityCategory) · core
entity_registry.py (`async_entries_for_area`, `async_get_effective_area_id`, registry fields) ·
home-assistant.io/template-functions/area_entities (device inheritance) · community 378523
(entity_category not template-exposed → registry layer) · core #88504 (device_class mis-inheritance).

## Tiering + non-goals
- **Tier 2-DB** — config-flow is a shared surface (ROOM/ZONE/CM entry types, options-flow
  round-trip, RestoreEntity); the prior-art scan + 3 framing-disjoint reviews apply. The risk is
  options-flow round-trip regressions and area-autodetect mis-pairing — acceptance must include the
  round-trip test.
- **Non-goal:** removing any capability. Everything deferred stays reachable in Options. This is a
  presentation + assist + flow-shape change, not a feature cut.
- **Next:** operator review of these proposals → pick the P1-P7 scope for a first cycle (P1+P2+P5
  deliver most of the ≥50% alone) → Tier-2-DB plan with the institutional-context + acceptance
  section → build.
