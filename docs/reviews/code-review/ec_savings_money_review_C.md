# EC savings money — Review C (test authority, per-site source mutation)

Branch fix/ec-savings-money a1866c5a vs develop ca3a0eb6. Verdict: SHIP (after the added tests, commit on branch).

Method: independently enumerated 133 load-bearing sites across energy.py, energy_billing.py, energy_const.py, energy_tou.py, database.py, sensor.py (builder listed 33+8). One mutation per run, restored in-process, git status clean after. Suite = test_ec_savings_money, test_energy_savings_unification, test_energy_consumption, test_ec_bill_cycle_day_wired, test_ec_bill_divergence_smarthub_stats, test_inclement_state_sensor, test_house_energy_correctness, test_v4_6_8_rate_reconciliation.

Result: 106 RED on first pass, 27 GREEN survivors (untested). After adding 14 tests: 130 RED, 3 GREEN, all equivalent mutants:
- E8 negative restore values (ctor clamps)
- E19 served gate (discharge_savings_usd returns 0 for served<=0)
- B26 now=None (outer try/except returns None)

Survivor groups killed: PA effective rate read at tick `now`; restore max-age arg (12 h); save guard before load; discharge-only ticks in persist cadence; real __init__ leaves inventory unloaded; kill-switch False (apply no-op + legacy charge row); ArbitrageInventory ctor/add/drain/cap/to_dict/min-kWh; rte guard; battery_served excludes solar; PA exception returns None; local-day modifier (UTC-5); guarded ALTER idempotency; sensor attrs kwh_discharged_today/this_cycle and last_cycle basis_source/kwh_discharged.

Pre-existing (not in diff): test_v47x_ev_tou_hardening pollutes test_house_energy_correctness when co-run (7 failures); excluded from the drill.
