-- HVAC-GUEST-EVIDENCE-RULE-1 phase 1: settle each house state SAFE / NOT SAFE /
-- INSUFFICIENT for the HVAC evidence rule, from the `hvac_evidence_shadow` table.
-- Plan: docs/planning/PLANNING_hvac_evidence_shadow_recording_2026_11.md rev 2 §7.
-- Run via scripts/probes/hvac_evidence_shadow_verdict.py (named parameters):
--   :since      first timestamp to read (UTC ISO; the D3 live date)
--   :grace      live knob 48 in seconds (re-read before running)
--   :boot       boot-window exclusion in seconds (rows opened earlier are dropped)
--   :floor_h    minimum legacy-occupied zone-hours for a verdict (30)
--   :ratio      allowed multiple of the home_day/home_evening reference rate (1.5)
--   :abs_floor  absolute bar, premature events per legacy-occupied zone-hour (0.02)
WITH ep AS (
  SELECT house_state AS st, kind, outcome, duration_s AS dur
  FROM hvac_evidence_shadow
  WHERE row_type = 'episode' AND timestamp >= :since
    AND COALESCE(opened_s_after_boot, 1e9) >= :boot
    AND COALESCE(json_array_length(json_extract(details_json,'$.refresh_failed_rooms')),0) = 0
    AND COALESCE(json_array_length(json_extract(details_json,'$.pending_rooms')),0) = 0
),
expo AS (
  SELECT house_state AS st, SUM(duration_s) / 3600.0 AS occ_zone_h
  FROM hvac_evidence_shadow
  WHERE row_type = 'exposure' AND timestamp >= :since
  GROUP BY house_state
),
agg AS (
  SELECT st,
         SUM(kind='less' AND dur >= :grace)                       AS eligible,
         SUM(kind='less' AND dur >= :grace AND outcome='resumed') AS premature,
         SUM(kind='less' AND dur >= :grace AND outcome='released') AS saved,
         SUM(CASE WHEN kind='less' THEN dur ELSE 0 END) / 3600.0  AS less_h,
         SUM(kind='more')                                         AS more_eps
  FROM ep GROUP BY st
),
j AS (
  SELECT e.st, e.occ_zone_h,
         COALESCE(a.eligible,0) AS eligible, COALESCE(a.premature,0) AS premature,
         COALESCE(a.saved,0) AS saved, COALESCE(a.less_h,0) AS less_h,
         COALESCE(a.more_eps,0) AS more_eps
  FROM expo e LEFT JOIN agg a USING (st)
  UNION ALL
  -- States with episodes but no exposure (e.g. only `more` episodes):
  -- listed with NULL hours so their counts are visible (review A-L2).
  SELECT a.st, NULL, a.eligible, a.premature, a.saved, a.less_h, a.more_eps
  FROM agg a WHERE a.st NOT IN (SELECT st FROM expo)
),
ref AS (
  SELECT SUM(premature) * 1.0 / NULLIF(SUM(occ_zone_h),0) AS ref_rate,
         SUM(occ_zone_h) AS ref_h
  FROM j WHERE st IN ('home_day','home_evening') AND occ_zone_h IS NOT NULL
)
SELECT j.st, ROUND(j.occ_zone_h,1) AS occ_zone_h, j.eligible, j.premature, j.saved,
       ROUND(j.less_h,2) AS less_h, j.more_eps,
       ROUND(j.premature / j.occ_zone_h, 4) AS rate,
       ROUND(r.ref_rate, 4) AS ref_rate,
       ROUND(MAX(:ratio * COALESCE(r.ref_rate,0), :abs_floor), 4) AS bar,
       CASE
         WHEN j.occ_zone_h IS NULL THEN 'NO EXPOSURE'
         WHEN j.st IN ('home_day','home_evening') THEN 'REFERENCE'
         WHEN COALESCE(r.ref_h,0) < :floor_h THEN 'INSUFFICIENT (reference)'
         WHEN j.occ_zone_h < :floor_h THEN 'INSUFFICIENT'
         WHEN j.premature / j.occ_zone_h <= MAX(:ratio * COALESCE(r.ref_rate,0), :abs_floor) THEN 'SAFE'
         WHEN j.premature >= 3 THEN 'NOT SAFE'
         ELSE 'INSUFFICIENT'
       END AS verdict
FROM j CROSS JOIN ref r
ORDER BY j.st;
