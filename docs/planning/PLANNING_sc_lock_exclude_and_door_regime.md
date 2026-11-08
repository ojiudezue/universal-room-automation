# PLANNING — SC lock sweep/lockdown exclusion + away-lock door rule

**Cards:** SC-LOCK-SWEEP-EXCLUDE-1 (tier 1 on the board) + SC-LOCK-REGIME-DOOR-LOCKS-1 (tier 2). Combined because the master-bedroom rule needs the exclusion to exist first.
**Tier:** 2 (see §9). One adversarial plan review before build. Not yet reviewed.
**Status:** rev 2, 2026-11-07 (operator answers folded in, §8). Plan only, nothing built.
**Parent:** GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 (lock regime, shipped v5.105.0). Plan of record for the regime: `docs/planning/PLANNING_sc_garage_remote_lockout.md` rev 5.

**Operator decisions (2026-11-07), as given:**
1. Register every lock in SC (`security_lock_entities`). Add a subset field: "exclude from sweep and lockdown". Excluded locks still show up in diagnostics (`doors`) and on the dashboard, but neither the periodic lock sweep nor a security lockdown ever locks them. Lockdown is for egress locks.
2. The master bedroom lock (passage mode, interior) goes back into the SC list, marked excluded. Today it is locked by hand only when Oji and Ezinne are both out. New rule: lock it when every configured person is away. Off by default, persons configurable. Build it inside the existing lock regime (`domain_coordinators/security_lock_regime.py`), reusing its person/away/arrival machinery. Release when any one of them arrives.
3. Options flow (`config_flow.py` step `coordinator_security`): put the SC lock list, the new exclude field and the garage lockout fields next to each other. Limit the distance-sensor picker to proximity distance sensors (today it accepts any `sensor`, so the operator could not find them). Update the labels in `strings.json` and `translations/en.json`.
4. Keep the validator that rejects overlap between the SC lock list and the lockout list. Add a check that the exclude list is a subset of the lock list.

---

## 0. Institutional context verified

### 0.1 Mandatory reads
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`: read completely (lines 1-853), because the rule consumes `person.*` state and `SIGNAL_PERSON_ARRIVING`. Relevant parts: the §1 table rows for the SC lock regime (raw `person.state` edges by design; `SIGNAL_PERSON_ARRIVING` is not a physical arrival, since `camera_face` fires on any zone camera); the `person_state_for_trust` row (trust readers vs edge readers); §7 (no GUEST → SLEEP edge, ledger #29). Nothing in the §10 ledger is re-asserted here.
- `docs/architecture/SENSOR_FLEET_CLASSES.md`: read completely. No sensor-class question arises; this cycle reads only `person.*` and proximity distance sensors.
- HVAC state-of-play: not applicable (no HVAC surface).
- `docs/Coordinator/SECURITY_COORDINATOR.md`: grepped for lockdown/sweep. Its sweep description predates the regime; the code below is authoritative.

### 0.2 Greps run (develop @ 5c10e98a)
```
grep -rn -e '"lock"' -e 'lock\.lock' -e 'SERVICE_LOCK' -e '"unlock"' --include='*.py' custom_components/
grep -rn -i -e lockdown -e lock_all -e CONF_SECURITY_LOCK_ENTITIES -e _lock_entities --include='*.py' custom_components/
grep -rn -A6 'ServiceCallAction(' --include='*.py' . | grep 'service='     # every non-SC ServiceCallAction
grep -n -e SECURITY_LOCK -e LOCKOUT -e LOCK_REGIME const.py
grep -n 'integration=' config_flow.py                                      # no precedent
grep -n 'EntityFilterSelectorConfig\|ENTITY_FILTER_SELECTOR_CONFIG_SCHEMA' .venv-ha/.../helpers/selector.py
git diff develop...fix/security-lock-sweep-retry-cap --stat
```

### 0.3 REUSE / NEW per piece

| Piece | Verdict | Evidence |
|---|---|---|
| SC lock list `CONF_SECURITY_LOCK_ENTITIES` | REUSED | `const.py:3406`; read at construction `__init__.py:3791` → `security.py:559` `self._lock_entities` |
| Overlap validator `lockout_overlap` | REUSED, extended alongside | `security_lock_regime.py:108-120`; called `config_flow.py:9058-9064` |
| Exclude list `CONF_SECURITY_LOCK_SWEEP_EXCLUDE = "security_lock_sweep_exclude"` | NEW | No exclude/skip key exists for locks: `grep -n 'SECURITY_LOCK' const.py` returns only `_ENTITIES` (3406) and `_CHECK_INTERVAL` (3415). The card's proposed name is kept. |
| Subset validator `lock_exclude_not_subset(lock, exclude)` | NEW, a pure helper next to `lockout_overlap` | Same `_as_set` coercion as `lockout_overlap` (`security_lock_regime.py:114-120`); extract `_as_set` to module level and share it |
| Live CM-options read | REUSED | `LockRegimeController._cfg` (`security_lock_regime.py:216-220`); SC reaches it through `self.lock_regime` (`security.py:660`) |
| Persons tracking (subscribe every person, added/removed domain trackers, persisted Store) | REUSED | `async_setup` `security_lock_regime.py:404-471`, `_on_person_added/_removed/_event` `:726-780` |
| "Arrival counts" + blip gate | REUSED | `_arrival_counts` / `_really_away` `:782-799`, `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` `const.py:3489` |
| P2 arriving signal | REUSED | `on_person_arriving` `:683-699` (already gated on `_really_away`) |
| Hazard release hook | REUSED, extended | `on_hazard` `:701-707`, fed from `security.py:2184-2201` |
| Unlock + read-back + one retry + HIGH NM | REUSED | `_spawn_unlock` / `_async_unlock` / `_on_readback` / `_notify_failure` `:945-1034`. Today these are lockout-specific in their wording, so the trigger/entity plumbing needs a `policy` arg (see D3) |
| Engage write discipline (synchronous predicate → call, no await between, `_engage_inflight`) | REUSED pattern | `_async_engage` `:1075-1103` |
| `_record` (decision log + activity log) | REUSED | `:1236-1287`. The activity-log description is hard-coded "Garage lockout ..." (`:1276`), so it needs a policy-aware description |
| Snapshot attrs on the SC status sensor | REUSED, extended | `snapshot()` `:1289-1296` → `sensor.py:7251-7256` |
| Options-backed switch class | REUSED | `SecurityLockoutOptionSwitch`, `_build_security_lockout_switches` `switch.py:5148-5180` |
| Away-lock kill switch `CONF_SECURITY_AWAY_LOCK_ENABLED = "security_away_lock_enabled"` | NEW | No away/both-out rule exists anywhere (`grep -rni 'away_lock\|both.*away' const.py switch.py domain_coordinators/security*.py` returns nothing relevant) |
| Away-lock entities `CONF_SECURITY_AWAY_LOCK_ENTITIES` | NEW | Same grep. Kept configurable rather than hard-coding `lock.master_bedroom_lock`: no entity IDs in code |
| Away-lock persons `CONF_SECURITY_AWAY_LOCK_PERSONS` | NEW | Distinct from `CONF_SECURITY_LOCKOUT_EXCLUDED_PERSONS` (`const.py:3449`), which has the opposite meaning ("never a resident"). Do not reuse it |
| Engage dwell `SECURITY_AWAY_LOCK_ENGAGE_DWELL_S` | NEW (rung 1) | No equivalent; `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` filters arrivals, not engages |
| Reload-suppress + no-live-attr key sets | REUSED | `__init__.py:7353-7358` (`_NO_LIVE_ATTR_KEYS`) and `:7648-7656` (CM `OPTIONS_RELOAD_SUPPRESS_KEYS`) |
| Distance-sensor selector filter | REUSED HA API, first use in URA | `EntitySelectorConfig` inherits `integration` / `domain` / `device_class` from `EntityFilterSelectorConfig` (`.venv-ha/.../helpers/selector.py:149-162, 179-185, 876-883`, HA 2026.2.3). Live HA is 2026.10.448 (`/config/.HA_VERSION`), see Q2 |

### 0.4 Prior plans and memory consulted
- `PLANNING_sc_garage_remote_lockout.md` rev 5 (full regime design: INV-2 no-await engage, INV-5 edge-only engage, M-2 boot exceptions, §3.3 overlap validator, §6.1a resident set). Line 487 records that the SC list held 3 locks, including `lock.master_bedroom_lock`.
- `PLANNING_nm_diag_text_menu.md:331` (the `doors` item reads `_lock_entities`).
- Cards: SECURITY-LOCK-SWEEP-RETRY-CAP-1 (status `review`, branch `fix/security-lock-sweep-retry-cap`, not on develop; it rewrites the same sweep loop, see §6 sequencing), SC-GEOFENCE-PERSON-SNAPSHOT-1 (adjacent, separate), SC-ARMING-ALARM-ONLY-1 (parked).
- Memory: `feedback_label_style_guide` (config-flow labels = short phrase + plain helper sentence; entity names ≤ 3 words), `feedback_config_first_before_code`, `feedback_parent_entry_reload_watchdog_hazard`, `reference_presence_state_of_play`.

### 0.5 Live config read (CM entry, `/config/.storage/core.config_entries`, 2026-11-07)
- `security_lock_entities` = `[lock.doorlock_kwikset_zwave_frontentry, lock.garage_hallway_doorlock_kwikset916_zwave_garagehallway]` (the master bedroom lock was removed today, per the card).
- `security_lockout_entities` = `[lock.ratgdov25i_dbfe2a_lock_remotes, lock.konnected_f0f5bd523b00_lock]`.
- `security_lockout_excluded_persons` = `[person.wall_kiosk]`. `security_lockout_distance_sensors` = `[]` (confirms the picker problem). `security_lockout_approach_zone` = `zone.home`. `security_lock_check_interval` = 60.
- **Master bedroom lock entity:** `lock.master_bedroom_lock` (entity registry; also `PLANNING_nm_diag_text_menu.md:331`, `PLANNING_sc_garage_remote_lockout.md:487`, card text).
- Proximity distance sensors in the registry (platform `proximity`, `original_device_class: distance`): `sensor.madronehaos_{oji_udezue,ezinne,ziri,jaya,nearest}_distance`.

### 0.6 Config-first check
No existing setting does this. Removing the lock from the SC list (what the operator did today) stops the battery drain, but it also hides the lock from `doors` and the dashboard, and there is no rule to lock it when both are out. An HA automation could do the both-away lock, but the operator asked for it in the regime, and an outside automation would get none of the regime's boot, blip and observation handling. So code is needed.

---

## 1. Falsifiable invariants

- **INV-X1 (exclusion).** For any legal options state, a URA `lock.lock` service call never targets an entity in `security_lock_sweep_exclude`, except one issued by `LockRegimeController`'s away-lock engage path (D3). It holds on every reachable path: the periodic sweep (every interval, any retry-cap state), lockdown (unknown person, security alert), the garage-lockout engage, restart, reload, and observation mode on or off.
  *Repro shape the reviewer should try to build:* exclude = `[X]`, X also in the lockout list (the validator rejects this, but an entry written before this cycle could still hold it). Expected: the runtime guard (D2c) still skips X.
- **INV-X2 (away-lock engage).** The away-lock engage issues `lock.lock` on entity E only if, at the moment the predicate passes (with no `await` between check and call): the kill switch is ON; E is in `security_away_lock_entities` ∩ `security_lock_sweep_exclude`; the persons list is non-empty; every listed person's current `person.state` is exactly `not_home` (a named zone such as `work` is NOT away; `home`, `unknown`, `unavailable` are not away) and has been for at least `SECURITY_AWAY_LOCK_ENGAGE_DWELL_S`; SC is running and not in observation mode; E reads `unlocked`.
- **INV-X3 (no foreign unlock).** The away-lock release issues `lock.unlock` only on an entity this policy locked and still owns (`away_lock_owned`, persisted). It never unlocks a lock a human locked.

Reviewer D's job is to break X1 first. The likeliest leak is a lock emission site this plan's §3 list misses.

---

## 2. Producer and consumer checks

### 2.1 Value: exclude set `security_lock_sweep_exclude`
- **Producer:** the options flow only (rung 2). It is read live from CM options at each use (`regime._cfg()`), not snapshotted. It is coerced with `_as_set` and intersected with `self._lock_entities`, so a stale entry for a lock no longer on the list has no effect.
- **Health:** the CM entry is always present while SC runs. If `lock_regime` is None (regime setup failed), the SC helper reads the CM entry directly through the same `_cm_entry` loop. **The fallback must never be "exclude nothing".** If the read fails, treat every lock as not excluded only when the key is absent; if the read raises, skip all *commands* to locks this tick, log a WARNING, and still record state. Fail closed toward not locking an interior door, because the sweep retries next interval anyway.
- **Consumers (all new reads):**

| Consumer | file:line (develop) | Trust or display | Change |
|---|---|---|---|
| Sweep command loop | `security.py:1736-1752` (`_evaluate_lock_check`) | trust (actuation) | skip command + retry-cap accounting for excluded locks |
| Lockdown | `security.py:1693-1708` (`_generate_lockdown_actions`; callers `:1086`, `:1629`) | trust | skip excluded |
| Garage-lockout engage | `security_lock_regime.py:1075-1091` | trust | runtime guard: skip excluded (defense in depth) |
| Sweep record `_last_lock_sweep` | `security.py:1844-1850` → `sensor.ura_security_last_lock_sweep` `sensor.py:7537-7595` | display | add `excluded: [...]`; excluded never appear in `found_unlocked` / `lock_actions_sent` |
| Unavailable NM | `security.py:1771-1822` | display / notify | **keep** excluded locks in it (a dead battery on the bedroom lock is worth knowing). Same 1/day dedup |
| Compliance `_lock_compliance` / `get_compliance_summary` | `security.py:1740-1742`, `:2580-2600` | display | drop excluded from `total` and `compliant`, otherwise the always-unlocked passage lock reads as permanent non-compliance |
| Aggregator `get_security_aggregator_state` | `security.py:2476-2576` | display (dashboard status) | drop excluded from `locks_total/locked/unlocked/jammed`; add `locks_excluded`. Without this, `status` can never reach ARMED (`:2554` needs all locks locked) |
| Diag `doors` | `house_status.py:133-147` | display | list excluded locks with the note "not auto-locked"; `unlocked` on an excluded lock is not flagged as a problem; `jammed` / `unavailable` still are |
| Hazard egress unlock | `security.py:2156-2170` | trust (safety) | **unchanged**: still iterates every SC lock, excluded included. Unlocking an interior door in a fire is correct (Q3) |

### 2.2 Value: away-lock "all persons away"
- **Producer:** new predicate `_all_away_persons_away(cfg, now_ts)` in the regime. For each person in `security_away_lock_persons`, it reads raw `person.state` from `hass.states` (the same raw edge reading as the lockout, per presence state-of-play §1, not `person_state_for_trust`). A person counts as away iff the state is exactly `not_home` (operator 2026-11-07: named zones do not count) and `_last_real[pid]` shows `not_home` held for at least the dwell. `_last_real` is already maintained by `_on_person_event` (`:776-780`), **but only for residents** (`_is_resident` filter at `:762`). An away-lock person who is also in `security_lockout_excluded_persons` would never be tracked. Fix: `_on_person_event` updates `_last_real` for every `person.*` and applies the resident filter only to the lockout release logic.
- **Dependency health:** `person.oji_udezue` / `person.ezinne` are HA person composites (GPS app + BLE). GPS `home` can be wrong in both directions (presence state-of-play §3, ledger #13 and #23). The direction that matters for engage is **false away while home**. That would lock the bedroom with Oji inside: a passage lock can be opened from inside, so the cost is an annoyance, not a safety risk. The dwell (300 s) plus the real-state requirement are the mitigation. The BLE-leads overrule (`person_state_for_trust`) only pushes a person toward away, so using it would *add* engages. Raw state is the conservative choice.
- **Restart:** `_last_real` entries stamped `restored=True` (`:770-772`) do not count toward the dwell. After a restart, engage needs one real transition, or a person who stays away through `GARAGE_LOCKOUT_BOOT_RECHECK_S` re-evaluated at the boot recheck (D3e).
- **Consumers:** only the away-lock engage predicate (trust) and `snapshot()` (display).

### 2.3 Value: `away_lock_owned` (set of entity ids)
- **Producer:** added only after the engage read-back sees the entity `locked` (D3b). A lock that did not take (passage mode on) is never recorded as owned. Cleared on release, and also when the entity is seen `unlocked` while there is no engage in flight (a human unlocked it, so we no longer own it). Persisted in the existing regime Store (`self._store`, key `"away_lock_owned"`, list of str), next to `"residents"`. The loader at `:410-425` accepts a missing key, so the schema is backward-compatible.
- **Consumers:** the release path (trust: X3) and `snapshot()`.

---

## 3. Emission / decision-site enumeration (`lock.lock` and lock commands)

Re-run by the plan reviewer independently. Grep: `grep -rn -e '"lock"' -e 'lock\.lock' --include='*.py' custom_components/` plus every `ServiceCallAction(` `service=` value.

| # | Site | Service | Iterates | This cycle |
|---|---|---|---|---|
| S1 | `security.py:1693-1708` `_generate_lockdown_actions` (callers `:1086` unknown person, `:1629` alert) | `lock.lock` | `_lock_entities` | filter excluded (D2a) |
| S2 | `security.py:1736-1752` `_evaluate_lock_check` (on the retry-cap branch: `_lock_retry_allows` inserted at the same loop) | `lock.lock` | `_lock_entities` | filter excluded **before** `_lock_retry_allows` and before the `found` list (D2b) |
| S3 | `security_lock_regime.py:1089-1092` `_async_engage` | `lock.lock` | `lockout_entities()` | runtime skip of excluded (D2c) |
| S4 | NEW: away-lock engage | `lock.lock` | `security_away_lock_entities` ∩ exclude | the sanctioned exception (D3) |
| U1 | `security.py:2156-2170` hazard egress | `lock.unlock` | `_lock_entities` | unchanged (Q3) |
| U2 | `security_lock_regime.py:597-600` disable release, `:945-950` `_async_unlock` | `lock.unlock` | lockouts | generalized for away-lock (D3) |
| C1 | `coordinator.py:1207-1212` + `config_flow.py:3363`, `:15491` AI-rule domain allowlist includes `lock` | any, operator-authored natural-language rules | rule targets | **carve-out, unchanged**: an operator-written AI rule is operator intent, not a URA policy. Stated in INV-X1 docs as out of scope |
| — | `energy.py:8045`, `safety.py:2701`, `:2820` (all other `ServiceCallAction`s) | light / valve / energy decision actions | — | not lock services (verified) |

No "Lock all" command exists in code (`grep -rni 'lock all\|lock_all'` finds only music-following `block_all`). The card's mention of "Lock all" is not a site.

---

## 4. Deliverables

### D0 — DROPPED as a gate (operator 2026-11-07)
HA exposes no passage-mode control on `lock.master_bedroom_lock` (only the lock, a door binary_sensor and battery), so URA can neither see nor change passage mode, and a probe could not separate "passage on" from "lock failed". Operator chose option B: build the away lock anyway; the operator turns passage mode off by hand when they want the rule armed. The passage-on cost is handled in D3b (one advisory per engage attempt, no ownership). Original probe text kept below for the record only.

#### (superseded) Probe: does `lock.lock` lock the master bedroom lock in passage mode?
The card says that sweeping it "won't lock it" because it is in passage mode. If passage mode makes `lock.lock` a no-op, then the away-lock rule (D3) cannot work without the operator leaving passage mode, and D3 should not be built as specified.
- **Do:** ura-prober reads the recorder for `lock.master_bedroom_lock` over the retention window: every `lock.lock` call context (URA sweep, 2026-11-07, while it was on the SC list) followed by the state 0-60 s later (`locking` → `locked`, or stays `unlocked`). Also read the device's passage-mode entity, if the integration exposes one (`switch.*`/`select.*` on the same device).
- **Gate:** if at least one URA `lock.lock` produced `locked` → D3 GO. If every call left it `unlocked` → D3 PARKED, with a revival trigger ("passage mode is a toggle URA can turn off, or the operator turns it off before leaving"). Ship D1 + D2 + D4 alone, and ask the operator (Q1).
- **Live:** n/a (the probe is the evidence; its result goes into this doc §10 before build).

### D1 — Config: exclude field, away-lock fields, validators, layout, selector scope
- New consts in `const.py` next to `CONF_SECURITY_LOCK_ENTITIES` (`:3406`), with rung comments (§5): `CONF_SECURITY_LOCK_SWEEP_EXCLUDE`, `CONF_SECURITY_AWAY_LOCK_ENABLED` + `DEFAULT_SECURITY_AWAY_LOCK_ENABLED = False`, `CONF_SECURITY_AWAY_LOCK_ENTITIES`, `CONF_SECURITY_AWAY_LOCK_PERSONS`, `SECURITY_AWAY_LOCK_ENGAGE_DWELL_S = 300`.
- `async_step_coordinator_security` (`config_flow.py:9033-9198`) field order: `security_lock_entities`, `security_lock_sweep_exclude` (EntitySelector `domain="lock"`, multiple), `security_away_lock_entities` (same), `security_away_lock_persons` (`domain="person"`, multiple), then the four lockout fields (`security_lockout_entities`, `_excluded_persons`, `_distance_sensors`, `_approach_zone`). After those come garage covers, entry sensors, lights, cameras, recording, alarm panel, auto-follow, interval, anomaly sensitivity. vol.Schema dict order is the render order.
- Distance-sensor selector: `selector.EntitySelectorConfig(multiple=True, filter=selector.EntityFilterSelectorConfig(integration="proximity", domain="sensor", device_class="distance"))`. Use `filter`, not top-level `integration` / `device_class`; it is the documented shape and the top-level keys are the older form. A stored value from outside the filter (today `[]`) stays valid: HA's entity selector validates format, not filter membership. Verify that on live HA (Q2). `sensor.madronehaos_nearest_distance` passes the filter. It maps to no person in `_person_for_sensor` (`:816-831`, `endswith(f"_{obj}_distance")`), so it is ignored harmlessly. Helper text says to pick one per resident.
- Validators, in order, each with an `errors[field]` key: (a) existing `lockout_overlap` → `lockout_overlaps_locks` (unchanged); (b) exclude ⊄ lock list → `errors["security_lock_sweep_exclude"] = "exclude_not_in_locks"`; (c) away-lock entities ⊄ exclude → `errors["security_away_lock_entities"] = "away_lock_not_excluded"`. An away-lock lock that is not excluded would also be swept, so it would be locked all the time; the check prevents that. Error strings go in `strings.json` + `translations/en.json` `options.error`.
- Labels (style guide: short phrase plus a plain helper sentence):
  - `security_lock_entities`: "Door locks" / "Every lock URA should know about. All of them show in Doors and on the dashboard."
  - `security_lock_sweep_exclude`: "Never auto-lock these" / "Interior or passage-mode locks. The lock check and a security lockdown leave them alone. Pick from Door locks."
  - `security_away_lock_entities`: "Lock when everyone below is out" / "Locked once all the people below are away, unlocked when any of them comes home. Must also be in Never auto-lock."
  - `security_away_lock_persons`: "People for the away lock" / "The lock above locks only when all of these people are away. Leave empty to turn the rule off."
  - `security_lockout_distance_sensors`: keep the label; helper adds "Only proximity distance sensors are listed."
- **Acceptance:**
  - **Test:** `test_sc_lock_exclude_options.py::test_exclude_subset_enforced` (exclude ⊄ locks → error key, nothing saved); `::test_away_lock_must_be_excluded`; `::test_lockout_overlap_still_rejected` (regression); `::test_field_order_locks_exclude_lockouts_adjacent` (schema key order); `::test_distance_selector_filter_proximity_distance` (the serialized selector config carries `integration: proximity`, `device_class: [distance]`); `::test_strings_have_new_keys` (strings.json and en.json both carry every new data / data_description / error key, and match each other).
  - **Discrimination:** the subset test must submit a valid lock list *with* an invalid exclude. A test that submits both empty passes under a missing validator too.
  - **Live:** open SC options; the four lock fields sit together; the distance picker lists exactly the 5 `madronehaos_*_distance` sensors; saving exclude = `[lock.master_bedroom_lock]` without adding it to Door locks shows the error.

### D2 — Exclusion at every lock emission site (S1, S2, S3) + display consumers
- **D2a** S1: `_generate_lockdown_actions` iterates `[l for l in self._lock_entities if l not in excluded]`. Garage covers unchanged.
- **D2b** S2: at the top of the lock loop, after the state read and `_lock_compliance` write, `if lock_id in excluded: excluded_seen.append(lock_id); continue` before the `locked`/`unlocked` branch. The `continue` sits before `_lock_retry_allows`, so excluded locks never open a retry episode. If an excluded lock is unavailable, it still goes on the unavailable list (§2.1). `_last_lock_sweep["excluded"] = excluded_seen`.
- **D2c** S3: in `_async_engage`, skip an entity in the exclude set with `engage_dropped_stale` `why="excluded"`. It cannot happen through the validated flow, but the guard means INV-X1 holds even for an options state written before this cycle.
- **D2d** display: compliance summary, aggregator (`locks_excluded`) and `doors` as in the §2.1 table.
- `excluded` is computed once per call via `self._sweep_excluded()` → `set(cfg.get(CONF_SECURITY_LOCK_SWEEP_EXCLUDE) or []) & set(self._lock_entities)`. It is captured once before the loop and passed down as a local, because the sweep awaits compliance scheduling later.
- Add `security_lock_sweep_exclude` to both `__init__.py` key sets (`:7353` and `:7648`), so editing only the exclude list does not reload the CM. It is read live. `security_lock_entities` stays reload-on-change, as today.
- **Acceptance:**
  - **Test:** `test_sc_lock_exclude.py::test_sweep_skips_excluded_unlocked` (excluded unlocked + normal unlocked → exactly one `lock.lock` action, for the normal lock); `::test_sweep_excluded_no_retry_episode` (after N sweeps, `_lock_retry_episodes` has no excluded key; this test lands with or after the retry-cap merge); `::test_lockdown_skips_excluded` (both callers: `_handle_unknown_person`-path and the alert path); `::test_lockout_engage_skips_excluded_runtime_guard` (exclude ∩ lockout written straight into options → no `lock.lock` on it, `why=excluded`); `::test_excluded_unavailable_still_notified`; `::test_aggregator_excludes_excluded` (all non-excluded locked + excluded unlocked + 1 camera streaming → `status == armed`, `locks_excluded == 1`); `::test_doors_excluded_unlocked_not_problem`; `::test_exclude_live_no_reload` (change options → next sweep honours it without reconstructing SC); `::test_hazard_unlock_still_includes_excluded` (U1 unchanged).
  - **Mutation anchors (framing C, builder pre-runs):** delete the S1 filter → `test_lockdown_skips_excluded` RED; delete the S2 `continue` → `test_sweep_skips_excluded_unlocked` RED; delete the S3 guard → `test_lockout_engage_skips_excluded_runtime_guard` RED.
  - **Discrimination:** the sweep test must include a *non-excluded* unlocked lock and assert that it IS commanded. A filter that drops every lock also passes "excluded not commanded".
  - **Live:** with `lock.master_bedroom_lock` added to Door locks and to Never auto-lock, run two sweep intervals (60 min). `sensor.ura_security_last_lock_sweep` shows `excluded: [lock.master_bedroom_lock]` and the lock is absent from `lock_actions_sent`. The recorder shows no `lock.lock` call with a URA context on `lock.master_bedroom_lock` (ground truth: `ssh ha` recorder query on `events`/`states.context_id`, not the sensor text). `doors` diag lists the bedroom lock with "not auto-locked".

### D3 — Away-lock rule in the lock regime (gated by D0)
In `LockRegimeController`, as a second policy beside the garage lockout. It shares persons tracking, Store, `_record`, and the unlock/read-back machinery. It has its own state and does **not** touch `self.reason`, `release_gen`, the backstop or re-engage. These belong to the garage policy; sharing them would couple the two policies.
- **D3a state:** `away_lock_owned: set[str]` (persisted), `_away_engage_inflight: dict[str, float]`, `_away_dwell_unsub`, `away_lock_last_action`.
- **D3b engage trigger:** in `_on_person_event`, after `_last_real` is updated (now for every `person.*`, §2.2), if the person is in the away-lock list, the kill switch is ON, and the new state is a real non-home state: (re)schedule a one-shot `call_later` at the latest dwell expiry across listed persons. It needs the `@callback` wrapper (`security_lock_regime.py:55-68`). When the timer fires, `_async_away_engage()` evaluates `away_lock_predicate(ent)` (INV-X2, synchronous) per entity and immediately awaits `lock.lock` (`blocking=False`, `_ctx_kwargs()`), with no other await between. In observation mode it records `away_would_engage` and writes nothing. Any listed person leaving `not_home` cancels the pending timer.
  **Engage read-back (passage-mode case):** after the call, one `call_later(GARAGE_LOCKOUT_READBACK_S)` read. `locked` → add to `away_lock_owned`, record `engage`. Anything else → record `engage_not_taken`, do NOT add to `away_lock_owned`, do NOT retry, and send at most ONE notification for that engage attempt at **LOW / advisory** severity (never HIGH), e.g. "Away Lock: <name> did not lock (passage mode may be on)". No new attempt until a listed person leaves `not_home` and the all-away condition forms again, so a lock left in passage mode yields one advisory per shared outing, never a stream.
- **D3c release triggers** (any of the listed persons): P1 `→ home` edge where `_arrival_counts` holds; P2 `on_person_arriving` for a listed person (already gated by `_really_away`); `on_hazard`; kill switch ON → OFF (`on_kill_switch_changed` routes by conf key, see D4); SC disable teardown (`async_release_if_disabled`). Release unlocks only `away_lock_owned` entities (INV-X3) through the existing `_spawn_unlock` read-back + one retry + HIGH NM, with `policy="away_lock"` so the NM and activity text say "Away Lock" (wording from the entity friendly name, not hard-coded). Release is a direct write; observation mode never suppresses it, matching the lockout.
- **D3d ownership loss:** a state listener on the away-lock entities (registered at setup, like `:451-456`) drops an entity from `away_lock_owned` when it reads `unlocked` with no engage in flight, and forgets the in-flight entry when it reads `locked`.
- **D3e boot:** no engage from replayed edges inside `_in_boot_window()` (INV-5 parity). At `_on_boot_recheck` (`:508`), evaluate the predicate once: if every listed person is away with a non-restored `_last_real` older than the dwell, engage. Otherwise wait for the next edge. Persisted `away_lock_owned` survives a restart, so an arrival after a restart still unlocks.
- **D3f snapshot keys:** `lock_regime_away_lock_enabled`, `_owned`, `_last_action`, `_pending_engage_at`.
- **Acceptance:**
  - **Test:** `test_sc_away_lock.py::test_engage_when_all_away_after_dwell` (two persons not_home ≥ 300 s → exactly one `lock.lock` on E); `::test_no_engage_one_home`; `::test_no_engage_named_zone` (one person `work`, other `not_home` → no engage); `::test_engage_not_taken_one_low_notice_no_ownership` (read-back `unlocked` → exactly one LOW NM, E not owned, no retry, no second NM until a fresh all-away formation); `::test_engage_taken_records_ownership`; `::test_no_engage_unknown_state` (one person `unavailable`); `::test_no_engage_before_dwell` (299 s); `::test_no_engage_kill_switch_off`; `::test_observation_mode_records_not_writes`; `::test_release_on_either_arrival` (P1 and P2, each releases); `::test_release_only_owned` (human-locked E, both arrive → no `lock.unlock`); `::test_manual_unlock_drops_ownership`; `::test_owned_survives_restart` (Store round-trip, arrival after restart unlocks); `::test_boot_replay_does_not_engage`; `::test_boot_recheck_engages_if_genuinely_away`; `::test_hazard_releases_owned`; `::test_kill_switch_off_releases_owned`; `::test_engage_target_must_be_excluded` (E not in exclude at runtime → no engage); `::test_empty_persons_inert`; `::test_away_person_also_lockout_excluded_still_tracked` (§2.2 `_last_real` fix); `::test_garage_policy_unaffected` (an away-lock engage and release leave `reason` / `release_gen` / backstop unchanged). Plus config-extreme tests: dwell 0 behaviour is defined by the rung-1 constant only (no knob), so it is tested by monkeypatching the constant to 0 → engages on the first away edge.
  - **Mutation anchors:** remove the dwell check → `test_no_engage_before_dwell` RED; remove the owned filter on release → `test_release_only_owned` RED; remove the `restored` exclusion → `test_boot_replay_does_not_engage` RED; record ownership before the read-back → `test_engage_not_taken_one_low_notice_no_ownership` RED; accept any non-home state → `test_no_engage_named_zone` RED.
  - **Discrimination:** `test_release_on_either_arrival` must have one person arrive while the other stays away. A rule wired to "all home" passes a both-arrive test.
  - **Live** (after the operator turns the switch ON and passage mode off): the next time Oji and Ezinne are both out, `sensor.ura_security_coordinator_status` attr `lock_regime_away_lock_last_action.action == "engage"`, and `lock.master_bedroom_lock` reads `locked` within 60 s (ground truth: entity state, not the attribute). On the first arrival, `action == "release"` and the lock reads `unlocked`. The disposition is a one-shot recorder query at the next shared outing, not a watch.

### D4 — Away-lock switch entity
- `_build_security_lockout_switches` (`switch.py:5148`) gains `SecurityLockoutOptionSwitch(conf_key=CONF_SECURITY_AWAY_LOCK_ENABLED, default=False, name="Away Lock", object_id="ura_security_coordinator_away_lock", icon="mdi:lock-clock", release_on_off=True)` (generic name, operator 2026-11-07).
- `release_on_off=True` routes to the regime. Today the release path (`switch.py:~5246`) calls `regime.on_kill_switch_changed`. It must dispatch by conf key, so turning the away lock off releases only away-lock-owned entities and turning the garage switch off releases only lockouts. Add the key to both `__init__.py` key sets.
- **Acceptance:** **Test:** `test_sc_away_lock.py::test_switch_off_releases_only_its_policy` (garage engaged + away engaged, away switch OFF → only E unlocked); `::test_switch_default_off`. **Live:** `switch.ura_security_coordinator_away_lock` exists, reads `off` after deploy, and survives a restart in the state it was left.

### D5 — Docs write-back
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §1 `person.*` row: add the away-lock reader (raw state, engage after a dwell, release on either arrival). Same commit as the build.
- `docs/Coordinator/SECURITY_COORDINATOR.md`: sweep/lockdown exclusion and the away-lock policy.
- `const.py:3443-3444` comment ("the sweep and lockdown iterate only security_lock_entities") gets "minus security_lock_sweep_exclude".
- README for the release (pre-deploy), with the validation table written back after restart.

---

## 5. Numbers and knobs

| Name | Value | Rung | Why | Kill / disable |
|---|---|---|---|---|
| `CONF_SECURITY_LOCK_SWEEP_EXCLUDE` | `[]` | 2 (options flow) | per-house structure (which locks are interior) | empty = today's behaviour, byte-identical |
| `CONF_SECURITY_AWAY_LOCK_ENABLED` | `False` | 3 (options-backed switch) | operator validates the rule live before relying on it | OFF = no away-lock writes; ON → OFF releases owned once |
| `CONF_SECURITY_AWAY_LOCK_ENTITIES` | `[]` | 2 | structure | empty = rule inert |
| `CONF_SECURITY_AWAY_LOCK_PERSONS` | `[]` | 2 | structure; the operator named Oji + Ezinne | empty = rule inert (never "all away" over an empty set) |
| `SECURITY_AWAY_LOCK_ENGAGE_DWELL_S` | 300 | 1 (module const) | a GPS-flap guard on a lock actuation; changing it should need review. 5 min is shorter than the 15 min arrival blip gate on purpose: a missed engage only means the bedroom stays unlocked (today's state), while a late engage costs nothing | 0 = engage on the first away edge (allowed, tested) |
| Reused: `GARAGE_LOCKOUT_READBACK_S` 20, `GARAGE_LOCKOUT_READBACK_RETRIES` 1, `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` 15, `GARAGE_LOCKOUT_BOOT_RECHECK_S` 120 | — | 1 | the same physical meaning for any regime lock | unchanged |

The reused constants carry a `GARAGE_` prefix but now serve both policies. Renaming them is a non-goal (churn on a shipped surface); add a comment at `const.py:3475-3489` saying they are shared regime constants.

---

## 6. Sequencing
1. ~~D0 probe~~ dropped (operator, §4 D0).
2. **D2 depends on SECURITY-LOCK-SWEEP-RETRY-CAP-1, as-is:** merges to develop first.** It rewrites the S2 loop (`fix/security-lock-sweep-retry-cap`, status `review`, waiting for a daytime deploy). Building D2b against develop now would cause a conflict in the same 30 lines, and its "no retry episode" test needs `_lock_retry_episodes`. If the operator holds the retry cap, D2b is written against develop and the retry-cap branch rebases. The orchestrator decides; this plan assumes merge-first.
3. Build D1 + D2 + D3 + D4 on one branch in a worktree.
4. After deploy, the operator re-adds `lock.master_bedroom_lock` to Door locks + Never auto-lock + the away lock, adds the persons, and adds the distance sensors. This is operator config, not part of the code ship.

## 7. Non-goals
- Door-lock policy beyond this one rule (night locking of egress doors, arming = alarm only: SC-ARMING-ALARM-ONLY-1 stays parked).
- Proximity (P5) or approach-zone release for the away lock. An interior bedroom door does not need an early release; `home` is enough. Parked, revival trigger: the operator reports arriving to a locked bedroom.
- Making the garage lockout's `GARAGE_*` constants policy-neutral by rename.
- SC geofence person snapshot (SC-GEOFENCE-PERSON-SNAPSHOT-1, separate card).
- Changing the AI-rule `lock` allowlist (C1).
- Changing which locks the hazard egress unlock covers (U1).
- Toggling passage mode from URA (only if D0 says it is needed, and then as a new card).
- Making `security_lock_entities` itself live-read (it stays reload-on-change).

## 8. Operator answers (2026-11-07, folded in)
- **Passage mode:** no HA passage-mode control exists on `lock.master_bedroom_lock`. Option B: build anyway; operator disables passage mode by hand. A `lock.lock` that does not take gives one LOW advisory per engage attempt and no ownership (D3b). D0 dropped as a gate.
- **Hazard unlock of excluded locks:** keep (U1 unchanged). References to "Q3" above mean this answer.
- **Switch name:** generic "Away Lock".
- **Excluded locks in the offline-lock notice:** keep.
- **Away:** `person.state == "not_home"` only; named zones are not away (INV-X2, §2.2, D3 tests).
- **Builder check still open (the "Q2" references above):** confirm the `filter=EntityFilterSelectorConfig(...)` shape on live HA 2026.10.448 (verified only in the 2026.2.3 venv source).

## 9. Tier classification
**Tier 2** (one adversarial plan review, two framing-disjoint code reviews, live validation). Triggers: new options fields, a new switch entity, a new actuation policy on a lock, edits to three emission sites. Not Tier 3: no reserve, money or HVAC value, and the worst reachable failure (an interior passage-mode door locked or unlocked at the wrong time) is a nuisance, not a safety or cost loss. The hazard egress path is unchanged. **Recommend operator elevation to Tier 2-DB (3 reviews)**, per the standing regression-prone policy: the change edits the shipped v5.105.0 regime's person-event handler (`_last_real` scope change, §2.2) and its switch release routing (D4), and a slip there could break the garage lockout release, which keeps a family member from being locked out at 3 AM. Suggested framings: A = local correctness of the predicate, filters and validators; B = regime integration (garage policy byte-identical, restart, Store, the in-flight race between engage and release); C = test authority via per-site mutation on S1/S2/S3 and the D3 anchors.

## 10. D0 result
Not run: dropped by the operator. No passage-mode entity exists to probe.
