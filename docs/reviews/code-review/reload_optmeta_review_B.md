# Review B — reload-optmeta (feature/reload-optmeta)

**Framing:** lifecycle + signal-chain integrity + restart resilience
**Range:** `33352c34d..6b1afdcb4` (D1 audit → D2 suppress+dispatch → D2 test-loader fix-up → opt-meta boot-transient)
**Reviewer:** Review B (Tier 2-DB, framing-disjoint with A/C)
**Date:** 2026-08-15

---

## Verdict

**DO NOT SHIP** — one HIGH regression must be closed.

The suppress + dispatch mechanism is well-shaped and its happy path is mutation-anchored (drills confirmed below). Signal ordering, kill-switch semantics, restart snapshot handling, and dispatch idempotence all check out. The opt-meta boot-transient fallback works and is mutation-verified.

However: the integration-entry snapshot has **no boot-time seed**, so the very first options save after every restart still falls through to the reload cascade — which is exactly the 2026-08-07 outage class this cycle exists to prevent. This is a straightforward mirror gap against the CM branch and must be fixed before deploy.

---

## Findings

### B-HIGH-1 — `integration_last_applied_options` has no boot-time seed (mirror gap vs CM)

**Site:** `custom_components/universal_room_automation/__init__.py`

The CM branch calls `_seed_cm_last_applied_options(hass, entry)` at CM setup (line 4265) so that the FIRST options save after each restart computes `changed_keys` against a real baseline. The integration-entry branch has no analogous seed — the only writers to `integration_last_applied_options` are inside `_async_update_listener` itself (lines 6591, 6623).

**Consequence.** On the first integration-options save after any restart:

```
old = snapshots.get(entry.entry_id, {})          # {}  (never seeded)
new = dict(entry.options)                        # many keys
changed_keys = {k for k in ... if old.get(k) != new.get(k)}
             = set(new.keys())                    # e.g. {camera_person_entities, egress_cameras, perimeter_cameras, ...}
```

`changed_keys.issubset(INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS)` becomes `{many keys}.issubset({camera_person_entities})` → **False** → falls through to the reload cascade.

So the very Camera Census save that caused the 2026-08-07 ~5-minute watchdog outage will still cascade a reload if it is the first save after any HA restart. This is a real and reachable regression from the stated cycle intent ("prevent the 2026-08-07 outage"). It is not caught by the D3 tests because they hand-populate `integration_last_applied_options` in the test setup (e.g. `test_reload_watchdog_hazard.py:421-423`) — the tests never exercise a bare `{}` initial snapshot.

**Fix (surgical):**

1. Add `_seed_integration_last_applied_options(hass, entry)` sibling of the CM helper (do NOT extend the CM helper — Bug Class #27 mirror-drift).
2. Call it once at the integration entry's setup site (grep for `entry_type == ENTRY_TYPE_INTEGRATION` in `async_setup_entry`).
3. Add a regression test that leaves `integration_last_applied_options` as `{}`, calls the update listener with an options dict where the ONLY changed key is `camera_person_entities`, and asserts the suppress path fires (`reload_calls == []`). Today that test would FAIL against HEAD.

**Bug class:** #27 (primary/deferred mirror drift). Same class explicitly called out in the code comment (`_dispatch_integration_key_signals` docstring) — the missed mirror is the seed, not the apply helper.

---

### B-MED-1 — Dispatch uses raw signal string, not the `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` constant

**Site:** `__init__.py:5934`

```python
_INTEGRATION_KEY_SIGNAL_TABLE: dict[str, tuple[str, ...]] = {
    CONF_CAMERA_PERSON_ENTITIES: ("ura_transit_config_changed",),
}
```

The subscriber side (`transit_validator.py:41`) imports `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` from `const.py:2014`. This side uses the raw string. If the const value is ever renamed, the dispatch silently no-ops (subscriber listens on the new name; dispatcher sends the old one). Nothing in the test suite anchors the string-to-const equivalence — `test_dispatch_line_is_load_bearing_for_transit_signal_test` overrides the table, so a renamed const would not be caught there either.

**Fix:** import `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` from `.const` at module top and reference it in the table. Add a one-line test that `_INTEGRATION_KEY_SIGNAL_TABLE[CONF_CAMERA_PERSON_ENTITIES] == (SIGNAL_URA_TRANSIT_CONFIG_CHANGED,)`.

**Bug class:** stringly-typed cross-module coupling (variant of #7 stale-data-source: the coupling assumes the string is a constant across two modules).

---

### B-MED-2 — Opt-meta DB-failure fallback silently re-produces the old false-HIGH

**Site:** `domain_coordinators/optimization.py:673-693`

The pre-fetch is wrapped in the outer `try:` starting at :673 whose `except` at :729 catches ANY exception — including `db.get_recent_optimization_findings` raising or the DB being unavailable at boot. In that case `self._boot_findings_seed` retains its `__init__` default of `[]`. Then `_assemble_corpus` (optimization_llm.py :689-706) sees `ram_cache == []` and `boot_seed == []` → `recent = []` alongside a nonzero `_open_findings_count` → the exact false HIGH "LLM cannot see problems" this cycle exists to eliminate.

The code comment says "best-effort seed" but does not document that a DB failure at boot silently re-enables the old wrong behavior. The `_LOGGER.warning` at :731 fires for the rate-cap seed failure, not distinctly for the meta-corpus seed — an operator triaging a post-restart false HIGH from the meta pass gets no signal that the seed failed.

**Fix (choose one):**

- **Accept + document:** add an explicit `_LOGGER.warning` distinct from the rate-cap failure ("Optimizer: LLM meta-pass boot seed unavailable; meta pass may emit spurious 'cannot see problems' until first cycle populates RAM cache") AND note it in the D2 audit doc's non-goals.
- **Fix:** if seed is empty AND `_open_findings_count > 0`, have the meta pass suppress the "LLM cannot see problems" verdict for one cycle post-boot (the meta pass already has an "open findings count" input to compare against).

Either is acceptable; leaving it undocumented is not.

**Bug class:** #23 (observation-mode gating variant: a fallback that silently reverts to the pre-fix state without operator-visible signal).

---

### B-LOW-1 — Hollow-anchor pattern in `test_dispatch_line_is_load_bearing_for_transit_signal_test`

**Site:** `quality/tests/test_reload_watchdog_hazard.py:410-440`

The test proves that removing the WIRING-TABLE ENTRY makes the D3 behavioral test's dispatch fire zero times. It does NOT prove that removing the DISPATCH CALL statement itself would be caught.

I independently drilled by commenting out `_dispatch_integration_key_signals(hass, entry, changed_keys)` in `__init__.py`:

- `test_camera_person_entities_change_dispatches_transit_signal_once` — **FAILED** (caught the regression: `assert 0 == 1`).
- `test_dispatch_line_is_load_bearing_for_transit_signal_test` — **PASSED** (did not catch it).

Aggregate coverage is fine because the behavioral test caught the mutation. But the "load-bearing" test's name is misleading — it verifies the wiring-table lookup is load-bearing, not the call. Rename to `test_wiring_table_entry_is_load_bearing_for_transit_signal_test`, or replace with a real call-site mutation drill. Anchors named "load-bearing" that do not actually anchor the load-bearing site are exactly the hollow-anchors class the operator has repeatedly flagged.

**Bug class:** hollow test anchors (operator-coined).

---

### B-LOW-2 — Kill-switch fall-through reseeds snapshot but leaves stale-snapshot window

**Site:** `__init__.py:6620-6624`

When kill-switch is False and the change IS allowlisted, the code correctly skips dispatch and falls through. Before falling through, it reseeds the snapshot to `dict(entry.options)`. The subsequent `async_reload` triggers `async_unload_entry` and `async_setup_entry` for children; a concurrent second save landing during that reload window would diff against the just-reseeded snapshot (correct behavior — matches CM B-HIGH-2). Confirmed by inspection.

Minor nit: two `hass.data.setdefault(DOMAIN, {}).setdefault(...)` calls at :6591 and :6623 duplicate the setdefault chain. Not a bug — cosmetic. No action required.

---

## Verified as clean (framing checklist)

- **Signal fires exactly once per suppressed save.** `_async_update_listener` runs once per HA `async_update_entry`; the suppress branch calls `_dispatch_integration_key_signals` exactly once and returns. Confirmed by test `test_camera_person_entities_change_dispatches_transit_signal_once` (assertion `.count(...) == 1`) and by dispatch-site mutation drill.
- **Ordering (post-persist read).** HA's update-listener contract fires listeners AFTER `async_update_entry` has committed. The dispatched signal handler in `transit_validator._on_config_changed` schedules `_build_and_subscribe`, which reads camera lists via `camera_manager._get_integration_camera_list` (camera_census.py:1803-1821) — that helper re-iterates `hass.config_entries.async_entries(DOMAIN)` and reads `{**entry.data, **entry.options}` on every call. So the rebuild reads the freshly-persisted options, not a snapshot. Good.
- **Kill switch skips BOTH suppress and dispatch.** `INTEGRATION_RELOAD_SUPPRESS_ENABLED and changed_keys.issubset(...)` — flipping the flag to False falls through to the reload path with no `_dispatch_integration_key_signals` call. Confirmed by `test_kill_switch_disables_suppress_and_skips_dispatch` (PASS).
- **Suppressed path with the update listener — no double reload, no double dispatch.** Single combined update pattern preserved.
- **Restart after suppressed save.** `hass.data[DOMAIN]["integration_last_applied_options"]` is RAM-only. On restart HA re-reads persisted options fresh from disk (`async_update_entry` had committed pre-listener). No snapshot poisoning across restart. Good.
- **Untracked-task check.** The dispatch is synchronous (`async_dispatcher_send`) — not a task. The opt-meta fallback is synchronous corpus assembly. No new task creation this cycle. Good.
- **Snapshot cleanup deferral (plan LOW-4).** Documented in the code comment (:6580-6588) as one dict per integration entry, torn down with `hass.data[DOMAIN]`. Consistent with CM convention. Acceptable.

---

## Mutation drills executed (independent re-runs)

Both drills followed the "restore + verify" discipline (`.pyc` cleared each side, source restored, drill directory left clean).

1. **Opt-meta fallback** — mutation: neutered `boot_seed = getattr(self.coordinator, "_boot_findings_seed", []) or []` to `boot_seed = []` in `optimization_llm.py`.
   - `test_empty_ram_cache_falls_back_to_db_seed` → **FAILED** (`assert []` — corpus empty, as expected on mutation). Fallback is load-bearing. Source restored.

2. **Reload-watchdog dispatch call** — mutation: commented out `_dispatch_integration_key_signals(hass, entry, changed_keys)` in `__init__.py:6614`.
   - `test_camera_person_entities_change_dispatches_transit_signal_once` → **FAILED** (`assert 0 == 1`). Call site is load-bearing (see B-LOW-1 for the anchor-naming caveat).
   - `test_dispatch_line_is_load_bearing_for_transit_signal_test` → **PASSED** (see B-LOW-1). Source restored.

---

## Suite baseline

`quality/tests/test_reload_watchdog_hazard.py` — 7 pass.
`quality/tests/test_opt_meta_boot_transient.py` — 3 pass.
(Full suite baseline diff is the validator's job; this review reports the cycle-specific tests only.)

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| HIGH | 1 | B-HIGH-1 |
| MED | 2 | B-MED-1, B-MED-2 |
| LOW | 2 | B-LOW-1, B-LOW-2 |

**Ship gate:** fix B-HIGH-1 (add integration-entry snapshot seed + regression test), then re-verify. B-MEDs should be resolved in the same fix-up pass per "Fix LOWs In-Cycle" (they are ~5-30 LoC each). B-LOW-1 is a rename or a real drill — either acceptable.
