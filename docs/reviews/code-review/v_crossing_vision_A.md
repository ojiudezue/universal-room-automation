# Review A: crossing vision shadow (VISION-CROSSING-SHADOW-1 D1-D3)

Branch `feature/crossing-vision-shadow` @ 18e3ba59. Diff base = merge-base with develop
`6e03ec09` (verified, one commit on branch). Framing A: data integrity + local correctness.
Read-only; no tests run (framing C owns mutation). Docs read: plan rev 2 §3/§5 D1, plan review,
D0 audit (main checkout), IDENTITY manual + PRESENCE doc diff rows and the presence-doc rows that
cover egress (not the full 1039-line presence doc: this change adds no presence/census input path).

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| A1 | LOW | `crossing_vision.py:577` | Schedule cap gate is `_calls_today + _pending() >= cap`, and `_run` increments `_calls_today` (`:716`) while the request is still `calling`, so an in-flight call counts twice until done. Effect is conservative only: near the cap (e.g. cap=2, one call in flight -> 1+1 >= 2) a crossing is recorded `skipped_cap` with one call unused. Never exceeds the cap. | Arithmetic (conservative) |
| A2 | LOW | `crossing_vision.py:705-706` | Switch turned off while a primary waits: `_run` returns with no primary row, but members already written as `clustered` carry `primary_crossing_key` pointing at a row that never exists. Scorer must tolerate orphans (plan accepts "no row while off"). | Data integrity (orphan ref) |
| A3 | LOW | `crossing_vision.py:607-613`, `:784` | A crossing that joins a cluster AFTER the primary row was written is not in the primary's `crossing_keys` (attrs copied at record time). Recoverable via the member's own `primary_crossing_key`; plan text "primary row carries all members" holds only for joins before the call returns. | Data integrity (snapshot) |
| A4 | LOW | `crossing_vision.py:154` docstring, plan §D1.8/§D1.9 | Docstring still lists `vision_direction`; code (correctly, per D0: no signal) neither asks for nor records it (test `test_crossing_vision_shadow.py:311` asserts absence). The manual records the deviation; the plan D1.8/9 text was not updated. Doc drift only. | Doc drift |
| A5 | LOW | `crossing_vision.py:826-827` | `started_at` = local-offset ISO (bus timestamp), `ended_at` = UTC ISO, and the readers filter `started_at >= ?` lexically (`database.py:11039, :11139, :11493`). Up to the UTC offset of skew at window edges. Same pre-existing shape as `egress_identity_outcome` (`transit_validator.py:2624`); not new. | Pre-existing TZ-string compare |
| A6 | LOW | `perimeter_enrichment.py` `analyze_crossing_frames` | `max_tokens` reuses the perimeter's `CONF_PERIMETER_ENRICHMENT_MAX_TOKENS` (default 1500, matches D0). An operator lowering it for perimeter alerts would truncate the JSON here -> `unparseable` (caught by the error trip-wire). Coupling, documented nowhere. | Shared knob coupling |

No CRITICAL / HIGH / MEDIUM.

## Cleared (holds because)

- **parse_vision_response** (`:146-227`), truth table:
  `{}` / `{"service_response":{}}` -> refused; `structured_response` empty/None -> refused; dict -> parsed;
  non-empty string structured_response w/o response_text -> unparseable; `response_text` "" -> refused, bad JSON -> unparseable;
  `frames` missing / not list / item not dict / `people` bool, negative, non-integer float -> unparseable;
  `frames: []` or all 0 -> blank, people_count None (INV-BLANK); peak>0: people_count = clamp(people_total or peak, [peak, peak*len]);
  people_total negative/bool -> treated as absent -> peak. `desc` truncated to `max(0,int(DESC_MAX))`. Unwrap of the D0 `service_response` envelope matches audit line 67.
- **INV-BLANK**: `:216-220` returns before `people_count` is set; blank -> agreement_case D (never A/B/C on a 0). No-match -> `no_frigate_event`, `_record` only, no `_spawn(_run)` (`:563-565`).
- **INV-OFF**: `_enabled()` checked before any row/sample (`:514`) and again at call time (`:705`); cap 0 -> `_enabled` False. Kill const also checked inside `analyze_crossing_frames`. Number key `crossing_vision_daily_calls` is in both `_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:7425, :7735`): a cap edit does not reload the CM.
- **INV-SCOPE**: ring admits only stems in `door_camera_stems()` (`:459`); match restricted to `door_group_members(stem)` (`:562`, `transit_validator.py:1298-1315`, same membership rule as the sampler `:1344-1352`). Clip ref is the matched event id, sanitized (`:674`, `:683`); ambiguous instance with >1 Frigate entry -> `no_clip_url`, no call. Concurrency `_pending() >= MAX_CONCURRENT` -> `skipped_busy`, nothing queued.
- **INV-ADDITIVE**: the sample moved from the DB-write site to before the bus fire (`transit_validator.py:2227-2235`); between the two sites (`:2238-2340`) there is no `await` (notify, census register/evict are sync), so the DB value is identical to develop and equals the bus value. Ambiguous -> None, no sample, no row (develop shape). Bus listeners (`sensor.py:4789-5026`, `perimeter_alert.py:1006`, `person_sighting.py`) read named keys only.
- **INV-SHADOW readers**: grep of `crossing_vision_shadow` / `CROSSING_VISION_EPISODE_TYPE` / `CROSSING_VISION_HASS_KEY` outside the module: const registry, sensor diag attrs (`sensor.py:4528`, in `_unrecorded_attributes`), switch/number. No compaction rule added.
- **Row schema**: `log_memory_episode` signature matches (`database.py:10686-10697`); type registered in `MEMORY_EPISODE_TYPES` (else the insert is dropped with a warning). Per-(node_id,type) RAM dedup cannot collide: node_id is per crossing.
- **Writer health**: type in WRITER_BACKED + ABSENCE_EXEMPT. Ships OFF -> pages after 7 days if never enabled; accepted in plan §D3 and plan review, discharge documented in `const.py`.
- **Timestamps**: bus `timestamp` comes from `dt_util.now()` (aware), so `e_ts.timestamp()` vs Frigate epoch `start_time` compare correctly.

## Verdict

**SHIP.** No must-fix. Optional in-cycle LOW fixes: A1 (count only `waiting` in the schedule gate, or decrement the double count), A4 (docstring + plan text), A6 (one-line comment or own rung-1 constant).

| Severity | Found | Must-fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 0 | 0 |
| LOW | 6 | 0 |
