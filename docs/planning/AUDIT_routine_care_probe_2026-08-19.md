# PROBE: Routine-care signal — measure-before-build (2026-08-19)

Read-only probe of the live URA DB (`/homeassistant/universal_room_automation/data/universal_room_automation.db`,
`anomaly_log WHERE event_class='regime_shift'`) to gate the `ROUTINE-CARE-DASHBOARD-1` design on
real data, per the measure-before-build rule. This report is the go/no-go gate.

## Findings (all 331 currently-unacked regime rows)

| Question | Measured result | Implication |
|---|---|---|
| **Dead-letter / dedup** | 331 rows across **29 distinct (person, time_bin, day_type) cells**, over **73 nights** (2026-05-15 → 08-19). Top cell = `(Jaya, bin2, weekday)` re-emitted **25 nights**. | Dedup/upsert collapses **331 → 29 (-91%)**. Confirms the nightly-re-INSERT dead-letter decisively. This is the single highest-value fix. |
| **JS distribution** (real value, `context_json.js`) | min 0.300 · **p50 0.392** · p90 0.525 · max 0.910. ≥0.3: 331 · ≥0.5: **58** · ≥0.7: **3**. | Half the events sit just over the 0.3 floor. INFO band (0.3–0.5) = **273/331 = 82%** = noise for a care panel. Only WARNING (58) + CRITICAL (3) deserve color escalation. |
| **Severity mix** | INFO 273 · WARNING 55 · CRITICAL 3 (5-level enum ints 0/1/4; `z_score` column unused = all 0, severity is JS-band-driven as the plan intended; enum slots 2/3 dead). | RED tier is genuinely **rare** (3 CRITICAL) — good. The care signal exists and is not swamped by CRITICALs. |
| **Individual vs household** (persons shifted per night) | 1-person nights: **26** · 2: 18 · 3: 15 · **all-4: 14**. | **Separable.** Individual-only signal (26 nights) is distinguishable from household-wide summer shift (14 all-4 nights). "Unusual for THIS person" (RED) vs "everyone shifted" (AMBER) is **buildable**, not a fantasy. |
| **Resolution** | time_bin 0–5 (six 4-hour bins) × day_type 0/1 (weekend/weekday). ~7 shifted cells/person. | Coarse but fine for a care panel ("mornings," "evenings"), not minute-level. |

## Verdict → the build is warranted AND smaller/better-specified than feared

- **GO.** The signal is real, discriminating (Oji INFO/31 < Ziri 146 tracks reality), and the
  individual-vs-household split needed for a trustworthy RED **exists in the data**.
- The dominant defect is **mechanical, not statistical**: dedup (331→29) + the manual-ack
  dead-letter. Cheap, high-leverage.
- **Calibration is a threshold move, not a redesign:** the alarming color must sit **above INFO**
  (0.3–0.5 is noise); reserve RED for CRITICAL (≥0.7) **AND** individual (damp when the same cell
  shifted household-wide). 3 rows qualify today.

## Feeds the plan (`ROUTINE-CARE-DASHBOARD-1`, Tier 2-DB)

- **D1 dedup/upsert** `anomaly_log` regime rows (one row per (person,cell) updated in place) — kills the 331.
- **D2 discharge:** re-baseline/adopt so a sustained new-normal returns a cell to GREEN (the "discharge" the accumulator lacks).
- **D3 calibration + household-damping:** color bands GREEN(stable)/AMBER(drifting-or-household-wide)/RED(individual ≥CRITICAL vs stable baseline)/GREY(away). RED requires NOT-household-wide.
- **D4 color dashboard card**, sensor-only, no notifications.
- **Acceptance must discriminate:** RED fires for a lone-person CRITICAL; the same JS as a 4-person household shift renders AMBER, not RED.
