# PLANNING: person-awareness layer leak cleanup (re-cut under the 11-17 no-rebuild rule)

Date 2026-11-17. Author ura-planner. Card LAYER-LEAK-CLEANUP-PLAN-1 (parent LAYER-LEAK-CLEANUP-1). Plan only: no code,
no kanban edit. Code read: `develop` @ 7462e2ec2 (live line v5.108.35). Live data: HA recorder (window 2026-11-10 10:12 UTC
to now, about 7 days) and the URA DB, read-only over SSH on 2026-11-17.

## Operator ruling (2026-11-17, verbatim)

"A. We should not rebuild tier 3 that are hardened and work and we should be skeptical of others. With clear pro/con.
Only proven code should supersede correct code. Let's make sure the shared layer benefit is still solid".

Option A (the smaller cut) is chosen. Every item below has to pass five tests: (1) is the code it would replace correct
today, with evidence; (2) is there a MEASURED live defect or risk (count, window, source), or only a structural one;
(3) is the replacement PROVEN (live since which version, how many consumers, any incident); (4) one-line pro and con;
(5) verdict: **BUILD** (measured defect + proven replacement), **BUILD-MINIMAL** (fix the defect in place, without
moving hardened code onto the layer) or **PARK** (with a revival trigger).

## Headline

- **Measured:** no item has a live defect on this house today. The audit's headline risk (S1, "78 iPad blips/week could
  open suppression windows while armed") is gone: the recorder shows 6 stale-source arrival edges in 7 days, all from
  the iPad tracker on 11-15 before the operator removed it from `person.oji_udezue`, none since, and the Security
  Coordinator was never armed in the window. No suppression window opened from a stale edge.
- **One item still builds, minimally:** the five fail-open identity vetoes look up `person.<slug>` by string and
  silently skip the veto when that entity does not exist. That cannot happen on this house, but it will on an install
  whose person entity id is not the slug of its name. Portability fixes are not parked as "second install only"
  (`feedback_portability_imperative`), so this one builds in place.
- **Finding that changes L4:** the old L4 routed those sites through `person_ids.tracked_person_entity_id`. That
  function is itself a string build (`person.` + lowercased name, `person_ids.py:25-37`), so the migration would fix
  nothing on the install it was meant for. The minimal fix resolves the person through HA's own person entities on the
  miss path only.
- **Effort:** about **1 builder-day, 1 build (Tier 2)**, down from ~10 days / 4 builds (old recommended cut) and ~17
  days / 6 builds (full close). Everything else is parked with a revival trigger. Guard total: 256 today, 257 after the
  build (the one H1 rule case makes a hidden leak countable; no other row changes).
- **Layer benefit:** solid, and mostly already delivered (§2). The remaining cleanup moves correct old consumers; its
  margin is a smaller allowlist, not behaviour.

## 1. Institutional context verified

Read completely this session: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. the §10 ledger #1-#43;
nothing below re-asserts a ledger claim), `docs/architecture/SENSOR_FLEET_CLASSES.md`, contract
`docs/planning/CONTRACT_person_awareness_layer.md` §0a. The previous version of this plan (commits 990487fb7 /
8be002d9a) supplied the site lists; its HVAC touch (`hvac.py:1558-1560, 2748-2749`) is now parked, so no HVAC code is in
scope and the HVAC state-of-play needs no write-back.

Identity model: this plan produces no fact. The one build touches F3 / F2 identity vetoes (consumer class: identity
veto, fail-open by design) and only their miss path.

Code checked against the plan's claims (2026-11-17):

| Claim | Evidence |
|---|---|
| Guard allowlist | `LAYER_ALLOWLIST_TOTAL = 256`, 228 rows (`quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py:28`, `test_person_awareness_layer_guard.py:64`) |
| S1 listener behaviour | `security.py:2255-2290` `_handle_person_state_change`: returns at once while DISARMED; a `not_home -> home` edge adds a 10-min expected arrival, `not_home -> zone` 30 min. No source-age test |
| G1 consumers | `crossing_vision.py:494` (since v5.108.25), `music_following.py:784` (step 8, since v5.108.33); delegate `presence.py:6131` |
| `persons_in_room` consumers | one: `person_sighting.py:1517` (interior vision, since v5.108.28), read through `getattr` |
| `house_census_view` consumers | `sensor.py:5422, 5437`, `aggregation.py:6679, 6708`, `binary_sensor.py:1953, 2001`, delegate `presence.py:6105` (since v5.108.25) |
| G3 one amend path | `transit_validator.amend_crossing` (`:1036`) -> `attach_crossing_attribute` (`:1232`); writers on develop: `camera_census.py:5348`; on `feature/crossing-p3-d2-d3` (00cd94cef, not merged) also `crossing_vision.py:1365-1398` |
| Inline person-id builds left | 9 `f"person.{...}"` outside `person_ids.py`: `person_coordinator.py:1824`, `camera_census.py:4841, 4898, 5979, 6711`, `transit_validator.py:2289`, `perimeter_alert.py:1118, 6224`, `person_sighting.py:729` |
| Fail-open shape | `camera_census.py:4841-4846`, `:4898`, `:5979`, `:6711` and `transit_validator.py:2289-2295`: `hass.states.get(f"person.{slug}")` is None -> no veto |
| H1 boot seed | `presence.py:3291-3298` reads `sensor.{DOMAIN}_identified_persons_in_house`; not on the allowlist (the guard's R3 taint does not see the f-string) |

REUSE / NEW for the one build:

| Piece | Verdict |
|---|---|
| Slug and display rule | REUSED `person_ids.slug_of` (`person_ids.py:40`) |
| Person entity on a miss | NEW `person_entity_for_slug(hass, slug)` next to `person_state_for_trust` in `person_coordinator.py`: exact `person.<slug>` first (today's lookup), else the one `person.*` state whose `slug_of(entity_id)` or `slug_of(friendly_name)` equals the slug (HA sets `friendly_name` from the person's configured name); zero or two matches = None (today's answer). No equivalent after grep of `person_ids.py`, `person_coordinator.py` (`_find_person_entity` `:1812` is the same string build twice) |
| Miss counter | NEW counter in `get_layer_diagnostics()` (`person_entity_fallback_hits`, `_misses`); no entity |
| Knobs | none (no behavioural number) |

Config-first: no setting changes any of these paths.

## 2. Is the layer's benefit still solid?

Contract §0a made five claims on 2026-11-13. Checked against today's code and data:

| §0a claim | Then | Today | Holds? |
|---|---|---|---|
| Consumers reached into census internals | ~20 private methods, 40+ calls | Producers use public `PersonCensus` delegates since ship 2 (v5.108.25), pinned by `test_no_private_census_reads_outside_module`. What remains is census display (#7, 41 rows, ruled owner-display) and census's own BLE reads (#27, 2) | Yes, largely delivered |
| Person ids normalised in many places | 14+ inline copies, 5 reverse | 9 inline builds left (list in §1); the rule lives in one module | Partly. The one rule is still a string build, so the class of bug "entity id differs from the slug" is centralised, not removed. §3 L4 fixes the part that fails open |
| Natural host already existed | Presence owns F1/F4/F5 getters | Still true; no new coordinator was needed for ships 1-3b, interior vision or step 8 | Yes |
| It sets the ceiling | F5 14 d: 152 geofence / 68 BLE / 0 face; F3 name 30% entry / 49% exit | F3, last 7 days (`egress_identity_outcome`, 261 rows): entry 24 of 69 named (35%), exit 17 of 80 (21%), 112 direction-ambiguous, 10 vetoed. F5 source mix is not cheaply measurable: the counters are RAM in `get_layer_diagnostics()` and HA restarted 27 times in the window; the URA DB keeps residency edges (23 arrivals), not F5 sends by source | The ceiling is still low (exit naming fell). The layer is where it gets raised, but it has not raised it yet |
| It lets vision lead later | Vision must feed one point | Crossing vision P3-D3 (branch, 00cd94cef) records vision direction through the one G3 path, `amend_crossing`, from one call site, so its gate could be enumerated at that one site in review. Interior vision ships 1-2 read F4 through `persons_in_room` and publish through `_emit_unnamed` | Yes, and in use this week |

**What the layer has already delivered:** one read surface that every new consumer since 11-14 used instead of reaching
into internals: G1 edges (crossing vision, music following), the class-taking census view (5 display readers plus the
pinned trust golden), the BLE room read (interior vision), the F3 ring and the one G3 amend path (census exit backfill,
P3-D3), typed F5 dispatch, and the guard that stops new leaks (the allowlist ratchet). That is where the value is: new
features land on the layer and stay off the internals.

**What the remaining cleanup adds at the margin:** it moves old consumers that are correct today onto that surface.
The gain is a smaller allowlist (256 -> about 160 on the old cut) and lower change risk if presence internals are
refactored. It adds no behaviour any person in the house would notice, and the measurements in §3 found no defect it
would cure. The only margin worth paying now is portability of the fail-open vetoes.

**Verdict:** the benefit is solid. It comes from building new work on the layer, which is already happening; it does not
depend on migrating the old consumers.

## 3. Per-item test

Measurements (read-only, 2026-11-17; recorder window 11-10 10:12 UTC to now):
- **M1 S1 stale edges.** 40 `person.*` arrival edges (`not_home -> home` or `-> zone`). 6 stale-source (source tracker
  last changed more than 10 s before the edge; the rule of `arrival_edges.stale_source_arrival`), all `person.oji_udezue`
  with source `device_tracker.okosisipadmini6_2`, all on 11-15 (05:30 to 23:29 UTC), source age 24,577 to 89,345 s. 0
  stale edges after the iPad was removed (11-15). The residency log (`person_arrival` rows, from 11-14) agrees: 6
  `source_stale` on 11-15, 0 on 11-14 or 11-16. `sensor.ura_security_coordinator_security_armed_state` read
  `disarmed` 36 times, `unknown` 18, `unavailable` 1, never armed, and was `disarmed` at all 6 stale edges. **Suppression
  windows opened from a stale edge: 0.**
- **M2 H1 boot AWAY.** 27 HA restarts in the window. The house state went AWAY within 15 min of boot 3 times (11-11
  00:03, 11-12 18:59, 11-12 21:54 UTC). In all three every resident's `person.*` read `not_home` and AWAY lasted 37 to
  49 min: real departures. **Boot AWAY flashes from the seed: 0 of 27.**
- **M3 phone-left-behind.** The four `*_phone_left_behind` sensors were `on` 0.09 h, 0.06 h, 0.01 h and 0.00 h in 7 days
  (19 short episodes). The G6 behaviour change can only act inside those 10 minutes.
- **M4 identity vetoes on this house.** 10 vetoed egress outcomes in 7 days (7 exit, 3 entry): the string lookup hits
  here because every person entity id equals its slug.

| Item | (1) Replaced code correct today? | (2) Measured defect or risk | (3) Replacement proven? | (4) Pro / con | (5) Verdict |
|---|---|---|---|---|---|
| **L2-S1** security geofence listener `security.py:2198-2290` (#1, 3 rows) | Yes for every non-stale edge; acts only while armed | **Structural only.** M1: 6 stale edges in 7 days, all from the removed iPad, 0 while armed, 0 windows opened; 0 since 11-15 | G1 `subscribe_person_edges`: live since v5.108.25, 2 consumers, no incident. The stale predicate `arrival_edges.stale_source_arrival` is proven in the lock hold since v5.108.13 (0 of 40 real arrivals held, 78 of 78 blips caught) | Pro: closes a latent unlock-adjacent gap with a proven predicate. Con: changes Tier-3 access code for a path that fired 0 times while armed and whose only source was removed | **PARK.** Revival build (recorded): BUILD-MINIMAL inside the existing listener, before `add_expected_arrival`, skip a `not_home -> home` edge for which `stale_source_arrival` is True and count it (`security_stale_arrival_skipped`); no G1 move. Real arrivals have source age at most 0.0003 s, so the skip fails toward an alarm, the safe side. ~0.5 day, Tier 2 (one predicate, one site). Triggers: the SC reads any armed state in a week, OR a `person_arrival` row with `source_stale` true appears (query `memory_episodes`), OR a second GPS device is added to any `person.*` |
| **L2-S7** perimeter third ledger `perimeter_alert.py:546, 1120` (#3, 3 rows) | Yes (same rule as `arrival_edges`, 153 tests same on base and branch) | **None.** D10.5 runs only for dual-role cameras and `dual_role_cameras` is `[]` here, so the path is dormant | G1 as above | Pro: one fewer ledger. Con: pure migration of correct, dormant code | **PARK.** Trigger: a dual-role camera is configured, or the perimeter arrival rule changes |
| **L1 behaviour commit** #20 room occupancy PLB filter, #21 PLB sensor privates, #22 fan veto / recheck, #27 census BLE, C9 twin `presence.py:4841` (13 rows) | Yes. #20 extends a room by a raw BLE person; correct except while that person's PLB reads `on`. #21, #22, #27, twin are pure | **Measured, negligible.** M3: PLB `on` 10 min total in 7 days across 4 people, so #20 can mis-hold a room for at most that long. #22's slug fallback (`presence_fan_recheck.py:1383-1385`) normalises an area_id key from the area selector, no observed miss | `persons_in_room` live since v5.108.28 with 1 consumer (interior vision, display), no incident; never yet used by an occupancy decision | Pro: one BLE-in-room meaning across 40 rooms (operator Q1 yes). Con: a 40-room occupancy change, Tier 2-DB, to cure 10 min/week, on a read with one display consumer | **PARK.** Trigger: any person's PLB `on` exceeds 2 h in a week, OR a room hold is traced to a PLB-on person, OR a second occupancy consumer adopts `persons_in_room`. #22's fallback moves to REGISTRY-NOT-NAMES-1 |
| **L1 display commit** #26 (20 rows / 34) | Yes (display loops) | **None** | `persons_in_room` as above | Pro: allowlist -34. Con: pure migration of display code | **PARK.** Trigger: L1 behaviour revives (then it rides the same build) |
| **L3-H1** boot seed `presence.py:3291-3298` (#5, unguarded) | Yes. The seed reads the trust-derived identified-persons entity; awareness has its own entities | **None measured.** M2: 0 false boot AWAYs in 27 restarts; the 3 boot-adjacent AWAYs were real | `house_census_view(cls="house_state")` live since v5.108.25 for the PLB sensor, no incident; never used at boot | Pro: the seed can never follow a display entity whose meaning changes. Con: a Tier-3 house-state change at boot for a defect never observed | **PARK the code.** Add only the guard rule case (an R3 hit for an f-string `sensor.{DOMAIN}_..._persons_in_house` state read) as a test-only change in the L4 build, with one allowlist row, so the leak is counted. Trigger: the identified-persons entity's derivation changes (e.g. awareness promoted onto it), OR a boot AWAY with a resident `home` |
| **L4** five fail-open identity vetoes + inline ids (#31, 11 rows; fold sites) | **No on a second install.** `camera_census.py:4841` (face-leg veto), `:5979` (sighting veto hint), `:6711` (stale-face latch), `transit_validator.py:2289` (egress veto) skip the veto when `person.<slug>` does not exist, and `camera_census.py:4898` (BLE crossing trackers) finds no trackers. Correct on this house (M4) | **Portability risk, measured 0 here.** An install whose person entity id is not the slug of its name (HA de-duplicated `_2`, a renamed person) gets no identity veto, silently | The old replacement (`tracked_person_entity_id`) does not fix it (string build). The minimal fix is NEW code on the miss path only; it reuses the proven `slug_of` | Pro: closes a silent fail-open on the next install; byte-identical here. Con: new helper (small), touches identity code in 5 places | **BUILD-MINIMAL** (D1 below). The rest of the old L4 (#33 getters, #34 restore move, #16, H6 delete, the other 4 inline builds) is pure migration: **PARK**, trigger: the person-id rule itself is replaced by a registry resolver (REGISTRY-NOT-NAMES-1) |
| **L5a** 13 cross-coordinator private reads (`hvac.py:1558-1560, 2748-2749`, `coordinator.py` fan state, `coordinator_diagnostics.py`, `manager.py`, `__init__.py`) | Yes; byte-identical getters were the plan | **None**; structural only (a rename of a presence private would break the reader). The guard rows keep each one visible | Getters would be new; nothing to prove | Pro: change safety for presence refactors. Con: touches hardened HVAC Wait-for-Presence and compliance code for no behaviour | **PARK.** Trigger: any change that renames or reshapes one of those presence privates (the getter is then written in that change) |
| L2 build 2 (lock ledger), L3-H2 (inference snapshot), L5b (presence display) | Correct (unchanged from the previous cut) | None | n/a | Parked before this ruling | **PARK** (triggers unchanged: LOCK-REGIME-BOOT-REALLY-AWAY-1 dispatched; any `_run_inference` read change or a measured tick inconsistency; a presence-private refactor) |

## 4. The one build

### D1. Fail-open identity vetoes resolve the real person entity (L4-min). Tier 2. ~1 builder-day

`person_coordinator.person_entity_for_slug(hass, slug) -> str | None`: returns `person.<slug>` when that state exists
(today's lookup, unchanged), else the one `person.*` state whose `slug_of(entity_id)` or `slug_of(friendly_name)`
equals `slug`, else None. Two or more matches return None (today's answer) and count a miss. The five veto sites call it
in place of the inline `f"person.{slug}"` (`camera_census.py:4841, 4898, 5979, 6711`, `transit_validator.py:2289`); the other four inline builds stay (parked). Plus the test-only H1 guard rule case.

**Invariant INV-VETO-RESOLVE:** for every slug, the veto decision equals today's decision whenever `person.<slug>`
exists; when it does not and exactly one person entity matches the slug by entity id or name, the veto reads that
entity's state. Falsified by any veto decision that differs on an install where every person entity id equals its slug,
or by a veto skipped when exactly one matching person exists.

**Acceptance:**
- **Verify:** fixture install with `person.oji_udezue_2` (friendly name "Oji Udezue") reading `not_home` and a face leg
  `oji_udezue`: each of the five sites vetoes (today: none does). Discriminates against "helper wired but exact path
  changed": the same fixture with `person.oji_udezue` present gives today's result on every site.
- **Test:** `test_veto_resolves_person_entity_not_slug` (parametrised over the five sites, each call-neutered RED),
  `test_veto_exact_entity_byte_identical` (golden over this house's live person set), `test_person_entity_for_slug_ambiguous_is_none`,
  guard drill for the H1 rule case.
- **Live:** `get_layer_diagnostics()["person_entity_fallback_hits"]` = 0 and `_misses` = 0 on this house after a day
  (every lookup is exact); egress `vetoed` outcomes per day in the same range as M4 (10 in 7 days).
- **Guard:** allowlist total 256 -> 257 (the H1 row); no other row changes.

**Non-goals:** no G1 move, no G6 move, no getter, no restore move, no HVAC touch, no change to `tracked_person_entity_id`,
`slug_of` or `entity_key_slug`, no change on the exact-hit path.

**Tier:** Tier 2 (identity vetoes, byte-identical on this house). One plan review (this table is the plan; framing G
included because the arc is ambitious), two framing-disjoint build reviews (A correctness incl. the ambiguous case; C
per-site mutation on the five sites).

## 5. Effort

| Item | Verdict | Builds | Builder-days |
|---|---|---|---|
| D1 L4-min (+ H1 guard case) | BUILD-MINIMAL | 1 | ~1 |
| L2-S1 | PARK (revival build ~0.5 day, Tier 2) | 0 | 0 |
| L2-S7, L1 behaviour, L1 display, L3-H1 code, rest of L4, L5a | PARK | 0 | 0 |
| L2 build 2, L3-H2, L5b | PARK (unchanged) | 0 | 0 |
| **Total** | | **1** | **~1** (was ~10 recommended, ~17 full) |

Order: D1 takes the next free builder slot after the current arc §4a row; it blocks nothing. The revival triggers above
are one-shot queries (SC armed state, `person_arrival.source_stale`, PLB on-hours) to run at each session-start organic
sweep; none needs runtime code.

## 6. Non-goals

No new fact, store or coordinator. No AWAY trigger change. No change to S1's windows or guest scope. No HVAC change. No
migration of correct code onto the layer in this cut. No allowlist row added except the H1 rule case.
