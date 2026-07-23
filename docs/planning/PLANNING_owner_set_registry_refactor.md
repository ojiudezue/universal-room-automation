# PLANNING — EVSE Owner-Set Persistence Registry + `energy_pool` Module Extraction

**Status:** BUILD-READY (planner), operator scheduling required (BACKLOG top entry, 2026-07-20)
**Cycle type:** Behavior-frozen refactor
**Tier proposed:** **Tier 3 (four framing-disjoint reviews + operator checkpoint before deploy)** — see §5 for the argument. The BACKLOG entry says "2-DB"; this plan argues the blast radius pushes it.
**Base commit:** develop, post-v5.28.0 (blind-window guard just landed — the registry MUST absorb its N+1 owner surfaces or the refactor undoes them)
**Sequencing gate:** NM overhaul pipeline Cycle C closed AND operator scheduling (BACKLOG line 26-28). Do NOT enter build without explicit go.

---

## 0. Load-bearing invariant (falsifiable, up-front — Tier 3 discipline)

> **For every legal (owner-state × TOU period × SOC × precedence event) input tuple in the fixture sweep, the pre-refactor and post-refactor code produce byte-identical:**
> **(a) `determine_actions(...)` action lists** (same order, same evse_id, same action verb, same payload keys),
> **(b) resulting owner-set memberships after applying the action list** (all 12+ sets, both EV and plug tiers),
> **(c) `_save_evse_state` KV payload** (JSON-normalized, key-sorted),
> **(d) `get_status()`  → `pause_reason_human` and `energy_status` per EVSE/plug,**
> **(e) dispatch-ownership bookkeeping** (`_dispatch_owners`, `_pause_dispatch_ts` liveness).
>
> Any diff on any of the five surfaces on any tuple = FAIL. This is the singular property Reviewer D must attempt to falsify.

---

## 1. Context-wide blast-radius audit (operator gate)

Grepped exhaustively across the repo (`_paused_by_*`, `_excess_solar_*`, `_proactive_offpeak_*`, `_blind_window_*`, `_load_shed_was_on_*`, `_arbitrage_pause_reason`, `_dispatch_owners`, `pause_reason_human`, `paused_by_energy`). Two owner tiers exist: EV pool (`EVChargerController`, `energy_pool.py:181`) and Smart-plug tier (`SmartPlugController`, `energy_pool.py:~2780`). Each has its own owner sets; the registry must model BOTH tiers (proposed shared abstraction, tier-scoped instances).

### 1a. EV-pool owners (12 surfaces — matches §2.4b table)

| # | Owner attr | Init:line | Purpose / precedence row (§2.4b) | Persistence key(s) in `_save_evse_state` / `_restore_evse_state` (`energy.py:~1347–1907`) | Peer-holds membership (`_stronger_peer_holds`, `energy_pool.py:~398–410`) | Inline mentions in OTHER owners' deferral / release lists | Dispatch-ownership tag | Prune membership (`_prune_removed_evses`, `energy_pool.py:779–797`) |
|---|---|---|---|---|---|---|---|---|
| 1 | `_paused_by_us` (TOU) | 196 | TOU peak/mid-peak pause | `paused_by_energy` (per-EVSE bool, `energy.py:1347,1833`) | NO (TOU is subordinate to protection owners) | discard sites: 1178, 1195, 1246, 1556, 2643; peer-check: 1934, 2172, 2359, 2653, 2695, 2734, 2917, 3255, 3414, 3480, 3505 | `"tou"` (via `_claim_pause_dispatch_owner`) | YES (780) |
| 2 | `_excess_solar_active` | 197 | Excess-solar grant | `excess_solar_active` per-EVSE bool (`energy.py:1357,1834`) | NO (grant, not pause) | 890, 1341, 1439, 1453, 1485, 1513, 1577, 1592, 1600, 1608, 1620, 2135, 2471, 2577, 3499(plug-tier read) | n/a (state, not a pause dispatch) | YES (781) |
| 3 | `_paused_by_grid_cap` | 198 | Grid import cap | `evse_paused_by_grid_cap` list (`energy.py:1379,1840`) | YES (400) | 1646, 1652, 1657, 1677, 1693, 1933, 2170, 2357, 2562, 2647, 2689, 2729 | `"grid_cap"` | YES (782) |
| 4 | `_paused_by_battery_drain` | 199 | Battery drain-protection | `evse_paused_by_battery_drain` list (`energy.py:1390,1844`) | YES (398) | 1666, 1774, 1788, 1807, 1815, 1880, 1893, 1940, 1961, 2171, 2358, 2560, 2647, 2688, 2729, 3143, 3155, 3171, 3179, 3223, 3232, 3259, 3279, 3415, 3478, 3502 | `"battery_drain"` | YES (783) |
| 5 | `_paused_by_dp` (drain-precedence) | 211 | EVSE drain-precedence transition | `evse_paused_by_dp` list (`energy.py:1439,1866`) — **intent-state, must persist** | **NO — intentionally excluded (energy_pool.py:389-393); TOU + excess-solar consult it INLINE** | 1173, 1543, 1546, 1568, 2570, 3861, 3892, 3959, 4114, 4146, 4287 | `"dp"` | YES (789) |
| 6 | `_paused_by_arbitrage` | 217 | Arbitrage compound-load protection | `evse_paused_by_arbitrage` list (`energy.py:1417,1854`) + `_arbitrage_pause_reason` side-map (241) | YES (401) | 855, 1190, 1193, 1935, 2173, 2299, 2308, 2316, 2328, 2344, 2564, 2650, 2690, 2731; sensor cross-ref `sensor.py:7046` | `"arbitrage"` (label from `_arbitrage_pause_reason` ∈ {redirect, breaker}) | YES (784) |
| 7 | `_paused_by_load_shed` | 226 | Load-shed EV tier | **NOT PERSISTED** (in-RAM only, re-derived from `_paused_by_load_shed` reconstruction in `energy.py:2358`) + `_load_shed_was_on_at_shed` dict (233) IS persisted | YES (402) | 1667, 2174, 2360, 2648, 2691, 2732 | `"load_shed"` | **NO — missing from `_prune_removed_evses` (bug candidate, flag in audit)** |
| 8 | `_paused_by_fill_priority` | 284 | Fill-priority hold | `evse_paused_by_fill_priority` list (`energy.py:1405,1849`) | YES (399) | 1668, 1936, 2029, 2066, 2084, 2096, 2109, 2117, 2149, 2163, 2178, 2200, 2470, 2558, 2649, 2685, 2730, 3256, 3338, 3354, 3365, 3373, 3381, 3396, 3410, 3437, 3479, 3499, 3502 | `"fill_priority"` | YES (785) |
| 9 | `_proactive_offpeak_holds` | 261 | Off-peak proactive turn-on intent | `evse_proactive_offpeak_holds` list (`energy.py:1450,1870`) — **intent-state, must persist** (256-257 comment is load-bearing) | NO (intent-state, not a pause) | 888, 976, 1136, 1179, 1196, 1220, 1245, 1357, 1976, 2588, 2643, 2679(clear), 2939, 2955, 2973, 2989 | n/a | YES (787) |
| 10 | `_paused_by_blind_window` | 313 | Blind-window guard pause (v5.28.0) | `evse_blind_window_paused` list (`energy.py:1461,1878`) + epoch `evse_blind_window_epoch_started_at` (1492,1907) | YES (409) — **added by v5.28.0** | 571, 947, 974, 977, 981, 1084, 1112, 1152, 1379, 1486, 1675, 1938, 2176, 2362, 2653, 2697, 2736 | `"blind_window"` | YES (791) |
| 11 | `_blind_window_liveness_ride` | 373 | Per-epoch liveness-ride latch (v5.28.0, D-HIGH-3 fix-up Batch 6) | `evse_blind_window_liveness_ride` list (`energy.py:1472,1888`) | via short-circuit in `_stronger_peer_holds` guard consumers (562-565) | 502, 508, 570, 972, 1083, 1462 | n/a (latch) | YES (793) |
| 12 | `_paused_by_us` peer surface `_force_charge_until` window (250) + companion admin bypass | 250 | Force-charge admin bypass (window, not a set) | **NOT PERSISTED** (window ephemeral by design; Bug Class #7 tolerated) | short-circuits ALL owners when active (via `force_charge_active` flag path 1152) | 866-869, 1152 | n/a | n/a |

**Auxiliary maps that ride with owners (must be modeled in the registry):**
- `_load_shed_was_on_at_shed: dict[str,bool]` (233) — release policy for #7, persisted.
- `_arbitrage_pause_reason: dict[str,str]` (241) — resume-policy label for #6.
- `_battery_drain_cooldown: dict[str,float]` (242) — cooldown for #4.
- `_dispatch_owners: dict[str, set[str]]` (278) — reference-counted, references owner tags of #1,#3,#4,#5,#6,#7,#8,#10.
- `_pause_dispatch_ts`, `_observed_off_since_pause` (269-270) — shared manual-override detection state, ref-counted by `_dispatch_owners`.
- Blind-window scalars: `_blind_window_entry_first_at` (314), `_blind_window_epoch_started_at` (315), `_blind_window_defers_this_epoch` (316), `_blind_window_pre_engaged` (326).

### 1b. Plug-tier owners (5 surfaces — parallel schema, tier-scoped instances)

`SmartPlugController.__init__` (`energy_pool.py:~2790–2824`):
1. `_paused_by_us` (2793) — TOU pause (plug tier).
2. `_paused_by_battery_drain` (2794).
3. `_paused_by_fill_priority` (2802).
4. `_paused_by_load_shed` (2807).
5. `_proactive_offpeak_holds` (2824).

Persistence: bundled through the same `_save_evse_state` path (`energy.py:3089–3093`). NO plug-tier equivalents of grid_cap, arbitrage, dp, blind_window, liveness-ride, excess_solar — the registry declaration set is a **strict subset** of the EV declarations.

### 1c. Cross-tier / cross-file consumer sweep (context-wide rule)

- **`sensor.py`:**
  - `sensor.py:7046` reads `paused_by_arbitrage` from `get_status()` as `evse_paused_by_arbitrage` D4 cross-ref.
  - `sensor.py:7075` reads `paused_by_arbitrage`, `sensor.py:7078` reads `paused_by_grid_cap`.
  - `sensor.py:8255` reads `paused_by_energy`.
  - `pause_reason_human` (per-EVSE and per-plug dict emitted at `energy_pool.py:2597–2617`) — surfaced on the EV charging-status sensor + battery-strategy sensor.
- **`get_status()` public dict keys** (`energy_pool.py:2456–2485`) exposed as HA sensor attrs — **the registry MUST reproduce every key byte-identically:** `paused_by_energy`, `paused_by_grid_cap`, `paused_by_battery_drain`, `paused_by_arbitrage`, `paused_by_fill_priority`, `excess_solar_active`, `excess_solar_evses`, `proactive_offpeak_holds`, and the parallel plug-tier keys (`energy_pool.py:3546–3548`).
- **`energy.py` load-shed cascade** (2358, 2362, 2384, 2385, 2436, 2437) reads `_paused_by_load_shed` directly on both controllers — a private-attr cross-module coupling the registry can either preserve as-is (behavior-frozen) or expose via a facade method. **Preserve as-is for the byte-identical property; facade cleanup is a follow-up cycle.**
- **`__init__.py`** — no direct references (setup path only).
- **`number.py`, `switch.py`, `config_flow.py`, `binary_sensor.py`** — no owner-set reads. Safe.
- **Test files touching owner sets:**
  - `quality/tests/test_evse_drain_precedence_session_b2b_ii.py`
  - `quality/tests/test_evse_drain_precedence_session_b2c1_fixup.py`
  - `quality/tests/test_energy_pause_release_hygiene.py`
  - `quality/tests/test_blind_window_evse_guard.py`
  - `quality/tests/test_fill_priority_daylight_restoration.py`
  - `quality/tests/test_dp_yields_to_excess_solar.py`
  - `quality/tests/test_part2_ec_hc_writeback.py`
  - `quality/tests/test_v4761_labels_helpers_excess_solar_number.py`
  - All eight touch private attrs — the refactor MUST preserve attr names OR the plan lists these files as required migration targets. Recommendation: preserve names (registry-backed properties, not renames).
- **Dashboards / PWA / Shipwatch:**
  - PWA (`~/Code/ura-dashboard-pwa`) and `/ura-v6` read `pause_reason_human` + `energy_status` off the EV charging-status sensor. Byte-identical status-token & message strings are contract.
  - Shipwatch READMEs — none currently include acceptance hypotheses on owner-set attrs (spot-checked `README_v5.28.0.md`), but the module-extract cycle README will. Author acceptance in the new `home_assistant.state_attribute` schema (BACKLOG line 66-71).
- **Docs:**
  - `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.4b (commit a0d48a95) — precedence table is the contract. Registry declarations MUST cite the §2.4b row for each owner (see §3 OwnerDeclaration schema).
  - `docs/planning/PLANNING_ec_blind_window_evse_guard.md` — the guard's 7-batch fix-up history is the motivating evidence. Every batch added a new deferral-list mention or persistence key; the registry replaces those N-owner touch-points with 1 owner declaration edit.
  - `docs/planning/PLANNING_fill_priority_daylight_restoration.md` — daylight branch (§6 sequencing) will add ONE more owner touch-point per pattern; the registry must land BEFORE this branch enters build, or daylight-restoration pays the N+1 tax too.

### 1d. Blast-radius summary

- **12 EV-pool owners + 5 plug-tier owners = 17 owner surfaces.**
- **Per owner, an average of 8–15 inline call sites** across peer-check, discard, add, precedence-classifier, and persistence code paths. Cross-owner deferral lists (`_stronger_peer_holds`, plug `_paused_by_us` peer-list, etc.) mention 4–7 sibling owners each.
- **~350 owner-attr call sites total** in `energy_pool.py` + `energy.py` (grep count from §1a mentions column, order-of-magnitude).
- **8 test files** read owner private attrs directly.
- **5 sensor attrs** are contract-visible outputs whose byte-identity is load-bearing.

---

## 2. Institutional context verified

**Greps run:**
- `_paused_by_|_excess_solar|_proactive_offpeak|_blind_window` → §1a/1b tables built from results.
- `pause_reason_human|paused_by_energy|paused_by_battery_drain|paused_by_fill_priority|paused_by_arbitrage|paused_by_grid_cap|paused_by_dp|excess_solar|proactive_offpeak|blind_window|paused_by_load_shed` across whole repo → 39 files; sensor + database + test hits enumerated in §1c.
- `CONF_ENERGY_EXCESS_SOLAR|_stronger_peer_holds|enumeration_contract` → verified no formal `enumeration_contract` helper exists yet; the v5.28.0 blind-window planning doc coined the term for the guard's own peer-holds check. REUSED name; NEW helper (see §3).

**REUSED vs NEW proposals (this cycle proposes NO new CONF_*, NO new sensors, NO new signals — behavior-frozen):**
- `OwnerDeclaration` dataclass — **NEW.** No equivalent exists in `energy_pool.py` or elsewhere. Justified: the whole point of the cycle.
- `OwnerRegistry.register(...)` — **NEW.** Sibling of `EnergyCoordinator._register_write_verifier` pattern (`energy_write_verify.py`); same shape as a class-level ledger.
- Persistence keys — **REUSED** to the last byte. Every key listed in §1a persistence column is preserved; the registry MERELY iterates them.
- Owner tags for `_dispatch_owners` — **REUSED** ("tou", "grid_cap", "battery_drain", "load_shed", "fill_priority", "arbitrage", "dp", "blind_window"). Verified at `_release_pause_dispatch_owner` (751-769) and claim sites.

**Prior planning docs consulted:**
- `docs/planning/PLANNING_dp_sticky_yields_to_excess_solar.md` (S3 ratified line ~530 — owner sets stay SEPARATE; owner enumeration ~301, 442). **This is the contract.**
- `docs/planning/PLANNING_ec_blind_window_evse_guard.md` — 7 fix-up batches; every batch added a new N-owner surface (deferral list edit ×5, persistence key add ×3, prune-list add ×1). This IS the motivating evidence.
- `docs/planning/PLANNING_fill_priority_daylight_restoration.md` — the fill-priority daylight branch touches owner #8; sequencing implication in §6.
- `docs/planning/PLANNING_part2_ec_hc_options_writeback_retrofit.md` — options-writeback pattern, referenced for RestoreEntity discipline.
- `docs/PLANNING_v3.11.0_ENERGY_REFINEMENT.md` — historical baseline of the pool/plug controller shapes.

**Memory bodies pulled:**
- `feedback_context_wide_scoping.md` (operator 2026-07-10) — the "context-wide sweep" rule that produced §1c.
- `project_v5_5_0_inclement_weather_shipped.md` — Bug Class #53 (computed-but-not-consumed), directly analogous to N-owner peer-list omission.
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — reminder that refactors touching persistence paths can silently balloon write volume; §4 fixture sweep includes a KV-write-count assertion.

**Design docs read:**
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.4b (12-row precedence table — canonical contract).

**Code locations surveyed end-to-end:**
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` — full read of `EVChargerController.__init__` (181-380), `_stronger_peer_holds` (383-410), `_prune_removed_evses` (771-813), `determine_actions` (830-1250), excess-solar block (1300-1620), grid-cap block (1640-1700), drain block (1750-1970), fill-priority block (2029-2210), arbitrage block (2250-2360), `get_status` (2440-2620), TOU/excess-solar/grid-cap drain helpers (2632-2740), `SmartPlugController.__init__` (2790-2830) + parallel sections through 3550.
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — `_save_evse_state` (1820-1910) and `_restore_evse_state` (1330-1640) verified end-to-end.

---

## 3. Registry design sketch

### 3a. `OwnerDeclaration` dataclass (frozen)

```
@dataclass(frozen=True)
class OwnerDeclaration:
    name: str                              # e.g. "battery_drain"
    attr: str                              # e.g. "_paused_by_battery_drain"
    precedence_row: int                    # §2.4b row (1-12); None for non-precedence (intent-state)
    persistence_key: str | None            # KV key in _save_evse_state; None = not persisted
    persistence_kind: Literal["list","per_evse_bool","scalar"] = "list"
    peer_holds_member: bool = True         # inclusion in _stronger_peer_holds
    dispatch_tag: str | None = None        # owner tag for _dispatch_owners; None = not a pause dispatcher
    prune_participant: bool = True         # inclusion in _prune_removed_evses
    exemptions: frozenset[str] = frozenset()  # sibling owners that MAY pre-empt (e.g. force_charge)
    tier: Literal["evse","plug"] = "evse"
    side_maps: tuple[str,...] = ()         # companion attrs (e.g. _load_shed_was_on_at_shed)
    reason_token: str = ""                 # for pause_reason_human/energy_status classifier
    reason_human: str = ""                 # human-readable pause message
```

### 3b. `OwnerRegistry` (class-level, one instance per controller tier)

Responsibilities (all derived from declarations — the point is single source of truth):
1. **Enumeration contract:** `iter_all()`, `iter_persisted()`, `iter_peer_holds()`, `iter_prune_participants()`, `iter_by_dispatch_tag(tag)`.
2. **Persistence facade:** `save(controller, kv) -> None` iterates persisted declarations and writes; `restore(controller, kv) -> None` reverse. Replaces the hand-rolled loop at `energy.py:1830-1907` and `energy.py:1347-1490`.
3. **Peer-holds derivation:** `stronger_peer_holds(controller, evse_id) -> bool` iterates `iter_peer_holds()` and short-circuits — replaces the hand-rolled `_stronger_peer_holds` at `energy_pool.py:398-410`.
4. **Prune facade:** `prune(controller, known_evses) -> None` replaces the hand-rolled tuple in `_prune_removed_evses`.
5. **Dispatch bookkeeping:** claim/release helpers pull owner-tag from the declaration, eliminating the string-literal tags scattered at call sites.
6. **Classifier data:** `_classify_evse` (2557-2594) becomes a table walk over declarations sorted by `precedence_row`.

### 3c. Migration strategy — big-bang vs one-owner-at-a-time

**Recommendation: big-bang, with the fixture sweep as the oracle.** Argument:

- **One-owner-at-a-time is tempting but breaks the invariant.** Every declaration adds itself to `_stronger_peer_holds` AND to sibling owners' inline deferral lists. Halfway states leave the enumeration contract asymmetric — owner N migrated to registry-derived `iter_peer_holds()`, but owner N+1 still hand-rolls its check. Bug Class #53 (computed-but-not-consumed) reappears in transition.
- **Big-bang works IF and ONLY IF the fixture-sweep oracle exists first.** Capture the golden output from `pre-refactor-vX.Y.Z` tag, then diff post-refactor. Any tuple that differs is a build error.
- **Sequence:**
  1. Capture golden (§4) BEFORE any code change.
  2. Extract `OwnerRegistry` + declarations in ONE commit (no behavior touches).
  3. Migrate `_save_evse_state`, `_restore_evse_state`, `_prune_removed_evses`, `_stronger_peer_holds`, `_classify_evse` to registry-derived in ONE commit each (five commits, each provably byte-identical against golden — small enough to bisect).
  4. Extract `EVChargerController` + `SmartPlugController` + `OwnerRegistry` to a new module `energy_pool_owners.py` in ONE commit (import-only diff to `energy_pool.py`).
- **Owner-set attrs stay on the controller instance** (registry references them by name via `getattr`). S3 constraint preserved: owner sets remain SEPARATE.

### 3d. What the registry deliberately does NOT do

- Does NOT merge owner sets (S3).
- Does NOT change owner semantics or precedence (rows preserved verbatim from §2.4b).
- Does NOT introduce new owner tags (all 8 dispatch tags reused verbatim).
- Does NOT add a new persistence key or schema version.
- Does NOT expose new HA entities, sensors, or CONF fields.
- Does NOT touch load-shed cross-file `_paused_by_load_shed` assignments in `energy.py:2358,2362` (facade cleanup deferred to a follow-up cycle).

---

## 4. Byte-identical fixture-sweep design

### 4a. Tuple space

Each fixture case is a tuple `(owner_state, tou_period, soc, precedence_event)`:

- **owner_state:** the 2^17 space of "which owners currently hold this EVSE" is intractable in full. Restrict to the **reachable** subset via the §2.4b precedence table — an EVSE can only legally be in a specific combination of owners. Approach: enumerate the ~40 reachable-configuration classes (drawn from §2.4b + the peer-holds matrix) × per-tier (EV, plug). Adding `_arbitrage_pause_reason` label ∈ {redirect, breaker, None} multiplies by 3 for arbitrage-holding classes.
- **tou_period:** {off_peak, mid_peak, peak, super_peak, unknown} — 5.
- **soc:** {0, 15, 40, 55, 75, 90, 100} — 7 buckets covering reserve floor, drain target, fill target, super, full.
- **precedence_event:** {tick_no_event, ev_toggle_off, ev_toggle_on, force_charge_open, force_charge_expire, excess_solar_grant, excess_solar_revoke, blind_window_enter, blind_window_release, dp_transition, load_shed_activate, load_shed_deescalate, grid_cap_breach, grid_cap_release, drain_trigger, drain_cooldown_expire, fill_priority_engage, fill_priority_release, arbitrage_engage_redirect, arbitrage_engage_breaker, arbitrage_release, prune_removed_evse, restart_roundtrip} — 23.

**Estimated size:** ~40 classes × 2 tiers × 5 TOU × 7 SOC × 23 events ≈ **64,400 cases**. Fixture runs headless (no HA); pre-refactor golden capture ≤ 60s wall on developer laptop. Store golden as gzipped JSONL keyed by tuple hash.

### 4b. Oracle capture

1. Tag `pre-refactor-vX.Y.Z-baseline` at the pre-refactor develop tip.
2. New test `quality/tests/test_owner_registry_byte_identical.py`:
   - `pytest.mark.golden_capture` mode: constructs the tuple space, drives `EVChargerController` + `SmartPlugController` pre-refactor, records the 5-tuple output (action list, owner memberships, KV payload, `get_status()` slice, dispatch bookkeeping) as `quality/tests/golden/owner_registry_baseline.jsonl.gz`.
   - `pytest.mark.golden_verify` mode: replays the same tuple space against the post-refactor controllers, diffs against the golden. Any diff fails the test with the tuple + which of (a)-(e) differed.
3. Commit the golden to the repo (bounded, ~1-2 MB gzipped). Regeneration is a documented, one-line command.
4. **Cannot regenerate golden mid-refactor.** The golden is frozen at baseline; if the refactor's diff reveals a legitimate pre-existing bug, file it as a separate hotfix and re-baseline in a follow-up cycle.

### 4c. Auxiliary fixture assertions (belt & braces)

- KV write count per (owner_state, event) is unchanged (v5.0 write-flood memory).
- `pause_reason_human` string match is character-exact (dashboards read it).
- Owner-attr `id()` identity check post-refactor: attrs still exist on the controller (test-file back-compat).

---

## 5. Tier call

**BACKLOG says 2-DB. This plan recommends elevating to Tier 3.** Rationale:

1. **Every owner is touched simultaneously.** Big-bang migration (§3c) is the correct call for correctness reasons, but it means the diff spans ALL 12+5 = 17 owner surfaces AND their ~350 call sites. Three converging framings could all miss ONE — v5.5.3 Tier-3 experience is exactly this shape (Reviewer D found a 7th unclamped emission site; here D would look for the N+1 owner touchpoint the registry didn't absorb).
2. **Money-path + safety-path.** Blind-window guard is safety (battery reserve), arbitrage is money (compound-load breaker), grid_cap is safety (main-panel current). A single owner missing from `iter_peer_holds()` = silent money or safety loss.
3. **Operator standing policy (2026-06-08):** Tier 2-DB (rebranded Tier 3-shape) is the default for regression-prone shared-primitive work. This is textbook shared-primitive: the peer-holds enumeration IS the shared primitive.
4. **Load-bearing invariant is falsifiable** (§0). Reviewer D's job — enumerate the invariant surface, find a legal tuple where pre ≠ post — has a concrete target.
5. **Framings for the four reviews:**
   - **A — local correctness.** Registry declaration accuracy per owner: §2.4b row, persistence key exact match, dispatch-tag string exact match, peer-holds flag correct.
   - **B — integration / persistence-roundtrip.** `_save_evse_state`/`_restore_evse_state` produce byte-identical KV payloads; restart replay through the registry restore recreates identical owner memberships. Cross-tier (EV + plug) bundle preserved.
   - **C — test authority via real per-site source mutation.** For each of the 5 migrated surfaces (persist, restore, prune, peer-holds, classifier), neuter ONE call site in production source, run the byte-identical suite, confirm a SPECIFIC tuple fails. A surface whose mutation leaves suite green = unattested.
   - **D — adversarial completeness / diff-blind.** Enumerate ALL owner surfaces (INCLUDING pre-existing ones the registry may have missed absorbing — e.g. is `_paused_by_load_shed` missing from prune-list a pre-existing bug the registry should fix or preserve? Preserve per behavior-freeze, but flag as follow-up). D also owns the "did any NEW owner get added to `energy_pool.py` between planning and merge" check (v5.28.0 landed 2 new sets — the daylight-restoration branch may add more; §6).

**Fallback:** if operator insists on 2-DB, drop Reviewer C's per-site mutation pass. Do NOT drop D (diff-blind completeness is what buys the byte-identical guarantee).

---

## 6. Sequencing interactions

### 6a. Post-v5.28.0 tree

- v5.28.0 blind-window guard landed 2 new owner surfaces (`_paused_by_blind_window`, `_blind_window_liveness_ride`) + 3 new persistence keys + peer-holds membership + 4 blind-window scalars. **The registry MUST absorb these before the next owner-adding cycle, or the N+1 tax compounds.** The BACKLOG entry pre-dates v5.28.0's fix-up batches; the audit in §1a is post-v5.28.0.
- The v5.28.0 review record (`docs/reviews/code-review/v5.28.0_ec_blind_window_guard.md`) noted the peer-holds enumeration as a known duplication hazard — this cycle closes that hazard.

### 6b. Fill-priority daylight-restoration branch

- `docs/planning/PLANNING_fill_priority_daylight_restoration.md` — will add MORE fill-priority release paths (daylight edge), touching owner #8. Two orderings possible:
  1. **Land registry first, then daylight.** Daylight cycle becomes a 1-declaration edit (change fill_priority reason_human/exemptions) instead of touching 5 sibling deferral lists. Preferred.
  2. **Land daylight first.** Daylight pays the N-owner tax now (~5 sibling touches). Registry cycle absorbs them later.
- **Recommendation to operator:** hold daylight until registry is live. The whole justification for the refactor is that new owner-touching cycles get cheaper AFTER it lands.

### 6c. NM overhaul pipeline (BACKLOG line 26)

Independent workstream. Cycle C closure is the gate per BACKLOG. No code overlap with `energy_pool.py`.

### 6d. Config Subentries (BACKLOG line 30)

Independent. No owner-set overlap.

---

## Deliverables (build-ready enumeration)

- **D1.** Capture golden fixture (§4b), commit tagged baseline. Verify pre-refactor test runs green against fresh golden capture (self-consistency).
- **D2.** Introduce `OwnerDeclaration` + `OwnerRegistry` (new module `energy_pool_owners.py`), populate declarations for all 12 EV + 5 plug owners. No consumer edits yet. **Acceptance:** registry constructs without error; declaration count = 17; §2.4b row coverage = 1-12 unique + intent-state marker for #9,#12 (non-precedence).
- **D3.** Migrate `_save_evse_state` / `_restore_evse_state` (`energy.py`) to iterate `registry.iter_persisted()`. **Acceptance:** byte-identical KV payloads across the fixture sweep.
- **D4.** Migrate `_prune_removed_evses` to iterate `registry.iter_prune_participants()`. **Acceptance:** post-prune owner memberships byte-identical across sweep.
- **D5.** Migrate `_stronger_peer_holds` to iterate `registry.iter_peer_holds()`. **Acceptance:** per-tuple boolean identical across sweep.
- **D6.** Migrate `_classify_evse` (`get_status`, 2557) to table-walk over `iter_all()` sorted by precedence_row. **Acceptance:** `pause_reason_human` + `energy_status` character-identical across sweep.
- **D7.** Extract `EVChargerController` + `SmartPlugController` + registry to `energy_pool_owners.py` (or keep in-file as `energy_pool.py` sub-module if diff is cleaner). Behavior-frozen. **Acceptance:** imports resolve; `energy_pool.py` file-length reduction ≥ 25%; owner-set attrs on controllers unchanged (test back-compat).
- **D8.** Full four-review Tier-3 pass; operator checkpoint before deploy; README with the byte-identical acceptance table.

## Verification steps (planner-authored, reviewer-consumed)

- [ ] `pytest -q quality/tests/test_owner_registry_byte_identical.py` = 0 failures across ~64k tuples.
- [ ] All existing tests listed in §1c green unchanged (attr names preserved).
- [ ] `grep -c "self._paused_by_\|self._excess_solar\|self._proactive_offpeak\|self._blind_window" energy_pool.py` — count preserved or LOWER (helper calls replace them); no NEW inline mentions.
- [ ] `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.4b table cross-referenced against `registry.iter_all()` — every §2.4b row appears once; every declaration cites its §2.4b row.
- [ ] Restart roundtrip in the fixture: `save → clear controllers → restore → assert owner memberships identical`. Extra assertion: no KV keys emitted that weren't in pre-refactor.

---

## Open questions (for operator)

1. **Tier decision.** Plan recommends Tier 3 (§5). Confirm elevation or explicitly override to 2-DB.
2. **Module boundary.** Extract to new file `energy_pool_owners.py`, or keep the classes in `energy_pool.py` and only extract the registry helper? Recommendation: new file — the extraction is the second value prop after persistence unification. But this makes the diff bigger; if the operator prefers minimum-diff, keep in-file.
3. **Preserve `_paused_by_load_shed` absence from `_prune_removed_evses`** (potential pre-existing bug) or fix in-cycle? Recommendation: preserve (behavior-freeze); file follow-up. Alternative: fix, and accept a byte-identity waiver for the prune-removed tuple case.
4. **Preserve cross-file private-attr writes to `_paused_by_load_shed` from `energy.py:2358,2362`** or facade them? Recommendation: preserve; facade cleanup is a follow-up.
5. **Daylight-restoration sequencing** — hold daylight cycle until registry lands? Recommendation: yes.
6. **Golden regeneration policy** — if a legitimate bug is discovered post-golden and fixed in-cycle, do we re-baseline (loses byte-identity guarantee for that tuple) or refuse the fix in this cycle? Recommendation: refuse in-cycle; file hotfix cycle; re-baseline after.

---

## Audit summary (headline)

- **Owner surfaces:** 12 EV + 5 plug = **17**.
- **Persistence keys touched:** **10** (8 list-keys + 1 per-EVSE bool bundle + 1 scalar epoch).
- **Peer-holds members:** **6** EV owners + intent-state exclusions documented.
- **Dispatch tags reused:** **8** (`tou, grid_cap, battery_drain, load_shed, fill_priority, arbitrage, dp, blind_window`).
- **`_prune_removed_evses` participants:** **11** sets + **7** dicts (audit flags load_shed set MISSING — §1a note).
- **Test files reading owner privates:** **8**.
- **Cross-module consumers:** `sensor.py` (5 sites), `energy.py` (~50 sites incl. save/restore/load-shed cascade), dashboards + PWA (via `pause_reason_human` + `energy_status`).
- **Call-site count (approx):** **~350** inline owner-attr mentions in `energy_pool.py` + `energy.py`.

## Design decision recommendations

- Big-bang migration with byte-identical golden oracle (§3c).
- New module `energy_pool_owners.py` (§3c, §D7) — operator override available.
- Preserve all owner attr names (test back-compat) — registry references via `getattr`.
- Preserve pre-existing quirks (load_shed absent from prune, cross-file private writes) in-cycle; file follow-ups.
- Fixture-sweep test lives at `quality/tests/test_owner_registry_byte_identical.py`; golden gzipped in `quality/tests/golden/`.

## Tier call

**Tier 3** (four framing-disjoint reviews A/B/C/D + operator checkpoint before deploy + Live Validation Review E). Operator may downgrade to 2-DB; do NOT drop Reviewer D under any downgrade.

---
## Operator rulings — 2026-07-23 pre-build checkpoint
1. **Tier 3 confirmed** (upgraded from the BACKLOG's 2-DB): four framings
   incl. diff-blind D; operator checkpoint before deploy.
2. **Sequencing: this cycle FIRST**, LKG wave 1 queued behind it (LKG's
   persistence keys will land as registry declarations).
3. **Prune quirk (_paused_by_load_shed): PRESERVE in-cycle** — golden
   oracle reproduces it byte-identically; one-line Tier-1 fix + test lands
   immediately after this cycle merges.
4. (Sequencing note corrected: fill-priority daylight already shipped in
   v5.28.0 — the registry absorbs it as one of the 17.)
