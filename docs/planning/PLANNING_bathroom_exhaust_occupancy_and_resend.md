# PLANNING — Bathroom Exhaust: occupancy-dwell venting + humidity-fan on-resend fix + master-switch decoupling

**Status:** PLAN-REV2 (operator-approved deliverables 2026-10-14; Rev 2 resolves all findings from `docs/reviews/code-review/plan_bathroom_exhaust_review.md`; ready for build dispatch).
**Owner area:** `custom_components/universal_room_automation/automation.py` (humidity fan + new occupancy-dwell path), `coordinator.py` (handler-gate wiring), `const.py` (new knobs + defaults), `config_flow.py` (per-room enables), `strings.json`/`translations/en.json` (labels).
**Tier:** **Tier 2-DB** (operator elevated 2026-10-14 per standing policy for regression-prone fan work; FAN-MANUAL-1 needed 3 DO-NOT-SHIP reviews). THREE framing-disjoint reviews: A = correctness + emission-site enumeration + None-guards; B = cross-coordinator + lifecycle + manual-override + state-machine integrity (dwell↔humidity↔cap composition); C = adversarial completeness + I1/I2/I3/I4 falsification + legal-config combinatorial. ONE adversarial plan review precedes build dispatch.
**Cycle shape:** single version, four deliverables shipped together (D1–D4). D4 is config-only (no code).

---

## Rev 2 — review resolution

Finding IDs are from `docs/reviews/code-review/plan_bathroom_exhaust_review.md`.

| # | SEV | Finding (one line) | Edit in this doc |
|---|---|---|---|
| 1 | CRIT | No-humidity room has no OFF emitter; `:3525` is HOLD only | D3 step 11 adds explicit **dwell-OFF branch** (fan-ON by dwell AND vacant AND presence-runtime window expired-or-never-armed → one `turn_off` + clear all anchors). I4 extended with the OFF obligation. Test `test_humidity_fan_dwell_off_when_window_expires_no_humidity` added. |
| 2 | CRIT | `dwell_fired` keyed on `not fan_is_on` → oscillation at `timeout` while occupied | D3 step 3 split into `dwell_satisfied` (occupied AND elapsed ≥ dwell — HOLDS while occupied) and `dwell_fire_edge` (transition). D3 step 12 **blocks the humidity-OFF branch** at `:3540-3549` while `_humidity_dwell_fan_on_at is not None and room_occupied`. Test `test_humidity_fan_dwell_hold_blocks_humidity_off_while_occupied` added. |
| 3 | HIGH | Post-vacancy window arms only if `wet_room`; dwell path needs it in non-wet (no-humidity) rooms | D3 step 13: when `dwell_fire_edge` fires, **unconditionally arm the presence-runtime window** regardless of `wet_room`. Fix in `_humidity_update_presence_runtime` call site, not in the helper's internal gate. |
| 4 | HIGH | Powder sensor hold + URA occupancy timeout makes every handwash fire | **Measured-data update below (recorder probe, 10 d):** raw sensor p50 Powder 40 s / Master Toilet 34 s; p90 Powder 107 s / Master Toilet 77 s; it does NOT hold ~4 min. Dwell must measure against the **raw occupancy/motion sensor's continuous ON-run** (state `last_changed`), NOT URA's room-occupied timer (which carries the 300 s occupancy_timeout and would inflate every visit). D3 step 2 (new) + step 3 rewritten accordingly. Default dwell held at **60 s** (operator's 45–60 range); at 60 s dwell the probe selects ~25% of Powder visits and ~15% of Master Toilet visits — matches "number-2" intent. Table recorded in §Measured dwell basis. |
| 5 | HIGH | Manual-off detector mislabels `blocking=False` tick + unavailable | D2 step 4 rewritten: detection requires an **observed `on→off` state_changed event with `context` whose parent is NOT a URA-emitted service call** (reuse the FAN-MANUAL-1 oracle at `hvac_fans.py:343/686` for the context predicate). `unavailable` is **explicitly excluded** (treated as relay drop, feeds the re-assert path, never the manual window). Spec moved from a probe-read to a state-change listener keyed on `self._humidity_fans`. |
| 6 | HIGH | Sleep-off `:3385` and D1 extension emit `turn_off` every tick, untransitioned | D2 step 6 (new): gate **both** `:3385` (sleep-off) and `:3363` (cap-only safety OFF under D1-decoupled gate) on `fan_is_on OR _fan_is_actually_on(humidity_fans)`. Also the D3 dwell-OFF (finding #1) and the humidity-OFF at `:3544` get the same gate (one `turn_off` per true transition). Enumeration table updated with the "transition-gated OFF" column. |
| 7 | MED | `humidity <= off_threshold` crashes on None; enumerate every reader | D3 step 2 (new) now **lists every `humidity`-reader site to guard**: `:3424, :3464, :3495, :3517, :3538, :3540, :3551`. Each wrapped `if humidity is not None:` before compare. Test `test_humidity_fan_no_crash_when_humidity_none` added. |
| 8 | MED | Powder's interim HA automation is a second writer; HA's 7-min OFF would be read as manual | **Operator decision**: disable `automation.guest_toilet_automation2` (id `1750820778098`) **AT deploy**, as part of `deploy.sh` steps, NOT after live validation. D3 step 10 updated; README deploy checklist carries the HA disable step. |
| 9 | LOW | Handler ticks ~30 s + jitter; dwell can fire up to dwell+30 s | AC updated to "**±1 tick (≈30 s)**" everywhere dwell timing appears. Stated in D3 ACs + knob ladder. |
| 10 | LOW | Back-compat kw on internal helper is churn | D1 step 1 updated: **drop the kw entirely**, hard-remove `automation_enabled` from `humidity_venting_enabled`. Not an out-of-tree-called helper (grep confirms sole caller `coordinator.py:5420`). Backcompat test removed. |

---

## Measured dwell basis (added Rev 2 for finding #4)

Orchestrator recorder probe, last 10 days, raw sensor on-durations (continuous ON runs by `state last_changed`):

| Sensor | Visits | p10 | p50 | p90 | <2 min |
|---|---|---|---|---|---|
| `binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_powder_occupancy` | 75 | 19 s | 40 s | 107 s | 70 / 75 |
| `binary_sensor.rgbw_motion_lux_3rdr_wifi_matter_mastertoilet_occupancy` | 179 | 19 s | 34 s | 77 s | — |

At a 60 s dwell measured on the raw sensor's continuous ON time, ~25% of Powder visits and ~15% of Master Toilet visits select — matches "number-2" intent (long sits), rejects handwashes. The URA room-occupancy timer (300 s `occupancy_timeout`) would inflate every visit past dwell and defeat the gate. **The dwell MUST clock against the raw occupancy/motion sensor's continuous ON-run, not `_became_occupied_time`.**

Operator's toilets in scope: **Powder** (`binary_sensor...powder_occupancy`) and **Master Bath Toilet** (`binary_sensor...mastertoilet_occupancy`). Master Bath Toilet has NO humidity sensor today; operator will add one after 2026-10-18 — plan remains correct (humidity-less path is D3's I4).

---

## Institutional context verified

### Prior-art scan — Code / Plans / Memory

**Mandatory reads completed:**

- `docs/planning/PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md` v5 (the shipped cycle). D1 shipped the "humidity path is sole owner" invariant I1 + the `CONF_HUMIDITY_FAN_CONTROL_ENABLED` toggle #3. D3 shipped **only** the POST-VACANCY runtime window (`min(base + per_min × occupancy_min, cap)`), modeled on `automation.guest_toilet_automation2`. **The occupancy TURN-ON of that HA automation (dwell→fan-on) was NOT ported.** That is the gap this cycle closes.
- `docs/planning/PLANNING_fan_actuation_shared_layer.md` — fan oracle / chokepoint design. Humidity-fan path does NOT currently go through the oracle (actuator_reconciler.py:63/110 explicitly EXCLUDES `CONF_HUMIDITY_FANS`). This cycle preserves that exclusion.
- Kanban card `HUMIDITY-FAN-ON-RESEND-SPAM-1` (`docs/planning/kanban.data.yaml` lines 15221–15248), including `mechanism_2026_10_14`, `measured_housewide_2026_10_14`, `why_only_master_2026_10_14`.
- `custom_components/universal_room_automation/automation.py` lines 3269–3659 (`handle_humidity_based_fan_control` + `_humidity_update_presence_runtime` + `_humidity_update_baseline` + `_humidity_spike_should_fire` + `_fan_is_actually_on` at 3260).
- `custom_components/universal_room_automation/coordinator.py` lines 5409–5431 — `humidity_venting_enabled` gate.
- `custom_components/universal_room_automation/_humidity_gate.py:30` — the gate helper. AND-combines `not skip_first_this_tick` with `automation_enabled`.
- `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py:343, 686` — FAN-MANUAL-1 oracle: observed `on→off` state_changed with non-URA context source. **Reused for D2 manual-off detection (Rev 2 finding #5).**
- Operator HA automations in `/Users/okosisi/ha-config/automations.yaml`: `Guest Toilet Automation2` (id `1750820778098`), `Bathroom - Master Toilet Automation`. Powder: operator will disable id `1750820778098` AT deploy (finding #8).

### Greps run + REUSED / NEW tally

| Proposed item | Verdict | Evidence (file:line) |
|---|---|---|
| Humidity-fan entity list | REUSED | `CONF_HUMIDITY_FANS` — `const.py:927`; actuation sites `automation.py:3365, 3386, 3447, 3513, 3547` (ONLY sites repo-wide; `actuator_reconciler.py:63/110/1004` explicitly excludes) |
| Humidity-fan master gate | REUSED | `CONF_HUMIDITY_FAN_CONTROL_ENABLED` — `const.py:1356`; default `True` `:1357`; consumed `automation.py:3319-3321/3347` |
| Handler per-tick gate | REUSED | `humidity_venting_enabled` — `_humidity_gate.py:30`; sole caller `coordinator.py:5420-5428` |
| Fan actual-on probe | REUSED | `_fan_is_actually_on` — `automation.py:3260` |
| Manual-off oracle predicate | REUSED | FAN-MANUAL-1 context-source check at `hvac_fans.py:343, 686` (Rev 2) |
| Post-vacancy runtime constants | REUSED | `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_{ENABLED,BASE_S,PER_MIN_S,CAP_S}` — `const.py:1389-1395`; defaults 60/30/600 |
| EMA baseline / spike / threshold / timeout / max-runtime cap | REUSED | existing per prior cycle |
| Raw occupancy sensor id (per-room) | REUSED | each room's configured occupancy / motion binary_sensor (per `measured dwell basis` table — Powder and Master Toilet in scope); D3 reads `hass.states.get(<raw_sensor>).last_changed` for dwell timing |
| Wet-room flag | REUSED | `CONF_WET_ROOM` |
| Sleep probe | REUSED | `is_sleep_mode_active()` — `automation.py:500` |
| **Decouple from master (D1)** | **CODE CHANGE** | drop `automation_enabled` from `humidity_venting_enabled()` + from the short-circuit at `automation.py:3347` |
| **Transition-gated turn_on + slow re-assert (D2)** | **NEW** | `HUMIDITY_FAN_REASSERT_INTERVAL_S` (module constant). Per-room state `_humidity_fan_last_asserted_at`. |
| **Manual-OFF window (D2, Rev 2)** | **NEW mirror of FAN-MANUAL-1** | state-change listener keyed on humidity_fans; per-room `_humidity_fan_manual_off_until`; module constant `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S=1800`. |
| **Occupancy-dwell turn-ON (D3)** | **NEW CONFs (2)** | `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED`, `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S` |
| Dwell state | NEW | `_humidity_dwell_fan_on_at: datetime | None` |

**Total: 8 REUSED, 2 NEW CONFs, 2 NEW module constants, 3 NEW per-room state fields, 1 behavioral CODE change (decouple).**

---

## Falsifiable invariants

> **I1 (Humidity venting gated ONLY by the humidity-fan master switch).** For every room with `CONF_HUMIDITY_FANS` non-empty, post-D1 the humidity handler emits venting **iff `CONF_HUMIDITY_FAN_CONTROL_ENABLED=True` AND `_skip_first_this_tick=False`**. The room-master switch is NOT a gate. The max-runtime safety cap continues to fire universally. Falsifier: Ziri Bathroom with master-automation OFF, humidity_fan_control ON, humidity > threshold → zero turn_on today; post-D1 exactly one turn_on at rising edge.

> **I2 (Transition-gated emission; capped re-assert; manual-off respected; no untransitioned OFF spam).** On any single tick with ON-decision, at most ONE `turn_on` under: (a) `_humidity_fan_triggered_time is None` (anchor-transition), OR (b) anchor says ON, `_fan_is_actually_on=False`, and `now - _humidity_fan_last_asserted_at ≥ HUMIDITY_FAN_REASSERT_INTERVAL_S` (relay-drop re-assert). On any OFF-decision tick, at most ONE `turn_off` and only on a true transition (`fan_is_on OR _fan_is_actually_on`). While `_humidity_fan_manual_off_until > now`, zero `turn_on`. Falsifier: Master Bathroom 7-day = 3,806 turn_on → post-D2 < 50/day (healthy relay) with max ~20/h during a persistent relay outage. Rev 2 adds: no sleep-off OFF-spam on repeat sleep ticks.

> **I3 (Exactly-one-owner preserved).** `actuator_reconciler.py` continues to EXCLUDE `CONF_HUMIDITY_FANS`; `hvac_fans.py` has no humidity path; the humidity handler is sole writer; D3 adds a new TRIGGER inside the same handler, same single actuation site.

> **I4 (Occupancy-dwell works in rooms with no humidity sensor, AND the fan eventually turns OFF).** For a room with `CONF_HUMIDITY_FANS` non-empty, `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED=True`, `data[STATE_HUMIDITY] is None`, raw occupancy sensor continuously ON ≥ `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S`: exactly one `turn_on`. On vacancy edge, the presence-runtime window arms **regardless of `wet_room`** (Rev 2 finding #3). When the window expires AND vacant AND fan is on by dwell AND humidity is None → **exactly one `turn_off`** (Rev 2 finding #1). Humidity-OFF branch is blocked while the dwell anchor is set and the room is still occupied (Rev 2 finding #2). Falsifier: Master Bath Toilet never vents today; post-D3 fan ON within dwell+1 tick, OFF after presence-runtime window.

Plan reviewer D's sole job: produce legal-config reachable repros that falsify I1–I4.

---

## Deliverables

### D1 — Decouple humidity venting from the room master automation switch

**What:** `switch.<room>_automation` must NOT gate humidity venting; `CONF_HUMIDITY_FAN_CONTROL_ENABLED` is the sole venting gate; max-runtime cap stays universal.

**Code changes:**

1. `_humidity_gate.py:30` — change signature to `humidity_venting_enabled(skip_first_this_tick) -> bool`. **Drop `automation_enabled` entirely** (Rev 2 finding #10 — grep confirms sole caller is `coordinator.py:5420`; not an out-of-tree surface).
2. `coordinator.py:5420-5428` — drop `self._is_automation_enabled()` from the call.
3. `automation.py:3347` — change `if (not toggle3_on) or (not automation_enabled):` → `if not toggle3_on:`. `automation_enabled` parameter on `handle_humidity_based_fan_control` is retained ONLY for the cap-only safety path (which runs regardless of either gate).
4. Skip-first semantics preserved: reload-seed + cap-only + max-runtime-cap run on `_skip_first_this_tick=True`; venting (turn-on, off-threshold, EMA spike, presence-runtime, sleep-policy off, D3 dwell) requires `_skip_first_this_tick=False` + toggle #3 ON.

**ACs:**
- Live: Ziri Bathroom (master OFF, humidity_fan_control ON) emits exactly 1 `turn_on` at the 65% rising edge.
- Test `test_humidity_venting_runs_with_master_off` + regression `test_humidity_cap_still_runs_with_master_off_and_toggle3_off`.
- Grep: `automation_enabled` inside `handle_humidity_based_fan_control` appears only in the cap-only branch.

**Non-goals:** no change to the master switch for lights/covers/HVAC; no change to toggle #3 default.

---

### D2 — Stop turn_on resend spam + transition-gated OFF + manual-off window

**Code changes:**

1. New module constants in `const.py`:
   - `HUMIDITY_FAN_REASSERT_INTERVAL_S: Final = 180`
   - `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S: Final = 1800` (operator decision, Rev 2)
2. New per-room state: `_humidity_fan_last_asserted_at: datetime | None`, `_humidity_fan_manual_off_until: datetime | None`.
3. **ON branch** (`:3496-3518`) — replace with:
   ```
   if on_trigger:
       if self._humidity_fan_manual_off_until and now < self._humidity_fan_manual_off_until:
           return
       fan_actually_on = self._fan_is_actually_on(humidity_fans)
       is_transition = not fan_is_on
       due_for_reassert = (
           fan_is_on and not fan_actually_on and (
               self._humidity_fan_last_asserted_at is None
               or (now - self._humidity_fan_last_asserted_at).total_seconds()
                     >= HUMIDITY_FAN_REASSERT_INTERVAL_S
           )
       )
       if not (is_transition or due_for_reassert):
           return
       if is_transition:
           self._humidity_fan_triggered_time = now
           self._humidity_on_since = now
           self._humidity_spike_was_trigger = spike_fired and not absolute_triggered
       await self._safe_service_call("homeassistant", SERVICE_TURN_ON, {"entity_id": humidity_fans}, blocking=False)
       self._humidity_fan_last_asserted_at = now
       return
   ```
4. **Manual-OFF detection (Rev 2 finding #5)** — reuse FAN-MANUAL-1 oracle pattern (`hvac_fans.py:343, 686`):
   - Register a `state_changed` event listener (via `async_track_state_change_event`) on each entity in `humidity_fans` at setup, torn down at unload. Handler fires ONLY on an **observed `on→off` state transition** where:
     - `new_state.state == "off"` (NOT `"unavailable"` — unavailable is a relay drop, routes to re-assert path only), AND
     - `event.context.parent_id` / `context.id` does NOT match any of the recent URA-emitted service-call contexts for that entity (reuse the context-ring buffer the FAN-MANUAL-1 oracle maintains; if URA has not emitted within the last ~5 s, context is treated as external).
   - On match AND `self._humidity_fan_triggered_time is not None` (we think it should be ON): set `self._humidity_fan_manual_off_until = now + HUMIDITY_FAN_MANUAL_OFF_RESPECT_S` and clear the anchors (`_humidity_fan_triggered_time`, `_humidity_on_since`, `_humidity_fan_last_asserted_at`, `_humidity_dwell_fan_on_at`).
   - **Max-runtime safety cap never respects this window** (safety > comfort); on off_threshold / cap / sleep-off, the window is cleared.
5. **Clear discharge state on anchor-clear.** Reset `_humidity_fan_last_asserted_at` and `_humidity_fan_manual_off_until` wherever `_humidity_fan_triggered_time` / `_humidity_on_since` are reset today: `:3368-3373`, `:3451-3459`, `:3555-3560`.
6. **Transition-gated OFF emitters (Rev 2 finding #6).** Every `turn_off` site below gates on `fan_is_on OR _fan_is_actually_on(humidity_fans)` — zero `turn_off` when the fan is already off, zero per-tick spam.

**Humidity fan write-site enumeration (Rev 2 — now with transition-gated OFF column):**

| File:line | Direction | Branch | Rev 2 edit |
|---|---|---|---|
| `automation.py:3363-3367` | OFF | cap-only safety (toggle3 off) | Gate on `fan_is_on or probe_on`; clear discharge state on fire |
| `automation.py:3385-3388` | OFF | sleep-policy FAN_SLEEP_OFF | **Gate on `fan_is_on or probe_on` (finding #6)**; clear discharge state |
| `automation.py:3446-3449` | OFF | max-runtime cap | Already transitioned on cap-arm; clear discharge state |
| `automation.py:3510-3515` | ON  | on_trigger (THE SPAM SITE) | **Replace with transition + re-assert gated emission (step 3)** |
| `automation.py:3544-3549` | OFF | off_threshold / spike-off branch | Gate on `fan_is_on or probe_on`; **block while `_humidity_dwell_fan_on_at is not None and room_occupied` (finding #2, D3 step 12)**; clear discharge state |
| **NEW** D3 dwell-OFF (no-humidity rooms, finding #1) | OFF | presence-runtime window expired AND vacant AND fan-on-by-dwell AND humidity is None | Single `turn_off`; clear discharge state + dwell anchor |
| `actuator_reconciler.py` | — | EXCLUDES `CONF_HUMIDITY_FANS` | No touch |
| `hvac_fans.py` | — | no humidity path | No touch |

Plan-reviewer re-runs `grep -rn "humidity_fans\|CONF_HUMIDITY_FANS" custom_components/universal_room_automation/` — any new site BLOCKS.

**ACs:**
- Live: Master Bathroom `turn_on` < 50/day (down from 3,806/7d).
- Live: relay-drop ≤ 20 re-asserts/h, exactly 180 s spaced.
- Live: operator flips `switch.<fan>` off during a shower → 30 min silence; max-runtime cap still fires inside the window (anchor cleanup).
- Test `test_humidity_fan_turn_on_only_on_transition` (20 ticks above threshold → 1 turn_on).
- Test `test_humidity_fan_reassert_on_actual_off` (anchor ON, probe False → re-asserts at 0, 180, 360 s).
- Test `test_humidity_fan_no_reassert_when_actually_on`.
- Test `test_humidity_fan_manual_off_from_state_change_listener` — simulate `state_changed` on→off with external context → window armed; URA-emitted `state_changed` on→off → window NOT armed.
- Test `test_humidity_fan_unavailable_not_manual` — `state_changed` on→unavailable → window NOT armed, re-assert eligible.
- Test `test_humidity_fan_manual_off_window_cleared_on_off_threshold`.
- Test `test_humidity_fan_sleep_off_no_spam_when_already_off` (finding #6).
- Test `test_humidity_fan_off_threshold_no_emit_when_already_off` (finding #6).

**Non-goals:** no change to `_safe_service_call`. No per-room re-assert knob.

---

### D3 — Occupancy-dwell exhaust ("the number-2 rule")

**What:** New turn-ON trigger: continuous **raw occupancy / motion sensor ON-run** ≥ dwell-knob → fan ON. MUST work in rooms with NO humidity sensor. Vacancy → presence-runtime window arms (regardless of `wet_room`) → explicit `turn_off` when window expires.

**Code changes:**

1. New CONFs in `const.py`:
   - `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED` — per-room bool. Default `True` iff `CONF_WET_ROOM=True` else `False`.
   - `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S` — int seconds. Default `60` (operator 45–60; midpoint 60 justified by Measured dwell basis — ~25% Powder / ~15% Master Toilet of visits select). Bounds 20–300.
2. **Humidity-None guards (Rev 2 finding #7).** The early-return at `:3316` becomes `if not humidity_fans: return`. **Every subsequent reader of `humidity`** is wrapped `if humidity is not None:` — enumerated readers to guard: **`:3424, :3464, :3495, :3517, :3538, :3540, :3551`**. The dwell + presence-runtime + reload-seed + cap-only + max-runtime-cap paths run regardless.
3. **Dwell timing source (Rev 2 finding #4).** `dwell_elapsed` is computed against the **raw occupancy / motion sensor's continuous ON-run**, NOT URA's room-occupied timer:
   ```
   raw_sensor = self.config.get(CONF_OCCUPANCY_SENSOR) or self.config.get(CONF_MOTION_SENSOR)  # per-room; existing fields
   raw_state = self.hass.states.get(raw_sensor) if raw_sensor else None
   dwell_elapsed = (
       (now - raw_state.last_changed).total_seconds()
       if raw_state and raw_state.state == STATE_ON
       else 0.0
   )
   dwell_satisfied = dwell_enabled and dwell_elapsed >= dwell_s and not self._humidity_cap_suppressed
   dwell_fire_edge  = dwell_satisfied and not fan_is_on and self._humidity_dwell_fan_on_at is None
   ```
   `dwell_satisfied` (Rev 2 finding #2) **HOLDS the fan ON while occupied** — composed into `on_trigger`. `dwell_fire_edge` is the transition that seeds `_humidity_dwell_fan_on_at = now`.
4. **Compose with existing `on_trigger`.** `on_trigger = (humidity is not None and (absolute_triggered or spike_fired)) or dwell_satisfied`. Same single ON emission site as D2 (I3).
5. **Occupancy flap handling.** Flap resets `raw_state.last_changed` naturally; dwell re-arms. Reviewer A verifies no path mutates the raw sensor's `last_changed`.
6. **Max-runtime cap interaction.** `_humidity_cap_suppressed` blocks dwell equally. In humidity-less rooms, add `elif humidity is None: self._humidity_cap_suppressed = False` in the suppression-clear block so suppression clears next tick (otherwise it would latch forever).
7. **Sleep exemption.** D3-dwell inherits wet-room sleep exemption at `:3382`. Non-wet rooms with dwell+sleep+FAN_SLEEP_OFF → dwell blocked (surfaced §B).
8. **Post-vacancy window — ARM REGARDLESS OF wet_room (Rev 2 finding #3).** On the fan-on edge (dwell OR humidity), call `_humidity_update_presence_runtime` so the window arms for the no-humidity dwell path too. Internal `wet_room` gate (if any) is bypassed at the call-site when `dwell_fire_edge` fired.
9. **One owner.** Dwell routes through the SAME D2 ON emission site.
10. **Powder HA automation disable AT deploy (Rev 2 finding #8).** `deploy.sh` adds a step to toggle `automation.guest_toilet_automation2` (id `1750820778098`) OFF via HA service call BEFORE restarting URA. README deploy checklist carries the step. If deploy aborts, operator re-enables manually (one HA UI click).
11. **Dwell-OFF branch (Rev 2 finding #1 — the no-humidity OFF emitter).** After the humidity-OFF branch at `:3544-3549`, add:
    ```
    # Dwell-OFF: no humidity sensor, fan-on by dwell, vacant, presence window expired
    if (
        humidity is None
        and self._humidity_dwell_fan_on_at is not None
        and not room_occupied
        and self._humidity_presence_runtime_until is not None
        and now >= self._humidity_presence_runtime_until
        and (fan_is_on or self._fan_is_actually_on(humidity_fans))  # transition-gated (finding #6)
    ):
        await self._safe_service_call("homeassistant", SERVICE_TURN_OFF, {"entity_id": humidity_fans}, blocking=False)
        # clear ALL anchors
        self._humidity_fan_triggered_time = None
        self._humidity_on_since = None
        self._humidity_fan_last_asserted_at = None
        self._humidity_dwell_fan_on_at = None
        self._humidity_presence_runtime_until = None
    ```
12. **Block humidity-OFF while dwell-held and occupied (Rev 2 finding #2).** At the humidity-OFF branch (`:3540-3549`), add short-circuit:
    ```
    if self._humidity_dwell_fan_on_at is not None and room_occupied:
        return  # dwell holds the fan on; do not fire humidity-driven OFF
    ```
13. **Presence-runtime window arms regardless of wet_room (finding #3).** When `dwell_fire_edge` or any ON edge fires, call presence-runtime arm unconditionally; do not short-circuit on `not wet_room` for the dwell path.

**ACs (Rev 2):**
- Live: Master Bath Toilet (no humidity sensor) — raw sensor continuously ON ≥ 60 s → fan ON within **±1 tick (~30 s, finding #9)**. Exit → fan OFF when presence-runtime window expires (base 60 + 30/min × occ_min, cap 600 s). Confirm the single `turn_off` fires.
- Live: Powder (interim HA automation disabled at deploy) — raw sensor ≥ 60 s → fan ON; brief handwash (p50 40 s) → no fire.
- Live (I2 preserved): humid shower in Master Bathroom → single turn_on at rising edge regardless of which trigger fired first.
- Test `test_humidity_fan_dwell_fires_in_rooms_without_humidity_sensor` (raw sensor ON ≥ dwell_s, humidity=None).
- Test `test_humidity_fan_dwell_off_when_window_expires_no_humidity` (finding #1).
- Test `test_humidity_fan_dwell_hold_blocks_humidity_off_while_occupied` (finding #2 — dwell on, humidity drops below off_threshold while occupied → no OFF).
- Test `test_humidity_fan_dwell_presence_window_arms_in_non_wet_room` (finding #3).
- Test `test_humidity_fan_dwell_uses_raw_sensor_not_room_timer` (finding #4 — URA room-occupied for 10 min with raw sensor OFF for 9 of them → NO dwell fire).
- Test `test_humidity_fan_no_crash_when_humidity_none` (finding #7 — tick with humidity=None exercises every reader).
- Test `test_humidity_fan_dwell_does_not_fire_during_cap_suppression`.
- Test `test_humidity_fan_dwell_disabled_no_fire`.
- Test `test_humidity_fan_dwell_flap_resets_timer` (raw sensor off then on → timer from new last_changed).
- Test `test_humidity_fan_dwell_sleep_policy_wet_room_exempt`.
- Test `test_humidity_fan_dwell_single_actuation_regardless_of_source` (humidity+dwell same tick → 1 turn_on).

**Non-goals:** no new motion-source selector; no per-room override of post-vacancy formula; no HVAC-fans change.

---

### D4 — Threshold calibration via options (NO CODE)

Operator adjusts `CONF_HUMIDITY_FAN_THRESHOLD` + `CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT` per-room via options. Measured inputs documented in prior section. If any input materially shifts, D4 surfaces a code finding.

AC: options write-back takes effect next tick (existing behavior).

---

## Knob ladder

| Name | Rung | Default | Bounds | Why |
|---|---|---|---|---|
| `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED` | Config/options | True iff wet_room | — | Per-room policy. |
| `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S` | Config/options | **60 s** | 20–300 | Operator 45–60 range; midpoint; measured basis selects ~25%/15% of visits. Effective firing window **dwell_s ± 1 tick (~30 s)** (finding #9). |
| `HUMIDITY_FAN_REASSERT_INTERVAL_S` | Module const | 180 s | — | Relay backstop; changing requires review. |
| `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S` | Module const | **1800 s (30 min)** | — | Operator decision Rev 2; mirrors FAN-MANUAL-1. |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_{BASE,PER_MIN,CAP}_S` | REUSED | 60 / 30 / 600 | existing | — |
| Thresholds / spike / timeout / max-runtime | REUSED | existing | existing | D4 operator calibration. |

Kill-switches: `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED=False` disables D3 per room; `CONF_HUMIDITY_FAN_CONTROL_ENABLED=False` disables all URA venting per room.

---

## Producer / Consumer checks

- **Producer `dwell_satisfied`** (Rev 2): `raw_state.last_changed` on the per-room occupancy/motion binary_sensor; health = sensor liveness (HA state-not-None, not `unavailable`). Falsifier: a dead sensor stuck at ON would latch dwell — guarded by requiring `raw_state.state == STATE_ON` AND the configured sensor is not `unavailable` (add guard).
- **Producer `on_trigger`**: composed from `humidity is not None and (absolute_triggered or spike_fired)` or `dwell_satisfied`. Humidity-None path is fully guarded (finding #7).
- **Consumer**: single site `automation.py:3510-3515` (post-D2).
- **Producer `_humidity_fan_manual_off_until`** (Rev 2): written by state-change listener on observed external `on→off`; cleared at off_threshold / cap / sleep-off / expiry.
- **Discriminator** (unchanged): D1-broken → Ziri stays 0; D2-broken → Master stays >500/day; D3-broken → Master Bath Toilet stays 0; dwell-OFF broken → Master Bath Toilet fan latches ON past window.

---

## Non-goals (explicit)

- No change to `hvac_fans.py` / `hvac.py` / `actuator_reconciler.py`.
- No new motion-source selector.
- No per-room knob for re-assert / manual-off windows.
- No change to `CONF_HUMIDITY_FAN_CONTROL_ENABLED` default.
- No deletion of HA automations in-code (Powder's `1750820778098` disabled AT deploy via deploy.sh step — not deleted).
- D4 ships NO code.
- No back-compat kw on `humidity_venting_enabled` (Rev 2 finding #10).

---

## Operator decisions (recorded)

- **§A — skip-first-tick venting.** KEEP (reload-seed stability > 1 tick delay).
- **§B — sleep policy for non-wet dwell rooms.** BLOCK dwell under sleep-off (operator may flip `CONF_WET_ROOM` or `CONF_FAN_SLEEP_POLICY`).
- **§C — manual-OFF respect window.** 1800 s (30 min) — Rev 2 confirmed.
- **§D — dwell default.** 60 s (operator range 45–60; measured basis supports).
- **§E — Review tier.** **Tier 2-DB (3 framing-disjoint)** — Rev 2 confirmed (standing policy for regression-prone fan work).
- **§F — Powder cutover.** Disable `automation.guest_toilet_automation2` (id `1750820778098`) **AT deploy**, as a deploy.sh step (Rev 2 confirmed).
- **§G — D1 scope.** Humidity venting is independent of the room master switch (confirmed Rev 2).

---

## Verification steps (plan-reviewer re-run before build dispatch)

1. Re-grep `CONF_HUMIDITY_FANS` → confirm the 5 automation.py sites + reconciler exclusion only; BLOCK on any new site.
2. Re-grep `humidity_venting_enabled(` → confirm sole caller `coordinator.py:5420`; BLOCK on any other.
3. Re-grep `humidity` reads inside `handle_humidity_based_fan_control` → confirm EVERY reader (:3424, :3464, :3495, :3517, :3538, :3540, :3551) is guarded by `if humidity is not None:` or lives on a path that only runs when `humidity is not None`.
4. Confirm the raw occupancy/motion sensor's `last_changed` is NOT mutated by sub-second re-fires.
5. Confirm FAN-MANUAL-1 context-source predicate (`hvac_fans.py:343, 686`) is reusable from the humidity handler without duplication.
6. Confirm `automation.guest_toilet_automation2` id `1750820778098` is a scriptable automation that `deploy.sh` can disable via HA service call (`automation.turn_off`).
7. Confirm every `turn_off` emission site is transition-gated (`fan_is_on or probe_on`).

---

## Live Validation table (post-deploy — rewrite with observed per CLAUDE.md)

| Criterion | Expected observation | Discriminator |
|---|---|---|
| D1 — Ziri Bathroom vents with master OFF | ≥1 turn_on within one shower cycle of 65% crossing | Fail = 0 across ≥10 crossings |
| D1 — Safety cap unchanged with master OFF | Cap-fire within cap-interval after fan on past max-runtime | Fail = fan past cap, no log |
| D2 — Master Bathroom turn_on rate | < 50/day on `fan.switch_shelly1pmminig3_wifi_masterbathfan` | Fail = >100/day |
| D2 — Relay-drop re-assert | ≤ 20/h during persistent outage, exactly 180 s | Fail = <180 s spacing |
| D2 — Manual-OFF respected | 30 min silence after operator OFF | Fail = turn_on within window |
| D2 — Unavailable ≠ manual | Relay drops unavailable → re-assert fires at 180 s | Fail = 30 min silence |
| D2 — Sleep-off no spam | 0 extra `turn_off` once fan already OFF across sleep ticks | Fail = `turn_off` per tick |
| D3 — Master Bath Toilet vents on dwell | Fan ON within dwell_s ± 1 tick of raw sensor ON-run reaching 60 s; OFF when presence window expires | Fail = 0 turn_on across confirmed sit; OR fan latches ON past window |
| D3 — Powder HA automation disabled at deploy | HA UI shows `automation.guest_toilet_automation2` disabled; URA D3 fires instead | Fail = double-writer |
| D3 — Dwell + humidity same tick → one turn_on | Single turn_on event | Fail = double-emit |
| D3 — Handwash does not fire | Powder visit <60 s → zero turn_on | Fail = turn_on on handwash |
| D4 — Laundry threshold change | Live threshold entity reflects next tick | — |

Cycle not closed until this table is in the README with observed values.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
