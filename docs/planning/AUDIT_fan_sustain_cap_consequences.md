# AUDIT — Fan Sustain-Provenance Cap (AWAY-BLOCK-1 rec 2) consequences

**Date:** 2026-08-13 · **Status:** ADVERSARIAL AUDIT · no code changes

## Executive verdict

**NOT Tier-1. Minimum Tier-2-DB; recommend Tier-3.**

Rec 2 ("comfort-fan sustain requires non-mmwave-sole provenance after
N min, or a max mmwave-sole runtime cap") is NOT a small local change.
Three structural reasons:

1. **Provenance is not plumbed to the fan-decision site.** The oracle's
   `FanDecisionSnapshot` (`fan_policy_oracle.py:162-177`) carries no
   provenance field — only `now / sleep_state / sleep_axis / house_state
   / is_hvac_managing / entities / observed_any_on`. The primitive
   `mmwave_sole_here` exists in the presence pipeline
   (`coordinator.py:2270`) but is not visible to the oracle or to the
   HVAC-tier snapshot builder (`hvac_fans.py:1495-1517`,
   `hvac.py:2782`, `hvac_predict.py:1154`, `automation.py:2891`,
   `presence_fan_recheck.py:1165`). Rec 2 = **new snapshot field + 5
   wire-in sites** — the classic wire-in-anchor surface (see
   MEMORY: "wire-in anchor").
2. **Fights the v4.7.13 sleep-trust doctrine.** Motionless sleeper +
   no PIR = legitimately mmwave-sole for 8h. A cap-fire mid-night is a
   comfort regression exactly where the doctrine says "trust mmWave."
3. **Likely REDUNDANT with existing SUSTAIN gate.** The Tier-3 D2
   mmwave-demoted latch (`coordinator.py:2260-2308`) already demotes
   mmwave-sole occupancy when the fan is on → substrate flips vacant
   → normal W1 vacancy-off turns the fan off. If AWAY-BLOCK-1 saw
   sustained mmwave-sole fans, the D2 latch has a GAP. Fix the gap
   (one place) before adding a second mechanism.

**Recommended first step (probe-before-build per CLAUDE.md
"Measure Before You Build"):** enumerate the AWAY-BLOCK-1 offending
rooms and confirm whether D2 latch fired. If it didn't, the correct
Tier-1 change is inside the D2 latch (extend clear-conditions, close
a bypass), not a new sustain-cap primitive.

## Provenance-plumbing assessment

| Layer | Has `mmwave_sole`? | Site |
|---|---|---|
| Presence fusion | YES | `coordinator.py:2270` (`mmwave_sole_here`), `_last_pir_motion_time` @ 331 |
| Fan-veto (creation + demotion) | YES | `coordinator.py:2283-2308` gate, `fan_veto.should_veto_comfort_fan` |
| `FanDecisionSnapshot` (oracle input) | **NO** | `fan_policy_oracle.py:162-177` — 7 fields, no provenance |
| Oracle verdict (`_may_turn_on_inner` / `_may_turn_off_inner`) | **NO** | only checks manual holds + sleep-axis |
| HVAC-tier snapshot builder | **NO** | `hvac_fans.py:1495-1517` (`_build_fan_snapshot_hvac`) |
| Room-tier snapshot builder | **NO** | `automation.py:2891` |
| Pre-arrival / vacancy sweep snapshot | **NO** | `hvac.py:2782`, `hvac_predict.py:1154` |

Adding the field = 1 dataclass edit + 5 builder edits + 1 read site
in the verdict inner. Manageable, but crosses coordinator boundaries
and mutates the oracle contract → Tier 2-DB by CLAUDE.md standing
policy on shared primitives.

**Additional plumbing gap:** the cap is TEMPORAL, not per-consult. It
needs a per-room `last_non_mmwave_occupied_ts` (or equivalent) so the
oracle can compute "mmwave-sole runtime". No such field exists in
`_RoomRecord` / `RoomFanLedger`. Adding one is another shared-state
change with restart semantics to consider (RAM-only ledger vs. restore).

## The 7 questions

| # | Question | Verdict | Repro |
|---|---|---|---|
| 1 | mmwave-sole rooms w/ real occupant (reader) | **BLOCKER without carve-out** | 6 no-PIR rooms → cap kills fan mid-heatwave. Carve-out ("skip if PIR absent from config") resurrects the loop — the fan-ghost class it's meant to break is exactly the no-PIR-room class. |
| 2 | Sleep bedrooms w/ motionless sleeper (v4.7.13 doctrine) | **BLOCKER without sleep-axis exemption** | Master @ 03:00, sleeper motionless 45min, phone across room (LEFT_BEHIND). Cap fires → fan off → wake-up. Fights `FAN_TRUST_STATES` (`hvac_fans.py:781`). Fix: cap MUST defer under `sleep_axis="house_state" && house_state in FAN_TRUST_STATES` AND under `sleep_axis="room_window"`. |
| 3 | FAN-MANUAL-1 hold precedence | **harmless (contingent on impl)** | Oracle `_compute_off_verdict` already returns `DEFER("manual_on_hold")` for OFF under live hold (`fan_policy_oracle.py:663-665`). Cap-fire routed as `oracle.actuate("off", trigger="FAN_TRIGGER_SUSTAIN_CAP")` inherits this correctly. Impl bug: bypass the oracle and manual hold is silently lost. |
| 4 | Oscillation at cap boundary | **needs-guard** | Cap fires → substrate decays 2-3min → real occupant re-detected → fan re-arm → cap resets → fires N min later. Period-N flap. Oracle's edge-dedup (`_last_verdict[(trigger, hold_id)]`) does NOT cover this; needs `min_time_since_last_cap_fire` cooldown ≥ 2× N. |
| 5 | HVAC compensation cost inversion | **needs-guard** | Fan off → room heat delta widens → zone compressor cranks. Zone-duty off-phase honesty (v5.73.0 S14) exposes it in accounting; operator sees "URA killed my fan AND my AC bill spiked." Guard: if cap fires under `is_hvac_managing=True`, log a diagnostic bump; consider defer to next zone-off boundary. |
| 6 | Bathroom / humidity fan scoping leak | **harmless** | Humidity/bathroom-exhaust (v5.6.0 unification) do NOT wire through `oracle.actuate` — they run on a distinct subsystem. All 9 oracle wrap sites (W1-W12) are comfort/HVAC-zone fans. Scoping by "trigger_path ∈ comfort-family" at cap-check is clean. |
| 7 | Oracle chokepoint sufficiency | **NEEDS PLUMBING** | Oracle IS the chokepoint for per-emit verdicts. But cap is not per-emit — it's a temporal watchdog. Either (a) new HVAC tick site re-evaluates every N min and emits `FAN_TRIGGER_SUSTAIN_CAP` through oracle, or (b) new oracle-owned async timer. (a) simpler + honors existing tick cadence. Neither is "small". |

## Three sharpest second/third-order consequences

### C1 — Sleep-fan silent kill (BLOCKER without exemption)
**Scenario:** Zone-1 master, house_state=sleep, per-spec sleep-fan LOW,
motionless sleeper (no PIR fire in 60min), phone LEFT_BEHIND (BLE
absent), Zigbee mmWave holding occupancy. Rec-2 cap (say N=90min)
fires at 04:30 → fan off. Sleeper wakes at 05:15 hot. Ships → next-day
kanban card.
**Why sharp:** the v4.7.13 doctrine EXISTS because bedrooms fail
exactly this way. Rec 2 as literally stated re-opens the wound.
**Fix:** cap MUST defer whenever `snapshot.sleep_axis is not None`
(i.e., any sleep context — house-state OR room-window). Then it only
fires on awake-house comfort fans in low-signal rooms.

### C2 — Carve-out inversion: the cap protects the wrong rooms
**Scenario:** operator carves out (a) no-PIR rooms, (b) sleep contexts,
(c) manual-on hold, (d) HVAC-managed rooms. What's LEFT? Only PIR-
equipped, awake, non-HVAC-managed, non-manual rooms — the exact
population where the D2 mmwave-demoted latch (`coordinator.py:2266`)
would ALREADY have demoted the mmwave-sole occupancy → the vacancy
path (W1) ALREADY turns the fan off. Cap becomes dead code.
**Why sharp:** whether the cap fights the doctrine (C1) or is dead
code (C2), the operative value of rec 2 is near-zero. The AWAY-BLOCK-1
symptoms are more probably a D2 GAP (latch not triggering / cleared
too aggressively) than a missing new mechanism. Fix the latch.
**Fix:** BEFORE building, run a one-shot recorder probe (per
CLAUDE.md probe-first) on the offending rooms: did
`_mmwave_demoted_latch` fire during the sustained-fan window? If no
→ the fix is inside the latch, not a new primitive.

### C3 — Substrate-cap limit cycle (needs-guard)
**Scenario:** awake-house room, PIR-equipped but a real occupant is
sitting still reading. PIR times out (60s), fan on → cap-N fires →
fan off → occupant unchanged, still mmwave-sole → substrate flips
vacant (2-3 min) → occupant fidgets → PIR fires → fan re-arm → cap
counter resets → repeat every N+decay minutes. Period-N flap.
**Why sharp:** oracle's per-`(trigger, hold_id)` verdict dedup does
NOT catch this because each cap-fire has a fresh hold_id (external
adopt increments hold_id, `fan_policy_oracle.py:758`). Anti-flap
machinery (v5.70.0 no-flap evidence) covers rapid ON/OFF churn but
not a stable period-N.
**Fix:** cooldown ≥ 2×N after a cap-fire before the cap can arm
again for the same room. State lives on `_RoomRecord`
(`last_sustain_cap_fire_ts`); adds another field to the ledger.

## Recommended guards / carve-outs / precedence

If rec 2 is actually built (only after probing D2 latch gap):

1. **Defer under any sleep context.** `snapshot.sleep_axis is not None`
   → cap NEVER fires. Covers per-room sleep-window (Zone bedrooms) AND
   house_state sleep/waking (v5.51.x sleep-fans-per-spec).
2. **Route as an oracle trigger, not a bypass.** New
   `FAN_TRIGGER_SUSTAIN_CAP`; call via
   `async with oracle.actuate(room, FAN_TRIGGER_SUSTAIN_CAP, snap,
   "off"):`. Inherits FAN-MANUAL-1 hold precedence for free.
3. **Post-fire cooldown ≥ 2×N.** New `_RoomRecord` field prevents C3
   limit cycle.
4. **HVAC-managed diagnostic.** If cap fires with
   `snapshot.is_hvac_managing=True`, emit a diagnostic so the
   compressor-uplift cost (C4/C5) is observable.
5. **No-PIR-room carve-out is a design cliff.** If a per-config
   "trust mmWave-sole here" flag is added, cap must consult it. Or
   accept that no-PIR rooms simply don't get rec 2's protection —
   they instead need presence-side fixes (D2 latch tuning, camera-
   person fusion) which is a different cycle.
6. **Kill switch:** `FAN_SUSTAIN_CAP_S = 0` disables. Numbers-Get-Knobs
   ladder rung: **module constant** (safety bound; operator does not
   tune this hourly — CLAUDE.md rung 1).

## Framing-disjoint reviews (if built)

- **A — local correctness:** cap arithmetic, snapshot field, verdict
  precedence, kill-switch semantics.
- **B — plumbing completeness (mutation-verified per site):** every
  `FanDecisionSnapshot(...)` construction populates the new field
  correctly. Detach the value at each of the 5 builder sites; a
  specific test must fail per site.
- **C — cross-coordinator + doctrine:** sleep-trust invariant
  (falsifiable form: "for any tick where `sleep_axis is not None` AND
  `mmwave_sole=True` AND fan_on_duration > cap, cap MUST NOT emit
  OFF"), fan_veto ↔ D2 latch ↔ new cap interaction (no double-
  demote, no C3 limit-cycle).
- **D (Tier-3 only, adversarial completeness):** re-enumerate every
  emission site that could bypass the cap — automation.py W1/W2/W3,
  hvac.py W8/W9, hvac_fans.py W4, hvac_predict.py W12, safety W11.
  For each: does the sustain-timer reset correctly on
  external-adopt? On restart (RAM ledger empty)? On
  RECHECK_PAUSE/RESTORE?

## Non-goals / out of scope

- Bathroom exhaust / humidity fans (v5.6.0 unification, separate
  actuation path, not through `oracle.actuate`).
- Sleep-fan sustain policy (owned by v5.51.x sleep-fans-per-spec).
- The D2 mmwave-demoted latch itself — audited separately.
- Camera-person fusion as an alternative provenance source (own
  cycle: fusion library backlog `PLANNING_paper_and_oss_fusion_library.md`).
