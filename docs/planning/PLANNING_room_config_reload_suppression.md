# PLANNING — Room-config SAVE reload suppression (climate step)

**Card:** `ROOM-CONFIG-SAVE-FULL-RELOAD-STALL-1`
**Tier:** **2-DB** (reload path + shared substrate primitive, regression-prone;
follows the CM reload-suppression precedent).
**Status:** PLAN — plan-review FIX-REQUIRED findings (P1-P9) folded 2026-09-19;
awaits re-review before build. **Scope: D0 + D1 only.** D2 is log-clarity/dedup
only; the per-room `refresh_subscriptions` refactor stays PARKED as
`SUBSTRATE-PER-ROOM-REFRESH-1`.
**Author:** ura-planner (revised)
**Date:** 2026-09-19

---

## 0. Falsifiable invariant (state up front — D-reviewer falsifies)

> **INV-A (suppression correctness).** For every room-options SAVE whose
> `changed_keys` are all in the (extended) `_ROOM_SUPPRESS_KEYS` allowlist,
> the entry performs **zero** platform teardown / entity re-add (entity
> object identity is stable across the save) AND every consumer of every
> changed key reflects the new value on its next natural tick (no stale
> reads). Contrapositive: if any changed key has a CACHED consumer that
> is not paired with an in-place push in the suppress branch, the save
> MUST fall through to the full reload (INV-A must not be satisfied
> vacuously by admitting a stranded-cache key).
>
> **INV-B (substrate scope — SUPPRESSED path only; per plan-review P4).**
> On a SUPPRESSED save (changed_keys ⊂ `_ROOM_SUPPRESS_KEYS`),
> `OccupancySubstrate.refresh_subscriptions` reaches the no-diff return
> at `occupancy_substrate.py:442`: **zero** bucket resets, **zero**
> listener swap, **zero** synthetic-edge dispatches for ANY room. On the
> FALL-THROUGH (full-reload) path INV-B is intentionally NOT claimed:
> `_reset_and_seed_room_bucket` runs for every room in `room_entities`
> (`occupancy_substrate.py:454-457`), a single house-wide listener swap
> occurs (`:459-495`), and synthetic edges dispatch for every (room, kind)
> whose seeded state differs from the pre-refresh snapshot
> (`:502-529`) — see §2 accepted known-cost.

Acceptance tests (D3) discriminate INV-A from a *vacuous* pass by
exercising both a live-read key (must suppress + consumer sees new value)
and a would-be-cached key (must fall through — not silently allowlisted).

---

## 1. Institutional context verified

### 1.1 Greps run + REUSE-or-BUILD per proposed piece

Every proposed change is a REUSE / EXTEND of existing machinery. No new
signal, sensor, helper, coordinator, or constant is proposed.

| Piece | Verdict | Existing at |
|---|---|---|
| ROOM options-update reload-suppression branch | REUSE (extend) | `__init__.py:7676-7715` (`_async_update_listener`, ROOM branch, `_ROOM_SUPPRESS_KEYS`) |
| Allowlist frozenset pattern (`_ROOM_SUPPRESS_KEYS`) | REUSE (extend membership) | `__init__.py:7660-7674` |
| Snapshot **seeding at setup** (D0 — plan-review P1) | NEW WIRE-UP of existing dict | `hass.data[DOMAIN]["room_last_applied_options"]` (currently only written inside `_async_update_listener` at `__init__.py:7677-7679, 7692, 7723`; no setup seeding — root cause of first-save-per-room-per-lifetime full reload) |
| In-place-push pattern for CACHED consumers (rare) | REUSE (CM setter-dispatch loop) | `__init__.py:_EC_SETTER_DISPATCH` at `:6693` + loop at `:7458` (per plan-review P6; the earlier cite of `_NM_A2_KEYS` was wrong — that set EXTENDS `_NO_LIVE_ATTR_KEYS` at `:6822, :6954` and pushes NOTHING) |
| Substrate re-subscribe signal on options_updated | REUSE (already dispatched) | `__init__.py:7700-7714`, `signals.py`, `presence.py` handler → `refresh_subscriptions` |
| Substrate fast-path noop when entity set unchanged | REUSE (already exists — INV-B leans on it) | `occupancy_substrate.py:436-442` (`if not added and not removed and not reclassified: return`) |
| Reload background-task dispatch (fall-through) | REUSE (unchanged) | `__init__.py:7616-7629` (docstring), fall-through below `_ROOM_SUPPRESS_KEYS` |
| `changed_keys` diffing via `room_last_applied_options` snapshot | REUSE (unchanged) | `__init__.py:7677-7685, 7723` |
| CONF constants referenced by allowlist expansion | REUSE (import from `const.py`) | see D1 field enumeration below |

**No NEW pieces.** D0 is a wire-up of the existing snapshot dict at
setup/unload; D1 is membership + audit; D2 is a log-format change.

### 1.2 Prior planning / audit docs consulted

- `docs/planning/PLANNING_cm_reload_suppression*.md` (the pattern this
  cycle mirrors). Relevant: the CM branch's `OPTIONS_RELOAD_SUPPRESS_KEYS`
  and its per-key audit comments are the template for D1's inline audit
  block. **Correction (plan-review P6):** the CACHED-push mechanism to
  mirror is `_EC_SETTER_DISPATCH` (`__init__.py:6693`, driven by loop at
  `:7458`), NOT `_NM_A2_KEYS` (which is a NO-push, live-read set).
- `docs/planning/PLANNING_onboarding_simplify.md` §D2/§D9 — cited at
  `config_flow.py:2575-2580`; confirms `CONF_WET_ROOM` is set once at
  room-create via `ROOM_TYPE_FEATURE_DEFAULTS`, so a wet-room *toggle*
  from the climate step is legal and expected to hit the suppress path.
- `docs/planning/PLANNING_hvac_demand_knobs_and_obs_gaps.md` (v5.103.8)
  — introduced `CONF_HVAC_VACANCY_HOLD[_NIGHT]` including the
  clearable-key `merged.pop` semantics
  (`config_flow.py:11484-11493`). Load-bearing for D1's default-
  materialization handling (see plan-review P7 below).
- `docs/reviews/PARENT_RELOAD_WATCHDOG.md` / memory
  [[feedback_parent_entry_reload_watchdog_hazard]] — same failure class
  at a different level; this cycle is ROOM-entry only per N-2.

### 1.3 Memory bodies pulled

- [[project_cm_reload_suppression_cycle_stack]] — CM allowlist grew
  5→37 with per-key audit; RestoreEntity dropped for pushed keys; the
  no-reload proof was the sibling-`last_changed` invariant. That proof
  becomes D3's L1 live-validation test.
- [[feedback_parent_entry_reload_watchdog_hazard]] — reloading a
  parent-scope entry cascades → event-loop stall → watchdog ~5min. This
  cycle attacks the ROOM-scope analogue (~10-30s stall, no watchdog).
- [[feedback_coincidental_equality_masks_concept_split]] — hazard: a
  key may look live-read via `merged.get(...)` in one call site while
  being cached in another. D1 requires per-consumer-site verdicts, not a
  single first-hit classification (plan-review P9).
- [[feedback_do_robust_fix_not_bandaid_and_card]] — argues against
  carding a partial fix if the full expansion is doable. D1 policy:
  every climate-step key gets an explicit LIVE / REFRESHED / EXCLUDED
  verdict — no "we'll get to the rest later" residue.

### 1.4 Design docs read

- `docs/Coordinator/PRESENCE.md` — for `SIGNAL_ROOM_ENTRY_LIFECYCLE`
  handler ownership (PresenceCoordinator forwards to
  OccupancySubstrate).
- No IDENTITY/CAMERA scope in this cycle → IDENTITY_FUSION_CAMERAS_MANUAL
  not required.

### 1.5 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/__init__.py:1798`
  (ROOM `async_setup_entry` — D0 seeding site).
- `.../__init__.py:7616-7770` (the update listener, both ROOM and CM
  branches; snapshot writes at `:7677-7679, :7692, :7723`).
- `.../__init__.py:6393-6413` (`_NM_A2_KEYS`) and `:6822-6979`
  (`OPTIONS_RELOAD_SUPPRESS_KEYS`, `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`);
  `_EC_SETTER_DISPATCH` at `:6693` + loop at `:7458` (the true
  CACHED-push template — plan-review P6).
- `.../config_flow.py:2549-2707` (create-flow `async_step_climate`) and
  `:11432-11754` (options-flow `async_step_climate`) — the write source
  and default-materialization site (P7).
- `.../domain_coordinators/occupancy_substrate.py:75-92, 200-230`
  (multi-CONF WARN at `:219`, cross-room first-claim-wins arbitration —
  plan-review P3), `:351-529` (`refresh_subscriptions` + fast-path at
  `:436-442` + fall-through reset+seed loop at `:454-457` + house-wide
  listener swap at `:459-495` + synthetic-edge dispatch at `:502-529`).
- `.../domain_coordinators/presence.py` (lifecycle handler).
- `.../automation.py:867-940` (`_refresh_config` — the REFRESHED
  mechanism; called at `:922` from `handle_occupancy_change`) and
  `:2542` (REFRESHED consumer of `CONF_HUMIDITY_FAN_THRESHOLD`).
- `.../coordinator.py:4934` (`_refresh_config` at top of tick — UNIVERSAL
  refresh path), `:5013` (a SECOND `_refresh_config` call gated behind
  `_is_cover_automation_enabled()` — NOT universal; coverage of `:5013`
  is per-path).
- `.../binary_sensor.py:1080` (LIVE consumer of
  `CONF_HUMIDITY_FAN_THRESHOLD` via `merged.get(...)`) — proves per-site
  concept split (plan-review P9).
- `.../domain_coordinators/hvac_zones.py:894-940`
  (`_effective_hvac_hold_seconds` takes `override_day` / `override_night`
  as CALL PARAMETERS; call sites at `hvac_zones.py:1018`,
  `binary_sensor.py:894` pass the current values per-call — proves
  `CONF_HVAC_VACANCY_HOLD[_NIGHT]` are LIVE, not CACHED-suspected — see
  §D1 classification correction).

### 1.6 Prior-art scan verdict

**REUSE-only cycle.** Every mechanism this plan touches already exists.
D0 wires the existing snapshot dict at setup/unload; D1 extends
membership in an existing frozenset; D2 changes a log format string.

---

## 2. Problem (verified from logs 2026-09-19)

Operator saves a single toggle on the room "Climate & Fans" form. HA
becomes unresponsive ~10-30s. **No** HA restart. Log timeline shows:

1. Options-flow `async_step_climate` computes `merged = {**options,
   **user_input}` (`config_flow.py:11470-11493`) — with an explicit
   `merged.pop(...)` at `:11485-11490` for the two clearable
   `CONF_HVAC_VACANCY_HOLD[_NIGHT]` keys (unset → fall through to
   room-type table) — and calls `async_create_entry` → HA persists the
   entry and fires `_async_update_listener`.
   - **Default-materialization corollary (plan-review P7).** Every OTHER
     climate-step field is `vol.Optional(K, default=self._get_current(K,
     DEFAULT_K))` at `config_flow.py:11521+`. HA returns the default for
     any absent key, so `user_input` ships ~20 fields on every save even
     if the operator only touched one. On a "virgin" room (key never set
     before), `old.get(k) = None`, `new.get(k) = default`, so the key
     enters `changed_keys` on FIRST save — one EXCLUDED key in the form
     forces the whole save to fall through. **The benefit of D1 is
     therefore all-or-nothing across the climate step** — either every
     climate-step key is LIVE/REFRESHED-with-coverage and the form
     suppresses, or one CACHED key strands the whole form on reload.
     `CONF_HVAC_VACANCY_HOLD[_NIGHT]` are IMMUNE to this because of the
     `merged.pop` at `:11485-11490`; all others are subject.
2. `_async_update_listener` computes `changed_keys` via the snapshot
   diff (`__init__.py:7682-7685`). **First-save-per-room-per-HA-lifetime
   bug (plan-review P1, root cause #2):** `room_last_applied_options` is
   ONLY written inside `_async_update_listener` (`:7678-7679, :7692,
   :7723`). Nothing seeds it at setup. So the FIRST save after HA start
   compares against `{}` → every present key is "changed" → subset test
   at `:7686` fails even if the operator toggled ONLY an allowlisted
   key. This is the guaranteed-first-save failure D0 fixes.
3. Because the climate step re-submits ~20 climate fields (default-
   materialized per P7 above), and most are NOT in the current
   `_ROOM_SUPPRESS_KEYS` (only `CONF_ZONE`, comfort-temp min/max,
   comfort-humidity max, `fan_control_enabled`,
   `humidity_fan_control_enabled`), the subset test at `:7686` fails.
4. Fall-through fires the ROOM reload as a background task (~90 entities
   unload/re-add) plus the `SIGNAL_ROOM_ENTRY_LIFECYCLE` cascade natural
   to reload, which drives `OccupancySubstrate.refresh_subscriptions`;
   the reload transiently removes-then-re-adds every occupancy entity of
   the changed room, which crosses the `added/removed` diff threshold at
   `occupancy_substrate.py:428-434`, and drives `_reset_and_seed_room_bucket`
   for **every room** in `room_entities` (`:454-457`) — a single
   house-wide listener swap at `:459-495`, followed by synthetic-edge
   dispatch at `:502-529` for any (room, kind) whose seeded state
   differs from the pre-refresh snapshot.
5. Net effect: a save that only meant to flip one boolean cycles
   platform setup for ~90 entities on the event loop, blocking other
   coroutines for the observed 10-30s window.

**Accepted known-cost on the FALL-THROUGH path.** The house-wide
reset+seed at `occupancy_substrate.py:454-457` and house-wide listener
swap at `:459-495` are BY DESIGN — a genuine entity churn from one
room's reload requires the substrate to re-derive claims across all
rooms (first-claim-wins arbitration lives at
`occupancy_substrate.py:200-230, :219`; a scoped variant would still
have to visit every room to detect claim overlap). D1 attacks the
frequency of fall-through (from "every climate save" to "only when a
CACHED key changed"); D2 attacks the *log noise* on the residual
fall-through. The full per-room refactor is PARKED as
`SUBSTRATE-PER-ROOM-REFRESH-1`.

**Root causes (verified against code):**
- **RC-A (plan-review P1):** No setup seeding of
  `room_last_applied_options` → first save per room per HA lifetime
  diffs against `{}` → unavoidable fall-through even on an allowlisted
  key. **D0 fixes this.**
- **RC-B:** `_ROOM_SUPPRESS_KEYS` covers only 5 keys today; the climate
  step writes ~20 (default-materialized per P7); the subset check
  almost always fails. **D1 fixes this** — for keys that are LIVE or
  REFRESHED-with-coverage.

**Non-cause (verified):** substrate `refresh_subscriptions` itself is
cheap on the *suppressed* path (fast-path noop at `:436-442`). The stall
is driven by the full reload, not by the substrate signal.

---

## 3. Deliverables

**Scope: D0 + D1 only.** D2 is log-clarity/dedup only (no refactor).
The per-room substrate refresh refactor is PARKED as
`SUBSTRATE-PER-ROOM-REFRESH-1`.

### D0 — Seed `room_last_applied_options` at ROOM setup (BLOCKING prereq of D1)

**Plan-review P1 (CRITICAL).** The snapshot dict is written ONLY inside
`_async_update_listener` (`__init__.py:7677-7679, :7692, :7723`). No
setup seeding. First save per room per HA lifetime therefore diffs
against `{}` and the subset test at `:7686` fails — D1 alone is
guaranteed to miss on the first save (fresh-restart), i.e. the exact
condition post-deploy live validation runs in.

**File:** `custom_components/universal_room_automation/__init__.py`
(ROOM branch of `async_setup_entry` at `:1798`; also the corresponding
unload handler).

**Change:**
1. In ROOM `async_setup_entry` (after `entry.entry_id` is valid and
   before returning True), execute:
   ```python
   hass.data.setdefault(DOMAIN, {}).setdefault(
       "room_last_applied_options", {},
   )[entry.entry_id] = dict(entry.options)
   ```
   Guard idempotency: overwrite on every setup (a reload sets the
   snapshot from the just-loaded options, which is the correct baseline
   for the NEXT save).
2. In the ROOM `async_unload_entry` path, `.pop(entry.entry_id, None)`
   from the same dict so a removed-and-re-added entry doesn't diff
   against a stale ghost snapshot.

**Non-goals inside D0:** no change to the listener; no change to the CM
branch (it already has the same class of bug but is out of this cycle's
scope — card if needed).

### D0 Acceptance Criteria (discriminating)

- **Verify (D0 fixes the first-save case):** After HA restart, save
  toggling ONLY an allowlisted key (e.g. `CONF_FAN_CONTROL_ENABLED`,
  which is LIVE + already in `_ROOM_SUPPRESS_KEYS` today). Log MUST show
  the suppress line; MUST NOT show "Setting up universal_room_automation"
  for that entry. Without D0, this test FAILS (first-save baseline).
- **Verify (D0 discriminator):** With D0 REVERTED (source-mutation drill,
  Reviewer C), the same test MUST FAIL — proves D0 is load-bearing, not
  paper.
- **Test:** `quality/tests/test_room_options_reload_suppression.py::test_first_save_after_setup_suppresses`
  — sets up a ROOM entry, saves with only an allowlisted key differing,
  asserts suppress log + no reload.
- **Live:** Post-deploy, the FIRST climate-step save on any room MUST
  suppress if all changed_keys ⊂ allowlist. Prior behaviour: first save
  always reloaded.

### D1 — Extend `_ROOM_SUPPRESS_KEYS` to climate-step keys, per-consumer-site proven safe

**File:** `custom_components/universal_room_automation/__init__.py`
(only `_ROOM_SUPPRESS_KEYS` at `:7660-7674` and, if any key requires it,
a small in-place push block above the `return` at `:7715` — mirroring
the `_EC_SETTER_DISPATCH` loop at `:7458`, NOT `_NM_A2_KEYS` — see
plan-review P6).

**Classification taxonomy — THREE classes, not two (plan-review P2).**

- **LIVE** — every consumer reads `entry.options` / `entry.data` /
  `merged.get(...)` on every tick or every decision. No in-memory cache
  copied at setup. Safe to bare-suppress.
  Example proved LIVE this cycle: `CONF_HVAC_VACANCY_HOLD[_NIGHT]` —
  `hvac_zones._effective_hvac_hold_seconds` (`hvac_zones.py:894-940`)
  takes `override_day` / `override_night` as CALL PARAMETERS; callers
  pass the current values per-call at `hvac_zones.py:1018` and
  `binary_sensor.py:894`; no setup cache. (This corrects the previous
  "CACHED-suspected" note — plan-review CORRECTION.)
- **REFRESHED** (NEW class — plan-review P2) — value is stored on a
  cached attribute (typically `self.config[K]` in `automation.py`) BUT
  the enclosing entry-point re-derives it from `entry.data` /
  `entry.options` on every tick or every decision that reads the key.
  Two known refreshers: `automation._refresh_config` (`automation.py:867`),
  called at `automation.py:922` (`handle_occupancy_change` top) and at
  `coordinator.py:4934` (periodic tick top — UNIVERSAL).
  **REFRESHED requires PROVEN COVERAGE, not mere existence.** A key is
  REFRESHED-with-coverage only if the builder cites the refresher call
  site AND proves it precedes every read of that key on that path.
  Notably `coordinator.py:5013` also calls `_refresh_config` but is
  gated behind `_is_cover_automation_enabled()` — NOT universal;
  coverage of paths going through `:5013` is per-key.
  Staleness bound: ≤1 tick, acceptable for threshold-class values.
- **EXCLUDED** (default) — any key whose consumer set the builder
  cannot fully classify LIVE or REFRESHED-with-coverage. Stays OUT of
  the allowlist; save falls through to reload. The builder does NOT
  allowlist on suspicion.

**Per-consumer-site verdicts, min-wins (plan-review P9).** The audit
table lists EVERY consumer site for each key with its own LIVE /
REFRESHED / EXCLUDED verdict; the key's final verdict is the
**minimum** across sites (LIVE > REFRESHED > EXCLUDED, in safety
order). Concrete instance: `CONF_HUMIDITY_FAN_THRESHOLD` has both a
REFRESHED site (`automation.py:2542`, reads `self.config.get(...)`;
refreshed via `_refresh_config`) and a LIVE site
(`binary_sensor.py:1080`, reads `merged.get(...)`). Verdict = REFRESHED
(the weaker site wins). A key allowlisted on the LIVE site alone while
another site cached it would be a concept-split bug
([[feedback_coincidental_equality_masks_concept_split]]).

**Push-in-place (rare, only if trivial) — mirrors `_EC_SETTER_DISPATCH`.**
When a CACHED consumer exists whose refresh mechanism is one-line and
idempotent (e.g. a setter on a live coordinator), the suppress branch
may dispatch it before the `return` at `__init__.py:7715`, in the style
of the CM `_EC_SETTER_DISPATCH` loop at `__init__.py:7458` (NOT the
`_NM_A2_KEYS` set at `:6393`, which extends `_NO_LIVE_ATTR_KEYS` — a
NO-push, live-read set). **Prefer EXCLUDE over push.** Push is only
worth the code weight when the alternative is a common-path reload.

**Pre-build enumeration (build output, plan asserts the shape only).**
The builder reads `config_flow.py:async_step_climate` (both create at
`:2549-2707` and options at `:11432-11754`) and produces the EXACT
field list — no key may be guessed. From the read above (§1.5) the
climate-step submitted keys are (audit-table columns to be filled by the
builder before adding any key to the allowlist):

| CONF key | Source line | Per-site verdict (site: LIVE/REFRESHED/EXCLUDED) | Key verdict (min over sites) |
|---|---|---|---|
| `CONF_HVAC_COORDINATION_ENABLED` | `config_flow.py:2599, 11524` | TBD (list every consumer site) | TBD |
| `CONF_FAN_CONTROL_ENABLED` | `:2600, 11528` | **already allowlisted, LIVE** — see `__init__.py:7665-7673` audit | KEEP |
| `CONF_COMFORT_FAN_AWAY_VETO_ENABLED` | `:2606, 11532` | TBD | TBD |
| `CONF_HUMIDITY_FAN_CONTROL_ENABLED` | `:2610, 11540` | **already allowlisted, LIVE** — see `__init__.py:7665-7673` audit | KEEP |
| `CONF_WET_ROOM` | `:2613, 11547` | TBD | TBD |
| `CONF_BLE_HOLD_CAP_ENABLED` | `:2615, 11550` | TBD | TBD |
| `CONF_HUMIDITY_FAN_SPIKE_ENABLED` | `:2618, 11557` | TBD | TBD |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED` | `:2621, 11561` | TBD | TBD |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S` | `:2624, 11567` | TBD | TBD |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S` | `:2630, 11576` | TBD | TBD |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S` | `:2636, 11585` | TBD | TBD |
| `CONF_FAN_TEMP_THRESHOLD` | `:2641, 11594` | TBD | TBD |
| `CONF_HUMIDITY_FAN_THRESHOLD` | `:2644, 11618` | **REFRESHED (`automation.py:2542` via `_refresh_config`); LIVE (`binary_sensor.py:1080` via `merged.get`)** — min = REFRESHED | REFRESHED (requires coverage proof on the automation.py path) |
| `CONF_HUMIDITY_FAN_TIMEOUT` | `:2647, 11624` | TBD | TBD |
| `CONF_HUMIDITY_FAN_MAX_RUNTIME` | `:2650, 11630` | TBD | TBD |
| `CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT` | `:2657, 11638` (advanced) | TBD | TBD |
| `CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S` | `:2663, 11647` (advanced) | TBD | TBD |
| `CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE` | `:2669, 11656` (advanced) | TBD | TBD |
| `CONF_FAN_SPEED_LOW_TEMP` | `:2719, 11600` | TBD | TBD |
| `CONF_FAN_SPEED_MED_TEMP` | `:2722, 11606` | TBD | TBD |
| `CONF_FAN_SPEED_HIGH_TEMP` | `:2725, 11612` | TBD | TBD |
| `CONF_TARGET_TEMP_HEAT` | `:2685, 11677` | TBD | TBD |
| `CONF_TARGET_TEMP_COOL` | `:2688, 11683` | TBD | TBD |
| `CONF_CLIMATE_ENTITY` | `:2692, 11689` | TBD | TBD |
| `CONF_HVAC_VACANCY_HOLD` | options-flow schema range `config_flow.py:11519-11746` | **LIVE** — `hvac_zones._effective_hvac_hold_seconds` takes as CALL PARAMETER (`hvac_zones.py:894-940`); callers pass per-call (`hvac_zones.py:1018`, `binary_sensor.py:894`). Immune to P7 materialization via `merged.pop` at `config_flow.py:11485-11493`. | LIVE — one of the safest to allowlist |
| `CONF_HVAC_VACANCY_HOLD_NIGHT` | options-flow schema range `config_flow.py:11519-11746` | as above | LIVE |

**Note (plan-review P8):** options-flow line cites above may drift as
`config_flow.py` evolves; the authoritative range for the climate step
is `config_flow.py:11432-11754` (write handler) and
`:11519-11746` (schema). The 26-key set is complete/correct;
individual line numbers are a starting point, not a contract.

**Audit-comment style:** MIRROR the existing block at
`__init__.py:7642-7659` (CONF_ZONE audit) and `:7665-7673`
(fan-toggle audit). Each newly-allowlisted key gets 3-6 lines: the
per-consumer-site file:line list with its verdict, the reason it's LIVE
or REFRESHED-with-coverage, the specific refresher call site if
REFRESHED, and a one-liner on what would flip it to EXCLUDED.

**Default-materialization test coverage (plan-review P7).** Add a
"virgin room" test: create a ROOM whose options do NOT contain any of
the ~20 climate keys, save the climate step with the operator changing
ONLY one allowlisted key, assert that the ~19 default-materialized keys
also all resolve into the allowlist (i.e. suppress still holds). If a
single EXCLUDED key is default-materialized into the write, the test
MUST assert fall-through — no silent pass.

**Non-goals inside D1:**
- No new CONF keys.
- No refactor of any consumer from CACHED → LIVE / REFRESHED. If a key
  is CACHED and the push is non-trivial, EXCLUDE it — do not rewrite
  the consumer in this cycle.
- No change to the create-flow write path (it uses `_data.update()`
  and finalizes in `async_step_notifications`, not `async_step_climate`
  directly — see `:2582-2584`; the create flow is out of scope: on
  create, a full setup runs anyway).

### D1 Acceptance Criteria (discriminating)

- **Verify (INV-A pass, suppression happens):** A toggle of one
  LIVE key produces a single log line `"ROOM options changed for '<room>'
  … suppressing reload (changed_keys=[…])"` and **zero** `"Setting up
  universal_room_automation"` / platform setup lines for that entry
  within 30s of save.
- **Verify (INV-A discriminator: stale-cache NOT admitted):** A change
  to any key classified EXCLUDED causes the fall-through reload — log
  line `"ROOM options changed … suppressing reload"` MUST NOT appear
  for that save. A test that suppresses an EXCLUDED key is a FAIL.
- **Verify (consumer freshness — LIVE):** For each newly-allowlisted
  LIVE key, a behavioral test toggles the value in `entry.options`,
  does NOT reload, and asserts the next coordinator tick / entity
  update reads the new value.
- **Verify (consumer freshness — REFRESHED):** For each
  REFRESHED-with-coverage key, the test drives the enclosing entry-
  point (tick / `handle_occupancy_change`) and asserts the refresher
  ran BEFORE the read (source-mutation drill: neuter the specific
  `_refresh_config` call cited as coverage; test MUST fail; restore).
- **Verify (virgin-room, per plan-review P7):** A "virgin room" first
  climate-step save (default-materialization of ~20 keys) suppresses
  when only allowlisted keys differ from the setup snapshot (proves
  the allowlist covers the materialization set AND that D0 seeded
  correctly).
- **Entity identity-stable:** For any key in the extended allowlist,
  entity-object `id()` for a sampled room-scoped entity is identical
  before and after the save (proves no teardown/re-add).
- **Sensor:** `sensor.<room>_active_holds` (or another live per-room
  sensor) shows `last_changed` unchanged on sibling rooms across the
  save.
- **Test:** `quality/tests/test_room_options_reload_suppression.py`
  (extend or add) — one test per newly-allowlisted key; plus one test
  per key intentionally EXCLUDED asserting fall-through; plus the
  virgin-room test.
- **Test authority = source-mutation.** Reviewer C neuters the
  cited-live-read (or the cited refresher call site for REFRESHED
  keys); ONE specific test must fail; restore (Tier 2-DB Review C
  convention). Verify bytecode-cache discipline
  ([[feedback_mutation_verification_pycache_staleness]]).
- **Live (post-restart):** Save a real climate-step form on one room
  with only an allowlisted toggle changed; observe (a) no "Setting up"
  log for that entry, (b) HA UI remains responsive (subjective, but
  ≤2s stall vs baseline 10-30s). See D2 for log-clarity criteria on
  the fall-through path.

### D2 — Kill the "sibling re-claim" log noise (log-clarity/dedup only)

**Plan-review P3 (HIGH) — correct finding.** The original D2 claim
that D1 subsumes D2 was FALSIFIED. The two substrate WARNs at
`occupancy_substrate.py:219` (`"multiple CONF lists for room '%s'"`)
and its cross-room-claim sibling (`"claimed by multiple rooms"` in the
same `_discover_entity_map` neighbourhood at `:200-230`) fire BEFORE
the no-diff fast-path at `:436-442`, and are **not** log-once. On the
suppressed path the ROOM branch DOES dispatch
`SIGNAL_ROOM_ENTRY_LIFECYCLE` (`__init__.py:7700-7714`) →
`presence.py` handler → `refresh_subscriptions` → `_discover_entity_map`,
so those two WARNs re-emit on every suppressed save. D1 does NOT
silence them.

**Two acceptable outcomes for D2 (choose one at build time):**

- **D2a (preferred — log-once dedup).** Add log-once/dedup to those
  two WARNs on a stable key (e.g. `(entity_id, room_name)` for the
  cross-room claim; `(entity_id, room_name, kind)` for the multi-CONF
  case). This is faithful to D2's original spirit ("kill the
  misread") without touching `_discover_entity_map`'s claim
  arbitration semantics.
- **D2b (fallback — drop the acceptance criterion).** If a safe
  log-once key can't be defined without altering arbitration, drop
  the "no sibling re-claim warning" acceptance criterion outright and
  document in the audit block that these two WARNs are pre-existing +
  orthogonal (they are correct log output about a real config-shape
  condition; the misread is on the reader's side).

**Parking of the per-room `refresh_subscriptions` refactor stays
justified**, but not on the falsified "solved by D1" basis. The
correct rationale: dedup needs the FULL desired entity set to detect
claim overlap (first-claim-wins arbitration at
`occupancy_substrate.py:200-230`); a scoped per-room refresh would
have to re-derive the whole desired set anyway. Card:
`SUBSTRATE-PER-ROOM-REFRESH-1` (parked; not in scope).

### D2 Acceptance Criteria (discriminating)

- **Verify (INV-B pass on suppressed path):** On a climate-step save
  whose changed_keys ⊂ `_ROOM_SUPPRESS_KEYS`, the substrate reaches
  the no-diff return at `occupancy_substrate.py:442` — no bucket
  reset, no listener swap, no synthetic-edge dispatch. Log
  `"OccupancySubstrate.refresh_subscriptions: no diff — noop"`
  appears exactly once; no `"emitted N True-edge …"` line appears.
- **Verify (D2a chosen — log dedup):** On the SUPPRESSED path, the
  two `_discover_entity_map` WARNs at
  `occupancy_substrate.py:200-230, :219` emit at most ONCE per stable
  key per process lifetime, not once per save.
- **Verify (D2b chosen — dropped criterion):** The audit block
  explicitly names both WARNs as pre-existing orthogonal noise; no
  behavioural regression asserted.
- **Fall-through path (accepted known-cost, NOT asserted as
  INV-B):** On a fall-through save (EXCLUDED key changed),
  `_reset_and_seed_room_bucket` is expected to run for every room and
  the listener swap is expected to fire. That is correct behaviour;
  see §2. No acceptance criterion is stated against it here; the
  full refactor is `SUBSTRATE-PER-ROOM-REFRESH-1`.
- **Test:** unit test on `refresh_subscriptions` that installs a
  known entity map, fires the signal with no CONF change, and
  asserts the no-diff branch is taken (dispatch counter == 0).
- **Live:** climate-step save on an allowlisted key produces zero
  substrate `emitted …` log lines cluster-wide AND (if D2a chosen)
  zero repeat `"multiple CONF lists"` / `"claimed by multiple rooms"`
  WARNs beyond the first per stable key.

---

## 4. Knob ladder — numbers-get-knobs audit

**Zero new knobs proposed.** Every value in scope is already a CONF or
frozenset membership decision:

| Value | Rung today | Change this cycle |
|---|---|---|
| `_ROOM_SUPPRESS_KEYS` | Module constant (frozenset in `__init__.py`) | EXTEND membership. Correct rung — this is safety-adjacent (a bad allowlist strands cached consumers); belongs behind code review, not operator-tunable. |
| Each climate-step CONF | Options-flow field | UNCHANGED |
| Substrate diff thresholds | N/A (structural) | UNCHANGED |

Rationale: adding a runtime toggle to suppress reload would be a
**footgun knob** (an operator who flips it wrong strands cached state
until the next natural reload). Correct rung is module constant.

---

## 5. Non-goals

- **N-1.** The concurrent Shelly / Tuya / Bond network-timeout storm
  observed in the same log window is a separate integration issue and
  not URA. Not in scope.
- **N-2.** The parent / CM entry reload path is unchanged. This cycle
  is ROOM-entry only (`entry_type == ENTRY_TYPE_ROOM` branch).
- **N-3.** No refactor of any CACHED consumer into LIVE / REFRESHED
  (see D1 non-goal above). Refactors are individually valuable but
  each has its own ripple; carded separately if a specific consumer
  becomes a stall path.
- **N-4.** No per-room substrate scoping refactor (parked as
  `SUBSTRATE-PER-ROOM-REFRESH-1`; see D2). The house-wide reset+seed +
  listener swap on the FALL-THROUGH path is an accepted known-cost
  documented in §2.
- **N-5.** No change to the options-flow UI or the climate-step field
  set.
- **N-6.** No change to the create flow — a new-room create runs full
  platform setup by design.
- **N-7.** No change to the fall-through reload's background-task
  dispatch behavior (v4.0.5 fix at `:7619-7624` remains).
- **N-8 (plan-review P5).** No change to the deferred ZM update path
  fired from a climate save. When the operator saves a climate step
  and the room's zone has no `CONF_ZONE_THERMOSTAT` yet, the flow
  builds `pending_zm_update` at `config_flow.py:11456-11469` and
  fires `hass.config_entries.async_update_entry(zm_entry_ref,
  options=zm_options)` after `asyncio.sleep(2)` at
  `config_flow.py:11499-11509`. That triggers a SEPARATE reload path
  on the ZM entry (via ZM's own `_async_update_listener` branch,
  outside `_ROOM_SUPPRESS_KEYS`). This cycle does NOT touch that
  path; if it needs suppression it will be carded as
  `ZM-CLIMATE-DEFERRED-UPDATE-SUPPRESS-1`.

---

## 6. Review plan (Tier 2-DB — three framing-disjoint reviewers)

Per `CLAUDE.md` §Tier 2-DB. Standing policy: three disjoint framings.

- **Reviewer A — data integrity + consumer-classification correctness.**
  Re-runs the full grep for EVERY climate-step key across ALL surfaces
  in §D1 consumer list; independently classifies **per-site** as
  LIVE / REFRESHED / EXCLUDED (plan-review P2 + P9); the key's verdict
  is the min over sites. Compares to the builder's table. Any
  disagreement = HIGH finding. Verifies that no key was allowlisted
  on the strength of ONE call site while another site cached it
  (concept-split hazard [[feedback_coincidental_equality_masks_concept_split]]).
  For every REFRESHED-marked key, A verifies the cited refresher call
  site precedes every read of that key on that path (coverage, not
  mere existence).
- **Reviewer B — migration correctness + signal chain + D0 wire-up.**
  Verifies (a) D0 seeding runs on every ROOM setup and pops on unload;
  (b) the `SIGNAL_ROOM_ENTRY_LIFECYCLE` dispatch on the suppressed
  path reaches `refresh_subscriptions` and short-circuits at
  `occupancy_substrate.py:442`; (c) fall-through path preserves the
  v4.0.5 background-task semantics; (d) snapshot reseed at `:7723`
  still fires on the fall-through so the NEXT save diffs correctly;
  (e) the deferred ZM update at `config_flow.py:11499-11509` is
  unchanged (N-8).
- **Reviewer C — test authority via source mutation.** For each key
  the builder adds to the allowlist, C edits the production consumer
  source to neuter its live-read (LIVE) or the specific refresher call
  cited as coverage (REFRESHED), runs the suite, asserts a SPECIFIC
  test fails, restores. A key whose neuter leaves the suite green is
  not really tested — HIGH finding, block ship. C also runs the D0
  neuter drill (comment out the setup seeding line; the
  first-save-suppression test MUST fail). Verifies bytecode-cache
  discipline ([[feedback_mutation_verification_pycache_staleness]]).

**Optional D — adversarial completeness.** Not mandatory for Tier 2-DB
but recommended given the shared-primitive (substrate) touch. D's job:
state INV-A and INV-B (the P4-restated form) as falsifiable, then
break them. Concrete targets: (a) find a climate-step key that
reaches a CACHED consumer via a path A/B/C didn't grep; (b) find a
REFRESHED-marked key whose refresh does NOT precede a read on some
reachable path; (c) construct a legal-config sequence where INV-B
fails on the SUPPRESSED path (substrate touches a room bucket on a
suppressed save).

**Plan-review (before build — this document).** This document itself
goes to ONE adversarial plan reviewer per Tier 2 plan-review policy.
The reviewer re-greps the D1 field enumeration against
`config_flow.py:2549-2707` and `:11432-11754` to confirm no key is
missing; re-verifies the LIVE claim for `CONF_HVAC_VACANCY_HOLD[_NIGHT]`
via `hvac_zones._effective_hvac_hold_seconds` call sites; re-verifies
that `room_last_applied_options` is written ONLY at the three cited
listener sites (P1); re-verifies `_NM_A2_KEYS`-vs-`_EC_SETTER_DISPATCH`
role split (P6).

---

## 7. Pre-deploy zero-bugs gate

Per [[feedback_pre_deploy_zero_bugs_gate]]:

- `grep '<<<<<<<'` on the diff — no conflict markers.
- `py_compile` on `__init__.py` and `occupancy_substrate.py`.
- Cycle tests: `pytest quality/tests/test_room_options_reload_suppression.py -v`.
- Suite-baseline-diff vs `pre-review-vX.Y.Z` — name-diff (not count).
- Independent orchestrator verification: re-grep
  `_ROOM_SUPPRESS_KEYS` membership vs the climate-step field list —
  the builder's audit table is a hypothesis until the orchestrator
  re-runs the grep. Also re-grep `room_last_applied_options` writers
  to confirm D0 added exactly one setup-time writer AND one unload
  cleanup.

---

## 8. Live validation (README write-back — MANDATORY)

Post-deploy, the `README_v<version>.md` prospective bullets get
replaced with a `Validated <date>` table:

| Criterion | Result | Evidence |
|---|---|---|
| D0: first-save-after-restart on allowlisted key suppresses | TBD | log line + entry-id trace on fresh HA restart |
| D1: LIVE-key save produces suppress log | TBD | log line `"ROOM options changed … suppressing reload"` cite |
| D1: REFRESHED-key save produces suppress log + consumer reads new value on next tick | TBD | log cite + entity attribute read pre/post save |
| D1: EXCLUDED-key save falls through (reloads) | TBD | log cite + entity-id change confirmed |
| D1: virgin-room first climate save suppresses | TBD | log cite on a room with no prior climate options |
| No platform setup lines for entry within 30s of allowlisted save | TBD | `journalctl -u home-assistant … --since` scan cite |
| Substrate no-diff noop on suppressed path (INV-B) | TBD | `"no diff — noop"` log cite |
| D2 (a or b): repeat `"multiple CONF lists"` / `"claimed by multiple rooms"` noise silenced OR documented as pre-existing | TBD | log cite + audit-block cite |
| HA UI responsive across save (~subjective) | TBD | operator observation |

---

## 9. Plan-completion tracking

Items planned in this doc that will be tracked to completion at cycle
close (§ per CLAUDE.md "Plan Completion Tracking"). **The following are
SHIP GATES — non-negotiable:**

1. **D0 seeding wired at ROOM setup AND unload cleanup shipped.**
   Neuter drill (Reviewer C) proves the setup line is load-bearing.
2. **D1 audit table filled for EVERY climate-step key with
   per-consumer-site verdicts** (LIVE / REFRESHED / EXCLUDED). **No
   TBD rows at ship.** Key verdict = min over sites (plan-review P9).
3. **Virgin-room test** (first climate save on a room with no prior
   climate options) shipped and passing (plan-review P7).
4. Every LIVE / REFRESHED-with-coverage key added to
   `_ROOM_SUPPRESS_KEYS` with inline audit comment mirroring
   `:7642-7673` style, citing per-site verdicts AND (for REFRESHED
   keys) the specific refresher call site proving coverage.
5. Every EXCLUDED key documented in the audit block (why excluded,
   what would flip it).
6. D2 outcome (D2a log-once dedup OR D2b documented-as-pre-existing)
   shipped or explicitly named in ship note.
7. Card `SUBSTRATE-PER-ROOM-REFRESH-1` created (parked) with the
   dedup-invariant rationale from §D2.
8. Card `ZM-CLIMATE-DEFERRED-UPDATE-SUPPRESS-1` created (parked) per
   N-8 — the deferred ZM update from a climate save is out of scope.
9. README validation table (§8) written back post-live-validation.

Any deferred item is explicitly named in the ship note with reason and
card ID — no silent drops.

---

## 10. Risk register (short)

- **R-0 (was hidden; now HIGH — plan-review P1):** Without D0, the
  first climate save per room per HA lifetime fall-through-reloads
  regardless of D1 correctness. Live validation immediately after
  deploy runs in exactly this state. Mitigation: D0 is a ship gate.
- **R-1 (HIGH):** A consumer misclassified LIVE / REFRESHED (actually
  CACHED, or REFRESHED-without-coverage on a reachable path) strands
  stale state on the suppressed path. Mitigation: Reviewer A
  independent per-site re-classification + Reviewer C per-key
  source-mutation test. REFRESHED keys additionally require A to cite
  the specific refresher call site and prove it precedes every read
  on that path.
- **R-1a (HIGH — plan-review P7):** Default-materialization at
  `config_flow.py:11521+` submits ~20 keys on every climate save. One
  EXCLUDED key in the materialization set forces reload for the whole
  form (all-or-nothing). Mitigation: the audit table classifies EVERY
  climate-step key; virgin-room test proves the allowlist covers the
  materialization set.
- **R-2 (MED):** A climate-step key missing from the enumeration
  table (schema drift between plan and build). Mitigation:
  plan-reviewer re-greps the schema; builder writes the enumeration
  table BEFORE editing `_ROOM_SUPPRESS_KEYS`; orchestrator verifies.
- **R-3 (MED):** Snapshot reseed at `:7723` skipped by a control-flow
  slip during the D1 edit. Mitigation: Reviewer B checks; test
  covers "second save after fall-through diffs correctly."
- **R-4 (LOW):** D2 change accidentally alters diff logic.
  Mitigation: D2a is confined to a log-once wrapper on two log
  statements; D2b is doc-only.
- **R-5 (LOW):** The clearable-key semantics for
  `CONF_HVAC_VACANCY_HOLD[_NIGHT]` interact with the snapshot diff
  (unset → present transitions). Mitigation: build enumerates the
  clearable case in the test matrix. Both keys are already classified
  LIVE (§1.5, §D1), so the interaction is benign.

---

## Appendix — Summary of plan-review findings folded (2026-09-19)

- **P1 (CRIT) — D0 added.** Setup-time seeding of
  `room_last_applied_options` + unload cleanup. Blocking prereq of D1.
  Verified: writes only at `__init__.py:7677-7679, :7692, :7723`.
- **P2 (HIGH) — REFRESHED class added.** Third classification with
  proven-coverage requirement. Verified: `automation._refresh_config`
  at `automation.py:867`, called `:922` + `coordinator.py:4934`
  (universal) and `:5013` (gated by `_is_cover_automation_enabled()`,
  NOT universal).
- **P3 (HIGH) — D2 corrected.** D2 chooses log-once dedup (D2a) or
  drops the criterion (D2b). Verified: the two WARNs sit at
  `occupancy_substrate.py:200-230, :219` BEFORE the fast-path at
  `:436-442`; suppress branch dispatches
  `SIGNAL_ROOM_ENTRY_LIFECYCLE` at `__init__.py:7700-7714`.
- **P4 (HIGH) — INV-B restated.** Suppressed-path scoped. Fall-through
  behaviour (reset+seed for every room, house-wide listener swap,
  synthetic edges) moved to §2 as accepted known-cost. Verified:
  `occupancy_substrate.py:454-457, :459-495, :502-529`.
- **P5 (MED) — N-8 added.** Deferred ZM update from a climate save at
  `config_flow.py:11456-11469, :11499-11509` explicitly out of scope;
  carded as `ZM-CLIMATE-DEFERRED-UPDATE-SUPPRESS-1`.
- **P6 (MED) — Push miscite fixed.** CACHED-push mirror target is
  `_EC_SETTER_DISPATCH` (`__init__.py:6693` + loop `:7458`), NOT
  `_NM_A2_KEYS` (which extends `_NO_LIVE_ATTR_KEYS` at `:6822, :6954`
  and pushes NOTHING). Preference EXCLUDE over push documented.
- **P7 (MED) — Default-materialization folded.** §2 states the
  all-or-nothing corollary; virgin-room test is a ship gate.
  Verified: `config_flow.py:11521+` uses
  `default=self._get_current(...)`; `CONF_HVAC_VACANCY_HOLD[_NIGHT]`
  are immune via `merged.pop` at `:11485-11493`.
- **P8 (MED) — Line cites softened.** Options-flow cites replaced
  with symbol names + range cite (`config_flow.py:11519-11746`) where
  drift is likely; 26-key set itself is complete.
- **P9 (MED) — Per-consumer-site verdicts, min-wins.** D1 audit
  table restructured. Example folded: `CONF_HUMIDITY_FAN_THRESHOLD`
  = REFRESHED (`automation.py:2542`) ∧ LIVE (`binary_sensor.py:1080`)
  → verdict REFRESHED.
- **CORRECTION — `_effective_hvac_hold_seconds` is LIVE.** Verified:
  `hvac_zones.py:894-940` takes overrides as CALL PARAMETERS; callers
  pass per-call at `hvac_zones.py:1018`, `binary_sensor.py:894`. Both
  `CONF_HVAC_VACANCY_HOLD` and `CONF_HVAC_VACANCY_HOLD_NIGHT` are
  reclassified LIVE (was CACHED-suspected).
