# v4.6.2.2 — Guest Mode False-Positive Hardening

**Date:** 2026-05-14 CDT
**Type:** Tier 1 hotfix during v4.6.2 soak
**Predecessor:** v4.6.2.1 (Humidity Fan Hardening — deployed earlier same day)
**Severity:** UX reliability — house was flipping into Guest mode dozens of times per day with no guests present

## Problem

Live audit during v4.6.2 soak: `sensor.ura_coordinator_manager_house_state` was flipping to `guest` constantly, despite no guests. 3-day history of `unidentified_persons_in_house` oscillated 0↔1↔2↔3 essentially continuously during waking hours, and house-state history showed many dozens of `home_day ↔ guest` flips per day across May 7–9.

### Root cause

The guest gate at `presence.py:408-415` fired on any single-tick `unidentified_count > 0` while the house was in `HOME_DAY / HOME_EVENING / HOME_NIGHT`. `unidentified_count` is computed at `camera_census.py:1162` as `max(0, camera_total - identified_count)` where identified is `face_ids ∪ ble_ids`.

When a family member is briefly camera-visible but not face-recognized (Frigate face DB undersize: 11–17 samples per family member at threshold 0.9; ~1 match per 50 events) **and** not currently BLE-resolved (phone not advertising, scanner gap, IRK rotation), they're counted as a guest. Single-tick mis-IDs immediately flipped house state. Common scenario: resident walking toward the door — BLE flickers silent in the door-side antenna shadow while the camera still sees them → unidentified=1 for one tick → GUEST fires → BLE recovers → exit GUEST. Chatter pattern.

Three independent failure paths the current gate didn't close:

1. **No persistence guard.** One transient census tick was enough to fire GUEST.
2. **No confidence gate.** `presence.py` never read `census_confidence`. When confidence was `low` (BLE-only, single-source, or cameras disagree), the gate still fired.
3. **Threshold of 1.** Any non-zero count fired.

## Fix

### D1 — Extend `SIGNAL_CENSUS_UPDATED` payload

Two additive keys at `camera_census.py:803-813`:
```python
"confidence": house_result.confidence,           # "high" | "medium" | "low" | "none"
"source_agreement": house_result.source_agreement,  # "both_agree" | "close" | "disagree" | "single_source"
```

No subscribers break; presence reads via `payload.get(..., "none")` so legacy emit paths are safe.

### D2–D4 — `_guest_gate_armed` three-step evaluation

Replaces the old one-line gate with an ordered guard in `domain_coordinators/presence.py`:

1. **Existence:** `unidentified_count > 0` (fail-closed at zero).
2. **Confidence:** `_confidence_at_least(census_confidence, require_confidence)` using a private integer rank map `{"none": 0, "low": 1, "medium": 2, "high": 3}`. Refuses to fire when the observed rank is below the required rank.
3. **Persistence:** Tracks `_unidentified_first_seen`; on first qualifying tick, sets it; on subsequent qualifying ticks, fires only when `(now - first_seen) >= persistence_seconds`; on any qualifying-condition-false tick, clears it.

Persistence timer uses `async_call_later` scheduled at `now + persistence_seconds + 5` and is cancelled on every exit path (fire / disarm / state-leave-HOME / coordinator unload). Tracked via `entry.async_on_unload` to prevent Bug Class #19 leaks.

Exit branch (`unidentified == 0` → return home) is preserved IMMEDIATE — no persistence on exit, cheaper to leave guest mode than enter it.

### D5–D6 — Threshold knob considered + dropped

The original plan had `CONF_GUEST_MODE_MIN_UNIDENTIFIED` (default 2) as a third gate. **Dropped after live-audit reasoning:** persistence + confidence together filter the observed chatter pattern (resident BLE flicker, face-DB miss producing transient unidentified=1 ticks) without sacrificing single-visitor detection. The effective existence threshold of `unidentified > 0` is preserved. Real visitors (1 unrecognized person sustained ≥ 5 min) still trigger GUEST.

### Config knobs (Coordinator Manager options flow)

| CONF | Default | Range | What it does |
|---|---|---|---|
| `CONF_GUEST_MODE_PERSISTENCE_SECONDS` | 300 (5 min) | 0–1800s | Set to 0 to disable persistence (legacy single-tick fire). |
| `CONF_GUEST_MODE_REQUIRE_CONFIDENCE` | `medium` | `high` / `medium` / `low` | `medium` blocks BLE-only and disagree-camera firings. |

## Files changed

- `const.py` — 2 new `CONF_GUEST_MODE_*` + 2 new `DEFAULT_GUEST_*` constants
- `camera_census.py` — payload extension (5 LoC)
- `domain_coordinators/presence.py` — `_guest_gate_armed`, `_disarm_guest_gate`, `_schedule_guest_persistence_recheck`, `_confidence_at_least`, `_CONFIDENCE_RANK` map, new state fields, updated `_handle_census_update`, updated `_run_inference`, updated `async_teardown`
- `config_flow.py` — 2 new fields in `async_step_coordinator_presence`
- `__init__.py` — passes 2 new knobs to `PresenceCoordinator`
- `strings.json` + `translations/en.json` — labels + helper text
- `quality/tests/test_v4622_guest_mode_hardening.py` — 37 new tests (new file, ~866 LoC)
- `quality/tests/test_presence_coordinator.py` — 1 updated test for new `guest_gate_armed=` API

## Test count

- v4.6.2.1: 2960 passing
- **v4.6.2.2: 2997 passing** (+37 new tests)

## What's NOT done in this hotfix (deferred to v4.6.2.3)

From the Tier 1 review (`docs/reviews/code-review/v4.6.2.2_guest_mode_hardening.md`):

- **MEDIUM #1 — Signal-reactivity gap on confidence-only change.** `_handle_census_update` only triggers `_run_inference` on count change. Confidence upgrade (low→high) with unchanged counts waits up to one 60s periodic cycle. Trivial fix: add `old_confidence != self._census_confidence` to the trigger condition.
- **LOW #2 — Dead state `_census_source_agreement`** captured but never read. Either wire it into the gate or remove the field.
- **LOW #7 — Test stub re-implementation drift.** Some tests construct a stub that mirrors `_guest_gate_armed`; production-code drift risk. Refactor to call the real method.

See `docs/BACKLOG.md` → "v4.6.2.3 — Review carry-overs from v4.6.2.1 + v4.6.2.2".

## Live validation plan

1. Confirm `binary_sensor.ura_guest_mode` / `sensor.ura_coordinator_manager_house_state` do NOT flip to `guest` for short (< 5 min) unidentified-count blips. Compare to baseline frequency from pre-deploy 3-day history.
2. Drop persistence to 60s temporarily (via Coordinator Manager options) and validate gate timing — guest should fire ~60s after a sustained unidentified blip.
3. Confirm real-guest scenario still works: resident recognized + visitor unrecognized for ≥ persistence window → guest fires.
4. Confirm exit timing is unchanged (guest → home_day immediate on count=0 tick).
5. Watch logs for any `async_call_later` warnings or orphan-callback errors on entry reload.
6. After 24h, query DB for `house_state` write rate vs baseline — should drop dramatically.
