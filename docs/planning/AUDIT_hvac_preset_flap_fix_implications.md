# AUDIT — HVAC preset-flap fix implications (P1 / P2 / P3)

**Date:** 2026-08-06
**Author:** context-wide audit (no code changes proposed here — scoping only)
**Trigger incident:** 2026-08-06 ~5–6 PM CDT, zone_1 (Entertainment + Master
Suite, keyed off Study B thermostat) preset oscillated `home` ↔ `away`
at ~5-minute cadence while zone occupancy was stable-occupied. Duty ran
67% cooling; living room reached 82°F occupied.
**Proposals under audit (from operator):**
- **P1.** Asymmetric preset min-dwell — `away→home` immediate; `home→away`
  requires ~15-min stability (URA-initiated flips only; manual untouched).
- **P2.** Zone-vacancy trust — `zone_vacant_past_grace` defers to the
  zone `anyone` occupancy sensor when they disagree during `home_day`.
- **P3.** `runtime_exceeded` rest moves from preset-swap to arrester
  setpoint OFFSET with trip/clear hysteresis. Preset stays as
  occupancy statement; offsets become the energy actuator.

**Scope (per CLAUDE.md context-wide rule):** rooms + zones + house +
cross-cutting consumers. Verdict per proposal at the end.

---

## Institutional context verified

**Coordinator docs read:**
- `docs/Coordinator/HVAC_COORDINATOR_MANUAL.md` (v5.18.0 current) —
  §3.1 preset/house-state map, §3.2 vacancy delays (Number #48/#49),
  §3.3 Max-Zone-Occupied guard (§4.1 #50), §3.5 sleep-state trust
  (v4.7.13), §6.1 known Zone-1 `home_night` gap.
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — §4 coarse-vs-fine
  strategy (presets = COARSE for major mode changes; setpoint offsets
  = FINE for energy tuning); §7 Response Logic by Mode; §7 Sleep Hour
  Protection (±1.5°F). Historical intent explicitly matches P3's
  framing: preset for mode, offsets for tuning.

**Source read end-to-end for this audit:**
- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
  — `_apply_house_state_presets` (1089–1523), D6 defer gate
  (1105–1154), continuous heat_cool enforcer (1156–1213), preset
  target derivation (1220), grace_minutes selection (1226–1231),
  D1 vacancy override (1244–1262), D6 stale-sensor failsafe
  (1264–1337), D5 duty-cycle force-away (1340–1341), v4.2.2 zone
  entry dwell (1343–1356), v4.7.13/D2 FAN_TRUST_STATES night-trust
  suppression (1358–1412), RH3 vacancy-bypass (1414–1422), preset
  write + arrester suppress (1424–1482), activity/decision/compliance
  logging (1456–1518), `_handle_energy_constraint` counter reset
  (1735–1772), `_accumulate_zone_runtime` (2122–2166),
  `_compute_zone_presence_states` (2324–2358).
- `hvac_preset.py` (whole file, 226 lines) — `PresetManager`,
  `compute_energy_offset` (174–200), `should_change_preset` (202–217),
  `_max_sleep_offset=1.5`.
- `hvac_zones.py` — `ZoneState` dataclass (fields, `any_room_occupied`
  property, 145–148), `update_zone_climate_state` (433–449),
  `update_room_conditions` (456–566; `last_occupied_time`,
  `continuous_occupied_since`, `current_session_start` update rules).
- `hvac_override.py` head + severe/normal branches (1–100, 890–996);
  `SUPPRESS_TTL_SECONDS=5` (line 82); NM alert titles "HVAC Override:
  {zone}" (926, 987); `_apply_compromise` scheduler (997+).
- `hvac_const.py` §Override thresholds (229–234), §Duty cycle (225–227:
  20-min window, 0.75 coast, 0.50 shed), `FAN_TRUST_STATES` (399).
- `aggregation.py` `ZoneAnyoneBinarySensor` (3892–4062, 4066–4110,
  4224–4303) — three-layer `is_on` (room-rollup + sleep-fallback +
  non-sleep D2 fallback with 5-min quiet window), and the
  **`_setup_hvac_occupancy_listeners` writer** (3927–3971) which
  dispatches `climate.set_preset_mode` DIRECTLY from the aggregation
  layer on any binary-state change (§Cross-cutting Finding X below).

**Greps run for the proposals' terms:**
- `preset_mode` writers across the integration → **TWO independent
  writers found**: (1) `hvac.py:1440–1448` (Coordinator, 5-min cycle,
  wraps `_override_arrester.suppress()`), (2)
  `aggregation.py:4017–4023` (per-zone entity, event-driven on room
  binary-state change, does NOT wrap suppress). Both consult
  `HVAC_PRESET_SKIP` for manual/sleep but do not coordinate with each
  other. This is directly relevant to the flap — see §"Weirdest
  behavior".
- `runtime_exceeded` → 6 in-tree readers/writers in
  `hvac.py`/`hvac_zones.py` (single-writer under `_accumulate_zone_runtime`
  at 2122–2166, reset in `_handle_energy_constraint` 1758/1772 and
  window rollover 2140/2146). Feeds two decisions: force-away at 1340
  and `zone_presence_state = "runtime_limited"` at 2343.
- `any_room_occupied` → 5 consumer sites, plus `is_on` layers in the
  ZoneAnyone binary sensor (aggregation.py 4066+).
- `FAN_TRUST_STATES` = `("home_night", "sleep", "waking")` (hvac_const.py:399).
  **Confirmed the trust block does NOT cover `home_day`** — see
  §Weirdest behavior for how this is the mechanistic seat of the
  reported 5PM oscillation.

**Memory bodies pulled (relevance-filtered):**
- `project_zone_away_when_occupied_home_night_gap` — precedent for
  applying a person-tracker trust extension to a state where mmWave
  is degenerating. Directly relevant to P2 framing.
- `feedback_marginal_benefit_pushback` and
  `feedback_numbers_get_knobs` (CLAUDE.md placement ladder) — used
  to size the P1 dwell knob and P3 offset knobs against the "should
  this be reviewed vs live-tunable?" test.
- `project_v5_5_0_inclement_weather_shipped` and Tier-3 discipline
  — used to gauge review-tier for P3 (touches offset chain shared
  with pre-cool/coast/shed).

**Prior planning docs surveyed (skim):**
- `docs/planning/PLANNING_hc_precool_toggle_oc_observability.md`
  (mentioned inline in hvac_predict.py:150-155) — confirms the
  precool/banking pipeline consumes preset baselines, not raw
  preset transitions.
- `docs/planning/PLANNING_presence_pair_guest_latch_veto_gap.md`
  (untracked) — reinforces that presence signals are actively
  being hardened; a `zone_vacant_past_grace` fix should sit
  DOWNSTREAM of presence trust, not re-derive it.

---

## Reconciliation vs HC manual (highlights)

### 1. Preset semantics per manual §3.1 vs the incident
Manual §3.1: "preset = home/sleep/away based on the house state
machine … Energy Coordinator constraints modulate WITHIN the chosen
preset, mostly through setpoint offsets." The incident *inverted this
contract*: preset was being toggled as a **duty-cycle actuator** (D5
force-away at hvac.py:1340), not as an occupancy statement. **P3 is
already the direction the design manual points at.** The `home →
away` swap at 67% duty in an occupied zone is a design-doc
violation, not merely a UX complaint.

### 2. Arrester + manual-hold rules (asked directly)
- **Can the arrester ramp/shave an operator quick-cool during peak?**
  Yes — `OverrideArrester` (hvac_override.py:85+) is preset-driven
  detection: it triggers on `preset_mode -> "manual"` OR any
  temp change while off "manual" (:811–:814). Once triggered, it
  runs its two-tier response (severe: 2-min grace → revert at :917;
  normal: 5-min grace → compromise at :997 → 30-min revert),
  independent of energy mode. AC-ramp (`_perform_soft_nudge` and
  friends) can shave a manual quick-cool if kWh-rate stays above
  threshold and the arrester's suppression window has ended. **NOT
  cited in a single manual section** — the manual is silent on
  arrester-vs-manual quick-cool interaction. That is a **manual gap**,
  not an implementation gap.
- **Rationale for runtime-cap-via-preset (D5 at hvac.py:1340).**
  Documented as "duty cycle enforcement" in §3.3 attribution but the
  manual §3 does not explicitly justify implementing it as a preset
  swap versus an offset swap. **Design intent per HVAC_COORDINATOR_DESIGN.md
  §4/§7 is offsets, not presets, for energy tuning.** The current
  preset-swap implementation is an artifact of the v3.17.0 zone-
  intelligence plan (`PLANNING_v3.17.0_HVAC_ZONE_INTELLIGENCE.md`
  lines 698, 806), not a manual-endorsed contract. **P3 restores
  the manual/design alignment.**

### 3. Coarse vs fine per design §4
Design table 4:
- COARSE = preset change, "major mode changes (home→away→home)"
- FINE = target_temp_high/low offset, "energy optimization within a mode"
The runtime-cap force-away and the vacancy_past_grace force-away both
use COARSE for what is functionally FINE-scope behavior (still-occupied,
just energy-restricted). **P3 aligns runtime-cap with the manual/design
contract; P2 partially aligns vacancy-past-grace.**

### 4. Sleep hour protection (design §7, `_max_sleep_offset=1.5`)
Any P3 offset scheme must inherit `_max_sleep_offset` via
`PresetManager.compute_energy_offset` (hvac_preset.py:174–200), otherwise
P3 offsets stack with energy_offset and can violate the ±1.5°F sleep
guardrail. Design §7's `_limit_for_sleep` (:791) is the analogous
choke point.

---

## Consumer/subscriber enumeration — what each proposal breaks

Consumers of preset STATE (as opposed to preset transitions):
| Consumer | Reads | Sensitivity to P1/P2/P3 |
|---|---|---|
| `PresetManager.should_change_preset` (hvac_preset.py:202) | current + target preset | **P1**: still runs; but is bypassed at hvac.py:1416 for vacancy/runtime paths, so P1 must hook the bypass block AND the normal path OR the bypass will keep flapping. |
| `hvac_predict.py` seasonal baseline / banking release (:889-:892, :870-:875) | `_last_emitted_range[zone]` + preset baseline | **P3**: predictor may see offsets it did not emit. Predictor uses `_last_emitted_range` as truth, so a Coordinator-side offset write would need to update that map or the banking-release path will fight it (Bug Class #55: reads without a verified writer). |
| `hvac_override.py` `_expected_setpoints` (deep in OverrideArrester) | expected cool/heat for override delta calc | **P3**: an arrester-owned offset is now expected → arrester's own delta baseline must include the offset or every offset-write self-registers as a normal-severity override → compromise loop. **This is the biggest hidden landmine in P3.** |
| `compliance_log` (via `_compliance.schedule_check` at hvac.py:1512) | `commanded_state.preset_mode` | **P3**: fewer preset writes → fewer compliance rows → post-peak compliance scoring shifts. Fine, but the compliance analytics reference lines must be updated or the "expected commanded state" oracle stale-flags. |
| `activity_logger` (hvac.py:1463) preset_change events | `old_preset`, `new_preset`, `house_state` | **P1**: emit rate drops (fewer flip events). **P3**: preset_change count for runtime-cap drops to ~0 (as intended — this is a feature, not a bug). Add reason terms per §"Ledger reason shape" below. |
| `NotificationManager` — HVAC Override alerts fired today | fires on arrester detection of "preset_mode -> manual", not on URA-initiated flips | **All three** proposals unaffected DIRECTLY. However, P3 changes arrester delta baseline (see landmine above) — if not handled, arrester generates **new** NM alerts titled "HVAC Override: {zone}" (hvac_override.py:926/987) for URA's own offset writes → NM spam. |
| Sleep-preset machinery (v5.31 "47 transitions" history — presence.py `_sleep_preset_manager`) | last preset, sleep window, house_state | **P1**: home→away dwell of 15 min may straddle the sleep boundary. If sleep timer fires while a home→away request is dwelling, effective_preset is "sleep" (target from house_state), so the dwell latch must clear on target_preset changes; otherwise it holds stale intent. |
| `hvac_predict._handle_person_arriving` → pre-arrival zones | `zone_presence_state`, sets preset to home | **P1**: pre-arrival IS the away→home direction — proposal says away→home is immediate → OK. **P2**: `_pre_arrival_zones` already bypassed at hvac.py:1353 for entry-dwell — deference to zone-anyone sensor should mirror this bypass. |
| Fan controller (hvac_fans.py) `FAN_TRUST_STATES` + `_house_state` | house_state, not preset directly | **All three** unaffected. |
| `ZoneAnyoneBinarySensor._setup_hvac_occupancy_listeners` (aggregation.py:3927) | room binary-state changes | **CROSS-CUTTING — see §Weirdest behavior.** This entity is a **SECOND WRITER** of `set_preset_mode` and can flap independently of hvac.py. |
| `energy.py` / `energy_pool` — reads current preset for HVAC constraint math | zone preset_mode | **P3**: preset stays `home`, so energy coordinator sees "home-conditioned zone at higher offset" instead of "away zone" — this is more accurate, but any conditional gated on `preset == "away"` (grep `preset_mode == \"away\"` in energy.py — none found in this pass; recommend re-grep at plan time) must be re-audited. |
| Diagnostic sensors (`ZonePresenceStatusSensor`, dashboards HVAC.tsx/Zones.tsx read `runtime_exceeded`) | zone attrs | **P3**: `runtime_exceeded` semantic changes from "we flip to away" to "we widen the deadband". Dashboard color mapping (`status-yellow` at HVAC.tsx:124) still valid, but tooltip/copy should be updated. |
| `_stuck_signal_nm.fire_stuck_signal` (hvac.py:1320-1337) | zone-stale-occupancy diagnosis | **P2**: OK, but the D6 stale-sensor branch and P2's "trust zone-anyone" branch may DISAGREE (D6 says "presence is stale, force away"; P2 says "anyone-sensor disagrees, defer"). Precedence must be defined — my proposal: D6 wins (safety) UNLESS the zone-anyone sensor was made "occupied" via a person-tracker fallback (Layer 2 or Layer 3), in which case defer. |

---

## Weirdest behavior found (per proposal)

### P1 — asymmetric 15-min home→away dwell

**Weird #1 (semi-obvious, small $).** House really empties 1 min after
occupancy ends: 15 extra minutes of home-preset cooling on an empty
zone. At today's 67% duty and ~0.8 kW/ton observed: ~10-15 min × 0.75
duty × zone kW load ≈ 0.15–0.25 kWh per false-vacancy event. At ~$0.15
avg blended rate that's ~$0.03/event — negligible unless it fires
dozens of times/day. **Sizing is fine; call it out but not a blocker.**

**Weird #2 (subtle — the *actual* landmine).** Dwell interacts with
the D5 duty-cycle force-away at hvac.py:1340. Today: zone hits 75%
duty in coast → `runtime_exceeded=True` → next cycle forces away →
duty accounting stops. If P1 gates that swap behind 15-min dwell, the
zone keeps cooling for another 15 min at 75%+ duty. The duty-window
runtime **keeps accumulating** because it's per-window, not preset-
gated (hvac.py:2150) → zone hits 90–100% duty before the swap takes
effect → **defeats the point of the duty cap**. Fix if adopting P1:
either exempt D5 force-away from the dwell (`effective_preset ==
"away"` from runtime_exceeded skips dwell) OR bind dwell to only
`zone_vacant_past_grace`-sourced away. **Trivially fixable in-plan;
must be spelled out or P1 quietly defeats P3's intent-cousin (duty
cap).**

**Weird #3 (state-machine × time seam).** Dwell straddling a sleep
boundary. Dwell starts at 9:30 PM (`home_day` → dwell latched); sleep
window opens at 10:00 PM → target preset becomes `sleep`. What does
the pending dwell resolve to? Current away target is stale. **Must
invalidate dwell on target_preset change**, else zone jumps to a
non-target preset. This is exactly the class of bug memory calls
"state-machine × time seam" (see feedback_marginal_benefit_pushback).

**Weird #4 (arrester scheduling).** OverrideArrester `SUPPRESS_TTL_SECONDS=5`
(hvac_override.py:82) covers URA-initiated writes. A dwell that DEFERS
the write does not create arrester events (arrester is preset-
detection, not intent-detection). Safe. But dwell + suppress do NOT
compose: a manual quick-cool DURING the dwell window (occupant returns
briefly, cranks setpoint) → arrester fires → grace + compromise runs
→ dwell expires mid-compromise → coordinator now writes `away` on top
of the arrester's in-flight compromise. **Race condition; low freq
but non-zero.** Mitigation: skip the dwell-expiry write if the
arrester currently has an active override on the zone
(`self._override_active[zone_id]`).

### P2 — defer to zone-anyone sensor when it disagrees during `home_day`

**Weird #1 (the actual landmine).** The zone-anyone sensor
(`aggregation.py:3892` `ZoneAnyoneBinarySensor`) is **NOT a simple
rollup of room `any_room_occupied`.** It is a 3-layer sensor: Layer
1 = room-rollup (same source as HVAC's `any_room_occupied`), Layer 2
= sleep-window person-tracker fallback (v4.7.13, `is_on` at 4066+),
Layer 3 = non-sleep person-tracker fallback (v4.7.15 D2, at 4092–4094
+ 4224–4303) with a `_NONSLEEP_QUIET_THRESHOLD_SECONDS` room-quiet
guard (≥5 min). During `home_day`, if all rooms have been quiet for
≥5 min AND a `zone_persons` tracker is home, the sensor says
"occupied" while `any_room_occupied` says "vacant". **P2 wired
literally deferring to the sensor is fine — this is exactly the
signal you want.** But: Layer 3 uses `_last_motion_time` per room
coordinator; that field's freshness has its own known flap history
(BLE + mmWave demotion). Making it AUTHORITATIVE over the HVAC
preset means every mmWave demotion glitch during `home_day` can
now cancel a legitimate vacancy → **regression in the other
direction** (missed vacancy cooling savings). Recommended
amendment: defer to zone-anyone-sensor ONLY when its non-Layer-1
layers are the reason it's ON — i.e., "defer if
`sensor.is_on and not any_room_occupied`", which is exactly the
disagreement clause. Then it's a strict widen-but-never-narrow
predicate. Safe.

**Weird #2 (Bug Class #55 read-without-writer).** The zone-anyone
entity is per-URA-zone (aggregation.py, `ZoneAnyoneBinarySensor.zone`
= URA zone). The HVAC zone is a MERGE of one-or-more URA zones (per
manual §2, "Entertainment + Master Suite"). Which anyone-sensor
does the HVAC merged zone consult? **This mapping does NOT exist
today.** Naive impl = pick the first URA zone in the merge → false
"vacant" if that URA zone is empty but a sibling URA zone in the
same HVAC zone is occupied. Fix: OR the anyone-sensors across all
URA zones in the merged HVAC zone. Not hard, but MUST be in the
build spec or P2 quietly reintroduces a variant of the compound-
zone bug.

**Weird #3 (double-writer collision).** See §Cross-cutting Finding X.
`ZoneAnyoneBinarySensor` itself writes `set_preset_mode` on room
occupancy state change. If P2 makes HVAC defer to this same sensor's
state, we now have "aggregation writes preset when sensor flips + HVAC
reads sensor state to decide when NOT to write preset". The two paths
race on the same 5-min cycle boundary. This is likely a large fraction
of the reported flap even without P2.

### P3 — runtime_exceeded → arrester setpoint offset

**Weird #1 (the biggest landmine).** OverrideArrester detects
overrides by watching setpoint DELTAs from `_expected_setpoints`
(deep in hvac_override.py, computed from preset + energy_offset).
If P3 adds a NEW offset dimension (`runtime_exceeded_offset`),
`_expected_setpoints` must ADD that offset into its expected
baseline, or **every P3 write self-registers as a normal override**
(delta > 1.0°F trivially for a 2–3°F cap-rest offset), triggering
the 5-min grace → 30-min compromise loop → NM spam titled "HVAC
Override: {zone}". This is the same shape as the pre-cool banking
issue solved by Tier-1 CRITICAL-1 wiring (`hvac_predict.py:158–163`).
**Every arrester-relevant expected-baseline site must inherit the
new offset.** This alone probably makes P3 a Tier-2-DB (regression-
prone) or Tier-3 change per CLAUDE.md standing policy.

**Weird #2 (offset stacking / double-coast).** P3 offset stacks with
`energy_offset` (compute_energy_offset at hvac_preset.py:174). During
coast (energy_offset = +3°F) with a P3 cap-rest offset of +2°F, cool
setpoint drifts +5°F. Sleep clamp `_max_sleep_offset=1.5` gates the
energy_offset but NOT the P3 offset. Total sleep offset possible:
+3.5°F (1.5 + 2) → 78°F sleeping room. **P3 MUST route through the
same clamp or add its own sleep guardrail.** Suggested: introduce
`_max_runtime_rest_offset` at module const with `is_sleep` clamp
mirror at hvac_preset.py:186.

**Weird #3 (freeze floor + arrester + P3 offset stacking).**
`emit_set_temperature` freeze floor (hvac_setpoint) protects
URA-emitted ranges. A P3 offset in cooling season is safe (only
touches cool_setpoint upward). In HEATING season, if P3 grows to
symmetrically raise/lower for heat runtime caps, freeze floor must
be re-verified. Not a v1 problem; document as heat-season out-of-scope
until the freeze-floor chokepoint is confirmed to include the offset.

**Weird #4 (trip/clear hysteresis vs 20-min duty window).**
DUTY_CYCLE_WINDOW_SECONDS = 1200 s. Today `runtime_exceeded` clears
on window rollover (hvac.py:2146). If P3 keeps that clear semantics,
the offset toggles ON/OFF on every 20-min boundary → new flap at
20-min cadence instead of 5-min cadence. **Hysteresis on the offset
side is load-bearing.** Suggested clear rule: offset persists until
duty%_this_window drops below 60% (COAST threshold − 15%) for at
least 5 min, OR window rollover fires AND cumulative runtime in the
prior window was <75%. Live-tunable via Number entity per CLAUDE.md
"Numbers Get Knobs" §3 (operator will tune by observation).

**Weird #5 (energy release path).** `_handle_energy_constraint` at
hvac.py:1768–1772 resets `runtime_exceeded=False` on constrained→normal
release (added v4.7.30 per B-MED-1). Under P3, this reset must also
clear the offset. If offset lives on `ZoneState` (recommended), one-line
add. If it lives on ArresterOverride, more surgery. Argues for the
former.

---

## Cross-cutting Finding X — TWO independent preset writers (probable root cause of the 5-min oscillation)

This is the weirdest single finding in the audit, and it is not
addressed by any of P1/P2/P3 as stated.

**Writer A:** `hvac.py:1440–1448` (`HVACCoordinator._apply_house_state_presets`).
Runs every 5 min in `async_track_time_interval` (hvac.py:765). Wraps
`_override_arrester.suppress()` (:1426) so URA-initiated writes do not
self-register as manual overrides.

**Writer B:** `aggregation.py:4017–4023`
(`ZoneAnyoneBinarySensor._handle_zone_occupancy_change`). Event-driven
from `async_track_state_change_event` on room `binary_sensor.*_occupied`
entities (:3963). Fires the moment room-level binary state transitions
(vacant↔occupied). Reads `CONF_ZONE_VACANT_PRESET` / `CONF_ZONE_OCCUPIED_PRESET`
(defaults) from the ZONE (not ZoneManager) config entry. Skips if current
preset is in `HVAC_PRESET_SKIP` (`manual`, `sleep`) — but NOT `away`,
NOT `home`. **Does NOT call `_override_arrester.suppress()`.**

**Failure mode matching the incident:**
1. Occupancy stable-occupied per person-tracker. Room binary flaps
   vacant→occupied→vacant over sub-second interval (mmWave demotion
   / BLE noise / a curated sensor bounces).
2. Writer B fires on binary flap → writes `home` (occupied) or
   `away` (vacant) directly to Study B thermostat.
3. Writer A fires on its 5-min cycle → reads the current thermostat
   preset (possibly the value Writer B just wrote), computes target
   from house_state + zone.any_room_occupied + D5 runtime_exceeded
   + D1 vacancy_past_grace + FAN_TRUST_STATES suppression (which
   does NOT cover `home_day`, hvac_const.py:399), and writes its
   own decision.
4. If D5 `runtime_exceeded` is true (67% duty reported → very
   plausible after a couple of coast intervals), Writer A forces
   `away` even while zone-anyone is on.
5. Next cycle either writer flips it back. 5-min cadence tracks
   Writer A; sub-cycle events track Writer B.

**Implications for the proposals:**
- **P1 (dwell)** applied only to Writer A leaves Writer B free to
  flap. Partial fix at best.
- **P2 (defer to anyone sensor)** is *especially* dangerous with
  Writer B alive: the sensor P2 defers to is ITSELF one of the
  writers, i.e. HVAC's preset now depends on the sensor's current
  state, but that sensor also independently writes preset. Feedback
  loop risk (state-of-thermostat → sensor's is_on layers do NOT
  read thermostat state, so no direct loop; but the intent-conflict
  is guaranteed).
- **P3 (offset-instead-of-preset for runtime cap)** removes one
  source of Writer A preset churn (the D5 force-away). Does NOT
  remove Writer B churn.

**Recommended pre-requisite to ANY of P1/P2/P3:**
1. Deprecate Writer B (aggregation.py:3892–4062 HVAC-listener
   scaffold) OR route it through Writer A (dispatch a signal that
   triggers `_async_decision_cycle` rather than directly writing
   `set_preset_mode`).
2. Verify no config-flow surface still promises "zone-occupancy
   directly drives preset" — this appears to be v3.3.5.9 legacy
   (comment at aggregation.py:3930) predating the HVAC Coordinator.
3. Only then apply P1/P2/P3. Otherwise every fix is defeated by the
   surviving writer, and the operator sees "we fixed it and it still
   flaps" — a Bug Class #33 shape (partial fix — sibling helpers
   skipped).

This finding is **THE weirdest behavior in this audit** and the one
I'd flag as the load-bearing pre-req even if the operator ships none
of P1/P2/P3.

---

## Ledger reason shape (the ONE approved change)

Approved change: record `preset_change` reason terms at the
activity_logger call (hvac.py:1466) and the DecisionLog context
(hvac.py:1500). Suggested reason enum (single-choice, joined for
compound reasons):
- `house_state_transition` — driven by house_state change (target
  preset differs from current on the natural path).
- `vacant_past_grace` — D1 vacancy override fired.
- `runtime_exceeded` — D5 duty-cycle force-away fired.
- `stale_sensor` — D6 stale-sensor failsafe fired (already logged
  separately via `_stuck_signal_nm`, but should appear in the reason
  set too).
- `night_trust_suppression` — a suppression that CANCELLED a would-be
  write (log a synthetic `preset_change` with `old==new` and this
  reason). Optional; helps debug "why didn't it flip during
  home_night".
- `manual_detected` — arrester engaged; the coordinator SKIPPED a
  write because preset is currently "manual".
- `dwell_pending` (if P1 lands) — a would-be write is being held for
  the min-dwell timer. Log with `old==new` and this reason.

Store as `reason` (str) and optional `reason_detail` (dict:
`{"grace_minutes": 15, "duty_percent": 78.4}` etc.). Update
`ZoneState.last_action_type` (hvac_zones.py:139) to include the
reason so the dashboard can show it inline.

**Shape recommendation:** DO NOT overload `preset_change` to include
non-change events. Add a separate action type
`preset_change_suppressed` for the dwell/night-trust/manual cases,
with the same reason enum. Otherwise dashboard counts will double
because a "suppressed" event still writes a row.

---

## Verdicts

### P1 — asymmetric preset min-dwell
**SAFE-WITH-AMENDMENTS.**
Required amendments:
1. Bypass the dwell for D5 `runtime_exceeded` force-away (or move to
   P3 first; see below).
2. Invalidate the dwell latch on `target_preset` change (house_state
   transitions must not be held).
3. Skip dwell-expiry write if arrester currently has an active
   override on the zone.
4. Log dwell-pending decisions to the ledger (`preset_change_suppressed`).
5. Marginal-benefit test (per CLAUDE.md pushback duty): P1 alone,
   with Writer B still alive, does not fix the reported incident.
   **Do NOT ship P1 without first deprecating Writer B.**
6. Knob: expose `home_away_min_dwell_minutes` as a Number entity
   (default 15, live-tunable, per CLAUDE.md "Numbers Get Knobs" §3).

### P2 — defer to zone-anyone sensor during `home_day`
**REDESIGN.**
As stated ("defer to the sensor when they disagree") it is fine in
principle but has three structural gaps:
1. The URA-zone → HVAC-zone many-to-one mapping (compound HVAC zone)
   is not currently threaded to any anyone-sensor lookup. Must OR
   across all URA zones in the merged HVAC zone.
2. Writer B (see §X) is the anyone-sensor's OWN preset writer. P2
   creates a cycle: HVAC-Writer-A ← sensor-state ← Writer-B ←
   room-binary-state. Only safe once Writer B is deprecated.
3. `home_day` scope is too narrow — the same structural degeneration
   (mmWave drop on a still occupant) is exactly what Layer 3 in
   the sensor already targets across
   `home_day / home_evening / home_night / arriving / guest / waking`.
   Either match the sensor's own scope OR document why `home_day`
   specifically.

**Alternative** (redesign): don't add a P2 branch in
`_apply_house_state_presets`. Instead, change the source of truth for
`zone.any_room_occupied` when consumed by the vacancy path. Add a
`zone.any_person_present` derived predicate (aligned with the anyone
sensor's Layer 2/3) and use `any_room_occupied or any_person_present`
in the D1 vacancy check at hvac.py:1249. This has ONE choke point
instead of scattering P2 logic across the preset apply path, and it
composes naturally with P1/P3.

### P3 — runtime_exceeded via arrester offset with hysteresis
**SAFE-WITH-AMENDMENTS (biggest amendment list; but this is the
manual/design-aligned direction).**
Required amendments:
1. Update `OverrideArrester._expected_setpoints` (and any sibling
   expected-baseline site) to include the P3 offset, or arrester
   self-fires normal-severity overrides on every P3 write → NM spam
   under title "HVAC Override: {zone}". **Blocker if missed.**
2. Route the P3 offset through `PresetManager.compute_energy_offset`
   or a sibling clamp so `_max_sleep_offset=1.5` still holds. Do
   NOT let it stack unbounded with `energy_offset` during sleep.
3. Hysteresis on offset clear: don't clear at duty-window rollover
   alone (would create 20-min-cadence flap). Recommended: clear
   when window-rollover fires AND prior-window duty <75% for at
   least 5 continuous minutes. Both thresholds Number-entity
   configurable.
4. `_handle_energy_constraint` release path (hvac.py:1758–1772) must
   also clear the P3 offset when clearing `runtime_exceeded=False`.
5. Predictor + banking release (`_last_emitted_range`,
   `hvac_predict.py:158–177`) must recognize the P3 offset so it
   does not re-baseline to a pre-P3 setpoint on release (Bug Class
   #55 shape).
6. Dashboards: HVAC.tsx / Zones.tsx `runtime_exceeded` visualization
   (color-tag only) still works; tooltip/copy update noted.
7. Tier classification: **Tier 2-DB minimum**; consider Tier 3
   under CLAUDE.md standing policy — P3 touches a shared primitive
   (setpoint offsets) consumed by arrester + predictor + energy +
   compliance + dashboard, precisely the "trust-hierarchy ripple"
   shape.

### Order of operations (recommended)
1. **First:** Deprecate or route-through Writer B (aggregation.py).
   This is a hotfix-tier surgical change with Tier-2 review (touches
   a preset-writing surface). Without this, no other fix sticks.
2. **Then:** P3 as a Tier 2-DB / Tier 3 build (biggest arrester +
   predictor + energy ripple, but aligns with manual/design).
3. **Then:** P1 as a Tier-1 hotfix (small, once P3 removes the D5
   force-away collision).
4. **Last / maybe never:** P2 as a redesign into a
   `zone.any_person_present` predicate consumed by the D1 vacancy
   check — a smaller, more contained shape than the "defer at the
   preset-apply site" framing. Only after Writer B is gone.

---

## Notes on things NOT in scope (per plan-completion tracking)

- The known Zone-1 `home_night` gap
  (`project_zone_away_when_occupied_home_night_gap`) is TANGENTIAL —
  same failure family (preset-away with occupant) but different root
  (FAN_TRUST_STATES + bed-sensor absence). This audit does not
  extend the trust to `home_day` on its own; that is P2's job with
  the amendments above.
- No proposal has been made here regarding the arrester's
  quick-cool-during-peak behavior (asked in the tasking). Answer:
  yes it can shave, no it is not documented in the manual, and the
  manual should get a §3.4b note about arrester + AC-ramp + manual
  interaction independent of these three proposals.
- Freeze-season heating parity for P3 is deliberately deferred
  until the freeze-floor chokepoint is re-verified to route
  P3-relevant offsets through it.
