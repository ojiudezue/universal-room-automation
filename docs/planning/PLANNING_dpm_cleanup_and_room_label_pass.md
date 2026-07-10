# PLANNING — DPM Form Cleanup + Room-Form Label De-Jargoning

**Date:** 2026-07-10
**Branch:** develop (post-v5.11.0)
**Proposed version:** two-part cycle (single deploy)
**Tier proposal:** Tier 2 (two framing-disjoint reviews + live spot-check)

---

## Cycle intent (verbatim operator directives)

- Part 1 (2026-07-10 re-audit): the vestigial DPM bucket-range surface is still
  wired through strings.json / MIRROR_KEYS / voluptuous schema call sites even
  though v4.7.17.2 (median-driven DPM) and v4.7.18 D1 (schema-strip) already
  removed the runtime path. **Remove the vestigial surface end-to-end. Keep
  CONF constants for backward-compat restore; keep `classify_bucket()`
  diagnostic labelling working.**
- Part 2 (2026-07-10, verbatim): *"make room form labels — config flow,
  reconfig, room device — more user friendly, no nerd language."*

---

## Institutional context verified

### Prior-art surfaces greped

1. **`config_flow.py:444-466`** — `MIRROR_KEYS_ZONE_DPM` still lists the 17
   vestigial keys (`customize_buckets` + 16 bucket cells) alongside the 4
   active ones. Mirror still fires them across siblings on save.
2. **`config_flow.py:7132-7328`** (`async_step_zone_dynamic_preset` +
   `_build_dynamic_preset_schema`) — VERIFIED: v4.7.18 D1 already strips
   the 17 fields from the rendered schema (only the first 4 `conf_keys`
   are read; trailing 17 are ignored positional args). **So the FORM is
   already clean** — what remains vestigial is:
   - The 21 imports at `config_flow.py:7176-7192`
   - The 17 positional args at the render call site `:7252-7260`
   - The 17 keys in `MIRROR_KEYS_ZONE_DPM` (:449-465)
   - The 32 strings entries (labels + `data_description`) in
     `strings.json:608-645` and `translations/en.json:608-645`
   - This CORRECTS the operator's re-audit note: the fields are gone
     from `config_flow.py ~445-460` schema-render; the range 444-466 is
     the MIRROR_KEYS set, not the form schema.
3. **`domain_coordinators/energy_const.py:368-386`** —
   `CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS` + 16 bucket CONF
   constants. **KEEP** (backward-compat, options-dict restore, and
   `classify_bucket()` still reads its OWN args at
   `dynamic_preset.py:713` — a separate DPM-internal knob layer, not the
   per-zone bucket cells).
4. **`domain_coordinators/dynamic_preset.py:237, 629, 713`** —
   `classify_bucket(delta, cool_max, mild_max, hot_max)` fed by
   `dpm_cool_day_relax_f` / `dpm_hot_day_tighten_f` and DPM's own
   climate-norm math (v4.7.17.2 simplified frame). The classifier does
   NOT read the per-zone `zone_dynamic_preset_*_low/high` values — its
   thresholds come from DPM globals. Removal is safe.
5. **`docs/planning/PLANNING_v4.7.17.2_dpm_simplified_operator_frame.md`
   + `PLANNING_v4.7.18_dpm_drift_guard_and_cleanup.md`** — v4.7.18 D1
   note ("bucket cells remain in entry.options — data preserved,
   strip is UI-only"). Part 1 of THIS cycle completes what D1 left in
   place: the labels, mirror, and imports.
6. **`docs/readmes/README_v4.7.17.2.md` + `README_v4.7.18.md`** —
   confirm the two operator knobs `CONF_DPM_COOL_DAY_RELAX_F` and
   `CONF_DPM_HOT_DAY_TIGHTEN_F` (energy_const.py) are the surviving
   operator-facing DPM controls.
7. **`v4.7.6.1` cycle memory (`project_v4761_live.md`)** — Labels +
   Helper Text + `excess_solar_soc` Number promotion. Prior art for
   label-clarity work: labels/helper text are additive, non-behavioural,
   review-light BUT strings.json/en.json parity is load-bearing.
8. **`v4.7.25` cycle memory (`project_v4_7_25_hvac_presence_timer_knobs_live.md`)**
   — Prior art for collapsed config-flow sections and helper-text
   discipline (`presence_timing` section).
9. **`v5.10.0` cycle** — hit a strings/en.json parity gap; note MEMORY
   entry that "parity test only checks keys not values" so both files
   must be updated together, and value edits are builder-discipline, not
   test-caught. This is called out explicitly in the acceptance criteria
   for Part 2.
10. **`quality/tests/test_v4_7_18_dpm_drift_guard.py`,
    `test_v4_7_17_2_dpm_simplified_frame.py`, `test_v474_dpm_ui.py`,
    `test_v47x_dynamic_preset.py`** — pre-existing DPM test authority.
    Any AST-lock referencing the 17 vestigial keys must be relaxed or
    replaced by an equivalent absence-lock.

### Room-facing surface inventory (Part 2)

Room-facing config-flow / options steps (verified `strings.json` +
`config_flow.py`):

| Step | Fields (data keys, approx.) |
|---|---|
| `room_setup` | 9 (room_name, room_type, area_id, zone, shared_space, shared_space_auto_off_hour, shared_space_warning, occupancy_timeout, occupancy_debounce) |
| `sensors` | 14 (motion_sensors, presence_sensors, occupancy_sensors, scanner_areas, disable_camera_presence, temperature/humidity/illuminance, door/window/is_egress_window, water_leak, door_type) |
| `devices` | ~10 (lights, night_lights, fans, humidity_fans, covers, auto/manual_switches, auto/manual_devices, light_capabilities) |
| `night_light_detail` | 4 |
| `cover_behavior` | 12 |
| `automation_behavior` | 6 |
| `init_automation_chaining` + chain_* | ~20 across 4 sub-steps |
| `init_ai_rules` / `init_ai_rule_add` | 3 |
| `climate` (+ humidity_fan_advanced + climate_backstop sections) | 17 |
| `fan_speeds` | 3 |
| `sleep_protection` | ~10 |
| `automation` / others (skipped scan) | ~15 |

**Estimated total labels + helper-text strings to touch:** 130–160
`data`/`data_description` pairs, split across ~15 room steps. `strings.json`
has **146 `data`/`data_description` sections total** (integration-wide);
audit filters to only the room-facing ones.

Room-device entity `_attr_name` audit (sensor.py, number.py, switch.py):
most are already plain (`Persons In House`, `House State`, `Egress Paused
Zones`). Numbered prefixes (`47 · Zone Entry Dwell`, `03 · Dynamic Preset
Dwell`, `04 · Dynamic Preset Hysteresis`) are the jargon carriers.
"Hysteresis" and "Dwell" are the two nerd words that leaked into visible
entity names.

---

## Falsifiable invariant (Part 1)

**No operator-visible knob or persisted key referring to the vestigial
DPM bucket surface remains AFTER this cycle. Existing entry.options rows
carrying those keys survive HA restart unchanged (data-safe strip),
and DPM runtime behavior is byte-identical (median-driven frame + two
operator globals).**

---

# PART 1 — DPM form cleanup

## D1.1 Remove vestigial imports + call-site args in `config_flow.py`

- Delete the 17 `CONF_ZONE_DYNAMIC_PRESET_*` imports at `config_flow.py:7176-7192`
  that feed only the ignored positional args of `_build_dynamic_preset_schema`.
  Keep `CONF_ZONE_DYNAMIC_PRESET_ENABLED / _OFFSET / _RESET_OFFSET_GUEST /
  _SLEEP_ENABLED`.
- Reduce the render call at `:7252-7260` to the 4 active keys.
- Simplify `_build_dynamic_preset_schema` signature: drop the
  `*conf_keys` trailing positional pattern and take the 4 keys as
  named params. Remove the `if len(conf_keys) < 4` guard.
- Delete the "trailing 17 conf_keys ignored" docstring paragraphs.
- Do NOT delete the CONF constants from `energy_const.py` — options-dict
  restore still needs them so a downgrade doesn't lose data.

### Acceptance
- **Verify:** `grep -n CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_LOW config_flow.py` → no hits
- **Test:** `test_v4_7_18_dpm_drift_guard.py` still passes (frame preservation)
- **Test:** new AST test asserts `_build_dynamic_preset_schema` signature has 4 typed params (no `*args`)

## D1.2 Prune `MIRROR_KEYS_ZONE_DPM`

- Remove the 17 vestigial keys from `config_flow.py:449-465`. Keep the
  4 active ones (`enabled`, `offset`, `reset_offset_guest`,
  `sleep_enabled`).
- Add a code comment: *"v5.11.x cleanup — bucket cells were UI-stripped
  in v4.7.18 D1; this drops them from sibling mirror too. Constants
  remain in energy_const.py for options-dict restore."*

### Acceptance
- **Verify:** `MIRROR_KEYS_ZONE_DPM` len == 4
- **Test:** mirror unit test (if any) asserts siblings only receive the 4
  keys after a save

## D1.3 Prune strings.json + translations/en.json

- Remove 16 vestigial entries from `data` block (:608-623) in BOTH files.
- Remove 16 corresponding `data_description` entries (:630-645).
- Update the `description` string at `:602` — it currently says "…set
  target setpoint ranges for each outdoor condition bucket." That is
  now false. New copy (draft): *"Enable dynamic preset for this zone,
  set a small offset if this zone runs warm or cool, and (optionally)
  keep a distinct sleep-window offset."*
- Remove the `sections.sleep_section` entry — v4.7.18 D1 removed the
  section wrapper too.

### Acceptance
- **Verify:** strings.json + en.json parity — same keys under
  `config.step.zone_dynamic_preset.data` and `.data_description`
  (v5.10.0 lesson).
- **Live:** Zone → Configure → DPM step renders 4 fields, no orphan
  labels, no broken translation warnings in HA log.

## D1.4 Test-authority updates

- `test_v474_dpm_ui.py` and `test_v47x_dynamic_preset.py` — remove any
  assertion that the 16 bucket labels exist in strings.json. Add an
  ABSENCE lock: those keys must NOT appear in strings.json (regression
  guard against reintroduction).
- Keep `classify_bucket()` unit tests untouched.

### Acceptance
- **Test:** new absence-lock passes; existing DPM frame tests pass.

---

# PART 2 — Room-form label de-jargoning

## D2.1 Full inventory of room-facing labels

- Enumerate every `config.step.*` and `options.step.*` in strings.json
  that is a ROOM-facing step (excludes integration_config, energy_setup,
  zone_*, hvac_*, oc_*).
- For each: capture (step_id, field_key, current_label,
  current_description).
- Output the full audit as an appendix table in this planning doc BEFORE
  build begins (operator reviews wording style before code changes).

### Acceptance
- **Verify:** appendix table in this doc lists all room-facing labels
  BEFORE build (operator-approve pass).

## D2.2 Nerd-language flag pass

Terms to hunt (denylist) — flag every occurrence; replace or gloss:

| Term | Policy |
|---|---|
| "mmWave" | KEEP (load-bearing for the operator; sensor-type distinction) but add plain-language gloss in `data_description` on first use per step |
| "PIR" | KEEP + gloss ("PIR — the motion sensors that only see movement") |
| "BLE" | KEEP + gloss ("BLE — Bluetooth beacons on phones") |
| "hysteresis" | REPLACE — "temperature margin" or "how much the temperature must change before the setpoint moves" |
| "debounce" | REPLACE — "settle time" / "confirm delay" |
| "dwell" | REPLACE — "wait time" / "how long the zone stays active" |
| "provenance" | HIDE — internal only, do not surface |
| "substrate" | HIDE — internal only |
| "tier" (as in "tier 1/2 presence") | HIDE — internal |
| "failsafe" | REPLACE — "safety fallback" |
| "egress" | KEEP (load-bearing — the operator uses this word) but add gloss on first use per step ("egress = doors/windows to outside") |
| "lux" | KEEP + gloss ("lux = brightness level, roughly 10 = dim, 100 = normal indoor") |
| "occ" (as an abbreviation in a label) | REPLACE — "occupancy" |
| "Coord."/"Cfg." etc. abbreviations | REPLACE — spell out |
| Version numbers in labels ("v4.7 style") | REMOVE |
| Raw domain (`switch.*`, `fan.*`) in labels | HIDE from labels; OK in helper text as examples |

## D2.3 Rules of engagement

1. **NEVER** rename entity_ids, translation KEYS, or CONF keys —
   friendly-name / label / description text only. Entity renames break
   dashboards (v4.7.25 rename-precedent applies).
2. Technical detail moves to `data_description` in plain words — never
   deleted. (data_description is the "helper text" line under the label
   in HA UI.)
3. Load-bearing operator terms keep their word + get a gloss.
4. Both `strings.json` AND `translations/en.json` must be updated
   in the same commit — parity test only checks KEYS, not VALUES
   (v5.10.0 lesson). Builder discipline required; add a scratch
   `diff <(jq -S ... strings.json) <(jq -S ... en.json)` check to the
   plan's Build Notes.
5. Propose the FULL old→new label table IN THIS PLANNING DOC (Appendix)
   so operator can review wording style before build. Do NOT ship
   without operator sign-off on the table.

## D2.4 Sample of the 10 worst current labels + proposed replacements

(Prospective — operator to review before build. Sourced from
`strings.json` sections `sensors`, `climate`, `sleep_protection`,
`init_automation_chaining`, and `number.py` `_attr_name` values.)

| # | Where | Current | Proposed |
|---|---|---|---|
| 1 | `sensors.presence_sensors` | "Presence Sensors (mmWave)" | "Presence Sensors" (helper: "mmWave/radar sensors that see you even when you're still — good for reading nooks and desks") |
| 2 | `sensors.occupancy_sensors` | "Combined Occupancy Sensors" | "Pre-Combined Motion + Presence Sensors" (helper: "Sensors that already fuse motion and presence into one signal — usually vendor-supplied") |
| 3 | `sensors.scanner_areas` helper | "Only needed for sparse scanner homes. Select areas where BLE scanners are located that should map to this room…" | "Only needed if BLE (phone Bluetooth beacon) coverage in this room is thin. Point it at nearby rooms whose scanners can see this one." |
| 4 | `room_setup.occupancy_debounce` | "Motion Detection Delay" (label OK) — helper mentions "pre-filtered sensors (Screek, ESPHome LD2410)" | Label unchanged; helper: "How long to wait after a sensor trips before URA calls the room 'occupied'. Lower = faster response, higher = fewer false triggers. Use 0 if your sensor already filters noise (e.g. Screek, LD2410)." |
| 5 | `number.py:2405` `_attr_name` | "04 · Dynamic Preset Hysteresis (°F)" | "04 · Dynamic Preset Temperature Margin (°F)" (helper via strings: "How much the temperature must move before the DPM setpoint follows.") |
| 6 | `number.py:2327` `_attr_name` | "03 · Dynamic Preset Dwell (minutes)" | "03 · Dynamic Preset Settle Time (minutes)" (helper: "How long a bucket must hold before DPM commits to the new setpoint.") |
| 7 | `number.py:395` `_attr_name` | "47 · Zone Entry Dwell (minutes)" | "47 · Zone Entry Wait Time (minutes)" |
| 8 | `sensors.is_egress_window` helper | "…configured Egress Pause Threshold (~3 min) pauses the HVAC zone that serves this room (hvac_mode: off). Designed for kid-forgetfulness…" | "When ON, leaving this window open for a few minutes pauses the HVAC for the zone that serves this room (so you're not cooling the outside). Turn OFF for small vent windows that open often but shouldn't stop HVAC." |
| 9 | `climate.hvac_coordination_enabled` | "Enable HVAC-Managed Fans" (label OK) — helper says "…managed by the HVAC coordinator instead of room-level rules." | Label unchanged; helper: "When ON, comfort fans follow the whole-house cooling plan instead of just this room's temperature." |
| 10 | `sleep_protection.sleep_bypass_motion_count` | (current label ends up as internal-sounding) | "Motion Bypass Count" → "Motions Required to Wake Automation" (helper: "How many motion trips during sleep hours before URA treats the room as awake and resumes normal automation.") |

## D2.5 Institutional-context section (required by CLAUDE.md)

Already included above under "Institutional context verified".

## D2.6 Test authority

- No behavior changes → no new behavior tests.
- Add / extend the strings/en.json PARITY test to cover the room-facing
  steps' `data` and `data_description` blocks: both files must have the
  same keys AND same values (values are label text, so equality is the
  right check for a user-facing translation source). This closes the
  v5.10.0 gap ("parity test only checks keys, not values") for the
  labels in scope.
- AST test: assert no room-facing `strings.json` label contains any
  token from the denylist (`hysteresis`, `debounce`, `provenance`,
  `substrate`, `tier`, `failsafe`, `occ ` abbrev.). Denylist words in
  `data_description` are permitted (that's where glosses live).

## D2.7 Acceptance criteria

- **Verify:** appendix table (D2.1) filled with every room-facing label
  BEFORE any strings.json edits.
- **Verify:** operator approves the label table.
- **Verify:** no entity_id / translation KEY / CONF key renames — grep
  diff proves it.
- **Verify:** strings.json + en.json byte-identical for room-facing
  `data`/`data_description` blocks (jq -S diff empty).
- **Test:** parity test extended (D2.6) passes.
- **Test:** denylist AST test passes.
- **Live:** Spot-check on 3 rooms (Master Bedroom, Kitchen, AV Closet)
  — reconfigure flow renders new labels; no missing-translation
  warnings in HA log; entity friendly names in device page updated;
  existing dashboard tiles still render (proves no entity_id break).

---

## Tier justification (Tier 2, not Tier 2-DB)

- No DB schema change, no persisted-payload shape change, no
  cross-coordinator ripple. Part 1 is text-strip + config-flow schema
  trim; Part 2 is UI-string edits.
- Regression surfaces: (a) options-dict backward-compat on restart,
  (b) sibling-mirror behavior on save, (c) strings/en.json parity,
  (d) accidental entity_id / translation key rename.
- Two framing-disjoint reviews cover this without escalating:
  - **Reviewer A — vestigial-removal correctness / no-consumer-breakage.**
    Verify `energy_const.py` CONF constants preserved; verify
    `classify_bucket()` unaffected; verify options-dict restore for a
    room with pre-existing bucket keys is data-safe; verify no
    non-config-flow reader of the 17 keys exists (grep the whole tree
    including tests, domain_coordinators, sensor.py, dashboards).
  - **Reviewer B — label coverage + strings/en.json parity + no key
    renames.** Verify every room-facing step audited; verify parity
    (keys + values) between strings.json and en.json; verify no
    entity_id, translation KEY, or CONF key was renamed; verify
    denylist absence.
- Live validation: reconfigure-flow spot-check on 3 representative
  rooms; grep HA log for "Translation" warnings; confirm entity
  friendly names updated in device page.

## Deliverable summary (files touched, best-guess)

| File | Change |
|---|---|
| `custom_components/universal_room_automation/config_flow.py` | Remove 17 imports (:7176-7192); shrink render call (:7252-7260); rewrite `_build_dynamic_preset_schema` signature (:7265+); prune `MIRROR_KEYS_ZONE_DPM` (:444-466) |
| `custom_components/universal_room_automation/strings.json` | Delete 16+16 vestigial DPM entries + sleep_section; rewrite `zone_dynamic_preset.description`; edit ~120-150 room-facing labels + helper text per D2 table |
| `custom_components/universal_room_automation/translations/en.json` | Same as strings.json (parity) |
| `custom_components/universal_room_automation/number.py` | Rename 3 `_attr_name` values ("Hysteresis" → "Temperature Margin"; "Dwell" → "Settle Time" / "Wait Time"). NOTE: `_attr_name` on entities with a translation_key uses the translation instead — audit which pattern applies before edit; entity_id is NOT the same as friendly name, so friendly-name edits do not break dashboards. |
| `quality/tests/test_v4_7_18_dpm_drift_guard.py` (or new file) | Absence-lock: 16 vestigial DPM keys must not appear in strings.json; denylist AST test for room-facing labels; parity test extension |

## Pre-review baseline
```
git tag pre-review-v<next-version> -m "Pre-review baseline: DPM cleanup + room label pass"
```

## Open questions for the operator

1. Do you want Part 1 + Part 2 in a single deploy, or Part 1 first
   (small, safe), Part 2 as a follow-up cycle? Recommend single deploy
   — both are text-only, review budgets combine cleanly.
2. On D2.5 label-table review: prefer the appendix filled in this doc,
   or a separate `LABELS.md` review artifact?
3. `number.py` `_attr_name` audit: confirm we should touch the 3
   numbered-prefix entities. Alternative: leave numbers, only edit the
   suffix ("Dynamic Preset Hysteresis" → "Dynamic Preset Temperature
   Margin").

---

## Appendix A — Full room-facing label audit (TO FILL BEFORE BUILD)

*[Placeholder — this section is populated during D2.1 and shown to
operator for wording sign-off before any code edits.]*
