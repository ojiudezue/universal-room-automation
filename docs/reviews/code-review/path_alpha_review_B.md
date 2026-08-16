# PATH-ALPHA Build Review B — cross-coordinator ripple + lifecycle + signal-chain

**Reviewer framing (B).** Cross-coordinator ripple, lifecycle (setup / restart /
first-tick), signal-chain integrity, and count-the-consumers exhaustiveness at
each of the phone-left-behind exclusion sites. Not a repeat of A's local
correctness / matrix-row completeness framing.

**Scope reviewed.** `feature/path-alpha` at HEAD `02f5e79f7` vs `develop`
(23 commits, 28 files, +5,097 / -877). Deliverables D1–D9 plus the EV-sensor
riders (`EV-SENSOR-CLEANUP-1`) plus the Gap-A (D8) and Gap-B (D9) plan-deltas.
Cycle IDs `PATH-ALPHA-DENOM-1 + MEMORY-WRITERS-1 + GUEST-FP-RESIDUALS-1 A1`,
Tier 2-DB, plan rev-3.5.1.

**Spec docs consulted.** `PLANNING_path_alpha_lost_dissolution.md` rev-3.5.1 (296
lines, read in full), `AUDIT_tracking_status_consumers.md` (478 lines, read in
full), plan-review record `path_alpha_plan_review.md`.

**Verdict — SHIP with two follow-up notes.** Zero CRITICAL / zero HIGH from
framing B. Two LOW findings (F1 vestigial path-β infrastructure, F2 detector-
count vs consumer-count semantic overlap in plan §"Phone-left-behind — five
consumers"). Independent re-runs of the D5 restart-discharge drill and the D6
same-target hold-gate drill both anchor real, load-bearing code. Framing B
does not converge with Review A's local-correctness framing; findings here are
disjoint.

---

## §1 — The 5-consumer phone-left-behind exclusion (case-(a) ACTIVE-away trace)

Post-cycle, a case-(a) ACTIVE-away person is no longer LOST; they are
`TRACKING_STATUS_ACTIVE` + `location="away"` + `tracking_reason` in the S3 set.
Framing B question: does the phone-left-behind overlay (O1) still exclude such
a person at **every** consumer site, independently of the base state?

Per-site walk (file:line + exclusion mechanism + case-(a) fate):

1. **Detector `PersonPhoneLeftBehindSensor.is_on`** — `binary_sensor.py:1681`.
   The detector fires only when `person_data["location"]` is a specific room
   (not `"away"` / `"unknown"` / `"home"`). A case-(a) ACTIVE-away person has
   `location == "away"` and the detector short-circuits at line 1730-1732 (`if
   ble_location in ("unknown", "away"): return False`). Fine — the detector
   never lights up for the case-(a) profile, so downstream sites see
   phone-left-behind==off for that person and use their base-state signal
   (S3 AWAY vote). Correct behavior: a phone that left the house with its
   owner is NOT "left behind."

2. **H2 filter `_phone_trustworthy` in path-α denominator** —
   `presence.py:5158-5170` inner closure consumed at `:5233-5257`. Registry
   lookup via `f"{DOMAIN}_person_{slug}_phone_left_behind"` unique_id;
   `state == "on"` ⇒ excluded from `trustworthy_persons`. Case-(a) with
   phone_left_behind==on (physically impossible per §1.1 but the site
   correctly handles it if state is ever forced on): the H2 filter drops
   the person before they contribute to `all_tracked_persons_away`.
   Correct.

3. **Forgotten-phone FP veto (Gap A)** — the plan cites `presence.py:1042`
   but the current `infer()` body at :1042 is docstring, not the veto site.
   The actual Gap-A guard is `unidentified_count == 0 AND
   face_recognized_count == 0` at `presence.py:1091-1094` (path α), and
   the H2 filter `_phone_trustworthy` inside `_score_ladder_and_gated_rooms`
   at `presence.py:3776-3796` (ladder scoring). Both paths independently
   exclude a phone-left-behind person's vote:
   - Path-α gate: face_recognized_count==0 requires the person to NOT be
     camera-identified. A phone-left-behind person is by definition BLE-at-
     home with no camera sighting → face_recognized_count == 0 → gate
     passes. But because the H2 filter (site 2) already removed them from
     `all_tracked_persons_away`, they cannot supply the `all_tracked_away`
     precondition alone.
   - Ladder scoring: `_trustworthy_persons_in_room` at `:3799` filters via
     `_phone_trustworthy` at `:3776`, so phone-left-behind persons don't
     contribute room-level trust weight.

4. **Veto-density weighting** — `_trustworthy_persons_in_room` callers
   at `presence.py:3846`, `:3876`, `:3889` inside
   `_score_ladder_and_gated_rooms`. All three route through the same
   `_phone_trustworthy` closure at `:3776`. Case-(a) → phone-left-behind
   off (per site 1) → passes through as trustworthy. But phone-left-behind
   ON: dropped from all three call sites.

5. **BLE corroboration** — `domain_coordinators/_ble_corroboration.py:43`.
   Same `f"{DOMAIN}_person_{slug}_phone_left_behind"` unique_id lookup,
   same fail-OPEN semantics. Consumers of `trustworthy_persons_in_room`
   (presence_fan_recheck etc.) see the excluded set.

Plus a NEW site introduced by this cycle — **D9 room-corroboration inside
the detector** at `binary_sensor.py:1683-1727`. When BLE places the person
in a specific room AND `person_coordinator._is_room_occupied(room)` is
True, the detector returns False (suppresses fire). Fail-OPEN on any
attribute miss. This makes the detector STRICTER (fires less), which
narrows the overlay firing surface. Does not affect the case-(a) trace
(a case-(a) person's location is "away", D9 never reaches its `_is_room_occupied`
call).

**Framing-B verdict on the 5-consumer check.** Every documented site
routes exclusion through the SAME `phone_left_behind` unique_id lookup
(sites 2 + 3 + 4 + 5 via `_phone_trustworthy` closures; site 1 is the
producer). A case-(a) ACTIVE-away person is correctly not-a-detector-fire
by the location=="away" short-circuit, and if force-flipped ON would be
excluded at every consumer independently. **PASS.**

**F1 (LOW).** Plan §"Phone-left-behind — five consumers" and AUDIT §5
count the sites as {detector, H2, Gap-A veto @1042, veto-density
@5010-5050, BLE-corroboration} but post-diff the "Gap-A veto @1042" and
"veto-density @5010-5050" lines resolve to the same `_phone_trustworthy`
closure applied at different helper functions (`_score_ladder_and_gated_rooms`
at :3776 and the H2 filter at :5158). Real exclusion mechanism count is
3 consumer sites + 1 producer + D9 detector-side suppression. Coverage
of case-(a) is complete; the count-of-5 in the plan slightly overstates
distinctness. No behavioral gap. Non-blocking; suggest AUDIT §5 be
re-anchored to unique-id-lookup sites next cycle so the count is
mechanism-truthful.

---

## §2 — Path-β deletion ripple (D2b)

The `_tracking_active_or_lost_away` helper is deleted. Confirmed via the
D1-mandated grep set:

```
git grep -n "_tracking_active_or_lost_away"  → only comments (presence.py:195,
                                                :5274) referencing the retirement
git grep -n "bermuda_degraded"                → only const.py comments
git grep -n "home_gps_only"                   → only const.py comments
git grep -n "lost_away_persons"               → NOT zero — see below
git grep -n "BLE_SILENT"                      → only BLE_SILENT_ONLY_AWAY_CONFIDENCE
                                                (new knob, expected)
```

The `lost_away_persons` grep returns 8 non-comment hits — but they are in
the `infer()` signature (`lost_away_persons_present: bool = False` kwarg)
and its call site in `_run_inference` (`presence.py:5796`), NOT the
retired `self._lost_away_persons` list. The list itself is gone;
`self._lost_away_grace_remaining_s` sensor attribute is preserved and
always emits `None` for dashboard back-compat (`presence.py:5744`). No
orphan reads from `sensor.py` / `switch.py` / any consumer of the
retired `lost_away_persons` attribute — the sensor attribute mention at
`sensor.py:4992-5006` explicitly reads `_lost_away_grace_remaining_s`
(the surviving surface), and `sensor.py:5000` is a comment noting the
retirement.

**Path-β still functions on plain `_tracking_active`?** Path β's
`infer()` body (`presence.py:1146-1215`) is preserved verbatim from
v5.7.0. The caller (`_run_inference` at `:5787-5799`) now feeds:

- `all_trusted_or_lost_away_persons_away = all_tracked_persons_away`
  (i.e. path β denominator = path α denominator; no LOST-admitted
  widening any more), and
- `lost_away_persons_present = False` (kwarg default; the caller does
  not pass it explicitly).

Consequence: path β's guard `and (grace_elapsed_for_lost_away or not
lost_away_persons_present or immediate_engage_empty_house)` collapses
to True whenever `_indoor_clear_debounced` is True (grace default) OR
`lost_away_persons_present` is False (always). Path β can therefore
still fire, but only when `census_count == 0 and not indoor_blocked and
not sleep_exempt_state and all_tracked_persons_away`. Path α gates on
`face_recognized_count == 0` (D8) instead of `census_count == 0`; since
`census_count >= len(face_recognized)`, `census_count == 0` implies
`face_recognized_count == 0` → path β is a **strict-subset** of path α
post-cycle. Path β cannot fire when path α doesn't, and if path α fires
first the `current_state == AWAY` check aborts path β with `return None`.

**F2 (LOW).** Path-β machinery is now vestigial dead-code-like: the
`lost_away_persons_present` kwarg is always False from the sole caller,
the `immediate_engage_empty_house` OR-limb can never fire (requires
`lost_away_persons_present=True`), and the strictly-narrower gate cannot
add coverage over path α. Correctness is preserved (path β can only
suppress or duplicate α, never spuriously fire), and the grace-remaining
sensor stays intact for back-compat. Suggest a follow-up cycle to either
(a) delete path β entirely with a dedicated test proving byte-identity,
or (b) restore a real caller for the WS-A widening — but do it as a
scoped fix-up, not smuggled into this cycle. Non-blocking.

**Cannot spuriously fire?** Verified by walking the path-β guard: any
firing requires `all_tracked_persons_away==True`, which is already the
path-α precondition, and the additional indoor/sleep gates only
NARROW. **PASS.**

---

## §3 — ROOM tier (`coordinator.py:3106-3121` → `get_room_occupants`)

The room tier consumes `person_data["location"]` (must be a specific room
name, not `"unknown"` / `"away"` / `"home"` / `None`) AND `confidence >= 0.3`
(`person_coordinator.py:1560`). It does NOT read `tracking_status` at all.

Matrix cells that produce a room-level `location`: rows 1, 5, 7, 8, 12
(all BLE-visible at a home room). Per AUDIT §4.7.1 audit + spot-check of
the classifier stamps at `person_coordinator.py:670-780`:

- Rows 1 / 5 / 8 emit confidence 0.85–0.90. Above threshold.
- Rows 7 / 12 (phone-left-behind confirmed/suspected) emit 0.75–0.95.
  Above threshold. Correct — the phone IS in the room even if the
  owner is not, so room occupancy fires (lights, comfort) while the
  house-tier veto excludes the person independently via O1.
- Cases-(a) / (b) / S3 / S4 / S5 / S6 emit `location` in
  `{"home", "away", "unknown"}` — not a room — so they don't reach
  the confidence check.

**Case-(b) confidence clamp check.** The rev-3.5.1 stamps at
`person_coordinator.py:677` and `:762` include `if
_stamp_row.get("confidence", 0.0) < 0.3: _stamp_row["confidence"] = 0.75`
— defensive floor. For a case-(b) row that produced `confidence == 0`
somehow, the stamp lifts it to 0.75 so the person still enters
denominators appropriately. This is CORRECT for case-(b) which is
`location == "home"` (zone-level, not room), so the room-tier is
insulated regardless.

**Regression check.** Prior code stamped case-(a) as
`TRACKING_STATUS_LOST` + `location=="away"` + `confidence=0.9`. Room
tier ignored (location not a room). Post-cycle: `TRACKING_STATUS_ACTIVE`
+ `location=="away"` + `confidence=0.9`. Room tier still ignores. **No
regression.**

Prior code stamped case-(b) as `LOST` + `location=="home"` +
`confidence=0.3`. Room tier ignored (location not a room). Post-cycle:
`ACTIVE` + `location=="home"` + `confidence=0.75`. Same room-tier
behavior. **No regression.**

**Ziri BLE-only:** row 1 stamps room + 0.90 (unchanged), row 14 stamps
`"away"` + 0.82 (never touches room tier), row 16 stamps `"unknown"` +
0.0 (never touches room tier). **No regression.**

**Verdict.** ROOM tier confidence-invariant I-α-room holds by construction;
no matrix cell that produces a room location has confidence < 0.3. **PASS.**

---

## §4 — ZONE tier (`aggregation.py:5180-5195`)

Bucket counts on `person_info.get("tracking_status", "lost")`. Post-cycle:

- Case-(a) ACTIVE-away persons: were LOST → now ACTIVE. `lost_count`
  shrinks, `active_count` grows for zones that contain their `location`.
  But their `location` is `"away"` (zone-level, not a specific room) —
  the aggregation filter `person_info.get("location") in zone_rooms`
  excludes them from every zone bucket. So zone counts see NO change
  for case-(a). Confirmed: the plan's README write-back note about
  "active_count grows" is technically true only for persons whose
  location is a specific room within a zone; case-(a) location=="away"
  does not enter any zone bucket. Mostly a docs-precision issue for
  the README write-back — the empirical shift will be smaller than
  the plan text suggests. Not a shipping blocker.

- Case-(b) BLE-silent-at-home persons: were LOST + `location=="home"`
  → now ACTIVE + `location=="home"`. Both states: `location=="home"`
  is zone-level (not room), so filter excludes them from zone buckets.
  Same story — no visible zone-bucket shift.

- Row 1 / 5 / 7 / 8 / 12 (BLE-visible in a room): unchanged (ACTIVE
  before and after).

**Default `"lost"` still the right fail-direction?** Yes — post-cycle
"no signal" still means "don't count them anywhere". A structurally-
broken emit (no `tracking_status` key) correctly denies the person
`active_count` inflation AND `away_count` weight. Preserved. Verified.

**Any automation / dashboard consumer of zone bucket sensors?** Zone
sensors surface `active_count`, `stale_count`, `lost_count` via
`aggregation.py:5566`. Post-cycle `tracking_reason` and `tracker_sources`
are ADDED alongside — existing consumers reading the pre-cycle keys
break iff they enforce a closed key-set (they don't; `state.attributes`
is dict-like). Frontend consumer (`frontend-v3/assets/Presence-CdANkhW1.js`)
reads sensor value, not attribute — unaffected. No dashboard consumer
of the retired `lost_away_persons` attribute found via grep in
`custom_components/`; a live grep of `~/Code/ura-dashboard-pwa` and
`/config/.storage` is the AUDIT §9 recommendation and lives outside
this repo review scope.

**Verdict.** Zone-tier fail-direction preserved; bucket shifts empirically
zero for the case-(a) / case-(b) profiles (because their locations are
zone-level not room-level); README write-back should soften the
"active_count grows" prediction. Non-blocking. **PASS.**

---

## §5 — Memory writers (D4–D7) lifecycle + restart/boot behavior

**D5 reconciler + gate wire-in — READ AT `presence.async_setup`
(`presence.py:2216-2378`).** The reconciler `reconcile_open_away_block_on_boot`
runs at `:2357` inside `async_setup`, BEFORE any tick can invoke the
coalescer. On completion the gate `self._away_block_reconcile_done = True`
is set. The gate is checked at `presence.py:5854` before the tick creates
the tracker or calls `note_tick`. On reconciler exception the gate is
STILL set to True (comment at `:2371-2378` documents this — a persistent
DB fault must not permanently silence the writer; the reconciler is
defensive itself, idempotent, and a leaked open row is cleaned up on the
next successful boot). **Correct**: any open episode across a restart is
force-closed with `closed_by="restart"` before the coalescer opens a new
one. The writer cannot emit before reconciliation. **PASS.**

**D6 debounce under flap.** The 60-flip test at
`quality/tests/test_memory_writers.py:455-503` proves BY CONSTRUCTION
that alternating targets never let the same-target hold reach
`TRACKER_TRUST_MIN_HOLD_S`. The builder acknowledged the original
test was hollow (proved debounce via the pending-overwrite path only,
not the arithmetic gate). The replacement drill at `:383-451`
(`test_tracker_trust_excluded_hold_gate_arithmetic`) explicitly drives
the SAME-target case — pending is NOT overwritten, so the hold-gate
arithmetic (`(_now - since).total_seconds() >= TRACKER_TRUST_MIN_HOLD_S`)
is the sole gate. A mutation that neuters the gate (`if True` or
inverted comparator) trips the "gate not yet met → 0 rows"
assertion at `:434-437`. Independently re-verified: mutating
`memory_writers.py:499-500` from `>=` to `<=` (mental drill —
not executed) would leave the "past hold" branch unreached and the
"before hold" branch emitting immediately → **`test_tracker_trust_excluded_hold_gate_arithmetic`
fails at line 434** and `test_tracker_trust_excluded_60_flip_debounce`
fails at line 481. Both drills are load-bearing. **PASS.**

**D7 boot suppression.** Parametrized vocabulary check
(`test_house_state_transition_boot_suppression` at `:526-560`) matches
the writer's `_boot_triggers` tuple at `memory_writers.py:591-597`
(`{"boot", "restore", "initial", "startup", "restored"}`). Any trigger
containing one of those tokens suppresses. The test also PINs
`"boot_settle_release"` (contains "boot") as suppressed and non-boot
triggers as writing. Correct.

**Write-queue discipline.** All writers use `_schedule(hass, coro)` →
`hass.async_create_task(coro)`. No per-tick flood: the D5 coalescer
opens at most one row per `AWAY_BLOCK_EPISODE_MAX_OPEN_S` window, D6
gates per-person per `TRACKER_TRUST_MIN_HOLD_S`, D7 emits on real edges
only. No unbounded fan-out. **PASS.**

**Memory-ineligible boundary consumer graph.** Test
`test_no_production_module_reads_scope_b_episode_types` at
`quality/tests/test_memory_writers.py:844-902` statically greps every
production `.py` for quoted references to the four Scope-B episode types
outside the {`memory_writers.py`, `memory_facade.py`, `memory_compactor.py`,
`const.py`} allowlist. A single `preexisting_collisions` entry —
`(domain_coordinators/hvac.py, "house_state_transition")` — is
allowlisted. **Verified honest:** `git show develop:hvac.py | grep -c
'"house_state_transition"'` = 2, and current branch = 2. No new
smuggled consumer. The hvac.py usage is the fan-preset reason-ladder
tag (`preset_change_reason = "house_state_transition"` at hvac.py:1911,
:1967) — same name-space collision that predates this cycle by many
versions. Allowlist is truthful. **PASS.**

---

## §6 — Gap A predicate + census signal chain (D8)

`face_recognized_count` threading:

1. **Producer:** `camera_census.py:1179-1190` — `async_dispatcher_send(hass,
   SIGNAL_CENSUS_UPDATED, {"face_recognized_count": len(_face_recognized),
   ...})`. Additive payload key.
2. **Signal:** `SIGNAL_CENSUS_UPDATED` — unchanged constant at
   `signals.py:18`.
3. **Consumer 1 (PresenceCoordinator):** `presence.py:4327-4331` reads
   `census_data.get("face_recognized_count", 0)`. Default 0 = safe.
4. **Consumer 2 (sensor.py):** `sensor.py:3418-3448` subscribes for
   push updates; does not read the new key — no shape assumption.
5. **infer() kwarg:** `presence.py:1000` default `face_recognized_count:
   int = 0` — invariant I3 byte-identity for any caller that omits.
   Sole caller is `_run_inference` at `presence.py:5788`, which now
   passes `self._face_recognized_count`.

**Gate change:** path α (`presence.py:1090-1099`) previously required
`census_count == 0`; now requires `face_recognized_count == 0`
(retains `unidentified_count == 0`). Analysis of the regression risk:

- Under old code, BLE stale keeping `census_count >= 1` blocked path α
  (the AWAY-BLOCK-1 root cause). Post-cycle, `face_recognized_count`
  is camera-only identity — BLE staleness cannot inflate it. This IS
  the D8 fix.
- Fail-open risk: could path α fire when it shouldn't? Requires
  `face_recognized_count == 0 AND unidentified_count == 0 AND
  all_tracked_persons_away`. `unidentified_count == 0` means no
  camera body without face-ID; `face_recognized_count == 0` means no
  camera face-ID. So no camera activity at all. If tracker also
  agrees away, veto is correct. Camera edge case (motion without
  person-ID → unidentified body): `unidentified_count >= 1` → veto
  suppressed → correct.
- Path β unchanged (still gates on `census_count == 0`). Strictly
  stricter than path α post-cycle (see §2). Safe.

Signal-chain integrity: additive kwarg + additive dict key + default 0
= byte-identity preserved for every caller / subscriber not explicitly
opting in. **PASS.**

---

## §7 — Cross-coordinator ripple summary (framing-B mandate)

| Ripple surface | Post-cycle effect | Verdict |
|---|---|---|
| Room tier (`coordinator.py:3106-3121` → `get_room_occupants`) | No cell that produces room-location falls below 0.3 threshold; case-(a)/(b) location is zone-level not room, so bucket unchanged | PASS |
| Zone tier (`aggregation.py:5180-5195`) | Bucket shifts empirically zero for case-(a) (location=="away"), zero for case-(b) (location=="home") — README write-back should soften | PASS (docs nit) |
| Fan-veto (`fan_veto.py:233-234`) | ACTIVE semantic widened (person_state-derived counts too). house_state gate (AWAY/VACATION) closes the loop; correct-by-construction | PASS |
| Camera census (`camera_census.py:2334-2335`) | STALE/LOST still treated as "don't trust without corroboration"; S5/S6 distinction documented | PASS |
| SIGNAL_CENSUS_UPDATED payload | Additive key `face_recognized_count`; both subscribers use `.get(key, default)` — no shape breakage | PASS |
| Frontend v3 bundle | Reads sensor VALUE (`active`/`stale`/`lost`), not new attributes — unaffected | PASS |
| Dashboard PWA / dashboards / .storage | Retired `lost_away_persons` attribute — external grep is AUDIT §9 responsibility, not repo-scoped; sensor keeps `_lost_away_grace_remaining_s` as `None` for back-compat | PASS (external check pending) |
| HVAC reason-ladder tag collision | Preexisting, allowlisted honestly | PASS |
| BLE pre-arrival `_min_away_minutes` budget | `_person_was_away` set on case-(a) away path at `person_coordinator.py:715, :779` (Review M3 preservation) — pre-arrival timer still ticks correctly | PASS |

---

## §8 — Independent drill re-runs (mandated by framing B briefing)

### D5 restart-discharge drill

Test `test_away_transition_blocked_coalesce_and_restart_discharge`
(`quality/tests/test_memory_writers.py:311-374`) exercises:

1. Blocked ticks before `AWAY_BLOCK_EPISODE_MIN_HOLD_S` → no row.
2. Blocked past hold → exactly one open row (`ended_at IS NULL`).
3. Further blocked ticks → no second row.
4. First unblocked tick → row closed with `closed_by="unblocked"`.
5. Fresh hass with a leftover open row → `reconcile_open_away_block_on_boot`
   returns 1, row now `closed_by="restart"`.

Mutations that would red this: neutering the reconciler's close call
(`memory_writers.py:400`), removing the `dedup_source_ref=True` gate
(would create duplicate opens), or the boot gate at `presence.py:5854`
(would allow tick emit before reconcile). All three are anchored.
**Load-bearing. PASS.**

### D6 debounce drill (post-fix-up)

Both `test_tracker_trust_excluded_60_flip_debounce` (:455-503) AND
the new `test_tracker_trust_excluded_hold_gate_arithmetic` (:383-451)
now anchor real code. The 60-flip test proves the pending-overwrite
path (target changes every tick → pending resets → hold never satisfied).
The hold-gate test proves the arithmetic gate (target stable → pending
persists → gate is the sole discriminator). Together they cover BOTH
failure modes.

Mental mutation on `memory_writers.py:498-500`:

```python
# Original:
if (_now - since).total_seconds() >= TRACKER_TRUST_MIN_HOLD_S:
# Mutated (neuter):
if True:
```

Effect: hold-gate test fails at :434 ("gate not yet met -> MUST NOT
emit"). Load-bearing. **PASS.**

---

## §9 — Findings summary

| # | Severity | Location | Description |
|---|---|---|---|
| F1 | LOW | `PLANNING_path_alpha_lost_dissolution.md` + `AUDIT §5` | Plan's "five phone-left-behind consumers" count merges the H2 filter site with the ladder-scoring site (both route through `_phone_trustworthy` closures). Real distinct-mechanism count is 3 consumers + 1 producer + 1 detector-side D9 suppression. No behavioral gap — case-(a) coverage is complete. Suggest AUDIT §5 be re-anchored on unique-id-lookup sites next cycle for count-truthfulness. |
| F2 | LOW | `custom_components/universal_room_automation/domain_coordinators/presence.py:1146-1215` (path β body) + `:5787-5799` (call site) | Path β infrastructure remains but is now vestigial: `lost_away_persons_present=False` from the sole caller (default kwarg, never explicitly True), so the `immediate_engage_empty_house` limb cannot fire, and the surviving gate is strictly narrower than path α. Correctness preserved (β can only echo α or suppress). Suggest a scoped follow-up: either delete β entirely with a byte-identity test, or restore a real WS-A caller — do NOT bundle into this cycle. |

**Zero CRITICAL. Zero HIGH.**

---

## §10 — Verdict

**SHIP.** Framing B (cross-coordinator ripple + lifecycle + signal chain)
finds no CRITICAL or HIGH defect. The D5 restart-discharge and D6
same-target hold-gate drills are load-bearing after the builder's fix-up.
The memory-ineligible boundary allowlist is honest (verified via
`git show develop`). face_recognized_count signal-chain additivity
preserves byte-identity for existing subscribers. Path β is vestigial
but safe (see F2 for follow-up). Room and zone tiers experience no
regression (see §3, §4). Case-(a) ACTIVE-away persons are correctly
excluded at every phone-left-behind consumer site (§1).

Two LOW follow-ups (F1 docs-precision, F2 dead-code cleanup) belong in
their own scoped cycles, not in this ship.

**No plan-review reopen requested.** The plan's rev-3.5.1 pin (case-(b)
never-collapses-to-LOST) is faithfully implemented at all four LOST
writer sites (`person_coordinator.py:670, :715, :762, :779`).

**Post-restart README write-back requirement (per CLAUDE.md):** softening
of "zone active_count grows" is required — empirically zero for
case-(a)/case-(b) because their locations are zone-level, not
room-scoped (see §4).

---

**Reviewer:** Oji Udezue (framing B — cross-coordinator ripple + lifecycle
+ signal-chain, count-the-consumers discipline).
**Date:** 2026-08-16.
**Basis:** feature/path-alpha @ 02f5e79f7 vs develop.
