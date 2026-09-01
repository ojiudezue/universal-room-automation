# AUDIT — Egress-identity producer: post-ship supersession & consumer-gap (2026-08-28)

Post-ship audit per CLAUDE.md "Post-Ship Supersession & Consumer-Gap Audit", run the night the
egress-identity **producer** shipped in **v5.91.4** (card `EGRESS-IDENTITY-JOIN-GAP-1`). The producer
stamps advisory `person_id` (canonical slug) + identity confidence (0.6 single-leg / 0.75 same-camera
two-engine / 0.9 cross-camera) onto `person_entry_exit_events` and the `ura_person_egress_event` bus
event; observability via the census sensor's `egress_identity_*` D3 attrs.

Extends the 2026-08-18 `AUDIT_census_identity_supersession_and_consumers.md` (§3 gaps G1–G5). Method:
four parallel read-only scans (HVAC, Notification, Security coordinators + shipped-4mo/roadmap
retrospective), grep-grounded, deduped against existing cards.

---

## 0. Coverage reality (measure-before-build gate) — CORRECTED 2026-08-28

The producer is armed but currently stamps `person_id` on **0 of 7,123** crossings/24h. Root cause is
NOT "face rec down" (an earlier probe error that checked only the dead Frigate sensors):

- **Frigate** `sensor.*_last_recognized_face_2` — the source `_resolve_face_legs` reads today — IS
  dead/stuck at `Unknown` house-wide.
- **Protect** face rec is **ALIVE**: `protect_list_smart_detections` shows 19 face events in recent
  hours (conf up to 95); `protect_list_known_faces` has **Oji** (46 detections, avg conf 82, active),
  **Ziri** (40, conf 79), Ade+Shola (minimal), Jaya/Ezinne NOT enrolled, plus unenrolled clusters
  (`face_265`, `face_degraded_*`).
- **The producer has no live source wired**: URA reads the dead Frigate feed + the Protect bridge
  `sensor.<cam>_face_recognized`, which is **D1 (outside-URA) and UNBUILT**.

**Therefore every consumer below is gated on building D1** (poll the Protect API → republish
`_face_recognized`, mapping `recognized_person_id`→name via the Known-Faces registry), then re-measuring
the real attach rate at the egress cameras. Consumers are graceful-anonymous so nothing breaks meanwhile.

---

## 1. Supersession → three-bucket triage

What does per-person egress identity make redundant? **Scope = the identity DOMAIN, not the cycle diff.**

- **DELETE — none.** No dead-and-useless code is superseded by the producer. (Clean, expected outcome.)
- **KEEP + WIRE (should-be-consuming gaps):** the naive `camera_total > ble_total` unexpected-person
  count (`binary_sensor.py:1540`) is a live heuristic that SHOULD consume egress identity to subtract a
  phone-left-behind resident — see §3. This is a gap, not debt.
- **KEEP + DOCUMENT:** the confidence tiers (0.75/0.9) are currently read by NO consumer — forward infra,
  not dead code; documented in manual §5.5 as awaiting the first confidence-gating consumer.

Distinct-semantics (NOT triage subjects): the 4 display sensors' `person_id` reads are live consumers.

---

## 2. Producer / Consumer map

**Producer arithmetic:** interior-face fusion over {egress cam stem ∪ interior-adjacent cams} within a
direction-keyed asymmetric window; agreement model → HIGH 0.9 (≥2 legs, distinct `base_stem`) / CORRELATED
0.75 (same camera, 2 engines) / MEDIUM 0.6 (single); abstain on ≥2 distinct names. Dependency health:
Frigate feed DEAD, Protect bridge UNBUILT → producer starved (see §0).

**Real consumers TODAY (verified in code):**
- `PersonsEnteredTodaySensor` (`sensor.py:4268`), `PersonsExitedTodaySensor` (`:4386`),
  `LastPersonEntrySensor` (`:4464`), `LastPersonExitSensor` (`:4512`) — read `person_id`, fall back to
  `"unidentified"`. **Display only; no decision, no confidence read.**
- `identity_confidence` / `agreement_class`: **zero readers** (grep-confirmed).

---

## 3. Should-be-consuming-but-isn't (ranked)

Confidence doctrine (manual §5.5): **security suppress/actuate ≥0.9 (de-escalate/annotate only, never
escalate from identity); notification naming ≥0.75; display none.** Asymmetric cost: a single-leg misID
used to suppress a security alert admits a stranger silently.

| # | Opportunity | Card | Gate | Wire-in | Value |
|---|---|---|---|---|---|
| 1 | Perimeter alert names the person ("Oji at the side door" vs "Person Detected"); resident-alert self-de-escalates | `PERIMETER-ALERT-NAME-PERSON-1` (enriched) | ≥0.75 | `perimeter_alert.py:1316`; join via face resolver (perimeter cam is exterior-detection, not the egress crossing) | **Highest daily** (deep-night S/N) |
| 2 | Arrival/departure notify ("Jaya left") | `ARRIVAL-DEPARTURE-NOTIFY-1` (enriched) | none (graceful-anon) | `transit_validator.py:1279` egress event | Daily, **lowest-risk** |
| 3 | Guest gate consumes door-identity — a recognized resident stops triggering GUEST→auto-arm | `GUEST-GATE-DOOR-IDENTITY-1` (enriched) | **≥0.9** (suppressing guest wrongly UNDER-secures) | `presence.py:4988` (`_is_known_person_in_room`, BLE-only today) | High (census double-count wound) |
| 4 | Security unknown-person path consumes census identity — **the whole SanctionChecker census path is DORMANT today** | `SECURITY-CENSUS-UNKNOWN-WIRE-1` (enriched) | **≥0.9 suppress-only** | `security.py:239/313/985` | Med, footgun |
| 5 | "Unexpected person" = "person we can't NAME" (subtract phone-left-behind resident) | `UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1` (enriched) | **≥0.9** (live ALERT path) | `binary_sensor.py:1540` | Med |
| 6 | Security entry-verdict names the person (verdict already knows "known person, unusual timing" but drops WHO) — **NEW/uncarded before tonight** | `SECURITY-ENTRY-VERDICT-NAME-1` (new) | ≥0.75 | `security.py:1480/1573` | Med (high per-event) |
| 7 | HVAC pre-arrival consumes the camera-face "who arrived" signal it currently drops — **independent of the egress producer** | `HVAC-CAMERA-FACE-ARRIVAL-SOURCE-1` (new) | ~0.6+ | `hvac.py:529/977` (source filter defaults to `[geofence,ble]`, ignores `source="camera_face"` from `presence.py:4702`) | Cheap high-signal HVAC win |
| 8 | Last-resident-egress → arm-away accelerate — **NEW, investigate-first** | `LAST-RESIDENT-EGRESS-ARM-1` (new) | **≥0.9 confirm-only** (census `residents_home==0` stays authority; never arm on identity alone) | `security.py:1114-1360` | Low |
| 9 | Dashboard tile for the egress observability attrs ("who entered today, named") — NEW | `EGRESS-IDENTITY-DASHBOARD-TILE-1` (new) | none | `sensor.py:4260` | Low display |
| 10 | Transit checkpoints keyed to `person_id` (per-person movement paths; feeds agentic layer) — NEW, PARKED | `TRANSIT-PERSON-CHECKPOINT-1` (new, parked) | — | traversal checkpoints (v5.60.0) | Speculative |

**Key discovery (Security scan):** the SanctionChecker unexpected/unknown-person machinery **never
executes** today — `manager.py:607-618` `_build_context()` never sets a `"census"` key, no
`source="census_update"` intent is emitted, and security isn't a `SIGNAL_CENSUS_UPDATED` subscriber. So
"unexpected person" is currently only the naive `camera_total > ble_total` count with no identity. Wiring
census identity here is both an unblock AND a footgun (auto-locks all doors) → investigate-first + ≥0.9
suppress-only + kill switch.

**HVAC scan bottom line:** the egress-*departure* gap is real but LOW (HVAC already setbacks on vacancy;
identity only buys the lead-time minutes, and namespace mismatch slug↔`person.<entity>` adds cost). The
high-value HVAC identity win is on the *arrival* side (#7), independent of this producer. Per-person
setpoints (`hvac.py:3585`) are heavy/marginal — most zones are single-sleeper, shared preset ≈ primary's
preference; marginal-benefit-gated maybe, not carded.

---

## 4. Recommended sequence

1. **Build D1 Protect bridge** (the real unblock — Protect names Oji/Ziri now) → re-measure attach rate.
2. **First consumers (if yield real):** #1 perimeter-naming + #2 arrival/departure — display/notify, safe
   under sparse coverage, justify the ≥0.75 naming tier.
3. **Parallel cheap win, no egress dep:** #7 HVAC camera-face arrival-source.
4. **Later, Tier 2-DB + measured-coverage-gated:** the security suppressors (#3/#4/#5/#6/#8) under the
   ≥0.9-only doctrine.

Refs: manual `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md §5.5`; prior
`AUDIT_census_identity_supersession_and_consumers.md`; memory
`reference_egress_face_coverage_7pct_not_a_ceiling` (carries the corrected face-rec finding).
