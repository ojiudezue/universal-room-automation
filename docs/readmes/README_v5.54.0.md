# v5.54.0 — Census Cutover to CameraResolver (golden-master gated)

Flips CENSUS_USE_NEW_RESOLVER=True after the golden-master diff artifact
(docs/planning/GOLDEN_MASTER_census_cutover_diff.md §§1-10) reached GO:
24 rows compared, 21 identical, 3 differing — all resolver-CORRECT
(staircase legacy mis-stem fixed ×2, F1 filter exclusion), 3 egress
UniFi blockers (~305 events/wk) resolved, platform_differing=0, no
base+`_2` duplicate rows.

Fixes shipped with the flip: bidirectional camera-stem index with
both-order `_N`/person-suffix normalization (live F2 shape
`*_person_occupancy_2` collapses correctly); evidence-gated `_N`
disambiguation (no cross-camera over-fusion); disabled-entity skip;
cached resolver invalidated on registry-updated events (no per-read
registry walks); entity→device area_id fallback matching legacy;
platform-hint preference (unifiprotect over co-resident platforms);
resolver-crash visibility counter; probe metric hardened
(platform_differing in the verdict line).

Reviews: 3 framing-disjoint (A ladder / B blast-radius / C
test-authority incl. independent probe re-run reproducing §9 byte-tight
+ 2 silent-green sites found and anchored). Fix-up mutation ledger 5
sites red; orchestrator personally re-verified the `_2`-collapse fix
red/green. Fire axe: revert the single flip commit (census path only;
D3/D5 resolver consumers unaffected).

## Live Validation (prospective)
- **Live:** census values (interior + egress transit) within expected
  ranges post-restart; no census-derived alerts fire spuriously in the
  first hour.
- **Live:** egress transit entities include the 3 UniFi legs (spot-check
  get_transit_egress_entities via debug or first organic egress event).
- **Live:** no resolver-crash counter increments; zero URA ERROR lines.
- **Live:** presence census_count parity with the PC People Home sensor
  maintained across the flip.

## Validated 2026-08-06 post-restart
v5.54.0 live on HA; zero URA ERROR lines; census values sane post-restart (People Home=2 pre-restart parity held); resolver-crash counter silent. Organic criteria
(first egress event legs / first deep-night vehicle, seam counters)
ride the next natural events — morning sweep checks.
