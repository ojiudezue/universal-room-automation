# v4.5.21.1 — Enabled Switch Sorts to Top of HC Controls

**Date:** 2026-05-12 CDT
**Type:** Tier 1 cosmetic follow-up to v4.5.21
**Predecessor:** v4.5.21 (HC device-page ordering experiment)

## Summary

v4.5.21 left `CoordinatorEnabledSwitch` unprefixed under the (incorrect) assumption that `"E"` would sort before `"2"`/`"3"`/`"4"`. It didn't — HA's frontend uses `Intl.Collator(..., { numeric: true })` (`frontend/src/common/string/compare.ts`), so the numeric-prefixed Force/Cancel buttons sorted as numbers (20, 22, 30, …) and **landed above** `"Enabled"`, pushing the master switch to the bottom of the Controls cluster.

This cycle adds a one-line branch in `CoordinatorEnabledSwitch.__init__`: when `coordinator_id == "hvac"`, `_attr_name = "00 · Enabled"`. Sorts to the top of Controls (number 0 < 20, 30, 40). Other coordinator devices keep bare `"Enabled"` — they'll be picked up in their own sweep cycles per the v4.5.21 plan.

## Files changed

- `custom_components/universal_room_automation/switch.py` — 4-line conditional in `CoordinatorEnabledSwitch.__init__`
- `quality/tests/test_v4521_hc_device_ordering.py` — new `test_enabled_switch_hvac_prefix` (source-grep), updated SWITCH_HC_CLASSES doc-comment

## What's NOT changed

- All v4.5.21 prefixes preserved (Sensors / CONFIG / Diagnostic clusters unchanged)
- `CoordinatorEnabledSwitch` for Safety/Security/Presence/NM/MF/Energy/CM/Room/Zone — bare `"Enabled"` retained
- No entity_id / unique_id / device_info changes
- No behavioral changes

## HA frontend sort research (compiled this cycle)

For the record, since we now know how the sort actually works:

| Question | Answer | Source |
|---|---|---|
| Sort field | `stateName` (= registry `name` || `original_name`) | `frontend/src/panels/config/devices/ha-config-device-page.ts` |
| Sort algorithm | `Intl.Collator(..., { numeric: true })` | `frontend/src/common/string/compare.ts` |
| Whitespace stripping pre-sort | None | (verified across frontend + registry) |
| `sort_order` field on entity registry | Does not exist | `homeassistant/helpers/entity_registry.py` |
| Zero-width prefix chars (U+200B/200C/2060) | Codepoints > 8000 → sort AFTER digits/letters; useless | Unicode codepoint tables |
| Hidden-order alternative | Lovelace `auto-entities` custom card (off the device page) | thomasloven/lovelace-auto-entities |

**Practical implication:** there is no native HA mechanism to hide a sort key from device-page labels. The numeric prefix is the only lever. If/when the visual weight becomes intolerable, the path forward is a custom Lovelace dashboard, not a `_attr_name` trick.

## Tier 1 Review

Cosmetic-only, single-branch addition. Single staff-engineer review focused on:
- HVAC-only scope (no spillover to other coordinator Enabled switches)
- "00 · " sorts before all other HC Controls prefixes (verified: 0 < 20/22/30/32/40/42 numerically)
- No regression on other coordinator devices

Verdict: APPROVED. 0 CRITICAL/HIGH/MEDIUM/LOW.

## Test count

- v4.5.21: 538 (in-file), broader suite 2606 pre-existing pass
- **v4.5.21.1: 539** (+1 `test_enabled_switch_hvac_prefix` source-grep)

## Live validation plan (post-restart)

1. **Open Settings → Devices & Services → URA → "URA: HVAC Coordinator" device page.**
2. **Verify Controls cluster order:** `00 · Enabled` (toggle) at top, then `20/22 · Force/Cancel (Back Hallway)`, `30/32 · (Entertainment + Master Suite)`, `40/42 · (Upstairs)`.
3. **Verify all other clusters (Sensors / CONFIG / Diagnostic) unchanged** vs v4.5.21.
4. **Verify other coordinator device pages (Safety, Security, Presence, NM, MF, Energy, CM)** — their `Enabled` switches still read as bare `"Enabled"`, no prefix spillover.

## Deploy notes

- 2 files touched (switch.py, test_v4521_hc_device_ordering.py)
- HACS download required
- HA restart required
- Easy revert path: `git revert <commit>` undoes the one branch

## Documents

- Winter morning peak strategy filed: `docs/planning/PLANNING_v4.6.x_winter_morning_peak_strategy.md` (separate cycle, options A/B/C/D pending choice)

## Next

- Validate v4.5.21.1 on HC device page (this cycle)
- Decide whether to proceed with sweep to other coordinators (CM → House → Zone → other coords → Room last) OR pivot to Lovelace dashboard path
- v4.6.x — winter morning peak strategy (option choice pending)
- v4.6.0 — Routine Awareness Phase 1
