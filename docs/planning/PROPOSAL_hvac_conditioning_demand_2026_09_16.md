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

### Stage A — Circulation-aware zone demand (the core change)

One new explicit distinction: mark circulation rooms (the ~6 hallways/foyer).
**Operator-declared, not derived** — you know your house, and deriving transit-vs-
dwell is exactly the flaky move H1/H2 warned against. HVAC zone demand becomes the
OR over **non-circulation** rooms; circulation rooms stop voting for conditioning.

- Reuses `room.occupied` as-is (all machinery intact). **No raw sensor tap.**
- One field, read at the one existing rollup site. Lighting untouched (no
  regression risk to lights).
- Directly targets the measured defect; predicted to kill most of zone_3's 15/day.
- `grace_hold` and `vacancy_grace` unchanged.

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

### Named separately, NOT folded in — the fast-in constraint

The 5-minute decision tick is a **hard floor** on "react quickly if it's hot." Even
at dwell=0, worst-case latency to act is a full tick; the founding incident had the
occupant at the thermostat in ~2.5 min. **No demand-signal fixes this** — fast-in
needs an event-driven path that acts between ticks. Any plan claiming fast-in
without addressing the tick is promising something it can't deliver.

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
cycle), after Stage 0 confirms. It's cleaner than three timers:

1. **The circulation set** — which rooms are transit. My read: Garage Hallway,
   Kitchen Hallway, Kitchen Hallway Garage, Master Hallway, Upstairs Hallway, Foyer.
   This *is* the aggression lever — a declaration you can eyeball, not a number.
2. **Absolute or soft** — never condition a zone on hallway-only occupancy
   (recommended), vs. a brief pre-condition.
3. **Retreat timing** — keep `vacancy_grace`=10 initially; tighten later on measured
   residual, not now.

### Two caveats I won't bury

- A person genuinely lingering in a hallway (long phone call) wouldn't get
  conditioning. Rare, low-cost, reversible (reclassify).
- A dwelling room with poor sensor coverage, reachable only through a hallway, could
  be missed. A per-zone coverage question — Stage 0 can check it too.

---

## 8. Live reference numbers (verified from `.storage`, this house)

- `vacancy_grace` = **10 min** (constrained 5 during energy coast/shed);
  `zone_entry_dwell` = **5 min**; energy tick = **5 min**.
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

## 10. Immediate next step

**Run Stage 0** — the recorder query attributing zone_3's pointless episodes to
room role. It confirms or kills H3 before any build, and it sharpens the numbers
behind the operator checkpoint.
