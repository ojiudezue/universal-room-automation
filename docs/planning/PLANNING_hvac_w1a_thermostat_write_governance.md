# PLANNING — HVAC W1 Stage A: Thermostat Write Governance (behaviour-neutral)

**Rev 2** — 2026-09-26. Folds adversarial plan-review FIX-PLAN-FIRST F1-F15 and the W1+W2 integration doc §6 C2-fields amendment. Rev 1 language replaced in place; no appendix.

**Card:** HVAC-W1-THERMOSTAT-DEFINITION (Stage A only)
**Children in scope:** HVAC-SETHVACMODE-CHOKEPOINT-1 (incl. `scope_added_2026_09_25_record_every_write`), Phase 1 of HVAC-THERMOSTAT-ABSTRACTION-1, capability-gate half of HVAC-PRESET-WRITE-STRATEGY-1 (shipped v5.103.2; nothing new).
**Branch base:** `develop`, AFTER `feature/hvac-live-room-establishment` (v5.103.15) merges. See §Sequencing.
**Tier:** **Tier 2-DB** (three framing-disjoint reviews + one plan review + live validation + README write-back). Regression-prone: touches every URA-originated thermostat write.
**Stage A is BEHAVIOUR-NEUTRAL.** No gate, value, ordering or timing change. Adds a third funnel + ONE durable row per attempted wire call + AI-rule pathway lockdown + AST completeness lint. NO brand strategy, NO presets-only returns, NO coherence rule — Stage B, Tier 3, operator go.

---

## 0. State-of-play acknowledgement (MANDATORY)

I have re-read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely, INCLUDING the new §10 entries **C16** (Carrier polling cadence = 30-min full poll + 5-min post-write guard, NOT 42-79 s continuous) and **C17** (arrester suppression is TWO windows: `SUPPRESS_TTL_SECONDS=5` for temperature at `hvac_override.py:129`, `SUPPRESS_TTL_SECONDS_PRESET=120` for preset at `:153`, `:141-146`). Stage A does not depend on either — but its logging must be robust to *both* Carrier lag shapes because a wire-write's echo can return after either window; the row records `ts_issued` + `ts_returned` (F12) so downstream analysis can correlate.

I have re-read `docs/planning/PLANNING_hvac_arc_w1_w2_integration.md` §6. Amendment "W1-A D2: add C2 fields (`preset_mode`, `hold_activity` at write time)" is folded into D2 below (F6).

Precedence rule from state-of-play §0.2: code at cited file:line wins. All D3 line numbers in this plan are TENTATIVE and MUST be re-resolved by symbol after v5.103.15 merges (F13).

---

## 1. Falsifiable invariant (Stage A)

> **INV-A:** For every wire-level climate service call URA issues (`set_temperature`, `set_preset_mode`, `set_hvac_mode`) on any zone from anywhere in `custom_components/universal_room_automation/` — including AI-rule execution paths and startup-audit paths — a `climate_write` row-schedule call is issued **before the funnel returns or raises**, one per attempted wire call, carrying verb + entity_id + zone_id + site + reason + `values_after` (exact service_data sent) + `values_before` snapshot + `preset_mode` + `hold_activity` + `blocking` + `ts_issued` + `ts_returned` + `wire_ok` + `excursion_id` (when passed by a borrow site). No URA-originated climate write reaches `hass.services.async_call("climate", ...)` outside `hvac_setpoint.py`.

**Exclusion (F5, made explicit):** `optimization.py:3546`/`:3688` climate actions are shadow-by-default and remain OUT of INV-A for Stage A. They enter the codebase's `DYNAMIC_DOMAIN_ALLOWLIST` (D-new, reviewed entry with the string reason `"optimizer-shadow-actions-carded-for-later-routing"`) and are carded for later funnel routing (Stage B or a follow-on card). Any AI-rule chained route to a climate service (`coordinator.py:1096-1130`) is IN scope: after Stage A, AI rules refuse ALL `climate` services, not just the three verbs.

**Falsifiers** D must go looking for:
- A URA code path issues a climate service call and **zero** rows are scheduled (bypass) — mutation drill catches it.
- More than one row per **attempted** wire call.
- A row is scheduled but its dict lacks any required key (verb / site / zone_id / entity_id / reason / blocking / `values_after` / `ts_issued`).
- The row-schedule call is `await`ed (F2 CRIT) or otherwise linked into the wire-call's failure path such that logging changes raise/swallow/return semantics.
- A future PR adds `hass.services.async_call("climate", ...)` OR `hass.services.call("climate", ...)` OR an executor-wrapped equivalent OR an alias of `hass.services.async_call` outside `hvac_setpoint.py` and CI passes.
- The resume-then-pin path emits fewer than one row per wire attempt (resume, pin, pin_retry each = one attempted wire call = one row each; F11).

**Non-falsifiers** (Stage B territory):
- Whether the write was semantically correct.
- Whether URA can distinguish its own late echo from a human write.
- Whether `manual` counts as a human.

---

## 2. Institutional context verified

### 2a. Design/state docs read end-to-end this session
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — full read (§0-§12), including §10 C16 + C17.
- `docs/planning/AUDIT_thermostat_write_paths_2026_09_16.md` — full read.
- `docs/planning/PLANNING_hvac_arc_w1_w2_integration.md` §1-§6 — full read; §6 C2 folded into D2 (F6).

### 2b. Kanban cards read
- `HVAC-W1-THERMOSTAT-DEFINITION` (kanban.data.yaml:1804-1820).
- `HVAC-SETHVACMODE-CHOKEPOINT-1` (kanban.data.yaml:2037-2086) incl. `scope_added_2026_09_25_record_every_write`.
- `HVAC-THERMOSTAT-ABSTRACTION-1` (10609+) — Phase 1 == Stage A here; Phase 2 = Stage B.
- `HVAC-PRESET-WRITE-STRATEGY-1` (10744+) — SUBSUMED; capability half shipped v5.103.2.

### 2c. Prior-art scan (code) — REUSE / NEW per proposed piece
| Piece | REUSE / NEW | Evidence |
|---|---|---|
| Third-verb funnel `emit_set_hvac_mode` | **NEW** | 0 hits for the symbol; all 7 raw sites are direct `hass.services.async_call("climate","set_hvac_mode",...)` (AUDIT §1b B1-B7). |
| Kwarg shape `site` / `zone_id` / `reason` | **REUSE pattern** from `emit_set_preset_mode` (`hvac_setpoint.py:288+`) BUT MADE REQUIRED across all three funnels (F3). Rev-1 said "mirror"; rev-2 pins them as required keyword-only. |
| `blocking` kwarg on `emit_set_hvac_mode` | **REQUIRED kwarg** (F10). Every migrated site names its current value so a review can diff. |
| `excursion_id` kwarg | **NEW optional funnel kwarg** (F6). Passed by borrow sites from their token (S3, S4, S5, S6, S7, S8, S11-S13, egress). NEVER inferred from module state — passed or absent. |
| Row writer | **REUSE `database.log_activity` DIRECTLY** (`database.py:5788-5822`) — bypassing `ActivityLogger.log`. Rationale (F4): the class adds dedup (`_DEDUP_WINDOWS`, `activity_logger.py:27-31`), tz normalization, `SIGNAL_ACTIVITY_LOGGED` dispatch, and `ura_action` HA-event fires (`activity_logger.py:4-6`). NONE of those are wanted here: two identical writes 1 s apart must land as two rows; there is no downstream sensor that consumes `climate_write`; firing an HA event per wire write is bus pollution. Direct `database.log_activity` preserves the row + retention + WS-query surface without any of that. |
| `hass.data` access pattern (guarded, never raises) | **REUSE pattern** from `_log_deferred_write` (`hvac_setpoint.py:108-159`); F14. |
| Fire-and-forget scheduling | **REUSE pattern** `hass.async_create_task(...)` — precedents `hvac.py:2716` (preset_change), `hvac_setpoint.py:138` (deferred write). F2. |
| New `action="climate_write"` string | **NEW value** (0 hits). Additive; no schema change. |
| Retention behaviour | **REUSE `prune_activity_log`** (`database.py:5824-5859`). NOTE: `info` = 7 d, `notable`/`critical` = 30 d (F9). Row importance = **`"notable"`**, so 30 d retention. |
| AST completeness lint | **NEW** test file `quality/tests/test_hvac_climate_write_funnel_completeness.py`. |
| AI-rule climate-domain block (F5) | **EXTEND** existing `coordinator.py:1107-1123` refusal (which today blocks only 3 verbs) to refuse ALL `climate` services with an allowlist for the funnel path and the reviewed `DYNAMIC_DOMAIN_ALLOWLIST` shadow-optimizer entry. |
| `DYNAMIC_DOMAIN_ALLOWLIST` | **NEW module constant** with a single entry (optimizer shadow actions) carrying its `reason` and its owning card id. |

### 2d. Prior-art scan (plans + memory)
- AUDIT §8 rec 1 — Stage A honours "advance Phase 1 ... explicitly NOT the fix for HIGH-2 or the oscillation".
- `PLANNING_hvac_governed_excursion.md` rev-6 — do NOT rebuild the stripped lease gate.
- Memory `feedback_tier2db_for_regression_prone`, `feedback_tier2plus_prior_art_scan`, `feedback_do_robust_fix_not_bandaid_and_card`, `project_optimizer_db_write_flood_incident_2026_06_09` (write-volume review), `feedback_hollow_test_anchors` (F1's motivation), `feedback_verify_claim_types_not_felt_uncertainty`.

### 2e. Code locations surveyed
- `hvac_setpoint.py` (both funnels, `_log_deferred_write` guarded pattern, `_needs_resume_first`, resume-then-pin ordering `:350-353`)
- `hvac.py` (S1 preset apply, heat_cool enforcer, `preset_change` async_create_task at `:2716`)
- `hvac_override.py` (S3-S9, B4-B7; nudge start/restore path S5/S6/S7)
- `hvac_egress.py` (B2 pause, B3 resume, S9 predict paths not applicable)
- `hvac_excursion.py` (bookkeeping only, C13; startup-audit nudge preset restore path — F13)
- `hvac_predict.py` (S11-S13 all funnelled)
- `coordinator.py:1096-1130` (AI-rule refusal surface — F5)
- `optimization.py:3546`, `:3688` (shadow-by-default climate actions — F5 exclusion)
- `database.py:5788-5822` (`log_activity` DAO) + `:5824-5859` (prune) + `:1351-1369` (DDL)
- `activity_logger.py:4-8, 27-31, 51-` (why NOT reused — F4)

---

## 3. Producer / Consumer analysis

### 3a. PRODUCER
- Three funnels in `hvac_setpoint.py`. Row shape is captured **synchronously** (F2): a helper `_capture_climate_write_row(...)` builds the row dict from funnel args + `hass.states.get(entity_id)` snapshot + `ts_issued = time.monotonic()` **before** the wire call. After the wire call returns (or raises), the funnel sets `wire_ok`, `ts_returned`, and (on raise) `exc`; then `hass.async_create_task(database.log_activity(...))` — never awaited (F2). The helper is guarded like `_log_deferred_write` and never raises (F14).
- The row is scheduled **once per attempted wire call**. In `emit_set_preset_mode`'s resume-then-pin path (`hvac_setpoint.py:350-353`), the ordering is: (i) synchronous field-capture for the resume, (ii) await resume, (iii) schedule resume row (AFTER the resume returns/raises), (iv) synchronous field-capture for the pin, (v) await pin, (vi) schedule pin row, (vii) if pin failed and retry runs, capture/await/schedule pin_retry the same way. Nothing awaitable lands between resume and pin (F2).
- Dependency health: `database.log_activity` is the same DAO already carrying `preset_change`; DB write queue is proven at 771-1,883 rows/day (F8). Boot-safe.
- On exception in the wire call: the funnel schedules the row with `wire_ok=False, exc="<class name>"` then **re-raises the original exception** (F11). Row emission never alters raise/swallow/return.

### 3b. CONSUMERS (Stage A)
- **Test acceptance** — per-site mutation drills (F15), the AST completeness lint (D5), the C2-field discriminator tests (F6), the dedup-off tests (F4).
- **Live validation** — per-site JOIN queries between `climate_write` and pre-existing tables (F7), not a ±5 % aggregate.
- **No trust decisions consume `climate_write` in Stage A.** Diagnostic only. Stage B will consume for provenance classification.
- Existing WS API `ura/logs/activity` (`websocket_api.py:173`) can query the new action — no wiring added.

---

## 4. Measured write rates + table decision

### 4a. Measured (7 days to 2026-09-26; state-of-play §4.3, §9.1 + counts folded from F8)
| Source | 7 d count | ≈ writes/day (3 zones) |
|---|---:|---:|
| `ura_activity_log` `preset_change` (S1) | 315 | ~45 |
| Nudge start / restore pairs (`ac_ramp_events` `nudge_started` / `nudge_restored`) | 112 / 112 | ~48 wire writes/day (start ~16, restore-setpoint ~16, restore-preset ~16) |
| Hard reset (`ac_ramp_events`) — 3 verbs per reset | 4 | ≤2 wire writes/day |
| S3 compromise (`hvac_excursion_events`) | 34 | ~10 |
| S12 pre-cool (`hvac_excursion_events`) | 16 | ~5 |
| Egress / banking / other | sparse | ≤5 |
| Heat_cool enforcer / B4 override-revert mode / B2/B3 egress mode | sparse | ≤5 |
| **Total estimated `climate_write` rows/day** | | **≈ 110-130/day** |
| `ura_activity_log` total volume | 5,397-13,181 | 771-1,883/day |

**`climate_write` share of the shared log ≈ 10 %** (F8 — NOT the "<1 %" rev-1 wrongly asserted). Retention windows are already tiered (7 d info / 30 d notable). At `"notable"`, ≈ 3,300 `climate_write` rows resident at steady state — trivial for the DB (≈ 500 KB); non-trivial for the log's fairness only if a bug loops the funnel, which the per-site tests catch.

### 4b. Table decision: **REUSE `ura_activity_log`** (unchanged from rev-1; volume math corrected)
Justification stands: fits the schema without migration, retention already tiered, WS-query surface reused, ≈ 10 % of shared log is well inside safe fraction. Direct `database.log_activity` bypasses `ActivityLogger`'s dedup + dispatch + HA-event fire (F4), preserving the ledger property that two identical wire writes 1 s apart produce two rows.

### 4c. Row shape (final)
```
timestamp   = dt_util.utcnow().isoformat()          # tz-aware
coordinator = "hvac"
action      = "climate_write"
room        = None
zone        = <zone_id>                              # required
importance  = CLIMATE_WRITE_LOG_IMPORTANCE = "notable"   # F9: 30-day retention
description = "<verb> zone=<z> site=<site> reason=<reason>"
entity_id   = <climate.entity>
details_json = json.dumps({
  "verb":              "set_temperature" | "set_preset_mode" | "set_hvac_mode",
  "site":              "<site tag>",
  "reason":            "<caller-supplied string>",
  "blocking":          <bool>,                       # F12
  "wire_ok":           <bool>,
  "exc":               "<class name or null>",
  "excursion_id":      "<from borrow token, or null>",   # F6, never inferred
  "values_before": {
     "preset_mode":    <str|null>,                   # F6 (C2 status feed)
     "hold_activity":  <str|null>,                   # F6 (C2 config feed)
     "target_low":     <float|null>,
     "target_high":    <float|null>,
     "hvac_mode":      <str|null>,
  },
  "values_after":      <exact service_data dict sent, post freeze-floor/deadband>,   # F12
  "ts_issued":         <monotonic seconds before await>,          # F12
  "ts_returned":       <monotonic seconds after await/raise>,     # F12
})
```
All keys are ALWAYS present with `null` when unknown (F6 "null-with-key when absent"). Missing key = falsification.

---

## 5. Deliverables

### D1 — `emit_set_hvac_mode` funnel in `hvac_setpoint.py`
```
async def emit_set_hvac_mode(
    hass, entity_id, hvac_mode,
    *, site: str, zone_id: str, reason: str, blocking: bool,          # ALL REQUIRED (F3, F10)
    excursion_id: str | None = None,
) -> bool
```
Wraps ONE `hass.services.async_call("climate", "set_hvac_mode", data, blocking=blocking)`. NO gate (Stage A preserves current behaviour — safety-side mode writes are deliberately ungated per AUDIT §5). Row-schedule via the helper below; NEVER `await`ed (F2). Never raises from the log path (F14); re-raises any wire-call exception unchanged (F11).

**Acceptance (D1):**
- **Verify (AST):** `hvac_setpoint.py` contains exactly one `AsyncFunctionDef` named `emit_set_hvac_mode` whose body contains exactly one `Await` on `hass.services.async_call` with first positional arg literal `"climate"` and second literal `"set_hvac_mode"`.
- **Test:** `test_emit_set_hvac_mode_happy_path` — real fake hass + in-memory `database.log_activity` stub; assert one service call issued, one row scheduled (`hass.async_create_task` called once with a coro that invokes `log_activity`), row keys complete per §4c, `wire_ok=True`.
- **Test:** `test_emit_set_hvac_mode_wire_raises` — service raises `HomeAssistantError`; assert row scheduled with `wire_ok=False, exc="HomeAssistantError"` AND `HomeAssistantError` propagates to caller (F11).
- **Test:** `test_emit_set_hvac_mode_missing_kwargs_typeerror` — calling without `site`/`zone_id`/`reason`/`blocking` raises `TypeError` at call time (F3, F10).
- **Test:** `test_emit_set_hvac_mode_never_awaits_log` — assert the row-schedule expression is `hass.async_create_task(...)`, not `await ...` (F2 mutation drill: rewrite to `await` → this test fails).
- **Live:** within 24 h of ship, at least one row with `verb="set_hvac_mode"` from ANY of the 7 sites (natural fires are rare for AC reset; heat_cool enforcer or egress-adjacent fires more often; D5 mutation supplies the guaranteed discriminator).

### D2 — Row-schedule helper + wire it into all three funnels (C2 fields; F6)
Add `_schedule_climate_write_row(hass, *, verb, entity_id, site, zone_id, reason, blocking, excursion_id, values_before, values_after, ts_issued, ts_returned, wire_ok, exc)` in `hvac_setpoint.py`. Guarded exactly like `_log_deferred_write` (`:121-128`): `hass.data.get(DOMAIN, {}).get(...)`, never raises (F14), fire-and-forget via `hass.async_create_task(database.log_activity(...))` (F2, F4).

`values_before` is captured synchronously by reading `hass.states.get(entity_id)` immediately before the `await`, extracting `preset_mode`, `hold_activity`, `target_temp_low`, `target_temp_high`, `state` (as `hvac_mode`). Absent attributes = `null` with the key present (F6). `values_after` is the exact `service_data` dict passed to `async_call` **after** freeze-floor + deadband transforms (F12) — i.e. the truth of what URA sent, not what the caller intended.

Extend `emit_set_temperature` and `emit_set_preset_mode` to call `_schedule_climate_write_row` after each `await` on a climate service. **Sites the helper is called from (F11 — exactly 5, one per attempted wire call):**
1. `emit_set_temperature`'s wire await
2. `emit_set_preset_mode`'s direct-pin wire await (non-resume path)
3. `emit_set_preset_mode`'s **resume** wire await (resume-then-pin, scheduled AFTER the resume returns/raises)
4. `emit_set_preset_mode`'s **pin** wire await (resume-then-pin, scheduled AFTER the pin, sites `<caller>+pin`)
5. `emit_set_preset_mode`'s **pin_retry** wire await (only when pin failed and retry runs; scheduled AFTER the retry)

Plus a 6th when D1's `emit_set_hvac_mode` calls it. **No other call sites.** The AST test asserts that count.

`excursion_id` is a NEW keyword-only kwarg on each of the three funnels, forwarded unchanged into the row (F6). Borrow-owning sites (S3, S4, S5, S6, S7, S8, S11, S12, S13, egress pause/resume) pass their token's `excursion_id`; non-borrow sites pass `None`. It is NEVER inferred (F6): a bug that forgets to forward it becomes a null in the row, not a wrong id.

**Acceptance (D2):**
- **Verify (AST):** `_schedule_climate_write_row` is called from exactly 5 sites in `hvac_setpoint.py` (or 6 counting D1); tested via AST walk, not grep.
- **Test:** `test_row_shape_has_all_required_keys` — each of the 6 call sites produces a row whose top-level `details_json` dict contains every key listed in §4c, with `null` where the source was absent.
- **Test:** `test_c2_fields_read_synchronously_before_wire` (F6 discriminator) — mock `hass.states.get(entity_id)` to a state carrying `preset_mode="home", hold_activity="home"`; issue a `set_temperature` via S5 nudge; then mutate the returned state to `manual`/`manual`; assert the SCHEDULED row's `values_before.preset_mode == "home"` and `values_before.hold_activity == "home"` (proving the read happened BEFORE the await, not after).
- **Test:** `test_dedup_off_two_identical_1s` (F4) — two identical `emit_set_hvac_mode` calls 1 s apart → 2 rows in `log_activity` stub.
- **Test:** `test_no_signal_no_bus_event` (F4) — assert `SIGNAL_ACTIVITY_LOGGED` not dispatched and no `ura_action` bus event fired for `climate_write` (achieved by bypassing `ActivityLogger`).
- **Test:** `test_two_different_writes_within_30s` (F4) — two DIFFERENT wire writes 3 s apart → 2 rows (would be dedup'd if we'd routed via `ActivityLogger` with `importance="info"` 30-s window).
- **Test:** `test_resume_then_pin_schedules_two_rows_in_order` — force `_needs_resume_first`=True; assert two `hass.async_create_task` calls in order, first with `site="<caller>+resume"`, then `site="<caller>+pin"`. If pin fails and retry runs, three tasks; sites `+resume`, `+pin`, `+pin_retry`.
- **Test:** `test_resume_row_scheduled_after_pin_await_returns` (F2 nuance) — since nothing awaitable lies between resume and pin, the resume row must be scheduled either (a) between resume's await and pin's await, OR (b) after pin returns — the plan pins option (a) so a failed pin does not race the resume row. Assert scheduling happens between the two awaits.
- **Test:** `test_row_helper_never_raises_when_hass_data_missing` (F14) — call funnel with a `hass` whose `data` dict lacks `DOMAIN`; wire write still succeeds; no exception; no row scheduled; `_LOGGER.debug` recorded.
- **Test:** `test_row_helper_wire_raise_semantics_unchanged` (F11) — mock service to raise; assert (i) row scheduled with `wire_ok=False`, (ii) same exception type + args propagate.
- **Test:** `test_row_shape_carries_ts_issued_before_ts_returned` (F12) — assert `ts_issued <= ts_returned` and both are numeric monotonic seconds.
- **Test:** `test_excursion_id_forwarded_from_borrow_site` (F6) — S5 nudge call passes `excursion_id="nudge:zone_1:abc"`; assert the row carries the same id; a non-borrow call (S1) produces `excursion_id=null`. Never inferred: a mocked `borrow-context-in-thread-local` is IGNORED.
- **Live:** first 24 h post-restart, joins in F7 pass; C2 fields present on ≥95 % of rows (some may legitimately null when the entity is `unavailable` at write time — e.g. boot transient).

### D3 — Migrate the 7 raw `set_hvac_mode` sites through `emit_set_hvac_mode`
Line numbers below are per state-of-play + F13; re-resolve by symbol at build time (F13, §Sequencing).

| # | Site (symbolic) | Current file:line (verify) | `blocking` today | Notes |
|---|---|---|---:|---|
| B1 | Heat_cool enforcer drift revert | `hvac.py:~1928` (F13 real) | **True** (`hvac.py:1935`) | `suppress()` handshake wraps caller side; move only the wire call into the funnel. |
| B2 | Egress pause "off" | `hvac_egress.py:~683` (F13) | **True** (`egress:686`) | Inside `auto_release_on_incomplete` CM — bookkeeping stays outside. |
| B3 | Egress resume `saved_mode` | `hvac_egress.py:~779` (F13) | **True** (`:782`) | Preset half at `:795` already funnelled; only the mode half moves. |
| B4 | Override revert heat_cool | `hvac_override.py:~3520` (F13) | **False** (`override:3526`) | F13: description in rev-1 said `suppress()` "wraps"; actual pattern is `suppress()` **after + conditional** — do not add an extra suppress. |
| B5 | AC reset OFF | `hvac_override.py:~3889` (F13) | **True** | Preserve blocking. |
| B6 | AC reset restore | `hvac_override.py:~4007` (F13) | **True** | Preserve. |
| B7 | AC reset restore retry | `hvac_override.py:~4042` (F13) | **True** | Preserve `attempt<=2`. |

**Also NEW to the migration list (F13):**
| # | Site | File:line (verify) | Verb | Blocking | Notes |
|---|---|---|---|---:|---|
| S6-fix | Nudge RESTORE setpoints — missing `site`/`zone_id`/`reason` today | `hvac_override.py:4595` | `set_temperature` | (per-site) | F3: add REQUIRED kwargs; site tag `S6_nudge_restore_setpoint`. |
| S7-fix | Nudge RESTORE preset — missing kwargs today | `hvac_override.py:4638` | `set_preset_mode` | (per-site) | F3: add REQUIRED kwargs; site tag `S7_nudge_restore_preset`. |
| SA-startup | Startup-audit NUDGE preset restore | `hvac_excursion.py:1131` (F13) | `set_preset_mode` (already funnelled) | (per-site) | F13: ensure `site="SA_startup_audit_nudge_preset_restore"`, `zone_id`, `reason` are all supplied — currently already funnelled but may lack the required kwargs Stage A now enforces. |

**Byte-identical constraints (unchanged):**
- No new gate on any migrated site.
- Same `blocking` per row above.
- Same `service_data` dict.
- Preserve caller-side `_supports_heat_cool`, `suppress()`, and `auto_release_on_incomplete` wrapping.

**Acceptance (D3):**
- **Verify (AST test, F1):** ZERO `Call` nodes in `custom_components/universal_room_automation/` (except inside `hvac_setpoint.py`) whose func chain ends in `services.async_call` and whose first positional arg (or `domain=` kwarg) is the string literal `"climate"`. See D5 for the full lint spec including aliasing and non-literal domain.
- **Verify (grep sibling, F1):** `rg -U --multiline "services\.async_call\(\s*[\"']climate[\"']" custom_components/universal_room_automation/` returns matches ONLY in `hvac_setpoint.py`. **Acceptance for this grep specifically:** on the pre-migration commit (i.e. develop-post-v5.103.15-merge, pre-Stage-A), this same multiline grep MUST return ≥7 matches OUTSIDE `hvac_setpoint.py`. If it returns fewer, the grep is HOLLOW and the test is REJECTED — the AST test is the authoritative completeness test (F1). The grep exists only as a belt for the AST test's braces.
- **Test:** per-site mutation drills — §6 table below (F15).
- **Live:** per-site JOIN queries pass (F7).

### D4 — Log the hidden `resume` write with distinguishable sites
Sites `<caller>+resume`, `<caller>+pin`, `<caller>+pin_retry` recorded per D2 above. This is not a separate deliverable so much as a naming rule the D2 tests already enforce; kept as its own line for card traceability.

**Acceptance (D4):** covered by `test_resume_then_pin_schedules_two_rows_in_order`, `test_resume_row_scheduled_after_pin_await_returns`, and the F7 live JOIN.

### D5 — AST completeness lint (F1, F5)
`quality/tests/test_hvac_climate_write_funnel_completeness.py`. Python AST walk over `custom_components/universal_room_automation/`; FAILS on any Call node meeting:

1. **Any of these call shapes:** `hass.services.async_call(...)`, `self.hass.services.async_call(...)`, `services.async_call(...)`, `hass.services.call(...)`, `hass.async_add_executor_job(hass.services.call, ...)`, or `hass.loop.run_in_executor(None, hass.services.call, ...)` (F5: executor-wrapped equivalents).
2. **Whose domain arg** (pos 0 for `async_call`/`call`; the corresponding position under the executor wrapper; or `domain=` kwarg) is either:
   - the string literal `"climate"`, OR
   - **non-literal** (a Name / Attribute / Subscript / f-string), UNLESS the enclosing module's file is in the reviewed `DYNAMIC_DOMAIN_ALLOWLIST` (currently one entry: `optimization.py`, reason `optimizer-shadow-actions-carded-for-later-routing`; F5).
3. **Aliasing failure (F5):** any `Assign` node in the codebase whose value is `hass.services.async_call` or `services.async_call` (i.e. `foo = hass.services.async_call`), OR any `ImportFrom` that binds `async_call` as a module-level name outside `hvac_setpoint.py`. Aliasing is itself a failure — the AST cannot follow aliases at analysis time.
4. **Exception:** Call nodes inside `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py` are allowed.

The test reports each failure as `<file>:<lineno>: <message>` so a developer can find it.

**F5 also delivers (D5-b, coordinator.py):** extend the refusal at `coordinator.py:1107-1123` from three literal verbs to `domain == "climate"` refuses ALL services. Chained routes via `automation.trigger` / `scene.turn_on` / `script.turn_on` / `homeassistant.turn_on` remain a documented open gap (AUDIT §1b tail) — Stage A closes only the direct-climate-domain hole.

**Acceptance (D5):**
- **Test:** run the completeness lint on develop-HEAD-plus-Stage-A → PASSES.
- **Test (mutation, F15):** for EACH migrated site, revert its funnel call to the original `hass.services.async_call("climate", ...)` in production source, run the lint → FAILS pointing at that file:line; restore. This is BOTH D5's authority test AND D3's per-site test.
- **Test (aliasing, F5):** add `_c = hass.services.async_call` in `hvac.py`; lint FAILS. Remove.
- **Test (non-literal domain, F5):** add `hass.services.async_call(some_var, ...)` in `hvac.py`; lint FAILS. Remove.
- **Test (allowlist, F5):** same non-literal call in `optimization.py`; lint PASSES.
- **Test:** AI-rule refusal — construct an `ExecuteAction` targeting `climate.set_hvac_mode` (or `climate.turn_off`) via `coordinator.py`'s dispatch; assert refusal returns the expected structured error and NO service is invoked.
- **Baseline authority for the grep sibling (F1):** run the multiline grep on the pre-migration commit → asserts ≥7 hits outside `hvac_setpoint.py`. This is recorded once in the test module as a smoke, then the post-migration state is checked.

### D6 — Documentation write-back
- Update `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in the SAME commit as the ship (§0.4). §4.1 gains `emit_set_hvac_mode`; §4.3 flips to "URA-originated wire writes: YES — one `climate_write` row each"; the AI-rule refusal note is added; header snapshot bumped.
- README `docs/readmes/README_v<version>.md` — post-restart validation table (F7 JOINs + bypass bound) replaces the prospective Live block.

---

## 6. Mutation-drill table — Reviewer C + orchestrator hand-check (F15)

For every migrated site AND for the funnel row-schedule helper, mutate ONE thing in production source, run the suite, confirm a NAMED test fails, restore.

| Site / target | Mutation | Expected failing test(s) |
|---|---|---|
| `emit_set_hvac_mode` wire call | delete the `await hass.services.async_call(...)` line | `test_emit_set_hvac_mode_happy_path` (service-call assertion) |
| Row-schedule helper | delete the `hass.async_create_task(...)` line | `test_row_shape_has_all_required_keys`, `test_dedup_off_two_identical_1s`, every per-site row test |
| `_schedule_climate_write_row` **`await` mutation** | change `hass.async_create_task(...)` → `await hass.async_create_task(...)` (illegal-shape mutation — coroutine still runs but the wrapping becomes non-fire-and-forget) | `test_emit_set_hvac_mode_never_awaits_log` |
| B1 heat_cool enforcer | change verb literal | `test_hvac_heat_cool_enforcer_writes_mode_row_with_site_B1` |
| B2 egress pause | change `"off"` → `"heat_cool"` | `test_hvac_egress_pause_writes_mode_off_row_with_site_B2` |
| B3 egress resume | replace funnel call with `pass` | `test_hvac_egress_resume_writes_mode_row_with_site_B3` (also asserts preset half at `:795` still fires) |
| B4 override revert | change verb | `test_hvac_override_revert_writes_mode_row_with_site_B4` |
| B5 AC reset off | change `"off"` → saved | `test_hvac_ac_reset_off_writes_mode_row_with_site_B5` |
| B6 AC reset restore | change target_mode → `"off"` | `test_hvac_ac_reset_restore_writes_mode_row_with_site_B6` |
| B7 AC reset retry | delete retry branch | `test_hvac_ac_reset_retry_writes_mode_row_with_site_B7` |
| S6-fix nudge restore setpoints | remove `site="S6_..."` kwarg | `TypeError` at call time (F3) + a targeted `test_S6_kwargs_required` |
| S7-fix nudge restore preset | remove `zone_id` kwarg | `TypeError` + `test_S7_kwargs_required` |
| SA-startup audit nudge preset restore | remove `reason` kwarg | `TypeError` + `test_startup_audit_kwargs_required` |
| **F15 per-site routing drill** | for EACH migrated site, replace the `emit_set_*` call with the ORIGINAL raw `hass.services.async_call("climate", ...)` | (i) D5 AST lint FAILS at that file:line; (ii) that site's row-content test FAILS (row absent) |

**Orchestrator hand-check before deploy (Tier 2-DB standing policy, updated for F15):** re-grep `set_hvac_mode` and `services.async_call("climate"` across the tree (multiline); re-run TWO per-site routing drills (B2 the safety-off and one nudge site S5 or S6); confirm both drills go RED; restore; ship.

---

## 7. Live validation (Review D — feeds README write-back) — F7 per-site JOINs

Replace the rev-1 ±5 % cross-tab with per-site joins on the URA DB, run at 1 h and 24 h post-restart. All queries against `/config/universal_room_automation/data/universal_room_automation.db` via `ssh ha "python3 -"`.

1. **Nudge start ↔ S5 row (±5 s):** for every `ac_ramp_events.kind='nudge_started'` since restart, there must be exactly one `climate_write` row with `json_extract(details_json,'$.site')='S5_nudge_start'` on the same zone within [event_ts-5s, event_ts+5s]. Zero misses acceptance; any miss = falsification.
2. **Nudge restored ↔ S6 + S7 (+resume if triggered):** for every `nudge_restored`, exactly one `S6_nudge_restore_setpoint` row AND one `S7_nudge_restore_preset` row on the same zone within ±5 s; if `_needs_resume_first` fired, additionally one `S7_nudge_restore_preset+resume`.
3. **S1 preset flips ↔ `preset_change`:** for every `ura_activity_log` row with `action='preset_change'` since restart, exactly one paired `action='climate_write'` row with `site` starting `S1_` (± the same second — same code path emits both synchronously).
4. **`hvac_excursion_events` ↔ site rows:** for every non-nudge excursion event since restart, at least one `climate_write` row from the matching site (S3/S11/S12/S13/egress) with the same `excursion_id` in `details_json`.
5. **`excursion_id` correlation (F6):** for a 24 h sample, `climate_write` rows whose `site` starts `S5_`, `S6_`, or `S7_` carry an `excursion_id` matching an `ac_ramp_events.excursion_id` on the same zone at the same second.
6. **Bypass bound (F7):** query the HA recorder for `climate.*` `preset_mode`/`temperature`/`hvac_mode` changes since restart. For each recorder change with no `climate_write` row on that entity in the prior 90 s (accommodating Carrier's C16 30-min-poll + 5-min post-write guard by the LOOSER side), classify as `external_or_bypass`. Compute daily count. Baseline: same query on the pre-ship day. Acceptance: post-ship `external_or_bypass` count ≤ pre-ship baseline + 10 % (any increase = a URA bypass that Stage A missed; investigate before README write-back closes).
7. **C2-field presence:** `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND (json_extract(details_json,'$.values_before.preset_mode') IS NULL AND json_extract(details_json,'$.values_before.hold_activity') IS NULL) AND timestamp > <restart>` — should be a small minority (entity `unavailable` at write time). If majority, the synchronous read is failing.
8. **AST completeness lint** passes in CI on the shipped commit.

Every passing/failing result becomes a row in the README `Validated <date>` table.

---

## 8. Sequencing — coexistence with v5.103.15 (unchanged intent, hardened for F13)

`feature/hvac-live-room-establishment` (v5.103.15, in-flight fix-ups) edits `hvac.py`/`hvac_zones.py`. Stage A also edits `hvac.py` (S1, B1, possibly S10) plus `hvac_setpoint.py`, `hvac_override.py`, `hvac_egress.py`, `hvac_excursion.py`.

**Rules:**
1. Stage A build does NOT dispatch until v5.103.15 has merged to `develop`.
2. Before build, the builder re-resolves EVERY file:line in this plan by symbol — the D3 tables above are labelled TENTATIVE per F13. Real numbers on develop right now (per orchestrator's own greps for F13): `hvac.py:1928` (B1), `hvac_override.py:3520` (B4), `:3889` (B5), `:4007` (B6), `:4042` (B7), `hvac_egress.py:683` (B2), `:779` (B3). Any post-merge shift → update D3 table in place before build.
3. If v5.103.15 introduces a NEW raw `hass.services.async_call("climate", ...)`, add it to D3 and block ship until migrated. The D5 lint catches it either way.
4. Stage A ships behind v5.103.15 in the release order.

---

## 9. Non-goals (Stage A)

- NO brand strategy / no `ZoneThermostat` class / no `write_effective_preset` — Stage B (Tier 3).
- NO presets-only return path — Stage B.
- NO coherence rule — Stage B.
- NO lockout/arrester/comfort-grace change.
- NO change to DPM caller-side preset opinion (HIGH-2) — separate point-gate.
- NO change to `return_excursion` behaviour (C13).
- NO row for `set_activity_setpoint` — URA does not call it today; if Stage B adopts it, that funnel gets a row shape then.
- NO change to optimizer shadow actions (`optimization.py:3546`, `:3688`) — explicit INV-A exclusion + reviewed `DYNAMIC_DOMAIN_ALLOWLIST` entry, carded for later.
- NO fix to the chained-route escape hatch (`coordinator.py` via `automation.trigger` / `scene.turn_on` / `script.turn_on` / `homeassistant.turn_on`) — Stage A closes only the direct-`climate`-domain hole in AI rules (F5).
- NO occupancy fast path — W2.

---

## 10. Numbers get knobs (F9 corrected)

Stage A adds exactly ONE runtime constant + ONE lint constant. Both rung 1 (module constant — change requires review) because they govern log-shape/retention, not operator-observable behaviour.

| Constant | Value | Home | Why rung 1 |
|---|---|---|---|
| `CLIMATE_WRITE_LOG_IMPORTANCE` | `"notable"` | `hvac_const.py` | F9: `info` gets pruned at 7 days (`database.py:5827-5834`); `notable`/`critical` at 30 days. Diagnosis of a stranded-manual episode needs ≥30 d (longest observed strand ~11 h, but recurrence analysis across months needs the window). |
| `DYNAMIC_DOMAIN_ALLOWLIST` | `frozenset({"optimization.py"})` with a reason string map | `hvac_const.py` (or a new `climate_write_lint_const.py` if hvac_const has ordering concerns) | F5: any addition is a reviewed escape from INV-A; the constant carries owner card ids so future audits find them. |

No config-flow field, no entity — Stage A behaviour is neutral.

---

## 11. Tier justification (unchanged, hardened for F5)

**Tier 2-DB.** Regression-prone by standing policy; touches every URA-originated thermostat write across a live 3-zone infinite-holds Carrier fleet. Framings:

- **Review A — local correctness + payload equivalence.** For each D3 site: `service_data` byte-identical; every funnel call carries required kwargs (F3); every borrow site forwards `excursion_id` (F6); row shape complete (F12).
- **Review B — integration / cross-coordinator / restart.** Stage A adds no dispatch loop and no consumer that drives a decision. Row-emit is fire-and-forget (F2) so a DB stall cannot back-pressure the wire path. `_schedule_climate_write_row` is boot-safe (F14). AI-rule refusal (F5) tested for the shape returned to callers of the coordinator's action pipeline.
- **Review C — test authority via per-site source mutation.** §6 table + F15 per-site routing drill. Reviewer C personally runs at least three mutations (B2 safety-off, one nudge site, one AI-rule refusal) and confirms named tests go red.

**Plan review (mandatory Tier 2+):** already run — this is rev 2. Any subsequent revision goes through another single-pass plan review before build dispatch.

**Not Tier 3.** Stage A is behaviour-neutral, diagnostic-only, no cost/safety invariant to break. Stage B IS Tier 3 and requires operator go before scoping.

---

## 12. Open questions for the operator

None. All rev-1 open questions and all rev-2 fix-up decisions have been resolved by the state-of-play + AUDIT + orchestrator's own F5 scope call (AI rules IN, optimizer shadow OUT + allowlisted). Stage B is where operator calls (adopt `set_activity_setpoint`? presets-only-returns policy? coherence rule?) live — not here.

---

## Change log — F1-F15 mapping (rev 1 → rev 2)

| Fix | Where addressed in rev 2 |
|---|---|
| **F1 CRIT** hollow greps + AST authority | §1 falsifiers; D3 Verify (AST + F1 multiline grep with pre-migration ≥7-hits baseline as its own acceptance); D5 (AST lint is the completeness authority). |
| **F2 CRIT** no awaited logging; synchronous capture; scheduled AFTER wire; resume-before-pin ordering | §1 INV-A wording ("scheduled before the funnel returns or raises"); §3a producer note; §4c `ts_issued`/`ts_returned`; D2 spec (5 call sites, resume scheduled between the two awaits per `hvac_setpoint.py:350-353`); D1 `test_emit_set_hvac_mode_never_awaits_log`; D2 `test_resume_row_scheduled_after_pin_await_returns`; §6 mutation table (delete row-schedule = red; add `await` = red). |
| **F3 HIGH** required kwargs `site`/`zone_id`/`reason` on all three funnels; fix S6/S7 kwargs | D1 signature; D2 kwarg forwarding; D3 new rows S6-fix (`hvac_override.py:4595`) and S7-fix (`:4638`); AST test `test_every_emit_set_call_passes_site_zone_reason`; §6 mutation table `TypeError` drills. |
| **F4 HIGH** direct `database.log_activity`; no dedup; no signal; no bus event; two-identical/two-different tests | §2c REUSE row-writer row; §3a producer; §4b table decision paragraph; D2 tests `test_dedup_off_two_identical_1s`, `test_no_signal_no_bus_event`, `test_two_different_writes_within_30s`. |
| **F5 HIGH** AI rules block ALL climate; optimizer excluded + reviewed allowlist; aliasing = failure; non-literal domain gated | §1 INV-A "exclusion" paragraph; §2c new rows (AI-rule extension, `DYNAMIC_DOMAIN_ALLOWLIST`); §5 D5 lint spec bullets 1-4 + tests (allowlist / aliasing / non-literal / AI-rule refusal); §9 non-goals; §10 knob table. |
| **F6 HIGH** C2 fields `preset_mode`+`hold_activity` synchronous; excursion_id explicit kwarg forwarded from borrow tokens | §0 state-of-play read; §4c row shape (`values_before.preset_mode`/`hold_activity`, `excursion_id`, "null-with-key"); D2 spec + tests `test_c2_fields_read_synchronously_before_wire`, `test_excursion_id_forwarded_from_borrow_site`; §7 live JOIN 4-5 + presence check 7. |
| **F7 HIGH** replace ±5 % cross-tab with per-site joins + bypass bound | §7 replaced with 8 discriminating queries incl. bypass classification vs pre-ship baseline. |
| **F8** measured rates recorded, share ≈ 10 %, not <1 % | §4a table with real 7-day counts. |
| **F9** importance = `"notable"` for 30-day retention | §4c row shape; §10 knob table with prune-window citation `database.py:5827-5834`. |
| **F10** `blocking` required kwarg on `emit_set_hvac_mode`; per-site current values listed | D1 signature; D3 table `blocking` column with citations. |
| **F11** one row per attempted wire call; helper called from 5 sites; no raise/swallow/return change | §1 falsifiers; §3a producer; D2 "sites the helper is called from (exactly 5)" + `test_row_helper_wire_raise_semantics_unchanged`. |
| **F12** `values_after` = exact service_data sent; add `ts_issued`, `ts_returned`, `blocking` | §4c row shape; D2 `test_row_shape_carries_ts_issued_before_ts_returned`. |
| **F13** add `hvac_excursion.py:1131`; fix B4 description; re-resolve file:lines by symbol | D3 new SA-startup row; D3 B4 note ("`suppress()` after + conditional"); §8 sequencing rule 2 with real develop-current numbers. |
| **F14** row helper guards `hass.data` like `_log_deferred_write`; never raises | §2c REUSE row; §3a producer; D2 `test_row_helper_never_raises_when_hass_data_missing` + `_log_deferred_write` citation `:121-128`. |
| **F15** per-site routing drill: replace funnel call with raw `async_call` → AST + row test both RED | §5 D3 Verify (AST) + D5 acceptance + §6 mutation table final row + orchestrator hand-check. |

Rev 2 file complete. All rev-1 language superseded IN PLACE per orchestrator instruction; no appendix.
