# PLANNING — Camera detector-hung trip-wire (re-scope of CAMERA-SILENT-PRODUCER-TRIPWIRE-1)

Status: **Rev 2**, plan review folded in (FIX-PLAN, `docs/reviews/plan-review/PLAN_REVIEW_camera_detector_hung_tripwire.md`). Tier 2. Read-only scoping, 2026-10-21 overnight.

**Changelog**
- Rev 1 (2026-10-21): initial re-scope (SIMPLIFY to a frozen-stat check). D0 RESULT appended by the coordinator: GO, FROZEN_S=900.
- Rev 2 (2026-10-21): plan review folded in. HIGH: added the per-cycle findings-cap exemption (`optimization.py:5363-5384`) as emission site 4, and fixed the post-build grep check. MED: I1 restated as one page per process lifetime per episode, with re-page after a rebuild accepted, plus a new-instance re-arm test. MED: fps entity resolved through the entity registry (Frigate config entry, `detection_fps` unique_id), not the `_2` literal. MED: any non-numeric state resets the dwell, and `last_changed` is never trusted. LOW: staged daytime detector pause is a REQUIRED live check. LOW: `FROZEN_S<=0` returns no findings, with a test. Added a §5a builder brief.
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
> ≥ `CAMERA_DETECTOR_FROZEN_S` of continuous observed time after boot settle (dwell anchored at the first
> numeric value this process saw), then exactly **one** `camera_detector_hung` finding **per process lifetime
> per episode** is emitted, survives the per-cycle findings cap, and is routed to NM (not to the digest) within
> one optimizer cycle (300 s) of the dwell completing.
> **Accepted consequence (operator pick, Rev 2):** the latch and NM dedup are RAM-only (`optimization.py:5555`). A
> restart or CM rebuild during a long hang re-arms and re-pages after `FROZEN_S + BOOT_SETTLE_S` (about 18 min). This
> acts as a reminder, and restarts are at most a few per day. No `notification_log` seeding.
> **I2 (no false fire):** while the value changes at least once per `CAMERA_DETECTOR_FROZEN_S`, no such finding is emitted.

Reviewer D should break I1 with a restart cadence shorter than `FROZEN_S + BOOT_SETTLE_S` (that is a legal,
reachable config: the page is late, not lost, because the dwell re-accumulates after each boot), with a cap-saturated
cycle (site 4), and with an `unknown` boot state followed by the pre-boot value. Break I2 with a healthy fleet that is
legitimately constant. D0 closed that question: the longest healthy run with an unchanged value is 5.0 min.

## 3. Producer / consumer

- **Producer:** Frigate `/api/stats` reaches HA over MQTT/HA-integration polling as the Frigate config entry's `detection_fps` sensor (today `sensor.frigate_detection_fps_2`; fleet-sum detection fps). **Resolution (Rev 2):** resolve the entity_id at evaluation time through the entity registry: an entry whose `platform == "frigate"`, `domain == "sensor"`, and `unique_id` ends with `CAMERA_DETECTOR_FPS_UNIQUE_ID_SUFFIX` (`":sensor_fps:detection"`, verified against the live registry at build; per-camera fps sensors end `_detection` with no colon and do not match). Never use the `_2` literal (IDENTITY_FUSION_CAMERAS_MANUAL `_2` rules). If none resolves, or more than one does, log once at INFO (`camera_detector_hung_inert_unresolved`) and stay inert. The builder must verify the real unique_id shape from the live `core.entity_registry` before coding the suffix, and record it in the test fixture. Healthy cadence is about 20 s and values vary 23-67 at 02:00 CDT. Dependency health: it is the same Frigate integration entry as the person sensors. When Frigate is fully down, the value goes `unavailable` and camera_input_dark owns that case. The new check must **skip** non-numeric states so the two checks never both fire on one episode.
- **Unverified producer assumption (D0 gate):** the card says fps was "frozen" during the 09-29 hang. Recorder retention (earliest about 10-11) no longer covers 09-29, so the claim cannot be re-checked from HA today. D0 must find whether *healthy* fps is ever constant for ≥ 15 min (for example a nightly 0). If it is, the predicate becomes "constant AND value > 0", or the plan falls back to the coral `inference_speed` stat.
- **Consumer:** `_notify_if_severe` (trust: wake the operator to `docker restart frigate`). The binary_sensor attributes are display only. Nothing else reads it. No presence or census consumer by design (non-goal).

## 4. Emission/decision-site enumeration
1. New `_evaluate_camera_detector_hung_dimension`, added to the registry next to `optimization.py:1073`. This is the only emit site.
2. `_notify_if_severe` exemption at `optimization.py:5522`. Widen the tuple test to `{"camera_input_dark","camera_detector_hung"}`, keeping the outer-guard shape so the `test_nm_cycle_a2` mutation anchor still holds.
3. `binary_sensor.py:3305-3335` attribute block: add `detector_frozen_s`, `detector_hung_fired`. The binary sensor's on/off truth stays the census latch, so its semantics do not change.
4. **(Rev 2, review HIGH)** Per-cycle findings-cap exemption `_is_camera_input_dark` at `optimization.py:5363-5384` (cap `OPTIMIZER_MAX_FINDINGS_PER_CYCLE`). Widen it to the same two-kind set. If this site is missed, a saturated cycle drops the finding after the latch is already set, and no page is ever sent (Bug Class #53).

**Post-build grep check:** `grep -rn "camera_detector_hung" custom_components/` must hit the evaluator (site 1), the NM guard (site 2), the cap exemption (site 4), and const. Site 3 uses attribute names, so check it with `grep -n "detector_hung_fired\|detector_frozen_s" custom_components/universal_room_automation/binary_sensor.py`. Prefer a single shared module-level tuple, for example `_FLEET_ONESHOT_KINDS = ("camera_input_dark", "camera_detector_hung")`, read by both sites 2 and 4. Then also `grep -n _FLEET_ONESHOT_KINDS` must show exactly the definition plus 2 reads.

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
The evaluator remembers `(last_value, value_since)` in RAM. Exact per-tick order:
1. `if CAMERA_DETECTOR_FROZEN_S <= 0: return []` (kill switch; nothing else runs).
2. Resolve the entity through the registry (§3). If it is unresolved, set `last_value = value_since = None`, log once, and return [].
3. Read the state. If it is missing or non-numeric (`unknown`, `unavailable`, empty, or fails `float()`), set `last_value = value_since = None` and return []. That case belongs to camera_input_dark. **The dwell therefore starts at the first numeric value observed after boot. No pre-boot value is ever carried over, and `last_changed`/`last_reported` are never read.**
4. If `last_value is None` or the value differs from `last_value`: set `last_value = value`, `value_since = now`, and clear the latch.
5. `elapsed = now - max(value_since, boot_ref + BOOT_SETTLE_S)`. If `elapsed ≥ FROZEN_S` and the latch is not set, set the latch and emit one finding. The predicate is value-agnostic, per D0: a constant 0 counts too.
- **Verify:** fixture where fps is constant (value>0) for FROZEN_S+cycle → exactly one finding, `dedup_key=("camera_detector_hung","fleet")`, `payload.kind="camera_detector_hung"`, description says "docker restart Frigate".
- **Verify (discriminating):** same fixture but `unavailable` → zero detector_hung findings, and camera_input_dark fires instead. This separates hang from down.
- **Verify:** value changes every 20 s for 2 h → zero findings. A constant value, followed by a restart (coordinator rebuilt), followed by the same constant value → fires FROZEN_S+BOOT_SETTLE after boot. This is the restart-survival test and must drive real cycles, not an `inspect.getsource` grep (Bug Class #62).
- **Verify:** fps entity absent from the registry → one INFO log, zero findings across many ticks, and no exception.
- **Verify:** registry resolution follows the unique_id. If the fixture renames the entity_id to `sensor.frigate_detection_fps` (no `_2`) with the same unique_id, the check still fires.
- **Verify (boot):** `unknown` for 2 ticks, then a constant numeric value → fires only `FROZEN_S` after the first numeric tick (and not before `boot_ref + BOOT_SETTLE_S + FROZEN_S`). An `unavailable` blip mid-dwell restarts the dwell.
- **Verify (cap):** a cycle with more than `OPTIMIZER_MAX_FINDINGS_PER_CYCLE` high findings plus the hung finding → the hung finding survives the cap.
- **Test:** `test_detector_hung_fires_once_on_frozen_value`, `test_detector_hung_silent_when_unavailable`, `test_detector_hung_new_instance_rearms_and_fires_once` (builds a **new** OptimizationCoordinator instance against the same frozen state; asserts exactly one finding from the new instance after `FROZEN_S + BOOT_SETTLE_S`, and zero before), `test_detector_hung_clears_on_change`, `test_detector_hung_kill_switch_zero_and_negative` (`FROZEN_S` set to 0 and to -1 → `[]` even with a frozen value for hours), `test_detector_hung_non_numeric_resets_dwell`, `test_detector_hung_resolves_via_registry_unique_id`, `test_detector_hung_inert_when_unresolved`, `test_detector_hung_survives_findings_cap`, `test_detector_hung_pages_not_digest` (drives `_notify_if_severe`).
- **Mutation:** remove the latch → the once-test goes red. Remove the NM exemption (site 2) → the pages-test goes red. Remove the cap exemption (site 4) → the cap-test goes red. Make step 3 skip the reset → the non-numeric test goes red. Restore and `git status` clean after each drill.

### D2 — NM exemption + attributes (sites 2-3)
- **Live (passive):** after restart, `binary_sensor.ura_coordinator_manager_camera_input_dark` carries `detector_frozen_s` < 60 most of the time and `detector_hung_fired=false`.
- **Live (REQUIRED, operator-run, daytime only, not during sleep):** a staged detector pause. Stop or pause the Frigate detector so that the process, status, and camera fps stay up (for example, pause the detector in Frigate, or give the Coral a short `docker pause`). Then observe: (a) whether `detection_fps` freezes, oscillates, or goes `unavailable`. This is the first measurement of the hang mechanism, which D0 could not verify. (b) If it freezes, a `camera_detector_hung` NM page arrives within `FROZEN_S + 300 s`. If it goes `unavailable`, camera_input_dark fires instead, and this check is confirmed silent. If it oscillates, this check cannot see the hang: record the result and PARK per §10. Restore Frigate (30 s docker restart) right after. The cycle does not close without this row in the README validation table.
- **Live (organic):** the next Frigate degrade produces an NM titled sensor_health / camera_detector_hung within FROZEN_S+300 s, **and** the person sensors show zero transitions over the same window (the discriminator that this was a hang and not a quiet fps). It must NOT fire on an ordinary day. The one-shot disposition query is the `notification_log` rows for the kind over 7 days, with 0 expected absent a hang.

## 5a. Builder brief — likely mistakes (from plan review)
1. **Missing the cap site (site 4).** Both exemptions must be widened: the NM guard AND `_is_camera_input_dark` in the findings cap. Use one shared tuple.
2. **NM guard shape.** Widen the *outer* `dedup_key[0] in KINDS` tuple test that wraps `if should_defer_high_to_digest(...)`. Do NOT add a conjunction inside `should_defer_high_to_digest` or its predicate. The `test_nm_cycle_a2` mutation anchor depends on that line staying verbatim. Run that test after the change.
3. **Trusting `last_changed`/`last_reported`.** HA writes no row for an identical value, and both fields reset on restart. Track the value and your own first-seen timestamp only.
4. **Carrying a pre-boot value.** Any non-numeric read (including boot-time `unknown`) resets to `None`. The dwell starts at the first numeric value.
5. **A rebuild test that reuses the same instance.** The re-arm test must construct a NEW coordinator object. Resetting fields on the old one proves nothing about the lifecycle.
6. **Kill switch.** `<= 0` must short-circuit before the elapsed comparison, because `elapsed >= 0` is always true.
7. **Hardcoding `_2`.** Resolve through the registry by unique_id suffix.
8. **Wire-in anchor.** Tests must drive real optimizer cycles through the registry entry (site 1). A source grep is not a test (Bug Class #62).

## 6. Prior DO-NOT-SHIP findings, disposition
- A-HIGH-1 RAM reset: the window is minutes, not hours, and the freeze persists across restarts, so the page is delayed, never lost. Re-paging after a rebuild is accepted (I1). Proven by `test_detector_hung_new_instance_rearms_and_fires_once`.
- A-HIGH-2 min fleet: one fleet-level stat, nothing to shrink. N/A.
- A-MED-1 disappearance: camera_input_dark already covers it.
- A-MED-2 vacation-empty house: fps is detection load, which comes from motion and continuous object tracking, not from occupancy. D0 checks the quiet-night case.
- A-MED-3a hollow anchor: replaced by cycle-driven tests.
- B-3 digest: exempted (D2).

## 7. Knobs
| Knob | Default | Rung | Why / kill switch |
|---|---|---|---|
| `CAMERA_DETECTOR_FROZEN_S` | 900 (D0: 3 × 5.0 min max healthy run) | module const | A fitted number from measured cadence; retuning needs review. **`<= 0` → evaluator returns `[]` before any read** (tested at 0 and -1). |
| `CAMERA_DETECTOR_FPS_UNIQUE_ID_SUFFIX` | `":sensor_fps:detection"` (verified against the live registry, 2026-10-21) | module const | Registry match key. Replaces the Rev 1 `_2` literal entity_id. Unresolved → inert, with one log. |
| `BOOT_SETTLE_S` | 180 | REUSED | |

## 8. Non-goals / parked
- **PARKED: fleet zero-ON-transition predicate** (the original card design, which needs recorder history or persisted timestamps). Revival trigger: a recorded episode where person detection went fleet-silent while detection_fps kept changing, i.e. the hang is somewhere fps does not see.
- **DROP: restart-time flapping of camera_input_dark.** About 31 episodes of 10-40 s, display only. The fire path is boot-settled and the dwell is 270 s, which is why only one NM row appeared in 14 days. Display-only noise, no consumer. A residual card is not worth it. If a consumer of the binary sensor's on-state ever appears, apply BOOT_SETTLE_S to the census latch then.
- No per-camera silence, no Frigate auto-restart, no change to camera_stuck or the camera_input_dark predicate, no new entity, no presence/census consumption.

## 9. Tier
**Tier 2** (adds one evaluator and touches the shared NM gate, notification only, with no actuation). One plan review before build. Builder: ura-builder. Two framing-disjoint reviews (A correctness+edge cases; B restart/lifecycle + NM gate non-regression) plus a mutation drill. The trigger for raising it: none. Reconsider if D1 ever gains a presence consumer.

## 10. Marginal benefit
The shipped trip-wire covers host-down (09-25..27 45 h, 10-06 24 h). It covers **zero** of the detector-hang episodes (09-29 39 h; 09-20..25 up to 74.7 h), which are the dominant and longest outages, and the fix is a 30 s operator docker restart. Marginal cost is about 60 LoC plus one guard widening, with no persistence, recorder query or new entity. This clearly pays, conditional on D0. If D0 shows a legitimately constant fps, the next-cheapest signal is coral inference speed. If that fails too, PARK.
