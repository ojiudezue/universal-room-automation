# AUDIT: exterior-person alerts under ARRIVING (14 days to 2026-11-17 ~02:30 CST)

Card: EXTERIOR-PERSON-SEVERITY-ARRIVING-BODY-ONLY-1 (kanban.data.yaml:35867). Read-only. Method: URA DB via `ssh ha sqlite3 -readonly`, HA recorder (person.* history), code read.

## Verdict (lead)
The card's premise is stale. Exterior-person alerts are NOT lowered to LOW under ARRIVING. The ARRIVING rule never produced LOW in live data and the code now escalates, not softens. No harm found.
- Pre-step-1a rule: ARRIVING -> MEDIUM ("likely the operator approaching").
- Since commit a0d590ef2 (2026-11-13, in v5.108.19+; live manifest v5.108.34 contains it): ARRIVING with no resident evidence -> CRITICAL; MEDIUM only if a resident is home or a counted resident arrival within 300 s.
- 14d: 1,372 exterior_person alerts; 6 fired while the house read ARRIVING, all MEDIUM, all before the rule change. 0 LOW under ARRIVING. 0 ARRIVING alerts since the change (11 ARRIVING periods, 0 alerts).

## Code (rule + what is persisted)
- Resolver: const.py:2872-2975 (`NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY`); ARRIVING arm const.py:2936-2946 (CRITICAL if `arriving_resident_evidence is False and EXTERIOR_SEVERITY_ARRIVING_NEEDS_RESIDENT`, else MEDIUM). Knobs const.py:2859 (True), :2872 (RECENT_ARRIVAL_S=300), :2866 persons_home-from-residency (False).
- Caller: perimeter_alert.py:2131-2200 `_severity_for_current_house_state`; evidence = `get_residents_home_count()>=1` or `get_recent_resident_arrival(300)` (:2159-2170); any error -> CRITICAL. Dispatch at perimeter_alert.py:1990-2010 (`nm.async_notify(severity=..., hazard_type=exterior_person)`).
- Only home_day/home_evening reach LOW (const.py:2915-2931, needs persons_home>=1, which is forced 0 by default, perimeter_alert.py:2217-2222). Other LOWs come from elsewhere (see below).
- Persisted per alert: `notification_log` (timestamp, severity, hazard_type, location, route_reason, delivered, message="[audit]"). There is NO house_state column and NO downgrade-reason column. House state at alert time can only be recovered by joining timestamp against `house_state_log` (timestamp,state,trigger,previous_state). The join is exact (state interval containing the alert), so ARRIVING membership is determinable; "downgraded vs a counterfactual" is not persisted (the pre-downgrade severity is not stored). Also the evidence flag (residents_home / recent arrival) is only in the INFO log line, not the DB.

## Counts (UTC timestamps in DB; window = last 14 days)
| metric | value |
|---|---|
| exterior_person rows (notification_log) | 1,372 (CRITICAL 506, HIGH 814, MEDIUM 47, LOW 5) |
| ARRIVING periods in house_state_log | 31, every one exactly 1.0 min (shim), total 31.4 min |
| ARRIVING origin | all `previous_state=away`; triggers census_update 22, periodic 5, deferred_retry 4... (see log) |
| exterior alerts inside ARRIVING | 6 (ids 25794, 25795, 25824, 26372, 26683, 27458), all MEDIUM |
| alerts lowered to LOW under ARRIVING | 0 |
| all 5 LOW exterior rows | in home_day x2, home_night, sleep, away (ids 25566, 26115, 26161, 26915, 26993); none ARRIVING. Cause not determined here (not the ARRIVING rule; likely the identity/follow-up path) |
| ARRIVING alerts after the rule change (>=2026-11-13T15:30Z) | 0 (11 ARRIVING periods) |

## Per-episode (6 alerts, 5 ARRIVING periods)
| ARRIVING start (UTC) | alerts | resident arrival? | evidence |
|---|---|---|---|
| 2026-11-06 00:26:19 (id 8549) | 25794 rear_ptz, 25795 g5_bullet | UNKNOWN | recorder retention starts 2026-11-09 10:12 so no person.* data; egress log shows oji exit 00:30:39 and unidentified entry 00:31:35, so inconclusive |
| 2026-11-06 04:41:03 (8553) | 25824 g5_bullet | UNKNOWN | same retention gap; unidentified entry 04:42:02, oji exit 04:42:33, oji exit earlier at 03:37 |
| 2026-11-10 00:22:18 (8594) | 26372 g5_bullet | REAL | person.ezinne not_home>home 00:21:25, person.jaya 00:21:45 (recorder) |
| 2026-11-12 01:12:00 (8616) | 26683 g5_bullet | REAL | ezinne 01:10:52, jaya 01:10:55 not_home>home |
| 2026-11-16 00:12:02 (8677) | 27458 g5_bullet | REAL | oji_udezue 00:11:37, jaya 00:11:51 not_home>home |
Real vs false over the whole window: of the 31 ARRIVING periods, 53 person not_home>home transitions exist in the recorder for 14d (only since 11-09 retained). Prior audit figure: 6.4% of AWAY->ARRIVING edges are real (AUDIT_arriving_on_body_evidence_2026_11_13.md). Among the 5 ARRIVING periods that contained an exterior alert, 3 of 3 checkable were real arrivals, 2 undeterminable. The outdoor alert in a real arrival is the arriving resident, so MEDIUM was appropriate, and no false-ARRIVING + real-intruder case was found.

## Falsification
Disproof would be: a LOW (or any sub-HIGH) exterior alert inside an ARRIVING interval with no resident arrival. Query (below) returns zero LOW and the 6 MEDIUM ones are explained or unknown, not disproven. Caveat: for episodes 1-2 resident evidence is unknown (retention), so a real non-resident at MEDIUM there cannot be excluded; both predate the current CRITICAL-when-no-evidence rule.

## Harm assessment
- Downgrade harm today: none. Current code fails toward CRITICAL on ARRIVING without resident evidence (over-alerts, safe direction).
- Residual risk is the opposite: a false ARRIVING (93.6% of edges per prior audit) now makes exterior alerts CRITICAL when no resident is home, but the house was reading AWAY, which is already CRITICAL (const.py:2900), so no change in paging.
- Recommendation: close/re-scope the card as already resolved by step 1a D5 (a0d590ef2); only add a persisted `house_state` + evidence flag on alert rows if future audits need it.

## Queries used (sqlite3 -readonly; HA db /config/home-assistant_v2.db, URA db /config/universal_room_automation/data/universal_room_automation.db)
```
create temp view hs as select id,timestamp ts,state,trigger,previous_state,lead(timestamp) over (order by timestamp,id) nxt from house_state_log;
select n.id,n.timestamp,n.severity,n.location,n.route_reason,h.id from notification_log n join hs h on n.timestamp>=h.ts and (h.nxt is null or n.timestamp<h.nxt)
 where n.hazard_type='exterior_person' and h.state='arriving' and n.timestamp>datetime('now','-14 day');
-- person transitions (recorder): lag(state) over (partition by entity order by last_updated_ts) where prev<>state, entity like 'person.%'
```
Persons resolved via person.* entities (oji_udezue, ezinne, ziri, jaya; wall_kiosk excluded), not names.
