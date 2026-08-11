# PLANNING — FAN-LAYER-2: RoomFanState HVAC-tier delegation + oracle.actuate wrap-out

**Card:** FAN-LAYER-2 (deferred scope from FAN-LAYER-1 v5.70.0)
**Author:** ura-planner (opus)
**Date:** 2026-08-11
**Base branch:** `develop` at v5.70.0 (post-merge of FAN-LAYER-1 Sessions 1–3 + fix-up)
**Supersedes:** none — a direct continuation of `docs/planning/PLANNING_fan_actuation_shared_layer_v2.md` §7.9 (INV-FLA-T lock), §7.10 (field-delegation decision), §11 (reader-parity risk) and of the FAN-LAYER-1 review record's deferred-carded scope (`docs/reviews/code-review/v5.70.0_fan_layer_1.md`).

---

## 1. Falsifiable invariants (Reviewer D targets, up front)

Two invariants; both must hold at cycle close.

> **INV-FLA-T (temporal fan-layer authority, from v2 §7.9).** For any room `r`, if `manual_on_hold_until` becomes live at time `T` (via external-ON adopt), NO URA-issued fan OFF against `r` may reach `hass.services.async_call` return at any `T' > T` until the hold expires or is explicitly discharged (external-OFF, kill switch, safety-stop). Equivalent operational restatement: every URA-emitting site listed in §3.2 (W1, W2, W3, W8, W9, W10-pause, W10-restore) executes the `consult → services.async_call → note_actuation` sequence INSIDE an `oracle.actuate(room, trigger, snapshot, direction)` async-with block that holds the per-room `asyncio.Lock` across all three steps.
>
> **Concrete legal-config repro to break INV-FLA-T if the lock is missing:** room A has a live `may_turn_off(TEMP_ROOM)` consult that ALLOWed at T0; between T0 and the `await services.async_call` return, an external-ON dispatch fires on room A's fan `state_changed` bus → `RoomFanState` adopt-external path opens `manual_on_hold_until` at T1; the URA OFF completes at T2. Post-condition: the fan is OFF and the ledger says hold is live — a state the invariant forbids because the emitting caller cannot legitimately claim consult authority once the hold opened. The lock closes this window by forcing the adopt-side setter to serialize behind the URA-side critical section (see §5.4).

> **INV-DTA (dual-tier agreement, from FAN-LAYER-1 B-MED-3 residual).** For any room `r` served by BOTH the room-tier surface (`RoomAutomation` in `automation.py`) AND the HVAC-tier surface (`RoomFanState` in `hvac_fans.py`), a call to `oracle.get_state(r).manual_on_hold_until` returns the SAME datetime regardless of which tier last wrote (or which tier is asking). Equivalently: `RoomFanState.manual_on_hold_until` and `RoomFanState.manual_off_cooldown_until` are NOT independent state — they are read-through views of the oracle ledger keyed by the same string the room-tier uses.
>
> **Concrete legal-config repro to break INV-DTA if HVAC-tier stays local:** HVAC-tier zone-vacancy sweep (W8) detects external-ON on room A's fan at T0 and writes `RoomFanState.manual_on_hold_until = <T0+3600>`. Simultaneously the room-tier `may_turn_off(TEMP_ROOM)` consult in `automation.py:1801` runs against the oracle ledger, which is EMPTY for that field on the room-tier side, and returns ALLOW. OFF emits — invariant broken. This is the exact "non-safety `may_turn_off` consult for an HVAC-tier room misses that tier's hold" residual noted in the v5.70.0 review record.

Reviewer D's mandate: enumerate the ENTIRE fan-emission surface AND the ENTIRE `RoomFanState` field write surface (per §2), and mutate one site at a time to prove BOTH invariants. Include pre-existing code, not just the diff.

---

## 2. Institutional context verified

### 2.1 Field-access count — hypothesis "~34" was low; actual **46 lines**

`git grep -n 'manual_off_cooldown_until\|manual_on_hold_until' custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` on develop tip returns **46 lines** (not the ~34 hypothesized in the task brief). Classified against the v2 §11 template:

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

- **Real reads (must migrate to `oracle.get_state(r).<field>` via descriptor):** 356 (guard), 638, 641, 842, 844, 1076, 1079, 1469, 1474, 1588, 1589, 1597, 1600. Also `presence_fan_recheck.py:1002, 1007`. **Total = 15 reads.**
- **Real writes (must migrate to `oracle.set_manual_*` via descriptor):** 221, 225, 308, 312, 325, 335, 339, 411, 415, 651, 847, 849, 1081, 1089, 1477. **Total = 15 writes.**
- **Log / comment / docstring:** the remaining ~16 lines. Rewritten to reference the ledger by name; no behavior impact.

`presence_fan_recheck.py`: 3 hits (`:410` comment, `:1002` guard READ, `:1007` parse READ) — 2 real readers.

**Presence-fan-recheck reader classification (task item 2).** `_fan_in_manual_cooldown(room_name)` at `presence_fan_recheck.py:992-1014` is the ONLY reader; it reaches through `hass.data → coordinator_manager → hvac.fan_controller._room_fans[room_name]` to peek the ISO string, parses via `dt_util.parse_datetime`, and returns `dt_util.now() < until`. This reach-through is exactly the "private-field peek" v2 §11 flagged. Migration: **replace with** `oracle = _get_fan_oracle(self.hass); until = oracle.get_state(room_name).manual_off_cooldown_until if oracle else None; return until is not None and dt_util.now() < until`. **Note:** the room-tier `_fan_ledger_key()` currently uses config entry_id (post A-HIGH-1 fix); the HVAC-tier keys by `room_name` in `_room_fans`. §5.2 resolves the key-space collision.

### 2.2 Emitter enumeration — the 6 unwrapped writers (task item 3)

Post-v5.70.0 (Sessions 1–3 shipped), only W11 (`hvac.py:2654` `_stop_all_fans_safety_one`) and W12 (`hvac_predict.py:1164` `_activate_zone_fans`) are wrapped in `oracle.actuate`. Confirmed by `git grep 'oracle\.actuate'` returning exactly those two async-with sites plus plan-doc / test / audit references.

Six writers remain unwrapped:

| # | Site | File:line (current tip) | Direction | Current gate | Wrap target |
|---|---|---|---|---|---|
| W1 | Room-tier comfort revert | `automation.py:1801-1809` | OFF | `_fan_manual_on_until` @property (oracle-backed, Session 2) | `oracle.actuate(room, FAN_TRIGGER_TEMP_ROOM, snap, "off")` |
| W2 | Room-tier `FAN_SLEEP_OFF` | `automation.py:1729-1736` | OFF | same | `oracle.actuate(room, FAN_TRIGGER_SLEEP_OFF, snap, "off")` |
| W3 | Room-tier turn-ON (temp / sleep-onset) | `automation.py:2065-2083, ~1870, ~2148, 2727` | ON | `mark_fan_on_issued` seed (oracle.note_actuation edge, Session 2) | `oracle.actuate(room, FAN_TRIGGER_TEMP_ROOM_ON \| FAN_TRIGGER_SLEEP_ONSET_ON, snap, "on")` |
| W4-chokepoint | HVAC `_set_fan_state` service-call block | `hvac_fans.py:1231-1258` | ON + OFF | reads local ISO strings | `oracle.actuate(room_name, trigger, snap, direction)` around lines 1231-1258; trigger propagated from callers via new kw-only arg |
| W8 | HVAC zone-vacancy sweep | `hvac.py:2419-2430` (v2 line refs; re-verify at build) | OFF | **NONE — bypasses oracle** | `oracle.actuate(room, FAN_TRIGGER_HVAC_VACANCY, snap, "off")` |
| W9 | HVAC pre-arrival deactivation | `hvac.py:2629-2643` | OFF | **NONE — bypasses oracle** | `oracle.actuate(room, FAN_TRIGGER_HVAC_PREARRIVAL, snap, "off")` |
| W10-pause | Presence-fan-recheck pause OFF | `presence_fan_recheck.py:~582` → `fan_controller.pause_for_recheck` in `hvac_fans.py` | OFF | none at emit | `oracle.actuate(room, FAN_TRIGGER_RECHECK_PAUSE, snap, "off")` at the emit site inside `hvac_fans.py` |
| W10-restore | Presence-fan-recheck restore ON | `hvac_fans.py:~1069-1090` restore path | ON | none | `oracle.actuate(room, FAN_TRIGGER_RECHECK_RESTORE, snap, "on")` |

**Per-site verdict table (task item — "per-site verdict table for all 6 unwrapped writers"):**

| Site | Verdict this cycle | Wrap owner | Snapshot builder | Trigger constant | Test-name |
|---|---|---|---|---|---|
| W1 | WRAP | `RoomAutomation.handle_temperature_based_fan_control` | `_build_fan_snapshot_room` | `FAN_TRIGGER_TEMP_ROOM` (existing) | `test_w1_room_revert_wrapped_in_oracle_actuate` |
| W2 | WRAP | same handler, sleep branch | same helper | `FAN_TRIGGER_SLEEP_OFF` (existing) | `test_w2_sleep_off_wrapped_in_oracle_actuate` |
| W3 | WRAP | same handler + sleep-onset ON site | same helper | `FAN_TRIGGER_TEMP_ROOM_ON` / `FAN_TRIGGER_SLEEP_ONSET_ON` (existing) | `test_w3_room_on_wrapped_in_oracle_actuate` (parity: `mark_fan_on_issued` still fires idempotently) |
| W4-chokepoint | WRAP `_set_fan_state` service-call block (lines 1231-1258 only, NOT the entire method) | `FanController._set_fan_state` | `_build_fan_snapshot_hvac` | trigger propagated via new `trigger_path` kw-only arg on `_set_fan_state` (default = `FAN_TRIGGER_TEMP_HVAC` for existing HVAC-vacancy caller) | `test_w4_set_fan_state_wrapped_and_propagates_trigger` |
| W8 | WRAP (verify at build whether callsite goes through `_set_fan_state`; v2 asserts it currently bypasses) | `hvac.py` zone-vacancy sweep function | `_build_fan_snapshot_hvac` via `FanController` helper (since W8 lives outside `FanController`) | `FAN_TRIGGER_HVAC_VACANCY` (existing) | `test_w8_zone_vacancy_sweep_wrapped` — **BEHAVIOR CHANGE preserved:** the v5.70.0 §5 intentional behavior change (W8 now honors cooldown + hold) MUST STILL apply; a mutation that removes the wrap must fail `test_hvac_zone_vacancy_sweep_respects_manual_on_hold` (FAN-LAYER-1 D6 parity test) |
| W9 | WRAP | `hvac.py` pre-arrival function | same helper | `FAN_TRIGGER_HVAC_PREARRIVAL` (existing) | `test_w9_prearrival_off_wrapped` — parity: `test_hvac_prearrival_respects_manual_off_cooldown` remains green |
| W10-pause | WRAP | `FanController.pause_for_recheck` at the emit site | `_build_fan_snapshot_hvac` | `FAN_TRIGGER_RECHECK_PAUSE` (existing) | `test_w10_pause_wrapped_preserves_pause_context` |
| W10-restore | WRAP | `FanController.restore_after_recheck` at the emit site | `_build_fan_snapshot_hvac` | `FAN_TRIGGER_RECHECK_RESTORE` (existing) | `test_w10_restore_wrapped_credits_paused_duration` |

**None of these writers change POLICY.** The wrap is a critical-section discipline change (INV-FLA-T) plus an emission-path change (goes through `oracle.actuate`, which fires `note_actuation` on exit rather than the caller emitting it separately). Existing consults (Session 2 `is_fan_in_manual_on_hold` peek at W1/W2, `mark_fan_on_issued` seed at W3, W7 reconciler consult) collapse into the wrap.

### 2.3 Restart / reload semantics — VERIFIED

`RoomFanState` is a `@dataclass` on `FanController` (`hvac_fans.py:67-108`) — **NOT persisted**. Explicit RAM-only comment at line 92: "RAM-only (matches manual_off_cooldown_until — no persistence)." `git grep -E 'RestoreEntity|Store\(|async_save|restore_state|save_state' hvac_fans.py` returns nothing. The dataclass is re-initialized on `discover_fans()` (line 157 `self._room_fans.clear()`), which runs on `FanController.__init__` and on any re-discovery call.

**Comparison to `EVSEState` (task-mentioned "EVSE-state-style blob"):** `EVSEState` uses `homeassistant.helpers.storage.Store` for JSON blob persistence. `RoomFanState` does **not** — it is pure RAM. There is NO save/restore blob to migrate.

**Restart behavior post-migration (invariant preserved):** on boot, the oracle is constructed (`CoordinatorManager` __init__ — Session 2 pattern), `FanController.discover_fans()` clears `_room_fans`, first HVAC tick observes `is_on` state → adopt-external paths at `hvac_fans.py:308-339` fire their oracle writes via the new descriptor, ledger re-populates. **No new persistence added, no lifecycle change vs. today.**

**Reload discipline (B-HIGH-2 lesson from FAN-LAYER-1):** `CoordinatorManager` reload must REUSE the existing `hass.data[DOMAIN]["fan_oracle"]`. A fresh oracle on reload would drop HVAC-tier holds the same way it dropped room-tier holds pre-B-HIGH-2 fix. Reviewer B verifies at build that the reuse still holds after §5 wiring lands (it should — no touch to `CoordinatorManager` singleton lifecycle in this cycle).

**RoomFanState hydration parity note (B-HIGH-1 sister case) — LOAD-BEARING.** The Session-2 room-tier @property `_fan_manual_on_until` includes a **hydrate-on-read** step: if `oracle_val is None and local is not None`, it seeds the oracle from local and returns local (`automation.py:293-296`). The HVAC-tier delegation MUST include the symmetric step, because `RoomFanState.manual_on_hold_until` can be non-empty (from the current codepath's adopt-external writes) at the exact instant the oracle-backed delegation ships and the oracle has never seen that room. Without hydrate-on-read the first read post-deploy returns "" and every live HVAC hold is atomically dropped. **§5.1 spec covers it explicitly; D1 test `test_hvac_tier_hydrate_on_read_seeds_oracle` anchors it.**

### 2.4 Greps — REUSED vs NEW

Every entity in the plan is REUSED:

- `FAN_TRIGGER_*` closed enum — REUSED at `const.py` (FAN-LAYER-1 D2). Imported at `fan_policy_oracle.py:85-93`.
- `FanDecisionSnapshot` — REUSED at `fan_policy_oracle.py:142-156`.
- `oracle.actuate` async-context helper — REUSED (referenced from `hvac.py:2654`, `hvac_predict.py:1164`).
- `oracle.set_manual_off_cooldown` / `oracle.set_manual_on_hold` / `oracle.clear_manual_on_hold` — REUSED at `fan_policy_oracle.py:234-267`.
- `oracle.get_state(room).<field>` — REUSED (already the room-tier @property backing).
- `_get_fan_oracle(hass)` accessor — REUSED at `automation.py` (Session 2).
- `_fan_ledger_key()` — REUSED at `automation.py` (post A-HIGH-1); AMENDED per §5.2 to prefer `room_name` when present.

NEW:

- `_build_fan_snapshot_room(self, entities, observed_any_on)` on `RoomAutomation` and `_build_fan_snapshot_hvac(self, room_name, entities, observed_any_on)` on `FanController`. **NEW because** every wrap needs a `FanDecisionSnapshot` (v2 §7.8 required-positional, no default) built from tier-specific state; the room-tier reads its `_house_state_manager` + per-room sleep window and computes `sleep_axis="room_window"`, the HVAC-tier reads `FanController._house_state` and computes `sleep_axis="house_state"`. The axis-mismatch VETO at `fan_policy_oracle.py` §7.4a REQUIRES the caller supply the correct axis, so a shared helper cannot exist. Two helpers avoid a 7-line inline snapshot at every wrap site.
- `_OracleISOField` descriptor class on `RoomFanState` — **NEW because** no equivalent exists; the room-tier @property lives on `RoomAutomation` (which has hass access via self.hass) and cannot be reused for a dataclass whose instances don't hold hass. The descriptor walks a controller back-reference to find hass. §5.1 spec.
- Reverse-adjacency AST pass on `quality/tools/audit_fan_adjacency.py` — **NEW logic in an EXISTING file**. Forward walker (shipped): every `oracle.may_*` / `oracle.actuate` site is followed by a service call. Reverse walker (NEW): every `services.async_call` whose domain is fan-related AND whose call site is inside a function iterating `CONF_FANS` / `fan_entities` is preceded by an `oracle.actuate` context. Justification: forward proves consults reach an emit; it does NOT prove every emit was preceded by a consult. The reverse pass is the completeness half; without it, a future writer emitting without consulting goes unflagged. **NEW because no equivalent tooling exists.**

### 2.5 Prior planning docs consulted

- `PLANNING_fan_actuation_shared_layer_v2.md` — read end-to-end; §1, §7.4 (writer verdict table), §7.7 (lifecycle), §7.8 (FanDecisionSnapshot), §7.9 (INV-FLA-T + lock), §7.10 (field-delegation shape), §7.11 (exception posture), §7.13 (PauseContext), §7.14 (edges-only note_actuation), §11 (reader-parity risk) are the parent spec. This plan defers to it wherever silent.
- `docs/reviews/code-review/v5.70.0_fan_layer_1.md` — read end-to-end. Bug classes to defend against: **Hollow anchor #13** (source-presence tests), **Lifecycle-recreation state loss** (B-HIGH-2 CM reload + B-HIGH-1 boot-race hydration), **Silent anchor loss** (collection ERROR = disabled test). Applied throughout: §5.1 hydrate-on-read for HVAC tier, no collection ERRORs allowed, all D-tests behavioral (drive real methods, no source-presence).
- `PLANNING_fan_manual_on_override.md` (FAN-MANUAL-1) — skim; the manual-ON hold semantics (option A: policy triggers subordinate to hold; safety and kill switch superset) are unchanged.

### 2.6 Memory bodies pulled

- `feedback_hollow_test_anchors.md` — per-site source mutation via VALUE detachment (comment out the wrap, keep the source string) is the required drill; §D2 drill list is the 6 unwrapped sites in §2.2.
- `feedback_suppression_needs_discharge.md` — the lock acquisition serializes but does not suppress; discharge = context exit. No new suppression path added.
- `feedback_no_fabrication.md` — every line count above is grep-cited; every wrap target is file:line-cited; the "EVSE-state-style blob" hypothesis was VERIFIED and rejected in §2.3.
- `feedback_mutation_verification_pycache_staleness.md` — Reviewer C drill disables bytecode caching.
- `feedback_marginal_benefit_pushback.md` — see §7 "Scope pushback".
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — the note_actuation edges-only budget (v2 §7.14) covers the 6 new wrap sites without exceeding the < 200 rows/hour budget; §D2 test asserts it.

### 2.7 Design docs read

`docs/Coordinator/HVAC.md` — v2 D9 write-back owed post-deploy of FAN-LAYER-1; if not yet updated at build dispatch time, D5 of THIS plan absorbs it.

### 2.8 Code locations surveyed end-to-end

- `hvac_fans.py:1-500` and `:1050-1600` (RoomFanState decl, adopt paths, restore_after_recheck, pause context, diagnostic filter).
- `hvac_fans.py:1231-1268` (`_set_fan_state` service-call block — the W4 chokepoint).
- `fan_policy_oracle.py:1-560` (module header, RoomFanLedger, _RoomRecord, `set_manual_*`, `get_state`, `actuate` async-context, exception posture, edges-only note_actuation).
- `automation.py:280-395, 520-560` (@property delegations, `mark_fan_on_issued` oracle edge, `_fan_ledger_key`).
- `presence_fan_recheck.py:990-1020` (`_fan_in_manual_cooldown` reach-through).
- `hvac.py:2570-2700` (W11 `_stop_all_fans_safety` + `_stop_all_fans_safety_one` — reference `oracle.actuate` wrap-shape shipped in Session 3).
- `hvac_predict.py:1150-1180` (W12 `_activate_zone_fans` — second reference wrap-shape).
- `quality/tools/audit_fan_adjacency.py:1-200` (forward-adjacency walker + `_is_oracle_actuate_call` + `_is_oracle_consult_call` helpers).

---

## 3. Non-goals (explicit)

- **No new fan POLICIES.** Cooldown length, hold length, manual-ON hold semantics, kill-switch semantics, safety-override semantics all byte-frozen from v5.70.0.
- **No persistence added.** RoomFanState and the oracle ledger remain RAM-only. Adopt-external re-populates on boot (unchanged).
- **No new operator-facing knobs.** No new CONF_*, no new Number/Select/Switch entity, no new sensor.
- **No dashboard/PWA changes.** No new trigger strings.
- **No W11 / W12 rework.** They were wrapped in Session 3 and stay wrapped; only mentioned as reference shape.
- **No unification of room-tier vs HVAC-tier decision sources.** Both tiers still compute their own `desired_on`; the layer only guards emission.
- **No humidity-fan absorption** (unchanged from v2 M2 decision).
- **No shape (a) gateway construction** (v2 §6.5 parked).
- **No `RoomFanState` dataclass removal.** The delegation makes 2 fields read-through views; the dataclass survives to carry `is_on`, `speed_pct`, `trigger`, `last_on_time`, `vacancy_detected_time`, `manual_on_hold_paused_at`, `fan_recheck_suppress_until`, `fan_sleep_policy`, `fan_entities`, `room_name`, `zone_id`, `room_type`.
- **No test modifications to the FAN-LAYER-1 / v5.68.0 parity gates** (§9). If any of them need to change, STOP.

---

## 4. Tier — Tier 2-DB with ONE adversarial plan review

**Tier 2-DB (three framing-disjoint code reviews + live validation).**

**Why not Tier 3:** v2 §9 argued Tier 3 for the FAN-LAYER-1 extraction because it was inventing the shared primitive AND coining the falsifiable invariant AND enumerating the writer set for the first time. THIS cycle inherits all three artifacts; the extraction shape is decided, the invariants are stated (§1), the writer set is enumerated and shipped-partial. What remains is (a) wiring 6 existing writers into a shipped async-context helper following the exact pattern W11 and W12 demonstrate live, (b) delegating 2 dataclass fields to an already-populated ledger, (c) migrating 2 readers, (d) extending an existing audit tool by one code path. Regression-prone (fits the operator-coined 2026-06-08 standing policy — trust-hierarchy ripple across presence ↔ HVAC ↔ safety) but NOT invariant-inventing in the Tier-3 sense.

**Framings (three, disjoint):**
- **Review A — correctness + edge cases + hydrate-on-read parity.** Per-wrap site: does the snapshot builder pass the right axis, the right entities tuple, the right observed_any_on? Does the wrap fire `note_actuation` on the correct edge (verdict-change per §7.14)? For the two field delegations: does hydrate-on-read fire on first access post-deploy for a room whose RoomFanState was populated pre-oracle (mirror of B-HIGH-1)?
- **Review B — async lifecycle + INV-FLA-T + reload resilience.** Per-room lock scope (§5.4): does W8's out-of-`_set_fan_state` callsite hold the same lock as W4's in-`_set_fan_state` callsite? Does the adopt-external write path go through the same lock, so a URA OFF cannot interleave? CM reload: fresh `_room_fans` after `discover_fans()` — does the delegation still find the oracle-backed values? Boot-order: FanController construction vs. oracle construction — grep-verify + fixture test.
- **Review C — per-site source mutation + reverse-adjacency scanner authority.** For each of the 6 unwrapped sites in §2.2, comment out ONLY the `async with oracle.actuate(...)` line (keep the body's `services.async_call`), run the suite, confirm a NAMED test in §D2 fails. Restore. Then run the reverse-adjacency scanner on the tree with one WRAP deleted → the scanner must flag that site. Restore. `PYTHONDONTWRITEBYTECODE=1` + `__pycache__/` purge before drill (per `feedback_mutation_verification_pycache_staleness.md`).

**Plan-review discipline (per CLAUDE.md 2026-08-11 rule):** Tier 2-DB gets ONE adversarial plan review before build dispatch. Rationale: Tier 3 (strict two-plan-review shape) fits invariant-inventing cycles; this cycle inherits invariants from a plan that already passed two framing-disjoint plan reviews (v2 Review 1 completeness + Review 2 build-prediction). What this plan adds is delegation mechanics against an existing shape — the class of ambiguity a single adversarial plan review is sized for. **If the operator prefers Tier 3 stringency**, the second plan review would be a completeness pass — independent re-enumeration of the RoomFanState field write sites and the reverse-adjacency scanner's rule surface.

---

## 5. Design

### 5.1 HVAC-tier RoomFanState delegation (@property + hydrate-on-read)

**Shape decision:** `@property`-style descriptor with hydrate-on-read + datetime↔ISO conversion at the boundary. (Rejects v2 §7.10 "hard remove". The operator's task explicitly asks for @property delegation. Room-tier Session 2 uses this shape and has proven durable across the FAN-LAYER-1 review round — the v4.6.3-class silent-None bug the v2 §7.10 warned about is mitigated by hydrate-on-read + `_fallback_warn` observability, both of which the room-tier ships and both of which this delegation adopts verbatim.)

**RoomFanState rewrite (`hvac_fans.py:67-108`):**

```python
@dataclass
class RoomFanState:
    room_name: str
    zone_id: str
    room_type: str = ROOM_TYPE_GENERIC
    fan_entities: list[str] = field(default_factory=list)
    is_on: bool = False
    speed_pct: int = 0
    trigger: str = ""
    last_on_time: str = ""
    vacancy_detected_time: str = ""
    # DELEGATED to FanPolicyOracle (FAN-LAYER-2). Descriptors on the
    # class override read/write for these fields. Local slots persist
    # the last-written ISO string for hydrate-on-read fallback (B-HIGH-1
    # sister case). All 15 write sites and 15 read sites in this file
    # keep their existing string-typed shape; parsing/formatting happens
    # ONLY inside the descriptor.
    _manual_off_local: str = ""
    _manual_on_local: str = ""
    # ... remaining fields unchanged: manual_on_hold_paused_at,
    # fan_recheck_suppress_until, fan_sleep_policy
```

Descriptor implementation (module-level, applied to the class after definition):

```python
class _OracleISOField:
    """Read-through view of oracle.get_state(room).<field> as ISO string.

    Writes fan out to oracle.set_manual_*(...) AND stash to a local slot
    for hydrate-on-read fallback. Read prefers oracle; if oracle returns
    None and local is populated (pre-oracle-attach write, or restore
    just-before-oracle-ready) we hydrate the oracle from local and return
    local. Matches the room-tier @property shape at automation.py:283-329.
    """
    def __init__(self, oracle_field: str, setter_name: str, local_key: str):
        self._oracle_field = oracle_field   # "manual_on_hold_until" | "manual_off_cooldown_until"
        self._setter_name = setter_name     # "set_manual_on_hold" | "set_manual_off_cooldown"
        self._local_key = local_key         # "_manual_on_local" | "_manual_off_local"

    def __get__(self, obj, objtype=None) -> str:
        if obj is None:
            return self
        local = getattr(obj, self._local_key, "")
        oracle = _get_fan_oracle_for_room_fan(obj)  # walks obj -> hass
        if oracle is None:
            if local:
                _log_hvac_fallback_warn("read", obj.room_name)
            return local
        try:
            dt_val = getattr(oracle.get_state(obj.room_name), self._oracle_field)
            if dt_val is None:
                if local:
                    # Hydrate-on-read (B-HIGH-1 sister case)
                    parsed = dt_util.parse_datetime(local)
                    if parsed is not None:
                        getattr(oracle, self._setter_name)(obj.room_name, parsed)
                    return local
                return ""
            return dt_val.isoformat()
        except Exception:  # noqa: BLE001
            if local:
                _log_hvac_fallback_warn("read_exc", obj.room_name)
            return local

    def __set__(self, obj, value: str) -> None:
        setattr(obj, self._local_key, value)
        oracle = _get_fan_oracle_for_room_fan(obj)
        if oracle is None:
            _log_hvac_fallback_warn("write", obj.room_name)
            return
        try:
            if not value:
                getattr(oracle, self._setter_name)(obj.room_name, None)
            else:
                parsed = dt_util.parse_datetime(value)
                getattr(oracle, self._setter_name)(obj.room_name, parsed)
        except Exception:  # noqa: BLE001
            _log_hvac_fallback_warn("write_exc", obj.room_name)


RoomFanState.manual_off_cooldown_until = _OracleISOField(
    "manual_off_cooldown_until", "set_manual_off_cooldown", "_manual_off_local",
)
RoomFanState.manual_on_hold_until = _OracleISOField(
    "manual_on_hold_until", "set_manual_on_hold", "_manual_on_local",
)
```

**Getting hass from a RoomFanState:** RoomFanState instances live in `FanController._room_fans`. The descriptor helper `_get_fan_oracle_for_room_fan(obj)` walks a controller back-reference. Two implementation options: (a) inject `hass` into each RoomFanState via a factory call in `FanController.discover_fans`, or (b) keep a module-level `_active_controller_ref: weakref.ref[FanController]` set during `FanController.__init__`. Option (a) is cleaner — RoomFanState grows one non-dataclass private attr `_hass = None` set at construction and the descriptor reads `obj._hass`. Chosen: **(a)** — minimally invasive, no weakref dance, testable via direct injection in unit fixtures.

**Boundary responsibilities:**
- Reads: caller's `if room_fan.manual_off_cooldown_until:` truthiness works exactly as today (empty string = falsy).
- Writes: caller's `room_fan.manual_off_cooldown_until = dt_util.now().isoformat()` writes to local, parses via `dt_util.parse_datetime`, and hands the datetime to `oracle.set_manual_off_cooldown(...)`.
- Datetime↔ISO: parsing happens ONLY at the descriptor boundary. All 15 write sites keep their existing `.isoformat()` calls; all 15 read sites keep their existing `datetime.fromisoformat(...)` calls (the descriptor returns a fresh ISO string synthesized from the datetime it read from the oracle). Intentionally non-invasive.
- **Round-trip guarantee:** for a datetime `dt` written by the caller: `RoomFanState.f = dt.isoformat()` → descriptor stashes local, parses back to `dt2`, calls `oracle.set(dt2)`. Read: `oracle.get()` returns `dt2`, descriptor returns `dt2.isoformat()`. `dt2` must equal `dt` (str→dt→str fidelity). **`dt_util.parse_datetime` accepts what `datetime.isoformat()` emits.** Test `test_hvac_iso_datetime_round_trip_preserves_value` asserts this at the microsecond.

### 5.2 Key-space collision — resolved via room-name-first migration

Post A-HIGH-1, room-tier oracle writes are keyed by `entry_id`. HVAC-tier writes (this cycle) would be keyed by `room_name`. Two different keys pointing at the same physical room = INV-DTA broken.

**Resolution:** the room-tier `_fan_ledger_key()` (`automation.py`) is amended to prefer `room_name` when both `entry_id` and `room_name` are available. HVAC-tier does NOT have entry_id readily available at every write site (it operates on the `_room_fans[room_name]` dict), while room-tier has both. A single string key = single ledger row.

**Fallback for the A-HIGH-1 defense** (the reason `_fan_ledger_key` returned entry_id was collision when two rooms lacked a name): the amended key is `room_name if room_name else entry_id`. Rooms without a name still get their own row (entry_id fallback); rooms WITH a name use the name (and HVAC-tier finds them).

**Build-time live check (Reviewer B):** verify all live rooms have non-empty `CONF_ROOM_NAME` — read `.storage/core.config_entries` via the Samba mount for `domain == universal_room_automation` + `entry_type == ENTRY_TYPE_ROOM` and assert `data.get(CONF_ROOM_NAME)` is truthy for every entry. If any live room has empty name, the migration falls back safely for that room but the room is INV-DTA-excluded until named — surface as a build finding, not a ship blocker.

### 5.3 Six wraps — mechanical shape

Each of the six wraps follows the W11/W12 reference shape. Concrete example (W1, room-tier revert):

BEFORE (current tip):
```python
# automation.py:1801-1809
if self.is_fan_in_manual_on_hold():
    _LOGGER.info("Fan revert suppressed: manual-ON hold active for %s", room_name)
    return
await self.hass.services.async_call("fan", "turn_off", ...)
```

AFTER:
```python
snap = self._build_fan_snapshot_room(
    entities=fan_entities, observed_any_on=any_on,
)
async with oracle.actuate(
    self._fan_ledger_key(), FAN_TRIGGER_TEMP_ROOM, snap, "off",
) as verdict:
    if verdict.is_allow:
        await self.hass.services.async_call("fan", "turn_off", ...)
    else:
        _LOGGER.info(
            "Fan revert deferred: %s (reason=%s)",
            self._fan_ledger_key(), verdict.reason,
        )
# note_actuation fires on context exit per oracle.actuate contract
```

The `is_fan_in_manual_on_hold` explicit check is **removed** — the oracle consult inside `actuate` subsumes it. This is a REDUCTION in duplicate consult (Session-2 shipped both; FAN-LAYER-2 collapses to one). Test `test_w1_manual_on_hold_still_defers_revert` asserts the behavior is preserved by exercising the wrap end-to-end (not the removed peek).

W2 and W3 (`automation.py`) follow the same shape with different trigger constants. **W3 note:** the existing `mark_fan_on_issued` call at the top of the ON path becomes redundant (the wrap's `note_actuation` on-exit does the same edge write). Recommendation: **keep as idempotent belt-and-suspenders** so pre-existing tests naming `mark_fan_on_issued` still pass; v2 §7.14 edges-only dedup makes double-fire safe. A follow-up cycle can prune it if desired.

W4 (`hvac_fans.py:1231-1258`): the wrap goes AROUND the entire per-entity emission block, with the trigger propagated from a new kw-only arg on `_set_fan_state`. Callers that already thread a trigger context (W5 kill switch via `turn_off_all_managed`, W6 adopt paths) pass their trigger; the default (existing HVAC vacancy caller path) is `FAN_TRIGGER_TEMP_HVAC`.

W8/W9 (`hvac.py`): the wrap goes around the current `services.async_call` block. **Verify at build** whether these sites call through `_set_fan_state` or emit directly (v2 §5 asserted they bypass `_set_fan_state` — a build-time re-verification step is in D2 Verify).

W10-pause / W10-restore: wraps live in `hvac_fans.py` inside `pause_for_recheck` / `restore_after_recheck` at the actual `services.async_call` sites. `FAN_TRIGGER_RECHECK_PAUSE` / `FAN_TRIGGER_RECHECK_RESTORE` already in the enum. The `PauseContext` credit-paused-duration path (v2 §7.13) already exists on the oracle and is invoked automatically on the RECHECK_RESTORE verdict.

### 5.4 Lock scope — per-room, held across consult→emit→note; adopt-side alignment

Per v2 §7.9, the lock is per-room and owned by the oracle (`_room_locks: dict[str, asyncio.Lock]`, lazily created). The `actuate` async-context acquires the lock on entry, holds across the caller's body (which is where `services.async_call` awaits), releases on exit after firing `note_actuation`.

**Critical scope question:** does the adopt-external write path (`hvac_fans.py:308-339`) go through the same lock? **Today it does not.** The adopt path calls the RoomFanState descriptor's setter, which calls `oracle.set_manual_on_hold(room_name, dt)`. `set_manual_on_hold` today does NOT acquire the lock (grep `fan_policy_oracle.py:251-263`).

**This is a gap.** The URA-OFF side of the race is protected by `oracle.actuate`; the adopt-side write can still land between the `may_turn_off` consult on entry and the `services.async_call` await return, updating the ledger post-consult. The URA OFF completes; the ledger now reports HELD; the invariant statement is violated in fact even though the URA writer acted on the freshest verdict it saw.

**Fix in scope (recommended):** add `async def set_manual_on_hold_locked(room, dt)` and `async def set_manual_off_cooldown_locked(room, dt)` that `async with self._get_lock(room)` before writing. The RoomFanState descriptor setter cannot be async (Python descriptor contract), so:
- The adopt-external path in `hvac_fans.py:308-339` is invoked from `FanController.update` which IS async → it calls the async locked setters DIRECTLY, bypassing the descriptor for the write.
- The descriptor setter continues to write to local (fallback) and calls `oracle.set_manual_on_hold` (sync, unlocked) as the fast path for callers not on the adopt path.
- For adopt-path writes, wrap the assignment in `await oracle.set_manual_on_hold_locked(room, dt)` and skip the descriptor. This is a mechanical rewrite at the 4 adopt-path writes (:308, :335, :411, :651-ish for expiry clear).

Test `test_external_on_racing_ura_off_is_blocked_hvac_tier`: dispatch external-ON on the state bus mid-URA-OFF-await; assert the URA OFF sees the fresh hold on re-consult (which the actuate context can re-check on exit, an OPTIONAL enhancement) OR the adopt-side write is observably serialized behind the URA OFF's lock release.

**Escalation size:** ~40 LoC + 1 test. **Recommend land here.** If deferred to FAN-LAYER-3, README write-back explicitly documents "INV-FLA-T proven URA-side; adopt-side race deferred" with the concrete repro.

**Alternative escalation shape (park):** convert `set_manual_*` to `hass.async_create_task(async_locked_setter(...))`; simpler API but introduces task-scheduling latency between adopt-observation and ledger update, which itself is a small INV-DTA gap. Rejected in favor of the direct-await path from the adopt callsite.

### 5.5 Reverse-adjacency scanner (task item 4)

Extends `quality/tools/audit_fan_adjacency.py` with a second AST pass:

```python
def reverse_scan(tree: ast.Module) -> list[AdjacencyFinding]:
    """Every fan-emission services.async_call must be inside an
    oracle.actuate async-with body (or be an in-scope carve-out).
    """
    findings = []
    for func in _walk_functions(tree):
        if not _function_iterates_fan_entities(func):
            continue
        for stmt in ast.walk(func):
            if not _is_service_call_on_fan_domain(stmt):
                continue
            if not _enclosing_actuate_context(stmt, func):
                findings.append(AdjacencyFinding(
                    file=..., lineno=stmt.lineno,
                    site="reverse_adjacency",
                    reason="services.async_call on fan domain outside oracle.actuate",
                ))
    return findings
```

Fan-domain detection: `services.async_call("fan", ...)` (constant), `services.async_call("homeassistant", "turn_on"/"turn_off", ...)` when the entity_id iterates `fan_entities` / `CONF_FANS`, `services.async_call("switch", ...)` when the same iteration pattern is present.

**Known carve-outs** (documented in the scanner comment header, matching v2 §1): humidity fans (`_humidity_gate` block, sole-owner), state-restoration-only attribute writes at `hvac_fans.py:1541/1554/1567` (preset/oscillate/direction, covered by the parent RECHECK_RESTORE consult).

**Carve-out mechanism:** file-level suppression comment `# fan-adjacency: allow (reason=<explanation>)` immediately above the `services.async_call` line. Scanner respects the comment. Each carve-out has a mandatory `reason=` string that grep-audits against the v2 §1 list.

**Scanner run mode:** as a pytest test (`test_fan_adjacency_reverse_scan_clean`) that fails if any findings surface, mirroring the existing forward-scan test. Also runnable standalone via `python3 -m quality.tools.audit_fan_adjacency`.

---

## 6. Numbers get knobs

No new numbers. All existing tunables preserved at their current rungs (`DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S`, `DEFAULT_FAN_MANUAL_ON_HOLD_S`, `CONF_FAN_VACANCY_HOLD`, `CONF_FAN_MANUAL_ON_HOLD_S`, `FAN_TRIGGER_*` closed enum, oracle logger levels).

---

## 7. Scope pushback — marginal-benefit decomposition

The task bundles four items. Decomposed:

| Item | Simplest version | Marginal cost of "full" | Recommendation |
|---|---|---|---|
| 1. HVAC-tier RoomFanState delegation | @property-style descriptor on the 2 fields with hydrate-on-read | Full: ~150 LoC + 4 tests. Hard-remove alt (v2 §7.10): ~250 LoC + reader-drill on 15 sites. | LAND @property (operator asked for it; matches shipped room-tier pattern; safer boundary; less blast radius). |
| 2. `presence_fan_recheck.py:1002` reader migration | 5-line replacement | Trivial. | LAND with W10 (or D3). |
| 3. `oracle.actuate` wraps on W1-W3, W8-W10 | 6 wraps + 2 snapshot helpers | Full: ~200 LoC + 6 tests. Skipping any of the 6 leaves INV-FLA-T half-proven. | LAND all 6. Load-bearing scope. |
| 4. Reverse adjacency scan | AST walker extension + test | Full: ~100 LoC + 2 tests. Skip: leaves the completeness half open — a future writer added without a wrap goes unflagged (exactly the "grep-discipline mitigation" v2 §11 called tertiary risk). | LAND. Cheap and closes a real hole. |

**No item is a candidate for parking.** Splitting further would leave a partial-invariant state the operator already spent one cycle exiting.

**One suggested split of convenience:** if the §5.4 sync-setter lock escalation balloons, split it into FAN-LAYER-3 with a documented invariant gap. Recommendation in §5.4 is still to land it here.

---

## 8. Estimated cycle size

- **Diff:** ~600 LoC net additions, ~150 LoC net deletions across `hvac_fans.py` (~250 add / ~50 del for descriptors + rewrites), `automation.py` (~120 add / ~40 del for wraps + `_build_fan_snapshot_room` + `_fan_ledger_key` amendment), `hvac.py` (~80 add / ~10 del for W8/W9 wraps + snapshot-helper access), `presence_fan_recheck.py` (~20 add / ~30 del for reader migration), `fan_policy_oracle.py` (~50 add for locked setters if §5.4 lands), `quality/tools/audit_fan_adjacency.py` (~100 add for reverse scan).
- **Tests:** ~15 new tests: `test_hvac_iso_datetime_round_trip_preserves_value`, `test_hvac_tier_delegation_reads_oracle`, `test_hvac_tier_hydrate_on_read_seeds_oracle`, `test_hvac_tier_fallback_warn_fires_when_oracle_missing`, `test_dual_tier_agreement_room_key_room_name`, `test_w1..test_w10_*` (7 wrap tests + parity assertions), `test_external_on_racing_ura_off_is_blocked_hvac_tier`, `test_recheck_reader_migrated_to_oracle_get_state`, `test_recheck_reader_key_matches_room_name`, `test_fan_adjacency_reverse_scan_clean`, `test_fan_adjacency_reverse_scan_flags_deleted_wrap`, `test_fan_adjacency_reverse_scan_respects_carveout_comments`, `test_note_actuation_write_volume_under_budget_with_six_more_wraps` (§7.14 regression re-run).
- **Sessions:** ONE staged session preferred (under the >800 LoC staged-session threshold). Two commits on one branch for natural checkpointing: (a) descriptor + `_fan_ledger_key` amendment + reader migration + hydrate-on-read tests; (b) six wraps + snapshot helpers + reverse-scanner + write-volume test. Both merge together (per v2 §10 preamble discipline: partial merge leaves INV-FLA half-proven).
- **Reviewers:** 3 (Tier 2-DB parallel A/B/C per §4).
- **Underrun trigger:** below ~450 LoC OR below ~12 tests → audit for silently-dropped wrap or missed reader BEFORE dispatching reviewers.

---

## 9. Parity gates (must stay green, unmodified)

FAN-LAYER-1 behavioral tests + v5.68.0 guard anchors are the parity contract. **MUST NOT** be modified; must pass byte-identical:

- `quality/tests/test_fan_manual_on_hold_room_tier.py` (FAN-MANUAL-1, all tests including `test_mark_fan_on_issued_bridges_between_ticks`, `test_manual_on_hold_not_opened_by_ura_on`).
- Session-2 `test_set_fan_manual_off_until_writes_to_oracle` + sibling `_on_hold_` test.
- Session-2 `test_mark_fan_on_issued_records_oracle_edge`.
- Session-3 `test_safety_stop_consults_oracle_with_safety_true`, `test_prearrival_on_defers_under_manual_off_cooldown`.
- v5.68.0 vacancy-sweep parity anchor (the one caught by B-MED-1 fix-up).
- FAN-LAYER-1 D6 tests `test_hvac_zone_vacancy_sweep_respects_manual_on_hold`, `test_hvac_prearrival_respects_manual_off_cooldown`.
- Existing forward-adjacency test `test_fan_adjacency_walker_clean`.
- All existing HVAC restore/pause tests exercising `RoomFanState.manual_on_hold_paused_at` — the paused-at field is NOT delegated (§5.1 only delegates the two `_until` fields), so pause-context arithmetic is unchanged.

If any of these tests need to change, the cycle has silently altered policy — STOP and reopen scope.

---

## 10. Deliverables

### D1 — HVAC-tier RoomFanState delegation (@property + hydrate-on-read) + key-space unification

**Files:** `hvac_fans.py` (~250 add / ~50 del), `automation.py` (~20 add / ~5 del for `_fan_ledger_key` amendment).

- **Verify:** `git grep -n 'room_fan\.manual_off_cooldown_until\|room_fan\.manual_on_hold_until' custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` still returns the SAME set of 46 lines (callsites unchanged in shape); fields are backed by descriptors, not by inline dataclass slots.
- **Verify:** `_manual_off_local` and `_manual_on_local` slots are the ONLY places local ISO strings live in RoomFanState; no other code reads them.
- **Verify:** `discover_fans()` clears local slots on re-init (no cross-boot residue).
- **Verify:** `_fan_ledger_key()` returns `room_name if room_name else entry_id`; existing A-HIGH-1 tests pass unmodified (rooms with empty name still get their own row).
- **Verify (build-time live check):** every ENTRY_TYPE_ROOM entry in `.storage/core.config_entries` has non-empty `CONF_ROOM_NAME`. Surface any exception as a build finding.
- **Test:** `test_hvac_iso_datetime_round_trip_preserves_value` — write ISO, read ISO, parse both, equal to microsecond.
- **Test:** `test_hvac_tier_delegation_reads_oracle` — mock oracle returns a datetime; descriptor returns the same string; local slot is empty.
- **Test:** `test_hvac_tier_hydrate_on_read_seeds_oracle` — local slot pre-populated (simulating pre-oracle write), oracle returns None; first read triggers `oracle.set_manual_on_hold`, second read returns from oracle. Anchor against B-HIGH-1 bug class.
- **Test:** `test_hvac_tier_fallback_warn_fires_when_oracle_missing` — oracle absent; descriptor logs WARN; returns local. Mirror of A-MED-5.
- **Test:** `test_dual_tier_agreement_room_key_room_name` — populate the oracle from the room-tier side (simulating a live manual-ON via `_fan_manual_on_until` setter); read from the HVAC-tier RoomFanState descriptor for the SAME physical room; assert the ISO strings equal.
- **Live:** after triggering an external-ON on a bedroom fan, `oracle.get_state(<room>).manual_on_hold_until` in a dev-tools template equals the value the HVAC-tier diagnostic sensor payload reports at `hvac_fans.py:1588-1600` (which now reads through the descriptor).

### D2 — Six wraps (W1, W2, W3, W4-chokepoint, W8, W9, W10-pause, W10-restore) + snapshot helpers

**Files:** `automation.py` (W1, W2, W3 + `_build_fan_snapshot_room` — ~120 add / ~40 del), `hvac_fans.py` (W4 chokepoint + W10-pause + W10-restore + `_build_fan_snapshot_hvac` — folded into D1's diff), `hvac.py` (W8, W9 with helper calls into `_build_fan_snapshot_hvac` — ~80 add / ~10 del), `fan_policy_oracle.py` (locked setters if §5.4 escalation lands — ~50 add).

- **Verify:** `git grep -n 'oracle\.actuate' custom_components/universal_room_automation/` returns W11 (pre-existing) + W12 (pre-existing) + the SIX new sites — 8 total async-with sites (or 7 if W4-chokepoint subsumes W8/W9 per build-time re-verification, in which case W8/W9 lines carry a `# routes through _set_fan_state` comment).
- **Verify:** at each new site, `services.async_call` for the fan domain is INSIDE the `async with oracle.actuate(...)` block body — AST forward-adjacency walker passes.
- **Verify (build-time):** re-verify W8/W9 line numbers on develop tip (v2 asserts 2419-2430 / 2629-2643). If they currently call through `_set_fan_state`, the wrap at `_set_fan_state` may be sufficient; document in build commit message.
- **Verify:** `is_fan_in_manual_on_hold()` explicit checks at W1/W2 are removed (subsumed by wrap consult); `mark_fan_on_issued()` at W3 is KEPT as idempotent belt-and-suspenders (per §5.3).
- **Test:** `test_w1_room_revert_wrapped_in_oracle_actuate` — behavioral; a manual-ON hold on room X causes the revert branch to see `verdict.is_defer` and skip emit.
- **Test:** `test_w2_sleep_off_wrapped_in_oracle_actuate` — same shape, SLEEP_OFF trigger.
- **Test:** `test_w3_room_on_wrapped_in_oracle_actuate` — manual-OFF cooldown on room X causes turn-ON branch to defer; also asserts note_actuation edge is written (verdict-change).
- **Test:** `test_w4_set_fan_state_wrapped_and_propagates_trigger` — kwargs-driven trigger reaches oracle; mutation drill: pass wrong axis, oracle logs axis-mismatch VETO (§7.4a).
- **Test:** `test_w8_zone_vacancy_sweep_wrapped` — manual-ON hold persists across a zone-vacancy sweep tick; assert fan REMAINS ON (parity with FAN-LAYER-1 D6).
- **Test:** `test_w9_prearrival_off_wrapped` — cooldown persists across pre-arrival deactivation.
- **Test:** `test_w10_pause_wrapped_preserves_pause_context` — PauseContext is populated on `RECHECK_PAUSE` verdict.
- **Test:** `test_w10_restore_wrapped_credits_paused_duration` — `manual_on_hold_until` is extended by paused delta on restore.
- **Test:** `test_external_on_racing_ura_off_is_blocked_hvac_tier` — dispatch external-ON on the state bus during an awaited URA OFF at the W4 chokepoint; assert either verdict flipped to DEFER on the wrap OR the adopt-side write is observably serialized behind the URA OFF's lock release.
- **Test:** `test_note_actuation_write_volume_under_budget_with_six_more_wraps` — re-run v2 §7.14 write-volume regression with all 8 wrap sites live; assert < 200 rows / hour @ 40 rooms simulated over 3600s of mixed steady state.
- **Live:** synthesize a manual-ON at a bedroom fan; wait one HVAC tick (~5 min); observe `activity_log` shows `deferred: temp_hvac by manual_on_hold` at W4 AND the fan is not turned off; the room-tier symmetric behavior (deferred temp_room) also present. Duplicate for a manual-OFF vs. pre-arrival ON path.

### D3 — Recheck reader migration + presence-fan-recheck cleanup

**Files:** `presence_fan_recheck.py` (~20 add / ~30 del).

- **Verify:** `git grep -n 'manual_off_cooldown_until' custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py` returns **zero direct-field reads on `room_fan`**; only the `oracle.get_state(...)` accessor remains (and pre-existing comment / log strings).
- **Verify:** `_fan_in_manual_cooldown` no longer reaches through `hass.data → coordinator_manager → hvac.fan_controller._room_fans`; the entire reach-through is replaced by `oracle = _get_fan_oracle(self.hass); until = oracle.get_state(room_name).manual_off_cooldown_until if oracle else None`.
- **Test:** `test_recheck_reader_migrated_to_oracle_get_state` — inject an oracle with a known cooldown value; `_fan_in_manual_cooldown(room)` returns True; delete the oracle; returns False (fallback safety).
- **Test:** `test_recheck_reader_key_matches_room_name` — asserts the reader queries by `room_name` (per §5.2 key decision); guards INV-DTA.
- **Live:** trigger recheck on a fan with a live cooldown; observe recheck defers exactly as it does today (byte-frozen).

### D4 — Reverse adjacency scanner + carve-out audit

**Files:** `quality/tools/audit_fan_adjacency.py` (~100 add), 3 new tests.

- **Verify:** `python3 -m quality.tools.audit_fan_adjacency` returns 0 findings on develop tip post-D2.
- **Verify:** the scanner header enumerates the exact carve-outs from v2 §1 (humidity, state-restoration-only attribute writes at `hvac_fans.py:1541/1554/1567`).
- **Verify:** any legitimate carve-out in source is marked with `# fan-adjacency: allow (reason=<explanation>)` above the `services.async_call` line.
- **Test:** `test_fan_adjacency_reverse_scan_clean` — the reverse scan finds no findings on the real repo.
- **Test:** `test_fan_adjacency_reverse_scan_flags_deleted_wrap` — Reviewer-C drill fixture: on a `tmp_path` copy of one wrap file, remove the `async with oracle.actuate` line, run the scanner, assert the specific `services.async_call` line is flagged. (Fixture copy, not in-place mutation → no bytecode staleness concern.)
- **Test:** `test_fan_adjacency_reverse_scan_respects_carveout_comments` — a synthetic fixture with a valid `# fan-adjacency: allow (reason=humidity_sole_owner)` comment passes; a fixture with the comment missing fails.
- **Live:** none — build-time gate.

### D5 — Doc write-back

**Files:** `docs/Coordinator/HVAC.md` — extend the FAN-LAYER section (adding it if v2 D9 write-back never landed) with:
- HVAC-tier delegation semantics (§5.1 descriptor shape, hydrate-on-read).
- Key-space unification note (§5.2).
- INV-FLA-T + INV-DTA falsifiable statements.
- Reverse-adjacency scanner section: how to run it, how to add a carve-out.
- Post-live-validation README write-back (`docs/readmes/README_v<version>.md`) — replaces prospective Live rows with observed evidence table per CLAUDE.md.

---

## 11. Sharpest risk

**Not the wraps (they're mechanical mirrors of W11/W12) — the sharpest risk is `RoomFanState` descriptor semantics under a partially-populated ledger AND the key-space unification landing atomically with the delegation.**

Concrete failure repro: post-deploy, `FanController.discover_fans()` runs (constructor path), instantiates a fresh `RoomFanState` for room X. Local slots default to `""`. First HVAC tick reads `room_fan.manual_on_hold_until` — descriptor calls `oracle.get_state("X").manual_on_hold_until`. If the room-tier had previously seen X and populated the oracle under `entry_id` (pre-§5.2 key unification), the HVAC descriptor queries under `room_name` and gets None → returns "". Meanwhile the room-tier still sees the hold via its @property (queries under entry_id which the local `__dict__` cached at deploy time). Result: room-tier says HELD; HVAC-tier sweeps OFF because it sees no hold. **INV-DTA violated on the exact seam FAN-LAYER-2 is supposed to close.**

Mitigation: §5.2 key unification (room-tier `_fan_ledger_key()` prefers `room_name`) MUST land in D1 (not D2) so the descriptor and the room-tier @property both query the same key from the moment the delegation goes live. Test `test_dual_tier_agreement_room_key_room_name` explicitly anchors this.

**Secondary risk:** the adopt-external write path lock discipline (§5.4). If the sync-setter escalation is deferred to FAN-LAYER-3, INV-FLA-T is proven for the URA-OFF side of the race but not for the adopt-side write happening mid-await. Reviewer B validates the disposition (either the escalation lands here, or the README explicitly notes the deferred gap with the specific repro).

**Tertiary risk:** shape-(b)'s reliance on grep discipline for future writers. The reverse-adjacency scanner (D4) closes this — but only for writers that iterate `CONF_FANS` in a shape the AST walker recognizes. A future writer using indirection (e.g. iterating a list of entity_ids fetched from a helper) could evade. Documented under the scanner's header as a known limitation; the shape-(a) escalation trigger from v2 §6.5 still applies.

---

## 12. Open questions for operator

1. **§5.4 sync-setter lock escalation — land here or defer to FAN-LAYER-3?** Recommendation: land here (~40 LoC, closes INV-FLA-T fully). If deferred, README write-back explicitly documents the invariant gap.
2. **§5.2 key-space migration — safe assumption that every live room has non-empty `CONF_ROOM_NAME`?** Build-time live check required; if any live room fails, migration falls back to entry_id and that room is INV-DTA-excluded until named. Surface as build finding.
3. **W3 `mark_fan_on_issued` — keep as idempotent belt-and-suspenders, or prune?** Recommendation: keep (pre-existing test names it; §7.14 edges-only makes double-fire safe). Prune in a follow-up if desired.
4. **Tier 2-DB vs. Tier 3 — operator can elevate.** Recommendation: Tier 2-DB (§4 rationale). Elevate if the sync-setter escalation feels riskier than the plan reads.

---

## 13. Plan completion tracking (open items to reconcile at close)

- Any of the six wraps skipped → INV-FLA-T only half-proven; explicitly document and card FAN-LAYER-3.
- Reverse-adjacency scanner not landed → completeness half open; card as FAN-LAYER-3.
- §5.4 sync-setter escalation deferred → note in README write-back with concrete repro.
- If §5.2 key unification uncovers a live room without `CONF_ROOM_NAME`, card a follow-up naming cycle before closing FAN-LAYER-2.
- `docs/Coordinator/HVAC.md` write-back (D5) — must land pre-close.
- README `Validated <date>` table populated post-live-validation before cycle closes.
