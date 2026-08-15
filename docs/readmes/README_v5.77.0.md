# URA v5.77.0 — Reload-Suppress (integration entry) + Opt-Meta Boot Fix + Census Count Restore

Three plan-reviewed/root-caused fixes, one deploy. Config rider at restart: zone-camera person-only swap.

## RELOAD-WATCHDOG-HAZARD (Tier 2-DB: plan review ×2 + 3 reviews + 3-part fix-up)
A `camera_person_entities` options save on the INTEGRATION entry no longer full-reloads ~40 child
entries (the 2026-08-07 ~5-min watchdog-outage class). Suppress branch mirrors the shipped CM
pattern (sibling helper; `_apply_in_place` byte-identical); snapshot seeded at setup (the
cross-confirmed blocker: first post-restart save no longer sees `old={}`); v1 allowlist =
`{camera_person_entities}` ONLY (D1 classified every integration options key; perimeter/egress
keys deliberately still reload — perimeter_alert caches its subscriptions). Suppressed saves
dispatch `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` (transit_validator re-reads fresh). Kill switch
`INTEGRATION_RELOAD_SUPPRESS_ENABLED=False` (skips suppress AND dispatch). Test posture: AST
live-Call-node anchor on the setup seed (grep anchors proven comment-evadable — hollow-anchor
variant #7 coined this cycle); AST-slice loaders gained an undefined-Name guard.

## OPT-META-BOOT-TRANSIENT-1 (Tier 1)
The optimizer's false "cannot see underlying problems" HIGH after every restart is closed:
the LLM meta corpus falls back to a boot-time DB seed when the RAM findings cache is empty;
seed cleared after the first real cycle (no stale re-injection); WARNING when the seed
pre-fetch itself comes up empty.

## CENSUS-SUFFIX-FIX-1 (Tier 2, root-caused regression)
Census counting restored after the F1 retirement: all matchers now strip the `_N`
disambiguation suffix before suffix-matching, so the F2 `_2` count sensors and person
binaries map again (they matched NOTHING since 08-13 — census pinned at identified count,
daily max collapsed 6-7 → 4). Canonical-wins ambiguity guard with WARNING; real entity_ids
stored. 25 consumers enumerated (Review B): no threshold consumer step-fires on the 4→N
restart jump.

## GARAGE... (rider) ZONE-CAM-PERSON-SWAP
At this restart: Back Hallway `staircase_all_occupancy` → `staircase_person_occupancy`;
Upstairs `upstairs_hall_all_occupancy` → `upstairs_hall_person_occupancy_2`,
`playroom_all_occupancy_2` → `playroom_person_occupancy_2` (all-objects sensors were
polluting zone camera-confirmation; device_class identical so only label scope discriminates).

## Acceptance criteria
- **Test:** test_reload_watchdog_hazard (14) + test_opt_meta_boot_transient (6) +
  test_census_suffix_disambiguation (5+) ; suite 24 pre-existing failures, 0 net-new.
- **Live L1:** boot clean, zero URA ERROR lines.
- **Live L2 (census):** `sensor.ura_presence_coordinator_people_home_census` exceeds 4 within
  one census cycle+hold while the gathering is in the house; census confidence leaves
  single_source when both platforms contribute.
- **Live L3 (opt-meta):** NO "cannot see underlying problems" meta finding in the first
  post-boot optimizer cycle (boot seed populated, logged).
- **Live L4 (reload):** next camera-census options save → zero entry reloads, transit signal
  dispatched (log line), no watchdog. (Organic or operator-triggered.)
- **Live L5 (rider):** zone entries show person-only sensors post-boot.

## Live Validation

### Validated 2026-08-15 (v5.77.0 boot, ~16:28 CDT)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Boot clean, zero URA errors | **PASS** | system_log ERROR x universal_room: 0 entries post-boot |
| L2 | Census exceeds 4 with gathering present | **ORGANIC (open)** | Post-boot readings: 0 (boot transient) -> 4; no census-camera traversal yet since restart. Counting path proven: detectors read 6 (family room) this afternoon pre-deploy; suffix mapping drill-anchored in-suite. PASS = first recorder reading >4. UPDATE 2026-08-15 eve: gathering departed before a >4 traversal registered; proof redefined — interim: any unidentified contribution (identified+1 on a visitor), full: next gathering. |
| L3 | No false optimizer meta-alert on first post-boot cycle | **PASS** | First meta finding post-boot (21:33Z) = `cycle_ok` LOW only — the restart scenario that previously emitted the false "cannot see problems" HIGH is clean |
| L4 | Camera-census save -> zero reloads + transit dispatch | **ORGANIC (open)** | Next options save on the integration entry (organic or operator-triggered) |
| L5 | Zone-camera person-only swap | **FAILED THIS BOOT — rider bug, fixed + re-staged** | Swap script crashed on nested zones dicts (flat scan; `unhashable type`); config unchanged. Script rewritten (recursive walk), DRY-RUN VERIFIED against live file (exactly 2 zone edits found), re-staged for next restart. No regression — prior config simply persists one more interval. |

