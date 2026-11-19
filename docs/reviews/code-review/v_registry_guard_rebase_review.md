# Review: registry-not-names guard rebase (ed21285ec + 76620e187), Tier 1

Verdict: **SHIP**

- Round 1 (ed21285ec): HIGH. The allowlist was unchanged from ea777fa46, and the guard went 5 failed / 25 passed on a clean export. 76620e187 fixes this. The coordinator reports 30/30 on a clean export.
- The three added rows are all legitimate:
  - `sensor.py PersonProfileSensor.__init__` (N3): builds URA's own `unique_id`/`entity_id` from `person_ids.slug_of`. It is URA's own entity and the one person-id rule.
  - `music_following.py _slug` (N4): normalises URA room names for comparing one room with another. No HA entity is inferred.
  - `person_sighting.py _describe_target` (N4): matches operator text against URA room names and `slug_of`/`display_of`, with an area-registry fallback. That is operator-text matching.
- The 10 removed rows (4 camera_census, 5 music_following, 1 transit_validator) no longer hit. A STALE row fails the ratchet, so 30/30 proves it.
- No production code changed. The guard file runs in about 7 s.
