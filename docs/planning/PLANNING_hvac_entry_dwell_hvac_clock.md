> **SUPERSEDED 2026-09-26 night:** HVAC occupancy rides the lighting STATE_OCCUPIED + timeout (C24), so an onset-anchored dwell cannot filter transits. Replaced by step-4-B Stage B (arming-edge raw-persistence gate) — card HVAC-ENTRY-DWELL-ROOM-CLOCK-1.

> **SUPERSEDED 2026-09-28 — FOLDED into `PLANNING_hvac_fast_occupancy_response.md` §5b (D5 transit filter, built v5.103.20).** Knob 47 now gates arming on 60 s of persisted room evidence on the away→home edge; the lighting-session dwell is retired. Card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` closes as folded.


# PLANNING — HVAC-ENTRY-DWELL-ROOM-CLOCK-1 (v2, HVAC-clock)

**Supersedes:** `PLANNING_hvac_entry_dwell_room_clock.md` (v1 gated on the LIGHTING clock;
plan-review FIX-PLAN-FIRST — lighting timeouts make transits look long; hallways leak in).
**Tier:** 2-DB (regression-prone HVAC preset-decision change; three framing-disjoint reviews +
Review D live validation + README write-back). Standing policy per CLAUDE.md.
**Workstream:** HVAC-W2-OCCUPANCY-TRUTH (state-of-play §11 W2). Companion to the W2-1 fast
path (parked). Author date: 2026-09-26.

**Mandatory-read acknowledgement:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`
read completely (§3 occupancy model, §3.2 dwell row **DENOMINATION DEFECT**, §10 C18) before
scoping. Correction C18 cited verbatim below; §3.2 dwell row is the direct trigger.

**Delta from first draft (2026-09-26 late — orchestrator review):** the initial draft anchored
the dwell clock on the producer TICK of arming. That recreates C18 for any `dwell > 0`
(the first observing tick has arm-age 0, so the dwell skips, and the write lands one tick
later — the exact two-tick latency this cycle exists to remove). Rewritten: anchor on the
**raw evidence rising edge** the room coordinator already timestamps
(`get_became_occupied_time()` — the SAME `state_occupied` signal that drives `_hvac_armed`,
whose rising edge is raw evidence because lighting-timeouts extend only the falling side),
clamped against a new `_hvac_last_released[room]` to prevent backdating across a tail
release. Latency analysis in §5 updated accordingly.

---

## 1. Goal (operator scope, 2026-09-26 evening)

> "Room clock is not good for HVAC. We built a separate HVAC occupied to decouple it — one
> for turning things off, another for activating HVAC."

The entry dwell (`hvac.py:2438-2451`) still gates on the **lighting** clock — the exact
denomination `RoomCondition.hvac_occupied` was introduced (v5.103.7) to escape. Move the
gate and its clock onto the **HVAC** denomination:

- Gate: `zone.any_room_hvac_occupied` (not `any_room_occupied`).
- Clock: **earliest raw-evidence rising edge** among rooms currently `_hvac_armed=True`,
  clamped against the last HVAC release of that room (no backdating across a tail expiry).
- Hallways excluded **by construction** (the HVAC producer already forces
  `hvac_occupied=False` for hallways at `hvac_zones.py:650-665` / `724-735`,
  `arm_source="hallway_excluded"`; 0 on-rows across 7 hallways in 7 d — state-of-play §3.1).
- First tick that sees a room whose evidence has been present ≥ dwell can **ACT** — the
  point of the whole exercise.

Dwell knob stays `number.ura_hvac_coordinator_zone_entry_dwell` (integer minutes, rung-3
live-tunable), **live value 0**. With dwell = 0 the change is a **no-op** on the
skip-decision surface (guard `dwell_minutes > 0` at `hvac.py:2442`) and the recommendation is
to leave it at 0 until the MEASURE-FIRST probe justifies a value.

## 2. Falsifiable invariant

> **For any zone Z, in a house state where the entry dwell applies
> (home_day / home_evening / home_night / guest / waking), on a decision tick T with
> `zone.any_room_hvac_occupied == True`, target preset != "away", and Z not in
> `_pre_arrival_zones`:**
>
> - **ACT:** the dwell skip does NOT fire whenever some HVAC-armed room in Z has a
>   clamped raw-evidence rising edge at or before `T - dwell_minutes`.
> - **HOLD:** the dwell skip DOES fire whenever every HVAC-armed room in Z has a clamped
>   raw-evidence rising edge strictly after `T - dwell_minutes`.
> - Hallways never satisfy either half (they never become `_hvac_armed`).
> - Rooms in tail-hold (`_hvac_armed=True` with `state_occupied=False`) keep their original
>   rising-edge anchor; a mid-episode room-vacate NEVER pushes the zone clock forward.
> - The clamp `max(get_became_occupied_time(room), _hvac_last_released[room])` guarantees a
>   fresh HVAC arm after a tail release cannot inherit an older lighting-session start.

Review D's job: falsify this — enumerate reachable {house_state × any_room_hvac_occupied ×
per-room rising-edge ages × tail vs held × released-then-rearmed × pre_arrival × preset}
tuples and force ACT/HOLD disagreement.

## 3. Non-goals (explicit)

- **No** W2-1 fast path (occupancy-triggered decision cycle) — stays parked (state-of-play
  §9d).
- **No** change to `zone.any_room_hvac_occupied`, `_compute_hvac_occupied`,
  `_effective_hvac_hold_seconds`, tail-hold tables, `conditioning_retreat_ok`,
  `is_zone_hvac_established`, night-trust D7, D5/D6/D8.
- **No** change to the LIGHTING `zone.current_session_start` writer (Row 2d) — kept for
  observability + Review-D cross-check. This cycle introduces a NEW sibling on the HVAC
  denomination, it does not swap the existing one.
- **No** change to `_became_occupied_time` semantics in the room coordinator (READ-only new
  consumer via the existing public accessor).
- **No** wake-capable-room-type gating, no short-visit fast-retreat, no per-room override
  changes — separate cards.
- **No** synthetic time, no new signal / dispatch / listener, no new cross-coordinator
  coupling beyond the existing accessor. No new HA state-tracker subscription (the raw
  timestamp is re-read from the room coordinator at each producer pass).

## 4. Institutional context verified

**Design docs**
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — read complete: §2 (5-min tick, no
  occupancy-triggered cycle, C18 lag), §3.1 (`_compute_hvac_occupied`, hallway exclusion
  `_hvac_seen.add` but `hvac_occupied=False`, day tail-hold `ROOM_TYPE_HVAC_HOLD` bedroom 60 /
  common 60 / media 120 / hallway 0; night `ROOM_TYPE_HVAC_HOLD_NIGHT`), §3.2 (**dwell row
  DENOMINATION DEFECT** — this card), §3.3 (LIVE / dormant matrix), §8 (dwell knob live 0;
  vacancy grace 10; energy-saving grace 5), §9d (W2-1 scope), §10 C11 / C18.
- `HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1` (v5.103.17) — no interaction; write-path change,
  not producer.
- v1 plan `PLANNING_hvac_entry_dwell_room_clock.md` — reviewed for its edge-case matrix
  (E1–E10) and its plan-review findings (lighting timeouts, hallway leak) so this v2 does
  not repeat them.

**Prior planning / audit consulted**
- `PLANNING_hvac_zone_conditioning_demand.md` — Row-2d NO-SWAP for lighting was DELIBERATE
  (kept for observability); a new HVAC-denomination sibling is the sanctioned pattern
  (parallels Row-2a / 2c).
- `AUDIT_hvac_conditioning_demand_supersession_and_reuse_2026_09_16.md` — S2 (dwell) follows
  S1; the new sibling clock does not touch S1.
- `PLANNING_hvac_w2_occupancy_fast_path.md` — parked; scope disjoint (cadence vs clock).
- `AUDIT_hvac_preset_flap_fix_implications.md` — Row-2 interactions.

**Kanban cards**
- `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` — this card, incl. `reframe_2026_09_26` +
  `hallway_note_2026_09_26` + `next` (MEASURE first).
- `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1` (waiting_me; Jaya hold 5400) — orthogonal.
- `HVAC-HOLD-SIZING-ALL-ROOMS-1` (investigating) — orthogonal.

**Memory bodies**
- `reference_hvac_state_of_play.md` (mandatory read discipline);
  `feedback_tier2plus_prior_art_scan.md` (this section);
  `feedback_marginal_benefit_pushback.md`, `feedback_measure_before_build.md`
  (probe-first + MEASURE gate below);
  `feedback_read_consumers_before_asserting_function.md`.

**Code locations surveyed end-to-end**
- `domain_coordinators/hvac_zones.py:600-790` (producer loop, Row 2a-e writers,
  hallway short-circuit at `:724-735` and coordinator-absent branch at `:680-711`) and
  `:966-1123` (`_compute_hvac_occupied`, `_hvac_armed`, `_hvac_tail_until`,
  `_hvac_arm_source`).
- `domain_coordinators/hvac.py:2380-2500` (dwell skip, pre-arrival exemption,
  target-preset exemption).
- `coordinator.py:300-330` (`_became_occupied_time` field decl), `:3614/3682/3869/4797/4829`
  (SET on rising edges), `:4121/4400/4808/4840/5273` (CLEAR on vacant edges), `:5384-5395`
  (public `get_became_occupied_time()`).
- `__init__.py:5040-5060, 5520-5540` and `binary_sensor.py:250-410` (RestoreEntity + DAO
  round-trip for `_became_occupied_time` — persistence exists already, HVAC piggybacks READ-
  only).

**Prior-art scan — REUSE-or-BUILD**

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Anchor of "HVAC-arm raw-evidence onset per room" | **REUSE + CLAMP** — the raw-evidence rising edge of the SAME `state_occupied` signal that drives `_hvac_armed` is already timestamped by the room coordinator as `_became_occupied_time` (public `get_became_occupied_time()`, `coordinator.py:5384-5395`). Rising-edge writes at `coordinator.py:3614/3682/3869/4797/4829`; vacant-edge clears at `:4121/4400/4808/4840/5273`. STATE_OCCUPIED's rising edge IS raw evidence because lighting-timeouts extend only the falling side (§5 evidence 1). Clamped against a new sibling `_hvac_last_released[room]: dict[str, datetime]` (written when `_hvac_armed[room]` transitions True → False at `hvac_zones.py:1108-1110` and `:1120-1121`) so a stale lingering LIGHTING session cannot backdate a fresh HVAC arm across a tail release (E4). | grep 2026-09-26 |
| REJECTED — producer tick of arming | Recreates C18 for any `dwell > 0`: at the arming tick the clock age is 0, dwell skips, write lands one tick later (~5 min) — the exact two-tick latency the cycle exists to remove. Orchestrator review 2026-09-26 late. | — |
| REJECTED — `zone.current_session_start` (Row 2d LIGHTING) | Fused-OR of lighting-extended STATE_OCCUPIED at zone scope; loses per-room accuracy and inherits falling-side extension for the min-across-rooms. v1 plan's failure mode. | — |
| REJECTED — `zone.last_occupied_time` (Row 2a) / `zone.continuous_occupied_since` (Row 2c) | Both are HVAC denomination but reset on empty; wrong semantics for the earliest-among-currently-armed anchor. | — |
| REJECTED — subscribe to raw presence/motion entity `last_changed` per room | Would require enumerating each room's configured presence/motion entities (`CONF_MOTION_SENSORS` etc.) and adding an HA state-tracker per source. Equivalent semantics to `get_became_occupied_time()` (room coordinator already fused those raw entities into STATE_OCCUPIED rising edges) with ADDITIONAL listener surface — violates the "no new listener" constraint. Kept as a residual card ONLY if the probe (§7) shows the accessor lags raw entities by material minutes on a real entry. | — |
| Gate signal | **REUSE** `zone.any_room_hvac_occupied` | `hvac_zones.py:751` (exposed on `sensor.ura_hvac_coordinator_zone_{n}_status`). Fused OR over `RoomCondition.hvac_occupied`. |
| Cross-coordinator read | **REUSE existing plumbing** | `room_coordinators = {}` map is built in the producer loop `hvac_zones.py:602-619`; each iteration already has `coordinator = room_coordinators.get(room_name)` at `:668`. Add one call `coordinator.get_became_occupied_time()` before the `_compute_hvac_occupied` call. No new signal, no new dispatch. |
| `_hvac_last_released[room]` backdating clamp | **NEW (tiny)** — `dict[str, datetime]` on `ZoneManager`. Written at the two release sites (`:1108-1110`, `:1120-1121`); cleared on rising edge (`:1076-1080`) so the next arm's clamp uses the last-release from PRIOR to arm. Not persisted (bounded restart cost, see §6). | grep 2026-09-26 |
| Restart persistence for the anchor | **REUSE existing** for `_became_occupied_time` (RestoreEntity + DAO already round-trip it — `binary_sensor.py:278-282`, `__init__.py:5047-5053`, DB column `database.py:1278`). No new persistence for `_hvac_last_released` in v1 (bounded worst-case, §6). | — |
| Dwell knob | **REUSE** `number.ura_hvac_coordinator_zone_entry_dwell` | Option `hvac_zone_entry_dwell`, minutes integer, RestoreEntity, rung-3 live-tunable, live 0. Guard `dwell_minutes > 0` at `hvac.py:2442`. Kill-switch: 0 disables. |
| Observability | **NEW** — one `preset_change_suppressed` row per zone per suppression episode, reason=`entry_dwell_hvac`; new zone-status attributes | Rides `ura_activity_log` (analogous to `preset_change` / `preset_change_locked_out`, state-of-play §4.2 S1 + §4.3). Dedup per episode (§9). |

## 5. Anchor choice + evidence (rewritten)

**Choice:** anchor per-room clock at
`_hvac_arm_since[room] = max(get_became_occupied_time(room), _hvac_last_released.get(room, epoch))`
snapshotted at the SAME producer pass that writes `_hvac_armed[room] = True`
(rising-edge branch, `hvac_zones.py:1076-1080`). Read-only re-derivation each subsequent pass
is unnecessary — once the room is armed the anchor is stable until release. Zone-level clock:
`zone.hvac_entry_since = min(_hvac_arm_since[r] for r in zone.rooms if _hvac_armed[r])`
computed inline in the Row-2 loop where `room_coordinators` is already in scope.

### Which raw inputs make a room arm

`_compute_hvac_occupied` (`hvac_zones.py:1048-1123`) does NOT itself read HA entity states.
It takes `state_occupied: bool` (`:1053`) as an input from the caller loop
(`hvac_zones.py:717`: `room_occupied = bool(data.get("occupied", False))`) and arms on
its rising edge (`:1075-1080`: `if state_occupied and not prev: self._hvac_armed[room_name] = True`).

The rising edge of `state_occupied` (== the room coordinator's `data["occupied"]` == the
room's STATE_OCCUPIED) is what makes a room HVAC-arm. STATE_OCCUPIED itself is fused in the
room coordinator from that room's configured raw presence/motion/occupancy entities. On the
**rising edge** (any raw source turns on while the room was previously vacant), the room
coordinator sets `_became_occupied_time = now` at `coordinator.py:4797` (and the four sibling
rising-edge sites); the vacant-edge clears it. **Lighting timeouts extend only the FALLING
side of STATE_OCCUPIED** — they hold `data["occupied"] = True` after raw evidence has stopped;
they never delay the RISING edge. Therefore `get_became_occupied_time()` at the moment of
HVAC arm is the wall-clock timestamp of the actual raw-entity rising edge that drove the
room-coordinator's STATE_OCCUPIED to True — HVAC's own raw evidence, in HVAC's own denomination
(since HVAC arms on the same rising edge). The LIGHTING-denomination worry in §3.2 lives on
the falling side (extension keeps STATE_OCCUPIED up); we don't consume the falling side.

### Why the clamp

Without the clamp, this scenario re-orders wrong: (i) raw evidence stays continuously on for
10 min through a tail-release-then-re-arm; (ii) the room coordinator did NOT clear
`_became_occupied_time` (STATE_OCCUPIED never fell — lighting timeout held it), so the
timestamp is 10-min-old; (iii) meanwhile HVAC's `_hvac_armed` released at tail expiry and
just re-armed at t=now; (iv) reading `get_became_occupied_time()` unclamped would credit
the new HVAC arm with a 10-min-old anchor. Clamp = `max(get_became_occupied_time(),
_hvac_last_released[room])` forces the new anchor to be at least as recent as the last
HVAC release for THIS room. E4 test drives exactly this.

### Latency analysis (updated)

Let τ = time between the person's raw arrival and the next producer tick (uniform over
`[0, HVAC_DECISION_TICK]` = `[0, 5 min]`, mean 2.5 min). Let D = `dwell_minutes`.

- **Producer-tick anchor (rejected):** first observing tick has age 0; dwell skip fires
  for any D > 0; ACT lands on the tick AFTER that = τ + 5 min (mean 7.5 min, worst 10 min)
  for ALL entries. This is C18.
- **Raw-edge anchor (this cycle):** first observing tick has age τ; dwell skip fires iff
  τ < D; ACT latency = τ + skip · 5 min = τ if τ ≥ D, else τ + 5 min.
  - E[latency] = E[τ | τ ≥ D] · P(τ ≥ D) + (E[τ | τ < D] + 5) · P(τ < D)
  - D = 0: mean 2.5 min, worst 5 min (today).
  - D = 1 min: `P(τ < 1) = 0.2` → mean 2.5·0.8 + (0.5 + 5)·0.2 = 3.1 min; worst 6 min.
  - D = 2 min: mean 3.5 min; worst 7 min. Filters transits < 2 min.
  - D = 3 min: mean 4.1 min; worst 8 min. Filters transits < 3 min.

Transits filtered out entirely: a person who enters and leaves within D minutes may never
have HVAC arm (their tail plus grace expires before a tick) — no preset write ever fired, no
flap. Sizing (§7) trades filtered-transit count against added ACT latency for real entries.

### Trade-offs acknowledged

- **Clamp is authoritative, not the accessor.** If `get_became_occupied_time()` returns
  `None` (rare intra-tick race), fall back to `_hvac_last_released[room]` if present, else
  `now`. Documented in E7.
- **HA state restore-time.** Verified (HA convention): `hass.states.async_set` for RestoreEntity
  fills `last_changed` with the restore time, not the pre-restart wall time. `_became_occupied_time`
  is separately persisted via URA's DAO (`database.py:1278`) and restored at boot
  (`__init__.py:5047-5053`) — it carries pre-restart wall time. This is why we anchor on the
  URA-persisted timestamp, NOT `hass.states.get(entity).last_changed` for raw entities.
  Restart cost bounded in §6.
- **Race-free within a producer pass.** Accessor read + `_hvac_arm_since` write both run in
  the producer pass on the event loop; no other writer to either dict.

## 6. Restart / lifecycle behaviour (bound the in-memory hazard)

`_hvac_armed` / `_hvac_tail_until` / `_hvac_arm_source` are per-process in-memory dicts
(state-of-play scope; no DAO). `_hvac_arm_since` and `_hvac_last_released` inherit that
scope.

Post-restart, at the first `update_room_conditions` pass:

- Rooms with `state_occupied=True` hit the rising-edge branch (`prev` defaults False) and
  arm with `_hvac_arm_since[room] = max(get_became_occupied_time(room), epoch)` — because
  `_became_occupied_time` was persisted, this recovers the pre-restart raw-evidence timestamp
  for a person continuously present through the restart. First post-restart HVAC tick can ACT
  immediately for dwell > 0 (as long as `now - anchor ≥ dwell`).
- Rooms in a pre-restart tail-hold do NOT restore — a vacant room at boot with no prior
  `prev=True` is treated as never-armed, unchanged from today (state-of-play D8 tail is in-
  memory).
- `_hvac_last_released` empty at boot → clamp degenerates to `get_became_occupied_time()` on
  first arm (correct: no prior HVAC release to defend against).
- **Cost for dwell = 0:** no-op (`> 0` guard trips).
- **Cost for dwell > 0:** first post-restart tick behaves correctly *if* the persisted
  `_became_occupied_time` is present. If persistence gap (e.g. room STATE_OCCUPIED was False
  right before restart and became True during the restore race), fall back to `now` — one
  dwell of extra hysteresis on first post-boot cycle. Bounded.
- **Do NOT add HVAC-specific persistence in v1.** The LIGHTING `_became_occupied_time` already
  round-trips through DAO + RestoreEntity; we piggyback READ-only. Persisting `_hvac_arm_since`
  or `_hvac_last_released` would need a matching HVAC RestoreEntity + boot handoff for
  bounded win — card as residual only if the probe (§7) shows restart-induced misses matter.

## 7. MEASURE FIRST (per `feedback_measure_before_build.md`)

Trigger check (any yes → probe first): the dwell value depends on empirically unknown
distributions of transit vs stay durations. Qualifies.

**Probe** — read-only, one-shot, over recorder + `ura_activity_log`. Ship as
`scripts/probes/hvac_entry_dwell_hvac_clock_probe.py`.

Inputs (7-day window, per HVAC zone, cold-entry episodes: zone transitions
`any_room_hvac_occupied` False → True with ≥ 20 min of prior False):

1. **Per-episode arming-room raw evidence duration.** For the room that armed the episode,
   measure how long the underlying raw presence/motion sensor(s) stayed continuously ON
   from the arm-onset. Distribution: p20 / p50 / p80 / p95 + histogram at
   30 s / 1 min / 2 min / 5 min / 10 min. This IS the dwell sizing curve.
2. **Zone-flip count a given dwell would have prevented.** For candidate dwell
   `d ∈ {0, 30 s, 60 s, 90 s, 2 min, 3 min}` count episodes where (a) an S1 preset write
   fired within `d` of the anchor, AND (b) the zone went `vacant_past_grace` back to away
   within 20 min. Report as flips/week per zone.
3. **Cost side — added HOLD minutes AND added ACT latency.** For each candidate dwell,
   compute both (i) total zone-minutes at the wrong preset while dwell HELD, (ii)
   distribution of added latency-to-ACT for real entries (from the analytic model in §5,
   parameterised by the observed τ distribution from tick timing).
4. **Live vacancy grace context** (state-of-play §8: 10 min live / 5 min energy-saving);
   frame flap-cost in conditioning-minutes and $ in the probe.

**Go/no-go gate.** Only proceed to D1 build if the probe shows flap-rate material
(~2/day/zone at some candidate dwell) AND added-latency cost is tolerable (< ~1.5 min added
mean, < 6 min worst-case). Otherwise close `investigating → parked` with the probe report;
leave the knob at 0.

**Hand-built acceptance fixture** (per corollary): before automating D1 tests, hand-construct
3 real episodes from the probe (one transit, one genuine cold entry, one restart-crossing)
and commit as JSON under `quality/tests/hvac/fixtures/entry_dwell/`.

## 8. Producer + Consumer map

### Producer — `_hvac_arm_since[room]` (NEW, `hvac_zones.py:1075-1123`)

Arithmetic: on the rising-edge branch (`:1075-1080`), compute
```
anchor = coordinator.get_became_occupied_time()
if anchor is None:
    anchor = self._hvac_last_released.get(room_name) or now
released = self._hvac_last_released.get(room_name)
if released is not None and anchor < released:
    anchor = released
self._hvac_arm_since[room_name] = anchor
self._hvac_last_released.pop(room_name, None)  # consumed
```
On the two release paths (`:1108-1110`, `:1120-1121`) set
`self._hvac_last_released[room_name] = now` and pop `_hvac_arm_since[room_name]`. On the
`held` branch (`:1090-1095`) do NOTHING — the anchor is stable.

Dependency health: `get_became_occupied_time()` is populated on every STATE_OCCUPIED rising
edge and persisted (see prior-art table). Coordinator-absent rooms are excluded upstream at
`hvac_zones.py:680-711`; hallways at `:724-735`.

Derived zone-level clock (inline in Row-2 loop):
`zone.hvac_entry_since = min(_hvac_arm_since[r] for r in zone.rooms if _hvac_armed.get(r))`
or `None`.

### Consumers of `zone.hvac_entry_since` — exhaustive (post-cycle)

| # | Consumer | Site | Trust vs display |
|---|---|---|---|
| 1 | Dwell skip (moved) | `hvac.py:2438-2451` — swap `zone.any_room_occupied` → `zone.any_room_hvac_occupied`, swap `zone.current_session_start` → `zone.hvac_entry_since` | Trust |
| 2 | Zone-status sensor attribute `hvac_entry_since_iso` | `hvac_zones.py:751` (sensor attrs) | Display |
| 3 | `preset_change_suppressed` row payload (`reason=entry_dwell_hvac`) | new emit at the `continue` in `hvac.py:2451`; dedup keyed on (`zone_id`, `zone.hvac_entry_since`) via `_dwell_suppressed_episode_key[zone_id]` | Observability |

**Row 2d `zone.current_session_start` writer remains** — untouched (kept for observability
+ Review D regression baseline). Only its consumer moves.

**Adjacent invariants that MUST NOT regress:** `zone.last_occupied_time`,
`zone.continuous_occupied_since`, `zone.vacancy_sweep_done`, `zone.any_room_hvac_occupied`,
`_compute_hvac_occupied` outputs, `is_zone_hvac_established`, `conditioning_retreat_ok`,
`_hvac_seen`, `_hvac_armed`, `_effective_hvac_hold_seconds`.

## 9. Interaction matrix (edge cases)

| # | Case | Behaviour required | How this design meets it |
|---|---|---|---|
| E1 | Hallway is the only occupied room | Zone stays HOLD-eligible-but-not-armed; dwell gate not reached | Hallway short-circuit at `:724-735` sets `_hvac_armed[hall]=False` — no arm-since entry. `any_room_hvac_occupied=False` → dwell branch's own gate fails. |
| E2 | Bedroom rising edge at t0, kitchen rising edge at t0+30 s (still in dwell) | Zone clock = t0 | `hvac_entry_since = min(t0, t0+30 s) = t0`. |
| E3 | Earliest room drops to tail-hold mid-episode | Zone clock MUST NOT jump forward | Tail keeps `_hvac_armed=True`; its `_hvac_arm_since` stays; `min` unchanged. |
| E4 | Earliest room's tail expires, then that same room re-arms 10 s later while lighting held STATE_OCCUPIED throughout (so `_became_occupied_time` is stale/old) | Zone clock uses the FRESH HVAC arm, not the old lighting session start | Release site writes `_hvac_last_released[room] = now` at `:1120-1121`; next rising edge clamps `anchor = max(get_became_occupied_time(), _hvac_last_released[room])` = the release time. **Discriminates:** without clamp, would inherit the stale timestamp. |
| E5 | Earliest room's tail expires while another room stays armed | Zone clock advances to next-earliest armed | Released room's arm-since popped; `min` recomputes. Correct (person who held the episode is gone; the remaining occupant defines the session going forward). Cost bounded by tail-hold. |
| E6 | Person leaves fully, tail runs out, zone empty, returns 10 s later | Fresh episode, fresh dwell | All arm-since cleared on last release; new rising edge stamps new anchor (clamped by fresh `_hvac_last_released`). |
| E7 | Rising edge tick with `get_became_occupied_time()` returning `None` (intra-tick race) | Do NOT crash; do NOT eternally hold | Fallback: `_hvac_last_released[room] or now`. One-tick degradation to today's behaviour. |
| E8 | Pre-arrival zone | Exempt at `hvac.py:2448` | Unchanged. |
| E9 | Target preset "away" | Exempt at `hvac.py:2449` | Unchanged. |
| E10 | v5.103.15 excluded / transient room in the zone | Contributes nothing | Not reached in producer loop. |
| E11 | Restart mid-episode | For dwell = 0 no-op; for dwell > 0 anchor recovers pre-restart raw-evidence timestamp via persisted `_became_occupied_time` → first post-boot tick can ACT immediately if `now - anchor ≥ dwell` | §6. If persistence race leaves timestamp None: fall back to `now`, one dwell of extra hysteresis on first tick. |
| E12 | Override-occupied via `switch.<room>_override_occupied` (§9c) | Behaves as raw presence | Override sets `data[STATE_OCCUPIED]=True` at `coordinator.py:4791-4811`, which drives `_became_occupied_time` (:4797) — same anchor path. |
| E13 | Coordinator loads late | Contributes nothing until first `_compute_hvac_occupied` | Same as today's `_hvac_seen`. |

## 10. Knob (numbers-get-knobs)

**Reused** knob: `number.ura_hvac_coordinator_zone_entry_dwell` (option `hvac_zone_entry_dwell`,
minutes integer, RestoreEntity, rung-3 live-tunable, live **0**). Kill-switch preserved
by guard `dwell_minutes > 0` at `hvac.py:2442`.

**Recommended value on ship: leave at 0 pending probe.** If the probe justifies non-zero,
expected landing zone `{60 s, 90 s, 120 s}`. Sub-minute values require a knob-unit residual
card (minute-granular today).

**With dwell = 0 nothing changes.** Guard trips, dwell branch is skipped, gate-signal swap
is BEHIND the guard, observability emit is inside the branch. Strict expansion of vocabulary,
not a behaviour change at knob=0.

## 11. Deliverables

### D0 — Probe (measure-before-build gate)
`scripts/probes/hvac_entry_dwell_hvac_clock_probe.py` per §7. **Acceptance:** runs read-only;
per-zone histograms + flap counts + latency analytics at 6 candidate dwells; report committed
to this doc; go/no-go before D1.

### D1 — Raw-edge anchor producer + zone-level clock (with clamp)
File: `domain_coordinators/hvac_zones.py`.
- Add `self._hvac_arm_since: dict[str, datetime] = {}` and
  `self._hvac_last_released: dict[str, datetime] = {}` next to `self._hvac_armed`.
- Pass `coordinator` (already in scope at `:668`) INTO `_compute_hvac_occupied` OR read the
  anchor before the call (preferred: read before call, pass `arm_anchor` kwarg, keep the
  state-machine pure).
- Rising-edge branch (`:1075-1080`): compute clamped anchor per §8, write
  `_hvac_arm_since[room]`, pop from `_hvac_last_released`.
- Release sites (`:1108-1110`, `:1120-1121`): set `_hvac_last_released[room] = now`, pop
  `_hvac_arm_since[room]`.
- Row-2 (`:783-788` area, kept intact for LIGHTING clock): add sibling write
  `zone.hvac_entry_since = min(...)` or `None`. New field on the zone dataclass.
- Publish `hvac_entry_since_iso` on the zone-status sensor at `:751`.

#### Acceptance
- **Verify:** on rising-edge tick with `get_became_occupied_time()` = T_raw, no prior release,
  `_hvac_arm_since[room]` == T_raw (NOT `now`).
- **Verify:** E4 clamp — after a release at T_rel and a rising edge with
  `get_became_occupied_time()` = T_raw < T_rel, `_hvac_arm_since[room]` == T_rel.
- **Verify:** on tail entry (state_occupied False, no expiry yet), arm-since UNCHANGED.
- **Verify:** on tail-expiry release, `_hvac_last_released[room]` == release-time and
  `_hvac_arm_since[room]` popped.
- **Verify:** zone-level `hvac_entry_since` is `min` over currently-armed rooms.
- **Test:** `quality/tests/hvac/test_hvac_arm_since.py` covers E1–E13. Fake room coordinator
  exposes configurable `get_became_occupied_time()`; timelines drive `_compute_hvac_occupied`.
- **Test:** mutation drills (Review C): (a) drop the clamp `max()` → E4 must fail;
  (b) delete the release-site `_hvac_last_released` write → E4 must fail;
  (c) anchor on `now` instead of accessor → the "raw-edge preserves pre-tick presence" test
  must fail; restore each.

### D2 — Dwell skip on HVAC clock + observability
File: `hvac.py:2438-2451`.
- Swap `zone.any_room_occupied` → `zone.any_room_hvac_occupied` at `:2445`.
- Swap `zone.current_session_start` → `zone.hvac_entry_since` at `:2446-2447`.
- Keep guard `dwell_minutes > 0`, `_pre_arrival_zones` and `effective_preset != "away"`
  exemptions, comparator arithmetic (`< dwell_minutes * 60`).
- Emit ONE `preset_change_suppressed` row per (zone_id, `zone.hvac_entry_since`) via
  `ura_activity_log`; dedup dict cleared when `hvac_entry_since` is `None`. Payload:
  `{zone_id, current_preset, target_preset, hvac_entry_since_iso, age_seconds,
  dwell_minutes, reason: "entry_dwell_hvac"}`.

#### Acceptance
- **Verify:** with `dwell_minutes=0`, code path functionally identical to today. **Discriminates:**
  any behaviour change at knob=0 fails.
- **Verify:** with `dwell_minutes=1`, room's raw evidence started 90 s before tick → first
  observing tick ACTS (writes preset). **Discriminates:** producer-tick-anchor regression
  would still SKIP here.
- **Verify:** with `dwell_minutes=1`, room's raw evidence started 30 s before tick → SKIPS,
  ONE `preset_change_suppressed` emit.
- **Verify:** hallway-only zone (E1) — dwell branch unreachable.
- **Verify:** mid-episode room-vacate leaves `zone.hvac_entry_since` UNCHANGED (E3).
- **Test:** `quality/tests/hvac/test_hvac_entry_dwell_hvac_clock.py` matrix
  {dwell ∈ {0, 60 s}} × {house_state × away × pre_arrival} × E1..E13.
- **Test:** mutation drills: (a) drop the guard → the "no-op at knob=0" test must fail;
  (b) drop the dedup → "one row per episode" test must fail; restore each.
- **Live:** `ura_activity_log` shows `preset_change_suppressed` with `reason=entry_dwell_hvac`
  (0 rows at knob=0; > 0 at knob > 0).
- **Live:** `sensor.ura_hvac_coordinator_zone_{n}_status` attribute `hvac_entry_since_iso`
  matches `min` over the zone's armed rooms.

### D3 — README write-back on close
`docs/readmes/README_v<version>.md`: prospective bullets replaced post-restart with a
`Validated <date>` table: knob value, per-zone `hvac_entry_since` observed for one entry,
one `preset_change_suppressed` row observed, one hallway-only zone showing gate not entered,
one E4 clamp scenario if the probe found one, and the probe's ex-post flap-rate at the
shipped dwell.

## 12. Discriminating acceptance

| Observation under the fix | Different failure it rules out |
|---|---|
| Dwell = 0: zero `preset_change_suppressed` rows over 24 h, zero preset-decision diffs vs pre-cycle | Any behaviour-affecting change slipped past the guard. |
| Dwell = 60 s, room raw evidence 90 s old at first tick: **ACT** | Producer-tick-anchor regression (would SKIP). |
| Dwell = 60 s, hallway-only tick: gate not entered | LIGHTING-clock v1 regression (would enter + skip). |
| Dwell = 60 s, E4 (release then re-arm with stale `_became_occupied_time`): anchor = release-time, not the stale timestamp | Missing clamp — would inherit stale lighting-session start. |
| Dwell = 60 s, mid-episode room-vacate: `hvac_entry_since` UNCHANGED across the vacate tick | Naive `min` over `any_room_hvac_occupied` set would advance the clock. |
| Post-restart, currently-present room whose `_became_occupied_time` was persisted 1 h ago: first HVAC tick ACTS | Persistence not consumed → would treat as fresh arm, SKIP for D minutes. |
| `preset_change_suppressed` fires exactly ONCE per episode (dedup keyed on `hvac_entry_since`) | Missing dedup would firehose rows every 5 min. |

## 13. Tier + review framings (Tier 2-DB, three disjoint + D live)

- **A — Local correctness.** Anchor arithmetic (accessor read, clamp, fallback), None-
  safety, comparator boundary (`<` vs `≤`), seconds-vs-minutes at `hvac.py:2447`, dedup key
  correctness, guard-clause independence.
- **B — Cross-coordinator + lifecycle.** Interaction with tail-hold (E3–E5), D5/D6/D7/D8,
  pre-arrival exemption, restart semantics (§6 — persisted `_became_occupied_time` recovery),
  race between coordinator `_became_occupied_time` set/clear and HVAC producer read,
  `_hvac_armed` invariants unchanged, ordering inside `_compute_hvac_occupied`.
- **C — Test authority + consumer completeness.** Re-grep `hvac_entry_since` /
  `_hvac_arm_since` / `_hvac_last_released` / `any_room_hvac_occupied` consumers; source-
  mutation drills per D1/D2; hand-built fixture drive.
- **D — Adversarial completeness + live validation.** Encode §2 invariant; enumerate the
  reachable tuple space including the E4 clamp path; propose a legal-config repro for any
  suspected leak; post-restart replay one real entry + one real transit + one hallway-only
  tick + one E4 candidate from the probe timelines.

## 14. What the builder will get wrong (predicted; call these out in the build brief)

1. **Anchoring on `now` instead of the accessor** — recreates the producer-tick failure the
   orchestrator caught. **Anchor:** "raw-edge preserves pre-tick presence" test.
2. **Dropping the clamp** — E4 fails; stale lighting sessions backdate. **Anchor:** E4 test.
3. **Missing the two release-site writes** — `_hvac_last_released` stays empty, clamp
   degenerates to accessor. **Anchor:** E4 test.
4. **Writing `_hvac_arm_since` on the `held` branch** (`:1090-1095`) — every held tick
   refreshes the anchor to a fresh accessor read (post-clamp still forward-moving on later
   ticks); dwell would never fire mid-episode. **Anchor:** E3 test (arm-since UNCHANGED).
5. **Popping `_hvac_last_released` on release instead of on next arm** — clamp missed on
   next arm. **Anchor:** E4 test.
6. **Recomputing zone `hvac_entry_since` from `any_room_hvac_occupied` set** instead of the
   `_hvac_armed` set. **Anchor:** E5 test.
7. **Forgetting the guard `dwell_minutes > 0`** and swapping signals unconditionally →
   breaks the "knob=0 is a no-op" contract.
8. **Emitting `preset_change_suppressed` every 5-min tick** — dedup MUST be keyed on
   `hvac_entry_since`.
9. **Leaving Row-2d LIGHTING writer wired to the reader** (partial swap). Grep both symbols
   post-edit.
10. **Adding HVAC-specific persistence** for `_hvac_arm_since` / `_hvac_last_released`.
    Out of scope; rely on LIGHTING `_became_occupied_time` persistence + bounded restart cost.
11. **Subscribing to raw presence/motion entities directly.** No new listener; the room
    coordinator has already fused them and given us the rising-edge timestamp.

---

## Plan summary (report-out to operator)

**Delta from first draft:** the producer-tick-of-arming anchor recreated C18 (first observing
tick has age 0 → dwell always skips for any dwell > 0 → write lands +5 min). REWRITTEN.

**Arm-onset choice:** clamped raw-evidence rising edge —
`_hvac_arm_since[room] = max(coordinator.get_became_occupied_time(room), _hvac_last_released[room])`
snapshotted at the `_hvac_armed False → True` transition. Evidence:
1. The producer arms on the rising edge of `state_occupied` (`hvac_zones.py:1075-1080`), which
   IS the room coordinator's STATE_OCCUPIED. STATE_OCCUPIED's rising edge is raw evidence
   (lighting timeouts extend only the falling side). Its wall-clock rising-edge timestamp is
   `_became_occupied_time` (public accessor `coordinator.py:5384-5395`, set at the 5 rising-
   edge sites, cleared at 5 vacant-edge sites, persisted via URA's DAO + RestoreEntity).
   Same rising edge that drives HVAC arming → HVAC's own raw evidence, in HVAC's denomination.
2. Clamp against `_hvac_last_released[room]` (written at the two release sites `:1108-1110`
   and `:1120-1121`) prevents a stale lighting session (STATE_OCCUPIED held True through an
   HVAC tail-release-then-re-arm) from backdating a fresh HVAC arm.
3. Hallways excluded by construction (`:724-735` short-circuit — never reach arm).
4. First tick can ACT if the person has been present ≥ dwell before the tick; a transit
   whose evidence expired before any tick observed it never arms → filtered anyway.
5. Rejected: producer tick anchor (C18); LIGHTING `zone.current_session_start` (falling-side
   extension); Row 2a/2c (wrong reset semantics); direct HA raw-entity state trackers
   (equivalent semantics, adds listener surface — carded as residual).

**Updated latency:** with raw-edge anchor and dwell D, first observing tick ACTs iff
raw-evidence age ≥ D. Under uniform tick timing E[τ]=2.5 min: D=1 min → mean 3.1 / worst
6 min; D=2 min → mean 3.5 / worst 7 min; D=3 min → mean 4.1 / worst 8 min. (Producer-tick
anchor would have been mean 7.5 / worst 10 min at any D > 0.)

**Scope shape:** MEASURE FIRST (§7 probe) → D1 producer (arm-since + last-released + zone
rollup + sensor attr) → D2 reader swap + observability row → D3 README write-back. Knob
stays 0; nothing changes at knob=0. Tier 2-DB, three framing-disjoint reviews + Review D.
Non-goals + restart bounds unchanged.

---

**Files that will change** (absolute paths):
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac_zones.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac.py`
- `/Users/okosisi/Code/universal-room-automation/quality/tests/hvac/test_hvac_arm_since.py` (new)
- `/Users/okosisi/Code/universal-room-automation/quality/tests/hvac/test_hvac_entry_dwell_hvac_clock.py` (new)
- `/Users/okosisi/Code/universal-room-automation/quality/tests/hvac/fixtures/entry_dwell/*.json` (new, hand-built from probe)
- `/Users/okosisi/Code/universal-room-automation/scripts/probes/hvac_entry_dwell_hvac_clock_probe.py` (new)
- `/Users/okosisi/Code/universal-room-automation/docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (§3.2 dwell row + §10 corrections ledger, same commit as ship)
- `/Users/okosisi/Code/universal-room-automation/docs/readmes/README_v<version>.md` (new, per D3)
