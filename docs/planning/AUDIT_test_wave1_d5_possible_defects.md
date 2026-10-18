# AUDIT - Test Wave 1 D5: "possible real defects" triage

Run 2026-10-17 (CDT, `date` = 23:12 at start). Read-only. Tests re-run with
`PYTHONPATH=quality .venv-ha/bin/python -m pytest ...`; live reads via `ssh ha` (.storage JSON, read-only).
Presence/identity doc read for item 3: IDENTITY_FUSION_CAMERAS_MANUAL.md `_2` rules are consistent with the
census resolver behaviour cited below (Frigate-1 retired, `_2` permanent); verified against code, which wins.

## Summary

| # | Item | Verdict | Severity | Action |
|---|---|---|---|---|
| 1 | `__init__.py:4211` untracked `hass.async_create_task(fire_stuck_signal(` | REAL DEFECT (convention/lifecycle, small) | LOW | card; 1-line fix |
| 2 | Zone-delete enumerator misses 4 `hvac_ac_*_{zone_id}` sensor families | REAL DEFECT | MEDIUM | card; extend `id_prefixes` |
| 3 | Face resolver `_2` wiring | STALE TEST (production IS wired) | none | fix test clock |
| 4 | v5.7.1 B-1 RestoreEntity-OFF override | STALE TEST (harness bypassed); prod path unproven live | none/unknown | fix test stub |
| 5 | kanban_render `test_html_is_self_contained` | STALE TEST | none | update assertion |
| 6 | deploy_scripts SIGINT trap | REAL, env-dependent (gtimeout present) | LOW | card; or accept |

## 1. Untracked task at `__init__.py:4211` - REAL DEFECT (LOW)
- Test: `test_setup_unload_symmetry.py::TestNoUntrackedAsyncCreateTaskInScope` fails with exactly `line 4211: hass.async_create_task(fire_stuck_signal(` (re-run 2026-10-17).
- Code: inside `async_setup_entry` (def at `__init__.py:2215`), TOU-rejected branch, added 2026-09-14 (e5a0e5796, TOU-FILE-TOGGLE-AND-LOUD-FAILURE-1). `entry` is in scope; the file already uses `entry.async_create_background_task` (e.g. `__init__.py:2099`, 2818) and the test names that as the required pattern. No `# noqa: untracked-ok` justification.
- Mechanism: the task is not owned by the config entry, so it is not cancelled on entry unload/reload. `fire_stuck_signal` is fail-open (`_stuck_signal_nm.py` ~182-194: returns if NM missing) and short, so the practical effect is small: a reload racing the task could leave a notification coroutine running against torn-down state; the code comment ("will fire once NM is registered downstream") shows it is deliberately fire-and-forget but the justification marker was never added.
- User-visible effect: none observed. Live check: not cheap/meaningful (needs a rejected tou_rates.json). unknown whether the branch has ever fired.
- Fix shape: `entry.async_create_background_task(hass, fire_stuck_signal(...), name="tou_rate_file_rejected_signal")`.

## 2. Zone-delete orphans - REAL DEFECT (MEDIUM)
- Test: `test_zone_delete_flow.py::test_unique_id_prefix_enumeration_covers_all_known_families` fails listing sensor.py uids `hvac_ac_reset_day_count_zone_9`, `..._night_count_...`, `..._last_outcome_...`, `hvac_ac_ramp_durability_rate_zone_9`.
- Producer: `sensor.py:18658/18690/18721/18760` build `f"{DOMAIN}_hvac_ac_reset_day_count_{zone_id}"` etc. (added by 9ef7f4f91, 2026-08-22, after the zone-delete flow 4fa6bd009, 2026-07-10).
- Consumer: `config_flow.py:11657 _get_zone_entity_unique_id_prefixes` is the single source for the registry sweep (`config_flow.py` ~12083-12100, `startswith` against `id_prefixes`) and the preview count (~11814). The id list (config_flow.py ~11690-11702) has ramp_start/stop/reset/kwh_threshold/state/last_action/kwh_rate but none of the four new families, and `hvac_zone_{zone_id}_` does not match them.
- Live (`/config/.storage/core.entity_registry`, 2026-10-17): 12 matching registry entries exist, 4 per zone for zone_1, zone_2, zone_3 (e.g. `sensor.ura_hvac_coordinator_83_ac_reset_day_count_upstairs` uid `..._hvac_ac_reset_day_count_zone_2`). So the defect is reachable on a real zone delete.
- User-visible effect: deleting a zone leaves 4 orphaned diagnostic sensors in the registry (restored/unavailable entities), and the delete-preview undercounts entities. The post-sweep tripwire only logs a WARNING.
- Falsifier considered: other cleanup elsewhere (grep `ac_reset` in `__init__.py` shows only config-key plumbing) - none found.
- Fix: add four `f"{DOMAIN}_hvac_ac_..._{zone_id}"` prefixes. Beware prefix collision: `zone_1` is a prefix of `zone_10`/`zone_11`; existing prefixes share this property, so card should consider exact-match or trailing-delimiter handling.

## 3. Face resolver `_2` wiring - STALE TEST
- Both `test_face_resolver_finds_suffix_only_camera` AND `..._bare_canonical_camera` fail, so the failure is not `_2`-specific.
- Production: `domain_coordinators/presence.py:4913-4989` `_get_face_for_camera` calls `census._resolve_face_entity_id(base_name)` at :4967; resolver exists at `camera_census.py:3125`; census is registered at `__init__.py:2986`. The wiring exists.
- Root cause (reproduced in a scratch test): `presence.py` freshness check (:4981-4983) does `dt_util.utcnow() - state.last_changed`. The harness `dt_util.utcnow()` is tz-aware (tzinfo=UTC) while the test `_State.last_changed` is `datetime.utcnow()` naive -> `TypeError: can't subtract offset-naive and offset-aware datetimes`, swallowed by the function's blanket `except Exception: return None` (:4986). The test header says the harness stubs utcnow naive; that has drifted.
- Should assert: build `_State.last_changed` with `datetime.now(timezone.utc)` (or via the same `dt_util.utcnow()` the module uses). Note the blanket except makes this class of failure invisible in production too, but that is by design ("accelerator").

## 4. v5.7.1 B-1 restore precedence - STALE TEST (production correct on reading; not proven live)
- Test `TestD5Migration::test_restore_entity_off_overrides_options_true` fails in isolation (`assert True is False`). Production code `__init__.py:1775-1872` implements the override (restore_off -> `new_options[NEW_KEY]=False`, :1866-1869).
- Root cause (scratch probe): the helper does `from homeassistant.helpers import entity_registry as er` / `... import restore_state`. The test installs stubs only in `sys.modules`; `from pkg import submodule` resolves the parent package attribute first, and probe showed `homeassistant.helpers.entity_registry is sys.modules[...]` is False. So the real modules are used, the fake legacy entity is never found, and the logged line was `restore_off=False`.
- Should: also `monkeypatch.setattr(homeassistant.helpers, "entity_registry"/"restore_state", stub)` (restored automatically), or inject via `patch.dict`.
- Live: migration already ran. Config entry "URA: Coordinator Manager" options have `energy_precool_enabled: True`, no `hvac_solar_bank_enabled`; no `solar_banking` entity in registry or `core.restore_state`. Whether the operator's OFF was honored historically is unknown (evidence gone); current state is not wrong per se.

## 5. kanban_render `test_html_is_self_contained` - STALE TEST
- Fails because `scripts/kanban_render.py:1029-1031` emits `<link rel="stylesheet" href="https://fonts.googleapis.com/...">`, introduced deliberately by 919e894be (2026-09-12 board theme reskin, Hanken Grotesk/JetBrains Mono). Test (`test_kanban_render.py:123-131`) still bans `<link rel="stylesheet"` and `googleapis`. Other 13 tests pass.
- Decision needed from operator: either the board is allowed one Google Fonts dependency (update test to allow exactly that host, keep `<script src=` and `cdn.` bans) or self-host fonts to honor "self-contained". Not a runtime defect.

## 6. deploy_scripts SIGINT trap - REAL but environment-dependent (LOW)
- `test_v4710_trap_restores_clean_url_on_sigint` fails deterministically here (2 runs, 5.4 s each), not load noise. With a PATH that has no `gtimeout`/`timeout`, it passes (scratch run). This machine has `/opt/homebrew/bin/gtimeout`.
- Mechanism (inferred, not traced with strace): `scripts/dual-push.sh:92-110` wraps pushes in `gtimeout`; the test shim sleeps 5 s; bash defers its INT trap until the foreground child exits, so the script exits after about 5 s, racing the test's 5 s `proc.wait`. Whether coreutils timeout sits in a separate process group (so group SIGINT does not reach it) is UNCLEAR.
- Effect: Ctrl-C during a gitea mirror push would not restore the clean remote URL (token-bearing URL, see script header :5) until the push/timeout ends. Config risk window only, and trap runs eventually.
- Action: card or accept; test can set `GITEA_PUSH_TIMEOUT_SECS=0` to isolate.

## Side note
`docs/planning/KANBAN.md` shows a one-line regenerated-timestamp diff (23:12:12), which predates my test runs (first `date` 23:12:33); it is not attributable to this audit. No code or config was edited by me.
