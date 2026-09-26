# PLANNING — W2 HVAC Occupancy Fast Path (shave the 5-min tick) — REV 2

**Card:** `HVAC-W2-OCCUPANCY-TRUTH` (child: `HVAC-HOT-ENTRY-LATENCY-1`).
**Workstream:** W2 (Occupancy Truth), operator-approved 4-workstream HVAC arc.
**Design origin:** commit `82620357a`; prior context `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` + `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`.
**Operator scope (binding, §9d):** *"shave the 5-min tick only for now."* NO dwell / hold / grace / tail / override / retreat-semantics change; whole-house cycle preserved.
**Sequencing:** BUILD AFTER `feature/hvac-live-room-establishment` (v5.103.15) merges AND AFTER W1-A has been live ≥ 1 day (needed for the empirical write-rate baseline the limiter acceptance depends on — see §8 + §5.D0).

REV 2 folds FIX-PLAN-FIRST review findings 1-12 in place. Change log at bottom.

---

## 0. MANDATORY READ CONFIRMATION

Planner re-read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely including the new **C16 (Carrier 30-min schedule + 120-min reconcile + 5-min post-write guard, ha_carrier/const.py:46-59)**, **C17 (two suppression windows: `SUPPRESS_TTL_SECONDS=5` for temperature, `SUPPRESS_TTL_SECONDS_PRESET=120` for preset — `hvac_override.py:129`, `:141-146`, `:153`)**, and **C18 (hot-entry latency is 5-10 min, not ~7: the observing tick STARTS the dwell clock via `hvac_zones.py:714-716` and always skips at `hvac.py:2362-2365`; the preset write lands on the NEXT tick)**. C6 amendment aligned. The integration doc `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §9 (Carrier post-write guard × URA suppression interaction) is UNVERIFIED per C16 and out of scope for this plan.

**C18 reframes this whole design.** The dwell-expiry follow-up is NOT a corner case; it is the main hot-entry path (§4.4, §5.D3).

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
| Global min-interval between non-periodic cycles | **NEW module const** | `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` (finding 8) — house-wide floor between any two non-periodic cycles regardless of zone. |
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
- W1-A plan (naming per §11 arc) — sequenced BEFORE this cycle for the write-rate baseline

### 1.3 Memory + design docs read

- `feedback_wire_in_anchor_mandatory.md`, `feedback_suppression_needs_discharge.md`, `feedback_measure_before_build.md`, `feedback_marginal_benefit_pushback.md`, `feedback_tier2plus_prior_art_scan.md`, `feedback_mutation_verification_pycache_staleness.md`, `feedback_falsify_before_asserting.md`, `project_reload_storm_refuted_restart_storm_live.md`, `project_incident_v5_8_0_setup_recursion.md`.
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (C16-C18 folded — see §0).

### 1.4 Code locations surveyed

- `hvac.py`: subscribe block :1131-1213; periodic timer :1355-1363; boot-settle :1510-1552; `_async_decision_cycle` :1564-1598 (re-entrancy guard :1592, boot-settle early-return :1580); `_run_decision_cycle` :1600-1700; `_check_carrier_freshness` :1649; anomaly observations :1783; zone dwell :2355-2368; preset_change activity-log :2716-2748; `_handle_house_state_changed` :3096-3133; `_handle_person_arriving` :3990-4004.
- `hvac_override.py`: `check_ac_reset` count-coupling `:3805-3815` (`kwh_samples_above_threshold += 1` vs `_sustained_samples`); suppression windows `:129`, `:141-146`, `:153` (C17).
- `hvac_zones.py`: `update_room_conditions` :523; `_hvac_armed` :241/990; hallway exclusion :650-665; **`current_session_start = now` at :714-716 (C18 mechanism)**; hallway-excluded seen :988; `is_zone_hvac_established` :1043.
- `hvac_const.py`: `HVAC_DECISION_TICK` :11-13.
- `const.py`: `ROOM_TYPE_HVAC_HOLD` :1219-1224 (day), `ROOM_TYPE_HVAC_HOLD_NIGHT` :1230-1242 (night).
- `binary_sensor.py`: `HVACOccupiedBinarySensor` :745; slug + zone-lookup pattern :906-919.
- `signals.py`: full read — only `SIGNAL_ROOM_ENTRY_LIFECYCLE` :199 is relevant.

---

## 2. Falsifiable invariant (rev 2, per findings 1 + 11)

**INV:** *"For every HVAC-occupancy rising edge on a live, non-hallway room R (ROOM entry LOADED, coordinator present, `zm._hvac_armed[R]` NOT already True at event time) belonging to an HVAC zone Z:*
1. *`_run_decision_cycle` STARTS within `HVAC_FAST_PATH_SLA_S` of the source `state_changed` event, unless denied by the per-zone or global limiter (denials do NOT drop the observation — the periodic 5-min tick discharges);*
2. *When R's zone Z would be preset-flipped by that cycle but is dwell-blocked by `hvac.py:2362-2365`, a follow-up cycle is scheduled at `zone.current_session_start + zone_entry_dwell + FAST_PATH_DWELL_SLACK_S` (per-zone dedup), and the follow-up cycle is EXEMPT from the per-zone limiter (per-zone dedup already bounds it);*
3. *On a non-periodic cycle (`trigger != "periodic"`), the count-coupled side effects enumerated in §4.7 are SKIPPED (or proven time-based). The periodic-tick behavioural output for every other zone is byte-identical to `develop`;*
4. *Every fast-path subscription, per-zone timer, and pending follow-up is cancelled inside `async_teardown` (no orphan callbacks, no writes after unload); the state-change unsub is single-owned on `self._fast_path_state_unsub` (no double-unsub);*
5. *`_fast_path_last_run_at[Z]` is stamped ONLY when a cycle actually runs — not on rate-limited denials, boot-settle early returns, or re-entrancy skips (which set `_fast_path_rerun_requested` and produce one trailing rerun after lock release)."*

Discriminating observations (finding 10): under the fix, the **share of hot entries** — zone away, `any_room_hvac_occupied` False, no active session — whose *first* `ura_activity_log preset_change` row lands within **250 s** of the source `binary_sensor.{entry_id}_occupied` rising edge rises from ≈0 (today, C18 mechanism guarantees it can't) to ≈all, and those rows carry `trigger=fast_path_dwell_followup` in their details dict. Any hot entry with edge→write > 300 s post-fix and no rate-limit denial in the same window is a defect.

The "changes WHEN, not WHAT" claim and the "sibling zones quiescent" claim from rev 1 are **STRUCK** — the count-coupled side effects (§4.7) make untriggered whole-house cycles NOT behaviour-neutral in general; the fix is the `trigger`-gated skip.

---

## 3. D0 — Measure before you build (READ-ONLY, ~30 min) — REV 2 per finding 3

**Purpose:** size the per-zone limiter empirically; produce the pre-W2-1 write-rate baseline the limiter acceptance depends on (finding 8); characterise cycle-duration percentiles for SLA sizing (finding 11).

**Primary signal:** rising edges per **room** on `binary_sensor.{entry_id}_occupied` — resolve entity_ids from the entity registry for every non-disabled ROOM entry whose CONF_ROOM_TYPE != HALLWAY and whose room is a member of some HVAC `zone.rooms` (skip rooms in no HVAC zone; §4.6). This is the direct trigger source.

**Armed-gate replay (offline):** for each rising edge on room R, decide whether it would arm the D1 producer by replaying `zm._hvac_armed` — apply the per-room-type tail from `ROOM_TYPE_HVAC_HOLD` (day) / `ROOM_TYPE_HVAC_HOLD_NIGHT` (night), keyed on the recorded house-state at edge time. A rising edge landing INSIDE the tail window from the prior vacancy is NOT a fast-path candidate (the room is still armed from the tail; no state change to trigger on). Emit "trigger-eligible edges" per zone per day.

**Additional signals:**
- Per-zone daily trigger-eligible edge count (median / p95 / max) — sizes `HVAC_FAST_PATH_MIN_INTERVAL_S`.
- Inter-edge gap p50 / p95 / p99 per zone (seconds).
- Bursts-per-5-min p95 per zone.
- **Cycle-duration percentiles** (finding 11): from `ura_activity_log` and any coordinator timing rows, extract per-cycle wall-time p50/p95/p99. `HVAC_FAST_PATH_SLA_S` sized so p95 cycle duration + queuing headroom fits (SLA is "cycle STARTS within X s", so completion drives sizing separately).
- **Pre-W2-1 climate-write baseline** (finding 8): per-zone `climate_write` rows/day from W1-A's durable log across a ≥ 1-day post-W1-A window. This is the acceptance yardstick — the fast path is not allowed to raise the per-zone write count materially.

**Report:** `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md`, committed before D2 dispatch.

**Sizing rule:** `HVAC_FAST_PATH_MIN_INTERVAL_S` chosen so at p99 zone burst the limiter denies < 10% of trigger-eligible edges per zone. Starting proposal 60 s pending measurement. `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` sized so aggregate non-periodic cycles ≤ ~1 per 20 s house-wide (protects the cycle from becoming the load).

**Fail-out:** if the trigger-eligible rate on any zone is high enough that the sized limiter would deny > 10% AND the periodic tick already covers >90% of them, stop — the fast path's marginal benefit is thin against its ingredient risk (marginal-benefit pushback).

---

## 4. Design

### 4.1 Trigger source

`async_track_state_change_event` on the filtered set of `binary_sensor.{entry_id}_occupied` entity_ids (registry-resolved, finding 6). Filter set built at setup from all **non-disabled** ROOM entries; hallway flag and zone-membership are re-checked at EVENT TIME (source of truth may change between rebuilds).

**Rising-edge classification (finding 6):** old-state `"off"` → new-state `"on"` ONLY. `unknown` / `unavailable` / `None` on either side is NOT a rising edge — those are lifecycle noise. The rising-edge test is stricter than rev 1 (which admitted unknown→on); the strict form matches the room coordinator's steady-state emit pattern and rejects reload-storm artifacts.

**Per-event gating (all short-circuit, in this order):**
1. Room is a member of some HVAC `zone.rooms` — else skip.
2. Room's `CONF_ROOM_TYPE != ROOM_TYPE_HALLWAY` — else skip (circulation-excluded rooms cannot be HVAC-occupied per `hvac_zones.py:650-665`; triggering would just waste a cycle).
3. `zm._hvac_armed.get(room_name) is not True` — if already armed, the D1 producer's state won't change on this edge; a cycle is redundant.
4. Not inside boot-settle (`_boot_settle_done`) — if suppressed, count in an in-memory `_fast_path_boot_suppressed_count` for observability; do NOT stamp `_fast_path_last_run_at[Z]` (finding 5).
5. Per-zone limiter: `now - _fast_path_last_run_at.get(Z, min) >= HVAC_FAST_PATH_MIN_INTERVAL_S` — else deny (in-memory counter, `debug` log; NO per-denial NM per finding 9).
6. Global limiter: `now - _fast_path_last_run_at_any_zone >= HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` — else deny (same counters).
7. Re-entrancy: if `_decision_cycle_lock.locked()`, set `_fast_path_rerun_requested = True` (finding 5) and return — after the current cycle releases the lock, run ONE trailing cycle (see §4.5).

If all pass, dispatch via `hass.async_create_task(self._async_decision_cycle(trigger="fast_path"))`, tracked in `_pending_tasks`.

### 4.2 Rising-edge only (unchanged)

Argument in rev 1 stands: retreat gate needs fused-empty AND ≥ 10-min vacancy grace; a ≤ 5-min falling-edge lag is invisible. Falling edges continue to ride the tick.

### 4.3 Rate limiter — per-zone + global

**Constants (`hvac_const.py`, rung 1; sibling comment to `HVAC_DECISION_TICK`, "cloud API call-rate protective bound — change requires review"):**
- `HVAC_FAST_PATH_MIN_INTERVAL_S` — per-zone floor (sized from D0).
- `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` — house-wide floor between any two non-periodic cycles (finding 8).
- `HVAC_FAST_PATH_SLA_S` — target trigger→cycle-START latency (tests + observability). Sized from D0 cycle-duration percentiles + queuing headroom.
- `FAST_PATH_DWELL_SLACK_S` — 2 s. Slack past `current_session_start + zone_entry_dwell` (protects against wall-clock coupling at the edge).

**State (on `HVACCoordinator`):**
- `self._fast_path_last_run_at: dict[str, datetime]` — per zone_id, stamped ONLY when a cycle actually runs (finding 5). Never on denials, boot-settle early returns, re-entrancy skips.
- `self._fast_path_last_run_at_any_zone: datetime | None` — global counterpart, same stamping rule.
- `self._fast_path_rerun_requested: bool` — trailing-rerun flag (finding 5).
- `self._fast_path_pending_dwell: dict[str, CALLBACK_TYPE]` — per-zone `async_call_later` unsubs; cancelled from this dict in `async_teardown`, NOT via `_unsub_listeners` (finding 7 — helpers/event.py:441-447 raises on double-unsub).
- Counters exposed as attributes on an existing HVAC sensor (finding 2): `fast_path_triggers_total`, `fast_path_rate_limited_total`, `fast_path_global_rate_limited_total`, `fast_path_skipped_reentrant_total`, `fast_path_boot_suppressed_total`, `fast_path_dwell_followups_scheduled_total`, `fast_path_dwell_followups_ran_total`, `fast_path_dwell_followups_coalesced_total`. Reset on daily rollover using the existing `_last_daily_reset` hinge at `hvac.py:1606`.

**Restart survival:** no persistence — a restart legitimately reopens the limiter; the next periodic tick and any real edge will re-establish the stamp. Suppression discharge = the periodic timer.

**Boot-settle:** on `_async_decision_cycle` early-return at `hvac.py:1580` (boot-settle suppressed), the fast-path code path (which called it) MUST NOT stamp `_fast_path_last_run_at[Z]` (finding 5). Achieved by classifying the return path via `trigger` — see §4.5.

### 4.4 Dwell-expiry follow-up — the MAIN hot-entry path (finding 4, C18)

Per C18, EVERY observing tick that first sees `any_room_occupied` starts `current_session_start = now` (`hvac_zones.py:714-716`) and then hits the dwell skip (`hvac.py:2362-2365`). This is true for the periodic tick AND for a fast-path trigger. Without a follow-up, both cycles do exactly zero preset work; the preset lands on the NEXT tick, which today can be up to 5 min later — that's the 5-10 min hot-entry latency C18 records.

**Rule (rewritten, finding 4):** whenever `_run_decision_cycle` takes the dwell-skip branch at `hvac.py:2362-2365` for zone Z, IF no follow-up is pending for Z, register `async_call_later(hass, remaining_s + FAST_PATH_DWELL_SLACK_S, _fast_path_dwell_followup(Z))`. Store the unsub in `self._fast_path_pending_dwell[Z]`. **Schedule regardless of `trigger`** — this shaves periodic ticks that hit dwell too, not just fast-path ones.

**Follow-up cycle is EXEMPT from the per-zone limiter** (finding 4) — per-zone dedup already bounds volume to at most one follow-up per zone per dwell window. It is still subject to the global limiter, and to boot-settle / lock re-entrancy (which will produce the `_fast_path_rerun_requested` trailing behaviour, §4.5).

**Dedup + coalesce:** if a second dwell-skip lands for Z while a follow-up is pending, do nothing; counter `fast_path_dwell_followups_coalesced_total` increments.

**Teardown-safe:** follow-up unsubs are stored in `_fast_path_pending_dwell` and cancelled from that dict in `async_teardown`. NOT appended to `_unsub_listeners` (finding 7).

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

Stamping rule: `_run_decision_cycle` stamps `_fast_path_last_run_at[Z]` for the trigger's originating zone AND `_fast_path_last_run_at_any_zone` ONLY on entry, ONLY when `trigger != "periodic"`. Every early-return path above leaves the stamps untouched.

### 4.6 Zone / hallway resolution at event time (finding 6)

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
    if self._zone_manager._hvac_armed.get(room_name) is True: return
    # limiter + boot-settle + re-entrancy per §4.1
```

`self._room_name_by_entity`, `self._room_type_by_name` rebuilt on `SIGNAL_ROOM_ENTRY_LIFECYCLE` and on config-entry `options_updated` (finding 7).

### 4.7 Count-coupled side effects — MUST SKIP on non-periodic cycles (finding 1)

`_run_decision_cycle` today runs several call sites whose semantics assume "one call per 5-min tick." Firing an extra whole-house cycle on a fast-path trigger perturbs their counters. Threading `trigger` and skipping the count-coupled ones on `trigger != "periodic"` is required for INV conjunct (3) — behaviour-neutrality for every other zone.

Reviewer B on this plan MUST verify this table against the merged `develop` at build dispatch.

| Site (file:line) | Count-coupled OR time-based | Rev-2 disposition on non-periodic |
|---|---|---|
| `_check_carrier_freshness` (`hvac.py:1649`) | Time-based (last-poll timestamp) | Run — safe. |
| `update_room_conditions` (`hvac.py:1647`, `hvac_zones.py:523`) | Time-based (uses `now`, tail expiry) | Run — this is THE reason the fast path exists. Note: this call is what sets `current_session_start = now` at `hvac_zones.py:714-716`, which arms the dwell — so the fast-path cycle itself will hit the dwell skip and schedule the D3 follow-up. Expected. |
| `_egress_manager.async_tick(now)` (`hvac.py:1683`) | Time-based | Run. |
| `_predictor` updates (banking / pre-cool / pre-heat) | Time-based (per-schedule) — VERIFY | Default: skip on non-periodic to avoid off-cadence schedule reads. Reviewer B verifies each. |
| `_fan_controller` per-zone updates | Time-based | Run — fans are the operator's other fast-in lever; a delay-free fan update on entry is desirable. |
| `_cover_controller` updates | Time-based | Run. |
| `_override_arrester.check_ac_reset` (`hvac.py:1745`) → `hvac_override.py:3805-3815` `kwh_samples_above_threshold += 1` vs `_sustained_samples` | **COUNT-COUPLED** | **SKIP on non-periodic.** An extra call inflates the sample counter, tripping the nudge debounce early. |
| `_override_arrester` per-zone override detection | Contains its own suppression window (C17: 5 s temp / 120 s preset), event-driven internally | Run. Its own suppression handles the extra call. |
| Anomaly observations (`hvac.py:1783`) | **COUNT-COUPLED** (per-cycle samples feed `AnomalyDetector` baselines) | **SKIP on non-periodic.** Extra samples pollute baselines. |
| `_emit_and_reset_short_cycles` daily rollover (`hvac.py:1643`) | Time-based (LOCAL-day hinge) | Run. |
| `_predictor.flush_daily_outcome` (`hvac.py:1610`) | Time-based (daily hinge) | Run. |
| Row-1 / row-4 / row-10 / D5 / D6 / D7 / D9 / F4 preset & retreat logic | Time-based (reads current state) | Run — this IS the fast-path payload. |
| `preset_change` activity-log write (`hvac.py:2716-2748`) | Event-driven (only fires on actual change) | Run; add `trigger` to details dict (finding 2). |
| Zone-dwell skip (`hvac.py:2362-2365`) | Time-based | Run — schedules the D3 follow-up (§4.4). |

**Implementation shape:** `_run_decision_cycle(trigger)` receives the arg and guards each count-coupled call with `if trigger == "periodic":`. Adding two guards; no logic changes inside the guarded calls. Behaviour-neutrality for periodic ticks is byte-identical (the arg default is `"periodic"`).

House-state and pre-arrival triggers (already existing) inherit the same skip — they fire at low rates today, but they're also count-coupled by the same argument. Threading the arg fixes them retroactively; document in the D2 progress note.

### 4.8 Coexistence with other triggers (unchanged intent, updated per §4.7)

- Boot-settle: honoured; §4.5 stamping rule ensures no state pollution on early returns.
- House-state / pre-arrival: pass `trigger="house_state"` / `trigger="pre_arrival"` explicitly so the §4.7 skip applies to them too — a small side-benefit finding 1 unlocks.
- Egress initial-restore gate: unaffected.
- `SIGNAL_ZM_ZONES_UPDATED`: unaffected.
- Carrier post-write guard (C16) × arrester preset-suppression (C17 120 s): unchanged by this cycle — no new preset writes are introduced.

---

## 5. Deliverables

### D0 — Empirical probe (READ-ONLY, gate) — see §3
**Acceptance:**
- **Verify:** per-zone trigger-eligible edge counts (median / p95 / max / bursts-per-5-min p95) after armed-gate replay.
- **Verify:** cycle-duration p50/p95/p99 (SLA sizing).
- **Verify:** pre-W2-1 per-zone `climate_write` rows/day baseline from W1-A ≥ 1-day post-ship window.
- **Verify:** proposed `HVAC_FAST_PATH_MIN_INTERVAL_S`, `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S`, `HVAC_FAST_PATH_SLA_S` values with one-line justifications.

### D1 — Constants, state, `trigger` threading, count-coupled skips
Add the constants; add the state fields; thread `trigger` through `_async_decision_cycle` and `_run_decision_cycle`; add the two count-coupled guards per §4.7. Put `trigger` into the existing `preset_change` details dict (`hvac.py:2716-2748`). Expose counters as attributes on an existing HVAC sensor (finding 2 — pick the existing coordinator-status sensor; NO new sensor).

**Wire-in anchors:**
- `test_run_decision_cycle_trigger_defaults_periodic` — call sites without kwarg default to `"periodic"`.
- `test_fast_path_skips_check_ac_reset_sample_increment` — invoke `_run_decision_cycle(trigger="fast_path")`, assert `zone.kwh_samples_above_threshold` unchanged from prior value; mutation drill: comment out the guard → this test FAILS.
- `test_fast_path_skips_anomaly_observation` — spy on AnomalyDetector.observe; assert 0 calls; mutation drill on the guard.
- `test_periodic_cycle_byte_identical_to_develop` — snapshot behavioural output of a periodic cycle before and after the patch; require equivalence (structural, not stringly).
- `test_preset_change_activity_log_carries_trigger` — assert details dict contains `trigger` key with the expected enum value.

**Acceptance:**
- **Verify:** the count-coupled skip table (§4.7) has a matching guard in code, one per row.
- **Live:** post-restart, `ura_activity_log` `preset_change` rows carry a `trigger` in details for at least one row per trigger kind within 24 h.

### D2 — Fast-path trigger wiring (rising edge, hallway-excluded, armed-gated, limited)
Register `async_track_state_change_event` on the filtered set at `async_setup` (`hvac.py` — after room-coordinator seed at :1254, before / adjacent to the periodic timer at :1355). Single unsub on `self._fast_path_state_unsub` — release-then-reassign on rebuild (finding 7). Subscribe to `SIGNAL_ROOM_ENTRY_LIFECYCLE` AND to config-entry `options_updated` (finding 7) to rebuild.

**Wire-in anchors (mutation drills required — Tier 2-DB C-framing):**
- `test_fast_path_registered_at_setup_with_filtered_entities` — asserts registration; neuter drill on the call.
- `test_fast_path_rebuilds_on_lifecycle_signal_no_double_unsub` — fires `SIGNAL_ROOM_ENTRY_LIFECYCLE`; asserts previous unsub is called ONCE and a new one is stored; drill: replace release-then-reassign with re-registration → test FAILS RED with the `helpers/event.py:441-447` shape.
- `test_fast_path_rebuilds_on_options_updated` — analogous, options-flow path.
- `test_fast_path_hallway_excluded_at_event_time` — behavioural, not source-grep.
- `test_fast_path_skips_when_hvac_armed_already` — sets `zm._hvac_armed[room]=True`, dispatches edge, asserts no cycle.
- `test_fast_path_falling_edge_ignored` — on→off does nothing.
- `test_fast_path_unknown_unavailable_ignored` — old ∈ {unknown, unavailable, None} does not trigger.
- `test_fast_path_skips_room_in_no_hvac_zone` — a room absent from every `zone.rooms` produces no trigger.

**Acceptance:**
- **Test:** all wire-in tests pass with mutation drills.
- **Live:** counter `fast_path_triggers_total > 0` within 24 h; `fast_path_skipped_reentrant_total` bounded.

### D3 — Dwell-expiry follow-up (MAIN hot-entry path, per finding 4 + C18)
Implement §4.4 for periodic AND fast-path triggers (any dwell skip). Per-zone dedup dict `_fast_path_pending_dwell`; unsubs cancelled from that dict in `async_teardown`.

**Wire-in anchors:**
- `test_dwell_skip_schedules_followup_regardless_of_trigger` — parametrise `trigger ∈ {"periodic","fast_path","house_state"}`; each schedules one follow-up.
- `test_dwell_followup_exempt_from_per_zone_limiter` — stamp `_fast_path_last_run_at[Z]` recently; assert follow-up still runs.
- `test_dwell_followup_deduplicated_per_zone` — two dwell skips → one follow-up.
- `test_dwell_followup_cancelled_on_teardown` — call `async_unload` mid-window; assert no callback fires.
- `test_dwell_followup_writes_preset_when_expected` — end-to-end with a hot-entry fixture (zone away, empty, edge lands, follow-up fires after dwell + slack, `preset_change` recorded).

**Acceptance (rewritten, finding 10):**
- **Verify (D0 baseline restated):** today's edge→`preset_change` p50 latency on hot entries (zone away, `any_room_hvac_occupied` False, no active session) is **300-600 s** (C18).
- **Verify (post-fix discriminator):** share of hot entries with edge→`ura_activity_log preset_change` (or W1-A `climate_write`) latency < **250 s** rises from ≈0 to ≈all, with the winning row's details carrying `trigger=fast_path_dwell_followup`.
- **Live:** 3+ hot entries in the first 24 h post-restart show < 250 s edge→write; recorder + `ura_activity_log` cross-check.
- **Live (write-rate acceptance, finding 8):** per-zone `climate_write` rows/day ≤ pre-W2-1 baseline + D0-computed margin (i.e. the fast path did not raise the cloud call rate).

### D4 — Teardown, reload-storm safety, storm trip-wire (finding 9)
- Single-owned `_fast_path_state_unsub`; per-zone `_fast_path_pending_dwell` dict; both drained in `async_teardown`.
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

**Q1 — Per-zone vs whole-house cycle.** Left as-is per operator scope. Ask ONLY if D0 shows per-zone trigger volume × sibling-zone write rate would push Carrier per-thermostat cadence into a new regime; §4.7 makes non-periodic cycles behaviour-neutral for un-triggered zones by construction, so this is now much less likely to be needed.

No other open questions.

---

## 7. Non-goals (rev-2 additions in bold)

- No dwell / tail / grace / hallway-exclusion / retreat semantics change.
- No falling-edge fast path.
- No new preset/setpoint write sites.
- No producer refactor (`_compute_hvac_occupied` stays inside the tick).
- No operator UI knob for the limiter.
- **No new sensor** (`sensor.ura_hvac_coordinator_decision_cycle` was invented in rev 1 and is retracted, finding 2).
- **No new per-cycle DB writer** — counters are in-memory attributes; `trigger` piggy-backs on the existing `preset_change` activity-log row (finding 2).
- **No per-denial NM** — storm trip-wire only (finding 9).
- **No Nest / other-brand strategy changes** — W1-B territory.

---

## 8. Tier + review framings (unchanged from rev 1, expanded per finding 1 + 8)

**Tier 2-DB (three framing-disjoint reviews + live validation + README write-back).**

**Framings:**
- **A — Local correctness + limiter arithmetic + rising-edge classification.** Per-zone stamp discipline (finding 5); trailing-rerun idempotence; global limiter interaction.
- **B — Integration + decision-cycle integrity + count-coupled classification.** Verify §4.7 table against merged `develop`; verify the `trigger`-arg thread does not miss any call site; verify Carrier cloud bound holds against W1-A per-zone write-rate baseline (finding 8); verify house-state / pre-arrival paths inherit the skip cleanly; C16/C17 interactions still no-op for this cycle.
- **C — Test authority via real per-site mutation.** Neuter each of: state-change registration, per-zone limiter, global limiter, count-coupled skip guards, dwell follow-up scheduler, lifecycle re-subscribe, options_updated re-subscribe. Each mutation MUST turn a SPECIFIC test RED; no aggregate monkeypatch. Confirm no `.pyc` staleness (`feedback_mutation_verification_pycache_staleness.md`).

**Reviewer D (adversarial completeness):** re-enumerate every count-coupled site in `_run_decision_cycle` and every downstream reader of the counters/sensors the D1 patch touches; produce a legal-config reachable break of any INV conjunct.

**Plan review (mandatory):** ONE adversarial plan review before build dispatch — re-run §1.1 greps, re-derive §4.7 table, verify the D0 armed-gate replay logic in prose is executable as-is.

**Sequencing gate (finding 8):** merge only after **W1-A is live ≥ 1 day** AND `feature/hvac-live-room-establishment` is on `develop`. The pre-W2-1 climate-write baseline in §5 D3's acceptance is unmeasurable before W1-A.

---

## 9. Sequencing + overlap flag (v5.103.15)

Do not dispatch build until:
1. `feature/hvac-live-room-establishment` (v5.103.15) merges to `develop`.
2. W1-A ships and has been live ≥ 1 day.

Overlapping regions in `hvac.py` (v5.103.15): subscribe block :1131-1213; `_async_decision_cycle` :1564-1598 (round-3 `_row1_hold_write` scoping fix at :2002/:2056/:2533 in review — verify at dispatch); `_run_decision_cycle` :1600-1700 including :1647 `update_room_conditions` and the count-coupled sites in §4.7. At dispatch, re-verify §1.1 REUSE line numbers.

---

## 10. Knobs on the ladder

| Number | Rung | Why |
|---|---|---|
| `HVAC_FAST_PATH_MIN_INTERVAL_S` | 1 (module const) | Cloud-call-rate protective; not operator-facing. |
| `HVAC_FAST_PATH_GLOBAL_MIN_INTERVAL_S` | 1 (module const) | House-wide floor between non-periodic cycles; same posture. |
| `HVAC_FAST_PATH_SLA_S` | 1 (module const) | Test/observability target; sized from D0 cycle-duration percentiles. |
| `FAST_PATH_DWELL_SLACK_S` | 1 (module const) | Wall-clock slack past dwell edge. |

**Kill-switch:** none. Fast path degrades to today's behaviour (5-10 min hot entry per C18) if the state-change subscription fails — warning log + one NM LOW at boot.

---

## 11. Producer / Consumer map (rev 2)

**PRODUCER of the "fast-path trigger" value:** HA `state_changed` events for `binary_sensor.{entry_id}_occupied` (registry-resolved). Source health = URA room coordinator's STATE_OCCUPIED write path. Falling-edge failures (e.g. sensor `unavailable`) collapse to the periodic tick (5-min discharge).

**CONSUMERS + call-sites:**
- `HVACCoordinator._async_decision_cycle(trigger="fast_path")` → `_run_decision_cycle(trigger)` — sole trust-consumer. Count-coupled call sites guarded per §4.7.
- `_fast_path_dwell_followup(Z)` (D3) — sole time-shifted trust-consumer; re-enters `_async_decision_cycle(trigger="fast_path_dwell_followup")`.
- Existing `preset_change` activity-log details dict — carries `trigger` for the audit oracle in D3's acceptance (display + audit).
- Existing HVAC coordinator sensor attributes — in-memory counter view (display + audit).
- `AnomalyDetector` `fast_path_trigger_rate` — storm trip-wire (audit).

**No new trust downstream.** The plan changes WHEN the cycle runs and PARTIALLY WHAT it runs (count-coupled sites are gated by `trigger`); INV conjunct (3) makes the periodic-tick output byte-identical.

---

## Appendix A — INV restated for reviewer D

> Under normal steady-state operation (boot-settle released, no active reload storm, W1-A live), for every HVAC-occupancy rising edge on a live non-hallway room R in an HVAC zone Z, where `zm._hvac_armed[R]` is not already True:
>
> 1. A `_run_decision_cycle(trigger="fast_path")` STARTS within `HVAC_FAST_PATH_SLA_S` seconds unless the per-zone OR global limiter denied it.
> 2. If that cycle takes the dwell-skip branch at `hvac.py:2362-2365`, a follow-up `_run_decision_cycle(trigger="fast_path_dwell_followup")` runs at `zone.current_session_start + zone_entry_dwell + FAST_PATH_DWELL_SLACK_S`, exempt from the per-zone limiter, per-zone dedup'd.
> 3. On any non-periodic cycle, the count-coupled sites in §4.7 are SKIPPED. The periodic-tick output for every un-triggered zone is byte-identical to `develop`.
> 4. `_fast_path_last_run_at[Z]` is stamped ONLY when a cycle actually runs (not on denials, not on boot-settle early returns, not on re-entrancy skips — which set `_fast_path_rerun_requested` and produce one trailing cycle).
> 5. `async_teardown` cancels every fast-path subscription, per-zone follow-up timer, and pending rerun; the state-change unsub is single-owned on `self._fast_path_state_unsub`.
> 6. Hot-entry latency (edge → `ura_activity_log preset_change` row) drops from the C18 baseline of 300-600 s to < 250 s for the class defined in §5 D3.
>
> A legal-config, recorder-reachable violation of ANY conjunct falsifies INV.

---

## Rev 2 change log — findings 1-12 → sections

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
