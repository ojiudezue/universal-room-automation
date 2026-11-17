# Review: describe resolves room by HA area name/alias (56ea6f384, fix/describe-area-alias)

Tier 1, framing A (local correctness + blast radius). Base verified: merge-base develop = 319064f97; diff touches person_sighting.py + 2 test files.

Tests: 71 passed (test_interior_vision_describe.py + test_interior_vision_ship2_fixup.py). New tests drive a REAL HA area registry (`async_create`/`async_update(aliases=)`), not mocks.

| # | Sev | Site | Finding | Class |
|---|---|---|---|---|
| 1 | — | person_sighting.py:1280-1304 | Registry API verified in installed HA: `AreaRegistry.async_get_area(area_id)` (area_registry.py:242), `AreaEntry.aliases: set[str]` (:79). Name + aliases normalised with the same split/join/casefold as `want` (:1030). Symmetric. Area id via CONF_AREA_ID, no name guessing. | holds |
| 2 | LOW | person_sighting.py:1040-1046 | Precedence change: an area word now beats a person first name. Only bites if an area name/alias equals a tracked first name (e.g. alias "Jaya"); then the reply is a room refusal/describe, not the person. Exact room name still wins first (test at :678). Acceptable; note only. | #63-adjacent |
| 3 | LOW | :1287,:1294,:1310 | `except Exception` broad but each returns the safe fallback (no area match / no list); refusal still sent. | — |
| 4 | — | :1308 | Covered list calls `_ensure_interior_groups()` first, so not stale/empty-before-build. Sync, loop-context like the rest of describe. | holds |
| 5 | — | reply | Lists room names to the operator-only describe requester; no privacy issue. | holds |

Verdict: **SHIP**. No must-fix.
