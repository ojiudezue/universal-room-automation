# Sensor-Health Surfacing (SENSOR-HEALTH-SURFACING-1) — Tier 2 Review A

**Framing:** Correctness + edge cases (adversarial vs `docs/QUALITY_CONTEXT.md`).
**Diff base:** `git diff develop...feature/sensor-health-surfacing` @ commit `17134679b`.
**Reviewer:** Review A (framing-disjoint from B).
**Scope files:** `coordinator.py` (+280 LoC), `const.py`, `sensor.py`, tests.

## Verdict: **DO-NOT-SHIP**

One CRITICAL that voids the cycle's motivating incident (Garage B ratgdo 2026-08-09), one HIGH false-negative in the corroboration rule, and one MEDIUM false-positive class in single-sensor rooms. Two LOWs.

The CRITICAL is a Nyquist-sampling mismatch between the detector's ring-fill cadence and its threshold — proven by the test suite's own workaround (the incident-replay test ticks at **15 s** while the real coordinator ticks at **30 s**).

---

## A1 — CRITICAL: Detector is Nyquist-blind at production tick rate; cannot fire on the motivating incident.

**File / line:** `coordinator.py:1875` (`_detect_chatter`) + `coordinator.py:584` (tick interval) + `const.py:CHATTER_*` + test `quality/tests/test_chatter_detector.py:302,318` (incident replay).
**Bug class:** #7 (stale/wrong data source — sampling grain wrong for signal) + planning-doc §5 CONSUMER check missed the PRODUCER cadence.

### Mechanism

- `_detect_chatter` samples entity state ONCE per coordinator tick and appends `(mono, on_now)` to the per-entity ring. Transitions in the ring are counted by re-walking sampled adjacencies (`per_entity_transitions[eid] = trans`).
- The coordinator's `update_interval` is **30 s + jitter** (`coordinator.py:584`). Refreshes triggered mid-interval by BLE/state changes are opportunistic and NOT correlated with the chattering sensor's own edges — they do not oversample the target.
- Therefore at steady state the ring holds ≈ `60 min × 2 samples/min = 120 samples` over a 60-min window.
- Maximum achievable transitions in the ring = 120 (perfect on/off alternation between samples via aliasing). That yields `rate_per_min = 120 / 60 = 2.0`.
- The gate is `if rate_per_min <= CHATTER_MIN_TRANSITIONS_PER_MIN: continue` with `CHATTER_MIN_TRANSITIONS_PER_MIN = 2.0`. **Strict `>` required; 2.0 <= 2.0 is always true → the branch always `continue`s.**

### Failing input → wrong output

Garage B ratgdo, 2026-08-09: 3,765 on / 3,769 off in 24 h ≈ **5.2 transitions/min** in the real world. Under 30 s sampling, aliasing collapses this to at most 2.0/min in the ring → detector returns `set()` → NM never fires → `sensor.<room>_unavailable_entities` never shows `reason="chattering"`. **The cycle's stated motivating incident is not caught by the shipped detector.**

### Independent evidence — the test suite already admitted this

`test_chatter_detector_replay_garage_b_incident_2026_08_09` (`test_chatter_detector.py:302`) explicitly runs at `15 s` per tick (line 318: *"CHATTER_WINDOW_MIN=60min ring driven at 15s/tick → 200 samples"*), not the production 30 s. The other passing tests also use `dt_per_tick` values chosen to produce > 120 in-ring transitions in 60 min. There is no test at the real tick rate — because at 30 s the detector cannot pass its own threshold on any physical signal.

### Fix (pick one)

1. **Preferred — count edges, not samples.** Register an HA state-change listener per candidate entity (like the flap detector already does) and append `(mono, new_state_bool)` on every genuine transition. Then `rate_per_min = len(ring) / 60`, un-aliased. The 30 s coordinator tick is only used to advance the window and evaluate.
2. Or: lower `CHATTER_MIN_TRANSITIONS_PER_MIN` to something the sampler can actually exceed (e.g. `1.0`) AND change the gate to `<` — but this still cannot see faster oscillators, only slower ones. Not recommended.
3. And: add a test **at 30 s tick** that reproduces the ratgdo case end-to-end. The current suite is not authoritative for production timing.

---

## A2 — HIGH: Two co-chattering sensors in the same room silence each other.

**File / line:** `coordinator.py:` corroboration loop inside `_detect_chatter`:
```
has_corroborator = any(
    other != eid and per_entity_transitions.get(other, 0) > 0
    for other in candidates
)
```
**Bug class:** #7 / trust-oracle FN.

### Mechanism

The "different entity_id + any non-zero in-window transition" test protects against a *lone* chattering anchor self-corroborating. It does NOT protect against **two chattering candidates in the same room**: each sees the other as a corroborator (`transitions > 0`) and BOTH are silenced. Realistic triggers: shared RF interference (Garage B has ratgdo + a Zigbee mmwave + Protect motion — an RF event affecting the 2.4 GHz band can push two of those to chatter concurrently); dying batteries on a paired mmWave/PIR combo; a firmware regression hitting a device family.

### Failing input → wrong output

`motion_sensors = ["m1", "m2"]`, both chattering at 5/min. Each has non-zero transitions → each corroborates the other → `chattering = set()` → no NM, no D3 attribute. The louder the shared fault, the more silent the detector.

### Fix

The corroborator must itself be healthy. Cheapest structural fix: a corroborator's `per_entity_transitions[other]` must be **strictly below** `CHATTER_MIN_TRANSITIONS_PER_MIN * CHATTER_WINDOW_MIN` (i.e. below the chatter bar). Alternatively: exclude entities that would themselves be flagged this tick from the corroborator pool (two-pass: compute the candidate set of "over-threshold" first, then require corroboration by an entity NOT in that set).

Add a test: two co-chattering entities, exactly one legitimate low-rate entity → both flagged, legitimate entity is the corroborator.

---

## A3 — MEDIUM: Single-sensor rooms will false-positive on legitimately-active occupancy.

**File / line:** `_detect_chatter` corroborator requirement; candidate set = `motion ∪ mmwave ∪ occupancy`.
**Bug class:** #7 (wrong-oracle FP) + planning §6 non-goal 1 assumed "notify-only" makes FPs cheap — an NM ping to the operator is still user-visible.

### Mechanism

A room configured with only a single PIR (e.g. a closet, small utility room, or any room where the operator has intentionally kept the sensor set minimal) has no other candidate to corroborate. If the occupant does something that trips the PIR repeatedly for an hour — pacing, exercising, cooking, working at a bench — the PIR can genuinely produce > 2 transitions/min (even under aliased sampling, if activity happens on both sides of the 30 s boundary). With no corroborator possible, the detector flags the sensor as chattering and NM-notifies "Replace sensor — hardware fault (loose contact / dying battery / RF interference)."

### Failing input → wrong output

`motion_sensors = ["binary_sensor.closet_pir"]`, no mmwave, no occupancy candidate. Occupant works in the closet for an hour, PIR fires and clears 130 times → `rate = 2.17/min` (if A1 is fixed to make firing possible) → uncorroborated → chatter NM fires accusing a healthy sensor of hardware fault.

### Fix

Require a minimum candidate set size (skip evaluation when `len(candidates) < 2` — a single-candidate room cannot distinguish activity from chatter and should be excluded from this detector). Document as a known limitation. Alternatively, gate on room-level presence: if the room is currently occupied by an independent source (BLE trust, camera person), suppress the flag.

---

## A4 — LOW: `_chatter_last_state` populated but never consumed; stale-entity cleanup incomplete.

**File / line:** `coordinator.py` inside `_detect_chatter`:
```
prev = self._chatter_last_state.get(eid)
is_transition = prev is not None and prev != on_now
...
self._chatter_last_state[eid] = on_now
...
_ = is_transition
```
The `is_transition` value is deliberately discarded; the ring-walk recomputes transitions from sampled adjacencies. `_chatter_last_state` therefore serves no purpose (dead state).

Additionally, the config-hygiene cleanup only prunes `_chatter_rings` and `_chatter_last_state` for entities dropped from config; `_chatter_first_flagged`, `_chatter_transition_count`, `_chatter_quiet_since`, and `_chatter_nm_notified` are NOT pruned. A chattering entity removed from config leaks these dicts and can suppress a legitimate recovery emit (or fire a stale one) if re-added.

### Fix

Delete `_chatter_last_state` (and the `prev / is_transition / _ = is_transition` block) — it is not load-bearing. Extend the stale-purge loop to cover all six dicts.

---

## A5 — LOW: Kill-switch docstring lies about restart.

**File / line:** `const.py`:
```
# Kill switch — rung 1. False → _detect_chatter returns set() immediately,
# ... No lingering state; no restart required. Sibling of STUCK_EXCLUSION_ENABLED.
```
`CHATTER_DETECTOR_ENABLED` is a module-level `Final` constant. Changing it requires editing source and reloading the integration (config-entry reload at minimum; realistically an HA restart because the URA parent-entry reload is forbidden per operator rule). The comment "No restart required" is false and matches the *rung-3 (Number entity)* semantics, not rung 1.

### Fix

Reword: "Kill switch — rung 1 (module constant). Toggling requires code change + config-entry reload. Kept at rung 1 because the operator should not be able to disable a hardware-fault detector from the dashboard."

---

## Notes / non-findings (verified clean)

- **Recovery / re-flap same day.** `_chatter_nm_notified.discard(eid)` after `CHATTER_RECOVERY_QUIET_WINDOW_MIN` clears the process-scope gate; `fire_stuck_signal_recovered` per the docstring clears the per-day latch. Same-day re-flap can re-notify. OK **assuming** `fire_stuck_signal_recovered` actually clears the latch — Review B should confirm the NM contract, this is out-of-frame for A.
- **Boot-settle gate.** Early `return set()` before ring-update, so no phantom transitions from rehydration edges. `_chatter_last_state` is not seeded during suppressed ticks; first post-settle sample seeds cleanly. OK.
- **`_is_sensor_on` on missing entity.** Returns False (URA convention) → 0 transitions → not flagged. OK.
- **`hass.async_create_task(fire_stuck_signal(...))`** — untracked task marker present; standard URA pattern.
- **Threshold boundary arithmetic** (`> window_sec` prune, `<= threshold` reject): consistent with plan §4. OK modulo A1.
- **Presence-key literal (`"presence_sensors"` == `CONF_MMWAVE_SENSORS`).** Caller-resolved; docstring warns. OK.

---

## Required before re-review

1. Fix A1 (edge-listener OR retuned threshold + gate) and add a **30 s tick** ratgdo replay test.
2. Fix A2 (healthy-corroborator rule) with a two-co-chatter test.
3. Decide A3: either single-candidate skip OR document + suppress via room-occupied trust.
4. A4 / A5 are cleanups; safe to bundle.

A1 alone is disqualifying — the detector as shipped does not detect the case it was built for.
