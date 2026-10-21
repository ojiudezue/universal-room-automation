# PLANNING — Camera detector-hung trip-wire (re-scope of CAMERA-SILENT-PRODUCER-TRIPWIRE-1)

Status: plan, not reviewed. Tier 2 (one adversarial plan review before build). Read-only scoping, 2026-10-21 overnight.
Presence-adjacent (camera/census input health). Read for this plan: `PLANNING_frigate_down_tripwire.md` (Rev 2, shipped),
the card body in full, `optimization.py` evaluators. Not HVAC.

## 0. Verdict up front

**SIMPLIFY.** Do not rebuild the fleet-silence counter. The residual the shipped trip-wire misses is the
**detector hang**, and the cheapest discriminator for it is a **frozen stat**: `sensor.frigate_detection_fps_2`
normally changes value about every 20 s (live 2026-10-20 19:00Z to 10-21 07:30Z: **2,124 state changes in 12.5 h**).
A frozen-value window of about 15 min is short enough that HA restarts do not starve it (measured restart gaps
on the worst day, 09-18: 12 m, 89-367 m; and a frozen value stays frozen after boot, so the dwell simply
re-accumulates). So this needs **no recorder query and no persisted state**, which removes the defect that sank build 4f4183543.
The rejected fleet-quiet predicate (zero ON-transitions for 6 h) is PARKED (§8).

## 1. Institutional context verified

### Shipped coverage, from code
- `compute_camera_input_dark_frame` at `camera_census.py:180-258`: `dark_now = denominator>0 AND (fraction_unavailable >= 0.75 OR frigate_status_2 in {unavailable,unknown,"",none})`. It looks **only at availability**.
  **A hung detector leaves every person_count sensor holding a valid numeric state and status_2 = running, so `dark_now` is False. It does not catch the hang.**
- `_evaluate_camera_input_dark_dimension` at `optimization.py:2816-2990`: dwell `CAMERA_INPUT_DEGRADED_DWELL_S=270` (`const.py:4402`), `BOOT_SETTLE_S=180`, fleet latch `_camera_input_dark_fired` (`optimization.py:621`), dedup `("camera_input_dark","fleet")`, registry entry at `optimization.py:1073`.
- `_evaluate_camera_stuck_dimension` at `optimization.py:2020-2095`: fires per camera on `_person_occupancy_2` **ON** for longer than `CAMERA_STUCK_ON_THRESHOLD_S`. During a hang, frozen-OFF sensors (16 of 24 on 09-25) never trip it. Frozen-ON sensors would, one finding per camera, phrased as "stuck sensor", and only in the digest (see next item). **It gives partial, misattributed coverage at best.**
- NM routing: `_notify_if_severe` at `optimization.py:5495-5535` defers HIGH to the digest unless the dimension is allowlisted. The **only** exemption is `dedup_key[0]=="camera_input_dark"`. A new kind needs its own exemption or it reports a hang up to 24 h late (the same issue as the old B-3 finding).

### Greps (run 2026-10-21)
- `grep -rn detection_fps custom_components/` → **0 hits**. No consumer or producer of the Frigate stat exists. **NEW.**
- `grep -in "frozen\|FROZEN_" const.py` → only `frozenset` and unrelated HVAC/fan freeze notes. No frozen-stat constant. **NEW.**
- `grep get_significant_states` → `hvac_override.py:20,319,6468` (recorder history use exists). Not needed, see §0.
- `grep camera_input_dark|camera_stuck` const/optimization/binary_sensor → the sites listed above. **REUSE.**
- Live entity: `sensor.frigate_detection_fps_2` exists, `state_class: measurement`, unit fps, state 45 at 02:19 CDT.

### REUSE-or-BUILD per piece
| Piece | Verdict | Where |
|---|---|---|
| Evaluator registry slot | REUSE | `optimization.py:1058-1074` |
| Finding shape (SENSOR_HEALTH, house, severity high, dedup_key, latch) | REUSE | mirror `optimization.py:2962-2990` |
| Boot-settle constant | REUSE `BOOT_SETTLE_S` | `const.py` near 4403 |
| Inert-no-Frigate branch | REUSE pattern | `optimization.py:2873-2886` |
| NM HIGH→digest exemption | EXTEND (add the second kind to the existing outer guard) | `optimization.py:5522-5527` |
| Diagnostic surface | EXTEND attributes on existing `binary_sensor.ura_coordinator_manager_camera_input_dark` (`binary_sensor.py:3276-3335`); **no new entity** | |
| Frozen-stat evaluator + 2 constants + 3 state fields | **BUILD (NEW)** | only new code |

Prior plans consulted: `PLANNING_frigate_down_tripwire.md` (its non-goals exclude this mode: no Coral/Frigate-side work, no camera_stuck change); the card's REVIEWED_2026_09_17 findings (A-HIGH-1 RAM reset, A-HIGH-2 min-fleet, A-MED-1 disappearance, A-MED-2 vacation, A-MED-3a hollow anchor, B-3 digest). This design avoids each one (§6).

**Config-first:** no existing knob, option or HA setting raises an alert for a hung Frigate detector. Frigate's own stats are not wired into URA at all. Code is needed.

## 2. Falsifiable invariant

> **I1:** If `sensor.frigate_detection_fps_2` holds a valid numeric state whose *value* has not changed for
> ≥ `CAMERA_DETECTOR_FROZEN_S` of continuous observed time after boot settle, then exactly one
> `camera_detector_hung` finding is emitted and routed to NM (not to the digest) within one optimizer
> cycle (300 s), regardless of how many HA restarts happened earlier in the episode.
> **I2 (no false fire):** while the value changes at least once per `CAMERA_DETECTOR_FROZEN_S`, no such finding is emitted.

Reviewer D should break I1 with a restart cadence shorter than `FROZEN_S + BOOT_SETTLE_S` (that is a legal
reachable config; the answer is the restart-gap measurement in D0), and break I2 with a healthy fleet that is
legitimately constant. The constant case is the open empirical question that D0 must close: overnight with
no motion anywhere, fps may sit at 0.

## 3. Producer / consumer

- **Producer:** Frigate `/api/stats` reaches HA over MQTT/HA-integration polling as `sensor.frigate_detection_fps_2` (fleet-sum detection fps). Healthy cadence is about 20 s and values vary 23-67 at 02:00 CDT. Dependency health: it is the same Frigate integration entry as the person sensors. When Frigate is fully down, the value goes `unavailable` and camera_input_dark owns that case. The new check must **skip** non-numeric states so the two checks never both fire on one episode.
- **Unverified producer assumption (D0 gate):** the card says fps was "frozen" during the 09-29 hang. Recorder retention (earliest about 10-11) no longer covers 09-29, so the claim cannot be re-checked from HA today. D0 must find whether *healthy* fps is ever constant for ≥ 15 min (for example a nightly 0). If it is, the predicate becomes "constant AND value > 0", or the plan falls back to the coral `inference_speed` stat.
- **Consumer:** `_notify_if_severe` (trust: wake the operator to `docker restart frigate`). The binary_sensor attributes are display only. Nothing else reads it. No presence or census consumer by design (non-goal).

## 4. Emission/decision-site enumeration
1. New `_evaluate_camera_detector_hung_dimension`, added to the registry next to `optimization.py:1073`. This is the only emit site.
2. `_notify_if_severe` exemption at `optimization.py:5522`. Widen the tuple test to `{"camera_input_dark","camera_detector_hung"}`, keeping the outer-guard shape so the `test_nm_cycle_a2` mutation anchor still holds.
3. `binary_sensor.py:3305-3335` attribute block: add `detector_frozen_s`, `detector_hung_fired`. The binary sensor's on/off truth stays the census latch, so its semantics do not change.
grep after build: `grep -rn "camera_detector_hung" custom_components/` must return exactly sites 1-3 plus const.

## 5. Deliverables

### D0 — measurement probe (go/no-go gate; read-only, ura-prober)
Over the full recorder retention for `sensor.frigate_detection_fps_2` (plus any `sensor.frigate_*coral*inference_speed*`): the distribution of longest same-value runs per day, split by value==0 vs >0, and how those runs align with HA restart times and with the 10-11..10-21 camera_input_dark episodes.
- **GO** if healthy runs with the same value > 0 never reach 15 min. The threshold then becomes `max_healthy_run × 3`, floor 10 min.
- **Adjust** if healthy runs at 0 exist: gate the predicate on value > 0 and re-check.
- **NO-GO** (park the card, §8) if healthy runs with a non-zero constant value are common.
- Also record whether `last_changed` of the fps sensor matches value changes, or whether repeated identical values update only `last_reported`. The evaluator tracks the value itself and does not trust `last_changed`.

**D0 RESULT (run 2026-10-21 ~02:25 CDT, overnight pass, read-only; HA recorder `/config/home-assistant_v2.db` via `ssh ha "python3 -"`, script `.claude/scratch/fps_runs.py`): GO.**
- Window 10-13 04:12 -> 10-21 02:21 (full retention for this entity): 32,315 state rows, 32,314 same-value runs.
- Longest same-value run with value > 0: **5.0 min** (133 on 10-13 11:28; 57 on 10-14 01:15 - an overnight run, so quiet nights do NOT hold a constant value). Non-zero runs >= 10 min: **0**; >= 15 min: **0**.
- Value == 0: only 3 runs, longest 2.0 min (10-15 23:14, adjacent to an `unavailable` blip). No "nightly 0" plateau, so the predicate does not need a value > 0 gate; keep it value-agnostic (a hang that drops to a constant 0 is also caught).
- `unavailable` runs max 2.9 min (handled by the shipped camera_input_dark path, not this one).
- Threshold: max_healthy_run x 3 = 15 min -> `CAMERA_DETECTOR_FROZEN_S = 900` confirmed (floor 10 min satisfied).
- HA writes no state row for an identical value, so a frozen stat shows as an absence of rows; the evaluator must track the value + its own first-seen timestamp in memory (resets on restart, which is fine: 15 min fits between restarts and a frozen value stays frozen after boot).
- NOT verifiable: no detector-hang episode lies inside retention (last hang ended 10-08 12:14), so the claim that fps freezes (rather than, e.g., oscillating at low values) during a hang is still the card's 09-29 observation, not re-measured. Acceptance must include a staged check (e.g. stop the Frigate detector / pause the container in daytime) or accept this as the first live hang.

### D1 — frozen-stat evaluator
The evaluator remembers `(last_value, value_since)` in RAM. On each tick: if the state is non-numeric, reset and return (camera_input_dark owns that). If the value differs, reset `value_since=now`. If `now - max(value_since, boot_ref + BOOT_SETTLE_S) ≥ FROZEN_S` and the latch is not set, fire once. The latch clears on the first value change.
- **Verify:** fixture where fps is constant (value>0) for FROZEN_S+cycle → exactly one finding, `dedup_key=("camera_detector_hung","fleet")`, `payload.kind="camera_detector_hung"`, description says "docker restart Frigate".
- **Verify (discriminating):** same fixture but `unavailable` → zero detector_hung findings, and camera_input_dark fires instead. This separates hang from down.
- **Verify:** value changes every 20 s for 2 h → zero findings. A constant value, followed by a restart (coordinator rebuilt), followed by the same constant value → fires FROZEN_S+BOOT_SETTLE after boot. This is the restart-survival test and must drive real cycles, not an `inspect.getsource` grep (Bug Class #62).
- **Verify:** fps entity missing entirely while denominator>0 → log once and do not fire. Total disappearance belongs to camera_input_dark, which already counts missing as unavailable.
- **Test:** `test_detector_hung_fires_once_on_frozen_value`, `test_detector_hung_silent_when_unavailable`, `test_detector_hung_survives_coordinator_rebuild`, `test_detector_hung_clears_on_change`, `test_detector_hung_kill_switch`, `test_detector_hung_pages_not_digest` (drives `_notify_if_severe`).
- **Mutation:** remove the latch → the once-test goes red. Remove the NM exemption → the pages-test goes red.

### D2 — NM exemption + attributes (sites 2-3)
- **Live:** after restart, `binary_sensor.ura_coordinator_manager_camera_input_dark` carries `detector_frozen_s` < 60 most of the time and `detector_hung_fired=false`. Organic acceptance: the next Frigate degrade produces an NM titled sensor_health / camera_detector_hung within FROZEN_S+300 s, **and** the person sensors show zero transitions over the same window (the discriminator that this was a hang and not a quiet fps). It must NOT fire on an ordinary day. The one-shot disposition query is the `notification_log` rows for the kind over 7 days, with 0 expected absent a hang.

## 6. Prior DO-NOT-SHIP findings, disposition
- A-HIGH-1 RAM reset: the window is minutes, not hours, and the freeze persists across restarts. Proven by `test_..._survives_coordinator_rebuild`.
- A-HIGH-2 min fleet: one fleet-level stat, nothing to shrink. N/A.
- A-MED-1 disappearance: camera_input_dark already covers it.
- A-MED-2 vacation-empty house: fps is detection load, which comes from motion and continuous object tracking, not from occupancy. D0 checks the quiet-night case.
- A-MED-3a hollow anchor: replaced by cycle-driven tests.
- B-3 digest: exempted (D2).

## 7. Knobs
| Knob | Default | Rung | Why / kill switch |
|---|---|---|---|
| `CAMERA_DETECTOR_FROZEN_S` | 900 (set by D0) | module const | A fitted number from measured cadence; retuning needs review. `0` disables. |
| `CAMERA_DETECTOR_FPS_ENTITY` | `"sensor.frigate_detection_fps_2"` | module const | Same `_2` convention as the hardcoded `sensor.frigate_status_2` (`camera_census.py:238`). A second-home rollout makes this a candidate for the options flow later. |
| `BOOT_SETTLE_S` | 180 | REUSED | |

## 8. Non-goals / parked
- **PARKED: fleet zero-ON-transition predicate** (the original card design, which needs recorder history or persisted timestamps). Revival trigger: a recorded episode where person detection went fleet-silent while detection_fps kept changing, i.e. the hang is somewhere fps does not see.
- **DROP: restart-time flapping of camera_input_dark.** About 31 episodes of 10-40 s, display only. The fire path is boot-settled and the dwell is 270 s, which is why only one NM row appeared in 14 days. Display-only noise, no consumer. A residual card is not worth it. If a consumer of the binary sensor's on-state ever appears, apply BOOT_SETTLE_S to the census latch then.
- No per-camera silence, no Frigate auto-restart, no change to camera_stuck or the camera_input_dark predicate, no new entity, no presence/census consumption.

## 9. Tier
**Tier 2** (adds one evaluator and touches the shared NM gate, notification only, with no actuation). One plan review before build. Builder: ura-builder. Two framing-disjoint reviews (A correctness+edge cases; B restart/lifecycle + NM gate non-regression) plus a mutation drill. The trigger for raising it: none. Reconsider if D1 ever gains a presence consumer.

## 10. Marginal benefit
The shipped trip-wire covers host-down (09-25..27 45 h, 10-06 24 h). It covers **zero** of the detector-hang episodes (09-29 39 h; 09-20..25 up to 74.7 h), which are the dominant and longest outages, and the fix is a 30 s operator docker restart. Marginal cost is about 60 LoC plus one guard widening, with no persistence, recorder query or new entity. This clearly pays, conditional on D0. If D0 shows a legitimately constant fps, the next-cheapest signal is coral inference speed. If that fails too, PARK.
