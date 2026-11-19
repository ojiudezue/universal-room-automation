# Review A — LAYER-LEAK-CLEANUP-1 L4 (bf985dab1) — correctness + edge cases + goal fidelity

Verdict: **SHIP** (one MEDIUM doc fix before close). Tests: 181 passed from a clean export.

- **MEDIUM (docs):** `person_entity_for_slug` (person_ids.py:66) is not recorded in IDENTITY_FUSION_CAMERAS_MANUAL.md or the presence state-of-play. Add it as the one miss-path resolver beside `person_ids.py`.
- **LOW (noise):** `person_ids.py:101` counts a miss on every call that resolves nothing, including non-person face labels each census tick. The misses counter climbs without bound, so it can't show a regression. Skip counting when `target` is empty or the slug is `guest:`.
- **LOW:** the fallback counts but never logs. Add a debug log on a hit (slug to eid) so the "logged, counted" rule is met.

Holds:
- **Hit path is byte-identical.** The exact id is returned before any count (person_ids.py:78). `test_veto_exact_entity_byte_identical` covers this.
- **Registry rule:** this is not a name guess. It reads HA `person` states and the person's configured name (`friendly_name`). It does not parse a suffix. It only runs on a miss and it is counted. That fits the allowed last-resort fallback.
- **Ambiguity:** 0 or 2+ matches return the exact id, which keeps today's fail-open behaviour (`test_person_entity_for_slug_ambiguous_is_none`).
- **Veto direction, all five sites** (camera_census 4842, 4900, 5982, 6714; transit_validator 2321): a resolved home person is still counted or named. Only a resolved `not_home` person is vetoed, which is the intended correction. No site turns fail-closed for a home person (`test_veto_display_name_person_home_not_vetoed`).
- **F1-F5:** the change only consumes F1 (P home) inside the F2 and F3 veto consumers. Producers are unchanged.
