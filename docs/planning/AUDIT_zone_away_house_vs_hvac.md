# AUDIT — Zone "away": HOUSE zone vs HVAC zone (mechanism + recent-change + doc-drift)

**Date:** 2026-08-17 · **Branch:** develop · **Mode:** read-only investigation.
**Framing (standing project distinction):** a **HOUSE zone** is a presence
grouping (Back Hallway, Master Suite, "Outside") with a per-zone `mode`
(away/occupied/sleep/unknown) on the `ZonePresenceTracker`. An **HVAC zone** is
thermostat-keyed (`zone_N`) and one HVAC zone maps to MULTIPLE house zones by
design (memory `project_house_zones_vs_hvac_zones`). They are computed by
**separate derivations** and can disagree — kept in separate sections below.

All file:line refs are against the develop checkout at audit time.

---

## A. HOUSE-zone "away"

### A1. Where a house zone's mode is computed, and its inputs

The per-zone mode lives on `ZonePresenceTracker`:

- `ZonePresenceTracker.mode` — `presence.py:597-601`. Returns `self._override`
  if a manual override is set, else `self._derived_mode`.
- `ZonePresenceTracker._derived_mode` — `presence.py:702-730`. This is the heart
  of house-zone away. Tiered OR (any one tier ⇒ OCCUPIED, else AWAY):
  1. **Tier 3 — BLE (phone) person location**: `if self._ble_occupied: return
     OCCUPIED` (`presence.py:707-708`). Checked FIRST, ungated by sensor
     discovery (comment "BLE … most reliable").
  2. **Tier 1 — room occupancy sensors (mmWave/PIR/etc.)**: `if
     any(self._room_occupied.values()): return OCCUPIED` (`presence.py:713-714`),
     gated on `self._has_sensors`.
  3. **Tier 2 — camera person/motion (with timeout)**: `if
     self._any_camera_occupied(): return OCCUPIED` (`presence.py:717-718`).
  4. Else `AWAY` (`presence.py:723`); `UNKNOWN` only if no sensors and no BLE
     ever seen (`presence.py:730`).

**Each input is ADVISORY-to-occupied / no hard away gate**: the tiers are a pure
OR — any single positive tier holds the zone OCCUPIED. Nothing drives a zone to
AWAY *against* a positive sensor. AWAY is simply the absence of all three tiers.
The only hard gate is the manual **override** (`_override`), which beats all
tiers (`presence.py:598-599`) — set via the Zone Presence Override select
(AWAY/OCCUPIED/SLEEP/AUTO).

- `_room_occupied` (Tier 1 view) — `presence.py:594-682`. Derived OR over
  `_room_provenance[room][kind]` (provenance-split cycle) **plus** the
  fan-interference hold `_fan_interference_hold_until` which can only EXTEND
  occupancy, never shorten it (`presence.py:678-682`). So a fan-noise-suspect
  mmWave room can hold a zone occupied past its natural drop.

### A2. How PHONE vs SENSORS each contribute; who wins; outdoor exclusion

- **PHONE → house zone**: `_ble_occupied` is the phone/BLE contribution.
  Setter `update_ble_presence` — `presence.py:861-863`. Fed by
  `_update_ble_zone_presence` — `presence.py:4610-4631`: for each zone tracker,
  reads `person_coordinator.data`, and if any person's `location` is a real room
  (`not in ("away","unknown","")`, `presence.py:4626`) that is in
  `tracker.room_names`, the zone is BLE-occupied (`presence.py:4628-4631`).
  So phone is a Bermuda room-resolved location mapped up to the zone.
- **SENSORS → house zone**: Tier 1 room occupancy (`_room_occupied`) and Tier 2
  camera.
- **Who wins when they disagree (at the zone level)**: it's an OR — whichever
  says OCCUPIED wins; there is no conflict resolution because neither can force
  AWAY. Phone (Tier 3) is evaluated first, so a live BLE fix holds the zone
  occupied even if all local sensors are quiet.
- **Outdoor-zone exclusion**: `CONF_ZONE_IS_OUTDOOR` (imported `presence.py:50`).
  Occupied outdoor zones still count toward `any_zone_occupied`
  (`presence.py:5501-5504`) but are EXCLUDED from `any_indoor_zone_occupied`
  (`presence.py:5514-5521`; outdoor-name snapshot `presence.py:1685-1723`). This
  matters at the HOUSE-STATE layer (A3), not at the per-zone mode.

### A3. Interaction with HOUSE-STATE away (the veto paths)

House-zone away and house-STATE away are **distinct**. `any_zone_occupied`
(aggregate over zone modes, `presence.py:5501-5504`) is an INPUT to house-state
away; house-state away does not feed back into per-zone mode (except SLEEP-hours
masking of tracker mode, `presence.py:5523-5531`). Three away decision points in
`infer()`:

1. **Base away** — `presence.py:1059-1063`: `if census_count == 0 and not
   any_zone_occupied → AWAY` (conf 0.9). Here **sensors are a HARD gate** — any
   occupied zone (sensor/camera/BLE) blocks base away.
2. **Path α — person-tracker ACTIVE veto** — `presence.py:1090-1103`: fires when
   `all_tracked_persons_away and unidentified_count == 0 and
   face_recognized_count == 0` → AWAY (conf 0.95). This is the **phone path**: it
   forces AWAY *even against camera Tier-2 ghost motion*, defending against
   Frigate motion-without-person-ID. Note the D8 (v5.78) addition of the
   `face_recognized_count == 0` clause.
3. **Path β — LOST-admitted veto** — `presence.py:1136-1207`: admits LOST-but-away
   trackers into the denominator; gated by `any_indoor_zone_occupied` (the
   outdoor-excluded aggregate, `indoor_blocked` `presence.py:1132-1136`), a grace
   clock, a `sustained_external_empty` immediate-engage limb
   (`presence.py:1178-1181`), and a sleep exemption. Requires `census_count == 0`
   and `not indoor_blocked` — so **a real INDOOR sensor occupancy blocks the
   phone-driven away**.

**Net precedence at the house-STATE layer (corrected 2026-08-17 — the away paths
are NOT symmetric; do not summarise them as one rule):**
- Indoor sensor occupancy hard-gates the **base** path (`:1059`) and **path β**
  (`:1168`, `not indoor_blocked`), but **NOT path α** (`:1091`) — path α does not
  reference `any_zone_occupied` at all.
- So when **all phones are confidently away (path α)**, PHONE overrides BOTH room
  sensors AND camera-ghost motion and forces AWAY at 0.95; the only thing that keeps
  the house home on that path is a camera-confirmed **person** (`unidentified_count`
  or `face_recognized_count`), not room-sensor occupancy. A stuck mmWave does **not**
  hold the house home here. (The common case where a resident is home *with* their
  phone keeps the house home because the phone is home → not `all_tracked_persons_away`
  → path α never fires; the edge case is a resident home *without* their phone, where
  path α will force away despite the room sensor — the known phone-vs-sensor tradeoff.)
- When **a phone is uncertain/LOST (path β)**, room-sensor occupancy DOES keep the
  house home (conservative).
- Outdoor camera person-ID cannot block away (WS-A4).

---

## B. HVAC-zone "away"

### B4. Where HVAC-zone away/eco/setback is computed, and what drives it

HVAC has **no "away" mode of its own** — it maps house state to a Carrier
**preset**, then optionally overrides per-zone:

- **House-state → preset**: `HOUSE_STATE_PRESET_MAP` — `hvac_const.py:780`
  (`away → "away"`, `home_* → "home"`, `sleep → "sleep"`, etc.). Resolved via
  `HVACPresetManager.get_preset_for_house_state` — `hvac_preset.py:111-116`.
- **Applied in** `HVACCoordinator.evaluate` — `hvac.py:1367+`. `target_preset`
  from house state at `hvac.py:1508-1511`; `arriving` is skipped
  (`hvac.py:1506`).
- **D1 per-zone vacancy override** — `hvac.py:1544-1560`: `zone_vacant_past_grace
  = not zone.any_room_occupied and last_occupied_time is not None and (now -
  last_occupied_time) > grace_minutes*60`; if true and `target_preset in
  ("home","sleep")` → `effective_preset = "away"` + one vacancy sweep. This makes
  an HVAC zone go to the **away preset while the house is still home**.
- **D6 stale-occupancy failsafe** — `hvac.py:1565-1620`: if a zone is
  `any_room_occupied` for > `max_occupancy_hours` with insufficient
  multi-source confirmation (via `presence.check_zone_occupancy_confidence`,
  `hvac.py:1587-1588`), it is treated as a stuck sensor and forced to `"away"`.
- Grace is shortened when energy-constrained (coast/shed) — `hvac.py:1516-1521`.

### B5. How phone and sensors feed HVAC-zone away (SAME or separate path?)

**Separate derivation from house-zone away.** HVAC zone occupancy = the OR of
per-room `occupied` bools, NOT the `ZonePresenceTracker`:

- `ZoneState.any_room_occupied` — `hvac_zones.py:146-148`: `any(r.occupied for r
  in self.room_conditions)`.
- `room_conditions[*].occupied` source — `hvac_zones.py:546`:
  `data.get("occupied", False)` read from each **room coordinator's** `data`
  dict (`update_room_conditions`, `hvac_zones.py:456-546`).

So HVAC aggregates the **room-level fused `occupied` bool** across the rooms that
belong to the thermostat's zone. Phone/BLE and camera reach HVAC **only
indirectly**: (a) via the room-level occupancy fusion (if a room's `occupied`
includes BLE/camera evidence), and (b) via the **house state** (which phone
influenced through the path-α/β vetoes). There is NO direct BLE/camera/zone-
tracker read at the HVAC-zone tier, and no `any_indoor_zone_occupied` /
outdoor-exclusion concept in HVAC.

### B6. Independent HVAC away logic that can disagree with house-zone away

Yes — three divergence classes:

1. **HVAC away-preset while house zone reads OCCUPIED**: D1 vacancy override
   (`hvac.py:1544-1554`) forces the away preset when rooms have been vacant past
   grace *even though the house is home* — a design feature, not a bug, but it is
   HVAC-local and not visible in the house-zone tracker mode.
2. **HVAC holds "home" while a house zone reads AWAY**: the house-zone tracker
   sees BLE/camera (Tiers 2–3); HVAC's `any_room_occupied` does not read those
   at the zone tier. A BLE-only or camera-only occupied house zone contributes to
   `any_zone_occupied` but its HVAC zone can still read `any_room_occupied ==
   False` and drop to the away preset after grace.
3. **D6 forces away against `any_room_occupied == True`** (stuck sensor,
   `hvac.py:1608`) — HVAC overrides its own occupancy signal, independent of the
   presence coordinator's verdict, when confirmation is insufficient.

---

## C. What CHANGED in the last few cycles (v5.70 → v5.79)

Tags v5.70.0–v5.79.0 correspond to PRs #500-ish through #512 (2026-08-11 →
2026-08-16). Relevant cycles:

| Version | Cycle | Touches | Person-tracker vs zone-occupancy |
|---|---|---|---|
| **v5.78.0** | PATH-ALPHA (LOST dissolution + memory writers + census hole) | `presence.py` heavily | **PERSON-TRACKER.** Rewrites how a phone maps to `tracking_status`/`tracking_reason`/away-vote via the six-state evidence matrix (feeds `all_tracked_persons_away`, path α/β denominators). D8 (commit `2e76a5a91`) makes **path α gate on `face_recognized_count == 0`** (`presence.py:1090-1103`) — the census-hole fix. D2b retires the relaxed predicate (`9f3529e76`); D5-D7 add memory writers `away_transition_blocked` / `tracker_trust_excluded` / `house_state_transition` (`65d3dc80f`); D5 wire-in `reconcile_open_away_block_on_boot` (`380208546`). **Does NOT change per-zone occupancy** — it changes the phone side of the house-STATE away vetoes. Non-goal explicitly excludes the phantom-zone / fan-loop side. |
| **v5.75.0** | STUCK-SENSOR-1 (+ ROOM-NAME-DESYNC-1) | room/substrate tier | **ZONE-OCCUPANCY (indirect).** Duty-flagged sensors are now EXCLUDED from room occupancy when (exclusion enabled + a role-resolved corroborator is wired + corroborator live-ON observed post-boot + boot-settle). Because both zone types read room occupancy, a stuck sensor no longer holds EITHER a house zone (via `_room_provenance`) OR an HVAC zone (via room `occupied`) occupied. Restore-poisoning guarded (requires live-ON post-boot). Born from the 2026-08-13 away-transition incident. |
| **v5.77.0** | CENSUS-SUFFIX-FIX-1 (+ RELOAD-WATCHDOG-HAZARD, ZONE-CAM-PERSON-SWAP rider) | census matchers | **Feeds house-STATE away.** Census matchers now strip the `_N` disambiguation suffix, restoring `census_count` (pinned at identified-count since 08-13 F1 retirement). `census_count` is the hard gate in base away (`presence.py:1059`) and path α/β — a broken census silently disabled those away paths. |
| **v5.79.0** | GUEST-CENSUS (guest rooms lead, census corroborates) | `presence.py` guest composition | **Neither zone-away directly.** Inverts guest composition (guest rooms lead, census corroborates, `7f7c15d20`), decouples GUEST exit from `unidentified_count` (`44ccfabc6`). Discovered the guest-identity oracle (`_is_known_person_in_room`) had **never worked in production** (CRIT fix `7e3fa18d0`). Touches GUEST state, not the away derivations — but shares the census/unidentified inputs that also gate away. |
| v5.74.0 | CIRCLING-SEVERITY-1 + area inheritance | anomaly/diagnostics | Not zone-away. |
| v5.76.0 | MEMORY-COMPACTOR-1 + circling exemption | memory | Not zone-away. |

**Distinguishing the axes:** the recent heavy motion (v5.78) is on the
**person-tracker / phone** side of house-STATE away — the phone→away-vote
classification. The **zone-occupancy** change is v5.75 (stuck-sensor exclusion),
which reaches both zone types through the room tier. v5.77 restored the census
INPUT to house-state away. v5.79 (guest) did not touch either zone-away
derivation.

---

## D. Manuals vs code — doc-drift audit

### D0. Manuals that exist for these areas

- `docs/Coordinator/PRESENCE_COORDINATOR.md` — presence/house-state (house-zone
  away lives here conceptually).
- `docs/Coordinator/HVAC_COORDINATOR_MANUAL.md` — HVAC presets + vacancy.
- `docs/HVAC_MANAGEMENT_EXPLAINER.md` — HVAC preset map + seasonal defaults.
- `docs/Coordinator/HOUSE_MANUAL.md` — house-tier + BLE-extend + outdoor flag.
- `docs/Coordinator/ZONE_MANUAL.md` — zone config incl. `zone_is_outdoor`.
- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` (overview).
- **Absence finding:** there is **no dedicated "house-zone away" manual** and no
  section anywhere that documents the `ZonePresenceTracker` three-tier
  `_derived_mode` OR (BLE→sensor→camera) as the house-zone away mechanism. The
  presence manual documents the house-STATE machine, not the per-zone tracker
  derivation. **Absence is a finding** — the tracker tiering is the single most
  load-bearing house-zone-away logic and is undocumented.
- **Absence finding:** no manual documents that HVAC-zone occupancy is the OR of
  room-level `occupied` bools (`hvac_zones.py:146/546`) rather than the presence
  zone tracker — the exact source of house-vs-HVAC divergence (B6). The HVAC
  manual §3.2 describes vacancy timing but not the occupancy SOURCE.

### D1. Drift table

| Manual | Section | Claim | Code reality | DRIFT? | file:line |
|---|---|---|---|---|---|
| HVAC_MANAGEMENT_EXPLAINER.md | §3 House-state preset map | "`HOUSE_STATE_PRESET_MAP` (in `hvac_const.py:303`)" | Map is at `hvac_const.py:780` | **YES** (stale line ref) | manual `docs/HVAC_MANAGEMENT_EXPLAINER.md:34` vs `hvac_const.py:780` |
| HVAC_MANAGEMENT_EXPLAINER.md | §3 preset map, `guest` row | "`guest` → `home` (Phase 1 actuation cycle planned — v4.7.x)" | `guest → "home"` is live (`hvac_const.py:788`); the "planned v4.7.x" parenthetical is stale (guest actuation shipped v5.7.0-era) | **YES** (stale roadmap note) | `docs/HVAC_MANAGEMENT_EXPLAINER.md:39` |
| PRESENCE_COORDINATOR.md | §3 "Interaction with the v4.7.14 AWAY veto" | "The AWAY-state person-tracker veto … fires when **all** tracked persons are away AND `unidentified_count == 0`" | Path α now ALSO requires `census_count == 0` AND `face_recognized_count == 0` (D8, v5.78); path β (LOST-admitted) is a whole second veto | **YES** (incomplete predicate; missing D8 + path β) | manual `:1233` vs `presence.py:1090-1103` |
| PRESENCE_COORDINATOR.md | §3 line refs | "AWAY veto predicate: same file, lines ~983 and ~1046" | Predicate now at `presence.py:1059` (base), `:1090` (α), `:1136-1207` (β) | **YES** (stale line refs) | manual `:1238` vs `presence.py:1059/1090/1136` |
| PRESENCE_COORDINATOR.md | §infer pseudocode (`_infer_empty_house`, `PresenceContext`, `total_occupants`) | Empty-house away returns `HouseState.AWAY, 0.90` via a `ctx.total_occupants == 0` branch | Actual `infer()` uses `census_count` / `any_zone_occupied` and three explicit away branches with conf 0.9/0.95/0.95; no `PresenceContext`/`total_occupants` object | **YES** (illustrative pseudocode diverged from implementation; path β / immediate-engage / sleep-exempt / LOST-matrix entirely absent) | manual `:285-300` vs `presence.py:1059-1207` |
| PRESENCE_COORDINATOR.md | header/§1 zone tiers | "zone: derived OR over `_room_provenance`, `raw_occupied`, fan-interference hold, camera timeout, **BLE precedence**" | Matches code (`presence.py:702-730`) — BLE Tier-3 first | NO (accurate at a high level; but no full `_derived_mode` tier walk documented) | manual `:19-20` vs `presence.py:702-730` |
| HVAC_COORDINATOR_MANUAL.md | §3.1 Presets and house state | "**away** when the presence coordinator declares the house AWAY" | Accurate for house-driven preset; but omits that D1 per-zone vacancy override forces the away preset **while house is home** | **YES** (incomplete — omits the per-zone away override) | manual §3.1 vs `hvac.py:1544-1554` |
| HVAC_COORDINATOR_MANUAL.md | §3.2 Vacancy management | Zone vacancy delay → optional sweep; energy-saving shorter delay | Matches `hvac.py:1516-1560` (grace, constrained grace, sweep-once) | NO | manual §3.2 vs `hvac.py:1516-1560` |
| HOUSE_MANUAL.md | §"zone_is_outdoor" | "Outdoor zones still track occupancy but are excluded from the indoor-occupancy aggregate that gates the v5.7.0 AWAY path" | Matches `any_indoor_zone_occupied` (`presence.py:5514-5521`) | NO | manual `:221-223` vs `presence.py:5514-5521` |
| ZONE_MANUAL.md | §`CONF_ZONE_IS_OUTDOOR`, outdoor-blocking-away troubleshooting | Outdoor zone w/o flag holds indoor aggregate up, house refuses AWAY; toggle flag | Matches code semantics (`presence.py:5506-5521`) | NO | manual `:84,177-179` vs `presence.py:5506-5521` |
| HOUSE_MANUAL.md | §"away" state table | "`away`: Nobody home. Requires `census_count == 0` AND no zone occupied." | Matches base away (`presence.py:1059`); does not mention the two additional veto paths that can force away with census 0 + all-trackers-away | **PARTIAL** (correct for base; silent on α/β vetoes) | manual `:243` vs `presence.py:1059/1090/1136` |

---

## Summary

**(1) How each zone-away works + phone vs sensor precedence:**

- **HOUSE-zone away** = `ZonePresenceTracker._derived_mode`
  (`presence.py:702-730`): a pure OR of Tier-3 **BLE/phone** → Tier-1 **room
  sensors** → Tier-2 **camera**; AWAY = absence of all three; manual override
  wins over everything. **No input can force a zone away against a positive
  signal** — phone and sensors only ever vote OCCUPIED, and phone (BLE) is
  evaluated first. Aggregated as `any_zone_occupied` (and the outdoor-excluded
  `any_indoor_zone_occupied`).
- **HOUSE-STATE away** consumes `any_zone_occupied` (+ `census_count`). Base away
  is hard-gated by sensors/zones (`presence.py:1059`); the **phone** side adds two
  vetoes with DIFFERENT sensor treatment (corrected 2026-08-17 — the two paths are
  NOT the same and an earlier draft over-generalised path β's indoor condition onto
  both):
  - **Path α (all phones ACTIVE-away, `:1091`):** conditions are `all_tracked_persons_away
    AND unidentified_count == 0 AND face_recognized_count == 0`. It does **NOT** reference
    `any_zone_occupied` — so it **ignores room sensors** (a stuck mmWave does not block it)
    and forces AWAY at 0.95. The only things that keep the house home on this path are a
    camera that **identifies a person** (an unidentified body, or a face-recognized
    resident); camera **motion alone** (Tier-2 ghost) does not block it.
  - **Path β (a phone is LOST/uncertain, `:1168`):** conditions include `not indoor_blocked
    AND census_count == 0` — so it **DOES respect room sensors** (a stuck mmWave blocks
    away here) and is the conservative path.
  - **Precedence, precisely:** when phones are confidently away, PHONE overrides both room
    sensors and camera motion-ghosts (path α) — only a camera-confirmed *person* keeps the
    house home. When a phone is uncertain, room-sensor occupancy keeps the house home
    (path β). The base `:1059` path also respects room sensors.
- **HVAC-zone away** = house-state preset (`HOUSE_STATE_PRESET_MAP`,
  `hvac_const.py:780`) overlaid with a **per-zone vacancy override**
  (`hvac.py:1544-1554`) and a **stale-sensor failsafe** (`hvac.py:1565-1620`).
  HVAC-zone occupancy is the OR of **room-level `occupied` bools**
  (`hvac_zones.py:146/546`) — NOT the presence zone tracker. **Phone/camera reach
  HVAC only indirectly** (through room-level fusion and through house state). HVAC
  has no outdoor-exclusion and no direct BLE read at the zone tier, so it can
  disagree with the house-zone tracker (§B6).

**(2) What changed recently:** the heavy recent motion is on the **person-tracker
/ phone** side of house-STATE away — **v5.78.0 PATH-ALPHA** (six-state LOST
evidence matrix + D8 `face_recognized_count` gate on path α + memory writers).
The **zone-occupancy** change is **v5.75.0 STUCK-SENSOR-1** (duty-flagged sensors
excluded from room occupancy → propagates to both zone types). **v5.77.0**
restored the `census_count` input that gates all away paths. **v5.79.0** (guest)
touched neither zone-away derivation directly.

**(3) Stale manuals needing updates:**
- `HVAC_MANAGEMENT_EXPLAINER.md` — preset-map line ref (`303` → `780`) and stale
  "guest actuation planned v4.7.x" note.
- `PRESENCE_COORDINATOR.md` — **most stale**: the away-veto section documents only
  the v4.7.14 predicate (missing the D8 `face_recognized_count`/`census_count`
  clauses and the entire path β LOST-admitted veto + immediate-engage + LOST
  six-state matrix), and its `infer()` pseudocode (`PresenceContext` /
  `_infer_empty_house`) no longer resembles the implementation. Line refs stale.
- `HVAC_COORDINATOR_MANUAL.md §3.1` — omits the per-zone D1 vacancy override that
  forces the away preset while the house is home.
- **Two absence findings:** no manual documents (a) the `ZonePresenceTracker`
  three-tier OR as the house-zone away mechanism, nor (b) that HVAC-zone
  occupancy derives from room-level `occupied` bools rather than the zone tracker
  — the precise source of house-vs-HVAC divergence.
