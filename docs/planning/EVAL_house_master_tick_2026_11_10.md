# EVAL — House master tick ("planned synchrony") — 2026-11-10

**Type:** evaluation only. No build, no card change, no code.
**Operator idea (2026-11-10):** "one master loop at high resolution but with separate timer loop multiples that feed rooms and coordinators from the master. So there is planned synchrony."
**Verdict: PARK the master tick (keep `URA-CENTRAL-TICK-WHEEL-1` parked). Do not build a reconcile tick either; the one real candidate already has a home.** Details in §6.

**Read-first compliance.** HVAC timers are in scope, so I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §1–§2 (decision loop and timing) and the §10 corrections ledger (C8, C10, C18, C24 are the timing entries). I did not read all 726 lines; nothing here proposes an HVAC change, and no ledger claim is re-asserted. The presence timers below are inventoried only. I did not read the presence state-of-play doc, and no presence claim beyond the timer table depends on it.

**Doc drift found (code wins):** HVAC state-of-play §2 cites the 5-min tick at `hvac.py:1356-1360`. It now lives at `hvac.py:1692-1696`. The same section still has a bullet saying the occupancy fast path was "DESIGNED, never built". The row above it says it shipped in v5.103.20 (`_on_room_refresh`). The doc owner should drop the stale bullet and update the line numbers.

---

## 1. Prior art: this was already decided

| Source | What it says |
|---|---|
| Card `URA-CENTRAL-TICK-WHEEL-1` (`kanban.data.yaml:4033`), **parked** 2026-09-16, operator-approved | This is the same idea: one base clock, per-consumer divisors and phase offsets. Verdict PARK: "real benefit is a cleaner timing layer, not a feature." |
| `docs/planning/MEMO_ura_central_tick_wheel_2026_09_16.md` | Idea of record. The thundering-herd objection was **struck**, because offsets solve it. The watchdog stall history is a **design constraint** (no synchronous fan-out), not an objection. Revival trigger: **(a)** a 3rd/4th dedicated fast sub-loop need, or **(b)** a deliberate re-architecture pass on the loop layer. |
| Origin need: HVAC fast-in (`HVAC-ZONE-CONDITIONING-DEMAND-1`) | The memo chose a "targeted 60 s HVAC sub-loop". **What actually shipped (v5.103.20) was event-driven:** `_on_room_refresh` is a `DataUpdateCoordinator.async_add_listener` on every room coordinator, plus a per-zone `async_call_later` for the exit (HVAC SoP §2). The one concrete need that motivated the tick-wheel was met **without any periodic loop**. That weakens the case. |
| `RELOAD-WATCHDOG-HAZARD` (done), optimizer write-flood incident (memory), `AUDIT_db_write_worker_slow_2026_09_29.md` | Event-loop stalls are the live hazard. The DB audit shows a **~140 s whole-loop freeze on every boot (12/12 restarts)** with the cause unknown. A tick does not touch that cause. |

**Has the revival trigger fired?** Trigger (a): in the spirit of the memo, no. Since 09-16 one more 60 s loop has appeared: the excursion auto-release sweep (`hvac.py:1779`, `EXCURSION_AUTORELEASE_SWEEP_S=60` at `hvac_excursion.py:109`). With solar-follow and the presence/safety 60 s loops, that makes several 60 s loops. But none of them was hard to add, and none had an ordering bug. The trigger was meant as "adding cadences is getting painful", and there is no evidence of that pain. Trigger (b): no re-architecture pass is open.

---

## 2. Inventory of periodic timers (`custom_components/universal_room_automation`)

Method: `grep -rnE "async_track_time_interval\(|async_call_later\(|update_interval|async_track_time_change\(|async_track_point_in|asyncio\.sleep\("`. About 140 hits. They fall into three kinds:

- **Recurring loops.** These are the only things a master tick could own. Tabled below.
- **One-shot, event-armed timers** (`async_call_later`). There are dozens: about 18 in `hvac_override.py` (grace, compromise, nudge restore/eval/settled, durable, reset-outcome), plus HVAC fast-path arm/exit, presence fan-decay and guest persistence, NM cooldown/repeat, perimeter dispatch/release/agreement, transit validator, switch restore retries, the lock-regime boot recheck (`security_lock_regime.py:569`), and others. These are **deadlines relative to an event**. A tick could only quantise them, which adds up to one base period of jitter to each deadline. **They must stay out of scope.**
- **`asyncio.sleep` inside actions** (cover pacing, flash, music transfer, DB batch yields at 0.1 s, `hvac_fans` stagger, NM loops). These are pacing inside a running action, not schedules. Out of scope.

### Recurring loops

| # | Site | Period | Owner / scope | What it does | Reads state another loop writes? | Phase |
|---|---|---|---|---|---|---|
| 1 | `coordinator.py:693` `update_interval=30+jitter` | 30 s + U(0,5) s | Room DataUpdateCoordinator, **one per room (~40)** | Room occupancy, sensors, automation | Reads HA states (event-fresh), not other loops' memory | Drifts per room. The jitter was added *on purpose* after "31 rooms ... 20-39 s event loop contention" (`coordinator.py:685-687`) |
| 2 | `person_coordinator.py:163` `UPDATE_INTERVAL` 30 s (`const.py:55`) | 30 s | House, person tracking DUC | Person locations | Bermuda/HA states | Boot-aligned |
| 3 | `__init__.py:3062` census | 30 s (`SCAN_INTERVAL_CENSUS`) | House | Census recompute | Reads person/camera state; also event-driven | Boot-aligned |
| 4 | `aggregation.py:6149` presence decay | 30 s | Per `PersonLocationSensor` | Staleness decay | Also listens to `person_coordinator` updates (`:6121`) | Per-entity |
| 5 | `aggregation.py:1213`, `:4384` | retry intervals | Aggregation entities | Retry until sources exist | — | Self-cancelling |
| 6 | `presence.py:3194` `_periodic_inference` | 60 s | Presence coordinator | House-state inference | Room/census outputs (via states) | Boot-aligned |
| 7 | `safety.py:1276` / `:1282` | 60 s / save interval | Safety | Sustained flood/humidity checks, persist | HA states | Boot-aligned |
| 8 | `energy.py:1847` `_solar_follow._tick` | 60 s (`SOLAR_FOLLOW_TICK_S`) | Energy | Solar-follow EVSE | Energy decision state (same coordinator) | Boot-aligned |
| 9 | `hvac.py:1779` excursion sweep | 60 s | HVAC | Auto-release expired excursions | HVAC in-memory excursion table | Boot-aligned |
| 10 | `hvac.py:1692` decision cycle | 5 min (`HVAC_DECISION_TICK`) | HVAC | Full zone cycle (cloud call-rate bound, rung 1) | Room conditions (pulled at cycle start), house state, energy signals | Boot-aligned; also event-driven fast runs |
| 11 | `energy.py:1289` decision cycle | 5 min (`DEFAULT_DECISION_INTERVAL_MINUTES`, CONF knob) | Energy | Battery/TOU/EVSE | Envoy/SPAN states | Boot-aligned, **plus** `async_track_point_in_time` TOU boundary tick (`energy.py:7013`) and drain must-start (`:6874`). These are wall-aligned on purpose. |
| 12 | `optimization.py:973` | 5 min | Optimizer | OC cycle | Reads other coordinators' published sensors | Boot-aligned |
| 13 | `security.py:768` `_handle_periodic_lock_check` | `CONF_SECURITY_LOCK_CHECK_INTERVAL`, default 30 min, 0 = off (`security.py:548,764`) | Security | Queues an intent to the manager to check locks | Lock states | Boot-aligned |
| 14 | `manager.py:794` house-state heartbeat | 300 s (`house_state.py:38`) | CM | Persist house state | — | Boot-aligned |
| 15 | `manager.py:556` anomaly baselines | 3600 s | CM | Persist baselines | — | |
| 16 | `__init__.py:6492` memory baseline | 5 min | House | Diagnostics | — | |
| 17 | `__init__.py:1119` EC role scan | 1 h | Energy | Role scan | — | |
| 18 | `__init__.py:3268` bayesian save, `:3405` accuracy | interval / clock-time | House | Persist/score | — | |
| 19 | `__init__.py:2807`, `:2836` | `track_time_change` (wall) | House | Activity prune, nightly jobs | — | **Wall-aligned on purpose** |
| 20 | `notification_manager.py:1384`, `:5426`, `:5445` | `track_time_change` | NM | Digests, quiet-hours edges | — | **Wall-aligned on purpose** |
| 21 | `room_dwell_model.py:398` | nightly | Room model | Refit | — | Wall-aligned |
| 22 | `energy_outage_ledger.py:628` | `OUTAGE_SWEEP_INTERVAL_H`=24 | Energy | Ledger sweep | — | |
| 23 | `transitions.py:98`, `transit_validator.py:300` | cleanup intervals | Presence | Prune | — | |
| 24 | `frigate_ingress.py:279`, `exterior_track_linker.py:300`, `perimeter_alert.py:1186` (6 h) | sweeps | Camera/perimeter | Reconcile/prune | — | |
| 25 | `sensor.py:4648` (5 min), `:5334`, `:8490`, `:17639/17772/17911` (`OVERRIDE_FREQUENCY_REFRESH_S`), `:4748/:4879` (`track_time_change`) | various | Diagnostic sensors | Display refresh | Read DB/coordinator memory | |
| 26 | `routine_forecaster.py:172` | refresh interval | Forecaster | Refresh | — | |
| 27 | `version_check.py:105` (1 h), `external_url_check.py:102` (24 h) | | House | Housekeeping | — | |
| 28 | `_loop_stall_watchdog.py:46` | 2 s ping | Diagnostics | Detects loop stalls (runs off-loop by design) | — | Must **not** ride a loop-driven tick, because it measures the loop |

**Rough wakeup cost (steady state, computed from the table, not measured live):** about 80/min from room DUCs (40 rooms at 30 s), plus about 2 each from person, census and the per-person decay sensors (one per tracked person, so single digits ×2), plus about 5/min across the 60 s loops, plus well under 1/min for everything slower. **Total ≈ 95–110 wakeups/min.** The stall watchdog's 30/min sits outside the loop. On an HA event loop that handles thousands of state events per minute, this is noise. **Cost is not a problem a master tick would solve.**

**Known contention:** (i) room-DUC boot herd, already fixed by jitter (`coordinator.py:685`); (ii) ~140 s boot freeze on every restart, cause unknown, not timer-driven as far as the audit could tell (`AUDIT_db_write_worker_slow_2026_09_29.md`); (iii) the 2026-06-09 optimizer write-flood, which was per-cycle persist volume, not tick timing; (iv) the reload/restart storm, which was setup-driven (memory `project_reload_storm_refuted_restart_storm_live`). **None of these four was caused by unsynchronised timers.**

---

## 3. Problems a master tick would solve: evidence check

| Claimed problem | Evidence in the record | Would a tick fix it? |
|---|---|---|
| **Ordering hazards** (consumer reads before the producer's cycle) | I found no incident whose root cause was loop phase. Cross-coordinator values move through HA states, dispatcher signals and DUC listeners, all event-ordered. HVAC pulls room conditions at cycle start, and the fast path is listener-driven on room refresh, which is the *correct* ordering by construction. | No. Event ordering already gives "producer before consumer". A fixed phase order would be a weaker guarantee, because it orders cycles, not data. |
| **Stale reads across coordinators** (Bug Class #7 / #14) | #7 is about stale *data sources* (the DB cache path, a dead sensor). #14 is config read once at init. Neither is about timer phase. Real staleness incidents (SPAN SOC miscalibration, the `enphase_ev` grid mismatch, GPS-over-BLE) were wrong sources, not wrong timing. | No |
| **Duplicated "is it time yet" logic** | Real but small. Several 60 s loops each hand-roll a tracker. The one-shot deadlines in `hvac_override.py` are deadlines, not "is it time yet" loops. | Partly. The saving is roughly 10 tracker registrations becoming 10 registrations on a wheel. |
| **Missed-edge recovery** (lock boot recheck) | Real: restart replays and missed edges recur (garage boot recheck `security_lock_regime.py:611`, Bug Class #5 startup races, #10 cross-restart state loss). | Only coarsely. Boot recovery needs "N s after setup, once, with boot-window semantics" (`_in_boot_window`, `GARAGE_LOCKOUT_BOOT_RECHECK_S=120`). A periodic tick gives "sometime within a period", and has no notion of a boot window. |
| **Test determinism** (wall-clock-coupled test family) | Real and recurring: branches `feature/test-billing-wallclock`, `fix/dpm-tests-winter-clock`, `fix/test-bayes-b2-clock-skew`, `feature/oc-live-eval-clockfix`; QUALITY_CONTEXT frozen-time contamination (~line 1705). | **No.** These tests break because logic reads `dt_util.now()` and the calendar (season, billing month, DST), not because of timer scheduling. A tick changes *when* code runs, not *what time it believes it is*. Injecting a clock (`self._ts()` style, which already exists in `security_lock_regime`) is the fix, and it needs no tick. |

**Net:** of the five claimed benefits, one is real but small (dedup), one is real but a poor fit (missed-edge), and three have no supporting incident.

---

## 4. Risks

1. **Single point of failure.** Today a crash or stuck callback in one loop leaves the other 27 running. With a master tick, a bug in the dispatcher (an exception path, a missed reschedule, a guard that never clears) silences *every* periodic behaviour at once, including safety's 60 s flood check. Containment means per-consumer try/except, a reentrancy guard and a watchdog on the tick itself. As CLAUDE.md puts it, that containment machinery is evidence of risk, not a discount on it.
2. **Slow-consumer stall.** If the wheel awaits consumers in phase order (true "planned synchrony"), one slow consumer, such as a Carrier cloud call in HVAC or a DB-heavy optimizer cycle, delays everything behind it. If the wheel fires them as independent tasks, synchrony is gone and what remains is a renamed `async_track_time_interval`. **"Synchrony" and "isolation" pull against each other. The operator's framing buys the first at the cost of the second.**
3. **Migration blast radius.** Every recurring loop is a caller, so this is Tier 3 by construction (shared primitive, many sites, Bug Class #53 one-missed-site). It touches HVAC (rung-1 cloud-rate-bound tick), energy (TOU boundary alignment, cost-and-safety), safety and security. That adds four regression-prone domains for a refactor with no user-visible feature.
4. **Fights HA idioms.** Room coordinators are `DataUpdateCoordinator`s. HA owns their refresh, debounce, listener fan-out, `async_request_refresh`, and the jitter fix. Driving them from an external tick means either `update_interval=None` plus manual refreshes (losing HA's scheduling and error backoff) or two clocks. `track_time_change` and `async_track_point_in_time` jobs (TOU boundaries, nightly, quiet hours) are wall-aligned by design. Forcing them onto a boot-phased wheel would reintroduce the 0–5 min boundary lag that the TOU boundary tick removed (the anticipatory-tick lesson in CLAUDE.md).
5. **Where event-driven is already right, a tick would be worse:** the HVAC fast path (room refresh listener), presence and BLE transitions, geofence arrival (`security.py` person listener), census-on-camera events, perimeter dispatch, lock state listeners, the energy TOU boundary. Each reacts within seconds of the edge. A tick would add up to one base period of latency and invite "poll and diff" code that misses sub-period flaps.
6. **Quantising one-shot deadlines** (if someone extends the wheel to them later) adds jitter to arrester grace, compromise and nudge timers whose semantics are tuned in seconds (HVAC SoP: suppression TTL 15 s / 120 s). This must be a non-goal.

---

## 5. Marginal-benefit decomposition

**Simplest version: do nothing new.** Today's state already gives event-ordered data flow, a fixed boot herd, wall-aligned boundaries, and a per-consumer cadence picked by each domain's needs. The pain left over is cosmetic: about 10 hand-rolled tracker registrations.

| Option | Benefit captured | Marginal risk ingredients | Verdict |
|---|---|---|---|
| **(0) Status quo + conventions**: (i) inject a clock into new time-dependent logic for test determinism; (ii) keep the room-DUC jitter; (iii) new periodic needs use `async_track_time_interval` with a named knob and a reentrancy guard where the work is async | All of the test-determinism gain (the only well-evidenced problem), at zero runtime risk | None | **Do this** (it is already the house style) |
| **(a) Low-frequency reconcile tick**: one 5–15 min "desired vs actual" sweep with a few named consumers | Missed-edge recovery for consumers that lack one. But the main candidate (locks) **already has a periodic reconcile**: `security.py:768` `_handle_periodic_lock_check`, configurable interval with a 0 kill-switch, routed through the manager intent queue. HVAC already re-asserts every 5 min. Energy already re-decides every 5 min. Excursions already sweep every 60 s. | A new shared primitive (small), cross-coordinator registration, rare-fire paths that are hard to observe | **SIMPLIFY → not needed.** Each candidate already reconciles inside its own owner. A shared tick adds a dependency with no new capability. |
| **(b) Full phase-ordered synchrony for all loops** | Cleaner timing layer, uniform instrumentation, easier new cadences | New writer to every periodic path, cross-coordinator ordering state, SPOF, slow-consumer stall, fights DUC and wall-aligned jobs; Tier 3 across HVAC, energy, safety and security | **PARK** (as decided 2026-09-16; nothing since has changed the margin, and the one motivating need was solved event-driven) |

**Margin of (b) over (0):** about 10 timer registrations consolidated, plus a timing dashboard. **Price:** a Tier-3 four-review cycle touching the two highest-blast-radius coordinators. The margin does not pay.

### "What can be profitably attached": ranked if a wheel ever exists (value ↓, risk ↑)

| Rank | Candidate | Value | Risk | Note |
|---|---|---|---|---|
| 1 | Diagnostic and display refreshers (`sensor.py:4648`, `:5334`, `:8490`, `:17639/17772/17911`, memory baseline `__init__.py:6492`) | Low–med (dedup, one place to tune) | Very low (display only) | Best first tenant: zero trust-decision consumers |
| 2 | Housekeeping sweeps: transitions/transit cleanup, perimeter snapshot (6 h), Frigate ingress, exterior linker, outage ledger, version/URL checks | Low | Low | Pure prune or reconcile, idempotent |
| 3 | Persist cadences: house-state heartbeat 300 s, anomaly baselines 1 h, bayesian save | Low | Low–med | Must avoid co-phasing with DB-heavy work (write-queue bursts); offsets do this |
| 4 | Security periodic lock check (`security.py:768`) | Low (it already works) | Med (security) | Only if the wheel already exists; no reason to move it on its own |
| 5 | 60 s domain loops: safety, presence inference, solar-follow, excursion sweep | Med (the actual "several 60 s loops" pattern) | **Med–high** (safety SPOF; energy is cost-bearing) | Only with per-consumer isolation, and never phase-awaited |
| — | **Never attach:** room DUCs (HA-owned), HVAC / energy / optimizer 5-min decision cycles (rung-1 cloud-rate bound, cost-and-safety), TOU / nightly / quiet-hours wall-aligned jobs, one-shot event deadlines, the loop-stall watchdog (it measures the loop) | | | |

---

## 6. Recommendation

**PARK.** Keep `URA-CENTRAL-TICK-WHEEL-1` parked. Add this eval to its record. **Do not build (a).**

- No incident in the record is caused by unsynchronised timers. The incidents that look timing-related (boot freeze, write flood, restart storm, wall-clock tests) have other causes that a tick does not touch.
- The motivating need from 09-16 (HVAC fast-in) shipped event-driven, which is better than either a sub-loop or a wheel.
- "Planned synchrony" (phase-ordered, awaited) and failure isolation are in direct tension. The version that keeps isolation is just a tidier `async_track_time_interval`.
- **Revival triggers (sharpened from the 09-16 memo):** (1) a measured incident whose root cause is cross-loop phase or ordering, with a DB row or `command_trail` showing a consumer acting on a producer's previous cycle; or (2) a deliberate loop-layer re-architecture pass. If revived, phase it as: P1 = rank 1–2 tenants only (display and housekeeping, Tier 2); P2 = persist cadences with offsets (Tier 2-DB); P3 = 60 s domain loops with per-consumer isolation, never awaited in sequence (Tier 3). Decision cycles, DUCs and wall-aligned jobs stay out permanently.
- **Tier if ever built in full:** Tier 3 (shared primitive, every loop a caller). P1 alone is Tier 2.
- **Do now (zero-risk, already house style):** for the wall-clock test family, inject a clock (`_ts()` pattern, as in `security_lock_regime.py`) into time-dependent logic. That is the actual fix for test determinism, and it needs no tick.

### LOCK-BOOT-RECHECK-ENGAGE-1

It should **not** move to a tick, now or later. It is a one-shot boot-window edge recovery: fire once at setup + `GARAGE_LOCKOUT_BOOT_RECHECK_S` (120 s), evaluate with persisted since-stamps, never engage from replayed edges (`security_lock_regime.py:401-405, 569, 611`). Its semantics are "once, at a defined offset after boot", and `async_call_later` expresses that exactly. A periodic reconcile would fire at an arbitrary phase relative to boot and has no boot-window concept.

The proper steady-state "desired vs actual" safety net for locks already exists: `_handle_periodic_lock_check` (`security.py:768`, default 30 min, knob `CONF_SECURITY_LOCK_CHECK_INTERVAL`). If anything ever needs to absorb lock drift beyond boot, extend that existing loop, not a new house tick. (Config-first: check that knob's live value before carding any lock-drift work.)

---

## Non-goals of this eval
No card created or status changed. No code. One-shot event deadlines, DUC scheduling and wall-aligned jobs were judged out of scope for any tick.
