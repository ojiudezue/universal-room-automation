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

## D1 — relax the abstain, claim per edge
In `_backfill_exit_identity`:
- REMOVE: the `len(rows) > 1` abstain, the competing-edge abstain, and the deferred distinct-departer wait/count (their sole purpose was preventing a wrong WHO via assignment — dissolved).
- KEEP: flap-settle (re-read tracker still-away), sentinel-name filter, person-not_home veto, the TZ contract, the IS-NULL single-use claim.
- Each edge (identity = its own slug, certain): after settle+guards, `find_unnamed_exit_crossings(window)` → claim the NEAREST unconsumed null exit row (`ORDER BY timestamp DESC, id DESC LIMIT 1`) → `backfill_entry_exit_person_id(row_id, slug)`. The IS-NULL guard guarantees two concurrent edges never claim the same row; edge order determines best-effort binding. No abstain on multiplicity.
- Counters: `_ble_exit_ambiguity_abstain_count` now increments only on genuine identity-invalid (sentinel/veto/flap) — repurpose/rename or keep; add `_ble_exit_codepart_named_count` if useful.

## D2 — observability + acceptance discriminator
Keep the exit counters; the discriminating live check: a co-departure produces TWO named exit rows (not one named + one null, and not a wrong-WHO). Surface last-two-attached for validation.

## Non-goals
- Precise per-row binding under bunched co-departure (best-effort; set-correctness is the guarantee). Option 2 (bipartite) / Option 3 (order-pairing) parked if row-precision is later needed.
- Face-based exit naming (BLE is the exit signal; face corroborates via the shipped bridge).

## Tier-2 review framings (framing-disjoint)
- A correctness: each edge names its own slug; nearest-unconsumed claim; IS-NULL prevents double-claim; guards intact.
- B lifecycle: removing the deferred wait doesn't leak/regress the task tracking or teardown; no double-fire; restart.
- **D adversarial — the one that matters: can a resident who did NOT depart ever get named?** (right-WHO invariant). Probe: a flap that survives settle, a stale latch... no — this is BLE not_home edges; probe a tracker that goes not_home for a NON-departure reason (BLE drop while home) → must be caught by the flap-settle re-read + not_home veto. And confirm removing the abstain didn't open a wrong-WHO path (it shouldn't — each edge is its own tracker).
- C test-authority: RED-on-neuter for {two-edges→two-named-rows, each-edge-own-slug, IS-NULL single claim, flap still aborts, sentinel still drops, veto still holds}.

## Acceptance criteria
- **Test:** two co-departure edges → two distinct rows each named its own resident (the headline anchor); a single departer still names one; a flap/sentinel/vetoed name never attaches. Each RED-on-neuter.
- **Live:** a real couple leaving together → BOTH exit rows carry the correct `person_id` (not one-null); a resident whose tracker flaps not_home while home is NOT recorded as departed.
