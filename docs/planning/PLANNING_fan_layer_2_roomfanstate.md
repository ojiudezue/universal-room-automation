# PLANNING — FAN-LAYER-2: RoomFanState HVAC-tier delegation + oracle.actuate wrap-out

**Card:** FAN-LAYER-2 (deferred scope from FAN-LAYER-1 v5.70.0)
**Author:** ura-planner (opus)
**Date:** 2026-08-11 (rev-3 after plan-review round 2)
**Revision:** rev-3 — six targeted edits from round-2 (HIGH-1, HIGH-2, MED-1, MED-2, LOW-1, LOW-2). No structural changes vs rev-2. See §14 round-2 dispositions.
**Base branch:** `develop` at v5.70.0 (post-merge of FAN-LAYER-1 Sessions 1–3 + fix-up)
**Supersedes:** none — a direct continuation of `docs/planning/PLANNING_fan_actuation_shared_layer_v2.md` §7.9, §7.10, §11 and of the FAN-LAYER-1 review record's deferred-carded scope (`docs/reviews/code-review/v5.70.0_fan_layer_1.md`).

---

## 1. Falsifiable invariants (Reviewer D targets, up front)

Two invariants; both must hold at cycle close.

> **INV-FLA-T (temporal fan-layer authority, from v2 §7.9).** For any room `r`, if `manual_on_hold_until` becomes live at time `T` (via external-ON adopt), NO URA-issued fan OFF against `r` may reach `hass.services.async_call` return at any `T' > T` until the hold expires or is explicitly discharged (external-OFF, kill switch, safety-stop). Equivalent operational restatement: every URA-emitting site listed in §2.2 (W1, W2, W3, W8, W9, W10-pause, W10-restore) executes the `consult → services.async_call → note_actuation` sequence INSIDE an `oracle.actuate(room, trigger, snapshot, direction)` async-with block that holds the per-room `asyncio.Lock` across all three steps; AND every write to `manual_on_hold_until` / `manual_off_cooldown_until` originating from a URA async path (§5.4 classification) is performed under the same per-room lock.
>
> **Concrete legal-config reachable repro to break INV-FLA-T if the lock is missing:** room A has a live `may_turn_off(TEMP_ROOM)` consult that ALLOWed at T0; between T0 and the `await services.async_call` return, an external-ON dispatch fires on room A's fan `state_changed` bus → `RoomFanState.update()` adopt-external path at `hvac_fans.py:335` writes `manual_on_hold_until` at T1; the URA OFF completes at T2. Post-condition: the fan is OFF and the ledger says hold is live — a state the invariant forbids because the emitting caller cannot legitimately claim consult authority once the hold opened. The lock closes this window by forcing the adopt-side write at :335 to acquire the same per-room lock, serializing behind the URA-side critical section.

> **INV-DTA (dual-tier agreement, from FAN-LAYER-1 B-MED-3 residual).** For any room `r` served by BOTH the room-tier surface (`RoomAutomation` in `automation.py`) AND the HVAC-tier surface (`RoomFanState` in `hvac_fans.py`), a call to `oracle.get_state(<key(r)>).manual_on_hold_until` returns the SAME datetime regardless of which tier last wrote — where `<key(r)>` is the SAME string in both tiers per §5.2. Equivalently: `RoomFanState.manual_on_hold_until` and `RoomFanState.manual_off_cooldown_until` are NOT independent state — they are read-through views of the oracle ledger.
>
> **Concrete legal-config reachable repro to break INV-DTA if key spaces diverge:** HVAC-tier zone-vacancy sweep (W8) sees room "Living Room" and its adopt path writes to oracle key `room:Living Room` at T0. Simultaneously the room-tier `may_turn_off(TEMP_ROOM)` consult in `automation.py:2159` runs against oracle key `entry:01H...` (its config-entry id) and returns ALLOW because the room-tier row shows no hold. OFF emits — invariant broken. §5.2 closes this by unifying both tiers on `room:{normalize(CONF_ROOM_NAME)}` under a uniqueness + normalization gate.

Reviewer D's mandate: enumerate the ENTIRE fan-emission surface AND the ENTIRE `RoomFanState` field write surface (§2.1 + §2.2 + §5.4 tables) and mutate one site at a time to prove BOTH invariants. Include pre-existing code, not just the diff.

---

## 2. Institutional context verified

### 2.1 Field-access count — hypothesis "~34" was low; actual **46 lines**

`git grep -n 'manual_off_cooldown_until\|manual_on_hold_until' custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` on develop tip returns **46 lines**. Classified against the v2 §11 template AND split by LOW-2-round-1 into decision-reads vs observability-reads:

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

**Reads split by consumption class (LOW-2-round-1):**

- **DECISION reads (LOAD-BEARING — MUST see the write ordering enforced by §5.4's locked setters):** `hvac_fans.py:356` (external-ON adopt suppression guard), `:638, :641` (sleep-onset skip on live cooldown), `:842, :844` (temp-fan cooldown gate — see §5.4 row #14 note: this compare is PRESERVED at read-time), `:1076, :1079` (`_is_manual_on_hold_live` — feeds `is_room_in_manual_on_hold` consumed by W8/W9; PRESERVED at read-time), `:1469, :1474` (pause-context R-M-W), `presence_fan_recheck.py:1002, :1007` (recheck cooldown guard). **Total = 11 decision reads.**
- **OBSERVABILITY reads (can tolerate ledger jitter):** `hvac_fans.py:1588, :1589, :1597, :1600` (diag sensor filter), `:342, :344, :418, :420, :1212, :1484` (log-line format-args). **Total = ~10 observability reads.**

Real writes (must migrate — §5.4 classifies each): 221, 225, 308, 312, 325, 335, 339, 411, 415, 651, 847, 849, 1081, 1089, 1477. **Total = 15 writes** — fully enumerated + classified in §5.4.

**Presence-fan-recheck reader (task item 2).** `_fan_in_manual_cooldown(room_name)` at `presence_fan_recheck.py:992-1014` is the only reader; today it reaches through `hass.data → coordinator_manager → hvac.fan_controller._room_fans[room_name]`. Migration: replace with `oracle = _get_fan_oracle(self.hass); until = oracle.get_state(_room_key(room_name)).manual_off_cooldown_until if oracle else None; return until is not None and dt_util.now() < until`, where `_room_key` is the shared prefixer per §5.2.

### 2.2 Emitter enumeration — the 6 unwrapped writers, RE-VERIFIED line refs on develop tip

Post-v5.70.0, only W11 (`hvac.py:2654`) and W12 (`hvac_predict.py:1164`) are wrapped in `oracle.actuate`. Confirmed by `git grep 'oracle\.actuate'`. Six writers remain unwrapped — v2 line refs were STALE; re-greped:

| # | Site | Guard file:line (READ) | Emit file:line (`services.async_call`) | Direction | Current gate | Wrap target |
|---|---|---|---|---|---|---|
| W1 | Room-tier temp/vacancy revert | `automation.py:2159` (`is_fan_in_manual_on_hold()`) | `automation.py:2171` (`_safe_service_call("homeassistant", SERVICE_TURN_OFF, ...)`) | OFF | @property-backed check | `oracle.actuate(room_key, FAN_TRIGGER_TEMP_ROOM, snap, "off")` |
| W2 | Room-tier `FAN_SLEEP_OFF` | `automation.py:2072` (`is_fan_in_manual_on_hold()`) | `automation.py:2080` | OFF | same | `oracle.actuate(room_key, FAN_TRIGGER_SLEEP_OFF, snap, "off")` |
| W3 | Room-tier turn-ON — 2 sites | `:2234` (temp) + `:2898` (sleep-onset). Helpers `:511`/`:547`. | temp: `~2239-2260` (`fan.turn_on`); onset: `2900-2911` | ON | `mark_fan_on_issued` seed | `oracle.actuate(room_key, FAN_TRIGGER_TEMP_ROOM_ON \| FAN_TRIGGER_SLEEP_ONSET_ON, snap, "on")` at BOTH sites |
| W4-chokepoint | HVAC `_set_fan_state` service-call block | n/a — chokepoint | `hvac_fans.py:1231-1258` | ON + OFF | reads local ISO via descriptors post-D1 | `oracle.actuate(room_key, trigger_path, snap, direction)` around 1231-1258 |
| W8 | HVAC zone-vacancy sweep | `hvac.py:2751/:2754/:2764` | `hvac.py:2786` (DIRECT — NOT through `_set_fan_state` — evidence §5.3) | OFF | tier-fused check | INDEPENDENT `oracle.actuate(room_key, FAN_TRIGGER_HVAC_VACANCY, snap, "off")` |
| W9 | HVAC pre-arrival deactivation | `hvac.py:2998/:3000/:3006` | `hvac.py:3021` (DIRECT) | OFF | same | INDEPENDENT `oracle.actuate(room_key, FAN_TRIGGER_HVAC_PREARRIVAL, snap, "off")` |
| W10-pause | recheck pause OFF → `FanController.pause_for_recheck` | (upstream `_fan_in_manual_cooldown`) | `hvac_fans.py:1451` (enters W4 chokepoint) | OFF | none at emit | **NO independent wrap** — routes through W4-chokepoint via `trigger_path=FAN_TRIGGER_RECHECK_PAUSE` |
| W10-restore | recheck restore ON | `:1469-1487` R-M-W (MED-3) | restore branch `_set_fan_state(..., True, speed)` | ON | none | routed via W4 chokepoint with `FAN_TRIGGER_RECHECK_RESTORE`; R-M-W lock at §5.4a |

**Per-site verdict table:**

| Site | Verdict | Wrap owner | Wrap independence | Snapshot builder | Trigger constant | Test-name |
|---|---|---|---|---|---|---|
| W1 | WRAP | `RoomAutomation.handle_temperature_based_fan_control` revert | INDEPENDENT | `_build_fan_snapshot_room` | `FAN_TRIGGER_TEMP_ROOM` | `test_w1_room_revert_wrapped_in_oracle_actuate` |
| W2 | WRAP | same handler, sleep branch | INDEPENDENT | same | `FAN_TRIGGER_SLEEP_OFF` | `test_w2_sleep_off_wrapped_in_oracle_actuate` |
| W3 | WRAP at BOTH `:2234` and `:2898` | temp-branch + sleep-onset | INDEPENDENT (both) | same | `FAN_TRIGGER_TEMP_ROOM_ON` / `FAN_TRIGGER_SLEEP_ONSET_ON` | `test_w3_temp_branch_wrapped`, `test_w3_sleep_onset_wrapped` |
| W4-chokepoint | WRAP lines 1231-1258 only | `FanController._set_fan_state` | CHOKEPOINT | `_build_fan_snapshot_hvac` | trigger propagated via existing kw arg | `test_w4_set_fan_state_wrapped_and_propagates_trigger` |
| W8 | WRAP INDEPENDENT (NOT through chokepoint) | `hvac.py::_execute_vacancy_sweep` | INDEPENDENT | `_build_fan_snapshot_hvac` via `FanController` helper | `FAN_TRIGGER_HVAC_VACANCY` | `test_w8_zone_vacancy_sweep_wrapped` |
| W9 | WRAP INDEPENDENT | `hvac.py::_deactivate_prearrival_fans` | INDEPENDENT | same | `FAN_TRIGGER_HVAC_PREARRIVAL` | `test_w9_prearrival_off_wrapped` |
| W10-pause | NO new wrap | `FanController.pause_for_recheck` | ROUTES THROUGH W4 | chokepoint builds | `FAN_TRIGGER_RECHECK_PAUSE` | `test_w10_pause_routes_through_chokepoint_with_recheck_pause_trigger` |
| W10-restore | NO new wrap | `FanController.restore_after_recheck` | ROUTES THROUGH W4 | chokepoint builds | `FAN_TRIGGER_RECHECK_RESTORE` | `test_w10_restore_routes_through_chokepoint_with_recheck_restore_trigger` + `test_pause_extension_atomic_vs_adopt_external` |

**Nested-actuate deadlock avoided by construction** — see §5.3 for grep evidence + Reviewer-B verification item added in rev-3.

### 2.3 Restart / reload semantics — VERIFIED

`RoomFanState` is a `@dataclass` today on `FanController` (`hvac_fans.py:67-108`) — **NOT persisted**. Explicit RAM-only comment at :92. `git grep -E 'RestoreEntity|Store\(|save_state|restore_state' hvac_fans.py` returns nothing. Re-init at `discover_fans()` :157 (`self._room_fans.clear()`).

Comparison to `EVSEState`: `EVSEState` uses `homeassistant.helpers.storage.Store`; `RoomFanState` does not. No blob to migrate.

Restart post-migration: oracle constructed at CoordinatorManager __init__ (Session 2), `FanController.discover_fans()` clears `_room_fans`, first HVAC tick's adopt-external paths at `:308-339` fire oracle writes via new descriptor / locked setters. **No new persistence, no lifecycle change vs. today.**

**RoomFanState hydration parity note (B-HIGH-1 sister case) — LOAD-BEARING.** The Session-2 room-tier @property at `automation.py:293-296` includes hydrate-on-read: if `oracle_val is None and local is not None`, seed oracle from local. HVAC-tier delegation MUST include the symmetric step — see §5.1 spec + D1 test `test_hvac_tier_hydrate_on_read_seeds_oracle`.

**Reload discipline (B-HIGH-2):** CM reload REUSES `hass.data[DOMAIN]["fan_oracle"]`. No touch to CM singleton lifecycle in this cycle; Reviewer B verifies at build.

### 2.4 Greps — REUSED vs NEW

REUSED (with file:line): `FAN_TRIGGER_*` (`const.py`, imported at `fan_policy_oracle.py:85-93`), `FanDecisionSnapshot` (`fan_policy_oracle.py:142-156`), `oracle.actuate` (`fan_policy_oracle.py:379-409`), `oracle.set_manual_*` sync setters (`:234-267`), `oracle.get_state`, `_get_fan_oracle(hass)`, `_fan_ledger_key()` prefixed-key contract (`automation.py:250-268` — AMENDED §5.2), `is_room_in_manual_on_hold` (`hvac_fans.py:1094-1106`), `mark_fan_on_issued` (`automation.py:511` + oracle edge `:547`), `is_fan_in_manual_on_hold` (`automation.py:495`), `_is_manual_on_hold_live` (`hvac_fans.py:1060-1092` — **read-time behavior PRESERVED** per §5.4 row #14; no refactor).

NEW: `_build_fan_snapshot_room` / `_build_fan_snapshot_hvac` (per-tier snapshot builders; NEW because axis differs), `_room_key(room_name)` module helper (`f"room:{normalize(room_name)}"` per §5.2), `_OracleISOField` descriptor class (NEW; RoomAutomation @property can't be reused), `set_manual_on_hold_locked` / `set_manual_off_cooldown_locked` / `clear_manual_on_hold_locked` / `clear_manual_off_cooldown_locked` async methods (NEW — existing sync setters unlocked), reverse-adjacency AST pass (NEW logic in existing `audit_fan_adjacency.py`), synthetic-violation fixtures under `quality/tests/fixtures/fan_adjacency_synthetic/` (NEW), `async_cleanup_expired_holds` helper (NEW — cosmetic hygiene only, called inline from `FanController.update`; §5.4 row #14).

### 2.5 Prior planning docs consulted

- `PLANNING_fan_actuation_shared_layer_v2.md` — end-to-end.
- `docs/reviews/code-review/v5.70.0_fan_layer_1.md` — end-to-end. Bug classes: Hollow anchor #13, Lifecycle-recreation state loss (B-HIGH-1 / B-HIGH-2), Silent anchor loss.
- `PLANNING_fan_manual_on_override.md` (FAN-MANUAL-1) — skim; hold semantics unchanged.

### 2.6 Memory bodies pulled

- `feedback_hollow_test_anchors.md`, `feedback_suppression_needs_discharge.md`, `feedback_no_fabrication.md`, `feedback_mutation_verification_pycache_staleness.md`, `feedback_marginal_benefit_pushback.md`, `project_optimizer_db_write_flood_incident_2026_06_09.md`.

### 2.7 Design docs read

`docs/Coordinator/HVAC.md` — v2 D9 write-back owed; if not landed, D5 absorbs.

### 2.8 Code locations surveyed end-to-end

- `hvac_fans.py:1-500` (RoomFanState decl, `turn_off_all_managed`, adopt paths), `:625-720` (sleep-onset skip), `:836-849` (evaluate cooldown gate), `:1050-1170` (`_is_manual_on_hold_live` + `is_room_in_manual_on_hold` + `_set_fan_state` signature), `:1230-1268` (W4 chokepoint), `:1400-1512` (`snapshot_room_fan`, `pause_for_recheck`, `restore_after_recheck`), `:1580-1610` (diag filter).
- `fan_policy_oracle.py:1-560` — full module read.
- `automation.py:240-395` (`_fan_ledger_key`, @property delegations), `:495-555` (`is_fan_in_manual_on_hold`, `mark_fan_on_issued`), `:2060-2260` (W1/W2/W3-temp), `:2880-2920` (W3-onset).
- `presence_fan_recheck.py:990-1020`.
- `hvac.py:1220-1240` (`_fan_controller.update` call at :1227 — MED-1 evidence: no `oracle.actuate` above the call), `:2570-2700` (W11), `:2700-2800` (W8 emit at :2786), `:2960-3035` (W9 emit at :3021).
- `hvac_predict.py:1150-1180` (W12).
- `quality/tools/audit_fan_adjacency.py:1-200`.

---

## 3. Non-goals (explicit)

- **No new fan POLICIES.** All existing tunables byte-frozen.
- **No persistence added.** RAM-only.
- **No new operator-facing knobs.**
- **No dashboard/PWA changes.** No new trigger strings.
- **No W11 / W12 rework.**
- **No unification of room-tier vs HVAC-tier decision sources.**
- **No humidity-fan absorption.**
- **No shape (a) gateway construction.**
- **`RoomFanState` STOPS BEING A `@dataclass`** (MED-1-round-1 forces this — see §5.1). It becomes a plain class with an explicit `__init__` whose signature is **backward-compatible with every current @dataclass field as keyword-only-optional with today's defaults** (HIGH-1-round-2 requirement — the §9 parity gates constructors must not TypeError).
- **`_is_manual_on_hold_live` READ-TIME EXPIRY IS PRESERVED** (HIGH-2-round-2). See §5.4 row #14 — read-time evaluation stays load-bearing; the new `async_cleanup_expired_holds` is cosmetic hygiene only.
- **No test modifications to the FAN-LAYER-1 / v5.68.0 parity gates** (§9).

---

## 4. Tier — Tier 2-DB with plan-review discipline elevated (round 2 pending PLAN-READY)

Tier 2-DB (three framing-disjoint code reviews + live validation). Rationale unchanged from rev-1/rev-2. If operator wants Tier 3 code-review stringency, add a fourth adversarial-completeness review focused on re-enumerating all fan-emission surfaces beyond this cycle's diff.

**Plan-review discipline:** rev-1 got ONE plan review (round-1, framing = completeness). Rev-2 got a SECOND plan review (round-2, framing = adversarial build-prediction). Round-2 returned NEEDS-REVISION with 5 targeted edits addressed here in rev-3. Coordinator has stated that if rev-3 addresses all round-2 items with no new material, they will declare PLAN-READY on their own verification — no third review round.

**Framings for code review (three, disjoint):**
- **A — correctness + edge cases + hydrate-on-read parity + sleep-axis routing.**
- **B — async lifecycle + INV-FLA-T + reload resilience + descriptor init order + no-wrap-encloses-FanController.update verification (MED-1-round-2).**
- **C — per-site source mutation + reverse-adjacency scanner + synthetic-violation fixture drill.** `PYTHONDONTWRITEBYTECODE=1` + `__pycache__/` purge before drill.

---

## 5. Design

### 5.1 HVAC-tier RoomFanState delegation — plain class, descriptor + hydrate-on-read (MED-1-round-1) — **backward-compat __init__ signature (HIGH-1-round-2)**

Drop `@dataclass` from `RoomFanState`; use a plain class with an explicit `__init__`. Ordering: `_hass` first, then `object.__setattr__` for the two `_manual_*_local` slots (bypasses descriptor at construction) — closes the WARN-flood concern.

**Backward-compat __init__ signature (HIGH-1-round-2):** the rev-2 signature `(room_name, zone_id, *, hass, room_type, fan_entities)` TypeErrored ~10 existing test constructors (test_fan_manual_on_hold_hvac_tier.py:256, test_v4713...:611, test_hvac_fan_control.py:172, test_fan_incident replay:404, comfort_fan_away_veto:402, fan_trust_state:247, fan_sweep_trio:262, sleep_fans_and_flash:368/829/970) including §9 parity gates. **Rev-3 signature accepts EVERY current @dataclass field as keyword-only optional with today's defaults**, so existing constructors work byte-identical.

```python
# hvac_fans.py — replaces the @dataclass RoomFanState
class RoomFanState:
    """Tracks fan state for a single room.

    FAN-LAYER-2: dropped `@dataclass` sugar because two fields
    (`manual_off_cooldown_until`, `manual_on_hold_until`) are now
    delegated to `FanPolicyOracle` via class-level `_OracleISOField`
    descriptors. dataclass-generated `__init__` invokes `self.field =
    value` on every constructed instance, flooding the descriptor with
    pre-`_hass` writes. The explicit `__init__` below orders `_hass`
    first, then seeds locals via `object.__setattr__` (bypassing
    descriptors), leaving subsequent runtime writes to flow through.
    """

    def __init__(
        self,
        room_name: str,
        zone_id: str,
        *,
        # NEW in FAN-LAYER-2 — kw-only optional so existing constructors
        # (incl. §9 parity gates) keep working unmodified with hass=None
        # + descriptor fallback (see _OracleISOField.__get__ /__set__).
        hass: "HomeAssistant | None" = None,
        # EVERY current @dataclass field, kw-only optional with today's
        # defaults, so no existing test constructor TypeErrors.
        room_type: str = ROOM_TYPE_GENERIC,
        fan_entities: list[str] | None = None,
        is_on: bool = False,
        speed_pct: int = 0,
        trigger: str = "",
        last_on_time: str = "",
        vacancy_detected_time: str = "",
        manual_off_cooldown_until: str = "",
        manual_on_hold_until: str = "",
        manual_on_hold_paused_at: str = "",
        fan_recheck_suppress_until: str = "",
        fan_sleep_policy: str = DEFAULT_FAN_SLEEP_POLICY,
    ) -> None:
        # ORDERING: _hass FIRST so any subsequent descriptor __set__ can
        # resolve the oracle. object.__setattr__ bypasses the descriptor.
        object.__setattr__(self, "_hass", hass)
        self.room_name = room_name
        self.zone_id = zone_id
        self.room_type = room_type
        self.fan_entities = list(fan_entities or [])
        self.is_on = is_on
        self.speed_pct = speed_pct
        self.trigger = trigger
        self.last_on_time = last_on_time
        self.vacancy_detected_time = vacancy_detected_time
        # Seed the delegated fields via object.__setattr__ to the local
        # slot — do NOT go through the descriptor at __init__ time.
        # If caller supplies non-default values (rare — parity fixtures
        # do supply them), they land in the local slot; hydrate-on-read
        # will seed the oracle from local on first descriptor GET.
        object.__setattr__(self, "_manual_off_local", manual_off_cooldown_until)
        object.__setattr__(self, "_manual_on_local", manual_on_hold_until)
        self.manual_on_hold_paused_at = manual_on_hold_paused_at
        self.fan_recheck_suppress_until = fan_recheck_suppress_until
        self.fan_sleep_policy = fan_sleep_policy

# Descriptors applied AFTER class definition.
RoomFanState.manual_off_cooldown_until = _OracleISOField(
    "manual_off_cooldown_until", "set_manual_off_cooldown", "_manual_off_local",
)
RoomFanState.manual_on_hold_until = _OracleISOField(
    "manual_on_hold_until", "set_manual_on_hold", "_manual_on_local",
)
```

**`discover_fans()` (`hvac_fans.py:151-202`) is amended** to pass `hass=self.hass` on every `RoomFanState(...)` construction.

**Fixture constructions in existing tests do NOT need changes** (LOW-2-round-2 delete — rev-2 said "add `hass=mock_hass` to every direct constructor"; that is REMOVED here). Rationale: the `_hass=None` fallback is fully covered by `_OracleISOField.__get__` / `__set__` (they log `_fallback_warn` and return / stash to local). Existing tests that construct RoomFanState directly without `hass=` continue to work; the descriptor gracefully degrades to local-slot-only, which is the exact behavior those tests exercise today (they don't have an oracle wired either).

**Descriptor (module-level):**

```python
class _OracleISOField:
    """Read-through view of oracle.get_state(_room_key(room_name)).<field>
    as an ISO string, with hydrate-on-read + fail-safe fallback to a local
    slot. Mirrors RoomAutomation @property at automation.py:283-329.
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
    """Shared prefixed key for oracle ledger access (§5.2).

    Normalizes for Unicode combining sequences + trims whitespace so
    that "Café" (NFC) and "Café" (NFD) hash to the same row (MED-2-
    round-2). Rejects control characters. Colon in a name is legal but
    logged (the prefix is `room:` and colon collisions are cosmetic).
    """
    import unicodedata
    normalized = unicodedata.normalize("NFC", room_name).strip()
    # Reject control chars (defensive — HA UI does not allow these but
    # a hand-edited config-entry can smuggle them).
    if any(unicodedata.category(ch).startswith("C") for ch in normalized):
        _LOGGER.error(
            "fan-layer-2: rejecting room_name with control chars: %r",
            room_name,
        )
        raise ValueError(f"room_name contains control characters: {room_name!r}")
    if ":" in normalized:
        _LOGGER.info(
            "fan-layer-2: room_name contains ':' — legal but cosmetic "
            "collision with prefix scheme (name=%r)", normalized,
        )
    return f"room:{normalized}"
```

**Round-trip guarantee:** `RoomFanState.f = dt.isoformat()` → local stored, parse → `dt2`, `oracle.set(dt2)`. Read: `oracle.get()` returns `dt2`, descriptor returns `dt2.isoformat()`. Test `test_hvac_iso_datetime_round_trip_preserves_value` asserts equality at microsecond.

### 5.2 Key-space unification — Option A (keep prefixes; room-name-first) with uniqueness + normalization gate (HIGH-1-round-1 + MED-2-round-2)

**Chosen: Option A.** `_fan_ledger_key()` at `automation.py:250-268` amended to prefer `f"room:{normalize(name)}"` over `f"entry:{eid}"`, using the same `_room_key` normalization helper as the HVAC tier (§5.1 helper `_room_key`, exported for reuse from `hvac_fans`).

**Evidence both tiers derive the SAME string:** room-tier `automation.py:263` (`name = self.config.get(CONF_ROOM_NAME, "")`); HVAC-tier `hvac_fans.py:170` with empty-name skip at :171 (guaranteeing non-empty at HVAC tier); W8 confirms same source at `hvac.py:2803-2807`.

**Normalization (MED-2-round-2):** the `_room_key` helper applies `unicodedata.normalize("NFC", name).strip()` before keying/comparing. NFC form is what HA's config-flow stores (HA uses Python 3 str which is normalized on input by the frontend); NFD-encoded input from a clipboard paste in an options-flow WOULD produce a different key than NFC-stored data — the normalize step closes it. Whitespace trim closes the "Living Room " vs "Living Room" trailing-space case (HA's config-flow does trim but a hand-edited storage file may not). Control characters are REJECTED (raises ValueError, surfaced at build via the uniqueness gate — see below). Colon in the name is LEGAL but LOGGED (a name like "3:00 room" would produce key `room:3:00 room` which is unambiguous — the prefix `room:` is fixed-length so downstream parsers split on the first colon).

**Uniqueness + normalization gate (BUILD-TIME, MANDATORY BLOCKER):** implemented as a pytest that reads a committed snapshot of `.storage/core.config_entries` (see §10-D1 / §11-Risk-1 reconciliation LOW-1-round-2 — one mechanism, named pytest below) and asserts, across all `ENTRY_TYPE_ROOM` entries: (a) `CONF_ROOM_NAME` non-empty; (b) `_room_key(name)` succeeds (does not raise on control chars); (c) `_room_key(name)` is UNIQUE. A violation blocks build dispatch — remediation is a config-flow rename before re-dispatch, not a plan weakening.

**Migration is trivial** — RAM-only ledger. HA restart wipes old rows. Options-flow reload leaks harmless `entry:.*` rows cleaned by the optional 5-line `_migrate_legacy_entry_keys()` in `fan_policy_oracle.py` called once from `CoordinatorManager` after oracle attach.

**Consumers to update:** `automation.py:_fan_ledger_key` (amended); `hvac_fans.py` descriptor + wrap sites use `_room_key`; `hvac.py:_execute_vacancy_sweep` (W8) + `_deactivate_prearrival_fans` (W9) at wrap sites; `presence_fan_recheck.py:_fan_in_manual_cooldown` (D3).

**Tests:** `test_dual_tier_agreement_room_key_room_name` (populate from room-tier, read from HVAC-tier, assert equal); `test_room_key_normalizes_nfc_vs_nfd` (NFC and NFD forms produce the same key); `test_room_key_rejects_control_chars` (raises ValueError); `test_room_key_logs_colon_in_name` (WARNING/INFO logged).

### 5.3 Six wraps — W8/W9 do NOT route through `_set_fan_state` (MED-2-round-1) — **`FanController.update` is intentionally UNWRAPPED (MED-1-round-2)**

`git grep -n 'services.async_call' custom_components/universal_room_automation/domain_coordinators/hvac.py` returns 8 hits; the two that iterate `CONF_FANS` are at `hvac.py:2786` (`_execute_vacancy_sweep`) and `hvac.py:3021` (`_deactivate_prearrival_fans`). Both are DIRECT `hass.services.async_call(...)` — grep of enclosing functions for `_set_fan_state` returns zero hits. **W8 and W9 wraps are INDEPENDENT** (not nested inside W4-chokepoint). No reentrancy hazard.

**MED-1-round-2 — `FanController.update` is intentionally OUTSIDE any `oracle.actuate` wrap.** Evidence: `FanController.update` is called from `hvac.py:1227` (`await self._fan_controller.update(self._energy_constraint, self._house_state)`) inside `HvacCoordinator._async_update_data`. Grep of the enclosing function for `oracle.actuate` returns zero — no `async with oracle.actuate(...)` encloses the call site. This is INTENTIONAL because:

- `FanController.update` iterates ALL rooms (`for room_name, room_fan in self._room_fans.items():` at `:279`); a per-invocation wrap would need to acquire ALL per-room locks up-front (deadlock risk with W8/W9 which acquire per-room locks INDIVIDUALLY during their zone-sweep iterations).
- Sites #3 and #6 (external-OFF and external-ON adopt writes) fire from inside `update()`. Under the plan, these writes go through `set_manual_off_cooldown_locked` / `set_manual_on_hold_locked` which acquire the per-room lock INDIVIDUALLY per write — the per-room lock IS the atomicity boundary for those writes, not a wrapping `oracle.actuate` block. Wrapping `update()` in `oracle.actuate` at some higher level would (a) require a bogus "room" key (there is no single room for a cross-room iteration) and (b) deadlock the per-write `_locked` setters (asyncio.Lock non-reentrant).

**Reviewer-B verification item (added):** confirm no future wrap encloses `FanController.update`. Specifically:
1. `git grep -B 10 'await self\._fan_controller\.update(' custom_components/universal_room_automation/` — assert no `async with oracle.actuate` in the 10 lines above any call site (currently one call site at `hvac.py:1227`).
2. Reviewer B produces an audit line naming this invariant in the plan-review sign-off: "`FanController.update` runs OUTSIDE `oracle.actuate`; per-write atomicity is provided by `set_manual_*_locked`, not by a wrapping actuate context."
3. If a future cycle proposes wrapping `update()`, that cycle must FIRST retire the `_locked` setter fleet to avoid double-lock deadlock — a plan-review-blocking condition.

**W1, W2, W3 wraps** at `automation.py:2159/2072/2234/2898` are INDEPENDENT (they call `_safe_service_call`, not the HVAC chokepoint).

**W10-pause / W10-restore** DO call `_set_fan_state` (at `:1451` and the restore branch). They route through the chokepoint wrap by passing `trigger_path=FAN_TRIGGER_RECHECK_PAUSE` / `FAN_TRIGGER_RECHECK_RESTORE` and `room_name=<name>` (see W10 rows §2.2).

Reviewer C mutation drill (rev-2 test carried forward): `test_w8_wrap_is_not_nested_inside_set_fan_state` — temporarily insert a `_set_fan_state` call inside W8 wrap body; run tests; confirm deadlock detected (timeout). Restore.

### 5.4 Lock scope — per-room; **all 15 hvac_fans writes classified**

Per v2 §7.9 the lock is per-room, owned by the oracle (`_room_locks` at `fan_policy_oracle.py:269-274`).

**New oracle async-locked setters** (added to `fan_policy_oracle.py`, ~40 LoC — includes symmetric `clear_manual_off_cooldown_locked` needed for #5):

```python
async def set_manual_on_hold_locked(self, room_key: str, value) -> None:
    async with self._get_lock(room_key):
        self.set_manual_on_hold(room_key, value)

async def set_manual_off_cooldown_locked(self, room_key: str, value) -> None:
    async with self._get_lock(room_key):
        self.set_manual_off_cooldown(room_key, value)

async def clear_manual_on_hold_locked(self, room_key: str) -> None:
    async with self._get_lock(room_key):
        self.clear_manual_on_hold(room_key)

async def clear_manual_off_cooldown_locked(self, room_key: str) -> None:
    async with self._get_lock(room_key):
        self.set_manual_off_cooldown(room_key, None)
```

**Sync-context concern.** All 15 sites fire from paths ultimately entered via `async def` methods on `FanController`. Sync-context writes (`_evaluate_temp_fan`, `_is_manual_on_hold_live`) are classified `local_only_ok` — their writes are idempotent malformed-cleanup / self-healing.

**All 15 write sites — classified with rationale:**

| # | Site | Enclosing method (sync/async) | What it writes | Classification | Rationale | Rewrite |
|---|---|---|---|---|---|---|
| 1 | `:221` | `turn_off_all_managed` (async) | cooldown ← `""` | **locked_setter_required** | Race with mid-URA-OFF; kill switch clearing cooldown post-consult would let a subsequent URA turn-ON emit against a room whose operator just killed everything. | `await oracle.clear_manual_off_cooldown_locked(_room_key(room_name))` |
| 2 | `:225` | same (async) | hold ← `""` | **locked_setter_required** | Same as #1 for hold. | `await oracle.clear_manual_on_hold_locked(_room_key(room_name))` |
| 3 | `:308` | `update` external-OFF adopt (async) | cooldown ← now+DEFAULT | **locked_setter_required** | **CANONICAL INV-FLA-T RACE SITE** (repro §1). | `await oracle.set_manual_off_cooldown_locked(_room_key(room_name), parsed_dt)` |
| 4 | `:312` | same (async) | hold ← `""` (external OFF clears live hold) | **locked_setter_required** | Freshest-human-wins; must serialize with URA turn-ON. | `await oracle.clear_manual_on_hold_locked(_room_key(room_name))` |
| 5 | `:325` | `update` external-reversal (async) | cooldown ← `""` | **locked_setter_required** | Sibling of #3; freshest-human-wins. | `await oracle.clear_manual_off_cooldown_locked(_room_key(room_name))` |
| 6 | `:335` | same (async) | hold ← now+ROOMHOLD | **locked_setter_required** | **CANONICAL INV-FLA-T** (opens hold mid-URA-OFF). | `await oracle.set_manual_on_hold_locked(_room_key(room_name), parsed_dt)` |
| 7 | `:339` | same (async) | hold ← `""` (kill-switch semantics: hold_s == 0) | **locked_setter_required** | Sibling of #6. | `await oracle.clear_manual_on_hold_locked(_room_key(room_name))` |
| 8 | `:411` | `update` adopt-fan branch (async) | hold ← now+ROOMHOLD | **locked_setter_required** | Same INV-FLA-T race as #6, different code branch. | same as #6 |
| 9 | `:415` | same (async) | hold ← `""` (adopt with hold_s == 0) | **locked_setter_required** | Sibling of #8. | same as #7 |
| 10 | `:651` | `_maybe_sleep_onset_activate` async wrapper (`_evaluate_temp_fan` sync branch context) | cooldown ← `""` (parse-error cleanup) | **local_only_ok** | Self-healing; clears a value already established as malformed. Race with fresh locked write from #3 is benign because the adopt-external re-fires next tick. | Keep descriptor write |
| 11 | `:847` | `_evaluate_temp_fan` (SYNC) | cooldown ← `""` (parse-error cleanup) | **local_only_ok** | Sync context — cannot await. Malformed-cleanup idempotent. | Keep descriptor write |
| 12 | `:849` | same (SYNC) | cooldown ← `""` (except branch) | **local_only_ok** | Same as #11. | Keep descriptor write |
| 13 | `:1081` | `_is_manual_on_hold_live` (SYNC) | hold ← `""`, paused_at ← `""` (malformed ISO) | **local_only_ok** | Sync helper; malformed-cleanup idempotent. | Keep descriptor write |
| 14 | `:1089` | same (SYNC) | hold ← `""`, paused_at ← `""` (natural expiry when `now >= until` AND not paused) | **local_only_ok (LOAD-BEARING READ-TIME EVALUATION PRESERVED — HIGH-2-round-2)** | See detailed rationale below. | **Keep the write in-place.** ALSO add `async_cleanup_expired_holds` as COSMETIC HYGIENE. |
| 15 | `:1477` | `restore_after_recheck` (ASYNC) | hold ← extended_iso (pause-context R-M-W) | **locked_setter_required + R-M-W atomic guard (MED-3-round-1)** | R-M-W across adopt interleave. | §5.4a wraps entire R-M-W in manually-acquired `oracle._get_lock`. |

**Row #14 detailed rationale (HIGH-2-round-2 — expiry evaluation stays load-bearing):**

> **READ-TIME EXPIRY EVALUATION AT `_is_manual_on_hold_live` (`hvac_fans.py:1076-1089`) AND THE COOLDOWN COMPARE AT `_evaluate_temp_fan` (`:842-844`) IS PRESERVED.** These read-time checks are LOAD-BEARING — they gate downstream URA behavior (W8 sweep skip, sleep-onset skip, temp-fan activation gate) at the moment the decision is made. The inline `room_fan.<field> = ""` write at `:1089` (and #10-#13 malformed cleanups) is a memoization side-effect: once we've computed that the value is expired/malformed, we clear it so the next read is cheap. Removing the read-time evaluation would violate the "freshest state observed at decision time" contract these gates depend on.
>
> **`async_cleanup_expired_holds` is COSMETIC HYGIENE ONLY.** Its role: sweep expired holds/cooldowns off rooms whose read paths haven't fired in a while (e.g. a room that hasn't been evaluated this tick because its zone had no sweep event). Without it, an expired hold sits in the ledger dict indefinitely until the room's next read fires; with it, the ledger stays tidy. The functional behavior is IDENTICAL whether the helper runs or not — the read-time check at `:1076-1089` and `:842-844` produces the same verdict either way.

**`async_cleanup_expired_holds` scheduling (HIGH-2-round-2):** call it **INLINE from `FanController.update`** at the top of the per-room loop (`hvac_fans.py:~279`), gated by a cheap "> 60s since last cleanup" throttle to keep the tick cost low. No new listener, no `async_track_time_interval`, no cancellation contract. Rationale: `FanController.update` runs on the HVAC decision cadence (~5 min) so cleanup runs on the same cadence — matches the "cosmetic hygiene" role. If we instead wanted a separate scheduled task, we'd need to capture the interval handle and cancel it in `async_will_remove_from_hass` (HA lifecycle contract), which is machinery the cosmetic-only role does not justify.

```python
# hvac_fans.py — inside FanController.update, before the per-room loop
if self._last_cleanup_at is None or (now - self._last_cleanup_at).total_seconds() > 60:
    self._last_cleanup_at = now
    oracle = _get_fan_oracle(self.hass)
    if oracle is not None:
        await oracle.async_cleanup_expired_holds()
```

```python
# fan_policy_oracle.py
async def async_cleanup_expired_holds(self) -> None:
    """Cosmetic hygiene: drop expired manual_on_hold_until and
    manual_off_cooldown_until entries from the ledger. NOT load-bearing —
    read-time evaluation at hvac_fans.py:1076-1089 and :842-844 remains
    the authoritative expiry gate. See PLANNING §5.4 row #14.
    """
    now = _ha_dt.now() if _ha_dt is not None else datetime.now()
    for room_key in list(self._rooms.keys()):
        async with self._get_lock(room_key):
            rec = self._rooms.get(room_key)
            if rec is None:
                continue
            if rec.manual_on_hold_until is not None and now >= rec.manual_on_hold_until:
                rec.manual_on_hold_until = None
            if rec.manual_off_cooldown_until is not None and now >= rec.manual_off_cooldown_until:
                rec.manual_off_cooldown_until = None
```

**Summary counts:** locked_setter_required = 9 (#1-#9); local_only_ok = 5 (#10-#13, #14); locked R-M-W atomic-guard = 1 (#15). Total = 15.

**Tests:**
- `test_external_on_racing_ura_off_is_blocked_hvac_tier` — canonical INV-FLA-T at #6.
- `test_kill_switch_races_ura_off_serializes` — #1/#2.
- `test_read_time_expiry_evaluation_preserved` — assert `_is_manual_on_hold_live` still returns False for an expired hold WITHOUT relying on `async_cleanup_expired_holds` having run (fixture: hold live, tick past expiry, call `_is_manual_on_hold_live` directly, assert False + local slot cleared).
- `test_async_cleanup_expired_holds_is_cosmetic_only` — populate an expired hold in the oracle ledger; do NOT call cleanup; assert `oracle.get_state(room).manual_on_hold_until` still returns the stale datetime (proves cleanup is cosmetic; reader responsibility to compare against `now`).
- `test_async_cleanup_expired_holds_scheduled_inline_from_update` — verify `FanController.update` calls `async_cleanup_expired_holds` when the 60s throttle elapses.
- `test_pause_extension_atomic_vs_adopt_external` — MED-3 at #15.

### 5.4a Pause-context atomicity at :1477

`restore_after_recheck` R-M-W wrapped in manually-acquired per-room lock (asyncio.Lock non-reentrant — call sync `set_manual_on_hold`, NOT `_locked` variant, inside the lock):

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
                oracle.set_manual_on_hold(_room_key(room_name), new_until)
                _LOGGER.info(...)
    room_fan.manual_on_hold_paused_at = ""
```

### 5.5 Reverse-adjacency scanner — AST rules + synthetic-violation fixture (MED-4-round-1)

Five AST rules documented in scanner header: (1) direct fan domain, (2) `startswith("fan.")` branch, (3) `_set_fan_state` param-taint via hard-coded chokepoint allowlist, (4) enclosing `oracle.actuate` context, (5) `# fan-adjacency: allow (reason=...)` carve-out comment.

Synthetic-violation fixture directory `quality/tests/fixtures/fan_adjacency_synthetic/` (5 files): `violation_direct_fan_domain.py`, `violation_startswith_fan_branch.py`, `violation_set_fan_state_taint.py`, `violation_carveout_missing_reason.py`, `allow_carveout_valid.py`. Test `test_fan_adjacency_reverse_scan_flags_synthetic_violations` iterates each.

### 5.6 note_actuation dedup + same-trigger re-fire (LOW-1-round-1)

Dedup key at `fan_policy_oracle.py:547`: `edge_key = (trigger_path, rec.hold_id)`. `hold_id` bumps on external ON (`:541`). Behavior enumerated in rev-2 §5.6 with 3 regression tests.

### 5.7 Snapshot builders

`_build_fan_snapshot_room(entities, observed_any_on)` on `RoomAutomation` (`sleep_axis="room_window"`); `_build_fan_snapshot_hvac(room_name, entities, observed_any_on)` on `FanController` (`sleep_axis="house_state"`). See rev-2 §5.7 for full code.

---

## 6. Numbers get knobs

No new numbers.

---

## 7. Scope pushback — marginal-benefit decomposition (unchanged)

Six items all LAND per rev-2 §7 analysis.

---

## 8. Estimated cycle size + overrun trigger (LOW-3-round-1)

- **Diff:** ~700 LoC add / ~200 del. Breakdown per rev-2 §8.
- **Tests:** ~24 new tests (rev-2 tally + read-time-expiry-preserved + cleanup-cosmetic + cleanup-scheduled + normalization tests).
- **Sessions:** ONE staged session; two commits (D1 + D2) on one branch.
- **Reviewers:** 3 (Tier 2-DB A/B/C).
- **Underrun trigger:** < ~550 LoC OR < ~20 tests → audit for dropped scope.
- **OVERRUN trigger:** > ~900 LoC OR > ~30 tests → split D2a/D2b.

---

## 9. Parity gates (must stay green, unmodified)

Same as rev-2 §9. **HIGH-1-round-2 explicit anchor:** the following test-suite constructors of `RoomFanState` MUST work byte-identical against the rev-3 __init__ signature (no arg addition needed):

- `quality/tests/test_fan_manual_on_hold_hvac_tier.py:256`
- `quality/tests/test_v4713_...py:611` (exact filename per operator note)
- `quality/tests/test_hvac_fan_control.py:172`
- `quality/tests/test_fan_incident_replay.py:404`
- `quality/tests/test_comfort_fan_away_veto.py:402`
- `quality/tests/test_fan_trust_state.py:247`
- `quality/tests/test_fan_sweep_trio.py:262`
- `quality/tests/test_sleep_fans_and_flash.py:368, :829, :970`

Build must run the full suite; any TypeError at these constructors is a rev-3 build BLOCKER.

---

## 10. Deliverables

### D1 — Structural + delegation groundwork

**Files:** `hvac_fans.py` (~350/~80), `automation.py` (~20/~5 for `_fan_ledger_key`), `fan_policy_oracle.py` (~50 for locked setters + `async_cleanup_expired_holds` + optional `_migrate_legacy_entry_keys`), `presence_fan_recheck.py` (~20/~30 reader migration).

**Verify:**
- 46-line grep unchanged in shape.
- `@dataclass` removed; explicit `__init__` with **backward-compat kw-only signature per §5.1**; all 10 §9 constructors work unmodified (run those specific tests first as smoke).
- `_fan_ledger_key()` returns `room:{normalize(name)}` first.
- `_room_key` normalizes NFC + trims + rejects control chars + logs colon.
- **Uniqueness gate PYTEST NAME: `test_room_name_uniqueness_gate` in `quality/tests/test_fan_layer_2_uniqueness_gate.py`** (LOW-1-round-2 — single source of truth for the gate; reconciles §10-D1 and §11-Risk-1). Reads committed fixture `quality/tests/fixtures/config_entries_snapshot.json` (updated pre-cycle by orchestrator via `ha-mcp` or SSH dump). Asserts across ENTRY_TYPE_ROOM entries: non-empty CONF_ROOM_NAME, `_room_key(name)` non-raising, unique `_room_key(name)`. **This pytest is the build gate** — build dispatch blocks on its failure.
- 9 sites converted to `_locked` async setters; §5.4a R-M-W wrap uses manual `async with oracle._get_lock(...)` with sync setter inside.
- **`_is_manual_on_hold_live` READ-TIME EXPIRY EVALUATION IS PRESERVED**; only the tidy-up moves to `async_cleanup_expired_holds`.
- Presence reader `_fan_in_manual_cooldown` migrated.
- `FanController.update` remains UNWRAPPED by `oracle.actuate` (MED-1-round-2 verification: `git grep -B 10 'await self\._fan_controller\.update('` returns no `oracle.actuate` in the 10 lines above).

**Tests:** all tests from rev-2 §D1 PLUS:
- `test_room_key_normalizes_nfc_vs_nfd`, `test_room_key_rejects_control_chars`, `test_room_key_logs_colon_in_name`.
- `test_read_time_expiry_evaluation_preserved`.
- `test_async_cleanup_expired_holds_is_cosmetic_only`.
- `test_async_cleanup_expired_holds_scheduled_inline_from_update`.
- `test_room_name_uniqueness_gate` (the build blocker itself).
- `test_room_fan_state_backward_compat_signature` — instantiate `RoomFanState` with each of the 10 §9 parity-gate constructor shapes; assert no TypeError.

### D2 — Six wraps + snapshot helpers + R-M-W atomic wrap + reverse-scanner + synthetic fixtures

Same as rev-2 §D2. Test additions unchanged.

### D5 — Doc write-back

`docs/Coordinator/HVAC.md`: HVAC-tier delegation, `_room_key` unification + normalization + build-gate pytest name, INV-FLA-T + INV-DTA, `§5.4` locked-setter fleet + read-time-expiry-preserved contract + `async_cleanup_expired_holds` cosmetic-only role, `FanController.update` intentionally-unwrapped invariant, reverse-scanner + synthetic fixture. Post-live-validation README write-back.

---

## 11. Sharpest risk

**Risk 1 — Uniqueness gate mechanism.** (LOW-1-round-2 reconciled with §10-D1.) SINGLE MECHANISM: pytest `test_room_name_uniqueness_gate` in `quality/tests/test_fan_layer_2_uniqueness_gate.py` reading committed snapshot `quality/tests/fixtures/config_entries_snapshot.json`. Snapshot refresh discipline: orchestrator dumps live config-entries into the fixture immediately before build dispatch (via `ha-mcp` MCP tool OR SSH `cat /config/.storage/core.config_entries`). Staleness bounded by cycle latency; any live CONF_ROOM_NAME change within that window is surfaced by the first post-deploy live-validation check. NO parallel/duplicate gate mechanism — §11 and §10-D1 reference the same pytest by name.

**Risk 2 — Sync-context write races (§5.4 sites #10-#13).** Race benignity relies on adopt-external re-fire clearing transient inconsistency. Because #14's expiry-clear is PRESERVED at read-time (HIGH-2-round-2), the highest-frequency clash site remains — but the clash mode is the same: a fresh locked write from #6 followed by an inline sync clear at #14/#1089 clobbers the fresh hold. Mitigation: the clobber at read-time is masked at the emit gate (W8/W9 wrap's consult re-reads under lock and DEFERs against the fresh hold, which is what INV-FLA-T requires). Reviewer B asserts sites #10-#13 have INFO-level log lines wired.

**Risk 3 — Reverse-scanner parameter-taint gap.** A future writer using arbitrary helper hops may evade. Documented in scanner header; shape-(a) promotion trigger from v2 §6.5 applies.

---

## 12. Open questions for operator (unchanged from rev-2 §12 except LOW-1 resolved)

1. **`async_cleanup_expired_holds` cadence** — inline throttled at 60s from `FanController.update` (§5.4). Confirm.
2. **Optional `_migrate_legacy_entry_keys()` cleanup** — 5 LoC. Confirm include.
3. **Tier 2-DB vs Tier 3 code review** — recommend Tier 2-DB. Confirm.

(Uniqueness gate snapshot vs. live is RESOLVED in §11 Risk 1 — committed-snapshot pytest is the single mechanism.)

---

## 13. Plan completion tracking (open items to reconcile at close)

- Any of the six wraps skipped → INV-FLA-T half-proven; card FAN-LAYER-3.
- Reverse-adjacency scanner not landed → completeness half open; card FAN-LAYER-3.
- Any §5.4 site not converted per its classification → note in README write-back.
- Uniqueness gate blocked build → resolve collision before re-dispatch.
- `docs/Coordinator/HVAC.md` write-back (D5) — must land pre-close.
- README `Validated <date>` table populated post-live-validation.

---

## 14. Plan-review record

### Round 1 (2026-08-11, framing = completeness) — NEEDS-REVISION

Full disposition table in rev-2 §14. All 10 findings adopted.

### Round 2 (2026-08-11, framing = adversarial build-prediction) — NEEDS-REVISION, 6 targeted edits

| # | Sev | Finding | Disposition in rev-3 |
|---|---|---|---|
| HIGH-1 | HIGH | §5.1 `__init__` signature `(room_name, zone_id, *, hass, room_type, fan_entities)` TypeErrors ~10 existing test constructors (including §9 parity gates: `test_fan_manual_on_hold_hvac_tier.py:256`, `test_v4713...:611`, `test_hvac_fan_control.py:172`, `test_fan_incident_replay:404`, `comfort_fan_away_veto:402`, `fan_trust_state:247`, `fan_sweep_trio:262`, `sleep_fans_and_flash:368/829/970`). Signature must accept EVERY current @dataclass field as kw-only optional with today's defaults. | ADOPTED — §5.1 rewritten with a full kw-only-optional signature covering all 13 current fields (`hass`, `room_type`, `fan_entities`, `is_on`, `speed_pct`, `trigger`, `last_on_time`, `vacancy_detected_time`, `manual_off_cooldown_until`, `manual_on_hold_until`, `manual_on_hold_paused_at`, `fan_recheck_suppress_until`, `fan_sleep_policy`), each with today's default. §9 gains an explicit HIGH-1-round-2 anchor listing the 10 constructors that must work byte-identical. New test `test_room_fan_state_backward_compat_signature` in D1. |
| LOW-2 | LOW (embedded in HIGH-1) | Delete the "add `hass=mock_hass` to every direct constructor" instruction — it contradicts §9 (parity gates must not be modified) and is unnecessary because the `_hass=None` fallback in `_OracleISOField.__get__`/`__set__` covers it. | ADOPTED — §5.1 sentence "Fixture constructions in tests do the same (add `hass=mock_hass` to every direct constructor)" REMOVED. Replaced with an explicit paragraph explaining that existing tests need no changes because the fallback path is fully covered. |
| HIGH-2 | HIGH | §5.4 row #14: (a) spec `async_cleanup_expired_holds` scheduling explicitly — recommend INLINE from `FanController.update` (no new listener, no cancellation contract); if `async_track_time_interval` is picked instead, spec handle capture + unload cancellation. (b) Declare in bold that READ-TIME expiry evaluation at `_is_manual_on_hold_live` (`hvac_fans.py:1076-1089`) AND the cooldown compare (`:842-844`) IS PRESERVED; cleanup is cosmetic hygiene only, never load-bearing. | ADOPTED — §5.4 row #14 rewritten. Row-14 classification stays `local_only_ok` (write kept in-place, load-bearing at read-time). Bold declaration added: **READ-TIME EXPIRY EVALUATION AT `:1076-1089` AND `:842-844` IS PRESERVED. `async_cleanup_expired_holds` IS COSMETIC HYGIENE ONLY.** Scheduling: inline from `FanController.update` with 60s throttle (no listener, no cancellation contract). Full helper code shown. Two new tests: `test_read_time_expiry_evaluation_preserved`, `test_async_cleanup_expired_holds_is_cosmetic_only`, `test_async_cleanup_expired_holds_scheduled_inline_from_update`. §3 non-goal added. §2.4 "REUSED" note added preserving `_is_manual_on_hold_live` read-time behavior. |
| MED-1 | MED | §5.3 add: `FanController.update` is intentionally OUTSIDE any actuate wrap (verified: sites #3/#6 fire from `hvac.py:1227` with no wrap up-stack) + a Reviewer-B verification item that no future wrap encloses it. | ADOPTED — §5.3 gains an explicit block: "`FanController.update` is intentionally OUTSIDE any `oracle.actuate` wrap" with the `hvac.py:1227` evidence, the rationale (cross-room iteration + per-write atomicity via `_locked` setters + deadlock-with-`_locked`-reentry), and a Reviewer-B audit line naming the invariant. §5.4 framing B updated to include the audit item. |
| MED-2 | MED | Uniqueness gate + `_room_key`: apply `unicodedata.normalize("NFC", name).strip()` before keying/comparing; reject control chars; note colon-in-name is legal but logged. | ADOPTED — §5.1 `_room_key` code updated with `unicodedata.normalize("NFC", ...).strip()`, control-char rejection (raises ValueError, surfaced via uniqueness gate), colon-legal-but-logged. §5.2 normalization paragraph added. New tests: `test_room_key_normalizes_nfc_vs_nfd`, `test_room_key_rejects_control_chars`, `test_room_key_logs_colon_in_name`. |
| LOW-1 | LOW | Reconcile §10-D1 vs §11-Risk-1: pick the committed-snapshot fixture mechanism, name the pytest. | ADOPTED — SINGLE mechanism, named: `test_room_name_uniqueness_gate` in `quality/tests/test_fan_layer_2_uniqueness_gate.py` reading committed snapshot `quality/tests/fixtures/config_entries_snapshot.json`. §10-D1 and §11-Risk-1 both reference the same pytest by name; §12 open question about "snapshot vs live" is removed (resolved). |

Coordinator has stated that if rev-3 addresses all round-2 items with no new material, they will declare PLAN-READY on their own verification — no third review round unless rev-3 introduces new material. Rev-3 introduces no new material beyond the six targeted edits.
