# Code review B: house-state step 1a (integration, lifecycle, restart)

- Branch: `feature/house-state-step1a` @ 1c602a1b. Diff base `7d826060`, checked as `git merge-base HEAD develop` (develop is one docs-only commit ahead, b39736ac).
- Plan: `PLANNING_house_state_axes_step1.md` rev 3, Part A.
- Framing B: async work, lifecycle, restart and store migration, listeners and teardown, cross-coordinator wiring (presence / security / perimeter / NM), whether a legitimate unlock or alert is suppressed, and whether the no-op path is byte-identical.
- Before reviewing I read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` in full. Nothing below re-asserts a §10 ledger claim.

## Verdict: FIX-REQUIRED (one HIGH)

## Findings

### B-H1 (HIGH): the residency producer never matches a live resident. Records, `residents_home` and the ARRIVING evidence are dead in production.
Bug class: #63 / hollow test anchor (#62). Test fakes use one identifier form and production uses another.

- **Code.** `presence.py` `_residency_residents` (new, about line 5235) maps `tracked_persons` entries with `f"person.{p}"` and does not normalise them.
- **Where the values come from.** `PersonTrackingCoordinator.tracked_persons` is `integration_entry.data[CONF_TRACKED_PERSONS]` (`person_coordinator.py:166`). Live `.storage/core.config_entries` holds `data = ['Ezinne', 'Oji Udezue', 'Jaya', 'Ziri']`; the entity-id form `['person.ezinne', ...]` exists only in `options`. The person coordinator builds ids itself as `f"person.{name.lower().replace(' ', '_')}"` (`person_coordinator.py:979`).
- **Result.** The resident set is `{"person.Ezinne", "person.Oji Udezue", "person.Jaya", "person.Ziri"}`, and no event pid is in it:
  - `on_event` writes no record for any resident;
  - `get_residents_home()` calls `person_state_for_trust(hass, "person.Oji Udezue")`, which finds no state, so the count is always 0;
  - `sensor.ura_presence_coordinator_residents_home` reads 0, and the house-state attribute `residents_home` reads 0;
  - the ARRIVING evidence is always False, so every ARRIVING exterior alert resolves CRITICAL. D0 P1(a) estimated added pages assuming the softening works, so the live page rate is above that estimate.
  - Live checks L1 and L3 fail.
  - The writer-health absence exemption (`MEMORY_WRITER_HEALTH_ABSENCE_EXEMPT_TYPES`) means no zero-fire trip-wire catches the silence.
- **Repro (run, then removed).** `_coord(tracked=["Oji Udezue", "Ezinne"])` from `test_residency_wiring.py`, then feed `person.oji_udezue` `not_home -> home` at T+5000 s. The tracker's `recent` stays `[]`.
- **Why the tests miss it.** Every fake (`test_residency_wiring.py:51-90`, `test_residency_tracker.py`) uses entity ids.
- **Fix.** Normalise exactly as the person coordinator does: keep entries that already start with `person.`, otherwise `person.{p.lower().replace(' ', '_')}`. Add an anchor test that uses display-name `tracked_persons` (`"Oji Udezue"`) and asserts one record plus residents_home 1.
- The lock regime is not affected, because it uses the live `person` domain minus exclusions.

### B-L1 (LOW): residency teardown is awaited first and can take up to 5 s
`presence.async_teardown` awaits `_async_teardown_residency` (5 s bound) before cancelling the fan-belief timers, the sighting producer and `_unsub_listeners`. On a slow write queue, other presence timers and listeners stay live for that time on a coordinator that is being torn down. No correctness break was found: `_persist_residency_event` returns once torn down, and the DB is closed later (`__init__.py:5932` before `:5978`). Fix: set the flag first and move the gather to the end of `async_teardown`.

### B-L2 (LOW, rollback only): the migration is one-way
1a drops `garage_arrival_taint` from the next save. A rollback to v5.108.18 mid-episode reads the taint as False, so an ARRIVING-then-HOME_* edge would release again. This is acceptable because the rollback restores the older, laxer rule. Name it in the README rollback note.

## Cleared (evidence)

| Area | Holds because |
|---|---|
| Store migration | `_load_away_store` sets `_episode_saw_empty = saw_empty is True or legacy taint is True` (`security_lock_regime.py:3050-3054`). `async_setup` calls `_save_store()` after the load (~:641), and `_store_payload` replaces the whole dict, so the legacy keys are gone after the first save. The legacy `garage_episode_saw_arriving` key was always written together with the taint, so dropping it loses nothing. `_boot_rebuild` clears a stale flag when nothing is locked, the kill switch is off, or the house is SLEEP / VACATION. |
| Restart in an awake house with a `boot_unknown` lock (delta L2) | The recheck returns `house_edge_ignored`. Before that, `_boot_rebuild` scheduled the backstop with `allow_immediate=True` (`_backstop_delay_s` :559), which is 0 s in the day before sleep start. So a daytime restart still releases at once (trigger `backstop`, which the trip-wire exempts). Only a restart between sleep start and midnight waits for the morning. Matches plan. |
| Backstop discharge (M1) | `_cancel_backstop` callers are unchanged. The arrival branch of `_after_release` does not cancel it. |
| Operator triggers reach the lock | `HouseStateMachine.set_override` / `clear_override` call `on_state_change(..., "override_set" / "override_clear")` (`house_state.py:283, 314`). The manager adapter passes the trigger to `_dispatch_house_state_change` (`manager.py:772`). The select (`select.py:277`), `ura.set_house_state` and `clear_house_state_override` (`__init__.py:6210-6237`) all go through it. The inline override reset inside `transition()` dispatches with the inference trigger, which is correctly treated as non-operator. |
| Trip-wire false pages | The only `house_state:*` release site is :946. Boot-recheck `release` is reachable only for `waking` (`_edge_decision` without the operator flag), which is exempt. `backstop`, `person:*`, `hazard` and `kill_switch_off` are not house triggers. |
| Ignored edge keeps the episode | The `house_edge_ignored` return comes before the `kind == "none"` manual-unlock clear (:950-959). |
| Producer wire-in | `_handle_geofence_change` is `@callback`. `_feed_residency` runs before the `old_state is None`, unavailable and observation returns and never raises. `hass.async_create_task` is called from the event loop. Tasks are tracked, done-discarded and gathered with `return_exceptions`; on timeout `wait_for` cancels them. |
| Reload / person coordinator popped | `_residency_residents` re-reads `hass.data` on every call. A popped person coordinator gives unresolved records, which `recent_arrival` skips (fails toward CRITICAL). A CM reload rebuilds the tracker with a fresh 600 s window (fail-safe). |
| Cold ledger after restart | The tracker's ledger starts empty, so a post-window `unavailable -> home` counts (prev_real None). Develop's lock has the same behaviour (M-2 ii, INV-RULE parity). For severity it only softens when a resident just returned. Not new. |
| Byte-identical no-op paths | `HouseOccupiedBinarySensor` gives the same truth table (manager None -> False; AWAY / VACATION -> off). The fan-gate `_phone_trustworthy` delegation is equal on every input, error paths included (empty slug and a raising `states.get` both still give trustworthy). `_run_inference` (:7105) and `_dispatch_house_state_change` (:9476) have no hunks. `house_state.py`, `select.py` and `manager.py` are untouched. |
| Retired symbols | `git grep` finds no `arrival_taint` / `saw_arriving` / `arriving_hold` / `lock_regime_arriving_*` in `custom_components` apart from the migration read. |
| Perimeter | `_presence()` reads `coordinators.get("presence")`. The evidence code has its own try/except, so it fails to False and then CRITICAL. With `persons_home` switched off it returns 0 without touching presence. |

## Invariant checklist (framing B view)
- INV-MACHINE: PASS (no hunks).
- INV-LOCK: PASS (decision is (new, reason, operator); trigger plumbing verified).
- INV-REAL: PASS (the person path is unchanged; rule delegated verbatim).
- INV-PAGE: PASS (store migration and the boot sets match the taint set).
- INV-PRODUCER: **LEAK in production (B-H1)**: no resident record under the live display-name config.
- INV-SEV: holds only in the fail-closed direction, because of B-H1 (evidence never True).

## Must-fix
1. B-H1: normalise `tracked_persons` in `_residency_residents`, and add a display-name anchor test.
