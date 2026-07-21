# PLANNING — NM Cycle A-2 "Knob Surface" (config-flow promotion of A knobs)

**Date opened:** 2026-07-20
**Author:** ura-planner
**Parent plan:** `docs/planning/PLANNING_nm_overhaul_2026_07.md` (Cycle A LIVE as v5.24.0)
**Scope boundary:** Cycle A-2 promotes the Cycle A rung-2 knobs from
module-constant-with-override-helper to first-class CoordinatorManager
options-flow fields, adds the update-listener + cache-invalidation wiring
called out in parent-plan B-LOW-1, and lands the empty-by-default
optimizer A2 allowlist as a live-editable list. Cycle B's dry-run gate,
token buckets, and life-safety subtypes remain OUT OF SCOPE.

**Product-surface driver (operator, parent-plan line 20):** *"We need
reasonable volume reduction knobs. This is meant to be opened to more
people."* A-2 is the packaging step that makes A's tuning knobs
operator-owned instead of code-owned, without touching semantics.

---

## Institutional context verified

### Files read end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/_nm_cycle_a.py` (entire file, 77 LoC)
- `custom_components/universal_room_automation/const.py:1245-1290, 1874-1955` (NM CONF block + NM Cycle A knob block)
- `custom_components/universal_room_automation/__init__.py:4360-4657` (reload-suppression allowlist + `_apply_in_place` + `_NO_LIVE_ATTR_KEYS` machinery, all the dispatch tables)
- `custom_components/universal_room_automation/config_flow.py:2255-2628` (OptionsFlow class + CM menu wiring, `async_step_coordinator_*` pattern)
- `custom_components/universal_room_automation/domain_coordinators/optimization.py:4056-4074` (A2 allowlist consumer, `dim not in OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS`)
- `custom_components/universal_room_automation/domain_coordinators/optimization.py:159` (`class OptimizationDimension(str, Enum)` — L4 hazard analysis below)
- `custom_components/universal_room_automation/domain_coordinators/energy.py:5063-5089` (A1 route knob call site)
- `custom_components/universal_room_automation/domain_coordinators/safety.py:986, 1553-1844` (A4/A5 knob call sites)
- `custom_components/universal_room_automation/domain_coordinators/security.py:1308` (A3 lock dedup call site)
- `custom_components/universal_room_automation/domain_coordinators/energy_circuits.py:340` (A1 window call site)

### Prior planning docs consulted
- `docs/planning/PLANNING_nm_overhaul_2026_07.md` — full read; A-2 obligations at lines 20, 101-124 (Numbers-Get-Knobs table), 318-321 (fix-up ratifications).
- No standalone NM A-2 planning doc exists — this is it.

### Design docs / memory
- `docs/Coordinator/NOTIFICATION_MANAGER.md` v1.0 (skimmed; predates knob surface).
- Memory: "resume 2026-07-17" pickup (v5.24.0 NM Cycle A live); "reload suppression cycle" (CM Cycle 1/2 = v4.7.26/v4.7.27 — allowlist mechanism origin and the extension 5→37 keys); "v4.7.25 presence timer knobs live" (canonical example of Number-persistence + options-flow round-trip); "v5.21.0 D2 detection knobs" (most recent precedent: rung-1 module constants promoted to rung-2 options-settable knobs via allowlist).

### Reload-suppression mechanism located
- Allowlist: `__init__.py:4583` `OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str]` — currently 37 keys post-v4.7.27 extension (HVAC + EC + Routine + Bayesian + Optimizer + LLM + MF + DP families).
- Listener: `__init__.py:5064` `_async_options_updated` — computes `changed_keys`, calls `_apply_in_place`, and reloads only if `changed_keys` is NOT a subset of the allowlist (`__init__.py:5178`).
- Snapshot: `_seed_cm_last_applied_options` (`__init__.py:4660`) — per-entry `last_applied_options` dict, seeded at CM setup and advanced after each successful apply.
- No-live-attr keys: `_NO_LIVE_ATTR_KEYS` frozenset (`__init__.py:4540`) — the "consumer re-reads entry.options each tick" pattern, snapshot advances only.
- Dispatch tables: `_EC_SETTER_DISPATCH`, `_HVAC_TUNABLE_DISPATCH`, `_OFFPEAK_DRAIN_QUALITY` — chosen when a live setter side-effect is required.

### Grep survey for reuse — every A-2 addition
| Proposed | REUSED / NEW | Evidence |
|---|---|---|
| `CONF_TRIPPED_BREAKER_ZERO_WINDOW_S`, `CONF_TRIPPED_BREAKER_ROUTE_NM` | REUSED | `const.py:1895, 1900` (A1 defaults shipped v5.24.0) |
| `CONF_LOCK_UNAVAILABLE_DEDUP_S` | REUSED | `const.py:1906` |
| `CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT / MEDIUM / HIGH` | REUSED | `const.py:1914-1919` |
| `CONF_HUMIDITY_SWING_DELTA_PCT / MIN_ABS` | REUSED | `const.py:1926-1929` |
| `CONF_CO2_LOG_ONLY_CEILING_PPM` | REUSED | `const.py:1935` |
| `CONF_TVOC_ABSOLUTE_HIGH_PPB`, `CONF_TVOC_SUSTAINED_S` | REUSED | `const.py:1940-1943` |
| `CONF_SAFETY_DISCOVERY_BLOCKLIST` | REUSED | `const.py:1948` (tuple default; consumer at `safety.py:986`) |
| `CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS` (**NEW CONF_ key**) | NEW | Constant `OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS` at `const.py:1877` exists (empty frozenset); no CONF_-prefixed sibling. Justification: A-2 promotes it to options-flow-editable list. Consumer `optimization.py:4064` must be re-pointed to `nm_cycle_a_knob(...)`. |
| Options-flow step `async_step_coordinator_notifications_volume` | NEW | Sibling of existing `coordinator_notifications` step (menu at `config_flow.py:2589`); NEW step keeps volume knobs cohesive without swelling the existing notifications form. |
| Update-listener + cache invalidation wiring for these keys | REUSED (extend) | `OPTIONS_RELOAD_SUPPRESS_KEYS` at `__init__.py:4583`; `_apply_in_place` at `__init__.py:4673`; snapshot machinery already in place. A-2 adds ~10 keys and one cache-invalidation hook. |
| Cache module in `_nm_cycle_a.py` | NEW | Currently uncached by explicit design (`_nm_cycle_a.py:14-16`); A-2 adds a per-key module-level dict + invalidation on options-update. |
| Number/Switch/Select entities for these knobs | NOT PROPOSED — options-flow only | These are rung-2 knobs per parent-plan ladder (line 20). Rung-3 (Number entity) is reserved for values the operator "legitimately tunes by observation" — noise thresholds are set-once-per-deployment structural tuning, not daily dashboard turns. |

### Discrepancies / hazards surfaced during scoping
1. **L4 enum-vs-str, mitigated but explicit.** `OptimizationDimension` at `optimization.py:159` is `class OptimizationDimension(str, Enum)`, so `finding.dimension` compares equal to its `str` value (`OptimizationDimension.COMFORT == "comfort"` → True). The consumer at `optimization.py:4066` (`dim not in OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS`) works today even if `dim` is an Enum member — but the parent plan flags L4 as a hazard because a future refactor to a non-str Enum, or a `finding.dimension` field that happens to be `None` / a stringified `str(Enum)` (`"OptimizationDimension.COMFORT"`), silently breaks the check. **A-2 mitigates by normalizing on both sides:** load-time cast to lowercased `str` for stored allowlist entries; consumer coerces `dim` via `str(dim.value if hasattr(dim, "value") else dim).lower()` before membership test.
2. **`nm_cycle_a_knob` bool coercion** already handles str `"true"`/`"1"` (`_nm_cycle_a.py:56-61`) — options-flow bool selector returns `bool`, so no additional coercion needed for A1's `CONF_TRIPPED_BREAKER_ROUTE_NM`.
3. **Tuple/list coercion for blocklist + allowlist** already handled at `_nm_cycle_a.py:66-69` (`isinstance(default, (tuple, list, frozenset, set))`); options-flow `EntitySelector(multiple=True)` returns `list[str]` which will coerce back to `tuple`/`frozenset` correctly.

---

## Tier classification

**Tier 2-DB (three framing-disjoint reviews) — standing policy.**

Justification:
- **Shared-primitive touch.** Extending `OPTIONS_RELOAD_SUPPRESS_KEYS` and `_apply_in_place` is a modification to the CM reload-suppression primitive that every other coordinator's live-tunable knobs depend on. The v4.7.26/v4.7.27 build history (Reviewer-D-caught mis-wired keys during the 5→37 extension) is the exact regression class this policy exists to catch.
- **Cross-coordinator ripple.** These knobs are read by energy, energy_circuits, safety, security, and optimization coordinators via `nm_cycle_a_knob`. A cache-invalidation bug pins stale values across five coordinators simultaneously.
- **Cache invalidation.** Parent-plan B-LOW-1 is Bug-Class-#7 territory (stale data source) if the update-listener hook doesn't fire on every persisted options edit.
- Not Tier 3 — the invariant surface is bounded (~10 keys, one helper function, one consumer per key) and no state-machine seams are threaded. If Review D wants to be run in parallel it is cheap insurance; not mandatory.

**Three framings:**
- **Review A — Correctness + coercion:** every knob's options-flow selector matches its default type; `nm_cycle_a_knob` coercion handles the persisted shape; the L4 enum-vs-str normalization holds for every reachable `finding.dimension` shape (Enum, str, None, uppercase, `"OptimizationDimension.COMFORT"` stringification); kill-switch semantics documented on each knob behave as specified when set to the disable-value.
- **Review B — Reload-suppression + cache invalidation + async lifecycle:** every new key is in `OPTIONS_RELOAD_SUPPRESS_KEYS` OR the plan justifies why it forces a reload; cache-invalidation hook fires on `_async_options_updated` for every new key; snapshot advances on every successful apply; restart re-seeds from `entry.options`; no listener leak on CM unload.
- **Review C — Options-flow round-trip + backward compat + test authority:** options-flow form round-trips every knob (submit → `entry.options` → next form load shows persisted value); pre-A-2 deployments (no CONF_* in options) fall back to `const.py` defaults with zero behavior change; behavioral test drives `_async_options_updated` end-to-end and asserts the cache invalidates AND the consumer coordinator picks up the new value on next tick without CM reload.

Pre-review baseline tag: `pre-review-v<next>` per CLAUDE.md.

---

## Numbers-Get-Knobs table (A-2 scope)

Every knob is rung-2 (CM options-flow). Defaults are the values already
shipped in v5.24.0 — A-2 changes zero semantics.

| Knob (CONF_) | Rung | Home | Default (cite) | Kill-switch semantics |
|---|---|---|---|---|
| `CONF_TRIPPED_BREAKER_ZERO_WINDOW_S` | 2 | Options-flow (volume step) | `900` at `const.py:1896` | 0 = never dedup window; every zero-watt sample flags immediately (regression to pre-A behavior) — document as such; do not clamp to 0. |
| `CONF_TRIPPED_BREAKER_ROUTE_NM` | 2 | Options-flow (bool) | `False` at `const.py:1901` | `True` = re-enable NM paging (per parent plan A1 — anomaly-only by default). This IS the kill switch (default-off). |
| `CONF_LOCK_UNAVAILABLE_DEDUP_S` | 2 | Options-flow (int seconds) | `86400` at `const.py:1907` | `0` = disable dedup (pre-A3 behavior). Documented in `const.py:1904-1905`. |
| `CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT` | 2 | Options-flow (int %) | `78` at `const.py:1917` | Kill-switch via ceiling values — set all three ladder rungs above 100 = ladder inert. |
| `CONF_HUMIDITY_NORMAL_MEDIUM_PCT` | 2 | Options-flow (int %) | `85` at `const.py:1918` | See above. |
| `CONF_HUMIDITY_NORMAL_HIGH_PCT` | 2 | Options-flow (int %) | `92` at `const.py:1919` | See above. |
| `CONF_HUMIDITY_SWING_DELTA_PCT` | 2 | Options-flow (int %) | `20` at `const.py:1928` | `0` = disables swing detection (documented in `const.py:1925`). |
| `CONF_HUMIDITY_SWING_MIN_ABS_PCT` | 2 | Options-flow (int %) | `60` at `const.py:1929` | Set above 100 = swing floor unreachable = inert. |
| `CONF_CO2_LOG_ONLY_CEILING_PPM` | 2 | Options-flow (int ppm) | `1200` at `const.py:1936` | Set very high = CO2 ladder inert. |
| `CONF_TVOC_ABSOLUTE_HIGH_PPB` | 2 | Options-flow (int ppb) | `1500` at `const.py:1942` | Set very high = TVOC absolute rung inert. |
| `CONF_TVOC_SUSTAINED_S` | 2 | Options-flow (int seconds) | `1800` at `const.py:1943` | Very large = sustained rung never fires. |
| `CONF_SAFETY_DISCOVERY_BLOCKLIST` | 2 | Options-flow (`EntitySelector(multiple=True)`) | 2-tuple at `const.py:1949-1952` | Empty list = no exclusions (all discovered sensors participate). |
| `CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS` (**NEW**) | 2 | Options-flow (`SelectSelector(multiple=True)` over `OptimizationDimension` members) | `[]` — empty by design per parent plan L3 (line 320) | Empty list = all HIGH findings route to digest (default). Adding an entry = explicit operator opt-in for that dimension to page NM live. |

Every knob's rung placement matches the parent plan's ratified ladder
(parent-plan lines 20, 101-124). Zero knobs are proposed for rung 1
(module constant) beyond what already ships; zero knobs are proposed for
rung 3 (Number entity) in A-2 — noise thresholds are set-once-per-deployment,
not observation-tunable.

---

## Deliverables

### D1. Options-flow step: "Notification volume" (rung-2 knobs)

Add `async_step_coordinator_notifications_volume` to
`UniversalRoomAutomationOptionsFlow` (sibling of the existing
`coordinator_notifications` step). Add the menu option under the
`ENTRY_TYPE_COORDINATOR_MANAGER` branch at `config_flow.py:2589`.

Form fields (11 knobs, grouped visually):
- A1: `CONF_TRIPPED_BREAKER_ZERO_WINDOW_S`, `CONF_TRIPPED_BREAKER_ROUTE_NM`
- A3: `CONF_LOCK_UNAVAILABLE_DEDUP_S`
- A4: three humidity ladder + two swing knobs
- A5: `CONF_CO2_LOG_ONLY_CEILING_PPM`, `CONF_TVOC_ABSOLUTE_HIGH_PPB`, `CONF_TVOC_SUSTAINED_S`, `CONF_SAFETY_DISCOVERY_BLOCKLIST`
- A2: `CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS`

Defaults sourced from `const.py` `DEFAULT_*` constants (never inlined).
Selectors chosen per type (`NumberSelector` for numerics with
`min`/`max`/`step`/`unit_of_measurement`; `BooleanSelector` for the route
knob; `EntitySelector(multiple=True, domain="sensor")` for the blocklist;
`SelectSelector(multiple=True, options=[e.value for e in OptimizationDimension])` for the allowlist).

**Acceptance criteria:**
- **Verify:** Opening the CM options → "Notification volume" shows current persisted values (or defaults on first open).
- **Verify:** Submitting the form persists each knob into `entry.options`; re-opening shows the persisted values.
- **Test:** `quality/tests/test_nm_cycle_a2_options_flow.py::test_volume_step_roundtrip` — submit-then-reload roundtrip on every field.
- **Test:** `test_volume_step_defaults_when_absent` — form defaults resolve from `const.py` when `entry.options` is empty.
- **Live:** operator opens CM options → Notification volume, changes `CONF_HUMIDITY_NORMAL_MEDIUM_PCT` from 85→80, saves; entity `sensor.ura_notification_manager` attributes reflect the change on next safety tick (see D2 acceptance below); no CM reload observed in logs.

### D2. Reload-suppression allowlist extension + cache invalidation

Extend `OPTIONS_RELOAD_SUPPRESS_KEYS` at `__init__.py:4583` with all 12
A-2 CONF_ keys. Because these knobs are consumed via `nm_cycle_a_knob`
(which reads `entry.options` fresh on every call), they belong in
`_NO_LIVE_ATTR_KEYS` (the "consumer re-reads each tick" pattern) — NO
`_apply_in_place` dispatch entry required. The snapshot must still advance
on apply so the diff-listener stays honest.

Add cache-invalidation hook (resolves parent-plan B-LOW-1):
- `_nm_cycle_a.py` grows a module-level `_KNOB_CACHE: dict[str, Any]` and a public `invalidate_knob_cache(conf_key: str | None = None) -> None` (None = flush all).
- `nm_cycle_a_knob` populates the cache on lookup; returns cached value on hit.
- `_async_options_updated` in `__init__.py:5064` calls `invalidate_knob_cache()` on every options-update (any key) BEFORE `_apply_in_place`, so the next `nm_cycle_a_knob` call after apply reads fresh from `entry.options`.
- Cache scope is process-wide (single hass instance); invalidation is total-flush per event to keep the correctness proof trivial. Per-key invalidation is a Cycle-B+ optimization if profiling ever demands it.

**Acceptance criteria:**
- **Verify:** Every A-2 CONF_ key present in `OPTIONS_RELOAD_SUPPRESS_KEYS` AND in `_NO_LIVE_ATTR_KEYS`.
- **Verify:** `_async_options_updated` calls `invalidate_knob_cache()` unconditionally per invocation (before subset check).
- **Test:** `test_a2_keys_do_not_trigger_reload` — construct diff `changed_keys = {CONF_HUMIDITY_NORMAL_HIGH_PCT}`, run listener, assert no `hass.config_entries.async_reload(entry.entry_id)` call, snapshot advanced.
- **Test:** `test_cache_invalidation_on_options_update` — seed cache with value V1, drive `_async_options_updated` with new options containing V2, assert next `nm_cycle_a_knob` returns V2 (not V1).
- **Test:** `test_mixed_a2_and_non_allowlisted_key_still_reloads` — regression guard: adding a non-A2 non-allowlisted key alongside an A-2 key MUST still reload.
- **Live:** Change `CONF_HUMIDITY_NORMAL_MEDIUM_PCT` via options-flow; grep logs for "Setting up universal_room_automation" — MUST be absent (no reload); `sensor.ura_safety_coordinator` next tick shows new threshold in attributes (safety consumes via `nm_cycle_a_knob` at `safety.py:1799-1807`).
- **Live:** Change knob, confirm sibling entity `last_changed` invariant preserved (v4.7.26 no-reload proof pattern — a sibling entity's `last_changed` must NOT jump when the options edit lands).

### D3. A2 optimizer allowlist wiring (empty-by-default, enum-safe)

Currently `optimization.py:4064` imports `OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS` from `const.py` (empty `frozenset()`). Repoint to `nm_cycle_a_knob`:

```python
from ..const import (
    CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
    DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
)
from ._nm_cycle_a import nm_cycle_a_knob
allowlist_raw = nm_cycle_a_knob(
    self.hass,
    CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
    DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
)
# L4 normalization: coerce both sides to lowercased str.
allowlist = frozenset(str(x).lower() for x in allowlist_raw)
dim_val = getattr(finding.dimension, "value", finding.dimension)
dim_str = str(dim_val).lower()
if dim_str not in allowlist:
    ...
```

Add to `const.py` (next to the existing `OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS`):
- `CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: Final = "nm_a2_optimizer_high_allowlist_dimensions"`
- `DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: Final = ()` (empty tuple — matches parent-plan L3: empty by design, additions are explicit opt-in)
- Keep the pre-existing `OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: Final = frozenset()` as a deprecated alias for one release with a comment pointing at the new CONF_ (mechanical grep-safety), OR remove and re-run test suite — decision at build time based on whether any test still imports the bare constant.

**L4 hazard explicit mitigation:** the coercion above handles all four
reachable shapes of `finding.dimension` (Enum member, plain str, None
→ `"none"`, upstream refactor to non-str Enum → `str(Enum.MEMBER.value)`)
and all shapes of allowlist entries persisted via options-flow (str values
from `SelectSelector`). Options-flow `SelectSelector(options=[e.value for e in OptimizationDimension])` restricts operator input to the valid dimension string set at UI level; the runtime normalization is defense-in-depth.

**Acceptance criteria:**
- **Verify:** Empty allowlist (default) → every HIGH finding routes to digest (log line "not in NM allowlist" fires).
- **Verify:** Allowlist = `["comfort"]` via options → HIGH comfort findings page NM; HIGH occupancy findings still route to digest.
- **Test:** `test_a2_allowlist_empty_by_default` — no options-flow entry, HIGH finding of every dimension routes to digest.
- **Test:** `test_a2_allowlist_enum_str_normalization` — parametrize `finding.dimension` as (`OptimizationDimension.COMFORT`, `"comfort"`, `"COMFORT"`, `"OptimizationDimension.COMFORT"`) with allowlist `["comfort"]`; only the first three match (the fourth is the stringified-Enum artifact — assert as expected NON-match and document as a known-unsafe upstream shape that A-2 does not synthesize).
- **Test:** `test_a2_allowlist_options_flow_roundtrip` — save `["comfort", "safety"]`, reload flow, form shows both.
- **Live:** operator adds `"comfort"` to allowlist; next real HIGH comfort finding pages NM (or synth-triggered on-demand via `optimization.trigger_cycle` service).

### D4. Documentation write-back

- Update `const.py:1880-1889` block comment: replace "Cycle A-2 (separate plan)" with "Cycle A-2 (shipped v<next>) — options-flow at CM → Notification volume".
- Update `_nm_cycle_a.py` header docstring: replace "Deliberately does NOT cache" with cache + invalidation description.
- Cross-post ripple pointer to `docs/planning/PLANNING_nm_overhaul_2026_07.md` deferred-work register: "A-2 shipped v<next> — B-LOW-1 (cache invalidation) resolved; L3 (empty allowlist by design) preserved; L4 (enum-vs-str) mitigated by lowercased-str coercion on both sides."

---

## Cycle-level acceptance

- **Live/MCP:** Change one knob per category (breaker window, lock dedup, humidity ceiling, CO2 ceiling, blocklist add, allowlist add); observe no CM reload; observe next-tick behavior change.
- **Sensor:** `sensor.ura_safety_coordinator` and `sensor.ura_notification_manager` attributes reflect knob-driven thresholds where already surfaced; no new attributes required for A-2.
- **Test:** All D1-D3 test IDs pass; existing NM Cycle A test suite still green (regression guard).
- **Live (README write-back):** Post-restart, the README's Live Validation table for v<next> lists PASS for the no-reload proof (sibling-`last_changed` invariant), cache-invalidation proof (edit → next tick reads new value), and empty-allowlist digest-routing observation.

---

## Deferred-work register (populate on close)

Empty at plan open.

Prospective candidates (to be evaluated at close, NOT built in A-2):
- Per-key cache invalidation (vs. total-flush) — only if profiling shows the total-flush is measurable relative to safety tick cost. Currently anticipated NOT needed.
- Number-entity (rung-3) promotion for any specific knob that operator observation reveals gets tuned frequently — not anticipated for noise thresholds.

---

## Plan-completion accounting (fill at cycle close)

| Deliverable | Status | Notes / where tracked if deferred |
|---|---|---|
| D1 options-flow step | | |
| D2 allowlist extension + cache invalidation | | |
| D3 A2 optimizer allowlist wiring (with L4 mitigation) | | |
| D4 documentation write-back | | |

Any silently-dropped item = plan violation per CLAUDE.md "Plan Completion Tracking".
