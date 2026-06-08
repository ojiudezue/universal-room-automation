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

## Live Validation — prospective (to be recorded post-restart, Review D)

- **Live:** EV status sensor exposes a `proactive_offpeak_holds` attribute
  (JSON list; `[]` when no EVSE is held). Confirm entity_id + attribute present.
- **Live:** during an off_peak period, an EVSE that is off and not guard-held is
  turned ON proactively; `_classify_evse` reports `offpeak_proactive_on`
  ("off-peak proactive turn-on") for it. (Off-peak window required to observe.)
- **Live:** guard precedence holds — an EVSE under battery-drain / fill-priority /
  grid-cap / arbitrage is NOT proactively turned on (no on→off flap).
- **Live:** after a clean restart, the persisted guard sets + `_force_charge_until`
  restore from KV; a >10h-stale row is ignored (read-time filter).
- **Live (unit):** `sensor.ura_energy_*` consumption sensors declared kW report
  plausible kW (single-digit/teens), not ~1000x; grid cost-per-hour is sane.
- **Live:** no URA ERROR logs attributable to this cycle within an hour of restart.

_Note: Envoy (energy source) confirmed live and feeding data immediately before
this deploy (production/consumption flowing; `energy_envoy_available=on`)._
