# Review A: scoped egress mute (PERIMETER-GLOBAL-EGRESS-MUTE-1)

Framing A: local correctness and security invariants. Branch `feature/perimeter-egress-mute-scoped`, HEAD 9e7af15e,
base `git merge-base develop HEAD` = 1eb0308b (verified; three-dot diff). Identity model: this cycle CONSUMES F3
(door crossing + identity attach, `ura_person_egress_event`) in a security-silence consumer, so the >= 0.9 floor
applies. Manual consulted: `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`. Targeted tests:
`test_perimeter_egress_mute_scoped.py` + `test_exterior_seam_mute_covers.py` = 64 passed. Live evidence via the
Samba mount (config entries, entity registry, `exterior_seams.json`) and `memory_episodes` over 14 days.

## Findings

| # | SEV | Site | Finding | Class |
|---|---|---|---|---|
| A1 | MEDIUM | `exterior_track_linker.py:534-541` | A REJECTED seam file returns early and never touches `egress_mute_covers` or `mute_covers_source`. After a valid map is loaded, an invalid edit followed by the reload button keeps the OLD map live and muting, while `seam_validation` says "rejected" and `mute_covers_source` still says "loaded". The plan's INV-MUTE-FAILOPEN says an invalid map means no mute. Repro: load a valid file covering g5_bullet from garage_a, edit it so one covered name is a typo, press reload: the edit is rejected and g5_bullet keeps being muted under the old map. This mutes known-resident windows only, not strangers specifically, so it is not HIGH. Fix: clear covers and set the source to "rejected (no egress mute)" in the reject branch (and the path-resolve failure branch at :504-508), plus a valid-then-invalid reload test. | #53 one-missed-site (fail-open applied on 2 of 3 load outcomes) |
| A2 | MEDIUM | `perimeter_alert.py:5258-5352` (veto at decision time) | The veto is not retroactive. Crossing records land about 45 s after detection (`ENTRY_WINDOW_SECONDS` delay in transit_validator), so a stranger's crossing is invisible for its first ~45 s. Repro: Oji exits garage_a at t=0 (exit, 0.92, record at t=45). A stranger passes garage_a at t=60 (record due at t=105) and reaches g5_bullet at t=75: crossings in window = Oji's only, the edge is muted. When the stranger's veto record lands at t=105, nothing re-raises the muted edge. This is bounded like the plan's stated residual ("a stranger who never crosses a door", window plus episode cap, covered cameras only), but the plan presents the veto as protecting this case, and it does not for its first 45 s. Fix one of: (a) state it as a residual in the plan and README, or (b) on a failing crossing landing, alert for any edge that camera muted inside that crossing's window (one gate-row lookup). Operator's "A. Alert now" favours (b). | Ordering seam (veto evaluated before its producer lands) |
| A3 | MEDIUM | `perimeter_alert.py:5216-5221` `_door_key_for`; wiring :809-835 | The name-based fallback `_egress_key` is silent: no log, no counter, no diagnostic. For the live cameras it does hit: perimeter's map is built from same-device legs (`resolve_camera_entity`), while transit fires from cross-platform legs (`resolve_cross_platform_sensors`). Live 14-day rows show crossings from `binary_sensor.{madrone_g6_entry,doorbell_lite,front_door_aerial,garage_a}_person_detected` (Protect device, not in the map). Those happen to strip to the same key, so there is no split today. Any leg whose stem does not strip to the door key splits the door: a `sensor.*` leg that is not in the map keys under its raw entity id (the builder's own `test_egress_memory_count_sensor_without_map_is_not_garage_a` proves this), and a zone leg such as `..._package_person_occupancy_2` would key as `madrone_g6_entry_package`. An unknown crossing under a split key cannot veto. Fix: count fallback hits by entity in `egress_mute_stats`, and log once at INFO per entity. Better: build the map from `census.get_transit_egress_entities()` (the producer's own leg set) so every leg the producer can emit is mapped. Not HIGH because no live leg splits today (verified against the registry and live rows). | Registry-not-names (REGISTRY-NOT-NAMES-1) / silent fallback |
| A4 | LOW | `perimeter_alert.py:5545-5549` | Not byte-identical for D10.5: count-sensor crossings used to key under the raw `sensor.*` id (unreachable by D10.5); they now map to the door key, so D10.5 can see more identities. Unknown entries also share the 16-entry cap. No dual-role cameras are live (perimeter ∩ egress = empty), so there is no live effect. Note it in the README. | Byte-identity |
| A5 | LOW | `exterior_seams.py:305-325` | Covered cameras are checked only against `known_cameras` (perimeter ∪ egress), not perimeter-only as plan D2 says. An egress camera listed as covered is harmless because egress edges do not take the perimeter-only branch. Tighten it or reword the plan. | Plan-vs-code drift |
| A6 | LOW | `perimeter_alert.py:1439` | Dual-role branch with `EGRESS_MUTE_WINDOW_S=0` still mutes at age exactly 0.0 (`<=`), while the knob says "0 = never mute". Add `window > 0 and`. | Kill-switch semantics |
| A7 | LOW | zero-fire trip-wire :5416-5435 | Crossings on uncovered doors (garage_b, doorbell_lite as a door) count toward the >= 5 crossings. A quiet day with no covered-camera edge near a crossing can page "mute never ran". Count only covering-door crossings. | Trip-wire false positive |

## Cleared (holds because)

- **Qualifying rules** (:5288-5301): direction must be entry/exit (ambiguous vetoes; that is 50% of live rows, the safe direction). pid must be in `tracked_persons` (lowercased; residents only: ezinne, oji_udezue, jaya, ziri; producer emits URA slugs via `_canonical_person_slug`). conf < floor vetoes. Synthetic vetoes. Floor = `max(0.9, const)`: below 0.9 clamps up, above 1.0 kills because identity conf <= 1.
- **Veto over every covering door** (:5276-5281, :5346): crossings are collected from ALL doors listing the camera, and any failing one returns False before qualifying is consulted.
- **Window arithmetic**: `0 <= age <= window` on both crossings and stamps; future-dated entries are excluded. Naive or aware mismatch raises inside the try, so it fails open.
- **Episode/cap**: reset on `last` older than RESET_S; cap on `start` older than MAX_EPISODE_S; a fresh crossing never moves `start`. Longest continuous silence = cap (300 s), then at least RESET_S (120 s) of declines before a new episode. `cap <= 0` kills. Episodes are per camera key.
- **INV-EGRESS-SELF**: dual-role cameras take the unchanged stamp branch, and `elif` keeps them out of the scoped mute.
- **Fail-open**: `_egress_mute_decision` catches everything and returns False. `_mute_covers` catches and returns {}. Census failure leaves residents empty, so every crossing vetoes. Setup clears memory and episodes.
- **Current live file** has no `egress_mute_covers` (keys verified): covers = {}, every perimeter-only edge alerts, no decline rows, and the zero-fire wire returns early on the empty map (no page). The global `_last_egress_time` is now read only inside `_egress_stamp_for` for dual-role cameras.
- **Map isolation**: `egress_mute_covers` is read only by `perimeter_alert._mute_covers` and the diagnostic. The adjacency graph, linking, burst-demote and circling never reference it (grep).
- **Gate row**: `suppressed` is passed through the optional-key loop; `demoted: False`, `would_demote: False`, and the reason distinguishes mute from decline. The weekly scorer (`scripts/probes/perimeter_gate_scorer_weekly.py:46-54`) keys on (camera, gate, reason, daypart), so egress_mute rows get their own lines with demoted=0 and no existing count shifts. It does not print `suppressed`, but the reason carries the same information.
- **Validator**: reject-whole-file works (errors bubble up through `_validate` raise). Covers absent = []. Self-cover, non-egress door, empty list, non-object and unknown names are all rejected (tests at `test_exterior_seam_mute_covers.py:54-92`).

## Statistics

| Severity | Found | Must-fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 3 | 3 (A1, A2 as decision+doc or code, A3 counter) |
| LOW | 4 | fix in-cycle (A4 doc, A5-A7 small) |

Bug classes: #53 one-missed-site (A1), ordering seam / producer latency (A2), registry-not-names silent fallback
(A3), byte-identity (A4), kill-switch semantics (A6), trip-wire false positive (A7).

## Invariant checklist

- INV-MUTE-KNOWN: HOLDS for the stated conditions at decision time. Residual A2: a stranger's crossing that lands after the edge cannot veto retroactively.
- INV-MUTE-FAILOPEN: LEAK on the reject-after-valid reload (A1); holds on absent, exception, no census, setup.
- INV-EGRESS-SELF: PASS.
- D10.5 byte-identity: PASS for live config (no dual-role); semantic delta noted (A4).
- Map isolation: PASS.

**Verdict: FIX-REQUIRED (MEDIUM only, no HIGH).** Must-fix: A1 (clear covers on reject, plus test); A2 (operator
decision: retroactive alert, or a stated residual in plan and README); A3 (fallback counter and log). LOWs A4-A7
in the same fix-up.
