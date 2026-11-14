# Review A — PERIMETER-GATE-EVIDENCE Part A (data integrity + DB + local correctness)

Branch `feature/perimeter-gate-evidence` @ ea30b31a, diff base = merge-base with develop 528fb5d9 (three-dot, verified).
Focused tests: test_perimeter_ss_daylight / gate_log / vlm_location / fp_gates / identity_followup — 269 passed.

## Findings

| Sev | Where | Finding | Bug class |
|---|---|---|---|
| LOW | README_perimeter_gate_evidence_DRAFT.md:19-20 | Row-volume claim "~100-200 rows/day, ~30 MB/yr" is optimistic. A realistic D5 row's attrs JSON is ~540 B (~800 B with columns + index entry). Per alert: zone gate (zoned cams, perimeter_alert.py:1623), D5 or D10.5 (:1628/:1632), VLM when shadow/enforce (:1829), plus follow-ups, so 1-3 rows per alert and ~100-300 rows/day, which is ~30-90 MB/yr. Still small, but there is no `DELETE FROM memory_episodes` anywhere, so growth is unbounded. Correct the figure and card a retention policy if it matters. | Estimate drift |
| LOW | perimeter_alert.py:4669 (`at` = local `now.isoformat()`) | `started_at` carries a local offset; most other episode writers default to UTC (database.py:10751). Within this type the stamps are consistent, the writer-health count (UTC since_iso, 7-day window, database.py:11486) is off by at most the UTC offset, and the scorer uses naive local time, so this is harmless today. Cross-type time joins would need care. | Mixed-TZ timestamps |
| LOW | perimeter_alert.py:1223 / :498 | `_gate_log_torn_down` is never reset in `async_setup`. That is harmless because `__init__.py:3509` builds a new instance on each setup, but a reused instance would go silent. The writer-health trip-wire would catch it. Optional: reset it in async_setup. | Lifecycle latch |

No CRITICAL, HIGH or MEDIUM findings.

## Cleared (holds because)

- **Write queue:** `log_memory_episode` writes through `self._db()`, the single serialized writer queue (database.py:580, :10756). It commits per row, the same as every other episode writer, at about 1 row per 5 minutes. The episode type is registered in `MEMORY_EPISODE_TYPES` (const.py:6136), so the registry gate (database.py:10722) admits it.
- **Shape / NOT NULL:** node_id `perimeter_gate:<cam>`, episode_type, started_at=ended_at=`at`, adjudication default, attrs fully populated. `test_row_payload_shape_d5` asserts the non-sentinel values (35.0, True, "protect", CRITICAL→LOW).
- **source_ref uniqueness:** `cam|gate|at` with microsecond `at`. Zone and D5 rows share `at` but differ by gate. Even an exact collision cannot drop a row, because `dedup_source_ref=False` and `window_dedup=False` and source_ref has no UNIQUE constraint.
- **Attrs snapshot:** the `attrs` dict is built synchronously at schedule time. The task only serializes it.
- **Existing readers:** `read_memory_episodes` is filtered by node_id (new node prefix, so no bleed), `read_distinct_nodes_for_episodes` is filtered by type, and the status counts just gain a key. Compactor and adjudication paths act on explicit ids and types.
- **Writer-health:** the type is in WRITER_BACKED and not exempt. COUNT by type and since covers it. Zero rows in 7 days with ~100 alerts/day is a real dead-writer signal. `test_registered_in_writer_health_set` covers this.
- **is_daylight:** None, bool, non-numeric and NaN all count as night. `>=` makes 0.0 day at threshold 0.0. Parametrized table at test_perimeter_fp_gates.py:1905.
- **Sun read after `_agreement_open`:** perimeter_alert.py:4925 opens the sample before the eligibility chain, and the sun is read only in the final else branch (:4948). `test_agreement_sample_still_opened_at_night` covers this. Night skips the settle hold (no added latency). Both settles re-read the sun: D5 after the hold (:4976) and D10.5 at the decision after both holds (:5385).
- **D1b follow-up arming:** `egress_uncorroborated_night` is added to `_FOLLOWUP_UNKNOWN_REASONS` (:5407). Arming requires `demoted` False and severity_after equal to the sent severity, and the night path satisfies both. `egress_known_person` still demotes at night (test at ss_daylight:248).
- **D3 off = byte-identical:** with `ask_location` False, `enrich_with_verdicts` sends `_VERDICT_PROMPT` and `parse_vlm_verdict`, the same as the old `enrich_with_verdict` (perimeter_enrichment.py:272-292 vs :331-341). Location is never read by a branch in `_apply_vlm_gate`. The only change is additive `location` and `snapshot` keys on the in-memory diagnostic dict.
- **Fixture sun.sun 35° (fp_gates.py:124):** this restores the pre-cycle precondition. Without sun.sun, the new code treats every demote test as night, so the fixture keeps the old demote assertions meaningful. It does not mask anything: the night and unreadable paths have their own tests in test_perimeter_ss_daylight.py (51, 105, 123, 213, 240, 262).

## Verdict

**SHIP.** The 3 LOWs are optional and documentation-grade. Correcting the README volume figure is recommended before the final README.

| Sev | Found | Must-fix |
|---|---|---|
| CRIT/HIGH/MED | 0 | 0 |
| LOW | 3 | 0 |
