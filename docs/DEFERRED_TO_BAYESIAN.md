# Deferred Entities — Bayesian Predictive Intelligence (v4.0.0)

Entities removed in v3.20.2 (stub cleanup). Each will be reimplemented with real
data pipelines in the v4.0.0 Bayesian Predictive Intelligence milestone.

See `docs/ROADMAP_v11.md` section v4.0.0 for milestone definitions:
- **B1:** Bayesian model core — posterior update engine, time-of-day bins
- **B2:** Prediction sensors — per-person next-room prediction with confidence
- **B3:** Pre-emptive actions — high-confidence prediction triggers
- **B4:** Energy integration — occupancy-weighted consumption prediction

## Sensors

| Entity Class | Original Intent | Data Source Needed | v4.0.0 Milestone |
|---|---|---|---|
| OccupancyPercentageTodaySensor | % of day room occupied | room_transitions DB + time calc | B2: Prediction sensors |
| EnergyWasteIdleSensor | kWh wasted in vacant rooms | energy_history + occupancy join | B4: Energy integration |
| MostExpensiveDeviceSensor | Highest-cost device | circuit_state + TOU rates | B4: Energy integration |
| OptimizationPotentialSensor | Monthly savings estimate | Bayesian + energy model | B4: Energy integration |
| EnergyCostPerOccupiedHourSensor | $/hour when occupied | energy_daily + occupancy | B4: Energy integration |
| TimeUncomfortableTodaySensor | Minutes outside comfort zone | environmental_data + thresholds | B2: Prediction sensors |
| AvgTimeToComfortSensor | Avg recovery to comfort | environmental_data time series | B2: Prediction sensors |
| WeekdayMorningOccupancyProbSensor | AM weekday occupancy % | Bayesian posterior (room_transitions) | B1: Bayesian model core |
| WeekendEveningOccupancyProbSensor | PM weekend occupancy % | Bayesian posterior (room_transitions) | B1: Bayesian model core |
| TimeOccupiedTodaySensor | Hours occupied today | room_transitions + time calc | B2: Prediction sensors |
| OccupancyPatternDetectedSensor | Pattern description | Pattern learning + Bayesian | B1: Bayesian model core |

## Binary Sensors

| Entity Class | Original Intent | Data Source Needed | v4.0.0 Milestone |
|---|---|---|---|
| OccupancyAnomalyBinarySensor | Unusual occupancy detection | Bayesian + z-score | B2: Prediction sensors |
| EnergyAnomalyBinarySensor | Unusual energy usage detection | MetricBaseline + Bayesian | B4: Energy integration |

## Buttons

| Entity Class | Original Intent | Data Source Needed | v4.0.0 Milestone |
|---|---|---|---|
| ClearDatabaseButton | Clear old database entries | Database cleanup logic | B1: Bayesian model core |
| OptimizeNowButton | Generate optimization report | Bayesian + energy model | B4: Energy integration |

## Signals

| Signal/Class | Original Intent | Data Source Needed | v4.0.0 Milestone |
|---|---|---|---|
| SIGNAL_COMFORT_REQUEST / ComfortRequest | Cross-coordinator comfort adjustment requests | Zone comfort model + Bayesian predictions | B3: Pre-emptive actions |
