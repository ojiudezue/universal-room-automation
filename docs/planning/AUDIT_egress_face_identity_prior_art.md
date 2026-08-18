# AUDIT — Egress + Face-Identity Prior Art (READ-ONLY, pre-build)

**Date:** 2026-08-18
**Purpose:** Before building a face-identity corroboration path (Frigate-2 face
+ UniFi Protect face via the live Alarm Manager webhook, cross-correlated, tied
to egress crossings, feeding guest/census), confirm the work is **complementary**
to — not a **duplicate** of — existing egress-awareness and known-person code.
Map the seams with file:line. This is a prior-art map, **not** a design.

**Verdict up front: COMPLEMENTARY.** The new work fills the `person_id=None`
identity gap that `EgressDirectionTracker` explicitly leaves empty, and unifies
two currently-ad-hoc / unused face sources (Frigate `last_recognized_face` census
scan + the dormant Protect webhook) into an egress-keyed identity signal. No
existing layer associates face identity with egress crossings. Extend the
existing surfaces named in §C; do **not** add a parallel identity/count writer
(§D collision risk).

---

## A. Egress-awareness inventory

### A1. EgressDirectionTracker — `transit_validator.py:830-1158`
- **Computes:** entry / exit / ambiguous direction by time-window correlating
  egress-camera person events against interior-near-door camera events
  (`_resolve_direction`, `:1055-1128`). Confidence 0.3–0.9 from a multi-platform
  "how many sensors fired for the same camera stem" boost (`:1093-1099`,
  `_count_platforms_fired :1140`).
- **Subscribes:** egress person binary sensors + egress `person_count` 0→N
  transitions + interior person sensors (`async_init :860-958`). Entity lists
  resolved cross-platform via `census.get_transit_egress_entities()` /
  `get_transit_interior_entities()` with a `camera_manager` fallback, plus a
  Protect-sourced interior prepend (`:908-921`).
- **Fires:** `self.hass.bus.async_fire("ura_person_egress_event", {...})` at
  **`:1102-1108`** with payload `{direction, egress_camera, timestamp,
  person_id, confidence}`.
- **Persists:** `database.log_entry_exit_event(person_id=..., event_type="egress",
  direction, egress_camera, confidence)` at **`:1120-1126`** (DAO def
  `database.py:3709`), only when direction != ambiguous.
- **CONFIRMED — NO IDENTITY:** `person_id` is hard-coded `None` in the fired
  event (**`transit_validator.py:1106`**) and in the DB write
  (**`transit_validator.py:1121`**). The tracker resolves *direction only*; it
  has no notion of *who* crossed. This is the gap the new work fills.

### A2. Consumers of `ura_person_egress_event` (today)
`grep async_listen "ura_person_egress_event"` → **four aggregation sensors only**,
all in `sensor.py`:
- `PersonsEnteredTodaySensor` (`sensor.py:4147`, listen `:4184`)
- `PersonsExitedTodaySensor` (`sensor.py:4227`, listen `:4262`)
- `LastPersonEntrySensor` (`sensor.py:4305`, listen `:4323`)
- `LastPersonExitSensor` (`sensor.py:4353`, listen `:4371`)
- Shared handler `_handle_egress_event` (`sensor.py:4190+`) already reads
  `event.data.get("person_id") or "unidentified"` (`:~4199`) — **the identity
  slot exists and is wired**; it just always receives `None`, so every entry is
  labelled `"unidentified"`. When a producer stamps a real `person_id`, these
  sensors start showing names with **zero consumer changes**.

No other coordinator consumes the egress event. It does **not** feed guest/census
today.

### A3. Exterior track linker — `exterior_track_linker.py`
- Carries a **separate** identity notion: Frigate `sub_label` → `track.sub_label`
  → `identified` property (`:102`, `:152-153`, promotion logic `:521-550`,
  emitted in attrs `:663`, `:679`, `:774-792`).
- **Consumers:** `perimeter_alert.py` only (security path — `:593, 625, 685, 1139,
  1177, 1330, 1471, 1991, 2056`). Does **not** feed egress person_id, guest, or
  census. This is a distinct exterior-security track identity, not a crossing
  identity. (Collision note in §D.)

---

## B. Known-person / face-identity inventory (producers + consumers)

### B1. Face-identity PRODUCERS
- **Frigate face (shipped v5.80.0):** `camera_census._resolve_face_entity_id`
  (`camera_census.py:2470`) resolves `sensor.<cam>_last_recognized_face` tolerating
  the `_2` suffix (`:2484-2485`). Scanners:
  `_get_face_recognized_persons` (`:2620`), `_get_face_recognized_persons_fresh`
  (`:2652`, adds age check), `_get_face_recognized_person_names` (`:3283`).
  Names land in `PersonCensusResult.face_recognized_persons` (dataclass field
  `:162`, set at `:3458`) and are unioned with BLE into `identified_persons`
  (`known_persons = face_ids | ble_ids`, `:1855-1857`; also `:3388-3391`).
- **BLE / person-coordinator location:** `person_coord.data[name]["location"]`
  (populated `person_coordinator.py:452,528`). This is a *room-presence* identity,
  not a camera-face identity.
- **Exterior sub_label:** see §A3 (security-scoped, separate).
- **There is NO central face-identity producer/annotation layer.** Face names are
  scanned ad-hoc inside `camera_census` and consumed only for house-level census
  math. Nothing normalizes "who is at door X right now" for reuse.

### B2. Face-identity CONSUMERS (every one, file:line)
1. **Census guest math (the only real face-name consumer):**
   `identified_count`/`unidentified_count` derived from the face|BLE union
   (`camera_census.py:1843` `unidentified = camera_total - identified_count`;
   guest sensor `aggregation.py:5927`). Exposed attrs `identified_count`,
   `unidentified_count`, `face_recognized_count` (`camera_census.py:1253-1261`,
   the `face_recognized_count` added GAP-A D8 2026-08-16 `:1215-1225`).
2. **Room-level identified persons:** `coordinator._get_identified_persons_in_room`
   (`coordinator.py:1026-1042`) → `census.get_room_identified_persons(room)`, BLE
   fallback via `person_coordinator.get_persons_in_room`. Consumed at
   `coordinator.py:912,928`.
3. **Presence known-person gate:** `presence._is_known_person_in_room`
   (`domain_coordinators/presence.py:4929`) — reads `person_coord.data[name]
   ["location"]` (**BLE location, not face**), used by the GUEST-census arm-time
   exclusion (`:4798,4809,4907,5043`) and sticky variant `:4995`. Different
   identity source than face; do not conflate.
4. **`camera_resolver.py`** lists `_last_recognized_face` / `_face_recognized` as
   recognized suffixes (`:247,251,1416`) — resolver plumbing, not a decision
   consumer.
5. **HA automation (outside URA python):** the "dual known-person" notifier in
   `automations.yaml` (~`:7975-8064`) triggers on both Frigate
   `sensor.<cam>_last_recognized_face` **and** UniFi
   `sensor.<cam>_last_identified_person` and sends WhatsApp alerts. URA python
   consumes only the **Frigate** `_last_recognized_face` sensors (via census); the
   **UniFi `_last_identified_person`** face source is **NOT read by any URA python
   today**.

### B3. The Protect Alarm-Manager webhook probe — DORMANT, UNCONSUMED
- HA automation `URA KP Face Webhook Probe` (`automations.yaml:8421-8443`, id
  `1786827208839`): webhook `ura_kp_face_probe` (POST, local_only) → fires HA event
  **`ura_kp_face_probe_received`** with the raw payload + logs it. Self-described
  as a KP-ANNOTATION-1 revival probe "to confirm payload fields before wiring URA…
  Remove after probe concludes."
- **CONFIRMED — no URA python consumes `ura_kp_face_probe_received`** (grep of
  `custom_components/**/*.py` → empty). The Protect face channel is captured at the
  HA edge but is entirely unwired into URA. It is a greenfield input, not a
  duplicate.

---

## C. DUPLICATE-vs-COMPLEMENTARY verdict + wire-in seams

**COMPLEMENTARY.** Evidence:
1. `EgressDirectionTracker` resolves *direction only* and hard-codes
   `person_id=None` at the two egress emit sites (`transit_validator.py:1106,1121`).
   It does not — and structurally cannot today — attach identity. No duplication of
   identity work exists there to collide with.
2. No existing layer associates *face* identity with *egress crossings*. Face names
   land only in `camera_census` house-level guest math (§B2.1) and BLE room presence
   (§B2.3). The exterior `sub_label` identity is security-scoped (§A3). None is
   egress-keyed.
3. The two face sources the new work wants to fuse are currently under-used: Frigate
   `last_recognized_face` is scanned only for census counts; the Protect webhook
   (`ura_kp_face_probe_received`) and UniFi `last_identified_person` are **unconsumed
   by URA python**. Unifying them into one egress-keyed identity signal is net-new,
   not a re-implementation.

**Existing layer to EXTEND (do not replace):** the census face-resolution helpers
are the canonical Frigate-face reader — reuse `camera_census._resolve_face_entity_id`
(`:2470`) and `_get_face_recognized_person_names` (`:3283`) rather than writing a new
Frigate resolver.

**Concrete wire-in seams:**
- **S1 — stamp identity at the egress emit sites.** The single seam that closes the
  gap: populate `person_id` at `transit_validator.py:1106` (event) and `:1121` (DB
  write) instead of `None`. The correlator runs just before `_resolve_direction`
  fires (`:1096-1126`), matching a recent face-recognition against the crossing.
- **S2 — reuse census Frigate-face reader** (`camera_census.py:2470,3283`) as the
  Frigate-2 face input; do not add a parallel resolver.
- **S3 — first-ever consumer of `ura_kp_face_probe_received`** (`automations.yaml:8434`):
  a new URA python listener converts the Protect webhook probe into a live face
  source. This is the Protect leg of the corroboration. (Graduate the probe from
  "log-only" to a real handler.)
- **S4 — downstream is already wired.** `sensor.py:_handle_egress_event` (`:4190`,
  reading `person_id` at `:~4199`) needs no change; the four Persons/Last sensors
  begin showing names automatically once S1 stamps identity.
- **S5 — guest/census feed.** If egress-derived identity is to reduce guest count,
  fuse it into the census identified-persons **union** at `camera_census.py:1855`
  (dedup by person name), NOT as a separate additive count — see §D.

---

## D. Collision risk (two writers to the same identity signal)

1. **Census additive-vs-subtractive double-count (precedent, live incident).** The
   `_is_known_person_in_room` docstring (`presence.py:4929-4960`) records the
   GUEST-CENSUS 2026-08-17 CRIT: an additive derivation overwrote a subtractive one
   and double-counted residents into GUEST mode while dedup defenses were inert.
   Feeding a **new** identity source into census guest math risks re-triggering this
   class. Mitigation: integrate at the union point (`camera_census.py:1855`) with
   name-level dedup; never add a second parallel identified-count writer.
2. **Two identity notions must not be conflated.** `_is_known_person_in_room` is
   *BLE room-presence* identity; the exterior `sub_label` is *security-track*
   identity; the new egress identity is *crossing* identity. They answer different
   questions. Writing the new identity into either of those existing stores would
   cross-contaminate their consumers (presence GUEST gate; perimeter_alert).
3. **Frigate ↔ Protect double-fire for the same physical crossing.** Frigate face
   and Protect Alarm-Manager face can both recognize the same person at the same
   door within seconds. The correlator must dedup across platforms — mirror the
   existing egress stem-dedup (`transit_validator.py:1063-1073`,
   `_count_platforms_fired :1140`) so one crossing yields one identity, not two.
4. **Probe removal coupling.** The probe automation is flagged "Remove after probe
   concludes" (`automations.yaml:8425`). If S3 wires URA to
   `ura_kp_face_probe_received`, that automation becomes load-bearing — it must be
   promoted from throwaway probe to a supported producer, or the Protect leg goes
   silently dead.

---

## Summary (for the caller)

- **Verdict:** COMPLEMENTARY. `EgressDirectionTracker` explicitly emits
  `person_id=None` (`transit_validator.py:1106,1121`) — the identity gap is real and
  by-design empty. No existing code ties face identity to egress crossings.
- **Layer to EXTEND:** census face resolution
  (`camera_census._resolve_face_entity_id:2470`, `_get_face_recognized_person_names
  :3283`) is the canonical Frigate-face reader — reuse it. There is **no** central
  face-identity annotation layer; face names are read ad-hoc and only for census
  guest math → this argues for the new *unifying producer*, not a duplicate.
- **Unconsumed inputs to adopt:** the Protect webhook event
  `ura_kp_face_probe_received` (`automations.yaml:8434`) has **zero URA python
  consumers today**; UniFi `last_identified_person` is unread by URA python.
- **Wire-in seams:** S1 stamp `person_id` at `transit_validator.py:1106`+`:1121`;
  S2 reuse census Frigate reader; S3 add first consumer of
  `ura_kp_face_probe_received`; S4 downstream sensors already read `person_id`
  (`sensor.py:4190`); S5 fuse into census union at `camera_census.py:1855` with dedup.
- **Collision risks:** (a) census additive/subtractive double-count (2026-08-17 CRIT
  precedent) — integrate at the union, not a parallel count; (b) keep the three
  identity notions (BLE room-presence, exterior sub_label, egress crossing) distinct;
  (c) Frigate↔Protect same-crossing double-fire needs cross-platform dedup; (d) the
  "remove after probe" automation becomes load-bearing if wired.
