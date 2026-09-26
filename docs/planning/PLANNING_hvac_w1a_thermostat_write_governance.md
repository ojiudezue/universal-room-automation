# PLANNING — HVAC W1 Stage A: Thermostat Write Governance (behaviour-neutral)

**Card:** HVAC-W1-THERMOSTAT-DEFINITION (Stage A only)
**Children in scope:** HVAC-SETHVACMODE-CHOKEPOINT-1 (incl. `scope_added_2026_09_25_record_every_write`), phase-1 slice of HVAC-THERMOSTAT-ABSTRACTION-1, capability-gate half of HVAC-PRESET-WRITE-STRATEGY-1 (already shipped v5.103.2 — nothing new here)
**Branch base:** `develop` (this plan builds ON TOP of `feature/hvac-live-room-establishment` v5.103.15 AFTER it merges — see §Sequencing)
**Tier:** **Tier 2-DB** (three framing-disjoint reviews + plan review + live validation + README write-back). Regression-prone: touches every thermostat write in a live 3-zone house.
**Stage A is BEHAVIOUR-NEUTRAL.** No gate, value, ordering, or timing change. Adds a third funnel + one durable log row per wire write + a completeness lint. No brand strategy, no presets-only returns, no coherence rule — Stage B (Tier 3, operator go).

---

## 0. State-of-play acknowledgement (MANDATORY)

I have read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` **completely** — snapshot `develop @5072deaaf` 2026-09-26 ~02:30 CDT. This plan does **not** re-litigate:

- **§4.1** — funnels `emit_set_temperature` (`hvac_setpoint.py:223-279`) and `emit_set_preset_mode` (`:282-410`) exist; **`emit_set_hvac_mode` does not**.
- **§4.2** — 7 raw `set_hvac_mode` sites are enumerated; nudge is fully funnelled; `return_excursion` performs **zero** wire writes (§6 / C13); each SITE emits (a) set_temperature → (b) set_preset_mode → (c) set_hvac_mode itself.
- **§4.3** — `ura_activity_log` records `preset_change` only; `set_temperature`/`set_hvac_mode` land in `ac_ramp_events`/`hvac_excursion_events`/INFO logs; recorder context cannot attribute human-vs-URA. This is the observability gap Stage A closes.
- **§5** — Carrier semantics (status vs config feed, `set_temperature` forces manual, `infinite_holds=True`, `resume_schedule`, upstream `set_activity_setpoint` PR #427). Stage A does not depend on any of this — it just needs to *log* whatever the funnel already emits.
- **§6** — `return_excursion` is bookkeeping only; the ordering and mode-restore live at each call site.
- **§10** — corrections ledger. In particular: C1 (`ura_activity_log` never records set_temperature) is the exact hole Stage A fills; C13 (return_excursion writes nothing) is why the row must be emitted **inside the funnel**, not inside excursion bookkeeping.

Precedence rule from §0.2: code at cited file:line wins. If I find code that contradicts this plan's citations, the code wins and the plan is wrong — bring it back for a re-scope, do not silently diverge.

---

## 1. Falsifiable invariant (Stage A goal — the single property the cycle must guarantee)

> **INV-A:** For every wire-level climate service call URA issues (`set_temperature`, `set_preset_mode`, `set_hvac_mode`) on any zone, exactly one row lands in the write log within the same event-loop tick as the service call, carrying the verb, entity_id, zone_id, site id, reason, before/after values (where knowable), and excursion id (when in a borrow). No URA-originated climate write reaches `hass.services.async_call("climate", ...)` outside a funnel.

Falsifiers (D must go looking for these):
- A URA code path issues a climate service call and **zero** rows appear (bypass).
- A URA code path issues one service call and **two** rows appear (double-log, e.g. funnel logs + wrapper also logs).
- A row is written but the service call raised before the wire (must not log until after `await async_call`; or, symmetrically, must log the attempt with `wire_ok=False`).
- A future PR adds `hass.services.async_call("climate", verb, ...)` outside `hvac_setpoint.py` and CI passes.
- A row lacks any of: verb, entity_id, zone_id, site, reason. Nulls in those columns = falsification.

Non-falsifiers (out of scope — do not conflate with INV-A):
- Whether the wire write is *correct* (right preset, right values). Stage B.
- Whether the borrow ordering is right, or whether `manual` should be treated as human. Stage B.
- Whether the row can distinguish URA-late-echo from a human write on the thermostat. Recorder-side; Stage B.

---

## 2. Institutional context verified

### 2a. Design docs read (end-to-end this session)
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — full read (§0 through §12).
- `docs/planning/AUDIT_thermostat_write_paths_2026_09_16.md` — full read (§0-§8). Confirms 7 raw sites, all `set_hvac_mode`, all `climate` verb bypasses; funnel path is complete for the other two verbs.

### 2b. Kanban cards read
- `HVAC-W1-THERMOSTAT-DEFINITION` (kanban.data.yaml:1804-1820) — parent, Stage A/B split in `next`.
- `HVAC-SETHVACMODE-CHOKEPOINT-1` (kanban.data.yaml:2037-2086) — scope_added_2026_09_25_record_every_write folded into Stage A per operator ("biggest lever").
- `HVAC-THERMOSTAT-ABSTRACTION-1` (kanban.data.yaml:10609+) — Phase 1 = Stage A here; Phase 2 (ZoneThermostat handle, brand strategy) = Stage B, deferred.
- `HVAC-PRESET-WRITE-STRATEGY-1` (kanban.data.yaml:10744+) — SUBSUMED_2026_09_16; capability-gate half already shipped v5.103.2; nothing to build in Stage A.

### 2c. Prior-art scan (code) — REUSE / NEW per proposed piece
| Proposed piece | REUSE / NEW | Evidence |
|---|---|---|
| Third-verb funnel `emit_set_hvac_mode` | **NEW — no equivalent** | Greps for `emit_set_hvac_mode`, `set_hvac_mode.*chokepoint`, `set_hvac_mode.*funnel` return 0 hits (AUDIT §1b line 15; state-of-play §4.1). All 7 sites are raw `hass.services.async_call("climate","set_hvac_mode",...)` (state-of-play §4.2 line B1-B7). |
| Site/zone/reason plumbing signature | **REUSE** — mirror `emit_set_preset_mode` kwargs | `hvac_setpoint.py:282-410` already carries `site: str, zone_id: str \| None, reason: str \| None`. Same shape for the new funnel. |
| Optional `gate` callable | **REUSE pattern**; Stage A wires it as `gate=None` on every migrated site | `hvac_setpoint.py:8-23` docstring (ARREST-COMFORT-1 Cycle A); operator-doc says safety-side mode writes (egress off, AC reset) should NOT be gated by comfort delay (AUDIT §5 note). Stage A preserves current behaviour: no gate on any of the 7 sites — matches how they run today. |
| Durable per-write log row | **REUSE `ura_activity_log`** (see §4 table decision) | Table + writer already exist: `database.py:1351-1369` (DDL), `activity_logger.py:51-` (`ActivityLogger.log(coordinator, action, ...)`), WS API `websocket_api.py:173`, sensor consumers `sensor.py:16081` `_handle_activity_logged`, prune loop `database.py:5824 prune_activity_log`. Retention + dedup + dispatch already wired. |
| New `action` value `climate_write` | **NEW** action string (no schema change) | Grep for `action.*climate_write` / `climate_write` in `activity_logger.py`, `sensor.py`, `websocket_api.py`, `database.py` = 0 hits. `ura_activity_log.action` is a free-text column (`database.py:1356`); adding a new value is additive. Prior art for similar per-write action strings: `preset_change` (`hvac.py:2716-2748`), `preset_change_locked_out` (`hvac.py:2504-2519`), `override_detected`, `comfort_delay_deferred_write` (`hvac_setpoint.py:108-159`), `pool_activity_log` (`energy_pool.py:184`). Same pattern. |
| Details schema | **NEW keys in `details_json`** (free-form column) | `details_json TEXT` (`database.py:1361`). Reuses existing JSON-blob convention; no migration. |
| AST/grep completeness lint | **NEW** (Stage A ships it) | No test enforces "no raw climate.async_call outside hvac_setpoint.py" today. `quality/tests/` grep: 0 hits for `set_hvac_mode.*chokepoint`. Add as `quality/tests/test_hvac_climate_write_funnel_completeness.py`. |
| Migration of 7 raw sites | **REUSE existing helpers** (`_supports_heat_cool` capability check, `suppress()` handshake, `auto_release_on_incomplete` CM) — the wire-call line moves inside the funnel, everything around it stays. | Sites listed in AUDIT §1b B1-B7 (state-of-play §4.2). |

### 2d. Prior-art scan (plans + memory)
- `docs/planning/AUDIT_thermostat_write_paths_2026_09_16.md` — the source-of-truth inventory for this Stage A. Recommendation §8.1: "advance Phase 1 ... explicitly NOT the fix for HIGH-2 or the oscillation" — Stage A honours that.
- `docs/planning/PLANNING_hvac_governed_excursion.md` (rev-6) — referenced from state-of-play §6; do NOT rebuild the stripped lease gate.
- Memory `feedback_do_robust_fix_not_bandaid_and_card` — Stage A does the funnel + log as one shipment (they are the same surface); it does NOT try to do Stage B's brand strategy in the same round.
- Memory `feedback_tier2db_for_regression_prone` — Stage A is regression-prone (touches every URA thermostat write) → standing policy = Tier 2-DB.
- Memory `feedback_tier2plus_prior_art_scan` — this section is that scan.
- Memory `project_optimizer_db_write_flood_incident_2026_06_09` — the per-channel write-volume review is applied in §4 (table decision) below.

### 2e. Code locations surveyed
- `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py` (funnels + `_needs_resume_first`, `_capture_preset_reason`)
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` (S1, S10, heat_cool enforcer B1)
- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py` (S3-S9, B4-B7)
- `custom_components/universal_room_automation/domain_coordinators/hvac_egress.py` (egress pause/resume B2/B3)
- `custom_components/universal_room_automation/domain_coordinators/hvac_excursion.py` (bookkeeping — no writes; confirms C13)
- `custom_components/universal_room_automation/domain_coordinators/hvac_predict.py` (S11/S12/S13 funnelled)
- `custom_components/universal_room_automation/activity_logger.py` (writer)
- `custom_components/universal_room_automation/database.py:1351-1369, 5804, 5824-5850` (DDL + INSERT + prune)
- `custom_components/universal_room_automation/websocket_api.py:173` (query surface)
- `custom_components/universal_room_automation/sensor.py:16081` (`_handle_activity_logged`)

---

## 3. Producer / Consumer analysis

### 3a. PRODUCER (per verb, after Stage A)
- All three funnels live in `hvac_setpoint.py`. Each is the SOLE producer of a `climate_write` row for its verb. Dependency: `ActivityLogger.log()` (already boot-safe, `never raises`, uses DB write queue — `activity_logger.py:7-8`). Dependency health: the same writer feeds `preset_change` today with no known incidents on this surface.
- The row is emitted **inside the funnel, AFTER `await hass.services.async_call(...)` returns without raising**, so a row implies the wire write completed (or the integration accepted it — cloud-side ack is Stage B territory). On exception the funnel logs a `climate_write` row with `wire_ok: false` and the exception class in `details_json`, then re-raises — this preserves error propagation for callers that use `suppress()`.
- **No new dependency on Carrier / brand-specific state.** The funnel does not read `hold_activity` beyond what `_needs_resume_first` already reads (§4.4). Row values come from the funnel's own args + a pre-call `hass.states.get(entity_id)` snapshot for `values_before` (best-effort; None acceptable — see §5 non-goals).

### 3b. CONSUMERS (who reads a `climate_write` row after Stage A)
- **New (Stage A):**
  - The completeness test (§Deliverable D5) reads rows to verify a specific mutation-drilled site emits a row.
  - **Live validation query** (§7): a `ssh ha sqlite3` count over 1 h post-restart to confirm the row rate matches wire writes.
- **Existing infra picks it up for free** — but Stage A does NOT rely on them and does NOT add wiring:
  - WS API `ura/logs/activity` (`websocket_api.py:173`) — dashboards can query the new action verbatim.
  - `SIGNAL_ACTIVITY_LOGGED` dispatch — any existing sensor that filters on action name is unaffected (new action, no collision).
  - Prune loop treats it like every other row (`database.py:5824`) — 30 d retention like the rest.
- **No trust decisions** consume `climate_write` in Stage A. Diagnostic only. (Stage B will consume it for provenance classification: URA-vs-external.)
- **Discriminating consumer test** (per operator's producer/consumer rule): a Stage A row rate falling to zero would be indistinguishable from URA making no writes. So the acceptance test (§Deliverable D5) drives a KNOWN write (e.g. an S1 preset flip via a forced house-state change in-suite) and asserts a row lands with the right verb + site; and separately, mutates each of the 7 migrated sites and asserts the row goes missing (per-site mutation drill).

---

## 4. Table decision (measure-before-build)

### 4a. Measured write rates (from state-of-play §4.3, §9.1 — live URA DB, 2026-09-25/26)

The state-of-play already carries the measurements we need; no additional probe required at plan time (measure-before-build is satisfied by the existing forensic §9.1 read).

| Source | Measured | Extrapolated wire writes/day (3 zones) |
|---|---|---|
| `ac_ramp_events` zone_1 since 2026-08-26 (30 d) | 1,827 rows (state-of-play §4.3) | ~61 rows/day/zone → ~180 rows/day/3 zones. Each nudge cycle emits ~3 event rows (`nudge_started`, `nudge_restored`, `settled_verdict`) → ~60 nudge-side WIRE writes/day/3 zones (start + restore setpoint + snapshot-preset restore = 3 wire writes per cycle × ~20 cycles/day/3 zones — matches §9.1 "n=48 nudge starts in 130 h on zone_1" ≈ 9/day/zone) |
| `ura_activity_log` `preset_change` (S1) | §9.1: 88 manual entries in 130 h zone_1, ~26% attributable to S1 preset flips → ~4/day zone_1 preset writes | ~12 preset writes/day/3 zones |
| `hvac_excursion_events` non-nudge (banking/preheat/egress) | Sparse — days without events, seasonal (§9.1) | ≤10 writes/day/3 zones typical |
| Heat_cool enforcer B1, AC reset B5-B7 | Rare (limits: hard-reset budget 2/day/zone; heat_cool drift correction opportunistic) | ≤6 writes/day/3 zones typical |
| **Total wire writes / day (all verbs, 3 zones)** | | **~90-120 writes/day steady-state, peak days ~200** |

Monthly volume ~3-6k rows. `ura_activity_log` today already carries `preset_change`, `preset_change_locked_out`, `override_detected`, `comfort_delay_deferred_write`, `pool_activity_log`, safety events, per-room occupancy events, light events — far higher rate. Adding ~120/day is trivial relative to existing baseline.

### 4b. Decision: **REUSE `ura_activity_log`** (no new table)

Justification:
1. **Volume fits** — ~120 rows/day is <1% of current activity-log volume; write-queue load negligible. This is the exact per-channel volume review the Optimizer write-flood incident (2026-06-09) demands; the answer here is safe.
2. **Retention matches need** — 30 d default via `prune_activity_log`; enough to diagnose any strand ≤4 weeks old (§9.1 strands were 88-661 min).
3. **Reader stack ready** — WS API, sensor dispatch, dedup, importance ladder, tz-aware timestamp all wired. Zero new consumer code.
4. **Schema fits** — `coordinator`, `action`, `zone`, `entity_id`, `details_json` cover the row exactly; only NEW value is `action="climate_write"`.
5. **No migration** — additive action string; existing readers ignore unknown actions.

**Rejected alternative:** dedicated `hvac_climate_writes` table. Would duplicate DDL + prune + WS + dispatch for a channel that fits comfortably in the shared log. Would only be justified if the row shape diverged from `ura_activity_log`'s (it doesn't) or if volume threatened the shared log's fairness (it doesn't).

### 4c. Row shape (finalized)
```
coordinator = "hvac"
action      = "climate_write"
zone        = <zone_id>          # 'zone_1' / 'zone_2' / 'zone_3'
entity_id   = <climate.entity>
importance  = "info"             # notable on wire_ok=false; critical never (safety events already covered elsewhere)
description = "<verb> zone=<z> site=<site> reason=<reason>"
details_json = {
  "verb":            "set_temperature" | "set_preset_mode" | "set_hvac_mode",
  "site":            "<site tag e.g. S5_nudge_start / B2_egress_pause>",
  "reason":          "<caller-supplied>",
  "wire_ok":         true|false,
  "exc":             "<class name if wire_ok=false>",
  "excursion_id":    "<if in a borrow, else null>",
  "values_before":   {"preset_mode": "...", "target_low": ..., "target_high": ..., "hvac_mode": "..."},
  "values_after":    {...requested...},
  "hold_activity_before": "<if funnel already read it (preset path), else null>"
}
```
`values_before` is best-effort from `hass.states.get(entity_id)` at emit time; null-safe (a boot-transient unavailable state records `null` for all four; row still lands).

---

## 5. Deliverables

### D1 — Add `emit_set_hvac_mode` funnel in `hvac_setpoint.py`
Mirror `emit_set_preset_mode` signature: `(hass, entity_id, hvac_mode, *, site, zone_id, reason, gate=None, blocking=False)`. Wraps ONE `hass.services.async_call("climate", "set_hvac_mode", ...)` inside a try/except that ALWAYS logs a `climate_write` row (§4c) after the await, then re-raises on exception. No brand strategy, no capability gate (safety-side callers do their own `_supports_heat_cool` check today — Stage A preserves that; the funnel is verb-scoped, not intent-scoped, per AUDIT §5).

**Acceptance criteria (D1):**
- **Verify:** grep `def emit_set_hvac_mode` in `hvac_setpoint.py` returns exactly one hit; its body issues exactly one `services.async_call("climate", "set_hvac_mode", ...)`.
- **Test:** `quality/tests/test_hvac_setpoint_funnel.py::test_emit_set_hvac_mode_writes_wire_and_row` — real fake hass + real ActivityLogger stub with in-memory sink; assert one service call, one row with `verb=set_hvac_mode`, `site=<given>`, `wire_ok=True`.
- **Test:** exception path — service raises `HomeAssistantError`; assert row lands with `wire_ok=False, exc="HomeAssistantError"` AND exception propagates.
- **Live:** after deploy, `ssh ha sqlite3 /config/universal_room_automation/data/universal_room_automation.db "SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(details_json,'$.verb')='set_hvac_mode' AND timestamp > datetime('now','-1 hour')"` returns ≥1 within the first hour that any of the 7 sites fires (bounded: egress pause OR AC reset OR heat_cool enforcer). If no natural trigger in the first hour, discriminator is the D5 mutation test; disposition = one-shot query, not soak.

### D2 — Add durable `climate_write` row emission inside all three funnels
Extend `emit_set_temperature` and `emit_set_preset_mode` with the SAME row-emit block used in D1's new funnel. `emit_set_preset_mode` emits ONE row per outer call — including the resume-then-pin path (§4.1) which internally does resume + pin as TWO service calls: log BOTH, each with its own row (`site=<caller>+resume` and `site=<caller>+pin`). This makes the hidden `resume` write visible per Stage A scope item (3).

**Acceptance criteria (D2):**
- **Verify:** any `emit_set_*` call in the codebase produces exactly one `climate_write` row per underlying wire call. Grep confirms the `_log_climate_write` helper is called from exactly three places (once per funnel + once per resume-in-pin).
- **Test:** `test_emit_set_preset_mode_resume_then_pin_logs_two_rows` — force the resume path (mock `hold_activity=manual`), assert two rows with sites `<caller>+resume` and `<caller>+pin`, in that order.
- **Test:** existing `preset_change` row (`hvac.py:2716-2748`) STILL lands unchanged — Stage A adds the new `climate_write` row alongside; it does NOT replace `preset_change`. Assert both rows present for an S1 write.
- **Live:** `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND timestamp > <restart_ts>` matches, within ±5 %, the sum of (a) `ac_ramp_events` where kind IN (`nudge_started`, `nudge_restored`) × 1 row per wire + (b) `ura_activity_log` `preset_change` rows + (c) `hvac_excursion_events` non-nudge kinds counted once per site. Ratio computed at 1 h and 24 h.
- **Discriminating live check:** a period with zero wire writes (e.g. mid-day 2 h with no house-state flip and nudges disabled by kWh threshold) → zero new `climate_write` rows in that window. If rows appear anyway, Stage A over-logged. If wire writes happen and rows don't, Stage A under-logged.

### D3 — Migrate the 7 raw `set_hvac_mode` sites through `emit_set_hvac_mode`
Per state-of-play §4.2 / AUDIT §1b:

| # | File:line (develop @5072deaaf) | Site tag | Notes for migration |
|---|---|---|---|
| B1 | `hvac.py:1731` | `B1_heat_cool_enforcer` | `suppress()` handshake wraps caller side; move only the wire call into funnel |
| B2 | `hvac_egress.py:682` | `B2_egress_pause` | inside `auto_release_on_incomplete` CM — bookkeeping stays outside; only wire call moves |
| B3 | `hvac_egress.py:778` | `B3_egress_resume_mode` | mode half only; preset half already funnelled at `:795` |
| B4 | `hvac_override.py:3447` | `B4_override_revert_heat_cool` | sibling of B1; different site tag |
| B5 | `hvac_override.py:3816` | `B5_ac_reset_off` | blocking=True preserved |
| B6 | `hvac_override.py:3934` | `B6_ac_reset_restore` | blocking=True preserved |
| B7 | `hvac_override.py:3969` | `B7_ac_reset_restore_retry` | attempt<=2 preserved |

**Line numbers may shift after v5.103.15 merge — re-resolve by symbol before edit (§Sequencing).**

**Byte-identical constraints:**
- No gate. Every migration passes `gate=None`. Comfort-delay is deliberately not applied to safety-side mode writes (AUDIT §5).
- Preserve `blocking=True` on B5-B7.
- Preserve the caller-side `_supports_heat_cool` capability check (do NOT move it into the funnel — Stage A is verb-scoped).
- Preserve the caller-side `suppress()` on B1/B4.
- Preserve `auto_release_on_incomplete` wrapping on B2/B3.
- Same `service_data` shape → same wire payload.

**Acceptance criteria (D3):**
- **Verify:** `grep -n 'services.async_call.*climate.*set_hvac_mode' custom_components/universal_room_automation/` returns exactly ONE hit — the funnel body in `hvac_setpoint.py`. Zero hits outside.
- **Test:** per-site mutation drill (D3 also drives D5) — see §6 table below.
- **Live:** the first natural fire of each site (may take days for AC reset) lands one `climate_write` row with the matching site tag. Because AC reset is rare, the D5 mutation test is the primary discriminator; the live check is corroborating.

### D4 — Log the hidden `resume` write
The resume-then-pin path in `emit_set_preset_mode` currently emits `resume` then the pinned preset as two separate service calls (`hvac_setpoint.py:311, 327, retry :348`). D2's row-emit already logs each; D4 is the explicit acceptance that resume rows land with distinguishable sites (`<caller>+resume`, `<caller>+pin`, `<caller>+pin_retry`).

**Acceptance criteria (D4):**
- **Verify:** grep `+resume` and `+pin` site tags in tests and in a 24 h live sample; both present for every S1/S4/(predict)/egress preset write that triggered a resume.
- **Test:** covered by D2's `test_emit_set_preset_mode_resume_then_pin_logs_two_rows`.
- **Live:** post-restart, first Bryant "anonymous manual" recovery episode records the `+resume` + `+pin` pair in `ura_activity_log`.

### D5 — AST/grep completeness lint (CI gate against future bypasses)
`quality/tests/test_hvac_climate_write_funnel_completeness.py` — Python AST walk (not regex, so string literals in comments/docstrings don't false-positive) over `custom_components/universal_room_automation/`:

- Find every `Call` node whose func resolves to `hass.services.async_call` OR `self.hass.services.async_call` OR `services.async_call` where the first arg is the string literal `"climate"`.
- Assert: every such Call lives inside `hvac_setpoint.py`.
- Any other file containing such a call FAILS the test with a clear error naming file:line.

Also grep-based sibling test (belt & suspenders — catches dynamic domain construction the AST test misses):
- `rg -n "async_call\(\s*['\"]climate['\"]" custom_components/universal_room_automation/` returns matches ONLY in `hvac_setpoint.py`.

**Acceptance criteria (D5):**
- **Test:** running the completeness test on develop-HEAD-plus-Stage-A passes; deliberately reverting any one D3 migration makes it fail with a message pointing at that file:line.
- **Test:** a synthetic PR that adds `hass.services.async_call("climate","set_preset_mode",...)` in `hvac.py` fails the test.

### D6 — Documentation write-back
- Update `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` **in the same commit as the ship** (per §0.4 update discipline): §4.1 gains `emit_set_hvac_mode`; §4.3 "Do we record everything?" flips to YES for URA-originated wire writes (verb, site, zone, reason, values, excursion_id); §10 gains no correction (Stage A resolves the C1 observability gap rather than proving a claim wrong — record the resolution under §4.3, not §10). Bump the header snapshot commit.
- README `docs/readmes/README_v<version>.md` — post-restart validation table replaces the prospective Live block per CLAUDE.md discipline.

---

## 6. Mutation-drill table (per migrated site — for Review C and pre-ship orchestrator hand-check)

For each site, the drill = mutate the site's payload in production source so the wire write is a NO-OP (e.g. change `data={"hvac_mode": target_mode}` to `data={}` or change entity_id to a non-existent `climate.does_not_exist`), run the suite, confirm a SPECIFIC named test fails, restore. A site whose bypass leaves the suite green is an untested site.

| Site | Mutation | Expected failing test |
|---|---|---|
| Funnel `emit_set_hvac_mode` | delete the `await hass.services.async_call(...)` line | `test_emit_set_hvac_mode_writes_wire_and_row` (row still lands but wire_ok=True + no service invocation → mock assert) |
| Funnel row-emit block | delete `await activity_logger.log(...)` | `test_emit_set_hvac_mode_writes_wire_and_row` (row absent) AND every D3 per-site test below |
| B1 heat_cool enforcer | change verb to `set_temperature` | `test_hvac_heat_cool_enforcer_writes_mode_row_with_site_B1` |
| B2 egress pause | change `"off"` → `"heat_cool"` | `test_hvac_egress_pause_writes_mode_off_row_with_site_B2` |
| B3 egress resume mode | delete the funnel call | `test_hvac_egress_resume_writes_mode_row_with_site_B3` (also: preset half at :795 still fires — asserts both rows) |
| B4 override revert heat_cool | change verb | `test_hvac_override_revert_writes_mode_row_with_site_B4` |
| B5 AC reset off | change `"off"` → `saved_mode` | `test_hvac_ac_reset_off_writes_mode_row_with_site_B5` |
| B6 AC reset restore | change target_mode → `"off"` | `test_hvac_ac_reset_restore_writes_mode_row_with_site_B6` |
| B7 AC reset retry | delete the retry branch | `test_hvac_ac_reset_retry_writes_mode_row_with_site_B7` (retry-path invocation asserted) |

**Orchestrator hand-check (Tier 2-DB standing policy):** before deploy, orchestrator re-greps every `set_hvac_mode` occurrence in the tree and re-runs one mutation (pick B2, the highest-blast-radius safety-off site); confirms the named test fails; restores; then ships.

---

## 7. Live validation (Review D — feeds README write-back)

After HA restart:

1. Row rate matches wire rate (D2 Live check): 1 h and 24 h SQL cross-tab.
2. Every naturally-fired site since restart shows at least one row (D3 Live). For rarely-fired sites (AC reset), the D5 mutation test is the discriminator; the live table records "not observed in window — synthetic test confirms wire".
3. Discriminating null-check (D2): a 2 h zero-write window shows zero `climate_write` rows.
4. `+resume`/`+pin` pair present for the first anonymous-manual recovery (D4 Live).
5. Completeness lint passes on the shipped tree (CI record).

README validation table replaces prospective bullets per CLAUDE.md.

---

## 8. Sequencing — coexistence with v5.103.15 (live-room establishment)

`feature/hvac-live-room-establishment` (v5.103.15, in-flight round-3 review; state-of-play §11 row 0) edits `hvac.py` and `hvac_zones.py`. Stage A edits `hvac.py` (S1 preset call site at `hvac.py:2275` per AUDIT §1a; heat_cool enforcer B1 at `:1731`; possibly S10 at `:2568`) and `hvac_override.py`, `hvac_egress.py`, `hvac_setpoint.py`, `hvac_excursion.py`.

**Overlap risk:** v5.103.15's fix-up rounds touch establishment logic in `hvac.py`/`hvac_zones.py`. Concrete potential conflicts:
- `hvac.py` S1 flip logic (`:2013`, `:2275`, `:2504-2539` lockout path) — v5.103.15 may add live-room conjuncts around retreat but is not expected to move the S1 preset write itself. Verify at merge.
- No expected overlap with `hvac_override.py`, `hvac_egress.py`, `hvac_setpoint.py`, `hvac_excursion.py` (v5.103.15 scope is the establishment gate).

**Rule for Stage A:**
1. Stage A build does NOT dispatch until v5.103.15 has merged to `develop`.
2. Before build, orchestrator re-resolves every file:line in this plan by symbol (`emit_set_preset_mode`, `_heat_cool_enforcer`, `_ac_reset_off`, etc.) — NOT by the numbers frozen here. Update the D3 table in-place if lines shifted.
3. If v5.103.15's fix-ups introduce a NEW raw `hass.services.async_call("climate", ...)` (they shouldn't — establishment is a read-side gate), it lands in the D3 migration list and blocks Stage A ship until migrated. The D5 completeness lint would catch it regardless.
4. Stage A ships behind v5.103.15 in the release order.

---

## 9. Non-goals (Stage A)

- **NO brand strategy / no `ZoneThermostat` class / no `write_effective_preset` composed API** — that is Stage B (Tier 3, operator go).
- **NO presets-only return path for borrows** — Stage B.
- **NO coherence rule** ("manual counts as human only when CONFIG `hold_activity == manual`") — Stage B.
- **NO lockout release / no arrester delta change / no comfort-grace change** — different cards.
- **NO change to DPM's caller-side preset opinion** (HIGH-2) — different point-gate, AUDIT §8 rec 2.
- **NO change to `return_excursion` behaviour** — bookkeeping stays bookkeeping (state-of-play §6, C13).
- **NO row for `set_activity_setpoint`** (upstream PR #427) — URA does not call it today; if Stage B adopts it, that funnel gets its own row shape then.
- **NO chained-route escape hatch fix** (`coordinator.py:1096-1130` — AUDIT §1b tail); still an accepted open gap, out of scope.
- **NO occupancy fast path** — W2.

---

## 10. Numbers get knobs (placement ladder)

Stage A introduces exactly **two** numbers; both are module constants (rung 1 — change requires review) because they govern log-shape/volume, not operator-observable behaviour:

| Constant | Value | Home | Why rung 1 |
|---|---|---|---|
| `CLIMATE_WRITE_LOG_IMPORTANCE_OK` | `"info"` | `hvac_const.py` | governs dedup + retention behaviour of the shared log; changing it changes the entire log's fairness profile — review-worthy |
| `CLIMATE_WRITE_LOG_IMPORTANCE_ERR` | `"notable"` | `hvac_const.py` | as above; `notable` bumps dedup window from 30 s → 60 s (`activity_logger.py:27-31`) so a runaway wire-error path can't flood |

No config-flow field, no entity — Stage A behaviour is neutral, nothing for the operator to tune.

---

## 11. Tier justification

**Tier 2-DB** (three framing-disjoint reviews + one plan review + live validation + README write-back):

Regression-prone by the standing policy — touches every URA thermostat write in a live 3-zone house running an infinite-holds Carrier fleet with the strand defect (§9.1) still live. Sibling risks (arrester, S1 lockout, borrow ordering) are downstream of this surface and would collapse if a migration reshaped a payload. Framings:

- **Review A — local correctness + arithmetic + payload equivalence.** For each of the 7 D3 sites, `service_data` before/after migration is byte-identical (same `entity_id`, same `hvac_mode`, same `blocking`); the funnel's new row has all required keys.
- **Review B — integration / cross-coordinator / restart.** No dispatch loop, no cross-coordinator signal (Stage A is diagnostic-only, INV-A doesn't drive any decision). Restart resilience: the funnel is stateless beyond the underlying writer; `ActivityLogger` boot behaviour and DB write-queue apply identically to the new action. Boot-storm risk assessed against C.7 `boot_ramp_audit` sites (S9 already funnelled — will get rows on first boot; volume ≤6 rows/boot).
- **Review C — test authority via per-site source mutation.** The D5 completeness test + per-site drills in §6 constitute the C-review artifact. Reviewer C must edit production, run suite, confirm the named test fails, restore — for at least B2, B5, and the funnel's row-emit block.

**Not Tier 3** — Stage A is behaviour-neutral and diagnostic-only. There is no invariant-preserving state machine to break, no cost/safety decision downstream. Stage B (brand strategy) IS Tier 3 and requires operator go before that plan is even scoped.

**Plan review (mandatory Tier 2+):** one adversarial pass before build dispatch. Reviewer must independently re-grep the 7 raw sites against develop-post-v5.103.15 merge, re-verify `emit_set_hvac_mode` genuinely does not exist, re-verify the row shape has no null-vs-missing key ambiguity, and confirm INV-A is falsifiable in the shape stated in §1 (not softened during scoping).

---

## 12. Open questions for the operator (only if you must answer)

None. Stage A is fully specified by the state-of-play + AUDIT + operator scope notes on the card. All decisions (table reuse, no comfort-delay gate on mode writes, log inside funnel not inside excursion bookkeeping, resume logged as its own row, byte-identical wire payload) are derivable from existing rulings.

Everything requiring an operator call is Stage B: brand strategy, presets-only returns, coherence rule, `set_activity_setpoint` adoption. Those belong in the Stage B plan, not here.

---

## Orchestrator hand-check amendments (2026-09-26) — BINDING

**AM-A1 (HIGH — the chosen table would violate INV-A).** The plan reuses `ura_activity_log` via `ActivityLogger.log`, but that logger DEDUPLICATES by importance window (`activity_logger.py:26-30`: info 30 s, notable 60 s, critical 300 s). A nudge start + restore, a resume + pin, or two zones written in the same tick would collapse into one row — "exactly one row per wire write" would be false by construction, and the D2 test would only pass if it never exercises two writes inside the window. Binding: the climate-write row must bypass dedup (an explicit `dedup=False` path or a distinct writer that calls `database.log_activity` directly), with a test that issues two identical writes 1 s apart and asserts TWO rows. Plan review must confirm the chosen path against `activity_logger.py` and `database.py:5788-5815`.

**AM-A2 (MEDIUM — write rates were not measured).** The "measured" 90-120 writes/day are estimates carried from the state-of-play doc, not a probe. Before build, run the one-shot read-only count (ac_ramp_events nudge/reset rows + hvac_excursion_events + ura_activity_log preset_change, per zone per day, 7 d) and record it here; the write-VOLUME review and the "<1 % of activity-log throughput" claim both depend on it (Optimization-Coordinator write-flood lesson).
