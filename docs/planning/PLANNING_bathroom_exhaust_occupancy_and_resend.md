# PLANNING — Bathroom Exhaust: occupancy-dwell venting + humidity-fan on-resend fix + master-switch decoupling

**Status:** PLAN-READY (operator-approved deliverables 2026-10-14; awaiting one Tier-2 plan review before build dispatch).
**Owner area:** `custom_components/universal_room_automation/automation.py` (humidity fan + new occupancy-dwell path), `coordinator.py` (handler-gate wiring), `const.py` (new knobs + defaults), `config_flow.py` (per-room enables), `strings.json`/`translations/en.json` (labels).
**Tier:** **Tier 2** (per operator). Standing policy recommends Tier 2-DB for regression-prone fan work (FAN-MANUAL-1 needed 3 DO-NOT-SHIP reviews); operator has elected Tier 2 — orchestrator notes the elevation choice. Two framing-disjoint reviews, A = correctness + emission-site enumeration, B = cross-coordinator + lifecycle + manual-override semantics. ONE adversarial plan review precedes build dispatch.
**Cycle shape:** single version, four deliverables shipped together (D1–D4). D4 is config-only (no code).

---

## Institutional context verified

### Prior-art scan — Code / Plans / Memory

**Mandatory reads completed:**

- `docs/planning/PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md` v5 (the shipped cycle). D1 shipped the "humidity path is sole owner" invariant I1 + the `CONF_HUMIDITY_FAN_CONTROL_ENABLED` toggle #3. D3 shipped **only** the POST-VACANCY runtime window (`min(base + per_min × occupancy_min, cap)`), modeled on `automation.guest_toilet_automation2`. **The occupancy TURN-ON of that HA automation (dwell→fan-on) was NOT ported.** That is the gap this cycle closes.
- `docs/planning/PLANNING_fan_actuation_shared_layer.md` — fan oracle / chokepoint design. Humidity-fan path does NOT currently go through the oracle (actuator_reconciler.py:63/110 explicitly EXCLUDES `CONF_HUMIDITY_FANS` — "A-CRIT-2: humidity fans are driven solely by the room-tier humidity handler"). This cycle preserves that exclusion; the humidity handler stays the sole writer.
- Kanban card `HUMIDITY-FAN-ON-RESEND-SPAM-1` (lines 15221–15248 of `docs/planning/kanban.data.yaml`), including `mechanism_2026_10_14`, `measured_housewide_2026_10_14`, `why_only_master_2026_10_14`, and constraints (fan domain regression-prone, suppression needs a discharge, numbers get knobs).
- `custom_components/universal_room_automation/automation.py` lines 3269–3659 (`handle_humidity_based_fan_control` + `_humidity_update_presence_runtime` + `_humidity_update_baseline` + `_humidity_spike_should_fire` + `_fan_is_actually_on` at 3260).
- `custom_components/universal_room_automation/coordinator.py` lines 5409–5431 — `humidity_venting_enabled(skip_first_this_tick, self._is_automation_enabled())` gate at the call site. **The master-automation enable is bound into `automation_enabled`, which the handler at automation.py:3347 uses to short-circuit venting (cap-only backstop still runs).** That is exactly the coupling D1 removes.
- `custom_components/universal_room_automation/_humidity_gate.py:30` — the gate helper. It AND-combines `not skip_first_this_tick` with `automation_enabled`.
- Operator HA automations in `/Users/okosisi/ha-config/automations.yaml`: `Guest Toilet Automation2` (id 1750820778098, trimmed today to fan-only interim — on after 20 s occupied; off 7 min + 60 s + 30 s/min capped 600 s) and `Bathroom - Master Toilet Automation` (~line 316, on after 20 s occupied; off 5.5 min + linger 2 × stay capped 600 s; its stay_duration reads a different automation's `last_triggered` — a bug, DO NOT COPY).

### Greps run + REUSED / NEW tally

| Proposed item | Verdict | Evidence (file:line) |
|---|---|---|
| Humidity-fan entity list | REUSED | `CONF_HUMIDITY_FANS` — `const.py:927`; actuation sites `automation.py:3365, 3386, 3447, 3513, 3547` (ONLY sites repo-wide; `actuator_reconciler.py:63/110/1004` explicitly excludes) |
| Humidity-fan master gate | REUSED | `CONF_HUMIDITY_FAN_CONTROL_ENABLED` — `const.py:1356`; `DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED=True` `:1357`; consumed `automation.py:3319-3321/3347` |
| Handler per-tick gate | REUSED | `humidity_venting_enabled` — `_humidity_gate.py:30`; call site `coordinator.py:5420-5428` |
| Fan actual-on probe | REUSED | `_fan_is_actually_on` — `automation.py:3260` (used at `:3333`) |
| Post-vacancy runtime constants | REUSED | `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_{ENABLED,BASE_S,PER_MIN_S,CAP_S}` — `const.py:1389-1395`; defaults 60/30/600 (match operator's HA automation) |
| EMA baseline / spike / threshold / timeout / max-runtime cap / hysteresis | REUSED | existing per prior cycle v5.x |
| Room occupancy edge source | REUSED | `_became_occupied_time` — `coordinator.py:152/1534/1588` (read via `_humidity_update_presence_runtime` today at `automation.py:3646`) |
| Wet-room flag | REUSED | `CONF_WET_ROOM` (existing per prior cycle; gates sleep-exemption + default-on of occupancy-dwell per D3) |
| Sleep probe | REUSED | `is_sleep_mode_active()` — `automation.py:500` |
| **Decouple from master-automation (D1)** | **CODE CHANGE, NO NEW CONF** | drop `automation_enabled` from `humidity_venting_enabled()` AND from the `(not toggle3_on) or (not automation_enabled)` short-circuit at `automation.py:3347`. The sole gate becomes toggle #3 + per-knob enables. |
| **Transition-gated turn_on + slow re-assert discharge (D2)** | **NEW** | one new constant `HUMIDITY_FAN_REASSERT_INTERVAL_S` (module constant, `const.py`); no CONF — see knob ladder. New per-room state `_humidity_fan_last_asserted_at: datetime | None`. |
| **Manual-OFF-while-humid gate (D2)** | **NEW mirror of FAN-MANUAL-1** | reuse `_fan_is_actually_on`; one new per-room state `_humidity_fan_manual_off_until: datetime | None` + one named constant `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S` (module constant). |
| **Occupancy-dwell turn-ON (D3)** | **NEW CONFs (3)** | `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED` (per-room enable), `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S` (dwell), `CONF_HUMIDITY_FAN_OCCUPANCY_SOURCE` (optional: motion vs full presence — DEFER to options unless reviewer A requests). Greps for these strings in `const.py` + `config_flow.py` return zero matches. |
| New per-room state for dwell | NEW | `_humidity_dwell_fan_on_at: datetime | None` (set when dwell fires; used so the OFF branch knows this was a "number-2" firing rather than a humidity firing — the post-vacancy runtime window applies either way, see D3 flow). |

**Total: 7 REUSED surfaces, 3 NEW CONFs, 2 NEW module constants, 3 NEW per-room state fields, 1 behavioral CODE change (decouple).**

### Threshold calibration (D4) — CONFIG-only, no code

Operator will adjust per-room `CONF_HUMIDITY_FAN_THRESHOLD` + `CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT` via options flow based on the measured inputs below. **The plan relies on these measured inputs — if any materially shift, D4 may surface a code finding.**

Measured 7-day inputs (from kanban `measured_housewide_2026_10_14`):
- Master Bathroom: 3,806 turn_on calls (peak 652/h) — currently correctly crossing threshold; the spam is a per-tick emission bug, not a threshold miscalibration.
- Guest Bedroom 1 Bathroom + Master Bath Toilet: NO humidity sensor configured. Handler early-returns at `automation.py:3316` on `humidity is None` — these rooms NEVER vent today. D3 (occupancy-dwell) is the sole venting mechanism for them.
- Ziri Bathroom: crossed 65% threshold 236 samples; zero commands — `switch.ziri_bathroom_automation` off since 10-08. D1 unblocks.
- Powder: crossed 60% threshold 44 samples; zero commands — same mechanism. D1 unblocks.
- Laundry: peaked 60.1% vs 60 threshold (2 samples) — probably correct; threshold may want a +5 bump via D4 options.

---

## Falsifiable invariant (state up front — Tier 2 discipline)

> **I1 (Humidity venting is gated ONLY by the humidity-fan master switch).**
> For every room with `CONF_HUMIDITY_FANS` non-empty, in every reachable state of the cross-product
> `_is_automation_enabled() ∈ {True, False}` × `CONF_HUMIDITY_FAN_CONTROL_ENABLED ∈ {True, False}` × `_skip_first_this_tick ∈ {True, False}` × `humidity ⋛ threshold`,
> post-D1 the humidity handler emits turn_on / turn_off / spike / dwell / post-vacancy actuation **iff `CONF_HUMIDITY_FAN_CONTROL_ENABLED=True` AND `_skip_first_this_tick=False`** (plus the per-knob enables inside each branch). The room-master switch (`_is_automation_enabled()`) is NOT a gate on the venting path. The max-runtime safety cap continues to fire universally (unchanged).
>
> Falsifier (today's bug, headline repro): Ziri Bathroom with `switch.ziri_bathroom_automation=off`, `switch.ziri_bathroom_humidity_fan_control=on`, humidity > threshold → **zero turn_on calls** (because `coordinator.py:5424` passes `automation_enabled=False` → handler short-circuits at `:3347`). Post-D1: exactly one turn_on at the rising edge.

> **I2 (Transition-gated emission; capped re-assert discharge).**
> On any single tick in which the humidity handler decides "fan should be ON" (humidity ≥ threshold, OR spike, OR dwell, OR post-vacancy window), it issues at most ONE `homeassistant.turn_on` for the configured humidity fans **under either condition**:
>  (a) the handler's own `_humidity_fan_triggered_time` anchor is None (true transition), OR
>  (b) `_fan_is_actually_on(humidity_fans)` returned False AND the last-asserted timestamp is older than `HUMIDITY_FAN_REASSERT_INTERVAL_S` (relay-drop re-assert discharge).
> In all other ON-decision ticks, zero service calls are issued. Falsifier: Master Bathroom 7-day = 3,806 calls. Post-D2: a single showered day shows O(10) calls (one per rising edge + at most one re-assert per `HUMIDITY_FAN_REASSERT_INTERVAL_S` whenever the probe disagrees with the anchor).

> **I3 (Exactly-one-owner preserved — unchanged from the prior cycle).**
> `actuator_reconciler.py` continues to EXCLUDE `CONF_HUMIDITY_FANS` (`:110`); `hvac_fans.py` continues to have no humidity path; the humidity handler is the sole writer. D3 (dwell) does NOT introduce a second writer — it is a new TRIGGER inside the same handler, feeding the same single actuation site.

> **I4 (Occupancy-dwell works in rooms with no humidity sensor).**
> For a room with `CONF_HUMIDITY_FANS` non-empty, `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED=True`, humidity source absent (`data[STATE_HUMIDITY] is None`), continuous `_became_occupied` ≥ `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S`: the handler emits exactly one turn_on. On vacancy, the existing presence-runtime window (`_humidity_update_presence_runtime`) runs out and emits turn_off. Falsifier (today's bug): Master Bath Toilet + Guest Bedroom 1 Bathroom never vent despite occupancy.

Plan reviewer D's sole job: produce a legal-config reachable repro that falsifies I1, I2, I3, or I4.

---

## Deliverables

### D1 — Decouple humidity venting from the room master automation switch

**What:** The room-level master automation switch (`switch.<room>_automation`) must NOT gate humidity venting. The humidity-fan master switch (`CONF_HUMIDITY_FAN_CONTROL_ENABLED`, surfaced as `switch.<room>_humidity_fan_control`) is the sole venting gate; the max-runtime safety cap remains universal.

**Code changes (specified, not coded):**

1. `_humidity_gate.py:30` — modify `humidity_venting_enabled(skip_first_this_tick, automation_enabled)` → `humidity_venting_enabled(skip_first_this_tick)`. The venting gate returns `not skip_first_this_tick`. Keep the function (its name documents the gate) but drop the `automation_enabled` parameter. **Deprecation-safe:** retain a backward-compat keyword `automation_enabled: bool | None = None` that is accepted-and-ignored for one cycle, with a one-line debug log on the first call that passes it (helps any out-of-tree caller catch up).
2. `coordinator.py:5420-5428` — drop `self._is_automation_enabled()` from the call site; pass only `_skip_first_this_tick`.
3. `automation.py:3347` — change the short-circuit from `if (not toggle3_on) or (not automation_enabled):` to `if not toggle3_on:`. The entire `automation_enabled` parameter on `handle_humidity_based_fan_control` is retained for the cap-only safety path only — reviewer A to confirm the cap-only branch still functions correctly (it does; the cap-only path runs REGARDLESS of either gate per the fix-A comment at :3341).
4. **Skip-first semantics preserved.** Reload-seed (`automation.py:3330-3340`) and the cap-only branch continue to run on `_skip_first_this_tick=True`. Only venting (turn-on, off-threshold, EMA spike, presence-runtime, sleep-policy off, D3 dwell) requires `_skip_first_this_tick=False` + toggle #3 ON.
5. **Skip-first-only policy under the new gate (operator decision surfaced below).** First post-reload tick behavior for the venting path. See "Operator decisions this plan surfaces" §A.
6. **Sleep policy under the new gate** (operator decision surfaced below). See §B.

**Acceptance criteria:**

- **Verify (I1 live):** on a running HA with Ziri Bathroom master-automation OFF + humidity_fan_control ON, induce humidity ≥ 65 (steam from the shower or an input_number override on the humidity sensor in dev). Recorder shows exactly ONE `homeassistant.turn_on` for Ziri's exhaust at the rising edge; prior to D1, zero such calls across 236 samples / 7 d.
- **Verify (invariant):** `grep -n "automation_enabled" automation.py` inside `handle_humidity_based_fan_control` returns only the cap-only branch at :3347 (now `not toggle3_on`), not the venting branch.
- **Test:** `test_humidity_venting_runs_with_master_off` — toggles: master=OFF, humidity_fan_control=ON, humidity rising → exactly one turn_on at the edge. Pre-D1 counterpart: zero.
- **Test:** `test_humidity_cap_still_runs_with_master_off_and_toggle3_off` — regression anchor: safety cap unchanged (fan ON, elapsed > cap, master=OFF, toggle3=OFF → one turn_off).
- **Test:** `test_humidity_gate_backcompat_automation_enabled_kw` — `humidity_venting_enabled(skip_first_this_tick=False, automation_enabled=False)` still returns True (kw accepted-and-ignored).
- **Live:** `sensor.ziri_bathroom_humidity_fan_active` goes True inside one shower cycle; recorder confirms rising-edge-only turn_on.

**Non-goals:** no change to the master-automation switch semantics for lights / covers / HVAC. No change to toggle #3's default (`True`).

---

### D2 — Stop the turn_on resend spam (transition-gated emission + capped slow re-assert)

**What:** `automation.py:3496-3518` currently calls `homeassistant.turn_on` UNCONDITIONALLY on every humidity update while `on_trigger` is True. Replace with transition-gated emission + a slow capped re-assert when the ACTUAL fan state is OFF.

**Code changes (specified):**

1. New module constants in `const.py`:
   - `HUMIDITY_FAN_REASSERT_INTERVAL_S: Final = 180` — rung: module constant (safety / wire-protocol; see knob ladder).
   - `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S: Final = 1800` — mirror of FAN-MANUAL-1's manual-override respect window. See manual-OFF semantics below.
2. New per-room state on the Automation object: `_humidity_fan_last_asserted_at: datetime | None = None`, `_humidity_fan_manual_off_until: datetime | None = None`.
3. Replace the ON branch at `:3498-3520` with:
   ```
   if on_trigger:
       # Manual-OFF-while-humid respect (D2 mirror of FAN-MANUAL-1).
       if self._humidity_fan_manual_off_until is not None and now < self._humidity_fan_manual_off_until:
           return
       fan_actually_on = self._fan_is_actually_on(humidity_fans)
       is_transition = not fan_is_on  # anchor-based (existing)
       # Discharge: fan should be on, but the device isn't (relay drop /
       # Shelly timeout). Re-assert at most once per interval.
       due_for_reassert = (
           fan_is_on and not fan_actually_on and (
               self._humidity_fan_last_asserted_at is None
               or (now - self._humidity_fan_last_asserted_at).total_seconds()
                     >= HUMIDITY_FAN_REASSERT_INTERVAL_S
           )
       )
       if not (is_transition or due_for_reassert):
           return  # already-on, no actuation this tick
       if is_transition:
           self._humidity_fan_triggered_time = now
           self._humidity_on_since = now
           self._humidity_spike_was_trigger = spike_fired and not absolute_triggered
       await self._safe_service_call("homeassistant", SERVICE_TURN_ON, {"entity_id": humidity_fans}, blocking=False)
       self._humidity_fan_last_asserted_at = now
       return
   ```
4. **Manual-OFF-while-humid semantics (consistent with FAN-MANUAL-1).** When the user turns the fan OFF manually via the physical switch / HA UI during a humid period, the handler respects that for `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S` (default 30 min). Detection reuses the existing pattern: a transition to physically-OFF while `fan_is_on` (anchor says ON, probe says OFF, AND we did NOT just emit a turn_off) sets `_humidity_fan_manual_off_until = now + HUMIDITY_FAN_MANUAL_OFF_RESPECT_S`. The next re-assert check and the next ON-decision both honor the window. The max-runtime safety cap NEVER respects this window (safety > comfort). On fan-OFF via off_threshold or cap, the window is cleared.
   - **Operator decision surfaced (§C below).** The exact respect-window default is `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S=1800` (30 min). The dial is a module constant, not a per-room knob, matching FAN-MANUAL-1 (fan domain regression-prone → review required to change).
5. **Clear discharge state on anchor-clear.** `_humidity_fan_last_asserted_at` and `_humidity_fan_manual_off_until` are reset wherever `_humidity_fan_triggered_time`/`_humidity_on_since` are reset today: `:3368-3373` (cap-only safety), `:3451-3459` (venting cap-fire), `:3555-3560` (off-branch). Add one line each.

**Enumeration — EVERY humidity fan write site in the codebase (independent re-grep, per task instructions):**

| File:line | Direction | Branch | D2 touch? |
|---|---|---|---|
| `automation.py:3363-3367` | OFF | cap-only safety (toggle3/master off) | Add `_humidity_fan_last_asserted_at = None` + clear manual-off window on cap fire |
| `automation.py:3385-3388` | OFF | sleep-policy FAN_SLEEP_OFF | Clear discharge state (anchor already cleared `:3389-3390`) |
| `automation.py:3446-3449` | OFF | max-runtime cap | Clear discharge state |
| `automation.py:3510-3515` | ON  | on_trigger (THE SPAM SITE) | **Replace with transition + re-assert gated emission** |
| `automation.py:3544-3549` | OFF | off_threshold / spike-off branch | Clear discharge state |
| `actuator_reconciler.py` | — | explicitly EXCLUDES `CONF_HUMIDITY_FANS` (`:110`, `:1004`) | No touch |
| `hvac_fans.py` | — | humidity path removed by prior cycle | No touch |
| `hvac.py` (FAN-MANUAL-1 missed sites: zone-vacancy sweep + pre-arrival) | — | grep `CONF_HUMIDITY_FANS` in `domain_coordinators/hvac.py` returns ZERO matches post-prior-cycle | No touch — plan reviewer re-greps |
| D3 dwell-on (new) | ON  | occupancy dwell | Routes through SAME ON path as D2 (one owner, one emission site) |

Plan reviewer MUST re-run `grep -rn "humidity_fans\|CONF_HUMIDITY_FANS" custom_components/universal_room_automation/` and verify the five automation.py sites + the reconciler exclusion + zero hvac.py sites. If any new site appears, plan is BLOCKED.

**Acceptance criteria:**

- **Verify (I2 live):** Master Bathroom hour-of-peak (today 652/h on 10-13 12h) drops to O(1) at the rising edge + at most one re-assert per `HUMIDITY_FAN_REASSERT_INTERVAL_S=180s` ≈ 20 re-asserts/h cap when the relay is persistently dropping. Typical healthy-relay shower: 1 turn_on at rising edge, 1 turn_off at off_threshold.
- **Verify (relay-drop discharge):** inject a one-tick `_fan_is_actually_on → False` while `fan_is_on=True` (test harness); exactly one turn_on at that tick; subsequent 170 seconds of same condition → zero additional turn_on; at tick ≥180s → one more.
- **Test:** `test_humidity_fan_turn_on_only_on_transition` — humidity above threshold for 20 consecutive ticks → exactly 1 turn_on.
- **Test:** `test_humidity_fan_reassert_on_actual_off` — fan anchor ON, probe returns False continuously; re-asserts at [0, 180, 360, ...] seconds, never more frequent.
- **Test:** `test_humidity_fan_no_reassert_when_actually_on` — fan anchor ON, probe True → zero re-asserts across 10 min.
- **Test:** `test_humidity_fan_manual_off_respected` — user flips `switch.<fan>` off at tick 300 while humidity still above threshold; next 1800 s → zero turn_on. At 1800 s + 1 tick with humidity still above → one turn_on. Max-runtime cap still fires inside the window (fan is OFF so cap is moot, but anchor cleanup must happen).
- **Test:** `test_humidity_fan_manual_off_window_cleared_on_off_threshold` — fan auto-off via off_threshold → window cleared → next rising edge immediately eligible.
- **Live:** 24 h post-deploy, Master Bathroom `homeassistant.turn_on` count on `fan.switch_shelly1pmminig3_wifi_masterbathfan` is < 50 (down from 3,806/7d, i.e. ~544/day). Shelly `DeviceConnectionTimeoutError` log rate for that relay drops materially (observational; not a strict gate).

**Non-goals:** no change to `_safe_service_call` wrapper. No new per-room knob for the re-assert interval (module constant — see knob ladder).

---

### D3 — Occupancy-dwell exhaust ("the number-2 rule")

**What:** New turn-ON trigger: continuous occupancy ≥ dwell-knob → fan ON for smell reasons. Vacancy uses the existing presence-runtime window. MUST work in rooms with NO humidity sensor (today `automation.py:3316` early-returns on `humidity is None`).

**Code changes (specified):**

1. New CONFs in `const.py`:
   - `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED: Final = "humidity_fan_occupancy_dwell_enabled"` — per-room boolean. Default `True` iff `CONF_WET_ROOM=True`, else `False` (wet rooms want the smell-rule; a laundry does not).
   - `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S: Final = "humidity_fan_occupancy_dwell_s"` — integer seconds. **Default `60`** (operator range 45-60s; see knob ladder for justification).
   - Bounds `20-300` (allows the operator to tighten to the HA automations' 20s if desired; soft upper bound 5 min).
2. **Early-return relaxation at `automation.py:3316`.** Replace `if not humidity_fans or humidity is None: return` with:
   ```
   if not humidity_fans:
       return
   # Dwell path works in rooms with no humidity sensor; the humidity branches
   # below are guarded by `humidity is not None` locally.
   ```
   Every subsequent branch that reads `humidity` (threshold compare, EMA update, off_threshold compare, hysteresis) is wrapped in `if humidity is not None:`. The dwell + presence-runtime + manual-OFF-respect + reload-seed + cap-only + max-runtime-cap paths all run regardless.
3. **Dwell trigger.** After the toggle-#3 gate at `:3347` and before the humidity-threshold composition at `:3494`, add:
   ```
   dwell_enabled = bool(self.config.get(CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED, False))
   dwell_fired = False
   if dwell_enabled and self._coordinator._became_occupied_time is not None and room_occupied:
       dwell_s = int(self.config.get(CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S, DEFAULT_HUMIDITY_FAN_OCCUPANCY_DWELL_S))
       elapsed_occ = (now - self._coordinator._became_occupied_time).total_seconds()
       if elapsed_occ >= dwell_s and not fan_is_on and not self._humidity_cap_suppressed:
           dwell_fired = True
   ```
4. **Compose with existing `on_trigger`.** Change `on_trigger = absolute_triggered or spike_fired` → `on_trigger = (humidity is not None and (absolute_triggered or spike_fired)) or dwell_fired`. Set `self._humidity_dwell_fan_on_at = now` when `dwell_fired and not fan_is_on`.
5. **One owner.** The dwell-on routes through the SAME `_safe_service_call` ON site as D2 (preserves I2 and I3). Anchor seeding (`_humidity_fan_triggered_time`, `_humidity_on_since`) is identical whether humidity or dwell fired.
6. **Occupancy flapping / debounce.** No new debounce — rely on `_became_occupied_time` which is already stable across sub-second motion ticks (coordinator.py:1534/1588). Dwell gate `≥ dwell_s` means a flap that re-starts the timer naturally re-arms. Reviewer A to verify no path resets `_became_occupied_time` to `now` on a non-edge update.
7. **Max-runtime cap interaction.** `_humidity_cap_suppressed=True` suppresses dwell-fired turn-on exactly as it suppresses humidity-fired turn-on (same code path post-compose). Suppression clears on humidity ≤ off_threshold (existing) — in rooms with no humidity sensor, `humidity is None` means the suppression check at `:3463-3469` is unreachable, so suppression would persist forever. **Fix:** in the suppression-clear block, add `elif humidity is None: self._humidity_cap_suppressed = False` so humidity-less rooms clear suppression on the next tick (the cap's purpose was to bound total runtime; once the fan is off and vacant, there's nothing to suppress). Reviewer A to adjudicate.
8. **Sleep exemption for wet rooms.** D3-dwell inherits the existing wet-room sleep exemption at `:3382` (if `wet_room and sleep: skip the FAN_SLEEP_OFF branch`). Non-wet rooms with `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED=True` + sleep + FAN_SLEEP_OFF → dwell is blocked. (Rare combination; surfaced for operator confirmation §D.)
9. **Post-vacancy runtime.** The existing presence-runtime window (`_humidity_update_presence_runtime` at `automation.py:3486-3493/3646`) fires on vacancy edge regardless of whether the fan was humidity-fired or dwell-fired — it already keys on `fan_is_on`. No change.
10. **Post-ship step (not a deliverable):** disable the interim HA automation `Guest Toilet Automation2` (id 1750820778098) after live-validation of D3 passes for the Powder room. Added as a one-line note in the README's Live Validation table, closed after the operator flips it off in HA.

**Acceptance criteria:**

- **Verify (I4 live):** Master Bath Toilet (no humidity sensor) — enter, remain seated ≥ dwell_s → fan ON. Exit → fan runs out the presence-runtime window (base 60 + 30/min × occ_min, cap 600 s per existing defaults). Prior to D3, zero turn_on across any dwell duration.
- **Verify (I4 live):** Guest Bedroom 1 Bathroom same scenario.
- **Verify (I2 preserved):** humid shower in Master Bathroom with dwell also enabled → same transition-gated behavior (1 turn_on at rising edge regardless of which trigger fired first).
- **Test:** `test_humidity_fan_dwell_fires_in_rooms_without_humidity_sensor` — humidity=None, dwell_enabled=True, occupancy continuous for `dwell_s+1` → one turn_on.
- **Test:** `test_humidity_fan_dwell_does_not_fire_during_cap_suppression` — cap just fired, suppression active, occupancy continuous past dwell → zero turn_on until suppression clears.
- **Test:** `test_humidity_fan_dwell_disabled_no_fire` — flag False → zero turn_on regardless of occupancy.
- **Test:** `test_humidity_fan_dwell_flap_resets_timer` — occupancy flaps (vacant for 5 s then occupied again) → dwell timer re-arms from the new edge; fan does NOT fire at `old_edge + dwell_s`.
- **Test:** `test_humidity_fan_dwell_then_vacancy_runs_presence_window` — dwell fires, user leaves, presence-runtime window extends per existing formula; fan off at window end.
- **Test:** `test_humidity_fan_dwell_sleep_policy_wet_room_exempt` — wet room, sleep active, dwell satisfied → fan ON.
- **Test:** `test_humidity_fan_dwell_single_actuation_regardless_of_source` — humidity above threshold AND dwell satisfied on same tick → exactly one turn_on.
- **Live:** post-deploy, operator confirms Master Bath Toilet + Guest Bedroom 1 Bathroom fans trigger on occupancy within dwell_s (±1 tick). After Powder's D3 live-validates, disable `Guest Toilet Automation2` in HA.

**Non-goals:**
- No new motion-source selector in this cycle (dwell reads `_became_occupied_time`, which is the room's existing fused occupancy — the operator can switch the room's upstream presence sources via options, no new knob here). If reviewer A judges motion-only vs full-presence meaningfully different for toilets, surface as a follow-up card.
- No per-room override of the post-vacancy runtime formula; D3 reuses D-prior defaults (60 / 30 / 600).
- No change to the HVAC fans coordinator.

---

### D4 — Threshold calibration via options (NO CODE)

**What:** Operator will adjust per-room `CONF_HUMIDITY_FAN_THRESHOLD` and `CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT` via options flow. This plan declares the measured inputs it relies on; no code change.

**Measured inputs the plan depends on (from kanban `measured_housewide_2026_10_14`):**
- Master Bathroom 7d: 236 crossings of 65% (Ziri), 44 of 60% (Powder), 2 of 60% (Laundry — likely wants threshold ↑).
- Guest Bedroom 1 Bathroom + Master Bath Toilet: no humidity sensor; D3 is sole venting mechanism.

**Acceptance criteria:**
- **Verify:** options-flow change of `CONF_HUMIDITY_FAN_THRESHOLD` on a running room takes effect by the next coordinator tick (existing options-writeback behavior; no change needed).
- **Live:** post-deploy, operator confirms one threshold change in Laundry (e.g. 60 → 65) via options; next shower cycle sees expected behavior.

**Non-goals:** No code. If operator discovers a measured input the plan does not match, surface as a cycle finding and re-evaluate D1-D3.

---

## Knob ladder — every number named

Per CLAUDE.md "Numbers Get Knobs":

| Name | Rung | Default | Bounds | Why this rung |
|---|---|---|---|---|
| `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED` | **Config/options flow** (per-room) | True iff wet_room else False | — | Per-room policy; wet rooms want the smell rule, laundries do not. Operator sets it once per room via options. |
| `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_S` | **Config/options flow** (per-room) | **60 s** | 20-300 | Per-room ergonomics (toilet vs master bath differ); operator-tuned by observation; parsimony cap of 300 s. **Default 60 s chosen over 45 s**: the operator's two HA automations use 20 s (aggressive) but spam-fire on brief visits; 60 s is the midpoint of the operator's 45-60 s range and balances "number-2 detection" against false-fire on a brief wash-your-hands visit. Reviewer A may push 45 s if false-positives dominate. |
| `HUMIDITY_FAN_REASSERT_INTERVAL_S` | **Module constant** (`const.py`) | 180 s | — | Relay-recovery backstop; changing it should REQUIRE review (too low = re-spam; too high = fan stays off after a Shelly drop). Not an operator-tuned surface. |
| `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S` | **Module constant** (`const.py`) | 1800 s (30 min) | — | Mirrors FAN-MANUAL-1 (fan domain regression-prone). Changing it should require review. |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_{BASE,PER_MIN,CAP}_S` | REUSED (per-room, existing) | 60 / 30 / 600 | existing | — |
| `CONF_HUMIDITY_FAN_THRESHOLD`, `CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT`, `CONF_HUMIDITY_FAN_MAX_RUNTIME`, `CONF_HUMIDITY_FAN_TIMEOUT` | REUSED (per-room, existing) | existing | existing | D4 operator calibration. |

Kill-switch semantics: `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED=False` disables D3 for a room; `CONF_HUMIDITY_FAN_CONTROL_ENABLED=False` disables all URA venting for a room (D1 preserves this as the ONE gate).

---

## Producer / Consumer checks

- **Producer — `on_trigger` (D2 ON decision).** Composed from `humidity ≥ threshold` (producer: `data[STATE_HUMIDITY]` via `coordinator.py:5422`), `spike_fired` (producer: EMA baseline — existing arithmetic at `automation.py:3621-3644`), and NEW `dwell_fired` (producer: `now - self._coordinator._became_occupied_time ≥ dwell_s`, with `_became_occupied_time` from `coordinator.py:152/1534/1588`). Each dependency's health: STATE_HUMIDITY nullable (D3 explicitly handles None); `_became_occupied_time` set-to-now on the occupied→True edge and cleared on vacancy edge (verified `coordinator.py:1534/1588`); EMA state cleared on fan-off (`_humidity_reset_baseline` at `automation.py:3573`).
- **Consumer — single site.** `automation.py:3510-3515` (post-D2 revision) is the SOLE consumer of `on_trigger` for the ON actuation. Trust-decision (not display). Reviewer A verifies grep returns no other callers of `homeassistant.turn_on` with `humidity_fans` as entity_id (enumeration above).
- **Producer — `_humidity_fan_last_asserted_at` (D2 re-assert state).** Written at the ON actuation site; read ONLY by the re-assert check. Cleared at every anchor-clear site (five). Falsification observation: if the state is read on a path where it was not cleared with the anchor, a stale value could suppress a legitimate rising-edge re-assert for up to `HUMIDITY_FAN_REASSERT_INTERVAL_S`. Reviewer A's mutation site.
- **Producer — `_humidity_fan_manual_off_until` (D2 manual window).** Written at the "anchor says ON, probe says OFF, we did not just emit turn_off" detection point. Read at ON-decision and re-assert check. Cleared at off_threshold / cap / sleep-off / expiry.
- **Discriminator for live validation:** before D1/D2/D3, Ziri Bathroom = 0 turn_on across 236 threshold crossings AND Master Bathroom = 3,806 turn_on / 7d. After D1/D2/D3 (24 h window), Ziri > 0 at the first rising edge AND Master Bathroom < 50 turn_on / day. Different failure modes produce different observations: if D1 is broken, Ziri stays 0; if D2 is broken, Master stays > 500/day; if D3 is broken, Master Bath Toilet stays 0.

---

## Non-goals (explicit)

- No change to `hvac_fans.py`, `hvac.py`, `actuator_reconciler.py` (I3 preserved).
- No change to the fan-oracle / chokepoint layer — humidity fans remain explicitly excluded (actuator_reconciler.py:110).
- No new motion-source selector for D3 dwell.
- No new per-room knob for the re-assert interval or the manual-off respect window (module constants — fan domain regression-prone).
- No change to `CONF_HUMIDITY_FAN_CONTROL_ENABLED` default (stays True).
- No change to the EMA / spike / window-min modes.
- No deletion of the operator's HA automations in this cycle (post-ship manual step, documented in README).
- D4 ships NO code.

---

## Operator decisions this plan surfaces

- **§A — skip-first-tick venting under the new decoupled gate.** With D1, `_skip_first_this_tick` remains a gate on venting (reload-seed runs; venting does not fire that tick). Confirm this is the right behavior for the humidity path (dwell + humidity + spike + off-threshold). **Default in this plan: KEEP — skip-first suppresses venting; cap-only + reload-seed still run. Rationale: anchor stability on reload > ~1 tick of delayed venting.**
- **§B — sleep policy semantics for non-wet rooms with occupancy-dwell enabled.** A non-wet room with `CONF_HUMIDITY_FAN_OCCUPANCY_DWELL_ENABLED=True` + sleep + `FAN_SLEEP_OFF`: today's sleep branch at `:3382` only exempts wet rooms. **Default in this plan: BLOCK dwell under sleep policy for non-wet rooms** (consistent with current semantics); operator may flip the room's `CONF_WET_ROOM` or `CONF_FAN_SLEEP_POLICY` if they want night-time dwell.
- **§C — manual-OFF-while-humid respect window.** `HUMIDITY_FAN_MANUAL_OFF_RESPECT_S=1800 s` (30 min). Mirrors FAN-MANUAL-1's manual-override respect semantics. **Default proposed; operator confirms.**
- **§D — dwell default of 60 s vs 45 s.** Range per operator 45-60 s. Plan picks 60 s (justified in knob ladder). Operator may push to 45 s via options per room without code.
- **§E — tier.** Standing policy would elevate fan-domain regression-prone work to Tier 2-DB (three framing-disjoint reviews). Operator has elected Tier 2. Noted; two reviews + one plan review.

---

## Verification steps (plan-reviewer re-run before build dispatch)

1. Re-grep `CONF_HUMIDITY_FANS` across `custom_components/universal_room_automation/` — confirm five automation.py sites + the reconciler exclusion only. BLOCK on any new site.
2. Re-grep `humidity_venting_enabled(` call sites — confirm only `coordinator.py:5420`. BLOCK on any other caller.
3. Re-read `automation.guest_toilet_automation2` (today's trimmed interim) and `Bathroom - Master Toilet Automation` to confirm the dwell+vacancy shape this plan clones (NOT the `stay_duration` cross-reference bug).
4. Confirm `_became_occupied_time` is NOT reset on sub-second re-fires (coordinator.py:1534/1588) — the dwell timer depends on it.
5. Confirm the `humidity is None` relaxation at `:3316` does not uncover a crash path in any humidity-reading branch (every reader guarded by `if humidity is not None:`).
6. Confirm no out-of-tree caller of `humidity_venting_enabled` depends on the second parameter (backcompat kw retained for one cycle).

---

## Live Validation table (prospective — rewritten to observed post-deploy per CLAUDE.md "Record Live Validation Back Into the README")

| Criterion | Expected observation | Discriminator |
|---|---|---|
| D1 — Ziri Bathroom vents with master OFF | ≥1 `homeassistant.turn_on` on Ziri exhaust within one shower cycle of 65% crossing | Fail = 0 across ≥10 crossings |
| D1 — Master-automation OFF rooms still safety-capped | Cap-fire log line within one cap-interval of a fan ON past max-runtime | Fail = fan running past cap, no log |
| D2 — Master Bathroom turn_on rate | < 50 turn_on / day on `fan.switch_shelly1pmminig3_wifi_masterbathfan` | Fail = > 100 / day |
| D2 — Relay-drop re-assert | ≤ 20 re-asserts/h during a persistent Shelly outage, exactly spaced 180 s | Fail = burst re-asserts (<180s spacing) |
| D2 — Manual-OFF respected | After operator flips the switch off during a shower, 30 min of silence | Fail = turn_on within 30 min |
| D3 — Master Bath Toilet vents on dwell | Fan ON within dwell_s of occupancy edge, OFF after presence-runtime window | Fail = 0 turn_on across a confirmed sit-down |
| D3 — Guest Bedroom 1 Bathroom vents on dwell | Same | Same |
| D3 — Dwell + humidity same tick → one turn_on | Recorder shows single turn_on event, not two | Fail = double emit |
| D4 — Laundry threshold change takes effect next tick | Live threshold entity reflects new value within one coord tick | — |

Validation table rewritten with observed values + the Powder HA-automation-disabled flag after live validation; cycle not closed until this table is in the README.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
