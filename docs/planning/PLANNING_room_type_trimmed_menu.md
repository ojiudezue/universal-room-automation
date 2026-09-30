# PLANNING — ROOM-TYPE-TRIMMED-MENU-1

**Card:** `ROOM-TYPE-TRIMMED-MENU-1` (kanban.data.yaml:30597)
**Tier:** 2 (options-flow menu construction; user-visible surface across all room entries; no behavioural change).
**Author:** ura-planner, 2026-09-29
**Deploy:** HELD for operator.

The operator idea "mini room" is realised **not** as a new entry kind but as
**attenuation of the room options menu by `room_type`**. Every stored value keeps
working; the menu just stops showing steps that don't apply to the type. A
"More settings…" escape hatch reveals the full menu for one visit.

---

## Institutional context verified

### Greps run
- **Room type constants** — `const.py:437-450` — REUSED: `ROOM_TYPE_BEDROOM /
  _CLOSET / _BATHROOM / _MEDIA_ROOM / _GARAGE / _UTILITY / _COMMON_AREA /
  _GENERIC / _INFRASTRUCTURE / _HALLWAY` (10 types).
- **Current room options menu** — `config_flow.py:3526-3544` (`async_step_init`
  else branch, `entry_type == ENTRY_TYPE_ROOM`) — REUSED: the 12-step list
  (`basic_setup, sensors, devices, options_lighting, options_covers,
  automation_chaining, ai_rules, climate, sleep_protection, music_following,
  energy, notifications`). Confirmed against `translations/en.json:558-608`
  (`init.menu_options`).
- **Add-room wizard** — `config_flow.py:1439-1836` (`async_step_room_setup →
  room_class → …→ room_summary`). Wizard chains steps by calling
  `async_step_<next>` at the end of each step handler; `ROOM_TYPE_FEATURE_DEFAULTS`
  already seeds per-type defaults (line 1799). REUSED: same
  chaining pattern; the wizard is where "skipped steps take today's defaults"
  is enforced (no code change for hidden steps — defaults already seeded).
- **Existing per-type gating** — none found for the room options menu. HVAC uses
  `ROOM_TYPE_HALLWAY` as a CIRCULATION exclusion (`const.py:446`), but the
  options flow menu itself has no `room_type` branching today. NEW code needed:
  a single menu-filter helper.
- **Menu-construction pattern** — `async_show_menu(step_id="init",
  menu_options=[...])` (config_flow.py:3459, 3486, 3519, 3528). REUSED
  unchanged; we just pass a filtered list.
- **`CONF_ROOM_TYPE`** — read at `config_flow.py:1465, 1545, 1799, 2671`. Available
  from `self._config_entry.data` in the options flow; no new field.
- **`ROOM_TYPE_FEATURE_DEFAULTS`** — referenced at `config_flow.py:1546, 1799`
  (per-type seeding). REUSED as the source of truth for "what is a default" in
  the in-use check.

### Prior planning / analysis
- **`docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md`** —
  parent plan for the room-dialog refinement arc. The trimmed menu is the
  structural sibling of the ROOM-DIALOGS-USABILITY-SWEEP-1 (wording, done/held)
  and ROOM-LIGHTING-SETUP-REDESIGN-1 (Lighting step rebuild, in build slices
  A+B on `feature/room-lighting-roles`).
- **Adjacencies (kanban):** ROOM-LIGHTING-SETUP-REDESIGN-1 (Lighting step gets
  reshaped in parallel — this plan does NOT edit that step, only decides when
  to *show* it; every type shows Lighting so no conflict), ROOM-DIALOGS-
  USABILITY-SWEEP-1 (wording), ZONE-DIALOGS-CLEANUP-1 / HOUSE-DIALOGS-CLEANUP-1
  (later; same meta-pattern).

### Memory bodies pulled
- `feedback_label_style_guide` — plain phrasing for "More settings…".
- `feedback_configurability_clarity` — set-once knobs in config flow; a
  type-driven menu is the same idea one level up.
- `feedback_config_first_before_code` — verified: no live knob today attenuates
  the menu; adding a rung-1 map is the smallest fix.
- `feedback_extend_existing_never_rebuild` — extend `async_step_init`, don't
  clone a new entry type.

### Design docs read
- Room dialogs are UX; no coordinator design doc applies. HVAC state-of-play NOT
  required (no HVAC change).

### Files surveyed end-to-end during scoping
- `custom_components/universal_room_automation/config_flow.py:3453-3545` (init
  menus), `:1439-1836` (add-room wizard).
- `custom_components/universal_room_automation/const.py:436-450` +
  `ROOM_TYPE_FEATURE_DEFAULTS` (grepped, definition site to be verified during
  build).
- `translations/en.json:558-608` (menu labels).

### REUSE / BUILD verdict per proposed piece
| Piece | Verdict | Cite |
|---|---|---|
| Room type enum | REUSE | `const.py:437-450` |
| Options menu construction | REUSE (pass filtered list) | `config_flow.py:3528` |
| `CONF_ROOM_TYPE` read | REUSE | `config_flow.py:1465` |
| Per-type defaults for in-use check | REUSE | `ROOM_TYPE_FEATURE_DEFAULTS` |
| Type → visible-steps map | **NEW** — rung-1 module constant `ROOM_MENU_STEPS_BY_TYPE` in `const.py`. Justification: no existing table encodes this. |
| "In-use" predicate per step | **NEW** — small `_step_has_non_default_values(step, options, room_type)` in `config_flow.py`. |
| "More settings…" menu row | **NEW** — one extra menu key (`show_all_settings`) whose handler re-shows `init` with the full list, one visit only (transient flag on `self`). |

---

## Falsifiable invariant

> **No stored value is ever unreachable from the menu.**
> For every room entry, for every step S in the full 12-step room options menu:
> either (a) S appears in the trimmed menu for the room's current type, OR
> (b) `_step_has_non_default_values(S, options, room_type)` is False, OR
> (c) the user selects "More settings…" (which re-adds S to the visible list
> for that visit).
> Equivalently: any step whose stored values differ from defaults MUST be
> visible in the default (non-More) menu.

D's job: find a `(room_type, step, options)` triple where a non-default value
is stored AND the step is hidden AND "More settings…" is not offered.

---

## Deliverables

### D1 — Type → steps map (rung-1 module constant)

Add to `const.py` (adjacent to `ROOM_TYPE_*`):

```python
# Full room options menu — source of truth (mirrors config_flow.py:3528).
ROOM_MENU_STEPS_ALL: Final = (
    "basic_setup", "sensors", "devices",
    "options_lighting", "options_covers",
    "automation_chaining", "ai_rules",
    "climate", "sleep_protection", "music_following",
    "energy", "notifications",
)

# Per-type visible subset. Every type gets basic_setup + sensors + devices +
# options_lighting (operator ruling 2026-09-29: Lighting shown for ALL types
# including infrastructure). "More settings…" always reveals the full menu.
ROOM_MENU_STEPS_BY_TYPE: Final = {
    ROOM_TYPE_COMMON_AREA:    ROOM_MENU_STEPS_ALL,          # everything
    ROOM_TYPE_BEDROOM:        ROOM_MENU_STEPS_ALL,          # everything
    ROOM_TYPE_MEDIA_ROOM:     ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_GENERIC:        ROOM_MENU_STEPS_ALL,          # unknown → show all
    ROOM_TYPE_BATHROOM:       ("basic_setup", "sensors", "devices",
                               "options_lighting", "options_covers",
                               "climate", "notifications"),
    ROOM_TYPE_GARAGE:         ("basic_setup", "sensors", "devices",
                               "options_lighting", "options_covers",
                               "energy", "notifications"),
    ROOM_TYPE_INFRASTRUCTURE: ("basic_setup", "sensors", "devices",
                               "options_lighting", "climate",
                               "energy", "notifications"),
    ROOM_TYPE_CLOSET:         ("basic_setup", "sensors", "devices",
                               "options_lighting", "options_covers"),
    ROOM_TYPE_HALLWAY:        ("basic_setup", "sensors", "devices",
                               "options_lighting", "options_covers"),
    ROOM_TYPE_UTILITY:        ("basic_setup", "sensors", "devices",
                               "options_lighting"),
}
```

**Covers analysis (operator invited):**
Covers plausibly exist in: bedrooms (blinds), common_area (blinds/shades),
media_room (blackout), bathroom (blinds/skylights), garage (garage doors),
closet (occasional wardrobe blinds/skylights), hallway (skylights, transom
shades). Not typical: utility, infrastructure.
**Recommendation — show Covers on all room types EXCEPT utility and
infrastructure.** Rationale: (a) the "in use" rule and "More settings…" cover
the miss case anyway, so false-hides cost more than false-shows; (b) closet /
hallway covers are unusual but not exotic (skylights over stairwells, wardrobe
shades); (c) removing Covers from utility/infra costs nothing — anyone with a
covered utility room is a "More settings…" click away. This is what the table
above encodes. If the operator wants a tighter cut (e.g. drop closet/hallway),
edit the tuples — no other code changes.

### D2 — Filtered menu + in-use reveal

In `config_flow.py::async_step_init` (else branch, ~line 3528):

```python
room_type = self._config_entry.data.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
opts = self._config_entry.options
visible = list(ROOM_MENU_STEPS_BY_TYPE.get(room_type, ROOM_MENU_STEPS_ALL))
# In-use reveal: any step with non-default stored values is always shown.
for step in ROOM_MENU_STEPS_ALL:
    if step not in visible and _step_has_non_default_values(step, opts, room_type):
        visible.append(step)
# Preserve canonical order.
visible = [s for s in ROOM_MENU_STEPS_ALL if s in visible]
if getattr(self, "_show_all_this_visit", False):
    visible = list(ROOM_MENU_STEPS_ALL)
    self._show_all_this_visit = False   # one-shot
menu = visible + (["show_all_settings"] if visible != list(ROOM_MENU_STEPS_ALL) else [])
return self.async_show_menu(step_id="init", menu_options=menu)
```

And:

```python
async def async_step_show_all_settings(self, user_input=None):
    self._show_all_this_visit = True
    return await self.async_step_init()
```

### D3 — `_step_has_non_default_values` (the load-bearing piece)

A step's CONF keys → "non-default" per this precise rule (verify each list at
build time by grepping the step's `vol.Schema` in `config_flow.py`):

- **Present in `options` AND `options[k]` != `ROOM_TYPE_FEATURE_DEFAULTS[room_type].get(k, MODULE_DEFAULT)`.**
- For list/dict CONFs, non-default = **non-empty** (any configured sensor,
  device, chain, rule, etc.).
- For bool CONFs, non-default = value differs from the type-seeded default.
- For scalar knobs, non-default = value differs from the type-seeded default.

Build a `_STEP_CONF_KEYS: dict[str, tuple[str, ...]]` table adjacent to
`ROOM_MENU_STEPS_ALL` — enumerated from each `async_step_<name>` schema.
**Build task**: verify each step's schema and populate the table; every CONF
present in the step's schema MUST be in the table (an unlisted key is a false
negative — the invariant fails).

Test-authority requirement (Tier 2): the builder MUST write a schema→table
consistency test that greps every `async_step_<step>` in the room options flow,
extracts its `vol.Required/Optional` keys, and asserts they are all covered by
`_STEP_CONF_KEYS[step]`. Otherwise the map decays silently as steps evolve.

### D4 — Add-room wizard uses the same map

The wizard (`async_step_room_setup → …`) already seeds per-type defaults via
`ROOM_TYPE_FEATURE_DEFAULTS` at `config_flow.py:1799`. Modify the wizard chain
so after `room_class` it walks ONLY the steps in
`ROOM_MENU_STEPS_BY_TYPE[room_type]` in canonical order; steps not in the type's
list are skipped (defaults already seeded). No new prompts, no new fields.

### D5 — Type change redraws the menu

`basic_setup` (or wherever `CONF_ROOM_TYPE` is editable in options) must, on
change of `CONF_ROOM_TYPE`, return to `async_step_init` (already the pattern
after a save) — no extra work, but add an acceptance test.

### D6 — Translations

Add one label: `component.universal_room_automation.options.step.init.menu_options.show_all_settings = "More settings…"`. No other translation changes (all steps keep their existing labels).

---

## Non-goals

- No hiding fields **inside** a step (out of scope; belongs to per-step cleanup
  cards).
- No behaviour change by type (a hidden step's stored values continue to run
  unchanged — the coordinators never read the menu).
- No new entry type ("mini room" is realised as menu attenuation).
- No changes to `ROOM_TYPE_FEATURE_DEFAULTS` semantics or values (only *read*).
- No migration (menu-only; nothing persisted changes shape).
- No Zone/House menu changes (separate cards).

---

## Acceptance criteria

- **Test — menu snapshot per type:** parametrised test over all 10 room types.
  For a freshly-created room entry with only defaults, the `init` menu equals
  `ROOM_MENU_STEPS_BY_TYPE[type]` + `show_all_settings` (or exactly
  `ROOM_MENU_STEPS_ALL` for the "everything" types, with no `show_all_settings`
  row).
- **Test — in-use reveal per step:** for each (type, hidden_step) pair, seed
  one non-default value for a CONF in that step; assert the step now appears in
  the trimmed menu.
- **Test — More settings reaches all:** selecting `show_all_settings` returns
  `menu_options == list(ROOM_MENU_STEPS_ALL)` for one visit; a subsequent
  re-entry to `init` reverts to the trimmed list.
- **Test — hidden step round-trips:** hide a step by type; assert that its
  stored `options[k]` values are unchanged after opening + closing the options
  flow (the flow never writes zero for hidden keys).
- **Test — wizard for a closet asks exactly N steps:** closet wizard walks
  `basic_setup, sensors, devices, options_lighting, options_covers` and ends at
  `room_summary`; utility walks 4 (no covers); infrastructure walks 7.
- **Test — type change redraws:** change `CONF_ROOM_TYPE` from `bedroom` to
  `closet`; next `init` menu is the closet trim; a bedroom-only step whose
  values now differ from closet defaults reveals via the in-use rule.
- **Test — invariant guard:** for every (type, step) with step NOT in
  `ROOM_MENU_STEPS_BY_TYPE[type]`, verify `_STEP_CONF_KEYS[step]` covers every
  `vol.Required/Optional` in that step's schema (falsifies D's invariant if it
  doesn't).
- **Live — closet room:** open a closet room's options; menu shows 5 items +
  "More settings…"; select "More settings…"; all 12 items appear; re-enter
  options; back to 5 items. Verify no coordinator log warning about missing
  config.
- **Live — bathroom with a stored `music_following` value:** if any bathroom
  has non-default music_following stored (unlikely but possible), the row
  appears; verify.
- **Live — wizard:** add a new utility room; wizard asks 4 steps then summary;
  after create, coordinators come up green for that entry.

---

## Files touched

- `custom_components/universal_room_automation/const.py` — add
  `ROOM_MENU_STEPS_ALL`, `ROOM_MENU_STEPS_BY_TYPE`, `_STEP_CONF_KEYS`.
- `custom_components/universal_room_automation/config_flow.py` — modify
  `async_step_init` (else branch); add `_step_has_non_default_values` and
  `async_step_show_all_settings`; wizard chain filter (D4); one-shot flag on
  the flow instance.
- `custom_components/universal_room_automation/translations/en.json` +
  `strings.json` — add `show_all_settings` label.
- `quality/tests/config_flow/test_room_menu_trim.py` — new test file for D2/D3/D5
  criteria + the schema-consistency guard.

---

## Tier & review plan

- **Tier 2** (menu construction; every room entry sees this; correctness of
  the in-use predicate is load-bearing).
- **Plan review:** ONE adversarial plan review (Tier 2 rule) — re-grep every
  `async_step_<step>` schema and confirm `_STEP_CONF_KEYS` is complete;
  falsify the invariant on paper for a hand-picked (bathroom, sleep_protection)
  case.
- **Build reviews (two, framing-disjoint):**
  A = correctness + edge cases (defaults semantics, list/dict/bool/scalar
  branches, one-shot flag lifecycle, wizard skip correctness);
  B = UX + lifecycle (menu re-entry, type-change redraw, translation
  completeness, in-use reveal ordering, coexistence with the
  ROOM-LIGHTING-SETUP-REDESIGN-1 Lighting step landing in parallel).
- **Deploy HELD** for operator sign-off on the trim table (esp. Covers).

---

## Coordination note

`ROOM-LIGHTING-SETUP-REDESIGN-1` is mid-build on `feature/room-lighting-roles`.
This plan does not modify the Lighting step content; it only decides when to
show it, and every room type shows it. Merge order: land Lighting redesign
first, then this trim map — no rebase risk.
