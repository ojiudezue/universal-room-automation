# PLANNING — Night-light action selector (NIGHT-LIGHT-ACTION-SELECTOR-1)

Card: `NIGHT-LIGHT-ACTION-SELECTOR-1` (operator-approved 2026-09-15:
"another selector to show how we should actuate night light… it removes
all doubt"). Blocks `LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1`. Follows the
room-lighting-roles arc (v5.103.29 Slices A–E, v5.103.30, v5.103.31) —
that arc shipped STRUCTURE (role pickers, slots, scenes, hold, Away
sweep) but did NOT split the overloaded `CONF_ENTRY_LIGHT_ACTION`
field. The split is this cycle.

Status: pre-planning REV 2 (plan-review 2026-10-08 PLAN-FIX-REQUIRED
findings H1/H2/H3/M1/M2/M3/L1/L2/L3 folded in — see "Plan review
2026-10-08" section at the end).

Tier: **Tier 2-DB** (standing policy 2026-06-08: regression-prone
cross-coordinator change gets three framing-disjoint reviews). Shared
primitive consumed by TWO independent controllers (canonical
`_control_lights_entry` + actuator reconciler `_resolve_light`) whose
historical disagreement is the exact defect this cycle closes. Final
tier gate: operator.

---

## STEP 1 — Premise re-verified on current develop

Verdict: **STILL-REAL** (plan proceeds).

Evidence (file:line, develop @ working tree 2026-10-08):

- **(a) `CONF_ENTRY_LIGHT_ACTION` still gates night-light actuation on
  entry.** `automation.py:1292` reads the action; `automation.py:1295
  if action == LIGHT_ACTION_NONE: return` fires BEFORE the
  `is_sleep_hours and night_lights` branch at `automation.py:1313`.
  A room set to `entry_light_action=none` never turns on its night
  lights at entry, even under house-Sleep.
- **(b) Canonical vs reconciler divergence on entry=none + sleep is
  live.** `actuator_reconciler._resolve_light` reads `sleep` at
  `:800`; the sleep + night-light branch at `:813–:829` asserts the
  night-light entity ON for occupied members **BEFORE** the
  `entry_action == NONE` check at `:843`. So under (sleep + occupied
  + night-light member + main=NONE): canonical does nothing;
  reconciler asserts ON. This is LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1
  (AUDIT_room_light_automation.md F2/F3) still live.
- **(b′) H1 corollary — sleep branch is the ONLY authority in both
  controllers today.** Verified `automation.py:1313–1325` ALWAYS
  returns after the sleep branch; the non-sleep `should_turn_on`
  path at `:1332–:1340` is unreachable under sleep. In
  `actuator_reconciler.py:813–836` the sleep branch returns for
  occupied night-light members; vacant night-light members fall
  through to the vacant branch (OFF authority), never to the entry
  branch. And `lighting/resolver.py:95–97` short-circuits
  `effective_entry_set` to the night list whenever
  `is_sleep_hours and night` — any downstream reader under sleep
  sees "night only." The redesign MUST preserve this: sleep stays
  the one authority; no fall-through to the entry branch under
  sleep in either controller.
- **(c) The v5.103.29 roles arc did NOT add a night-light action
  policy.** New keys added by that arc (per
  `docs/readmes/README_v5.103.29.md`): `CONF_LIGHTS_ON_ENTRY`,
  `CONF_LIGHTS_ON_ENTRY_DARK_ONLY`, `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`,
  `CONF_AWAY_TURN_OFF_LEAVE_ON`, `CONF_OUTDOOR_LIGHT_SENSOR`,
  `CONF_OUTDOOR_DARK_LUX`, slot evening/scene keys. **Guest key
  (`CONF_LIGHTS_GUEST_MODE`) is NOT in `const.py` on current
  develop** — the plan-REV1 draft mis-asserted this; corrected per
  L1. Guest semantics remain owned by
  `LIGHTS-GUEST-MODE-BEHAVIOUR-1` and out of scope here. None of the
  shipped keys provides a WHEN policy for night lights independent
  of the main action; the Slice B' resolver `effective_entry_set` is
  only reached AFTER the main-action early-return. Not moot.

---

## Institutional context verified

### Greps run + results (REUSED vs NEW per proposed addition)

- `CONF_ENTRY_LIGHT_ACTION` — the overloaded field being split.
  `const.py:989`, used `automation.py:1292`, `actuator_reconciler.py:839`,
  `config_flow.py:2859` (new-room setup) and `:12774` (options flow).
  **REUSED** (unchanged; this cycle adds a sibling, does not alter
  the existing field semantics).
- `CONF_EXIT_LIGHT_ACTION` — mirror pattern on exit.
  `const.py:990`, `actuator_reconciler.py:840`. **REUSED** as the
  precedent shape for the new field.
- `LIGHT_ACTION_*` vocabulary — `const.py:1055–1059`. **REUSED**
  where meanings map; one **NEW** value `LIGHT_ACTION_FOLLOW_MAIN`
  (grepped `_FOLLOW_`/`_INHERIT_` on const.py: zero hits).
  Important correction (L2): the main-light entry picker in
  `config_flow.py:2847–2851` offers only three values
  (`LIGHT_ACTION_NONE`, `LIGHT_ACTION_TURN_ON`,
  `LIGHT_ACTION_TURN_ON_IF_DARK`); `TURN_OFF` / `LEAVE_ON` are
  **exit-only** in the UI today. The resolver's TURN_OFF/LEAVE_ON →
  NONE collapse is therefore **defensive** (handles values set
  programmatically or by future schema drift), not a user-visible
  behaviour. Called out explicitly in D1.
- `CONF_NIGHT_LIGHTS` — `const.py:923`. **REUSED**.
- `CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS` / `_SLEEP_COLOR` /
  `_DAY_BRIGHTNESS` / `_DAY_COLOR` — `const.py:924–927`. **REUSED**.
- `CONF_LIGHTS_ON_ENTRY` / `_DARK_ONLY` — `const.py:1012-1013`.
  **REUSED**.
- `CONF_LIGHTS_GUEST_MODE` — **grep of `const.py` returns zero hits
  on current develop**; the key does not exist in code (plan-REV1
  claim was wrong; corrected). Guest work tracked under
  `LIGHTS-GUEST-MODE-BEHAVIOUR-1`; out of scope here.
- `lighting/resolver.py` — `effective_entry_set` / `effective_exit_set`
  from Slice A/B'. **REUSED** as the extension point. Note
  `resolver.py:95–97` already enforces "night-only under sleep" — the
  new resolver helper below must COMPOSE with it, not fight it.
- `coordinator.py:1310 _get_builtin_target_entities` — AI-rule
  conflict-detect consumer (M2). **REUSED + EXTENDED**: today its
  TRIGGER_ENTER branch at `:1318` lists only `CONF_LIGHTS` + `CONF_FANS`
  + climate; it OMITS `CONF_NIGHT_LIGHTS`. Correct today because
  night lights are never a URA entry target under the current
  overload. Once this cycle makes `nl_action != NONE` a reachable
  entry-time URA write, night lights MUST appear in the TRIGGER_ENTER
  conflict-detect set when `nl_action != NONE` for that room
  (otherwise an AI rule targeting a night light at entry would not
  flag a conflict). See D5.

### NEW additions (justified)

- `CONF_NIGHT_LIGHT_ENTRY_ACTION` — the sibling to
  `CONF_ENTRY_LIGHT_ACTION`. Grep for
  `night_light_entry` / `night_light_action` / `nightlight_action`
  across `custom_components/`: zero hits. NEW.
- `DEFAULT_NIGHT_LIGHT_ENTRY_ACTION` — see §"Default" below. NEW.
- `LIGHT_ACTION_FOLLOW_MAIN = "follow_main"` — NEW (one line).
- `effective_night_light_entry_action(cfg)` — one pure helper in
  `lighting/resolver.py` returning one of
  `{NONE, TURN_ON, TURN_ON_IF_DARK}`. NEW.

### Prior planning docs consulted

- `docs/planning/PLANNING_night_light_off_path.md:110` — explicitly-
  DEFERRED canonical↔reconciler entry=none+sleep divergence; "Non-
  goals" at `:544` fenced off `_control_lights_entry`. This cycle is
  that deferred cycle arriving.
- `docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md`
  (REV 2.3 / 2.3.1 / 2.3.2) — the arc that shipped the role-picker
  surface in v5.103.29. The new field slots into the SAME
  `async_step_options_lighting_behaviour` step.
- `docs/planning/AUDIT_room_light_automation.md` — F2/F3 the defects
  this cycle closes.

### Memory bodies pulled

- `feedback_coincidental_equality_masks_concept_split` — directly on
  point.
- `feedback_label_style_guide` — governs §D4 wording.
- `feedback_configurability_clarity` — named-bucket Select, set-once.
- `feedback_marginal_benefit_pushback` — considered; operator rejected
  simpler A/B 2026-09-15.

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/automation.py`
  `_control_lights_entry` 1288–1430 (H3 note: `:1302 if not lights:
  return` fires BEFORE the sleep branch; must be scoped — see D2).
- `custom_components/universal_room_automation/actuator_reconciler.py`
  `_resolve_light` 794–895.
- `custom_components/universal_room_automation/const.py` 870–1060.
- `custom_components/universal_room_automation/config_flow.py`
  2847–2870 (new-room setup picker; 3 options), 12760–12790 (options
  flow picker).
- `custom_components/universal_room_automation/lighting/resolver.py`
  (full file; `effective_entry_set` sleep short-circuit at :95–97).
- `custom_components/universal_room_automation/coordinator.py:1310`
  `_get_builtin_target_entities` (M2 consumer).
- `docs/readmes/README_v5.103.29.md` end-to-end.

### Design docs read

Not applicable: room-tier light automation, not a coordinator domain.

### Prior-art scan verdict (REUSE-vs-BUILD per proposed piece)

| Proposed piece | Verdict | Prior art (file:line) |
|---|---|---|
| New vocabulary set | **REUSE** | `const.py:1055–1059` LIGHT_ACTION_\* (3 of 5 values map; `FOLLOW_MAIN` added) |
| Per-room Select field | **REUSE pattern** | `const.py:989 CONF_ENTRY_LIGHT_ACTION`, picker `config_flow.py:2859` |
| Config-flow placement | **REUSE step** | Slice B' `async_step_options_lighting_behaviour` already carries night-light pickers |
| Shared resolver helper | **REUSE module** | `lighting/resolver.py` already exists (Slice A); extend, don't new |
| Lazy-default idiom | **REUSE pattern** | `CONF_IS_EGRESS_WINDOW` / `DEFAULT_IS_EGRESS_WINDOW` `const.py:884–885` |
| AI-rule conflict surface | **REUSE + extend** | `coordinator.py:1310 _get_builtin_target_entities` |
| Migration shape (if operator picks B) | **REUSE pattern** | `async_migrate_entry` / entry version bump (precedent: prior room-config migrations in the repo; builder enumerates at build time) |

Nothing proposed as "new" was found elsewhere.

---

## Falsifiable invariant (single property this cycle must guarantee)

**After the cycle ships, for every room config, the canonical path
(`automation._control_lights_entry`) and the actuator reconciler
(`actuator_reconciler._resolve_light`) resolve night-light entry
actuation to the SAME ON/OFF/NO-OPINION outcome under every
(occupied, is_sleep_hours, is_dark, main_action, nl_action,
is_night_light_entity, has_main_lights) tuple. The outcome depends
ONLY on `effective_night_light_entry_action(cfg)` and the existing
sleep/occupancy/darkness branches — never on `CONF_ENTRY_LIGHT_ACTION`
directly inside either light-decision function for a night-light
entity. Under sleep, the sleep branch remains the SOLE authority in
both controllers (no fall-through to the entry branch).**

Falsifier (concrete, legal-config):
- Room A `night_lights=[light.bedside]`, `CONF_LIGHTS=[]`
  (Master Bedroom today), main=NONE, nl=TURN_ON, sleep=T,
  occupied=T → BOTH controllers must assert `light.bedside` ON.
- Room B same config except nl=NONE → NEITHER asserts ON (today
  the reconciler does — that is the F2/F3 bug this cycle closes).
- Room C main=TURN_ON, nl=NONE, sleep=T, occupied=T → sleep stays
  authority: night lights OFF (unaffected by main=TURN_ON because
  under sleep the sleep branch is the only authority). Discriminator
  row that pins H1.
- Room D main=NONE, nl=TURN_ON_IF_DARK, sleep=F, is_dark=F,
  occupied=T → NEITHER asserts ON (dark gate correctly refuses).

---

## Deliverables

### D1 — Add `CONF_NIGHT_LIGHT_ENTRY_ACTION` + resolver

- `const.py`:
  - `CONF_NIGHT_LIGHT_ENTRY_ACTION: Final = "night_light_entry_action"`.
  - `LIGHT_ACTION_FOLLOW_MAIN: Final = "follow_main"`.
  - `DEFAULT_NIGHT_LIGHT_ENTRY_ACTION: Final = LIGHT_ACTION_FOLLOW_MAIN`
    (see §"Default — operator pick" below; if operator picks B the
    default stays FOLLOW_MAIN but a per-entry migration seeds
    affected rooms with `turn_on`).
- `lighting/resolver.py` — new pure helper
  `effective_night_light_entry_action(cfg) -> str`:
  1. Read `cfg.get(CONF_NIGHT_LIGHT_ENTRY_ACTION, DEFAULT_NIGHT_LIGHT_ENTRY_ACTION)`.
  2. If value is `FOLLOW_MAIN` → return
     `cfg.get(CONF_ENTRY_LIGHT_ACTION, LIGHT_ACTION_NONE)` collapsed
     to the three night-light-legal values: NONE / TURN_ON /
     TURN_ON_IF_DARK. TURN_OFF / LEAVE_ON (not UI-reachable today
     for entry per `config_flow.py:2847–2851`; collapse is defensive
     for programmatic / future-schema values) → NONE.
  3. If value is one of {NONE, TURN_ON, TURN_ON_IF_DARK} → return
     as-is.
  4. Any other value → return NONE (fail-closed).
- Pure function; no `hass` dependency.

**Vocabulary justification.** Four options exposed to operators:
`follow_main`, `none`, `turn_on`, `turn_on_if_dark`. TURN_OFF /
LEAVE_ON are exit-shaped and never offered.

#### Acceptance criteria (D1)

- **Verify:** `const.py` grep finds the three new names.
- **Verify:** `lighting/resolver.py` exports
  `effective_night_light_entry_action`.
- **Test:** `test_night_light_action_resolver.py` — table-driven:
  5 vocabulary values × 5 main-action values = 25 cases, each
  checked against an **independently authored expected-outcome
  column** (M3) in the test file, not computed from the function
  under test. `FOLLOW_MAIN` rows explicitly list the TURN_OFF/LEAVE_ON
  → NONE collapse.
- **Test:** absent-key fixture returns the SAME value as a fixture
  with `CONF_NIGHT_LIGHT_ENTRY_ACTION=FOLLOW_MAIN`.

### D2 — Rewire canonical `_control_lights_entry`

- `automation.py:_control_lights_entry` (1288 onward):
  - Compute `main_action = cfg.get(CONF_ENTRY_LIGHT_ACTION, NONE)`.
  - Compute `nl_action = effective_night_light_entry_action(cfg)`.
  - **Remove** the current `if main_action == NONE: return` at
    `:1295`. Replace with:
    `if main_action == NONE and nl_action == NONE: return`.
  - **H3 scope fix** — the `if not lights: return` at `:1302`
    currently fires BEFORE the sleep branch and would prevent
    night-light actuation on a `lights=[]` + `night_lights=[L]`
    room (Master Bedroom is exactly this today). Replace with:
    `if not lights and not night_lights: return`. The main-only
    paths below still check `lights` locally. This fix is strict
    scope to the main-light path.
  - **Sleep branch stays the SOLE authority (H1).** The branch at
    `:1313 if is_sleep_hours and night_lights:` now:
    1. If `nl_action == NONE` → run `_turn_off_non_night_lights()`
       (unconditional non-night OFF sweep is preserved) and
       **return**. Do NOT fall through to the entry branch.
    2. Else: scene short-circuit (as today), then
       `_turn_on_night_lights(mode="sleep")`,
       `_turn_off_non_night_lights()`, and **return**.
  - Non-sleep branch (today's `should_turn_on` at `:1332`):
    - `main_should_on = main_action == TURN_ON or (main_action == TURN_ON_IF_DARK and is_dark)`.
    - `nl_should_on = nl_action == TURN_ON or (nl_action == TURN_ON_IF_DARK and is_dark)`.
    - If `main_should_on`: today's path (resolver + slot scene +
      `_turn_on_regular_lights`) on the resolver's set.
    - Else if `nl_should_on` (M1: night-lights only qualify):
      bypass `_maybe_activate_slot_scene` (no slot scene when only
      night lights qualify) and call `_turn_on_night_lights(mode="day")`
      — or the evening slot per Slice E — directly, using
      `slot_night_light_overrides` brightness/colour.
    - Else: return.

#### Acceptance criteria (D2)

- **Verify (H1):** `automation.py:1313–1325` always returns (no
  fall-through to `:1327` under sleep).
- **Verify (H3):** `automation.py:1302` guard is widened to the
  union with `night_lights`.
- **Test:** behavioural matrix `test_night_light_action_canonical.py`
  — expected outcomes **independently authored** in the test
  (M3). Rows include at minimum:
  - (sleep=T, occupied=T, main=NONE, nl=TURN_ON, lights=[], night_lights=[L]) →
    `_turn_on_night_lights` dispatched for [L]. (H3 live row: Master
    Bedroom.)
  - (sleep=T, occupied=T, main=NONE, nl=NONE, night_lights=[L]) →
    no `_turn_on_night_lights`; `_turn_off_non_night_lights` still
    runs; function returns before the entry branch (H1).
  - (sleep=T, occupied=T, main=TURN_ON, nl=NONE, night_lights=[L]) →
    night lights OFF-swept, no main-light turn-on under sleep
    (H1 discriminator: sleep remains authority).
  - (sleep=T, occupied=T, main=NONE, nl=TURN_ON_IF_DARK, is_dark=F) →
    no turn-on (dark-gate refuses even under sleep — operator may
    revisit if surprising).
  - (sleep=F, is_dark=T, main=NONE, nl=TURN_ON_IF_DARK) → night
    lights only; no slot scene (M1).
  - (main=TURN_ON, nl=FOLLOW_MAIN) → identical to pre-cycle for a
    room whose stored options match a FOLLOW_MAIN-defaulted room.
- **Test:** mutation drill — delete the new `nl_should_on` branch;
  a named test MUST go red (per Numbers-Get-Knobs mutation
  discipline).
- **Live (L3 — one-shot query, NOT a 24 h soak):** at the first
  sleep boundary post-restart, query
  `ura_activity_log` / `command_trail` for `light.turn_on` rows
  keyed to the test rooms. One SQL round. Pass = the one-shot
  observation matches the operator's chosen `nl_action` per room.

### D3 — Rewire reconciler `_resolve_light`

Mirror D2 so both controllers consume
`effective_night_light_entry_action` and agree.

- `actuator_reconciler.py:_resolve_light`:
  - **Sleep branch (`:813–:836`) stays the SOLE authority (H1).**
    For a night-light member entity:
    - occupied + `nl_action != NONE` → return `DesiredState(ON,
      reason="sleep_night_light")` with brightness from
      `slot_night_light_overrides` (sleep slot) (M1 parity with
      canonical).
    - occupied + `nl_action == NONE` → return `None` (NO opinion;
      do NOT fall through to the entry branch, which would
      re-admit the entity via `effective_entry_set(is_sleep_hours=
      True)` at `resolver.py:95–97` and reintroduce the exact bug
      we are closing).
    - vacant → unchanged (fall-through to vacant branch for OFF
      authority, as today).
    For a non-night-light entity under sleep: unchanged (today's
    OFF return at `:833`).
  - **Entry branch (`:839–:873`, non-sleep)**: for a night-light
    member entity, substitute `nl_action` for `main_action` in the
    ON decision; dark-only carve-out unchanged. For a main-only
    (non-night-light) entity: unchanged.
  - **Vacant branch (`:875–:895`)**: UNCHANGED. Out of scope.

#### Acceptance criteria (D3)

- **Test — M3 parity harness** `test_night_light_action_parity.py`:
  dense cartesian (occupied ∈ {T,F}) × (sleep ∈ {T,F}) × (is_dark ∈
  {T,F}) × (main ∈ 3 UI values + 2 defensive) × (nl ∈ 4 UI values)
  × (entity ∈ main_only / night_light / both-member / unknown)
  × (has_main_lights ∈ {T,F}). Each cell has an **independently
  authored expected outcome** (`on` / `off` / `no_opinion`) in a
  separate table literal in the test file; canonical AND reconciler
  are each asserted against that oracle (not against each other).
  Parity falls out as `canonical[cell] == reconciler[cell] ==
  expected[cell]`.
- **Discriminator rows (required, called out explicitly):**
  - (sleep=T, occupied=T, main=NONE, nl=TURN_ON, entity=night_light,
    has_main_lights=F) → expected ON for both.
  - (sleep=T, occupied=T, main=NONE, nl=NONE, entity=night_light) →
    expected `no_opinion` for both (today reconciler ON — regression
    anchor).
  - (sleep=T, occupied=T, main=TURN_ON, nl=NONE, entity=night_light) →
    expected OFF-swept by canonical; `no_opinion` by reconciler
    (sleep branch is sole authority — H1 pin).
  - (sleep=T, occupied=T, main=NONE, nl=TURN_ON_IF_DARK, is_dark=F,
    entity=night_light) → expected `no_opinion` for both.
- **Live (L3 — one-shot):** at the first sleep boundary post-restart,
  one SQL round against `ura_activity_log` (and reconciler row
  table if present) confirms the discriminator cells match the
  operator's per-room pick. No 24 h soak.

### D4 — Config-flow surface + labels

- `config_flow.py` **options flow only** (`async_step_options_lighting_behaviour`)
  — add one new `vol.Optional(CONF_NIGHT_LIGHT_ENTRY_ACTION,
  default=…)` SelectSelector. **NOT added to the new-room setup
  picker at `:2859`** — new rooms get FOLLOW_MAIN by default;
  operators tune the knob post-setup. (L2 clarification: options-
  only placement matches `CONF_LIGHTS_ON_ENTRY` placement from
  Slice B'.)
- `strings.json` + `translations/en.json` — label
  **"Night lights on entry"** (3 words) and four option strings:
  - `follow_main` → "Follow main lights"
    (helper: "Match whatever the main lights do on entry.")
  - `turn_on` → "Always on"
    (helper: "Night lights come on when someone enters.")
  - `turn_on_if_dark` → "Only when dark"
    (helper: "Night lights come on at entry only if the room is dark.")
  - `none` → "Never"
    (helper: "Night lights never come on from entry. Sleep scenes and
    manual control still work.")
- Knob-ladder placement: **config/options flow** (per-deployment
  structure, set-once-per-room). NOT a Number/Select/Switch entity.

#### Acceptance criteria (D4)

- **Verify:** opening a room's Options → Lighting behaviour shows
  the new field; default per operator's §"Default" pick (shown
  value = FOLLOW_MAIN unless operator picked B and this room is in
  the migrated 7).
- **Test:** `test_room_dialog_strings.py` extended; four option
  strings + the label asserted.
- **Test:** round-trip save `turn_on`, close, reopen → value
  preserved.
- **Live:** operator sets Jaya bedroom to "Always on" and master
  bedroom to "Never"; sleep-hour entry events dispatch per the
  room's pick (see D2/D3 Live, one-shot).

### D5 — Extend AI-rule conflict-detect consumer (M2)

- `coordinator.py:1310 _get_builtin_target_entities`:
  - TRIGGER_ENTER branch at `:1318`: when
    `effective_night_light_entry_action(cfg) != LIGHT_ACTION_NONE`,
    extend `entities` with the room's `CONF_NIGHT_LIGHTS` (deduped
    against `CONF_LIGHTS` as the TRIGGER_EXIT branch already does
    at `:1332`).
  - TRIGGER_LUX_DARK: same gate (lux_dark is an entry-shaped
    trigger).
  - TRIGGER_EXIT / TRIGGER_LUX_BRIGHT: unchanged (already includes
    night lights per NIGHT-LIGHT-NO-OFF-PATH-1 D6).

#### Acceptance criteria (D5)

- **Test:** `test_builtin_target_entities_night_light_entry.py` —
  three rows:
  - nl=NONE room → night lights NOT in TRIGGER_ENTER set.
  - nl=TURN_ON room → night lights IN TRIGGER_ENTER set, deduped.
  - nl=FOLLOW_MAIN + main=TURN_ON → night lights IN set.
- **Live:** an AI rule proposing `light.turn_on` on a configured
  night light during entry on a `nl != NONE` room must raise an
  AI-rule-vs-builtin-automation conflict row in
  `ura_activity_log`.

---

## Default — OPERATOR PICK (H2)

### Why this is not behaviour-neutral

The REV 1 claim "default `FOLLOW_MAIN` preserves today's observed
behaviour for all rooms" was WRONG. Today, for a room with
`entry_light_action='none'` + `night_lights` set, the canonical path
does nothing on sleep entry while the reconciler asserts the night
light ON (the F2/F3 bug). After this cycle, canonical and reconciler
agree — but on **which** behaviour depends on the default.

### Measured affected rooms (verified 2026-10-08 against the live
`.storage/core.config_entries` snapshot, filter: `entry_light_action
== 'none'` AND `night_lights` non-empty):

1. Breakfast Nook
2. Game Room
3. Jaya Bathroom
4. Living Room
5. Master Bedroom (lights=[], night_lights only — also the H3 live
   row)
6. Patio
7. Ziri Bathroom

Seven rooms are affected by the default pick.

### Options

- **(A) Default `FOLLOW_MAIN` everywhere (no migration).** Those 7
  rooms resolve to `nl_action = NONE`. **New behaviour: canonical
  does nothing (unchanged) AND reconciler no longer asserts ON
  (behavioural change).** Night lights that come on today at sleep
  entry in those 7 rooms will stop coming on until the operator
  flips the knob to `turn_on`. Matches canonical today; changes
  reconciler today.
- **(B) Default `FOLLOW_MAIN` + one-time per-entry migration seeds
  `nl_action = turn_on` for the 7 measured rooms; every other room
  gets `FOLLOW_MAIN`.** Both controllers assert ON for those 7
  rooms post-ship (keeps what the reconciler does today). Every
  other room is unchanged.
- **(C) Per-room operator pick during setup (no automatic
  default-time behaviour).** Deploy a `waiting_operator` card
  listing the 7 rooms; operator picks `turn_on` or `none` for each
  before the knob ships live. Highest-ceremony option.

### Recommendation: **B** (migrate the 7 affected rooms to `turn_on`;
`FOLLOW_MAIN` everywhere else).

Reasoning:
1. **Observable preservation.** The behaviour an operator SEES in a
   bedroom at 2 AM is driven by the reconciler (it is the loop that
   runs continuously); the canonical path on sleep-entry under
   `main=NONE` is dead code for those 7 rooms. The reconciler is
   today's de-facto producer. B preserves what the house actually
   does.
2. **Low surprise, bounded blast radius.** Seven rooms, named and
   measured. Migration is a per-entry version-bump setting one
   key; mechanically small; audited by name.
3. **Reversibility.** The knob is in options flow (D4). Any
   room an operator wants silent at sleep is one dropdown flip.
4. **A would silently darken night lights overnight after the
   deploy** — exactly the "bedroom changes overnight without the
   operator asking" risk the REV 1 default statement claimed to
   avoid.
5. **C adds ceremony for a decision we can defend with evidence.**
   The operator can still override per-room on day 1 via D4.

Operator may overrule.

### D1 — Default + migration (per operator pick)

- A: `DEFAULT_NIGHT_LIGHT_ENTRY_ACTION = FOLLOW_MAIN`; no migration;
  update acceptance to acknowledge the 7-room reconciler-side
  behavioural change and page the operator pre-deploy.
- B: `DEFAULT_NIGHT_LIGHT_ENTRY_ACTION = FOLLOW_MAIN`; add
  `async_migrate_entry` for the integration that, for the
  enumerated 7 room entries (matched by `room_name`), sets
  `CONF_NIGHT_LIGHT_ENTRY_ACTION = LIGHT_ACTION_TURN_ON` once;
  logged + idempotent via a version bump; no other rooms touched.
  Builder re-measures the 7 against the live snapshot at build
  time (names may have shifted) and includes the measured list in
  the ship README.
- C: ship the knob with `DEFAULT = FOLLOW_MAIN`, no migration; park
  deploy on a `waiting_operator` picks-card for the 7 rooms.

### Fixed Jaya acceptance line

Replace the REV 1 "Jaya bedroom byte-identical pre-vs-post deploy"
line with: **"For every room NOT in the H2-measured 7, canonical
and reconciler produce the same ON/OFF outcome as pre-deploy under
every entry/sleep/dark combination (byte-identical observable
behaviour). For the H2-measured 7, outcome depends on the operator
pick (A/B/C); the ship README records the observed outcome per room
at the first sleep boundary via the D2/D3 one-shot L3 query."**

---

## Producer AND Consumer map (standing rule)

**Producer:** `effective_night_light_entry_action(cfg)` — the
single producer, pure helper in `lighting/resolver.py`.

Depends on: `cfg[CONF_NIGHT_LIGHT_ENTRY_ACTION]` (new, lazy default
`FOLLOW_MAIN`), `cfg[CONF_ENTRY_LIGHT_ACTION]` (existing, resolver
input when `FOLLOW_MAIN`).

**Consumers (every reader, trust-vs-display):**

| Site | File:line | Trust/decision |
|---|---|---|
| Canonical entry decision — sleep branch gate (H1) | `automation.py:1313` (modified) | Trust (fires turn_on; sleep stays sole authority) |
| Canonical entry decision — non-sleep night-only branch (M1) | `automation.py` new post-:1340 branch | Trust (fires turn_on; no slot scene when only NL qualify) |
| Reconciler sleep branch (H1) | `actuator_reconciler.py:813–829` (modified) | Trust (asserts ON or returns None; never falls through to entry branch) |
| Reconciler entry branch | `actuator_reconciler.py:839–873` (modified for night-light members) | Trust (asserts ON) |
| AI-rule conflict detect (M2) | `coordinator.py:1318` (new gate) | Decision (adds night lights to TRIGGER_ENTER set when `nl_action != NONE`) |
| Slot scene short-circuit — sleep site | `automation.py:_maybe_activate_slot_scene` sleep call | Trust (dispatches scene) — gate: `nl_action != NONE` |
| Slot scene short-circuit — non-sleep site | `automation.py:_maybe_activate_slot_scene` non-sleep call | **M1**: bypass when ONLY night lights qualify (no main_should_on) |
| Away sweep (Slice D) | `automation.py:handle_away_leave_on_sweep` | UNAFFECTED |
| Guest gate (deferred) | `LIGHTS-GUEST-MODE-BEHAVIOUR-1` | OUT OF SCOPE (`CONF_LIGHTS_GUEST_MODE` not in `const.py` on develop — L1 correction) |
| D3 `RoomLightsSwitch` | `switch.py` (Slice C) | UNAFFECTED |

---

## Four open decisions settled

1. **Option vocabulary** — Four exposed values: `follow_main`,
   `none`, `turn_on`, `turn_on_if_dark`. Resolver collapses defensive
   TURN_OFF/LEAVE_ON (not UI-reachable on entry per
   `config_flow.py:2847–2851`) to NONE.
2. **Default** — **OPERATOR PICK A/B/C**. Recommendation: B. See
   §"Default — OPERATOR PICK (H2)."
3. **Config-flow placement** — Per-room **options flow only**,
   inside `async_step_options_lighting_behaviour`. Not shown in
   new-room setup picker. Label-style-guide wording per D4.
4. **Both controllers read ONE resolver** — Yes.

---

## Non-goals

- Guest mode behaviour — `LIGHTS-GUEST-MODE-BEHAVIOUR-1`.
- Exit-side night-light actuation — unchanged.
- Scene / slot vocabulary changes — Slice E's slot resolution reused
  unchanged.
- New Number/Select/Switch entities.
- Any change to `CONF_ENTRY_LIGHT_ACTION` semantics for main lights.
- Any change to the Away sweep, the manual hold, or the D3 room-
  lights switch.
- `KITCHEN-NIGHTLIGHT-RANGE-MISCONFIG-1` (parked).
- Any change to under-sleep darkness semantics (nl=TURN_ON_IF_DARK
  under sleep still refuses when not dark — called out so reviewers
  do not re-litigate).

---

## Migration

Depends on §"Default — OPERATOR PICK (H2)". A: none. B:
`async_migrate_entry` + entry version bump; one key set on the 7
measured rooms; logged + idempotent; re-measured at build time
against live `.storage/core.config_entries`. C: no code migration —
a `waiting_operator` picks-card gates deploy.

---

## Review tier + framings — **Tier 2-DB**

Three parallel reviews, framing-disjoint:

- **A — local correctness + edge cases.** Resolver vocabulary +
  collapse; absent-key path; new-field gating in both D2 and D3;
  `if not lights:` H3 scope fix; M1 slot-scene bypass logic.
- **B — cross-controller parity (sleep × main × nl).** The core
  framing for this cycle (per plan-review 2026-10-08). Reviewer
  independently enumerates every (occupied, sleep, is_dark,
  main_action, nl_action, entity-membership, has_main_lights) cell
  the parity harness covers and audits the expected-outcome oracle
  against the invariant and the H1/H3/M1 pins. Verifies the sleep
  branch is the sole authority on both sides (no fall-through).
  Verifies the M2 AI-rule consumer. Verifies the H2 recommended
  migration preserves what the house physically does.
- **C — surfaces + migration + fixtures.** D4 options-flow round-
  trip; translations; label-style guide; `RoomLightsSwitch` and Away
  sweep unaffected (grep + mutation drill); the H2 migration (if B
  picked): the 7-room list re-measured at build against live
  `.storage/core.config_entries`; migration idempotent and version-
  bumped; test fixtures extract from production source, not hand-
  copied.

Each reviewer runs per-site mutations and names which test goes red.

---

## Plan Completion Tracking

Placeholder — filled at ship. For each of D1 / D2 / D3 / D4 / D5,
record: DONE, DEFERRED (with reason + where tracked), or DROPPED.
Specifically record the operator's H2 pick (A/B/C) and the measured
room list at ship time.

---

## Plan review 2026-10-08 — findings folded in

Each finding verified against source by the planner before folding.

| Finding | Verified source | Resolution in this REV |
|---|---|---|
| H1 — sleep branch stays sole authority in both controllers; no fall-through | `automation.py:1313–1325` (always returns), `actuator_reconciler.py:813–836` (sleep returns or vacant-fall-through only), `resolver.py:95–97` (sleep ⇒ night-only short-circuit) | D2 sleep branch always returns (new §); D3 sleep branch returns `None` instead of falling through; invariant restated; two new parity rows added (sleep+main=turn_on+nl=none; sleep+main=none+nl=turn_on_if_dark+dark=F) |
| H2 — default is NOT behaviour-neutral; 7 live rooms measured | `.storage/core.config_entries` 2026-10-08 (coordinator-measured): Breakfast Nook, Game Room, Jaya Bathroom, Living Room, Master Bedroom, Patio, Ziri Bathroom; vs `automation.py:1295` (canonical NOP) and `actuator_reconciler.py:813–829` (reconciler ON) | New §"Default — OPERATOR PICK (H2)" with options A/B/C and recommendation B; Jaya "byte-identical" line replaced |
| H3 — `if not lights: return` precedes sleep branch | `automation.py:1302` | D2 widens guard to `not lights and not night_lights`; added test row (lights=[], night_lights=[L]) matching Master Bedroom live |
| M1 — no slot scene when only night lights qualify; both controllers use `slot_night_light_overrides` brightness | Slice E slot machinery in README_v5.103.29 §Slice E; `actuator_reconciler.py:816–828` brightness read | D2 non-sleep nl-only branch bypasses `_maybe_activate_slot_scene`; D3 sleep ON path sources brightness from `slot_night_light_overrides(sleep)`; parity row pinned |
| M2 — `_get_builtin_target_entities` consumer | `coordinator.py:1310` (ENTER at :1318 omits night lights) | New deliverable **D5** added; test + Live criterion |
| M3 — parity test uses independently authored oracle, not A==B | — | D1/D2/D3 acceptance now reference independently authored expected-outcome tables; discriminators paired with main=turn_on rows explicitly |
| L1 — `CONF_LIGHTS_GUEST_MODE` does not exist in `const.py` | grep over `custom_components/` returns zero hits | Prior-art + Consumer map corrected; Guest claim softened to "deferred under LIGHTS-GUEST-MODE-BEHAVIOUR-1; key not yet in const.py" |
| L2 — main picker exposes only 3 values; TURN_OFF/LEAVE_ON are exit-only | `config_flow.py:2847–2851` (3 options) | Resolver collapse re-labelled as **defensive**; D4 explicitly states the new field is **options-only**, not shown at new-room setup `:2859` |
| L3 — replace 24 h log-grep with one-shot query at first sleep boundary | — | D2 and D3 Live criteria rewritten as one-shot `ura_activity_log` / `command_trail` queries at the first sleep boundary post-restart |
| Tier | Standing policy 2026-06-08 | **Tier 2-DB**; framing B = cross-controller parity (sleep × main × nl) |

---

## Appendix — files that will be touched

| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | +3 constants (CONF, DEFAULT, LIGHT_ACTION_FOLLOW_MAIN) |
| `custom_components/universal_room_automation/lighting/resolver.py` | +1 pure helper `effective_night_light_entry_action` |
| `custom_components/universal_room_automation/automation.py` | `_control_lights_entry` 1288-end: H3 guard widen; sleep branch split by nl_action, always returns (H1); non-sleep nl-only branch bypasses slot scene (M1) |
| `custom_components/universal_room_automation/actuator_reconciler.py` | `_resolve_light` sleep branch 813–836: gate by nl_action, return `None` on nl=NONE occupied night-light (H1 — no fall-through); entry branch 839–873: night-light members read nl_action; vacant branch unchanged |
| `custom_components/universal_room_automation/coordinator.py` | `_get_builtin_target_entities` TRIGGER_ENTER + TRIGGER_LUX_DARK: include night lights when `nl_action != NONE` (D5) |
| `custom_components/universal_room_automation/config_flow.py` | +1 SelectSelector field in `async_step_options_lighting_behaviour` (options flow only; NOT the new-room setup picker) |
| `custom_components/universal_room_automation/strings.json` + `translations/en.json` | label + helper + 4 option strings |
| `custom_components/universal_room_automation/__init__.py` (B only) | `async_migrate_entry` version bump + per-entry `CONF_NIGHT_LIGHT_ENTRY_ACTION=turn_on` for the H2-measured rooms |
| `quality/tests/test_night_light_action_resolver.py` (new) | D1 unit matrix with independently authored oracle |
| `quality/tests/test_night_light_action_canonical.py` (new) | D2 behavioural matrix (H1/H3/M1 rows) |
| `quality/tests/test_night_light_action_parity.py` (new) | D3 cross-controller parity against independently authored oracle (M3) |
| `quality/tests/test_builtin_target_entities_night_light_entry.py` (new) | D5 consumer |
| `quality/tests/test_room_dialog_strings.py` (extend) | D4 translations + field assertions |
