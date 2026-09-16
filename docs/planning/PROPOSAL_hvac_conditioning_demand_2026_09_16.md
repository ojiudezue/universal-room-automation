# HVAC Conditioning Demand — Proposal & Digest

**Card:** `HVAC-ZONE-CONDITIONING-DEMAND-1` (step 4 of `HVAC-SUPPLE-SEQUENCE-1`)
**Status:** pre-planning · Tier 2-DB · **not yet built**
**Date:** 2026-09-16
**Read this before the operator checkpoint.** It carries the full hypothesis
history (including two dead ends), what the measurements actually said, the
proposal, and the honest caveats.

---

## 1. The problem, in one paragraph

HVAC decides whether to condition a zone by reading an occupancy signal that was
designed for a *different* job — switching lights. Lighting needs a generous hold
(≈5–9 min after last motion) so a lamp never blinks off on someone sitting still.
HVAC inherits that held signal, so a two-second walk through a hallway looks
identical to someone settling in for the evening. The 5-minute guard meant to
filter transit sits *downstream* of that 5–9-minute smoother, so it cannot win.
Result: rooms get conditioned that nobody stayed in.

**Measured cost (zone_3, 7 days):** ~15 pointless conditioning episodes/day, at a
median duration of *exactly* `vacancy_grace` (10 min). This is the single
cleanest number we have.

---

## 2. What "success" means (defined up front, operator-set)

Two metrics that **must move together** — either one alone is gameable:

- **(A) Fits like a glove (comfort):**
  - **A1 Spurious-away count** → target zero. *(Today unfalsifiable in zone_3 —
    no independent presence witness. The lockout telemetry shipped in v5.103.4
    and the guest/person work are what make this measurable.)*
  - **A2 Time-to-condition on entry** into an out-of-band zone → p90 below the
    point a human intervenes (founding incident: occupant at the thermostat in
    ~2.5 min).
  - **A3 Pointless-conditioning episodes** → large reduction. This is the
    cleanest single number (15/day in zone_3 today).
- **(B) Saves net $ (energy, honestly):**
  - **B1 Compressor runtime per cooling-degree-day, per zone.** Raw kWh is *not*
    acceptable — it's dominated by weather. Degree-day normalization is what makes
    a months-to-years claim real.
  - **B2 The same figure in $ against the TOU rate in force.**
  - **B3 No increase in compressor cycle count** (short-cycling is an
    equipment-life cost a runtime-only metric hides).

Baseline for all of the above was captured **before any build** (step 3, done).

---

## 3. Hypothesis history — including the two dead ends

The design moved three times. The dead ends matter because they're the reason the
surviving proposal looks the way it does.

### H1 — "Strip the lighting hold; HVAC reads the raw body signal + a duration dwell." **FALSIFIED.**

Operator asked for a simulation first ("assume an optimistic result and model
it"). The optimistic framing is what made it decisive — even the upper bound
fails.

Question modeled: *what fraction of raw activations last 5 minutes?*

| room | raw activations (7d) | median | max | under 5-min dwell |
|---|---|---|---|---|
| Garage Hallway (transit) | 152 | 0.5 min | 2.6 min | **100%** |
| Guest Bedroom 1 (dwell) | 11 | 1.1 min | 4.1 min | **100%** |

**The dwelling room also never sustains 5 minutes.** So the tap would have
filtered the bedroom too — a sleeping guest never satisfies dwell, the zone never
goes home, the room sits at the ~80°F away ceiling all night. That is a comfort
failure *worse* than the one it fixes.

It also corrected a wrong premise of mine: the room clearance timeout is **not** a
lighting artifact to discard. These sensors emit *sparse detection events* — a
sleeping body produces almost nothing. The hold is what converts sparse detections
into a usable continuous signal. Strip it and you get blips no timer can use.

The obvious alternative (recurrence: ≥3 detections clustered in 10 min) fails too,
and **inverted** — the transit corridor produced *longer, more clustered* sessions
(median 6.3 min, max 25.8) than the bedroom (median 1.0, max 4.5). Neither
duration nor recurrence separates transit from dwell.

**Honest limit:** Guest Bedroom 1 had 8 sessions in 7 days, 4.5-min max — there was
**no actual dwelling in the sample** (a guest room with no guest). So the dwell
half is not *refuted*, it's *untested*. The transit half is solid.

### H2 — "Drive HVAC from person-seen-in-zone / BLE." **Conceded flaky.**

Operator: *"Isn't this just a different tap? I'd be careful of raw sensor
dependency since there is no machinery for so many things that make this flaky."*
Correct. BLE has intra-floor leakage — we already have a card where BLE bleed held
a bathroom occupied for 441 minutes. It swaps one flaky raw dependency for another.

The deeper point: **raw signals are flaky precisely because the machinery lives
above them.** `room.occupied` is usable *because* of exclusion, chatter detection,
grace-hold, mmWave demotion, fan-phantom gating. Any raw tap throws all of that
away and has to rebuild it.

### H3 — "The zone occupancy is a flat OR across ~12 rooms, most of them corridors." **The survivor.**

Re-derived from what was measured rather than from a new input:

- The room signal is **not wrong** — someone *was* in the hallway.
- The defect is that a zone demands conditioning whenever anyone crosses **any**
  room in it, and zones contain transit corridors.
- zone_3's 15 pointless episodes/day at a median of *exactly* `vacancy_grace`, and
  the transit corridor producing the clustered sessions, are both consistent with
  **corridor crossings flipping the whole zone occupied** — an aggregation defect,
  not a fidelity defect.

This needs **no raw tap** (reuses the fully-machined `room.occupied`) and doesn't
depend on separating transit from dwell by duration (which H1 proved impossible).

---

## 4. The skeptical catch that reshaped H3

H3 needs to know which rooms are *circulation* vs *dwelling*. Room classification
already exists (`CONF_ROOM_TYPE`) — **but its values are room *purpose*, not
circulation-vs-dwelling**, and they do not separate the two:

| `room_type` (live) | rooms |
|---|---|
| `common_area` (15) | **Garage Hallway, Kitchen Hallway, Kitchen Hallway Garage, Master Hallway, Upstairs Hallway, Foyer** (transit) — *lumped with* — Living Room, Dining Room, Kitchen, Breakfast Nook, Game Room, Exercise Room, Patio, Receiving Room, Butler Pantry (dwelling) |
| bedroom (6), bathroom (7), closet (7), garage (2), generic (2), media_room (1), utility (2), infrastructure (1) | — |

So **H3 is not a pure compose** — there is no field that separates a hallway from
the Living Room. It needs exactly one new distinction. That is the whole build.

---

## 5. The proposal

### Stage 0 — CONFIRM before building (measurement, ~1 recorder query)

Attribute zone_3's pointless conditioning episodes to room role: do they coincide
with **Garage Hallway** occupancy and *not* guest-bedroom occupancy?
- **If yes** → H3 confirmed and discriminating → Stage A.
- **If the episodes track the bedrooms instead** → H3 is wrong → stop, don't build.

This is the gate. It has **not** been run yet.

### Stage A — Per-room HVAC-occupancy sensor with its own timer (the core change)

> **Revised 2026-09-16 (operator).** The original Stage A was a *binary circulation
> exclusion* (mark ~6 hallways, they stop voting). The operator generalized it, and
> the generalization is better — recorded here; the binary version is retired into a
> special case of this one.

Expose a **second, HVAC-specific occupancy view per room**, with its **own per-room
hold** (a decay *duration* — how long HVAC-occupancy persists after the signal
drops), separate from the `occupancy_timeout` that drives lights/automations. One
signal drives automations; the other drives HVAC.

> **Precision (operator, 2026-09-16): a hold is not a timer loop.** A *hold* is a
> duration a state persists, evaluated on whatever tick runs. A *loop/tick* is the
> evaluation cadence. They are orthogonal, and this Stage A is entirely about the
> **hold** (what the HVAC-occupancy state is). It does **not** change how fast HVAC
> reacts — that is the loop, and it is Stage-D's problem (§ fast-in), not this
> sensor's. Do not sell the per-room hold as improving reaction latency; it can't.

**Why this beats binary circulation exclusion:**
- **Handles the kitchen** — a room that is *both* circulation and a legit
  short-dwell space. Binary exclude loses its automation needs; a per-room HVAC
  dwell tunes it.
- **Subsumes circulation** — a pure hallway is simply a room whose HVAC-occupancy
  is off (or whose HVAC dwell is set so transit never qualifies). No new
  `room_type` value, no separate flag. (This answers "map to the room_type
  unification?" — **no**: `room_type` is *purpose* and feeds `ROOM_TYPE_TIMEOUTS` /
  `_FAILSAFE_DURATIONS` / `_FEATURE_DEFAULTS`; overloading it would ripple. The
  distinction lives on the per-room HVAC timer instead.)
- **Proven prior art — extend, don't invent.** `CONF_FAN_VACANCY_HOLD` (300s,
  per-room configurable; `const.py:966,1153`) is *exactly* this pattern: a second,
  consumer-specific hold stacked on the room's `occupancy_timeout`. Fans already do
  "one timer for me, a different one for the room." HVAC extends the same pattern.

**The layered shape (this is the skeptical part):** a per-room *duration* timer
alone does **not** separate transit from dwell in a **busy corridor** — measured:
the transit corridor produced *longer* clustered sessions (max 25.8 min) than the
bedroom (max 4.5). Repeated crossings defeat any duration threshold. So the HVAC
sensor's **input** cannot be "the fused signal held longer/shorter":

- **Input** = kind-aware presence, applied **on top of the room's already-grace-held
  `STATE_OCCUPIED`** — NOT raw `substrate.is_kind_active` (audit finding #7: a raw
  read bypasses `grace_hold` at `coordinator.py:3581` and drops occupancy on a sensor
  blip, reintroducing the H1 sparse-dropout failure). So: mmWave *stillness* where
  available, known-occupier BLE anchor, else the fused signal — all filtered over the
  grace-held occupied, never the raw substrate.
- **Hold** = the per-room HVAC decay duration (the `fan_vacancy_hold` pattern) —
  governs adopt-dwell and retreat *persistence*. NOT reaction cadence (that's the
  loop, § Stage D).

**Wire it by SWAPPING THE INPUT, not adding a parallel field** (audit finding #4):
`RoomCondition.occupied` is fed from the lighting-fused `coordinator.data["occupied"]`
at `hvac_zones.py:546`, and 12+ HVAC-path sites already read `RoomCondition.occupied`.
Change *what feeds it* (a room-level HVAC-occupancy view) rather than adding a parallel
`RoomCondition.hvac_occupied` that all 12 consumers must be taught to read. That single
mutation point (`hvac_zones.py:546`) IS the whole ripple. (Full audit:
`AUDIT_hvac_conditioning_demand_supersession_and_reuse_2026_09_16.md`.)

The hold is the per-room flexibility; the kind-aware input is what lets it separate
transit from dwell where duration can't. Reuses `room.occupied`'s fused, machined
signal (exclusion / chatter / grace-hold / mmWave-demotion all intact); consumed at
the one existing zone rollup site; lights untouched.

**Knob placement (operator-decided 2026-09-16):**
- **(a) Exposure: EXPOSE the per-room HVAC-occupancy entity** (operator: "it has to
  be observable"). It is a trust input; it must be visible. (Overrides the earlier
  internal-only lean.)
- **(b) Defaults per room type:** add a `ROOM_TYPE_HVAC_HOLD` table keyed by
  `room_type`, exactly like `ROOM_TYPE_TIMEOUTS` (`const.py:1171`), so bedroom /
  kitchen / hallway get sane defaults out of the box; a per-room config field
  (mirroring `CONF_FAN_VACANCY_HOLD`) overrides only exceptions.
- **(c) Add `hallway` to the room_type enum.** Verified safe: every `ROOM_TYPE_*`
  table reads via `.get(type, DEFAULT)` (`coordinator.py:695,3814`,
  `presence_fan_recheck.py:1102`), so a new value cannot KeyError; the selector is a
  hand-built list (`config_flow.py:1387`). Cost = one const + one selector line +
  hallway-specific entries only where it should differ (HVAC-occupancy off/minimal,
  short `occupancy_timeout`). Fixes the root data problem: the 6 hallways currently
  mis-typed as `common_area` get separated from Living Room / Dining / Kitchen.
  **Migration note:** the enum change does not auto-retype existing rooms — the
  operator reclassifies the 6 hallways by hand (a config edit). Extends the shipped
  `ROOM-CLASSIFICATION-CONSISTENCY-1` work; check that card for a parked
  missing-types deliverable before building.

### Stage A′ — Zone-level aggregation of the per-room signals (the piece I'd missed)

**Operator caught this gap 2026-09-16:** if each room has its own HVAC dwell/hold,
how does it sum to a zone decision? HVAC decides at the *zone* (thermostat)
granularity, and — verified in code — HVAC `ZoneState` enumerates its member rooms
*directly* (`zone.rooms`) and computes `any_room_occupied = any(r.occupied ...)`, a
pure OR (`hvac_zones.py:148`). House-zones do **not** enter HVAC aggregation; the
HVAC zone keeps its own room membership (which is why HVAC-zone ≠ house-zone). The
plan swaps the per-room *input* from the lighting-held `occupied` to the room's
HVAC-occupancy signal; the aggregation answer is **asymmetric, not a single
LCD/HCD choice:**

- **Entry (adopt conditioning) = first room to qualify** (OR / min). Zone conditions
  as soon as any member room's HVAC-occupancy flips true. Fast-in latency = that
  room's dwell-to-enter + one loop tick. Per-room dwell and loop cadence are
  independent: dwell decides *when a room contributes*; the loop decides *how often
  the zone re-reads the OR*.
- **Exit (retreat) = last room to clear** (max), then the zone retreat timer. Never
  abandon a zone while any member room still holds.

**Four decisions (recommendations):**
1. **Aggregation = OR** over HVAC-relevant rooms. Hallways drop out by having
   HVAC-occupancy off — not by a special-case rule. OR, never AND (AND would only
   condition when every room is full).
2. **Dwell-to-enter moves per-room; RETIRE the zone-level `zone_entry_dwell`
   (live 5 min).** Otherwise per-room dwell + zone dwell stack (e.g. 4+5=9 min) and
   defeat fast-in. This changes a live timer — call it out at the checkpoint.
3. **Retreat stays zone-level: keep `vacancy_grace` (10 min) as the single exit
   timer.** Per-room *holds* stay short (bridge mmWave dropout only), NOT second
   retreat timers — stacking two long holds makes exit latency unreasonable.
   Optional per-room "hold longer" override for a case like a bedroom overnight.
4. **The 60 s fast sub-loop reads the same zone OR**, just more often, for the
   hot-and-occupied case.

Net: dwell is per-room (the flexibility), retreat is one zone timer (reasoning stays
simple), entry is responsive, exit is conservative.

### Stage B — Within-room stillness (refinement, only if needed, measurement-gated)

If Stage A leaves residual pointless conditioning inside dwelling rooms from brief
entries, use the mmWave stillness kind (verified readable — see §6) to distinguish
a settled body from a passing one.
**Skeptical gate:** this house's mmWave is known to drop out during true stillness
(kitchen / Jaya memory). Stage B is gated on measuring that mmWave-occupancy *gaps*
during real dwelling are shorter than `vacancy_grace` — else it strands.

### Stage C — Guest-as-zone-person + BLE anchor + pre-cool

For the guest wing (no assigned residents) and pre-arrival. This is
`HVAC-GUEST-AS-ZONE-PERSON-1` (already carded, operator's own idea) — derive a
*dynamic* zone person from an occupied guest room with an explicit liveness/decay
contract. Not a stubbed dummy (rejected — a fiction defeats a trust gate).

### Stage D — Fast-in (the loop problem, NOT a hold)

The 5-minute decision tick is a **hard floor** on "react quickly if it's hot." Even
at dwell=0, worst-case latency to act is a full tick; the founding incident had the
occupant at the thermostat in ~2.5 min. **No hold and no demand-signal fixes this**
— reaction latency is set by the *loop cadence*, not by any state-persistence
duration (see the hold-vs-loop precision note in Stage A). Fast-in needs a faster
loop or an event path.

**Prior art (operator): a subsystem already runs a dedicated faster sub-loop.**
Energy runs a 5-min decision loop **plus a separate 60 s `_solar_follow` sub-loop**
(`energy.py:1382`, `SOLAR_FOLLOW_TICK_S`; `energy_const.py:1007,1016`). "One
coordinator, two cadences" is a proven in-repo pattern.

**Three options considered — recommendation is the middle one:**

1. **Reduce the whole HVAC loop to 60 s.** Rejected. 5× evaluations/hour → 5×
   activity-log + anomaly-detection DB volume, 5× compute, 5× *opportunities* to
   write Carrier cloud (change-gated, so not 5× writes, but more chances — and there
   is a reload-storm / write-sensitivity history). Reading faster than Carrier's own
   42–79 s refresh gains nothing. Only the hot-and-occupied case needs 60 s; ~95% of
   decisions are fine at 5 min. 5× cost for a narrow benefit.
2. **Dedicated 60 s HVAC fast sub-loop (RECOMMENDED)** — mirror `_solar_follow`. It
   evaluates *only* the hot-and-occupied fast-in decision (cheap, targeted), leaving
   the 5-min full cycle intact. Tightens both fast-in and retreat-latency (an expired
   hold is noticed within ~60 s, not up to 5 min). Proven pattern, bounded blast
   radius, no herd risk.
3. **Central URA loop / tick-multiplier abstraction.** Parked, not rejected — an
   appealing north star, and *cleaner* than the current pile of independent
   `async_track_time_interval`s when re-architecture comes.
   **Correction (operator, 2026-09-16): the thundering-herd objection was WRONG and
   is struck.** One base clock does NOT mean everything fires on the same tick — a
   tick-wheel gives each consumer a *divisor* (1×/30×/60×/300×) and a *phase offset*,
   so the herd is a solved design detail, not a risk. The honest reason to defer is
   **marginal benefit + it deserves to be a deliberate re-architecture, not bolted on
   for one fast-in need** — NOT stall risk. **Revival trigger:** a 3rd/4th fast
   sub-loop need appears, or a re-architecture pass opens → build the central
   tick-wheel then, with divisors + staggered offsets by design.

### Stage D design spec (operator, 2026-09-16) — for when it is built

Fast-in is DEFERRED, but the design is now pinned so it isn't re-derived:

- **Trigger = the preset bands, NOT a new temp threshold.** The home comfort band
  already defines "out of band"; fast-in fires when the zone temp is outside the
  home band. (The earlier "temp threshold" lever is RETRACTED — redundant with the
  bands. One fewer knob.)
- **Dwelling gate = the Stage-A demand signal, reused.** Continuous presence for X s
  via FUSION — mmWave continuous / PIR-continuous-for-X / BLE-claim-for-X-before-
  another-room-claims — not individual sensors. No separate gate. **HARD PLAN
  REQUIREMENT:** the Stage-D plan MUST detail BLE failure modes + how Bermuda works
  in detail (intra-floor bleed, the 441-min bathroom-bleed precedent, tier1-direct
  vs shared-scanner, claim latency), with a possible BLE exception.
- **Action = preset-driven by default; pre-cool = optional middle-ground knob.** The
  standing principle is preset-driven. Pre-cool is the gentle intermediate ramp (a
  middle preset step, applicable in BOTH directions) exposed as a knob — the same
  "middle step" as the trigger note above.
- **Pattern = zone-level analog of house-entry pre-cool.** `hvac.py:530` pre-arrival
  machinery (geofence/BLE/camera_face → person→zone routing → pre-cool) is the
  house-level version. The Stage-D plan MUST examine it and mirror-or-improve —
  reuse the pattern, flag any seams where the zone-level case wants something better.

Note on loop inventory (corrects a common mental model — it is not just HVAC + EC +
SC): ~10+ periodic loops exist at intentionally heterogeneous, jittered cadences —
room coordinator 30 s+jitter, census 30 s, `_solar_follow` 60 s, safety 60 s,
HVAC/energy/optimization 5 min, predictions 15 min, plus aggregation retry/decay,
sensor refreshers, perimeter/exterior sweeps. The heterogeneity is a feature, and it
is the argument against a single central loop.

---

## 6. Modality scan result (done 2026-09-16) — stillness IS readable

The infrastructure to read mmWave stillness exists in three places, all verified:

1. **Room substrate** — `occupancy_substrate.py`, per-room per-kind raw state, with
   `is_kind_active(room, "mmwave")`. Stored at
   `hass.data[DOMAIN]["occupancy_substrate"]` — globally reachable exactly like
   `person_coordinator`, so HVAC queries it with zero new wiring.
2. **Zone tracker** — `ZonePresenceTracker.provenance_for(room)` returns per-kind
   bools, already feeding the occupied-sensor attributes.
3. **Classification** — kind is recovered by CONF field *and* by entity name
   (`presence`/`mmwave` → mmwave), so a mmWave lumped under `motion_sensors`
   (Garage Hallway) is still typed correctly.

**Physical fact, checked live:** `binary_sensor.mmwave_zigbee_studya_presence` is
`device_class: occupancy` — continuous presence while a stationary body is present,
not a motion pulse. mmWave ON + motion OFF = a still body.

So Stage B is a compose, not a plumbing build — *if* the dropout gate (§5, Stage B)
passes.

---

## 7. The operator checkpoint — what's actually yours to decide

The checkpoint comes **pre-build** (Tier 2-DB; building the wrong aggression burns a
cycle), after Stage 0 confirms.

1. **Per-room HVAC-occupancy holds** — the aggression lever, now generalized (not a
   binary circulation flag). Pure-transit rooms → HVAC-occupancy off (the degenerate
   case): Garage Hallway, Kitchen Hallway, Kitchen Hallway Garage, Master Hallway,
   Upstairs Hallway, Foyer. Dwelling rooms → a per-room hold you can eyeball
   (kitchen short, bedroom generous). A declaration + a small table, not a fleet of
   timers.
2. **Exposure** — internal signal + opt-in diagnostic (recommended) vs. a real
   HVAC-occupancy entity in all 43 rooms.
3. **Fast-in loop cadence** — adopt the ~60 s HVAC reaction sub-tick (EVSE pattern)
   for hot-and-occupied, vs. leave fast-in for a later cycle. Distinct from the holds
   above (hold ≠ loop).

`vacancy_grace` stays 10 initially; tighten later on measured residual, not now.

### Two caveats I won't bury

- A person genuinely lingering in a hallway (long phone call) wouldn't get
  conditioning. Rare, low-cost, reversible (reclassify).
- A dwelling room with poor sensor coverage, reachable only through a hallway, could
  be missed. A per-zone coverage question — Stage 0 can check it too.

---

## 8. Live reference numbers (verified from `.storage`, this house)

- `vacancy_grace` = **10 min** (constrained 5 during energy coast/shed);
  `zone_entry_dwell` = **5 min**; energy tick = **5 min**.
  *(Audit #5 reconciliation: these are the LIVE `.storage` values and are load-bearing
  operator overrides; the source DEFAULTS differ — `hvac_const.py:374,377` ship 15 and
  3. The live values govern; the plan tunes against 10/5. Also: `zone_entry_dwell`
  must default to 0 the same cycle per-room dwell ships, or the two stack — audit
  footgun S1; keep the field one release for observability, delete later. And the new
  hold default goes at the root `const.py` home, not a third copy — `DEFAULT_FAN_VACANCY_HOLD`
  is already duplicated at `const.py:1153` + `hvac_const.py:821`.)*
- `occupancy_timeout`: mostly 300s; 360 Garage Hallway; 480–540 Kitchen / Study A /
  Game / Breakfast / Ziri; 900 bathrooms / Exercise / Master Bath.
- **Retreat-from-empty today:** ~15–20 min standard rooms, up to 25–30 min for
  long-hold rooms.
- **Stillness-capable rooms:** 31 (carry presence/occupancy/mmWave). **PIR-only:**
  12 (mostly closets, bathrooms, pantries — low-dwell).

---

## 9. Prior art this reuses (must NOT be rebuilt)

- `occupancy_substrate.py` — per-kind raw substrate (§6).
- `presence.check_zone_occupancy_confidence(zone)` — zone occupancy confidence
  already exists; extend, don't reinvent.
- `hvac.py:530` pre-arrival machinery (geofence/BLE/camera_face → person→zone) —
  Stage C extends it.
- The room layer's mmWave machinery (fan demotion, corroboration).
- `CONF_ZONE_DYNAMIC_PRESET_*` — the per-zone HVAC config precedent, if any config
  is ever needed.

---

## 10a. MANDATORY before build — code supersession + prior-art sweep (operator, 2026-09-16)

Operator: *"find areas to simplify… not have code stacked on top of code that is now
unnecessary, because this is what we should have built in the first place… absolutely
no new machinery where we don't need it… prior art, context-wide audits, so we don't
rework things we've already done."* And the clarification: **this is a sweep of the
SOURCE — HVAC code + presence/dwell/hold code — not a card sweep.**

This is a **fundamental re-architecture**, so the plan must carry two code audits
*before* any build, over the **HVAC + presence/dwell/occupancy-timing domain, read
end-to-end** (not the diff, not the cards):

### (i) Supersession sweep — what comes OFF

Under the three-bucket triage (DELETE / KEEP+WIRE / KEEP+DOCUMENT; "dead ≠ delete").
Candidates already spotted this session (starting list, not exhaustive — the sweep
must read the code to complete it):

- **`zone_entry_dwell` (zone-level 5 min)** — subsumed by per-room dwell-to-enter
  (decision A′-2). Retire, or the dwells stack and defeat fast-in.
- **HVAC's inheritance of the lighting-held `room.occupied`** via
  `RoomCondition.occupied` (`hvac_zones.py`) — replaced by the HVAC-occupancy signal.
  The old read path may become dead once HVAC stops consuming it.
- **The redundant second hold** — `SIMPLIFIED_2026_09_15` identified the room
  clearance timeout as a *second, redundant* hold stacked under HVAC's own
  `vacancy_grace`/`zone_entry_dwell`. Under the new signal, confirm which holds are
  now doing nothing for HVAC and remove them rather than leaving them inert.
- **mmWave-sole suppression / fan-phantom gate interplay** (`coordinator.py:3363,
  3449`) — check whether the kind-aware HVAC signal subsumes any of this for the HVAC
  path, so we don't run two mechanisms for one job.
- Any dead HVAC-occupancy-adjacent code left from prior cycles (S14 was already
  removed; verify no siblings linger).

### (ii) Prior-art reuse — no new machinery where it exists

Every proposed new mechanism carries a **REUSE-or-BUILD verdict with file:line**.
Known reuse targets (must not be rebuilt):

- `occupancy_substrate.is_kind_active` / `get_room_kinds` — kind-aware presence.
- `ZonePresenceTracker.provenance_for` — per-kind at the zone boundary.
- `CONF_FAN_VACANCY_HOLD` pattern — per-room, per-consumer hold.
- `check_zone_occupancy_confidence` — zone occupancy confidence (extend, don't invent).
- `grace_hold` (`coordinator.py:3581`) — unavailability fail-open (must be preserved).
- pre-arrival machinery (`hvac.py:530`) — Stage C extends it.
- `energy._solar_follow` — the fast sub-loop pattern (Stage D).
- `ROOM_TYPE_TIMEOUTS` / the room_type tables — the defaults-by-type pattern.

**Rule:** the plan is incomplete until both audits are in it. A proposed mechanism
without a REUSE-or-BUILD verdict, or a superseded mechanism left un-triaged, sends the
plan back (mirrors the Tier-2+ prior-art-scan doctrine, applied to a re-architecture).

## 10. Immediate next step

**Run Stage 0** — the recorder query attributing zone_3's pointless episodes to
room role. It confirms or kills H3 before any build, and it sharpens the numbers
behind the operator checkpoint.
