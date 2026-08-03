# PLANNING — Exterior Track Linking (perimeter person de-duplication + path)

Status: QUEUED (operator concept 2026-08-03, awaiting go). Tier: 2-DB
(threads into perimeter→NM severity path — regression-prone per standing
policy).

**Operator prompt:** the 2026-08-02 19:57–20:13 walker crossed THREE
perimeter cameras (utilities → rear → front-side, 10 Frigate person
events) and the system had no way to know it was ONE person — per-camera
alerting would read as 4+ unidentified persons. "Any way to do exterior
path tracking like we do interior? Might be a good sec coordinator trick
and prevent generically over-counting unidentified perimeter persons."

## Institutional context verified

- **NOT done before** (exhaustive sweep 2026-08-03): perimeter_alert.py
  is strictly per-camera (independent events, per-camera cooldowns, no
  identity linking). Census dedup work
  (PLANNING_census_overcount_dedup_decay.md) is interior-only.
  CATALOG_cross_correlation_primitives.md has no exterior-track entry.
- **REUSED ingredients:**
  - `transit_validator.py:339 _correlate_sighting_to_transition` + its
    sighting cache — the interior temporal-correlation pattern this
    copies (TransitValidator already proves the shape works).
  - `EgressDirectionTracker` (transit_validator.py:482) — direction
    inference precedent (entry-vs-exit ordering).
  - `PerimeterAlertManager` event stream + `frigate_events` bridge —
    the detection source, already wired, with event ids + scores.
  - **Memory identity/locality**: exterior cameras need an adjacency
    graph exactly like rooms (architecture §5b self-locality) — for
    cameras it is small enough to be operator-DECLARED config (9
    perimeter cams; a ring is ~10 edges). Stored as a house-level
    memory fact (topic: adjacency_graph, node domain exterior) for
    provenance symmetry.
  - Memory `memory_episodes` — a completed track is the natural episode
    (`exterior_track`, attrs: camera sequence, duration, event ids,
    classification), giving recurrence queries ("tracks matching
    circling in last month") for free.
- **Design doc read:** PLANNING_exterior_person_escalation.md INV-XP —
  the invariant this must NOT weaken (one CRITICAL per camera per
  cooldown when away). Track linking sits ABOVE the alert layer:
  same-track suppression is a REFINEMENT of cadence, never a new
  bypass.

## Concept

**ExteriorTrackLinker** (security-coordinator-owned): consume perimeter
person events; link event E to an open track T when (a) E's camera is
adjacent (declared graph) to T's last camera OR the same camera, AND
(b) Δt since T's last event ≤ TRACK_LINK_WINDOW_S (~180 s, rung-1).
Track closes after TRACK_CLOSE_IDLE_S (~300 s) of silence. No ML, no
re-identification — pure space-time plausibility, the same doctrine as
interior transit validation. (2026-08-02 replay: 10 events → exactly 1
track, utilities→rear→front-side→utilities→front→rear, 16 min.)

**What a track buys:**
1. **Counting**: perimeter person COUNT = open tracks, not events.
   Fixes the over-count the operator flagged; census/security surfaces
   report "1 unidentified person (3 cameras, 16 min)".
2. **Severity shaping** (the sec-coordinator trick): classification
   from the path — `pass_by` (boundary cameras only, monotonic
   progression, exits) vs `approach` (reaches egress-adjacent cameras)
   vs `circling` (revisits / ≥3 cameras / dwell above threshold).
   While away/sleep: circling/approach escalate ABOVE the current flat
   CRITICAL (repeat notification with path narrative + latest
   snapshot); pass_by can demote to a single digest line — last
   night's walker becomes one quiet line, not 4 suppressed CRITICALs.
3. **Narrative**: the NM message carries the path ("utilities → rear →
   front-side, 16 min, last seen heading N") and the track episode
   feeds memory narrative()/episodes().
4. **Vehicle extension (operator 2026-08-03)**: same linker, `car`
   label — deep-night vehicle track while away/sleep = high-severity
   negative signal; daytime = ignore. Config: label list + per-label
   severity map. Rides the same primitive, deferred to a second cycle.

## Track typing, representation, and surfaces (operator 2026-08-03)

**Per-identification-type tracks.** A track is keyed by Frigate label —
person, car, dog/cat (animal family) — and events only link WITHIN a
label (a car event never extends a person track; two labels moving
together produce two parallel tracks, which is correct: "person + car
arriving" is richer than either). Frigate `sub_label` (recognized
plate, face name if ever enabled) rides in attrs when present and can
PROMOTE a track's identity (sub-labeled track = identified, exits the
unidentified count). Severity policy is a (label × house-state × path
class) map: person/circling/away = highest; car/deep-night/away = high
(the operator's negative-signal case); animal/* = digest-only default.

**Path representation.** A track is an ordered hop list:
`[(camera, t_first, t_last, best_score, best_event_id), ...]` with
derived fields: duration, camera_count, revisit_count, direction
(computed against the declared adjacency ring: clockwise / counter /
inbound-toward-egress), and classification (pass_by / approach /
circling). Persisted verbatim in the `exterior_track` episode's
attrs_json; rendered compactly everywhere else as
`"utilities → rear → front-side · 16 min · person"` with the best
event_id per hop giving snapshot deep-links (the NM alert attaches the
LATEST hop's snapshot; the episode keeps them all).

**Census surface.** Interior census machinery is untouched. The
security/census sensors gain exterior counters derived from OPEN
tracks, not raw events: `exterior_person_tracks_active`,
`exterior_vehicle_tracks_active`, `exterior_animal_tracks_active`, plus
`exterior_unidentified_persons` (open person tracks without sub_label —
the number that replaces today's implicit per-camera overcount). One
walker = 1 everywhere, for the whole track lifetime.

**Dashboard surfaces (ura-v8).**
- Security tab, above the camera zones: an "Exterior activity" section —
  a markdown card listing OPEN tracks (label icon · path string · age ·
  last camera, tap → that camera's view) and, below it, last-24h closed
  tracks pulled via memory_query episodes(exterior_track) (path string +
  classification + time). Empty state: "perimeter quiet".
- Now/People census card gains one line: "Exterior: N tracks (M
  unidentified)" from the new counters.
- The NM CRITICAL/digest message body carries the path string — the
  operator sees "1 person, utilities → rear → front-side, 16 min"
  instead of four independent camera alerts.

## Parsimony guards

- No re-identification / appearance matching — space-time only. If two
  people walk the perimeter simultaneously on non-adjacent cameras,
  two tracks form (correct); if they swap, we don't care (count still
  right within ±1) — explicitly out of scope.
- Adjacency DECLARED (9 cameras), not learned — the room-adjacency
  derivation machinery is overkill at this scale.
- Alert-layer change is severity/cadence REFINEMENT under INV-XP, not
  new dispatch paths.
- Falsifiable invariant for the eventual Tier 2-DB review: "a single
  person crossing N adjacent perimeter cameras within link windows
  yields exactly one track and at most one alert thread."

## Acceptance sketch (full criteria at build time)

- **Test:** 2026-08-02 event replay fixture → 1 track, correct sequence.
- **Test:** two simultaneous non-adjacent detections → 2 tracks.
- **Test:** INV-XP unweakened (mutation-anchored on the alert gate).
- **Live:** next organic multi-camera person → one NM thread with path
  narrative; `exterior_track` episode written with event ids.
