# PLANNING — ROOM-TYPE-TRIMMED-MENU-1 (REV 4)

**Card:** `ROOM-TYPE-TRIMMED-MENU-1` (kanban.data.yaml:30597)
**Tier:** **2** (see "Tier & review plan" — room options flow only; UI-only,
no runtime behaviour change; the load-bearing risk is a stored value becoming
unreachable or being dropped on save, which is guarded by tests).
**Author:** ura-planner, 2026-09-29; REV 4 2026-10-02
**Deploy:** HELD for operator.

## Revision history
- **REV 1** (2026-09-29) — initial plan.
- **REV 2** (2026-09-29) — applied `docs/reviews/code-review/plan_review_room_type_trimmed_menu.md`
  (merged data+options read; schema-derived defaults; D4 dropped; owner table
  built by calling handlers; cross-step key ownership; Fan Mode not in-use;
  Covers hidden on garage).
- **REV 3 / 3.1** (operator 2026-09-30) — banners adding Simple/Advanced for
  every flow + required plain-words Advanced-mode hint.
- **REV 4** (2026-10-02, this file) — applies "Plan review REV 3.1 findings"
  (bottom). Decisions: Simple/Advanced is specified **for the ROOM options flow
  only** (D7-D9); zone/house/coordinator classification PARKED (see "Parked
  follow-on"). Fixes: Lighting step key is `options_lighting_behaviour`
  (F1); Advanced mode ⇒ full menu, no "More settings…" (F3); markers must go
  through `add_suggested_values_to_schema` (F4); extraction runs with Advanced
  ON (F5); hint REUSES `lighting_advanced_hint` generalised (F6); simple-mode
  save guard per marked step (F7); cites refreshed + sequencing satisfied
  (F8); Live rows updated (F9).

---

## Institutional context verified

### Greps run (against develop, 2026-10-02)
- **Room type constants** — `const.py:437-450` — REUSED: 10 types.
- **Live room options menu** — `config_flow.py:3587-3605` — 12 entries:
  `basic_setup, sensors, devices, options_lighting_behaviour, options_covers,
  automation_chaining, ai_rules, climate, sleep_protection, music_following,
  energy, notifications`. `async_step_options_lighting` still exists as a
  handler but is NOT a menu entry — it is NOT in this plan's step list.
- **Merged read** — `_get_current` `config_flow.py:3228` — REUSED pattern.
- **Add-room wizard** — `devices_confirm` `:1778`, `room_summary` `:1840`;
  creates walk no options steps → D4 stays dropped.
- **Room options step handlers** — `basic_setup :10571`, `sensors :10793`,
  `devices :11277`, `options_lighting_behaviour :11554` (schema = its own
  fields + `_lighting_basics_fields()` `:11438`, which contains section
  `reconcile_advanced :11500`; plus section `auto_manual_devices :11820`;
  advanced-marked fields `:11666-11815`; schema routed via
  `add_suggested_values_to_schema :11846`; save flattens both sections
  `:11601-11606`), `options_covers :11865`, `climate :11992` (sections
  `humidity_fan_advanced :12215`, `climate_backstop :12254`),
  `sleep_protection :12343`, `music_following :12403`, `energy :12450`,
  `notifications :12493`, `automation_chaining :12602`, `ai_rules :12701`.
- **Advanced-mode hint (shipped, Slice E v5.103.29)** —
  `LIGHTING_ADVANCED_HINT_HIDDEN/_SHOWN` + `lighting_advanced_hint()`
  `config_flow.py:42-64`, consumed at `:11853` as `{advanced_hint}`
  placeholder (`strings.json:2112`). Profile path ("click your name at the
  bottom left -> Advanced mode") already verified against the installed
  frontend in that comment. REUSED + generalised (D8).
- **Simple-mode save guard (shipped)** — Lighting `clearable` list only
  extends to advanced keys when `self.show_advanced_options` (`:11611-11624`).
  REUSED pattern (D8).
- **HA semantics** — `homeassistant/data_entry_flow.py:645-667`:
  `show_advanced_options` comes from flow context; the advanced-key filter is
  applied inside `add_suggested_values_to_schema`, NOT by `async_show_form`.
- **Per-type defaults (scattered)** — `ROOM_TYPE_TIMEOUTS`,
  `ROOM_TYPE_FEATURE_DEFAULTS` (`const.py:1546-1556`), `wet_default`,
  `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT`, HVAC-zone fan default. No new defaults
  table (Bug Class #63) — defaults come from the rendered schema.
- **Fan mode writers** — `_migrate_room_fan_mode` (`__init__.py:1765-1790`),
  Select (`select.py:207-209`).
- **Garage guard** — none in room covers; `hvac_covers.py:795-800` is HVAC only.

### Prior planning / analysis
- `docs/reviews/code-review/plan_review_room_type_trimmed_menu.md` (REV 1 review).
- `docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md` — parent
  arc; Slices B'/C/D/E landed (v5.103.28-.29) → **sequencing precondition MET**.

### Memory bodies pulled
- `feedback_hollow_test_anchors`, `feedback_coincidental_equality_masks_concept_split`,
  `feedback_extend_existing_never_rebuild`, `feedback_config_first_before_code`,
  `feedback_label_style_guide`, `feedback_configurability_clarity`.

### Config-first
No setting produces a trimmed menu; HA Advanced mode exists but URA's room
steps (except Lighting) mark nothing advanced. Code is required.

### REUSE / BUILD verdict
| Piece | Verdict | Cite |
|---|---|---|
| Room type enum | REUSE | `const.py:437-450` |
| Menu construction | REUSE (filtered list) | `config_flow.py:3589` |
| Merged read | REUSE `_get_current` pattern | `config_flow.py:3228` |
| Per-step defaults | REUSE — render the step's real schema | each handler |
| Advanced filter | REUSE HA `add_suggested_values_to_schema` | `:11846`, HA `data_entry_flow.py:650-667` |
| Hint text | REUSE + generalise `lighting_advanced_hint` | `config_flow.py:42-64` |
| Simple-mode save guard | REUSE Lighting `clearable` pattern | `:11611-11624` |
| Type→steps map | NEW `ROOM_MENU_STEPS_BY_TYPE` (rung 1, const.py) | — |
| Owner key table | NEW `_STEP_OWNED_KEYS`, built by calling handlers | — |
| In-use predicate | NEW `_step_has_non_default_values` | — |
| "More settings…" row | NEW `show_all_settings` | — |

---

## Falsifiable invariants

**I1 (no hidden step holds a value — Simple mode).** For every room entry
and every step S in `ROOM_MENU_STEPS_ALL`: if any key owned by S has a merged
(`{**data, **options}`) value that differs from the default S's schema renders
for that entry (schema built with Advanced ON), then S appears in the `init`
menu in Simple mode without selecting "More settings…".

**I2 (no stored value is unreachable).** For every room entry, every key with
a non-default stored value is rendered by some step that is in the Simple-mode
default menu (directly or via I1) — **and** if that key is an advanced-marked
field, it is rendered on that step **even in Simple mode** (the marker is
dropped for that render). In Advanced mode every step and every field is
rendered.

D's job: find a `(room_type, step, key, value, advanced_on)` tuple where a
non-default stored value is not on any form the user can reach.

**I3 (no silent drop on save).** A Simple-mode save of any step leaves every
stored value of a field not rendered on that form unchanged.

---

## Deliverables

### D1 — Type → steps map (rung-1 constant, `const.py`)

```python
ROOM_MENU_STEPS_ALL: Final = (
    "basic_setup", "sensors", "devices",
    "options_lighting_behaviour", "options_covers",
    "automation_chaining", "ai_rules",
    "climate", "sleep_protection", "music_following",
    "energy", "notifications",
)
_CORE = ("basic_setup", "sensors", "devices", "options_lighting_behaviour")
ROOM_MENU_STEPS_BY_TYPE: Final = {
    ROOM_TYPE_COMMON_AREA:    ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_BEDROOM:        ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_MEDIA_ROOM:     ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_GENERIC:        ROOM_MENU_STEPS_ALL,
    ROOM_TYPE_BATHROOM:       _CORE + ("options_covers", "climate", "notifications"),
    ROOM_TYPE_GARAGE:         _CORE + ("energy", "notifications"),
    ROOM_TYPE_INFRASTRUCTURE: _CORE + ("climate", "energy", "notifications"),
    ROOM_TYPE_CLOSET:         _CORE + ("options_covers",),
    ROOM_TYPE_HALLWAY:        _CORE + ("options_covers",),
    ROOM_TYPE_UTILITY:        _CORE,
}
```
Lighting shown for every type. Covers hidden for garage/utility/infrastructure
(no garage-door guard in room covers). Rendered menu order always follows
`ROOM_MENU_STEPS_ALL`.

### D2 — Menu construction (`async_step_init`, room branch `:3587`)

```python
if self.show_advanced_options:
    menu = list(ROOM_MENU_STEPS_ALL)            # Advanced mode = full menu
else:
    room_type = merged.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)   # merged read
    visible = set(ROOM_MENU_STEPS_BY_TYPE.get(room_type, ROOM_MENU_STEPS_ALL))
    for step in ROOM_MENU_STEPS_ALL:
        if step not in visible and await self._step_has_non_default_values(step):
            visible.add(step)
    menu = [s for s in ROOM_MENU_STEPS_ALL if s in visible]
    if len(menu) != len(ROOM_MENU_STEPS_ALL):
        menu.append("show_all_settings")
return self.async_show_menu(step_id="init", menu_options=menu,
    description_placeholders={"menu_hint": room_menu_hint(...)})

async def async_step_show_all_settings(self, user_input=None):
    return self.async_show_menu(step_id="init",
        menu_options=list(ROOM_MENU_STEPS_ALL),
        description_placeholders={"menu_hint": advanced_hint(self.show_advanced_options)})
```
**Advanced mode vs "More settings…" (F3):** Advanced mode ON ⇒ full menu,
`show_all_settings` omitted. "More settings…" is kept for Simple-mode users
as a one-visit reveal of hidden *steps*; it does NOT reveal advanced *fields*
(only Advanced mode, or I2's forced render, does). Rationale: many users never
enable Advanced mode; one click to reach a hidden step is cheaper than a
profile trip. Room type read uses merged data+options.

### D3 — `_step_has_non_default_values(step)` (schema-derived)

1. Read `merged = {**entry.data, **entry.options}`.
2. Owned keys only: `_STEP_OWNED_KEYS[step]`.
3. Per key: absent → not in use; list/dict → in use iff non-empty; scalar →
   in use iff `!=` the **factory default** for this entry (see Extraction —
   NOT the live schema's `default`, which every room handler sets to the
   stored value via `self._get_current(KEY, FALLBACK)`, e.g. covers
   `:11920-11982`; comparing against it would make every key "default").
4. Exclusions (operator rulings, unchanged): `CONF_ROOM_FAN_MODE` owned by no
   step; `CONF_ROOM_TYPE`, `CONF_ZONE` owned by `basic_setup`; `CONF_COVERS`
   owned by `devices`; `CONF_COVER_TYPE` owned by `options_covers`;
   `CONF_WET_ROOM` owned by `climate`.

**Extraction (F5, REV 4 re-check R1):** helper `_render_step_schema(step)`
calls the step handler with `user_input=None` on a **separate shim flow
instance** (never the live flow — do not toggle the live flow's context)
whose context has `show_advanced_options=True` and whose `_config_entry`
is a stub with `data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_TYPE:
<merged room type>}`, `options={}`, `entry_id` = the real entry's id. Every
`_get_current(KEY, FALLBACK)` / `_cur(...)` then returns FALLBACK, so the
rendered `default`s are the **factory defaults** for that room type
(type-aware fallbacks like `wet_default` `:12088` key off room type and are
absorbed). The same factory-default map feeds `_adv` (D8.2). It takes the returned `data_schema`, and walks it
recursively, descending into `section()` sub-schemas (`reconcile_advanced`,
`auto_manual_devices`, `humidity_fan_advanced`, `climate_backstop`),
collecting `(key, default)`. Owned keys of `options_lighting_behaviour`
include `_lighting_basics_fields()` (`:11438`, incl. `reconcile_advanced`) and
`auto_manual_devices`. Type-aware defaults are absorbed automatically.
Extraction runs at menu-open only for steps NOT already visible (≤ 8 renders;
no import-time build — handlers need `hass` + entry). Handlers must be
side-effect free on `user_input=None` — covered by the purity test.

### D4 — DROPPED (REV 2; wizard walks no options steps).

### D5 — Type change redraws (test only).

### D6 — Translations
`options.step.init.menu_options.show_all_settings = "More settings…"`;
`options.step.init.description` gains `{menu_hint}`; covers + climate step
descriptions gain `{advanced_hint}`. `strings.json` + `translations/en.json`.

### D7 — Room-flow field classification (Simple / Folded / Advanced)

Classes: **Simple** = shown always. **Folded** = existing collapsed
`section()` (visible, one click) — unchanged. **Advanced** = marked
`description={"advanced": True}`, shown only in Advanced mode (or forced by I2).

Rule: entity pickers, on/off feature switches, and anything most rooms of
that type need → Simple. Pure tuning numbers/offsets whose default is right
for most rooms → Advanced. Nothing inside an existing section moves.

| Step | Simple | Folded (existing, unchanged) | Advanced |
|---|---|---|---|
| basic_setup | all | — | none |
| sensors | all | — | none |
| devices | all | — | none |
| options_lighting_behaviour | basics + role pickers | `reconcile_advanced`, `auto_manual_devices` | already marked `:11666-11815` (manual-hold windows, evening brightness/colour, scenes) — unchanged except routed via `_adv` |
| options_covers | `CONF_COVER_TYPE`, `CONF_COVER_OPEN_MODE`, `CONF_COVER_OPEN_TIME_SOURCE`, `CONF_COVER_OPEN_HOUR`, `CONF_EXIT_COVER_ACTION`, `CONF_TIMED_CLOSE_ENABLED`, `CONF_COVER_CLOSE_TIME_SOURCE`, `CONF_COVER_CLOSE_HOUR`, `CONF_COVER_HVAC_MANAGED` | — | NEW: `CONF_SUNRISE_OFFSET`, `CONF_SUNSET_OFFSET` |
| climate | entity/feature fields, `CONF_WET_ROOM`, `CONF_FAN_TEMP_THRESHOLD`, `CONF_HUMIDITY_FAN_THRESHOLD`, `CONF_HUMIDITY_FAN_TIMEOUT` | `humidity_fan_advanced`, `climate_backstop` | NEW: `CONF_FAN_SPEED_LOW_TEMP`, `CONF_FAN_SPEED_MED_TEMP`, `CONF_FAN_SPEED_HIGH_TEMP`, `CONF_HUMIDITY_FAN_MAX_RUNTIME` |
| sleep_protection | all | — | none |
| music_following | all | — | none |
| energy | all | — | none |
| notifications | all | — | none |
| automation_chaining / ai_rules | all (list editors) | — | none |

Builder obligation: the classification test renders each step with Advanced
ON and asserts every NEW Advanced key is present at top level of that step's
schema (not inside a section). A key not found is a plan defect → stop and
report; do not substitute. Hour fields stay Simple — they are only used with
a fixed-time source the user just chose.

### D8 — Markers, hint, save guard

For `options_covers` and `climate` (gaining markers) and
`options_lighting_behaviour` (existing markers):
1. **Route through `add_suggested_values_to_schema` (F4)** with the merged
   current values, as Lighting does (`:11846`). Covers + climate gain this.
2. **I2 forced render:** shared helper `_adv(key, merged, default)` returns
   `{"advanced": True}` only if the merged value is absent or equals the
   factory default (the D3 shim render / the handler's `_get_current`
   FALLBACK constant — never the live schema default, which is the stored
   value); a non-default stored value renders unmarked. Used for every
   Advanced key in all three steps (Lighting's literal markers converted).
3. **Hint (F6):** rename `lighting_advanced_hint` → `advanced_hint(show)` and
   `LIGHTING_ADVANCED_HINT_*` → `ADVANCED_HINT_*`, updating existing Lighting
   test imports in the same commit (no aliases). Text unchanged and already
   verified: Simple → "Some rarely-used settings are hidden. To show them,
   turn on Advanced mode in your HA profile (click your name at the bottom
   left -> Advanced mode). Hidden settings keep working."; Advanced →
   "Advanced settings shown." New `room_menu_hint(room_type_label, trimmed,
   show_advanced)`: trimmed + Simple → "Showing the settings {type} rooms
   usually need. Pick More settings for the rest. " + Simple hint; untrimmed
   + Simple → Simple hint; Advanced ON → "Advanced settings shown."
   **Non-translatable by choice** (Python constants via placeholders, matching
   the shipped Lighting pattern); no translation follow-on carded.
4. **Save guard (F7):** in covers + climate save paths, any clear-on-omit
   logic touching Advanced keys runs only when `self.show_advanced_options`
   (Lighting pattern `:11612`). Where no clear-on-omit exists, the
   `{**options, **user_input}` merge already preserves omitted keys; the I3
   test still covers it.

### D9 — Tests
`quality/tests/test_room_menu_trim.py` (D1-D3, D5, D6) and
`quality/tests/test_room_advanced_fields.py` (D7-D8). Cases in
Acceptance criteria.

---

## Non-goals
- No zone / house / coordinator-manager / integration flow changes (PARKED below).
- No hiding of fields inside a step other than D7's Advanced column.
- No change to existing `section()` groupings.
- No runtime behaviour change; no migration; no garage-door guard (card separately).
- No hiding `CONF_COVERS` in `devices_confirm`.

---

## Acceptance criteria

- **Test — menu snapshot per type (Simple):** 10 types, default-only entry →
  `ROOM_MENU_STEPS_BY_TYPE[type]` (+ `show_all_settings` iff trimmed);
  `menu_hint` contains "Advanced mode" for every type.
- **Test — Advanced mode full menu:** same 10 entries with
  `show_advanced_options=True` → exactly `ROOM_MENU_STEPS_ALL`, no
  `show_all_settings`, `menu_hint == "Advanced settings shown."`.
- **Test — in-use reveal (I1):** every (type, hidden step) pair, seed one
  divergent owned key → step visible in Simple menu.
- **Test — legacy data-only room:** `CONF_POWER_SENSORS` in `data` only on a
  closet → Energy revealed; `CONF_ROOM_TYPE` in `data` only → correct trim.
- **Test — Fan-Mode-only room:** closet with only `CONF_ROOM_FAN_MODE` →
  Climate hidden.
- **Test — More settings:** returns full menu; next `init` is trimmed again.
- **Test — owner/schema consistency:** each step rendered with Advanced ON
  (section descent) contains every `_STEP_OWNED_KEYS[step]` key; cross-step
  owners as D3; Lighting owner set includes `_lighting_basics_fields()` keys
  and both sections' keys; `"options_lighting"` appears in no table.
- **Test — handler purity:** rendering every step with `user_input=None`
  leaves `entry.data` / `entry.options` identical.
- **Test — classification (F4):** every D7 Advanced key appears in its
  step's Advanced-ON schema and is ABSENT from the Simple-mode rendered
  schema when its stored value is default.
- **Test — I2 forced render:** for each D7 Advanced key, store a non-default
  value → Simple-mode render of its step contains the key.
- **Test — I2 global:** per room type, seed every owned key of every step
  with a non-default value; union of keys rendered across Simple-mode menu
  steps ⊇ all seeded keys.
- **Test — I3 save guard:** for covers / climate / lighting, store an Advanced
  key explicitly at its default value (so it is hidden in Simple mode), submit
  the step in Simple mode without it → stored value still present and
  unchanged. Mutation drill: remove the `show_advanced_options` gate on the
  clearable list → this test fails.
- **Test — hint per step:** covers / climate / lighting
  `description_placeholders["advanced_hint"]` is the hidden variant in Simple
  and "Advanced settings shown." in Advanced. Meta-test: every room step whose
  Advanced-ON schema has a key absent from its Simple schema passes
  `advanced_hint`, and its description string contains `{advanced_hint}`.
- **Test — type change redraws (D5):** bedroom→closet → closet trim; a
  divergent value reveals its step.
- **Live — closet (Simple):** 5 items (Basic, Sensors, Devices, Lighting,
  Covers) + "More settings…"; hint line names the room type and explains
  Profile → Advanced mode; More → 12; re-open → 5.
- **Live — Advanced mode ON (Profile → Advanced mode):** same closet → 12
  items, "Advanced settings shown."; Climate shows fan-speed temps; Covers
  shows sunrise/sunset offsets.
- **Live — garage:** Covers not in Simple menu; More reveals it.
- **Live — legacy room:** a room with energy/notification values only in
  `entry.data` shows those steps without More.

---

## Files touched
- `custom_components/universal_room_automation/const.py` — `ROOM_MENU_STEPS_ALL`, `ROOM_MENU_STEPS_BY_TYPE`.
- `custom_components/universal_room_automation/config_flow.py` — room branch
  of `async_step_init` (`:3587`); `async_step_show_all_settings`;
  `_step_has_non_default_values`, `_render_step_schema`, `_STEP_OWNED_KEYS`
  rules; `advanced_hint` (rename of `:58`) + `room_menu_hint`; `_adv`;
  `async_step_options_covers` (`:11865`) and `async_step_climate` (`:11992`):
  markers + `add_suggested_values_to_schema` + save guard + hint;
  `async_step_options_lighting_behaviour` (`:11554`): markers via `_adv`.
- `strings.json` + `translations/en.json` — D6 keys.
- `quality/tests/test_room_menu_trim.py`,
  `quality/tests/test_room_advanced_fields.py` — new.
- Existing Lighting hint tests — import rename.

---

## Tier & review plan
- **Tier 2.** Room options flow only, UI surface, no runtime behaviour. The
  REV 3 all-flows scope (which would have pushed this to 2-DB) is parked.
- **Plan review:** REV 4 needs ONE re-check against the findings table below.
- **Build reviews (two, disjoint):** A = correctness + edge cases (merged
  read, section descent, I1/I2 per type, scalar/list/dict branches,
  exclusions, `_adv` forced render); B = UX + lifecycle + save paths (I3
  guard, menu re-entry, Advanced-mode toggled between opens, hint text,
  translations, handler purity).
- **Deploy HELD** for operator.

## Sequencing
Precondition (lighting slices B'/C/D/E on develop, v5.103.28-.29) — **MET**.

## Operator decisions applied — flagged for confirmation
1. `CONF_ROOM_FAN_MODE` not in-use.
2. Covers hidden on garage (+ utility, infrastructure).
3. (REV 4) Advanced mode ON ⇒ full menu; "More settings…" kept for Simple.
4. (REV 4) A non-default advanced field renders in Simple mode (I2) instead
   of relying on the hint alone — chosen over the reviewer's "hint covers it"
   because the operator required "no stored value unreachable".
5. (REV 4) D7 adds only 6 new Advanced keys; widen later by observation.

---

## Parked follow-on — Simple/Advanced for zone, house, coordinator flows

**Parked from REV 3.** Classify + mark fields in the zone, house/integration
and coordinator-manager options flows (~600 `vol.Optional/Required` in
`config_flow.py`; many already folded in sections, e.g. `presence_timing
:6616`, `advanced :6962`, `optimizer_guards :8913`, `optimizer_llm :8916`,
`fan_recheck_advanced :4391`). Reuses D8's `_adv`, `advanced_hint`,
`add_suggested_values_to_schema` routing, save guard and I2/I3 test pattern.
**Revisit trigger:** this card ships AND an operator zone/house dialog
cleanup card enters planning — fold that flow's classification into its plan
rather than one sweep. Likely Tier 2-DB per coordinator flow (cost/safety
knobs). Record as an adjacency note on those cards, not a new card, unless no
such card exists at revisit time.

---

## Plan review REV 3.1 findings (ura-reviewer, 2026-10-02, against develop e9cd1bc03) — **REV 4 — re-checked (see below)**

| # | Sev | Finding | REV 4 resolution |
|---|---|---|---|
| 1 | HIGH | Stale step key `options_lighting`. | All tables/tests/Live use `options_lighting_behaviour`; owner set includes `_lighting_basics_fields()` (incl. `reconcile_advanced`) + `auto_manual_devices`; test asserts `options_lighting` absent. |
| 2 | HIGH | REV 3/3.1 only banners. | Room flow fully specified (I2/I3, D7 table, D8, D9, files, Tier 2); zone/house/CM parked with trigger. |
| 3 | HIGH | Advanced vs More settings undefined; advanced fields outside invariant. | D2: Advanced ON ⇒ full menu, More omitted; I2 forced render covers fields; tests added. |
| 4 | MED | Markers need `add_suggested_values_to_schema`. | D8.1 + classification test asserts absence in Simple render. |
| 5 | MED | Extraction in simple mode misses keys. | D3 `_render_step_schema` uses `show_advanced_options=True`. |
| 6 | MED | Hint duplicative. | REUSE + rename `lighting_advanced_hint` → `advanced_hint`; placeholders; non-translatable noted; meta-test. |
| 7 | MED | Simple-mode save clearing. | D8.4 + I3 test with mutation drill. |
| 8 | LOW | Stale cites; sequencing met. | Refreshed; sequencing MET. |
| 9 | LOW | Live rows. | Closet / Advanced-ON / garage / legacy rows updated. |

---

## Plan review REV 4 (ura-reviewer, 2026-10-02, against develop bbe9cfff0)

**Prior findings 1-9: all resolved, checked with greps.** Step key `options_lighting_behaviour` is at `config_flow.py:3595`, and `options_lighting` is only a handler (`:11516`), not a menu entry (F1). Zone/house/CM work is parked with a trigger (F2). D2 sets Advanced ⇒ full menu (F3). HA's `add_suggested_values_to_schema` drops advanced keys with no conditions (`data_entry_flow.py:661-665`), so routing through it plus the `_adv` forced render is correct (F4). Extraction runs with Advanced ON (F5). The hint helper and constants are at `:50-63`, and the tests that use them are in `quality/tests/test_lighting_slice_e_slots_scenes.py:306-327`, so the rename list is complete (F6). The save guard pattern is at `:11612` (F7). Cites are refreshed (F8) and the Live rows are present (F9).

**D7 field table:** every field it names is real and in the stated step. All 9 Simple and both NEW Advanced covers keys are top-level in `async_step_options_covers` (`:11920-11982`). Climate's `CONF_FAN_SPEED_{LOW,MED,HIGH}_TEMP` and `CONF_HUMIDITY_FAN_MAX_RUNTIME` are top-level, before the `humidity_fan_advanced` section (`~:12180-12214`). Both sections exist at the stated lines.

| # | Sev | Finding | Fix |
|---|---|---|---|
| R1 | CRITICAL | D3 compared the stored value with "the schema's `default`". Every room handler builds `default=self._get_current(KEY, FALLBACK)`, so that default IS the stored value (covers `:11920-11982`, climate `:12175-12214`, Lighting `_cur` `:11572-11575`). Every key would read "default", no hidden step would ever be revealed, I1 would fail for any seeded value, and `_adv` would mark every non-default field hidden, which breaks I2. | **Fixed in plan.** D3 now uses a factory-default render on a separate shim flow whose stub `_config_entry` carries only entry type + room type. Every `_get_current` returns FALLBACK. `_adv` (D8.2) uses the same factory-default source, and the live flow's context is never toggled. The existing "in-use reveal (I1)" and "I2 forced render" tests discriminate: under the R1 bug they fail. |
| R2 | LOW | Test path `quality/tests/config_flow/` does not exist. Tests are flat under `quality/tests/`. | **Fixed:** paths changed to `quality/tests/test_room_menu_trim.py` and `quality/tests/test_room_advanced_fields.py`. |
| R3 | LOW | The hint consumer is at `:11854`, not `:11853`. | Cosmetic, left as is. |

**Invariants:** I1-I3 can be tested and falsified. The I1/I2/I3 acceptance tests can tell a correct build from the R1 failure and from a dropped save guard (the mutation drill is named).

**Verdict: BUILD-READY** (R1 and R2 fixed in plan). Builder note: the shim render must not cause side effects (the purity test covers `entry.data`/`options`). The climate handler reads `room_in_hvac_zone(self.hass, entry_id)`, so the shim must carry the real `hass` and `entry_id`.
