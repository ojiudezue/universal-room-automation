# Census Accuracy — Code Review B (consumer ripple + lifecycle + cross-cycle)

- Branch tip reviewed: `6bf4f4eee` (`feature/census-accuracy`)
- Merge-base vs `develop`: `ec034585` (verified via `git merge-base`)
- Cycle commits in-scope (2): `8c97c0567` (D1+D2 build), `6bf4f4eee` (test isolation + kanban sync)
- Diff shape: 3 prod files (`camera_census.py` +204/-19, `const.py` +6/-1, `sensor.py` +17/-0), 1 new test file (`test_census_accuracy_d1_d2.py`, 444 lines), 1 sibling test tweak, kanban data churn.
- Spec: `docs/planning/PLANNING_census_accuracy.md` rev-2.
- Suite baseline (per orchestrator): branch 25/9208, develop 25/9194, NAME-DIFF EMPTY.
- Framing: consumer ripple of the decay change, cross-cycle interaction with v5.79.0 (GUEST — just shipped), new attr/payload surface hazards, D2 lifecycle, restart/reload resilience.

## Verdict

**SHIP-WITH-FIX** — one HIGH lifecycle finding (`B-HIGH-1`) that the cycle should address before deploy; the rest is CLEAN or MEDIUM/LOW deferrable. All consumer-ripple risk on the shared-primitive surface is either intended (guest exit) or de minimis; no threshold-cross on the enumerated consumer surface. The falsifiable invariants (`INV-DECAY-HONEST`, `INV-PEAK-NO-SELF-REFRESH`, `INV-PAYLOAD-DISCRIMINABLE`) hold on the reachable diff. Cross-cycle interaction with v5.79.0 is asymmetric-as-designed (exit reachability up, entry gate identical).

## Findings

### B-HIGH-1 — D2 last_camera map is memoised on FIRST call and never rebuilt; a first-call empty map (setup-timing / Frigate-reloaded / person-added) becomes a permanent silent fail-CLOSED for the face-based person-recognition path.

`PersonCensus._resolve_last_camera_entity_id` (camera_census.py:~2550) does:

```
cached = getattr(self, "_frigate_person_last_camera_map", None)
if cached is None:
    cached = self._build_frigate_person_last_camera_map()
    self._frigate_person_last_camera_map = cached
```

`_build_frigate_person_last_camera_map` returns `{}` on any of: `entity_registry` unreadable, `async_entries_for_platform("frigate")` raises, Frigate entities not yet registered, or `entries` empty. Once the empty dict is cached, **the sentinel is no longer `None`**, so no subsequent call rebuilds — including after Frigate's config entry reloads or a new tracked person is added to the frigate face library. The result is a permanent silent fail-CLOSED for the `_get_face_recognized_person_names` last_camera path (the caller at camera_census.py:~3244 hits the `if sensor_id is None: continue` branch every tick).

Blast radius:
- The `_get_face_recognized_persons` path (a *different* method — uses `_resolve_face_entity_id`, per-tick lookup, no memoisation) is unaffected.
- Impact is on `face_recognized_count` published on `SIGNAL_CENSUS_UPDATED` and consumed by `presence.py`'s guest gate (`_face_recognized_count`), plus the `_get_face_recognized_person_names` slug list used by the identification/dedup logic. A silent zero-out here means `unidentified_count` is inflated (persons counted as unidentified rather than face-recognised), which biases the just-shipped v5.79.0 GUEST gate **toward false-positive guest entry** — the exact regression class the v5.79.0 cycle was written to close.
- Probability: LOW on cold boot in steady state (Frigate loads before URA parent per current after_dependencies wiring). HIGHER after any Frigate reload or after adding a new frigate face-library person mid-run.

Confirmation drill (executed in isolated worktree at `6bf4f4eee`, `PYTHONDONTWRITEBYTECODE=1`, cache purged):
- Neutered `_build_frigate_person_last_camera_map` to `return {}`. Result: 4 targeted tests failed (`test_d2_last_camera_map_from_registry`, `..._prefers_canonical_over_suffixed`, `..._resolves_last_camera_for_ura_person_slug`, `..._ignores_registry_entries_with_unexpected_unique_id`). Restored + `git status` clean.
- Confirms the BUILDER is behaviorally load-bearing. **Does not** exonerate the lifecycle: none of the shipped tests exercise the sequence "resolve once with empty registry → cache = {} → registry populated → next resolve expected to hit" — the gap this finding calls out.

Recommended fix (small, in-cycle):
1. Change the empty-map guard to `if not cached` (rebuild on empty), OR
2. Subscribe to `EVENT_ENTITY_REGISTRY_UPDATED` (or the equivalent `async_track_registry_updated_event`) with a debounce and invalidate `_frigate_person_last_camera_map = None` on Frigate-domain changes, OR
3. At minimum: rebuild on empty AND rebuild if the last build was > N minutes ago and any lookup missed (bounded rebuilds).

`(1)` is the parsimonious fix and matches the "~5 entries, cheap" justification in the docstring. Add one test that populates the registry *after* first resolve and asserts the second resolve hits.

### B-MEDIUM-1 — `count_as_of` is stamped at both dispatch time (payload) AND attr-read time (sensor) with no cross-reference; two consumers reading the two surfaces will see values that differ by up to one full tick and infer bogus lag.

`camera_census.py:1231` stamps `count_as_of = dt_util.utcnow().isoformat()` at dispatch. `sensor.py:3565` stamps `attrs["count_as_of"] = _dt_util_d1.utcnow().isoformat()` at attribute-read time. The signal-payload consumer (any subscriber to `SIGNAL_CENSUS_UPDATED`) and the attribute reader (dashboard, external HA automation) will see different values for what looks like the same field.

There is no in-repo signal consumer that parses `count_as_of` today (grep-verified), so this is currently latent. But: a future consumer using `peak_age_seconds` + `count_as_of` to reason about freshness will get a lag measurement biased by up to the poll interval. Recommendation: rename one of them (e.g. sensor attr → `attrs_read_at`) OR always echo the dispatch-stamp — never re-stamp.

### B-MEDIUM-2 — `peak_age_seconds` is derived from `int(peak_age_minutes)`, giving 60-second granularity, which defeats the "short-window discrimination" the field is documented to provide.

Both `camera_census.py:1246` (`_peak_age_min * 60`) and `sensor.py:3583` compute seconds from truncated minutes. This is 60× coarser than the field name implies. Consumers writing `if peak_age_seconds < 30` will observe 0 for the entire first minute of hold — a discrimination the field promised. Suggest computing from the underlying `elapsed` seconds already available in `_apply_hold_decay` and threading it up via a `peak_age_seconds` output. In-cycle if cheap; otherwise a LOW.

### B-LOW-1 — `_face_lookup_missing_count` per-tick counter is incremented ONLY in `_resolve_face_entity_id`'s "neither variant resolves" branch — not in the parallel `_resolve_last_camera_entity_id` fail-CLOSED path. The name-implied contract ("face-lookup path was healthy this tick") is only partially true.

Two D2 resolvers exist; only one reports its misses. If B-HIGH-1 lands and the last_camera map is empty, `_face_lookup_missing_count` stays at 0 while every person-slug lookup is silently missing. This makes the counter unreliable as the "health telemetry" the docstring claims. Suggest either (a) incrementing in both fail-CLOSED paths, or (b) renaming to `_face_entity_id_missing_count` and adding a sibling `_last_camera_missing_count`.

### B-LOW-2 — Defensive `getattr(self, "_frigate_person_last_camera_map", None)` masks a real init-order guard.

The comment says "some legacy tests construct PersonCensus via `object.__new__`". That should be a test problem, not a production defensive. The getattr means a genuine future `__init__` regression (e.g. someone forgetting to initialise this attribute in a code path that constructs PersonCensus differently) will silently fall through to an empty-map build with all the B-HIGH-1 consequences. Prefer: drop the getattr; fix the offending tests to use a factory. Not a blocker.

## Consumer table — SIGNAL_CENSUS_UPDATED / `census.last_result.house.*` / new attrs

Verified by `git grep` at `6bf4f4eee`. Reviewer B independent re-enumeration (starting from v5.79.0 hypothesis but NOT trusting it).

| Consumer (file:line) | Field(s) read | D1 behavior delta | Threshold-cross? |
|---|---|---|---|
| `presence._handle_census_update` (`presence.py:4322-4380`) | `interior_count`, `unidentified_count`, `confidence`, `face_recognized_count` | Faster post-hold zero for both counts. Guest EXIT more reachable (intended, per plan §D1). Guest ENTRY unchanged: `unidentified > 0` while cameras genuinely see them; `fresh==peak` path returns `fresh` unchanged. | **No** (guest persistence 300s, interior hold 180s — under D1 a genuine sustained fresh_count keeps count elevated via the `elif fresh==peak: return fresh` early-return branch; the persistence 5-min gate can still fire) |
| `presence.py:2649` (setup seed) | `house.total_persons` | One-shot at coordinator setup; D1 has no seed-time effect. | No |
| `aggregation.ZoneGuestCountSensor` (`aggregation.py:5967, 5992`) | `house.total_persons` for `max(0, camera_total - ble_total)` | Camera total decays faster post-hold → guest count clamps to 0 sooner. Matches v5.79.0 intent. | No |
| `binary_sensor.URAUnknownPersonInHouseSensor` (`binary_sensor.py:1549, 1573`) | `house.total_persons > ble_total` | Cleaner drop-to-off after sustained low fresh. Intended. | No |
| `binary_sensor.PersonPhoneLeftBehindSensor` (`binary_sensor.py:1772`) | `house.total_persons > 0` as suppression | Faster zero → less suppression window. Legitimate all-left case fires sooner (correct). Sub-hold-window camera loss of a genuinely-home person: pre-existing hold (180s) still smooths; post-hold sustained zero would clear, but that also implies real absence. BLE + camera-sighting checks upstream still gate. | No |
| `sensor.URAPersonsInHouseSensor.extra_state_attributes` (`sensor.py:3496, 3556-3573`) | `peak_held`, `peak_age_minutes`, and NEW `count_as_of`/`peak_age_seconds`/`peak_refresh_suppressed_count`/`face_lookup_missing_count` | Additive attrs; None-safe getattr defaults; no in-repo reader parses `count_as_of` as a number (grep-verified). | No |
| `sensor.URAPersonsOnPropertySensor.extra_state_attributes` (`sensor.py:3647-3648`) | `peak_held`, `peak_age_minutes` for property zone | Property branch already used instant-drop; D1 is a no-op for property. | No |
| `SIGNAL_CENSUS_UPDATED` new keys (`peak_held`, `peak_age_seconds`, `count_as_of`, `peak_refresh_suppressed_count`, `face_lookup_missing_count`) | in-repo subscribers | No in-repo consumer parses these keys today. Additive-only dict payload — legacy consumers use `.get()`-style extraction and are byte-identical for the fields they read. | No |
| `database.py:3593-3634` (persistence writers) | `identified_count`, `unidentified_count`, `total_persons` from `PersonCensusResult` | Unchanged serialiser; the values simply track the new (faster-drop) semantics. No schema change, no double-emit, no shape change. | No |

**Peak_refresh_suppressed_count** is monotonic-lifetime (documented, `# LIFETIME peak_refresh_suppressed_count is NOT reset here.` at camera_census.py:1140). No consumer treats it as a rate. Restart clears it (no RestoreEntity backing) — acceptable per plan's "diagnostic counter" framing but worth capturing in the README's live-validation table so operators aren't surprised by post-restart drops.

## Cross-cycle interaction with v5.79.0 (GUEST, just shipped)

- **Guest ENTRY gate** (`presence.py:5065-5129` — `unidentified_count > 0` AND `confidence >= threshold` AND `persistence 300s sustained`): unaffected by D1 on the reachable path — the `elif fresh==peak` early-return branch preserves `unidentified` output for the duration cameras genuinely see the person, so the persistence 300s gate still elapses under a legitimate guest.
- **Guest EXIT** (documented residual in v5.79.0 planning): D1 explicitly closes this by allowing `unidentified` to drop post-hold rather than lingering forever via peak self-refresh. Expected acceptance-criterion improvement, not a regression.
- **Reconciliation risk (two census-touching cycles back-to-back):** The v5.79.0 gate reads only the *shape* of the payload; new keys are additive; presence handler tolerates missing keys via `.get("...", default)`. The only *behavioral* delta v5.79.0 sees is a legitimate decay-slope change — consistent with v5.79.0's stated dependency on eventual `unidentified` decay.
- **B-HIGH-1 caveat:** if the D2 last_camera map fails first-call and never rebuilds, `face_recognized_count` under-counts → `unidentified_count` over-counts → v5.79.0 GUEST enters false-positive faster. This is the single cross-cycle regression vector — resolving B-HIGH-1 also fully closes it.

## D2 lifecycle assessment

- **Setup-time order:** map is lazy (built on first `_resolve_last_camera_entity_id` call), not at PersonCensus `__init__`. If Frigate is `after_dependencies`-loaded but not yet fully populated when the first census tick fires, the map bakes empty. **See B-HIGH-1.**
- **Reload of Frigate config entry:** map is stale. **See B-HIGH-1.**
- **Frigate not installed:** map builds empty, all lookups return None, `face_recognized_count` = 0, `unidentified_count` unaffected upstream. Correct fail-CLOSED.
- **Person added mid-run:** map is stale. **See B-HIGH-1.**
- **Defensive getattr:** legit init-order bug masker. **See B-LOW-2.**
- **`.pyc` staleness:** drill run with `PYTHONDONTWRITEBYTECODE=1` and cache purge; no false negatives from stale bytecode.

## Restart / reload resilience

- `_peak_refresh_suppressed_count`: lifetime counter, no RestoreEntity; clears to 0 on restart. Documented behavior; low-severity.
- `_face_lookup_missing_count`: per-tick reset; irrelevant to restart.
- `_frigate_person_last_camera_map`: initialised `None` in `__init__`; rebuilt on first post-restart resolve. Restart therefore RECOVERS from the B-HIGH-1 stale-cache condition — but a mid-run Frigate reload does not.
- `count_as_of`: computed fresh each dispatch/attr-read; no restore hazard.
- New payload keys default to safe values via `.get()` in the presence handler; no crash on legacy sender + new consumer or vice versa.

## Drill executed (per Review-B mandate)

Isolated worktree at `6bf4f4eee`, `PYTHONDONTWRITEBYTECODE=1`, `find . -name __pycache__ -exec rm -rf`. Mutated `_build_frigate_person_last_camera_map` to `return {}`. Ran `quality/tests/test_census_accuracy_d1_d2.py`: 4 failed / 10 passed as expected (BUILDER is behaviorally load-bearing). Restored + `git status` clean + worktree removed. Confirms the D2 map is on the wire; **does not** exonerate the lifecycle gap (no test covers "empty first build → later population" — that gap is the substance of B-HIGH-1).

## Recommendation

Fix B-HIGH-1 in-cycle (one-line change + one test). B-MEDIUM-1/2 addressable in-cycle or deferred with issue references. B-LOW-1/2 deferrable. On B-HIGH-1 landing + a green targeted re-run, this branch is ship-clear from Reviewer-B's framing.
