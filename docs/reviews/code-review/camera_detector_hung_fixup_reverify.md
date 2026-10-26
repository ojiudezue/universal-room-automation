# CAMERA-SILENT-PRODUCER-TRIPWIRE-1: fix-up re-verification (8851fee75)

Base: 6eb6fff67 (build) to 8851fee75 (fix-up). Reviewer: ura-reviewer, focused re-verify. Verdict: **SHIP**.

## Finding closure
| Finding | Status | Evidence |
|---|---|---|
| A-HIGH-1 (value changes and changes back between 5-min samples, read as frozen) | CLOSED | `optimization.py:3177-3191`: `lc_advanced` compares HA `last_changed` against the previous tick's value and re-anchors the dwell. The dwell stays on our own clock (`_detector_value_since = now`), so plan I1 holds and `last_reported` is never read. |
| B-MED-1 (HIGH dropped during NM quiet hours, no discharge) | CLOSED | `optimization.py:3213-3232`: when quiet, no emit and no latch, and the dwell is kept. The first non-quiet tick emits. NM absent or an NM exception means emit. The key `hass.data[DOMAIN]["notification_manager"]` matches `sensor.py:8546`. `is_quiet_hours_active` is at `notification_manager.py:4075`. |
| LOWs (A-L2 no-read warn, A-L3 relog, rename to `_is_fleet_oneshot`) | CLOSED | `optimization.py:3157-3176` and `3148-3149`. The rename is behaviour-neutral (`_FLEET_ONESHOT_KINDS` is unchanged). |

## New findings
- **LOW (suppression needs a discharge): defer is unbounded if quiet hours never end.** `optimization.py:3223-3231`. Repro: `CONF_NM_QUIET_USE_HOUSE_STATE=False`, manual 00:00 to 23:59 (`notification_manager.py:4101` gives `start<=now<=end`, true all day), or house_state stuck in `sleep`/`home_night` (`:4093`). The page is deferred forever. The only trace is one INFO log plus attr `detector_hung_deferred_quiet=True`. In both cases the operator has asked for DND, so this is consistent with NM's semantics. It is not a ship blocker. Optional hardening: cap the defer (for example, emit anyway once deferred for more than 12 h).
- **Cleared: restart and reload false negatives.** `_detector_last_changed` and `_deferred_quiet` are RAM-only and reset in `__init__`/`_reset_detector_dwell` (`:3117-3118`). After a restart the first tick has `prev=None`, so `lc_advanced=False`, and the dwell restarts. That was already true before the fix-up. A source reload that bumps `last_changed` costs at most one extra dwell. Reloads usually pass through `unavailable` anyway, which already resets the dwell (`:3158`). HA does not advance `last_changed` for an identical state or for attribute-only updates, so a genuinely frozen stat keeps a fixed `last_changed` (test `..._frozen_value_frozen_last_changed_fires`). A periodic reload faster than the dwell would mask a hang, but that limit predates the fix-up and does not come from it.
- **Cleared: deferred state on restart.** It resets to False, and the dwell re-arms from scratch, so restart cannot leave a stale defer.

## Mutation drills (PYTHONDONTWRITEBYTECODE=1, __pycache__ cleared, test_camera_detector_hung.py only)
| Site neutered | Result |
|---|---|
| `or lc_advanced` removed (A-HIGH-1) | RED: `test_detector_hung_aliasing_same_value_moving_last_changed_no_fire` |
| `quiet = False` forced (B-MED-1) | RED: `test_detector_hung_defers_during_quiet_hours_then_fires_once`, `test_binary_sensor_exposes_deferred_quiet` |
| restored baseline | 33 passed; `git status` clean |

## Stats
| Sev | Found | Fixed |
|---|---|---|
| LOW | 1 | 0 (optional) |

Bug class: suppression needs a discharge (LOW, config-extreme only).
