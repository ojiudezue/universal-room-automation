# PLANNING — FAN-LAYER-2: RoomFanState HVAC-tier delegation + oracle.actuate wrap-out

**Card:** FAN-LAYER-2 (deferred scope from FAN-LAYER-1 v5.70.0)
**Author:** ura-planner (opus)
**Date:** 2026-08-11 (rev-2 same day after plan-review round 1)
**Revision:** rev-2 — addresses HIGH-1, HIGH-2, HIGH-3, MED-1..MED-4, LOW-1..LOW-3 from the plan-review-round-1 record at §14.
**Base branch:** `develop` at v5.70.0 (post-merge of FAN-LAYER-1 Sessions 1–3 + fix-up)
**Supersedes:** none — a direct continuation of `docs/planning/PLANNING_fan_actuation_shared_layer_v2.md` §7.9 (INV-FLA-T lock), §7.10 (field-delegation decision), §11 (reader-parity risk) and of the FAN-LAYER-1 review record's deferred-carded scope (`docs/reviews/code-review/v5.70.0_fan_layer_1.md`).

---

## 1. Falsifiable invariants (Reviewer D targets, up front)

Two invariants; both must hold at cycle close.

> **INV-FLA-T (temporal fan-layer authority, from v2 §7.9).** For any room `r`, if `manual_on_hold_until` becomes live at time `T` (via external-ON adopt), NO URA-issued fan OFF against `r` may reach `hass.services.async_call` return at any `T' > T` until the hold expires or is explicitly discharged (external-OFF, kill switch, safety-stop). Equivalent operational restatement: every URA-emitting site listed in §2.2 (W1, W2, W3, W8, W9, W10-pause, W10-restore) executes the `consult → services.async_call → note_actuation` sequence INSIDE an `oracle.actuate(room, trigger, snapshot, direction)` async-with block that holds the per-room `asyncio.Lock` across all three steps; AND every write to `manual_on_hold_until` / `manual_off_cooldown_until` originating from a URA async path (§5.4 classification) is performed under the same per-room lock.
>
> **Concrete legal-config reachable repro to break INV-FLA-T if the lock is missing:** room A has a live `may_turn_off(TEMP_ROOM)` consult that ALLOWed at T0; between T0 and the `await services.async_call` return, an external-ON dispatch fires on room A's fan `state_changed` bus → `RoomFanState.update()` adopt-external path at `hvac_fans.py:335` writes `manual_on_hold_until` at T1; the URA OFF completes at T2. Post-condition: the fan is OFF and the ledger says hold is live — a state the invariant forbids because the emitting caller cannot legitimately claim consult authority once the hold opened. The lock closes this window by forcing the adopt-side write at :335 to acquire the same per-room lock, serializing behind the URA-side critical section.

> **INV-DTA (dual-tier agreement, from FAN-LAYER-1 B-MED-3 residual).** For any room `r` served by BOTH the room-tier surface (`RoomAutomation` in `automation.py`) AND the HVAC-tier surface (`RoomFanState` in `hvac_fans.py`), a call to `oracle.get_state(<key(r)>).manual_on_hold_until` returns the SAME datetime regardless of which tier last wrote — where `<key(r)>` is the SAME string in both tiers per §5.2. Equivalently: `RoomFanState.manual_on_hold_until` and `RoomFanState.manual_off_cooldown_until` are NOT independent state — they are read-through views of the oracle ledger.
>
> **Concrete legal-config reachable repro to break INV-DTA if key spaces diverge:** HVAC-tier zone-vacancy sweep (W8) sees room "Living Room" and its adopt path writes to oracle key `room:Living Room` at T0. Simultaneously the room-tier `may_turn_off(TEMP_ROOM)` consult in `automation.py:2159` runs against oracle key `entry:01H...` (its config-entry id) and returns ALLOW because the room-tier row shows no hold. OFF emits — invariant broken. §5.2 closes this by unifying both tiers on `room:{CONF_ROOM_NAME}` under a uniqueness gate.

Reviewer D's mandate: enumerate the ENTIRE fan-emission surface AND the ENTIRE `RoomFanState` field write surface (§2.1 + §2.2 + §5.4 tables) and mutate one site at a time to prove BOTH invariants. Include pre-existing code, not just the diff.

---

## 2. Institutional context verified

### 2.1 Field-access count — hypothesis "~34" was low; actual **46 lines**

`git grep -n 'manual_off_cooldown_until\|manual_on_hold_until' custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` on develop tip returns **46 lines** (not the ~34 hypothesized in the task brief). Classified against the v2 §11 template AND split by LOW-2 into decision-reads vs observability-reads:

| Category | Lines | Count |
|---|---|---|
| Field declarations + intra-class docstring commentary | 85, 92, 93, 96, 98 | 5 |
| Clear-on-toggle-off writes | 221, 225 | 2 |
| External-OFF adopt path (write cooldown, clear hold) | 308, 312 | 2 |
| External-OFF expiry clear | 323, 325 | 2 |
| External-ON adopt path (write hold) | 335, 339 | 2 |
| External-adopt log lines | 342, 344 | 2 |
| External-ON suppression guard READ | 356 | 1 |
| Adopt-fan commentary + write hold | 401, 403, 404, 411, 415 | 5 |
| Adopt log lines | 418, 420 | 2 |
| Evaluate-path cooldown READ + expiry write | 638, 641, 651 | 3 |
| Adopt-fan speed-set cooldown commentary + READ + double-clear | 838, 842, 844, 847, 849 | 5 |
| restore_after_recheck READ + writes | 1069 (docstring), 1076, 1079, 1081, 1089 | 5 |
| Diagnostic log line | 1212 | 1 |
| Internal-write commentary | 1427 | 1 |
| Pause-context adjustment READ + write | 1469, 1474, 1477, 1484 | 4 |
| Diagnostic sensor filter READ | 1588, 1589, 1597, 1600 | 4 |

**Reads split by consumption class (LOW-2):**

- **DECISION reads** (must be atomically consistent with writes; can influence a URA actuation this tick): `hvac_fans.py:356` (external-ON adopt suppression guard), `:638, :641` (sleep-onset skip on live cooldown), `:842, :844` (temp-fan cooldown gate), `:1076, :1079` (`_is_manual_on_hold_live` — feeds `is_room_in_manual_on_hold` consumed by W8/W9), `:1469, :1474` (pause-context extension R-M-W), `presence_fan_recheck.py:1002, :1007` (recheck cooldown guard). **Total = 11 decision reads.** These paths MUST see the write ordering enforced by §5.4's locked setters.
- **OBSERVABILITY reads** (can tolerate ledger jitter — sub-second staleness fine, drives sensor payloads and log lines only): `hvac_fans.py:1588, :1589, :1597, :1600` (`_build_fan_diagnostic_state` sensor filter), `:342, :344, :418, :420, :1212, :1484` (log-line format-args). **Total = ~10 observability reads.** These are safe under either the fast (unlocked, `set_manual_*`) or slow (locked, `set_manual_*_locked`) setter path.

Real writes (must migrate — §5.4 classifies each): 221, 225, 308, 312, 325, 335, 339, 411, 415, 651, 847, 849, 1081, 1089, 1477. **Total = 15 writes** — fully enumerated + classified in §5.4.

**Presence-fan-recheck reader classification (task item 2).** `_fan_in_manual_cooldown(room_name)` at `presence_fan_recheck.py:992-1014` is the ONLY reader; it reaches through `hass.data → coordinator_manager → hvac.fan_controller._room_fans[room_name]` to peek the ISO string. This reach-through is exactly the "private-field peek" v2 §11 flagged. Migration: **replace with** `oracle = _get_fan_oracle(self.hass); until = oracle.get_state(_room_key(room_name)).manual_off_cooldown_until if oracle else None; return until is not None and dt_util.now() < until`, where `_room_key` is the shared prefixer per §5.2.

### 2.2 Emitter enumeration — the 6 unwrapped writers, **RE-VERIFIED line refs on develop tip** (HIGH-3)

Post-v5.70.0 (Sessions 1–3 shipped), only W11 (`hvac.py:2654` `_stop_all_fans_safety_one`) and W12 (`hvac_predict.py:1164` `_activate_zone_fans`) are wrapped in `oracle.actuate`. Confirmed by `git grep 'oracle\.actuate'`. Six writers remain unwrapped — the v2 line refs I inherited were STALE (they pointed at cover-close code). Re-greped:

| # | Site | Guard file:line (READ) | Emit file:line (`services.async_call`) | Direction | Current gate | Wrap target |
|---|---|---|---|---|---|---|
| W1 | Room-tier temp/vacancy revert (below-threshold or vacant) | `automation.py:2159` (`is_fan_in_manual_on_hold()` check) | `automation.py:2171` (`_safe_service_call("homeassistant", SERVICE_TURN_OFF, ...)`) | OFF | `is_fan_in_manual_on_hold` @property-backed check | `oracle.actuate(room_key, FAN_TRIGGER_TEMP_ROOM, snap, "off")` |
| W2 | Room-tier `FAN_SLEEP_OFF` | `automation.py:2072` (`is_fan_in_manual_on_hold()` check inside `if policy == FAN_SLEEP_OFF:`) | `automation.py:2080` (`_safe_service_call("homeassistant", SERVICE_TURN_OFF, ...)`) | OFF | same | `oracle.actuate(room_key, FAN_TRIGGER_SLEEP_OFF, snap, "off")` |
| W3 | Room-tier turn-ON — two live sites: temp-branch + sleep-onset activate | `automation.py:2234` (`mark_fan_on_issued()` — temp branch) + `:2898` (`mark_fan_on_issued()` — sleep-onset activate). Helper defs `mark_fan_on_issued` at `:511`; edge-emit at `:547` (`oracle.note_actuation`). | temp: `automation.py:~2239-2260` (`fan.turn_on` per-entity loop); sleep-onset: `automation.py:2900-2911` (`fan.turn_on` bulk + `homeassistant.turn_on` for switches). | ON | `mark_fan_on_issued()` seed (oracle.note_actuation edge, Session 2) | `oracle.actuate(room_key, FAN_TRIGGER_TEMP_ROOM_ON \| FAN_TRIGGER_SLEEP_ONSET_ON, snap, "on")` at BOTH sites |
| W4-chokepoint | HVAC `_set_fan_state` service-call block | n/a — chokepoint method | `hvac_fans.py:1231-1258` (per-entity fan.turn_on / homeassistant.turn_on / fan.turn_off / homeassistant.turn_off block) | ON + OFF | reads local ISO via descriptors post-D1 | `oracle.actuate(room_key, trigger_path, snap, direction)` around `1231-1258` |
| W8 | HVAC zone-vacancy sweep — `_execute_vacancy_sweep` | `hvac.py:2751` (`hasattr` check), `:2754` (`is_fan_in_manual_on_hold()`), `:2764` (`is_room_in_manual_on_hold(room_name)`) | `hvac.py:2786` (`services.async_call(domain, "turn_off", ...)` per fan entity — **DIRECT, does NOT go through `_set_fan_state`** — see MED-2 evidence §5.3) | OFF | tier-fused check (both room-tier + HVAC-tier `is_room_in_manual_on_hold`) | INDEPENDENT `oracle.actuate(room_key, FAN_TRIGGER_HVAC_VACANCY, snap, "off")` at the emit site |
| W9 | HVAC pre-arrival deactivation — `_deactivate_prearrival_fans` | `hvac.py:2998` (`hasattr`), `:3000` (`is_fan_in_manual_on_hold()`), `:3006` (`is_room_in_manual_on_hold`) | `hvac.py:3021` (`services.async_call(domain, "turn_off", ...)` per fan entity — **DIRECT, does NOT go through `_set_fan_state`**) | OFF | same tier-fused check | INDEPENDENT `oracle.actuate(room_key, FAN_TRIGGER_HVAC_PREARRIVAL, snap, "off")` at the emit site |
| W10-pause | Presence-fan-recheck pause OFF → `FanController.pause_for_recheck` | `presence_fan_recheck.py:992-1014` (`_fan_in_manual_cooldown` reach-through check upstream) | `hvac_fans.py:1451` (`self._set_fan_state(snapshot["entities"], False, 0)` — enters W4 chokepoint) | OFF | none at emit — chokepoint handles | **NO independent wrap** — W4-chokepoint wrap covers this via the `room_name=None, trigger_path=None` call at `:1451`. Instead: rewrite `:1451` to `self._set_fan_state(..., room_name=room_name, trigger_path=FAN_TRIGGER_RECHECK_PAUSE)` so W4 wrap sees the trigger. |
| W10-restore | Presence-fan-recheck restore ON | `hvac_fans.py:1469-1487` (pause-context extension R-M-W — MED-3) | `hvac_fans.py:~1512+` restore-branch `self._set_fan_state(..., True, speed)` (enters chokepoint) | ON | none at emit — chokepoint handles | Same as W10-pause: routed via W4 chokepoint wrap with `trigger_path=FAN_TRIGGER_RECHECK_RESTORE`. **Additionally:** the R-M-W at `:1469-1487` needs atomic guard — see §5.4 site :1477 classification. |

**Per-site verdict table (task item — "per-site verdict table for all 6 unwrapped writers"):**

| Site | Verdict this cycle | Wrap owner | Wrap independence | Snapshot builder | Trigger constant | Test-name |
|---|---|---|---|---|---|---|
| W1 | WRAP | `RoomAutomation.handle_temperature_based_fan_control` (revert branch) | INDEPENDENT | `_build_fan_snapshot_room` | `FAN_TRIGGER_TEMP_ROOM` (existing) | `test_w1_room_revert_wrapped_in_oracle_actuate` |
| W2 | WRAP | same handler, sleep branch | INDEPENDENT | same helper | `FAN_TRIGGER_SLEEP_OFF` (existing) | `test_w2_sleep_off_wrapped_in_oracle_actuate` |
| W3 | WRAP at BOTH `:2234` and `:2898` | temp-branch handler + sleep-onset activate | INDEPENDENT (both) | same helper | `FAN_TRIGGER_TEMP_ROOM_ON` (temp) / `FAN_TRIGGER_SLEEP_ONSET_ON` (onset) | `test_w3_temp_branch_wrapped`, `test_w3_sleep_onset_wrapped` |
| W4-chokepoint | WRAP `_set_fan_state` service-call block (lines 1231-1258 only) | `FanController._set_fan_state` | CHOKEPOINT | `_build_fan_snapshot_hvac` | trigger propagated via existing `trigger_path` kw arg (already present at `hvac_fans.py:1163`) | `test_w4_set_fan_state_wrapped_and_propagates_trigger` |
| W8 | WRAP INDEPENDENT (does NOT route through `_set_fan_state` — evidence in §5.3) | `hvac.py::_execute_vacancy_sweep` | INDEPENDENT (adjacent-to but NOT nested-inside W4) | `_build_fan_snapshot_hvac` obtained via `hass.data[...][fan_controller]._build_fan_snapshot_hvac(room_name, entities, observed_any_on)` helper | `FAN_TRIGGER_HVAC_VACANCY` (existing) | `test_w8_zone_vacancy_sweep_wrapped` — parity with `test_hvac_zone_vacancy_sweep_respects_manual_on_hold` (v5.70.0 D6) |
| W9 | WRAP INDEPENDENT (same as W8) | `hvac.py::_deactivate_prearrival_fans` | INDEPENDENT | same helper | `FAN_TRIGGER_HVAC_PREARRIVAL` (existing) | `test_w9_prearrival_off_wrapped` — parity with `test_hvac_prearrival_respects_manual_off_cooldown` |
| W10-pause | NO NEW WRAP — routes through W4 chokepoint | `FanController.pause_for_recheck` | ROUTES-THROUGH W4 | (chokepoint builds it) | `FAN_TRIGGER_RECHECK_PAUSE` (existing) — passed via `trigger_path` arg at `:1451` | `test_w10_pause_routes_through_chokepoint_with_recheck_pause_trigger` |
| W10-restore | NO NEW WRAP — routes through W4 chokepoint | `FanController.restore_after_recheck` | ROUTES-THROUGH W4 | (chokepoint builds it) | `FAN_TRIGGER_RECHECK_RESTORE` (existing) | `test_w10_restore_routes_through_chokepoint_with_recheck_restore_trigger` + `test_pause_extension_atomic_vs_adopt_external` (MED-3) |

**None of these writers change POLICY.** The wraps are (a) critical-section discipline (INV-FLA-T) and (b) unification of the emission-path so `note_actuation` fires per-verdict-edge from ONE place.

**Nested-actuate deadlock is avoided by construction:** W4-chokepoint wraps ONLY inside `_set_fan_state`; W8/W9 do NOT call `_set_fan_state` (direct `services.async_call` — evidence §5.3); W10-pause/restore DO call `_set_fan_state` and therefore rely on the chokepoint wrap (no independent wrap at pause/restore). asyncio.Lock is non-reentrant, and this layout ensures no callsite acquires the same per-room lock twice in a single call stack.

### 2.3 Restart / reload semantics — VERIFIED

`RoomFanState` is a `@dataclass` on `FanController` (`hvac_fans.py:67-108`) — **NOT persisted**. Explicit RAM-only comment at line 92: "RAM-only (matches manual_off_cooldown_until — no persistence)." `git grep -E 'RestoreEntity|Store\(|async_save|restore_state|save_state' hvac_fans.py` returns nothing. The dataclass is re-initialized on `discover_fans()` (line 157 `self._room_fans.clear()`), which runs on `FanController.__init__` and on any re-discovery call.

**Comparison to `EVSEState` (task-mentioned "EVSE-state-style blob"):** `EVSEState` uses `homeassistant.helpers.storage.Store` for JSON blob persistence. `RoomFanState` does **not** — it is pure RAM. There is NO save/restore blob to migrate.

**Restart behavior post-migration (invariant preserved):** on boot, the oracle is constructed (`CoordinatorManager` __init__ — Session 2 pattern), `FanController.discover_fans()` clears `_room_fans`, first HVAC tick observes `is_on` state → adopt-external paths at `hvac_fans.py:308-339` fire their oracle writes via the new descriptor / locked setters, ledger re-populates. **No new persistence added, no lifecycle change vs. today.**

**RoomFanState hydration parity note (B-HIGH-1 sister case) — LOAD-BEARING.** The Session-2 room-tier @property `_fan_manual_on_until` at `automation.py:293-296` includes a **hydrate-on-read** step: if `oracle_val is None and local is not None`, it seeds the oracle from local and returns local. The HVAC-tier delegation MUST include the symmetric step because `RoomFanState.manual_on_hold_until` can be non-empty (from adopt-external writes) at the exact instant the oracle-backed delegation ships and the oracle has never seen that room. §5.1 spec covers it explicitly; D1 test `test_hvac_tier_hydrate_on_read_seeds_oracle` anchors it.

**Reload discipline (B-HIGH-2 lesson from FAN-LAYER-1):** `CoordinatorManager` reload must REUSE the existing `hass.data[DOMAIN]["fan_oracle"]`. A fresh oracle on reload would drop HVAC-tier holds the same way it dropped room-tier holds pre-B-HIGH-2 fix. Reviewer B verifies at build that reuse still holds after §5 wiring lands (no touch to `CoordinatorManager` singleton lifecycle in this cycle).

### 2.4 Greps — REUSED vs NEW

REUSED (with file:line):

- `FAN_TRIGGER_*` closed enum — `const.py` (FAN-LAYER-1 D2); imported at `fan_policy_oracle.py:85-93`.
- `FanDecisionSnapshot` — `fan_policy_oracle.py:142-156`.
- `oracle.actuate` async-context helper — `fan_policy_oracle.py:379-409`; consumers at `hvac.py:2654`, `hvac_predict.py:1164`.
- `oracle.set_manual_off_cooldown` / `oracle.set_manual_on_hold` / `oracle.clear_manual_on_hold` — `fan_policy_oracle.py:234-267` (all currently SYNC + UNLOCKED).
- `oracle.get_state(room).<field>` — `fan_policy_oracle.py`.
- `_get_fan_oracle(hass)` accessor — `automation.py` (Session 2).
- `_fan_ledger_key()` prefixed-key contract — `automation.py:250-268` (returns `entry:{eid}` | `room:{name}` | `__unkeyed__`); **AMENDED per §5.2** to prefer `room:{name}`.
- `is_room_in_manual_on_hold(room_name)` — `hvac_fans.py:1094-1106` (consumed by W8/W9 today; retained as a delegate to `oracle.get_state(...).manual_on_hold_until is not None and > now`).
- `mark_fan_on_issued` helper — `automation.py:511`; oracle edge emit at `:547`.
- `is_fan_in_manual_on_hold` helper — `automation.py:495`.
- `_is_manual_on_hold_live(room_fan)` — `hvac_fans.py:1060-1092` (retained; internally rewrites the two ISO reads to descriptor reads which now flow through oracle).

NEW (with justification):

- `_build_fan_snapshot_room(self, entities, observed_any_on)` on `RoomAutomation` **and** `_build_fan_snapshot_hvac(self, room_name, entities, observed_any_on)` on `FanController` — NEW because every wrap needs a `FanDecisionSnapshot` (v2 §7.8 required-positional, no default). Room-tier sets `sleep_axis="room_window"` (per-room `is_sleep_mode_active()` time window); HVAC-tier sets `sleep_axis="house_state"` (`self._house_state`). Axis-mismatch VETO at `fan_policy_oracle.py:471-491` requires the caller supply the correct axis; a shared helper cannot exist across tiers.
- `_room_key(room_name: str) -> str` — module-level helper in `hvac_fans.py` returning `f"room:{room_name}"`. **NEW** thin wrapper for consistency with room-tier `_fan_ledger_key()` prefix scheme (§5.2). Consumers: descriptor, W4/W8/W9 wrap sites, `is_room_in_manual_on_hold`, `_fan_in_manual_cooldown` (via `presence_fan_recheck.py`).
- `_OracleISOField` module-level descriptor class in `hvac_fans.py`. **NEW** — no equivalent exists; the room-tier @property lives on `RoomAutomation` (which has `hass` via self.hass) and cannot be reused for a class whose instances don't hold hass directly.
- `set_manual_on_hold_locked(room, dt)` and `set_manual_off_cooldown_locked(room, dt)` — NEW `async def` methods on `FanPolicyOracle` that `async with self._get_lock(room)` before writing. **NEW** because existing sync setters (`fan_policy_oracle.py:234-267`) do NOT acquire the lock — the gap §5.4 closes for all writes classified `locked_setter_required`.
- Reverse-adjacency AST pass on `quality/tools/audit_fan_adjacency.py` — NEW logic in an EXISTING file. Existing forward walker proves consult→emit adjacency; reverse pass proves every emit was preceded by a consult. **NEW** because no equivalent tooling exists.
- Synthetic-violation fixture in the reverse-scanner test suite (`quality/tests/fixtures/fan_adjacency_synthetic/`) — NEW because MED-4 mandates that if the scanner's inter-procedural taint analysis has gaps (parameter-taint through `_set_fan_state`, `startswith("fan.")` branch), those gaps must be probed by a positive test that the scanner FLAGS a hand-crafted violation.

### 2.5 Prior planning docs consulted

- `PLANNING_fan_actuation_shared_layer_v2.md` — end-to-end; §1, §7.4, §7.7, §7.8, §7.9, §7.10, §7.11, §7.13, §7.14, §11 are the parent spec.
- `docs/reviews/code-review/v5.70.0_fan_layer_1.md` — end-to-end. Bug classes to defend against: **Hollow anchor #13**, **Lifecycle-recreation state loss** (B-HIGH-1 hydration, B-HIGH-2 CM reload), **Silent anchor loss**.
- `PLANNING_fan_manual_on_override.md` (FAN-MANUAL-1) — skim; manual-ON hold semantics unchanged.

### 2.6 Memory bodies pulled

- `feedback_hollow_test_anchors.md` — per-site source mutation via VALUE detachment; §D2 drill list = 6 unwrapped sites.
- `feedback_suppression_needs_discharge.md` — lock acquisition serializes but does not suppress.
- `feedback_no_fabrication.md` — every count grep-cited; every wrap target file:line-cited; "EVSE-state-style blob" hypothesis VERIFIED-and-rejected in §2.3.
- `feedback_mutation_verification_pycache_staleness.md` — Reviewer C drill disables bytecode caching.
- `feedback_marginal_benefit_pushback.md` — §7 pushback analysis.
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — edges-only note_actuation budget preserved; D2 test asserts < 200 rows/hour with all 8 wrap sites live.

### 2.7 Design docs read

`docs/Coordinator/HVAC.md` — v2 D9 write-back owed post-deploy of FAN-LAYER-1; if not yet updated, D5 of this plan absorbs it.

### 2.8 Code locations surveyed end-to-end

- `hvac_fans.py:1-500` (dataclass decl at :67-108, `turn_off_all_managed` at :204-226, adopt paths at :279-421), `:625-720` (sleep-onset skip at :634-651), `:836-849` (evaluate cooldown gate), `:1050-1170` (`_is_manual_on_hold_live` + `is_room_in_manual_on_hold` + `_set_fan_state` signature), `:1230-1268` (W4 chokepoint), `:1400-1512` (`snapshot_room_fan`, `pause_for_recheck`, `restore_after_recheck`), `:1580-1610` (diagnostic filter READs).
- `fan_policy_oracle.py:1-560` (module header, `RoomFanLedger`, `_RoomRecord`, `set_manual_*`, `_get_lock`, `actuate` at :379-409, `_may_turn_off_inner` / `_may_turn_on_inner`, `_check_sleep_axis` at :471-491, `_note_actuation_inner` at :493-560).
- `automation.py:240-395` (`_fan_ledger_key` at :250-268, `_LOCAL_FAN_OFF_KEY` slots, @property delegations), `:495-555` (`is_fan_in_manual_on_hold`, `mark_fan_on_issued` + oracle edge at :547), `:2060-2260` (W1 revert at :2159, W2 sleep-off at :2072, W3 temp-branch at :2234), `:2880-2920` (W3 sleep-onset activate at :2898).
- `presence_fan_recheck.py:990-1020` (`_fan_in_manual_cooldown` reach-through).
- `hvac.py:2570-2700` (W11 reference wrap-shape), `:2700-2800` (W8 `_execute_vacancy_sweep` — checks at :2751/:2754/:2764; emit at :2786), `:2960-3035` (W9 `_deactivate_prearrival_fans` — checks at :2998/:3000/:3006; emit at :3021).
- `hvac_predict.py:1150-1180` (W12 reference wrap-shape).
- `quality/tools/audit_fan_adjacency.py:1-200` (forward-adjacency walker + helpers).

---

## 3. Non-goals (explicit)

- **No new fan POLICIES.** All existing tunables byte-frozen from v5.70.0.
- **No persistence added.** RoomFanState and the oracle ledger remain RAM-only. Adopt-external re-populates on boot.
- **No new operator-facing knobs.** No new CONF_*, no new Number/Select/Switch entity, no new sensor.
- **No dashboard/PWA changes.** No new trigger strings.
- **No W11 / W12 rework.**
- **No unification of room-tier vs HVAC-tier decision sources.** Both tiers still compute their own `desired_on`.
- **No humidity-fan absorption** (unchanged from v2 M2 decision).
- **No shape (a) gateway construction** (v2 §6.5 parked).
- **`RoomFanState` STOPS BEING A `@dataclass`** (MED-1 forces this — see §5.1). It becomes a plain class with an explicit `__init__` so descriptor writes are ordered relative to `_hass` initialization. This is the ONE structural change from v5.70.0. The prior v2 non-goal "No `RoomFanState` dataclass removal" is **rescinded** — the dataclass sugar is what causes the descriptor-flood at construction; removing it is the fix.
- **No test modifications to the FAN-LAYER-1 / v5.68.0 parity gates** (§9). If any must change, STOP.

---

## 4. Tier — Tier 2-DB with ONE adversarial plan review (round 1 complete; round 2 pending per plan-review policy)

**Tier 2-DB (three framing-disjoint code reviews + live validation).** Rationale from rev-1 preserved: invariants + shared-primitive already invented in v5.70.0; this cycle is delegation mechanics against a shipped shape. If operator wants Tier 3 code-review stringency, add a fourth adversarial-completeness review with a mandate to re-enumerate all `RoomFanState` writes AND all fan-domain `services.async_call` sites.

**Plan-review discipline:** rev-1 got ONE plan review (findings at §14). Because that review returned NEEDS-REVISION with 3 HIGHs (including a design-invalidating HIGH-1), the plan-review authority has elevated this to **TWO plan reviews** — a second review will run against rev-2 before build dispatch, per the plan-review record's closing note. Per Tier-3 plan-review protocol this is framing (2) "adversarial build-prediction — what will the builder get wrong reading this?"; framing (1) "completeness — re-enumeration" was the rev-1 review that surfaced HIGH-3 (stale line refs) and HIGH-2 (incomplete write classification).

**Framings for code review (three, disjoint):**
- **Review A — correctness + edge cases + hydrate-on-read parity + sleep-axis routing.** Per-wrap: right axis, right entities tuple, right observed_any_on? note_actuation on correct edge (verdict-change per §7.14 dedup key `(trigger_path, hold_id)`)? Hydrate-on-read fires on first access post-deploy for pre-populated `_manual_*_local`?
- **Review B — async lifecycle + INV-FLA-T + reload resilience + descriptor init order.** Locked setters in §5.4 all cover their classified sites? W8/W9 do not nest inside W4 (no reentrancy deadlock)? Descriptor's `__set__` never called before `_hass` is set (MED-1)? CM reload keeps oracle singleton (B-HIGH-2)?
- **Review C — per-site source mutation + reverse-adjacency scanner authority + synthetic-violation fixture.** For each of the 6 unwrapped sites, comment out ONLY the `async with oracle.actuate(...)` line, run suite, confirm NAMED test fails. For each write in §5.4 classified `locked_setter_required`, comment out the `_locked` suffix (revert to sync setter), run the `test_external_on_racing_ura_*_hvac_tier` fixture, confirm it fails. Run the synthetic-violation fixture through the reverse scanner and confirm the scanner flags it. `PYTHONDONTWRITEBYTECODE=1` + `__pycache__/` purge before drill.

---

## 5. Design

### 5.1 HVAC-tier RoomFanState delegation — plain class, descriptor + hydrate-on-read (MED-1)

**Structural change:** drop `@dataclass` from `RoomFanState`. Use a plain class with an explicit `__init__` that initializes `_hass` and `_manual_*_local` slots BEFORE any descriptor `__set__` can fire. This closes the MED-1 "dataclass __init__ fires __set__ with _hass=None → WARN flood at every discover_fans" concern (dataclass-generated `__init__` does `self.field = value`, which invokes the descriptor). No `__slots__` are declared today (verified via grep — `class RoomFanState` has no `__slots__`); we keep it slot-free to preserve dynamic attribute access for the local + `_hass` additions.

```python
# hvac_fans.py — replaces the @dataclass RoomFanState
class RoomFanState:
    """Tracks fan state for a single room.

    FAN-LAYER-2: dropped `@dataclass` sugar because two of its fields
    (`manual_off_cooldown_until`, `manual_on_hold_until`) are now
    delegated to `FanPolicyOracle` via class-level `_OracleISOField`
    descriptors. dataclass-generated `__init__` invokes `self.field =
    value` on every constructed instance, which would flood the
    descriptor with pre-`_hass` writes on every `discover_fans()`. The
    explicit `__init__` below orders `_hass` first, then seeds locals
    directly via `object.__setattr__` (bypassing descriptors), leaving
    subsequent runtime writes to flow through the descriptor.
    """

    def __init__(
        self,
        room_name: str,
        zone_id: str,
        *,
        hass: "HomeAssistant | None" = None,
        room_type: str = ROOM_TYPE_GENERIC,
        fan_entities: list[str] | None = None,
    ) -> None:
        # ORDERING: _hass FIRST so any subsequent descriptor __set__
        # (if a caller assigns immediately after construction) can
        # resolve the oracle.
        object.__setattr__(self, "_hass", hass)
        self.room_name = room_name
        self.zone_id = zone_id
        self.room_type = room_type
        self.fan_entities = list(fan_entities or [])
        self.is_on = False
        self.speed_pct = 0
        self.trigger = ""
        self.last_on_time = ""
        self.vacancy_detected_time = ""
        # Bypass descriptor for initial-state seed — the field
        # defaults are "" and we do NOT want to fire an oracle setter
        # writing "" to a room the oracle has never seen (that would
        # PERSIST an empty-string interpretation and defeat hydrate-
        # on-read). object.__setattr__ writes the local slot only.
        object.__setattr__(self, "_manual_off_local", "")
        object.__setattr__(self, "_manual_on_local", "")
        self.manual_on_hold_paused_at = ""
        self.fan_recheck_suppress_until = ""
        self.fan_sleep_policy = DEFAULT_FAN_SLEEP_POLICY

# Descriptors applied AFTER class definition so they attach to the
# class dict, not intercept __init__ writes to un-related fields.
RoomFanState.manual_off_cooldown_until = _OracleISOField(
    "manual_off_cooldown_until", "set_manual_off_cooldown", "_manual_off_local",
)
RoomFanState.manual_on_hold_until = _OracleISOField(
    "manual_on_hold_until", "set_manual_on_hold", "_manual_on_local",
)
```

`discover_fans()` (`hvac_fans.py:151-202`) is amended to pass `hass=self.hass` on every `RoomFanState(...)` construction. Fixture constructions in tests do the same (add `hass=mock_hass` to every direct constructor).

**Descriptor (module-level in `hvac_fans.py`):**

```python
class _OracleISOField:
    """Read-through view of oracle.get_state(_room_key(room_name)).<field>
    as an ISO string, with hydrate-on-read + fail-safe fallback to a local
    slot. Mirrors the RoomAutomation @property pattern at automation.py:
    283-329 (Session 2). Writes fan to (a) local slot ALWAYS, (b) oracle
    via UNLOCKED sync setter — the WRITER, if it needs locked semantics,
    must call `oracle.set_manual_*_locked(...)` directly (§5.4).
    """
    def __init__(self, oracle_field: str, setter_name: str, local_key: str):
        self._oracle_field = oracle_field
        self._setter_name = setter_name
        self._local_key = local_key

    def __get__(self, obj, objtype=None) -> str:
        if obj is None:
            return self
        local = object.__getattribute__(obj, self._local_key)
        oracle = _get_fan_oracle(getattr(obj, "_hass", None))
        if oracle is None:
            if local:
                _log_hvac_fallback_warn("read", obj.room_name)
            return local
        try:
            key = _room_key(obj.room_name)
            dt_val = getattr(oracle.get_state(key), self._oracle_field)
            if dt_val is None:
                if local:
                    # Hydrate-on-read (B-HIGH-1 sister case).
                    parsed = dt_util.parse_datetime(local)
                    if parsed is not None:
                        getattr(oracle, self._setter_name)(key, parsed)
                    return local
                return ""
            return dt_val.isoformat()
        except Exception:  # noqa: BLE001
            if local:
                _log_hvac_fallback_warn("read_exc", obj.room_name)
            return local

    def __set__(self, obj, value: str) -> None:
        object.__setattr__(obj, self._local_key, value)
        oracle = _get_fan_oracle(getattr(obj, "_hass", None))
        if oracle is None:
            if value:
                _log_hvac_fallback_warn("write", obj.room_name)
            return
        try:
            key = _room_key(obj.room_name)
            if not value:
                getattr(oracle, self._setter_name)(key, None)
            else:
                parsed = dt_util.parse_datetime(value)
                getattr(oracle, self._setter_name)(key, parsed)
        except Exception:  # noqa: BLE001
            if value:
                _log_hvac_fallback_warn("write_exc", obj.room_name)


def _room_key(room_name: str) -> str:
    """Shared prefixed key for oracle ledger access (§5.2)."""
    return f"room:{room_name}"
```

**Round-trip guarantee:** `RoomFanState.f = dt.isoformat()` → local stored, `dt_util.parse_datetime` → `dt2`, `oracle.set(dt2)`. Read: `oracle.get()` returns `dt2`, descriptor returns `dt2.isoformat()`. `dt_util.parse_datetime` accepts what `datetime.isoformat()` emits (verified in oracle's existing use at `automation.py`). Test `test_hvac_iso_datetime_round_trip_preserves_value` asserts equality at microsecond resolution.

### 5.2 Key-space unification — **Option A (keep prefixes; room-name-first)** with uniqueness gate (HIGH-1)

**Chosen: Option A.** The plan-review record correctly flagged that (a) `_fan_ledger_key()` today returns PREFIXED keys (`entry:{eid}` | `room:{name}` | `__unkeyed__`) and my rev-1 spec would orphan pre-deploy ledger rows and re-open the A-HIGH-1 collision. Option A keeps the prefix scheme, unifies both tiers on `room:{CONF_ROOM_NAME}`, and relies on the RAM-only nature of the ledger (§2.3) to make migration trivial.

**Both tiers derive the SAME name string for the same physical room — evidence:**

- Room-tier reads `CONF_ROOM_NAME` at `automation.py:263` (`name = self.config.get(CONF_ROOM_NAME, "")`) via `self.config` which is the config-entry data/options merge.
- HVAC-tier reads `CONF_ROOM_NAME` at `hvac_fans.py:170` (`room_name = entry.data.get(CONF_ROOM_NAME, "")`) inside `discover_fans()`, and `discover_fans()` at line 171 **SKIPS** any entry with `not room_name` (`if not room_name or room_name not in room_to_zone: continue`). So HVAC-tier never sees an empty CONF_ROOM_NAME.
- Both reads target the SAME config-entry field. Same string → same key.
- W8 (`hvac.py:2715`) iterates `zone.rooms` (zone-name strings originating from HVAC discovery, sharing the same CONF_ROOM_NAME source) and calls `_get_room_coordinator(room_name)` at `:2716` which at `:2803-2807` does `entry.data.get(CONF_ROOM_NAME) == room_name` — proving W8's `room_name` is the same string as `CONF_ROOM_NAME`.
- Presence-fan-recheck's `room_name` argument to `_fan_in_manual_cooldown` originates from the room coordinator; same source.

**Room-tier amendment to `_fan_ledger_key()`** (`automation.py:250-268`):

```python
def _fan_ledger_key(self) -> str:
    """Return the stable room key for oracle ledger access.

    FAN-LAYER-2 §5.2: prefer `room:{CONF_ROOM_NAME}` so the HVAC-tier
    (`hvac_fans.py`) — which keys by CONF_ROOM_NAME via
    `_room_key(room_fan.room_name)` — sees the same ledger row for the
    same physical room. Fall back to `entry:{eid}` only when
    CONF_ROOM_NAME is empty (A-HIGH-1 defense: nameless rooms must not
    collide on ""). Fall back to `__unkeyed__` only when neither is
    available (fixture / early-boot).
    """
    try:
        name = self.config.get(CONF_ROOM_NAME, "")
    except Exception:  # noqa: BLE001
        name = ""
    if name:
        return f"room:{name}"
    entry = getattr(self, "_config_entry", None)
    if entry is not None:
        eid = getattr(entry, "entry_id", None)
        if eid:
            return f"entry:{eid}"
    return "__unkeyed__"
```

**Uniqueness gate (BUILD-TIME).** The A-HIGH-1 collision defense assumed the room-tier could use `entry_id` as an always-unique key. Once we prefer `room:{name}`, two rooms with the same CONF_ROOM_NAME collapse to one ledger row. The build-time gate reads `.storage/core.config_entries` via the Samba mount for `domain == universal_room_automation` + `entry_type == ENTRY_TYPE_ROOM` and asserts CONF_ROOM_NAME is **unique** (and non-empty) across all such entries. A violation BLOCKS build dispatch (this is stricter than rev-1's "surface as finding" — a duplicate breaks INV-DTA silently).

**Migration is trivial because the ledger is RAM-only.** Explicit note: the oracle ledger (`FanPolicyOracle._rooms`) is a dict populated at runtime from adopt-external observations and URA-issued actuations. On the deploy that ships §5.2:

- **If HA restarts** (typical `deploy.sh` path): the oracle is freshly constructed empty; the first adopt-external tick and first URA action re-populate rows under the new `room:{name}` keys. Zero migration code needed.
- **If ONLY the config-entry reloads** (options-flow reload, no HA restart): the CM reload preserves the singleton oracle (B-HIGH-2 discipline). Old rows under `entry:{eid}` remain but are simply unreachable — no reader queries them anymore (both tiers now use `room:{name}`). The hydrate-on-read path at the descriptor seeds a fresh `room:{name}` row from the local slot on first read; the room-tier @property does the same from its `__dict__` slot. Old `entry:{eid}` rows are harmless leaked-until-restart RAM (~1 KB × 40 rooms; negligible). A cleanup pass in `FanPolicyOracle.__init__` OR a one-shot boot task can drop keys matching `entry:.*` if we want the hygiene — cheap and optional; recommend include as a 5-line addition in `fan_policy_oracle.py::_migrate_legacy_entry_keys()` called once from `CoordinatorManager` after oracle attach.

**Consumers to update (grep-audit):** every callsite that today computes an oracle key. Enumerated:
- `automation.py:_fan_ledger_key` (amended above).
- `hvac_fans.py` descriptor + wrap sites use `_room_key(room_name)` — module helper defined in §5.1.
- `hvac.py:_execute_vacancy_sweep` (W8) at the wrap site — imports `_room_key` from `..domain_coordinators.hvac_fans` or the wrap uses the `_build_fan_snapshot_hvac(room_name, ...)` return that also exposes the key.
- `hvac.py:_deactivate_prearrival_fans` (W9) — same.
- `presence_fan_recheck.py:_fan_in_manual_cooldown` (D3) — `oracle.get_state(_room_key(room_name))`.

**Test:** `test_dual_tier_agreement_room_key_room_name` — populate the oracle from the room-tier side (via `_fan_manual_on_until` setter on a `RoomAutomation` whose `CONF_ROOM_NAME="Living Room"`); read from the HVAC-tier `RoomFanState` descriptor for the SAME room; assert the ISO strings equal.

### 5.3 Six wraps — W8/W9 do NOT route through `_set_fan_state` (MED-2, evidence)

`git grep -n 'services.async_call' custom_components/universal_room_automation/domain_coordinators/hvac.py` returns 8 hits; the two that iterate `CONF_FANS` are at `hvac.py:2786` (inside `_execute_vacancy_sweep`) and `hvac.py:3021` (inside `_deactivate_prearrival_fans`). Both are DIRECT `hass.services.async_call(...)` calls — grep of the enclosing functions for `_set_fan_state` returns zero hits. **W8 and W9 do NOT route through the chokepoint.** Therefore:

- **W8, W9 wraps are INDEPENDENT** — each wraps its own `services.async_call` block in `oracle.actuate`.
- **No nested-actuate risk.** `_set_fan_state` (which W4 wraps) is called from `turn_off_all_managed:212`, `pause_for_recheck:1451`, `restore_after_recheck:~1512`, and the sleep-onset activate at `_maybe_sleep_onset_activate:700` — none of these callers wrap their own `oracle.actuate`. So `_set_fan_state`'s wrap is entered from an unwrapped caller and the per-room lock is acquired exactly once per call stack. **asyncio.Lock non-reentrancy is not a deadlock hazard under this layout.**

Reviewer C mutation drill for this specific hazard: at W8 and W9, temporarily add an outer `async with oracle.actuate(...)` that itself calls `_set_fan_state(...)` in its body; run `test_w8_zone_vacancy_sweep_wrapped` and confirm the test times out (deadlock detected). Restore. This proves the plan's "no nesting" claim is enforced by tests, not just by code review.

**W1, W2, W3 wraps** at `automation.py:2159/2072/2234/2898` are INDEPENDENT of each other and of `_set_fan_state` (they call `_safe_service_call`, not the HVAC chokepoint).

**W10-pause / W10-restore** DO call `_set_fan_state` (at `:1451` and the restore branch). They route through the chokepoint wrap by passing `trigger_path=FAN_TRIGGER_RECHECK_PAUSE` / `FAN_TRIGGER_RECHECK_RESTORE` and `room_name=<name>` (see W10 rows in §2.2 table).

### 5.4 Lock scope — per-room; **all 15 hvac_fans writes classified** (HIGH-2)

Per v2 §7.9 the lock is per-room, owned by the oracle (`_room_locks: dict[str, asyncio.Lock]`, lazily created at `fan_policy_oracle.py:269-274`). The `actuate` async-context acquires the lock on entry, holds across the caller's body, releases on exit after `note_actuation`.

**New oracle async-locked setters** (added to `fan_policy_oracle.py`, ~30 LoC):

```python
async def set_manual_on_hold_locked(self, room_key: str, value) -> None:
    async with self._get_lock(room_key):
        self.set_manual_on_hold(room_key, value)  # calls existing sync body

async def set_manual_off_cooldown_locked(self, room_key: str, value) -> None:
    async with self._get_lock(room_key):
        self.set_manual_off_cooldown(room_key, value)

async def clear_manual_on_hold_locked(self, room_key: str) -> None:
    async with self._get_lock(room_key):
        self.clear_manual_on_hold(room_key)
```

**Sync-context concern (reviewer flagged: a sync setter cannot await asyncio.Lock).** All 15 hvac_fans write sites fire from paths ultimately entered via `async def` methods on `FanController`:
- `turn_off_all_managed` — `async def` (`:204`).
- `update` — `async def` (`:228`).
- `_evaluate_temp_fan` — SYNC, but called from `update` (async).
- `_maybe_sleep_onset_activate` — `async def` (called from `update`).
- `_is_manual_on_hold_live` — SYNC helper called from both `_evaluate_temp_fan` (sync) and `is_room_in_manual_on_hold` (sync, called from `_execute_vacancy_sweep` which is `async def`).
- `restore_after_recheck` — `async def` (`:1458`).
- `pause_for_recheck` — `async def` (`:1422`).

The **decision table below** classifies each write. Sync-context writes are rewritten as follows: the current `room_fan.field = ""` (which invokes the sync descriptor) is REPLACED by a call to `_schedule_locked_clear(room_fan, field)` where feasible, OR downgraded to `local_only_ok` when the write is idempotent/self-healing under race (malformed-cleanup and stale-expiry paths are self-healing — the next adopt-external tick corrects).

**All 15 write sites — classified with rationale:**

| # | Site | Enclosing method (sync/async) | What it writes | Classification | Rationale | Rewrite |
|---|---|---|---|---|---|---|
| 1 | `:221` | `turn_off_all_managed` (async) | cooldown ← `""` (kill switch clean-reset) | **locked_setter_required** | Race: mid-URA-OFF at the SAME room; kill switch clearing cooldown post-consult would let a subsequent URA turn-ON emit against a room whose operator just killed everything. | `await oracle.clear_manual_off_cooldown_locked(_room_key(room_name))` (add symmetric clear helper) |
| 2 | `:225` | same (async) | hold ← `""` (kill switch) | **locked_setter_required** | Same as #1; kill switch clearing hold must serialize with any URA-OFF-in-flight. | `await oracle.clear_manual_on_hold_locked(_room_key(room_name))` |
| 3 | `:308` | `update` external-OFF adopt (async) | cooldown ← now+DEFAULT (external OFF adopt) | **locked_setter_required** | THIS IS THE CANONICAL INV-FLA-T RACE SITE (repro in §1). External-OFF observation must serialize with any URA turn-ON preparing to emit. | `await oracle.set_manual_off_cooldown_locked(_room_key(room_name), parsed_dt)` |
| 4 | `:312` | same (async) | hold ← `""` (external OFF clears any live hold) | **locked_setter_required** | Same race as #3 in the direction "external human OFF discharges the ON hold"; must serialize with URA turn-ON. | `await oracle.clear_manual_on_hold_locked(_room_key(room_name))` |
| 5 | `:325` | `update` external-reversal branch (async) | cooldown ← `""` (external ON while cooldown live → reversal) | **locked_setter_required** | Sibling of #3; freshest-human-wins requires the clear serialize with URA-ON that might race. | `await oracle.set_manual_off_cooldown_locked(_room_key(room_name), None)` |
| 6 | `:335` | same (async) | hold ← now+ROOMHOLD (external-on-during-cooldown → open ON hold) | **locked_setter_required** | INV-FLA-T CANONICAL: this is the write that opens the hold mid-URA-OFF (§1 repro). MUST lock. | `await oracle.set_manual_on_hold_locked(_room_key(room_name), parsed_dt)` |
| 7 | `:339` | same (async) | hold ← `""` (kill-switch semantics: hold_s == 0) | **locked_setter_required** | Sibling of #6; the "no-hold" branch of the same external observation must be seen serialized. | `await oracle.set_manual_on_hold_locked(_room_key(room_name), None)` |
| 8 | `:411` | `update` adopt-fan branch (async) | hold ← now+ROOMHOLD (adopt externally-lit fan) | **locked_setter_required** | Adopt-external ON path (BUG 2 fix branch); same INV-FLA-T race as #6 on a different code branch. MUST lock. | same shape as #6 |
| 9 | `:415` | same (async) | hold ← `""` (adopt with hold_s == 0) | **locked_setter_required** | Sibling of #8. | same shape as #7 |
| 10 | `:651` | `_maybe_sleep_onset_activate` (async — the wrapping method is async even though `_evaluate_temp_fan` is not; the call chain here is async) | cooldown ← `""` (parse-error cleanup on malformed ISO) | **local_only_ok** | Self-healing: clears a value that we've already established is unparseable (i.e. useless). If adopt races us with a fresh cooldown, our clear is against the STALE value; the race is benign (fresh write via lock arrives after; oracle ends up with fresh value). **BUT:** because this write happens through the descriptor, it does write `""` to oracle unlocked. Downgrade rationale: the unlocked "" write races with a potential fresh locked write from #3; ordering is Best-Effort — worst case the fresh write is lost within one tick. Acceptable because the adopt-external re-fires on every tick until the state stabilizes. Test `test_malformed_cooldown_cleanup_is_race_benign` verifies. | Keep descriptor write; add comment referencing this classification |
| 11 | `:847` | `_evaluate_temp_fan` (SYNC, called from `update` async) | cooldown ← `""` (parse-error cleanup, sync) | **local_only_ok** | Sync context — cannot await. Same rationale as #10. | Keep descriptor write |
| 12 | `:849` | same (SYNC) | cooldown ← `""` (except branch — malformed cleanup) | **local_only_ok** | Same as #11. | Keep descriptor write |
| 13 | `:1081` | `_is_manual_on_hold_live` (SYNC helper, called from both sync `_evaluate_temp_fan` and async `is_room_in_manual_on_hold` consumers) | hold ← `""`, paused_at ← `""` (malformed ISO cleanup) | **local_only_ok** | Sync context (the helper is sync and consumers include sync paths). Malformed-cleanup is idempotent. | Keep descriptor writes |
| 14 | `:1089` | same (SYNC) | hold ← `""`, paused_at ← `""` (natural expiry clear when `now >= until` AND not paused) | **local_only_ok WITH CAVEAT** | Expiry clear COULD race with a fresh external-ON that opened a new hold between our read at `:1076` and the clear at `:1089`. If a fresh locked write from #6 lands between our sync read and sync write, we clobber it — this IS an INV-FLA-T violation shape. **Mitigation:** the clear happens INSIDE `_is_manual_on_hold_live` which returns False; consumers (e.g. W8 sweep) then proceed to emit an OFF. The OFF emission is itself wrapped in `oracle.actuate` (INDEPENDENT wrap per §5.3) whose consult READS the fresh hold and DEFERs. So the clobber is masked at the emit gate. **BUT** the ledger row is still corrupt (hold cleared post-write). To close this: refactor `_is_manual_on_hold_live` to READ ONLY (never clear inline); move the expiry clear into a periodic async `async_cleanup_expired_holds()` task that grabs the lock per room. **Recommend:** implement the refactor — the write disappears from this site entirely, converting it from `local_only_ok WITH CAVEAT` to `deleted`. | REFACTOR: remove inline clear; add `async def async_cleanup_expired_holds(self)` scheduled from `FanController.update` under the per-room lock. |
| 15 | `:1477` | `restore_after_recheck` (ASYNC) | hold ← extended_iso (pause-context R-M-W extension) | **locked_setter_required + R-M-W atomic guard (MED-3)** | Read-modify-write: reads `manual_on_hold_paused_at` at :1471, `manual_on_hold_until` at :1474, computes extension at :1476, writes at :1477. Race: an adopt-external write from #6 landing mid-computation clobbers our extension OR is clobbered by it. Both are INV-FLA-T violations. See §5.4a. | Wrap the entire R-M-W in `async with oracle._get_lock(_room_key(room_name)):` then read via `oracle.get_state(...)` then write via `oracle.set_manual_on_hold_locked(...)` (inner call is a no-op re-acquire on already-held lock? — see §5.4a implementation note). |

**Summary counts:** locked_setter_required = 9 (#1, #2, #3, #4, #5, #6, #7, #8, #9); local_only_ok = 4 (#10, #11, #12, #13); local_only_ok with refactor-to-delete = 1 (#14); locked R-M-W atomic-guard = 1 (#15). Total = 15 = all writes accounted.

**Concrete mechanism for sync-context sites (#10-#14):** they write to the local slot via `object.__setattr__` inside the descriptor and ALSO call `oracle.set_manual_*(...)` (sync, unlocked). The unlocked write can race with a locked write; the classification above documents why each is race-benign under the specific write pattern. NO sync site attempts to await asyncio.Lock — descriptor `__set__` remains sync.

**Test coverage:**
- `test_external_on_racing_ura_off_is_blocked_hvac_tier` — canonical INV-FLA-T repro at write site #6.
- `test_kill_switch_races_ura_off_serializes` — mutation drill at #1/#2.
- `test_expiry_clear_refactored_out_of_hot_path` — verifies `_is_manual_on_hold_live` never mutates.
- `test_pause_extension_atomic_vs_adopt_external` — MED-3 repro at #15.

### 5.4a Pause-context atomicity at :1477 (MED-3)

`restore_after_recheck` at `hvac_fans.py:1469-1487` does:

```
if room_fan.manual_on_hold_paused_at and room_fan.manual_on_hold_until:
    paused_at = fromisoformat(room_fan.manual_on_hold_paused_at)  # :1471
    until = fromisoformat(room_fan.manual_on_hold_until)           # :1474
    elapsed = dt_util.now() - paused_at
    if elapsed.total_seconds() > 0:
        room_fan.manual_on_hold_until = (until + elapsed).isoformat()  # :1477
```

Under the RAW descriptor pattern (post-D1) this is unsafe: an adopt-external write from `update()` running concurrently on the same event loop could interleave via `await` points (`fromisoformat` doesn't await, but nothing prevents another coroutine from being scheduled between the read at :1474 and the write at :1477 if a `dt_util.now()` implementation ever became async — belt-and-suspenders).

**Fix — wrap the R-M-W in the per-room lock:**

```python
async with oracle._get_lock(_room_key(room_name)):
    ledger = oracle.get_state(_room_key(room_name))
    if ledger.manual_on_hold_until is None:
        room_fan.manual_on_hold_paused_at = ""
        return
    if room_fan.manual_on_hold_paused_at:
        paused_at = dt_util.parse_datetime(room_fan.manual_on_hold_paused_at)
        if paused_at is not None:
            elapsed = dt_util.now() - paused_at
            if elapsed.total_seconds() > 0:
                new_until = ledger.manual_on_hold_until + elapsed
                # Direct sync setter under the lock we already hold —
                # calling set_manual_on_hold_locked here would re-acquire,
                # which asyncio.Lock does NOT support.
                oracle.set_manual_on_hold(_room_key(room_name), new_until)
                _LOGGER.info(...)  # existing log line
    room_fan.manual_on_hold_paused_at = ""
```

**Implementation note (asyncio.Lock non-reentrancy):** the `_locked` async setters use `async with self._get_lock(room_key)`; calling them from inside an already-acquired lock context DEADLOCKS. The pattern above calls the SYNC setter (`set_manual_on_hold`) directly while holding the lock we manually acquired. Reviewer B verifies at build that no `_locked` async setter is ever called from inside another `_locked` scope or from inside `oracle.actuate(...)` (which also acquires the same lock).

Test: `test_pause_extension_atomic_vs_adopt_external` — fixture spawns two coroutines: `restore_after_recheck` running the R-M-W, and an `update()` external-ON adopt attempting to write `manual_on_hold_until` mid-computation. Assert final ledger value equals the R-M-W's computed extension (not the adopt's fresh hold) OR the adopt's fresh hold (not a torn intermediate); the invariant is "no interleaving artifact — one write wins cleanly".

### 5.5 Reverse-adjacency scanner (task item 4) — AST rules + synthetic-violation fixture (MED-4)

Extends `quality/tools/audit_fan_adjacency.py` with a second AST pass.

**Detection rules (documented in the scanner header):**

1. **Direct rule.** Any `services.async_call("fan", ...)` OR `services.async_call("switch", ...)` OR `services.async_call("homeassistant", "turn_on"/"turn_off", ...)` is a candidate emit. If the call is inside a function whose body contains a `for <var> in <expr>:` where `<expr>` resolves (by name-lookup within the function or its enclosing class) to `CONF_FANS`, `fan_entities`, `room_fan.fan_entities`, or a param annotated / named `fans`/`entities`/`fan_entities`, the emit is a fan emit.
2. **`startswith("fan.")` branch rule.** If the enclosing conditional is `if entity_id.startswith("fan.")` OR `if <var>.startswith("fan.")` where `<var>` is the loop variable of a rule-1 loop, the emit is a fan emit.
3. **Parameter-taint rule (partial — proves the shape MED-4 asks about).** For known chokepoint methods (`_set_fan_state`), the `entities: list[str]` parameter is TAINTED as fan-list. `services.async_call` inside such a method body operating on the tainted param is a fan emit. The known-chokepoint list is HARD-CODED in the scanner (a small allowlist: `_set_fan_state`); adding a new chokepoint means editing the scanner allowlist. Documented as a limitation.
4. **Enclosing-context rule.** A candidate emit passes iff it is inside an `async with oracle.actuate(...)` body (walk `ast` parent chain up to enclosing FunctionDef; find `AsyncWith` whose `items[i].context_expr` is a `Call` to `.actuate`). Otherwise flag.
5. **Carve-out comment.** A file-level `# fan-adjacency: allow (reason=<explanation>)` immediately above the `services.async_call` line suppresses the finding for that line only. Reason string is grep-audited against the v2 §1 carve-out list.

**MED-4 mandate — synthetic-violation fixture.** Because rules 1-3 have inter-procedural gaps (a future writer that shovels entities through 3 helper hops or types them as `Iterable[Any]` might evade), the scanner ships with a fixture that PROVES the walker catches the exact `_set_fan_state`-taint + `startswith("fan.")` shape:

```
quality/tests/fixtures/fan_adjacency_synthetic/
    violation_direct_fan_domain.py       # rule 1
    violation_startswith_fan_branch.py   # rule 2
    violation_set_fan_state_taint.py     # rule 3
    violation_carveout_missing_reason.py # rule 5
    allow_carveout_valid.py              # rule 5 positive
```

Each fixture file contains a MINIMAL synthetic function that emits fan without a wrap; the scanner MUST flag it. Test `test_fan_adjacency_reverse_scan_flags_synthetic_violations` iterates each fixture and asserts a finding at the expected line. If the scanner regresses on any rule, the corresponding fixture fails — the fixture IS the rule's authority.

### 5.6 note_actuation dedup + same-trigger re-fire (LOW-1)

Dedup key (verified at `fan_policy_oracle.py:547`): `edge_key = (trigger_path, rec.hold_id)`. `hold_id` monotonically bumps in `_note_actuation_inner` at `:541` **only on external ON** (`if source == "external": rec.hold_id += 1`). Behavior:

- URA-side turn-ON via `note_actuation(direction="on", source="ura")` does NOT bump hold_id; verdict flip within the SAME hold cycle collapses to one edge row.
- External ON adopt → hold_id bumps → next same-trigger consult writes a fresh edge row because `edge_key` is new.
- Same-trigger re-fire across ticks WITHIN one hold cycle → edge_key unchanged; verdict unchanged → `prev_kind == current_kind` → NO row written (edges-only).
- Same-trigger re-fire with verdict FLIP (ALLOW→DEFER or DEFER→ALLOW) within one hold cycle → row written each flip. This is correct: an operator watching the activity log sees each transition of decision authority within a single hold.

Regression test: `test_note_actuation_dedup_across_ticks_same_hold_cycle` — 100 same-trigger consults with unchanged verdict → 1 row. `test_note_actuation_writes_on_verdict_flip` — 3 consults ALLOW/DEFER/ALLOW → 3 rows. `test_note_actuation_writes_fresh_row_after_hold_bump` — one row, external-ON (bumps hold_id), one row → 3 rows total (edge, bump, edge on new key).

### 5.7 Snapshot builders

`_build_fan_snapshot_room(self, entities, observed_any_on)` on `RoomAutomation`:

```python
def _build_fan_snapshot_room(
    self, entities: list[str], observed_any_on: bool,
) -> FanDecisionSnapshot:
    return FanDecisionSnapshot(
        now=dt_util.now(),
        sleep_state="asleep" if self.is_sleep_mode_active() else "awake",
        sleep_axis="room_window",
        house_state=self._house_state_manager.current_state
                    if getattr(self, "_house_state_manager", None) else "unknown",
        is_hvac_managing=bool(self._is_hvac_managing_fans()),
        entities=tuple(entities),
        observed_any_on=bool(observed_any_on),
    )
```

`_build_fan_snapshot_hvac(self, room_name, entities, observed_any_on)` on `FanController`:

```python
def _build_fan_snapshot_hvac(
    self, room_name: str, entities: list[str], observed_any_on: bool,
) -> FanDecisionSnapshot:
    return FanDecisionSnapshot(
        now=dt_util.now(),
        sleep_state="asleep" if self._house_state == "sleep" else "awake",
        sleep_axis="house_state",
        house_state=self._house_state or "unknown",
        is_hvac_managing=True,   # by definition — we ARE the HVAC tier
        entities=tuple(entities),
        observed_any_on=bool(observed_any_on),
    )
```

W8/W9 (in `hvac.py`) obtain the snapshot via `self._fan_controller._build_fan_snapshot_hvac(room_name, fans, observed_any_on)` where `observed_any_on = any(state.state == "on" for state in <existing state reads>)` — the same reads today's code performs pre-emit.

---

## 6. Numbers get knobs

No new numbers. All existing tunables preserved at their current rungs.

---

## 7. Scope pushback — marginal-benefit decomposition (unchanged from rev-1, still valid post-revisions)

| Item | Simplest version | Marginal cost of "full" | Recommendation |
|---|---|---|---|
| 1. HVAC-tier delegation | descriptor + hydrate-on-read | Full: ~150 LoC + 4 tests | LAND (§5.1) |
| 2. Presence-fan-recheck reader migration | 5-line replacement | Trivial | LAND with D3 |
| 3. `oracle.actuate` wraps on W1-W3, W4-chokepoint, W8, W9 | 6-7 wraps + 2 snapshot helpers | Full: ~200 LoC + 8 tests | LAND all |
| 4. Reverse adjacency scan | AST walker + synthetic fixture | Full: ~120 LoC + 5-fixture tests | LAND (MED-4 requires) |
| 5. Locked setter fleet (§5.4) | 9 async-locked writes + 1 R-M-W refactor + 1 clear-expiry refactor | ~60 LoC + 4 race tests | LAND (HIGH-2 requires — closes INV-FLA-T for the adopt-side; partial landing leaves invariant half-proven) |
| 6. RoomFanState @dataclass → plain class | Explicit __init__ with ordered `_hass` init | ~50 LoC | LAND (MED-1 requires — dataclass sugar causes descriptor-flood at construction) |

**No item is a candidate for parking.**

---

## 8. Estimated cycle size + overrun trigger (LOW-3)

- **Diff:** ~700 LoC net additions, ~200 LoC net deletions.
  - `hvac_fans.py`: ~350 add / ~80 del (drop @dataclass + plain-class __init__ + descriptor + `_room_key` + `_build_fan_snapshot_hvac` + refactored `_is_manual_on_hold_live` + 9 write-site rewrites to `_locked` setters + §5.4a R-M-W lock wrap + W4 chokepoint wrap).
  - `automation.py`: ~130 add / ~50 del (amended `_fan_ledger_key` + `_build_fan_snapshot_room` + 4 wraps at W1/W2/W3-temp/W3-onset — `mark_fan_on_issued` kept idempotent).
  - `hvac.py`: ~90 add / ~15 del (W8 + W9 independent wraps + snapshot fetch).
  - `presence_fan_recheck.py`: ~20 add / ~30 del (reader migration).
  - `fan_policy_oracle.py`: ~50 add (3 async-locked setters + optional `_migrate_legacy_entry_keys` cleanup + `async_cleanup_expired_holds` helper).
  - `quality/tools/audit_fan_adjacency.py`: ~120 add (reverse pass + carve-out comment parsing).
  - `quality/tests/fixtures/fan_adjacency_synthetic/`: ~50 add (5 fixture files).
- **Tests:** ~22 new tests: round-trip, dual-tier agreement, hydrate-on-read, fallback-warn, 8 wrap tests (W1, W2, W3-temp, W3-onset, W4, W8, W9, W10-pause-through-chokepoint, W10-restore-through-chokepoint), external-ON-race INV-FLA-T at write #6, kill-switch-race at #1/#2, expiry-clear-refactored, pause-extension atomic (MED-3), recheck reader migration, recheck-key-matches-room-name, 4 reverse-scanner tests (clean, flags-deleted-wrap, flags-synthetic-violations, respects-carveout), note_actuation dedup regression, note_actuation write-volume < 200 rows/hour with 8 wraps.
- **Sessions:** ONE staged session preferred (~700 LoC is under 800 threshold). Two commits on one branch recommended for reviewer checkpointing: (a) D1 (dataclass drop + descriptor + `_fan_ledger_key` amendment + `_room_key` helper + reader migration + hydrate-on-read tests + §5.4 locked setter fleet + expiry-clear refactor); (b) D2 (six wraps + snapshot helpers + §5.4a R-M-W wrap + reverse-scanner + synthetic fixtures + write-volume test).
- **Reviewers:** 3 (Tier 2-DB parallel A/B/C per §4).
- **Underrun trigger:** below ~550 LoC OR below ~18 tests → audit for silently-dropped scope BEFORE dispatching reviewers.
- **OVERRUN trigger (LOW-3):** above **~900 LoC OR above ~28 tests** → SPLIT into D2a (D1 + descriptor + locked setters + expiry-clear refactor + presence reader migration) landing as commit A on the branch, and D2b (six wraps + snapshot helpers + R-M-W wrap + reverse-scanner + fixtures) landing as commit B on the branch. Both still merge as ONE PR (per v2 §10 preamble discipline: partial merge trivially violates INV-FLA-T). Rationale: an overrun on this surface signals either (a) an unmeasured write site or (b) a wrap that spawned auxiliary code — either way the reviewer needs a smaller diff-per-commit to keep the mutation drill tractable.

---

## 9. Parity gates (must stay green, unmodified)

FAN-LAYER-1 behavioral tests + v5.68.0 guard anchors are the parity contract. MUST NOT be modified; must pass byte-identical:

- `quality/tests/test_fan_manual_on_hold_room_tier.py` (all tests).
- Session-2 `test_set_fan_manual_off_until_writes_to_oracle` + sibling `_on_hold_` test.
- Session-2 `test_mark_fan_on_issued_records_oracle_edge`.
- Session-3 `test_safety_stop_consults_oracle_with_safety_true`, `test_prearrival_on_defers_under_manual_off_cooldown`.
- v5.68.0 vacancy-sweep parity anchor.
- FAN-LAYER-1 D6 tests `test_hvac_zone_vacancy_sweep_respects_manual_on_hold`, `test_hvac_prearrival_respects_manual_off_cooldown`.
- Existing forward-adjacency test `test_fan_adjacency_walker_clean`.
- All HVAC restore/pause tests exercising `manual_on_hold_paused_at` — paused-at field NOT delegated; pause-context arithmetic byte-frozen (only the atomicity guard added).

If any of these tests need to change, STOP.

---

## 10. Deliverables

### D1 — Structural + delegation groundwork (@plain-class + descriptor + `_room_key` + `_fan_ledger_key` amendment + `_locked` setter fleet + `_is_manual_on_hold_live` refactor + presence reader migration)

**Files:** `hvac_fans.py` (~350 add / ~80 del), `automation.py` (~20 add / ~5 del for `_fan_ledger_key`), `fan_policy_oracle.py` (~50 add for locked setters + optional cleanup helpers), `presence_fan_recheck.py` (~20 add / ~30 del for reader migration).

- **Verify:** `git grep -n 'room_fan\.manual_off_cooldown_until\|room_fan\.manual_on_hold_until' custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` still returns the SAME set of 46 lines (callsites unchanged in shape); fields are backed by descriptors, not by inline dataclass slots.
- **Verify:** `@dataclass` decorator is REMOVED from `RoomFanState`; class body has an explicit `__init__` that sets `_hass` FIRST and uses `object.__setattr__` for the two `_manual_*_local` slots.
- **Verify:** `_fan_ledger_key()` returns `room:{name} if name else entry:{eid} if eid else "__unkeyed__"` (order swapped vs. current).
- **Verify (build-time live check — MANDATORY BLOCKER):** every ENTRY_TYPE_ROOM entry in `.storage/core.config_entries` has (a) non-empty `CONF_ROOM_NAME` AND (b) unique `CONF_ROOM_NAME` (no duplicates across entries). BLOCK build dispatch on any violation.
- **Verify:** `git grep -n 'oracle\.set_manual_.*_locked\|oracle\.clear_manual_.*_locked' custom_components/universal_room_automation/` returns exactly the 9 sites classified `locked_setter_required` in §5.4 (plus the §5.4a R-M-W site which uses the manual `async with oracle._get_lock(...)` pattern).
- **Verify:** `_is_manual_on_hold_live` at `hvac_fans.py:1060-1092` no longer mutates `room_fan.manual_on_hold_until` or `manual_on_hold_paused_at`; expiry clearing is moved to the new async `async_cleanup_expired_holds` helper scheduled from `FanController.update`.
- **Verify:** presence reader `_fan_in_manual_cooldown` no longer reaches through `hass.data → coordinator_manager → hvac.fan_controller._room_fans`; uses `_get_fan_oracle(self.hass).get_state(_room_key(room_name)).manual_off_cooldown_until`.
- **Test:** `test_hvac_iso_datetime_round_trip_preserves_value` — write ISO, read ISO, parse both, equal to microsecond.
- **Test:** `test_room_fan_state_construction_does_not_fire_descriptor` — instantiate 40 RoomFanStates; assert `_fallback_warn` was called ZERO times (no pre-`_hass` descriptor writes).
- **Test:** `test_hvac_tier_delegation_reads_oracle` — mock oracle returns a datetime; descriptor returns matching ISO string.
- **Test:** `test_hvac_tier_hydrate_on_read_seeds_oracle` — local slot pre-populated, oracle returns None; first read seeds oracle, second read returns from oracle. Anchor against B-HIGH-1.
- **Test:** `test_hvac_tier_fallback_warn_fires_when_oracle_missing` — oracle absent; descriptor logs WARN; returns local. Mirror of A-MED-5.
- **Test:** `test_dual_tier_agreement_room_key_room_name` — populate oracle from room-tier `_fan_manual_on_until` setter (room `CONF_ROOM_NAME="Living Room"`); read from HVAC-tier RoomFanState descriptor for same room; assert equal.
- **Test:** `test_external_on_racing_ura_off_is_blocked_hvac_tier` — canonical INV-FLA-T repro at write #6 (see §5.4).
- **Test:** `test_kill_switch_races_ura_off_serializes` — mutation drill at #1/#2.
- **Test:** `test_expiry_clear_refactored_out_of_hot_path` — `_is_manual_on_hold_live` invoked 100 times with a stale hold; assert `room_fan.manual_on_hold_until` NEVER mutated by the helper; assert `async_cleanup_expired_holds` clears it on its own schedule.
- **Test:** `test_malformed_cooldown_cleanup_is_race_benign` — verifies #10-#13 write pattern.
- **Test:** `test_recheck_reader_migrated_to_oracle_get_state` — inject oracle with known cooldown; `_fan_in_manual_cooldown(room)` returns True; drop oracle; returns False (fallback safety).
- **Test:** `test_recheck_reader_key_matches_room_name` — reader queries `room:{name}` key; regression guard for INV-DTA.
- **Live:** after triggering an external-ON on a bedroom fan, `oracle.get_state("room:<name>").manual_on_hold_until` in dev-tools template equals the HVAC-tier diagnostic sensor payload value.

### D2 — Six wraps + snapshot helpers + R-M-W atomic wrap + reverse-scanner + synthetic fixtures

**Files:** `automation.py` (W1, W2, W3-temp, W3-onset + `_build_fan_snapshot_room` — ~120 add / ~40 del), `hvac_fans.py` (W4 chokepoint + `_build_fan_snapshot_hvac` + §5.4a R-M-W wrap — folded into D1 diff), `hvac.py` (W8, W9 + snapshot helper access — ~90 add / ~15 del), `quality/tools/audit_fan_adjacency.py` (~120 add), `quality/tests/fixtures/fan_adjacency_synthetic/` (~50 add).

- **Verify:** `git grep -n 'oracle\.actuate' custom_components/universal_room_automation/` returns W11 (pre-existing) + W12 (pre-existing) + 7 new sites (W1, W2, W3-temp, W3-onset, W4-chokepoint, W8, W9) = 9 total async-with sites. W10-pause and W10-restore route through W4-chokepoint (no independent wrap).
- **Verify:** at each new site, `services.async_call` for the fan domain is INSIDE the `async with oracle.actuate(...)` block body — AST forward-adjacency walker passes.
- **Verify:** `is_fan_in_manual_on_hold()` explicit checks at W1/W2 are REMOVED (subsumed by wrap consult); `mark_fan_on_issued()` at W3 sites is KEPT as idempotent belt-and-suspenders.
- **Verify:** W8 wrap and W9 wrap do NOT call `_set_fan_state` (no nested-actuate deadlock possible).
- **Verify:** `pause_for_recheck` at `hvac_fans.py:1451` passes `room_name=room_name, trigger_path=FAN_TRIGGER_RECHECK_PAUSE` to `_set_fan_state` (fixes v5.70.0's `room_name=None` bypass — that was intentional PRE-FAN-LAYER-2 but is now handled by the wrap's PAUSE trigger).
- **Verify:** reverse-scanner returns 0 findings on develop tip post-D2; the synthetic-violation fixtures each produce the expected number of findings.
- **Test:** `test_w1_room_revert_wrapped_in_oracle_actuate` — manual-ON hold on room X causes revert branch to see `verdict.is_defer` and skip emit.
- **Test:** `test_w2_sleep_off_wrapped_in_oracle_actuate`.
- **Test:** `test_w3_temp_branch_wrapped`.
- **Test:** `test_w3_sleep_onset_wrapped`.
- **Test:** `test_w4_set_fan_state_wrapped_and_propagates_trigger` — trigger propagated via existing kw arg; sleep-axis mismatch mutation drill.
- **Test:** `test_w8_zone_vacancy_sweep_wrapped` — parity with existing `test_hvac_zone_vacancy_sweep_respects_manual_on_hold`.
- **Test:** `test_w8_wrap_is_not_nested_inside_set_fan_state` — mutation drill: temporarily insert a `_set_fan_state` call inside the W8 wrap body; run W8 tests; confirm deadlock is detected (timeout). Restore.
- **Test:** `test_w9_prearrival_off_wrapped`.
- **Test:** `test_w10_pause_routes_through_chokepoint_with_recheck_pause_trigger`.
- **Test:** `test_w10_restore_routes_through_chokepoint_with_recheck_restore_trigger`.
- **Test:** `test_pause_extension_atomic_vs_adopt_external` — MED-3 repro at write #15.
- **Test:** `test_note_actuation_dedup_across_ticks_same_hold_cycle` (LOW-1).
- **Test:** `test_note_actuation_writes_on_verdict_flip` (LOW-1).
- **Test:** `test_note_actuation_writes_fresh_row_after_hold_bump` (LOW-1).
- **Test:** `test_note_actuation_write_volume_under_budget_with_all_wraps` — < 200 rows/hour @ 40 rooms with 9 wraps live.
- **Test:** `test_fan_adjacency_reverse_scan_clean` — real repo passes.
- **Test:** `test_fan_adjacency_reverse_scan_flags_deleted_wrap` — Reviewer-C drill fixture: `tmp_path` copy of one wrap file with the `async with` line removed; scanner flags it.
- **Test:** `test_fan_adjacency_reverse_scan_flags_synthetic_violations` (MED-4) — iterates the 5-fixture directory and asserts findings.
- **Test:** `test_fan_adjacency_reverse_scan_respects_carveout_comments`.
- **Live:** synthesize a manual-ON at a bedroom fan; wait one HVAC tick; observe `activity_log` shows `deferred: temp_hvac by manual_on_hold` at W4 AND the fan is not turned off; the room-tier symmetric behavior (deferred `temp_room`) also present. Duplicate for a manual-OFF vs. pre-arrival ON.

### D3 — Presence-fan-recheck cleanup (subsumed into D1)

Merged into D1's commit A. Kept as a distinct verification in §D1.

### D4 — Reverse adjacency scanner (subsumed into D2)

Merged into D2's commit B.

### D5 — Doc write-back

`docs/Coordinator/HVAC.md` — HVAC-tier delegation semantics, `_room_key` unification, INV-FLA-T + INV-DTA, `§5.4` locked-setter fleet contract (which write sites are locked vs. local-only-ok, and why), reverse-adjacency scanner section, `async_cleanup_expired_holds` schedule. Post-live-validation README write-back (`docs/readmes/README_v<version>.md`) per CLAUDE.md.

---

## 11. Sharpest risk

**Two sharpest risks (tied):**

**Risk 1 — Uniqueness gate violation blocks build silently if `.storage/core.config_entries` inspection tool is unavailable.** The build-time uniqueness gate (§5.2) reads the storage file to verify CONF_ROOM_NAME uniqueness. If the Samba mount is stale or the CI environment lacks live-HA access, the gate cannot run. **Mitigation:** the gate is coded as an in-suite pytest that reads a committed fixture snapshot of `.storage/core.config_entries` (updated pre-cycle by the orchestrator using `ha-mcp` or SSH); the snapshot is what the gate asserts against. Refresh discipline: orchestrator dumps live config-entries into `quality/tests/fixtures/config_entries_snapshot.json` immediately before build dispatch. Snapshot staleness is bounded by cycle latency (days at worst), and any live change to CONF_ROOM_NAME uniqueness within that window is surfaced by the FIRST post-deploy live-validation check.

**Risk 2 — Sync-context write races (§5.4 sites #10-#13) leave the oracle transiently inconsistent with a fresh locked write.** Race benignity relies on the adopt-external re-fire clearing the transient inconsistency on the next tick. If a fresh locked write from #6 is IMMEDIATELY followed by a sync unlocked "" write from #14 (refactored out) or #11 (malformed cleanup), the fresh hold is silently dropped for one tick. **Mitigation:** the #14 refactor to `async_cleanup_expired_holds` REMOVES the highest-frequency clash site. Sites #10-#13 fire only on malformed-ISO cleanup, which is a diagnostic path (post-code-defect); it should never fire in normal operation. Reviewer B asserts sites #10-#13 have INFO-level log lines wired so any live occurrence is discoverable.

**Tertiary risk (unchanged from rev-1):** shape-(b) reliance on grep discipline for future writers. The reverse-adjacency scanner + synthetic-violation fixture (D4) close this for the shapes the scanner catches; parameter-taint through arbitrary helper hops remains a gap. Documented in the scanner header; shape-(a) promotion trigger from v2 §6.5 still applies.

---

## 12. Open questions for operator

1. **Uniqueness gate — snapshot vs. live?** Recommendation: snapshot-based pytest (fixture committed pre-cycle) so CI can enforce; live-check is a post-deploy assertion. Confirm.
2. **`async_cleanup_expired_holds` schedule** — every tick (~5 min) is cheapest; every 30 seconds is more responsive but louder. Recommendation: every tick, aligned with `FanController.update`. Confirm.
3. **Optional `_migrate_legacy_entry_keys()` cleanup** — 5 LoC to drop `entry:.*` keys from the oracle at boot. Recommendation: include; RAM-only makes it trivial. Confirm.
4. **Tier 2-DB vs Tier 3 code review — operator can elevate.** Recommendation: Tier 2-DB (§4 rationale). The plan-review round-1 already caught a design-invalidating issue (HIGH-1), so plan-review discipline has already been elevated to two reviews; if operator wants matching code-review stringency, add a fourth adversarial-completeness pass focused on re-enumerating all fan-emission surfaces beyond this cycle's diff.

---

## 13. Plan completion tracking (open items to reconcile at close)

- Any of the six wraps skipped → INV-FLA-T half-proven; card FAN-LAYER-3.
- Reverse-adjacency scanner not landed → completeness half open; card FAN-LAYER-3.
- Any §5.4 site not converted per its classification → note in README write-back with concrete repro.
- Uniqueness gate blocked build → resolve naming collision before re-dispatch; do not weaken the gate.
- `docs/Coordinator/HVAC.md` write-back (D5) — must land pre-close.
- README `Validated <date>` table populated post-live-validation before cycle closes.

---

## 14. Plan-review record

### Round 1 (2026-08-11, adversarial) — NEEDS-REVISION

| # | Sev | Finding | Disposition in rev-2 |
|---|---|---|---|
| HIGH-1 | HIGH | §5.2 key amendment was wrong twice: `_fan_ledger_key()` returns PREFIXED keys, so unprefixed `room_name` orphans pre-deploy rows; and `room_name`-first re-opens the A-HIGH-1 duplicate-name collision (uniqueness, not truthiness, is the needed invariant). Reviewer asked for either Option A (keep prefixes + evidence both tiers derive same name) or Option B (unprefix + live-uniqueness build gate + boot-time key migration). | ADOPTED — **Option A**. §5.2 rewritten: `_fan_ledger_key()` prefers `f"room:{name}"` over `f"entry:{eid}"`; HVAC-tier uses `_room_key(room_name) → f"room:{room_name}"`. Evidence that both tiers derive the SAME string from `CONF_ROOM_NAME`: room-tier `automation.py:263`, HVAC-tier `hvac_fans.py:170` (with empty-name skip at :171), W8 `hvac.py:2803-2807` — same field, same string. RAM-only ledger makes migration trivial (§5.2 spelled out). Uniqueness gate is MANDATORY BUILD BLOCKER (not a mere finding). |
| HIGH-2 | HIGH | §5.4 must enumerate ALL 15 hvac_fans writes and classify each; 4/15 is not a spec. All fire from async contexts, so async-locked setters are viable; if any setter must stay sync, give the concrete mechanism (a sync setter cannot await an asyncio.Lock). | ADOPTED — §5.4 rewritten with the full 15-row table: 9 `locked_setter_required`, 4 `local_only_ok` (sync-context malformed cleanup + adopt re-fire self-healing), 1 refactored-out (#14: `_is_manual_on_hold_live` no longer mutates; moved to `async_cleanup_expired_holds`), 1 `locked R-M-W atomic guard` (#15: §5.4a). Concrete mechanism for each. |
| HIGH-3 | HIGH | §2.2 line refs are STALE. Real sites: `is_fan_in_manual_on_hold` at `automation.py:2072, :2159`; `mark_fan_on_issued` at `:2234, :2898` (+ helpers `:511, :547`). Re-grep EVERY W-site line ref against develop tip and rewrite the table; also re-verify W8/W9 hvac.py refs. | ADOPTED — §2.2 rewritten with re-greped line refs including guard + emit sites: W1 guard `:2159` / emit `:2171`; W2 guard `:2072` / emit `:2080`; W3 guard `:2234` (temp) + `:2898` (onset), helpers `:511`/`:547`; W8 guards `:2751/:2754/:2764` / emit `:2786`; W9 guards `:2998/:3000/:3006` / emit `:3021`. |
| MED-1 | MED | Descriptor construction: dataclass `__init__` fires `__set__` with `_hass=None` → WARN flood at every `discover_fans`. Pick a mechanism (dropping @dataclass is cleanest — remove the §2.7 non-goal if so) and verify slots not set. | ADOPTED — drop `@dataclass`; explicit `__init__` orders `_hass` first and uses `object.__setattr__` for initial-state seed of `_manual_*_local` slots (bypasses descriptor). Non-goal "No `RoomFanState` dataclass removal" rescinded (§3). Grep verified `RoomFanState` has no `__slots__`. |
| MED-2 | MED | Resolve nested-actuate YOURSELF pre-build with greps: do W8/W9 route through `_set_fan_state`? asyncio.Lock non-reentrant → ambiguity is deadlock. | ADOPTED — §5.3 cites the grep evidence: W8 emit at `hvac.py:2786` and W9 emit at `hvac.py:3021` are DIRECT `services.async_call`, NOT through `_set_fan_state`. Therefore W8/W9 wraps are INDEPENDENT (not nested). W10-pause/restore DO route through chokepoint and rely on the chokepoint wrap; no independent wrap for them. Test `test_w8_wrap_is_not_nested_inside_set_fan_state` (mutation drill) asserts deadlock is detected if a builder ever nests them. |
| MED-3 | MED | Spec pause-context atomicity at `:1477` (R-M-W vs adopt interleave) + named test. | ADOPTED — §5.4a spells out the R-M-W lock wrap, with the asyncio.Lock non-reentrancy note (use `oracle._get_lock(...)` directly + call sync `set_manual_on_hold`, not `_locked`). Test `test_pause_extension_atomic_vs_adopt_external`. |
| MED-4 | MED | Spec the reverse-scanner AST rules for `_set_fan_state`'s parameter-taint + the `startswith("fan.")` branch, or mandate a synthetic-violation fixture proving the walker catches it. | ADOPTED — §5.5 documents 5 AST rules (direct fan domain, `startswith("fan.")` branch, `_set_fan_state`-taint via a hard-coded chokepoint allowlist, enclosing `oracle.actuate` context, carve-out comment). MANDATED synthetic-violation fixture directory `quality/tests/fixtures/fan_adjacency_synthetic/` with 5 files; `test_fan_adjacency_reverse_scan_flags_synthetic_violations` asserts each fixture produces the expected finding. |
| LOW-1 | LOW | Cite the note_actuation dedup key and same-trigger re-fire case. | ADOPTED — §5.6 cites `edge_key = (trigger_path, rec.hold_id)` at `fan_policy_oracle.py:547` and enumerates the ALLOW→ALLOW, ALLOW→DEFER→ALLOW, and post-hold-bump cases with 3 regression tests. |
| LOW-2 | LOW | Split observability reads from decision reads in §2.1. | ADOPTED — §2.1 now enumerates 11 decision reads + ~10 observability reads with the rationale that observability can tolerate ledger jitter. |
| LOW-3 | LOW | Add an overrun trigger (>900 LoC → split 2a/2b). | ADOPTED — §8 gains the OVERRUN trigger clause (>~900 LoC OR >~28 tests → split D2a/D2b as two commits on one branch, one PR). |

### Round 2 (pending)

Per plan-review-round-1 closing note ("A SECOND plan-review pass follows before build — plan discipline elevated per reviewer recommendation (this surface shipped 2 fix-ups last cycle)"), rev-2 is expected to receive one more adversarial plan review before build dispatch. Round-2 framing recommended: **adversarial build-prediction — "what will the builder get wrong reading rev-2?"** (Tier-3 plan-review framing 2). Round-1 was framing 1 (completeness re-enumeration) that surfaced HIGH-3 stale line refs and HIGH-2 incomplete write classification.

If round 2 returns NEEDS-REVISION, rev-3 will be produced with the same disposition discipline shown above. If round 2 returns SHIP, build dispatches.
