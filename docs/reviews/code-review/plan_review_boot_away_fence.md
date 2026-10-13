# Plan review: PLANNING_boot_away_fence.md (CENSUS-SHUTDOWN-AWAY-FENCE-1)

Reviewer: ura-reviewer, one adversarial plan pass (Tier 2+ plan-review rule). Read-only against `develop`.
Date: 2026-10-11. HVAC state-of-play doc NOT read in full: this plan only touches presence, and HVAC appears only as a consumer. No HVAC claim is asserted below.

## Verdict: PLAN-FIX-REQUIRED

The fence keys on "current state is home-like". On develop, in every case the plan names as the cause (no record, stale, corrupt, restore not yet run), the machine's current state is already **AWAY** (`house_state.py:153` default `initial_state=HouseState.AWAY`). In those cases the predicate is False, so the fence is a no-op exactly where the plan expects it to act. The evidence base also uses a display sensor that reports `"away"` by fallback before the manager exists. The mechanism is unproven, and the fence as specified cannot close it.

## Findings

### CRITICAL-1: the fence predicate is a no-op on the default-AWAY path
- `house_state.py:151-157`: `HouseStateMachine.__init__(initial_state=HouseState.AWAY)`, constructed with no argument at `manager.py:220`.
- `manager.py:673-676` logs `"no persisted record (cold-boot default AWAY)"`. When restore is not applied, `manager.py:695-700` logs "machine remains at %s", which is AWAY.
- `presence.py:1124-1126`: when `current_state == AWAY`, Nobody-home returns `None`, so no transition happens.
- So plan mechanisms (3) restore returns False and (4) restore not yet run both leave the house in AWAY **without any inference emission**. D1/D2 suppress only a home-like → AWAY emission. That emission only exists when restore SUCCEEDED, and in that case R2-2 deferral (`presence.py:6825-6833`, predicate `:2331-2343`) already blocks it until settle. The only hole left for D1 is the post-settle warm-up. Nothing in §Evidence shows that hole firing.
- Fix: the plan must address the default-AWAY initial state directly, e.g. initial state = unknown/hold, or "do not treat a non-restored default AWAY as authoritative until settle + warm-up". Otherwise it must show from `house_state_log` (not the sensor) that a home-like → away **transition row** happened after settle.

### CRITICAL-2: the evidence base is display data, and a display fallback reads "away"
- `sensor.py:5506-5511` `PresenceHouseStateSensor.native_value`: `if manager is None: return "away"`. Before the parent entry publishes `hass.data[DOMAIN]["coordinator_manager"]` (`__init__.py:4310`), the sensor reports "away". After that it reports the default AWAY until restore applies.
- The probe's "away at -3.2 → home_day at -1.6" rows, which land inside `async_setup` before `homeassistant_start`, are exactly what this fallback and default would produce **with no inference AWAY at all**. 8/14 "dirty" boots could be a recorder artifact.
- The plan's D0 item 4 (`house_state_log` rows) is the right oracle, but D0 is framed as "did it re-fire". It must first **re-classify the existing 14 boots** against `house_state_log` and the restore journal lines (`manager.py:684-700`). Run that before any build. If it finds zero `away` transition rows in those windows, D1-D3 are moot. The only real case left would then be the 10-03 62-min stick, most likely a no_record/stale restore leaving default AWAY (see CRITICAL-1).

### HIGH-1: mechanism (4) "restore ordering hazard" is WRONG
- `manager.py:470-486`: `_async_restore_house_state()` is awaited BEFORE the `for coordinator ... await coordinator.async_setup()` loop (`:493-494`). Presence's census/motion listeners only exist after its own `async_setup`, so no inference tick can run before restore. Remove (4), or restate it as the display-ordering effect in CRITICAL-2.

### HIGH-2: the D3 discharge semantics are inverted or ambiguous
- D3 says to "clear [counter] on first disagreement", and §Suppression says "On any intervening tick where inputs disagree ... the fence releases immediately." Released on disagreement, a single census>0 flicker followed by census=0 would allow immediate AWAY. That inverts the intent: disagreement should **reset** the counter to N, not release the fence. The builder will implement one or the other at random. Pick one and test it.
- I-BAF-2 uses `CONF_BOOT_AWAY_WARMUP_TICKS × tick_period`, but inference is event-driven plus retry (`_retry_unsub`, `presence.py:~6840`) and has no fixed tick period. A "tick" is undefined. With an empty house and no events, the counter never decrements, and the 180 s wall-clock backstop is the only real discharge. State that explicitly.

### HIGH-3: the invariant and the deliverables disagree
- I-BAF-1 says that after warm-up, AWAY "requires (a) sustained_external_empty OR (b) ... for N ticks". D1-D3 implement only a time and tick window. After it, Nobody-home fires as before on a single tick, with no (a)/(b) gate. Either add the gate as a deliverable (a real behaviour change to legitimate AWAY, which needs its own analysis) or drop it from the invariant.
- The discriminator expects a genuine-empty AWAY with `trigger = sustained_external_empty`. `sustained_external_empty` is an `infer()` kwarg, not a trigger string. The trigger comes from the `_run_inference` caller (`census_update`, etc.), so this live criterion cannot be observed as written.

### HIGH-4: genuine-away suppression is not bounded for HVAC or security
- If everyone left during or just before a restart, the fence delays AWAY by up to max(60 s settle, N events, 180 s backstop). That bound is acceptable but unstated as a security/HVAC consequence. Security arming and away-setback delays need one line of acceptance.
- The case where a genuine AWAY was restored (`current==AWAY`) is unaffected, which is correct. Say so.
- The 10-08 12:03Z genuine pre-stop AWAY must appear as a test fixture, so the fence is proven not to block it.

### MEDIUM-1: cited lines checked
| Claim | Status |
|---|---|
| presence.py:1124-1128 Nobody-home | CONFIRMED |
| :1167-1178 path α | CONFIRMED (predicate 1167-1172, return 1178) |
| :1241-1285 path β | CONFIRMED (immediate_engage 1241-1244, return 1285) |
| :6825 deferral | CONFIRMED (call 6825, transition 6834) |
| :2331-2343 predicate | CONFIRMED |
| house_state.py:383-428 restore | CONFIRMED (368-433); reasons also include `restore_disabled` and `unparseable_saved_at`, which the plan omits |
| manager.py:670-701 | CONFIRMED; the "ordering hazard" inference is WRONG (HIGH-1) |
| :6780-6816 cooldown | CONFIRMED |
| :5519-5543 bypass | CONFIRMED |
| "sensor.py:7891" read-only | WRONG FILE: it is presence.py:7887-7893, and it is a **writer** (`set_override(house_state)` at 7888). It is operator-driven, so it is not an inference path, but the "read-only" label is wrong. |
| §6 cooldown "proven mechanism" for the 62-min stick | UNPROVEN: no log or ground-truth citation. Downgrade to hypothesis. |

### MEDIUM-2: the AWAY writer enumeration is incomplete
The plan lists only the three `infer()` returns. Full writer set on develop:
- `infer()` 1128 / 1178 / 1285, which reach `transition()` at presence.py:6834.
- `set_override` at `__init__.py:5846` (service), `select.py:278`, and `presence.py:7888`.
- `apply_restored` at `manager.py:679`, which can restore a persisted `away`.
- Machine default `initial_state=AWAY` (`house_state.py:153`). This is the one that matters (CRITICAL-1).
- `force_state` (`house_state.py:321`) has no callers on develop.

Overrides are operator intent and are correctly out of scope, but the plan must list them as such.

### MEDIUM-3: knobs and acceptance criteria
- D4 says the options "round-trip through flow + RestoreEntity". Options-flow fields do not use RestoreEntity, so this criterion is untestable as written.
- The kill switch "restores v5.103.50 behaviour". Name the commit or base instead.
- D5's "no NM backstop fire in first week" is a soak watch, which the No-Soak rule prohibits. Replace it with the trip-wire alone.
- Knob ladder: the warm-up ticks in the options flow is acceptable. With HIGH-2, consider a wall-clock seconds knob instead, because "ticks" has no stable meaning.

### LOW-1: Tier
Tier 2-DB elevated is defensible. If CRITICAL-1's fix changes the machine's initial state or restore semantics (a shared primitive feeding HVAC, security, music and the forecaster), raise it to **Tier 3**.

## Must-fix before build
1. CRITICAL-2: re-classify the 14 boots from `house_state_log` plus the restore journal lines (D0 retargeted to the existing boots, not only the next boot).
2. CRITICAL-1: re-aim the fence at the default-AWAY / non-restored path, or prove a post-settle home → away transition exists.
3. HIGH-1: drop mechanism (4).
4. HIGH-2: define tick, and reset vs release on disagreement.
5. HIGH-3: reconcile the invariant with D1-D3, and fix the discriminator trigger string.
6. HIGH-4: state the genuine-away delay bound and add a genuine-away fixture.
