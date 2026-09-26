# PLANNING — HVAC Live-Room Establishment (HVAC-DEGRADED-ROOM-TRIPWIRE-1)

Author: Oji Udezue (via ura-planner)
Date: 2026-09-25
Card: `HVAC-DEGRADED-ROOM-TRIPWIRE-1` (kanban.data.yaml:1797)
Related: `HVAC-ZONE-CONDITIONING-DEMAND-1` (round-4 decision 2026-09-17;
correction 2026-09-25). Round-5 commit that this plan reverses in effect:
`f88f4bc84`.

Tier: **Tier 2-DB** (regression-prone by standing policy).
Plan-review: **ONE plan review before build dispatch** (Tier 2-DB rule).

---

## Operator rule (do not relitigate)

*Decided 2026-09-17 round 4; re-affirmed 2026-09-25.*

> HVAC must match occupancy IN THE ZONE. A zone's establishment must be
> computed over the rooms that are actually RUNNING; a disabled / failed
> room must not block the whole zone from ever retreating.

Round-4 implemented this wrongly as `any(...)`. Round-5 (orchestrator)
reverted to `all(zone.rooms)`, overriding the operator. This plan builds
the operator rule correctly: `all()` scoped to the **live set**, with an
explicit definition of live-vs-transient that is safe under
reload/boot.

---

## Institutional context verified

### Design docs read (end-to-end where marked)
- `docs/Coordinator/HVAC_COORDINATOR_MANUAL.md` — retreat gate ownership,
  establishment semantics.
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN_EXTENSION_2026_09.md` — the
  DPM / conditioning-demand extension where this gate lives.
- `docs/QUALITY_CONTEXT.md` — Bug Class #7 (stale data), #34 (setup-order
  races), #43 (coordinator-absent-on-first-tick — the reason the D1
  producer already tolerates `coordinator is None`), #53 (computed-but-
  not-consumed), #63 (coincidental equality masks a concept split — the
  live-set vs zone.rooms concept split this plan makes explicit).

### Prior planning docs consulted
- `docs/planning/PLANNING_hvac_conditioning_demand.md` — full read.
  D1/D7/D9/F3/F4 semantics; round-4 vs round-5 tension is documented
  there.
- Kanban cards read in full:
  - `HVAC-ZONE-CONDITIONING-DEMAND-1` (id, incl.
    `ROUND4_DECISIONS_2026_09_17`, `ROUND5_DONE_2026_09_17`,
    `correction_2026_09_25`).
  - `HVAC-DEGRADED-ROOM-TRIPWIRE-1` (this card, incl.
    `operator_decision_2026_09_25`, `operator_go_2026_09_25`).
  - `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`,
    `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` — sibling residuals
    of round-4/5; NOT touched by this cycle (non-goal — see below).

### Memory bodies pulled
- `feedback_suppression_needs_discharge` — any deferral needs an
  explicit discharge + backstop + restart story. Applied to
  "how long may a SETUP_RETRY room be counted as transient before it is
  reclassified permanent?" (the one knob this cycle introduces).
- `feedback_hollow_test_anchors` — mutation-anchored per-site tests,
  not source greps. Applied to the mutation drill below.
- `feedback_verification_needs_disjoint_framings` — three-reviewer
  framings are chosen disjoint (A/B/C below).
- `feedback_no_fabrication` — HA `ConfigEntryState` enum members are
  verified against installed source, cited below.
- `feedback_do_robust_fix_not_bandaid_and_card` — the trip-wire is
  demoted to a diag; the fix is structural.
- `project_incident_v5_8_0_setup_recursion`,
  `feedback_parent_reload_watchdog_hazard` — reload/boot cold-window
  hazards; the cycle is designed AROUND them, not against them.

### HA source verified (no fabrication)
`.venv-ha/lib/python3.13/site-packages/homeassistant/config_entries.py:141`
— `ConfigEntryState` members: **LOADED**, SETUP_ERROR, MIGRATION_ERROR,
**SETUP_RETRY**, **NOT_LOADED**, FAILED_UNLOAD, **SETUP_IN_PROGRESS**,
UNLOAD_IN_PROGRESS. The `_recoverable` flag distinguishes states where
the entry may still transition to LOADED (`LOADED`, `SETUP_ERROR`,
`SETUP_RETRY`, `NOT_LOADED` are recoverable=True; `MIGRATION_ERROR`,
`FAILED_UNLOAD`, `SETUP_IN_PROGRESS`, `UNLOAD_IN_PROGRESS` are False).

### Live install grounded
`/Users/okosisi/ha-config/.storage/core.config_entries` (Samba, RO):
grep of URA entries — 46 `"domain":"universal_room_automation"` rows,
**zero** with `disabled_by` set to a non-null value. So today the fix
is INERT on the live house (no permanently-disabled ROOM entries
exist), but the round-5 revert continues to block zone retreat on any
future room that a) fails setup terminally, b) is disabled_by user, or
c) sits in SETUP_RETRY across a boot. Acceptance criteria therefore
lean on synthetic fixtures + one live diag attribute we can read
post-restart.

### Prior-art scan — REUSE vs NEW (Tier 2+ mandatory)

Every proposed piece scanned across code / plans / analysis:

| Proposed piece | Verdict | Cite |
|---|---|---|
| "Is this ROOM config entry LOADED?" helper | **REUSED** — `aggregation.py:385 _integration_entry_is_loaded(entry)` already does the ConfigEntryState.LOADED test with a graceful fallback for mocked HA. Extend the same pattern (do NOT duplicate the function; either import it or lift the two-line body into hvac_zones.py behind an obvious name). | `aggregation.py:385-394` |
| `entry_id -> room_name` mapping | **REUSED** — `hvac_zones.py:303-309 entry_id_to_room_name` is built at the top of `update_room_conditions`. Same shape needed here; reuse the existing dict. | `hvac_zones.py:303` |
| Coordinator-absent tolerance on the D1 producer | **REUSED** — `hvac_zones.py:616-641` already appends a synthetic `RoomCondition(occupied=False, hvac_occupied=False)` on `coordinator is None` (v4.7.8 A-H1, Bug Class #43). We do NOT change producer behaviour; we only change what `_hvac_seen` means. | `hvac_zones.py:616` |
| `_hvac_seen` set | **REUSED** — declared `hvac_zones.py:256`, populated at `:665` (hallway) and `:988` (dwelling D1). Keep the writer surface unchanged. | `hvac_zones.py:256/665/988` |
| Establishment gate (`is_zone_hvac_established`) | **EXTEND** existing (`hvac_zones.py:1043`) — change denominator from `zone.rooms` to `live_rooms(zone)`; keep `all(...)` quantifier. NO new gate function; NO new callers. | `hvac_zones.py:1043` |
| Unified retreat authorisation (`conditioning_retreat_ok` + `_zone_conditioning_retreat_ok`) | **REUSED** unchanged (`hvac_zones.py:1085`, `hvac.py:3830`) — this is the single retreat chokepoint feeding row-1 (`hvac.py:2013`), D7 (`:2403`), D9 compose-away (`:2966`), F4 row-10 (arrester). Zero call-site changes. | `hvac_zones.py:1085` / `hvac.py:2013/2403/2966/3830` |
| SETUP_RETRY grace timer (transient→permanent reclassification) | **NEW** — no equivalent found after grep of `hvac_zones.py`, `hvac*.py`, `coordinator.py`, `__init__.py`. One `dict[room_name, first_non_loaded_ts]` tracked on ZoneManager. Justification: the operator hazard note demands "bounded window" for setup_retry before excluding. | (none) |
| Grace-window number | **NEW knob** — see Numbers-get-Knobs section (rung: module constant, `hvac_const.py`). Kill-switch by setting to a large sentinel. |  |
| Diagnostic attribute naming excluded rooms | **NEW diag** on an existing sensor — `sensor.<zone>_hvac_conditioning_demand` (the D1/D7/D9 debug sensor that already exposes zone establishment). No new entity. | `sensor.py` (D1-D9 debug sensor grepped separately during build) |
| Trip-wire (log/NM ping when a room is reclassified permanent) | **NEW** — one WARN log line + one NM notification via existing NM channel. No new NM template; reuse "hvac degraded" bucket. |  |

Result: **1 code change (establishment denominator)** + **1 small
helper (live_rooms)** + **1 new state field (grace-window timer)** +
**1 knob** + **1 diag attribute** + **1 trip-wire log line**. No new
gates, no new callers, no new signals, no new entities. This is the
minimum surface consistent with the operator rule.

### Code locations surveyed
- `domain_coordinators/hvac_zones.py` — full read of `ZoneManager`
  (state fields, `update_room_conditions`, `_compute_hvac_occupied`,
  `is_zone_hvac_established`, `conditioning_retreat_ok`).
- `domain_coordinators/hvac.py` — the four caller sites
  (`_zone_conditioning_retreat_ok` at :3830 and its four consumers at
  :2013, :2403, :2966, F4 row-10 arrester).
- `aggregation.py` — the LOADED-check pattern to reuse.
- `__init__.py` — coordinator-first-refresh setup order (:1737-1768 for
  ConfigEntryState checks; :4959-4962 for first_refresh boundary — the
  real reload-safety anchor).
- `quality/tests/test_zzz_hvac_conditioning_demand.py` — the two
  round-5 tests that pin current behaviour (`:429`, `:968`).

---

## The FALSIFIABLE invariant

**INVARIANT.** For every zone Z, define
`live_rooms(Z) = { r in Z.rooms | live(r) }` where `live(r)` is TRUE iff
r's ROOM config entry is in HA state `LOADED` **or** has been in a
transient state (`SETUP_IN_PROGRESS`, `SETUP_RETRY`, `NOT_LOADED`,
`UNLOAD_IN_PROGRESS`) continuously for **less than
`HVAC_LIVE_ROOM_SETUP_RETRY_GRACE_S`** since ZoneManager first observed
it non-LOADED. Then:

> A zone Z retreats (row-1 / D7 / D9 / F4 row-10) at time T only if
> `live_rooms(Z, T) ≠ ∅` AND for every r in `live_rooms(Z, T)`,
> `r ∈ _hvac_seen`, AND `Z.any_room_hvac_occupied is False`.

Two falsifiable corollaries (Reviewer D must break each with a legal
config repro):

1. **F-INV-A (transient safety).** In the reload/boot cold-retreat
   window, if any r ∈ Z.rooms is in a transient state and less than
   `GRACE_S` has elapsed since it went non-LOADED, `retreat_ok(Z)`
   returns False even if all other rooms are LOADED-and-seen-empty.
2. **F-INV-B (permanent tolerance).** If Z.rooms contains r_disabled
   whose entry is `disabled_by != None` (or has been non-LOADED for
   > GRACE_S), Z's establishment is decided over the remaining live
   rooms, and Z can retreat when they are all seen-empty.
3. **F-INV-C (all-dead safety).** If `live_rooms(Z) == ∅`, Z is
   UNESTABLISHED and `retreat_ok(Z)` is False.

Reviewer D re-enumerates the entire retreat surface (row-1, D7, D9
compose-away, F4 row-10 arrester) — including pre-existing code — and
must produce a concrete `(entry states, timing, occupancy)` tuple
that violates the invariant on ANY of these paths, or attest none
exists.

---

## Deliverables

### D1 — `live_rooms(zone)` helper on `ZoneManager`

Add a small helper `ZoneManager._live_zone_rooms(zone)` that returns
the subset of `zone.rooms` currently classified LIVE per the invariant
above. Uses:

- `entry_id_to_room_name` reverse-mapped to get the entry per room
  (built from `hass.config_entries.async_entries(DOMAIN)` filtered by
  `CONF_ENTRY_TYPE == ENTRY_TYPE_ROOM`).
- `ConfigEntryState` from HA source (verified above); do NOT hand-copy
  the enum values.
- Grace-window bookkeeping: a `dict[str, datetime]`
  `_room_non_loaded_since` on ZoneManager. Cleared when the entry is
  observed LOADED again. Room is EXCLUDED (not-live) iff:
  - `entry.disabled_by is not None`, OR
  - `entry.state == SETUP_ERROR` (terminal for our purposes; still
    marked recoverable=True by HA but requires explicit user action),
    OR
  - the entry has been non-LOADED continuously for
    `>= HVAC_LIVE_ROOM_SETUP_RETRY_GRACE_S` (default 300 s — one boot
    cycle worth).

Room is COUNTED LIVE (still blocks establishment) iff:
- `entry.state == LOADED`, OR
- entry is in a transient non-LOADED state AND `now - first_seen <
  GRACE_S`, OR
- entry cannot be located (defensive: an entry we can't classify still
  blocks — fail-closed for retreat).

#### Acceptance Criteria — D1
- **Verify (discriminating):** with a fixture where Z.rooms = [r_live,
  r_disabled] and r_disabled.disabled_by = USER,
  `_live_zone_rooms(Z)` returns `{r_live}`. Under the round-5 code
  path it would still include `r_disabled` (falsifies the fix).
- **Verify:** with r_transient in SETUP_RETRY for 60 s (< grace),
  `_live_zone_rooms(Z)` INCLUDES r_transient. At 400 s (> grace) it
  EXCLUDES it. The two observations differ — this discriminates
  transient-tolerance from permanent-exclusion.
- **Test:** `test_live_zone_rooms_excludes_disabled_by_user`,
  `test_live_zone_rooms_includes_setup_retry_within_grace`,
  `test_live_zone_rooms_excludes_setup_retry_past_grace`,
  `test_live_zone_rooms_all_dead_returns_empty`.
- **Live:** on the restarted install, `sensor.<zone>_hvac_
  conditioning_demand` attribute `live_rooms` equals `zone.rooms`
  (no disabled rooms exist today per live-install grep). If any room
  is temporarily NOT_LOADED at boot, its exclusion timestamp is set
  and the diag `live_rooms` list contracts, then expands once the
  entry loads.

### D2 — Rewire `is_zone_hvac_established` denominator

Change `hvac_zones.py:1083` from
`all(r in self._hvac_seen for r in rooms)` to
`live = self._live_zone_rooms(zone); return bool(live) and all(r in self._hvac_seen for r in live)`.

Keep `all()`. Keep the reset-only backstop in
`conditioning_retreat_ok` unchanged. `bool(live)` enforces F-INV-C.

#### Acceptance Criteria — D2
- **Verify (discriminating):** for Z with rooms = [r_live, r_disabled],
  after the D1 producer has processed r_live once,
  `is_zone_hvac_established(Z)` returns True (was False under
  round-5). For Z with all rooms disabled, returns False (safety).
- **Test:** REPLACE `test_f1_disabled_room_leaves_zone_unestablished_
  round5` with its inverse
  `test_f1_disabled_room_excluded_zone_establishes_from_live_rooms`.
  KEEP `test_row1_fail_open_unestablished_zone` as-is (a zone whose
  live rooms are unseen still must not retreat — invariant preserved).
- **Test:** `test_zone_all_rooms_disabled_stays_unestablished`
  (F-INV-C).
- **Test (mutation-anchored):** neuter `_live_zone_rooms` to return
  `zone.rooms` (i.e. the round-5 behaviour); the new discriminating
  test above must go RED. Restore, re-run, green. This proves the
  denominator swap is load-bearing, per the Tier 2-DB C-framing.
- **Live:** post-restart, all four retreat consumers (row-1 preset-flip,
  D7 night-trust suppression, D9 compose-away, F4 row-10 arrester)
  observe an ESTABLISHED zone within the same first-refresh tick that
  they do today (no regression window).

### D3 — Diagnostic attribute (trip-wire demoted to diag)

Extend the existing D1/D7/D9 debug sensor for each zone (identified
during build via `grep sensor.py hvac_conditioning`) with attributes:
- `live_rooms: list[str]` — the current LIVE set.
- `excluded_rooms: list[{name, reason}]` — one of
  `disabled_by_user | disabled_by_integration | setup_error |
  transient_past_grace`.
- `transient_rooms: list[{name, state, seconds_non_loaded}]` — rooms
  still inside the grace window.

Fire a single WARN log line + NM notification (existing "hvac
degraded" bucket) the first time a room transitions from
transient→excluded (i.e. crosses the grace boundary). Debounce: once
per (zone, room, boot).

#### Acceptance Criteria — D3
- **Verify:** attribute round-trips after restart (RestoreEntity not
  required — attrs are derived).
- **Test:** `test_diag_reports_excluded_disabled_room` and
  `test_transient_to_permanent_emits_one_warn_and_nm`.
- **Live:** `ha_get_state sensor.<zone>_hvac_conditioning_demand`
  after restart shows `excluded_rooms == []` and `live_rooms ==
  zone.rooms` on the current install (no disabled rooms).

### D4 — Grace-window knob

Add `HVAC_LIVE_ROOM_SETUP_RETRY_GRACE_S = 300` to `hvac_const.py`.

**Numbers-get-knobs — rung: module constant.** Rationale: this is a
safety-bound tuning; changing it should REQUIRE a code review because
too-small values regress the reload-safety window (F-INV-A) and
too-large values leave the feature INERT for a stuck-in-retry room
(the exact class this cycle exists to fix). Not an operator knob —
they should never turn this. Kill-switch semantics: setting to a
value larger than any realistic boot window (e.g. `10**9`) restores
the round-5 conservative behaviour for transient rooms only (permanent
disabled_by still excluded — that path does not consult the timer).

#### Acceptance Criteria — D4
- **Verify:** default 300 s; grep confirms exactly ONE definition and
  ONE reader (in `_live_zone_rooms`).
- **Test:** parametrised test asserting behaviour at grace-1 s
  (INCLUDES) and grace+1 s (EXCLUDES) using an injected clock.

---

## PRODUCER and CONSUMER checks

### PRODUCER — establishment
- **How computed:** `is_zone_hvac_established(zone_id)` at
  `hvac_zones.py:1043`. New arithmetic: quantified `all()` over
  `_live_zone_rooms(zone) ⊆ zone.rooms`.
- **Dependencies + health:**
  - `_hvac_seen` — populated by `update_room_conditions` at
    `:665` (hallway) and `:988` (D1 dwelling). Currently healthy;
    unchanged by this cycle.
  - `zone.rooms` — configured; unchanged.
  - `hass.config_entries.async_entries(DOMAIN)` +
    `entry.state`, `entry.disabled_by` — HA runtime API, verified
    against installed source `.venv-ha/.../config_entries.py:141`.
    Health cross-checked live via `.storage/core.config_entries`
    (46 URA entries, 0 disabled today).
  - `_room_non_loaded_since` — NEW, seeded on first non-LOADED
    observation per (boot, room). Cleared on LOADED observation.
- **Cross-check vs external ground truth:** the live-install
  `.storage/core.config_entries` file IS the ground truth; the diag
  attribute (D3) exposes producer output for direct comparison.

### CONSUMER + call-site check
Single retreat chokepoint: `ZoneManager.conditioning_retreat_ok` →
`HVACCoordinator._zone_conditioning_retreat_ok` (`hvac.py:3830`).
Four call sites, all trust-decisions (not display):
- `hvac.py:2013` — row-1 preset-flip retreat gate.
- `hvac.py:2403` — D7 night-trust suppression.
- `hvac.py:2966` — D9 compose-away.
- F4 row-10 arrester `comfort_delay_active` — grepped during build.

Zero call-site changes. All four consumers inherit the denominator
change transparently. Trust vs display: all four are trust
(actuation-gating). The diag attribute (D3) is the only display
consumer of the new producer output — pure display, cannot influence
retreat.

---

## The hazard we design around (reload/boot cold-retreat)

The round-5 revert existed because loose "live" would let a zone
retreat while other rooms are still loading. This plan preserves
reload safety via three layered defences, all falsifiable by
Reviewer D:

1. **Grace window (`GRACE_S = 300`).** SETUP_RETRY / SETUP_IN_PROGRESS
   / NOT_LOADED rooms REMAIN in `live_rooms` — and therefore continue
   to block establishment — for the first `GRACE_S` seconds after
   ZoneManager first observed them non-LOADED. This directly holds
   F-INV-A during the boot window.
2. **First-refresh boundary (unchanged).** `__init__.py:4959-4962`
   awaits `async_config_entry_first_refresh` before the coordinator
   is published, so the D1 producer's first pass populates
   `_hvac_seen` synchronously with retreat-consumer wire-up. This
   plan does NOT weaken that boundary.
3. **Fail-closed defaults.** An entry that cannot be located
   (e.g. race in `async_entries()` return) is treated as LIVE (not
   excluded); an empty `live_rooms` returns unestablished (F-INV-C);
   `conditioning_retreat_ok` returns False on any lookup exception
   (unchanged).

Note on SETUP_ERROR: per HA source it is marked recoverable=True
(user can retry from UI), but for our purposes "sitting in
SETUP_ERROR" is a terminal degraded case — we exclude immediately
rather than wait for the grace timer. If the operator fixes the
error, the next LOADED transition clears the exclusion in the same
tick (`_room_non_loaded_since.pop` on LOADED observation).

---

## Mutation drill plan (Tier 2-DB C-framing per-site source mutation)

Load-bearing sites to neuter one at a time; specific test that must
go RED for each:

| Site | Mutation | RED test |
|---|---|---|
| `_live_zone_rooms` denominator | replace body with `return list(zone.rooms)` (round-5 behaviour) | `test_f1_disabled_room_excluded_zone_establishes_from_live_rooms` reds |
| Grace-window inclusion | force `first_seen = now - 10**9` (i.e. always past grace) | `test_live_zone_rooms_includes_setup_retry_within_grace` reds |
| Grace-window exclusion | force `first_seen = now` (i.e. always inside grace) | `test_live_zone_rooms_excludes_setup_retry_past_grace` reds |
| `bool(live)` guard in `is_zone_hvac_established` | remove the `bool(live) and` prefix | `test_zone_all_rooms_disabled_stays_unestablished` reds |
| `disabled_by is not None` predicate | remove | `test_live_zone_rooms_excludes_disabled_by_user` reds |
| `_room_non_loaded_since.pop` on LOADED | remove | new `test_transient_room_recovers_after_load_clears_grace` reds |
| WARN + NM emission | comment out | `test_transient_to_permanent_emits_one_warn_and_nm` reds |

Every mutation is source-swap (not aggregate monkeypatch). Restore
after each; run `find . -name '__pycache__' -type d -prune -exec rm
-rf {} +` between mutations to defeat `.pyc` staleness (per
`feedback_mutation_verification_pycache_staleness`).

---

## Tests to add / replace (summary)

Replace:
- `test_f1_disabled_room_leaves_zone_unestablished_round5`
  → `test_f1_disabled_room_excluded_zone_establishes_from_live_rooms`
  (inverts the assertion).

Keep unchanged:
- `test_row1_fail_open_unestablished_zone` — the invariant that
  unseen live rooms block retreat is UNCHANGED.

Add:
- `test_live_zone_rooms_excludes_disabled_by_user`
- `test_live_zone_rooms_excludes_disabled_by_integration`
- `test_live_zone_rooms_includes_setup_retry_within_grace`
- `test_live_zone_rooms_excludes_setup_retry_past_grace`
- `test_live_zone_rooms_all_dead_returns_empty`
- `test_zone_all_rooms_disabled_stays_unestablished`
- `test_transient_room_recovers_after_load_clears_grace`
- `test_transient_to_permanent_emits_one_warn_and_nm`
- `test_diag_reports_excluded_disabled_room`

All new tests use an injected clock and an inline `ConfigEntryState`
fixture (do NOT hand-copy the enum — import from HA).

---

## Non-goals

- **F2 / `_last_emitted_range` restore-writer strand
  (`HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`).** Sibling
  residual of round-4; separately carded; blocked on measurement.
- **D9 compose-away throttle bypass
  (`HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`).** Blocker on
  enabling Custom Preset Ranges; dormant live; separately carded.
- **`set_hvac_mode` chokepoint / thermostat abstraction
  (`HVAC-SETHVACMODE-CHOKEPOINT-1`, `HVAC-THERMOSTAT-ABSTRACTION-1`).**
  Different write-verb governance work.
- **Zone_1 manual oscillation
  (`HVAC-ZONE1-MANUAL-OSCILLATION-1`).** Different producer
  (URA's AC soft-nudge + Bryant reclaim); mechanism corrected
  2026-09-25.
- **New operator-facing knobs.** The grace-window is intentionally a
  module constant, not a Number entity (see Numbers-get-Knobs).
- **New signals / dispatch sites / entities.** Diag lives on the
  existing debug sensor.

---

## Tier classification + justification

**Tier 2-DB.** Regression-prone by standing policy (operator-coined
2026-06-08):

1. **Shared primitive consumed by many decision sites.** The retreat
   authorisation chokepoint (`conditioning_retreat_ok`) feeds 4
   distinct HVAC actuation paths (row-1, D7, D9, F4 row-10). A wrong
   denominator ripples to every zone on every tick.
2. **Trust-hierarchy ripple.** The gate sits at
   presence ↔ HVAC ↔ compliance (empty vs occupied). A too-loose
   fix could retreat a zone that is not empty (comfort/safety loss);
   a too-strict fix restores the round-5 INERT-forever failure.
3. **State-machine × time seam.** SETUP_RETRY + grace window is
   exactly the "state machine × time" ingredient the two worst recent
   bug families lived at. Warrants three framing-disjoint reviews.
4. **History.** This surface has already seen 5 rounds of fix-up
   (round-4 wrong, round-5 override, this round the third attempt).

Three framing-disjoint reviews:
- **A — data integrity + retreat-chokepoint preservation.** No
  regression to `_hvac_seen` producer arithmetic; existing consumers
  see byte-identical behaviour when `live_rooms == zone.rooms`
  (which is the current live state); no new dispatch / signal
  emission; reset-only backstop preserved.
- **B — migration / cross-coordinator invariant.** Trace each of the
  4 consumers end-to-end under (disabled room, transient room within
  grace, transient room past grace, all-dead zone, reload cold
  window). Field-by-field shape comparison for the diag attribute.
- **C — new surfaces + test authority via per-site source mutation.**
  Per the mutation drill table above. `.pyc` staleness defence
  applied.

Plus **Reviewer D (adversarial completeness)** if any A/B/C finds
suggests the invariant enumeration is incomplete — Reviewer D
re-enumerates the entire retreat surface INCLUDING pre-existing code
(not just the diff) and produces a legal-config repro for any
violation of F-INV-A/B/C, or attests none exists.

Pre-review baseline tag: `pre-review-v<next>` before any review
fix-up. Live-validation write-back into `README_v<next>.md` mandatory.

---

## Open questions requiring operator (only if the operator rule doesn't already answer them)

**None on the semantic question.** The operator rule ("match occupancy
in the zone; disabled/failed rooms EXCLUDED; a zone of only dead
rooms stays unestablished") answers the shape completely.

**None on the trip-wire framing.** Card explicitly demotes it to a
diag; this plan implements it as an attribute + one WARN + one NM
ping per (zone, room, boot).

**Deferred to reviewer judgement (not operator):** whether
SETUP_ERROR should also honour the grace window rather than
immediate-exclude. This plan chooses immediate-exclude on the basis
that SETUP_ERROR is user-actionable (dashboard shows it) and
"sitting in SETUP_ERROR" is exactly the degraded case the operator
described. If Reviewer B disagrees, the change is one predicate line
plus a test update.

---

## Orchestrator hand-check amendments (2026-09-26) — BINDING, supersede conflicting text above

The planner ran on claude-opus-5; the operator directed a hand-check of its output. Findings:

**AM-1 (CRITICAL — the D2 formula as written FALSIFIES F-INV-A).** D2 computes
`bool(live) and all(r in self._hvac_seen for r in live)`. A room that is TRANSIENT (inside the grace
window) is in `live`, but it was very likely added to `_hvac_seen` BEFORE it went non-LOADED (e.g. a
room reload: LOADED → UNLOAD_IN_PROGRESS → NOT_LOADED → SETUP_IN_PROGRESS → LOADED), and while its
coordinator is absent the D1 producer appends a synthetic `RoomCondition(occupied=False,
hvac_occupied=False)` for it (`hvac_zones.py:616-641`). So during a single room's reload the zone can
read established AND fused-empty and retreat on a room nobody can see. That is exactly the cold-retreat
hazard the round-5 revert was protecting. **Binding rule:** establishment requires every live room to
be **LOADED AND in `_hvac_seen`**; ANY room in a transient state inside the grace window makes
`is_zone_hvac_established` return **False** outright (it blocks; it is never "satisfied" by a stale
seen-flag). Only rooms classified EXCLUDED leave the denominator. Required test:
`test_reloading_room_previously_seen_blocks_establishment` (room in `_hvac_seen`, entry flips to
SETUP_IN_PROGRESS, coordinator None → `is_zone_hvac_established` False, retreat_ok False). Mutation:
revert to the plan's original D2 formula → this test REDs.

**AM-2 (HIGH — incomplete state classification).** HA's `ConfigEntryState`
(`.venv-ha/.../config_entries.py:144-158`) has 8 members; the plan classifies 6. `MIGRATION_ERROR` and
`FAILED_UNLOAD` (both `recoverable=False`) are unhandled. **Binding classification:**
- EXCLUDED immediately: `disabled_by is not None` (any state), `SETUP_ERROR`, `MIGRATION_ERROR`.
- TRANSIENT (blocks for up to `HVAC_LIVE_ROOM_SETUP_RETRY_GRACE_S`, then EXCLUDED): `SETUP_RETRY`,
  `NOT_LOADED`, `SETUP_IN_PROGRESS`, `UNLOAD_IN_PROGRESS`, `FAILED_UNLOAD`.
- LIVE: `LOADED`.
- Any state not in these lists (a future HA member) → TRANSIENT (fail-closed) + one WARN.
Required test: `test_every_config_entry_state_is_classified` iterating `list(ConfigEntryState)` imported
from HA (never hand-copied).

**AM-3 (verified, no change).** `hass.config_entries.async_entries(domain)` includes disabled entries by
default (`include_disabled=True`, `config_entries.py:2073-2077`), so `disabled_by` rooms are visible to the
helper. Rooms whose entry was deleted are already dropped from `zone.rooms` at zone build with a WARN
(`hvac_zones.py:337-347`), so "entry cannot be located" arises only for a mid-session removal; keep the
plan's fail-closed treatment (blocks) — it self-heals on the next zone rebuild.

**AM-4 (process).** Reviewer D (adversarial completeness, whole retreat surface incl. pre-existing code) is
**MANDATORY**, not conditional — this is a state-machine × time seam with 5 prior fix-up rounds. The plan
review must NAME the exact diagnostic sensor entity that carries establishment today and the exact NM
channel/bucket used, with file:line — no "identified during build".

**AM-5 (scope note).** The synthetic-empty RoomCondition for an absent coordinator (`hvac_zones.py:616-641`)
is pre-existing; AM-1 neutralises its effect on the retreat gate for transient rooms. Reviewer D must still
check whether any OTHER consumer of `any_room_hvac_occupied` (not via `conditioning_retreat_ok`) acts on that
synthetic empty during a room reload.
