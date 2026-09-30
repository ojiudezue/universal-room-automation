> **REV 3 scope addition (operator 2026-09-30):** fold in a SIMPLE / ADVANCED model for EVERY URA config + options flow (room, zone, house, coordinators). Use HA's built-in per-user profile **Advanced mode** (`show_advanced_options`, verified homeassistant/data_entry_flow.py:645-667; fields marked `description={"advanced": True}` are dropped when off) instead of a custom toggle. Tiers: Simple (default) = the fields most people set; collapsed sections = visible-but-folded; Advanced mode = tuning values + trimmed steps revealed (subsumes most of "More settings…"). Deliverable: classify every field of every flow (table), apply markers, tests per flow for both modes, and a check that no stored value becomes unreachable (Advanced mode reveals all). First instance already built on the lighting branch: the two manual-hold windows are advanced fields. Needs a plan re-review after this rewrite.

# PLANNING — ROOM-TYPE-TRIMMED-MENU-1

**Card:** `ROOM-TYPE-TRIMMED-MENU-1` (kanban.data.yaml:30597)
**Tier:** 2 (options-flow menu construction; user-visible surface across all
room entries; no behavioural change).
**Author:** ura-planner, 2026-09-29
**Deploy:** HELD for operator.

## Revision history
- **REV 1** (2026-09-29) — initial plan.
- **REV 2** (2026-09-29, this file) — applies
  `docs/reviews/code-review/plan_review_room_type_trimmed_menu.md`. Changes:
  (1) in-use predicate reads **merged `data` + `options`** (mirrors
  `_get_current`, `config_flow.py:3167-3171`) — Finding 1;
  (2) NO new defaults table — each step's defaults are derived by **building
  the step's real schema** (per room type / zone / HVAC membership) and
  comparing — Finding 2 & 5;
  (3) **D4 DROPPED** (add-room wizard no longer walks options steps;
  `config_flow.py:1526-1533`) plus its tests — Finding 4;
  (4) step→keys table built by **calling each step handler** (incl. collapsed
  section schemas), not by grepping source — Finding 5;
  (5) cross-step keys (`CONF_ZONE`, `CONF_ROOM_TYPE`, `CONF_COVER_TYPE`,
  `CONF_COVERS`) excluded from steps that don't OWN them — Finding 6;
  (6) invariant restated in testable "Equivalently…" form — Finding 8;
  (7) show-once flag dropped — Finding 10;
  (8) D5 kept as a test only — Finding 9;
  (9) two operator decisions APPLIED with the recommended defaults, flagged:
  **Fan Mode does NOT count as in-use** (`CONF_ROOM_FAN_MODE`, written by
  migration + Select entity — Finding 3); **Covers hidden for garage too**
  (no garage-door guard in room cover automation — Finding 7);
  (10) new acceptance tests: legacy `data`-only room, Fan-Mode-only room;
  (11) sequenced AFTER `feature/room-lighting-roles` slices B'/C/D land, so
  the schema-derived key table picks up the new Lighting shape.

---

## Institutional context verified

### Greps run
- **Room type constants** — `const.py:437-450` — REUSED: 10 types.
- **Current room options menu** — `config_flow.py:3526-3544` — REUSED: the 12
  steps (`basic_setup, sensors, devices, options_lighting, options_covers,
  automation_chaining, ai_rules, climate, sleep_protection, music_following,
  energy, notifications`).
- **Merged data+options read pattern** — `_get_current` at
  `config_flow.py:3167-3171` — REUSED: `{**entry.data, **entry.options}[k]`.
  This is what D3 must mirror.
- **Add-room wizard shape (current)** — `config_flow.py:1526-1533` — the
  create-path is `room_setup → room_class → sensors_confirm →
  devices_confirm → room_summary`. The old mid-flow options steps are
  **unreached on create**. D4 is therefore not needed.
- **Existing per-type defaults (scattered, NOT one table)** —
  `ROOM_TYPE_TIMEOUTS` (`config_flow.py:1466`),
  `ROOM_TYPE_FEATURE_DEFAULTS` (bathroom-only, 3 keys, `const.py:1546-1556`),
  `wet_default = room_type == BATHROOM` (`:2672`),
  `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` (`:2678`),
  fan-mode default depends on HVAC-zone membership (`:11705`,
  `__init__.py:1786`). **No single defaults table exists — do NOT invent
  one.** The in-use check derives defaults by building the step's real schema.
- **Room fan mode writers** — `_migrate_room_fan_mode`
  (`__init__.py:1765-1790`) writes `CONF_ROOM_FAN_MODE` into every room's
  options; the Select entity writes it too (`select.py:207-209`). Recorded
  because it forces the operator ruling in D3.
- **Options save shape** — `merged = {**options, **user_input}` (e.g.
  `config_flow.py:11946`) — every save persists the full form, so
  default-valued keys end up in `options`. Motivates the collections-non-empty
  rule and Fan-Mode exclusion.
- **Nested `section()` schemas** — climate flattens `humidity_fan_advanced` +
  `climate_backstop` (`:11593-11598`); lighting flattens `reconcile_advanced`
  (`:11359-11363`). The key extraction MUST descend into sections.
- **Sub-steps** — chain_* (`:12213-12231`) and ai_rule_* (`:12310-12476`) sit
  under parents and store `CONF_AUTOMATION_CHAINS` / `CONF_AI_RULES` — their
  keys belong to the parent step in the table.
- **Cross-step keys** — `CONF_ZONE` + `CONF_ROOM_TYPE` in both basic_setup and
  climate; `CONF_WET_ROOM` in climate; `CONF_COVER_TYPE` in devices AND
  options_covers; `CONF_COVERS` (entity list) in **devices**, NOT
  options_covers. The table must OWN each key in exactly one step (the one
  whose visibility should be gated by it).
- **Garage-door guard** — none in room cover automation; `hvac_covers.py:795-800`
  excludes `device_class == garage` but that is HVAC, not room. Justifies
  hiding Covers on garage.

### Prior planning / analysis
- `docs/reviews/code-review/plan_review_room_type_trimmed_menu.md` — the REV 1
  plan review; drove REV 2.
- `docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md` — parent
  arc (ROOM-DIALOGS-USABILITY-SWEEP-1 wording + ROOM-LIGHTING-SETUP-REDESIGN-1
  structure).

### Memory bodies pulled
- `feedback_hollow_test_anchors` — extraction MUST call the step handler, not
  grep source (drives Finding 5's fix).
- `feedback_coincidental_equality_masks_concept_split` (Bug Class #63) — do not
  invent a parallel defaults table.
- `feedback_extend_existing_never_rebuild`, `feedback_config_first_before_code`,
  `feedback_label_style_guide` (for "More settings…").

### Design docs read
- Room dialogs are UX; no coordinator design doc applies.

### Files surveyed
- `config_flow.py:3453-3545` (init menus), `:1439-1836` (wizard path),
  `:3167-3171` (`_get_current`), `:11946` (options save shape), `:11593-11598`
  and `:11359-11363` (section schemas), `:11705` (fan default),
  `:12213-12476` (sub-steps).
- `const.py:437-450` (types), `:1546-1556` (bathroom feature defaults).
- `__init__.py:1765-1790` (fan-mode migration).

### REUSE / BUILD verdict per proposed piece
| Piece | Verdict | Cite |
|---|---|---|
| Room type enum | REUSE | `const.py:437-450` |
| Options menu construction | REUSE (pass filtered list) | `config_flow.py:3528` |
| `CONF_ROOM_TYPE` read | REUSE | `config_flow.py:1465` |
| Merged data+options read | REUSE `_get_current` pattern | `config_flow.py:3167` |
| Per-step defaults | REUSE — build the step's real schema | each `async_step_<step>` |
| Type → visible-steps map | **NEW** — rung-1 constant `ROOM_MENU_STEPS_BY_TYPE` in `const.py`. |
| Step-owner key table | **NEW** — `_STEP_OWNED_KEYS`, built by calling each step handler (with section descent). |
| "In-use" predicate | **NEW** — `_step_has_non_default_values(step, entry, hass)`. |
| "More settings…" menu row | **NEW** — one extra menu key (`show_all_settings`); one-visit reveal via a stateless handler. |

---

## Falsifiable invariant (testable form)

> **For every room entry, every step S in `ROOM_MENU_STEPS_ALL` that has at
> least one owned key whose merged (`{**data, **options}`) value differs from
> the value the step's own schema would render for that entry, appears in the
> `init` menu without the user selecting "More settings…".**

D's job: find a `(room_type, step, entry_state)` triple that stores an
owned-key value diverging from the schema default AND is not shown in the
default menu.

---

## Deliverables

### D1 — Type → steps map (rung-1 module constant)

Add to `const.py` (adjacent to `ROOM_TYPE_*`):

```python
ROOM_MENU_STEPS_ALL: Final = (
    "basic_setup", "sensors", "devices",
    "options_lighting", "options_covers",
    "automation_chaining", "ai_rules",
    "climate", "sleep_protection", "music_following",
    "energy", "notifications",
)

# Per-type visible subset. Lighting shown for EVERY type (operator ruling).
# Covers hidden for garage + utility + infrastructure (no garage-door guard
# in room cover automation; utility/infra don't have covers). "More
# settings…" always reveals the full menu.
ROOM_MENU_STEPS_BY_TYPE: Final = {
    ROOM_TYPE_COMMON_AREA:    ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_BEDROOM:        ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_MEDIA_ROOM:     ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_GENERIC:        ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_BATHROOM:       ("basic_setup", "sensors", "devices",
                               "options_lighting", "options_covers",
                               "climate", "notifications"),
    ROOM_TYPE_GARAGE:         ("basic_setup", "sensors", "devices",
                               "options_lighting",
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

**Covers rationale (REV 2, operator ruling applied):** hidden for garage,
utility, infrastructure. Room cover automation has no `device_class == garage`
exclusion (unlike HVAC covers, `hvac_covers.py:795-800`), so exposing Covers
on garage would invite the operator to attach sunrise-open / timed-close /
exit-cover behaviour to a garage door. Hazard beats convenience; "More
settings…" is still one click away. Card the garage-door guard separately.

### D2 — Filtered menu + in-use reveal + More settings

In `config_flow.py::async_step_init` (else branch, ~line 3528):

```python
room_type = self._config_entry.data.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
visible = list(ROOM_MENU_STEPS_BY_TYPE.get(room_type, ROOM_MENU_STEPS_ALL))
for step in ROOM_MENU_STEPS_ALL:
    if step not in visible and await _step_has_non_default_values(
        self.hass, self._config_entry, step
    ):
        visible.append(step)
visible = [s for s in ROOM_MENU_STEPS_ALL if s in visible]
menu = list(visible)
if visible != list(ROOM_MENU_STEPS_ALL):
    menu.append("show_all_settings")
return self.async_show_menu(step_id="init", menu_options=menu)

async def async_step_show_all_settings(self, user_input=None):
    # One-visit reveal; no persistent flag needed (each open is a fresh
    # OptionsFlow, HA menus have no back-nav).
    return self.async_show_menu(
        step_id="init", menu_options=list(ROOM_MENU_STEPS_ALL)
    )
```

### D3 — `_step_has_non_default_values` (schema-derived, no parallel table)

**Rules (REV 2):**

1. **Merged read.** Evaluate against `merged = {**entry.data, **entry.options}`
   — mirrors `_get_current` (`config_flow.py:3167-3171`). This catches
   legacy rooms whose values live in `entry.data`.
2. **Owned keys only.** For each step S, consult `_STEP_OWNED_KEYS[S]` — the
   set of CONF keys whose visibility should gate S. Cross-step keys
   (`CONF_ROOM_TYPE`, `CONF_ZONE`, `CONF_COVER_TYPE`, `CONF_COVERS`,
   `CONF_ROOM_FAN_MODE`) are OWNED by exactly ONE step (or NONE — see #4).
3. **Per-key comparison.** For each owned key `k`:
   - If `k` is absent from `merged` → not in use.
   - If value is a list/dict → in use iff non-empty.
   - Otherwise → in use iff value differs from the value the step's own
     schema would render as `default=` for this entry (see Extraction below).
4. **Explicit exclusions (operator rulings, REV 2):**
   - `CONF_ROOM_FAN_MODE` — NOT owned by any step. The Select entity
     (`select.py:207-209`) and `_migrate_room_fan_mode`
     (`__init__.py:1765-1790`) write it into options on every room; treating
     it as in-use would un-hide Climate on every closet/utility/infra room
     and defeat the trim. It is dashboard-owned; NM sees it via the Select.
   - `CONF_ROOM_TYPE`, `CONF_ZONE` — always set on every room; not owned by
     climate (which also renders them). Owned by `basic_setup` (which is
     always visible anyway) — effectively excluded from the reveal set.
   - `CONF_COVERS` — owned by `devices` (always visible), NOT
     `options_covers`. `CONF_COVER_TYPE` — owned by `options_covers`.

**Schema-based default extraction (Finding 2 & 5 fix):**

Build `_STEP_OWNED_KEYS` at import time by iterating
`ROOM_MENU_STEPS_ALL`, calling each `async_step_<step>` handler in
inspect-mode against a synthetic empty entry AND against the real entry, and
diffing the resulting `voluptuous.Schema` `defaults`. Concretely:

- Instantiate the OptionsFlow with the real entry.
- For each step, call the handler with `user_input=None`; capture the
  `data_schema` from the returned `FlowResult`.
- Recursively walk `Schema.schema` (dict), descending into any `section()`
  sub-schemas (climate: `humidity_fan_advanced`, `climate_backstop`;
  lighting: `reconcile_advanced`) — collect all `vol.Marker` keys and their
  `default`.
- Compare `merged[k]` against that `default` for each key in
  `_STEP_OWNED_KEYS[step]`.

This automatically absorbs type-aware defaults (`wet_default`,
`ROOM_TYPE_BLE_HOLD_CAP_DEFAULT`, `ROOM_TYPE_TIMEOUTS`, HVAC-zone-derived
fan default) because the step's schema is what gets rendered.

**Owner map construction:** `_STEP_OWNED_KEYS` is the intersection of "keys
this step's schema exposes" and the ownership rules above. The step whose
schema surfaces a key AND for which the trim should reveal it is the owner;
apply the explicit exclusions in #4. The map is asserted at test time
against live step handlers — no source grep.

### D4 — DROPPED (REV 2)

The add-room wizard already runs `room_setup → room_class →
sensors_confirm → devices_confirm → room_summary` (`config_flow.py:1526-1533`).
It walks NONE of the 12 options steps on create, so there is nothing to
filter. Hiding CONF_COVERS **inside** `devices_confirm` for utility /
infrastructure / garage is a **field-level** change and is explicitly out of
scope (non-goal: no hiding fields inside a step). Card separately if wanted.

### D5 — Type change redraws (test only, no code work)

Saving `CONF_ROOM_TYPE` in `basic_setup` (or climate) ends the flow via
`async_create_entry`; the next `init` open re-renders. No deliverable code,
but the acceptance test below MUST cover it.

### D6 — Translations

Add `component.universal_room_automation.options.step.init.menu_options.show_all_settings = "More settings…"` in `translations/en.json` + `strings.json`. No other translation changes.

---

## Non-goals

- No hiding fields inside a step (including CONF_COVERS in `devices_confirm`).
- No behaviour change by type.
- No new entry type.
- No changes to `ROOM_TYPE_FEATURE_DEFAULTS` / `ROOM_TYPE_TIMEOUTS` semantics.
- No migration.
- No zone/house menu changes (separate cards).
- No garage-door guard in room cover automation (card separately).

---

## Acceptance criteria

- **Test — menu snapshot per type:** parametrised over all 10 room types.
  Freshly-created room entry with only defaults: `init` menu equals
  `ROOM_MENU_STEPS_BY_TYPE[type]` + `show_all_settings` (or exactly
  `ROOM_MENU_STEPS_ALL` for the "everything" types, no `show_all_settings`).
- **Test — in-use reveal per step:** for each (type, hidden_step) pair, seed
  one non-default owned-key value; assert the step now appears.
- **Test — legacy `data`-only room (Finding 1):** construct an entry where
  `CONF_POWER_SENSORS` lives in `entry.data` only (not `options`); assert
  Energy reveals on a closet room.
- **Test — Fan-Mode-only room (Finding 3, operator ruling):** entry with
  `CONF_ROOM_FAN_MODE` set in options (any non-default value) and NO other
  Climate keys in use; assert Climate remains HIDDEN on a closet room.
- **Test — More settings reveals all:** selecting `show_all_settings`
  returns a menu with `menu_options == list(ROOM_MENU_STEPS_ALL)`. Next
  `init` open is back to trimmed.
- **Test — hidden step round-trips:** hide a step by type; assert its
  merged values are unchanged after opening + closing the options flow.
- **Test — type change redraws (D5):** change `CONF_ROOM_TYPE`
  bedroom→closet; next `init` menu is the closet trim; a step whose stored
  value differs from the closet schema default reveals via the in-use rule.
- **Test — schema/owner consistency (Finding 5 & 6):** for each step,
  build the schema by calling the step handler (descend into `section()`
  sub-schemas); assert every key in `_STEP_OWNED_KEYS[step]` appears in
  that schema; assert cross-step keys (`CONF_ROOM_TYPE`, `CONF_ZONE`,
  `CONF_COVER_TYPE`, `CONF_COVERS`, `CONF_ROOM_FAN_MODE`) are owned by
  their designated single owner (or by NONE for `CONF_ROOM_FAN_MODE`).
- **Test — invariant guard (falsifiable form):** for every
  (type, step in `ROOM_MENU_STEPS_ALL`) where step is not in the type's
  trim, seed a divergent owned-key value and assert step is visible in the
  default menu.
- **Live — closet room:** open a closet room's options; 5 items + "More
  settings…"; select it; all 12 appear; re-enter; back to 5.
- **Live — garage room:** open a garage room's options; Covers is NOT
  in the default menu; "More settings…" reveals it. No coordinator warns
  about missing config.
- **Live — legacy room:** pick a bathroom or garage room whose energy /
  notifications values live in `entry.data`; confirm those steps are
  revealed (or gated correctly) without the operator selecting More.

---

## Files touched

- `custom_components/universal_room_automation/const.py` — add
  `ROOM_MENU_STEPS_ALL`, `ROOM_MENU_STEPS_BY_TYPE`.
- `custom_components/universal_room_automation/config_flow.py` — modify
  `async_step_init` (else branch); add `_step_has_non_default_values`,
  `_STEP_OWNED_KEYS` build helper, `async_step_show_all_settings`.
- `custom_components/universal_room_automation/translations/en.json` +
  `strings.json` — add `show_all_settings` label.
- `quality/tests/config_flow/test_room_menu_trim.py` — new test file.

---

## Tier & review plan

- **Tier 2** (menu construction across every room entry; correctness of the
  in-use predicate is load-bearing).
- **Plan review:** DONE (REV 1 review applied here as REV 2).
- **Build reviews (two, framing-disjoint):**
  A = correctness + edge cases (merged-read semantics, section descent,
  list/dict/bool/scalar branches, owned-key exclusions, garage/utility trim);
  B = UX + lifecycle (menu re-entry, type-change redraw, translation
  completeness, ordering, coexistence with the ROOM-LIGHTING-SETUP-REDESIGN-1
  Lighting step landing first).
- **Deploy HELD** for operator sign-off (Covers-hide-on-garage +
  Fan-Mode-not-in-use rulings baked into REV 2).

---

## Sequencing

**After** `feature/room-lighting-roles` slices B'/C/D land on develop. The
schema-derived key table (D3) picks up the reshaped Lighting step
automatically; sequencing before the reshape would force a rebuild of the
consistency test.

## Operator decisions applied (default) — flagged for confirmation

1. **`CONF_ROOM_FAN_MODE` does NOT count as in-use.** Written by
   `_migrate_room_fan_mode` (`__init__.py:1765-1790`) and the Select entity
   (`select.py:207-209`) on every room; treating it as in-use would un-hide
   Climate everywhere. Excluded from `_STEP_OWNED_KEYS`.
2. **Covers hidden for garage** as well as utility + infrastructure. Room
   cover automation lacks a `device_class == garage` guard (unlike
   `hvac_covers.py:795-800`). Card a garage-door guard separately.

If either decision reverses, the change is one-line each
(add `CONF_ROOM_FAN_MODE` to `_STEP_OWNED_KEYS["climate"]`; add
`"options_covers"` back into the garage tuple).
