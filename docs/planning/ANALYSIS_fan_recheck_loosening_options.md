# Fan-Recheck Loosening — Options Memo (livability, algo-only)

**Date:** 2026-07-18 · **Scope:** `presence_fan_recheck.py` + `const.py:387-473`. Algo-only.
**Operator brief (verbatim):** "Investigate ways to loosen in a way that makes it effective for livability based on just the algo."
**Author:** ura-planner (delivered inline; filed by orchestrator).

## 1. Ground truth (2026-07-18 audit)
- Master ON; 6 eligible rooms (Study A, Living Room, Master Bedroom, Guest Bedroom 1, Kitchen, Game Room).
- LIFETIME fires: 1 (Living Room 2026-07-13 `occupied_confirmed`; pause invisible in device history).
- Master Bedroom permanently L1-vetoed (wearable resident); vacated outcomes ever: 0.
- Gates (`_is_eligible` L224-389): mmwave-sole 3 ticks; `house_state != SLEEP`; **hard veto** on BEDROOM+MEDIA_ROOM types on BOTH BLE paths (L358 tier-1 L2, L376 tier-0/2 C1 guard); BLE ladder L1/L2; boot-settle; `MAX_PER_HOUR=2`; cooldown 1800s. Timing: arm 60 → spindown 30 → window 60 → cooldown 1800.
- Interpretation: mechanism is essentially inert. 1 confirm / 0 vacates in 5 weeks = strong prior gates are too conservative to buy anything.

## 2. Division of labor — Layer-1 (silent) vs Mode-2 (this file)
- **Layer-1** (`presence.py:3208 _compute_fan_interference_rooms` + `:3369 _apply_fan_interference_gate` + `const.py:398 CONF_FAN_INTERFERENCE_HOLD_S=300`): silent, always-on, D3-gated. When fan-interference-suspect AND BLE ladder not-corroborated, EXTENDS occupancy via `_room_occupied` hold. Can only lengthen, never shorten. Job: avoid flapping vacant on noisy mmwave.
- **Mode-2** (this file, opt-in): actively **PAUSES the fan** to interrogate; if mmwave falls with airflow off, actively **RELEASES occupancy** (`OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE`, const.py:473). Only mechanism in the system that can *shorten* occupancy on a fan-shake suspect.
- **Consequence:** Mode-2's exclusive value is the DROP. Anything that would silently extend belongs in Layer-1. A loosening that doesn't buy more legitimate drops isn't Mode-2's business.

## 3. What a fan-faked mmWave hold actually costs (livability accounting)
Trace of stuck-occupied while empty:
1. **Lights stay on** — room auto-off is gated on `not occupied`. Primary cost: lit rooms hours later; energy + switch wear.
2. **HVAC treats zone as occupied** — `hvac.py:1055` vacancy-override never fires → setpoint held on empty room; real cooling-season dollars.
3. **Energy Coordinator context** — occupied rooms bias load-shed exemptions (small).
4. **Presence-count inflation** — house-state/away-veto denominators drift (secondary).

NOT a cost: "wasted fan noise" — the fan was going to run anyway. Frame is **stuck lights + stuck HVAC in an empty room**. Payoff of Mode-2 is bound to rooms where the false hold drives OTHER expensive actuations.

## 4. C1 rationale
`HIGH_STILL_RISK_ROOM_TYPES = {BEDROOM, MEDIA_ROOM}` (L92). v4.7.22 C1 enforces on BOTH BLE paths because a still napper reads exactly like empty in ~60s pause. Trust-asymmetry doctrine: BLE-absence is WEAK evidence. Wake-the-napper-by-dropping-AC is a livability HARM that dwarfs any lights-off benefit.

## 5. Institutional context verified
- v4.7.20 Layer-1 silent gate; v4.7.22 C1 guard mirror; fan-noise mmwave mitigation backlog (2026-06-03, layered strategy places drops LAST).
- Trust-asymmetry doctrine: BLE-presence authoritative; BLE-absence weak; BLE-absence-authorized drops require physical re-verification.
- Prior planning: `docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md` (D1-D6).
- v4.7.19 provenance split makes `recent_occupancy_sources` mmwave-sole detection cheap.
- Numbers-Get-Knobs: all tunables here already exist as module consts; no new knobs proposed.
- Marginal-Benefit Decomposition (2026-07-14) applied per candidate below.

## 6. Candidate loosenings

### (a) `MMWAVE_HISTORY_TICKS` 3→2 (or time-based)
- **Change:** `const.py:462` 3→2, or wall-clock "mmwave-sole ≥30s" at L266-279.
- **Benefit:** shortens arm-latency ~1 tick. At LIFETIME=1 the ticks-gate is clearly not the bottleneck.
- **Veto counter:** `veto_mmwave_history_ticks` must be >>0 for weeks to justify.
- **Verdict: not without data.** Pure churn otherwise.

### (b) High-still-risk type veto → whole-house BLE-absence-of-all-trackers
- **Change:** L376-378 + mirror L358-360. Allow when NO trustworthy phone for ANY tracked person exists ANYWHERE in the home AND the room's zone has no L2/L3 hit. Keep room-type as conservatism DIAL via `ROOM_TYPE_RECHECK_FACTOR` (const.py:466-470, applied L449) — bedrooms ≥1.5× window (needs config audit; not set today).
- **Benefit:** unlocks Master Bedroom + Guest Bedroom 1 during confirmed empty-house windows — the daytime empty-house case where a napper can't exist by construction. Unattended bedroom lights + AC holds drop cleanly.
- **Trust-asymmetry:** BLE-absence here is bounded, not eliminated: the recheck's spindown+window is a real physical probe, and the whole-house denominator is materially stronger than adjacent-room absence. Acceptable IFF (i) GUEST house-state hard-vetoes (untracked guest = residual failure) and (ii) bedroom recheck-factor ≥1.5×.
- **Risk:** C1 napper harm; residual = untracked guest sleeping during whole-house-absent window.
- **Veto counters:** `veto_high_still_risk_type` × synthesized `whole_house_ble_absent` non-trivial for weeks AND `veto_ble_l1_room` zero in those windows.
- **Verdict: worth it IFF data supports AND GUEST gate + bedroom factor ship coupled.** Highest livability ceiling. Tier 3.

### (c) SLEEP exclusion narrowed to sleep-relevant zones
- **Change:** L258-260 + arm-expiry mirror L619-621: veto only when the room is in a bedroom zone OR room-type BEDROOM. A downstairs Living Room fan at 23:30 while the house sleeps upstairs is exactly the wasted-hold case.
- **Benefit:** overnight downstairs stuck lights drop; downstairs-zone AC releases. Real cooling-season dollars, exactly when nobody notices the pause.
- **Risk:** low — v4.7.13 keep-fans-through-sleep is bedroom-specific; motion mid-flight cancels (L578).
- **Veto counter:** `veto_house_sleep` × `{room_type, room_in_bedroom_zone}` — dominated by non-bedroom rooms confirms.
- **Verdict: worth it.** Cleanest standalone win.

### (d) `MAX_PER_HOUR` 2→4 — **never on its own** (cap not binding; compounds napper exposure if b/c ship). Revisit only if `veto_rate_limit` appears post-loosening.

### (e) Pause-window shortening — **never.** The window IS the anti-C1 physical-evidence bound; zero upside at ~1×/week firing.

### (f) Cooldown 1800→900 — **not without data** (never binding today).

### (g) Arm with lights-only (no fan running) — **never in this machine.** No fan to pause = no physical intervention = the "recheck" is the same observation twice = BLE-absence-authorized drop. Real problem, wrong organ: push to Layer-1 extension backlog (silent mmwave-sole confidence decay) or a new physical probe.

### (h) Invert default (recheck as primary vacancy prober) — **never.** (g) scaled up; also Layer-1's scope.

### (i) Split OUTCOME model: positive corroboration for VACATE
- **Change:** `_on_pause_window_done` L494-506 — add a positive leg (lux-delta daytime / temp-rate consistent with vacancy / repeated L1-absent snapshot) to the current "mmwave stopped driving" negative.
- **Benefit:** loosen intake, harden verdict — makes (b) safe.
- **Verdict: worth it as coupled prerequisite to (b);** valuable alone as groundwork.

## 7. Top-3 by livability-per-risk
1. **(c)** SLEEP → sleep-relevant zones only. Standalone, no doctrine load, real overnight waste.
2. **(b)+(i)** whole-house-absence softening WITH hardened vacate verdict + GUEST gate + bedroom factor. Highest ceiling; Tier 3; data-gated.
3. **(i) alone** — raises confidence in every future firing; operator-trustable log.

## 8. Never-ship (doctrine cites)
(e) window shortening — C1 physical-evidence bound. (g) armless probe — trust-asymmetry violation. (h) inverted default — same, plus scope violation.

## 9. Data required (from the observability cycle) to promote
- `veto_house_sleep` × room-type/zone → gates (c).
- `veto_high_still_risk_type` × `whole_house_ble_absent` → gates (b); `veto_ble_l1_room` per-room/hour must be zero in those windows.
- `veto_mmwave_history_ticks` / `veto_rate_limit` / `veto_fan_not_on` / `veto_boot_settle` → bounds (a)(d)(f).
- Minimum 2 weeks continuous; 4 preferred (cover a travel week for sustained whole-house absence).

**Recommendation:** observability first → **(c) as a Tier-1/2 cycle after ~2 weeks of confirming counter data** → park **(b)+(i)** as Tier-3 pending 4 weeks + GUEST gate + factor audit. (a)/(d)/(f) only if counters show them binding.
