# Review A: person-awareness read API ship 2 (RA6-RA10), byte-identity + local correctness

Branch `feature/person-awareness-read-api-ship2` @ 1d49aef9, base `release/batch-1` ca133c9d
(`git merge-base release/batch-1 HEAD` = ca133c9d, verified). Diff read three-dot. Card
PERSON-AWARENESS-READ-API-1, plan `docs/planning/PLANNING_person_awareness_read_api.md` ship 2.
Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`.
Identity facts touched: F1 (RA8 trust reads, display + HVAC trust consumers), F2 (RA7 display
readers), F5 (RA10 payload read by security / lock regime (access consumers) and music (display)).

**Verdict: SHIP.** No site differs under the live config. Two LOWs, both documentation/edge.

## Live config (read-only, `.storage`)

- URA integration entry: `data.tracked_persons` = `['Ezinne', 'Oji Udezue', 'Jaya', 'Ziri']`,
  `options.tracked_persons` = `['person.ezinne', 'person.oji_udezue', 'person.jaya', 'person.ziri']`.
- Person registry: `oji_udezue`, `ezinne`, `ziri`, `jaya`, `wall_kiosk`; no whitespace or mixed-prefix names.
- Live unique ids that depend on the key rule: 4 `..._person_<slug>_phone_left_behind`, 4
  `..._person_<slug>_routine_status`, 4 `..._mf_person_follow_person.<slug>` (these embed `person.`).

## Site-by-site

| Site | Old vs new | Live result |
|---|---|---|
| `__init__.py:3145-3151` tracked_persons conversion (written back to `entry.data`) | old: strip `person.` then `_`->space, `.title()`; new `display_of`. `.title()` is case-independent; only whitespace / mid-string `person.` differ | options list -> `['Ezinne','Oji Udezue','Jaya','Ziri']`, equal to the stored `entry.data`; no write change |
| `person_coordinator.py:845, :1019, :1769` (the three `person.person.*` fixes) | `tracked_person_entity_id` keeps a `person.*` entry | coordinator reads `integration_entry.data` (`:204`) = display names, so no entry starts with `person.`: **zero live entries change**. Only an install whose `entry.data` held `person.*` ids would change, and those were broken before (`person.person.x`) |
| `entity_key_slug` (`person_ids.py:66`) at `binary_sensor.py:2154`, `sensor.py:16468`, `switch.py:6638`, `_ble_corroboration.py:40`, `presence.py:5376`, `arrival_edges.py:202, :240` | identical expression `name.lower().replace(' ', '_')` | all 12 live unique ids reproduce. The MF follow ids keep `person.` (`mf_person_follow_person.oji_udezue`); `slug_of` would have orphaned them, so the separate frozen rule is required, not cosmetic |
| `arrival_edges.live_arrival_slug` `:66` | `replace('person.','').lower()` -> `slug_of` | equal for every `person.*` entity id (no whitespace, one dot); non-person ids also equal |
| `.title()` inverses: `notification_manager.py:4766`, `perimeter_alert.py:1780, :5563`, `transit_validator.py:2671`, `music_following._person_key` `:64` | inputs are canonical slugs / `person.*` ids (`leg.canonical_slug`, egress `person_id`) | equal; `guest:x` slugs give `Guest:X` both ways; `casefold(lower(x)) == casefold(x)` for the music key |
| RA6 23 delegates (`camera_census.py:3925-4028`) | each a one-line call/getattr of the private, same args (`_resolve_ble_legs(timestamp, direction)`, `_consume_ble_arriving_legs(slug)`, etc.); counter writers keep the old `+=` / `append` / `hasattr` init; no instance attribute shadows a delegate name (grep) | equal; `canonical_person_slug` (`:3918`) is a pure delegate; `transit_validator.py:2316` keeps its `census_ref is not None` guard |
| RA7 `census_view.house_census_view` (`census_view.py:64`) vs the five old readers (`sensor.py:5231, :5247`, `aggregation.py:6736, :6770`, `binary_sensor.py:1950, :1998, :2217, :2267`) | same fields (`total_persons`, `identified_count`, `unidentified_count`, `confidence`); the int fields are declared `int` (`camera_census.py:314-319`); `FullCensusResult` has no `__bool__`/`__len__`, so old truthiness == new `is None` | equal on a well-formed house; only a malformed house (missing field) now reads None / 0 instead of raising (accounted in README) |
| RA7 deletions: `coordinator.py:1370` dead hook, `presence.py:3223` seed branch | `get_room_identified_persons` and `camera_integration_manager` have no definer/writer (grep) | inert |
| RA8 six loops: `aggregation.py:4766, :4897`, `hvac.py:3417, :3994`, `hvac_fans.py:1530`, `hvac_zones.py:2729` | same predicate `person_state_for_trust(...) == "home"`, list order kept, `first_` short-circuits like the `break`/`return`; `(x or [])` guard moved into the helper (callers already guarded). None of the six old loops applied the phone-left-behind cut (diff), so its absence in `persons_home_for_trust` is correct. `person_state_for_trust` never raises (`person_coordinator.py:141-162`), so the night-trust partial-list-on-exception path cannot be reached | equal; no HVAC decision, write site or ledger row changes (HVAC doc header entry holds) |
| `get_residents_home(zone_persons=None)` | new optional arg; default path unchanged; no caller passes it | equal |
| RA10 `PersonArrivingPayload.from_signal` (`signals.py:946`) in `security.py:2403, :2421`, `security_lock_regime.py:1254`, `music_following.py:561` | dict: same keys and defaults; object: `hasattr(person_entity)` gate (security/music had it; lock regime did not, but an object without the field gave `''` and returned at `if not person`); `source`/`sighting` default None, `zone` default `''` | equal for dict, object, None, and missing fields (pinned by the base-passing parametrised tests) |

## Builder's base-golden claim

Re-run in a detached base worktree (`.claude/worktrees/reviewA-ship2-base` @ ca133c9d) with the
ship-2 test file copied in unchanged: **44 passed, 27 failed** (71 items). The 27 failures are new-API
calls, the two intended `person.*`-entry fixes, the deleted hook test and the AST guard, as the README
says. Every RA7/RA9/RA10 reader golden passes on base. Claim holds in substance.

## Findings

| # | SEV | Where | Finding | Bug class |
|---|---|---|---|---|
| A-L1 | LOW | `docs/readmes/README_person_awareness_read_api_ship2_DRAFT.md:32` | Says "35/35 ... the 27 that fail"; the file has 71 items, 44 pass on base. Fix the count. | Doc/ledger accuracy |
| A-L2 | LOW | `__init__.py:3148` | The display conversion is written back into `entry.data`, so an edge input (leading/trailing whitespace, e.g. options `' person.jaya'`) now persists a stripped name where the old rule persisted the space. Off the live config; the stripped form is the better value. No action needed beyond the README line already present. | Edge-input drift |

No CRITICAL / HIGH / MEDIUM.

## Statistics

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | - | - |
| HIGH | 0 | - | - |
| MEDIUM | 0 | - | - |
| LOW | 2 | 0 | 2 (doc) |

Bug classes: none of #53 / #62 / #63 recur here. The `entity_key_slug` vs `slug_of` split is a
deliberate concept split (#63 handled correctly): the MF follow unique ids prove the two rules differ
on live data. No new QUALITY_CONTEXT class.
