# Plan review: PLANNING_crossing_vision.md (rev 1, commit d5d945c1)

Reviewer: ura-planner, Mode 2, one adversarial plan review (Tier 2-DB plan rule), 2026-11-13.
Read first: the plan; PRESENCE / SENSOR_FLEET / IDENTITY manual not re-read in full by this reviewer (no presence
claim is made below beyond code citations; HVAC not touched). All findings verified by grep / read against the
worktree (develop @ ac664761 + plan commit) and the live llmvision 1.7.1 / Frigate integration on the HA mount.

**Verdict: FIX-PLAN, fixes applied in-plan as rev 2 (F1-F13). After rev 2: BUILD-READY.**
Scope: FOCUSED. Tier 2-DB for Phase 1 confirmed.

## Verified as stated

- **Temperature finding is correct.** `llmvision/providers.py:466-484` reads temperature / top_p from the entry config
  (`hass.data[llmvision][entry_id]`, populated from `entry.data` at `__init__.py:101-102`); `:690-696` put both in the
  payload; `:707-710` strips them only for `gpt-5`, `gpt-5-mini`, `gpt-5-nano`. OpenAI step selector Temperature and Top P
  are 0..1 step 0.1 (`config_flow.py:555-575`), so 1.0 is legal. No `async_set_unique_id` / `_abort_if_*` anywhere in
  `config_flow.py`, so a second OpenAI entry is allowed. `validate()` posts "Hi" with no temperature (`:798-807`).
  The second-entry recommendation (do not touch the perimeter entry) is right.
- **Credential rule holds.** `video_analyzer` with `event_id` builds `/api/frigate/notifications/<id>/clip.mp4`
  (`media_handlers.py:932-934`), signs it with HA's `async_sign_path` and fetches from HA's own base URL
  (`:630-643`). The Frigate integration's `NotificationsProxyView` injects its own auth headers upstream
  (`frigate/views.py` mixin `get`). The fallback (`PerimeterAlertManager._http_get_bytes`, `perimeter_alert.py:3979+`)
  only accepts relative HA paths. No URA code holds or sends Frigate credentials. Consistent with the rule.
- **Payload shape:** adding `peak_person_count` to `ura_person_egress_event` IS a "changes payload shape of a dispatched
  event" Tier 2-DB trigger. The plan's tier is right, but its review list lacked the B framing duty (F12).
- `_sample_peak_person_count` has one caller (`transit_validator.py:2298`), sync, called after the bus fire with no
  await between; hoisting is value-identical. Bus `timestamp` and outcome-log `crossing_key` use the same
  `egress_timestamp.isoformat()` (`:2194`, `:2556-2560`), so the `source_ref` join holds.
- Frigate ingress dedups by (event id, family) only (`frigate_ingress.py:437-470`); `update` / `end` messages reach
  consumers, so the "call at event end" wait is implementable. Consumers are sync callbacks.
- `MEMORY_EPISODE_TYPES` / `MEMORY_WRITER_BACKED_EPISODE_TYPES` at `const.py:6018` / `:6064` as cited; 0 hits for
  `crossing_vision` in the integration.
- Knob ladder mostly complete; D0 gates sensible (D0b/D0c gate deploy, D0d gates Phase 2 only, D0a gates D5 only).
- INV-SHADOW, INV-OFF, INV-ADDITIVE, INV-BLANK are falsifiable with concrete break recipes.

## Findings (all fixed in plan rev 2)

| # | Sev | Finding | Fix in plan |
|---|---|---|---|
| F1 | HIGH | Frigate `after.camera` → door-group map was specified only as "D0c map" (a committed fixture). A builder would hard-code the 4 camera names: portability violation and a silent miss on rename / `_2` suffix. | §5 D1.1: runtime derivation through `_extract_camera_stem` (`transit_validator.py:1465` → camera_census) + `door_groups`; fixture becomes the test oracle (`test_runtime_camera_map_matches_fixture`). |
| F2 | MED | Plan says `person_sighting.py` is on the unmerged `feature/person-sightings-p1`. It is on develop (`git branch --contains`), `FACE_SIGHTING_ENABLED = True` (`const.py:3362`), registered from `presence.py:5533`: a live sixth listener of the event D2 changes. | Intro, §1.3, §8, §9 corrected; listener list now includes `person_sighting.py:454-492` and `perimeter_alert.py:5081`. |
| F3 | MED | INV-SHADOW's allowed-reader set omitted three pre-existing generic `memory_episodes` readers: `get_memory_status_counts` (`database.py:11152`, memory status sensor), `MemoryFacade.episodes/narrative` behind the `memory_query` service (`__init__.py:6395-6411`), the writer-health check (`:11491`). As written, the invariant was "broken" on day 1 by display code. Also no rule forbade adding a `MEMORY_COMPACTION_RULES` entry (which would derive facts). | §3 lists them as display / operator-query readers and forbids a compaction rule for the type in Phase 1. |
| F4 | MED | `event_id` makes llmvision use the default Frigate URL. `get_default_config_entry` returns None when `async_entries("frigate")` > 1, counting disabled entries (`frigate/views.py:47-57`), so a lingering retired Frigate 1 entry turns every call into an error. D0c only checked "loaded" entries. Perimeter code already avoids the default URL for this reason (`perimeter_alert.py:3840-3858`). | §5 D1.7: pass instance-scoped `video_file` path when the instance is known, `event_id` only with exactly one entry. D0c counts all entries and records `notification_proxy_enable` (the proxy refuses when off). |
| F5 | MED | Cluster rule ambiguous: "open request" leaves a crossing 30 s after a completed call free to re-analyse the same Frigate event (double count). Clustered crossings had no row, but D4 joined by `source_ref` only, so they vanished from the scorer. | §5 D1.3: cluster against open OR completed requests and by matched event id; every crossing writes its own row (`outcome=clustered`, `primary_crossing_key`); D4 join 1:1. |
| F6 | MED | `asyncio.wait_for(…, 45)` around `blocking=True` cancels llmvision's handler in place (HA `core.py` awaits the handler coroutine directly), which can orphan its ffmpeg subprocess and leak its `delete=False` temp clip. 45 s is below llmvision's own `request_timeout` default 60 s (`providers.py:502-507`) plus fetch + ffmpeg. | `CROSSING_VISION_TIMEOUT_S` 90, set by D0b to ≥ 1.5 × p99; Review B covers cancellation. |
| F7 | LOW | Cap counter "persist or name it" left a choice to the builder. | Decided: RAM, midnight reset, residual named (≤ one extra cap per restart, ≤ $0.50). |
| F8 | LOW | Inline numbers without knobs: error trip-wire min 8 calls, 24 h window, hourly eval, `desc` 200 chars, 5 s teardown gather, `[E − 10, E + 45]` window. | Six named rung-1 constants added; the window reuses existing names. |
| F9 | LOW | `use_memory` not stated. Default False, and llmvision sends memory images only when True (`providers.py:759-761`), but §15.2 forbids it; make it explicit and tested. | D1.7 + `test_use_memory_false`. |
| F10 | LOW | D2's discriminating test ("change the buffer at the await point") cannot discriminate: there is no await between the bus fire and the DB write. | Replaced with a call-count stub (sampler called once; both sinks carry the first value). |
| F11 | LOW | Wire-in anchor vague ("in `__init__.py` after …"). | Anchored next to `ExteriorTrackLinker` (`__init__.py:3569-3586`). |
| F12 | LOW | §9 review framings omitted the Tier 2-DB payload-shape duty for the D2 key. | Review B now includes field-by-field comparison across every listener + recorder. |
| F13 | LOW | INV-SCOPE promised "never an interior neighbour / perimeter camera", which code cannot know; ungrouped stems undefined. | Scope = configured `door_groups` (ungrouped stem = group of one); D0c verifies membership is door-only. |

## Residuals not fixed (judgement, non-blocking)

- Switch ships off, but the type is in `MEMORY_WRITER_BACKED_EPISODE_TYPES`, so the weekly health check pages if the
  operator has not turned it on within 7 days. The plan already names this as the discharge; acceptable.
- D0b as written exercises `event_id`; after F4 it should also do one instance-scoped `video_file` call. The prober brief
  should include it (orchestrator note, not a plan defect).
- Cost figures are estimates (llmvision returns no usage); stated as such.

## Stats

| Severity | Found | Fixed in plan |
|---|---|---|
| HIGH | 1 | 1 |
| MEDIUM | 5 | 5 |
| LOW | 7 | 7 |
