# PLANNING — W2 HVAC Occupancy Fast Path (shave the 5-min tick) — REV 3

**Card:** `HVAC-W2-OCCUPANCY-TRUTH` (child: `HVAC-HOT-ENTRY-LATENCY-1`).
**Workstream:** W2 (Occupancy Truth), operator-approved 4-workstream HVAC arc.
**Design origin:** commit `82620357a`; prior context `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` + `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`.
**Operator scope (binding, §9d):** *"shave the 5-min tick only for now."* NO dwell / hold / grace / tail / override / retreat-semantics change; whole-house cycle preserved.
**Sequencing:** BUILD AFTER `feature/hvac-live-room-establishment` (v5.103.15) merges AND AFTER W1-A has been live ≥ 1 day (needed for the empirical write-rate baseline the limiter acceptance depends on — see §8 + §5.D0).

REV 2 folded FIX-PLAN-FIRST review findings 1-12. REV 3 folds the D0 measurement
(`docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md`, probe
`scripts/probes/hvac_fast_path_d0_probe.py`) and its §6.4 planner findings, then applies
the orchestrator's marginal-benefit decision (2026-09-26) to drop the global-limiter
DEFER machinery in favour of DENY + follow-up exemption. Change log at bottom.

---

## REV 3 DELTA (what changed vs REV 2, and why)

Based on the D0 audit (7-day window 2026-09-19 → 2026-09-26, 5 restarts excluded; 33 rooms
in scope; variant S "cycle simulation" as the recommended basis):

1. **ZONE-COLD GATE ADDED (§4.1 gate 3b + §2 INV).** D0 shows **472 trigger-eligible edges
   in 7 d (≈ 68.6/day house-wide)**, but only **114 (≈ 16.6/day, 24 %)** are *zone-cold* —
   i.e. the zone had NO HVAC-armed room at the edge, so the edge is the one that can
   actually change `zone.any_room_hvac_occupied` and therefore the preset outcome. The
   remaining 76 % land in zones already armed by a sibling room and cannot change the
   preset flow on that cycle. Gating the fast path on "zone-cold at event time" is the
   simplest version that captures the preset benefit at a quarter of the fire rate.
   Fan-controller trade-off explicitly acknowledged below (§4.7 fan row); operator scope
   §9d is "shave the 5-min tick for HVAC occupancy response," which is the preset path.

2. **GLOBAL LIMITER: DENY (per REV 2), BUT FOLLOW-UPS EXEMPT FROM BOTH L AND G
   (§4.3 + §4.4).** D0 §6.2 shows a denying `G = 20 s` loses **7 of 114 zone-cold edges
   (6 %) + 5 of 114 follow-ups (4 %)** across the week — cross-zone collisions where a
   sibling zone's cycle started slightly earlier. Orchestrator decision (2026-09-26,
   marginal-benefit decomposition per CLAUDE.md): DROP the DEFER machinery that an
   earlier REV 3 draft proposed. Reason: its entire benefit is the ~7 zone-cold
   edges/week (~1/day) that collide cross-zone within G=20 s (~1 event/day gets today's
   5-min-tick latency), while it would add a new `async_call_later` timer + per-zone
   pending dict + teardown / restart discharge surface — the state-machine × time
   ingredient behind our worst bug families. Simpler version adopted:
   - Global limiter **DENIES** on collision (as in REV 2). Denied zone-cold edges
     discharge on the next periodic 5-min tick (backstop; expected volume ~1/day per
     D0 §6.2). Denials are counters (`fast_path_global_rate_limited_total`); NO
     per-denial NM (finding 9).
   - **Dwell-expiry follow-ups (§4.4) are exempt from BOTH the per-zone AND the global
     limiter.** Per-zone dedup already bounds follow-up volume to one per zone per
     dwell window, and losing a dwell follow-up loses the hot-entry latency benefit
     (D0 §6.2: 5/114 follow-up losses at G=20 DENY). Exempting them here (no new
     state) is the recovery for that leak.
   - The parked DEFER alternative is recorded in §7 with an explicit revival trigger
     (revive if measured zone-cold G-denials > ~3/day or a denied cold edge coincides
     with a comfort complaint).

3. **CONSTANTS SIZED FROM D0 (rung 1, module constants — see §10 ladder):**
   - `HVAC_FAST_PATH_MIN_INTERVAL_S = 60` — re-based on ZONE-COLD edges: **0/114
     denied at any L ≤ 300 s** (D0 §6.1). All-edge denial at L=60 is 15–21 %, but every
     denied edge is decision-neutral for presets (warm zone, already armed). 60 s keeps
     one fast-path cycle per zone per burst; is a meaningful cloud-rate protector; and
     comfortably ≥ HA event-loop lateness of the 5-min tick (D0 fitted 300.3–301.1 s).
   - `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S = 20` — D0 §6.2: at G=0 the house never exceeds
     2 non-periodic cycles in 20 s; G=20 enforces the ≤ 4,320/day theoretical ceiling.
     Under DENY (this REV 3) the cross-zone-collision cost is ~1 zone-cold edge/day
     falling back to the next periodic tick — accepted per §REV 3 DELTA #2.
   - `HVAC_FAST_PATH_SLA_S = 45` — D0 §6.3: cycle-END proxy p95 = **27.6 s** (proxy
     method: cycle-END recorder rows on `sensor.ura_hvac_coordinator_zone_N_status`
     minus inferred tick START; the phase is the lower envelope of the densest 15-s
     cluster per 6-h chunk, so absolute cycle duration is unmeasured and ≥ the proxy —
     D0 §5, §8). 45 s = 27.6 s + ~17 s headroom for proxy error + one chained trailing
     rerun. Note explicitly in the constant's comment that the SLA is trigger→cycle-START
     and that absolute cycle DURATION was not measured directly.
   - `FAST_PATH_DWELL_SLACK_S = 2` — unchanged from REV 2. Sizing rationale unchanged:
     wall-clock slack past `current_session_start + zone_entry_dwell`; not tightened
     because the live `hvac_zone_entry_dwell` is 2 (state of play §3.2), so a 2 s slack
     is 1.7 % of dwell — plenty of protection against wall-clock coupling at the edge
     without significantly moving the total follow-up delay.

4. **D3 ACCEPTANCE (write-rate) — PENDING (§5 D3 note, §7 audit §7).** W1-A shipped
   v5.103.16 at 2026-09-26 ~15:25 CDT; at probe time only 3 `climate_write` rows existed
   (all inside the empty-house window). The per-zone `climate_write` rows/day baseline
   is measurable after ≥ 1 clean day (**earliest 2026-09-27 ~15:25 CDT**). Query in
   audit §7. The build may be dispatched after part 2 of the audit (§7) fills the
   baseline table; the ship gate (D3 Live) still requires the pre-W2-1 baseline for the
   ±margin acceptance.

5. **EXPECTED ADDED CYCLES/DAY (recomputed for DENY + follow-up exemption).** With the
   zone-cold gate (change 1) + DENY global limiter + follow-up exemption (change 2):
   - **Base fast-path cycles ≈ 16.6/day** minus **~1/day zone-cold edges G-denied**
     (D0 §6.2 at G=20) ≈ **15.6/day fires**. Rounded to hourly, <1/hour on average
     — a rounding error against the 288/day periodic ticks (+5.4 %).
   - **Dwell follow-ups scheduled ≈ 16.6/day** (one per zone-cold edge that hits the
     dwell skip — which is all of them per C18 mechanism; note follow-ups are scheduled
     for periodic-tick dwell skips too, so the true number is ≥ 16.6/day). Exempt from
     both L and G, so all scheduled follow-ups run.
   - **Trailing reruns from lock re-entrancy ≈ 0.7/day** (edges landing during a
     periodic cycle: p95 cycle-end proxy 27.6 s × 16.6 edges/day / 300 s tick period).
   - **Total ≈ 33/day** on top of 288 periodic ticks, +11 %. Well inside the C5 cloud
     call-rate contract (writes, not cycles, are the Carrier budget — and this cycle
     adds no new preset/setpoint writes; §7 non-goal).
   - Compare REV 2's implicit budget (all trigger-eligible edges gated only by
     per-zone L=60): 79.0/day non-periodic cycles at L=60/G=0, +24 % (D0 §6.2 table
     row 1). REV 3 more than halves that at the cost of ~1 zone-cold edge/day
     falling back to today's 5-min-tick latency (parked DEFER alternative could
     recover this if measurement shows it matters).

6. **FALSIFIABLE INVARIANT UPDATED (§2).** INV conjunct (1) narrows the domain to
   *zone-cold* rising edges AND states the DENY-with-tick-backstop discharge explicitly;
   conjunct (6) hot-entry latency target unchanged. The old "for every rising edge"
   wording would have been trivially falsifiable by any denied warm edge — a false
   positive.

**FAN / OTHER-CONSUMER VERDICT (mandated verification, cited).** Read the full call
list at `hvac.py:1656-1789` and REV 2 §4.7. Under the zone-cold gate, warm-zone
rising edges no longer fire the fast path. Consumers of `_run_decision_cycle` and
whether any BENEFIT from a warm-zone (already-armed) event-driven fire:
- `update_room_conditions` (`hvac.py:1656`, `hvac_zones.py:523`): fused
  `any_room_hvac_occupied` is already True in a warm zone; producer output unchanged
  by re-firing early. **No benefit.**
- Row-1 preset flip / row-10 arrester comfort-delay / D5 / D6 / D7 / D9 / F4 preset &
  retreat logic (`hvac.py:2013`, `:2063`, `:2271`, `:2403`, `:2966`;
  `hvac_override.py:2319`): preset payload only fires on transitions of the fused
  signal; a warm zone can't transition on a warm-edge fire. **No benefit.**
- `_egress_manager.async_tick` (`hvac.py:1696`), `_check_carrier_freshness`
  (`hvac.py:1670`), `_cover_controller.update` (`hvac.py:1767`),
  `_predictor.update` (`hvac.py:1784`): all time-based; would run either way on the
  next 300-s tick. **No meaningful benefit** at sub-tick cadence.
- `_override_arrester.check_ac_reset` (`hvac.py:1760` → `hvac_override.py:3805-3815`):
  count-coupled; SKIPPED on non-periodic per REV 2 §4.7 regardless. **No benefit** (it
  wouldn't run on the fast path anyway).
- `_fan_controller.update(constraint, house_state)` (`hvac.py:1764` → `hvac_fans.py:495`,
  reads `room_cond.occupied` at `hvac_fans.py:761`, `:997`, `:1207`, `:1255-1260`,
  `:1334`): **REAL benefit and the only one.** Fast-in on a warm-zone edge would
  accelerate per-room comfort/night-window fan activation for that specific room.
  Today under REV 2 (all-edge gate + fans-RUN row), this benefit was implicitly
  included. Under REV 3 (zone-cold gate), a warm-zone rising edge's fan update
  falls back to the next periodic tick — median wait 142–181 s per D0 §3.1.

**Decision (orchestrator + operator scope):** ADOPT the zone-cold gate. Rationale per
operator scope §9d ("shave the 5-min tick only for HVAC occupancy response" — the
preset path) + marginal-benefit decomposition (CLAUDE.md): the simplest version
captures 100 % of the preset benefit at 24 % of the fires; the marginal benefit of
warm-edge firing is ONE consumer (per-room fan-in), whose latency under the
zone-cold gate is unchanged from today (falls back to the 5-min tick, wait-median
142–181 s). If measurement shows the fan latency on warm-zone entries actually
matters, the follow-up card `HVAC-FAST-PATH-FAN-WARM-EDGES-1` (minted by the
orchestrator on the board 2026-09-26) is the escape hatch — it would fire
`_fan_controller.update` alone on warm edges, not a whole-house cycle.

**Contradictions with other sections (all fixed in-line below):**
- §4.1 gate 3 (already-armed room) subsumes zone-cold on the specific room, but
  NOT on siblings — a fresh edge in an unarmed room of a warm zone still passed
  REV 2's gate 3 while being warm-zone. New gate 3b adds the sibling check. Every
  §2 / §4 / §5 reference to "trigger-eligible edges" now means zone-cold-eligible.
- §3 sizing rule and fail-out — rewritten in place to use the zone-cold denominator
  (per D0 §6.4 finding 1).
- §4.3 rate limiter — REV 2 DENY semantic retained; per-zone `_fast_path_pending_defer`
  state field NOT added; discharge map documented per "suppression needs a discharge"
  (backstop = periodic tick for both denial paths).
- §4.4 dwell follow-ups — exempt from BOTH per-zone AND global limiter (was only
  per-zone in REV 2).
- §4.7 fan row — disposition annotated with the warm-edge trade-off; behaviour
  under zone-cold gate is that fans still get their fast-in on cold edges (which
  is where entry-fan matters most, since cold zones are unoccupied), and warm
  edges fall back to the tick (today's behaviour).
- §6 open Q1 — CLOSED. The zone-cold gate collapses volume enough that per-zone
  vs whole-house is no longer a live tension. (Whole-house preserved; count-coupled
  skip still gates the sibling side effects on non-periodic.)
- §7 non-goals — add "no warm-zone triggers"; PARK the DEFER alternative with an
  explicit revival trigger; keep reference to `HVAC-FAST-PATH-FAN-WARM-EDGES-1`.

---

## 0. MANDATORY READ CONFIRMATION

Planner re-read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely (W1-A
Stage A SHIPPED v5.103.16 2026-09-26, §10 C1–C22 including the C18 hot-entry mechanism
and the C20 zone_1 borrow-return strand class) AND `docs/planning/PLANNING_hvac_arc_w1_w2_integration.md`
(C1–C7 contracts; C6 binding — trigger source is the room coordinator's own
`binary_sensor.{entry_id}_occupied`, registry-resolved, NOT the recomputed HVAC-occupancy
sensor). The integration doc `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §9
(Carrier post-write guard × URA suppression interaction) is UNVERIFIED per C16 and out of
scope for this plan.

**C18 reframes this whole design.** The dwell-expiry follow-up is NOT a corner case; it is
the main hot-entry path (§4.4, §5.D3).

---

## 1. Institutional context verified

### 1.1 Prior-art scan — REUSE-or-BUILD per proposed piece

| Proposed piece | Verdict | Existing symbol (file:line) |
|---|---|---|
| Decision-cycle trigger dispatch | **REUSE pattern** | `hass.async_create_task(self._async_decision_cycle())` tracked in `_pending_tasks` — house-state at `hvac.py:3131-3133`, pre-arrival at `hvac.py:4002-4004`, boot-settle kickoff at `hvac.py:1539-1547` via `async_call_later` unsub'd on `_unsub_listeners`. Re-entrancy guard `self._decision_cycle_lock` at `hvac.py:1592-1598` (finding 5: drops triggers today — §4.5). |
| Per-room rising-edge source | **REUSE entity** | `binary_sensor.{entry_id}_occupied` — registry-resolved via `homeassistant.helpers.entity_registry.async_get_entity_id("binary_sensor", DOMAIN, f"{entry_id}_occupied")`. NOT the `hvac_occupied` sensor (that's a lazy mirror that only updates when the room coordinator pushes — same producer, same lag). |
| Armed-gate replay in the D0 probe | **REUSE producer state** | `zm._hvac_armed[room]` (`hvac_zones.py:241`, `:990`, `:994`, `:1026`, `:1038`); tail-hold tables at `const.py:1219-1224` (day) and `:1230-1242` (night). D0 replays these offline (finding 3). |
| Trigger dedup / re-entrancy trailing rerun | **NEW (one flag)** | `self._fast_path_rerun_requested: bool` — flip on trigger when lock held, drop-and-rerun after lock releases. Prior art is `_pending_tasks` set (lifecycle only, not coalesce). |
| Per-zone rate limiter | **NEW module const + dict** | `HVAC_FAST_PATH_MIN_INTERVAL_S` in `hvac_const.py` (rung-1, cloud-call-rate protective, sibling to `HVAC_DECISION_TICK` at `:11-13`). State `self._fast_path_last_run_at: dict[str, datetime]`. Stamped ONLY when a cycle actually runs (finding 5). |
| Global min-interval between non-periodic cycles | **NEW module const** | `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` (finding 8) — house-wide floor between any two non-periodic cycles regardless of zone. **REV 3: DENY on collision (per REV 2); dwell follow-ups exempt (§4.4). The DEFER alternative is parked in §7.** |
| Dwell-expiry follow-up | **REUSE pattern (main path per C18)** | `async_call_later` + per-zone dedup dict `self._fast_path_pending_dwell: dict[str, unsub]`; unsubs cancelled in `async_teardown` from the per-zone dict — NOT appended to `_unsub_listeners` (finding 7, avoid double-unsub `helpers/event.py:441-447`). |
| `trigger` classification through the cycle | **NEW arg + REUSED skip-guards** | Thread `trigger: Literal["periodic","boot_settle_kick","house_state","pre_arrival","fast_path","fast_path_dwell_followup"]` through `_async_decision_cycle(_now=None, *, trigger="periodic")` → `_run_decision_cycle(trigger)`. On non-periodic, SKIP the count-coupled call sites (§4.7). |
| Trigger classification recorded | **REUSE surfaces** | Put `trigger` into (a) the existing `preset_change` `ura_activity_log` details dict (`hvac.py:2716-2748`), (b) an existing HVAC coordinator sensor's attributes (in-memory counters). NO new sensor and NO new per-cycle DB writer (finding 2 — `sensor.ura_hvac_coordinator_decision_cycle` does NOT exist; retracted). |
| Storm trip-wire | **REUSE** | `AnomalyDetector` at `hvac.py:1485-1501` — add a `fast_path_trigger_rate` metric (per-zone, LOCAL-day bucket like `short_cycle_rate`). NM fires only on the trip-wire (finding 9), no per-denial NM. |
| Listener rebuild on room lifecycle | **REUSE pattern** | `SIGNAL_ROOM_ENTRY_LIFECYCLE` (`signals.py:199`); presence pattern at `presence.py:2624-2651`; store the state-change unsub on a dedicated attribute (`self._fast_path_state_unsub`), release-then-reassign — single unsub, no `_unsub_listeners` append (finding 7). Also rebuild on `options_updated`. |
| Latency oracle | **REUSE** | `ura_activity_log` `preset_change` row time (`hvac.py:2716-2748`); OR when W1-A ships, the durable per-write row from W1-A. NOT recorder `preset_mode` (Carrier status-lagged per §5 and C16). Finding 10. |

### 1.2 Prior planning docs consulted

- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md`
- `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`
- `docs/planning/PLANNING_hvac_live_room_establishment.md` REV 2 (v5.103.15 in flight — §9 overlap)
- `docs/planning/PLANNING_hvac_governed_excursion.md` rev-6 (trigger routes through `_async_decision_cycle`, not `_run_decision_cycle`)
- `docs/planning/PLANNING_hvac_arc_w1_w2_integration.md` (C1–C7 contracts binding this cycle)
- `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md` (D0 probe — REV 3 input)
- W1-A plan (naming per §11 arc) — sequenced BEFORE this cycle for the write-rate baseline

### 1.3 Memory + design docs read

- `feedback_wire_in_anchor_mandatory.md`, `feedback_suppression_needs_discharge.md`, `feedback_measure_before_build.md`, `feedback_marginal_benefit_pushback.md`, `feedback_tier2plus_prior_art_scan.md`, `feedback_mutation_verification_pycache_staleness.md`, `feedback_falsify_before_asserting.md`, `project_reload_storm_refuted_restart_storm_live.md`, `project_incident_v5_8_0_setup_recursion.md`.
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (C16-C22 folded — see §0). W1-A Stage A SHIPPED v5.103.16.

### 1.4 Code locations surveyed

- `hvac.py`: subscribe block :1131-1213; periodic timer :1355-1363; boot-settle :1510-1552; `_async_decision_cycle` :1564-1598 (re-entrancy guard :1592, boot-settle early-return :1580); `_run_decision_cycle` :1600-1789 (fan controller at :1764, cover at :1767, predictor at :1784); `_check_carrier_freshness` :1670; anomaly observations :1783; zone dwell :2355-2368; preset_change activity-log :2716-2748; `_handle_house_state_changed` :3096-3133; `_handle_person_arriving` :3990-4004.
- `hvac_fans.py`: `FanController.update` :495, reads `room_cond.occupied` at :761 (SAME source as the fast-path trigger — the only warm-edge consumer that would benefit).
- `hvac_override.py`: `check_ac_reset` count-coupling `:3805-3815` (`kwh_samples_above_threshold += 1` vs `_sustained_samples`); suppression windows `:129`, `:141-146`, `:153` (C17).
- `hvac_zones.py`: `update_room_conditions` :523; `_hvac_armed` :241/990; hallway exclusion :650-665; **`current_session_start = now` at :714-716 (C18 mechanism)**; hallway-excluded seen :988; `is_zone_hvac_established` :1043.
- `hvac_const.py`: `HVAC_DECISION_TICK` :11-13.
- `const.py`: `ROOM_TYPE_HVAC_HOLD` :1219-1224 (day), `ROOM_TYPE_HVAC_HOLD_NIGHT` :1230-1242 (night).
- `binary_sensor.py`: `HVACOccupiedBinarySensor` :745; slug + zone-lookup pattern :906-919.
- `signals.py`: full read — only `SIGNAL_ROOM_ENTRY_LIFECYCLE` :199 is relevant.

---

## 2. Falsifiable invariant (REV 3 — zone-cold predicate; DENY discharge documented)

**INV:** *"For every HVAC-occupancy rising edge on a live, non-hallway room R (ROOM entry
LOADED, coordinator present, `zm._hvac_armed[R]` NOT already True at event time) belonging
to an HVAC zone Z **for which no sibling room R' of Z has `zm._hvac_armed[R']` True at
event time (i.e. Z is zone-cold)**:*
1. *`_run_decision_cycle` STARTS within `HVAC_FAST_PATH_SLA_S` of the source `state_changed` event, UNLESS denied by the per-zone limiter (D0: 0/114 zone-cold denials in 7 d) OR the global limiter (D0: ~7 zone-cold denials in 7 d — expected volume ~1/day). A DENIED zone-cold edge is discharged by the NEXT periodic 5-min tick (backstop); no zone-cold edge is dropped without a discharge path;*
2. *When R's zone Z would be preset-flipped by that cycle but is dwell-blocked by `hvac.py:2362-2365`, a follow-up cycle is scheduled at `zone.current_session_start + zone_entry_dwell + FAST_PATH_DWELL_SLACK_S` (per-zone dedup), and the follow-up cycle is EXEMPT from BOTH the per-zone AND the global limiter (per-zone dedup already bounds it; no separate defer state is added);*
3. *On a non-periodic cycle (`trigger != "periodic"`), the count-coupled side effects enumerated in §4.7 are SKIPPED (or proven time-based). The periodic-tick behavioural output for every other zone is byte-identical to `develop`;*
4. *Every fast-path subscription and per-zone dwell timer is cancelled inside `async_teardown` (no orphan callbacks, no writes after unload); the state-change unsub is single-owned on `self._fast_path_state_unsub` (no double-unsub);*
5. *`_fast_path_last_run_at[Z]` and `_fast_path_last_run_at_any_zone` are stamped ONLY when a cycle actually runs — not on rate-limited denials, not on boot-settle early returns, not on re-entrancy skips (which set `_fast_path_rerun_requested` and produce one trailing rerun after lock release)."*

**Scope of INV (REV 3 explicit):** a warm-zone rising edge (Z already has `_hvac_armed[R']`
True for some R' ≠ R) is OUT OF SCOPE for this cycle. Warm-zone edges continue to be
handled by the periodic 5-min tick, exactly as they are today. This is a marginal-benefit
decision: warm edges cannot change the preset outcome (§REV 3 DELTA #1 + fan-verdict).

Discriminating observations (finding 10, updated): under the fix, the **share of zone-cold
hot entries** — zone away, `any_room_hvac_occupied` False, no active session — whose *first*
`ura_activity_log preset_change` row lands within **250 s** of the source
`binary_sensor.{entry_id}_occupied` rising edge rises from ≈0 (today, C18 mechanism
guarantees it can't) to ≈all EXCEPT the ~1/day cross-zone-G-denied edges (which land at
the next periodic tick, up to 300 s + dwell). Any zone-cold hot entry with edge→write
> 300 s post-fix AND no global-limiter denial logged in the same window is a defect.

The "changes WHEN, not WHAT" claim and the "sibling zones quiescent" claim from rev 1 are
**STRUCK** — the count-coupled side effects (§4.7) make untriggered whole-house cycles NOT
behaviour-neutral in general; the fix is the `trigger`-gated skip.

---

## 3. D0 — Measure before you build (READ-ONLY) — DONE 2026-09-26

**Result:** `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md`. Probe:
`scripts/probes/hvac_fast_path_d0_probe.py`. Window 2026-09-19 20:45Z → 2026-09-26 20:45Z,
165.2 h MAIN with 5 restarts excluded, 33 rooms in scope (7 hallways + 3 outside-HVAC
skipped), variant S (cycle-simulation) as the recommended basis.

**Headline numbers folded into REV 3 (§REV 3 DELTA #1 + #3):**
- 472 trigger-eligible edges over 165.2 h (68.6/day house-wide).
- 114 zone-cold edges (16.6/day, 24 % of eligible) — THE population for sizing.
- 5-min sliding burst p95 = 3 (max 4–6) at the all-eligible level; **zone-cold burst
  p95 = max = 1 in every zone** — no bursts among the edges that matter.
- Inter-edge gap: eligible p50 551–1181 s, p5 6–13 s; zone-cold min gap **646 s in
  every zone** (i.e. per-zone limiter at any L ≤ 300 s denies 0 zone-cold edges).
- Cross-zone-collision denials at G=20 DENY: 7/114 zone-cold edges (~1/day) — accepted
  cost (discharged by next periodic tick, §REV 3 DELTA #2).
- Cycle-END proxy: p50 13 s, p90 23 s, p95 27.6 s, p99 54.8 s (bulk 0–30 s; 30–60 s
  tail is background). Proxy method + absolute-duration caveat in D0 §5 + §8; SLA
  headroom in §REV 3 DELTA #3.
- Periodic tick coverage of eligible edges: ≤60 s 19–23 %, ≤120 s 35–42 %, ≤300 s
  ~100 % (uniform-phase expectation — no correlation between tick and occupancy).

**Sizing rule (REV 3):** `HVAC_FAST_PATH_MIN_INTERVAL_S` chosen so it denies **0 % of
zone-cold trigger-eligible edges per zone**. D0 §6.1: 0/114 at any L ≤ 300 s. Adopted:
**60 s**. `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S = 20` sized to ceiling non-periodic
cycles at ≤ 1 per 20 s house-wide; the ~1/day zone-cold edges that G-deny fall back to
the next periodic tick per DENY semantic.

**Fail-out:** the REV 2 fail-out condition ("deny > 10 % AND tick covers > 90 %") DID
NOT FIRE on the zone-cold denominator (0 % per-zone denied; ~6 % global-denied; tick
coverage < 42 % at any X < 300 s). Fast-path build proceeds.

---

## 4. Design

### 4.1 Trigger source

`async_track_state_change_event` on the filtered set of `binary_sensor.{entry_id}_occupied`
entity_ids (registry-resolved, finding 6). Filter set built at setup from all
**non-disabled** ROOM entries; hallway flag and zone-membership are re-checked at EVENT
TIME (source of truth may change between rebuilds).

**Rising-edge classification (finding 6):** old-state `"off"` → new-state `"on"` ONLY.
`unknown` / `unavailable` / `None` on either side is NOT a rising edge — those are
lifecycle noise. D0 measured only **1 non-off→on transition in 7 d** (§audit §1) —
noise is negligible.

**Per-event gating (all short-circuit, in this order):**
1. Room is a member of some HVAC `zone.rooms` — else skip.
2. Room's `CONF_ROOM_TYPE != ROOM_TYPE_HALLWAY` — else skip (circulation-excluded rooms cannot be HVAC-occupied per `hvac_zones.py:650-665`).
3. `zm._hvac_armed.get(room_name) is not True` — if already armed, the D1 producer's state won't change on this edge.
3b. **REV 3: Zone-cold gate.** For zone Z of room R, `any(zm._hvac_armed.get(sibling, False) for sibling in Z.rooms if sibling != R) is False` — else skip. Only edges that can flip `zone.any_room_hvac_occupied` (and therefore the preset outcome) fire the fast path. See §REV 3 DELTA #1 for the trade-off and fan-consumer verdict.
4. Not inside boot-settle (`_boot_settle_done`) — if suppressed, count in `_fast_path_boot_suppressed_count`; do NOT stamp `_fast_path_last_run_at[Z]` (finding 5).
5. Per-zone limiter: `now - _fast_path_last_run_at.get(Z, min) >= HVAC_FAST_PATH_MIN_INTERVAL_S` — else DENY (counter `fast_path_rate_limited_total`, `debug` log; NO per-denial NM per finding 9). D0: 0/114 zone-cold hits this branch — kept as a cloud-rate cap.
6. **Global limiter (REV 3: DENY).** `now - _fast_path_last_run_at_any_zone >= HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` — else DENY (counter `fast_path_global_rate_limited_total`; NO NM). A denied zone-cold edge falls back to the NEXT periodic 5-min tick (backstop discharge; expected ~1/day per D0 §6.2). The DEFER alternative (recover the ~1/day by scheduling an `async_call_later` per denied edge) is PARKED in §7 with a revival trigger.
7. Re-entrancy: if `_decision_cycle_lock.locked()`, set `_fast_path_rerun_requested = True` (finding 5) and return — after the current cycle releases the lock, run ONE trailing cycle (see §4.5).

If all pass, dispatch via `hass.async_create_task(self._async_decision_cycle(trigger="fast_path"))`, tracked in `_pending_tasks`.

### 4.2 Rising-edge only (unchanged)

Argument in rev 1 stands: retreat gate needs fused-empty AND ≥ 10-min vacancy grace; a
≤ 5-min falling-edge lag is invisible. Falling edges continue to ride the tick.

### 4.3 Rate limiter — per-zone + global (REV 3: DENY, follow-ups exempt)

**Constants (`hvac_const.py`, rung 1; sibling comment to `HVAC_DECISION_TICK`, "cloud API call-rate protective bound — change requires review"):**
- `HVAC_FAST_PATH_MIN_INTERVAL_S = 60` — per-zone floor. D0 §6.1: 0/114 zone-cold edges denied at any L ≤ 300 s (min in-zone cold-gap 646 s). 60 s is a meaningful cloud-rate protector >> HA event-loop lateness of the 5-min tick.
- `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S = 20` — house-wide floor between any two non-periodic cycles. D0 §6.2: at G=0 the house never exceeds 2 non-periodic cycles in any 20 s window; G=20 enforces a ≤ 4,320/day theoretical ceiling. DENY semantic (§4.1 gate 6); ~1 zone-cold edge/day falls back to the next periodic tick.
- `HVAC_FAST_PATH_SLA_S = 45` — target trigger→cycle-START latency. D0 §6.3 arithmetic: cycle-END proxy p95 27.6 s + ~17 s headroom for proxy error and one trailing rerun. Constant's comment MUST state: (a) SLA is trigger→cycle-START, not completion; (b) absolute cycle DURATION is unmeasured (proxy method in D0 §5), so absolute cycle length is ≥ 27.6 s p95 by that lower-envelope construction.
- `FAST_PATH_DWELL_SLACK_S = 2` — slack past `zone.current_session_start + zone_entry_dwell`.

**State (on `HVACCoordinator`):**
- `self._fast_path_last_run_at: dict[str, datetime]` — per zone_id, stamped ONLY when a cycle actually runs (finding 5).
- `self._fast_path_last_run_at_any_zone: datetime | None` — global counterpart, same stamping rule.
- `self._fast_path_rerun_requested: bool` — trailing-rerun flag (finding 5).
- `self._fast_path_pending_dwell: dict[str, CALLBACK_TYPE]` — per-zone `async_call_later` unsubs for dwell follow-ups; cancelled from this dict in `async_teardown`, NOT via `_unsub_listeners` (finding 7 — helpers/event.py:441-447 raises on double-unsub).
- **No `_fast_path_pending_defer` field** — the DEFER alternative was considered and PARKED (§7). DENY discharges via the periodic tick backstop.
- Counters exposed as attributes on an existing HVAC sensor (finding 2): `fast_path_triggers_total`, `fast_path_rate_limited_total` (per-zone L denials), `fast_path_global_rate_limited_total` (global G denials, REV 3), `fast_path_skipped_reentrant_total`, `fast_path_boot_suppressed_total`, `fast_path_dwell_followups_scheduled_total`, `fast_path_dwell_followups_ran_total`, `fast_path_dwell_followups_coalesced_total`, `fast_path_warm_zone_gated_total` (REV 3 — number of edges dropped by gate 3b, sanity metric that our marginal-benefit decomposition is empirically correct). Reset on daily rollover using the existing `_last_daily_reset` hinge at `hvac.py:1606`.

**Restart survival:** no persistence. The pending-dwell dict clears on restart
(in-memory); the next periodic tick and any real edge re-establish stamps. **Discharge
map (per "suppression needs a discharge"):**
- Per-zone `L` denial (gate 5): discharged by the periodic 5-min tick (backstop). D0
  shows 0 zone-cold edges hit it.
- Global `G` denial (gate 6, REV 3 DENY): discharged by the periodic 5-min tick
  (backstop). D0 §6.2: ~7/week zone-cold edges at G=20 (~1/day) get today's
  5-min-tick latency — accepted per §REV 3 DELTA #2. Trip-wire if the counter
  exceeds ~3/day is the revival trigger for the parked DEFER alternative (§7).
- Re-entrancy skip (gate 7): discharged by the trailing rerun in §4.5.
- Boot-settle early-return (gate 4): discharged by the boot-settle 1 s kickoff at
  `hvac.py:1539-1547` and by the next periodic tick.

**Boot-settle:** on `_async_decision_cycle` early-return at `hvac.py:1580` (boot-settle
suppressed), the fast-path code path MUST NOT stamp `_fast_path_last_run_at[Z]`
(finding 5). Achieved by classifying the return path via `trigger` — see §4.5.

### 4.4 Dwell-expiry follow-up — the MAIN hot-entry path (REV 3: exempt from BOTH L and G)

Per C18, EVERY observing tick that first sees `any_room_occupied` starts
`current_session_start = now` (`hvac_zones.py:714-716`) and then hits the dwell skip
(`hvac.py:2362-2365`). Without a follow-up, both periodic and fast-path cycles do
zero preset work; the preset lands on the NEXT tick, up to 5 min later.

**Rule (rewritten, finding 4 + REV 3):** whenever `_run_decision_cycle` takes the
dwell-skip branch at `hvac.py:2362-2365` for zone Z, IF no follow-up is pending for Z,
register `async_call_later(hass, remaining_s + FAST_PATH_DWELL_SLACK_S,
_fast_path_dwell_followup(Z))`. Store the unsub in `self._fast_path_pending_dwell[Z]`.
**Schedule regardless of `trigger`** — this shaves periodic ticks that hit dwell too.

**Follow-up cycle is EXEMPT from BOTH the per-zone AND the global limiter (REV 3)** —
per-zone dedup already bounds volume to at most one follow-up per zone per dwell window
(D0 §6.2 shows 5/114 follow-up losses across 7 d at G=20 DENY without exemption; the
exemption recovers them at zero new state). Still subject to boot-settle / lock
re-entrancy (which produces the `_fast_path_rerun_requested` trailing behaviour, §4.5).

**Dedup + coalesce:** if a second dwell-skip lands for Z while a follow-up is pending, do
nothing; counter `fast_path_dwell_followups_coalesced_total` increments.

**Teardown-safe:** follow-up unsubs are stored in `_fast_path_pending_dwell` and cancelled
from that dict in `async_teardown`. NOT appended to `_unsub_listeners` (finding 7).

### 4.5 Re-entrancy — trailing rerun (finding 5)

Today's guard at `hvac.py:1592-1596` DROPS the trigger. Rev-2 rule:

```
async def _async_decision_cycle(self, _now=None, *, trigger="periodic"):
    if not self._enabled: return
    if not self._boot_settle_done:
        # count-only; do NOT stamp _fast_path_last_run_at
        self._boot_settle_hvac_suppressed += 1
        if trigger != "periodic":
            self._fast_path_boot_suppressed_count += 1
        return
    if self._decision_cycle_lock.locked():
        if trigger != "periodic":
            self._fast_path_rerun_requested = True
            self._fast_path_skipped_reentrant_total += 1
        return
    async with self._decision_cycle_lock:
        await self._run_decision_cycle(trigger=trigger)
        # Trailing rerun — one only, exempt from per-zone limiter,
        # honours global limiter + boot-settle + lock re-entrancy.
        if self._fast_path_rerun_requested:
            self._fast_path_rerun_requested = False
            # Note: recursion is safe — lock is released on exit of `async with`.
            self.hass.async_create_task(
                self._async_decision_cycle(trigger="fast_path")
            )
```

Stamping rule: `_run_decision_cycle` stamps `_fast_path_last_run_at[Z]` for the trigger's
originating zone AND `_fast_path_last_run_at_any_zone` ONLY on entry, ONLY when
`trigger != "periodic"`. Every early-return path above leaves the stamps untouched.

### 4.6 Zone / hallway / zone-cold resolution at event time (finding 6 + REV 3)

Handler pseudocode:
```
def _on_room_occupancy_state_change(event):
    entity_id = event.data["entity_id"]
    old = event.data.get("old_state"); new = event.data.get("new_state")
    if not (old and new and old.state == "off" and new.state == "on"): return
    room_name = self._room_name_by_entity.get(entity_id)         # built at rebuild
    if not room_name: return
    room_type = self._room_type_by_name.get(room_name)
    if room_type == ROOM_TYPE_HALLWAY: return
    zone_id = self._resolve_zone(room_name)                      # zm.zones scan
    if not zone_id: return
    zm = self._zone_manager
    if zm._hvac_armed.get(room_name) is True: return             # gate 3
    zone_rooms = self._rooms_of_zone(zone_id)                    # cached at rebuild
    if any(zm._hvac_armed.get(sib, False) for sib in zone_rooms if sib != room_name):
        self._fast_path_warm_zone_gated_total += 1               # gate 3b (REV 3)
        return
    # limiter + boot-settle + re-entrancy per §4.1 gates 4-7
```

`self._room_name_by_entity`, `self._room_type_by_name`, `self._rooms_of_zone` rebuilt on
`SIGNAL_ROOM_ENTRY_LIFECYCLE` and on config-entry `options_updated` (finding 7).

### 4.7 Count-coupled side effects — MUST SKIP on non-periodic cycles (finding 1)

`_run_decision_cycle` today runs several call sites whose semantics assume "one call per
5-min tick." Firing an extra whole-house cycle on a fast-path trigger perturbs their
counters. Threading `trigger` and skipping the count-coupled ones on
`trigger != "periodic"` is required for INV conjunct (3) — behaviour-neutrality for every
other zone.

Reviewer B on this plan MUST verify this table against the merged `develop` at build
dispatch.

| Site (file:line) | Count-coupled OR time-based | Rev-3 disposition on non-periodic |
|---|---|---|
| `_check_carrier_freshness` (`hvac.py:1670`) | Time-based (last-poll timestamp) | Run — safe. |
| `update_room_conditions` (`hvac.py:1656`, `hvac_zones.py:523`) | Time-based (uses `now`, tail expiry) | Run — this is THE reason the fast path exists. Note: this call sets `current_session_start = now` at `hvac_zones.py:714-716`, arming the dwell — so the fast-path cycle itself hits the dwell skip and schedules the D3 follow-up. Expected. |
| `_egress_manager.async_tick(now)` (`hvac.py:1696`) | Time-based | Run. |
| `_predictor` updates (banking / pre-cool / pre-heat) (`hvac.py:1784`) | Time-based (per-schedule) — VERIFY | Default: skip on non-periodic to avoid off-cadence schedule reads. Reviewer B verifies each. |
| `_fan_controller.update(constraint, house_state)` (`hvac.py:1764`, reads `room_cond.occupied` `hvac_fans.py:761`, `:997`, `:1207`) | Time-based | Run on non-periodic. **REV 3 note: under the zone-cold gate (§4.1 gate 3b), warm-zone rising edges no longer fire the fast path, so warm-edge fan-in falls back to the periodic tick (median wait 142–181 s per D0 §3.1) — the same as today. Cold-zone entries DO get their fan fast-in via the fast-path fire. If a future measurement shows warm-edge fan latency actually matters, the escape hatch is card `HVAC-FAST-PATH-FAN-WARM-EDGES-1` (minted by orchestrator 2026-09-26) — do NOT bake warm-edge whole-house triggering into this cycle to serve one consumer.** |
| `_cover_controller.update` (`hvac.py:1767`) | Time-based | Run. |
| `_override_arrester.check_ac_reset` (`hvac.py:1760`) → `hvac_override.py:3805-3815` `kwh_samples_above_threshold += 1` vs `_sustained_samples` | **COUNT-COUPLED** | **SKIP on non-periodic.** An extra call inflates the sample counter, tripping the nudge debounce early. |
| `_override_arrester` per-zone override detection | Contains its own suppression window (C17: 5 s temp / 120 s preset), event-driven internally | Run. Its own suppression handles the extra call. |
| Anomaly observations (`hvac.py:1783`) | **COUNT-COUPLED** (per-cycle samples feed `AnomalyDetector` baselines) | **SKIP on non-periodic.** Extra samples pollute baselines. |
| `_emit_and_reset_short_cycles` daily rollover (`hvac.py:1643`) | Time-based (LOCAL-day hinge) | Run. |
| `_predictor.flush_daily_outcome` (`hvac.py:1610`) | Time-based (daily hinge) | Run. |
| Row-1 / row-4 / row-10 / D5 / D6 / D7 / D9 / F4 preset & retreat logic | Time-based (reads current state) | Run — this IS the fast-path payload. |
| `preset_change` activity-log write (`hvac.py:2716-2748`) | Event-driven (only fires on actual change) | Run; add `trigger` to details dict (finding 2). |
| Zone-dwell skip (`hvac.py:2362-2365`) | Time-based | Run — schedules the D3 follow-up (§4.4). |

**Implementation shape:** `_run_decision_cycle(trigger)` receives the arg and guards each
count-coupled call with `if trigger == "periodic":`. Adding two guards; no logic changes
inside the guarded calls. Behaviour-neutrality for periodic ticks is byte-identical (the
arg default is `"periodic"`).

House-state and pre-arrival triggers (already existing) inherit the same skip — they fire
at low rates today, but they're also count-coupled by the same argument. Threading the arg
fixes them retroactively; document in the D2 progress note.

### 4.8 Coexistence with other triggers (unchanged intent, updated per §4.7)

- Boot-settle: honoured; §4.5 stamping rule ensures no state pollution on early returns.
- House-state / pre-arrival: pass `trigger="house_state"` / `trigger="pre_arrival"` explicitly so the §4.7 skip applies to them too — a small side-benefit finding 1 unlocks.
- Egress initial-restore gate: unaffected.
- `SIGNAL_ZM_ZONES_UPDATED`: unaffected.
- Carrier post-write guard (C16) × arrester preset-suppression (C17 120 s): unchanged by this cycle — no new preset writes are introduced.

---

## 5. Deliverables

### D0 — Empirical probe (READ-ONLY, gate) — DONE 2026-09-26
**Acceptance:**
- **Verify (DONE):** per-zone trigger-eligible edge counts (median / p95 / max / bursts-per-5-min p95) after armed-gate replay — see AUDIT §2, §3.1, §3.2.
- **Verify (DONE):** cycle-duration p50/p95/p99 (SLA sizing) — proxy per AUDIT §5.
- **Verify (PENDING — audit §7):** pre-W2-1 per-zone `climate_write` rows/day baseline from W1-A ≥ 1-day post-ship window. Earliest 2026-09-27 ~15:25 CDT. Query in audit §7. **Build may be dispatched after this table is filled; ship gate (D3 Live) still consumes it.**
- **Verify (DONE):** proposed `HVAC_FAST_PATH_MIN_INTERVAL_S = 60`, `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S = 20`, `HVAC_FAST_PATH_SLA_S = 45` with justifications — see §REV 3 DELTA #3.

### D1 — Constants, state, `trigger` threading, count-coupled skips
Add the four constants at sized values (`HVAC_FAST_PATH_MIN_INTERVAL_S = 60`,
`HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S = 20`, `HVAC_FAST_PATH_SLA_S = 45`,
`FAST_PATH_DWELL_SLACK_S = 2`); add the state fields (including
`_fast_path_warm_zone_gated_total`); thread `trigger` through `_async_decision_cycle` and
`_run_decision_cycle`; add the two count-coupled guards per §4.7. Put `trigger` into the
existing `preset_change` details dict (`hvac.py:2716-2748`). Expose counters as attributes
on an existing HVAC sensor.

**Wire-in anchors:**
- `test_run_decision_cycle_trigger_defaults_periodic` — call sites without kwarg default to `"periodic"`.
- `test_fast_path_skips_check_ac_reset_sample_increment` — invoke `_run_decision_cycle(trigger="fast_path")`, assert `zone.kwh_samples_above_threshold` unchanged from prior value; mutation drill: comment out the guard → this test FAILS.
- `test_fast_path_skips_anomaly_observation` — spy on AnomalyDetector.observe; assert 0 calls; mutation drill on the guard.
- `test_periodic_cycle_byte_identical_to_develop` — snapshot behavioural output of a periodic cycle before and after the patch; require equivalence (structural, not stringly).
- `test_preset_change_activity_log_carries_trigger` — assert details dict contains `trigger` key with the expected enum value.

**Acceptance:**
- **Verify:** the count-coupled skip table (§4.7) has a matching guard in code, one per row.
- **Live:** post-restart, `ura_activity_log` `preset_change` rows carry a `trigger` in details for at least one row per trigger kind within 24 h.

### D2 — Fast-path trigger wiring (rising edge, hallway-excluded, armed-gated, ZONE-COLD-gated, DENY-limited)
Register `async_track_state_change_event` on the filtered set at `async_setup` (`hvac.py`
— after room-coordinator seed at :1254, before / adjacent to the periodic timer at :1355).
Single unsub on `self._fast_path_state_unsub` — release-then-reassign on rebuild
(finding 7). Subscribe to `SIGNAL_ROOM_ENTRY_LIFECYCLE` AND to config-entry
`options_updated` (finding 7) to rebuild. Implement gate 3b (zone-cold) and gate 6
(global DENY) per §4.1.

**Wire-in anchors (mutation drills required — Tier 2-DB C-framing):**
- `test_fast_path_registered_at_setup_with_filtered_entities` — asserts registration; neuter drill on the call.
- `test_fast_path_rebuilds_on_lifecycle_signal_no_double_unsub` — fires `SIGNAL_ROOM_ENTRY_LIFECYCLE`; asserts previous unsub is called ONCE and a new one is stored; drill: replace release-then-reassign with re-registration → test FAILS RED with the `helpers/event.py:441-447` shape.
- `test_fast_path_rebuilds_on_options_updated` — analogous, options-flow path.
- `test_fast_path_hallway_excluded_at_event_time` — behavioural, not source-grep.
- `test_fast_path_skips_when_hvac_armed_already` — sets `zm._hvac_armed[room]=True`, dispatches edge, asserts no cycle.
- `test_fast_path_skips_when_zone_warm` (REV 3) — sets `zm._hvac_armed[sibling]=True` in the same zone (target room NOT armed), dispatches edge, asserts no cycle and `_fast_path_warm_zone_gated_total` incremented; mutation drill on gate 3b.
- `test_fast_path_falling_edge_ignored` — on→off does nothing.
- `test_fast_path_unknown_unavailable_ignored` — old ∈ {unknown, unavailable, None} does not trigger.
- `test_fast_path_skips_room_in_no_hvac_zone` — a room absent from every `zone.rooms` produces no trigger.
- `test_fast_path_global_limiter_denies_and_next_tick_recovers` (REV 3) — stamp `_fast_path_last_run_at_any_zone` at now-5s (G=20 → within window); dispatch a zone-cold edge; assert no fast-path cycle fires AND `_fast_path_global_rate_limited_total` incremented; advance clock to the next periodic tick and assert `_run_decision_cycle` runs with `trigger="periodic"` and processes the zone (edge is not lost — discharged by the tick backstop). Mutation drill: comment out the gate-6 counter increment → this test FAILS.

**Acceptance:**
- **Test:** all wire-in tests pass with mutation drills.
- **Live:** counter `fast_path_triggers_total > 0` within 24 h; `fast_path_skipped_reentrant_total` bounded; `fast_path_warm_zone_gated_total` > 0 within 24 h (D0 predicts ≈52/day house-wide); `fast_path_global_rate_limited_total` ≤ 3/day on average (revival trigger for parked DEFER, §7).

### D3 — Dwell-expiry follow-up (MAIN hot-entry path, per finding 4 + C18)
Implement §4.4 for periodic AND fast-path triggers (any dwell skip). Per-zone dedup dict
`_fast_path_pending_dwell`; unsubs cancelled from that dict in `async_teardown`.
Follow-ups EXEMPT from BOTH per-zone AND global limiters (REV 3).

**Wire-in anchors:**
- `test_dwell_skip_schedules_followup_regardless_of_trigger` — parametrise `trigger ∈ {"periodic","fast_path","house_state"}`; each schedules one follow-up.
- `test_dwell_followup_exempt_from_per_zone_limiter` — stamp `_fast_path_last_run_at[Z]` recently; assert follow-up still runs.
- `test_dwell_followup_exempt_from_global_limiter` (REV 3) — stamp `_fast_path_last_run_at_any_zone` recently (within G); assert follow-up still runs immediately (not denied, not deferred); mutation drill: remove the exemption → test FAILS.
- `test_dwell_followup_deduplicated_per_zone` — two dwell skips → one follow-up.
- `test_dwell_followup_cancelled_on_teardown` — call `async_unload` mid-window; assert no callback fires.
- `test_dwell_followup_writes_preset_when_expected` — end-to-end with a hot-entry fixture (zone away, empty, edge lands, follow-up fires after dwell + slack, `preset_change` recorded).

**Acceptance (rewritten, finding 10 + REV 3):**
- **Verify (D0 baseline restated):** today's edge→`preset_change` p50 latency on ZONE-COLD hot entries (zone away, `any_room_hvac_occupied` False, no active session) is **300-600 s** (C18).
- **Verify (post-fix discriminator):** share of ZONE-COLD hot entries with edge→`ura_activity_log preset_change` (or W1-A `climate_write`) latency < **250 s** rises from ≈0 to ≈all, EXCEPT the ~1/day cross-zone-G-denied edges (which land at the next periodic tick + dwell), with the winning row's details carrying `trigger=fast_path_dwell_followup`.
- **Live:** 3+ zone-cold hot entries in the first 24 h post-restart show < 250 s edge→write; recorder + `ura_activity_log` cross-check.
- **Live (write-rate acceptance, finding 8) — PENDING baseline (audit §7):** per-zone `climate_write` rows/day ≤ pre-W2-1 baseline + D0-computed margin.

### D4 — Teardown, reload-storm safety, storm trip-wire (finding 9)
- Single-owned `_fast_path_state_unsub`; per-zone `_fast_path_pending_dwell` dict; all drained in `async_teardown`.
- `SIGNAL_ROOM_ENTRY_LIFECYCLE` handler is idempotent: release-then-reassign (no double-unsub).
- Add `fast_path_trigger_rate` metric to `AnomalyDetector` (per-zone, LOCAL-day bucket, sibling to `short_cycle_rate` at `hvac.py:1496-1500`). Storm trip-wire = anomaly on this metric → single NM. NO per-denial NM.

**Wire-in anchors:**
- `test_reload_storm_no_duplicate_dispatch` — 5 rapid lifecycle signals → exactly one active listener set.
- `test_fast_path_no_op_during_boot_settle` — trigger with `_boot_settle_done=False`; assert no cycle runs and `_fast_path_boot_suppressed_count` increments (and `_fast_path_last_run_at[Z]` NOT stamped).
- `test_storm_trip_wire_fires_once_at_threshold` — inject a burst; assert exactly one NM.

**Acceptance:**
- **Live:** no `RuntimeError` in logs referencing fast-path; storm trip-wire silent in first hour.

---

## 6. Open operator question

**Q1 — Per-zone vs whole-house cycle.** CLOSED by REV 3 zone-cold gate: expected ≈33 non-periodic cycles/day + 288 periodic ticks, +11 %. §4.7 count-coupled skip keeps sibling zones behaviourally unaffected. No per-thermostat cadence regression expected; the D3 write-rate acceptance is the empirical ship gate.

No other open questions.

---

## 7. Non-goals + PARKED alternatives (rev-2 additions bolded; rev-3 additions italicised)

- No dwell / tail / grace / hallway-exclusion / retreat semantics change.
- No falling-edge fast path.
- No new preset/setpoint write sites.
- No producer refactor (`_compute_hvac_occupied` stays inside the tick).
- No operator UI knob for the limiter.
- **No new sensor** (`sensor.ura_hvac_coordinator_decision_cycle` was invented in rev 1 and is retracted, finding 2).
- **No new per-cycle DB writer** — counters are in-memory attributes; `trigger` piggy-backs on the existing `preset_change` activity-log row (finding 2).
- **No per-denial NM** — storm trip-wire only (finding 9). *Per-global-DENY denials are counters, no NM (REV 3).*
- **No Nest / other-brand strategy changes** — W1-B territory.
- *No warm-zone triggers (REV 3, §4.1 gate 3b) — an edge in a zone that already has an armed sibling room does NOT fire the fast path.*
- *No dedicated fan-only fast path in this cycle (REV 3) — the warm-edge fan-latency trade-off is accepted; escape hatch is card `HVAC-FAST-PATH-FAN-WARM-EDGES-1` (minted by orchestrator on the board 2026-09-26).*

### PARKED alternative — Global-limiter DEFER (REV 3, not built)

An earlier REV 3 draft proposed deferring globally-limited triggers via `async_call_later(G - elapsed_s)` (per-zone `_fast_path_pending_defer` dict, teardown cancellation, restart-clears semantics), so a G-denied zone-cold edge would fire at `last_any_zone + G` instead of falling back to the periodic tick.

- **Marginal benefit measured:** ~7 zone-cold edges/week (~1/day) at G=20 (D0 §6.2) currently get today's 5-min-tick latency instead of ~20 s.
- **Marginal cost:** a new `async_call_later` per denied edge + per-zone pending state dict + teardown / restart discharge machinery — the state-machine × time ingredient behind our worst bug families (kanban memory `feedback_marginal_benefit_pushback`).
- **Orchestrator decision (2026-09-26):** simpler DENY + tick backstop wins on marginal-benefit grounds.
- **Revival trigger:** revive the DEFER design (recover the ~1/day edges) IF `fast_path_global_rate_limited_total` exceeds ~3/day on a 7-day rolling average, OR a specific denied cold edge coincides with a comfort complaint traceable to the delayed HVAC response.
- **Design carrier:** this planning doc's git history — the DEFER draft state is retrievable from the intermediate REV 3 file version. No card exists today; mint one when the revival trigger fires.

---

## 8. Tier + review framings (unchanged from rev 1, expanded per finding 1 + 8; REV 3 adds gate 3b + follow-up exemption)

**Tier 2-DB (three framing-disjoint reviews + live validation + README write-back).**

**Framings:**
- **A — Local correctness + limiter arithmetic + rising-edge classification.** Per-zone stamp discipline (finding 5); trailing-rerun idempotence; per-zone L + global G DENY arithmetic; zone-cold gate correctness at event time (siblings-set lookup consistent under lifecycle rebuilds); follow-up exemption from both L and G (REV 3).
- **B — Integration + decision-cycle integrity + count-coupled classification.** Verify §4.7 table against merged `develop`; verify the `trigger`-arg thread does not miss any call site; verify Carrier cloud bound holds against W1-A per-zone write-rate baseline (finding 8; PENDING per audit §7); verify house-state / pre-arrival paths inherit the skip cleanly; C16/C17 interactions still no-op for this cycle; **verify zone-cold gate does not lose a legitimate preset outcome under any legal config (e.g. edge lands in the same 20 s as a sibling's arm — is the sibling armed BEFORE or AFTER the producer runs?); verify the DENY tick-backstop actually processes a denied zone-cold edge (test `test_fast_path_global_limiter_denies_and_next_tick_recovers`).**
- **C — Test authority via real per-site mutation.** Neuter each of: state-change registration, zone-cold gate 3b, per-zone L, global G DENY (counter + return), count-coupled skip guards, dwell follow-up scheduler, follow-up exemption from L and G (REV 3), lifecycle re-subscribe, options_updated re-subscribe. Each mutation MUST turn a SPECIFIC test RED; no aggregate monkeypatch. Confirm no `.pyc` staleness (`feedback_mutation_verification_pycache_staleness.md`).

**Reviewer D (adversarial completeness):** re-enumerate every count-coupled site in
`_run_decision_cycle` and every downstream reader of the counters/sensors the D1 patch
touches; produce a legal-config reachable break of any INV conjunct. **REV 3 addition:
re-enumerate every producer path that could cause a zone's `_hvac_armed` sibling set to
change under the fast-path handler's foot (race with producer pass triggered by another
edge in the same event-loop iteration); confirm the DENY tick-backstop has no legal
config that could silently DROP a zone-cold edge (must land on a periodic tick within
300 s + dwell).**

**Plan review (mandatory):** ONE adversarial plan review before build dispatch — re-run
§1.1 greps, re-derive §4.7 table, verify §REV 3 DELTA numbers against the audit, verify
the DENY discharge map covers every legal early-exit and that no path drops a zone-cold
edge without a tick backstop.

**Sequencing gate (finding 8):** merge only after **W1-A is live ≥ 1 day** AND
`feature/hvac-live-room-establishment` is on `develop`. The pre-W2-1 climate-write
baseline in §5 D3's acceptance is unmeasurable before W1-A. **REV 3: baseline is
PENDING per audit §7; build may be dispatched once the baseline table is filled
(earliest 2026-09-27 ~15:25 CDT).**

---

## 9. Sequencing + overlap flag (v5.103.15)

Do not dispatch build until:
1. `feature/hvac-live-room-establishment` (v5.103.15) merges to `develop`.
2. W1-A ships and has been live ≥ 1 day. **(SHIPPED v5.103.16 2026-09-26 ~15:25 CDT; baseline measurable 2026-09-27 ~15:25 CDT.)**

Overlapping regions in `hvac.py` (v5.103.15): subscribe block :1131-1213;
`_async_decision_cycle` :1564-1598 (round-3 `_row1_hold_write` scoping fix at
:2002/:2056/:2533 in review — verify at dispatch); `_run_decision_cycle` :1600-1789
including :1656 `update_room_conditions` and the count-coupled sites in §4.7. At
dispatch, re-verify §1.1 REUSE line numbers.

---

## 10. Knobs on the ladder

| Number | Value | Rung | Why |
|---|---|---|---|
| `HVAC_FAST_PATH_MIN_INTERVAL_S` | 60 | 1 (module const) | Cloud-call-rate protective; not operator-facing. Sized on ZONE-COLD edges from D0 (0/114 denied at any L ≤ 300 s). |
| `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` | 20 | 1 (module const) | House-wide floor between non-periodic cycles. DENY semantic — ~1 zone-cold edge/day falls back to next periodic tick (accepted per §REV 3 DELTA #2; DEFER alternative parked in §7). |
| `HVAC_FAST_PATH_SLA_S` | 45 | 1 (module const) | Test/observability target for trigger→cycle-START. Sized from D0 cycle-END proxy p95 27.6 s + ~17 s headroom + trailing rerun. Comment MUST note the proxy method and that absolute DURATION is unmeasured. |
| `FAST_PATH_DWELL_SLACK_S` | 2 | 1 (module const) | Wall-clock slack past dwell edge; 1.7 % of live 120 s dwell. |

**Kill-switch:** none. Fast path degrades to today's behaviour (5-10 min hot entry per
C18) if the state-change subscription fails — warning log + one NM LOW at boot.

---

## 11. Producer / Consumer map (rev 3)

**PRODUCER of the "fast-path trigger" value:** HA `state_changed` events for
`binary_sensor.{entry_id}_occupied` (registry-resolved). Source health = URA room
coordinator's STATE_OCCUPIED write path. Falling-edge failures (e.g. sensor
`unavailable`) collapse to the periodic tick (5-min discharge). REV 3: the effective
producer domain is narrowed at the handler by the zone-cold gate (3b) so only edges
that can move the preset outcome propagate.

**CONSUMERS + call-sites:**
- `HVACCoordinator._async_decision_cycle(trigger="fast_path")` → `_run_decision_cycle(trigger)` — sole trust-consumer. Count-coupled call sites guarded per §4.7.
- `_fast_path_dwell_followup(Z)` (D3) — sole time-shifted trust-consumer; re-enters `_async_decision_cycle(trigger="fast_path_dwell_followup")`. Exempt from both limiters (REV 3).
- Periodic-tick backstop for global-DENY: `_async_decision_cycle(trigger="periodic")` picks up any denied zone-cold edge on the NEXT 5-min tick.
- Existing `preset_change` activity-log details dict — carries `trigger` for the audit oracle in D3's acceptance (display + audit).
- Existing HVAC coordinator sensor attributes — in-memory counter view (display + audit).
- `AnomalyDetector` `fast_path_trigger_rate` — storm trip-wire (audit).

**No new trust downstream.** The plan changes WHEN the cycle runs and PARTIALLY WHAT it
runs (count-coupled sites are gated by `trigger`); INV conjunct (3) makes the periodic-
tick output byte-identical.

---

## Appendix A — INV restated for reviewer D

> Under normal steady-state operation (boot-settle released, no active reload storm,
> W1-A live), for every HVAC-occupancy rising edge on a live non-hallway room R in an
> HVAC zone Z, where `zm._hvac_armed[R]` is not already True AND no sibling of R in Z
> is armed (zone-cold, REV 3 §4.1 gate 3b):
>
> 1. A `_run_decision_cycle(trigger="fast_path")` STARTS within `HVAC_FAST_PATH_SLA_S`
>    seconds unless denied by the per-zone or global limiter. A DENIED zone-cold edge
>    is discharged by the NEXT periodic 5-min tick (no zone-cold edge is dropped
>    without a discharge path).
> 2. If that cycle takes the dwell-skip branch at `hvac.py:2362-2365`, a follow-up
>    `_run_decision_cycle(trigger="fast_path_dwell_followup")` runs at
>    `zone.current_session_start + zone_entry_dwell + FAST_PATH_DWELL_SLACK_S`, exempt
>    from both per-zone and global limiters, per-zone dedup'd.
> 3. On any non-periodic cycle, the count-coupled sites in §4.7 are SKIPPED. The
>    periodic-tick output for every un-triggered zone is byte-identical to `develop`.
> 4. `_fast_path_last_run_at[Z]` and `_fast_path_last_run_at_any_zone` are stamped
>    ONLY when a cycle actually runs (not on denials, not on boot-settle early
>    returns, not on re-entrancy skips — which set `_fast_path_rerun_requested` and
>    produce one trailing cycle).
> 5. `async_teardown` cancels every fast-path subscription and per-zone dwell timer;
>    the state-change unsub is single-owned on `self._fast_path_state_unsub`.
> 6. Hot-entry latency (zone-cold edge → `ura_activity_log preset_change` row) drops
>    from the C18 baseline of 300-600 s to < 250 s for the class defined in §5 D3,
>    EXCEPT the ~1/day cross-zone-G-denied edges that discharge on the next tick.
>
> A legal-config, recorder-reachable violation of ANY conjunct falsifies INV.

---

## Rev 3 change log — audit-driven + orchestrator decision

| # | Change | Section(s) folded | Evidence |
|---|---|---|---|
| R3-1 | ZONE-COLD gate (§4.1 gate 3b); INV narrowed to zone-cold; marginal-benefit adopted | REV 3 DELTA #1; §2 INV; §4.1 gate 3b; §4.6 handler; §5 D2 wire-in `test_fast_path_skips_when_zone_warm`; §7 non-goals; §11; App A | Audit §0 headline: 114/472 (24 %) zone-cold; §6.4 finding 1 |
| R3-2 | Global limiter DENIES (per REV 2); follow-ups EXEMPT from both L and G; DEFER alternative PARKED in §7 with revival trigger. **Orchestrator decision 2026-09-26 (marginal-benefit): DEFER's benefit (~1/day recovered) doesn't pay for the new timer/dict/discharge surface.** | REV 3 DELTA #2; §2 INV conjunct (1) discharge; §4.1 gate 6 DENY; §4.3 counter naming + no `_fast_path_pending_defer` field + discharge map; §4.4 exemption; §5 D2 wire-in `test_fast_path_global_limiter_denies_and_next_tick_recovers`; §5 D3 wire-in `test_dwell_followup_exempt_from_global_limiter`; §5 D4 (no defer teardown test); §7 PARKED alternative + revival trigger; §8 framings updated; §11 consumers (add tick backstop, drop defer-fire) | Audit §6.2: 7 cold + 5 follow-up losses at G=20 DENY; exemption recovers the 5; DENY accepts the 7 (~1/day) |
| R3-3 | Constants sized: `HVAC_FAST_PATH_MIN_INTERVAL_S=60`, `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S=20`, `HVAC_FAST_PATH_SLA_S=45` | REV 3 DELTA #3; §3 sizing rule + fail-out; §4.3 constants block; §10 ladder | Audit §6.1, §6.2, §6.3 + §5 proxy caveat |
| R3-4 | D3 write-rate baseline documented PENDING with earliest date and query | REV 3 DELTA #4; §5 D0 acceptance + §5 D3 acceptance; §8 sequencing gate; §9 note | Audit §7 |
| R3-5 | Recomputed cycles/day ≈ 33, +11 % over 288 periodic ticks (DENY reduces base fires by ~1/day vs the DEFER draft) | REV 3 DELTA #5; §6 open Q1 closed | Audit §0 + §6.2 arithmetic |
| R3-6 | Fan-controller/other-consumer verdict explicit in §4.7 fan row + REV 3 DELTA fan verdict; card `HVAC-FAST-PATH-FAN-WARM-EDGES-1` minted by orchestrator on the board 2026-09-26 as the escape hatch | REV 3 DELTA fan-verdict; §4.7 fan row; §7 non-goals | `hvac_fans.py:495`, `:761` inspected; §4.7 rev-2 table |

## Rev 2 change log — findings 1-12 → sections (retained)

| # | Finding | Section(s) folded |
|---|---|---|
| 1 | HIGH — count-coupled side effects, `trigger` arg, skip on non-periodic; strike "changes WHEN not WHAT" and "sibling zones quiescent" | §2 (INV rewritten, claims struck), §4.7 (new table), §5 D1 (implementation + wire-in), §8 framings A/B/C, §11 (partial WHAT change acknowledged). House-state / pre-arrival note in §4.7. |
| 2 | HIGH — no invented surfaces; `trigger` on existing preset_change + counters as attrs on existing sensor | §1.1 (retraction), §4.3 (counters as attrs), §5 D1 (existing activity-log details dict + existing sensor), §7 (non-goals: no new sensor / no new DB writer). |
| 3 | HIGH — D0 uses `{entry_id}_occupied` via registry, armed-gate replay with day/night tail tables, cycle-duration percentiles | §3 (rewritten). §1.1 REUSE citations for tail tables. §10 sizing rule for SLA. |
| 4 | HIGH — dwell follow-up is the MAIN path; schedule on any dwell skip; exempt from limiter; rewrite D3 Live | §4.4 (rewritten), §5 D3 (Live acceptance rewritten around hot-entry share + trigger name). |
| 5 | MED — trailing rerun; stamp only when cycle actually runs; boot-settle stamps unchanged | §4.1 gate 7, §4.3 stamping rule, §4.5 (rewritten with pseudocode), §5 D4 wire-in. |
| 6 | MED — trigger spec (registry resolve, off→on strict, armed-gate at event time, hallway + zone at event time) | §4.1 gates 1-3, §4.6 (handler pseudocode). |
| 7 | MED — listener lifecycle: single unsub, options_updated rebuild, per-zone dict for D3 unsubs | §1.1, §4.3 state fields, §4.4 (dedicated dict), §5 D2 wire-in (no-double-unsub test cites helpers/event.py:441-447), §5 D4 teardown. |
| 8 | MED — merge after W1-A ≥ 1 day; write-rate acceptance vs baseline; global min interval | §3 baseline signal, §4.3 constants (global), §5 D3 write-rate acceptance, §8 sequencing gate, §9. |
| 9 | MED — denials as counters + debug log; storm trip-wire via AnomalyDetector, no per-denial NM | §4.3 counters (no NM), §5 D4 (trip-wire), §7 (non-goals). |
| 10 | MED — latency baseline 300-600 s (C18); oracle = ura_activity_log preset_change (or W1-A row); discriminator = share of hot entries edge→write < 250 s | §2 discriminator, §5 D3 acceptance, App A. |
| 11 | LOW — INV as "cycle STARTS within X s"; SLA sized from D0 cycle durations | §2 INV wording ("STARTS"), §3 cycle-duration percentiles, §10 rung note. |
| 12 | LOW — C6 amended; align text | §0 (integration-doc note); consistent language with the state-of-play. |
