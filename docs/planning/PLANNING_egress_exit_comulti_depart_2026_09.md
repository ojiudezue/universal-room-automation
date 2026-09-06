# PLANNING — Exit identity: name BOTH co-departers (Option 1)

**Card:** EGRESS-EXIT-COMULTI-DEPART-1. **Tier:** 2 (modifies the shipped v5.96.1 exit `person_id` producer — regression-prone; the invariant is "never a wrong WHO"). Accuracy upgrade on step 2/3; after it → step 5 (integration arrangement).

## Core insight (operator 2026-09-06)
Each resident carries their OWN `bluetooth_le` tracker; each loses signal at its own edge. So two people leaving produce **two distinct, self-identifying `not_home` edges** — the WHO is certain per edge. v5.96.1 abstained on co-departure only because it couldn't decide WHICH camera row to bind each to (an assignment problem). But the identity is already solved by the tracker; the row-binding is secondary. **Camera confirms the exit (direction, identity-agnostic, its own 0.3–0.9 confidence); BLE supplies identity (0.72); agreement raises identity confidence** (two axes — the `confidence` column stays direction-confidence per transit_validator.py:1740-1749; identity confidence rides the resolver/attrs).

## Exit naming has THREE paths (operator 2026-09-06) — face is primary, BLE is fallback
Verified in code: the resolver matches FACE legs on EXIT within `[crossing-180s, +30s]` (transit_validator.py:1344, `FACE_MATCH_EXIT_WINDOW_*`), and `_resolve_face_legs` is now fed real-time by the v5.97.0 Frigate face bridge. So:
1. **Face at the crossing → names the exit in REAL-TIME at the +45s resolve, no BLE, no backfill.** A recognized face binds to its OWN crossing directly, so co-departure has NO assignment problem when both faces are seen. This is the PRIMARY exit namer and is ALREADY SHIPPED.
2. **BLE `not_home` edge → backfill (~6min later)** — this card. The FALLBACK for exits with no recognized face (majority today: ~10% garage face hit-rate, back-of-head on exit).
3. **Both agree → higher identity confidence.**
Interaction: whichever names first wins via the `person_id IS NULL` claim. If face already named the row at resolve, the later BLE backfill sees non-null and skips (no conflict); if BLE named it and a face also matched, the resolver's agreement path raises confidence. Option 1's job is strictly to cover the un-faced exits and to name BOTH co-departers there.

## Institutional context verified (prior-art scan)
- **`EgressDirectionTracker`** (transit_validator.py) already writes the exit row with direction + direction-confidence, `person_id=None` — the "exit confirmed" fact. UNCHANGED; the camera alone confirms the exit.
- **`_backfill_exit_identity`** (camera_census.py, v5.96.1) — the async edge handler. Reuse its: TZ-naive bound derivation, `find_unnamed_exit_crossings` SELECT, `backfill_entry_exit_person_id` UPDATE (`WHERE id=? AND person_id IS NULL` — the single-use claim), the flap-settle re-read, the sentinel-name filter, the person-not_home veto. RELAX: the abstain-on-multiple + competing-edge + deferred-window-close distinct-departer machinery (that existed to prevent a wrong WHO — now unnecessary because each edge IS a certain WHO).
- **DAO** find_unnamed_exit_crossings / backfill_entry_exit_person_id — reuse as-is (the IS-NULL guard is the per-row claim that makes two edges fill two distinct rows).

## Falsifiable invariant
> For each admissible BLE `not_home` edge (resident R's own tracker, past the flap-settle + sentinel + not_home-veto identity guards), R is recorded as departed by claiming exactly one nearest unconsumed NULL exit row and backfilling `person_id=R`. Two co-departers → two edges → two distinct rows, BOTH named R_A / R_B. (a) The set of names attached in a window equals the set of residents whose trackers went not_home — never a name of a resident who did NOT depart (right-WHO always); (b) each edge consumes at most one row (IS-NULL claim); (c) row-BINDING is best-effort (a swap of which row A vs B lands on is permitted — the SET is correct); (d) all v5.96.1 identity-validity guards (flap, sentinel, veto) still hold.

Falsified by: a name attached for a resident who did not go not_home; one edge consuming ≥2 rows; a co-departure leaving a row NULL when a distinct null row was available; a sentinel/flap/vetoed name attaching.

## D1 — relax the abstain; retry-claim per edge; RETAIN the settle (rev2, plan-review fixes)
In `_backfill_exit_identity`:
- **RETAIN the settle wait (F2 — CRITICAL):** the flap re-read is deliberately downstream of the one `asyncio.sleep`. Remove ONLY the window-length *deferral* (`r_ts + WINDOW`) and the distinct-departer scan; REINSTATE a FIXED settle before the re-read using the existing `BLE_EXIT_DEPARTURE_SETTLE_S = 90` (const.py:2283). New ordering: **settle sleep (honor the `_exit_settle_s` test override) → live tracker re-read flap-abort → SELECT/claim.** Deleting the sleep is forbidden — it voids the flap guard and opens a wrong-WHO path (a BLE drop while home naming someone else's crossing).
- **REMOVE:** the `len(rows) > 1` abstain, the competing-edge abstain, and the distinct-departer scan (their purpose — preventing a wrong WHO via assignment — is dissolved because each edge carries its own certain slug).
- **KEEP (the real BLE-path guards, F4 corrected):** the derived tracker→slug map lookup (`_ble_tracker_slug_map`, camera_census.py:4157 — the edge's OWN person, never inferred from the row), the `tracked_persons` INV-EGRESS-ID check (:4161-4172), the **per-slug cooldown** `BLE_EXIT_PER_SLUG_COOLDOWN_S` (:4213-4224 — F3; without it a phone+watch resident double-claims), and the retained tracker flap-settle. (Sentinel filter + not_home veto are FACE-path only — they do NOT run here; do not claim them.)
- **Retry-claim loop (F1 — CRITICAL, this is also Case-1 co-departure reconciliation):** the SQL `IS NULL` guard prevents a double-WRITE, NOT a double-CLAIM — two concurrent edges both SELECT the same nearest row, A writes, B gets `changed==0`. So on `ok is False`, do NOT return — RE-SELECT and claim the NEXT unconsumed null row, bounded by `BLE_EXIT_CLAIM_MAX_ATTEMPTS: Final = 3` (const.py, module rung). Exit the loop on a successful claim (invariant b: one row per edge) or when the re-SELECT is empty (`_ble_exit_edge_no_match_count`). `LIMIT 2` in the DAO stays valid ONLY because we re-SELECT after each write (post-A the remaining row becomes rows[0]); do NOT pre-fetch an N-row list against `LIMIT 2`.
- **Case-2 disagreement (operator question 2026-09-06; adjudicated keep-face+flag+measure, reversible):** if the retry loop exhausts with NO claimable null row AND a face-named row in the window carries a DIFFERENT slug than this edge (genuine same-row conflict, this slug has no own crossing): do NOT overwrite the committed face name (real-time, at the door) and do NOT silently drop — increment `_ble_exit_face_disagree_count` and record the dispute (attr), so we can measure the disagreement rate before choosing a precedence policy. (Alternative on file: BLE-wins-overwrite, matching the resolver's existing BLE-over-disagreeing-resident-face precedence — deferred pending the disagreement data + operator confirm.)

## D1b — retired/inverted tests (F5)
- `test_exit_backfill_abstains_when_multiple_candidate_rows` (:304) → INVERT to "two candidate rows + two edges → BOTH named their own slug".
- `test_exit_backfill_abstains_on_competing_departing_edge` (:324) → INVERT to "both competing edges named with their own slugs".
- `test_exit_backfill_defers_and_abstains_on_late_competing_edge` (:599) → DELETE (the deferral is gone).
- PRESERVE the `_exit_settle_s` override contract (tests :373/:441/:505/:620) against the re-based fixed settle.

## D1c — supersession triage (F6/F7)
- `_ble_exit_recent_departing_edges` deque + prune (:1407, :4227-4237) and `BLE_EXIT_DECISION_MARGIN_S` (const.py:2287): DELETE (only the distinct-departer scan / deferral used them) — verify no other reader.
- Counter key `ble_exit_ambiguity_abstain_count` (sensor.py:3828): KEEP the attribute key stable (shipwatch history), REDEFINE to identity-invalid-only; ADD `ble_exit_row_contention_retry_count` (F1 retries) + `ble_exit_face_disagree_count` (Case-2) as new surfaces.
- Drop plan line 13's "resolver agreement raises confidence on a BLE-named row" — no row-level path (face INSERTs, backfill refuses the confidence column). Face/BLE agreement confidence lives only in the resolver's in-memory attrs at resolve time, not on a backfilled row.

## D2 — observability + acceptance discriminator


Keep the exit counters; the discriminating live check: a co-departure produces TWO named exit rows (not one named + one null, and not a wrong-WHO). Surface last-two-attached for validation.

## Non-goals
- Precise per-row binding under bunched co-departure (best-effort; set-correctness is the guarantee). Option 2 (bipartite) / Option 3 (order-pairing) parked if row-precision is later needed.
- Face exit naming is NOT built here — it is ALREADY SHIPPED (v5.97.0 bridge + the resolver's exit face window). This card builds ONLY the BLE fallback for un-faced exits; the two coexist via the IS-NULL claim.

## Tier-2 review framings (framing-disjoint)
- A correctness: each edge names its own slug; nearest-unconsumed claim; IS-NULL prevents double-claim; guards intact.
- B lifecycle: removing the deferred wait doesn't leak/regress the task tracking or teardown; no double-fire; restart.
- **D adversarial — the one that matters: can a resident who did NOT depart ever get named?** (right-WHO invariant). Probe: a flap that survives settle, a stale latch... no — this is BLE not_home edges; probe a tracker that goes not_home for a NON-departure reason (BLE drop while home) → must be caught by the flap-settle re-read + not_home veto. And confirm removing the abstain didn't open a wrong-WHO path (it shouldn't — each edge is its own tracker).
- C test-authority: RED-on-neuter for {two-edges→two-named-rows, each-edge-own-slug, IS-NULL single claim, flap still aborts, sentinel still drops, veto still holds}.

## Acceptance criteria
- **Test:** two co-departure edges → two distinct rows each named its own resident (the headline anchor); a single departer still names one; a flap/sentinel/vetoed name never attaches. Each RED-on-neuter.
- **Live:** a real couple leaving together → BOTH exit rows carry the correct `person_id` (not one-null); a resident whose tracker flaps not_home while home is NOT recorded as departed.
