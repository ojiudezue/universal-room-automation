# Review A — RELOAD-WATCHDOG-HAZARD (D1/D2/D3) + OPT-META-BOOT-TRANSIENT-1

**Framing:** correctness + config/data integrity.
**Branch:** `feature/reload-optmeta` (worktree `.claude/worktrees/reload-optmeta`).
**Build range:** `33352c34d..6b1afdcb4` (4 commits) vs merge-base `0bf8d3e00` on `develop`.
**Plan:** `docs/planning/PLANNING_reload_watchdog_hazard.md` rev-2 + plan review `bf8ee9f65`.
**Card:** OPT-META-BOOT-TRANSIENT-1.

## Verdict: **DO NOT SHIP** — one HIGH (H-1) neutralises the D2 suppress on the exact scenario the cycle was written to fix; one MED (M-1) is a staleness leak in the opt-meta fallback.

Correctness of the changed-keys computation, the subset check, the kill-switch gate, the dispatch helper, the parity with the CM branch, and the D1 audit spot-checks all check out. The dead-import removal is genuinely dead. Test authority for the load-bearing subset check is confirmed by mutation. But: on a cold HA restart the `integration_last_applied_options` snapshot is not seeded, so the FIRST post-restart Camera Census save is treated as "all-keys changed" and falls through to the legacy reload path — reproducing the ~5-minute watchdog outage the cycle exists to prevent.

---

## Findings

### H-1 — `integration_last_applied_options` is never seeded at INTEGRATION setup; suppress branch is DORMANT on the first post-restart save. **HIGH, must fix pre-ship.**

**Site:** `custom_components/universal_room_automation/__init__.py:6589-6624` (the INT branch of `_async_update_listener`) — and the absent seed call in the INT-setup path at `:1596-…`.

**Mechanism (falsifiable):**
1. `hass.data[DOMAIN]["integration_last_applied_options"]` lives in RAM. On HA start it does not exist. It is only ever populated by (a) the suppress branch after a successful in-place apply (`:6616`), or (b) the fall-through reseed (`:6622-6624`).
2. There is NO analogue of `_seed_cm_last_applied_options(hass, entry)` (called for CM at `:4265`) in the INT setup path. Grep confirms: `grep -n "integration_last_applied" __init__.py` returns only the two listener sites plus the LOW-4 comment. No setup-time seed exists.
3. Therefore on the first post-restart options save on the INTEGRATION entry, `old = snapshots.get(entry.entry_id, {}) = {}`. The changed-keys computation `{k for k in (old.keys() | new.keys()) if old.get(k) != new.get(k)}` reduces to `set(new.keys())` — the full options dict.
4. The Camera Census OptionsFlow submits a `{**existing, **user_input}` 9-key dict (per plan review context); `new.keys()` therefore contains ~9 keys, not a subset of the single-element `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`.
5. The `changed_keys.issubset(...)` gate is FALSE. Control flow reseeds the snapshot at `:6622` and continues past the `if entry_type == ENTRY_TYPE_INTEGRATION:` block into the generic reload scheduler at `:6636`. **Full cascading reload. Outage reproduces.**

**Reachable repro:** HA restart → operator opens Camera Census options → changes only `camera_person_entities` → clicks Save. First post-restart save; snapshot empty; suppress dormant; reload cascades to ~40 child entries; ~5-minute event-loop stall; supervisor watchdog restart. This is precisely the 2026-08-07 outage. The suppress branch begins working only on the SECOND save (once the fall-through reseed at `:6622-6624` has populated the snapshot).

**Why the tests don't catch it:** every test in `test_reload_watchdog_hazard.py` (spot-checked at `:302, :329, :348, :390, :410`) seeds `hass.data[DOMAIN]["integration_last_applied_options"][entry.entry_id]` explicitly in its Arrange block, matching the second-save state. There is no test for the empty-snapshot first-post-restart case.

**Fix (mirror CM):**
- Add a `_seed_integration_last_applied_options(hass, entry)` helper (or reuse a generic seeder) and call it at the end of the `ENTRY_TYPE_INTEGRATION` setup path at `:1596-…`, adjacent to the update-listener registration (per the comment at `:1601-1605`, the seed must happen BEFORE that listener is armed — same ordering rule as CM at `:4265`).
- Add a regression test that (a) does NOT pre-seed the snapshot, (b) fires the listener with a single-key options change equal to the allowlisted key, and (c) asserts `reload_calls == []`. Today this scenario reloads.

**Bug class:** #24 "Boot-transient / warm-cache assumption" (also close to #7 stale-data-source and the CM B-HIGH-2 lineage).

---

### M-1 — OPT-META boot-seed fallback is not cleared after the first cycle, causing stale (resolved) findings to re-enter the corpus whenever `_last_findings` is subsequently empty. **MEDIUM.**

**Site:** `custom_components/universal_room_automation/domain_coordinators/optimization.py:557` (comment claims "cleared implicitly once the first post-boot cycle populates `_last_findings`") + `optimization_llm.py:680-696` (fallback branch).

**Mechanism (falsifiable):**
1. The coordinator assigns `self._last_findings = all_findings` at `optimization.py:1027` unconditionally on every cycle.
2. If a cycle legitimately produces zero findings (healthy house — nothing to report), `_last_findings = []`.
3. `optimization_llm.py:657` gates on `if ram_cache:` — an empty list is falsy → falls back to `_boot_findings_seed`.
4. `_boot_findings_seed` is NEVER cleared or invalidated after `async_setup`. It permanently holds the 200 rows read from `optimization_findings` at boot.
5. Result: a healthy tick re-injects UP TO `_MAX_RECENT_FINDINGS` rows of pre-restart findings — many of which may now be resolved — into the LLM meta corpus for the remainder of the session. The false-HIGH the cycle is written to prevent is not re-fired, but the LLM sees a stale corpus.

**Not a regression** — pre-cycle, the fallback did not exist, and the meta pass saw `findings_recent=[]`. But the "cleared implicitly" claim in the source comment (and the plan) is false: the code does not clear, and the fallback fires again whenever the RAM cache is empty.

**Fix (small):** set `self._boot_findings_seed = []` (or a one-shot flag) the first time the coordinator completes a cycle — regardless of whether findings were produced. Preferred site: bottom of the cycle in `optimization.py` after the `_last_findings = all_findings` write. One line + one anchor test that (a) seeds boot cache, (b) runs a zero-finding cycle, (c) asserts assembly returns `[]` on the next tick.

**Bug class:** #7 stale-data-source (RAM-side variant).

---

### L-1 — Redundant `hass.data.setdefault(DOMAIN, {}).setdefault(...)` in the fall-through reseed block. **LOW / hygiene.**

**Site:** `__init__.py:6622-6624`.

`snapshots` is already the same dict obtained at `:6590-6592` via the identical `setdefault` chain. Re-fetching adds a second dict lookup and mildly obscures intent. The CM branch (`:6573-6575`) does the same thing, so this is parity-preserving, not a regression — but the comment there notes "defensively in case `hass.data[DOMAIN]` was cleared between the suppress-branch entry and here", which is impossible in the async path (no await between `:6590` and `:6622`). Replace with `snapshots[entry.entry_id] = dict(entry.options)` for clarity, or leave for CM parity. Not shipping-blocking.

**Bug class:** none — hygiene.

---

### L-2 — `_dispatch_integration_key_signals` dispatches per-key even though today's table maps every key to the same signal `ura_transit_config_changed`. **LOW / observation.**

**Site:** `__init__.py:5936-5963`.

If a future v2 admits both `camera_person_entities` and `egress_cameras` to the allowlist (parked follow-up #1), and both map to the same discharge signal, this helper will dispatch that signal twice per save. Not a correctness bug today (single-key allowlist, single-signal table), but a foreseeable duplication when the table grows. Consider de-duplicating signals before dispatch: `for sig in {s for k in changed_keys for s in _INTEGRATION_KEY_SIGNAL_TABLE.get(k, ())}:`. Not blocking.

**Bug class:** #27 mirror-drift (adjacent).

---

## Spot-checks against D1 audit — 3 keys, re-verified

| Key | Audit verdict | Re-verified? | Notes |
|---|---|---|---|
| `CONF_CAMERA_PERSON_ENTITIES` | SAFE-WITH-DISPATCH | ✅ | `camera_census.py:1801` fresh via `_get_integration_camera_list`; `fan_veto.py:353` fresh via caller-passed `config`; `transit_validator.py:26,247` caches — audit's SIGNAL_URA_TRANSIT_CONFIG_CHANGED subscribe+dispatch chain is the only refresh path. Verdict correct. |
| `CONF_EGRESS_CAMERAS` / `CONF_PERIMETER_CAMERAS` | NEEDS-DISCHARGE-WORK (dropped from v1) | ✅ | `perimeter_alert.py:410-411` caches at setup via `_resolve_camera_infos`; the `:1622-1623` hits are static tuple constants, NOT a re-subscription. Correctly excluded from v1 allowlist. |
| `CONF_ELECTRICITY_RATE` | NEEDS-DISCHARGE-WORK | ✅ (weaker) | grep of `domain_coordinators/` returns zero consumers; only config_flow hits exist. Actual consumers may live elsewhere (energy_* modules) or the key may be dead — either way, not in v1 allowlist is safe. |

---

## Mutation drill (D2 subset-check, load-bearing verification)

`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared per site policy.

Mutation: replace `changed_keys.issubset(INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS)` with `True` at `__init__.py:6606`. Result:

```
FAILED test_integration_options_mixed_falls_through_to_reload
  AssertionError: assert [] == ['integration_entry_id']
=========== 1 failed, 6 passed in 0.20s ===========
```

Subset check is load-bearing; test `test_integration_options_mixed_falls_through_to_reload` catches its bypass. Source restored (`git status` clean). D3 dispatch line already carries its own load-bearing test at `:410` (per author).

---

## OPT-META boot-seed ordering (no race in normal flow)

The boot seed is populated inside `optimization.py:async_setup` after `await db.get_recent_optimization_findings(...)`. The coordinator's periodic tick starts only after HA finishes awaiting `async_setup`. There is no code path that runs the LLM meta pass concurrently with async_setup. No ordering race.

Edge: if the DB is momentarily unavailable at boot (`db is None` or method missing), the seed stays `[]` and the fallback branch degrades to the pre-cycle behavior (false-HIGH). Not a regression, not a new bug — plan explicitly scoped OPT-META as best-effort seed.

---

## Byte-parity with CM `_apply_in_place`

The plan's non-goal is that `_apply_in_place` is byte-identical after this cycle. Diff confirms: this build does not touch `_apply_in_place` (the INT branch uses the sibling helper `_dispatch_integration_key_signals` at `:5936` — a separate function, not a branch inside `_apply_in_place`). Non-goal preserved. Bug Class #27 primary/deferred mirror-drift risk avoided.

---

## binary_sensor.py dead-import removal

`grep -n "CONF_CAMERA_PERSON_ENTITIES" binary_sensor.py` returns exactly one hit post-removal: the comment at `:59-61`. Confirmed the entity-key literal `"camera_person_detected"` elsewhere in the module is a distinct string, not this CONF. Genuinely dead. ✅

---

## Test run

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=quality python3 -m pytest \
  quality/tests/test_reload_watchdog_hazard.py \
  quality/tests/test_opt_meta_boot_transient.py -v
```
→ 10 passed. Also `test_cm_reload_suppression.py` and `test_part2_ec_hc_writeback.py` diffs are additive (+5 lines each — untouched).

---

## Summary

| Sev | ID | Title | Fix scope |
|---|---|---|---|
| HIGH | H-1 | INT snapshot never seeded → suppress dormant on first post-restart save | ~5 LoC (setup-path seed call) + 1 regression test |
| MED  | M-1 | Opt-meta boot seed never cleared → stale findings re-enter corpus | ~2 LoC + 1 test |
| LOW  | L-1 | Redundant `setdefault` chain in INT fall-through (parity noise) | 1 LoC or leave |
| LOW  | L-2 | Per-key dispatch may double-fire once allowlist grows | prophylactic; leave until v2 |

**Ship after H-1 fixed and mutation-anchored, and M-1 fixed in-cycle per LOW policy.** L-1/L-2 can defer.
