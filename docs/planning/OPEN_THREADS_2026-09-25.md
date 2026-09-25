# Open Threads — 2026-09-25

**How to use:** each thread has an `> **ANSWER:**` line. Type inline, save, tell me "read the open
threads doc". Leave blank = no decision yet.

---

## 1. COVERAGE-RATING-FALSE-ANOMALOUS-1 — built, reviewed, awaiting deploy

### The problem
`sensor.*_energy_coverage_delta` publishes a `coverage_rating`. Live recorder evidence 2026-09-19:
`delta_percent` was **-635.30 at 22:56** (rated `INCOMPLETE`) and **-643.90 at 00:11** (rated
`ANOMALOUS`). The value barely moved; the **classification flipped** — purely because the
post-restart excuse window closed at local midnight.

Root cause: the in-memory tiers re-anchor **lazily** (`_maybe_reclassify_at_midnight` only *flags*
entries; the re-classify happens on each sensor's next read), so the negative-delta asymmetry
survives the midnight boundary by up to ~an hour. The old docstring asserted it "will converge at
next midnight re-anchor" — measurement falsified that. Secondary defect: the ANOMALOUS warning
asserted a unit-of-measurement mismatch **as fact** when the signature has more than one cause.

### The solution (`c5ea7dfc7` + fix-up `ca69d45c2`)
- New `COVERAGE_MIDNIGHT_REANCHOR_WINDOW_MIN = 120` (rung-1 module constant — sized from 10d of
  recorder history: midnight re-anchor ANOMALOUS runs ended by 01:20 local; the *separate* sustained
  evening-drift pattern never began before 14:00 local, so the window can't swallow it).
- `_get_coverage_rating` gains `midnight_reanchor_window`; the existing negative-delta excuse fires
  for **either** window. `>100` / `None` / `NaN` are still **never** excused.
- `midnight_reanchor_window` published as an attribute so live validation can **discriminate** a
  suppressed boundary artifact from a real mid-day ANOMALOUS.
- Warning text now reports what was observed and *names* candidates instead of diagnosing.
- **Deliberately NOT suppressed:** the sustained evening attribution drift (the majority of ANOMALOUS
  samples, a candidate real defect) keeps its signal. Carded separately as
  `COVERAGE-EVENING-ATTRIBUTION-DRIFT-1`.

### How it passed the gate
| Gate | Result |
|---|---|
| **Hollow-anchor fix** | `test_coverage_rating_bounds.py` loaded `aggregation.py` **without a parent package**, so its relative imports always raised and the **whole file silently skipped in every env** — the D3 bounds tests and the B-H4 post-restart test had **never executed**. Now imported as a package member: 1 skip → 31 passing. |
| **Wire-in anchor** | A mutation drill showed deleting the call-site argument left the helper tests green. That deletion now fails 2 tests. |
| **Review A** (local correctness) | SHIP, no CRIT/HIGH. Invariant held under falsification; discharge structural; consumer count re-grepped. Raised MEDIUM-1 (shared warn-throttle) + LOW-3. |
| **Review B** (test authority) | SHIP. 5 mutation drills; build *understated* its own coverage (4 red, not 2); discriminator proven non-tautological; time **injected**, not wall-clock. Raised a pre-existing HIGH → new card `TEST-SILENT-WHOLE-FILE-SKIPS-1` (10 never-executed tests elsewhere). |
| **Fix-up** | MEDIUM-1: split the shared throttle so a re-anchor warning at 00:05 can't swallow a genuine ANOMALOUS at 00:50. LOW-3: publish `midnight_reanchor_window` on the no-data early-return too. Reviewer-B LOW: added an **absolute 15:00-local** backstop test that does *not* read the constant, so widening it 120→900 can't leave the suite green. |
| **Orchestrator verify** | Diff re-read, **163 pass / 0 skip** (baseline 160), own mutation drill red-then-restored, `git status --porcelain` residue 0. |
| **Out of scope** (declared) | Review-A LOW-1 (DST fall-back lengthens the window) and LOW-2 (`-inf` via the negative branch, unreachable behind `whole_house > 0`). Constant `120` unchanged. |

> **ANSWER — deploy now?** (yes / hold / questions):
>

---

## 2. Camera fleet — CLOSED by operator

Operator 2026-09-25: *"the camera fleet is fine now. Frigate is having periodic degrades on the
hardware side that I am working on. The quick fix is a docker reload."*

→ The 74.7h one-instant fleet freeze is **explained** (Frigate hardware-side degrade, not 16 faults,
not a URA defect). I'll close `CAMERA-SILENT-PRODUCER-TRIPWIRE-1`'s freeze evidence as
attributed-and-owned-by-operator.

Two residuals that are still mine:

**2a. `FRONT-SIDE-PTZ-CHATTER-1`** — blocked on your answer, not on the freeze. The Sep-17 evidence
(which predates the freezes) stands; the re-measurement was only needed to discriminate an
individual camera fault from a fleet event. Given 2 above, a fleet event is now the better
explanation and the card can probably close.

> **ANSWER — close FRONT-SIDE-PTZ-CHATTER-1 as fleet-attributed?** (close / still investigate):
>

**2b. Should URA *detect* a fleet-wide silent producer?** A Frigate degrade currently goes unnoticed
until someone looks. A cheap trip-wire (all exterior detection producers silent > N hours → NM
notification) would tell you to docker-reload without you discovering it days later. Per *No Soak
Watching*, this is exactly the "trip-wire in code" shape. Tier 1-2.

> **ANSWER — build the fleet-silence trip-wire?** (yes / no / later):
>

---

## 3. Envoy — MEASURED. You were right: it is flapping.

### Measurement (read-only, recorder, run 2026-09-25)

`sensor.envoy_482543015950_battery`, all state changes (not significant-only), 2026-09-18 04:13 →
2026-09-20 19:10 local — the recorder returned **1000 state rows in 2.6 days** and the window filled
before exhausting retention.

| Local day | available↔unavailable transitions |
|---|---|
| 2026-09-18 | **220** |
| 2026-09-19 | **324** |
| 2026-09-20 | **223** |

That is roughly **110-160 complete down/up cycles per day** — one every 5-10 minutes, all day,
every day. Typical outage 15s-10min; longest in window ~2h20m (09-19 23:05 → 09-20 01:25).

**This is not a rare hard failure. It is a continuous flap.** My prior handoff framed it as
"frozen / dead-until-restart", which understated it — flapping is the dominant mode, and the freeze
is where a flap fails to recover.

### Current state (2026-09-25)
- Config entry `01KNYRAGVP5XESS6N8PD6BVQP2` is back in **`setup_in_progress`** — the frozen state,
  i.e. the flap failed to recover again. Options carry `disable_keep_alive: true` (prior mitigation).
- `sensor.envoy_482543015950_battery` = `unavailable` since **09:40:57 today**.
- Live core log confirms the mechanism, repeating: `enphase_envoy/coordinator.py:201
  _async_try_refresh_firmware` → `pyenphase/envoy.py:233 setup` → `pyenphase/firmware.py:123 setup`
  → `firmware.py:81 _get_info`. This is the **second** unguarded background task from upstream bug
  **#181243** (the first, `_async_fetch_and_compare_mac`, was what we caught on 09-19).
- URA degrades gracefully — `energy_battery` holds state; no URA defect in the loop.
- Separate benign artifact: `consumption_today` = **28,999 kWh** (99.8% off) → URA's cross-check
  WARN. Already recorder-excluded; URA holds state.

### Mechanism, stated falsifiably
Upstream #181243 (OPEN, affects core 2026.8.3 **and 2026.9.0** = your version; no fix merged):
`_async_try_refresh_firmware` and `_async_fetch_and_compare_mac` run unguarded, so a
`RuntimeError: Session is closed` **escapes** the task. Each escape kills the coordinator's refresh
→ entities go `unavailable` → HA retries → sometimes recovers (a flap), sometimes doesn't (the
freeze). Prediction this makes: flap frequency should track how often those two tasks fire, and the
only true cure is upstream or a local core patch. `disable_keep_alive` reduces the session-close
rate but cannot eliminate it.

### Your question: "I think we said we need to reboot the HA host?"
**I can't confirm that — and I don't want to fabricate it.** What the record shows is an HA **core
restart** on 2026-09-19 (which moved the entry `setup_in_progress` → `setup_retry`, an improvement
that has since regressed). I have **no record of a host-reboot decision.** My read: a host reboot is
unlikely to help, because the failure is a Python exception escaping a task inside the core
container, not an OS/network-stack condition — a core restart reaches it and a host reboot adds
nothing but downtime.

What would *actually* move it, in order of value:

| Option | Effect | Cost / risk |
|---|---|---|
| **A. Local core patch** — wrap the two tasks in try/except in `enphase_envoy/coordinator.py` | Converts flap-to-freeze into flap-and-recover. Targets the real cause. | Patch lives in the container; **lost on every core update** unless re-applied. Needs a re-apply hook. |
| **B. Dual-homed pinning** (your lead — not yet investigated) | If the two interfaces cause local-API contention, pinning to the stable IP could cut the session-close rate. | Read-only investigation first; cheap. **Still un-run — say the word.** |
| **C. Track upstream + bump core when fixed** | The real cure. | Unbounded wait; no fix merged today. |
| **D. Nothing** | URA holds state; no actuation harm observed. | Battery SOC data is missing ~a third of the day; any future consumer of live SOC inherits the gap. |
| **E. Host reboot** | Not indicated by the evidence (see above). | ~5min whole-house downtime for a mechanism it doesn't touch. |

> **ANSWER — which of A / B / C / D / E?** (B is cheap and yours; A is the only one that changes
> today's behavior):
>

---

## 4. Jev decision-classifier spike — blocked on you

Harness ran, but hit **label leakage**: the labels were derived from the classifier's own inputs
(`persons_in_house` / `sensors_on`), so 100% / 88.9% accuracy is meaningless. Verdict INCONCLUSIVE.
Needs an **independent** occupancy truth source before re-running. No URA behavior change either way
— this is pure measurement.

Candidate disjoint source: recorder + operator-confirmed episodes (e.g. Jaya empty 2026-09-18
17:44-19:26).

> **ANSWER — provide labels / approve the recorder+confirmed-episodes source / park the spike?**
>

---

## 5. HVAC conditioning-demand step-4-B — blocked on a policy call

On `feature/hvac-conditioning-demand`. **Daytime path clean. Night-trust path fails review** on
three counts: D9 defeats the backstop at the setpoint layer; the throttle strands; establishment is
permanently-off on a disabled room. Recommendation: **DECOUPLE** — ship the daytime path, hold
night-trust.

Needs your **backstop-breadth policy call** (how broadly the backstop is allowed to override
night-trust).

⚠️ **Do NOT re-run the daytime manual-% remeasure** — it is non-stationary (zone_1 swings
46 / 81 / 50 / 50.3), and the acceptance criterion "zone_1 → ~6%" **fires falsification**. I
over-claimed a PASS on this and retracted it; it stays retracted.

Residual: Bryant native-schedule reclaim, blocked on your Bryant-schedule decision.
(Zone tonnage: 1 = 4-ton, 2 & 3 = 3-ton — you are the oracle here, the doc is wrong.)

> **ANSWER — backstop breadth policy:**
>
> **ANSWER — Bryant native schedule (keep / reclaim):**
>
> **ANSWER — decouple and ship daytime now?** (yes / no):
>

---

## 6. v5.103.14 README write-back — mine to do, no decision needed

`docs/readmes/README_v5.103.14.md` (reload-suppression, Tier 2-DB, shipped) still carries
**prospective** live-validation bullets at §21-26. Per the MANDATORY write-back rule the cycle is not
closed until the observed post-restart results replace them. Two things to verify live:
1. A room **Climate & Fans** save (non-entity change) produces **NO ROOM reload** and no websocket backup.
2. A `CONF_CLIMATE_ENTITY` change **DOES** reload.

Siblings parked: `SUBSTRATE-PER-ROOM-REFRESH-1`, `ZM-CLIMATE-DEFERRED-UPDATE-SUPPRESS-1`.

> **ANSWER — anything to add, or shall I just do it?** (default: I do it):
>

---

## 7. Housekeeping

- `WORKTREE-BACKLOG-PRUNE-1` **reopened**: 52 worktrees / 3.3GB, some **3542 commits behind**,
  **25 dirty** → explicitly *not* a blind delete. Needs a triage pass (dirty ones inspected before
  removal).
- `TEST-SILENT-WHOLE-FILE-SKIPS-1`: 10 tests that have **never executed** (same hollow-anchor class
  as the one fixed above, found by Review B). Worth a sweep — a test file that silently skips is
  worse than no test, because it reads as coverage.
- `MEMORY.md` at 20KB of a 24.4KB read limit; four `project_session_pickup_*` entries where the
  older three are largely superseded. Compaction pass available on request.

> **ANSWER — priority order for these three (or "you pick")?**
>
