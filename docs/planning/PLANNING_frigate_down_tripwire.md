# PLANNING — Frigate-Down Tripwire + Degraded-Input Consumption (Rev 2)

Status: DRAFT Rev 2 (incorporates plan review 2026-10-09; ready for re-review)
Tier: **Tier 2** (feature cycle; one new NM producer + wires existing `degraded_mode` to decision consumers). D2 (auto-reload) PARKED — see §9.

## 0. Problem (measured 2026-10-05 → 2026-10-08)

- Frigate HA integration (entry `01KM239Z8ZQWQTN1D9CV5JRA7V`, `https://192.168.13.18:8971`) hit `setup_retry` while the Frigate server was down (10-05 ~14:12 CDT).
- Frigate came back; the HA entry did NOT self-recover. All 24 `sensor.*_person_count` sensors stayed `unavailable` until a manual **Reload** on 10-08 12:14 — ~70 hours dark.
- URA's camera_census ran ~3 days with zero camera input. **Nothing in URA alerted the operator.** Previously carded as CAMERA-SILENT-PRODUCER-TRIPWIRE-1 (per-sensor stuck-ON path shipped v5.101.x) and PERIMETER-DETECTION-WENT-DARK-1 (recurrence tracker). Neither covers the *all-sensors-unavailable fleet-wide* failure mode: the stuck-ON evaluator only fires on cameras it still sees as ON for too long; `unavailable` doesn't trip it.
- Important nuance surfaced by plan review: census ALREADY detects this condition (`CensusResult.degraded_mode = True`), but the flag has zero decision consumers today — it is a display attribute at `sensor.py:3667` and nothing else. The gap is NM + consumer wiring, not detection.

## 1. Falsifiable invariant

> **If `>= CAMERA_INPUT_DEGRADED_FIRE_THRESHOLD` of the configured `sensor.*_person_count` entities (denominator = Frigate-legged cameras with a resolved `person_count_sensor`) are `unavailable` continuously for `>= CAMERA_INPUT_DEGRADED_DWELL_S`, OR `sensor.frigate_status_2` is `unavailable`/`unknown` for the same dwell, URA raises exactly ONE operator-visible NM notification per episode and `binary_sensor.ura_camera_input_degraded` reads `on`.** The binary_sensor state is driven by the EXISTING `CensusResult.degraded_mode` (sticky mirror), NOT a second latch. The NM one-shot latch is independent and governs notification de-duplication only. The flag CLEARS one tick after `degraded_mode` is False; the NM latch clears when the fleet-unavailable fraction drops below `CAMERA_INPUT_DEGRADED_CLEAR_THRESHOLD` (hysteresis). No fire on single-camera flap. No fire when denominator = 0 (Protect-only house). Boot transient (first `BOOT_SETTLE_S` after HA start / URA setup) suppressed; discharge = either the dwell timer completes post-settle or the fraction clears — never silently absorbed.

Discriminating observations (§6):
- 24/24 unavailable, 10 min → fires once; `off → on`; one NM row.
- 1/24 unavailable → no fire, binary_sensor off.
- 24/24 AVAILABLE but all reading `0` (empty house) → no fire, `degraded_mode` False, binary_sensor off. (This discriminates "quiet" from "dark".)
- Frigate down, Protect binary platforms up → `degraded_mode` True via `camera_census.py:1905`, binary_sensor on, NM fires. `camera_total` sourced from binary platform count.
- Denominator = 0 (no Frigate cameras configured; Protect-only 2nd-home) → inert, one-time `inert_no_frigate`-style log, no NM.

## 2. Institutional context verified

### Prior-art scan (REUSE/BUILD table — Rev 2)

| Piece | Verdict | Where (verified) |
|---|---|---|
| Fleet-wide `degraded_mode` detection (Frigate down OR all cameras unavailable) | **REUSE** | `camera_census.py:176` (dataclass field), set True at `:1905` (Frigate down, binary up) and `:1917` (all platforms unavailable); carried through `:1981`, `:2066`, `:5794`, `:5837`. Zero decision consumers today — only `sensor.py:3667` reads it as a display attribute. |
| Face-producer health reason (`frigate_down`) | REUSE as corroborating signal | `camera_census.py:3854` sets `_face_producer_health_reason = "frigate_down"` based on `sensor.frigate_status_2` / `binary_sensor.frigate_status_2` resolved via registry at `:3874-3876`. Exposed at `sensor.py:3654`. Use as OR-trigger alongside the fraction check. |
| Frigate `person_count` fleet enumeration | REUSE | `_camera_manager.get_all_frigate_cameras()` yields `CameraInfo` with `person_count_sensor` field (`camera_census.py:160`). `frigate_available` already computed per tick at `camera_census.py:1738-1802`. No need for a new `known_person_count_entities()` helper — expose a thin census accessor or compute inside census. |
| Per-sensor camera staleness tripwire | REUSE as sibling, NOT extend | `camera_stuck` evaluator at `domain_coordinators/optimization.py:1881` (registered `:935`, dedup via `OptimizationFinding.dedup_key = ("camera_stuck", cam_key)` at `:1951`). Also a second camera_stuck mechanism at `camera_census.py:2533-2705` firing NM through `_fire_camera_stuck_nm` at `:110`. New evaluator is a disjoint failure mode (stuck-ON vs. gone-dark). |
| Notification delivery + one-shot latch idiom | REUSE | `_camera_stuck_fired` latch pattern at optimization.py:1912, 1918, 1928. Emit through `OptimizationFinding` + `dedup_key=("camera_input_dark", "fleet")` — NOT a hand-rolled NM call. |
| Suppression / debounce idiom | REUSE | optimization.py camera_stuck latch; discharge on fraction-clear below hysteresis threshold. |
| `binary_sensor` scaffold | REUSE | `binary_sensor.py` already carries house-level diagnostic flags; add `CameraInputDegradedBinarySensor` under the CM entity set (fleet-scope, not per-room). State mirrors `CensusResult.degraded_mode` (sticky to one tick); attributes include fraction and NM-latch state so the two truths are visible side-by-side. |
| Boot-transient suppression (`BOOT_SETTLE_S`) | **NEW** | Rev-1 claimed "reuse if exists"; grep returns no matching constant. Mark NEW in `const.py`. See finding #7. |
| D1 enumeration / siting | **BUILD (one site)** | New evaluator sited in `domain_coordinators/optimization.py` next to `_evaluate_camera_stuck_dimension` (`:1881`); registered next to it at `:935`. Rationale for picking optimization over camera_census: emission + dedup + finding plumbing already exists there (`OptimizationFinding` + `dedup_key`), presence/perimeter already consume findings, and the evaluator READS from census (`frigate_available`, fleet via `_camera_manager.get_all_frigate_cameras()`) rather than re-enumerating. One source of truth for enumeration (census), one source of truth for emission (optimization). |

### Prior planning docs consulted
- `docs/planning/kanban.data.yaml` cards: `CAMERA-SILENT-PRODUCER-TRIPWIRE-1` (shipped per-sensor stuck-ON; producer-level staleness explicitly deferred — line 3724), `PERIMETER-DETECTION-WENT-DARK-1` (recurrence log), `PERIMETER-PHANTOM-XCORR-1` (unrelated pool phantom).
- `OPEN_THREADS_2026-09-25.md` — perimeter resilience thread.

### Memory bodies pulled
- `reference_frigate1_retired_2suffix_permanent` — F2 `_2` suffix mandatory; `_camera_manager` resolver handles this already.
- `project_frigate_mqtt_topic_collision` — don't conflate URL/MQTT health with HA-side setup state.
- `reference_protect_face_latency_async` — Protect vs Frigate domains are distinct; this plan touches only Frigate.
- `feedback_suppression_needs_discharge` — enforced in §5.
- `feedback_config_first_before_code` — see §2 config-first check.
- `feedback_tier2plus_prior_art_scan` — scan re-run per reviewer finding; corrections above.

### Design docs read
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` — canonical camera manual. Confirms `person_count` fleet is the right producer-level signal (not face/sublabel which have independent dropout modes). The degraded flag belongs at the camera-input layer, upstream of fusion. Confirms `degraded_mode` is the correct lever.

### Code locations surveyed (end-to-end)
- `custom_components/universal_room_automation/camera_census.py` — `CensusResult` (:170ff), degrade-mode branches (`:1891-1918`), `_face_producer_health_reason` + `frigate_status_2` resolver (`:3800-3903`).
- `domain_coordinators/optimization.py` — `_evaluate_camera_stuck_dimension` (`:1881`), registration (`:935`), `OptimizationFinding` + `dedup_key` plumbing (`:1951`).
- `domain_coordinators/presence.py` — guest/vacancy gate (`:1035-1145`), census_count derivation (`:1134`), `_census_count = last.house.total_persons` (`:2903`).
- `transit_validator.py` — peak sampler (`:1144-1225`); non-int state dropped at `:1160` so `peak_person_count` is `None` (not `0`) when dark.
- `perimeter_alert.py` — grep for `person_count` / `degraded` returns no direct consumer; stays no-change (see §3 D3 consumer table).
- `binary_sensor.py` — house/CM-level diagnostic entity scaffold.
- `__init__.py` — HA-start listener pattern for BOOT_SETTLE clock.

### Config-first check (honest rewrite — finding #8)
- A YAML automation on `sensor.frigate_status_2 == unavailable for: 5m` would cover the single house today, and the operator could author one in minutes. The reason to put this in code is **not** that HA can't do it — it's the multi-house rollout (second home live 2026-10-03/04; more planned). Every onboarded house would otherwise have to re-author the same automation with correct dwell + boot suppression + NM dedup + the "Protect-only / no Frigate configured" inert branch. Code is justified by that rollout, not by HA capability gaps.
- Live-knob check: no existing URA Number/Switch/Select governs this; this is a one-time code change, not a knob turn.

## 3. Deliverables

### D1 — Fleet-dark tripwire + one-shot NM (BUILD; required)

New evaluator `_evaluate_camera_input_dark_dimension` in `domain_coordinators/optimization.py`, registered next to `_evaluate_camera_stuck_dimension` at `:935`:

- Pull fleet from census: `camera_manager.get_all_frigate_cameras()` → the subset with a non-empty `person_count_sensor`. Define this as the **denominator**.
- Count `unavailable_now` = number whose current state is `unavailable` or `unknown`.
- Compute `fraction = unavailable_now / denominator`.
- **Zero-denominator inert branch:** if `denominator == 0` (Protect-only / 2nd-home rollout), log `camera_input_dark_inert_no_frigate` ONCE per URA setup and return no findings. Mirrors census `inert_no_frigate` reason at `camera_census.py:3832`.
- Fire condition: `(fraction >= CAMERA_INPUT_DEGRADED_FIRE_THRESHOLD) OR (sensor.frigate_status_2 state in {unavailable, unknown})`, AND dwell `>= CAMERA_INPUT_DEGRADED_DWELL_S` continuously, AND `(now - ha_started) >= BOOT_SETTLE_S`.
- Emit via `OptimizationFinding(dimension=SENSOR_HEALTH, severity="high", dedup_key=("camera_input_dark","fleet"), payload={...})`. The optimizer's existing finding → NM pipeline handles the one-shot delivery.
- One-shot latch `_camera_input_dark_fired: bool` (not per-key — fleet-scope, singleton episode). Mirrors `_camera_stuck_fired` discharge pattern.
- Clear: latch discharges when `fraction < CAMERA_INPUT_DEGRADED_CLEAR_THRESHOLD` AND `frigate_status_2` state is a nominal value for one eval tick (hysteresis — finding #5).
- Attribute payload: fleet count, denominator, unavailable count, fraction, frigate_status_2 state, first N affected entity_ids (cap = 10), ha_entry title of the Frigate config entry if resolvable.
- Naming (finding #6): the finding kind, NM category, and invariant all use **`camera_input_dark`** (not `camera_input_degraded`). The user-facing binary_sensor keeps the softer `ura_camera_input_degraded` name for discoverability, but internal `dedup_key`, log identifiers, and anomaly rows use `camera_input_dark`. One canonical name for the fire event.

Routing justification (finding #3): D1's one-shot NM is routed through the optimizer `OptimizationFinding` → NM path with `dedup_key=("camera_input_dark","fleet")`. The optimization site owns emission; the census site owns detection. We do not add a parallel NM call from camera_census — single ownership.

#### Acceptance Criteria
- **Verify:** evaluator mutation drill — comment out registration at optimization.py `:935` → `test_camera_input_dark_evaluator_registered` goes red. Restore; residue 0.
- **Verify:** 24/24 fake-unavailable fixture with dwell satisfied, denominator = 24 → exactly ONE `OptimizationFinding` + ONE NM row per episode. Clearing to 5/24 then back to 24/24 within one tick → NO re-fire (hysteresis).
- **Verify:** 23/24 fresh (fraction = 0.0417, well below fire threshold) → zero findings.
- **Verify:** `(now - ha_started) < BOOT_SETTLE_S` with 24/24 unavailable → zero findings; after settle + dwell → one finding.
- **Verify:** denominator = 0 → one `inert_no_frigate` log at setup, zero findings.
- **Verify (discriminator):** 24/24 AVAILABLE and all reading `0` (empty house) → zero findings, `degraded_mode` False.
- **Verify (Frigate-down + Protect-up):** `frigate_available=False`, binary platforms up → `degraded_mode` True (`camera_census.py:1905` path), D1 fires, `camera_total` sourced from binary count (not 0).
- **Verify (`frigate_status_2` OR-trigger):** 0/24 unavailable but `sensor.frigate_status_2` unavailable for dwell → D1 fires.
- **Test:** `test_camera_input_dark_fires_on_fleet_unavailable`, `test_camera_input_dark_single_flap_noop`, `test_camera_input_dark_hysteresis_no_reflap_refire`, `test_camera_input_dark_boot_suppressed`, `test_camera_input_dark_zero_denominator_inert`, `test_camera_input_dark_empty_house_available_noop`, `test_camera_input_dark_frigate_down_protect_up_fires`, `test_camera_input_dark_frigate_status_2_or_trigger`, `test_camera_input_dark_evaluator_registered`.
- **Live:** post-deploy, with Frigate up: `binary_sensor.ura_camera_input_degraded = off`, zero new `camera_input_dark` findings within 1h.

### D3 — Wire the EXISTING `degraded_mode` + consumers (BUILD; required — rewritten per finding #1)

**Not a new flag.** This deliverable KEEP+WIREs the existing `CensusResult.degraded_mode` (`camera_census.py:176`), which already correctly flips under both failure branches (`:1905`, `:1917`). The deliverable has three parts: the binary_sensor, the consumer table, and the "don't downgrade on dark" behavior for presence.

**(a) `binary_sensor.ura_camera_input_degraded` (CM-scope, fleet):**
- State: `on` when the most recent `CensusResult.house.degraded_mode` is True; `off` otherwise. Pure mirror — no second latch, no second dwell. This flag flips immediately on dark; the NM one-shot (D1) is the thing that waits for dwell. Two separate truths with two separate purposes.
- Attributes: `fraction_unavailable` (from D1's cached eval), `unavailable_count`, `denominator`, `frigate_status_2_state`, `face_producer_health_reason` (from `camera_census.py:3854`), `affected_entities` (first N), `nm_latch_fired` (bool, mirrors `_camera_input_dark_fired`), `boot_settle_remaining_s`, `last_fired_utc`.
- Enabled by default, on CM device.

**(b) Per-consumer decision table (finding #2 — enumerated):**

| Site | File:line | Current behavior | Rev-2 decision | Why |
|---|---|---|---|---|
| Guest / AWAY veto path α | `presence.py:1143-1153` (gate `all_tracked_persons_away AND unidentified_count == 0 AND face_recognized_count == 0`) | A dark fleet makes `face_recognized_count` and `unidentified_count` both 0 (nothing to recognize), so the veto fires on BLE-away alone, falsely escalating AWAY. | **GATE on `degraded_mode`:** suppress the veto path (return without transitioning) when `house.degraded_mode` is True. Hold last-known house state (Bug Class #7 "stale data" idiom applied correctly: prefer last-known over wrong-known). | Dark fleet cannot speak to "0 unidentified"; treating silence as "no one here" is the exact failure mode. |
| `census_count` consumer (vacancy decision) | `presence.py:1134` (`census_count = max(camera_total, len(face ∪ ble))`) and `:1222` | When Frigate is down and Protect up, `camera_total` already correctly sources from binary platforms (`camera_census.py:1903`), so `census_count` is honest in that sub-case. When ALL platforms are unavailable (`:1917`), `camera_total = 0`. | **LABEL-ONLY** (no numeric change): add a `source_degraded: bool` attribute on the sensor exposing `census_count`, and gate higher-trust decisions (the α-veto) on it per row above. Do NOT mutate the numeric `census_count` itself — downstream tests pin values. | Numeric mutation would ripple into dashboards and tests; the trust gate at the veto is the surgical fix. |
| `_census_count` snapshot | `presence.py:2903` (`_census_count = last.house.total_persons`) | Snapshots count only. | **NO CHANGE** — downstream reads route through the α-veto gate above, which already consults `degraded_mode`. | Snapshot is diagnostic; gating happens at the trust-decision, not at the record. |
| `_cross_validate_platforms` consumers | `camera_census.py:1891-1918` | Already computes `degraded_mode`; `camera_total` sourced correctly per branch. | **NO CHANGE** inside census; this is the producer. | Site is correct; the gap is downstream. |
| transit_validator peak sampler | `transit_validator.py:1144-1225` (non-int dropped at `:1160` → `peak_person_count = None`) | Honest-by-None when dark: a `None` peak is distinguishable from `0`. | **NO CHANGE.** Document the inherent safety. | Site already discriminates dark from empty via `None` vs `0`. Changing it would be a regression. |
| `perimeter_alert.py` | grep for `person_count` / `degraded` returns no direct consumer (checked) | No direct read of `person_count` or `degraded_mode`. | **NO CHANGE.** | Not a consumer; perimeter alerts route through different signals (motion / door / event bus). |

Mutation drill for (b): remove the `degraded_mode` check in presence's α-veto → `test_presence_alpha_veto_suppressed_when_camera_dark` goes red; restore; residue 0.

**(c) Sensor-attribute surfacing:**
- The existing presence/census sensors that today display `degraded_mode` as a passive attribute (`sensor.py:3667`) remain; add the twin NM-latch state (`camera_input_dark_fired`) alongside so operators can see both the immediate flag and the latched-NM state in one place.

#### Acceptance Criteria
- **Verify:** `binary_sensor.ura_camera_input_degraded` has expected unique_id, enabled by default, on CM device; `off` in healthy state with `fraction_unavailable=0.0`.
- **Verify:** when census emits `degraded_mode=True`, the binary_sensor reads `on` within one coordinator tick (no dwell).
- **Verify (presence):** fixture with `degraded_mode=True`, all phones away, zero face/unidentified → α-veto does NOT trigger AWAY transition (stale-last-known held).
- **Verify (presence discriminator):** fixture with `degraded_mode=False`, all phones away, zero face/unidentified (empty house) → α-veto DOES trigger AWAY. (This discriminates "dark" from "truly empty".)
- **Verify (test authority):** real source mutation — comment out `degraded_mode` gate in presence α-veto → `test_presence_alpha_veto_suppressed_when_camera_dark` goes red specifically. Restore; residue 0.
- **Live:** flag is `off` in healthy state; attribute `fraction_unavailable=0.0`; `nm_latch_fired=false`. During a manually-forced degrade (dev-tools `homeassistant.set_state` on 20/24 person_count to `unavailable`), observe `on` within one census tick and NM one-shot after dwell.

### Non-goals
- No change to the per-sensor `camera_stuck` evaluator at optimization.py:1881 or camera_census.py:2533-2705.
- No Frigate-side changes (MQTT, Coral, scheduled restart — those live on `PERIMETER-DETECTION-WENT-DARK-1`).
- No face/sublabel coverage changes.
- No per-camera reachability pings.
- No numeric mutation of `camera_total` / `census_count` on the dark path (label-only; see D3 (b)).
- No change to how HA's own `setup_retry` backoff schedule works.
- **No auto-reload of foreign (Frigate) config entry** — see §9.

## 4. Numbers get knobs (placement ladder — Rev 2)

| Number | Default | Rung | Why |
|---|---|---|---|
| `CAMERA_INPUT_DEGRADED_FIRE_THRESHOLD` | 0.75 | **Module const** (`const.py`) — NEW | Fire boundary; needs review to retune (false-fire vs. miss). |
| `CAMERA_INPUT_DEGRADED_CLEAR_THRESHOLD` | 0.25 | **Module const** — NEW | Hysteresis clear boundary (finding #5). Must satisfy clear < fire; a one-eval 18/24 flap sitting at ~0.75 cannot re-fire the NM. |
| `CAMERA_INPUT_DEGRADED_DWELL_S` | 300 | **Module const** — NEW | Shaped by HA `setup_retry` cadence; not operator policy. |
| `BOOT_SETTLE_S` | 180 | **Module const** — **NEW** (finding #7; no equivalent exists today) | Protocol-ish; one-shot per setup. |

No live-tunable Number entity — none of these are "turn by observation." Any future retune is a reviewed code change (small blast radius). D2 knobs removed (see §9).

Kill-switch semantics: setting `CAMERA_INPUT_DEGRADED_FIRE_THRESHOLD > 1.0` disables D1 fire entirely (documented on the constant). `BOOT_SETTLE_S = 0` disables boot suppression. D3's binary_sensor is unaffected by these (it mirrors census directly).

## 5. Suppression discharge (mandatory)

Per `feedback_suppression_needs_discharge`, every suppression on this path specifies re-fire + backstop + restart:

- **Boot-settle suppression (D1):** discharges automatically at `ha_started + BOOT_SETTLE_S`. Backstop: if dwell crosses during suppression, it starts counting at discharge, not retroactively (prevents instant fire on first eval after boot). On HA restart: `_camera_input_dark_fired` latch does NOT persist across restart — re-fires once per episode after settle + dwell (~480s total). This is accepted given the restart-storm history (operator pref: at-most-one bark per restart during an ongoing outage, not none). If restart-storm cardinality becomes a problem, card a persisted latch.
- **One-shot NM latch (D1):** discharges when `fraction < CAMERA_INPUT_DEGRADED_CLEAR_THRESHOLD` AND `frigate_status_2` nominal for one eval tick (hysteresis — finding #5). Backstop: no manual-clear service in v1 (consistent with `camera_stuck`); operator can force-clear by reloading the URA entry.
- **binary_sensor.ura_camera_input_degraded (D3):** no suppression — pure mirror of `degraded_mode`. Discharges with census one tick after fleet recovery. This is deliberate asymmetry with D1's dwell: operators get an immediate "something is wrong" indicator, and a de-duplicated "wake up" notification. Two truths, two purposes, documented on the entity.

## 6. Falsifiable observations summary

| Observation | Fix state | Different-failure state |
|---|---|---|
| 24/24 person_count `unavailable` for 10min | NM fires once; binary_sensor on; one anomaly row | 1/24 unavailable → no fire, binary_sensor off |
| Fleet recovers (24 avail, nominal) | binary_sensor off within 1 cycle; NM latch cleared below `CLEAR_THRESHOLD` | binary_sensor flaps or re-fires (fail — hysteresis bug) |
| 24/24 AVAILABLE, all reading 0 (empty house) | binary_sensor off, zero NM, `degraded_mode` False | binary_sensor on (fail — "quiet ≠ dark" discriminator broken) |
| Frigate down, Protect binary up | binary_sensor on (`degraded_mode` True via `:1905`); D1 fires; `camera_total` from binary count | `camera_total = 0` (fail — regression on `:1903`) |
| Denominator = 0 (Protect-only house) | inert; one setup log; no NM; no binary_sensor fire | NM fires anyway (fail — zero-denom not guarded) |
| Fleet dark through HA restart | fires once post-boot-settle + dwell | fires N times (fail — latch persistence bug) OR never fires (fail — boot-settle not discharging) |
| 18/24 flaps around 0.75 | fires once, then latch holds until clear <0.25 | re-fires each crossing (fail — no hysteresis) |
| `sensor.frigate_status_2` unavailable, 24/24 person_count fresh | D1 fires via OR-trigger | no fire (fail — OR-trigger not wired) |

## 7. Verification steps (summary)

1. Static greps: evaluator registered at optimization.py `:935`; D3 binary_sensor in `async_setup_entry` for the CM platform; `degraded_mode` has >1 consumer (presence α-veto).
2. Unit tests enumerated per deliverable; wire-in anchors per `feedback_wire_in_anchor_mandatory`.
3. Mutation drills (real source mutation per `feedback_hollow_test_anchors`): unregister evaluator → named test red; remove hysteresis clear-threshold check → named test red; remove boot-settle check → named test red; remove the `degraded_mode` gate on presence α-veto → named test red; restore each; residue 0; `.pyc` cleared per `feedback_mutation_verification_pycache_staleness`.
4. Live: post-deploy, binary_sensor off + `fraction_unavailable=0.0` + `nm_latch_fired=false`. Dev-tools force-set 20/24 person_count to `unavailable` → binary_sensor on within one tick; NM one-shot after dwell. Reset.
5. README post-ship: write back a Validated-table replacing the prospective bullets, naming the entities + attribute values observed (per the mandatory README write-back rule).

## 8. Open plan-review questions

1. ~~Keep D2 or park it?~~ **Resolved — PARKED (§9).**
2. ~~Does `camera_census` already expose a `known_person_count_entities()`-equivalent?~~ **Resolved — no, use `_camera_manager.get_all_frigate_cameras()` filtered by `person_count_sensor` non-empty.** Confirmed by grep.
3. Reuse an existing per-episode manual-clear service, or ship v1 without one? **Decision: v1 without; operator can URA-reload to force-clear.** Consistent with camera_stuck.
4. ~~Does Frigate expose a native `binary_sensor.*_status`?~~ **Yes — `sensor.frigate_status_2` (resolved via registry at `camera_census.py:3874`). Used as OR-trigger in D1.**
5. (new) Should the binary_sensor latch stickiness match D1's dwell, or stay as a pure mirror? **Decision: pure mirror** — see §5 asymmetry rationale.

## 9. D2 (auto-reload of foreign Frigate config entry) — PARKED

**Removed from Rev-2 build scope** per plan-review finding #9. D1 alone converts a 70h silent outage into a ~8-minute operator-visible NM; the manual Reload tap is a single UI action. D2 would add a write to a foreign integration's config-entry lifecycle for exactly one saved tap, with ambiguity in multi-house / multi-entry rollouts, exponential backoff bookkeeping, and three attempt-knob rungs — none of which pay for themselves at today's observed outage cadence (one event, 70h, operator eventually noticed by data drift).

**Revival trigger (explicit):** card D2 (or a successor) if either (a) more than one fleet-dark episode per quarter is observed post-D1 ship, OR (b) operator feedback indicates the "wake up and reload" tap is friction. Record the trigger on `PERIMETER-DETECTION-WENT-DARK-1` or a new successor card at parked status, not as implicit soak.

## Rev 2 changelog (finding # → change)

| Finding | Severity | Change applied in Rev 2 |
|---|---|---|
| 1 | HIGH — D3 duplicates existing producer | §2 REUSE table + §3 D3 rewritten as KEEP+WIRE around `CensusResult.degraded_mode` (`camera_census.py:176`, flips at `:1905`, `:1917`); no second flag; D1's latch now drives ONLY the NM one-shot, while the binary_sensor is a pure mirror of `degraded_mode`. Two separate truths with explicitly separate purposes (§5). |
| 2 | HIGH — D3 consumers not enumerated | §3 D3 (b) adds a per-consumer decision table for `presence.py:1143-1153` (GATE), `:1134`/`:1222` (LABEL-ONLY), `:2903` (NO CHANGE snapshot), `camera_census.py:1891-1918` (NO CHANGE producer), `transit_validator.py:1144-1225` (NO CHANGE — None-safe at `:1160`), `perimeter_alert.py` (NO CHANGE — not a consumer, grep verified). Each gets a reason and a wire-in anchor. |
| 3 | MEDIUM — D1 siting + enumeration source | §2 REUSE table corrects site to `optimization.py:1881` (registered `:935`); explicitly picks optimization as emission owner (REUSE `OptimizationFinding` + `dedup_key=("camera_input_dark","fleet")` at `:1951`) and census as enumeration owner (`_camera_manager.get_all_frigate_cameras()` + `CameraInfo.person_count_sensor`). No invented `known_person_count_entities()` helper. |
| 4 | MEDIUM — fraction denominator + zero-denom + status_2 OR | §1 invariant + §3 D1 define denominator as Frigate-legged cameras with resolved `person_count_sensor`; zero-denominator inert branch mirrors `inert_no_frigate` (`camera_census.py:3832`); `sensor.frigate_status_2` unavailable added as OR-trigger. |
| 5 | MEDIUM — hysteresis | New `CAMERA_INPUT_DEGRADED_CLEAR_THRESHOLD = 0.25` added to §4 knob ladder; clear condition in §3 D1 + §5 discharge requires fraction below CLEAR + status_2 nominal for one tick. |
| 6 | MEDIUM — discriminating acceptance + naming | §1 + §6 add the all-available-zero (empty house) and Frigate-down-Protect-up discriminators; D1 ACs add tests for both. Naming aligned: internal kind / `dedup_key` / NM category = `camera_input_dark`; user-facing entity keeps `ura_camera_input_degraded`. One canonical fire-event name. |
| 7 | LOW — BOOT_SETTLE_S NEW | §2 and §4 mark it NEW (grep returned no equivalent). §5 states restart stance explicitly: latch does NOT persist across restart; one bark per restart during ongoing outage is accepted; card persisted-latch if restart-storm cardinality becomes a problem. |
| 8 | LOW — honest config-first | §2 config-first paragraph rewritten: HA retries on backoff; a per-house YAML automation on `sensor.frigate_status_2` would suffice for one house. The justification for code is multi-house rollout (2nd home live 2026-10-03/04), not an HA capability gap. |
| 9 | D2 PARK confirmed | D2 removed from §3 Deliverables; §9 records the park with explicit revival trigger. Tier remains 2. |
| 10 | Knob ladder acceptable with #5 and #7 | §4 updated accordingly; invariant in §1 is now falsifiable with the added CLEAR threshold and NEW BOOT_SETTLE_S. |
