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

## Live Validation (Review D) — prospective criteria
- [ ] Clean restart; zero new URA ERRORs; no write-queue saturation.
- [ ] Banking switch visible on EC device, ON; `banking_enabled: true` attr on the HVAC house-state sensor.
- [ ] **Operator hands-on (next good-solar day):** flip banking OFF mid-bank → `solar_banking_zones` empties within one cycle and thermostats return to preset range.
- [ ] Run Cycle Now button AVAILABLE within ~3 min of boot (30s/180s refreshes — closes the v5.3.5 finding).
- [ ] Tonight at home_night: presence blip in an occupied bedroom does NOT kill a running fan; a genuinely-vacated room's fan stops at the normal timeout.
- [ ] Tonight: zero zone `away`-flips while the master bedroom is occupied at home_night (the v4.7.13-gap live case); suppression line appears ONCE per zone at INFO then goes quiet.
- [ ] Carried-forward operator hands-on (v5.3.3/5): escalation stage→instant buttons→Cancel; options-flow label rendering.

*Replaced with observed results post-restart per the README write-back rule.*
