# AUDIT — Census / Identity Supersession + Producer/Consumer Map + Should-Be-Consuming Gaps

> ⚠️ **CORRECTION 2026-08-18 (operator) — the "~7% egress face coverage" figure used throughout
> this doc is WRONG as a ceiling and its downstream recommendation is RETRACTED.** The 7% came from
> `PROBE_protect_face_egress.md`, which measured the WRONG camera (the front door
> `madrone_g6_entry`). Most family entries are via the **garage**, and Protect names people in the
> **family room** — i.e. on the *real* entry path. Frigate is on **all** cameras (front overhead +
> doorbell + foyer; garage doorbell + inside-garage cam), and Protect has face recognition on the
> doorbell + family room reachable via the **live Alarm Manager webhook**
> (`EXTERIOR-GUEST-FACE-FASTFOLLOW-1` D2). So the identity path is **viable**; coverage must be
> **re-measured against garage entries + family-room arrival**, not the front door. The
> "recommend a face-independent approach-track signal" conclusion below is **RETRACTED** — the
> operator already chose **identity-first**, and the face-independent arm is a *deferred,
> gated-on-value fallback* (`EXTERIOR-GUEST-EGRESS-1`, revisit only if identity proves insufficient).
> Treat every "~7%" / "capped by coverage" / "face-independent" line below as superseded by this note.

**Type:** READ-ONLY audit (no code changed by this doc).
**Date:** 2026-08-18
**Scope:** the census / guest / presence-identity cycle group — v5.79.0 (guest correctness),
v5.80.0 (interior census accuracy + `_2`-suffix face fix), v5.81.0 (egress face-identity),
v5.82.0 (device switches).
**Ground truth:** group README `docs/readmes/README_GROUP_census_guest_presence_identity.md`
(entity inventory live-verified 2026-08-18) + source read this pass. HA was **not** re-queried
live this pass; live values below are cited from the group README's 2026-08-18 verification or
marked "code-only". Cycle live-validation L2/L3 is still organic-pending (residents return Wed PM).

> **README-vs-reality note:** the group README §3 lists the three device switches as
> "**NOT YET SHIPPED**" (confirmed absent 2026-08-18 AM). They have since shipped as **v5.82.0** —
> `camera_census.py:2861` carries the comment *"post-CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 ship,
> 2026-08-18"* and the egress kill-switch reader now defaults **True**. The group README §3/§4
> should be reconciled (default flip OFF→ON, switches now live). Flagged, not fixed here.

---

## 1. SUPERSESSION — items these capabilities make redundant

Each candidate was grep-verified. **Nothing is deleted here** — this is a marked list for a later
deletion cycle, and every DELETE-CANDIDATE is explicitly gated on the cycle's organic L2/L3
validation landing (Wed PM). The reason for the gate: several of these items are the *fallbacks*
the new paths lean on; deleting them before the new path is proven live would remove the safety net.

| # | Superseded item | Where (file:line) | Superseded by | Safe to delete when | Disposition / risk |
|---|---|---|---|---|---|
| S1 | `CENSUS_DECAY_STEP_SECONDS` constant | `const.py:2777` (`= 300  # DEAD post-D1`) | v5.80.0 D1 deleted the linear `−1 per step` decay slope; the constant's only reader was that slope | Any time — already tombstoned, zero readers (grep: only the const def + two explanatory comments at `camera_census.py:72,3039,3138`) | **DELETE-CANDIDATE (safe now, pending L2/L3 for tidiness batching).** Risk: none — orphan constant. |
| S2 | Old broken `_is_known_person_in_room` lookup (wrong coordinator key `coordinators["person"]` + non-existent `_tracked_persons` attr) | Was in `presence.py`; **already fully replaced** in v5.79.0 (`presence.py:4988-5054`, canonical `person_coordinator` + `data[name]["location"]`) | v5.79.0 repair | Already done | **KEEP / N-A — already superseded and removed.** No vestigial `_tracked_persons` assignment survives (grep: only comment references at `const.py:394,409` + the repair docstring `presence.py:4999`). No dead identity remnant to delete. |
| S3 | `_guest_room_known_last_true` sticky cache + `_is_known_person_sticky` fallback (`presence.py:5055`) | `presence.py` | — | Only if `GUEST_KNOWN_STICKY_S` set to 0 permanently AND egress identity firms the guest gate | **KEEP (load-bearing).** This is the BLE-flap absorber that egress identity does NOT yet feed (see gap G2). Do not delete. |
| S4 | Naive additive census `guest_count = max(0, camera_total − ble_total)` attribute | `binary_sensor.py:1584` | `identified_count`/`unidentified_count` from the deduped `_cross_correlate_persons` union | Only after confirming no dashboard/automation reads this attribute | **KEEP (still exposed).** Attribute-only, not an entity; overlaps the deduped figure but is a distinct naive floor. Reconcile later, not delete now. Risk: two "guest count" numbers can diverge and confuse (documented in README §3 note). |
| S5 | `last_person_entry` / `last_person_exit` sensors (`sensor.py:4352,4400`) | `sensor.py` | `persons_entered_today` / `persons_exited_today` `entries[]` lists (which now also carry `person_id`) | Only if nothing displays "last entry/exit" | **KEEP (display, low cost).** Grep: **zero** code consumers outside `sensor.py` — pure display. Overlaps `entries[-1]` but cheap; not worth a delete-cycle. Not a real redundancy risk (both are display, no trust divergence). |
| S6 | `face_recognized_count` vs `identified_count` — "who's home" computed two ways | producer `presence.py:4408`; `identified_count` from census union `camera_census.py:1895` | — | **Do NOT delete** | **KEEP (both load-bearing, different semantics).** `face_recognized_count` = camera-face-only signal that gates the away-veto (`presence.py:1081-1094`, GAP-A D8); `identified_count` = face∪BLE∪egress union head-count. They answer different questions; the overlap is intentional. Deleting either breaks a distinct consumer. |
| S7 | String-built Frigate face / `last_camera` code paths | (resolver-superseded; see risk) | the `_2`-suffix resolver (`camera_resolver.py`) + `_normalize_name_set` / `_canonical_person_slug` | After confirming no remaining string-concatenated Frigate id survives on the egress/census path | **KEEP-PENDING-VERIFY.** This pass did not exhaustively enumerate every legacy string-built Frigate id branch; the egress resolver (`transit_validator._resolve_egress_face_identity`, `:1120`) reads live entity state, not a string-built id. Recommend a focused grep sweep (`f"...frigate..."`, `.replace("frigate_"` etc.) as a follow-up before any deletion. Risk of silent-fail on a bare (non-`_2`) Frigate leg is real (see memory "frigate 1 retired 2 suffix"). |

**Net:** only **S1** is an unambiguous safe-now delete (tombstoned constant). Everything else is
either already-superseded-and-removed (S2), or still load-bearing/fallback (S3, S6), or a
reconcile-later overlap that is NOT safe to delete pre-validation (S4, S5, S7). There is **no large
pool of dead identity code** left by the repairs — the v5.79.0 fix replaced in place rather than
leaving a vestigial branch.

---

## 2. PRODUCER / CONSUMER map of the NEW capabilities

### 2.1 `person_id` on `ura_person_egress_event` (bus) + `person_entry_exit_events.person_id` (DB row)

**PRODUCER** — `transit_validator.EgressDirectionTracker`:
- Computed by `_resolve_egress_face_identity(egress_camera_id, egress_timestamp)` (`:1120`), called
  once at `:1279` and the single result reused for BOTH the bus event (`:1288`) and the DB row
  (`:1337`) — so the two sites can never disagree (I3).
- Arithmetic (`:1181-1199`): reads the egress camera's face sensor state; requires
  `0 <= age <= FACE_MATCH_WINDOW_S` (60 s) where `age = now − state.last_changed`; older or negative →
  returns `None`. No identity without fresh evidence (I3).
- **Dependency health:**
  - Frigate face sensor on the egress-camera stem — **degraded.** Per the D0 probe recorded on
    `EGRESS-INTERIOR-COUNT-REINFORCE-1` (kanban `d0_impact_2026_08_17`): **face coverage at egress is
    ~7% even post-`_2`-suffix fix.** So `person_id` is `None` on the large majority of real crossings.
    This is the single most important health fact in this audit.
  - `FACE_MATCH_WINDOW_S=60` — module constant, healthy.
  - `_2`-suffix resolver — the resolver reads live entity state (not string-built), so it is not the
    fragile string-id path; but the underlying Frigate face *rate* is the limiter, not the resolver.

**CONSUMERS + call-sites (bus event `ura_person_egress_event`):**
- `sensor.py:4190` — `PersonsEnteredTodaySensor._handle_egress_event`: on `direction=="entry"`,
  `_count += 1`; if `person_id` truthy, `_egress_identities_stamped += 1` (`:4208`) and appends
  `{person_id or "unidentified", time, egress_camera}` to `entries[]`. **Display + observability**, not a trust decision.
- `sensor.py:4300` — `PersonsExitedTodaySensor` (sibling, exit count). **Display.**
- `sensor.py:4361` — `LastPersonEntrySensor`. **Display.**
- `sensor.py:4409` — `LastPersonExitSensor`. **Display.**
- `transit_validator.py:1316` — **the only trust-adjacent consumer:** if `person_id` and
  `direction in ("entry","exit")`, calls `census.register_egress_face` (entry) or
  `census.evict_egress_face` (exit). Feeds §2.2.

**CONSUMER (DB row):** `database.log_entry_exit_event(person_id=..., ...)` (`:1336`) →
`person_entry_exit_events` table (`database.py:797`, `person_id TEXT` nullable, indexed
`:806`). Read back by `PersonsEnteredTodaySensor` on boot via `get_entry_exit_events_since` (`:4182`)
for restore. **Historical/restore**, not a live trust path.

### 2.2 `egress_face_ids` fused into the census identity union

**PRODUCER** — `camera_census.CameraCensus`:
- Registered by `register_egress_face(name, ts)` (`:2878`): kill-switch gated
  (`_is_egress_identity_enabled`, `:2857`, default now **True** post-v5.82.0); canonicalizes name to
  URA person-slug (`_canonical_person_slug`, I5) so union dedups by identity; stores
  `_egress_face_ids[norm] = ts` (`:2911`); tz-coerces naive timestamps (A-LOW-2, `:2900`); bounded
  prune at >32 entries (`:2914`).
- Evicted on exit by `evict_egress_face` (`:2923`, B-CRIT-1 — a walk-in-then-out within TTL must not
  linger as a phantom).
- Freshness filter `_get_egress_face_ids_fresh(now)` (`:2940`): drops entries older than
  `EGRESS_FACE_UNION_TTL_S` (300 s) or with negative age; returns `set()` when kill-switch OFF (so
  both fuse sites are byte-identical to pre-cycle).
- **Dependency health:** entirely downstream of §2.1's `person_id`, so inherits the **~7% egress face
  coverage** ceiling — the set is empty most of the time. Live `egress_face_ids_active` was 0 on the
  empty house (expected).

**CONSUMERS (both census writers — must fuse at BOTH or it's a house-level no-op, plan-review C-CRIT-1):**
- `camera_census.py:1886-1892` — `_cross_correlate_persons` (raw/zone path): when enabled,
  `known_persons = normalize(face_ids) | normalize(ble_ids) | egress_face_ids`; else exact pre-cycle
  `set(face_ids) | set(ble_ids)` (D-MED-1 true byte-identical kill switch). `identified_count =
  len(known_persons)` (`:1895`). **Trust-decision** (drives census identity counts → guest gate).
- `camera_census.py:3663-3668` — `_apply_enhanced_house_census` (enhanced/house path, default ON):
  same union with `egress_face_ids`. **Trust-decision.**

### 2.3 `identified_count` post-fuse

**PRODUCER:** `len(known_persons)` in `_cross_correlate_persons` (`:1895`) after the egress union;
`unidentified_count = max(0, camera_total − identified_count)` (`:1899`); `total = max(camera_total,
identified_count)` (`:1900`). Depends on face_ids (Frigate face) + ble_ids (Bermuda IRK) + egress set.
**CONSUMERS:** surfaced on `sensor.universal_room_automation_persons_in_house` (`identified_count`
attr); the identified/unidentified head-count feeds `presence_house_state` `census_count` and the
guest composition. Trust-decision + display.

### 2.4 The two device switches (v5.82.0)

**PRODUCER/backing:** each `SwitchEntity` writes back a config-entry option (source of truth stays the
option; Option B pattern):
- `switch.ura_presence_face_matching` → `CONF_FACE_RECOGNITION_ENABLED` (scoped: transit_validator +
  presence zone-confirm only; NOT a global face kill switch).
- `switch.ura_name_people_at_doors` → `CONF_EGRESS_IDENTITY_ENABLED`. Read live (no reload) by
  `_is_egress_identity_enabled` (`camera_census.py:2857`) fresh at every crossing/tick.
- (`switch.ura_smart_people_counting` → `CONF_ENHANCED_CENSUS`, read by `_is_enhanced_census_enabled`
  `:2971`, requires reload.)

**CONSUMERS:** the `_is_*_enabled` readers above are the consumers; the switch is a control surface,
not a data value. **Control, not trust.**

### 2.5 Observability attrs `egress_face_ids_active` + `egress_identities_stamped`

**PRODUCER:** `PersonsEnteredTodaySensor.extra_state_attributes` (`sensor.py:4257-4262`).
`egress_face_ids_active = len(census._egress_face_ids)` read defensively at attribute time (`:4248-4256`);
`egress_identities_stamped` = cumulative session counter incremented at `:4209`.
**CONSUMERS:** **none in code** — pure observability for live validation (L2/L3). No dashboard card
reads them yet (see gap G5). Session-lifetime (resets on restart), by design.

---

## 3. SHOULD-BE-CONSUMING BUT ISN'T — the gap-finding

> **Framing caveat that discounts several gaps:** the egress `person_id` is present on only **~7% of
> crossings** (D0 probe). So any consumer wired to it gets an identity <1-in-10 crossings. This does
> NOT make the gaps invalid — a named alert 7% of the time still beats 0% — but it caps the marginal
> value and argues for *graceful* consumption ("named when known, anonymous otherwise"), never a
> design that assumes the identity is present.

| # | Downstream that should consume it | Current state (file:line) | The gap | Value of closing | Rough tier | Card? |
|---|---|---|---|---|---|---|
| **G1** | **Perimeter alerts** | `perimeter_alert.py:1316-1320` builds title `"Perimeter Alert — Person Detected"` + `PERIMETER_ENRICHMENT_BASE_TEMPLATE_PERSON` (`const.py:1521`: *"Person Detected on {entity_id} at {hhmmss}"*). Enriches with **track-path** narrative (`:1342`) and llmvision, but **never** with face/egress `person_id`. | An egress/face-identified crossing that fires a perimeter alert still says anonymous "Person Detected" even when the census/egress layer knows it's a resident. | High for signal-to-noise: "Oji at the side door" vs "Person Detected" is the difference between an ignorable and an actionable deep-night alert; naming a *known resident* also lets the alert self-suppress or de-escalate. | Tier 2 (touches notify message + a trust-ish suppress decision; regression-prone via NM) | **NEEDS ONE** (uncarded). |
| **G2** | **Guest false-positive reduction / guest-room gate** | Guest arm-gate's sole identity check is `_is_known_person_in_room` (`presence.py:4988`) reading `person_coordinator.data[name]["location"]` (BLE/room substrate). It does **not** consume egress identity at all. Parked cards `EGRESS-INTERIOR-COUNT-REINFORCE-1` + `GUEST-IDENTITY-PHONE-LEFT-BEHIND-1` cover adjacent scope. | A resident identified *at the door* on egress (walking in/out) does not firm up the guest gate or cancel a nascent guest false-positive; the gate relies entirely on BLE room-location, whose flap is exactly what `GUEST_KNOWN_STICKY_S` papers over. | High — this is the double-count/guest-FP class the whole arc set out to kill; a door-identified resident is *strong causal* evidence they're not a guest. **But** gated by the ~7% coverage and by `EGRESS-INTERIOR-COUNT-REINFORCE-1`'s own gate ("D1 identity accurate"), which the D0 probe says is NOT met on faces today. | Tier 2-DB (guest ↔ presence ↔ census ripple) | **PARTIAL card** — `EGRESS-INTERIOR-COUNT-REINFORCE-1` (planned, gated) is the closest; it is scoped to interior *count* reinforcement, not specifically the guest-gate exclusion. A guest-gate-specific consumer is **uncarded**. |
| **G3** | **Notifications / NM naming** | Egress event has `person_id`, but no NM/notification path emits "Oji arrived/left". The `entries[]` list carries `person_id` for display only; no arrival/departure notification consumes it. | Presence/arrival notifications stay anonymous or absent; the house knows who walked in but never says so. | Medium (nice-to-have; capped hard by ~7% coverage — most crossings would still be anonymous). | Tier 2 | **NEEDS ONE** (uncarded). |
| **G4** | **House census / presence trust firm-up beyond the fuse** | Egress identity fuses into the census *identity union* (§2.2) but the resulting `identified_count` is not separately used to *raise confidence* or reconcile against the interior substrate. | `EGRESS-INTERIOR-COUNT-REINFORCE-1` is exactly this and is **carded + pre-approved but gated** on D1 accuracy (unmet on faces per D0). | Medium-high, but explicitly gated. | Tier 2-DB | **CARDED** — `EGRESS-INTERIOR-COUNT-REINFORCE-1` (status: planned, gated). No new card needed; note the D0 gate likely keeps it parked until a face-independent signal is added. |
| **G5** | **Dashboard for the new observability attrs** | `egress_face_ids_active` / `egress_identities_stamped` exist on `persons_entered_today` (`sensor.py:4260`) but no dashboard card surfaces them; v5.80.0 D3 built exterior KEEP-BOTH dashboards but not these. | Live validation (L2/L3) must read the attrs by hand; no operator-facing view of whether the fuse is producing identities. | Low-medium (validation convenience; also the natural home for a "who entered today, named" tile). | Tier 1 (dashboard-only) | **NEEDS ONE** (uncarded) — small. |

### Top 3 highest-value UNCARDED gaps (flagged explicitly)

1. **G1 — Perimeter alerts should name a known person.** Highest signal-to-noise payoff; a deep-night
   "Person Detected" that could say "known resident Oji" (or stay "unidentified person" for a real
   stranger) is the exact known-vs-unknown discriminator the arc was built to produce
   (`EXTERIOR-GUEST-FACE-FASTFOLLOW-1` card line: *"says WHO … the actual guest/security
   discriminator"*). Wire the egress/census identity into `perimeter_alert`'s message builder,
   graceful-anonymous when unknown. **NEEDS A CARD.**
2. **G2 — Guest-gate consumption of door-identity.** A resident identified at the door should
   actively suppress a guest false-positive, not merely (eventually, maybe) reinforce a count. This is
   the closest thing to closing the original double-count/guest-FP wound at its source. Adjacent cards
   exist but none targets the guest *gate* exclusion specifically. **NEEDS A CARD** (Tier 2-DB), with
   the honest note that the ~7% face-coverage gate applies.
3. **G3 — "Oji arrived / left" notifications.** The `person_id` is already on the bus and on the DB
   row; nothing turns it into a presence notification. Lowest-risk of the three to build; value capped
   by coverage. **NEEDS A CARD.**

**Recommendation (corrected — see the banner at the top of this doc).** The "~7%" is NOT a
ceiling; it measured the front door, not the real garage/family-room entry path, and predates the
Protect-named-face webhook now being wired. So before carding G1/G2/G3 for build, run a fresh
one-shot **measure-before-build** probe of the *actual* egress identity rate — but measured
against the **garage entries + family-room arrival** path, and **including Protect named face**
(via the live `ura_kp_face_probe_received` webhook / `EXTERIOR-GUEST-FACE-FASTFOLLOW-1` D2), not
Frigate-egress-at-the-front-door alone. All three gaps consume identity **graceful-anonymous**
(name when known, anonymous otherwise), so none is invalidated by imperfect coverage. Do **not**
recommend the face-independent approach-track arm here: the operator already chose identity-first,
and that arm is a **deferred, gated-on-value fallback** (`EXTERIOR-GUEST-EGRESS-1`) — it revisits
only if the identity path, measured on the real entry path, proves insufficient.

---

## Appendix — key file:line index

- Egress resolve + emit: `transit_validator.py:1120` (`_resolve_egress_face_identity`), `:1274-1344` (emit/register/evict/DB).
- Census union fuse sites: `camera_census.py:1886-1895` (raw), `:3663-3668` (enhanced).
- Egress-face store: `camera_census.py:2878` (register), `:2923` (evict), `:2940` (fresh), `:1076` (`_egress_face_ids` init).
- Kill-switch reader: `camera_census.py:2857` (`_is_egress_identity_enabled`, default True post-v5.82.0).
- Observability attrs: `sensor.py:4166-4262` (`PersonsEnteredTodaySensor`).
- DB row: `database.py:797-806` (`person_entry_exit_events`, nullable `person_id`, indexed).
- Guest gate identity check: `presence.py:4988-5054` (`_is_known_person_in_room`, repaired v5.79.0) + `:5055` (sticky fallback).
- `face_recognized_count` (distinct from `identified_count`): `presence.py:4408`, gates away-veto `:1081-1094`.
- Perimeter alert message: `perimeter_alert.py:1316-1345`; template `const.py:1521`.
- Tombstoned constant: `const.py:2777` (`CENSUS_DECAY_STEP_SECONDS`).
- D0 coverage evidence: `docs/planning/kanban.data.yaml` card `EGRESS-INTERIOR-COUNT-REINFORCE-1` (`d0_impact_2026_08_17`, ~7% egress face coverage).

---

## ADDENDUM — domain-wide pre-existing supersession sweep (2026-08-18)

**Scope correction.** §1 above was wrongly scoped to the cycle group's OWN files (v5.79.0–v5.82.0
diff). Supersession is about the code that came BEFORE — pre-existing code the census/guest/
presence-identity arc made redundant. This addendum re-runs the sweep REPO-WIDE across all of
`custom_components/universal_room_automation/` (every `domain_coordinators/*.py`, `sensor.py`,
`binary_sensor.py`, `aggregation.py`, `camera_census.py`, `transit_validator.py`, `camera_resolver.py`),
not the cycle's diff.

**Method: three-bucket triage** (per CLAUDE.md "Post-Ship Supersession"): DELETE (dead AND no use
case AND footgun — mark only, never delete), KEEP+WIRE (useful capability missing a consumer /
needs a resolver migration → gap backlog), KEEP+DOCUMENT (dead-today but plausible future tunable).
Default KEEP when uncertain.

### Grep patterns run + hit counts (repo-wide, test files excluded)

| Pattern (git grep) | Purpose | Hits (non-test) |
|---|---|---|
| `f".*[Ff]rigate` | string-built Frigate ids | 6 — all `perimeter_alert`/`security` **URL/description** builds (snapshot `/api/frigate/...` paths), **zero** entity-id face lookups |
| `f"sensor\.{...}_last_recognized_face` | string-built face-sensor ids | **3** — `camera_census.py:2523/2524` (the resolver itself: canonical + `_2`) + **`presence.py:4557`** (the one bare build, no `_2` fallback) |
| `f".*_last_camera"` | string-built last_camera ids | **0** — the last_camera path (`_resolve_last_camera_entity_id`, `camera_census.py:2615`) is registry-scan, not string-built |
| `f"...{...}_person_count"` / `_person_occupancy"` | string-built count/occupancy ids | 4 (`camera_census.py:417,656,658,835`) — all inside `CameraCensus`; 417/835 already carry `_N`-variant fallback (CENSUS-SUFFIX-FIX); 656/658 are discovery-time sibling candidates checked against the registry |
| `guest_count` / `_get_guest_count` / `_get_wifi_guest_count` | second-way guest derivations | 12 — the load-bearing hit is **`aggregation.py:5983`** (`camera_total − ble_total`) + `binary_sensor.py:1584` (S4) |
| `occupant_count` / `persons_home` / `residents_home` | second-way "who's home" | `aggregation.py:1688` (`Identified People Count`, BLE-tracker) |
| `identified_count` / `face_recognized_count` | census identity producers/consumers | as mapped in §2 (no new second-way producer found) |
| `decay` / `DECAY` in `camera_census.py` | decay logic post-separation | linear slope already deleted (S1); `_apply_hold_decay` is the retained hold path |
| `person_id or` / `or "unidentified"` / `person_id is None` | anonymous-only egress handling | `sensor.py:4216,4315` already `person_id or "unidentified"` — **graceful, no hard-anonymous branch survives** |

### Per-hit three-bucket table (findings NEW to this repo-wide pass)

| Item | file:line | Bucket | Superseded by | Reason |
|---|---|---|---|---|
| A1 · `_get_face_for_camera` string-built face id (bare `_last_recognized_face`, **no `_2` fallback**) | `presence.py:4557` | **KEEP+WIRE** | `camera_census._resolve_face_entity_id` (`:2509`, canonical+`_2`) | Live camera-face-arrival accelerator; on an `_2`-suffixed Frigate leg it silently returns `None` (memory "frigate 1 retired 2 suffix"). **Already carded — `CENSUS-FACE-RESOLVER-MIGRATE-1`.** This sweep PROVES it is the **only** non-resolver `_last_recognized_face` string build repo-wide. |
| A2 · `ZoneGuestCountSensor._get_guest_count` naive subtractive `max(0, camera_total − ble_total)` | `aggregation.py:5983` (entity `sensor.<>_zone_<z>_guest_count`) | **KEEP+WIRE** | census deduped `unidentified_count` union (`camera_census.py:1899`) | Pre-existing per-zone guest **entity** computing guest count a second way — camera total minus BLE-active count, the exact additive/subtractive divergence class that caused the census GUEST double-count (memory "cross-investigation synthesis"). Should read census `unidentified_count`, not recompute. **UNCARDED → new bucket-2 card.** Not delete: it backs a live entity. |
| A3 · S4 sibling: naive `guest_count` attr, same `camera_total − ble_total` formula | `binary_sensor.py:1584` | **KEEP+WIRE** | census `unidentified_count` | Same formula as A2, attribute-only (already S4 in §1). Fold into the A2 migration card so both naive derivations retire together. |
| A4 · `Identified People Count` / `occupant_count` (BLE person-tracker head-count) | `aggregation.py:1688` | **KEEP+DOCUMENT** | *not superseded* | Distinct semantics: person-tracker "residents home" (BLE), **not** the face∪BLE∪egress per-zone camera census `identified_count`. Overlapping name, different question — same reasoning as S6. Document the overlap; do not wire or delete. |
| A5 · `camera_census.py:417,656,658,835` `_person_count`/`_person_occupancy` string candidates | `camera_census.py` | **KEEP (no action)** | — | Not superseded: 417/835 already `_N`-suffix-tolerant (CENSUS-SUFFIX-FIX); 656/658 are discovery-time candidates validated against the registry. Proves the resolver migration is unneeded here. |
| A6 · Egress/entry anonymous handling | `sensor.py:4216,4315` | **KEEP (no action)** | `person_id` fuse (§2.1) | Consumers already emit `person_id or "unidentified"` — graceful-anonymous. **No hard-anonymous branch survives** to supersede (bucket 5 empty). |
| A7 · Perimeter/security `f"...frigate..."` builds | `perimeter_alert.py:1696,3317,3320,3327,3337`; `security.py:411` | **KEEP (no action)** | — | Snapshot-URL / log-description builds, **not** entity-id face lookups — outside the resolver's remit. |

### Bucket-1 (DELETE) items

**None.** No dead-AND-footgun code was found that the arc left behind. (Consistent with §1's net finding: the v5.79.0 repair replaced in place; it did not leave a vestigial branch.) S1 (`CENSUS_DECAY_STEP_SECONDS`) remains the only tombstoned constant and is a KEEP+DOCUMENT per the later reframe, not a delete.

### Bucket-2 (WIRE) items needing a card — FLAGGED

1. **A1 — face-resolver migration `presence.py:4557`.** Already carded: **`CENSUS-FACE-RESOLVER-MIGRATE-1`**. This sweep confirms that card's scope (only `:4557`) is complete — no other `_last_recognized_face` string build exists repo-wide. No new card.
2. **A2 + A3 — retire the naive `camera_total − ble_total` guest derivations** (`aggregation.py:5983` entity + `binary_sensor.py:1584` attr) in favor of the census deduped `unidentified_count`. **UNCARDED → NEEDS A CARD.** Tier 2-DB (census ↔ guest ↔ presence ripple; this is the additive/subtractive divergence class behind the historical GUEST double-count, so treat as regression-prone). Suggested id: `GUEST-COUNT-DEDUP-MIGRATE-1`.

### Net

The repo-wide sweep adds **one** genuinely-new supersession finding beyond §1 and beyond the known
`presence.py:4557`: the pre-existing naive subtractive guest-count derivations (A2/A3) that the
census deduped `unidentified_count` union now supersedes and which should be wired to it. Everything
else is either already-carded (A1), distinct-semantics KEEP (A4, S6), already-suffix-tolerant (A5),
already-graceful (A6), or out-of-remit URL builders (A7). **No deletions.** The claim that
"`presence.py:4557` is the only face-resolver migration target" is now PROVEN (grep table above),
not asserted.

---

## ADDENDUM 2 — tier + coordinator semantic sweep (2026-08-18)

**Gap this addendum closes.** ADDENDUM 1 proved the *string-lookup* (resolver-migration) question
repo-wide, and §1 mapped the cycle group's own diff. Neither exhaustively walked the **room tier,
zone tier, house_state tier, and every `domain_coordinator`** for a SECOND way of *computing* what
the census/guest/presence-identity arc now provides canonically. This pass does that: it reads each
tier/coordinator surface and asks "does this derive a headcount / guest-count / known-person /
occupancy-decay a second way that the census canonical (`identified_count` / `unidentified_count` /
`persons_in_house` union, the repaired `_is_known_person_in_room` oracle, the `_2` resolver, egress
`person_id`, or the decay-separation) now supersedes?"

**Canonical capabilities a duplicate would be superseded BY (restated):** census `identified_count`
/ `unidentified_count` / `persons_in_house` (deduped `_cross_correlate_persons` +
`_apply_enhanced_house_census` union); repaired `_is_known_person_in_room` oracle + guest-room-lead;
`_2`-suffix face resolver (`camera_resolver.py`); egress `person_id`; decay-separation instant-drop.

### Method

Read each surface end-to-end or grepped its identity/count/guest/decay defs, then three-bucket
triaged every candidate: **DELETE** (dead AND no use-case AND footgun — mark only), **KEEP+WIRE**
(useful, missing/mis-fed consumer → card), **KEEP+DOCUMENT** (plausible-future or distinct-semantics
overlap). Default KEEP when uncertain. A "nothing new" result is only legitimate with the per-file
read shown below.

### Per-surface coverage checklist (each read/grepped this pass)

**House tier**
- `domain_coordinators/house_state.py` — **checked, found nothing.** File is the `HouseState` enum +
  transition-timing map + guest-transition suppression comments only. It holds NO census/guest/
  identity/headcount derivation; `census_count==0` is merely *referenced* in the AWAY-entry comment
  (`:96`). The `census_count` value itself is produced by `presence.py:1788` (canonical consumer of
  `census_data["interior_count"]`, set at `presence.py:4391`) — one producer, no second way.
- House-level census sensors `sensor.py:3456-3744` (`URAPersonsInHouseSensor`,
  `URAIdentifiedPersonsInHouseSensor`, `URAUnidentifiedPersonsInHouseSensor`, …) — **checked, canonical
  consumers** of `result.house.identified_count` / `unidentified_count`. Not a second way.
- House-level `Identified People Count` (`aggregation.py:1688`, entity `{DOMAIN}_occupant_count`) —
  **checked = A4 (KEEP+DOCUMENT).** BLE person-tracker head-count (`get_tracked_person_count()`),
  distinct modality from the face∪BLE∪egress camera census. Overlapping name, different question
  (same reasoning as S6/A4). Its `persons_home` attr (`:1768`) is a *sensor attribute*, NOT the
  `context["census"]` security reads (see the security finding below).

**Zone tier**
- `ZoneAnyoneBinarySensor` (`aggregation.py:3891`) — **checked, found nothing.** Boolean occupancy
  rollup + Layer-2 sleep veto; no count/guest/identity number. Not superseded.
- `ZoneGuestCountSensor` (`aggregation.py:5926`, `_get_guest_count` `:5983`) — **checked = A2
  (KEEP+WIRE), already carded `GUEST-COUNT-DEDUP-MIGRATE-1`.** Naive `camera_total − ble_total`, the
  additive/subtractive divergence class behind the historical GUEST double-count. Should read census
  `unidentified_count`. No new card (folded with S4/A3).
- `ZoneCurrentOccupantsSensor` (`:4784`) / `ZoneOccupantCountSensor` (`:4923`) /
  `ZoneIdentifiedPersonsSensor` (`:5836`) — **checked = A4-class (KEEP+DOCUMENT).** All are
  `person_coordinator` BLE room-location rollups (`get_persons_in_zone`), NOT the camera census
  identity union. Distinct modality; document overlap, do not wire or delete.
- `check_zone_occupancy_confidence` (`presence.py:2014`) — **checked, found nothing.** Counts
  *independent occupancy SOURCES* (motion recency etc.) for a confidence tuple; orthogonal to
  headcount/identity. Not superseded.

**Room tier**
- `CurrentOccupantsSensor` (`sensor.py:2696`) / `OccupantCountSensor` (`sensor.py:2793`) — **checked =
  A4-class (KEEP+DOCUMENT).** Per-room `person_coordinator.get_persons_in_room` BLE rollup. Distinct
  from census. Not superseded.
- `_is_known_person_in_room` (`presence.py:4988`, repaired v5.79.0) + sticky (`:5054`) — **checked =
  the canonical oracle itself** (S2/S3), not a duplicate. Its non-consumption of egress identity is
  gap **G2** (already documented §3).
- `_room_occupied` (`presence.py:604`) + `occupancy_substrate.py` — **checked, found nothing.** Raw
  per-room sensor fusion + room-timeout hold; a **different modality** (physical sensor timeout) from
  the camera-census decay-separation. `occupancy_substrate.py` has zero census/guest/identity/decay
  hits. Not superseded — the census decay separation did not create a second room-occupancy decay.

**Every `domain_coordinator/`**
- `presence.py` — census_count consumer (canonical), guest-gate oracle (canonical). No second-way
  producer. Covered above.
- `security.py` — **NEW FINDING (see T1 below).** `SanctionChecker` unknown-person path.
- `hvac.py` — **checked, found nothing.** All `guest`/`census` hits are `house_state in (...,"guest")`
  consumers or the v4.6.3 `census_count` *anomaly-suppression* note (`:3544-3572`); no headcount /
  guest / identity derivation of its own.
- `safety.py`, `energy*.py`, `base.py`, `signals.py`, `coordinator_diagnostics.py`,
  `occupancy_substrate.py`, `fan_policy_oracle.py`, `notification_manager.py`, `music_following.py` —
  **checked, found nothing.** Zero guest/census/identified/headcount derivations (grep hit-count 0 each,
  except `base.py`/`signals.py` whose hits are the `Intent.source` docstring example and the
  `SIGNAL_CENSUS_UPDATED` name constant — plumbing, not a second derivation).

### Grep patterns run this pass (tier/coordinator scope, non-test)

| Pattern | Purpose | Result |
|---|---|---|
| `def .*(census\|guest\|occup\|identif\|count\|known_person\|resident)` in `presence.py` | second-way producers in presence | only canonical `census_count`, guest-gate oracle, zone-confidence — no duplicate |
| `guest\|census\|identified\|resident\|occupant_count\|known_person` per coordinator | per-coordinator headcount/guest/identity | hits only in `security.py` (T1), `hvac.py` (consumer), `aggregation.py` (A2/A4); 0 in safety/energy/substrate/fan/notify/music |
| `persons_home\|unknown_present` producers repo-wide | who feeds security's census context | **`persons_home`: 1 (a sensor attr, `aggregation.py:1768`); `unknown_present`: 0 producers** |
| `source=["']census_update["']` emitters | who fires security's census intent | **0 emitters repo-wide** |
| `SIGNAL_CENSUS_UPDATED` subscribers | census fan-out | `camera_census`, `sensor.py`, `presence.py` — **security is NOT a subscriber** |
| `decay\|hold\|linger\|grace` in `occupancy_substrate.py` | second room-decay vs census decay-separation | 0 — no duplicate decay |

### Three-bucket table (findings NEW to this tier/coordinator pass)

| Item | file:line | Bucket | Superseded / should-consume | Reason |
|---|---|---|---|---|
| **T1** · `security.SanctionChecker` unknown-person path (`has_unknown_persons` `:312`, `check_entry` `:239`, `_handle_census_intent` `:969`) — reads `context["census"]["unknown_present"]` / `["persons_home"]` | `security.py:239,251-315,969` | **KEEP+WIRE (footgun-cautioned)** | census `unidentified_count > 0` / guest composition (`camera_census.py:1899`) | **Inert today, two ways over.** (1) `unknown_present` has **zero producers** repo-wide — `has_unknown_persons` always returns `False`. (2) No `source="census_update"` intent is emitted anywhere, so `_handle_census_intent` (unknown-person → lock-all-doors) is **never invoked**; security is not even a `SIGNAL_CENSUS_UPDATED` subscriber. This is a designed security consumer that SHOULD consume the now-reliable census `unidentified_count`, but the wiring was never completed. **UNCARDED → NEEDS A CARD** — but see footgun note. |
| **T2** · House/zone/room BLE occupant rollups (`aggregation.py:1688,4784,4923,5836`; `sensor.py:2696,2793`) | as listed | **KEEP+DOCUMENT** | *not superseded* | `person_coordinator` BLE "who's home / in this room/zone" — distinct modality from the face∪BLE∪egress camera census. Overlapping names, different question (S6/A4 reasoning). No wire, no delete. |
| **T3** · Room occupancy hold/timeout (`presence.py:604` `_room_occupied`, `occupancy_substrate.py`) | as listed | **KEEP (no action)** | *not superseded* | Physical per-room sensor-timeout hold ≠ the camera-census decay-separation. The decay work did not spawn a duplicate room-decay. |

### Bucket-1 (DELETE) items

**None.** T1 is inert but is a *designed capability with a legitimate consumer intent*, not a
dead-AND-footgun orphan — default KEEP+WIRE, not delete. (Deleting it would remove the only
census→security bridge point rather than fix it.) Consistent with §1 and ADDENDUM 1: the arc left
**no dead code pool** behind.

### Bucket-2 (WIRE) — new card needed

1. **T1 — wire the census unidentified signal into security's unknown-person path.** Suggested id:
   **`SECURITY-CENSUS-UNKNOWN-WIRE-1`**. Subscribe `security` to `SIGNAL_CENSUS_UPDATED` (or have the
   manager emit a real `census_update` intent with `context["census"]` populated from
   `result.house.unidentified_count` / identity composition) so `has_unknown_persons` reflects the
   canonical census instead of an unpopulated key.
   **⚠️ FOOTGUN / TIER CAUTION (mandatory on the card):** `_handle_census_intent` **locks all doors**
   on `unknown_present`. Given the arc's *own* guest-false-positive history (memory "cross-investigation
   synthesis": census double-counted residents into GUEST when face-recognition was dead; ~7% egress
   face coverage per D0), wiring raw `unidentified_count>0 → lock-all-doors` would auto-lock on a
   guest-FP or a coverage gap. This is **Tier 2-DB minimum** (census ↔ security ↔ guest ripple,
   safety-actuating) and **must** gate on the same confidence/guest-composition the guest gate uses,
   with a kill switch — NOT a bare `unidentified_count>0`. Recommend carding as *investigate-first*
   (confirm the capability is even desired) before build, given the actuation risk.

### Net

The tier + coordinator semantic sweep adds **one genuinely-new finding (T1)** beyond §1 and
ADDENDUM 1: security's `SanctionChecker` unknown-person path is a **designed-but-inert consumer** of
the census unidentified/identity signal (unfed key + un-emitted intent + not a `SIGNAL_CENSUS_UPDATED`
subscriber) that the now-reliable census `unidentified_count` should feed — **KEEP+WIRE, footgun-
cautioned, needs a card (`SECURITY-CENSUS-UNKNOWN-WIRE-1`, Tier 2-DB, investigate-first).** Everything
else across house_state, the zone tier, the room tier, and the other nine coordinators is either the
census canonical itself, a distinct-modality BLE rollup (T2, KEEP+DOCUMENT), a different-modality
room-occupancy hold (T3, KEEP), an already-carded naive guest derivation (A2/`GUEST-COUNT-DEDUP-
MIGRATE-1`), or plumbing. **No second-way census/guest/identity/decay producer, and no deletions.**
