# URA v5.3.6 — Solar Banking Toggle + Fan-Trust State Extension

Combined release (one restart):
1. **Solar HVAC banking master toggle** — Tier 1 (1 CRIT + 1 HIGH + 2 MED fixed). Ledger: `docs/reviews/code-review/solar_banking_toggle.md`
2. **Fan-trust extension sleep→{home_night,waking}** — operator-mandated Tier 2-DB (1 CRIT + 4 HIGH + 5 MED fixed + 4th pass). Ledger: `docs/reviews/code-review/fan_trust_state_extension.md`
3. Rides along: OC Run-Cycle-Now post-boot availability refreshes (1bc4f1b, v5.3.5 live finding).

## What ships

### Banking toggle (operator: "fires all the time on good solar days, pins HVAC")
- `switch.ura_energy_coordinator_solar_hvac_banking` on the EC device, default ON. OFF = banking branch never fires; zones banked at flip-time release within one cycle to the TRUE baseline (`_last_emitted_range`, not the live thermostat echo — the review's key catch); restart-mid-bank reconciles one-shot; `banking_enabled` attr distinguishes operator-OFF from conditions-unmet.

### Fan-trust extension (operator: extend STOP control; bidirectional)
- **Extended to home_night + waking:** blip stop-protection (bedroom-gated at these states — people roam, so zone-level "person home" isn't room evidence outside sleep), the zone preset person-trust (fixes the live master-bedroom `away`-flip at home_night), and the sleep speed cap (bedrooms-only at flank states; house-wide at sleep).
- **House-state fan activation REMOVED entirely (operator revision 2):** fan starts are temperature-driven only, at every state incl. sleep — the pre-existing hotfix-B sleep auto-start is gone. ON = hold-protected; OFF = stays off unless warm; manual actions win.
- **`fan_sleep_policy` now actually works on coordinator-managed fans:** read live per cycle (was frozen at startup); `normal` = no cap; `off` = never coordinator-activated + conservatively capped (the build had silently removed even the cap).
- **Bidirectionality (operator supreme criterion):** genuinely-empty rooms still vacancy-expire; an emptying house still reaches `away` (v4.7.14 veto path proven untouched).

## Live Validation — Validated 2026-06-12

**Deploy-night incident (NOT this release):** the first post-deploy boot broke — all 40 entries stranded `not_loaded`. Root cause was an unresponsive Envoy: `enphase_envoy` hung → HA stage-2 bootstrap timeout cancelled URA's queued setups (`after_dependencies` coupling), and on the recovery boot the one-shot Envoy validation race dropped the EnergyCoordinator (`envoy_entity_missing` at 00:41:38, entity appeared 00:41:55). v5.3.6 code was exonerated by diff; the broken boots also exposed EC sub-switch restore poisoning (`unavailable` last-state restored as OFF — all 6 intended-ON switches silently disabled, manually restored 06:15Z). All three failure modes fixed in **v5.3.7** (`PLANNING_ec_envoy_boot_decoupling.md`).

| Criterion | Result | Evidence |
|---|---|---|
| Clean restart, zero URA ERRORs | PASS (after Envoy incident resolved) | Final boots 06:09Z + 15:58Z: 40/40 entries loaded; no URA ERROR lines; no write-queue saturation |
| Banking switch on EC device, ON; attrs | PASS (with caveat) | `switch.ura_energy_coordinator_solar_hvac_banking` registered + ON. Caveat: initially restored OFF via the restore-poisoning bug (Bug Class #52, fixed v5.3.7) |
| Run Cycle Now available ≤3 min of boot | PASS | `button.ura_optimization_coordinator_run_cycle_now` state `unknown` (=available) at 03:09:19Z, ~3 min after entry load — v5.3.5 finding closed |
| home_night/sleep fan blip protection | PASS | Both master-bedroom fans ran continuously 03:13→11:00Z through sleep: Fanimaton `on` throughout (only 2-8s RF `unavailable` blips, zero off-transitions); PolyFan single unbroken `on`. No mid-night stops despite 3 restarts |
| Zero zone away-flips, master occupied | PASS | House state held `sleep` 06:18→11:00Z continuously (organic wake at exactly 06:00 CDT → waking → home_day); Zone 1 preset history shows `sleep`/`manual` only, zero `away` presets during sleep |
| Suppression line once-per-zone | UNVERIFIED-QUIET | Log rotated across 3 restarts; no repeated suppression spam observed in surviving windows |
| Operator hands-on: banking OFF mid-bank | OPEN | Awaiting next good-solar day |
| Carried-forward: escalation buttons, label rendering | OPEN | Operator hands-on, carried to next cycle |

Boot-default `away` blips at 03:06/05:38/06:12Z were restart artifacts (HouseStateMachine boots AWAY by design), each re-resolving to sleep within ~7 min. Zone 1 `sleep`↔`manual` preset churn near 05:40 CDT is pre-existing thermostat hold-boundary behavior, out of scope.
