# Energy Coordinator v3.7.0 — Questions for Review

## Q1: Consumption Tracking Accuracy
The daily consumption baseline uses `import_kwh + export_kwh` as the actual consumption figure.
This is imprecise — real consumption = import + solar self-consumed (not export). We don't have
a "self-consumed solar" sensor. The Bayesian adjustment should compensate over time, but the
initial predictions will be rough. Should we add a template sensor for self-consumed solar?

Answer - yes. The information you need is on the Envoy Device. For example look at the lifetime sensors e.g. sensor.envoy_202428004328_lifetime_battery_energy_discharged
These always increase but if you sum a 24 hour period you should have what you need in combination with other lifetime sensor. Reflect the logic from this to make sure you understand and have what you need.

## Q2: EV Charger Pause Strategy
Currently pauses EVs during both peak AND mid-peak. Mid-peak rates are moderate — do you want
EVs to continue charging during mid-peak? This is a simple change in `energy_pool.py` line 223.

Answer - No. Preserve the ability to pause mid peak. My current EV strategy is to charge at night at the lowest rates or with excess solar ie during fat days after the battery is full and pre-cool and EV can coexist based on prediction.

## Q3: Pool Speed During Mid-Peak
Pool speed reduction only happens during peak (not mid-peak). Should mid-peak also get a
partial speed reduction (e.g., 50 GPM instead of 30)?

Answer - No. Peak is fine. We need very low turbulence with the poo adjustment to prevent problems.

## Q4: Bill Cycle Day
Defaulted to 23rd based on PEC billing. Is 23rd correct for your billing cycle?

Answer - yes

## Q5: Storm Forecast Sources
Currently using weather entity conditions (lightning/hail/tornado). Should we also check
NWS alerts or a separate severe weather sensor?

Answer - If we can. What are the options?

## Q6: Dashboard Entity ID Verification
The Energy tab entity IDs are predicted based on HA's naming convention for `has_entity_name=True`.
They'll be `sensor.ura_energy_coordinator_<name>`. After deployment, some IDs might differ
if HA deduplicates or slugifies differently. We'll verify and patch after first restart.

## Q7: Enphase Codicil Confirmation
Per the codicil, the battery strategy now uses self_consumption exclusively with reserve level
as the primary control lever. Never uses savings mode. The key strategies:
- Peak: self_consumption + low reserve (battery covers load, solar exports)
- Mid-peak: self_consumption + reserve = current SOC (hold charge for peak)
- Off-peak: self_consumption + low reserve (charge from solar)
- Storm: backup mode (or self_consumption + grid charging if SOC low)

Does this match your intended behavior?

Answer - I think so. Do you see any critiques that make this inadequate?. We may need a test run on a sunny day to see how the system behaves. Do we have what we need to monitor a test run properly?
