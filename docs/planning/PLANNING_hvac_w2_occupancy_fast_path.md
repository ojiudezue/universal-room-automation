# PLANNING — W2 HVAC Occupancy Fast Path (shave the 5-min tick) — REV 4

> **SUPERSEDED 2026-09-28 by `PLANNING_hvac_fast_occupancy_response.md` (REV 7, built v5.103.20).** The fast path shipped ZONE-SCOPED (never a whole-house cycle) on the room HVAC-evidence stamp, with an exact-release exit timer and the D5 transit filter; the REV 4 dwell follow-up, global limiter G and rerun machinery were not built (see that plan §13). Historical only.


> **⚠️ SUPERSEDED DESIGN PREMISE (2026-09-27).** This document cites the S1 manual guard (`should_change_preset` refusing to write over `manual` — "Don't fight manual — that's the arrester's job", `hvac_preset.py:202-217`, v3.8.0) as design intent or as a load-bearing fact. The operator superseded that rule on 2026-09-27; W1-B replaces it with four gates (person-protected hold / arrester grace-compromise / arrester disabled / live borrow row). **Do not derive new designs from this doc's reasoning about the guard** — read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §9e and §10 C25 first. NOTE (parked plan): its `should_change_preset` predicate references assume the old guard; re-check against §9e if revived.

**STATUS 2026-09-26 (evening): PARKED by operator.** REV 4 failed its second plan review (4 HIGH). Replaced by setting the zone entry dwell to 0 (removes C18's second tick with no code; `hvac.py:2442` guard `dwell_minutes > 0`). Revive if measured entry latency p90 > 5 min or hot-entry complaints — see card HVAC-W2-OCCUPANCY-TRUTH.


**Card:** `HVAC-W2-OCCUPANCY-TRUTH` (child: `HVAC-HOT-ENTRY-LATENCY-1`).
**Workstream:** W2 (Occupancy Truth), operator-approved 4-workstream HVAC arc.
**Design origin:** commit `82620357a`; prior context `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` + `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`.
**Operator scope (binding, §9d):** *"shave the 5-min tick only for now."* NO dwell / hold / grace / tail / override / retreat-semantics change; whole-house cycle preserved.
**Sequencing:** BUILD AFTER `feature/hvac-live-room-establishment` (v5.103.15) merges AND AFTER W1-A has been live ≥ 3 days (REV 4: F9 margin rule needs ≥3-day baseline).

REV 2 folded FIX-PLAN-FIRST review findings 1-12. REV 3 folded the D0 measurement
(`docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md`) and the orchestrator's
marginal-benefit decision to keep global limiter as DENY. REV 4 folds the plan-review
FIX-PLAN-FIRST findings F1-F15 (orchestrator decisions per each). Change log at bottom.

---

## REV 4 DELTA (what changed vs REV 3, plan-review-driven)

Orchestrator decisions on plan-review findings F1-F15:

- **F1 (HIGH) — Dwell follow-up guarded + capped.** Schedule a follow-up ONLY when the
  dwell skip is BLOCKING a real preset change: i.e. `effective_preset != zone.preset_mode`
  AND `should_change_preset` would allow the write. Place the scheduler INSIDE
  `_apply_house_state_presets` immediately BEFORE the `continue` at **hvac.py:2451** (not
  in `_run_decision_cycle`). Add a per-zone follow-up rate cap
  `HVAC_FAST_PATH_DWELL_FOLLOWUPS_PER_ZONE_PER_HOUR = 6` (rung-1 module const; why: caps
  a runaway dwell-skip loop on an oscillating room to at most one per 10 min average per
  zone; well above the D0 zone-cold cold-edge rate of ≤ 2/day/zone). See §4.4.
- **F2 (HIGH) — Non-periodic S1 write-loop restricted to origin_zones; producer runs for
  ALL zones (bounded drift ≤ 1 tick, accepted).** `_async_decision_cycle` /
  `_run_decision_cycle` take a new keyword `origin_zones: set[str] | None`. On
  `trigger ∈ {fast_path, fast_path_dwell_followup}` the S1 preset-write loop
  (`_apply_house_state_presets`, iterating `zone_id`) SKIPS zones not in `origin_zones`
  — those zones are evaluated read-only (producer runs, decision computed, but NO
  `emit_set_preset_mode` / `emit_set_temperature` / `emit_set_hvac_mode` call is issued).
  For periodic ticks and every other trigger, `origin_zones = None` = "all zones" (today's
  behaviour). The producer (`update_room_conditions`, `hvac.py:1656`, iterates all rooms
  by design — no per-zone entry point) runs on every non-periodic cycle for ALL zones —
  sibling zones therefore have their tail_start / last_occupied_time /
  continuous_occupied_since / current_session_start updated at the fast-path cadence too.
  This is a strict refinement (finer-grained truth of the same observations, never new
  writes since S1 is origin-gated), so the sibling-zone drift vs "produce only on the
  periodic tick" is bounded by ≤ 1 periodic-tick interval (300 s) — the same envelope
  siblings live in today. Choice justification vs "only run producer for origin_zones":
  producer has no per-zone entry point in current code (`hvac_zones.py:523` iterates all
  rooms), so origin-only production would require a producer refactor (out of scope by
  §9d — "shave the 5-min tick only"). All-zones production preserves today's producer
  contract exactly and keeps §9d clean (no producer semantics change).
- **F3 (HIGH) — §4.7 skip set is ONLY {fast_path, fast_path_dwell_followup}.** Other
  triggers — `periodic`, house-state (`hvac.py:3131`), pre-arrival (`hvac.py:4004`), boot
  kick (`hvac.py:1553`), setup cycle (`hvac.py:1372`) — stay periodic-classified and run
  the full site list. The `trigger` enum literal for the boot-kick and setup cycle is
  `"periodic"` (they DO expect the full site set). Predictor row in §4.7 hardened:
  **count-coupled + event payload → SKIP on non-periodic (definitive; verified against
  `hvac.py:1784`).**
- **F4 — Zone-cold gate reads `zone.any_room_hvac_occupied`, not a sibling loop.** The
  fused signal is the authoritative "zone-cold" test (`hvac_zones.py:751`, exposed on
  `sensor.ura_hvac_coordinator_zone_{n}_status`). Race-freedom: HA runs on a single event
  loop; the handler reads the coordinator's last-computed fused value at
  `state_changed` dispatch time, and any concurrent producer update happens on the same
  loop (never truly concurrent). Worst-case misjudgment = one redundant fast-path cycle
  (which S1 write-loop then finds nothing to do in — accepted) or one edge falling back
  to the periodic tick (accepted per §REV 3 DELTA #2). This replaces the REV 3 gate 3b
  sibling-set lookup — one atomic read instead of a set comprehension over `_hvac_armed`.
- **F5 — Periodic ticks that hit the lock ALSO set `_fast_path_rerun_requested`.** The
  trailing rerun runs as `"periodic"` when a periodic cycle was dropped (not always as
  `"fast_path"`); track the CLASSIFICATION of the DROPPED trigger. Order of gates
  updated: **lock / rerun gate ahead of global DENY** — a periodic cycle should never
  be denied by the global limiter (it's the backstop), and a rerun request predates the
  limiter decision.
- **F6 — Origin_zones threading + rerun tracking + `_tearing_down`.** Origin zones flow
  through `_async_decision_cycle(_now=None, *, trigger="periodic", origin_zones=None)`
  → `_run_decision_cycle(trigger, origin_zones)`. Trailing reruns exempt from BOTH
  limiters AND tracked in `_pending_tasks`. New `self._tearing_down: bool` flag set
  synchronously at the top of `async_teardown`; checked by state-change handler,
  dwell-followup callback, and rerun scheduler — each returns immediately if
  `_tearing_down`. `async_teardown` DRAINS `self._fast_path_state_unsub` and all entries
  of `self._fast_path_pending_dwell` BEFORE its first `await` (so no callback fires
  against a half-torn-down coordinator).
- **F7 — Dwell follow-up pops its dict entry BEFORE dispatch.** Dispatched follow-up:
  `self._fast_path_pending_dwell.pop(zone_id, None)` then `hass.async_create_task(...)`.
  Wire-in `test_dwell_followup_rearms_after_fire` — after one follow-up fires, another
  dwell-skip on the same zone must schedule a fresh follow-up.
- **F8 — Follow-up rows carry `origin_trigger`; D3 pass criterion uses LIVE dwell.**
  When the follow-up runs and produces a `preset_change` row, the row's details dict
  carries `trigger="fast_path_dwell_followup"` AND `origin_trigger` ∈
  `{"fast_path","periodic","house_state","pre_arrival"}` (the trigger that scheduled the
  follow-up). D3 pass criterion (Live):
  - `p90(edge → preset_change_ts) ≤ hvac_zone_entry_dwell(live seconds) + FAST_PATH_DWELL_SLACK_S + HVAC_FAST_PATH_SLA_S` — dwell read from the LIVE `number.ura_hvac_coordinator_zone_entry_dwell` (state of play §3.2 — value has legitimately been retuned by the operator: current live = 2 minutes = 120 s), NOT a compile-time constant.
  - AND **≥ 90 %** of zone-cold hot entries have `origin_trigger="fast_path"` (i.e. the fast-path handler saw them; the residual ≤ 10 % is the periodic-tick backstop path for G-denied cold edges).
- **F9 — Corrected W1-A query, ≥ 3-day margin, attributable criterion.** Baseline query
  (audit §7 corrected):
  ```
  SELECT date(timestamp, 'unixepoch', 'localtime') AS d,
         json_extract(details_json, '$.zone_id')  AS zone,
         json_extract(details_json, '$.verb')     AS verb,
         COUNT(*) AS n
  FROM ura_activity_log
  WHERE action = 'climate_write'
    AND timestamp >= ?
  GROUP BY d, zone, verb ORDER BY d, zone, verb;
  ```
  Column name `details_json` (verify at build dispatch against W1-A's writer). Margin
  computation needs ≥ **3** full days of baseline; margin = `max(daily_delta_pct)` over
  the baseline days. Add **attributable ship criterion**: `fast_path_preset_change_rows_per_day
  ≤ zone_cold_edges_per_day_from_D0` per zone (D0 §2 has the numbers). If the fast path is
  writing more preset changes than there are zone-cold edges, something is wrong.
- **F10 — In-code hard ceiling + parked-DEFER recorder query.**
  - Hard ceiling: `HVAC_FAST_PATH_MAX_PER_ZONE_PER_HOUR = 15` (rung-1 module const; why: 15 = ~2.5× the p95-day per-zone zone-cold edge rate D0 §3.1 headline 2/day/zone worst — a safety brake that fires only if something is fundamentally wrong upstream; well below the L=60 s theoretical ceiling of 60/hour). On breach, emit ONE NM ("HVAC fast-path rate ceiling tripped on zone Z"), then FALL BACK TO TICK-ONLY for that zone until next daily rollover (skip fast-path fires; periodic tick unaffected). Counter `fast_path_ceiling_tripped_total`; ceiling state per-zone in `_fast_path_ceiling_tripped_until: dict[str, datetime]`.
  - Parked-DEFER revival query (recorder / ura DB):
    ```
    SELECT date(timestamp, 'unixepoch', 'localtime') AS d,
           json_extract(details_json, '$.zone_id') AS zone,
           COUNT(*) AS denies
    FROM ura_activity_log
    WHERE action = 'fast_path_global_deny'  -- if you emit a debug row; else read the counter attribute daily snapshot
    GROUP BY d, zone;
    ```
    Revival trigger: `denies/day > 3` on a 7-day rolling avg per zone (§7).
- **F11 — File:line citations refreshed** against `develop @ c1c555291` (current tip).
  Notable updates: dwell skip is `hvac.py:2451` (was cited variously as :2362-2365 in
  REV 2/3 — reviewer's audit); setup initial cycle `hvac.py:1372`; boot kick
  `hvac.py:1553`; count-coupled check_ac_reset call `hvac.py:1760`; fan controller call
  `hvac.py:1764`; predictor update `hvac.py:1784`.
- **F12 — `zm.zones` read live** (not cached at listener rebuild — zones dict is a live
  reference on `ZoneManager`).
- **F13 — ONE `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription** covers `options_updated`
  paths (URA fires the lifecycle signal from its own options-updated handling — verified
  against `signals.py:199` producers). Drop the separate options_updated subscription.
- **F14 — Thread `trigger` all the way to the `preset_change` write.** The trigger label
  must land in `_ura_activity_log_preset_change` details dict (`hvac.py:2716-2748`) — not
  just in an in-memory counter. Give `HVAC_FAST_PATH_SLA_S` a live consumer:
  `last_fast_path_edge_to_start_s: float | None` attribute on the coordinator, exposed on
  the existing `sensor.ura_hvac_coordinator_status` sensor (the sensor that also carries
  the counters in F14/F15). Rerun arithmetic corrected: **~1.5/day** (p95 cycle proxy 27.6
  s / 300 s tick × 16.6 zone-cold edges/day × 1 rerun each ≈ 1.5). REV 3 had ~0.7/day —
  wrong. Boot-suppressed counter unified: keep only `_fast_path_boot_suppressed_total`
  (removed the `_fast_path_boot_suppressed_count` alias).
- **F15 — `AnomalyDetector.record_observation`** is the correct method (not `observe`).
  Mutation drills: neuter the RETURN, not just the CALL (a returned-None mutation catches
  callers that rely on side effects too). Replace `test_periodic_cycle_byte_identical_to_develop`
  with `test_periodic_cycle_call_sequence_unchanged` (assert the ordered list of major
  call sites is identical; behavioural output equivalence is hard to assert cleanly).

Also updates:
- Recomputed load per REV 4 gates: base fast-path ~15.6/day + dwell follow-ups
  (**gated by F1 — most zone-cold entries land on a zone whose preset would change, so
  ~15/day scheduled**) + trailing reruns ~1.5/day (F14 correction) = **~32/day**
  non-periodic cycles, +11 % over 288 periodic ticks. Load envelope unchanged.
- INV conjunct (3) REWRITTEN TRUTHFULLY per F2: non-periodic cycles run the producer
  for all zones (bounded drift ≤ 1 periodic tick) and S1 preset-writes ONLY for zones
  in `origin_zones`; the "byte-identical to develop" claim is REPLACED with
  "preset-write output for zones ∉ origin_zones is identical to what a periodic tick at
  the same wallclock would produce."

**Card `HVAC-FAST-PATH-FAN-WARM-EDGES-1`** minted by orchestrator on the board
2026-09-26 as the escape hatch for the warm-edge fan-latency trade-off (§4.7, §7).

---

## 0. MANDATORY READ CONFIRMATION

Planner re-read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely (W1-A
Stage A SHIPPED v5.103.16 2026-09-26, §10 C1–C22 including C18 hot-entry mechanism and
C20 zone_1 borrow-return strand class) AND `docs/planning/PLANNING_hvac_arc_w1_w2_integration.md`
(C1–C7 binding). Integration doc `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md`
§9 (Carrier post-write guard × URA suppression) is UNVERIFIED per C16 and out of scope.

**C18 reframes this whole design.** The dwell-expiry follow-up is NOT a corner case; it is
the main hot-entry path (§4.4, §5.D3).

---

## 1. Institutional context verified

### 1.1 Prior-art scan — REUSE-or-BUILD per proposed piece

| Proposed piece | Verdict | Existing symbol (file:line, refreshed per F11) |
|---|---|---|
| Decision-cycle trigger dispatch | **REUSE pattern** | `hass.async_create_task(self._async_decision_cycle())` tracked in `_pending_tasks` — house-state at `hvac.py:3131-3133`, pre-arrival at `hvac.py:4002-4004`, boot-settle kickoff at `hvac.py:1553` via `async_call_later`, setup initial at `hvac.py:1372`. Re-entrancy guard `self._decision_cycle_lock` at `hvac.py:1592-1598`. |
| Per-room rising-edge source | **REUSE entity** | `binary_sensor.{entry_id}_occupied` — registry-resolved via `async_get_entity_id("binary_sensor", DOMAIN, f"{entry_id}_occupied")`. NOT the `hvac_occupied` sensor (lazy mirror, same producer, same lag). |
| Zone-cold gate | **REUSE fused signal** (F4) | `zone.any_room_hvac_occupied` on `ZoneManager.zones[zone_id]` — the fused OR set by the producer at `hvac_zones.py:751`. Atomic read, single-event-loop = race-free. |
| Trigger dedup / re-entrancy trailing rerun | **NEW (one flag)** | `self._fast_path_rerun_requested: str | None` — stores the CLASSIFICATION of the dropped trigger (`"periodic"` for a dropped tick, else the non-periodic label) so the rerun replays the right kind (F5). |
| Per-zone rate limiter | **NEW module const + dict** | `HVAC_FAST_PATH_MIN_INTERVAL_S` in `hvac_const.py` (rung-1, cloud-call-rate protective). State `self._fast_path_last_run_at: dict[str, datetime]`. |
| Global min-interval between non-periodic cycles | **NEW module const** | `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` — DENY on collision; periodic tick is the backstop discharge (§4.3). DEFER alternative parked (§7). |
| Dwell-expiry follow-up | **REUSE pattern (main path per C18)** | `async_call_later` + per-zone dedup dict `self._fast_path_pending_dwell`. F1-gated: only scheduled when a real change is blocked; F7: pops dict entry before dispatch. Cancelled in `async_teardown` BEFORE first await (F6). |
| Per-zone follow-up rate cap | **NEW module const + counter** | `HVAC_FAST_PATH_DWELL_FOLLOWUPS_PER_ZONE_PER_HOUR` (rung-1; F1). Sliding-window counter in `_fast_path_followup_bucket[zone_id]: deque[datetime]`. |
| Non-periodic hard ceiling | **NEW module const** | `HVAC_FAST_PATH_MAX_PER_ZONE_PER_HOUR` (rung-1; F10). |
| `trigger` + `origin_zones` classification through the cycle | **NEW args + REUSED skip-guards** | `_async_decision_cycle(_now=None, *, trigger="periodic", origin_zones=None)` → `_run_decision_cycle(trigger, origin_zones)`. On `trigger ∈ {fast_path, fast_path_dwell_followup}` the S1 preset-write loop `_apply_house_state_presets` skips zones ∉ origin_zones (F2). Count-coupled sites skipped per §4.7 (F3). |
| Trigger classification recorded | **REUSE surfaces** | Put `trigger` (and `origin_trigger` for follow-ups, F8) into the existing `preset_change` details dict (`hvac.py:2716-2748`). Threaded ALL THE WAY to the write, not just to counters (F14). |
| Storm trip-wire | **REUSE** | `AnomalyDetector.record_observation` (F15 — verified correct method name) at `hvac.py:1485-1501` — add `fast_path_trigger_rate` metric per-zone LOCAL-day bucket. NM only on the trip-wire (finding 9). |
| Listener rebuild on room lifecycle | **REUSE pattern (one signal, F13)** | `SIGNAL_ROOM_ENTRY_LIFECYCLE` (`signals.py:199`); URA options_updated flows through this signal, so ONE subscription is enough. Presence pattern at `presence.py:2624-2651`. Store the state-change unsub on `self._fast_path_state_unsub`, release-then-reassign (finding 7). |
| Live SLA consumer sensor | **REUSE sensor** (F14) | `sensor.ura_hvac_coordinator_status` — carries counters + `last_fast_path_edge_to_start_s: float | None`. |
| Latency oracle | **REUSE** | `ura_activity_log preset_change` row (`hvac.py:2716-2748`) — trigger + origin_trigger in details (F8). W1-A `climate_write` rows for the write-rate baseline (F9). |

### 1.2 Prior planning docs consulted

- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md`
- `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`
- `docs/planning/PLANNING_hvac_live_room_establishment.md` REV 2 (v5.103.15 in flight — §9 overlap)
- `docs/planning/PLANNING_hvac_governed_excursion.md` rev-6 (trigger routes through `_async_decision_cycle`, not `_run_decision_cycle`)
- `docs/planning/PLANNING_hvac_arc_w1_w2_integration.md` (C1–C7 contracts binding this cycle)
- `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md` (D0 probe — REV 3 input; §7 corrected query per F9)

### 1.3 Memory + design docs read

- `feedback_wire_in_anchor_mandatory.md`, `feedback_suppression_needs_discharge.md`, `feedback_measure_before_build.md`, `feedback_marginal_benefit_pushback.md`, `feedback_tier2plus_prior_art_scan.md`, `feedback_mutation_verification_pycache_staleness.md`, `feedback_falsify_before_asserting.md`, `project_reload_storm_refuted_restart_storm_live.md`, `project_incident_v5_8_0_setup_recursion.md`, `feedback_no_fabrication.md`.
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (C16-C22 folded — see §0). W1-A Stage A SHIPPED v5.103.16.

### 1.4 Code locations surveyed (refreshed per F11 against develop @ c1c555291)

- `hvac.py`: subscribe block :1131-1213; periodic timer :1355-1369; setup initial cycle :1372; boot-settle kick :1553; `_async_decision_cycle` :1564-1598 (re-entrancy guard :1592-1598, boot-settle early-return :1580); `_run_decision_cycle` :1600-1789 (update_room_conditions :1656; check_carrier_freshness :1670; egress tick :1696; check_ac_reset :1760; fan controller :1764; cover controller :1767; predictor update :1784; anomaly observation :1783); `_apply_house_state_presets` :2013+ **with dwell-skip `continue` at :2451** (F11 correction); preset_change activity-log :2716-2748; `_handle_house_state_changed` :3096-3133; `_handle_person_arriving` :3990-4004.
- `hvac_fans.py`: `FanController.update` :495, reads `room_cond.occupied` at :761 (SAME source as the fast-path trigger — the only warm-edge consumer that would benefit).
- `hvac_override.py`: `check_ac_reset` count-coupling `:3805-3815` (`kwh_samples_above_threshold += 1` vs `_sustained_samples`); suppression windows `:129`, `:141-146`, `:153` (C17).
- `hvac_zones.py`: `update_room_conditions` :523 (iterates all rooms — no per-zone entry point); `_hvac_armed` :241/990; hallway exclusion :650-665; `current_session_start = now` at :714-716 (C18 mechanism); fused `any_room_hvac_occupied` set at :751; `is_zone_hvac_established` :1043.
- `hvac_const.py`: `HVAC_DECISION_TICK` :11-13.
- `const.py`: `ROOM_TYPE_HVAC_HOLD` :1219-1224 (day), `ROOM_TYPE_HVAC_HOLD_NIGHT` :1230-1242 (night).
- `binary_sensor.py`: `HVACOccupiedBinarySensor` :745.
- `signals.py`: `SIGNAL_ROOM_ENTRY_LIFECYCLE` :199 (covers options_updated via URA's own re-emit — F13).

---

## 2. Falsifiable invariant (REV 4 — zone-cold; origin_zones write scope; producer drift bounded)

**INV:** *"For every HVAC-occupancy rising edge on a live, non-hallway room R (ROOM entry
LOADED, coordinator present, `zm._hvac_armed[R]` NOT already True at event time) belonging
to an HVAC zone Z that is currently zone-cold (`zone.any_room_hvac_occupied is False`,
F4):*
1. *`_run_decision_cycle` STARTS within `HVAC_FAST_PATH_SLA_S` of the source `state_changed` event, UNLESS denied by the per-zone limiter (D0: 0/114 zone-cold denials in 7 d), OR denied by the global limiter (D0: ~1/day), OR gated by the F10 hard-ceiling fallback for zone Z. A DENIED zone-cold edge is discharged by the NEXT periodic 5-min tick (backstop); no zone-cold edge is dropped without a discharge path.*
2. *When R's zone Z would be preset-flipped by that cycle but is dwell-blocked at `hvac.py:2451` AND (`effective_preset != zone.preset_mode` AND `should_change_preset(zone,effective_preset)` is True), a follow-up cycle is scheduled at `zone.current_session_start + (zone_entry_dwell_live_seconds) + FAST_PATH_DWELL_SLACK_S` (per-zone dedup; per-zone rate cap `HVAC_FAST_PATH_DWELL_FOLLOWUPS_PER_ZONE_PER_HOUR`, F1). The follow-up cycle carries `origin_zones={Z}` and is EXEMPT from BOTH the per-zone AND the global limiter.*
3. *On a `trigger ∈ {fast_path, fast_path_dwell_followup}` cycle with `origin_zones = O`: (a) the producer (`update_room_conditions`) runs for ALL zones — sibling-zone producer state is REFRESHED with today's `now`, refining the same observations (never new writes); the sibling-zone drift vs a "producer only on the periodic tick" world is bounded by ≤ HVAC_DECISION_TICK (300 s), the same envelope siblings live in today. (b) The S1 preset-write loop (`_apply_house_state_presets`) skips zones ∉ O — the preset/setpoint/mode WRITES for zones ∉ O are IDENTICAL to what the next periodic tick would produce, evaluated at the periodic-tick wallclock. (c) The count-coupled sites in §4.7 are SKIPPED (or proven time-based per the table). Other triggers (`periodic`, `house_state`, `pre_arrival`, boot-kick, setup) are treated as `origin_zones=None` (all zones) and run the full site list.*
4. *Every fast-path subscription and per-zone dwell timer is DRAINED in `async_teardown` BEFORE its first await (F6). The handler, dwell-followup callback, and rerun scheduler each check `self._tearing_down` and return immediately if set. The state-change unsub is single-owned on `self._fast_path_state_unsub`.*
5. *`_fast_path_last_run_at[Z]` and `_fast_path_last_run_at_any_zone` are stamped ONLY when a cycle actually runs — not on denials, boot-settle early returns, hard-ceiling fallback, or re-entrancy skips (which set `_fast_path_rerun_requested` to the DROPPED trigger label, F5, and produce one trailing rerun after lock release, running WITH that trigger label).*
6. *Hot-entry latency (zone-cold edge → `ura_activity_log preset_change` row with `origin_trigger="fast_path"`): p90 ≤ `hvac_zone_entry_dwell_live_seconds + FAST_PATH_DWELL_SLACK_S + HVAC_FAST_PATH_SLA_S` (F8) for the class in §5 D3, AND at least 90 % of zone-cold entries have `origin_trigger="fast_path"`.*

Discriminating observations: today, zone-cold hot entries have edge→write p50 300–600 s
(C18). Under the fix, the p90 target uses the LIVE dwell number (currently 120 s → target
≈ 120 + 2 + 45 = 167 s). The `origin_trigger` field on the `preset_change` row is the
label that discriminates "the fast path handled this" from "the periodic tick handled this".

---

## 3. D0 — Measure before you build — DONE 2026-09-26

**Result:** `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md`. Probe:
`scripts/probes/hvac_fast_path_d0_probe.py`. Window 165.2 h MAIN with 5 restarts
excluded, 33 rooms in scope, variant S as the recommended basis.

**Headline (unchanged from REV 3):** 472 trigger-eligible edges (68.6/day); 114
zone-cold (16.6/day, 24 %); zone-cold burst p95 = 1 in every zone; zone-cold min in-zone
gap 646 s (per-zone L up to 300 s denies 0/114); global G=20 DENY denies ~7/week
zone-cold (~1/day, accepted per §REV 3 DELTA #2); cycle-END proxy p95 27.6 s.

**Sizing rule (REV 4):** `HVAC_FAST_PATH_MIN_INTERVAL_S = 60` (0/114 zone-cold denied);
`HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S = 20` (~1/day zone-cold falls back to periodic
tick — accepted); `HVAC_FAST_PATH_SLA_S = 45`; `FAST_PATH_DWELL_SLACK_S = 2`;
`HVAC_FAST_PATH_DWELL_FOLLOWUPS_PER_ZONE_PER_HOUR = 6` (F1); `HVAC_FAST_PATH_MAX_PER_ZONE_PER_HOUR = 15` (F10).

**Fail-out (REV 2 formula) did not fire on the zone-cold denominator.** Build proceeds.

---

## 4. Design

### 4.1 Trigger source

`async_track_state_change_event` on the filtered set of `binary_sensor.{entry_id}_occupied`
entity_ids (registry-resolved). Filter set built at setup from all non-disabled ROOM
entries; hallway flag and zone-membership re-checked at EVENT TIME (`zm.zones` read live
per F12).

**Rising-edge classification:** strict `"off"` → `"on"` only. D0 measured only 1 non-off→on
transition in 7 d (audit §1) — noise negligible.

**Per-event gating (all short-circuit, in this order — REV 4 updated per F4, F5, F10):**
1. `self._tearing_down` — return (F6).
2. Room is a member of some HVAC `zone.rooms` — else skip.
3. Room's `CONF_ROOM_TYPE != ROOM_TYPE_HALLWAY` — else skip.
4. `zm._hvac_armed.get(room_name) is not True` — if already armed, D1 producer state won't change.
5. **Zone-cold gate (F4):** `zone.any_room_hvac_occupied is False` — else skip and increment `_fast_path_warm_zone_gated_total`. Uses the fused signal on `ZoneManager.zones[zone_id]` (`hvac_zones.py:751`), not a sibling loop.
6. Not inside boot-settle — if suppressed, increment `_fast_path_boot_suppressed_total` (F15 unified name), do NOT stamp last-run.
7. **F10 hard-ceiling fallback:** if `now < _fast_path_ceiling_tripped_until.get(Z, min)`, skip and increment `fast_path_ceiling_gated_total`.
8. **F5 lock/rerun gate — AHEAD of global DENY:** if `_decision_cycle_lock.locked()`, set `_fast_path_rerun_requested = trigger` (the DROPPED trigger label — F5) and return.
9. Per-zone limiter (DENY, counter `fast_path_rate_limited_total`). D0: 0/114 zone-cold hit.
10. Global limiter (DENY, counter `fast_path_global_rate_limited_total`). ~1/day zone-cold falls back to next tick.
11. Update F10 sliding-window sample. If breach, set `_fast_path_ceiling_tripped_until[Z] = next_local_midnight`, emit ONE NM, return (this fires BEFORE the dispatch so the tripping cycle is denied).

If all pass, dispatch via
`hass.async_create_task(self._async_decision_cycle(trigger="fast_path", origin_zones={zone_id}))`,
tracked in `_pending_tasks`.

**F4 race-freedom.** Read of `zone.any_room_hvac_occupied` is single-loop atomic. Even if
a sibling's `_hvac_armed` is about to flip in the same tick, either (a) the sibling's
state_changed callback ran first and the fused signal reflects it (we skip — correct),
or (b) it runs after ours (we fire — one redundant cycle, no incorrect writes because S1
is origin-gated). No misclassification loses a preset outcome.

### 4.2 Rising-edge only (unchanged)

Falling edges ride the periodic tick — retreat needs fused-empty AND ≥ 10-min vacancy
grace; ≤ 5-min falling-edge lag is invisible.

### 4.3 Rate limiter — per-zone + global (REV 3 DENY; REV 4 order + ceiling)

**Constants (`hvac_const.py`, rung 1; sibling comment to `HVAC_DECISION_TICK`):**

| Const | Value | Why (rung 1 = cloud-rate protective / policy — change requires review) |
|---|---|---|
| `HVAC_FAST_PATH_MIN_INTERVAL_S` | 60 | Per-zone floor. D0 §6.1: 0/114 zone-cold denied at any L ≤ 300 s; 60 s is a meaningful cloud-rate cap >> HA loop lateness. |
| `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` | 20 | House-wide floor. D0 §6.2: G=20 caps at ≤ 1 non-periodic cycle per 20 s; ~1 zone-cold edge/day falls back to periodic tick (accepted per §REV 3 DELTA #2). |
| `HVAC_FAST_PATH_SLA_S` | 45 | Trigger→cycle-START target. D0 §6.3 proxy p95 27.6 s + 17 s headroom. Comment MUST note proxy method + absolute-duration unmeasured. Live consumer: `last_fast_path_edge_to_start_s` attr on `sensor.ura_hvac_coordinator_status` (F14). |
| `FAST_PATH_DWELL_SLACK_S` | 2 | Wall-clock slack past dwell edge. |
| `HVAC_FAST_PATH_DWELL_FOLLOWUPS_PER_ZONE_PER_HOUR` | 6 | F1 per-zone follow-up cap. Caps a runaway dwell-skip loop to ≤ 1 per 10 min per zone; well above the D0 zone-cold rate (max 2/day/zone). |
| `HVAC_FAST_PATH_MAX_PER_ZONE_PER_HOUR` | 15 | F10 hard ceiling. ~2.5× the p95-day per-zone zone-cold edge rate; kill-switch, not throttle. On breach: one NM + tick-only fallback for that zone until midnight. |

**State (on `HVACCoordinator`):**
- `self._fast_path_last_run_at: dict[str, datetime]`
- `self._fast_path_last_run_at_any_zone: datetime | None`
- `self._fast_path_rerun_requested: str | None` — F5: the DROPPED trigger label, or `None`.
- `self._fast_path_pending_dwell: dict[str, CALLBACK_TYPE]`
- `self._fast_path_followup_bucket: dict[str, collections.deque[datetime]]` — sliding-hour window for F1 cap.
- `self._fast_path_ceiling_bucket: dict[str, collections.deque[datetime]]` — sliding-hour window for F10.
- `self._fast_path_ceiling_tripped_until: dict[str, datetime]` — per-zone tick-only fallback until LOCAL midnight.
- `self._tearing_down: bool = False` — F6.
- Counters exposed on `sensor.ura_hvac_coordinator_status` (F14): `fast_path_triggers_total`, `fast_path_rate_limited_total`, `fast_path_global_rate_limited_total`, `fast_path_ceiling_gated_total`, `fast_path_ceiling_tripped_total`, `fast_path_skipped_reentrant_total`, `fast_path_boot_suppressed_total` (F15 unified), `fast_path_dwell_followups_scheduled_total`, `fast_path_dwell_followups_ran_total`, `fast_path_dwell_followups_coalesced_total`, `fast_path_dwell_followups_rate_capped_total` (F1), `fast_path_warm_zone_gated_total`. Plus `last_fast_path_edge_to_start_s: float | None` gauge (F14). Reset on daily rollover.

**Restart survival:** none of the pending dicts persist. Backstop = periodic tick.

**Discharge map (per "suppression needs a discharge"):**
- Per-zone `L` DENY: next periodic 5-min tick.
- Global `G` DENY: next periodic 5-min tick (~1/day, accepted).
- F10 ceiling: next LOCAL midnight OR restart (whichever first).
- Re-entrancy skip: trailing rerun in §4.5 (running with the DROPPED trigger label, F5).
- Boot-settle early-return: boot-settle kick (`hvac.py:1553`) + next periodic tick.
- F1 dwell-followup cap: next periodic 5-min tick.

### 4.4 Dwell-expiry follow-up — the MAIN hot-entry path (REV 4: F1 gated + capped, F7 popped)

**Placement:** the scheduler lives INSIDE `_apply_house_state_presets`, BEFORE the
`continue` at **hvac.py:2451** (F1). NOT in `_run_decision_cycle`.

**Gate (F1):** schedule ONLY when all of:
- The dwell skip is being taken (the existing `if` branch at :2442-2450).
- `effective_preset != zone.preset_mode` (the SKIP is blocking a real preset change).
- `should_change_preset(zone, effective_preset)` returns True (S1 would actually write if not dwell-blocked).
- No follow-up pending for Z (`Z not in self._fast_path_pending_dwell`).
- F1 rate cap: `len(followup_bucket[Z] within last 3600 s) < HVAC_FAST_PATH_DWELL_FOLLOWUPS_PER_ZONE_PER_HOUR` — else increment `fast_path_dwell_followups_rate_capped_total`, do NOT schedule.

**Schedule:**
```
remaining = (dwell_minutes * 60) - (now - zone.current_session_start).total_seconds()
delay = max(0.5, remaining + FAST_PATH_DWELL_SLACK_S)
origin_trigger = trigger  # capture the trigger that scheduled this (F8)
unsub = async_call_later(hass, delay, partial(self._fast_path_dwell_followup, zone_id, origin_trigger))
self._fast_path_pending_dwell[zone_id] = unsub
self._fast_path_followup_bucket[zone_id].append(now)
```

**Fire (F7):**
```
async def _fast_path_dwell_followup(self, zone_id, origin_trigger, _now):
    if self._tearing_down: return
    self._fast_path_pending_dwell.pop(zone_id, None)   # F7: pop BEFORE dispatch
    task = self.hass.async_create_task(
        self._async_decision_cycle(
            trigger="fast_path_dwell_followup",
            origin_zones={zone_id},
            _origin_trigger=origin_trigger,           # forwarded to preset_change row (F8)
        )
    )
    self._pending_tasks.add(task)                     # F6 rerun/tracking discipline
    task.add_done_callback(self._pending_tasks.discard)
```

**Follow-up exempt from BOTH L and G** (§4.3 rule): per-zone dedup + F1 cap already
bound volume; exemption recovers the 5/114 follow-up losses D0 §6.2 measured at DENY.

**F7 rearm:** because we pop the dict entry BEFORE dispatch, a subsequent dwell-skip on
the same zone (e.g. a second edge lands after the follow-up fires but before its next
periodic tick) can schedule a fresh follow-up. Test: `test_dwell_followup_rearms_after_fire`.

**Teardown-safe (F6):** cancelled from `_fast_path_pending_dwell` in `async_teardown`
BEFORE the first await; `_tearing_down` guards prevent late-arriving callbacks from
touching a torn-down coordinator.

### 4.5 Re-entrancy — trailing rerun (F5 + F6)

Today's guard at `hvac.py:1592-1598` DROPS the trigger. Rev-4 rule:

```
async def _async_decision_cycle(
    self, _now=None, *, trigger="periodic",
    origin_zones=None, _origin_trigger=None,
):
    if self._tearing_down: return                              # F6
    if not self._enabled: return
    if not self._boot_settle_done:
        self._fast_path_boot_suppressed_total += 1             # F15 unified
        return
    if self._decision_cycle_lock.locked():
        # F5: record the DROPPED trigger (periodic OR non-periodic), rerun as-that.
        self._fast_path_rerun_requested = trigger
        self._fast_path_skipped_reentrant_total += 1
        return
    async with self._decision_cycle_lock:
        await self._run_decision_cycle(
            trigger=trigger, origin_zones=origin_zones,
            _origin_trigger=_origin_trigger,
        )
        rerun_trigger = self._fast_path_rerun_requested
        if rerun_trigger:
            self._fast_path_rerun_requested = None
            # F6: rerun exempt from limiters + tracked in _pending_tasks.
            rerun_origin = origin_zones if rerun_trigger in {"fast_path","fast_path_dwell_followup"} else None
            task = self.hass.async_create_task(
                self._async_decision_cycle(trigger=rerun_trigger, origin_zones=rerun_origin)
            )
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
```

Stamping: `_run_decision_cycle` stamps `_fast_path_last_run_at[Z]` for each `Z ∈ origin_zones`
AND `_fast_path_last_run_at_any_zone` ONLY on entry, ONLY when `trigger ∈ {fast_path, fast_path_dwell_followup}`.

### 4.6 Handler pseudocode (F4 + F6 + F10 + F12 + F13)

```
def _on_room_occupancy_state_change(event):
    if self._tearing_down: return                              # F6
    entity_id = event.data["entity_id"]
    old = event.data.get("old_state"); new = event.data.get("new_state")
    if not (old and new and old.state == "off" and new.state == "on"): return
    room_name = self._room_name_by_entity.get(entity_id)
    if not room_name: return
    room_type = self._room_type_by_name.get(room_name)
    if room_type == ROOM_TYPE_HALLWAY: return
    zm = self._zone_manager
    zone_id = self._resolve_zone_live(room_name, zm)           # F12: read zm.zones live
    if not zone_id: return
    if zm._hvac_armed.get(room_name) is True: return
    zone = zm.zones.get(zone_id)
    if zone is None or zone.any_room_hvac_occupied:            # F4 (also handles missing)
        self._fast_path_warm_zone_gated_total += 1
        return
    if not self._boot_settle_done:
        self._fast_path_boot_suppressed_total += 1             # F15
        return
    now = dt_util.utcnow()
    if now < self._fast_path_ceiling_tripped_until.get(zone_id, dt.datetime.min.replace(tzinfo=dt.timezone.utc)):
        self._fast_path_ceiling_gated_total += 1               # F10 fallback active
        return
    if self._decision_cycle_lock.locked():                     # F5: ahead of DENY
        self._fast_path_rerun_requested = "fast_path"
        self._fast_path_skipped_reentrant_total += 1
        return
    last_z = self._fast_path_last_run_at.get(zone_id)
    if last_z and (now - last_z).total_seconds() < HVAC_FAST_PATH_MIN_INTERVAL_S:
        self._fast_path_rate_limited_total += 1
        return
    if self._fast_path_last_run_at_any_zone and \
       (now - self._fast_path_last_run_at_any_zone).total_seconds() < HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S:
        self._fast_path_global_rate_limited_total += 1
        return
    # F10 ceiling sample + breach check
    bucket = self._fast_path_ceiling_bucket.setdefault(zone_id, deque())
    bucket.append(now)
    _prune_older_than(bucket, now - dt.timedelta(hours=1))
    if len(bucket) > HVAC_FAST_PATH_MAX_PER_ZONE_PER_HOUR:
        self._fast_path_ceiling_tripped_total += 1
        self._fast_path_ceiling_tripped_until[zone_id] = _next_local_midnight_utc(now)
        _emit_nm_once(...)  # NM MED "fast-path rate ceiling tripped"
        return
    task = self.hass.async_create_task(
        self._async_decision_cycle(trigger="fast_path", origin_zones={zone_id})
    )
    self._pending_tasks.add(task)
    task.add_done_callback(self._pending_tasks.discard)
    # sensor gauge: t0 captured here; _run_decision_cycle records t1-t0 into
    # self._last_fast_path_edge_to_start_s (F14)
    self._pending_fast_path_start_times[zone_id] = now
```

Maps are rebuilt on `SIGNAL_ROOM_ENTRY_LIFECYCLE` (F13 — ONE subscription covers
options_updated too, verified against `signals.py:199` producers).

### 4.7 Count-coupled side effects — SKIP ONLY on {fast_path, fast_path_dwell_followup} (F3)

REV 4 clarification (F3): the skip set applies ONLY to
`trigger ∈ {fast_path, fast_path_dwell_followup}`. `periodic`, `house_state`,
`pre_arrival`, boot-kick (`hvac.py:1553` — invoked with default `trigger="periodic"`),
setup initial cycle (`hvac.py:1372` — same) all stay periodic-classified and run the
full site list. Reviewer B verifies this table against merged `develop` at build dispatch.

| Site (file:line, F11-refreshed) | Count-coupled OR time-based | REV 4 disposition on {fast_path, fast_path_dwell_followup} |
|---|---|---|
| `_check_carrier_freshness` (`hvac.py:1670`) | Time-based | Run — safe. |
| `update_room_conditions` (`hvac.py:1656`, `hvac_zones.py:523`) | Time-based; iterates ALL rooms (no per-zone entry point) | Run — F2 producer-drift-accepted: sibling-zone tail/session state is refreshed at fast-path cadence, drift ≤ 300 s vs a "producer only on tick" world. |
| `_egress_manager.async_tick(now)` (`hvac.py:1696`) | Time-based | Run. |
| `_predictor.update` (`hvac.py:1784`) — banking / pre-cool / pre-heat | **COUNT-COUPLED + event payload** (F3 definitive) | **SKIP.** Extra samples pollute schedule reads AND fire event payloads off-cadence. |
| `_fan_controller.update(constraint, house_state)` (`hvac.py:1764`) | Time-based | Run. Under zone-cold gate, warm-zone rising edges don't fire the fast path at all, so warm-edge fan-in falls back to periodic tick (median wait 142–181 s per D0 §3.1) — same as today. Escape hatch = card `HVAC-FAST-PATH-FAN-WARM-EDGES-1`. |
| `_cover_controller.update` (`hvac.py:1767`) | Time-based | Run. |
| `_override_arrester.check_ac_reset` (`hvac.py:1760`) → `hvac_override.py:3805-3815` `kwh_samples_above_threshold += 1` | **COUNT-COUPLED** | **SKIP.** Extra call inflates sample counter, tripping nudge debounce early. |
| `_override_arrester` per-zone override detection | Contains own suppression window (C17: 5 s temp / 120 s preset), event-driven internally | Run. |
| Anomaly `record_observation` (F15: correct method) at `hvac.py:1783` | **COUNT-COUPLED** | **SKIP.** Extra samples pollute baselines. |
| `_emit_and_reset_short_cycles` daily rollover (`hvac.py:1643`) | Time-based (LOCAL-day hinge) | Run. |
| `_predictor.flush_daily_outcome` (`hvac.py:1610`) | Time-based (daily hinge) | Run. |
| Row-1 / row-4 / row-10 / D5 / D6 / D7 / D9 / F4 preset & retreat evaluation | Time-based (reads current state) | Evaluated FOR ALL ZONES (producer-drift F2). |
| S1 preset-write loop `_apply_house_state_presets` at :2013+ | Event-driven writes | **F2 origin-gate:** WRITES only for zones in `origin_zones`; other zones are evaluated read-only (compute `effective_preset` but skip `emit_set_preset_mode` / `emit_set_temperature`). |
| Zone-dwell skip at `hvac.py:2451` (F11) | Time-based | Runs FOR ALL ZONES; the F1 follow-up scheduler sits just before this `continue` and fires only for origin zones (zones ∉ origin have no fast-path follow-up scheduled by a fast-path cycle — the periodic tick that hit dwell schedules them if needed). |
| `preset_change` activity-log write (`hvac.py:2716-2748`) | Event-driven (only fires on actual change) | Run; add `trigger` (F14 threaded to the write, not just to a counter) AND `origin_trigger` for follow-ups (F8) to details dict. |

**Implementation shape:** `_run_decision_cycle(trigger, origin_zones, _origin_trigger)`
receives the args. Each SKIP-on-fast-path guard: `if trigger not in FAST_PATH_TRIGGERS:`
where `FAST_PATH_TRIGGERS = frozenset({"fast_path","fast_path_dwell_followup"})`.
Behaviour-neutrality for periodic ticks: byte-identical (all args default to
`trigger="periodic"`, `origin_zones=None`, `_origin_trigger=None`).

### 4.8 Coexistence

- Boot-kick (`hvac.py:1553`) + setup (`hvac.py:1372`): call `_async_decision_cycle()` with defaults → classified `periodic` per F3.
- House-state / pre-arrival: pass `trigger="house_state"` / `"pre_arrival"` explicitly for observability, but F3 classifies them periodic (they RUN the full site list).
- Egress initial-restore gate: unaffected.
- `SIGNAL_ZM_ZONES_UPDATED`: unaffected.
- Carrier post-write guard (C16) × arrester preset-suppression (C17 120 s): unchanged — no new preset writes.

---

## 5. Deliverables

### D0 — Empirical probe (READ-ONLY, gate) — DONE 2026-09-26
- **DONE:** per-zone trigger-eligible + zone-cold + burst + gap stats (AUDIT §2/§3.1/§3.2).
- **DONE:** cycle-duration proxy (AUDIT §5).
- **PENDING (audit §7, F9 corrected query):** pre-W2-1 per-zone `climate_write` rows/day baseline — earliest 2026-09-27 15:25 CDT; margin computed over **≥ 3** full days; attributable criterion added (F9).
- **DONE:** sizing (§REV 4 DELTA / §4.3 constants).

### D1 — Constants, state, `trigger`+`origin_zones` threading, count-coupled skips
Add all six constants at sized values; add state fields (F5 `_fast_path_rerun_requested`
as `str | None`; F6 `_tearing_down`; F1/F10 sliding-window deques + tripped-until dict;
F14 `last_fast_path_edge_to_start_s`); thread `trigger` AND `origin_zones` AND
`_origin_trigger` through `_async_decision_cycle` and `_run_decision_cycle`; add the
count-coupled skip guards per §4.7 (F3-narrowed). Put `trigger` INTO the write path at
`hvac.py:2716-2748` (F14).

**Wire-in anchors (F15: neuter the RETURN in drills, not just the CALL):**
- `test_run_decision_cycle_trigger_defaults_periodic` — call sites without kwargs default to `"periodic"` + `origin_zones=None`.
- `test_fast_path_skips_check_ac_reset_sample_increment` — mutation drill: replace `return` with `pass` on the guard → test FAILS.
- `test_fast_path_skips_predictor_update` — F3: predictor SKIP verified; mutation drill.
- `test_fast_path_skips_anomaly_record_observation` — F15: correct method name; spy the coordinator's `AnomalyDetector.record_observation`; assert 0 calls.
- `test_periodic_cycle_call_sequence_unchanged` (F15 replaces byte-identical) — record ordered list of major call sites under `trigger="periodic"` before and after patch; assert equivalence.
- `test_preset_change_activity_log_carries_trigger_and_origin_trigger` (F14/F8) — trigger on the row, origin_trigger for follow-ups.
- `test_boot_kick_and_setup_are_periodic_class` (F3) — invocation from `hvac.py:1553` and `:1372` runs the full site list.

**Acceptance:**
- **Verify:** count-coupled skip table (§4.7) has a matching guard per row.
- **Live:** `ura_activity_log preset_change` rows carry `trigger` (and follow-ups `origin_trigger`) within 24 h.

### D2 — Fast-path trigger wiring (rising edge, hallway-excluded, armed-gated, ZONE-COLD, DENY, F10 ceiling)
Register `async_track_state_change_event` on the filtered set at `async_setup` between
`hvac.py:1254` and `:1355`. Single unsub on `self._fast_path_state_unsub`. Subscribe to
ONE `SIGNAL_ROOM_ENTRY_LIFECYCLE` (F13 — covers options_updated). Implement §4.1
gates 1-11 (F4 fused, F5 order, F10 ceiling).

**Wire-in anchors (mutation drills required — Tier 2-DB C-framing):**
- `test_fast_path_registered_at_setup_with_filtered_entities` — neuter drill.
- `test_fast_path_rebuilds_on_lifecycle_signal_no_double_unsub` — helpers/event.py:441-447 shape asserted RED under regression.
- `test_fast_path_hallway_excluded_at_event_time` — behavioural.
- `test_fast_path_skips_when_hvac_armed_already` — gate 4.
- `test_fast_path_skips_when_zone_warm_via_fused_signal` (F4) — sets `zone.any_room_hvac_occupied = True`, asserts no cycle + counter increment; mutation drill.
- `test_fast_path_falling_edge_ignored`.
- `test_fast_path_unknown_unavailable_ignored`.
- `test_fast_path_skips_room_in_no_hvac_zone`.
- `test_fast_path_global_limiter_denies_and_next_tick_recovers` — DENY + backstop cycle picks up the zone.
- `test_fast_path_lock_gate_ahead_of_global_deny` (F5) — hold lock + set global stamp in-window → rerun requested with the ORIGINAL trigger label (not silently swallowed by DENY).
- `test_periodic_tick_that_hits_lock_sets_rerun_periodic` (F5) — periodic cycle dropped by lock → trailing rerun runs as `periodic`.
- `test_fast_path_ceiling_trip_falls_back_to_tick_only` (F10) — 16 edges in an hour → one NM + subsequent edges gated + counter increments; state clears at LOCAL midnight.
- `test_zone_manager_zones_read_live` (F12) — mutate `zm.zones` between subscribe and dispatch; new zone recognised without a lifecycle rebuild.

**Acceptance:**
- **Test:** all wire-in tests pass with mutation drills (neuter the RETURN).
- **Live:** `fast_path_triggers_total > 0` within 24 h; `fast_path_warm_zone_gated_total > 0` within 24 h; `fast_path_global_rate_limited_total ≤ 3/day` on average (revival trigger for parked DEFER, §7); `fast_path_ceiling_tripped_total == 0` in steady state; `last_fast_path_edge_to_start_s` populated on `sensor.ura_hvac_coordinator_status` (F14).

### D3 — Dwell-expiry follow-up (MAIN hot-entry path — F1 gated + F7 popped + F8 tagged)
Implement §4.4: gate on `effective_preset != zone.preset_mode` AND
`should_change_preset()` allow AND rate cap. Place BEFORE `continue` at `hvac.py:2451`.
Per-zone dedup dict; unsubs cancelled from that dict in `async_teardown` BEFORE first
await (F6). Follow-up dispatch POPS its dict entry BEFORE `async_create_task` (F7).
`origin_trigger` forwarded (F8).

**Wire-in anchors:**
- `test_dwell_skip_schedules_followup_only_when_preset_would_change` (F1) — parametrised: (a) `effective_preset == zone.preset_mode` → no follow-up; (b) `should_change_preset` returns False → no follow-up; (c) both allow → follow-up scheduled. Mutation drill neuters the gate → suite RED.
- `test_dwell_followup_rate_cap` (F1) — inject 7 dwell-skips within 1 h → 6 scheduled, 7th capped + counter increments.
- `test_dwell_skip_schedules_followup_regardless_of_trigger` (`trigger ∈ {"periodic","fast_path","house_state"}` all schedule when F1 gate passes).
- `test_dwell_followup_exempt_from_per_zone_limiter`.
- `test_dwell_followup_exempt_from_global_limiter` — stamp `_fast_path_last_run_at_any_zone` recently; assert follow-up still runs; mutation drill.
- `test_dwell_followup_deduplicated_per_zone` — two dwell skips → one follow-up.
- `test_dwell_followup_rearms_after_fire` (F7) — follow-up fires, dict entry popped; a subsequent dwell-skip on the same zone SCHEDULES a fresh follow-up.
- `test_dwell_followup_cancelled_on_teardown` — `async_unload` cancels BEFORE first await (F6).
- `test_dwell_followup_writes_preset_with_origin_trigger` (F8) — end-to-end: hot-entry fixture → follow-up fires → `preset_change` row has `trigger="fast_path_dwell_followup"` AND `origin_trigger="fast_path"`.

**Acceptance (F8, F9):**
- **Verify (D0 baseline):** today's zone-cold hot-entry edge→`preset_change` p50 = 300-600 s (C18).
- **Verify (post-fix discriminator, F8):**
  - `p90(edge → preset_change ts) ≤ hvac_zone_entry_dwell_live_seconds + FAST_PATH_DWELL_SLACK_S + HVAC_FAST_PATH_SLA_S` — dwell read LIVE from `number.ura_hvac_coordinator_zone_entry_dwell` (current 120 s → target ≈ 167 s).
  - AND ≥ 90 % of zone-cold entries have `origin_trigger="fast_path"` in the details dict.
- **Live (write-rate acceptance, F9):** per-zone `climate_write` rows/day ≤ pre-W2-1 baseline (≥ 3 full days) + margin. **Attributable criterion (F9): fast-path-attributable `preset_change` rows/day (rows with `origin_trigger="fast_path"`) ≤ zone-cold edges/day (D0 §2 per zone).** If the fast path is writing more preset-changes than zone-cold edges exist, something is wrong (likely origin_zones threading bug or F7 rearm loop).

Baseline query (F9 corrected):
```
SELECT date(timestamp, 'unixepoch', 'localtime') AS d,
       json_extract(details_json, '$.zone_id')  AS zone,
       json_extract(details_json, '$.verb')     AS verb,
       COUNT(*) AS n
FROM ura_activity_log
WHERE action = 'climate_write' AND timestamp >= ?
GROUP BY d, zone, verb ORDER BY d, zone, verb;
```

### D4 — Teardown, reload-storm safety, storm trip-wire (F6 + F10)
- `async_teardown` sets `self._tearing_down = True` synchronously, DRAINS `_fast_path_state_unsub` and every `_fast_path_pending_dwell[Z]` BEFORE any await (F6).
- Handler + follow-up + rerun all check `_tearing_down` and return early (F6).
- `SIGNAL_ROOM_ENTRY_LIFECYCLE` handler idempotent: release-then-reassign.
- `AnomalyDetector.record_observation` (F15 correct method) with `fast_path_trigger_rate` metric per-zone LOCAL-day bucket. Storm trip-wire = anomaly → single NM.
- F10 in-code hard ceiling: separate from storm-trip anomaly; deterministic (`HVAC_FAST_PATH_MAX_PER_ZONE_PER_HOUR = 15`); on breach one NM + tick-only fallback until midnight.

**Wire-in anchors:**
- `test_reload_storm_no_duplicate_dispatch` — 5 rapid lifecycle signals → exactly one active listener set.
- `test_fast_path_no_op_during_boot_settle` — trigger with `_boot_settle_done=False`; no cycle, `_fast_path_boot_suppressed_total` (F15) increments, last_run NOT stamped.
- `test_tearing_down_guards_all_paths` (F6) — set `_tearing_down=True`; dispatch edge, fire pending follow-up, request rerun; assert none reach `_async_decision_cycle`.
- `test_teardown_drains_before_await` (F6) — patch `_fast_path_pending_dwell` with a spy unsub; `async_teardown` must call unsub BEFORE it awaits anything.
- `test_storm_trip_wire_fires_once_at_threshold`.
- `test_ceiling_fallback_lifts_at_local_midnight` (F10).

**Acceptance:**
- **Live:** no `RuntimeError` in logs referencing fast-path; storm trip-wire silent in first hour; ceiling never trips in steady state.

---

## 6. Open operator question

**Q1 — Per-zone vs whole-house cycle.** CLOSED. F2 origin-gate keeps sibling-zone WRITES
unaffected; producer runs for all zones (accepted drift ≤ 1 tick — see §REV 4 DELTA F2).
Expected load ~32 non-periodic cycles/day + 288 periodic ticks (+11 %).

No other open questions.

---

## 7. Non-goals + PARKED alternatives

- No dwell / tail / grace / hallway-exclusion / retreat semantics change.
- No falling-edge fast path.
- No new preset/setpoint write sites.
- No producer refactor (`_compute_hvac_occupied` stays as-is; runs all zones on non-periodic per F2).
- No operator UI knob for the limiter.
- **No new sensor** — counters + `last_fast_path_edge_to_start_s` gauge land on the existing `sensor.ura_hvac_coordinator_status` (F14).
- **No new per-cycle DB writer** — `trigger` / `origin_trigger` piggy-back on the existing `preset_change` activity-log row (F14/F8).
- **No per-denial NM** — storm trip-wire (AnomalyDetector) + F10 in-code ceiling only.
- **No Nest / other-brand strategy changes** — W1-B territory.
- *No warm-zone triggers (§4.1 gate 5 / F4) — an edge in a zone whose fused signal is True does NOT fire.*
- *No dedicated fan-only fast path in this cycle — escape hatch card `HVAC-FAST-PATH-FAN-WARM-EDGES-1` (minted 2026-09-26).*

### PARKED alternative — Global-limiter DEFER (REV 3, not built)

An earlier REV 3 draft proposed deferring globally-limited triggers via
`async_call_later(G - elapsed_s)`. Orchestrator decision 2026-09-26: DENY + tick backstop
wins on marginal-benefit grounds (~1/day recovered vs a new timer/dict/discharge surface).

- **Revival trigger:** `fast_path_global_rate_limited_total` per-zone `> 3/day` on a 7-day rolling avg, OR a denied cold edge coincides with a comfort complaint traceable to the delay.
- **Revival evaluation query (recorder/ura DB):**
  ```
  SELECT date(day_ts, 'unixepoch', 'localtime') AS d,
         zone,
         AVG(denies) OVER (PARTITION BY zone ORDER BY day_ts
                           ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS rolling_7d_avg
  FROM (
    SELECT day_ts, zone, MAX(counter_value) - MIN(counter_value) AS denies
    FROM sensor_history
    WHERE entity_id = 'sensor.ura_hvac_coordinator_status'
      AND attr = 'fast_path_global_rate_limited_total'
    GROUP BY day_ts, zone
  );
  ```
  (Or the daily-snapshot table if we start recording one; the counter attribute is the primary source.)
- **Design carrier:** this planning doc's git history — the DEFER draft state is retrievable from a prior revision. No card until revival.

---

## 8. Tier + review framings

**Tier 2-DB (three framing-disjoint reviews + live validation + README write-back).**

**Framings:**
- **A — Local correctness + limiter arithmetic + rising-edge classification.** Per-zone stamp discipline; trailing-rerun idempotence with the DROPPED-trigger label (F5); per-zone L + global G DENY arithmetic; F4 fused-signal read correctness; follow-up exemption from both L and G; F1 rate cap; F10 ceiling arithmetic + LOCAL-midnight clear; F14 gauge population.
- **B — Integration + decision-cycle integrity + count-coupled classification + origin-zones scope.** Verify §4.7 table against merged `develop`; verify `trigger` + `origin_zones` thread reaches EVERY affected site (S1 write loop, preset_change details, boot-kick / setup / house-state / pre-arrival stay periodic per F3); verify F2 sibling-zone read-only behaviour (no `emit_*` calls issued for zones ∉ origin_zones); verify Carrier cloud bound holds against W1-A per-zone write-rate baseline (F9, PENDING); C16/C17 interactions still no-op; DENY tick-backstop actually processes a denied zone-cold edge; F10 fallback lifts.
- **C — Test authority via real per-site mutation.** Neuter the RETURN (not just the CALL, F15) of: state-change registration, F4 fused-signal gate, F5 lock-ahead-of-DENY order, per-zone L, global G DENY (counter + return), F10 ceiling (all three transitions: sample append, breach check, tripped-until stamp), count-coupled skip guards, origin_zones write skip in S1 loop, F1 dwell-follow-up gate + rate cap, follow-up exemption from L and G, F6 tearing-down guards on every path, F13 single subscription. Each mutation MUST turn a SPECIFIC test RED; no aggregate monkeypatch. Confirm no `.pyc` staleness.

**Reviewer D (adversarial completeness):** re-enumerate every count-coupled site in
`_run_decision_cycle`; every downstream reader of the counters/sensors; every place a
race on `zone.any_room_hvac_occupied` could yield a wrong classification; every legal
config where a zone-cold edge could silently DROP (must always land on the periodic
tick within 300 s + dwell); every path where `_tearing_down` guards might be missing
(F6); every place the F1 gate could be evaluated against stale state.

**Plan review (mandatory):** ONE adversarial plan review before build dispatch — re-run
§1.1 greps, re-derive §4.7 table, verify §REV 4 DELTA numbers, verify the F9 query is
executable against the live schema, verify F1/F10 rung + values against the ladder.

**Sequencing gate:** merge only after `feature/hvac-live-room-establishment` on
`develop` AND W1-A live ≥ **3** days (F9 margin rule) — earliest 2026-09-30 for build
dispatch on the baseline.

### 8b. What the builder will most likely get wrong (reviewer's list)

Include in the builder brief. These are the specific traps this plan sets:

1. **Threading `origin_zones` only into `_async_decision_cycle` but not into `_run_decision_cycle` and NOT into the S1 write loop.** The point of F2 is the write skip inside `_apply_house_state_presets` at zone iteration; the plumbing job isn't done until an `if origin_zones is not None and zone_id not in origin_zones: continue` sits inside that loop with a wire-in test that fails-red when removed.
2. **Putting the F1 dwell-followup scheduler in `_run_decision_cycle` instead of inside `_apply_house_state_presets` before `continue` at hvac.py:2451.** Only inside the S1 loop do you know both `effective_preset` and the `should_change_preset` verdict; scheduling in the outer cycle either duplicates that logic or schedules unnecessarily.
3. **Assuming `SIGNAL_ROOM_ENTRY_LIFECYCLE` won't fire for options_updated** and adding a second subscription — resulting in double-rebuild storms on every options change. F13: ONE subscription; verify at build dispatch that URA's options-updated handler re-emits the lifecycle signal.
4. **Reading `self._room_name_by_entity` inside the handler but caching `zone_id` at rebuild time.** F12: `zm.zones` must be read LIVE at event time, not snapshotted at listener rebuild.
5. **F5 gate ordering:** putting the lock/rerun check AFTER global DENY, so a periodic cycle that hits the lock gets swallowed by DENY on the next attempt. Order matters: lock → per-zone L → global G.
6. **F7: forgetting to `pop` the pending-dict entry before dispatching the follow-up**, so a rearm looks like "already pending" and gets coalesced away. Test `test_dwell_followup_rearms_after_fire` catches this.
7. **F14: threading `trigger` into a counter but not into the `preset_change` details dict.** The Live D3 discriminator NEEDS the trigger label on the DB row, not on an in-memory attribute.
8. **F6: cancelling the pending dwell dict AFTER an await in `async_teardown`.** Any timer that fires during that await can dispatch a cycle against a partially-torn coordinator. Drain BEFORE the first await; use `_tearing_down` as the belt.
9. **F3: adding the count-coupled skip to `house_state` / `pre_arrival` triggers** (which are periodic-classified per REV 4). Those triggers SHOULD run the full site list; a hasty union of "everything not periodic" is the wrong classification.
10. **F10: emitting the NM inside the F10 breach path per-event (loud) instead of latch-once-per-trip** (with a manual reset only via LOCAL midnight or restart). The `_emit_nm_once` helper must dedup per `(zone_id, trip_ts)`.

---

## 9. Sequencing + overlap flag (v5.103.15)

Do not dispatch build until:
1. `feature/hvac-live-room-establishment` (v5.103.15) merges to `develop`.
2. W1-A live ≥ **3** days (F9 margin) — earliest 2026-09-30 15:25 CDT.

Overlapping regions in `hvac.py` (refresh at dispatch per F11): subscribe block
:1131-1213; `_async_decision_cycle` :1564-1598; `_run_decision_cycle` :1600-1789 (S1
loop inside `_apply_house_state_presets` :2013+, dwell-skip continue :2451). At
dispatch, re-verify §1.1 REUSE line numbers.

---

## 10. Knobs on the ladder

| Number | Value | Rung | Why |
|---|---|---|---|
| `HVAC_FAST_PATH_MIN_INTERVAL_S` | 60 | 1 (module const) | Cloud-call-rate protective. D0 §6.1: 0/114 zone-cold denied at any L ≤ 300 s. |
| `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` | 20 | 1 (module const) | House-wide floor; DENY + tick backstop; ~1 zone-cold edge/day discharged by next tick. |
| `HVAC_FAST_PATH_SLA_S` | 45 | 1 (module const) | Test/observability target. Comment MUST note proxy method + absolute-duration unmeasured. Live consumer: `last_fast_path_edge_to_start_s` on `sensor.ura_hvac_coordinator_status` (F14). |
| `FAST_PATH_DWELL_SLACK_S` | 2 | 1 (module const) | Wall-clock slack past dwell edge. |
| `HVAC_FAST_PATH_DWELL_FOLLOWUPS_PER_ZONE_PER_HOUR` | 6 | 1 (module const) | F1 per-zone dwell-follow-up cap. ~1 per 10 min per zone; well above D0 zone-cold rate. |
| `HVAC_FAST_PATH_MAX_PER_ZONE_PER_HOUR` | 15 | 1 (module const) | F10 hard ceiling / kill-switch. On breach: one NM + tick-only fallback for that zone until LOCAL midnight. |

**Kill-switch:** F10 hard ceiling degrades a runaway zone to today's tick-only behaviour.
Full-cycle kill-switch: subscription failure at boot → warning log + one NM LOW; fast path
degrades to 5–10 min hot entry per C18.

---

## 11. Producer / Consumer map (REV 4)

**PRODUCER of the "fast-path trigger" value:** HA `state_changed` events for
`binary_sensor.{entry_id}_occupied` (registry-resolved). Source health = URA room
coordinator's STATE_OCCUPIED write path. Failures collapse to periodic tick.

**CONSUMERS + call-sites:**
- `HVACCoordinator._async_decision_cycle(trigger="fast_path", origin_zones={Z})` → `_run_decision_cycle(trigger, origin_zones)` — sole trust-consumer. Count-coupled sites SKIPPED per §4.7 F3-narrowed; S1 write loop restricted to origin zones per F2.
- `_fast_path_dwell_followup(Z, origin_trigger)` (D3) — time-shifted trust-consumer; re-enters `_async_decision_cycle(trigger="fast_path_dwell_followup", origin_zones={Z}, _origin_trigger=origin_trigger)`. Exempt from both limiters (§4.4).
- Periodic-tick backstop for global-DENY, per-zone L DENY, F10 ceiling-fallback: `_async_decision_cycle(trigger="periodic")` picks up the zone on the next tick.
- Existing `preset_change` activity-log row — `trigger` + `origin_trigger` in details (F14, F8) — D3 acceptance oracle.
- `sensor.ura_hvac_coordinator_status` — counters + `last_fast_path_edge_to_start_s` gauge (F14).
- `AnomalyDetector.record_observation` `fast_path_trigger_rate` (F15) — storm trip-wire.

**No new trust downstream.** The plan changes WHEN cycles run and PARTIALLY WHAT they
run (F2 write scope + F3 count-coupled skip).

---

## Appendix A — INV restated for reviewer D

> Under normal steady-state operation (boot-settle released, no active reload storm,
> W1-A live), for every HVAC-occupancy rising edge on a live non-hallway room R in an
> HVAC zone Z where `zm._hvac_armed[R]` is not already True AND
> `zone.any_room_hvac_occupied is False` (zone-cold, F4):
>
> 1. A `_run_decision_cycle(trigger="fast_path", origin_zones={Z})` STARTS within
>    `HVAC_FAST_PATH_SLA_S` seconds unless denied by the per-zone or global limiter, or
>    gated by the F10 hard ceiling. A DENIED zone-cold edge is discharged by the NEXT
>    periodic 5-min tick.
> 2. If that cycle takes the dwell-skip branch at `hvac.py:2451` AND
>    `effective_preset != zone.preset_mode` AND `should_change_preset` allows the
>    write, a follow-up `_run_decision_cycle(trigger="fast_path_dwell_followup",
>    origin_zones={Z})` runs at
>    `zone.current_session_start + hvac_zone_entry_dwell_live_seconds +
>    FAST_PATH_DWELL_SLACK_S`, exempt from both limiters, per-zone dedup'd, and
>    subject to `HVAC_FAST_PATH_DWELL_FOLLOWUPS_PER_ZONE_PER_HOUR`.
> 3. On any `trigger ∈ {fast_path, fast_path_dwell_followup}`: (a) the producer
>    (`update_room_conditions`) runs for ALL zones (drift ≤ HVAC_DECISION_TICK, same
>    envelope siblings live in today); (b) the S1 preset-write loop skips zones ∉
>    origin_zones, so their preset/setpoint/mode WRITES are identical to what a
>    periodic tick at the same wallclock would produce; (c) the count-coupled sites in
>    §4.7 are SKIPPED. Other triggers (`periodic`, `house_state`, `pre_arrival`,
>    boot-kick, setup) are `origin_zones=None` and run the full site list (F3).
> 4. `_fast_path_last_run_at[Z]` and `_fast_path_last_run_at_any_zone` are stamped
>    ONLY when a cycle actually runs (not on denials, boot-settle early returns, F10
>    ceiling gating, or re-entrancy skips — which set `_fast_path_rerun_requested` to
>    the DROPPED trigger label, F5).
> 5. `async_teardown` DRAINS `self._fast_path_state_unsub` and every entry of
>    `self._fast_path_pending_dwell` BEFORE its first await. Handler, follow-up
>    callback, and rerun scheduler each check `self._tearing_down` and return
>    immediately if set (F6).
> 6. Hot-entry latency: p90(zone-cold edge → `preset_change` row with
>    `origin_trigger="fast_path"`) ≤ `hvac_zone_entry_dwell_live_seconds +
>    FAST_PATH_DWELL_SLACK_S + HVAC_FAST_PATH_SLA_S` (F8); ≥ 90 % of zone-cold entries
>    carry `origin_trigger="fast_path"`.
>
> A legal-config, recorder-reachable violation of ANY conjunct falsifies INV.

---

## Rev 4 change log — plan-review-driven (F1–F15)

| # | Finding | Fold |
|---|---|---|
| F1 | HIGH — gate dwell follow-up on real preset change; add per-zone cap; place inside `_apply_house_state_presets` before `continue` at hvac.py:2451 | §REV 4 DELTA F1; §4.4 gate + rate cap; §5 D3 wire-in `test_dwell_skip_schedules_followup_only_when_preset_would_change`, `test_dwell_followup_rate_cap`; §10 knob; §11 producer/consumer |
| F2 | HIGH — origin_zones param, S1 write loop restricted to origin; producer runs for all zones with bounded drift; INV rewritten truthfully | §REV 4 DELTA F2; §2 INV conjunct (3); §4.5 pseudocode; §4.6 handler `origin_zones={zone_id}`; §4.7 S1 row; §5 D1 threading; §8 framing B; Appendix A |
| F3 | HIGH — §4.7 skip set = {fast_path, fast_path_dwell_followup} only; house_state / pre_arrival / boot kick / setup remain periodic-classified; predictor = COUNT-COUPLED + event payload | §REV 4 DELTA F3; §4.7 predictor row + implementation shape; §4.8 coexistence; §5 D1 `test_boot_kick_and_setup_are_periodic_class`, `test_fast_path_skips_predictor_update` |
| F4 | Zone-cold gate uses `zone.any_room_hvac_occupied`; race-freedom argument | §4.1 gate 5; §4.6 handler; §REV 4 DELTA F4 race argument; §5 D2 `test_fast_path_skips_when_zone_warm_via_fused_signal` |
| F5 | Periodic ticks that hit lock ALSO set rerun; lock/rerun gate AHEAD of global DENY; rerun replays with the DROPPED trigger label | §4.1 gate 8 order; §4.5 pseudocode; §REV 4 DELTA F5; §5 D2 `test_periodic_tick_that_hits_lock_sets_rerun_periodic`, `test_fast_path_lock_gate_ahead_of_global_deny` |
| F6 | origin_zones threading; rerun exempt + tracked in _pending_tasks; `_tearing_down` flag on all paths; teardown DRAINS BEFORE first await | §4.1 gate 1; §4.5 pseudocode; §4.6 handler; §5 D4 `test_tearing_down_guards_all_paths`, `test_teardown_drains_before_await` |
| F7 | Follow-up pops its dict entry BEFORE dispatch; rearm test | §4.4 fire pseudocode; §5 D3 `test_dwell_followup_rearms_after_fire` |
| F8 | Follow-up rows carry `origin_trigger`; D3 pass uses LIVE dwell + ≥ 90 % origin_trigger | §REV 4 DELTA F8; §2 INV conjunct (6); §4.4 origin_trigger forwarding; §5 D3 acceptance; Appendix A |
| F9 | Corrected query (details_json, zone column, per-day grouping); ≥ 3-day margin; attributable criterion | §REV 4 DELTA F9; §5 D0 acceptance; §5 D3 acceptance + baseline query; §8 sequencing gate; §9 note |
| F10 | Hard ceiling `HVAC_FAST_PATH_MAX_PER_ZONE_PER_HOUR = 15` + NM + tick-only fallback until midnight; parked-DEFER revival query | §REV 4 DELTA F10; §4.1 gate 7/11; §4.3 state; §5 D2/D4 wire-in; §7 parked DEFER query; §10 knob |
| F11 | Refresh file:line citations against develop @ c1c555291 (dwell `continue` at hvac.py:2451; boot kick :1553; setup :1372; check_ac_reset :1760; fan :1764; predictor :1784) | §1.4 code locations; §4.7 table; §4.4 placement note; §9 overlap |
| F12 | Read `zm.zones` live (not cached at listener rebuild) | §4.6 handler; §5 D2 `test_zone_manager_zones_read_live` |
| F13 | ONE `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription (covers options_updated) | §1.1; §4.6 note; §5 D2 wire-in (single subscription) |
| F14 | Thread `trigger` to the preset_change write; give SLA a consumer via `last_fast_path_edge_to_start_s` on `sensor.ura_hvac_coordinator_status`; unify boot-suppressed counter name; fix rerun arithmetic to ~1.5/day | §REV 4 DELTA F14; §4.3 state; §4.6 handler; §5 D1 `test_preset_change_activity_log_carries_trigger_and_origin_trigger`; §7 sensor name; §10 SLA row |
| F15 | `AnomalyDetector.record_observation` (not observe); mutation drills neuter the RETURN; replace byte-identical test with call-sequence test | §4.7 anomaly row; §5 D1 wire-in tests; §8 framing C |

## Rev 3 change log — audit-driven + orchestrator decision (retained)

See docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md + this doc's REV 3 body
(previous revisions). Highlights: zone-cold gate; DENY global limiter + follow-up
exemption; constants sized 60/20/45/2.

## Rev 2 change log — findings 1-12 (retained)

See prior revisions for the full 12-row table.
