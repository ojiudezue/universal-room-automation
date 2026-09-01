# PLANNING — Shared Power-Read Staleness Helper (ENVOY-PRODUCTION-STALE-1)

**Card:** `ENVOY-PRODUCTION-STALE-1` (consolidated per operator 2026-08-31).
**Rev:** 5 (2026-09-01) — plan-review FIX-REQUIRED on Rev 4 addressed. Rev-4 verified CLEAR on CRITICAL-1 consumer coverage for `battery_power_w`, HIGH-3 cloud-SOC preserve-accept, HIGH-4 unconfigured/missing split, MED-5 class names + import-cycle safety, MED-6 6th gate + negative clamp, D4-G load-shed sustained-window, net_power consumer enumeration (except one streak-wipe row), envoy_status display-only ruling. Rev-5 corrections target four mis-targeted / over-scoped items:

> - **Rev-5 CRIT-A** — Rev-4 D4-H patched DEAD code. `_grid_import_guard_triggered` at `energy_battery.py:2635-2646` has ZERO callers (grep: only the def + stale comment refs at `:519` and `:4829`). The LIVE 12 kW breaker guard is THREE inline sites: `energy_battery.py:3150-3197`, `:4523-4547`, `:4680-4703` — each shaped `if snap is not None and snap[0] > self._arbitrage_grid_import_guard_kw:` (the exact fail-OPEN shape after D4-A). D4-H is re-scoped to those three sites; the dead helper is disposed per supersession rules (see D4-H "Dead helper triage").
> - **Rev-5 CRIT-B** — the same three sites all end with an `else: self._arbitrage_guard_consecutive_trips = 0` branch (`energy_battery.py:3196`, `:4547`, `:4703`); post-D4-A a one-tick stale gap silently WIPES an accumulated trip streak, so `ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK` (2) may never latch under alternating stale/over-import. D4-H specifies HOLD-not-reset on `snap is None` at all three sites, distinct from a genuine under-cap tick.
> - **Rev-5 HIGH-C** — Rev-4 D4-D-1/D4-D-2 over-scoped: skipping the entire `determine_battery_drain_actions(...)` call on `battery_power_w is None` also skips its RELEASES — the `force_charge_active` release at `energy_pool.py:2147-2150` (EVSE) and `:3723-3726` (plugs), AND the `must_start_by_min` hard 03:00 L1 release at `energy.py:6329-6331` (documented as "the ONLY hard release the operator's L1 charger gets"). A persistently dead CT would strand the EV all night. Rev-5 splits pause-evaluation from release-evaluation via a `battery_power_unknown=True` flag on the call.
> - **Rev-5 MED-D** — Rev-4 D-OBS `_resolve_source_age` pseudocode called `_get_entity(CONF_ENERGY_NET_POWER_ENTITY)` but `_get_entity(key)` at `energy_battery.py:719` expects the SHORT name from the key_map at `energy.py:986-996` (`"net_power"`, `"battery_power"`, `"solar_production"`, `"battery_soc"`). As written every source would return `"unconfigured"` — silently green-tests the HIGH-4 anchor while breaking the tile. Fixed to short names.

Rev 3 D-OBS retained (with MED-D fix); Rev 4 producer/consumer table retained (with the streak-wipe row added and D4-H re-scoped).

**Tier:** **2-DB** (regression-prone, cross-coordinator ripple: energy_battery → energy_pool → EVSE + DP + NM + billing; shared primitive; folds together six hand-rolled gates whose thresholds MUST be preserved byte-for-byte on the fresh path).
**Mode:** planning only (read-only). Awaits third plan-review pass before build dispatch.

**Falsifiable invariant (state up front — Rev 5, unchanged from Rev 4):**
> For every trust-decision-consuming power/SOC read in the Energy family, a numeric HA state whose **`last_reported`** stamp (falling back to `last_updated` when the platform did not populate `last_reported`) is older than the site's configured `MAX_AGE_S` MUST be treated as **absent** (helper returns `None`) AND EACH CONSUMER of that value MUST route to a **fail-SAFE** fallback that preserves the SAFETY DIRECTION of the guard it participates in — the drain-pause set is HELD **while releases still evaluate**, the breaker guard TRIPS **and its consecutive-trip streak HOLDS**, the load-shed sustained window is drained (no stitched-run false escalation), the billing tick is SKIPPED, the persisted analytics column is NULL (never `0`). On the fresh path (age ≤ MAX_AGE_S, valid unit, in-range) the returned value MUST be **byte-identical** to today's read.
>
> Why `last_reported`, not `last_updated`: HA advances `last_reported` on every re-publish (even when the value did not change), but only advances `last_updated` on a value change. A healthy sensor pinned at 0 W (solar at night) or a constant-valued sensor would therefore be judged stale under `last_updated`. Same reason the existing grid solar-follow gate at `energy_pool.py:4406-4413` (INV-SF-10) uses `last_reported`. Any migrated site is INDIVIDUALLY specified below to preserve its current stamp choice — see D5.
>
> Rev-5 refinement of the per-consumer clause: **safety-guard side-effects (pause SETS and streak COUNTERS) MUST be treated as separate axes from the guard's Boolean output.** Producer-only gating that inadvertently WIPES a pause set (Rev-4 HIGH-C) or WIPES a streak counter (Rev-4 CRIT-B) silently disarms the guard just as much as returning False. The invariant covers both.

---

## Institutional context verified

### Design/rules read
- `CLAUDE.md` — Tier 2-DB triggers; Producer/Consumer rule; "Numbers get knobs" ladder; "Coincidental equality masks a concept split"; "Extend existing, never rebuild"; "Do the robust fix, not band-aid+card"; **"Post-Ship Supersession & Consumer-Gap Audit"** (applied to `_grid_import_guard_triggered` in D4-H).
- `docs/QUALITY_CONTEXT.md` — Bug class **#7 stale data source** + **#63 coincidental equality masks a concept split**.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.5a — reserve verifiable backout knob (MAX_AGE_S=0 fire-axe).

### Prior planning / memory pulled
- Memo `reference_ec_reserve_verifiable_backout_knob` — fire-axe precedent.
- Memo `feedback_coincidental_equality_masks_concept_split` — LKG numeric == primary when frozen; D2-A discriminator MUST be `_soc_source_last`, not value.
- Memo `feedback_do_robust_fix_not_bandaid_and_card`.
- Memo `feedback_read_consumers_before_asserting_function` — the load-bearing memory this whole cycle's Consumer × None-direction table honors.
- v5.17.5 A1 review record — `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600` (`energy_battery.py:882-910`); the `except` branch at `:907-910` explicitly ACCEPTS on missing/naive `last_updated` ("let unit + range checks decide") — a fail-OPEN branch D5 preserves.
- v4.5.0 unit-consistency sweep — `_read_power_w` template.
- Rev 3: `docs/dashboards/ura_v6_v8_solar_aware_ev_and_census_cards.md`.

### Producer AND Consumer surveyed (re-verified by grep 2026-09-01, Rev-5 line numbers corrected)

**Class-name correction (Rev 4 preserved).** `class BatteryStrategy` at `energy_battery.py:307`; `class CostTracker` at `energy_billing.py:92`; `class PeakAvoidanceTracker` at `energy_billing.py:457`. No `EnergyBatteryCoordinator`/`EnergyBillingCoordinator` classes exist (grep — 2 hits, both unrelated typing refs in other coordinators).

**Helper HOME decision (Rev 4 preserved).** `_state_age_s` is a **module-level function in `energy_battery.py`** (top of file, after imports); `BatteryStrategy` gets thin instance-method wrappers `_read_fresh_power_w` / `_read_fresh_float`; `sensor.py` and `energy_billing.py` import `_state_age_s` directly.

**PRODUCER table — sites this cycle gates:**

| # | Site (producer) | file:line | Current reject | Fallback that engages when helper returns `None` |
|---|---|---|---|---|
| 1 | `_read_power_w("solar_production")` via `solar_production_w` | `energy_battery.py:1572-1596`, called at `:1614` | unknown/unavailable only | `solar_production_w_envelope()` at `:2287` — entry check at `:2330` also gated (D3). |
| 2 | `_read_power_w("net_power")` via `net_power_w` | `energy_battery.py:1628-1636` | unknown/unavailable only | expanded Consumer table + per-consumer fail-CLOSED specs (D4). |
| 3 | `battery_power_w` inline | `energy_battery.py:1546-1570` | unknown/unavailable only | drain-protection consumers currently fail-OPEN on `None`; D4-D REQUIRES paired call-site **pause/release split** at `energy.py:6161` AND `:6317` before the producer gate ships. |
| 4 | PRIMARY `battery_soc` via `_get_state_float(self._get_entity("battery_soc"))` | 4 CALL SITES — D2 | unknown/unavailable only | three-tier resolver (LKG → cloud) at `:838-921` for site A only; sites B/D migrated; site C classified. |

**LKG-stamp arithmetic note (Rev 2 preserved).** LKG re-stamped at READ time (`:830-832`); aggregate blindness under a frozen primary is **sequential**: up to `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` + up to `DEFAULT_SOC_LKG_MAX_AGE_S` before cloud engages.

---

### CONSUMER × None-direction table (Rev 5 — updated with Rev-5 corrections + streak-wipe row)

Every migrated producer's DOWNSTREAM sites, with SHIPPED None behavior today (fail-open = safety guard disarms; fail-closed = safety guard engages / conservative fallback) and REQUIRED post-cycle behavior. **Safety guards MUST be fail-CLOSED, side-effects included.**

#### `battery_power_w` consumers

| # | Consumer | file:line | Trust vs display | None today | Required post-cycle | Rev-5 mechanism |
|---|---|---|---|---|---|---|
| 1 | EVSE drain gate — plugs | `energy_pool.py:2207-2209` (`is not None and < -100`) | trust (drain pause) | **fail-OPEN** — `discharging=False` → drain pause never fires | fail-CLOSED for PAUSES + **preserve RELEASES** | D4-D-1: pass `battery_power_unknown=True` to `determine_battery_drain_actions`; force-charge release at `:2147-2150` still evaluates; pause-evaluation branch HOLDS `_paused_by_battery_drain`. |
| 2 | EVSE drain gate — smart plugs | `energy_pool.py:3711-3713` (identical shape) | trust (drain pause) | **fail-OPEN** | same — pause HOLD + release EVALUATE | D4-D-2: mirror at `energy.py:6317`; force-charge release at `energy_pool.py:3723-3726` still evaluates; `must_start_by_min` L1 release at `energy.py:6329-6331` still evaluates. |
| 3 | `_effective_import_kw` (breaker math) | `energy_battery.py:2600-2633` (`batt_w=None → 0`, does not subtract) | trust (breaker guard math) | **fail-CLOSED already** — treating batt charge as 0 makes effective_import ≥ net, guard trips MORE easily. Documented at `:2623-2625`. | unchanged | none — preserve. |
| 4 | Envoy restart cache write | `energy.py:2455-2460` (writes raw `.battery_power` prop) | display / restart seed | writes frozen prop | gate on `_soc_source_last == "envoy"` | D4-F. |
| 5 | Write-verifier / forecast reads | `energy_write_verify.py:1794`, `energy_forecast.py:566` | trust | not investigated | out of scope — CARDED `BATTERY_POWER_W_CONSUMERS_AUDIT_1` | non-goal. |

**Sign-flip note:** `battery_power_w` is signed. `is None` short-circuit runs before any threshold comparison.

#### `net_power_w` consumers

| # | Consumer | file:line | Trust vs display | None today | Required post-cycle | Rev-5 mechanism |
|---|---|---|---|---|---|---|
| 1 | EVSE grid-cap | `energy.py:6071` (`or 0 / 1000`) | trust (pause/resume EVSE) | **fail-OPEN** — grid ≈ 0 kW, resumes paused EVSEs | fail-CLOSED — HOLD `_paused_by_grid_cap` | D4-B. |
| 2 | Persisted analytics row | `energy.py:3129-3130` (`or 0`) | trust (writes DB) | writes false 0 | NULL propagation | D4-C. |
| 3 | Load-shed sustained-window | `energy.py:7381-7387` (`snap is None: return`) | trust (SHED escalation) | **fail-OPEN by early-return + deque frozen** → stitched-run false escalation on trailing edge | fail-CLOSED — `_sustained_import_readings.clear()` + return; keep existing shed set intact | D4-G. |
| 4 | Breaker guard inline site A — `_reevaluate_arbitrage` CHARGE-phase | `energy_battery.py:3150-3197` | trust (breaker trip → chunk lock) | **fail-OPEN**: `if snap is not None and snap[0] > cap` → None passes to `else` at `:3196`, guard does NOT trip AND `_arbitrage_guard_consecutive_trips = 0` (wipes streak) | fail-CLOSED — treat None as "assume over-cap" (count as a trip: increment streak, honor `ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK`, log the None distinctly); do NOT reset the streak in the `else` on None | D4-H-1 (Rev-5). |
| 5 | Breaker guard inline site B — attainability `_get_attain_action_charging` | `energy_battery.py:4523-4547` | trust | **fail-OPEN + streak wipe** (same shape; `else` at `:4547` resets streak) | fail-CLOSED — same | D4-H-2. |
| 6 | Breaker guard inline site C — attainability `_get_attain_action_entry` | `energy_battery.py:4680-4703` | trust | **fail-OPEN + streak wipe** (same shape; `else` at `:4703` resets streak). NOTE the upstream `_breaker_guard_fail_closed_on_blind("attain_entry")` at `:4676` only covers `_degraded_telemetry_source` — a value-pinned local CT bypasses it, so this site's inline check is the last line of defense. | fail-CLOSED — same | D4-H-3. |
| 7 | Streak-wipe cross-site invariant | `_arbitrage_guard_consecutive_trips` reset at `:3196`, `:4547`, `:4703` | trust (2-tick lock latch) | one-tick stale gap alternating with over-import → streak never reaches 2 → guard never locks the chunk | on `snap is None`, HOLD the streak (do NOT reset); only reset on a genuine under-cap fresh read | D4-H covers all three (single change per site). |
| 8 | Billing accumulate (direct grid) | `energy_billing.py:152-170` | trust (dollars) | fail-open on frozen-valid CT | fail-CLOSED — skip tick | D4-E. |
| 9 | Billing accumulate (fallback) | `energy_billing.py:178-190` | trust (dollars) | fail-open on frozen-valid | fail-CLOSED — skip tick | D4-E. |
| 10 | Aggregation reads | `aggregation.py:6289`, `:6319` | trust — pending re-verification | out of scope | CARDED `AGGREGATION_NET_POWER_STALE_1` | non-goal. |
| 11 | Sensor exposure | `sensor.py:8690`, `:11538` | display | display-only | unchanged | none. |

**Rev-5 CRIT-A supersession disposition of `_grid_import_guard_triggered` (`energy_battery.py:2635-2646`):** grep across `custom_components/` returned three hits — the def itself, `:519` (a stale comment referencing "`_grid_import_guard_triggered()` + 3 inline sites"), and `:4829` (a stale comment inside `_breaker_guard_fail_closed_on_blind`). ZERO real callers. Three buckets per CLAUDE.md supersession triage:

- **DELETE** candidate — dead AND buggy (returns False on the very None case the LIVE guards must trip on) AND a footgun (a future refactor could wire it and re-introduce the fail-OPEN Rev-5 CRIT-A exposes). Deletion posture: DELETE **after** D4-H ships and post-restart live-validation confirms the three inline sites are fail-CLOSED (per CLAUDE.md "only delete after new path is live-validated"). Rev-5 does NOT delete pre-ship; the deletion PR follows the cycle's Live Validation.
- The `:519` and `:4829` stale comments are updated in-cycle to reference the inline sites only (dead-comment cleanup, safe in-cycle).

#### `solar_production_w` consumers

Trust consumers at `energy.py:3229/:3404/:3557` accept `None` via existing None-safe strategy math. Envelope entry at `energy_battery.py:2330` addressed by D3-B. Persisted row at `energy.py:3126` already None-safe.

#### `battery_soc` consumers

Resolver (D2-A) collapses tiers; downstream sees the tiered result (None only when ALL tiers fail — existing blind-hold branch handles).

---

### 5th AC-kWh gate (Rev-2 preserved)

`hvac_override.py:3962` — non-goal; carded `HVAC-OVERRIDE-KWH-STALE-FAIL-OPEN-1`.

### Consumer-check finding (unchanged)

`sensor.ura_energy_envoy_status.stale` DISPLAY-ONLY (grep Rev 4 re-verified: three self-references only). Extending is display-safe.

### Grep prior-art results for proposed additions
- `_state_age_s` / `state_age_s` / `read_fresh` / `_read_state_fresh` — **NEW** module-level function in `energy_battery.py`.
- `DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S`, `DEFAULT_NET_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` — **NEW**, rung 1.
- `battery_power_unknown` kwarg on `determine_battery_drain_actions` — **NEW** (Rev-5). Two call sites (`energy.py:6161`, `:6317`); no prior art; default False (fresh-path byte-identity).
- Rev-3/4: `sensor.ura_energy_coordinator_envoy_status` — **REUSED** (extended).
- Rev-3/4: `solar_age_s`, `net_power_age_s`, `battery_power_age_s`, `primary_soc_age_s`, `stale_sources`, `unconfigured_sources`, `missing_sources`, `stale_reason`, `fallback_active` — **NEW attributes**.

### Code locations surveyed end-to-end (Rev-5 line numbers)
- `energy_battery.py:307` (`class BatteryStrategy`), `:719-735` (`_get_entity` — short-name key), `:770-925` (SOC resolver + A1 gate at `:882-910`, `except` at `:907-910`), `:830-832` (LKG stamp), `:1130-1155` (6th gate — cloud-oracle lag with `max(0.0,…)` clamp at `:1149`), `:1530-1636` (power readers), `:2225-2320` (envelope entry checks), `:2440-2461` (`envoy_available`), `:2600-2633` (`_effective_import_kw`), **`:2635-2646` (`_grid_import_guard_triggered` — DEAD, disposition per D4-H)**, `:3150-3197` (LIVE breaker guard site A + streak-wipe at `:3196`), `:3365-3370` (`_breaker_guard_fail_closed_on_blind` — scope-limited compensator), `:4144` (streak reset — separate context, out of scope), `:4523-4547` (LIVE breaker guard site B + streak-wipe at `:4547`), `:4680-4703` (LIVE breaker guard site C + streak-wipe at `:4703`), `:6080-6100` (soc_resolution diagnostics).
- `energy.py:986-996` (key_map — SHORT names, MED-D corrective), `:2450-2460` (save_envoy_cache — D4-F), `:3115-3140` (persisted analytics), `:3225-3560` (solar strategy), `:6055-6090` (EVSE grid-cap — D4-B), `:6150-6165` and `:6310-6335` (drain-actions call sites — D4-D targets; `:6329-6331` `must_start_by_min` L1 release), `:7370-7400` (load-shed — D4-G).
- `energy_billing.py:92` (`class CostTracker`), `:144-191` (`_get_net_power` — D4-E), `:457` (`class PeakAvoidanceTracker`).
- `energy_pool.py:2140-2225` (EVSE drain — force-charge release at `:2147-2150`), `:3705-3735` (plug drain — force-charge release at `:3723-3726`), `:4395-4417` (grid-follow), `:4685-4710` (per-bay solar power).
- `energy_const.py:300-340`, `:960-985`.
- `sensor.py:12480-12515` — AC-kWh display gate.
- `sensor.py:13293-13444` — `EnergyEnvoyStatusSensor`.

---

## Deliverables

### D1 — Add the shared helper (single source of truth)

Add a **module-level function** in `energy_battery.py` (top of file, after imports):

```python
def _state_age_s(state, *, stamp: str = "last_reported") -> float | None:
    """Return the age in seconds of `state` measured against `stamp`,
    falling back to `last_updated` if the chosen stamp is absent.
    Returns None if state is missing, both stamps absent, or the chosen
    stamp is naive (fail-closed per CF-8 precedent at
    energy_pool.py:4402-4409).

    Rev-4 (MEDIUM-6): negative ages clamped to 0.0 to defend against
    clock skew or future-stamped inputs, matching the shipped clamp at
    energy_battery.py:1149.
    """
```

Plus two thin `BatteryStrategy` instance-method wrappers:

- `_read_fresh_power_w(entity_key, max_age_s, *, stamp="last_reported") -> float | None`
- `_read_fresh_float(entity_id, max_age_s, *, stamp="last_reported") -> float | None`

`sensor.py` and `energy_billing.py` import `_state_age_s` directly from `.domain_coordinators.energy_battery`.

**Stamp choice per NEW gate:** solar / net / battery_power / primary_soc → `last_reported`.

#### Acceptance
- **Verify:** helper importable; no site calls it yet.
- **Test:** `test_state_age_s_missing_naive_fresh_stale`.
- **Test:** `test_state_age_s_prefers_last_reported_falls_to_last_updated`.
- **Test:** `test_state_age_s_negative_stamp_clamps_to_zero`.
- **Test:** `test_read_fresh_constant_valued_sensor_is_fresh`.
- **Test:** `test_read_fresh_power_w_unit_scaling_preserved`.

### D2 — Migrate PRIMARY `battery_soc` — ALL FOUR SITES

Unchanged from Rev 4 (A `:828`, B `:2242`, C `:2455` KEEP-raw, D `:6091` migrate).

**Const:** `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S: Final = 300`.

**Bug Class #63 discriminator:** D2-A tests anchor on `_soc_source_last`, not value. `test_primary_soc_stale_discriminator_is_source_not_value`.

**`primary_age_s` attribute** on `soc_resolution` sensor — Rev-2 preserved.

#### Acceptance (D2)
- (Rev-3 tests preserved + Rev-4 discriminator anchor.)
- **Live:** `soc_resolution.primary_age_s` 6h — zero ticks `source_last == "envoy"` AND `primary_age_s > 300`.

### D3 — Migrate `solar_production_w` — BOTH producer AND envelope entry check

Unchanged from Rev 3 (D3-A `:1614`, D3-B `:2330`).

### D4 — Migrate `net_power_w`, inline `battery_power_w`, billing `_get_net_power`, PAIRED call-site fixes (Rev-5 corrections applied)

**D4-A — `energy_battery.py:1636` net_power_w producer.** Migrate to `self._read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S, stamp="last_reported")`. **New const** `DEFAULT_NET_POWER_MAX_AGE_S: Final = 180`.

**Single-diff gate (Rev-4 preserved, Rev-5 tightened):** D4-A MUST ship in the same commit as D4-B, D4-C, D4-E, D4-G, **and all three sub-sites of D4-H** (`energy_battery.py:3150-3197`, `:4523-4547`, `:4680-4703`). Reviewer B enforces via single-diff check.

**D4-B — grid-cap consumer at `energy.py:6071` — fail-SAFE HOLD `_paused_by_grid_cap` (unchanged from Rev 2/3/4).**

**D4-C — persisted analytics `grid_import_kw` / `solar_export_kw` (`energy.py:3129-3130`) — NULL propagation (unchanged).**

**D4-D — `battery_power_w` inline refactor + PAIRED call-site pause/RELEASE split (Rev-5 HIGH-C fix).**

Producer (`energy_battery.py:1546-1570`): route through `_read_fresh_power_w("battery_power", DEFAULT_BATTERY_POWER_MAX_AGE_S, stamp="last_reported")` with sign-flip at the call site. **New const** `DEFAULT_BATTERY_POWER_MAX_AGE_S: Final = 180`. Display prop at `:1530` unchanged.

**D4-D-0 (NEW Rev-5): extend `determine_battery_drain_actions` signature** in `energy_pool.py` (both EVSE at `:2140`-ish and plug at `:3705`-ish variants):

```python
def determine_battery_drain_actions(
    self,
    *,
    battery_power_w: float | None,
    battery_soc: float | None,
    soc_threshold: int,
    reserve_soc: int | None,
    force_charge_active: bool,
    solar_replenishing: bool,
    is_offpeak: bool,
    dp_forcing: bool = False,
    now_local=None,
    must_start_by_min: int | None = None,
    battery_power_unknown: bool = False,   # NEW Rev-5
) -> list[dict]:
    """... battery_power_unknown=True means the CT read was rejected as
    stale. Under this flag: RELEASE branches (force_charge, must_start_by,
    DP-forcing) evaluate normally; PAUSE-evaluation is skipped and any
    existing `_paused_by_battery_drain` membership is HELD. Default False
    preserves fresh-path byte-identity."""
```

Inside the function (both variants), the release branches (force-charge at `energy_pool.py:2147-2150` / `:3723-3726`; `must_start_by_min` L1 hard release at the point it's honored in the plug variant that consumes `must_start_by_min`; DP-forcing release) execute BEFORE any `battery_discharging` check. The `battery_discharging = (battery_power_w is not None and battery_power_w < -100)` line and its downstream pause-add logic are gated on `not battery_power_unknown`. When `battery_power_unknown=True`, the pause-add path is a no-op (memberships persist); when False, behavior is byte-identical to today.

**D4-D-1 (Rev-5 corrected): call site at `energy.py:6161` — EVSE drain call.**

```python
_bp = self._battery.battery_power_w
drain_actions = self._ev.determine_battery_drain_actions(
    battery_power_w=_bp,
    battery_soc=self._battery.battery_soc,
    soc_threshold=self._ev_battery_drain_soc,
    ...
    battery_power_unknown=(_bp is None),   # NEW Rev-5
)
```

**D4-D-2 (Rev-5 corrected): call site at `energy.py:6317` — smart-plug drain call.** Mirror; `must_start_by_min=self._dp_must_start_by_min` is already passed and MUST still be honored under `battery_power_unknown=True` (this is the operator's L1 3am release — the one Rev-4 accidentally suppressed).

**Tests (Rev-5):**
- `test_drain_stale_battery_power_holds_pause_set_evse` — bay in `_paused_by_battery_drain`, `battery_power_w = None` for 5 ticks, membership persists.
- `test_drain_stale_battery_power_holds_pause_set_plugs` — mirror for plugs.
- `test_drain_stale_battery_power_still_honors_force_charge_release` (Rev-5 HIGH-C anchor) — plug in `_paused_by_battery_drain`, `battery_power_w = None`, `force_charge_active = True` → membership CLEARED (release path evaluated) despite stale CT.
- `test_drain_stale_battery_power_still_honors_must_start_by` (Rev-5 HIGH-C anchor) — L1 socket in `_paused_by_battery_drain`, `battery_power_w = None` for 6 hours, wall-clock crosses `must_start_by_min` → membership CLEARED (hard release path evaluated) despite persistently dead CT. **This is the anti-strand test.**
- `test_drain_producer_gate_without_call_site_unknown_flag_regresses` (mutation anchor) — mutate D4-D-1 to omit `battery_power_unknown=(_bp is None)` (or hard-code False); pause-hold test fails. Restoring re-passes.
- `test_drain_over_scoped_skip_regresses_release` (mutation anchor NEW Rev-5) — mutate D4-D-1 to Rev-4's `if _bp is None: return` shape; `must_start_by` test fails. Confirms the pause/release SPLIT is load-bearing.

**D4-E — billing `CostTracker._get_net_power` at `energy_billing.py:144-191` — fresh-read migration for both branches (unchanged from Rev 4).** Import `_state_age_s` from `.energy_battery`.

**D4-F — Envoy restart cache write gating at `energy.py:2455-2460` (Rev-4 preserved).** Gate on `_soc_source_last == "envoy"`.

**D4-G — Load-shed sustained-window drain at `energy.py:7381-7387` (Rev-4 preserved).** `_sustained_import_readings.clear()` + return on stale snap.

**D4-H — Breaker guard fail-CLOSED at THREE inline sites (Rev-5 CRIT-A + CRIT-B re-scope).**

The Rev-4 target (`_grid_import_guard_triggered` at `:2635-2646`) is DEAD (see supersession disposition above). The LIVE sites are all shaped:

```python
snap = self._effective_import_kw()
if snap is not None and snap[0] > self._arbitrage_grid_import_guard_kw:
    ... increment self._arbitrage_guard_consecutive_trips ...
    ... if >= ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK: LOCK ...
else:
    self._arbitrage_guard_consecutive_trips = 0   # <-- streak wipe (CRIT-B)
```

Rev-5 change (applied identically at all three sites, only line numbers differ):

```python
snap = self._effective_import_kw()
if snap is None:
    # Rev-5 CRIT-A/B fail-CLOSED: stale net_power (post-D4-A) →
    # treat as "assume over-cap" AND do NOT reset the streak.
    # A value-pinned local CT bypasses _breaker_guard_fail_closed_on_blind
    # (which only compensates when _degraded_telemetry_source is set;
    # a stale-but-numeric local read does not set that flag), so this
    # inline site is the last line of defense for the 12kW panel guard.
    self._arbitrage_guard_consecutive_trips += 1
    if self._arbitrage_guard_consecutive_trips >= ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK:
        # (site-appropriate LOCK block: chunk_completed, aborted_at,
        # aborted_kw = None-sentinel or last-known, warning log naming
        # the stale-CT cause, return the site's chunk-locked value —
        # None or ARBITRAGE_PHASE_WAIT depending on the site.)
        from homeassistant.util import dt as dt_util
        self._arbitrage_chunk_completed = True
        self._arbitrage_guard_aborted_at = dt_util.now().isoformat()
        self._arbitrage_guard_aborted_kw = None   # sentinel: locked on stale, not on measured overdraw
        _LOGGER.warning(
            "Arbitrage grid-import guard: net_power STALE — assuming "
            "over-cap; %d consecutive stale/over-cap ticks. Chunk locked "
            "(retry next chunk).",
            self._arbitrage_guard_consecutive_trips,
        )
        return <site-appropriate locked value>
    _LOGGER.info(
        "Arbitrage grid-import guard: net_power STALE — treating as trip "
        "%d/%d; deferring one tick.",
        self._arbitrage_guard_consecutive_trips,
        ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK,
    )
    return <site-appropriate defer-one-tick value>
elif snap[0] > self._arbitrage_grid_import_guard_kw:
    ... existing over-cap branch UNCHANGED ...
else:
    # Genuine under-cap fresh read — safe to reset the streak.
    self._arbitrage_guard_consecutive_trips = 0
    ... existing under-cap continuation UNCHANGED ...
```

**D4-H-1** applies at `energy_battery.py:3150-3197` (arbitrage CHARGE-phase). Site-appropriate values: defer-one-tick returns `ARBITRAGE_PHASE_CHARGE`, locked returns `ARBITRAGE_PHASE_WAIT`.

**D4-H-2** applies at `energy_battery.py:4523-4547` (attainability `_get_attain_action_charging`). Site-appropriate values: defer-one-tick continues (no early return); locked sets `self._attain_state = "inactive"` and returns `None`.

**D4-H-3** applies at `energy_battery.py:4680-4703` (attainability `_get_attain_action_entry`). Site-appropriate values: defer-one-tick continues; locked returns `None`. NOTE the upstream `_breaker_guard_fail_closed_on_blind("attain_entry")` at `:4676` remains as the DEGRADED-telemetry compensator; D4-H-3 is the LOCAL-stale compensator (disjoint conditions, both required).

**`_arbitrage_guard_aborted_kw = None` sentinel:** locked-on-stale vs locked-on-measured-overdraw needs to be distinguishable in the diagnostic. Add a Rev-5 note in the arbitrage-status sensor's docstring; no new sensor.

**Tests (D4-H, per-site):**
- `test_breaker_guard_charge_phase_trips_on_stale_net_power` (D4-H-1)
- `test_breaker_guard_attain_charging_trips_on_stale_net_power` (D4-H-2)
- `test_breaker_guard_attain_entry_trips_on_stale_net_power` (D4-H-3)
- `test_breaker_guard_streak_holds_on_alternating_stale_and_over_cap` (Rev-5 CRIT-B anchor) — sequence: over-cap, stale, over-cap → streak reaches 2 → LOCK. Under Rev-4/pre-fix code (streak wipe on stale) the same sequence NEVER locks; this test proves the invariant holds.
- `test_breaker_guard_streak_resets_on_genuine_under_cap` (regression) — sequence: over-cap, fresh under-cap → streak reset. Fresh-path behavior unchanged.
- **Neuter→RED per site (mutation anchors):** revert the `if snap is None:` branch to `pass` at ANY ONE of the three sites → the corresponding site test fails; the other two still pass. Confirms the invariant is enforced independently at each site (no co-verified aggregate).
- **Fresh-path byte-identity tests** (`test_breaker_guard_<site>_fresh_over_cap_unchanged`, `test_breaker_guard_<site>_fresh_under_cap_unchanged`) — the existing over-cap and under-cap branches are byte-identical when `snap is not None`.

**Dead helper cleanup (in-cycle):** update the stale comments at `energy_battery.py:519` and `:4829` to reference the three inline sites only (remove the `_grid_import_guard_triggered()` mention). DO NOT delete the def in this cycle; deletion PR follows Live Validation of D4-H per the supersession-triage rule ("only delete after new path is live-validated").

#### Acceptance (D4)
- **Tests:** all above per-sub-deliverable.
- **Neuter→RED:** every sub-deliverable has its own reverse-mutation anchor; D4-D has TWO (pause-hold and release-still-fires); D4-H has THREE per-site (plus the cross-site streak-hold anchor).
- **Live (D4-A/B):** peak-import counter freezes on next Envoy CT stall > 180s.
- **Live (D4-C):** row's `grid_import_kw`/`solar_export_kw` NULL (not 0.0) when `net_power_w is None`.
- **Live (D4-D):** during any observed `battery_power_w` stale window ≥ 180s while a bay is `_paused_by_battery_drain`, membership persists (recorder cross-tab). Rev-5: during any observed stale window that crosses 03:00 with an L1 plug in the set, membership CLEARS at 03:00 (release still evaluated).
- **Live (D4-E):** `_cost_today`/`_import_kwh_today` ±5% vs comparable day; direction = trim.
- **Live (D4-F):** post-restart `envoy_cache` fields either fresh or stale-but-flagged.
- **Live (D4-G):** `_sustained_import_readings` observed to drain on stall; no shed escalation on trailing edge.
- **Live (D4-H):** during any observed net_power stale window while an arbitrage CHARGE chunk is running, `_arbitrage_guard_consecutive_trips` observed to INCREMENT (not reset); if the stall persists past 2 ticks the chunk locks with `_arbitrage_guard_aborted_kw = None` sentinel; diagnostic sensor names STALE as the cause. Post-Live: file the follow-up PR to DELETE `_grid_import_guard_triggered` (`:2635-2646`) per supersession triage.

### D5 — Fold the SIX hand-rolled gates through the helper

Unchanged from Rev 4:

1. `energy_battery.py:882-910` (cloud-SOC A1) — `stamp="last_updated"`; EXPLICIT `age is None → pass (accept)` preserving v5.17.5 fail-OPEN. Anchor `test_cloud_soc_fold_preserves_fail_open_on_missing_stamp`.
2. `energy_battery.py:1136-1150` (cloud-oracle lag D2 tracker) — `stamp="last_reported"`; helper embodies the `max(0.0, …)` clamp at `:1149`.
3. `energy_pool.py:4695-4708` (EVSE per-bay solar) — `stamp="last_updated"`.
4. `energy_pool.py:4406-4413` (grid-follow INV-SF-10) — `stamp="last_reported"`.
5. `sensor.py:12491-12507` (AC-kWh display) — `stamp="last_updated"`; MEDIUM-8 corrected rationale (exception PROPAGATES today → new `stale=True` behavior is strictly BETTER). Anchor `test_ac_kwh_naive_stamp_renders_stale_true_no_exception`.
6. `hvac_override.py:3962` — NOT folded; carded.

### D6 — Pre/post row-rate snapshot

Unchanged from Rev 3 (three pinned `ssh ha sqlite3` queries).

---

### D-OBS — Operator-facing staleness surface + Lovelace tile (Rev-5 MED-D fix applied)

**Rev-5 MED-D corrected `_resolve_source_age` — uses SHORT names per `energy.py:986-996` key_map** (Rev-4 pseudocode incorrectly used CONF_* constants, which would return `"unconfigured"` for every source and silently green-test the HIGH-4 anchor while breaking the tile):

```python
def _resolve_source_age(short_key: str) -> tuple[float | None, str]:
    """Return (age_s, status) where status in {'unconfigured','missing','fresh','stale'}.
    short_key is the SHORT name used by BatteryStrategy._get_entity — one of
    'net_power' | 'battery_power' | 'solar_production' | 'battery_soc' —
    NOT the CONF_ENERGY_*_ENTITY constant."""
    eid = energy._battery._get_entity(short_key)
    if not eid:
        return (None, "unconfigured")
    st = hass.states.get(eid)
    if st is None:
        return (None, "missing")
    age = _state_age_s(st, stamp="last_reported")
    if age is None:
        return (None, "missing")
    return (age, "fresh")   # threshold applied by caller

solar_age_s,          solar_status          = _resolve_source_age("solar_production")
net_power_age_s,      net_power_status      = _resolve_source_age("net_power")
battery_power_age_s,  battery_power_status  = _resolve_source_age("battery_power")
primary_soc_age_s,    primary_soc_status    = _resolve_source_age("battery_soc")
```

The classification loop (`stale_sources`, `unconfigured_sources`, `missing_sources`) unchanged from Rev 4. Only `stale_sources` drives the state-enum "stale" transition in D-OBS-2.

**Rev-5 MED-D regression anchor** (added to the HIGH-4 test suite): `test_envoy_status_short_key_resolution` — inject a fixture where `_get_entity("net_power")` returns a valid entity_id AND `_get_entity("CONF_ENERGY_NET_POWER_ENTITY")` returns None (matching the real key_map behavior); `net_power_status` MUST be `"fresh"` (or `"stale"`/`"missing"` per source state), NOT `"unconfigured"`. Under Rev-4's pseudocode this test fails. Under Rev-5 it passes.

`stale_reason` attribute (Rev-4 LOW-10) preserved.

D-OBS-1 attributes: `solar_age_s`, `net_power_age_s`, `battery_power_age_s`, `primary_soc_age_s`, `stale_sources`, `unconfigured_sources`, `missing_sources`, `fallback_active`, `stale_reason`.

D-OBS-2 (`native_value`): unchanged from Rev 3 (union with existing triggers; only `stale_sources` drives the new "stale" branch).

D-OBS-3 (tile): unchanged from Rev 3 (with Rev-4 rows for `unconfigured_sources`, `stale_reason`).

#### D-OBS Acceptance (Rev-4 + Rev-5)

- `test_envoy_status_unconfigured_net_power_does_not_pin_stale` (HIGH-4 anchor).
- `test_envoy_status_missing_entity_reports_missing_not_stale`.
- `test_envoy_status_stale_reason_last_available_only` (LOW-10).
- `test_envoy_status_short_key_resolution` (Rev-5 MED-D anchor).
- (Rev-3 D-OBS tests preserved.)
- **Live:** attributes populated on both dashboards; `stale_sources == []` on healthy Envoy; per-source ages < each `MAX_AGE_S`.

---

## Non-goals (explicit)

- No new unconsumed staleness sensor.
- No threshold changes to any existing gate.
- No change to `envoy_available` composition.
- No flip of v5.17.5-shipped cloud-SOC fail-OPEN-on-missing-stamp decision.
- No periodic reload / probe / watchdog.
- No change to display props (`battery_power` at `:1530`; AC-kWh `native_value`).
- No unification of hand-rolled thresholds.
- No migration of non-Energy staleness sites (BLE, presence LKG, tracker-stale).
- `hvac_override.py:3962` NOT folded — carded.
- `aggregation.py:6289/6319`, `energy_write_verify.py:1794`, `energy_forecast.py:566` NOT investigated — carded.
- AC-kWh `native_value` staleness gate not added — carded.
- No parallel staleness sensor; no NM push; no `state == "degraded"` enum variant; no PWA tile change.
- **Rev-5: no deletion of `_grid_import_guard_triggered` pre-ship.** Deletion PR follows Live Validation of D4-H (per supersession-triage "only delete after new path is live-validated"). Rev-5 IN-CYCLE update: stale comments at `:519` and `:4829` corrected to reference the three inline sites.

---

## Tier 2-DB review plan (3 framings + Live) — Rev-5 additions

- **Review A — data integrity / read-layer correctness.** Byte-identity fresh path; helper `stamp=` + clamp; LKG stamp; **Rev-5:** verify D4-H fresh-path byte-identity at all three sites (fresh over-cap and fresh under-cap branches unchanged).
- **Review B — signal-chain / cross-coordinator integration + PER-CONSUMER None direction.** Trace each consumer to fail-safe fallback. Re-verify D2-B/D, D3-B. Single-diff gate: D4-A NOT shipped without D4-B/C/E/G/H-1/H-2/H-3 in the same commit; D4-D producer NOT shipped without D4-D-1 AND D4-D-2 AND the `battery_power_unknown` kwarg on `determine_battery_drain_actions`. **Rev-5:** re-grep `_grid_import_guard_triggered` to confirm still zero callers (protect against a concurrent cycle wiring it before our D4-H ships); confirm every release path inside `determine_battery_drain_actions` executes BEFORE any `battery_discharging` check (the pause/release split invariant); confirm `_arbitrage_guard_consecutive_trips = 0` appears ONLY in the genuine-under-cap branch at all three D4-H sites (not in the stale-None branch) — mutation drill: revert any one site's `snap is None` branch to `pass` → per-site test fails.
- **Review C — new surface / test authority + helper HOME correctness.** Const round-trip; tests drive production; discriminating tests actually discriminate. **Rev-5:** verify D-OBS `_resolve_source_age` uses SHORT keys (grep for `_get_entity("net_power"|"battery_power"|"solar_production"|"battery_soc")`, no CONF_* strings in the pseudocode-derived code); verify `test_envoy_status_short_key_resolution` genuinely fails under a CONF_*-arg mutation and passes under the correct short-name form.
- **Review D — Live Validation, post-restart.** D6 queries pre/post. `soc_resolution.primary_age_s` 6h — zero decision-path ticks `source_last == "envoy"` AND `primary_age_s > 300`. **Rev-5:** during any observed net_power stale window while arbitrage or attainability is CHARGING, `_arbitrage_guard_consecutive_trips` observed to INCREMENT (not reset); on ≥2 stale/over-cap ticks, chunk locks with `_arbitrage_guard_aborted_kw = None` sentinel. During any battery_power stale window that spans 03:00 with an L1 plug paused, release fires at 03:00. `envoy_status.stale_sources`, `unconfigured_sources`, `stale_reason` populated correctly on both dashboards. README `Validated <date>` table written back. Post-Live: file supersession PR to DELETE `_grid_import_guard_triggered`.

---

## Files to change

- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — module-level `_state_age_s` (D1); `BatteryStrategy` wrappers (D1); migrate 4 SOC + 2 envelope + 3 power sites (D2/D3/D4-A/D4-D producer); fold A1 gate (D5-1) and cloud-oracle-lag D2 tracker (D5-2); **Rev-5: fail-CLOSED + streak-hold at three inline breaker-guard sites (`:3150-3197`, `:4523-4547`, `:4680-4703`) — D4-H-1/2/3**; stale-comment cleanup at `:519` and `:4829`; `primary_age_s` attribute on soc_resolution.
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` — fold 2 gates (D5-3, D5-4); **Rev-5: add `battery_power_unknown: bool = False` kwarg to both `determine_battery_drain_actions` variants; hoist release branches (force-charge at `:2147-2150` and `:3723-3726`, DP-forcing, `must_start_by_min`) to evaluate BEFORE any `battery_discharging` check; gate the pause-add path on `not battery_power_unknown`.**
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — D4-B fail-safe grid-cap (`:6071`); D4-C NULL persisted row (`:3129-3130`); **Rev-5: D4-D-1/D4-D-2 pass `battery_power_unknown=(_bp is None)` at `:6161` and `:6317`** (was Rev-4 `if None: return`); D4-F cache-save gating (`:2455`); D4-G sustained-window drain (`:7381`).
- `custom_components/universal_room_automation/domain_coordinators/energy_billing.py` — D4-E fresh-read migration for both branches in `CostTracker._get_net_power`; import `_state_age_s`.
- `custom_components/universal_room_automation/sensor.py` — fold 1 display gate (D5-5); import `_state_age_s`; expose `primary_age_s`; D-OBS extend attrs + `native_value`; **Rev-5: `_resolve_source_age` uses SHORT keys (`"net_power"|"battery_power"|"solar_production"|"battery_soc"`), NOT CONF_* constants.**
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — 4 new `DEFAULT_*_MAX_AGE_S` consts.
- `quality/tests/` — new `test_shared_power_read_staleness.py` covering D1-D5 + D-OBS (all Rev-4 + Rev-5 anchor tests).
- D-OBS tile via `ha_config_set_dashboard` (deploy-time, not build).
- `docs/readmes/README_v<next>.md` — Rev-5 additions to Live table: D4-D release-still-fires row, D4-H per-site trip-on-stale + streak-hold row, `_arbitrage_guard_aborted_kw = None` sentinel row.
- **Follow-up PR (post-Live, out of this cycle's diff):** delete `_grid_import_guard_triggered` at `energy_battery.py:2635-2646` per supersession triage.

## Risks & mitigations

- **Test-file collision** — worktree isolation + serialised suite runs.
- **`.pyc` staleness during mutation drills** — `PYTHONDONTWRITEBYTECODE=1` + cache clear before each drill.
- **Silent threshold drift** — Review A explicit checklist.
- **Billing regression (D4-E)** — boot-time INFO summary for first 24h; Review D compares.
- **Rev-4 → Rev-5 partial-ship hazards (updated):**
  - D4-A without D4-H-1/H-2/H-3 in same commit → 12kW breaker guard silently disarmed on any stale-net window (fail-OPEN + streak wipe compounded).
  - D4-D producer without the `battery_power_unknown` kwarg + call-site plumbing → drain guard disarmed OR (Rev-4 shape) EV stranded overnight when CT dies.
  Mitigation: single-diff gate (Review B); mutation-anchor tests for both split-shipping shapes (`test_drain_producer_gate_without_call_site_unknown_flag_regresses`, `test_drain_over_scoped_skip_regresses_release`, per-site `test_breaker_guard_<site>_*`).
- **Dead-helper reintroduction risk.** A concurrent cycle could wire `_grid_import_guard_triggered` before D4-H ships, re-introducing the fail-OPEN we just closed. Mitigation: Review B re-greps at review time; stale comments at `:519` / `:4829` corrected in-cycle so no future planner scoping off comments will target the dead helper.
- **D-OBS state-enum expansion** — grep-verified zero decision consumers; `stale_reason` attribute names trigger.
- **D-OBS attribute drift** — reconciliation-through-shared-helper invariant.
- **D-OBS tile-staleness** — entities card preferred; markdown wrapper requires `entity_id:` watch-list.
- **Rev-5 D4-H `_arbitrage_guard_aborted_kw = None` sentinel** — dashboards / diagnostics that display this value must tolerate None. Grep for consumers before build; if any assume float, coerce at the display site (out-of-cycle, tiny) or use a distinct attribute `aborted_cause: "measured" | "stale"`.

## Open questions for operator (not blocking planning)

- `hvac_override.py:3962` (5th AC-kWh gate) — fold in follow-up or flip fail-OPEN first?
- AC-kWh `native_value` staleness gate — card, or leave?
- Sequential ~600s stale-trust horizon for primary SOC — keep or lower?
- D5 site 1: preserve v5.17.5 fail-OPEN-on-missing-stamp (planned default) or open a follow-up to flip?
- D-OBS: tile section placement per dashboard — builder picks (default) or operator preference?
- Rev-5 D4-H `_arbitrage_guard_aborted_kw = None` sentinel vs. distinct `aborted_cause` attribute — preference?
- Rev-5 deletion PR for `_grid_import_guard_triggered` — file same day as Live Validation success, or fold into next cycle?
- Follow-up cards `AGGREGATION_NET_POWER_STALE_1` and `BATTERY_POWER_W_CONSUMERS_AUDIT_1` — schedule after this cycle or backlog?

---

## Rev 5 change summary (2026-09-01)

Applied per adversarial plan-review FIX-REQUIRED on Rev 4 (all four items verified against source before rewrite):

1. **Rev-5 CRIT-A (D4-H patched dead code)** — grep confirmed `_grid_import_guard_triggered` at `energy_battery.py:2635-2646` has ZERO callers (only def + stale comments at `:519`, `:4829`). D4-H re-scoped to the three LIVE inline breaker-guard sites at `energy_battery.py:3150-3197` (arbitrage CHARGE), `:4523-4547` (attainability charging), `:4680-4703` (attainability entry) — each shaped `if snap is not None and snap[0] > cap`, the exact fail-OPEN shape after D4-A. Rev-5 spec: on `snap is None`, treat as "assume over-cap" (increment streak, honor `ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK`, lock with `_arbitrage_guard_aborted_kw = None` sentinel). Three per-site tests + fresh-path byte-identity tests + per-site mutation anchors. Dead helper triaged per supersession rules: DELETE post-Live-Validation; stale comments corrected in-cycle.
2. **Rev-5 CRIT-B (streak-wipe on stale gap)** — same three sites all end with `else: self._arbitrage_guard_consecutive_trips = 0` (`:3196`, `:4547`, `:4703`). Rev-5 change moves that reset to the genuine-under-cap branch ONLY; the stale branch INCREMENTS the streak (does not reset). Cross-site test `test_breaker_guard_streak_holds_on_alternating_stale_and_over_cap` anchors the invariant (sequence: over-cap, stale, over-cap → LOCK).
3. **Rev-5 HIGH-C (D4-D over-scoped, would strand the EV)** — Rev-4's "skip determine_battery_drain_actions on battery_power_w is None" also skipped the force-charge release (`energy_pool.py:2147-2150`, `:3723-3726`) and the `must_start_by_min` L1 hard release (`energy.py:6329-6331` — "the ONLY hard release the operator's L1 charger gets"). A persistently dead CT would strand overnight. Rev-5 introduces `battery_power_unknown: bool = False` kwarg on both `determine_battery_drain_actions` variants; hoists release branches BEFORE any `battery_discharging` check; gates pause-add path on `not battery_power_unknown`. Two anti-strand tests (`test_drain_stale_battery_power_still_honors_force_charge_release`, `test_drain_stale_battery_power_still_honors_must_start_by`) plus mutation anchor proving the pause/release SPLIT is load-bearing (`test_drain_over_scoped_skip_regresses_release`).
4. **Rev-5 MED-D (D-OBS pseudocode wrong key)** — `_get_entity(key)` at `energy_battery.py:719` expects SHORT names from the key_map at `energy.py:986-996` (`"net_power"`, `"battery_power"`, `"solar_production"`, `"battery_soc"`). Rev-4 pseudocode used CONF_* constants → would silently return `"unconfigured"` for every source and green-test the HIGH-4 anchor while breaking the tile. Rev-5 pseudocode uses short keys; anchor `test_envoy_status_short_key_resolution` fails under CONF_*-form mutation.
5. **LOW-5 line drift corrected throughout:**
   - `_effective_import_kw` def `:2600` (was `:2627`); read at `:2630-2633`.
   - `_grid_import_guard_triggered` (dead) `:2635-2646` (Rev-4 said `:2648` for `return False` line — actual line is `:2645`, block spans `:2635-2646`).
   - `_breaker_guard_fail_closed_on_blind` `:3365` (was `:3358`).
   - EVSE drain call site `:6161` (was `:6162` in one Rev-4 reference).
   - Confirmed unchanged: `:3196`, `:4547`, `:4703` streak-reset lines; `:2147-2150`, `:3723-3726` force-charge release lines; `:6329-6331` `must_start_by_min` L1 release.

Rev-4 verified CLEAR carried forward without change: CRITICAL-1 consumer coverage for `battery_power_w` (Rev-5 HIGH-C refines the mechanism, coverage is complete); HIGH-3 cloud-SOC preserve-accept; HIGH-4 unconfigured/missing split (Rev-5 MED-D fixes the pseudocode key); MED-5 class names + no import cycle; MED-6 6th gate + `max(0.0, …)` clamp; D4-G load-shed sustained-window drain; net_power consumer enumeration otherwise complete (Rev-5 CRIT-B adds streak-wipe row); envoy_status display-only ruling.

Invariant re-verification with the Rev-5 pause/release-split and streak-hold clauses: producer-only + Rev-4-shape gating provably regresses two safety paths (drain: over-hold prevents releases → EV stranded; breaker: streak wiped on stale gap → guard never locks). The discriminating anchor tests (`test_drain_over_scoped_skip_regresses_release`, `test_breaker_guard_streak_holds_on_alternating_stale_and_over_cap`) FAIL the Rev-4-shape build and PASS the Rev-5 build. Invariant holds.

---

## Rev 4 change summary (retained, 2026-09-01)

(Rev-4 summary preserved verbatim from prior revision — CRITICAL-1 paired drain call-site changes at `energy.py:6161`/`:6317`; CRITICAL-2 initial net_power consumer enumeration + D4-G load-shed drain; HIGH-3 D5 site 1 explicit accept mapping; HIGH-4 `_resolve_source_age` split (Rev-5 fixes the key-name bug in the pseudocode); MED-5 class names; MED-6 6th gate + clamp in helper; MED-7 D4-F save_envoy_cache gating; MED-8 sensor.py:12494 rationale corrected; LOW-9 discriminator; LOW-10 stale_reason. Rev-5 supersedes Rev-4 D4-D shape (over-scoped skip → pause/release split) and Rev-4 D4-H target (dead helper → three inline sites) and Rev-4 D-OBS pseudocode key (CONF_* → SHORT); other Rev-4 fixes stand.)

---

## Rev 3 addition summary (retained)

(D-OBS added as ADDITIVE deliverable; extends existing `envoy_status` sensor; Lovelace tile on `ura-v8` + `ura-v6`; NO parallel sensor, NO NM push, NO PWA tile change. Rev-4 HIGH-4 corrected the classification; Rev-5 MED-D corrects the pseudocode's `_get_entity` key form.)

---

## Rev 2 fix summary (retained)

(`stamp=` arg + `last_reported` fallback; D3-B; D2 4-site expansion; D4-B/C/E; LKG stamp arithmetic; 5th AC-kWh gate scope-carded; D5 sensor.py byte-identity claim corrected; D6 pinned queries. Rev-4 supersedes MED-5, MED-6, MED-8; Rev-5 supersedes D4-D shape, D4-H target, D-OBS pseudocode. Other Rev-2 fixes stand.)
