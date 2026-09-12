# PLANNING — Identity Fusion Producer (BLE/face fusion + real-time face bridge)

**Cycle:** first of the 6.0.0 IDENTITY-DRIVEN AUTONOMY arc — PRODUCER +
already-wired census union only.
**Tier:** **2-DB (elevated per plan-review M5)** — the resolver output flows
into the census identity union (already wired), and the change touches a
shared primitive (leg-set assembly) consumed downstream by
`identified_count` / `unidentified_count` / GUEST-mode math. Elevation gives
us 3 framing-disjoint build reviews + a Reviewer D framed on §0 (fail-safe).
**Author date:** 2026-09-04. **Revised:** 2026-09-04 post plan-review
FIX-REQUIRED (7 must-fix findings incorporated + on-demand D4 drill
affordance added; see §11 changelog).
**Precedes:** v5.91.4 egress-identity PRODUCER on
`feature/egress-identity-producer` (built pending deploy — this cycle
EXTENDS its resolver, does NOT rebuild).
**Cards:** FRIGATE-SUBLABEL-FACE-BRIDGE-1 (task #11, MEASURE-GATED — see
§3.1 H3) + BLE-fusion-leg + guest-face class + fail-safe drill.

---

## 0. Falsifiable invariant (D4 — fail-safe)

> **Under any face-producer outage (Frigate service down, `frigate_status_2`
> unavailable, `sensor.<cam>_last_recognized_face[_2]` unavailable/unknown,
> Protect `_face_recognized[_2]` unavailable, or the MQTT face bridge silent
> for > `FACE_PRODUCER_STALE_TTL_S`, OR the on-demand drill switch engaged),
> no leg whose PROVENANCE is face-derived — regardless of which accessor
> produced it, which cache it came from, or which sensor it was mirrored
> through — MAY attach an identity on ANY reachable path in
> `_resolve_egress_face_identity` OR in its downstream census union at
> `camera_census.py:2017` / `:3954` (the `identified_count` /
> `unidentified_count` recompute at `:2029` that feeds GUEST mode). In the
> SAME window, a BLE home↔away transition (provenance-verified as a
> Bermuda/BLE `device_tracker`) within the direction-keyed lag window MUST
> still name the crossing (residents) or leave it anonymous (unknowns); the
> egress pipeline MUST NOT stall (no bounded async_call_later leak); and no
> security-alert path MUST be downgraded by a stale/missing face.**

The invariant now spans PROVENANCE not just accessor identity (C1 depth
fix): a face name that somehow appears via a merged-signal source (e.g. a
`person.<slug>` update whose `source` attribute is a camera_face) must
still be classified as face-provenance and gated by the face-producer
health guard.

Reviewer D's sole job is to break this in any legal config.

---

## 1. Institutional context verified

### 1.1 Design docs read
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (CANONICAL; §1
  platform roles, §1.1 `_2` suffix rule, current through v5.91.3, egress
  producer v5.91.4 pending deploy).
- `docs/planning/AUDIT_frigate_face_resolution.md`.
- `docs/planning/PLANNING_egress_identity_producer.md`,
  `PLANNING_egress_face_identity.md` (predecessors; leg-set +
  direction-keyed windowing are theirs — REUSED, not re-invented).
- `docs/planning/AUDIT_census_identity_supersession_and_consumers.md`
  (post-ship gaps; consumers still deferred EXCEPT the already-wired
  census union — see §3.5 H1).

### 1.2 Memory bodies pulled
- `reference_egress_face_coverage_7pct_not_a_ceiling.md` — face is
  currently DOWN house-wide; justifies BLE as a first-class leg.
- `reference_frigate1_retired_2suffix_permanent.md` — `_2` suffix
  permanent; resolve via registry.
- `reference_protect_face_latency_async.md` — Protect face back-fills
  onto the ORIGINAL detection `last_changed`.
- `feedback_read_consumers_before_asserting_function.md` — direct
  cause of C1/C2/C3 in plan review (assumed function of
  `SIGNAL_PERSON_ARRIVING` from its NAME).
- `feedback_coincidental_equality_masks_concept_split.md` — informs C4
  (EGRESS_ENTRY/EXIT_WINDOW_SECONDS vs FACE_MATCH_* window family are
  named-similar but semantically distinct; do not couple).
- `feedback_suppression_needs_discharge.md` — informs D4 read-time
  guard (no timers, no suppression, restart-safe).

### 1.3 Code locations surveyed end-to-end

- `transit_validator.py:1101-1420` — `_resolve_egress_face_identity`
  (EXTENDED).
- `transit_validator.py:1296-1306` — multi-slug DISAGREE → abstain (H2
  precedence rule; RETAINED, not regressed).
- `transit_validator.py:1313-1325` — person-tracker veto (fail-OPEN
  already; guests already pass — M3, no change).
- `transit_validator.py:1493` — `register_egress_face` call site into
  the census union (H1 wiring).
- `camera_census.py:2017` — face-recognized-names union feeder;
  `:2029` — `identified_count` / `unidentified_count` recompute;
  `:3954` — `_get_face_recognized_person_names`. These are the ALREADY
  WIRED downstream this cycle must reason about (H1).
- `camera_census.py:2654` — `_resolve_face_entity_id` (existing
  suffix-tolerant resolver, fail-CLOSED `_face_lookup_missing_count`).
- `camera_census.py:2697-2820` — `_resolve_face_legs` — 4 candidates
  today at `:2703-2708` (Frigate + Frigate_2 + Protect + Protect_2).
  EXTENDED; the MQTT bridge is a SEPARATE branch BEFORE this loop, not
  a 5th tuple (M1).
- `camera_census.py:3067-3110` — `_canonical_person_slug` (EXTENDED
  for D3 guest namespace).
- `camera_census.py:3051-3065` — `_get_tracked_person_slugs` (REUSED).
- `exterior_track_linker.py:53` — `FRIGATE_EVENTS_BUS_EVENT =
  "frigate_events"` (the HA-bus event, NOT MQTT topic strings). Payload
  shape `{"type", "after": {...}}`.
- `exterior_track_linker.py:256` — `sub_label = after.get("sub_label")`
  (extraction pattern REUSED).
- `exterior_track_linker.py:273` — `hass.bus.async_listen(FRIGATE_EVENTS_BUS_EVENT, …)`
  subscription pattern REUSED for D1.
- `exterior_track_linker.py:351-362` — `normalize_camera` +
  `EXTERIOR_CAMERA_KEY_ALIASES` (M2 — MUST route
  `after["camera"]` display-case through this to reach the HA sensor
  stem, else the bridge cache is permanently empty).
- `presence.py:4702` — `SIGNAL_PERSON_ARRIVING` is dispatched from a
  MERGED source (ble + geofence + camera_face). **DO NOT use as the
  BLE-leg source** — a face-derived arrival would masquerade as a BLE
  leg and survive a face outage → falsifies §0 (C1).
- **Correct BLE source (C1/C2/C3 fix):** `person.<slug>` state_changed
  home↔away transitions on the HA state bus. `person` is a
  device_tracker aggregate, never a face signal. Provenance guard:
  admit as a `BleTransitionLeg` ONLY if
  `person.<slug>.attributes["source"]` matches a Bermuda/BLE
  device_tracker id (measured live: `device_tracker.iphone_oji_bermuda_tracker`,
  `device_tracker.ezinne_iphone_bermuda_tracker`,
  `device_tracker.private_ble_device_249050` for jaya). Match rule:
  substring `"bermuda"` OR `"ble"` OR `"private_ble"` in the source
  string. Both directions (arrive + depart) — there is NO separate
  departure signal (C2).
- `const.py:2183-2196` — `EGRESS_ENTRY_WINDOW_SECONDS=45`,
  `EGRESS_EXIT_WINDOW_SECONDS=30`, `FACE_MATCH_WINDOW_S=60`,
  `EGRESS_FACE_UNION_TTL_S=300`. **Framing fix (C4):**
  `EGRESS_ENTRY/EXIT_WINDOW_SECONDS` are the `_delayed_resolve`
  SCHEDULING knobs, NOT the identity-window knobs.
- `const.py:2202-2209` — `FACE_MATCH_EXIT_WINDOW_BEFORE_S=180`,
  `FACE_MATCH_EXIT_WINDOW_AFTER_S=30`,
  `FACE_MATCH_ENTRY_WINDOW_BEFORE_S=60`,
  `FACE_MATCH_ENTRY_WINDOW_AFTER_S=300`,
  `FACE_MATCH_ABSTAIN_MARGIN_S=15`, `FACE_MATCH_MIN_CONFIDENCE=0.60`.
  These are THE identity-window family; the BLE cache TTL derives from
  the MAX of these (see §6, C4 fix).

### 1.4 REUSED vs NEW per proposed addition

| Addition | Status | Cite / justification |
|---|---|---|
| Frigate HA-bus subscription | REUSED pattern | `exterior_track_linker.py:53, :273` |
| `sub_label` extraction | REUSED | `exterior_track_linker.py:256` |
| `normalize_camera` + `EXTERIOR_CAMERA_KEY_ALIASES` on `after["camera"]` | REUSED (M2) | `exterior_track_linker.py:351-362` |
| Face-leg accessor extension | REUSED + EXTEND | `_resolve_face_legs:2697` — MQTT branch BEFORE the 4-candidate loop (M1) |
| Canonicalizer extension | REUSED + EXTEND | `_canonical_person_slug:3067` — guest-face class |
| Tracked-slug list | REUSED | `_get_tracked_person_slugs:3051` |
| Direction-keyed leg model | REUSED | `_resolve_egress_face_identity:1246-1275` |
| Multi-slug abstain (H2) | REUSED, retained | `_resolve_egress_face_identity:1296-1306` |
| Fail-open person veto | REUSED (M3) | `_resolve_egress_face_identity:1313-1325` |
| `person.<slug>` state_changed listener | NEW (C1/C2 fix) | HA state bus; provenance-guarded via `attributes["source"]` substring |
| `BleTransitionLeg` type | NEW | face-only `FaceLeg` today; BLE distinct engine tag `ble` |
| MQTT face-bridge module | NEW (MEASURE-GATED, H3) | pattern reused from `exterior_track_linker` |
| `FACE_PRODUCER_STALE_TTL_S` | NEW | no equivalent; caps `last_changed` age |
| `BLE_TRANSITION_CACHE_TTL_S` (derived) | NEW, derived from `FACE_MATCH_ENTRY_WINDOW_AFTER_S=300` (C4) | max of FACE_MATCH_* family |
| `guest:<first_token>` slug namespace | NEW | unmapped face names dropped today |
| Producer-health guard `_is_face_producer_live` | NEW | needed for §0 invariant |
| On-demand fail-safe drill switch | NEW | Frigate will be UP by validation; natural outage cannot be relied on. See §3.4 drill affordance. |

---

## 2. Ground truth — measure-before-build evidence

- **BLE producer (REVISED per C1/C2/C3).** `person.<slug>` state_changed
  home↔away transitions, both directions, measured **106 transitions /
  14d** across Oji/Jaya/Ezinne. Provenance guarded by
  `attributes["source"]` (Bermuda/BLE device_tracker). Prior §2 figure
  "126 in 10d via SIGNAL_PERSON_ARRIVING" is SUPERSEDED —
  SIGNAL_PERSON_ARRIVING is merged (ble + geofence + camera_face at
  `presence.py:4702`) and unusable as a provenance-clean BLE source.
- **Frigate face producer.** INTERMITTENT, proven when up (135 named
  recognitions across Oji/Jaya/Ojini/Ezinne in an 08-30/31 burst).
  Currently `frigate_status_2` unavailable; operator restoring service.
- **JOIN failure baseline.** `person_entry_exit_events`: 7,265 rows,
  `person_id` attach = 1 (~0%). Root causes measured: faces fire on
  INTERIOR cams while lingering (~0% within 45 s, ~3% at ±300 s);
  egress events are mostly noisy door person-DETECTIONS (0/60 aligned
  with real resident crossings).
- **Ojini** — face-known guest, no BLE; today dropped by canonicalizer.
- **Ziri** — away months, expected-silent; must NOT register as
  coverage failure; MUST fire correctly on return.

---

## 3. Deliverables

### Sequencing (H3, revised)

**Build order (single feature branch):** D2 → D3 → D4 → D1.

- **D2, D3, D4 do NOT need Frigate up.** They build against BLE +
  `person.<slug>` state + the existing face-leg accessor.
- **D1 is MEASURE-GATED.** Before writing D1 code: (a) operator restores
  Frigate; (b) a one-shot read-only probe subscribes to
  `FRIGATE_EVENTS_BUS_EVENT` for ≥ 30 min live and confirms the
  `{"type", "after": {"camera", "sub_label", "id", …}}` payload shape.
  `tracked_object_update` is not referenced anywhere in-repo and is
  unverified as a real bus event type in this deployment. Probe
  output attached to §3.1 before D1 build.

### 3.1 D1 — Real-time Frigate face bridge (MEASURE-GATED, builds LAST)

**Problem.** Frigate 0.17 publishes recognized-name updates onto the
`frigate_events` HA bus (mirrored from MQTT by the Frigate integration)
BEFORE they propagate to `sensor.<cam>_last_recognized_face[_2]`. In the
resolver's identity window this latency often costs the JOIN.

**Gate condition (H3).** Do not open D1 until BOTH:
1. Frigate service restored (`frigate_status_2` != unavailable ≥ 1h).
2. Probe attached to this doc.

**Design.**
- New module `frigate_face_bridge.py` owned by `camera_census`.
  Setup/teardown mirror `exterior_track_linker`.
- Subscribes to `hass.bus.async_listen(FRIGATE_EVENTS_BUS_EVENT, …)`.
- Callback: `after = event.data.get("after") or {}`; extract
  `sub_label` (`exterior_track_linker.py:256` pattern); extract
  `camera` and **route through `normalize_camera` +
  `EXTERIOR_CAMERA_KEY_ALIASES` (M2)** to the HA sensor stem — else the
  cache is permanently empty (Frigate publishes display-case
  `ReolinkStudyBPorchPTZ`, our stems are lowercase slugs).
- Cache: `{sensor_stem: (name, last_changed_dt, confidence_or_None,
  ingest_ts)}`. `last_changed` = `after.get("frame_time")` if present
  (converted to `datetime`), else `dt_util.now()` at ingest.
- **Wire into `_resolve_face_legs` as a SEPARATE branch BEFORE the
  4-candidate `states.get` loop (M1)** — not a 5th tuple:
  ```
  # Bridge branch (D1)
  bridge_leg = self._bridge_leg_for(base_name)
  if bridge_leg is not None:
      results.append(bridge_leg)
  # Then the existing 4-candidate loop.
  ```
  De-dupe: bridge + `_last_recognized_face_2` carrying the same name
  within `FACE_MATCH_ABSTAIN_MARGIN_S` → keep bridge leg (fresher
  `last_changed`); do NOT emit both as "two engines".
- **Provenance tag:** bridge legs carry `engine="frigate2"` +
  `provenance="face"` (feeds §0 invariant).

**Acceptance:**
- **Live probe attached** (gate).
- **Verify:** `FRIGATE_FACE_BRIDGE_ENABLED=OFF` → resolver behavior
  byte-identical to pre-D1 (regression fixture).
- **Verify:** bridge cache populates for every Frigate camera stem
  observed on the bus within 24 h.
- **Sensor:** `sensor.camera_face_bridge_mqtt_lag_ms` p95 < 3000 ms.
- **Test:** `_ingest`, `_display_case_alias_normalization`,
  `_ttl_expiry`, `_wrong_event_ignored`, `_malformed_payload_defensive`,
  `_bridge_and_sensor_dedup`.
- **Live:** on a face-covered egress crossing,
  `_egress_identity_outcomes` label `attached` or
  `attached_ble_face_corroborated`, `contributor_engines` contains
  `frigate2`, `signed_lag_delta_seconds` inside the FACE_MATCH_*
  window family.

### 3.2 D2 — BLE transition leg in the resolver (BUILDS FIRST)

**Problem.** Face is temporally + spatially decoupled from the crossing
edge; BLE transitions ARE the crossing edge. The naïve source
(`SIGNAL_PERSON_ARRIVING`) is merged with camera_face at
`presence.py:4702` — unusable (C1).

**Design.**
1. Subscribe via `async_track_state_change_event` on `person.<slug>`
   for every slug in `_get_tracked_person_slugs()` (per-slug listener;
   teardown symmetric).
2. Filter: emit a `BleTransitionLeg` ONLY when
   - `old_state.state != new_state.state`, AND
   - transition is home↔not_home, AND
   - **provenance guard:** `new_state.attributes.get("source","")`
     lowercased contains `"bermuda"` OR `"ble"` OR `"private_ble"`.
   Anything else REJECTED (counted in
   `ble_leg_rejected_provenance_count`).
3. `BleTransitionLeg` dataclass sibling of `FaceLeg`:
   `person_slug`, `transition_ts`, `direction`
   (`arriving`/`departing`), `engine="ble"`,
   `confidence=BLE_TRANSITION_CONFIDENCE`, `provenance="ble"`,
   `source_entity`.
4. `_ble_transition_cache: deque[BleTransitionLeg]`, bounded, TTL =
   `BLE_TRANSITION_CACHE_TTL_S` (§6).
5. `_resolve_ble_legs(timestamp, direction)` — in-window BLE legs
   matching direction.
6. `_resolve_egress_face_identity` combines: `face_legs +
   ble_legs`.

**Trust model (with H2 precedence):**
- **BLE-only, no face** → `attached_ble`, `CENSUS_AGREEMENT_SINGLE`,
  `identity_confidence = BLE_TRANSITION_CONFIDENCE`.
- **BLE + agreeing RESIDENT face** →
  `attached_ble_face_corroborated`, `CENSUS_AGREEMENT_TWO_ENGINES`,
  confidence bumped to `BLE_PLUS_FACE_CORROBORATED_CONFIDENCE`.
- **BLE + disagreeing RESIDENT face** → **BLE wins**;
  `ble_face_disagree_ble_wins`.
- **BLE (resident) + disagreeing face (`guest:*`)** → **ABSTAIN
  (H2 fix)** — repro: Oji cached, Ojini named 20 s later must NOT
  be attributed to Oji. Outcome `abstain_resident_vs_guest`. Retains
  `transit_validator.py:1296-1306` DISAGREE→abstain semantics.
- **Face-only, no BLE** → unchanged.
- **No leg** → unchanged.

**Outcome vocabulary extension** (single owner at :1153-1165):
add `"attached_ble"`, `"attached_ble_face_corroborated"`,
`"ble_face_disagree_ble_wins"`, `"abstain_resident_vs_guest"`.

**Acceptance:**
- **Verify:** `person_id` attach rate rises from 1/7265 toward the
  BLE-transition rate (≥ 100 attaches / 14 d combined; discriminator
  > 20× baseline).
- **Verify:** Ziri (away) zero attaches AND zero `ble_face_disagree*`;
  first crossing on return attaches with `ble` provenance +
  Bermuda/BLE `source_entity`.
- **Verify (H2 repro drill):** Oji BLE cached, Ojini face 20 s later →
  `abstain_resident_vs_guest`; DB row for Ojini's crossing MUST NOT
  carry `person_id = oji_udezue`.
- **Test:** `test_ble_leg_only_attaches`,
  `_ble_plus_face_resident_agree_bumps`,
  `_ble_plus_face_resident_disagree_ble_wins`,
  `_ble_resident_plus_face_guest_abstains`,
  `_ble_out_of_window_no_attach`,
  `_person_state_change_geofence_source_rejected`,
  `_person_state_change_no_source_attr_rejected`,
  `_ziri_absent_silent`.
- **Live:** DB query `SELECT person_id, COUNT(*) FROM
  person_entry_exit_events WHERE ts > deploy_ts GROUP BY person_id`
  shows non-null counts for Oji/Jaya/Ezinne within 24 h.

### 3.3 D3 — Known-face-guest identity class (BUILDS SECOND)

**Problem.** Ojini is face-recognized but not in `tracked_persons`;
`_canonical_person_slug` first-token miss → pass-through →
`person.ojini` missing → DROPPED.

**Design.**
1. `known_face_guests` list on INTEGRATION entry options (sibling of
   `tracked_persons`). Seed: `["Ojini"]`.
2. `_canonical_person_slug` extension: after tracked-slug attempts
   fail (before pass-through drop), case-insensitive first-token
   match against `known_face_guests` → return
   `f"guest:{first_token_lower}"`.
3. `guest:*` semantics:
   - Distinct namespace; never collides with tracked (which are
     multi-token underscore-separated).
   - Person-veto (`_resolve_egress_face_identity:1313-1325`) already
     fail-open — `person.guest:ojini` doesn't exist, `states.get`
     returns None, no veto fires. **REUSED, no code change (M3).**
   - DB `identified_persons` carries `guest:*` string as-is.
4. **Precedence (H2):** face first-token matches BOTH tracked AND
   guest → tracked wins.

**Acceptance:**
- **Verify:** `known_face_guests=["Ojini"]` + Frigate up → "Ojini"
  → `canonical_slug = "guest:ojini"`.
- **Verify:** removing `Ojini` reverts to pre-cycle drop.
- **Verify:** tracked-slug first-name wins over guest match
  (`test_tracked_slug_wins_over_guest`).
- **Verify:** guest veto fail-open by construction (M3 regression).
- **Test:** `test_known_face_guest_named`, `_guest_veto_fail_open`,
  `_tracked_slug_wins_over_guest`, `_guest_removed_reverts`.
- **Live:** real Ojini visit → DB row `person_id = "guest:ojini"`.

### 3.4 D4 — FAIL-SAFE (invariant §0) (BUILDS THIRD)

**Design — producer-health guard + provenance gate.**
1. `_is_face_producer_live()` — read-time, per resolver call:
   - Frigate: `binary_sensor.frigate_status_2 != unavailable`.
   - Protect: NVR status entity (grep in build; degrade to per-leg
     `last_changed` age gate if absent).
   - MQTT bridge: `now - last_ingest_ts > FACE_PRODUCER_STALE_TTL_S`
     → DEAD.
   - **Drill switch (see below): if
     `switch.egress_identity_face_failsafe_drill = on`, ALL face
     branches return DEAD unconditionally.**
2. `_resolve_face_legs` sources skipped when their producer is DEAD
   — no stale-cache reuse.
3. **Per-leg staleness gate (defense-in-depth):** face leg dropped
   if `now - leg.last_changed > FACE_PRODUCER_STALE_TTL_S`.
4. **Provenance gate:** every leg carries `provenance` (`"face"` or
   `"ble"`). When any face producer is DEAD AND
   `EGRESS_IDENTITY_FAILSAFE_STRICT=ON` (default), all
   `provenance=="face"` legs filtered out at the top of
   `_resolve_egress_face_identity`. This is the code embodiment of §0.
5. **Census union guard (H1):** same provenance filter at the union
   write path (`camera_census.py:2017`, `:3954`).
6. BLE path INDEPENDENT — `_resolve_ble_legs` never reads face state.
7. No new async_call_later / timers / suppression: read-time only.
   Restart-safe (no cache survives).

#### 3.4.1 Live drill affordance (on-demand — Frigate will be UP at validation time)

Frigate will be UP by review/validation time, so the §0 invariant
cannot be validated by a natural outage. A dedicated **on-demand
drill switch** forces the producer-down condition WITH Frigate healthy.

- **Knob:** `switch.egress_identity_face_failsafe_drill` (NEW; distinct
  from `EGRESS_IDENTITY_FAILSAFE_STRICT` — the two are OPPOSITE
  concepts: `_STRICT` is the always-on kill-switch that ENABLES the
  fail-safe machinery; the drill switch FORCES its trigger condition.
  `_STRICT=OFF` during a drill would prove nothing because the guard
  wouldn't run). Rung: **Switch entity** (dashboard-exposed, persisted
  via the URA Number-persistence machinery), labelled
  `Egress Identity Fail-Safe Drill (drill only)`.
- **Mechanism:** when engaged, `_is_face_producer_live()` returns
  `False` for the frigate2 AND protect2 AND mqtt_bridge branches
  unconditionally. Nothing else changes — no Frigate service is
  touched, no HA entity is faked. `sensor.face_producer_health` exposes
  a `reason` attribute distinguishing `drill_forced` from natural
  causes (`frigate_down` / `mqtt_stale` / `protect_down`).
- **Drill-of-the-drill safety:** leaving the switch engaged is NEVER
  unsafe. It can ONLY suppress face-provenance identity, which
  degrades to BLE (residents) or anonymous (guests). It cannot
  escalate any alert, cannot fabricate an identity, cannot bypass a
  veto. Documented inline at the switch entity description and on the
  dashboard label. A boot with the switch ON logs a WARNING and
  raises a repair issue so it cannot be silently left engaged.

**Drill procedure.**
1. Confirm Frigate healthy: `binary_sensor.frigate_status_2 = on`,
   `sensor.face_producer_health = live`, a recent
   `sensor.<cam>_last_recognized_face_2` state within 10 min.
2. Engage: `switch.egress_identity_face_failsafe_drill → on`.
3. `sensor.face_producer_health` flips to `down` with
   `reason=drill_forced` within one resolver tick.
4. Perform ≥ 3 real egress crossings covering:
   (a) a resident with a Bermuda/BLE beacon,
   (b) Ojini or another known-face guest (arrange OR trigger a face
       event for that name via an existing Frigate test path),
   (c) an unknown crossing (no BLE, not in `known_face_guests`).
5. Read outcomes deque + DB rows + census sensor.
6. Release: `switch.egress_identity_face_failsafe_drill → off`.
   `face_producer_health` returns to `live` within one tick; the next
   crossing may attach via face again.

**Discriminating live-observable acceptance (each is a live check,
not in-suite only):**
- **(a) Zero face-provenance attaches on ANY path.** DB query on
  `person_entry_exit_events` for the drill window: no row with
  `engine` containing `frigate` OR `protect`.
  `_egress_identity_outcomes` contains zero `attached` /
  `attached_ble_face_corroborated`; only `attached_ble`, `no_leg`,
  `abstain_*` are legal.
- **(b) BLE resident naming still works.** Resident crossings during
  the drill produce `attached_ble`; DB rows carry `person_id` =
  resident slug, `engine = "ble"`, Bermuda/BLE `source_entity`.
- **(c) Guest (Ojini) reads anonymous, NEVER misattributed.**
  Ojini's crossing during the drill produces `no_leg`; DB row
  `person_id` is NULL; census `identified_guests_count` unchanged;
  and CRITICALLY her crossing MUST NOT be attributed to Oji or any
  resident (H2 hazard replayed under the drill).
- **(d) No pipeline stall.** Median resolver latency during the
  drill within 2× of pre-drill median (grep resolver-latency
  telemetry); no bounded `async_call_later` leak
  (`hass.data` inspection); the delayed-resolve queue drains
  normally.
- **(e) No security-alert severity downgrade.**
  `sensor.perimeter_alert` (and any alert deriving `severity` from
  identity) fires at pre-drill sensitivity for the same crossings;
  histogram of `severity` for the drill window matches the
  pre-drill window ± noise floor.

**Post-release re-verification.** After `off`, the next face-covered
resident crossing produces `attached` or
`attached_ble_face_corroborated` (face-provenance resumes).

**Secondary passive confirmation (NOT a gate — supplements the
on-demand drill).** Frigate was down 4 days recently; a natural flap
WILL recur. The `_egress_identity_outcomes` deque should show the
fail-safe engaging (`face_dropped_producer_down_count` incrementing,
`attached_ble` labels appearing) and releasing (face labels returning)
across a real flap. Operator or Shipwatch-style watcher can passively
observe — no ceremony, no gate; confirms the drill's mechanism
matches the natural failure mode.

#### 3.4.2 Unit + mutation drills (M4 — must drive REAL `_resolve_face_legs`)

- **`test_face_producer_dead_no_face_legs`:** set `hass.states` such
  that `frigate_status_2 = unavailable`, populate a live-looking
  `sensor.<cam>_last_recognized_face_2` state, call the REAL
  `_resolve_face_legs` end-to-end, assert `[]`. Do NOT monkeypatch
  the accessor wholesale.
- **`test_face_producer_stale_no_face_legs`:** producer LIVE but
  `last_changed` older than TTL → dropped.
- **`test_ble_still_names_when_face_dead`:** face dead, BLE in-window
  → `attached_ble`, `provenance=ble`.
- **`test_census_union_rejects_face_provenance_under_outage` (H1):**
  identity union recompute at `:2029` under simulated outage receives
  NO face-provenance names.
- **`test_no_pipeline_stall_on_face_dead`:** resolver returns within
  budget; no bounded `async_call_later` leaks.
- **`test_drill_switch_forces_face_dead`:** engage switch with all
  face sensors LIVE → `_is_face_producer_live()` returns False for
  every face branch; `_resolve_face_legs` returns `[]`.
- **`test_drill_switch_off_restores_face_live`.**
- **`test_drill_switch_never_escalates`:** engage drill mid-scenario;
  assert no alert severity increases.
- **`test_drill_switch_persists_across_restart_with_warning`:** boot
  with switch ON → RestoreEntity carries state, WARNING logged,
  repair issue raised.
- **Mutation drill:** neuter `_is_face_producer_live` (force True) →
  `test_face_producer_dead_no_face_legs` MUST fail; neuter the
  per-leg staleness gate → `test_face_producer_stale_no_face_legs`
  MUST fail; neuter the provenance filter → the census-union test
  MUST fail; neuter the drill-forced branch →
  `test_drill_switch_forces_face_dead` MUST fail.

### 3.5 H1 — Census identity union: INTENDED behavior spec

The resolver flows into the census union via
`transit_validator.py:1493 register_egress_face` →
`camera_census.py:2017` (union feeder) →
`camera_census.py:3954` (`_get_face_recognized_person_names`) →
`camera_census.py:2029` (`identified_count` / `unidentified_count`
recompute) → GUEST mode. ALREADY WIRED; consumers-are-non-goal does
NOT apply to this path (per plan-review H1).

**Intended union behavior:**
1. **BLE-derived attaches (resident slugs, provenance=`ble`):** enter
   the identity union as identified residents (contribute to
   `identified_count`). Union is a SET of slugs — a slug already in
   the set from a prior face event is unchanged (no double-count).
2. **`guest:*` slugs:** enter a SEPARATE set (`identified_guests`) —
   do NOT commingle with the tracked-resident set (this is the prior
   double-count incident surface —
   `feedback_cross_investigation_synthesis.md`). `identified_count`
   (resident scope) is UNAFFECTED by `guest:*` entries.
   `unidentified_count = <detected persons> − identified_count −
   identified_guests_count`.
3. **Under face-producer outage (D4, natural OR drill):** union
   additions from face provenance are gated OFF; only BLE-provenance
   additions accrue. Existing set entries from before the outage age
   out at `EGRESS_FACE_UNION_TTL_S`.

**Acceptance (H1, guest-math non-corruption — HARD):**
- **Verify:** 3 residents home (BLE-derived) + 1 Ojini guest
  (`guest:ojini`) → `identified_count = 3`, `identified_guests_count
  = 1`, `unidentified_count = 0`. Guest does NOT inflate resident
  count.
- **Verify:** same scenario with drill engaged (or Frigate down):
  `identified_count = 3` (from BLE), `identified_guests_count = 0`,
  `unidentified_count` picks up the unattributed detection. NO
  face-provenance name enters either set.
- **Verify (prior double-count regression):** `_recompute_identity_union`
  under D2+D3 does NOT double-count the same resident when a BLE leg
  and a face leg both attach the SAME slug within
  `EGRESS_FACE_UNION_TTL_S`. Set semantics.
- **Test:** `test_union_resident_ble_only`,
  `_union_resident_ble_plus_face_no_double_count`,
  `_union_guest_slug_separate_counter`,
  `_union_under_outage_face_provenance_excluded`,
  `_union_guest_math_regression_v5_16_style`.
- **Live:** post-deploy census sensor attributes show
  `identified_persons`, `identified_guests`, `unidentified_count` as
  three DISTINCT tallies; a natural guest visit does not perturb
  `identified_count`.

---

## 4. Producer / Consumer map

**Producer arithmetic — identity attach.**
- Inputs: `_resolve_face_legs(stem)` (existing HA-sensor 4-candidate
  loop + D1 MQTT-bridge branch when enabled + gated) — all
  `provenance="face"`; PLUS `_resolve_ble_legs(ts, direction)` — all
  `provenance="ble"`.
- Dependency health: `_is_face_producer_live` guards face branch per
  source (including the drill switch); BLE branch depends only on
  the always-on person_coordinator / device_tracker platform.
- Multiple derivations: BLE wins over disagreeing RESIDENT face;
  BLE + guest face → ABSTAIN (H2).

**Consumers this cycle.** Two:
1. `transit_validator._resolve_egress_face_identity` (extension site).
2. `camera_census` identity union (H1) at `:2017` / `:2029` /
   `:3954` — already wired.

All OTHER consumers stay non-goal per §7.

---

## 5. Telemetry / observability

- REUSED: `_egress_identity_outcomes` deque,
  `_egress_identity_agreement_class_last`,
  `_egress_identity_last_attach`, `_egress_identity_boost_events`
  (extend outcome enum only).
- NEW: `sensor.camera_face_bridge_mqtt_lag_ms` (D1, gated).
- NEW: `sensor.face_producer_health` (`live`/`stale`/`down`, per-source
  attributes: `frigate2`, `protect2`, `mqtt_bridge`, plus `reason`
  attribute — `drill_forced` vs natural causes).
- NEW counters: `attached_ble_count`,
  `attached_ble_face_corroborated_count`, `attached_guest_count`,
  `ble_face_disagree_ble_wins_count`,
  `abstain_resident_vs_guest_count`, `face_dropped_stale_count`,
  `face_dropped_producer_down_count`,
  `face_dropped_drill_forced_count`,
  `ble_leg_rejected_provenance_count`.
- NEW: `sensor.census_identified_guests_count` (H1 — third distinct
  tally so guest-math is observable).
- NEW: `switch.egress_identity_face_failsafe_drill` (§3.4.1).

---

## 6. Numbers-get-knobs — ladder placement

| Knob | Value | Rung | Why |
|---|---|---|---|
| `FACE_PRODUCER_STALE_TTL_S` | 120 s | Module constant | Safety bound; wrong value reintroduces §0 hazard. |
| `BLE_TRANSITION_CONFIDENCE` | 0.75 | Module constant | Fitted trust weight; drift silently rebalances agreement. |
| `BLE_PLUS_FACE_CORROBORATED_CONFIDENCE` | 0.95 | Module constant | Must dominate face-only and BLE-only in ranking. |
| `BLE_TRANSITION_CACHE_TTL_S` | `max(FACE_MATCH_EXIT_WINDOW_BEFORE_S, FACE_MATCH_EXIT_WINDOW_AFTER_S, FACE_MATCH_ENTRY_WINDOW_BEFORE_S, FACE_MATCH_ENTRY_WINDOW_AFTER_S) + 30` = **330 s** (C4) | Module constant, derived | Coupled to the FACE_MATCH_* window FAMILY (max = `FACE_MATCH_ENTRY_WINDOW_AFTER_S=300`), NOT the `EGRESS_ENTRY/EXIT_WINDOW_SECONDS` scheduling knobs. |
| `known_face_guests` list | `["Ojini"]` seed | Config/options flow | Operator adds face-library names as guests appear. |
| `FRIGATE_FACE_BRIDGE_ENABLED` | OFF at merge; ON after D1 gate met | Config/options flow | Kill-switch; OFF = D1 branch inert. |
| `EGRESS_IDENTITY_FAILSAFE_STRICT` | ON | Config/options flow | Kill-switch that ENABLES the D4 provenance filter + producer-health guard. Reviewer-drill use only; documented at the knob as "operator should never turn OFF in production". |
| `switch.egress_identity_face_failsafe_drill` | OFF at merge; on-demand | **Switch entity** (dashboard-exposed, persisted via URA Number-persistence machinery) | On-demand live drill of §0 (§3.4.1). Distinct from `_STRICT` — this FORCES the trigger while `_STRICT` remains ON so the guard actually runs. Fail-safe of the drill itself: engaged = degrade to BLE/anonymous only; NEVER escalates. Boot with ON → WARNING + repair issue. |
| Window / abstain-margin params | unchanged | Module constant (existing) | Not touched. |

---

## 7. Non-goals

- **Frigate service stability** — operator restores out-of-band; D1
  MEASURE-GATED behind that restore.
- **Downstream consumers OTHER than the census identity union** —
  perimeter alerts, arrival/departure NM, guest gate consuming
  door-identity, egress-arm identity all stay carded in
  `AUDIT_census_identity_supersession_and_consumers.md`. The census
  identity union (H1) IS in scope because it's already wired.
- **Door-naming cards, census-unknown, egress-arm** — out.
- **Protect Alarm Manager webhook** — empty payloads, separate fix.
- **Window-parameter retunes** — measure-before-tune; not this cycle.
- **Migration cycle** — single-user; additive knobs default safe.

---

## 8. Tier + review plan

- **Tier 2-DB (M5).** 3 framing-disjoint build reviews + Reviewer D
  framed on §0 fail-safe.
- **Plan review (already run):** FIX-REQUIRED with 7 must-fix + drill
  affordance addition; this revision applies all. See §11.
- **Build reviews (3 parallel, framing-disjoint):**
  - **Review A — data integrity + union preservation.** H1 union
    semantics; set vs count, guest-math regression; DB row shape;
    identified_count invariants.
  - **Review B — migration + signal-chain integrity.** Every leg
    provenance tag preserved end-to-end; D2 `person.<slug>` state
    listener re-enumeration (grep every `SIGNAL_PERSON_*` and
    `person.<slug>` state consumer for double-emit risk); D1 bridge
    branch does not shadow or double-emit HA-sensor legs.
  - **Review C — new surfaces + test authority.** MQTT-bridge
    listener lifecycle; new sensors + drill switch round-trip;
    behavioral tests drive REAL `_resolve_face_legs` (M4).
  - **Reviewer D — §0 fail-safe invariant.** State the invariant in
    falsifiable form; break it. Re-enumerate ALL emission/decision
    sites INCLUDING pre-existing code; every flag with legal-config
    reachable repro. Explicitly probe: (i) can any face-provenance
    name reach the union under outage OR drill? (ii) can any accessor
    other than `_resolve_face_legs` produce a face leg? (iii) can the
    bridge cache serve a name whose ingest predates the current
    outage/drill? (iv) can the drill switch's `_STRICT`-independent
    behavior be bypassed by any code path?
- **Live validation (Review D+):** primary = the on-demand drill
  (§3.4.1) with Frigate healthy; secondary = natural-flap passive
  observation; plus H1 guest-math queries at +24 h and D2 attach-rate
  DB query.

---

## 9. Files touched

- `const.py` — new knob constants (§6).
- `camera_census.py` — MQTT bridge branch in `_resolve_face_legs`
  (D1, gated); guest slug in `_canonical_person_slug` (D3);
  `_resolve_ble_legs` + `_ble_transition_cache` + per-slug
  `person.<slug>` state-change listeners with provenance guard (D2);
  `_is_face_producer_live` (with drill-switch branch) + provenance
  filter at `_resolve_face_legs` and census union write path
  (D4/H1); H1 `identified_guests` separate tally.
- `frigate_face_bridge.py` — NEW module (D1, MEASURE-GATED).
- `transit_validator.py` — leg-set assembly extension (BLE +
  provenance); outcome vocabulary; H2 precedence branches;
  provenance top-of-resolver filter (D4).
- `config_flow.py` / `options_flow.py` — `known_face_guests`,
  `FRIGATE_FACE_BRIDGE_ENABLED`, `EGRESS_IDENTITY_FAILSAFE_STRICT`.
- `switch.py` — NEW `EgressIdentityFaceFailsafeDrillSwitch`
  (RestoreEntity, WARNING + repair issue on boot-ON).
- `sensor.py` — new diagnostic sensors (§5).
- `quality/tests/` — new test files per §3 acceptance sections;
  mutation drill script for D4.
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` — face-source
  table gains MQTT bridge row (post-D1); §0 fail-safe invariant
  added as canonical; census union H1 semantics; drill affordance
  §3.4.1 referenced; version bump at deploy.

---

## 10. Deferrals / plan-completion tracking

All §7 non-goals are cards. Any deliverable deferred at build time
MUST be listed at cycle close with WHY + tracking location.

---

## 11. Changelog

**Revision 2 (2026-09-04, coordinator addendum — on-demand drill):**
14. **D4 live drill affordance.** Frigate will be UP by
    review/validation time; the §0 invariant cannot be validated by a
    natural outage. Added `switch.egress_identity_face_failsafe_drill`
    (Switch-entity rung, dashboard-exposed, RestoreEntity persistence,
    boot-ON → WARNING + repair issue). Distinct from
    `EGRESS_IDENTITY_FAILSAFE_STRICT` (opposite concepts — `_STRICT`
    ENABLES the guard, drill FORCES its trigger). Mechanism forces
    `_is_face_producer_live()` False for all face branches
    unconditionally; nothing else changes. Drill is itself fail-safe
    (can ONLY suppress → degrade to BLE/anonymous; never escalates
    an alert or fabricates an identity). Full procedure + five
    discriminating live-observable acceptance checks (a)–(e) added at
    §3.4.1. Secondary passive-confirm (natural flap) documented but
    NOT a gate. Added `face_dropped_drill_forced_count` counter and
    `reason=drill_forced` attribute on `sensor.face_producer_health`
    to distinguish drill vs natural down. Added four unit tests
    (`test_drill_switch_forces_face_dead`,
    `_off_restores_face_live`, `_never_escalates`,
    `_persists_across_restart_with_warning`) and extended the
    mutation drill. Reviewer D probe (iv) added.

**Revision 1 (2026-09-04, plan-review FIX-REQUIRED):**
1. **C1 (BLE provenance):** Source flipped from `SIGNAL_PERSON_ARRIVING`
   (merged: ble + geofence + camera_face at `presence.py:4702`) to
   `person.<slug>` state_changed transitions, gated by
   `attributes["source"]` substring match on `bermuda`/`ble`/`private_ble`.
   §0 broadened to PROVENANCE not just accessor identity.
2. **C2 (departure signal):** BLE listener covers BOTH directions.
3. **C3 (measured rate correction):** 126/10d SIGNAL_PERSON_ARRIVING
   → 106/14d `person.<slug>`, provenance clean.
4. **C4 (TTL derivation):** BLE cache TTL derives from FACE_MATCH_*
   family max (330 s), NOT EGRESS_ENTRY/EXIT scheduling knobs.
5. **H1 (census union spec):** §3.5 added with guest-math
   non-corruption criterion; consumers-non-goal removed for this
   already-wired path.
6. **H2 (guest precedence):** BLE wins ONLY vs RESIDENT face; BLE
   (resident) vs face (`guest:*`) → ABSTAIN. Oji-then-Ojini repro.
7. **H3 (sequencing + MEASURE-GATED D1):** Build order D2 → D3 → D4
   → D1; D1 gated on Frigate restore + live bus probe.
8. **M1 (D1 wiring):** MQTT bridge = SEPARATE branch BEFORE the
   4-candidate loop, not a 5th tuple.
9. **M2 (camera alias):** `after["camera"]` routed through
   `normalize_camera` + `EXTERIOR_CAMERA_KEY_ALIASES`.
10. **M3 (guest veto):** already fail-open; REUSED, no code change.
11. **M4 (D4 drill authenticity):** tests drive REAL
    `_resolve_face_legs`; mutation exercises guards themselves.
12. **M5 (tier elevation):** Tier 2 → **Tier 2-DB**.
13. **Citation fixes:** `_resolve_face_entity_id` :2654;
    `sub_label` :256; `FRIGATE_EVENTS_BUS_EVENT` at
    `exterior_track_linker.py:53`.
