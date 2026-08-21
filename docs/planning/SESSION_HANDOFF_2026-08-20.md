# Session Handoff — 2026-08-19 → 2026-08-20 (overnight)

Prepared to clear context. This is the authoritative pickup for the next session.
Board is source of truth (`docs/planning/KANBAN.md`); this doc adds the narrative + open decisions.

---

## ⛳ OPEN DECISIONS AWAITING OPERATOR (do these first)

1. **EVSE drain-precedence bug — stopgap vs real fix** (`EVSE-DRAIN-PRECEDENCE-KNOB-80-1`).
   Operator to choose: (a) **stopgap now** — set `number.ura_energy_coordinator_ev_battery_drain_soc` = 10
   so tonight actually sequences drain-then-charge (static, non-adaptive patch); AND/OR (b) **real fix cycle**
   — bind the DP drain target to `current_offpeak_drain_target` (forecast-based), Tier 2-DB/3, plan pins the
   producer this time. Nothing set yet — awaiting the call.
2. **STEP 2-day forcing gate fires 2026-08-21 09:00 CDT** (cloud routine `trig_01XZno8URQxUmuiNJczBjKaw`).
   Flip `select.ura_chatter_mode` to `act` or declare moot. Evidence accumulating (see STEP below).
3. **Routine-care dashboard** (`ROUTINE-CARE-DASHBOARD-1`) — probe done, verdict GO. Operator chose "probe
   first"; probe complete (`AUDIT_routine_care_probe_2026-08-19.md`). Next is scope the Tier 2-DB build OR defer.
4. **Daily memory digest** (operator picked use #3, Ollama-reasoned, compact, hand-testable) — next step is the
   hand-test/D0 (pull one real day of node-memory, hand-write the wanted digest, confirm memory holds the facts).

---

## ✅ SHIPPED THIS SESSION (live)

- **v5.85.0 STEP physics chatter-quarantine — SHADOW-FIRST.** Tier-3 full gauntlet. Boot-validated L1/L2/L3
  PASS (mode=shadow, K=10/T_floor=1.0, zero errors). L4/L5 organic. See `README_v5.85.0.md`.
- **deploy.sh `--why` forcing gate** — a real (carded) release now REQUIRES a substantive vibememo reasoning
  trail (≥200 chars, validated pre-push); `vibememo_ship.py` re-validates + writes a `type: reasoning` entry.
  Fixes the thin auto-stub class. Memory: `feedback_vibememo_quality_never_thin`.
- (earlier same session) **v5.84.0 fan-recheck deadlock fix + v5.84.1 presence-startup hotfix** — live,
  incident closed. Fan-recheck confirmed working: `fan_recheck_eval_count`=111 (was frozen at 1).

---

## 🔬 THE BIG DIAGNOSTIC THREAD — "nothing is managed" → actually "everything managed, poorly legible"

Operator flagged HVAC/arrester/battery as unmanaged. Rigorous tracing (operator: *"tired of half-arsed
tracing"* — a fair correction; the deep code-read trace is what resolved it) yielded:

- **HVAC — MANAGED.** Occupancy-aware presets tracked home(77/70)/away(80/66)/sleep(75/68) all day.
  `manual` preset = URA's control-write mechanism on Bryant units, NOT an escape. Away-setback fires; cooling
  while a zone's Back-Hallway *room* is empty is correct because ZONE 3 serves multiple rooms.
- **Arrester — WORKING.** 24h recorder history: **15 overrides detected, 14 cleanly reverted, 1 compromise
  (12:29).** My earlier "idle/0 overrides" was a post-reload counter-reset snapshot (misleading). Overrides
  are EXTERNAL (Bryant native schedule fighting URA) — operator did not touch HVAC. Immune list has
  `person.oji_udezue`.
- **Battery reserve 37% — NOT a stuck write (my misdiagnosis, corrected).** It's the `evse_battery_hold`
  correctly pinning reserve to SOC while the EV charges from grid (battery idle, not drained into car). I had
  read the wrong entity (local Enpower=10, un-driven); URA writes the cloud oracle `iq_battery_hacs`=37 which
  the Envoy enforces. The "pending stuck 2701s" was cloud-oracle-flap noise. Card `BATTERY-RESERVE-CLOUD-ORACLE-FLAP-1`.

### …which uncovered the REAL defect (code + plan + README verified):

**`EVSE-DRAIN-PRECEDENCE-KNOB-80-1` — the drain-precedence re-eval (leg-2: release-hold → pause EV →
drain battery to off-peak floor) is BUILT + ENABLED but never fires.** Root cause, triple-verified:
- **Code:** DP drains toward the static manual knob `_ev_battery_drain_soc` (=80) at `energy.py:4456/4522/4540/4555`.
  Gate `energy_drain_precedence.py:656` (`if soc ≤ drain_target_soc: already_below_target`) → 37 ≤ 80 → never
  transitions. The forecast off-peak target (`current_offpeak_drain_target`=10) feeds ONLY `BatteryStrategy`
  (`energy.py:257`), NEVER the DP. `_ev_battery_drain_soc` is written only by the operator number entity —
  never from the forecast.
- **Plan** (`PLANNING_evse_drain_precedence.md`): Knobs table has **no drain-target knob**; `drain_target` is an
  **unbound input symbol** in D2/D3 (example `drain_target = 15`). The plan pinned the CONSUMER, never the
  PRODUCER — a textbook Producer-check gap that plan-review missed.
- **README:** silent on the source too.
- **Consequence (both legs of the same non-transition):** reserve never released (battery held at 37) AND the
  EV is never paused to drain first → car charges from grid all night (verified: `battery_power` 0.07 kW idle,
  `net_power` ~12 kW grid import, DP state `hold_pre_eval`), battery never empties for tomorrow's solar. The
  "don't drain battery INTO car" mandate IS honored (car on grid); the drain-FIRST sequencing is dead.
- **Fix:** bind DP `drain_target` to `current_offpeak_drain_target`; decide if `_ev_battery_drain_soc` survives
  as a distinct protective/charge-above floor. Stopgap: set the knob to 10. (See Open Decision #1.)

---

## 🗂️ CARDS CREATED THIS SESSION

| ID | Status | Gist |
|---|---|---|
| `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` | inbox | **THE defect** — DP drain target mis-sourced (static 80, not forecast 10); code+plan+README verified |
| `BATTERY-RESERVE-CLOUD-ORACLE-FLAP-1` | inbox | Misdiagnosis corrected; residual = cloud-oracle flap pollutes write-verify (Tier-1 hotfix) |
| `ROUTINE-CARE-DASHBOARD-1` | pre-planning | Use D — per-person routine care dashboard, color signature, sensor-only. Probe GO. |
| `ROUTINE-DETECTOR-NO-DISCHARGE-1` | inbox | RegimeDetector math faithful, but no discharge/dedup/consumer (331 dead-letter) |
| `ZIRI-COLLEGE-PERSISTENT-AWAY-1` | inbox | Resident persistently away; drift detector caught pre-departure, vacation-guard suppresses clean absence; NO departure alert exists |
| `STEP-SHADOW-EVIDENCE-WATCH-1` | inbox | Nightly shadow-evidence check until the 08-21 gate |
| `PERIMETER-PHANTOM-XCORR-1` | inbox (reframed) | Live 12:09 garage walk-in = real person + ~5s snapshot lag, NOT phantom; hand-exam lag before building; don't ship corroboration-demote alone |

Also: STEP + fan-recheck cards marked shipped_organic via deploy.

---

## 📌 KEY CORRECTIONS / LESSONS THIS SESSION

- **I was wrong ≥3×** and the operator caught each: (1) presented shipped-organic cards (FAN-MANUAL, DIMMER,
  ARREST-COMFORT, HVAC-PRESET-FLAP — all shipped/operator-closed) as "open bugs"; (2) called URA-managed
  `manual`-preset HVAC "unmanaged"; (3) declared the battery reserve a "stuck write" from a snapshot of the
  wrong entity. **Root fix: stop snapshot-poking + hypothesizing; read code/recorder end-to-end before
  asserting.** The Ziri guest-return risk was also a phantom (he keeps his phone).
- **Operator mandate reinforced:** rigorous, complete tracing over iterative guessing. Producer-AND-Consumer
  check is the through-line — the DP bug is precisely a producer-left-unbound failure.
- **New memory saved:** `feedback_vibememo_quality_never_thin` (+ deploy `--why` gate enforces it).

---

## 🧭 WORKSTREAMS IN FLIGHT

- **STEP** — shadow live; 2-day gate 08-21 (Open Decision #2). Nightly evidence watch card active.
- **Memory-foundation near-term uses** (before the agentic layer): operator picked the **daily digest** (#3).
  Ladder framing: *answer → explain → suggest → act*; we're building "explain/digest" before "act". The
  battery saga is the poster child for the legibility gap the digest/explainability surface would close.
- **Routine detector** — care dashboard (GO, needs plan) + the no-discharge/dedup residual.
- **Board health:** tactical bug queue is largely CLEAR (36 shipped-organic-open are done-pending-validation,
  not open work). Genuinely-open builds: the DP fix, `PERIMETER-PHANTOM-XCORR-1` (snapshot-lag reframe),
  routine work. Strategic: `ROADMAP-STALE-AGENTIC-LAYER-1` (needs operator priority call).

---

## 🔧 LIVE-STATE ANCHORS (as of ~2026-08-20 00:25 CDT)

- House: `sleep`, census 3, people home. Battery SOC 37% (held by evse_battery_hold, EV charging from grid).
- `select.ura_chatter_mode` = shadow. `number.ura_chatter_burst_k`=10, `..._t_floor`=1.0.
- DP state `hold_pre_eval` (eligible, will not transition due to the drain_target=80 bug).
- develop tip after this session's commits; all pushed to origin + gitea.
