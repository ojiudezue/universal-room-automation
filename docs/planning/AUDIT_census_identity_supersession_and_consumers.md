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
