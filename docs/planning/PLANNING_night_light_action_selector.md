# PLANNING — Night-light action selector (NIGHT-LIGHT-ACTION-SELECTOR-1)

Card: `NIGHT-LIGHT-ACTION-SELECTOR-1` (operator-approved 2026-09-15:
"another selector to show how we should actuate night light… it removes
all doubt"). Blocks `LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1`. Follows the
room-lighting-roles arc (v5.103.29 Slices A–E, v5.103.30, v5.103.31) —
that arc shipped STRUCTURE (role pickers, slots, scenes, hold, Away
sweep) but did NOT split the overloaded `CONF_ENTRY_LIGHT_ACTION`
field. The split is this cycle.

Status: pre-planning draft (not reviewed, not built).
Tier: **Tier 2** (feature cycle: new config field + both light
controllers + migration-free default). Elevation to Tier 2-DB (3
framing-disjoint reviews) is RECOMMENDED because this is a shared-
primitive change consumed by two independent controllers (canonical
`_control_lights_entry` + actuator reconciler `_resolve_light`), and
mis-wiring either side silently alters bedroom behaviour at sleep —
the exact profile Tier 2-DB (standing policy 2026-06-08) exists for.
Final tier gate: operator.

---

## STEP 1 — Premise re-verified on current develop

Verdict: **STILL-REAL** (plan proceeds).

Evidence (file:line, develop @ working tree 2026-10-08):

- **(a) `CONF_ENTRY_LIGHT_ACTION` still gates night-light actuation on
  entry.** `automation.py:1292` reads the action; `automation.py:1295
  if action == LIGHT_ACTION_NONE: return` fires BEFORE the
  `is_sleep_hours and night_lights` branch at `automation.py:1313`.
  Consequence: a room set to `entry_light_action=none` never turns on
  night lights at entry, even under house-Sleep. Night lights have no
  independent WHEN.
- **(b) Canonical vs reconciler disagree on entry=none + sleep.**
  `actuator_reconciler._resolve_light` at `:800` reads `sleep`, at
  `:813–:829` the sleep branch asserts night-light entities ON for
  occupied night-light members **BEFORE** the `entry_action == NONE`
  check at `:843`. So under sleep + occupied, canonical says "do
  nothing" and the reconciler says "turn the night light on." This is
  LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1 (AUDIT_room_light_automation.md
  F2/F3) still live.
- **(c) The v5.103.29 roles arc did NOT add a night-light action
  policy.** New keys added by that arc (per
  `docs/readmes/README_v5.103.29.md`): `CONF_LIGHTS_ON_ENTRY`,
  `CONF_LIGHTS_ON_ENTRY_DARK_ONLY`, `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`,
  `CONF_AWAY_TURN_OFF_LEAVE_ON`, `CONF_OUTDOOR_LIGHT_SENSOR`,
  `CONF_OUTDOOR_DARK_LUX`, slot evening/scene keys, `CONF_LIGHTS_GUEST_MODE`
  (Guest DEFERRED to LIGHTS-GUEST-MODE-BEHAVIOUR-1 — NOT yet wired).
  None of these controls WHEN a night light actuates independently of
  the main-light action. The arc's resolver (`lighting/resolver.py
  effective_entry_set`) is still called downstream of the `NONE`
  early-return in `_control_lights_entry`, so it never runs when the
  main action is `none`.

Not moot.

---

## Institutional context verified

### Greps run + results (REUSED vs NEW per proposed addition)

- `CONF_ENTRY_LIGHT_ACTION` — the overloaded field being split.
  `const.py:989`, used `automation.py:1292`, `actuator_reconciler.py:839`,
  `config_flow.py:2859 / :12774`. **REUSED** (unchanged; this cycle adds
  a sibling, does not alter the existing field semantics).
- `CONF_EXIT_LIGHT_ACTION` — mirror pattern on exit.
  `const.py:990`, `actuator_reconciler.py:840`. **REUSED** as the
  precedent shape for the new field (same vocabulary vol.In,
  per-room, config-flow Select).
- `LIGHT_ACTION_*` vocabulary — `const.py:1055–1059` (NONE / TURN_ON /
  TURN_ON_IF_DARK / TURN_OFF / LEAVE_ON). **REUSED** where meanings
  map; one **NEW** value `LIGHT_ACTION_FOLLOW_MAIN` proposed below
  (grepped: no existing `_FOLLOW_` or `_INHERIT_` light-action literal
  — new because preserving today's behaviour needs an explicit value,
  not a sentinel).
- `CONF_NIGHT_LIGHTS` — `const.py:923`. **REUSED** (the entity list is
  not changing; only its policy knob is new).
- `CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS` / `_SLEEP_COLOR` / `_DAY_BRIGHTNESS`
  / `_DAY_COLOR` — `const.py:924–927`. **REUSED** (HOW, not WHEN).
- `CONF_LIGHTS_ON_ENTRY` / `_DARK_ONLY` — `const.py:1012-1013`.
  **REUSED** (main-light picker; unaffected).
- `CONF_LIGHTS_GUEST_MODE` — committed in v5.103.29 README as
  deferred; the key constant is present per README §Slice D but the
  code is NOT wired yet (`LIGHTS-GUEST-MODE-BEHAVIOUR-1`). This
  cycle treats Guest as **out of scope** (own card); the selector
  must not change Guest behaviour.
- `lighting/resolver.py` `effective_entry_set` / `effective_exit_set`
  — new resolver seam from Slice A/B'. **REUSED** as the extension
  point: both the canonical path and the reconciler already route
  through it when `CONF_LIGHTS_ON_ENTRY` is set. The new field will
  flow into / be read beside the resolver (see D1 below) so both
  controllers consume ONE resolved night-light decision.

### NEW additions (justified)

- `CONF_NIGHT_LIGHT_ENTRY_ACTION` (new per-room key) — the sibling to
  `CONF_ENTRY_LIGHT_ACTION` that this card exists to add. Grep for
  `night_light_entry` / `night_light_action` / `nightlight_action`:
  zero hits in `const.py`, `config_flow.py`, `automation.py`,
  `actuator_reconciler.py`. NEW because nothing equivalent exists.
- `DEFAULT_NIGHT_LIGHT_ENTRY_ACTION = LIGHT_ACTION_FOLLOW_MAIN` —
  module const for the migration-free default. NEW (one line).
- `LIGHT_ACTION_FOLLOW_MAIN = "follow_main"` — new vocabulary value
  for the new field only. The existing `LIGHT_ACTION_*` set is reused
  for the explicit choices; `FOLLOW_MAIN` is the "preserve today's
  observed behaviour for all ~40 rooms" default. NEW (one line).
- One shared resolver helper `effective_night_light_entry_action(cfg)`
  — pure function in `lighting/resolver.py` returning one of
  `{NONE, TURN_ON, TURN_ON_IF_DARK}` (the three values that make sense
  for night lights; TURN_OFF/LEAVE_ON do not — see D1 vocabulary
  justification). Resolves `FOLLOW_MAIN` to the current
  `CONF_ENTRY_LIGHT_ACTION` so both call sites consume ONE answer.

### Prior planning docs consulted

- `docs/planning/PLANNING_night_light_off_path.md:110` — the
  explicitly-DEFERRED canonical-vs-reconciler entry=none+sleep
  divergence. "Non-goals" at `:544` fenced off `_control_lights_entry`.
  This cycle is that deferred cycle arriving.
- `docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md`
  (ROOM-LIGHTING-SETUP-REDESIGN-1, REV 2.3 / 2.3.1 / 2.3.2) — the
  arc that shipped the role-picker surface in v5.103.29. The new
  field will slot into the SAME `async_step_options_lighting_behaviour`
  step added by that arc.
- `docs/planning/AUDIT_room_light_automation.md` — F2/F3 are the
  defects this cycle closes; D1 scope + the dual-listed/affected
  rooms list is the migration risk surface.

### Memory bodies pulled

- `feedback_coincidental_equality_masks_concept_split` — directly
  applicable: "two named quantities equal in common config = SMELL
  hiding a concept split." The night-light action and the main-light
  action are coincidentally equal in every current room; splitting
  them makes the concept explicit (Bug Class #63 avoidance).
- `feedback_label_style_guide` — "no nerd words (hysteresis, debounce,
  provenance, substrate, tier, failsafe)"; short phrases + plain
  helper text. Governs the config-flow label wording below.
- `feedback_configurability_clarity` — named-bucket Select with
  one-sentence consequence per bucket, set-once in config flow
  (NOT a runtime Number entity). Matches `CONF_ENTRY_LIGHT_ACTION`.
- `feedback_marginal_benefit_pushback` — considered: simpler
  alternative = "pick A or B on LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1
  and leave the overload in place." Operator rejected 2026-09-15.
  Decision stands; this cycle is the explicit split.

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/automation.py`
  `_control_lights_entry` 1288–1430 (full function including the sleep
  branch at 1313, the dark-only resolver call at 1346, the slot/scene
  dispatch at 1364).
- `custom_components/universal_room_automation/actuator_reconciler.py`
  `_resolve_light` 794–895 (sleep branch 805–837, entry branch
  839–873, vacant branch 875–895).
- `custom_components/universal_room_automation/const.py` 870–1060
  (CONF_LIGHTS\* keys, LIGHT_ACTION\* vocabulary).
- `custom_components/universal_room_automation/config_flow.py`
  2850–2870 and 12760–12790 (both `CONF_ENTRY_LIGHT_ACTION` picker
  sites) + the Lighting-behaviour step added by Slice B'.
- `custom_components/universal_room_automation/lighting/resolver.py`
  (`effective_entry_set`, `effective_exit_set` seam).
- `docs/readmes/README_v5.103.29.md` end-to-end — Slice A through
  Slice E — to confirm no night-light action knob was shipped.

### Design docs read

Not applicable: this cycle is room-tier light automation, not a
coordinator domain with its own `docs/Coordinator/<NAME>.md`.
IDENTITY_FUSION_CAMERAS_MANUAL.md is not relevant (no identity /
census / fusion / egress surface).

### Prior-art scan verdict (REUSE-vs-BUILD per proposed piece)

| Proposed piece | Verdict | Prior art (file:line) |
|---|---|---|
| New vocabulary set | **REUSE** | `const.py:1055–1059` LIGHT_ACTION_\* (3 of 5 values map; `FOLLOW_MAIN` added) |
| Per-room Select field | **REUSE pattern** | `const.py:989 CONF_ENTRY_LIGHT_ACTION`, picker `config_flow.py:2859` |
| Config-flow placement | **REUSE step** | Slice B' `async_step_options_lighting_behaviour` already carries night-light pickers |
| Shared resolver helper | **REUSE module** | `lighting/resolver.py` already exists (Slice A); extend, don't new |
| Default-preserves-today | **REUSE pattern** | Lazy default idiom (`CONF_IS_EGRESS_WINDOW` / `DEFAULT_IS_EGRESS_WINDOW` `const.py:884–885`) |
| Migration | **NONE needed** | Absent-key default = `FOLLOW_MAIN` resolves to today's `CONF_ENTRY_LIGHT_ACTION` for all rooms |

Nothing proposed as "new" was found elsewhere. Everything "reused"
cites file:line.

---

## Falsifiable invariant (single property this cycle must guarantee)

**After the cycle ships, for every room config, the canonical path
(`automation._control_lights_entry`) and the actuator reconciler
(`actuator_reconciler._resolve_light`) resolve night-light entry
actuation to the SAME ON/OFF outcome under every (occupied,
is_sleep_hours, is_dark, main_action, night_light_action, is_night_light_entity)
tuple.** The outcome depends ONLY on
`effective_night_light_entry_action(cfg)` — never on
`CONF_ENTRY_LIGHT_ACTION` directly inside either light-decision
function — AND on the existing sleep/occupancy branches. Any config
whose two controllers disagree is a bug.

Falsifier (concrete, legal-config): a bedroom with
`night_lights=[light.bedside]`, `CONF_ENTRY_LIGHT_ACTION=none`,
`CONF_NIGHT_LIGHT_ENTRY_ACTION=turn_on` under house-Sleep + occupied:
canonical must turn `light.bedside` ON (today's bug: it returns
early); reconciler must also assert ON (today: it does). The opposite
room with `CONF_NIGHT_LIGHT_ENTRY_ACTION=none` under same conditions:
canonical must NOT turn `light.bedside` ON AND reconciler must NOT
assert ON (today: canonical skips, reconciler asserts — divergence
closes here).

---

## Deliverables

### D1 — Add `CONF_NIGHT_LIGHT_ENTRY_ACTION` + resolver

Add the field, its vocabulary, its default, and the resolver helper
BOTH controllers consume.

- `const.py` — three additions:
  - `CONF_NIGHT_LIGHT_ENTRY_ACTION: Final = "night_light_entry_action"`.
  - `LIGHT_ACTION_FOLLOW_MAIN: Final = "follow_main"`.
  - `DEFAULT_NIGHT_LIGHT_ENTRY_ACTION: Final = LIGHT_ACTION_FOLLOW_MAIN`.
- `lighting/resolver.py` — new pure helper
  `effective_night_light_entry_action(cfg) -> str`:
  1. Read `cfg.get(CONF_NIGHT_LIGHT_ENTRY_ACTION, DEFAULT_NIGHT_LIGHT_ENTRY_ACTION)`.
  2. If value is `FOLLOW_MAIN` → return
     `cfg.get(CONF_ENTRY_LIGHT_ACTION, LIGHT_ACTION_NONE)` collapsed to
     the three night-light-legal values: NONE / TURN_ON / TURN_ON_IF_DARK.
     Main-action TURN_OFF or LEAVE_ON collapse to NONE for night-light
     purposes (TURN_OFF / LEAVE_ON are exit-side meanings; a night
     light with no explicit WHEN inherits "do nothing on entry" when
     the main field is on an exit-shaped value).
  3. If value is one of {NONE, TURN_ON, TURN_ON_IF_DARK} → return as-is.
  4. Any other value → return NONE (fail-closed, matches today's
     "if action not recognised, do nothing").
- Pure function; no `hass` dependency; unit-testable directly.

**Vocabulary justification.** Options for the new Select:
`follow_main` (default, equals today), `none` (never on entry),
`turn_on` (always on entry — most common bedroom intent), `turn_on_if_dark`
(darkness-gated). Deliberate omissions: `turn_off` and `leave_on` are
exit-side concepts that have no clean "entry" meaning for a night
light; adding them would re-overload the field. If a future need
arises (e.g. "ensure OFF at entry during the day"), that is a
separate card.

#### Acceptance criteria (D1)

- **Verify:** `const.py` grep finds `CONF_NIGHT_LIGHT_ENTRY_ACTION`,
  `LIGHT_ACTION_FOLLOW_MAIN`, `DEFAULT_NIGHT_LIGHT_ENTRY_ACTION`.
- **Verify:** `lighting/resolver.py` exports
  `effective_night_light_entry_action`.
- **Test:** `test_night_light_action_resolver.py` — table-driven:
  5 vocabulary values × 5 main-action values = 25 cases; each returns
  one of {NONE, TURN_ON, TURN_ON_IF_DARK}; `FOLLOW_MAIN` rows mirror
  the main action with the TURN_OFF/LEAVE_ON → NONE collapse named.
- **Test:** absent-key fixture returns the SAME value as a fixture
  with `CONF_NIGHT_LIGHT_ENTRY_ACTION=FOLLOW_MAIN` (lazy-default
  equivalence — the migration-free invariant).

### D2 — Rewire canonical `_control_lights_entry`

Replace the early-return-on-NONE with a split that honours night
lights independently.

- `automation.py:_control_lights_entry`:
  - Compute `main_action = cfg.get(CONF_ENTRY_LIGHT_ACTION, NONE)` (today).
  - Compute `nl_action = effective_night_light_entry_action(cfg)` (D1 helper).
  - **Remove** the current `if main_action == NONE: return` at `:1295`.
    Replace with: `if main_action == NONE and nl_action == NONE: return`
    (both silent → no-op, today's happy-path for rooms with no night
    lights preserved).
  - Sleep branch (`:1313 if is_sleep_hours and night_lights`): gated
    by `nl_action != NONE` instead of running unconditionally — a
    room that explicitly says "night lights NONE on entry" skips the
    sleep-mode night-light turn-on. Scene short-circuit retained.
  - Non-sleep branch (today's `should_turn_on` computation at `:1332`):
    - `main_should_on = main_action == TURN_ON or (main_action == TURN_ON_IF_DARK and is_dark)`
    - `nl_should_on = nl_action == TURN_ON or (nl_action == TURN_ON_IF_DARK and is_dark)`
    - If `main_should_on`: today's path (resolver + slot scene +
      `_turn_on_regular_lights`) unchanged, operating on the main set
      only (`entry_set - night_lights`).
    - Else if `nl_should_on`: run `_turn_on_night_lights(mode="day")`
      (or evening slot per existing Slice E logic) for the night-light
      subset only. This is the NEW path — today it's unreachable.
    - Else: return.
- Behaviour preservation (`FOLLOW_MAIN` default): because
  `effective_night_light_entry_action` collapses to the main action
  under `FOLLOW_MAIN`, every existing room's canonical path produces
  the SAME turn-on set as before.

#### Acceptance criteria (D2)

- **Verify:** `automation.py:1295` no longer early-returns solely on
  `main_action == NONE`; the gate is the conjunction with `nl_action`.
- **Test:** behavioural matrix `test_night_light_action_canonical.py`:
  - (sleep=T, occupied=T, main=NONE, nl=TURN_ON, night_lights=[L]) →
    `_turn_on_night_lights` called with [L].
  - (sleep=T, occupied=T, main=NONE, nl=NONE, night_lights=[L]) →
    NO turn_on dispatched. Scene branch skipped.
  - (sleep=F, is_dark=T, main=NONE, nl=TURN_ON_IF_DARK) → night lights
    only on; main lights off (per `_turn_off_non_night_lights` or
    simple no-call on main set).
  - (main=TURN_ON, nl=FOLLOW_MAIN) → identical to pre-cycle behaviour
    (regression anchor, 1:1 with the pre-cycle fixture).
- **Test:** mutation drill (per Numbers-Get-Knobs discipline) — delete
  the new `nl_should_on` branch; a named test MUST go red.
- **Live:** Jaya bedroom (bedside night light, operator-known test
  room) under sleep: previously tested set to `entry=none`, flipping
  `nl_action` to `turn_on` makes bedside come on; `nl_action=none`
  keeps it off. Capture via `ura_activity_log` `light.turn_on` rows
  under room entry events during sleep hours.

### D3 — Rewire reconciler `_resolve_light`

Mirror D2's split so both controllers consume
`effective_night_light_entry_action` and agree.

- `actuator_reconciler.py:_resolve_light`:
  - Sleep + occupied + night-light member (`:813–:829`): gate the ON
    assertion on `nl_action != NONE`. If `nl_action == NONE`, fall
    through (same path vacant night-lights already use) so the vacant
    branch does not fire and the main-action occupied branch runs on
    this entity. For an entity that is a night light AND
    `nl_action == NONE` AND `main_action == NONE`: `None` (no assertion
    — today it is asserted ON by the sleep branch, which is the exact
    bug).
  - Entry branch (`:839–:873`, non-sleep): for a night-light member
    entity, use `nl_action` instead of `main_action` for the ON
    decision. The existing `effective_entry_set` call stays; night-light
    membership restricts the set the same way. Capability + brightness
    pass-through unchanged.
  - Vacant branch (`:875–:895`): UNCHANGED. Exit decisions are
    governed by `CONF_EXIT_LIGHT_ACTION` + `effective_exit_set` and
    are out of scope.
- `FOLLOW_MAIN` default again: night-light members whose nl_action
  resolves back to the main action produce today's reconciler row for
  every existing room.

#### Acceptance criteria (D3)

- **Test:** parity-fixture `test_night_light_action_parity.py`:
  for a dense cartesian (occupied ∈ {T,F}) × (sleep ∈ {T,F}) ×
  (is_dark ∈ {T,F}) × (main ∈ 5 values) × (nl ∈ 5 values) × (entity
  ∈ main_only / night_light / both), canonical and reconciler agree
  on the OUTCOME (on/off/no-opinion) for every cell.
- **Test (discriminator — the F2/F3 fix):** two sibling rooms,
  identical except `nl_action`. Room A `nl=turn_on` under
  (main=NONE, sleep=T, occupied=T) → BOTH controllers assert the
  night light ON. Room B `nl=none` under same conditions → NEITHER
  controller asserts ON. Previously BOTH rooms behaved identically
  AND internally inconsistent.
- **Live:** post-restart, with Jaya bedroom and master bedroom carrying
  opposite `nl_action` values, grep HA log for
  `actuator_reconciler` divergence warnings over 24 hours of normal
  sleep — zero. Fill the README Live Validation table with observed
  entity_id state transitions at the sleep boundary.

### D4 — Config-flow surface + labels

Add the Select to the existing Lighting-behaviour step.

- `config_flow.py` `async_step_options_lighting_behaviour` — add one
  new `vol.Optional(CONF_NIGHT_LIGHT_ENTRY_ACTION,
  default=self._get_current(CONF_NIGHT_LIGHT_ENTRY_ACTION,
  DEFAULT_NIGHT_LIGHT_ENTRY_ACTION))` field, immediately after the
  Night Lights picker, in the SAME step the Night Lights picker now
  lives in post-Slice-B'. SelectSelector with four options.
- `strings.json` + `translations/en.json` — add the field label and
  helper text under the step. Label: **"Night lights on entry"** (3
  words). Options (per label-style-guide: ≤3 words, no nerd terms):
  - `follow_main` → "Follow main lights"
    (helper: "Match whatever the main lights do on entry.")
  - `turn_on` → "Always on"
    (helper: "Night lights come on when someone enters.")
  - `turn_on_if_dark` → "Only when dark"
    (helper: "Night lights come on at entry only if the room is dark.")
  - `none` → "Never"
    (helper: "Night lights never come on from entry. Sleep scenes and
    manual control still work.")
- No `description={"advanced": True}` — this is a core intent knob,
  not a tunable.
- Knob-ladder placement: **config/options flow** (per-deployment
  structure, set-once-per-room, infrequent change). NOT a Number /
  Select / Switch entity (would clutter the room device dashboard;
  operator ruling in Slice D "not on the room device" for the
  manual-hold windows applies here too).

#### Acceptance criteria (D4)

- **Verify:** opening a room's Options → Lighting behaviour shows the
  new "Night lights on entry" field with four choices; default
  "Follow main lights"; the four helper strings render.
- **Test:** `test_room_dialog_strings.py` — extend `ROOM_OPTIONS_STEPS`
  with the new field key; four option strings asserted present in
  translations.
- **Test:** round-trip — save `turn_on`, close options, reopen; value
  preserved (lazy-default guard — absence ≠ FOLLOW_MAIN explicit, both
  must map to the same runtime answer per D1).
- **Live:** operator sets Jaya bedroom to "Always on" and master
  bedroom to "Never"; sleep-hour entry events dispatch per the room's
  pick (see D2/D3 Live).

---

## Producer AND Consumer map (standing rule)

**Producer** of the night-light action value:

- `effective_night_light_entry_action(cfg)` — the single producer,
  pure helper in `lighting/resolver.py`.
- Depends on: `cfg[CONF_NIGHT_LIGHT_ENTRY_ACTION]` (new, lazy default
  `FOLLOW_MAIN`), `cfg[CONF_ENTRY_LIGHT_ACTION]` (existing, when
  resolving `FOLLOW_MAIN`). Dependency health: both are stored
  options read via `cfg.get`; never None at call time (config entry
  is loaded by the time either controller runs).

**Consumers (every reader, trust-vs-display):**

| Site | File:line | Trust/decision |
|---|---|---|
| Canonical entry decision | `automation.py:1292` and new split | Trust (fires turn_on) |
| Reconciler sleep branch | `actuator_reconciler.py:813` (modified) | Trust (asserts ON) |
| Reconciler entry branch | `actuator_reconciler.py:839` (modified for night-light members) | Trust (asserts ON) |
| Slot scene short-circuit | `automation.py:_maybe_activate_slot_scene` call sites (sleep + non-sleep) | Trust (dispatches scene instead of per-light) — the gate is `nl_action != NONE` for the sleep scene site |
| Away sweep (Slice D) | `automation.py:handle_away_leave_on_sweep` | UNAFFECTED (writes OFF for `CONF_LIGHTS_LEAVE_ON_WHEN_EMPTY`; not an entry decision) |
| Guest gate (deferred) | `LIGHTS-GUEST-MODE-BEHAVIOUR-1` | OUT OF SCOPE (Guest card will consume separately when it ships) |
| D3 `RoomLightsSwitch` | `switch.py` (Slice C) | UNAFFECTED (its ON = resolver `effective_entry_set`; night-light sub-decision is not its concern) |
| Dashboard/entity display | none proposed | — |

The map's point: ONE producer, every entry-time night-light reader
runs through it. The two sites that today disagree (canonical,
reconciler) become one answer.

---

## Four open decisions settled

1. **Option vocabulary** — Reuse `LIGHT_ACTION_NONE` / `_TURN_ON` /
   `_TURN_ON_IF_DARK`; add one new value `LIGHT_ACTION_FOLLOW_MAIN`.
   TURN_OFF and LEAVE_ON intentionally omitted (exit-side meanings).
2. **Default** — `FOLLOW_MAIN`. Lazy-default idiom; no migration
   needed; every existing room produces today's behaviour unchanged
   until the operator opens the knob.
3. **Config-flow placement** — Per-room options, inside
   `async_step_options_lighting_behaviour` (added by Slice B'),
   immediately after the Night Lights entity picker. Label-style-guide
   wording per D4.
4. **Both controllers read ONE resolver** — Yes:
   `effective_night_light_entry_action(cfg)` in `lighting/resolver.py`.
   This is the structural fix that closes LIGHT-SLEEP-ENTRYNONE-DIVERGENCE-1.

---

## Non-goals

- Guest mode behaviour — owned by `LIGHTS-GUEST-MODE-BEHAVIOUR-1`.
- Exit-side night-light actuation — governed by
  `CONF_EXIT_LIGHT_ACTION` and `effective_exit_set`; NIGHT-LIGHT-NO-OFF-PATH-1
  shipped. Unchanged here.
- Scene / slot vocabulary changes — Slice E's slot resolution is
  reused unchanged; adding "evening-only night-light action" is a
  future card.
- New Number / Select / Switch entities — set-once knob, config-flow
  only.
- Any change to `CONF_ENTRY_LIGHT_ACTION` semantics for main lights.
- Any migration of stored room data (absent-key default handles it).
- Any change to the Away sweep, the manual hold, or the D3 room-lights
  switch.
- `KITCHEN-NIGHTLIGHT-RANGE-MISCONFIG-1` (parked; wrong-entity config
  bug, unrelated).

---

## Migration

**None required.** Lazy-default idiom (per `CONF_IS_EGRESS_WINDOW`
precedent `const.py:884`): rooms whose stored options lack
`CONF_NIGHT_LIGHT_ENTRY_ACTION` resolve to `FOLLOW_MAIN` →
`CONF_ENTRY_LIGHT_ACTION`. The behavioural matrix in D2's acceptance
tests PROVES per-room preservation for every representative
(main, sleep, dark, occupied, night_light_member) configuration seen
across the ~40 live rooms. Operator-ruled test anchor: Jaya bedroom
behaviour must be byte-identical pre-vs-post deploy until the
operator explicitly flips the knob.

---

## Review tier + framings

- **Baseline:** Tier 2 (feature cycle, config surface + 2
  controllers). TWO parallel reviews with disjoint framings:
  - Reviewer A — correctness + edge cases + vocabulary coherence
    (TURN_OFF/LEAVE_ON collapse logic; absent-key path; main=none
    + nl=none interaction with the removed early-return).
  - Reviewer B — async + lifecycle + cross-controller parity
    (canonical↔reconciler agreement across the acceptance cartesian;
    interaction with Slice C hold, Slice D Away, Slice E slot scenes).
- **Recommendation to elevate to Tier 2-DB (THREE framing-disjoint
  reviews):** YES. This is a shared-primitive change consumed by two
  independent controllers whose historical disagreement is the
  defect being closed; the standing policy (2026-06-08) covers it.
  Framings:
  - A — local correctness of the new field + resolver.
  - B — migration/no-flap: every existing room produces today's
    behaviour under `FOLLOW_MAIN` default; no boot-time edge dispatches.
  - C — surfaces: config-flow round-trip; translations; label-style
    guide compliance; `RoomLightsSwitch` and Away sweep genuinely
    UNAFFECTED (grep + mutation drill).
- Final tier gate: operator.

---

## Plan Completion Tracking

Placeholder — to be filled at ship. For each of D1 / D2 / D3 / D4,
record: DONE, DEFERRED (with reason + where tracked), or DROPPED
(with reason + explicit decision citation). Any plan item not built
MUST be accounted for in the ship README per CLAUDE.md.

---

## Appendix — files that will be touched

| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | +3 constants (CONF, DEFAULT, LIGHT_ACTION_FOLLOW_MAIN) |
| `custom_components/universal_room_automation/lighting/resolver.py` | +1 pure helper `effective_night_light_entry_action` |
| `custom_components/universal_room_automation/automation.py` | `_control_lights_entry` 1288-end: split main vs night-light decision |
| `custom_components/universal_room_automation/actuator_reconciler.py` | `_resolve_light` sleep branch 813–837 and entry branch 839–873: gate night-light members on `nl_action` |
| `custom_components/universal_room_automation/config_flow.py` | +1 SelectSelector field in `async_step_options_lighting_behaviour` |
| `custom_components/universal_room_automation/strings.json` + `translations/en.json` | label + helper + 4 option strings |
| `quality/tests/test_night_light_action_resolver.py` (new) | D1 unit matrix |
| `quality/tests/test_night_light_action_canonical.py` (new) | D2 behavioural matrix |
| `quality/tests/test_night_light_action_parity.py` (new) | D3 canonical↔reconciler parity |
| `quality/tests/test_room_dialog_strings.py` (extend) | D4 translations + field assertions |
