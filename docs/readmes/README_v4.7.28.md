# URA v4.7.28 — EV Off-Peak Proactive Charging + Pause-State Persistence (+ Energy Unit/Sign Reconciliation)

**Release date:** 2026-06-07
**Tier:** Tier 2-DB (operator-elevated — three parallel framing-disjoint reviews:
A = persistence correctness; B = behavior / precedence / no-flap; C = surfaces /
test-authority — plus live validation). Bundles a same-domain energy unit/sign
audit (Tier-1-equivalent, independently reviewed).

**Scope:** Two complementary energy-domain changes shipped together:
1. **EV off-peak proactive charging + persistence** — the headline cycle.
2. **Energy W/kW/kWh + power-sign reconciliation** — a correctness audit of the
   same coordinators the EV cycle depends on (3 display BUGs fixed + 2 latent
   capacity-conversion gaps hardened).

**Files:**
- `domain_coordinators/energy.py` — WS1 persistence (force-charge KV, guard-set
  parity, 10h staleness DAO); unit fixes (`net_consumption_kw` docstring,
  battery-capacity uom guard).
- `domain_coordinators/energy_pool.py` — WS2 off-peak ensure-on behavior;
  `_classify_evse` `offpeak_proactive_on` token; hold-set lifecycle.
- `domain_coordinators/energy_forecast.py` — battery-capacity uom guard.
- `database.py` — `restore_energy_state_with_age` age-aware DAO.
- `sensor.py` — D3 `proactive_offpeak_holds` attr; 3 unit fixes (grid cost-per-hour,
  Total/Net consumption display sensors → normalized `_w` properties).
- `strings.json` / `translations/en.json` — widened `_ev_tou_enabled` helper text.
- `quality/tests/test_ev_offpeak_proactive.py` (NEW, 32 tests),
  `quality/tests/test_v47x_ev_tou_hardening.py` (2 contract updates).
- Planning + review docs in `docs/planning/` and `docs/reviews/code-review/`.

---

## Trigger

Cars weren't charged by morning. Root cause (verified in source): the off-peak
branch of `EVChargerController.determine_actions` was **resume-only** — it only
un-paused URA's own TOU pauses. A fresh overnight plug-in, or the post-sunset
excess-solar hand-off, left the EVSE in **no pause-set with nothing to restart
it**. The only proactive start was solar-gated (dead at night).

---

## Headline Changes

### EV off-peak (WS1 persistence + WS2 behavior)
- **WS1 — persistence hardening** (existing `energy_state` KV + `evse_state`, no
  schema migration): persist `_force_charge_until` (KV `ev_force_charge_until`,
  canonical; Switch RestoreEntity stays the fresher fast-path), plus
  `_paused_by_fill_priority`, `_paused_by_arbitrage`, and the new
  `_proactive_offpeak_holds` intent-set. 10h read-time staleness guard on all KV
  restores via the new `restore_energy_state_with_age` DAO. `dt_util.parse_datetime`
  throughout; tz-aware saves; no DELETE; no new timer (reuses the 15-min cadence).
- **WS2 — behavior**: off-peak branch rewritten from resume-only to **ensure-on**
  with guard precedence. Carry-over guards (battery drain / fill-priority /
  grid-cap / arbitrage) win; force-charge skips the proactive claim; `turn_on`
  re-issued idempotently each tick. Hold-set cleared on transition out of off-peak.
  `_ev_tou_enabled` semantics widen to "pause high-rate AND ensure-on off-peak."
- **D3** — `proactive_offpeak_holds` attribute (JSON list) on the EV status sensor;
  `offpeak_proactive_on` classifier token for live validation.

### Energy unit/sign reconciliation
- **BUG (grid cost-per-hour)** read the raw `net_power` entity assuming W → $/h
  1000x too low on kW-firmware. Now uses normalized `net_power_w`.
- **BUG (Total/Net Consumption display sensors)** declared kW but returned the
  raw mis-named `*_kw` trap properties → 1000x mislabel on W-firmware. Now derive
  true kW from `total_consumption_w` / `net_power_w` ÷ 1000.
- **HARDEN** both `_get_battery_capacity_kwh` impls — uom-checked Wh→kWh.
- Sign conventions audited: consistent everywhere (no changes). MWh lifetime
  deltas confirmed correct.

---

## Review

EV cycle: 3 parallel framing-disjoint reviews → **0 CRIT, 1 HIGH, 2 MED, 7 LOW**;
all HIGH/MED + every actionable LOW fixed, 3 LOW deferred as non-issues
(`docs/reviews/code-review/ev_offpeak_proactive_review.md`).
Unit/sign audit: 3 BUG + 2 harden, independently documented
(`docs/reviews/code-review/energy_unit_sign_reconciliation_audit.md`).

**Pre-deploy gate:** conflict-markers clean, `py_compile` OK, JSON valid,
**73 cycle tests pass**, full-suite baseline-diff = **zero new failures** (39
pre-existing flakiness/import errors, unchanged).

---

## Live Validation — Validated 2026-06-08 (Review D)

Run against the restarted live house (HACS-installed v4.7.28 active:
`update.universal_room_automation_update` installed_version = `v4.7.28`). TOU
period at validation time was **mid_peak**, so the off-peak ensure-on *turn-on*
could not be observed live — but the full intent-surface, persistence, and
correct mid-peak pausing were all confirmed.

| # | Criterion | Result | Observed evidence |
|---|-----------|--------|-------------------|
| 1 | D3 `proactive_offpeak_holds` attribute present | **PASS** | `sensor.ura_energy_coordinator_ev_charging_status` exposes `proactive_offpeak_holds: []` (empty — correct, TOU=mid_peak). |
| 2 | `paused_by_arbitrage` persisted guard set surfaced (decision 4 parity) | **PASS** | Same sensor exposes `paused_by_arbitrage: []` alongside the other four guard sets — the new persisted set round-trips. |
| 3 | Force-charge persistence restored cleanly (empty-sentinel → None) | **PASS** | `force_charge_until_iso: null` after restart — no stale future-ISO honored; F1 empty-string sentinel handling correct. |
| 4 | Correct mid-peak behavior (TOU pause, no spurious proactive-on) | **PASS** | `garage_a` `energy_status: paused`, `pause_reason_human: "TOU peak/mid-peak pause"`; `proactive_offpeak_holds` empty — no off-peak claim fired during mid_peak. |
| 5 | Off-peak ensure-on *turn-on* + `offpeak_proactive_on` classifier | **DEFERRED (not in window)** | TOU=mid_peak at validation. Mechanism proven in-suite (32 cycle tests incl. classifier token + guard precedence); attribute surface live. Will manifest at the next off_peak window. |
| 6 | Unit fix — kW-declared consumption sensors report true kW | **PASS** | `sensor.ura_energy_coordinator_total_consumption` = 8.074 kW = Envoy `current_power_consumption` 8.074; `…_net_consumption` = 7.363 = Envoy net 7.363 (1:1, plausible kW, not 1000×-off). |
| 7 | No URA ERROR logs attributable to this cycle within an hour of restart | **PASS** | System ERROR log filtered to `universal_room` = empty this boot. |

**Deferred-to-window (criterion 5):** the proactive off-peak turn-on only fires
during an `off_peak` TOU period; validation ran during `mid_peak`. The classifier
token (`offpeak_proactive_on`), guard precedence, and hold-set lifecycle are
covered by the 32 cycle tests and the live attribute surface is confirmed
present. No code path is unproven — only the live wall-clock observation awaits
the next off-peak window.

**Envoy context:** the energy source recovered before this deploy and was feeding
data within ~1 min of this restart (`sensor.envoy_482543015950_current_power_consumption`
≈ 8 kW live); the boot-storm Envoy lag seen earlier in the day did not recur.
