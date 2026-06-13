# PLANNING — Load-Shedding Correctness Fixes (existing-scope only)

**Target version:** post-v5.4.0 (next free patch slot; suggest v5.4.1 if no bigger cycle queued).
**Branch:** `feature/load-shedding-correctness` off `develop`.
**Tier:** Tier 2-DB (operator-elevated). Trust-hierarchy ripple across Energy load-shedding ↔ EVSE TOU controller ↔ battery-drain / fill-priority / arbitrage / grid-cap pause sets. The collision IS the regression surface. Three framing-disjoint reviews + Live validation + README write-back.

## HARD SCOPE BOUNDARY — correctness-only

This cycle fixes correctness defects in the EXISTING 4-level cascade (`pool → ev → smart_plugs → hvac`, `energy_const.py:548`). It does **not**:
- introduce progressive pool sub-tiers (booster / infinity-edge / spa / jets);
- couple shedding to solar/load forecasts or the arbitrage gate;
- add new sheddable domains;
- change the priority ordering;
- expose new operator-facing CONF knobs (likely zero new CONF — parsimony, this is a bug-class fix).

Those belong to the parked foundations / IP-grade track in `project_load_shedding_ip_capability_hold.md`. If a reviewer or builder finds themselves proposing capability expansion, **stop — out of scope.**

---

## Institutional context verified

### Code surveyed end-to-end
- `custom_components/universal_room_automation/domain_coordinators/energy.py`
  - `_update_load_shedding(tou_period)` — `energy.py:3494-3655`. Reactive cascade. Off-peak full release at `:3510-3515`. Escalate at `:3571-3614`. De-escalate (one tier per tick after `_load_shedding_grace_cycles`) at `:3615-3655`.
  - `_execute_shed_action(target, activate)` — `energy.py:3657-3750`. **pool** branch `:3665-3686` (mutates `self._pool._original_speed`, `self._pool._state`). **ev** branch `:3687-3712` (mutates `self._ev._paused_by_us` — the EXACT collision). **smart_plugs** branch `:3713-3737` (mutates `self._smart_plugs._paused_by_us`, also colliding with TOU). **hvac** branch `:3738-3742` (no-op; shed enforced via constraint signal at `:3394-3395`).
  - `_restore_load_shedding_level` — `energy.py:1383-1408`. Restores only the integer level via `db.restore_energy_state("load_shedding_level")` + a 3-cycle grace; does **NOT** re-execute shed actions nor re-populate pause-sets / `_original_speed`. Confirms audit HIGH finding #2.
  - `_save_load_shedding_level` — `energy.py:1410-1420`. Persists level only. Pause-sets / pre-shed speed are RAM only.
  - Escalation entry from tick: `_update_load_shedding(period)` called at `energy.py:2678`. Hard-shed (full cascade) at `energy.py:790-853` (`_handle_emergency_shed_all`).
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py`
  - **EV `_paused_by_us` shared with load-shed EV tier** — declared `energy_pool.py:196`; mutated by `EVChargerController.determine_actions` (peak/mid_peak add at `:510`; off_peak discard at `:548`, `:565`, `:616`); mutated by load-shed `_execute_shed_action` at `energy.py:3700` / `:3705` / `:3712`. **Same set, two owners — this is the CRIT collision.**
  - Other EV ownership sets (the prior-art pattern to mirror): `_paused_by_grid_cap:198`, `_paused_by_battery_drain:199`, `_paused_by_arbitrage:205`, `_paused_by_fill_priority:256`, `_arbitrage_pause_reason:213` (side-map).
  - **v5.3.9 arbitrage solution to copy** — `determine_arbitrage_actions` `energy_pool.py:1266-1410`: creates a dedicated `_paused_by_arbitrage` set + `_arbitrage_pause_reason` side-map labelling rung intent; release-side guard (`grid_charge_on`) refuses to release while hardware contradicts; carry-over precedence check on off-peak ensure-on at `:542-550` (arbitrage/drain/fill/grid-cap WIN over TOU intent); resume-only-if-no-other-pause-reason precedence at `:1387-1396`. Review trail in `docs/reviews/code-review/arbitrage_solar_attainability_ladder.md`.
  - Smart-plug `_paused_by_us` shared with TOU at `energy_pool.py:1671`, mutated by TOU `determine_actions` at `:1744` / `:1747-1760`, AND by load-shed shed at `energy.py:3725` / `:3727-3737`. Same collision shape as EV.
  - Smart-plug peers: `_paused_by_battery_drain:1672`, `_paused_by_fill_priority:1680`.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:536-548` — `LOAD_SHEDDING_PRIORITY = ["pool", "ev", "smart_plugs", "hvac"]`, `LOAD_SHEDDING_MODE_AUTO`, percentile / min-days. Unchanged this cycle.
- `database.py:4128 / :4141 / :4158` — `save_energy_state` / `restore_energy_state` (string KV) — REUSE for any new restart-persistence; no new DAO needed.

### Memory bodies pulled
- `project_load_shedding_audit_backlog.md` — full body. Source of the 1 CRIT + 2 HIGH (+ 1 MED release-deadband + 1 LOW HVAC drift, both out-of-scope this cycle per parsimony unless reviewers escalate). Safe-test path codified there.
- `project_load_shedding_ip_capability_hold.md` — full body. Defines the hard boundary above.
- `project_ev_pause_post_peak_midpeak_decision.md` — DURABLE EV philosophy: solar-first, never drain battery into EV, off-peak grid cheapest. The shed/TOU collision must not regress (1) shed → unintended EV resume during peak (battery drain risk), nor (2) shed-release → EV blast-on into post-peak mid_peak (already philosophy-violating).
- `feedback_tier2db_for_regression_prone.md` — three framing-disjoint reviews mandated for regression-prone work.
- `feedback_parsimonious_room_config.md` — drive zero-new-CONF default unless absolutely required.

### Prior planning / review docs skimmed
- `docs/reviews/code-review/arbitrage_solar_attainability_ladder.md` — v5.3.9 review record; pattern source for separate pause-owner set + side-map + precedence.
- `docs/planning/` filenames skimmed for `load_shed*` — only the audit memo exists; no prior planning doc to inherit.

### Design docs
- No `docs/Coordinator/EnergyCoordinator.md` checked in for this specific surface; cited code is authoritative.

---

## Findings re-verified against current code (2026-06-13)

| # | Severity | Audit-claim | Re-verified file:line | Status |
|---|----|----|----|----|
| F1 | CRIT | EV shed tier shares `_paused_by_us` with EVSE TOU controller | EV TOU mutates `_paused_by_us` at `energy_pool.py:510, 548, 565, 616`; load-shed mutates same set at `energy.py:3700, 3705, 3712`. Same tick: `determine_actions` runs (`energy.py:2355` per audit) before `_update_load_shedding` at `:2678`. During peak the EVSE is already in `_paused_by_us` → shed activate guard at `:3694` (`evse_id not in _paused_by_us`) is FALSE → **EV tier sheds nothing, just bumps the level counter**; on de-escalation it discards and may turn_on, then TOU re-pauses next tick → flap. CONFIRMED. | Fix required |
| F2 | HIGH | Orphan restore (post-restart + mid-shed code paths) | `_restore_load_shedding_level` `energy.py:1383-1408` restores integer level only; never re-runs `_execute_shed_action(activate=True)`. Pool `_original_speed` (`energy_pool.py:74`) and the EV / plug `_paused_by_us` sets are NOT persisted. Post-restart: level=2 in DB → coordinator THINKS pool+EV are shed, real hardware is unchanged, EV pause-set is empty so the de-escalation discard branch is a no-op, pool restore-speed is lost forever. CONFIRMED. | Fix required |
| F3 | HIGH | Manual-off clobber on shed release (plugs + EVs) | Smart-plug release branch `energy.py:3727-3737` blindly issues `switch.turn_on` whenever `entity_id in self._smart_plugs._paused_by_us`, with **no check that current `state.state == "off"` is the operator's choice vs URA's pause**. The pool branch `:3678-3686` similarly restores `_original_speed` with no "did the operator manually set a different speed during shed?" check. The TOU side at `energy_pool.py:1753` at least gates resume on `state.state != "on"`, but the load-shed release has no such check. CONFIRMED. | Fix required |

---

## Deliverables

### D1 — Separate ownership: `_paused_by_load_shed` (CRIT, F1)

**Pattern: REUSE the v5.3.9 arbitrage pattern verbatim.**
- Add new EV-side set `EVChargerController._paused_by_load_shed: set[str]` (`energy_pool.py` near `:205`). **NEW** — no equivalent set exists; this is the same "give each owner its own set" remedy that v5.3.9 chose for arbitrage rather than overloading `_paused_by_us`.
- Add equivalent `SmartPlugController._paused_by_load_shed: set[str]` (near `:1680`). **NEW** for the same reason on the plug side.
- Migrate `_execute_shed_action` `energy.py:3687-3712` (EV) and `:3713-3737` (plugs) to add/discard the new set, NEVER touching `_paused_by_us`. **REUSED** action-spec emit pattern from current `_execute_shed_action`.
- **Precedence in EV `determine_actions` carry-over guards `energy_pool.py:542-550`** — extend the carry-over tuple to include `_paused_by_load_shed`. Mirrors the v5.3.9 pattern at the same site. So even during off-peak, an EV claimed by load-shed (cross-period escalation) stays paused. **REUSED** precedence pattern.
- **Resume gating in EV release** — when load-shed releases an EV, it must NOT issue `turn_on` if any of `{_paused_by_battery_drain, _paused_by_fill_priority, _paused_by_grid_cap, _paused_by_arbitrage}` still claim it. Mirrors `energy_pool.py:1387-1396`. **REUSED**.
- **Mirror for plugs** — extend smart-plug TOU `determine_actions` `energy_pool.py:1737-1762` so the off-peak resume branch refuses to turn on while `_paused_by_load_shed` claims the plug. Mirrors EV pattern. **REUSED**.
- **No side-map needed yet** — `_arbitrage_pause_reason` exists because v5.3.9 had two rung intents on one set. Load-shed has only one intent. If reviewers see a need, surface it; default is no side-map (parsimony).
- TOU sets `_paused_by_us` and load-shed `_paused_by_load_shed` are independent. The EV tier of load-shedding is now allowed to ACTUALLY pause an EV (it previously couldn't because the TOU set was always populated first).
- **Why this is safe vs the v4.7.28 / philosophy concern in the audit:** shed ADDS to its own set, never removes from `_paused_by_us`. If TOU is currently pausing, the EV is already off — shed activate becomes a claim only (mirror v5.3.9 `:1344-1351` proactive-claim pattern when switch is already off). Resume never blasts the EV on during peak/mid_peak because the carry-over guards at `:542-550` keep TOU intent intact and the new shed-release precedence above defers to other owners. The DURABLE EV philosophy (no battery-drain into car) is preserved because `_paused_by_battery_drain` is in the precedence list.

#### Acceptance criteria
- **Verify:** During peak with TOU active, escalating to EV tier results in `_paused_by_load_shed = {evse_id}` AND `_paused_by_us` still contains the EVSE; no `turn_off` action is duplicated (proactive-claim when already off).
- **Verify:** De-escalating the EV tier while TOU still pausing does NOT issue `switch.turn_on`; discard from `_paused_by_load_shed` only.
- **Verify:** Off-peak tick after shed-released-but-load-shed-still-claims — EV stays OFF; once `_paused_by_load_shed` cleared, off-peak ensure-on fires normally.
- **Sensor:** `sensor.ura_energy_coordinator_load_shedding_status` exposes `paused_by_load_shed` arrays (EV + plug) under attributes (REUSE the `paused_by_*` reporting pattern at `energy_pool.py:1484-1498`). **NEW** attribute, additive.
- **Test:** new in `quality/tests/test_energy_load_shedding_correctness.py`:
  - `test_ev_shed_during_peak_does_not_touch_paused_by_us`
  - `test_ev_shed_release_during_peak_keeps_ev_off`
  - `test_ev_shed_release_off_peak_defers_to_battery_drain`
  - `test_plug_shed_release_defers_to_battery_drain`
- **Live (SAFE per audit):** observation-mode ON + low `_load_shedding_threshold_kw` fixed + ONE smart plug — escalate through `pool → ev` levels, confirm the `paused_by_load_shed` EV-side attribute grows even though no EV `turn_off` fires (proactive-claim because TOU already off). DO NOT live-toggle the EV tier with obs OFF until D1+D2+D3 are all in.

### D2 — Orphan restore: rebuild shed state on startup + persist pre-shed speed (HIGH, F2)

- Extend `_save_load_shedding_level` `energy.py:1410-1420` to ALSO persist a small bundle: `{ "level": int, "pool_original_speed": float|null, "ev_set": [evse_id, ...], "plug_set": [entity_id, ...] }`. **REUSED** `save_energy_state` KV (single key e.g. `load_shedding_bundle`, JSON-encoded string). No new DAO. Keep legacy `load_shedding_level` write for one cycle for back-out safety.
- Extend `_restore_load_shedding_level` `energy.py:1383-1408` to read the bundle. If present:
  - Restore `self._load_shedding_active_level`.
  - Re-populate `self._pool._original_speed`, `self._ev._paused_by_load_shed`, `self._smart_plugs._paused_by_load_shed`.
  - **Do NOT re-issue `switch.turn_off` actions** — the live device state IS the authority post-restart. If a device is on, the next escalation tick will catch up; if it's off, we've correctly registered ownership.
  - Keep the 3-cycle grace.
- If bundle absent (older deploy), fall back to legacy integer-only restore (back-compat).

#### Acceptance criteria
- **Verify:** restart mid-shed (level=2, pool reduced, EV claimed) — post-restart: `paused_by_load_shed` re-populated, `_original_speed` restored, no spurious actions issued.
- **Verify:** legacy DB row (integer-only) still restores level + arms grace; no exception.
- **Test:**
  - `test_save_restore_load_shedding_bundle_roundtrip`
  - `test_restore_load_shedding_bundle_legacy_integer_falls_back`
  - `test_restore_does_not_issue_turn_off_actions`
- **Live:** observation mode + low threshold + ONE plug — escalate to level 2, restart HA, confirm `load_shedding_status` attributes survive restart (level + pool-original-speed + paused_by_load_shed).

### D3 — Manual-off-wins on shed release (HIGH, F3)

- In `_execute_shed_action(..., activate=False)` plug branch `energy.py:3727-3737`, **before** appending `switch.turn_on`, check current `hass.states.get(entity_id)`:
  - If state is `off` AND the off transition happened AFTER our shed dispatch timestamp (`_pause_dispatch_ts` already exists on `SmartPlugController` at `energy_pool.py:1675`), treat as operator-manual-off → discard from `_paused_by_load_shed`, do NOT turn on. **REUSED** `_pause_dispatch_ts` infrastructure; possibly REUSED `_observed_off_since_pause` (already maintained `:1676`). Confirm during build that the ts is set when load-shed dispatches; if not, add a `_claim_pause_dispatch_owner("load_shed")` call (already supports multi-owner refcount at `:1704-1719`).
  - Else: proceed with `turn_on`.
- Pool branch `energy.py:3678-3686`: before restoring `_original_speed`, read current `_pool.current_speed`. If it has been changed by the operator (not equal to `POOL_REDUCED_SPEED`) DURING shed, treat the new value as the operator's choice; discard `_original_speed` without restore. **REUSED** `current_speed` property.
- EV branch `energy.py:3702-3712`: not strictly a "manual-off clobber" risk (release issues `turn_on`, not `turn_off`), but mirror the pattern for symmetry — skip `turn_on` if state is currently `on` (idempotency) AND respect the precedence list from D1.

#### Acceptance criteria
- **Verify:** operator-manual-off mid-shed → shed-release does NOT re-enable the plug; entity is discarded from `_paused_by_load_shed` cleanly.
- **Verify:** operator changes pool speed mid-shed → shed-release does NOT restore the stale `_original_speed`.
- **Verify:** no flap regression: a normal automatic shed/release with NO operator interaction still restores correctly (baseline preserved).
- **Test:**
  - `test_plug_shed_release_respects_manual_off`
  - `test_pool_shed_release_respects_manual_speed_change`
  - `test_plug_shed_release_baseline_restores_when_no_manual_action`
- **Live:** observation mode + low threshold + ONE plug — trigger shed, manually flip the plug off in HA UI, release → confirm via state machine that the plug stays off and is dropped from `paused_by_load_shed` (sentinel: `load_shedding_status.paused_by_load_shed` shrinks; `last_action` reason field shows `respect_manual_off`). REUSE existing `_record_decision` pattern from `energy.py:3587-3594`.

### D4 — Status sensor surface refresh (small, supports validation)

- `load_shedding_status` attributes at `energy.py:5328-5343`: add `paused_by_load_shed_ev`, `paused_by_load_shed_plugs`, `pool_pre_shed_speed`, `last_release_reason` (one of `auto`, `respect_manual_off`, `deferred_to_battery_drain`, `restart_restored`). **REUSED** dict-attribute pattern.
- Activity-log additions: when D3 skips a `turn_on`, emit an `activity_logger.log(action="load_shed_release_respect_manual_off", ...)` mirroring `energy.py:3597-3612`. **REUSED** `activity_logger`.

#### Acceptance criteria
- **Sensor:** new attributes present + non-null after first shed event of the run.
- **Live:** Activity-log row `load_shed_release_respect_manual_off` appears when D3 triggers.

---

## Out of scope (explicit non-deliverables — guard against scope-creep)

| Item | Why deferred | Where it lives |
|---|---|---|
| Progressive pool sub-tiers (booster / infinity-edge / spa / jets / blower) | Capability expansion — foundations / IP track | `project_load_shedding_ip_capability_hold.md` |
| Forecast-coupled proactive shedding (reuse arbitrage gate) | Capability expansion — foundations / IP track | same |
| New sheddable domains (lighting, EV charging-current modulation, etc.) | Capability expansion | same |
| Release deadband at ~0.8× threshold (audit MEDIUM) | Behavior change, not correctness; deserves a separate small cycle once D1-D3 land | future backlog memo |
| HVAC shed `max_runtime` get_next_transition re-verify (audit MEDIUM) | Already de-risked by v4.7.29 day-boundary work; track as watch-only | already noted in audit |
| HVAC tier fire-and-forget state drift (audit LOW) | Pre-existing; out of scope | future backlog |
| Medical / safety allowlist guard on shed lists | UNVERIFIED in audit; should be its own cycle if real | future backlog |
| Coordinate-with-battery-before-shedding optimization | Optimization, not correctness; IP track | foundations track |
| Cost / comfort weighted tier order | Optimization, IP track | foundations track |
| New operator-facing CONF knobs | Parsimony default — none added | n/a |

If a reviewer finds a defect outside D1-D4 that meets the QUALITY_CONTEXT.md CRITICAL/HIGH bar, file it; otherwise defer.

---

## Tier 2-DB review plan — three framing-disjoint axes

Run in parallel. Operator-elevated per `feedback_tier2db_for_regression_prone.md`.

- **Reviewer A — Pause-ownership / precedence / resume races, and the EVSE collision specifically.**
  - Verify the new `_paused_by_load_shed` is added to every relevant precedence tuple on the EV side (`energy_pool.py:542-550`, `:731-746`, `:893-907`, `:1007-1012`, `:1388-1396` — confirm during review) and plug side (`:1747-1760`, `:1881-1884`, `:2018-2021`, `:2081-2083`, `:2102-2108`).
  - Trace each tick path: TOU peak → shed-escalate-ev; TOU off-peak → shed-de-escalate-ev; arbitrage CHARGE → shed-active; battery-drain → shed-active. No double-emit `turn_off`, no spurious `turn_on`.
  - Confirm DURABLE EV philosophy preserved: battery never dumps into EV because of shed-release.
- **Reviewer B — Restore / orphan / restart-resilience + manual-off-wins.**
  - Read D2 bundle persist/restore end-to-end. Field-by-field round-trip. Legacy integer compatibility.
  - Read D3 timestamp comparison logic; confirm `_pause_dispatch_ts` set on load-shed dispatch (build must add the `_claim_pause_dispatch_owner("load_shed")` call). Confirm baseline restore still fires when no manual action.
  - Pool-speed manual-change detection: confirm `current_speed` read at release time is authoritative.
- **Reviewer C — Test authority + safe-test design (EV tier cannot be live-toggled).**
  - Confirm new tests drive PRODUCTION code paths (`_execute_shed_action`, `_update_load_shedding`), not duplicated INSERT/UPDATE/DELETE.
  - Confirm Live criteria are achievable via observation-mode + ONE smart plug per the audit safe-test path; no Live criterion requires toggling the EV tier with obs OFF.
  - Pre-deploy snapshot: capture last 7-day row rates by `(coordinator=energy, action ∈ {load_shed_escalate, load_shed_release, load_shed_release_respect_manual_off}, level)` from the activity-log / decisions table. Post-deploy ±25% comparison.

**Live Validation (Review D):** post-restart, observation mode ON, low fixed threshold, ONE non-essential smart plug. Drive escalation to level 3 (`pool → ev → smart_plugs`), then release. Validate against the four bullets in D1/D2/D3 Live sections + the D4 sensor attributes. Confirm no EV `turn_off` / `turn_on` actions issued in observation mode. The EV-tier collision fix is proven IN-SUITE (Reviewer C-blessed tests); only the plug+pool side is proven live.

**README write-back mandatory** — Validated `<date>` table with PASS/FAIL per criterion + observed evidence (entity attribute snapshot + activity-log row).

---

## Plan-completion tracking

After build, the close-out memo MUST explicitly state:
- Capability-expansion items (progressive pool sub-tiers, forecast-coupled shed, new sheddable domains) NOT built — deferred to the foundations / IP-grade track per operator decision 2026-06-12.
- Audit MEDIUM (release deadband) + HVAC tier LOW NOT built — deferred to a future small cycle.
- Medical / safety allowlist UNVERIFIED — open backlog item.

---

## Open questions for operator (resolve at plan-review)

1. **Persist pool `_original_speed` across restart — confirm desired behavior.** Bundle persistence in D2 will restore the pre-shed speed snapshot taken at escalate-time. If hours pass before restart and the operator changed expected pool speed in the interim, restore would push a stale value. Acceptable, or should restore drop `_original_speed` if it's older than some TTL (e.g. 6h)?
2. **D3 manual-off detection on plugs depends on `_pause_dispatch_ts` being set when load-shed dispatches the turn_off.** Currently the TOU path sets it; the load-shed path does NOT. Build will add `_claim_pause_dispatch_owner("load_shed")` at dispatch time. Confirm this multi-owner refcount (`energy_pool.py:1704-1719`) is the right reuse target rather than a parallel `_load_shed_dispatch_ts`.
3. **EV-side `_pause_dispatch_ts` equivalent exists?** A quick search did not surface a per-EVSE dispatch-timestamp dict analogous to the smart-plug one (`energy_pool.py:1675`). If absent, the EV release branch's "manual-off-wins symmetry" in D3 simplifies to idempotency only; confirm acceptable.
4. **Single bundle key or split keys?** D2 proposes one JSON-encoded `load_shedding_bundle` row. Alternative: separate KV rows per field. Single bundle keeps the restore atomic; split allows partial reads. Default proposal: single bundle. Confirm.
