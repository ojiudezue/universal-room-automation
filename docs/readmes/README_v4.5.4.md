# v4.5.4 — Room config & dead-code cleanup (closes Bug Class #32 hits)

**Date:** 2026-05-08
**Type:** Tier 2 cleanup (5 deliverables; pure dead-code removal + docs)
**Predecessor:** v4.5.3 (EC switch lifecycle race)

## Summary

Closes the room-config dead-code findings from a thorough re-audit of
"things the user can configure that don't actually do anything" — the
class of bug that the v4.5.0.4 venetian-blind-tilt hotfix exposed. The
audit was scoped to verify, for each suspect CONF, **where the feature
evolved to** (room → zone → CM → coordinator) before deletion. A
docs/git pass before execution caught one wrong audit verdict (the
legacy time-window CONFs are part of an active fallback chain) and
shrunk D3 scope accordingly. Net: ~50 LoC delete, no behavior change
for any saved entry.

This release also adds **Bug Class #32 (Form Field With No Runtime
Reader)** to `QUALITY_CONTEXT.md` and a runtime-reader-required step
to `DEVELOPMENT_CHECKLIST.md` so this class doesn't recur.

## What was done

### D1 — Removed `CONF_HVAC_EFFICIENCY_ALERTS` (the only blinds-class hit in scope)

- Climate-step boolean toggle that had been collected in the form for
  years with no runtime reader anywhere. HVAC coord's AnomalyDetector
  is not gated by it; no successor exists at any other level.
- Removed from `const.py`, `config_flow.py` (Climate step + reconfig
  flow), `strings.json`, `translations/en.json`.
- The `_get_current(...)` re-read pattern means existing entries that
  have `hvac_efficiency_alerts: True/False` in `entry.options` carry
  the dead key forward. Harmless — nothing reads it. No back-compat
  shim needed (single-user no-back-compat per memory).

### D2 — Deleted 3 of 4 pure orphan constants

- Removed from `const.py`: `CONF_PHONE_TRACKERS` (v3.1.5 multi-phone
  residue, deprecated v3.2.4 → `CONF_SCANNER_AREAS`), `CONF_ROOM_BEACONS`
  (v3.1.5 ESPresense/Bermuda residue), `CONF_TRACK_PERSONS_IN_ROOM`
  (room-level person tracking, superseded by integration-level
  presence coordinator).
- **Deferred** `CONF_COMFORT_ENABLED`. The audit said it was a
  truly-dead constant, but on closer look its value
  `"comfort_coordinator_enabled"` is referenced in
  `COORDINATOR_ENABLED_KEYS` as a placeholder for a future Comfort
  coordinator (no `ComfortCoordinator` class exists today). Same
  shape as `CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED` (which the user
  also deferred to the CM cleanup cycle). Defer to that cycle so we
  touch the CM coordinator-slot wiring once, not twice.

### D3 — Deleted only the truly-dead `DEFAULT_*` time-window constants

A first-pass plan would have deleted `CONF_OPEN_TIME_START`,
`CONF_OPEN_TIME_END`, `CONF_CLOSE_TIME`, plus the helpers
`_is_in_open_time_range` and `_is_after_close_time`. **The pre-execution
docs/grep pass caught that this was wrong.** These CONFs and helpers
are part of the legacy fallback chain in `_is_cover_open_time` /
`_is_cover_close_time` — when an entry has neither the new
`CONF_COVER_OPEN_TIME_SOURCE` nor the legacy `CONF_OPEN_TIMING_MODE`
in v3.6.39's design path 1, the chain falls through to
`TIMING_MODE_TIME` / `BOTH_LATEST` / `BOTH_EARLIEST` modes that read
those CONFs. URA dates back to v3.3.5.3; many of the 34 live entries
likely still rely on this fallback and have never been re-edited
through the new form. Deletion would silently break them.

So D3 deleted only the 4 truly-dead `DEFAULT_*` constants:

- `DEFAULT_OPEN_TIME_START`, `DEFAULT_OPEN_TIME_END`, `DEFAULT_CLOSE_TIME`,
  `DEFAULT_SCAN_INTERVAL` — defined in `const.py` but never referenced
  anywhere. The `.get(CONF_OPEN_TIME_START, 7)`-style reads in
  `automation.py` use literals, not the constants. Pure unused.

### D4 — `CONF_ENTRY_COVER_ACTION` audit verdict revised

The original audit said `CONF_ENTRY_COVER_ACTION` was "still in form
at config_flow.py:1081." On verification, **the audit was wrong** —
it conflated `CONF_ENTRY_COVER_ACTION` (legacy, already removed from
the form in some prior cycle) with `CONF_EXIT_COVER_ACTION` (still in
the form, the modern close-on-exit mechanism). No form-field hide
needed; the legacy fallback in `automation.py:_get_cover_open_mode`
is already the only consumer.

Action: added a comment block above the legacy fallback
(`automation.py:919-944`) documenting the full mapping so a future
maintainer can verify the fallback's correctness without grepping
old READMEs:

```python
# Legacy fallback for pre-v3.6.39 entries that still have the
# legacy CONF_ENTRY_COVER_ACTION key in entry.data. The room form
# has not collected this CONF since v3.6.39 (the new 5-mode
# system in CONF_COVER_OPEN_MODE replaced it). Mapping is the
# one documented in README_v3.6.40 and verified in v4.5.4 audit:
#   COVER_ACTION_NONE   → COVER_OPEN_NONE
#   COVER_ACTION_ALWAYS → COVER_OPEN_ON_ENTRY (no time gate)
#   COVER_ACTION_SMART  → COVER_OPEN_ON_ENTRY_AFTER_TIME
```

### D5 — Bug Class #32 + DEVELOPMENT_CHECKLIST step

- New section in `docs/QUALITY_CONTEXT.md`: **Bug Class #32 — Form
  Field With No Runtime Reader.** Documents the pattern, detection
  one-liner (`grep` for the CONF outside `const.py` and `config_flow.py`;
  zero hits = this class), three known hits (`CONF_COVER_TYPE` v4.5.0.4,
  `CONF_HVAC_EFFICIENCY_ALERTS` v4.5.4, `CONF_MUSIC_FOLLOWING_ENABLED`
  deferred), and prevention checklist.
- New step in `quality/DEVELOPMENT_CHECKLIST.md` Phase 7 (Pre-Commit):
  every new `vol.Optional(CONF_X, …)` form addition must include a
  runtime reader in the same PR, or the field gets deleted in review.

## What this DOES NOT do

- **Doesn't touch music following or comfort coordinator placeholders.**
  Both are CM-level coordinator slots that should be cleaned up
  together when the CM cleanup cycle runs.
- **Doesn't touch `CONF_CAMERA_PLATFORM`.** Excluded per user
  direction; person-tracking architecture audit will revisit.
- **Doesn't touch the legacy time-window CONFs** (`CONF_OPEN_TIME_START`,
  `CONF_OPEN_TIME_END`, `CONF_CLOSE_TIME`) or the helpers that read
  them. Active fallback for pre-v3.6.39 entries; will be deleted
  wholesale only when a dedicated migration cycle migrates every
  legacy entry to the new `CONF_COVER_*_TIME_SOURCE` keys.
- **Doesn't change behavior for any saved entry.** Existing entries
  with the deleted CONFs in their `entry.options` continue working
  unchanged (the keys are now just stale residue with no consumer).

## Tier 2 Review

| Severity | Finding | Resolution |
|---|---|---|
| (no CRITICAL) | — | — |
| HIGH | The first-pass plan would have broken pre-v3.6.39 cover-timing entries by deleting active fallback CONFs | Caught in pre-execution docs/grep pass; D3 scope reduced to 4 truly-dead `DEFAULT_*` constants |
| MEDIUM | First audit's D4 verdict was wrong (conflated entry vs exit cover action) | Verified manually; D4 reduced to a comment-only change |
| MEDIUM | `CONF_COMFORT_ENABLED` is a CM-level coordinator placeholder, not a pure orphan | Deferred to CM cleanup cycle |
| LOW | Strings/translations had `hvac_efficiency_alerts` in two locations each (initial form + reconfig flow) | All four sites cleaned; `grep hvac_efficiency_alerts` returns 0 hits |

**Verdict: READY TO DEPLOY.**

## Tests

28 new tests in `quality/tests/test_v454_room_config_cleanup.py`:

- **D1 (4):** `CONF_HVAC_EFFICIENCY_ALERTS` removed from const.py, config_flow.py, strings.json, translations/en.json.
- **D2 (4):** 3 orphan constants gone; `CONF_COMFORT_ENABLED` intentionally still present (defer-to-CM-cleanup contract).
- **D3 (5):** the 4 dead `DEFAULT_*` time-window constants gone; sun-offset defaults preserved.
- **D3 (preservation, 7):** legacy fallback chain CONFs (`CONF_OPEN_TIMING_MODE`, `CONF_CLOSE_TIMING_MODE`, `CONF_OPEN_TIME_START`, `CONF_OPEN_TIME_END`, `CONF_CLOSE_TIME`) and helpers (`_is_in_open_time_range`, `_is_after_close_time`) still defined.
- **D4 (3):** form does not collect `CONF_ENTRY_COVER_ACTION`; fallback still reads it; mapping matches v3.6.40 spec for all 3 legacy values + defensive default.
- **D5 (2):** Bug Class #32 in QUALITY_CONTEXT.md; runtime-reader rule in DEVELOPMENT_CHECKLIST.md.
- **Source compiles (3):** const.py, config_flow.py, automation.py compile cleanly after deletions.

**Test count progression:**
- v4.5.3: 1926 tests, 0 isolated failures across 51 files
- **v4.5.4: 1954** (+28), 0 isolated failures across 52 files

## Live validation (post-restart)

This release is pure dead-code removal — no entity changes, no behavior
changes, no schema changes. Validation is "nothing broke":

1. After HACS download + HA restart, watch logs for the first 5 minutes:
   - No new SyntaxError / ImportError / NameError / AttributeError on URA modules
   - All previously-loaded URA entities still load
   - No "missing config" warnings on any room
2. Open Devices & Services → URA Coordinator Manager → spot-check a
   room's options form: Climate step should no longer show "HVAC
   Efficiency Alerts." All other Climate-step fields unchanged.
3. Cover automation: covers in rooms that use legacy `entry_cover_action`
   (i.e. that have never been re-edited since v3.6.39) should automate
   identically to before — the `_get_cover_open_mode` fallback is
   unchanged and still reads the legacy key.
4. Run `python3 scripts/test_isolation_check.py` in dev — confirm 0
   isolated failures (52 files).

## Deploy notes

- No DB schema changes
- No migration needed (deleted CONFs were never required; existing
  entry.options values become harmless residue)
- HACS download required after deploy.sh per memory `feedback_verify_hacs_install.md`
- HA restart required to pick up the const/config_flow/strings changes

## Next

- **Coordinator Manager cleanup cycle** — separate scope; cleans up
  CM-level placeholders (`CONF_MUSIC_FOLLOWING_ENABLED`,
  `CONF_COMFORT_ENABLED`, the unused `"comfort"` slot in
  `COORDINATOR_ENABLED_KEYS`). Defer until ready to wire or remove
  the actual coordinator slots.
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation.
- **Person-tracking architecture audit** — revisit `CONF_CAMERA_PLATFORM`
  alongside the broader presence/tracking story.
