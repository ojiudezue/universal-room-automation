# v4.5.0.4 — Venetian blind tilt control hotfix

**Date:** 2026-05-07
**Type:** Tier 1 hotfix (room cover dispatch + verify; ~50 LoC change + 24 regression tests)
**Predecessor:** v4.5.0.3
**Discovered:** User report — "rooms allow describing the kind of blind (roller shade or venetian blinds with tilt controls), but if you specify the latter, the blinds control just acts like a roller shade."

## Summary

Fixes a long-latent dead-config bug. Rooms have always allowed configuring `cover_type` as either `shade` (roller blind) or `tilt` (venetian blind), and the value was correctly stored in `entry.options`. But **the value was never read in production runtime code** — `automation.py:_send_covers_with_verify` always called `cover.open_cover` / `cover.close_cover` regardless. On a venetian blind, those services raise/lower the whole blind; the slats never tilt. The user's intent (tilt slats on entry/exit) was silently dropped.

`grep CONF_COVER_TYPE custom_components/**/*.py` pre-fix showed 5 hits in `config_flow.py` (3 form locations + 2 imports), 1 in `const.py` (definition), and **zero** in any runtime path.

## Bug shape

`automation.py:_send_covers_with_verify` — the central per-room cover-action dispatcher:
- Took an `action` parameter of `"open_cover"` or `"close_cover"`
- Passed that action verbatim to `hass.services.async_call("cover", action, …)`
- Verified target state via `_cover_at_target(state, target_state)` which checked `current_position` attribute

For a tilt-capable cover entity:
- `cover.open_cover` raises the entire blind to position=100 (slats unchanged)
- `current_position` reads 100 even when slats are closed (because the BLIND is at full position)
- Verify path saw `position == 100`, target_state == "open" → `True`. So URA logged success while slats stayed wherever they were.

Result: Venetian blinds got correctly classified by URA's verify ("blind is open!") but were physically NOT in the user-intended state (slats pointed however the user last left them). The dead config silently passed all integration tests because `cover.open_cover` is a valid HA service that doesn't error — it just doesn't do what the user expected for tilt blinds.

## Fix

Two changes, both in `automation.py`:

### 1. Dispatch the right HA service

```python
# v4.5.0.4 in _send_covers_with_verify:
from .const import CONF_COVER_TYPE, COVER_TYPE_SHADE, COVER_TYPE_TILT
cover_type = self.config.get(CONF_COVER_TYPE, COVER_TYPE_SHADE)
if cover_type == COVER_TYPE_TILT:
    service_name = f"{action}_tilt"   # "close_cover_tilt" / "open_cover_tilt"
else:
    service_name = action             # "close_cover" / "open_cover" (unchanged)
```

`cover.close_cover_tilt` / `cover.open_cover_tilt` are standard HA cover services that any tilt-capable cover integration (Hunter Douglas, Aqara, MQTT-templated, etc.) implements.

### 2. Verify against the right attribute

```python
# v4.5.0.4 in _cover_at_target:
if cover_type == "tilt":
    tilt_pos = attrs.get("current_tilt_position")
    if tilt_pos is not None:
        # 5% tolerance: closed if tilt_pos ≤ 5, open if ≥ 95
        ...
    return state.state == target_state   # fallback for integrations
                                         # that don't expose tilt_position
```

Roller-shade path is byte-for-byte unchanged — the tilt path branches before the position-based check.

## Behavior matrix

| User config | Action | Service issued | Verify uses |
|---|---|---|---|
| roller shade (shade) | open_cover | `cover.open_cover` | `current_position` ≥ 95 |
| roller shade (shade) | close_cover | `cover.close_cover` | `current_position` ≤ 5 |
| venetian (tilt) | open_cover | `cover.open_cover_tilt` | `current_tilt_position` ≥ 95 |
| venetian (tilt) | close_cover | `cover.close_cover_tilt` | `current_tilt_position` ≤ 5 |
| (defensive) unknown / "" | any | falls back to shade behavior | falls back to position |

The defensive fallback: if `cover_type` is somehow `""`, `None`, or some unknown string, the code branches `if cover_type == "tilt"` evaluates False and the existing shade behavior runs. No crash; no behavior change for shade users.

## What this DOESN'T do

- Doesn't change anything for users who already had `cover_type = shade` (the default and the dominant case)
- Doesn't add per-blind position control (just open/close at full extent or tilt fully open/closed)
- Doesn't fix HVAC-driven cover actions in `domain_coordinators/hvac_covers.py` — those have their own dispatch path; if HVAC-managed venetian blinds are common, that's a follow-up. User's reported case is room-level (entry/exit automation), so room-level is the scope here.

## Tier 1 Review

| Severity | Finding | Resolution |
|---|---|---|
| (no CRITICAL) | — | — |
| HIGH | Latent dead-config: feature visible in form but never functional | **Fixed** with two surgical changes |
| LOW | HVAC covers path may have same pattern (untested) | Documented as out-of-scope; can investigate when reported |
| LOW | Tests are mirror-style (don't import production helper) due to pre-existing Python 3.9 incompat in `automation.py:508` (tech debt #0) | Documented; v4.5.2 (test baseline cleanup) replaces with real-import tests |

**Verdict: READY TO DEPLOY.**

## Tests

24 new tests in `quality/tests/test_v4504_blind_tilt.py`:
- **6** service dispatch (shade/tilt × open/close + unsupported action + unknown cover_type)
- **7** shade-path verify (state, position 0/100/50/95/5)
- **8** tilt-path verify (tilt_position 0/100/50/95/5, no-attr fallback, ignores current_position)
- **2** unknown-cover-type fallback
- **1** None-state defensive

The mirror-style tests are intentional given the existing `test_cover_verify.py` is blocked from collecting on this dev box by pre-existing Python 3.9 union-syntax incompat in `automation.py:508` (a tech-debt #0 item to be resolved in v4.5.2). The mirror is kept in sync via review; v4.5.2 will replace these with real-import tests.

**Test count progression:**
- v4.5.0.3: 181
- **v4.5.0.4: 205** (+24)
- 0 new regressions in broader suite

## Live validation (post-restart)

For a room with `cover_type: tilt` and `covers: [cover.<entity>]`:

1. Trigger occupancy (motion + presence sensor) → URA fires the entry automation
2. Watch HA Developer Tools → Logbook for the room's covers
3. **Pre-fix:** entry shows `cover.open_cover` action (slats unchanged on a tilt-capable entity)
4. **Post-v4.5.0.4:** entry shows `cover.open_cover_tilt` action (slats tilt to fully open)
5. Inspect the cover entity attributes: `current_tilt_position` should be ≥95 after open, ≤5 after close
6. The room's `_cover_failures_today` counter should NOT increment (verify path now correctly checks tilt_position)

For roller-shade rooms (`cover_type: shade`), no behavior change expected.

## Deploy notes

- No DB schema changes
- No migration needed (cover_type was always set in entry.options; just newly read at runtime)
- HACS download required after deploy.sh per memory `feedback_verify_hacs_install.md`
- **User pre-action:** confirm any rooms with venetian blinds have `cover_type: tilt` set in their config-flow form. If they say `shade` (the default), the bug fix doesn't help them — they need to update the form too.

## Next

- **v4.5.1** — Config-flow restructure (paginated form, rate-plan top-level toggle, net-metering branch). Charge-rate control via barneyonline DROPPED from scope per v4.5.0.3 investigation findings (Enphase doesn't expose battery rate control).
- **v4.5.2** — Test baseline cleanup. Drive 57+14 → 0; add CI failure-count guard; resolve Python 3.9 compat issues so `test_cover_verify.py` and friends can collect; replace v4.5.0.4's mirror-style tests with real-import tests.
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
