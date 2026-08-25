# SESSION HANDOFF — 2026-08-24 (EVSE cycle split, DP ready, test-harness progress)

## Read this first

Two plans are **build-ready and awaiting operator go**. Nothing is mid-build; the tree is clean.

1. **`docs/planning/PLANNING_dp_drain_target_mis_sourcing.md`** — ships FIRST.
2. **`docs/planning/PLANNING_evse_solar_follow_amps.md`** — ships after DP.

Neither has been dispatched to a builder. Both have had plan reviews and the findings are applied.

---

## What shipped / changed this session

* **Test suite: 77 → 61 failing IDs, zero regressions.** Fixed the chatter-detector cluster (15
  tests) — three stacked defects: a module-level `from`-import binding, a rebind that copied the
  wrong function out of `sys.modules`, and `entity_registry.async_get` resolved at CALL time so
  last-writer-wins across the session. Fix is an autouse fixture re-asserting stubs before each
  test. **Standing lesson: import-time stub installation cannot win against a later importer.**
* **`HVAC-ANOMALY-BLIND-1`** — build reviewed DO-NOT-SHIP twice. Branch
  `feature/hvac-anomaly-blind-1` is NOT merged. A short producer plan exists at
  `docs/planning/PLANNING_hvac_short_cycle_producer.md`. **Two open questions for the operator**
  are recorded on the card (see "Awaiting operator" below).
* **`SENSOR-FANINDEP-1`** — probe CONFIRMED then REFINED the class claim. 2 of 5 units latch;
  fix is per-unit, one room (Upstairs Guestroom). Card is `planned`.
* **`EGRESS-IDENTITY-PRODUCER-EMITS-NOTHING-1`** — run 2 of 2 done. **NEITHER prediction fired.**
  Face recognition is DOWN house-wide since ~08-21 and the 08-23 storage fix did not restore it.
  The eight consumer cards stay gated; what they are gated ON changed from "structurally
  incapable" to "broken producer".

---

## The EVSE split — the main event

The solar-follow cycle was **split**. It had reached 1371 lines and 19 revisions, and three
framing-disjoint plan reviews returned 39 then 10 CRITICALs.

* **`EVSE-SOLAR-FOLLOW-AMPS-1`** (`planned`) — amp modulation ONLY. Changes how much current an
  EVSE draws inside a session. Touches no session semantics.
* **`EVSE-SOLAR-STOP-CONDITIONS-1`** (`pre_planning`, NEW) — the start/stop rework. Carries a
  **founding design problem** and six inherited review findings so none is re-derived.

**Why the split:** every design-level critical was in the start/stop half; none in modulation.
The decisive one is an **oscillator** — a per-EVSE stop must fire while fleet conditions are
still good, but the claim leg re-claims anything not in `_excess_solar_active` on the next tick.
Stop at N, re-claim at N+1, forever. The stop card names three candidate resolutions and says
which to hear out first.

**Do NOT re-merge these two cycles.** The split is the finding, not a convenience.

---

## Awaiting operator

| # | Decision | Where |
|---|---|---|
| 1 | Go/no-go to BUILD the DP drain-target fix | card `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` |
| 2 | Go/no-go to BUILD solar-follow amp modulation | card `EVSE-SOLAR-FOLLOW-AMPS-1` |
| 3 | HVAC short-cycle producer: approve the plan? It costs **14 days of baseline maturity** before the metric can fire | `PLANNING_hvac_short_cycle_producer.md` |
| 4 | HVAC baselines **never forget** (unbounded Welford, no `max_samples`) — a metric matured on August cooling may misfire in October. Scope it in, or record as a known limitation? | card `HVAC-ANOMALY-BLIND-1` |

---

## Live faults found but NOT fixed (each needs a card)

1. **`sensor.envoy_482543015950_current_power_production` was stale ~16.5 h** on 08-24 — reading
   0.0 kW while the house exported 6 kW. It is what `CONF_ENERGY_SOLAR_ENTITY` derives to.
   **`energy_envoy_entity` is only a serial-discovery seed** (`__init__.py:3026` →
   `extract_envoy_serial` → `derive_envoy_config`), so config derivation is unaffected. Whether
   any EC decision path reads the derived value is **an open question I did not chase**.
2. **Face recognition down house-wide since ~08-21**, interior cameras included, person detection
   healthy throughout. Separate fault from the 08-20 storage issue.
3. **`very_poor` drain target cannot be live-updated** — `energy.py:8647` validates only
   `{excellent, good, moderate, poor}` while `_drain_targets` carries `very_poor`. Pre-existing;
   the DP cycle makes it load-bearing. Recorded in the DP plan's §5.
4. **`EV Drain-Protection SOC Floor` is live at 80 against a documented default of 50**, and its
   own help text positions it as a "deep floor BEHIND Pause EV Until Battery SOC" — which is also
   80. The two-layer design is collapsed. Recorded in the DP plan, not diagnosed.
5. **No cross-field validation exists for the EC SOC ladder.** `validate_threshold_ladder` takes
   only `reserve_soc`, `drain_targets`, `arbitrage_trigger`, `peak_buffer_target` — it never sees
   resume/pause/drain-floor. Parked item **P1 covers exactly this and its trigger has now fired**;
   promote it from DEFER.

---

## Running probes / background state

* **Carrier blind-episode detector** is running **detached on the HA host**:
  `nohup python3 -u /tmp/carrier_blind_watch.py > /tmp/carrier_blind_watch.out`, 6 h horizon,
  exits on the first confirmed episode. **It must be POLLED** — `cat /tmp/carrier_blind_watch.out`
  — because detaching it means nothing notifies you. Only `/tmp` is writable for the ssh user, so
  it does not survive an HA restart. Committed copy:
  `scripts/probes/carrier_blind_episode_detector.py`. Card `CARRIER-STALE-POLL-REFRESH-1`.
* Probes committed this session: `hobeian_fan_latch_probe.py`,
  `hvac_cycle_duration_probe.py`, `hvac_shortcycle_daily_probe.py`,
  `hvac_shortcycle_distribution_probe.py`, plus the fixed `frigate_health_probe.py`.

---

## Process rules earned this session — these are the expensive ones

* **A plan must contain its own design.** Nineteen revisions replaced spec text with
  "unchanged from Rev-N" pointers until whole deliverables existed only in git history. A pointer
  to a prior revision is a review-blocking defect.
* **Integrate updates into the document's structure; never append.** A decision record explains
  why an alternative was rejected and belongs in the plan. A changelog explains what changed since
  yesterday and belongs in git. Writing the second while calling it the first is how the document
  reached 1371 lines of self-contradiction.
* **Read the consumers before asserting what something does.** Six instances this session of
  inferring function from a NAME or asserting absence from a search that could not have found the
  thing. Written up as `feedback_read_consumers_before_asserting_function.md`.
* **Load the skills.** `ura-config-and-flags` and `ura-energy-strategy-reference` both cover this
  exact work and neither was loaded; the EC config surface was rediscovered TWICE in two days.
  `reference_ec_config_surface.md` now exists as the atlas.
* **A code grep cannot establish that an entity has no writer.** Emporia's native mode was
  modulating `garage_a` at 60 s the whole time; only the entity's state history showed it.

---

## Where things sit

* Branch `develop`, tree clean, everything committed.
* Suite baseline: **61 failing IDs** (was 77). Largest remaining cluster is
  `test_egress_face_identity_d1.py` (10) — same subsystem as the dead face recognition, so the
  two threads may share a root.
* `.venv-ha` real-HA harness: blocker known (`-p no:homeassistant`), switching cost measured
  (273 failing vs 76). Strangler migration, not a flag day. Untouched this session.
* 51 worktrees still uncleaned. `.claude/worktrees/namediff-dev` and `namediff-branch` are from
  this session and are safe to delete.
