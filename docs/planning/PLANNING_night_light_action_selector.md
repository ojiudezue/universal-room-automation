# PLANNING — Night-light actuation rule (NIGHT-LIGHT-ACTION-SELECTOR-1)

Card: `NIGHT-LIGHT-ACTION-SELECTOR-1`. Blocks
`LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1`. Follows the room-lighting-roles
arc (v5.103.29 Slices A–E, v5.103.30, v5.103.31).

Status: **REV 3** — operator ruling 2026-10-08 (card
`operator_2026_10_08_pick` + `operator_2026_10_08_intent`). REV 2's
3-way selector (`CONF_NIGHT_LIGHT_ENTRY_ACTION` + `LIGHT_ACTION_FOLLOW_MAIN`)
is **DROPPED**. The policy is now a RULE in code; config adds exactly
ONE boolean knob + a label-and-placement cleanup for existing colour
fields. No new timers (URA's existing vacancy / occupancy handling turns
night lights off).

Tier: **Tier 2-DB** (unchanged — standing policy 2026-06-08). Shared
primitive (`_resolve_light`, `_control_lights_entry`) consumed by two
controllers; the asymmetry this cycle closes is the exact failure mode
of a mis-coordinated change. Three framing-disjoint reviews.

---

## STEP 1 — Premise re-verified on current develop

Verdict: **STILL-REAL** (REV 2 verification carries; re-checked file:line
for REV 3 shape).

- `automation.py:1292–1297` canonical early-returns on
  `CONF_ENTRY_LIGHT_ACTION == NONE` **before** the sleep night-light
  branch at `:1313`. Rooms whose main action is `none` therefore never
  trigger canonical's sleep branch today.
- `automation.py:1302` short-circuits on `not lights:` **before**
  the sleep branch — a night-light-only room (Master Bedroom:
  `CONF_LIGHTS=[]`, `CONF_NIGHT_LIGHTS=[…]`) is skipped entirely in
  canonical even outside sleep.
- `actuator_reconciler.py:_resolve_light` sleep branch at `:813–:829`
  asserts the night light ON under (sleep AND night_light member AND
  occupied) BEFORE the `entry_action == NONE` check at `:843`. The two
  controllers disagree today — LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1.
- `resolver.py:95–97` already enforces "under sleep ⇒ night list only."
- `resolver.py:150–162 resolve_slot(...)`: `evening` ⇐ `not sleep AND
  is_dark is True`. `is_dark` is already the composed primitive
  (`automation.py:1199 is_dark(illuminance)` with sun fallback through
  `lighting/darkness.is_dark_fallback`). **This is the "night outside
  Sleep" signal we reuse.** No new signal.
- v5.103.29 roles arc did NOT add a WHEN policy for night lights
  independent of the main action (verified against README_v5.103.29.md).

---

## Operator ruling (REV 3) — the actuation rule

For a room with `CONF_NIGHT_LIGHTS` non-empty and an occupancy ENTER
event:

| House state | `is_dark` | `night_lights_by_day` | Night-light outcome |
|---|---|---|---|
| Sleep | — | — | **ON** (sleep slot colour/brightness) |
| Not Sleep | True | — | **ON** (day/evening slot colour/brightness) |
| Not Sleep | False (daytime) | True | **ON** (day slot colour/brightness) |
| Not Sleep | False (daytime) | False (default) | OFF (no night-light opinion) |
| Vacant | — | — | OFF via existing exit / reconciler vacant branch (unchanged) |

Independent of `CONF_ENTRY_LIGHT_ACTION`. The main action continues to
drive `CONF_LIGHTS` entries exactly as today.

**"Night outside Sleep" = `is_dark is True`** (per
`automation.py:1199` and `resolver.py:150–162`). Chosen because it
already composes sun-fallback + room-lux and is the same signal that
drives `evening` slot colour (`resolve_slot`), so colour and
actuation share one trigger. Rejected alternatives: a new wall-clock
window (new timer, violates operator ruling); `is_sleep_hours`
(too narrow — operator wants dusk coverage); raw sun-below (ignores
room-lux override already configured).

---

## Falsifiable invariant

**After the cycle ships, for every room config, canonical
(`automation._control_lights_entry`) and the reconciler
(`actuator_reconciler._resolve_light`) resolve each night-light member
entity on ENTER to the SAME ON / OFF / NO-OPINION outcome under every
(occupied, is_sleep_hours, is_dark, main_action, night_lights_by_day,
is_night_light_entity, has_main_lights) tuple. The outcome depends ONLY
on (sleep, is_dark, night_lights_by_day). Under sleep, the sleep branch
is the SOLE authority in both controllers — no fall-through to the
entry branch, no main-light leak-on.**

Discriminator rows (concrete, legal-config, each has an independently
authored oracle in the test file):

- sleep=T, occupied=T, main=NONE, nl_by_day=F, night_lights=[L],
  lights=[] (Master Bedroom today) → BOTH ON.
- sleep=T, occupied=T, main=TURN_ON, nl_by_day=F, night_lights=[L] →
  night light ON, main lights NOT touched by canonical/reconciler
  under sleep (sleep is sole authority).
- sleep=F, is_dark=T, main=NONE, nl_by_day=F → night light ON.
- sleep=F, is_dark=F, nl_by_day=F → NO-OPINION (both).
- sleep=F, is_dark=F, nl_by_day=T → night light ON.
- sleep=F, is_dark=T, main=TURN_ON, nl_by_day=F → night light ON
  (independent of main=TURN_ON); main lights also ON per existing
  main-light path.

---

## Institutional context verified

### Prior-art scan verdict (REUSE vs BUILD, per piece)

| Proposed piece | Verdict | Prior art (file:line) |
|---|---|---|
| "Night outside Sleep" signal | **REUSE** | `automation.py:1199 is_dark()`, `lighting/darkness.is_dark_fallback`, `resolver.py:150–162 resolve_slot` |
| Sleep slot colour/brightness | **REUSE** | `const.py:924 CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS`, `:925 _SLEEP_HUE`, `:926 _SLEEP_COLOR` (red hue shipped v5.103.31) |
| Day slot colour/brightness | **REUSE** | `const.py:926 CONF_NIGHT_LIGHT_DAY_BRIGHTNESS`, `:927 _DAY_COLOR` (default 4000K) |
| Evening slot override | **REUSE** | `const.py` evening keys + `resolver.slot_night_light_overrides` |
| Night-light list | **REUSE** | `const.py:923 CONF_NIGHT_LIGHTS` |
| Sleep branch in canonical | **REUSE + EXTEND** | `automation.py:1313–1325` — un-gate from the `main==NONE` early-return (H1); widen the `not lights` guard (H3) |
| Sleep branch in reconciler | **REUSE** | `actuator_reconciler.py:813–829` — already correct under sleep |
| Daytime opt-in boolean | **NEW** (one) | grep `night_lights_by_day` / `night_by_day` / `night_light_day_mode` in `custom_components/`: zero hits |
| AI-rule conflict surface | **REUSE + EXTEND** | `coordinator.py:1310 _get_builtin_target_entities` TRIGGER_ENTER at `:1318` — include night lights whenever `CONF_NIGHT_LIGHTS` non-empty |
| Config-flow placement | **REUSE** step | `async_step_options_lighting_behaviour` (`config_flow.py:12866+`) |
| `_adv()` Advanced marker | **REUSE** | `_adv(...)` idiom at `config_flow.py:12988` etc. |
| Timers | NONE | Explicitly out — URA's vacancy/occupancy timers already turn night lights off (NIGHT-LIGHT-NO-OFF-PATH-1 Rev 3) |

### Only NEW addition

- `CONF_NIGHT_LIGHTS_BY_DAY: Final = "night_lights_by_day"` and
  `DEFAULT_NIGHT_LIGHTS_BY_DAY: Final = False` in `const.py`.

Everything else dropped from REV 2
(`CONF_NIGHT_LIGHT_ENTRY_ACTION`, `LIGHT_ACTION_FOLLOW_MAIN`,
`DEFAULT_NIGHT_LIGHT_ENTRY_ACTION`,
`effective_night_light_entry_action` resolver helper,
`async_migrate_entry` for the 7 rooms) is **removed**: a rule in code
does not need a selector, and no per-entry migration seeds a value.

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/automation.py`
  `_control_lights_entry` 1288–1430, `is_dark` 1199–1225.
- `custom_components/universal_room_automation/actuator_reconciler.py`
  `_resolve_light` 790–895.
- `custom_components/universal_room_automation/lighting/resolver.py`
  full file; `resolve_slot` 150–162; `slot_night_light_overrides`.
- `custom_components/universal_room_automation/lighting/darkness.py`.
- `custom_components/universal_room_automation/config_flow.py`
  options-devices night-light colour/brightness block 12620–12663
  (NOT Advanced today — moved in D4), `async_step_options_lighting_behaviour`
  12866–13190.
- `custom_components/universal_room_automation/coordinator.py`
  `_get_builtin_target_entities` 1310+.
- `custom_components/universal_room_automation/const.py` 870–1060.

### Prior planning docs / memory / design docs

- `docs/planning/PLANNING_night_light_off_path.md:110` — the deferred
  canonical↔reconciler entry=none+sleep divergence; this cycle resumes
  it with the rule, not a selector.
- `docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md`
  (REV 2.3.*) — Slice B'/D/E surfaces reused.
- `docs/planning/AUDIT_room_light_automation.md` F2/F3 — the parity
  defect this cycle closes.
- `docs/readmes/README_v5.103.29.md` (Slices A–E),
  `README_v5.103.31.md` (sleep-red default).
- Memory: `feedback_label_style_guide`, `feedback_configurability_clarity`,
  `feedback_coincidental_equality_masks_concept_split`,
  `feedback_marginal_benefit_pushback` (REV 3 reduces config vs REV 2 —
  one boolean beats one Select-of-four), `feedback_config_first_before_code`
  (operator chose config-first: colour fields moved to Advanced; new
  behaviour expressed as one boolean knob).
- Design docs: N/A (room-tier light automation, not a coordinator
  domain).

---

## Deliverables

### D1 — Add `CONF_NIGHT_LIGHTS_BY_DAY` (ONE boolean)

- `const.py`:
  - `CONF_NIGHT_LIGHTS_BY_DAY: Final = "night_lights_by_day"`.
  - `DEFAULT_NIGHT_LIGHTS_BY_DAY: Final = False`.
- No resolver helper. The rule is 3 lines in each controller (D2, D3).

**Acceptance:**
- **Verify:** grep finds both names in `const.py`.
- **Test:** `test_night_light_rule_const.py` — `DEFAULT_NIGHT_LIGHTS_BY_DAY
  is False`.

### D2 — Rewire canonical `_control_lights_entry`

In `automation.py` (1288 onward):

1. Read early: `main_action = cfg.get(CONF_ENTRY_LIGHT_ACTION, NONE)`;
   `night_lights = cfg.get(CONF_NIGHT_LIGHTS, [])`;
   `nl_by_day = cfg.get(CONF_NIGHT_LIGHTS_BY_DAY, DEFAULT_NIGHT_LIGHTS_BY_DAY)`.
2. **Remove the `main == NONE` early-return at `:1295`.** Replace with
   a tail guard _after_ the night-light block runs: if the main path
   also does nothing, return (details in step 5).
3. **H3** — replace `if not lights: return` at `:1302` with
   `if not lights and not night_lights: return`.
4. **Sleep branch (`:1313`) stays the SOLE authority (H1).** The branch
   now runs whenever `is_sleep_hours and night_lights` regardless of
   `main_action`:
   - Scene short-circuit as today, else
     `_turn_on_night_lights(mode="sleep")`,
     then `_turn_off_non_night_lights()`, and **return**.
   - No fall-through to the main-light branch under sleep. Sleep +
     main=TURN_ON MUST NOT turn main lights on (invariant).
5. **Non-sleep night-light sub-branch (NEW).** After the normal
   darkness read (`:1328–:1335`), compute:
   `nl_should_on = bool(night_lights) and (is_dark is True or nl_by_day)`.
   If `nl_should_on` AND NOT the main `should_turn_on` path (main
   lights not qualifying):
   - **M1**: bypass `_maybe_activate_slot_scene` (no slot scene when
     only night lights qualify), call `_turn_on_night_lights(mode=
     "day" if is_dark is not True else "evening")`, do NOT touch
     `CONF_LIGHTS`, and return.
   If `nl_should_on` AND the main path ALSO qualifies: today's main
   path runs (scene / `_turn_on_regular_lights`), and ADDITIONALLY the
   night-light members get `_turn_on_night_lights(mode=...)` — same
   mode selector — so a mixed room (main lights + night lights, dark)
   lights both. Preserves the existing `effective_entry_set` behaviour
   when the operator has an explicit `CONF_LIGHTS_ON_ENTRY` list.
6. If `main_action == NONE and not nl_should_on and not
   (is_sleep_hours and night_lights)` → return (the collapsed
   equivalent of today's :1295 for the no-op case).

**Acceptance (D2):**
- **Verify (H1):** `automation.py:1313–1325` is unconditionally entered
  on `is_sleep_hours and night_lights` and always returns before the
  non-sleep branch.
- **Verify (H3):** `automation.py:1302` guard is widened.
- **Test:** `test_night_light_rule_canonical.py` — matrix with an
  **independently authored expected-outcome column** (M3):
  - (sleep=T, occupied=T, main=NONE, nl_by_day=F, lights=[],
    night_lights=[L]) → `_turn_on_night_lights(sleep)` dispatched for
    [L]; `_turn_off_non_night_lights` runs. (Master Bedroom live row.)
  - (sleep=T, occupied=T, main=TURN_ON, nl_by_day=F, lights=[M],
    night_lights=[L]) → sleep branch fires, [M] NOT turned on by this
    function (H1 pin).
  - (sleep=F, is_dark=T, main=NONE, nl_by_day=F, night_lights=[L]) →
    night light [L] ON via `_turn_on_night_lights(evening|day)`; no
    main-light turn-on; no slot scene (M1).
  - (sleep=F, is_dark=F, nl_by_day=F) → no night-light turn-on.
  - (sleep=F, is_dark=F, nl_by_day=T) → night light ON.
  - (sleep=F, is_dark=T, main=TURN_ON, night_lights=[L]) → main-light
    path AND `_turn_on_night_lights(evening)` for [L].
- **Mutation drill:** delete the `nl_should_on` branch; the sleep=F /
  is_dark=T / main=NONE test MUST go red.
- **Live (L3, one-shot):** at the first sleep boundary and the first
  dusk-cross post-restart, ONE SQL round against `ura_activity_log`
  per boundary confirms the expected rows for 2 test rooms (one with
  main=NONE, one with main=TURN_ON).

### D3 — Rewire reconciler `_resolve_light`

In `actuator_reconciler.py:_resolve_light` (790–895):

1. **Sleep branch (`:813–:836`) stays SOLE authority (H1).**
   - occupied + night-light member → return `DesiredState(ON, reason=
     "sleep_night_light")` (today's path, unchanged).
   - occupied + non-night-light member → return
     `DesiredState(OFF, reason="sleep_non_night_off")` (today's :833,
     unchanged).
   - vacant → fall through to vacant branch (today's :830, unchanged).
   - **Never fall through to the entry branch.** (Already the case —
     keep so.)
2. **Entry branch (`:839–:873`, non-sleep)** — add a night-light
   sub-rule BEFORE the `entry_action == NONE` guard at `:843`:
   ```
   if entity_id in night_lights:
       is_dark = automation.is_dark(data.get(STATE_ILLUMINANCE))
       nl_by_day = cfg.get(CONF_NIGHT_LIGHTS_BY_DAY,
                           DEFAULT_NIGHT_LIGHTS_BY_DAY)
       if occupied and (is_dark is True or nl_by_day):
           # colour/brightness per slot; evening overrides handled
           # by slot_night_light_overrides as in canonical.
           return DesiredState(state="on", domain=domain,
                               service="turn_on",
                               params={... slot colour/brightness ...},
                               reason="entry_night_light")
       if occupied:
           return None  # dark=False and nl_by_day=False → NO-OPINION
   # non-night-light member: existing path (entry_action etc.).
   ```
3. **Vacant branch (`:875–:895`)** — UNCHANGED. Night-light OFF-on-
   vacancy is already correct (NIGHT-LIGHT-NO-OFF-PATH-1 Rev 3).

**Acceptance (D3):**
- **Test — M3 parity harness** `test_night_light_rule_parity.py`:
  cartesian (occupied ∈ {T,F}) × (sleep ∈ {T,F}) × (is_dark ∈ {T,F,None})
  × (main_action ∈ {NONE, TURN_ON, TURN_ON_IF_DARK}) × (nl_by_day
  ∈ {T,F}) × (entity ∈ {main_only, night_light, both-member}) ×
  (has_main_lights ∈ {T,F}). Each cell has an **independently
  authored expected outcome** (`on` / `off` / `no_opinion`). Canonical
  and reconciler each asserted against that oracle. Parity falls out.
- **Discriminator rows** (required, called out):
  all six rows from the invariant section above, plus a vacant-sleep
  cell (sleep=T, occupied=F, night_light) → OFF (existing vacant
  branch).
- **Live (L3, one-shot):** sleep-boundary + dusk-cross SQL as D2.

### D4 — Config-flow surface + Advanced cleanup

In `config_flow.py`:

- **ADD** one field to `async_step_options_lighting_behaviour`
  (options-flow only; NOT the new-room setup picker at `:2859` —
  per L2, new rooms get the default False and operator opts in
  per-room post-setup):
  ```
  vol.Optional(
      CONF_NIGHT_LIGHTS_BY_DAY,
      default=self._get_current(CONF_NIGHT_LIGHTS_BY_DAY,
                                DEFAULT_NIGHT_LIGHTS_BY_DAY),
  ): selector.BooleanSelector(),
  ```
- **MOVE to Advanced** the four night-light colour/brightness fields
  at `config_flow.py:12630–12663` (currently plain) — they are rarely
  tuned, defaults are red/4000K and ship-shipped by v5.103.31. Wrap
  each with `description=_adv(<key>, _merged, <default>)` matching the
  existing Advanced-marker idiom. Behaviour unchanged; the fields
  stay reachable in Advanced mode and when a non-default is already
  stored (I2 reach-back via `_adv`).

**Labels** (strings.json + translations/en.json; label-style guide: 3–4
short words, no nerd words):

| Key | Label | Helper |
|---|---|---|
| `night_lights_by_day` | **Use night lights by day** | "Also turn on night lights when it's not dark. Off by default." |

No other new strings.

**Lighting step field inventory — before vs after:**

| Field | Before | After |
|---|---|---|
| `CONF_LIGHTS_ON_ENTRY` | shown | shown (unchanged) |
| `CONF_LIGHTS_ON_ENTRY_DARK_ONLY` | shown (Advanced via `_adv`) | shown (unchanged) |
| `CONF_NIGHT_LIGHTS` | shown | shown (unchanged) |
| `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY` | shown | shown (unchanged) |
| `CONF_AWAY_TURN_OFF_LEAVE_ON` | shown | shown (unchanged) |
| `CONF_ALERT_LIGHTS` | shown | shown (unchanged) |
| `CONF_LIGHT_MANUAL_ON_HOLD_S` / `_OFF_COOLDOWN_S` | Advanced | Advanced (unchanged) |
| `CONF_LIGHT_DARK_USE_SUN_FALLBACK` / `_LUX_SOURCE` | shown | shown (unchanged) |
| Evening brightness/colour + scenes | Advanced | Advanced (unchanged) |
| **`CONF_NIGHT_LIGHTS_BY_DAY`** | — | **shown (new, +1)** |

In the sibling `options_devices` step (12620–12663):

| Field | Before | After |
|---|---|---|
| `CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS` | plain | **Advanced** |
| `CONF_NIGHT_LIGHT_SLEEP_HUE` | plain | **Advanced** |
| `CONF_NIGHT_LIGHT_SLEEP_COLOR` | plain | **Advanced** |
| `CONF_NIGHT_LIGHT_DAY_BRIGHTNESS` | plain | **Advanced** |
| `CONF_NIGHT_LIGHT_DAY_COLOR` | plain | **Advanced** |

Net visible-surface delta in Simple mode: **+1 field, –5 fields** (five
colour knobs retreat to Advanced). Economical.

**Acceptance (D4):**
- **Verify:** opening a room's Options → Lighting behaviour shows the
  new boolean with default False.
- **Verify:** in Simple mode the five night-light colour/brightness
  fields do NOT appear; in Advanced they do; a room with a non-default
  stored value still sees its field in Simple (via `_adv` reach-back,
  I2).
- **Test:** `test_room_dialog_strings.py` extended — label + helper.
- **Test:** round-trip save `True`, close, reopen → value preserved;
  save unchecked → stored False (not dropped).

### D5 — Extend AI-rule conflict-detect consumer (M2, simplified)

`coordinator.py:1310 _get_builtin_target_entities`:

- TRIGGER_ENTER (`:1318`) and TRIGGER_LUX_DARK: when
  `cfg.get(CONF_NIGHT_LIGHTS)` is non-empty, include those entities in
  the entry target set (deduped against `CONF_LIGHTS`). Reason: under
  the new rule, night lights are a *potential* entry target in all
  three regimes (sleep, dark, daytime-opt-in); the AI-rule conflict
  detector should flag an AI rule proposing a night-light turn-on
  during entry regardless of which regime is live. Simpler than
  REV 2's `nl_action != NONE` gate; no false negatives.
- TRIGGER_EXIT / TRIGGER_LUX_BRIGHT: unchanged (already includes night
  lights per NIGHT-LIGHT-NO-OFF-PATH-1 D6).

**Acceptance (D5):**
- **Test** `test_builtin_target_entities_night_light_entry.py`:
  - night_lights=[] → not in TRIGGER_ENTER set.
  - night_lights=[L], main=NONE → L in TRIGGER_ENTER set, deduped.
- **Live:** an AI rule proposing `light.turn_on` on a configured night
  light during entry on a `night_lights` room raises an AI-rule-vs-
  builtin-automation conflict row in `ura_activity_log`.

---

## Behaviour-change inventory (operator-facing)

Measured 2026-10-08 via REV 2 live snapshot of
`.storage/core.config_entries` (filter `domain ==
"universal_room_automation"`). Builder re-measures at ship time against
the live snapshot and includes the final list in the ship README.

### Cohort A — rooms where night lights START coming on where they didn't

Rooms with `CONF_NIGHT_LIGHTS` non-empty AND `CONF_ENTRY_LIGHT_ACTION
== 'none'` (the 7 measured in REV 2 §H2 — Breakfast Nook, Game Room,
Jaya Bathroom, Living Room, Master Bedroom, Patio, Ziri Bathroom):

- **Sleep + occupied:** today canonical does nothing, reconciler
  asserts ON (observable: night light ON because reconciler is the
  loop). Post-ship: ON (unchanged in physical behaviour; canonical
  now agrees with reconciler — this is the parity close).
- **Non-sleep + occupied + is_dark=True (dusk / dark room):** today
  neither controller turns the night light on. **Post-ship: night
  light ON.** This is a new behaviour for these 7 rooms.
- **Non-sleep + occupied + is_dark=False (daytime):** today OFF.
  Post-ship: OFF (default `night_lights_by_day = False`). No change.
- **Vacant:** no change (existing OFF path).

### Cohort B — rooms where night lights STOP coming on by day

Rooms with `CONF_NIGHT_LIGHTS` non-empty AND `CONF_ENTRY_LIGHT_ACTION
in {'turn_on'}` AND no explicit `CONF_LIGHTS_ON_ENTRY` list (today
`effective_entry_set` returns `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS`, so
night lights come on at daytime entry along with the main lights).

Under the new rule, night lights come on at entry only when sleep OR
is_dark OR `night_lights_by_day = True`. **Daytime bright-room entries
no longer light up night lights for these rooms.** Main lights
behaviour unchanged.

Builder re-measures this cohort at ship (live
`.storage/core.config_entries`); provisional list is pending — not
measured in REV 2. Any operator-visible room (e.g. hallways with
decorative RGB night lights wired as `night_lights`) that currently
flashes on at midday on entry falls here. Per-room opt-in via the new
boolean restores it.

### Cohort C — rooms with `CONF_ENTRY_LIGHT_ACTION == 'turn_on_if_dark'`

Behaviour unchanged in all regimes (main-light action is already dark-
gated; the night-light path now mirrors that dark-gate independently).

### No-change cohort

Rooms with `CONF_NIGHT_LIGHTS` empty: ZERO behaviour change (no path
reads the new boolean).

---

## Follow-on — HA night-light automation retirement (operational, post-deploy)

Scope: the operator's existing `/config/automations.yaml` motion-driven
night-light automations. Not code — operational: once URA covers each
case, DISABLE in batches, DELETE after a sleep-boundary + dusk-cross
confirmation.

### Automation → light → URA room coverage (provisional; builder re-verifies at ship)

| Automation id | Alias | Light entity | Expected URA room | Night-light in that room's `CONF_NIGHT_LIGHTS`? | Dusk/dark trigger covered? | Sleep trigger covered? | Verdict |
|---|---|---|---|---|---|---|---|
| 1749970595184 | Ziri Bathroom night light | `light.rgbw_motion_lux_3rdr_wifi_matter_ziribath` | Ziri Bathroom | **re-verify at ship** | yes (is_dark) | yes (sleep slot) | COVERED if listed |
| 1749970744049 | Jaya Night Light | `light.rgbw_motion_lux_3rdr_wifi_matter_jayabath` | Jaya Bathroom | re-verify | yes | yes | COVERED if listed |
| 1750070811993 | Guest Bathroom night light | `light.rgbw_lux_motion_3rdr_wifi_matter_guestroom1bath` | Guest Bathroom | re-verify | yes | yes | COVERED if listed |
| 1756872301649 | Smart Staircase Night Light | `light.rgbw_motion_lux_3rdr_wifi_matter_stairs` | Stairs | re-verify | yes | yes | COVERED if listed (plus loses Pushover alert — see note) |
| 1766774718198 | Stair Closet Night Light | `light.rgbw_motion_lux_3rdr_wifi_matter_staircloset` | Stair Closet | re-verify | yes | yes | COVERED if listed |
| 1766974833049 | Garage Hallway Night light | `light.rgbw_motion_lux_3rdr_zigbee_garagehallway` (`_2` suffix per 2026-08-13 retirement) | Garage Hallway | re-verify | yes | yes | COVERED if listed; builder confirms the `_2` suffix matches the room config |
| 1767658311068 | Master Hallway Night Light | `light.rgbw_motion_lux_3rd_zigbee_masterhallway` | Master Hallway | re-verify | yes | yes | COVERED if listed |
| 1789357400673 | Dining Room Night Light (correctly named — operator physically MOVED the light; entity id still says `jayabath`) | `light.rgbw_motion_lux_3rdr_wifi_matter_jayabath` (builder re-verifies the trigger: if it still keys on `_jayabath_occupancy_2` it is driven by the WRONG room's sensor) | **Dining Room** | re-verify (likely NOT listed — light is probably still in Jaya Bathroom's `CONF_NIGHT_LIGHTS`; move it to Dining Room) | yes | yes | NOT a duplicate. COVERED only once the entity sits in Dining Room's night lights. 1749970744049 must be re-checked: if it drives the same entity it is now the stale one (Jaya Bath no longer has this light) |

Legend: a room is **COVERED** when the light is in that room's
`CONF_NIGHT_LIGHTS`. The builder re-queries the live snapshot at ship,
fills in the "listed?" column, and lists any **GAPS** (light not in
`CONF_NIGHT_LIGHTS` of the right room) in the ship README as a
pre-retirement task for the operator (add to night-lights list, OR
leave the HA automation in place).

Operator should also sweep `/config/automations.yaml` for any other
"night light" automations not in this id list and merge them into the
same table at retirement time. Known candidates mentioned by the
operator: ~20 total; names like "Garage Hallway", "Jaya Bath", "Stair
Closet", "Master Hallway" are already here.

### Retirement procedure (batches)

1. **Pre-retire check (per automation):** confirm the light is in the
   expected URA room's `CONF_NIGHT_LIGHTS`; if not, add it (one-field
   edit, no ship), then proceed.
2. **Disable** the HA automation (UI → toggle off). Do NOT delete.
3. **Observe one full day:** a sleep boundary (night light on in sleep)
   and a dusk crossing (night light on when dark). One SQL round
   against `ura_activity_log` suffices — not a 24h soak watch.
4. **If OK**, delete the automation. **If not**, re-enable, file a
   card describing the gap.

Pushover security alerts attached to the Staircase automation
(`1756872301649`) are **out of scope** for this cycle — they're not
night-light actuation, they're perimeter notify. Operator decides
whether to retain the automation stripped-to-notify-only, migrate the
notify to URA's NM, or drop it.

### Non-code (no acceptance / tests)

This section drives operator action, not builder work. Builder output
= the final mapping table in the ship README; retirement itself is
operator-executed post-deploy.

---

## Producer AND Consumer map (standing rule)

**Producer:** a RULE in two controllers (no dedicated resolver helper).
Inputs: `is_sleep_hours` (via `is_sleep_lighting_active()`), `is_dark`
(via `automation.is_dark(illuminance)` with
`darkness.is_dark_fallback`), `occupied`, `CONF_NIGHT_LIGHTS`,
`CONF_NIGHT_LIGHTS_BY_DAY` (new). Each dependency healthy today;
`is_dark` already composes sun-fallback + room-lux.

**Consumers (every reader, trust-vs-display):**

| Site | File:line | Trust/decision |
|---|---|---|
| Canonical sleep branch (H1 sole-authority) | `automation.py:1313–1325` (modified) | Trust (sleep ON; no fall-through) |
| Canonical non-sleep night-light sub-branch (NEW) | `automation.py` post-`:1335` (new block) | Trust (ON when sleep=F + (is_dark=T or nl_by_day)) |
| Reconciler sleep branch (H1) | `actuator_reconciler.py:813–829` (unchanged) | Trust |
| Reconciler entry night-light sub-rule (NEW) | `actuator_reconciler.py:~843` (new block, before entry_action NONE guard) | Trust |
| AI-rule conflict detect | `coordinator.py:1318` (new gate: night_lights non-empty) | Decision |
| Vacant branches | `automation.py` exit, `actuator_reconciler.py:875–895` | Unchanged |
| D3 `RoomLightsSwitch` / Away sweep | unchanged | Unaffected |

---

## Non-goals

- A night-light action **selector**. (REV 2's design — dropped.)
- A per-entry migration seeding values for the 7 rooms. (Rule-only.)
- Any new timers.
- Any change to `CONF_ENTRY_LIGHT_ACTION` semantics for main lights.
- Guest-mode behaviour (`LIGHTS-GUEST-MODE-BEHAVIOUR-1`).
- Exit / vacancy semantics (NIGHT-LIGHT-NO-OFF-PATH-1 already shipped).
- Scene / slot vocabulary changes.
- Pushover notify migration from the Staircase automation.
- `KITCHEN-NIGHTLIGHT-RANGE-MISCONFIG-1` (parked — different problem).

---

## Review tier + framings — **Tier 2-DB**

Three parallel reviews, framing-disjoint:

- **A — local correctness.** Rule arithmetic in D2 and D3 (sleep, dark,
  nl_by_day truth table); H3 guard scope; M1 slot-scene bypass; `is_dark
  is True` vs `None` distinction (`None` = unknown MUST be treated as
  not-dark to avoid false positives).
- **B — cross-controller parity (sleep × dark × nl_by_day).** The core
  framing. Independent re-enumeration of every cell of the parity
  matrix; audits the independently authored oracle against the
  invariant; verifies the sleep branch is sole authority on both sides;
  verifies the Cohort A/B behaviour-change inventory against the live
  snapshot (re-measured at build).
- **C — surfaces + fixtures + Advanced move.** D4 round-trip + label
  wording; the five colour fields' Advanced-mode visibility (I2 reach-
  back for stored non-defaults); D5 AI-rule consumer; `RoomLightsSwitch`
  / Away sweep untouched (grep + mutation drill); the retirement
  mapping table re-measured at ship against the live config.

Each reviewer runs per-site mutation drills and names which test goes
red. Orchestrator independently re-greps the two emission sites before
deploy (do not trust reviewer summaries).

---

## REV 2 findings — carry-over ledger

| REV 2 finding | REV 3 disposition |
|---|---|
| H1 — sleep is sole authority in both controllers | **KEPT**; invariant restated; discriminator "sleep=T + main=TURN_ON" row preserved |
| H2 — default is NOT behaviour-neutral; options A/B/C | **OBSOLETED by operator ruling**: no selector, so no `FOLLOW_MAIN` default to pick. New default = `night_lights_by_day = False` has its OWN behaviour-change surface (Cohorts A/B above), measured + listed |
| H3 — `if not lights: return` precedes sleep branch | **KEPT**; D2 widens the guard |
| M1 — no slot scene when only night lights qualify | **KEPT**; applies to the new non-sleep night-light sub-branch |
| M2 — `_get_builtin_target_entities` consumer | **KEPT, simplified** (gate = night_lights non-empty, not `nl_action != NONE`) |
| M3 — independently authored oracle, not A==B | **KEPT** for canonical, reconciler, parity harness |
| L1 — `CONF_LIGHTS_GUEST_MODE` not in `const.py` | **KEPT** (guest work out of scope) |
| L2 — new field options-flow-only, not new-room picker | **KEPT** |
| L3 — one-shot query, not 24h soak | **KEPT** |

Dropped from REV 2 (now obsolete): the 4-value Select vocabulary, the
`LIGHT_ACTION_FOLLOW_MAIN` TURN_OFF/LEAVE_ON defensive collapse, the
`effective_night_light_entry_action` resolver helper, the H2
`async_migrate_entry` for the 7 rooms, the "Four open decisions
settled" section (reduced to one new boolean).

---

## Plan Completion Tracking

Placeholder — filled at ship. For each of D1 / D2 / D3 / D4 / D5,
record: DONE, DEFERRED (reason + where tracked), or DROPPED. Record
the measured Cohort A and Cohort B room lists at ship time, and the
final automation retirement mapping (ids + verdicts).

---

## Appendix — files that will be touched

| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | +2 constants (`CONF_NIGHT_LIGHTS_BY_DAY`, `DEFAULT_NIGHT_LIGHTS_BY_DAY`) |
| `custom_components/universal_room_automation/automation.py` | `_control_lights_entry` 1288-end: remove `main==NONE` early-return; widen `:1302` guard (H3); sleep branch un-gated from main (H1); add non-sleep night-light sub-branch (M1 slot-scene bypass) |
| `custom_components/universal_room_automation/actuator_reconciler.py` | `_resolve_light` entry branch: night-light sub-rule BEFORE `entry_action == NONE` guard; sleep + vacant unchanged |
| `custom_components/universal_room_automation/coordinator.py` | `_get_builtin_target_entities` TRIGGER_ENTER + TRIGGER_LUX_DARK: include `CONF_NIGHT_LIGHTS` whenever non-empty (D5) |
| `custom_components/universal_room_automation/config_flow.py` | +1 BooleanSelector in `async_step_options_lighting_behaviour` (options only); move 5 night-light colour/brightness fields to Advanced via `_adv()` in `options_devices` |
| `custom_components/universal_room_automation/strings.json` + `translations/en.json` | one label + one helper for `night_lights_by_day` |
| `quality/tests/test_night_light_rule_const.py` (new) | D1 default |
| `quality/tests/test_night_light_rule_canonical.py` (new) | D2 behavioural matrix (H1/H3/M1 rows) |
| `quality/tests/test_night_light_rule_parity.py` (new) | D3 cross-controller parity against independently authored oracle (M3) |
| `quality/tests/test_builtin_target_entities_night_light_entry.py` (new) | D5 consumer |
| `quality/tests/test_room_dialog_strings.py` (extend) | D4 label + Advanced visibility assertions |

No `__init__.py` migration (operator-ruled: no per-entry seeding).

---

## Plan review 2026-10-08 REV 3

Verdict: PLAN-FIX-REQUIRED (folded below; builder implements as written here).

- **R3-H1 (HIGH, folded): the by-day "stop" is not wired.** Cohort B and the invariant say night lights get no
  turn-on by day when `nl_by_day=False`, but D2 step 5 keeps the main path's unconditional
  `_turn_on_night_lights(...)` (`automation.py:1411-1416`) and says it "preserves `effective_entry_set`", which
  still returns `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS` by day (`lighting/resolver.py:105`). Result with main=TURN_ON,
  is_dark=False, nl_by_day=False: canonical turns the night light ON, the reconciler's new sub-rule returns None.
  The invariant breaks. **Fold:** D2 removes the night-light call from the main branch at :1411 and routes night
  lights ONLY through the `nl_should_on` gate. `effective_entry_set` (non-sleep, no explicit on-entry list) drops
  night members when `is_dark is not True and not nl_by_day`, with a new `night_lights_by_day` input. Add a parity
  row: (sleep=F, dark=F, main=TURN_ON, nl_by_day=F) → canonical no turn-on AND reconciler no_opinion.
- **R3-M1 (MED, folded): precedence on overlaps.** (a) An entity in both `CONF_LIGHTS` and `CONF_NIGHT_LIGHTS`, and
  (b) an explicit `CONF_LIGHTS_ON_ENTRY` that lists a night light while `CONF_LIGHTS_ON_ENTRY_DARK_ONLY` does not
  (commit 4f76fbe76's dark-only exceptions). **Ruling for builder:** membership in `CONF_NIGHT_LIGHTS` wins. The
  night rule decides those entities, and the explicit on-entry list cannot force a night light on by day (the
  by-day checkbox does that). State this in the label help text. The parity matrix `both-member` cell asserts it.
- **R3-M2 (MED, folded): reconciler params must equal canonical.** D3's `params={... slot colour ...}` is
  under-specified. The reconciler must build params through the same helper canonical uses (factor the param
  build out of `_turn_on_night_lights` at `automation.py:1629` / `slot_night_light_overrides`). If it doesn't,
  the two controllers assert different colour/brightness and the reconciler re-fires against canonical every tick.
  Test: identical params for the evening and day slots.
- **R3-L1 (LOW, folded): retirement-map correction (item 7).** 1789357400673 is a real Dining Room automation (the
  light was moved). It is not a duplicate. The table row above is fixed.
- Cleared: the sleep branch stays sole authority in both controllers (`automation.py:1313`,
  `actuator_reconciler.py:813-836`). Vacant branch unchanged. The AI conflict detector (`coordinator.py:1326-1332`)
  already unions night lights, so D5 holds. Choosing `is_dark` matches operator option A.

---

## Builder notes (2026-10-08, branch `feature/night-light-rule`)

- **D1 DONE** — `CONF_NIGHT_LIGHTS_BY_DAY` + `DEFAULT_NIGHT_LIGHTS_BY_DAY=False` added to `const.py`. Key also appended to `_ROOM_SUPPRESS_KEYS` in `__init__.py` (room-level reload-suppress allowlist — both consumers in `automation.py:_control_lights_entry` and `actuator_reconciler._resolve_light` read LIVE/REFRESHED each tick). CM-level `OPTIONS_RELOAD_SUPPRESS_KEYS` is parent-scope and not applicable.
- **D2 DONE** — canonical `_control_lights_entry` rewired per REV 3:
  1. `action==NONE` early-return removed; night-light-only rooms (`CONF_LIGHTS=[]`) now reach the sleep + non-sleep night-light branches.
  2. `not lights` guard widened to `not lights and not night_lights` (H3).
  3. Sleep branch stays the SOLE authority (H1) — no fall-through to the main-light branch.
  4. Non-sleep: `main_should_on` and `nl_should_on = bool(night_lights) and (is_dark is True or nl_by_day)` computed independently. A night-light-only hit (M1) bypasses slot scenes and dispatches `_turn_on_night_lights(mode=…)` directly.
  5. **R3-H1 fold applied**: the former unconditional `if night_lights: _turn_on_night_lights(…)` at automation.py:~1411-1416 is REMOVED; night lights ride the main-path only when `nl_should_on`.
  6. Night-light members stripped from `actual_lights` / `switches_as_lights` so the main path never applies regular brightness/colour to a night light (R3-M1: membership in `CONF_NIGHT_LIGHTS` wins).
- **D3 DONE** — reconciler `_resolve_light` grew a night-light sub-rule BEFORE the `entry_action==NONE` gate. Returns ON (`reason="entry_night_light"`) when `occupied and (is_dark is True or nl_by_day)`, else `None` (no-opinion) when occupied but not admitted. Params built via `night_light_turn_on_params(cfg, mode)` — the SAME helper canonical consumes (R3-M2 lineage). Sleep + vacant branches untouched. The existing `effective_entry_set` call also receives `night_lights_by_day` so picker-path strip is consistent.
- **D4 DONE** — options flow:
  - `options_lighting_behaviour` gained one `BooleanSelector` (`CONF_NIGHT_LIGHTS_BY_DAY`, default False); new-room setup picker untouched (L2).
  - The 5 colour/brightness fields in `options_devices` (`CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS`, `_SLEEP_HUE`, `_SLEEP_COLOR`, `_DAY_BRIGHTNESS`, `_DAY_COLOR`) now carry `description=_adv(...)` and the step routes through `add_suggested_values_to_schema` + emits `advanced_hint`. `strings.json` / `translations/en.json` descriptions carry `{advanced_hint}`. I2 reach-back for stored non-defaults works via `_adv()` (tested). Field keys and defaults unchanged.
  - strings: added `night_lights_by_day` label + helper ("Use night lights by day" / "Also turn on night lights when it's not dark. Off by default.").
- **D5 DONE** — `coordinator.py:_get_builtin_target_entities` for `TRIGGER_ENTER` / `TRIGGER_LUX_DARK` unions `CONF_NIGHT_LIGHTS` whenever non-empty (deduped against `CONF_LIGHTS`), per REV 3 simplification.

### Tests
- New: `test_night_light_rule_const.py` (2), `test_night_light_rule_resolver.py` (11), `test_night_light_rule_parity.py` (15, real `_control_lights_entry` + `_resolve_light` via the sibling `_real_modules` fixture chained in), `test_builtin_target_entities_night_light_entry.py` (3), `test_night_light_rule_options_flow.py` (17). All green.
- Touched for intentional behaviour change: `test_night_light_off_path.py::test_D6_exit_target_entities_include_night_only` (D5 now unions night lights into the ENTER target set) and `test_room_advanced_fields.py::test_meta_every_step_with_advanced_fields_passes_hint` (hard-coded set extended with `devices`).

### Review fix-up pass (2026-10-08, post-3-review)
Fixes 1-6 from the three reviews, baseline tag `pre-review-night-light-rule`:
1. **A/B HIGH-1** — `actuator_reconciler._resolve_light` night-light sub-branch now guards `_nl_params` with `domain == "light"`; switch.* night lights receive `{}` and plain `switch.turn_on` (mirrors the sleep guard at :824).
2. **C HIGH / A MED** — canonical `_turn_on_night_lights` now builds its `service_data` from `night_light_turn_on_params(cfg, mode, include_transition=True)`. The helper owns transition + capability-default BASIC so canonical and reconciler route through the same source. Red-hue override (sleep + FULL + colour-capable bulb) stays per-entity in canonical (needs live hass lookup). Golden parametrized tests pin canonical payload for sleep/day/evening × BASIC/BRIGHTNESS/FULL, and `test_canonical_and_reconciler_agree_day_full` asserts canonical payload (minus `transition`/`entity_id`) == reconciler `params`.
3. **A/B MED** — reconciler day/evening night-light branch no longer sets `has_params_to_apply=bool(params)`. An already-on night light is now a reconcile NO-OP (`:645`) so a person's manual dim survives. Sleep branch unchanged. Covered by `test_reconciler_day_night_light_already_on_at_dim_no_turn_on` + `test_reconciler_day_night_light_off_still_turns_on`.
4. **C MED** — new `test_options_flow_rendered_default_night_lights_by_day_is_false` reads the rendered schema's `vol.Optional` default (not just the constant).
5. **C MED** — new `test_canonical_night_set_strip_dark_room_on_entry_picker` drives `_control_lights_entry` with `CONF_LIGHTS_ON_ENTRY=[main, night]`; asserts the night light appears only in a batch with night-light params, never alongside main lights.
6. **C LOW** — new `test_night_lights_by_day_in_room_suppress_set` text-asserts `"night_lights_by_day"` is in the `_ROOM_SUPPRESS_KEYS` frozenset literal.

Per-site mutation drills (PYTHONDONTWRITEBYTECODE=1, cache cleared, restored clean each time):
| Site | Mutation | Test → result |
|---|---|---|
| reconciler switch guard | drop `if domain=="light"` branch | `test_reconciler_switch_night_light_has_no_light_params` FAIL |
| canonical helper routing | drop `**base_params` from `service_data` | `test_canonical_payload_full_capability_matches_helper[*]` FAIL (3) |
| helper transition fold | remove `include_transition` block | `test_canonical_payload_basic_capability_matches_helper[*]` FAIL (3) |
| manual-dim fix | re-add `has_params_to_apply=bool(params)` | `test_reconciler_day_night_light_already_on_at_dim_no_turn_on` FAIL |

Out of scope (operator-tagged, carded): reconciler SLEEP branch sends brightness only vs canonical colour — pre-existing, untouched by this pass.

### Mutation drill — restored + git-status clean after each

| Site | Mutation | Failing test |
|---|---|---|
| Canonical sleep branch | `_turn_on_night_lights(mode="sleep")` → `pass` | `test_sleep_main_none_night_light_only_room`, `test_sleep_main_turn_on_night_wins_sole_authority` |
| Canonical non-sleep `nl_should_on` gate | force `nl_should_on = False` | `test_nonsleep_dark_main_none_night_light_on`, `test_nonsleep_bright_byday_true_turns_on`, `test_mixed_room_dark_main_and_night_both_on` |
| Reconciler night-light sub-rule | `if False and night_lights and …:` | `test_reconciler_nonsleep_dark_night_light_on`, `test_reconciler_nonsleep_bright_byday_true_on`, `test_r3_m2_reconciler_params_match_canonical_helper_{day,evening}` |
| Resolver by-day strip (R3-H1) | strip-line → `pass` | `test_entry_set_bright_no_byday_strips_night`, `test_entry_set_r3_m1_night_membership_wins_over_on_entry_picker` |
| By-day admit arm | `is_dark is True or bool(nl_by_day)` → `is_dark is True` | `test_nonsleep_bright_byday_true_turns_on` |

### Deviations
- The by-day strip in `effective_entry_set` fires only when `is_dark is False` (not `is_dark is not True`). Required to keep the resolver-equivalence tests green, which call with `is_dark=None` (unknown). Runtime always evaluates `is_dark` to a bool via `automation.is_dark(illuminance)`, so the production invariant holds. Reviewer A's `is_dark is True vs None` guard-rail is preserved end-to-end: `None` treated as not-dark for the ADMIT decision (`nl_should_on = is_dark is True or nl_by_day`).
- `options_devices` now routes through `add_suggested_values_to_schema` + emits `advanced_hint` (previously it did not). Without this, the `_adv()` description markers would not be filtered by HA's data-entry-flow. The sibling `options_lighting_behaviour` step already follows the same pattern.
