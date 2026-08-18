# PLANNING — Egress Face-Identity (EXTERIOR-GUEST-FACE-FASTFOLLOW-1)

**Date:** 2026-08-18  **Operator go:** 2026-08-18
**Card:** EXTERIOR-GUEST-FACE-FASTFOLLOW-1
**Prior art:** `docs/planning/AUDIT_egress_face_identity_prior_art.md` (verdict COMPLEMENTARY; seams S1–S5)
**Spike:** `docs/planning/RESEARCH_protect_face_to_ha.md` (Alarm-Manager webhook path 4b)

Close the `person_id=None` gap at the egress emit sites so egress crossings carry
identity, then fuse that identity into the census union with name dedup — never
as a parallel additive count. Frigate face is the primary source (already
resolvable post-v5.80.0 D2). UniFi Protect face, via the LIVE Alarm-Manager
webhook (`automation.ura_kp_face_webhook_probe` → `ura_kp_face_probe_received`),
is a **corroboration** input added AFTER a real payload has been captured.

---

## 0. Institutional context verified

**Grep evidence (REUSED / NEW):**

- REUSED — Frigate face reader: `camera_census._resolve_face_entity_id`
  (`custom_components/universal_room_automation/camera_census.py:2470`),
  `_get_face_recognized_persons` (`:2620`),
  `_get_face_recognized_persons_fresh` (`:2652`),
  `_get_face_recognized_person_names` (`:3283`). The new work MUST NOT introduce
  a parallel Frigate-face resolver; extend/consume these.
- REUSED — Census identity union point — **TWO writers, both must fuse
  (plan-review C-CRIT-1):**
  (1) `camera_census.py:1855` (`known_persons = face_ids | ble_ids`, raw
  per-zone in `_cross_correlate_persons`) — necessary but NOT sufficient.
  (2) `camera_census.py:3391-3392` (`recognized_set = set(ble_persons) |
  set(face_recognized)`, house-level in `_apply_enhanced_house_census`),
  returned at `:3440` and OVERWRITING the raw value — THIS is the set that
  actually flows into `identified_count` (`:1253`), `unidentified_count` via
  `raw_total_ceiling` (`:3424`), and every guest-math consumer. Fusing
  `egress_face_ids` into `:1855` ALONE is a house-level no-op (the exact
  2026-08-17 GUEST-CENSUS double-count geometry, inverted: a silently-dead
  fuse instead of a silently-additive one). The new egress-face name set MUST
  be unioned into BOTH sites. Name-level dedup happens via set union (S5).
- REUSED — Egress event emit + DB write sites: `transit_validator.py:1102-1108`
  (event) and `:1120-1126` (DB) — the `person_id=None` slot lives here (S1).
- REUSED — Egress downstream consumers already read `person_id`:
  `sensor.py:4184` listener, `:4199` `event.data.get("person_id") or
  "unidentified"`. Zero consumer-side changes needed (S4).
- REUSED — Cross-platform stem dedup: `transit_validator.py:1063-1073`
  (`_last_resolved` 5s window) + `_count_platforms_fired` (`:1140-1164`,
  frigate vs unifi). The face-side cross-NVR dedup mirrors this shape (do not
  invent a second dedup mechanism).
- REUSED — Protect webhook edge: `automations.yaml:8421-8443`
  (`URA KP Face Webhook Probe`, webhook_id `ura_kp_face_probe`, fires
  `ura_kp_face_probe_received`, local_only POST). VERIFIED receiving; the
  payload shape is unconfirmed until a live face event.
- REUSED — Person-coord room location (BLE identity, DIFFERENT NOTION, must not
  be conflated): `person_coordinator.py:452,528`; `presence._is_known_person_in_room`
  (`domain_coordinators/presence.py:4929`).
- REUSED — Exterior sub_label (security-track identity, DIFFERENT NOTION):
  `exterior_track_linker.py:102,152-153,521-550,663-679`; consumers = only
  `perimeter_alert.py`. Do not cross-write.
- NEW — Egress ↔ face correlator: a small helper on `EgressDirectionTracker`
  (or a sibling in `transit_validator.py`) that, at emit time, asks the census
  face reader for the freshest recognized face on the egress camera stem within
  a bounded window. No equivalent exists (audit §B: "There is NO central
  face-identity producer/annotation layer").
- NEW (D2 only) — Consumer of `ura_kp_face_probe_received`: audit §B3 confirmed
  zero URA python consumers today. This is the Protect leg.
- NEW — Census `egress_face_ids` set fed into the union at BOTH
  `camera_census.py:1855` AND `:3391` (C-CRIT-1). Additive-vs-subtractive
  collision avoided by shape: set-union with the existing `face_ids | ble_ids`
  at each site, not a new count writer.
- NEW knobs (see §7): `FACE_MATCH_WINDOW_S`, `CROSS_NVR_AGREEMENT_WINDOW_S`,
  `PROTECT_CORROBORATION_ENABLED` (options-flow, default OFF until Wed capture),
  `PROTECT_CORROBORATION_CONFIDENCE_BUMP`.

**Prior planning docs consulted:**
- `docs/planning/AUDIT_egress_face_identity_prior_art.md` — full read.
- `docs/planning/RESEARCH_protect_face_to_ha.md` — full read.
- `docs/planning/PLANNING_exterior_guest_egress.md` — referenced (parent cycle);
  `EGRESS-INTERIOR-COUNT-REINFORCE-1` is downstream of this and remains gated.
- `docs/readmes/README_v5.80.0.md` — D2 fresh-face fix, source of the resolvable
  `_last_recognized_face_2` state.
- Skim of kanban `CENSUS-FACE-MISS-WATCH-1` (face lookup 12/tick on empty
  house — fail-CLOSED; irrelevant to correctness of this cycle but noted for
  the Live check).

**Memory bodies pulled:** `project_presence_guest_latch_and_veto_gap.md`,
`feedback_cross_investigation_synthesis.md` (double-count discipline),
`project_frigate_ghost_evidence_chain.md`.

**Code locations surveyed end-to-end during scoping:**
- `transit_validator.py:830-1200` (EgressDirectionTracker full path).
- `camera_census.py:1820-1900` (union), `:2460-2510` (face resolver),
  `:2620-2700` (fresh-face), `:3280-3300` (name reader), `:3450-3470`
  (union write into result).
- `sensor.py:4140-4400` (all four egress consumer sensors, shared handler).
- `automations.yaml:8415-8443` (probe automation).

---

## 1. Tier classification

**Tier 2-DB (three framing-disjoint reviews + live validation).** Rationale:

- Touches the census identity union — the exact surface where the
  2026-08-17 GUEST-CENSUS CRIT double-counted residents (additive vs
  subtractive path). Any change here is regression-prone by the standing
  Tier-2-DB elevation rule.
- Stamps a value (`person_id`) that is CONSUMED downstream on an existing
  trust path (`sensor.py:4199`, and — via §5 fuse — the guest arm-time
  math and `unidentified_count`). This crosses coordinators
  (transit_validator → sensor + camera_census), which is the trust-hierarchy
  ripple pattern.
- Adds a NEW load-bearing dependency on an HA automation
  (`ura_kp_face_probe_received`) — a config-side wiring the URA python did
  not previously depend on. The probe's own note says "Remove after probe
  concludes"; once S3 consumes it, that instruction becomes wrong and the
  automation is production infra.

Not elevated to Tier 3: no new shared primitive; no state-machine with
one-missed-site failure geometry (the emission-site count is small and
enumerable — two sites in `transit_validator.py`, one union point in
`camera_census.py`, one probe consumer). If review finds a broader ripple
than the audit shows, escalate.

**Three framing-disjoint reviewer axes (for the reviewer dispatch):**
- **A — Correctness + edge cases:** face-window arithmetic, empty face
  reader returns, unavailable/unknown states, name-normalization, camera
  stem extraction failure. No spurious identity attached when no face was
  actually recognized recently.
- **B — Cross-coordinator + double-count precedence:** the census union
  invariant (§3), the identified/unidentified derivation before AND after
  the fuse, and every guest-math consumer downstream. Prove no path adds
  the new source ADDITIVELY. Confirm all three identity notions stay
  segregated.
- **C — Lifecycle + probe-graduation + restart:** load-bearing status of
  the HA automation documented and enforced (the "remove after probe" note
  updated); listener registered exactly once; teardown clean; payload
  parse defensive against the unknown Wed shape; behavior with the probe
  disabled/deleted (Protect leg silent, Frigate leg unaffected).

---

## 2. Falsifiable invariants (state up front; reviewer D-equivalent falsifies)

**I1 (NO DOUBLE-COUNT, cardinal).**  For every census tick, the house-level
identified count equals the cardinality of the NAME UNION of all identity
sources — never their sum:

    identified_count == | face_ids ∪ ble_ids ∪ egress_face_ids |

A real defect (an additive writer, a name-namespace mismatch that admits
"Oji" and "oji" as two, or a fuse that increments a count instead of adding
to the set) VIOLATES this. Test: introduce one resident recognized by BOTH
Frigate census and egress-face; identified_count MUST NOT increase relative
to the pre-cycle baseline where only Frigate saw them.

**I2 (SAME-CROSSING SINGLE IDENTITY).**  For any physical egress crossing
(same camera stem within the cross-platform window), AT MOST ONE
`ura_person_egress_event` is emitted, and its `person_id` is a single value
(not a Frigate name and a separately-emitted Protect name). Falsifier: a
crossing where Frigate and Protect both recognize the same person; only ONE
event fires (existing 5s stem dedup at `transit_validator.py:1063-1073`
already covers the direction leg — extend for the face leg).

**I3 (NO IDENTITY WITHOUT EVIDENCE).**  `person_id` in the emitted event
and DB write is `None` unless a face was recognized on the egress camera
(by name) within `FACE_MATCH_WINDOW_S` of the crossing timestamp. Falsifier:
crossing at T with the last recognized face at T-3600s ⇒ event MUST carry
`person_id=None`.

**I4 (IDENTITY-NOTION SEGREGATION).**  The new egress-face identity is
never written into `person_coord.data[name]["location"]` (BLE room-presence
notion) nor into any `sub_label`/`identified` property in
`exterior_track_linker.py` (security-track notion). Falsifier: any grep hit
of the new writer against those stores.

**I5 (NAME-NAMESPACE NORMALIZATION, plan-review C-MED-2).**  All names
entering the union at BOTH fuse sites are normalized to ONE canonical form
before set-union, so the same person recognized via different sources cannot
appear as two set members. The three producers use different casings/forms:
`:1857 sorted(list(known_persons))`, `:3443 sorted(recognized_set)`,
`:3388 face_recognized` (Frigate first-name slugs, e.g. `oji`). Falsifier:
a resident whose Frigate face yields `oji` and whose egress-face yields `Oji`
increments `identified_count` by 2. Test: case-varied names for the same
person must union to cardinality 1. The egress-face helper MUST emit names in
the SAME namespace the census union already uses (Frigate first-name slug);
if it cannot, it normalizes at the fuse boundary.

---

## 3. PRODUCER / CONSUMER checks

### 3a. `person_id` on `ura_person_egress_event` + DB row

**PRODUCER (post-cycle):**
- Single site: `transit_validator._resolve_direction` at `:1102-1108`
  (event) and `:1120-1126` (DB), stamped from a new helper
  `_resolve_egress_face_identity(egress_camera_id, timestamp)`.
- Helper computes: extract stem via `_extract_camera_stem`; call the
  reused census reader (`camera_census._resolve_face_entity_id` +
  `_get_face_recognized_persons_fresh`) filtered to the stem's face
  sensor; select the freshest recognized name whose recognition
  timestamp is within `FACE_MATCH_WINDOW_S`; return that NAME or `None`.
- **MUST mirror the fail-open veto (C-LOW-2):** the reused name reader
  `_get_face_recognized_person_names` (`:3346-3366`) suppresses a
  recognized name when that person's `person.<slug>` tracker reads
  `not_home` (a stale-face guard). The new helper reads face state more
  directly and MUST apply the SAME `person.<slug> == not_home` veto, else
  it re-admits an identity the census already rejects. Test: face
  recognized on the egress cam but `person.oji == not_home` ⇒ helper
  returns `None`.
- Dependencies: (i) census face resolver healthy (v5.80.0 D2 fix landed;
  watch `sensor.<house>_face_lookup_missing_count`), (ii) Frigate 2
  suffix path live (CENSUS-FACE-MISS-WATCH-1 relevant), (iii) egress
  camera has a face sensor at all — many do not; helper returns `None`
  in that case (I3 preserved).
- Ground truth cross-check: HA state of `sensor.<cam>_last_recognized_face_2`
  at the crossing time. NOT another URA-computed name.

**CONSUMERS:**
- `sensor.py:4199` — display/aggregation. `PersonsEnteredTodaySensor` +
  siblings. Trust-decision use: aggregation only (name is displayed,
  count still increments regardless). Backward compatible with `None`
  (existing "unidentified" fallback).
- (via S5 fuse only) `camera_census` union at `:1855`. THIS is a
  trust-decision consumer — feeds `identified_count`/`unidentified_count`
  → guest math (`aggregation.py:5927`). See §3b.
- DB row (`database.log_entry_exit_event`) — historical/analytics; no
  live decision loop reads it today. Confirm during Live.

### 3b. Fused census identity (egress_face_ids into the union)

**PRODUCER (post-cycle):** a short-lived per-tick set built in
`camera_census` from the most-recent egress-face events (bounded age, e.g.
last 5 minutes — knob: `EGRESS_FACE_UNION_TTL_S`). Set of NAMES ONLY,
normalized to the Frigate-slug namespace (I5). Unioned at **BOTH** identity
writers (C-CRIT-1):
- `:1855` — `known_persons = face_ids | ble_ids | egress_face_ids` (raw).
- `:3391` — `recognized_set = set(ble_persons) | set(face_recognized) |
  egress_face_ids` (house-level, the one that survives to `identified_count`).
Not persisted as its own count; no `identified_count` increment outside these
two set-unions. Reviewer B must prove both fuse sites carry the same set and
that no third writer recomputes the count downstream of `:3391`.

**CONSUMERS:** unchanged — `identified_count`, `unidentified_count`,
`face_recognized_count` attrs (`camera_census.py:1253-1261`), guest sensor
(`aggregation.py:5927`), room-level `_get_identified_persons_in_room`
(`coordinator.py:1026-1042`). Because `egress_face_ids ⊆ face_ids` will
usually hold (Frigate saw the face at census scan time too), the fuse
value is small — it captures the WINDOW between "face was recognized on
egress N seconds ago" and "face has decayed off the sensor by the current
census tick." That window is the incremental identification the cycle
delivers.

---

## 4. Deliverables

**Split recommended: ship D1 first (Frigate), gate D2 on the real
Wed payload.** See marginal-benefit §8.

### D1 — Frigate person_id stamp + census union fuse (SHIP FIRST)

Populate `person_id` at the two egress emit sites from the Frigate census
face reader; feed the resulting names into the census union.

**Files:**
- `custom_components/universal_room_automation/transit_validator.py`
  (add `_resolve_egress_face_identity`; stamp at `:1106` + `:1121`).
- `custom_components/universal_room_automation/camera_census.py`
  (expose a small accessor for `_resolve_face_entity_id` +
  `_get_face_recognized_persons_fresh` filtered by camera stem, if not
  already reachable; add `egress_face_ids` register + TTL prune; wire
  into the union at **BOTH `:1855` AND `:3391`** per C-CRIT-1 — fusing only
  `:1855` is a house-level no-op because `_apply_enhanced_house_census`
  recomputes `recognized_set` at `:3391` and overwrites).
- `custom_components/universal_room_automation/const.py` — new module
  constants (§7).
- Tests under `quality/tests/` (unit + behavioral; NO wall-clock coupling).

**Acceptance criteria:**
- **Verify:** at least one live entry event in the recorder carries
  `person_id="<resident name>"` after a real crossing whose camera has
  a face sensor. Discriminator vs "wrong fix": a matched crossing where
  the resident's face was recognized 30+ minutes earlier MUST carry
  `person_id=None` (I3), not the stale name.
- **Verify:** `sensor.persons_entered_today` last entry attribute shows
  the resident name (not "unidentified") for that event.
- **Sensor:** house-level `identified_count` for the tick during a known
  crossing equals `|face_ids ∪ ble_ids ∪ egress_face_ids|` — NOT the sum
  (I1). Discriminator: if a resident is in BOTH Frigate face scan and
  egress-face for the same tick, `identified_count` does NOT double.
  DISCRIMINATOR vs the silently-dead-fuse failure (C-CRIT-1): an
  egress-face-ONLY resident (present in `egress_face_ids`, absent from the
  Frigate face scan and BLE) MUST raise the house-level `identified_count`
  by exactly 1 — proving the fuse reached `:3391`, not just `:1855`. If that
  resident does NOT move the count, the `:3391` fuse is missing.
- **Test:** unit test — resolver returns `None` when no face sensor
  exists on the camera; returns the fresh name when one exists;
  returns `None` when the recognized-face state is unavailable/unknown
  /empty/none.
- **Test:** behavioral test — feed a synthetic egress event + a synthetic
  face-recognition state 3s before it; assert the emitted
  `ura_person_egress_event` carries the expected name. Then advance an
  INJECTED clock (freezegun or a passed-in `now`, NOT `time.sleep` — per
  the wall-clock-coupled-test memory, C-LOW-1) to `FACE_MATCH_WINDOW_S + 1s`
  past the face state; assert `person_id=None`.
- **Test:** census fuse test — exercised at the HOUSE level (through
  `_apply_enhanced_house_census`, not just `:1855`): with `face_ids={"oji"}`
  and `egress_face_ids={"oji"}`, house `identified_count == 1`. With
  `face_ids={"oji"}`, `egress_face_ids={"ziri"}`, `identified_count == 2`.
  With `face_ids={}`, `ble={}`, `egress_face_ids={"ziri"}`, `identified_count
  == 1` (the C-CRIT-1 discriminator — proves `:3391` fuse present).
- **Test:** name-normalization (I5, C-MED-2) — `face_ids={"Oji"}` (title
  case) and `egress_face_ids={"oji"}` (slug) union to `identified_count == 1`,
  not 2. Both fuse sites normalize before union.
- **Live:** after deploy, watch for the first real crossing on a
  face-covered camera (family-room-visible entry via garage per the
  card). Confirm `person_id` appears in the DB entry-exit row AND in
  the last-entry sensor. Empty-house window: if no real face event
  occurs before validation deadline, live check passes on the
  restart-time invariant (no crash, no spurious identities, no
  identified_count drift on an empty house).
- **Live:** `sensor.<house>_face_lookup_missing_count` per-tick delta
  does not increase materially from the pre-deploy baseline (this
  cycle must not regress the CENSUS-FACE-MISS-WATCH-1 metric).

### D2 — Protect corroboration listener (GATED on Wed payload capture)

> ⛔ **DO NOT BUILD D2 IN THIS CYCLE (plan-review C-MED-1).** D1 is the only
> deliverable dispatched now. D2 is fully specced here for continuity but is
> HARD-GATED on a real captured `ura_kp_face_probe_received` payload (Wed) +
> the §D2-payload appendix + `PROTECT_CORROBORATION_ENABLED` default OFF. A
> builder inheriting this plan builds D1 ONLY. D2 is out of scope for the D1
> build and its files/tests must not be touched. This fence is the gate.

Add the FIRST URA python consumer of `ura_kp_face_probe_received`. Convert
the parsed name into a second `egress_face_ids` contribution and use it as
a confidence bump on the egress event, mirroring the existing
`_count_platforms_fired` shape.

**Precondition (measure-before-build gate):** at least one real face-match
POST captured (Wed operator note) and its field shape documented in this
plan (append a §D2-payload appendix before build). Do NOT hard-code a
guessed field name. If the payload is too poor (no name, or only user id
without name mapping), park D2 with an evidence trigger and ship D1 alone.

**Files (post-gate):**
- `transit_validator.py` — subscribe to `ura_kp_face_probe_received`;
  parse defensively via `payload.get(...)`; buffer recent Protect faces
  keyed by camera + timestamp with TTL prune. Cross-NVR dedup via a
  new small helper mirroring `_count_platforms_fired` (do not extend
  `_count_platforms_fired` itself — that's about person-detection
  platforms, not face platforms).
- `config_flow.py` / `options_flow.py` — new bool
  `PROTECT_CORROBORATION_ENABLED` (default OFF; kill switch).
- `const.py` — `CROSS_NVR_AGREEMENT_WINDOW_S`,
  `PROTECT_CORROBORATION_CONFIDENCE_BUMP`.
- Update the HA automation description at
  `/Users/okosisi/ha-config/automations.yaml:8421-8443`: remove the
  "Remove after probe concludes" language and mark it as URA-load-bearing
  production wiring (config-side; done via HA automations editor, but
  the plan calls it out so a future cleanup cycle does not delete it).

**Acceptance criteria (post-gate):**
- **Verify:** Wed live face event on family-room camera fires
  `ura_kp_face_probe_received`; URA consumer logs the parsed name; if
  Frigate also recognized the same person on the same crossing within
  `CROSS_NVR_AGREEMENT_WINDOW_S`, exactly ONE egress event fires with
  a single `person_id` (I2 discriminator: name must not appear twice
  in the last-entry attribute; DB row count for the crossing = 1).
- **Sensor:** `confidence` on the emitted egress event is bumped by
  `PROTECT_CORROBORATION_CONFIDENCE_BUMP` when both NVRs corroborate;
  unchanged when only one NVR recognized. Discriminator: single-NVR
  case must be observably distinguishable from dual-NVR case in the
  event data (a reviewer can prove corroboration was actually consulted).
- **Test:** payload-shape defensive tests — missing name field ⇒
  no `egress_face_ids` contribution, no crash; malformed JSON ⇒ same;
  unknown extra fields tolerated.
- **Test:** cross-NVR dedup — synthesize Frigate face at T + Protect
  face at T+2s for the same person on the same stem; assert one
  egress event, one person_id, confidence bumped once (not twice).
- **Live:** with `PROTECT_CORROBORATION_ENABLED=false`, D2 code paths
  are inert (kill-switch proof). Flip it on; observe corroboration
  on the next dual-NVR event.
- **Live:** the probe HA automation description no longer says
  "remove after probe."

---

## 5. Non-goals

- **NO writing egress-face identity into BLE room-presence store.** The
  BLE `person_coord.data[name]["location"]` remains BLE-sourced only
  (I4). `_is_known_person_in_room` semantics unchanged.
- **NO writing into `exterior_track_linker` sub_label / identified.**
  Perimeter security identity remains security-scoped (I4).
- **NO reinforcement of interior head-count from egress crossings.**
  That is `EGRESS-INTERIOR-COUNT-REINFORCE-1`, still gated on D1
  accuracy proof (kanban ref).
- **NO change to `_count_platforms_fired` direction-side dedup.** It
  answers a different question (which detection platform fired); face
  cross-NVR dedup gets its own small helper.
- **NO custom Protect integration adoption.** Path 4b (Alarm-Manager
  webhook) only. Paths 4a (`uiprotect` websocket) and unifi-protect-bridge
  stay parked per the spike ranking.
- **NO upstream HA core PR** in this cycle.
- **NO retroactive backfill** of past `person_id=None` rows.

---

## 6. Collision-risk design (audit §D)

1. **Census double-count / silently-dead-fuse (2026-08-17 precedent,
   C-CRIT-1).** Mitigation IS invariant I1 + the shape of the fuse — a
   normalized name set (I5) unioned at BOTH existing writers (`:1855` raw
   AND `:3391` house-level), not a new count writer. The 2026-08-17 CRIT
   fused/computed at the wrong writer; here the same trap appears inverted
   (fuse only `:1855` ⇒ silently-dead at house level). Reviewer B must
   prove (a) both fuse sites carry the identical normalized set, and (b) no
   path anywhere increments `identified_count` from the new source outside
   these two unions.
2. **Frigate ↔ Protect same-crossing double-fire.** Existing
   direction-side stem dedup (`transit_validator.py:1063-1073`, 5s
   window) already prevents two egress events per crossing. For the
   face leg specifically: the correlator selects at most one name per
   crossing (freshest recognized within `FACE_MATCH_WINDOW_S`), so even
   without corroboration, `person_id` is single-valued. When D2 lands,
   the Protect face is a corroboration bump on the SAME event, not a
   second event (I2).
3. **Three identity notions kept distinct** — see I4 + Non-goals.
4. **Load-bearing probe automation** — D2 explicitly rewrites the
   automation description and calls out the load-bearing status in this
   plan. Cleanup discipline: any future cycle scanning for "remove after
   probe" automations checks this plan first.

---

## 7. Numbers get knobs (with rung)

| Number | Purpose | Rung | Why this rung |
|---|---|---|---|
| `FACE_MATCH_WINDOW_S` (default 60) | Max age of recognized face vs egress crossing to attach identity | **Module constant** (`const.py`) | Correctness bound. A wrong value silently attaches stale identities (I3) or drops fresh ones. Change requires review. |
| `EGRESS_FACE_UNION_TTL_S` (default 300) | How long an egress-face name stays in `egress_face_ids` for the census union | **Module constant** | Bounds the incremental identification window; wrong value inflates `identified_count` too long. Not operator-tunable. |
| `CROSS_NVR_AGREEMENT_WINDOW_S` (default 10) | Frigate ↔ Protect face agreement window at the same stem | **Module constant** | Mirrors the existing 10s platform-agreement window at `:1154`. Same rationale. |
| `PROTECT_CORROBORATION_CONFIDENCE_BUMP` (default 0.05) | Additive bump on egress event `confidence` when both NVRs agree | **Module constant** | Small policy value; changing it shifts downstream trust behavior; wants review. |
| `PROTECT_CORROBORATION_ENABLED` (default `False` until Wed capture) | Master enable for the Protect consumer (S3). Kill switch. | **Options-flow bool** | Deployment-time toggle; must be live-flippable if Protect payload changes shape or the automation is disabled at the HA side. This IS the kill switch. |

Kill-switch semantics: `PROTECT_CORROBORATION_ENABLED=false` ⇒ D2 code
path fully inert; D1 continues to function unchanged. Documented on the
options-flow field itself.

---

## 8. Marginal-benefit decomposition + verdict

**Simplest version:** D1 alone — Frigate person_id stamp + census union fuse.

**What D1 alone captures:**
- Closes the `person_id=None` gap at the two emit sites (the entire
  audit-identified structural gap).
- Turns "unidentified" into a real name for the four egress consumer
  sensors immediately, house-wide, on every face-covered egress camera.
- Fuses egress-face identity into the census union with name dedup —
  the incremental guest-math value the cycle is meant to deliver.
- Uses ONLY primitives that already exist and are proven post-v5.80.0.
  Zero new external inputs; zero new HA automations to depend on.
- Reviewable within Tier-2-DB with the three named framings.

**What D2 (Protect) adds MARGINALLY over D1:**
- A confidence bump on the egress event when both NVRs corroborate.
- A second face source at cameras where Protect recognizes but Frigate
  does not — the audit does not quantify how often this happens; the
  card notes family-room garage entry recognition works on Protect.
  UNVERIFIED as a frequency (no probe done).

**MARGINAL RISK ingredients of D2:**
- NEW external input (Alarm-Manager webhook) whose payload shape is
  unknown until Wed. Hard-coding a guessed field is exactly the fabrication
  class. Defensive parsing is possible but tests can only be as good as
  the assumed shape.
- NEW load-bearing HA automation dependency. Every future cycle now has
  a config-side artifact it must not delete.
- Rare-fire code path (dual-NVR agreement is by definition intermittent),
  harder to observe organically, easier to ship latent.
- Two writers into `egress_face_ids` (Frigate + Protect) — needs the
  cross-NVR dedup helper. New dedup surfaces are historically where
  double-fire bugs live (see audit §D3).

**VERDICT — SPLIT: ship D1 now; gate D2 on captured payload.**

D1 delivers the entire structural closure (person_id != None) and the
census fuse value. D2's marginal addition is a confidence bump plus a
second source at unknown frequency, paid for with a payload of unknown
shape and a new load-bearing config dependency. This is exactly the
marginal-benefit anti-pattern: the fancy variant introduces a categorically
risky ingredient (unknown external payload + config-side load-bearing) for
a small confidence delta.

Ship D1 now. After Wed's real face event captures the payload, append the
§D2-payload appendix to this plan, run D2 as a follow-up Tier-2 cycle
(likely can drop to Tier-2 non-DB since the census union is not touched a
second time — reassess at the time). If Wed's payload proves poor
(missing name, ambiguous id-to-name mapping, no confidence field we care
about), park D2 with the evidence trigger "if guest false-positive rate
warrants a second NVR face source, revisit."

---

## 9. Plan-completion tracking notes

- D2 explicitly deferred, gated on live payload capture. Tracked here
  and on the kanban card EXTERIOR-GUEST-FACE-FASTFOLLOW-1.
- The probe automation's description update is a D2 concern, not D1.
- `EGRESS-INTERIOR-COUNT-REINFORCE-1` remains blocked on D1's accuracy
  proof (per kanban), NOT on D2.
- `CENSUS-FACE-MISS-WATCH-1` is a sibling watch, not this cycle's owner
  — this cycle must not regress its per-tick miss count (Live check).
