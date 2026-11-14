# AUDIT: perimeter FP gates D3 / D5 disposal (read-only, 2026-11-14 02:10 CST)

Card PERIMETER-FP-GATES-DISPOSE-1. Deployed = develop = v5.108.21 (`ha-config/custom_components/.../manifest.json`).
Verdict: D3 = NOT EVALUATING (never configured), RETUNE-then-enable path needs 1 operator config step. D5 = ALREADY
ENFORCING (the 11-12 "shadow/learning" finding is stale), but only on g5_bullet. Persistence EXISTS (no new code).

## 1. Verify-before-work (each prior finding vs today)
| Prior finding (11-12) | Today | Evidence |
|---|---|---|
| D3 never evaluates; zone sensors never configured | TRUE. `perimeter_zone_sensors` is absent from the URA entry options (full key list dumped) | `core.config_entries` options keys for title "Universal Room Automation" (python dump, 02:05 CST). Code: `_build_zone_map` returns at `perimeter_alert.py:4455` when empty; D3 returns at `:4871-4872` (`if not zones: return`, "unzoned camera: no record") |
| D3 switch off | TRUE (key `perimeter_zone_agreement_demote` absent -> `DEFAULT_..=False`, const.py:2628) | same dump |
| D5 is shadow / learning | STALE. `perimeter_single_source_demote: True` in live options = ENFORCING | same dump; gate reads it fresh at `perimeter_alert.py:4937-4940` |
| gate_decisions_by_camera `{}`, zone_map `{}` | `{}` at last observation 11-13 19:57 CST (AUDIT_perimeter_silence_post_v5_108_20.md:12); I could not re-read the live attribute (diag sensor is not in `core.restore_state`, no HA token). zone_map `{}` is implied by empty config | restore_state grep; unknown for the live instant |
| D5 settle 8 s < camera lag | TRUE, see section 3 (`const.py:2636`) | probe below |
| ~2,295 CRIT + 1,754 HIGH / 30 d | ~same shape: 15 Oct -> 14 Nov 1,983 CRITICAL, 1,682 HIGH, 27 MEDIUM, 10 LOW | SQL A below |
| no would_demote counts persisted | STALE. Persistence shipped 11-13 14:50 CST (`ea30b31a`, v5.108.20): `_record_gate` -> `_persist_gate_decision` writes `memory_episodes` rows (`perimeter_alert.py:4646`, `:4688-4740`; `const.py:2657-2658`, `PERIMETER_GATE_LOG_PERSIST=True`). Live row count = **0** today | SQL B below; zero is expected: the writer is downstream of the egress-mute check and no non-muted edge has occurred since install (silence audit :4-9, :35-36). Zero-fire is therefore unproven-live, not proven-broken |
| no disposal date | still none | this doc proposes one (section 5) |

SQL A (`ssh ha sqlite3 -readonly .../universal_room_automation.db`):
`select severity,count(*) from notification_log where hazard_type like '%exterior_person%' and timestamp>'2026-10-15' group by 1;`
-> CRITICAL 1983, HIGH 1682, LOW 10, MEDIUM 27.
SQL B: `select min(started_at),max(started_at),count(*) from memory_episodes where episode_type='perimeter_gate_decision';` -> `||0`.

D5 live effect so far: the only LOW `exterior_person` rows outside DND/force-immediate hot_tub/pool/back_yard ones are two
daytime g5_bullet rows (2026-11-13 18:42Z and 22:42Z, `route_reason=enriched_llmvision`), consistent with two D5 demotes
(daylight-only, first-alert, g5_bullet). Inference only: the gate rows did not exist yet, so not provable. Net D5 effect to date
~2 demotes versus ~3,700 pages: it is not the lever for the volume problem.

D5 eligibility today (`perimeter_agreement` store, `.storage/`, mtime 11-13 18:27; rate = true/len):
g5_bullet 0.66 over 47 (ELIGIBLE: >= 0.6 and >= 20, `const.py:2637-2638`), rear_ptz 0.44/36 (no), utilities_ptz 0.79/14 (<20 samples),
pool_equipment 0.56/9, hot_tub 1.0/9, front_side_ptz 1.0/5, back_yard 0.0/4. So **only g5_bullet** can ever be demoted by D5.
Note the stored g5 rate (0.66) is below the README probe (0.82) and the 30-day recorder probe (0.81): a different pairing window.

## 2. What D3 needs (per camera)
Options-flow key (single field, Camera Census step, Advanced): `perimeter_zone_sensors` (`const.py:2596`, `config_flow.py:5164-5165`)
= list of `binary_sensor.*` Frigate zone person sensors. Mapping rule (`perimeter_alert.py:4438-4530`): zone stem must start with
`<camera stem>_` for exactly one configured perimeter camera; non-matching -> WARN, not subscribed. Separate gate toggle:
`perimeter_zone_agreement_demote` (switch `switch.ura_perimeter_zone_agreement_demote`).

Registry resolution (`core.entity_registry` platform + device name, not names): the `*_property_person_occupancy` sensors are
platform `frigate`, unique_id `01KM239Z8ZQWQTN1D9CV5JRA7V:occupancy_sensor:<cam>_property_person`, devices "<Camera> Property", none disabled:
| camera (in `perimeter_cameras`?) | zone sensor to fill |
|---|---|
| g5_bullet (yes) | `binary_sensor.g5_bullet_property_person_occupancy` |
| rear_ptz (yes, as `_high_resolution_channel`) | `binary_sensor.rear_ptz_property_person_occupancy` |
| utilities_ptz (yes) | `binary_sensor.utilities_ptz_property_person_occupancy` |
| front_side_ptz (yes) | `binary_sensor.front_side_ptz_property_person_occupancy` |
| madrone_g6_entry / doorbell_lite / front_door_aerial | `..._property_person_occupancy` exist, but these are only in `egress_cameras`, NOT `perimeter_cameras` (dual-role D10 not configured), so a zone sensor would not alert-gate them |
| hot_tub, pool_equipment, back_yard, garage_b, armcrest, madroneptultra, sonoffwindow, reolinkstudybporch | no property zone entity registered: D1/D3 cannot cover them |
Unverifiable from here: that Frigate's `property` zone polygon actually excludes the street (Frigate config not read). Operator
must confirm before relying on D3. Also `property_all/car/dog/cat` variants exist; only `*_person_*` is correct.
Side effect to know: D1 swaps the camera's whole-frame Frigate leg for the zone sensor, which is itself the strongest street-noise
lever (street people never fire the zone leg), independent of the D3 demote switch.

## 3. D5 settle: lag distribution
Command: `ssh ha "python3 -" < scripts/probe_perimeter_engine_lag.py` (recorder, 30 d, second-engine lag after first, +-60 s pairing), run 02:08 CST:
| cam | agreement | p50 s | p90 s | | cam | agreement | p50 | p90 |
|---|---|---|---|---|---|---|---|---|
| g5_bullet | 0.81 | 1.1 | 10.2 | | rear_ptz | 0.51 | 3.7 | 8.5 |
| utilities_ptz | 0.84 | 8.7 | 20.4 | | front_side_ptz | 0.88 | 3.9 | 26.3 |
| doorbell_lite | 0.89 | 1.3 | 23.5 | | madrone_g6_entry | 0.61 | 3.1 | 22.4 |
| front_door_aerial | 0.88 | 1.5 | 23.1 | | pool_equipment | 0.44 | 2.5 | 52.0 |
| garage_a | 0.84 | 1.6 | 10.6 | | hot_tub / back_yard | 0.47 / 0.0 | 2.7 / - | 5.6 / - |
Recommendation: knob = existing `PERIMETER_SS_SETTLE_S` (`const.py:2636`, rung 1 module constant; fitted-from-measurement, so
review-gated is right). Since g5_bullet is the only eligible camera and its p90 is 10.2 s: set **12** (p90 rounded up, same rule
as the plan, `PLANNING_perimeter_fp_build_2026_11.md:396`). 8 s today covers ~p80 (g5) so ~1 in 5 demotes may wrongly fire on a
real single-engine-late event. Caveat: operator rule "waits ship at 0" (memory alert_latency_over_precision) argues for settle 0
(lookback only); with 12 s the demoted-or-not decision only delays pages in the daylight, first-alert, g5-only case. Do not raise
the cap for door cameras (D10.5 has its own 20 s, `const.py:2721`).

## 4. Are shadow decisions logged already?
YES, no new code for counting. Two surfaces:
1. `memory_episodes` rows, `episode_type='perimeter_gate_decision'`, `node_id='perimeter_gate:<cam>'`, `attrs_json` has `gate`,
   `reason`, `would_demote`, `demoted`, `enforce`, `severity_before/after`, `is_day`, `inputs` (`perimeter_alert.py:4693-4710`). Count query:
   `select json_extract(attrs_json,'$.gate'),json_extract(attrs_json,'$.reason'),count(*),sum(json_extract(attrs_json,'$.would_demote')) from memory_episodes where episode_type='perimeter_gate_decision' group by 1,2;`
2. In-memory `gate_decisions_by_camera` (latest per gate/camera only, `:4642`, `:4752`).
Gap: D3 records nothing for unzoned cameras (`:4870-4872`), so D3 counts can only start after step 2 config. Rows exist only from
install on 11-13 ~20:00 CST and only for non-egress-muted edges; the first real data point is pending (0 rows now). If the
disposal wants day-0 numbers, the 2 LOW g5 rows above are the only retroactive evidence. A would_demote replay from `notification_log`
for D3 is impossible (no zone data), so no code can backfill it.
No code change recommended. (If a trip-wire is wanted: a zero-fire anomaly on `perimeter_gate_decision` after N alerts is a new
anomaly producer, Tier 1-2, `perimeter_alert.py` near `_record_gate:4635`; not needed for disposal.)

## 5. Disposal recommendation (one-shot)
| gate | verdict | evidence / action |
|---|---|---|
| D3 zone agreement | **RETUNE-then-enable** (blocked on config, not code) | Step 1: operator sets `perimeter_zone_sensors` to the 4 perimeter-listed `*_property_person_occupancy` ids in section 2 (this alone also enables D1 street rejection) and confirms the Frigate `property` zone excludes the road. Step 2: with D3 switch still off, count `zone_agreement` rows where `would_demote=1` vs `in_zone` after >= 30 alerts (zone `reason` rows `outside_property_zone`). Step 3: enable if would_demote events sample as street/empty (same 30-snapshot method as D4a). Zero rows after 30 alerts = trip-wire finding. Do not retire: never fired, so no evidence against it |
| D5 single-source | **RETUNE-then-keep enabled** | Already ON. Change `PERIMETER_SS_SETTLE_S` 8 -> 12 (g5 p90 10.2 measured), Tier 1 constant change; or 0 per latency rule. Re-read eligibility: only g5_bullet (0.66, n=47); utilities_ptz reaches eligibility at 20 samples (0.79). Expected volume effect is small (2 LOW g5 demotes vs 3.7k pages), so do not count D5 as the FP fix; D1 zone config and the D4 daytime re-sample are the volume levers. Retire only if the first 30 gate rows show `single_source` demotes sampling as real people |
Disposal date proposal: judge both on the first 30 `perimeter_gate_decision` rows per gate or 2026-11-28, whichever first; if D3 still
has 0 rows on 11-28 because the config step was not done, park it with that revival trigger (not organic).

## Falsification run
- Would show D5 not enforcing: `perimeter_single_source_demote` false in options. Observed True.
- Would show persistence broken: gate rows absent after a non-muted alert. Not yet testable (0 alerts since install); first test next non-egress-muted edge.
- Gaps: live diag attributes not re-read (no token); the ~2 LOW demotes are inferred; HA logs not reachable.
