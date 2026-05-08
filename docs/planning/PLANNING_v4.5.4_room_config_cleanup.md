# PLANNING v4.5.4 — Room config & dead-code cleanup

**Status:** Planned, not started
**Tier:** Tier 2 cycle (multiple files, room-form behavior change for new edits)
**Predecessors:** v4.5.3 (EC switch lifecycle race fix)

## Why this exists

The v4.5.0.4 venetian-blind-tilt hotfix exposed a recurring class of bug:
**form fields collected from the user that have zero runtime readers**.
A re-audit (with proper evolution-tracking, after a first pass produced
muddled findings) confirmed the same class of bug elsewhere, plus a
larger pile of pure orphaned constants and superseded legacy fields.

The audit was scoped to verify, for each suspect CONF, **where the
feature evolved to**: room → zone → house/CM → coordinator. We don't
delete anything until the successor is identified, because room-level
"dead" config sometimes turns out to be the surviving half of a
moved-to-coordinator feature.

## Scope (verified, evidence-cited)

### Bug class — form field with no runtime reader (the v4.5.0.4 pattern)

| CONF | Form site | Real gate today | Action |
|---|---|---|---|
| `CONF_HVAC_EFFICIENCY_ALERTS` | `config_flow.py:1577` (Climate step) | None — abandoned. HVAC coord's AnomalyDetector is not gated by this CONF. | Remove form field + const + strings/translations |

This is the only verified blinds-class hit in v4.5.4 scope.

### Out of scope per user direction (2026-05-08)

- `CONF_MUSIC_FOLLOWING_ENABLED` is also a verified blinds-class hit
  (room form at `config_flow.py:5339`, no runtime reader; CM-level
  `CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED` is the real gate via
  `__init__.py:1445` + `switch.py:95`). **Deferred** until the
  Coordinator Manager cleanup cycle so we don't clobber the MF
  coordinator's wiring twice.

- `CONF_CAMERA_PLATFORM` is `MEDIUM` confidence dead — only in const.py,
  no form, no reader, but the camera/presence migration story isn't
  fully traced. **Excluded** from v4.5.4 per user direction; revisit
  when person-tracking architecture gets a dedicated audit cycle.

### Pure orphaned constants (`const.py` only, no form, no reader)

These are residue from deprecated features. Safe to delete; they cannot
break anything because they're already not connected to anything.

| Constant | Story |
|---|---|
| `CONF_PHONE_TRACKERS` | Marked DEPRECATED at `config_flow.py:92` → replaced by `CONF_SCANNER_AREAS` (integration-level). v3.2.4-era. |
| `CONF_ROOM_BEACONS` | Beacon tracking moved to integration / presence-coordinator. |
| `CONF_TRACK_PERSONS_IN_ROOM` | Per-room person tracking superseded by presence coordinator (integration-level). |
| `CONF_COMFORT_ENABLED` | Was planned as a comfort-scoring gate; never wired. `ComfortScoreSensor` is ungated diagnostic today. |

### Dead legacy time-window CONFs (read-only via hardcoded fallback, never collected)

| CONF / Default | Status | Replacement |
|---|---|---|
| `CONF_OPEN_TIME_START` | Never in any form. `automation.py:988 _is_in_open_time_range` reads `.get(CONF_OPEN_TIME_START, 7)` — always falls back to literal 7. | `CONF_COVER_OPEN_TIME_SOURCE` + `CONF_COVER_OPEN_HOUR` (form-collected) |
| `CONF_OPEN_TIME_END` | Same — hardcoded fallback 20. | (see above) |
| `CONF_CLOSE_TIME` | `automation.py:1365` reads with hardcoded fallback 20. | `CONF_COVER_CLOSE_TIME_SOURCE` + `CONF_COVER_CLOSE_HOUR` |
| `DEFAULT_OPEN_TIME_START`, `DEFAULT_OPEN_TIME_END`, `DEFAULT_CLOSE_TIME`, `DEFAULT_SCAN_INTERVAL` | Defined but no consumer references them. The `.get()` calls all use literals instead. | (delete) |
| `_is_in_open_time_range` | Helper in `automation.py:986-990`; unused vestige of the legacy time-window system. | (delete) |

### Legacy cover action fallback (keep code, hide form field)

| CONF | Status |
|---|---|
| `CONF_ENTRY_COVER_ACTION` (values `COVER_ACTION_NONE/ALWAYS/SMART`) | Still in form at `config_flow.py:1081`. Read at `automation.py:932` as a fallback when `CONF_COVER_OPEN_MODE` (the new 5-mode system) is absent. **Migration is silent — works correctly for existing entries with the legacy key.** |

**Action:** hide the legacy form field from the room cover_behavior step
in `config_flow.py` so users only see the modern `CONF_COVER_OPEN_MODE`.
**Keep** the fallback-read code in `automation.py:919-937` so already-saved
entries still resolve to a valid mode without forcing a re-edit.

## Deliverables

### D1 — Remove `CONF_HVAC_EFFICIENCY_ALERTS` (the only blinds-class hit)

- Delete the form field from `config_flow.py:1577` (Climate step).
- Delete the constant from `const.py`.
- Delete the strings from `strings.json` and `translations/en.json`.
- For any existing entry that has the key set in `entry.options`: leave
  it. It does nothing today and won't do anything after removal. (No
  back-compat shim needed per single-user no-back-compat memory.)

#### Acceptance criteria
- **Verify:** `grep CONF_HVAC_EFFICIENCY_ALERTS custom_components/` returns 0 hits.
- **Verify:** Climate step renders without the field; existing entries don't error.
- **Test:** `test_v454_d1_efficiency_alerts_removed.py` AST-grep test asserts the constant is gone from const.py and config_flow.py.
- **Live:** post-deploy, restart HA; HVAC coord still loads; existing room edits don't surface the dead field.

### D2 — Delete pure orphaned constants

- Delete from `const.py`: `CONF_PHONE_TRACKERS`, `CONF_ROOM_BEACONS`, `CONF_TRACK_PERSONS_IN_ROOM`, `CONF_COMFORT_ENABLED`.
- Delete the deprecation comment in `config_flow.py:92` (`CONF_PHONE_TRACKERS`).

#### Acceptance criteria
- **Verify:** `grep` for each constant returns 0 hits.
- **Test:** existing tests still pass (no consumer broke).
- **Live:** integration loads cleanly; no startup errors.

### D3 — Delete dead legacy time-window CONFs

- Delete `CONF_OPEN_TIME_START`, `CONF_OPEN_TIME_END`, `CONF_CLOSE_TIME` from `const.py`.
- Delete `DEFAULT_OPEN_TIME_START`, `DEFAULT_OPEN_TIME_END`, `DEFAULT_CLOSE_TIME`, `DEFAULT_SCAN_INTERVAL` from `const.py`.
- Delete `_is_in_open_time_range` from `automation.py:986-990`.
- Audit `automation.py:1365` and similar sites for `.get(CONF_CLOSE_TIME, 20)`-style reads and remove them; confirm the modern `CONF_COVER_CLOSE_TIME_SOURCE` + `CONF_COVER_CLOSE_HOUR` path is the only one.

#### Acceptance criteria
- **Verify:** Cover open/close timing functions identically (pre-vs-post deploy comparison on a few rooms).
- **Test:** `test_v4504_blind_tilt.py` and any cover-timing tests still pass.
- **Live:** cover entry/exit automation runs unchanged.

### D4 — Hide the legacy `CONF_ENTRY_COVER_ACTION` form field

- In `config_flow.py:1081` (room cover_behavior step), remove the form
  field for `CONF_ENTRY_COVER_ACTION`.
- **Keep** the fallback-read code in `automation.py:919-937`
  (`_get_cover_open_mode`) intact — already-saved entries with the
  legacy key still resolve correctly.
- Add a comment at the fallback site noting that the form field was
  removed in v4.5.4 and the fallback is for legacy entries only.

#### Acceptance criteria
- **Verify:** new room edits show only `CONF_COVER_OPEN_MODE` (5-mode dropdown).
- **Verify:** existing rooms with `CONF_ENTRY_COVER_ACTION = COVER_ACTION_SMART` still automate correctly (silent migration via fallback).
- **Test:** unit test that `_get_cover_open_mode` returns the right new mode for each legacy value.

### D5 — Add Bug Class #32 to `QUALITY_CONTEXT.md`

- **#32 — Form field with no runtime reader.** Pattern: a `CONF_*` is
  collected in `config_flow.py`, validated, written to `entry.options` /
  `entry.data`, but **no runtime path reads it**. The setting silently
  does nothing. Hits to date: `CONF_COVER_TYPE` (v4.5.0.4 venetian-blind-tilt),
  `CONF_HVAC_EFFICIENCY_ALERTS` (v4.5.4), `CONF_MUSIC_FOLLOWING_ENABLED`
  (deferred to CM cleanup).
- Detection: for every CONF in `const.py`, grep across runtime code
  paths (anything outside `const.py` and `config_flow.py`); zero hits =
  this bug class.
- Add a quality check to `DEVELOPMENT_CHECKLIST.md`: when adding a new
  form field, the PR must include a runtime read site or be deleted.

#### Acceptance criteria
- **Verify:** `QUALITY_CONTEXT.md` lists #32 with examples.
- **Verify:** `DEVELOPMENT_CHECKLIST.md` step added.

## Out of scope (don't pull into v4.5.4)

- **Music following cleanup** — defer to a dedicated CM cleanup cycle
  so we touch the MF wiring once, not twice.
- **`CONF_CAMERA_PLATFORM`** — defer to person-tracking architecture
  audit cycle. Insufficient migration evidence for confident removal.
- **EC switch seed-stomp removal** — v4.5.3 fixed the lifecycle race;
  the cm_config seed itself is harmless given the robust retry. Don't
  bundle a seed-removal here.
- **Dead signals or dispatcher asymmetry** — first audit's claims here
  were spurious (signals all have listeners, just on multi-line
  registrations). Re-audit before opening this can.

## Tier 2 review plan

Two reviews + post-deploy live validation.
- **Review 1 (Core A):** D1+D2+D3 — config-removal blast radius, no
  back-compat shim, existing entry behavior.
- **Review 2 (Core B):** D4 — hide-but-keep migration safety; D5 —
  bug class doc accuracy.
- **Live:** verify each affected room still automates per its saved
  config (no behavior change for legacy entries); HVAC coord still
  loads; cover entry/exit unchanged.

## Cost

| Component | Effort | LoC |
|---|---|---|
| D1 efficiency_alerts removal | 30 min | ~15 lines deleted |
| D2 orphan constants delete | 30 min | ~10 lines deleted |
| D3 legacy time-window cleanup | 1-2 hours | ~30 lines deleted |
| D4 hide legacy cover-action form field | 30 min | ~5 lines deleted, comment added |
| D5 docs (Bug Class #32 + checklist step) | 30 min | ~30 lines added |
| **Total** | **3-5 hours** | **~80 LoC net delete** |

## Risks ranked

1. **D3 hidden consumer.** The `.get(CONF_X, 7)`-style reads in
   `automation.py` always evaluate to the literal because no form
   collects the CONF. Risk: a user's entry.options has the key set
   manually (via YAML import or hand-edit) and removing the read site
   silently breaks their setup. Single-user no-back-compat memory says
   this is acceptable; no shim.
2. **D4 silent migration regression.** If `_get_cover_open_mode`'s
   fallback path is mis-mapped for any value of `CONF_ENTRY_COVER_ACTION`,
   the user's covers behave differently after the form field is hidden
   (since they can't edit the legacy key anymore). Mitigation: D4 unit
   test covers all 3 legacy values + 5 new modes.
3. **Audit miss.** A "dead" CONF might actually be read at a site I
   didn't grep correctly (the first audit pass had this exact failure
   mode). Mitigation: each D's "Verify" step is `grep` across the
   entire `custom_components/` tree, not just the obvious files.
