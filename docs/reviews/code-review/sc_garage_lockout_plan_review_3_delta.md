# SC garage lockout — plan review 3 (delta, rev 3 → rev 4)

**Plan:** `docs/planning/PLANNING_sc_garage_remote_lockout.md` rev 4 (diff `da0ec039..HEAD`).
**Scope:** the rev 3 → rev 4 changes only, and whether each review-2 finding is closed. Read-only.
**Mandatory reads done:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 850 lines, §10 ledger through #29) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (all of it). No ledger claim is re-asserted here. Rev 4 does not contradict the ledger; #29 (no GUEST → SLEEP edge) agrees with §4.2.
**HA source checked:** `.venv-ha` pins HA 2026.2 (`homeassistant/const.py:18-19`).

**Verdict: FIX-PLAN** (local edits only, no re-scope). One HIGH: the H1 generation check runs at the wrong time. Three MEDIUMs. After these are fixed the plan can go to build without another review round. The orchestrator can check the edits.

---

## Verified (holds)

| Claim | Evidence |
|---|---|
| `coordinator_should_run` exists with the cited shape | `coordinator_gate.py:43-50`: reads the `*_enabled` key, then the entitlement hook. Pass `hass=None` from teardown, so no repair-issue side effects. |
| Switch writes the option before the reload | `switch.py:751-761`: `async_update_entry(... conf_key: False)` is synchronous and runs before `await async_reload(integration entry)`. The integration unload runs `coordinator_manager.async_stop()` (`__init__.py:5891-5894`), which awaits every `async_teardown()` (`manager.py:868-875`). So teardown can read `disabled`. |
| A normal HA restart does not run teardown | `config_entries.py:2176-2186`: on `EVENT_HOMEASSISTANT_STOP` HA only calls `entry.async_shutdown()`, and that only cancels setup retries (`:931-940`). It never unloads the entry. `manager.py:52-55` says the same thing. On an ordinary reload `should_run` reads True. So there is no spurious release on either path. |
| `async_track_state_added_domain` / `_removed_domain` exist and fire for `person` | `helpers/event.py:653`, `:711`. The filters at `:637-649` and `:687-699` trigger on `old_state is None` / `new_state is None` for any domain. They therefore fire for person entities, including storage-backed persons on deletion (any state removal). |
| `DistanceConverter.convert` signature | `util/unit_conversion.py:122` is the classmethod `convert(value, from_unit, to_unit)` (inherited, class at `:296`). An unknown unit raises `HomeAssistantError` (`:145-150`), so "rejected unit = no signal" has to catch that type. |
| Optimizer dispatch surface (re-enumerated) | Only one device service call: `optimization.py:4989`, inside `_dispatch_device_action` (`:4864`). Its only caller is `_apply_action` (`:4594`, called once at `:5224`). The config path (`:5138`) is limited to `number` / `select` (`const.py:4369`). The L1 shadow branch only fires an intent (`:4698-4703`) and makes no service call. Tier-1 findings all have `proposed_action=None`. LLM `service_data` is allowlisted, and `entity_id` is not on the allowlist (`const.py:4893-4915`, `optimization_llm.py:1226-1241`), so `service_data` cannot redirect the call away from `target_entity`. A Layer-1 block placed in `_dispatch_device_action` covers every reachable cover dispatch. |
| Payload has no `source` key (M1 premise) | `presence.py:2588-2594` passes `source="boot_settle_override"` with trigger `override_set`, as the plan says. |

## Review-2 closure

| R2 finding | Closed? | Note |
|---|---|---|
| C1 dead disable path | **Yes**, with M-1 below | The real path and the ordering are verified above. |
| H1 queued engage after release | **Partly** | See H-1. The evaluate-time check leaves an evaluate → execute window. |
| H2a advisory veto | Yes | The Layer-1 hard block is independent of SC. Placement: see L-1. |
| H2b fail-open helper / hollow test | Yes | The configured-list leg comes first, and the hollow test is dropped. |
| H3 blips / multi-trigger / timers | **Partly** | See M-2: the blip rule can strand a resident across a restart. (b)-(d) are fine. |
| M1 boot replay | Yes | The wording is wrong, but the conclusion holds (L-2). |
| M2 settled | Yes | L-3: the retry must re-check the whole re-engage row. |
| M3 hazard placement | Yes | |
| M4 units | Yes | Catch `HomeAssistantError`. |
| M5 / M6 (Phase 2) | Yes | |
| L1-L4, Q12, sequencing | Yes | |

---

## Findings

### H-1 HIGH — the H1 generation check runs at evaluate time, but the lock is written later (INV-2 still falsifiable)
`manager.py:969-1003`: the batch calls each coordinator's `evaluate()` in priority order and awaits each one. It then resolves conflicts and runs every action through `_execute_action`, which awaits `hass.services.async_call(..., blocking=True)` (`:1054-1060`) one after another. SC is priority 80 and is evaluated early. Every lower-priority `evaluate()` (presence, HVAC, energy, ...) and every earlier blocking action yields the event loop before SC's `lock.lock` runs. There is no pre-execute hook (`ServiceCallAction`, `base.py:121-126`).

**Repro:** SLEEP edge at 23:00:00.00 queues the engage. The batch fires at 0.10 s and SC `evaluate()` passes (`gen == release_gen`). While HVAC/energy `evaluate()` is awaited, Ezinne's P1 `not_home → home` fires at 0.15 s. The release bumps `release_gen` and its task issues `lock.unlock`. Then the manager executes SC's `lock.lock`. Result: a lock lands after the release with no new engage trigger. That is exactly the case INV-2 (rev 4) says can never happen. The 20 s read-back would probably see `locked` and retry the unlock, so in practice this heals in about 20 s. But the plan neither states nor tests that, and the invariant as written is false.

**Fix (pick one, state it in §6.1a H1):**
- (a) Move the gate to execute time. The regime owns the engage write: `evaluate()` returns no `ServiceCallAction`; it hands the decision to the regime, which re-checks `gen` (and kill switch, house state, settled) synchronously right before its own `async_call`. Observation mode is still honoured by the regime.
- (b) Keep the action, and make the release's read-back the named compensator. It must run after any in-flight engage: track an `engage_inflight` flag that is set at evaluate and cleared after execute, and have the release re-read once the flag clears.

Add `test_release_between_evaluate_and_execute_no_lock_survives`. Drive a real manager batch with a lower-priority coordinator whose `evaluate()` awaits and fires the arrival.

### M-1 MEDIUM — teardown must read the LIVE CM entry, not SC's construction snapshot
SC is built from values copied out of `cm_config` (`__init__.py:3789-3812`) and holds no entry reference. A builder who reads "merged CM data+options" from anything captured at setup will get `security_coordinator_enabled: True`, and C1 silently never fires. State it explicitly: at teardown, look the CM entry up live via `hass.config_entries.async_entries(DOMAIN)`, the REUSE pattern of `OptimizationCoordinator._read_cm_config` (`optimization.py:4314-4322`). Also tighten the test: its fake reload should call `coordinator_manager.async_stop()`, not SC teardown directly. Otherwise the integration-unload → manager → teardown chain has no anchor (L-5).

### M-2 MEDIUM — the blip rule can strand a resident who arrives during a restart
HA `person` restores its last state on add (`components/person/__init__.py:467-468`), then waits for `EVENT_HOMEASSISTANT_START` (`:470-482`). If all its trackers are unavailable at that point, it writes `unknown` (`:551-552`).

**Repro:** Ezinne is `not_home` at 02:00 when HA restarts. She drives in during the restart. The person restores `not_home` (SC sees `old_state None` → `not_home` and stamps `last_real_state` with the boot timestamp). At start the trackers are unavailable → `unknown`, then `home` at T+40 s. The blip rule needs `not_home` held for ≥ 15 min, but the stamp is seconds old, so no P1. P5's first reading after unknown is not a crossing (M4). The boot recent-arrival rule runs only at setup. ARRIVING needs AWAY, and the house is SLEEP. Result: the lockout stays locked until 07:00. Release is the safe direction to over-fire.

**Fix:** a `→ home` edge counts unconditionally when it arrives inside the boot window, or when `last_real_state` was recorded from an `old_state is None` (restore) write. Test `test_restart_restore_then_unknown_then_home_releases`.

### M-3 → rated LOW (REUSE): Layer 1 duplicates an existing chokepoint
`_check_safety_denylist` (`optimization.py:4539-4588`) already runs for every reversible-device action, at every level (`:4691-4695`), using the `cm_config` read in `_apply_action` (`:4632`). `_check_reserve_role_hard_deny` (`:4875-4879`) is the hard-deny shape at the top of the dispatch method. Extend one of these with the owned-cover predicate. Do not add a third parallel block next to `egress_paused`. Config-first note: listing both garages in `CONF_OPTIMIZER_SAFETY_DENY_ENTITIES` closes the optimizer hole today, before Phase 1 ships, with no code.

### L-2 LOW — M1 states the setup order backwards
The plan says "when SC is set up first". In fact Presence is set up before SC: `register_coordinator(presence)` is at `__init__.py:3755` and `register_coordinator(security)` at `:3813`, and setup follows dict insertion order (`manager.py:493-499`). So Presence's 60 s failsafe starts earlier and the replay lands even more surely inside SC's 120 s window. Fix the sentence. The replay runs on a later inference tick, not exactly at release, so state that the margin (≥ 60 s) covers the tick latency.

### L-3 LOW — the evaluate-time condition list omits the re-engage row's own conditions
The re-engage row in §6.1 also requires "both doors closed, house SLEEP, before `sleep_end_hour`". H1's list names only the gen, the kill switch, SC enabled, house state and settled. With M2 re-checking every 900 s for up to 3600 s, a retry could run past `sleep_end_hour`. Say that every retry re-checks the full row.

### L-4 LOW — stale rev 3 text still reads as the spec
- §6.1 table row "SC enabled True → False … setter override" (plan line ~215).
- The setup row "resolve `CONF_SECURITY_LOCKOUT_RESIDENTS`" (~218).
- §11 reviewer-B framing "setter override fires on disable but not on teardown" (~442).

"§6.1a wins" is a rule for the builder to remember. Strike these rows inline instead; this is the build-prediction class review 2 exists for.

### L-5 LOW — `person` removal on an integration reload
`removed_domain` fires on any state removal. That includes a `person` reload or re-add, not only a deletion. Dropping the person from `releasing_set` at once lets a re-engage pass while that resident is still en route. Keep the member until it is re-added or `GARAGE_LOCKOUT_REENGAGE_MAX_WAIT_S` passes.

### L-6 LOW — unnamed residual: integration disabled or deleted
Disabling or deleting the integration/CM entry tears SC down with `should_run` still True, so there is no release, and URA is gone with the lockout `locked`. Name this in §5.2 next to "SC disabled across a restart".

### Note (parsimony, no action required)
The persisted resident Store is functionally redundant. Subscribing by id (`async_track_state_change_event` works before the entity exists) plus `added_domain` already covers persons that load late. Its only output is the boot diff log. This is the operator's ask, so keep it. A store-load failure must not block the listeners.

### Hollow-test scan (rev 4 additions)
No new source-grep tests. `test_regime_never_emits_cover_service` and `test_only_auto_open_module_emits_cover_open` are now behavioural. The H1 test set misses the execute-time window (H-1). The C1 switch test is only half-anchored (M-1 / L-5).

---

**Must-fix before build dispatch:** H-1, M-1, M-2. LOW items are cheap and should be fixed in the same edit.
