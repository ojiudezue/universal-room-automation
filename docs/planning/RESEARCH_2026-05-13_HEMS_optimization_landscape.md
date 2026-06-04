# External Research — HEMS Optimization Landscape

**Date:** 2026-05-13
**Method:** Web search + code-reading agent (general-purpose subagent, ~10 min, ~30 tool calls)
**Purpose:** Inform URA's build/adopt/fork decision for Advanced Energy Management (v4.7.x). Linked from `docs/planning/PLANNING_v4.7.x_advanced_energy_management.md`.
**Constraint:** Research focus is on **general residential HEMS optimization** — explicitly NOT EV-specific optimizers (EVs treated as just another controllable load).

This memo is the agent's output as delivered. Edits limited to header + light formatting. All citations preserved.

---

## Thread 1: emhass deep-dive

**Algorithm.** emhass solves a **Mixed-Integer Linear Program via CVXPY**, defaulting to the **HiGHS** solver (Gurobi/CPLEX optional). It is *not* PuLP. See `src/emhass/optimization.py:7-9` (`import cvxpy as cp`) and `:2811-2872` (solver dispatch). Three modes: `perform_perfect_forecast_optim`, `perform_dayahead_forecast_optim`, `perform_naive_mpc_optim` (receding-horizon, line 3118).

**Objective.** Maximization framing with three configurable cost functions in `_build_objective_function` (`optimization.py:887-1001`): `profit` (revenue − cost), `cost` (cost only), `self-consumption`. Battery cycle cost, inverter/battery "stress" penalties, and thermal-battery comfort terms are additive (`:971`, `:994-998`). Single objective; comfort enters as soft penalty, not a Pareto front.

**Constraints.** Battery SOC bounds, separate charge/discharge power caps (`plant_conf["battery_discharge_power_max"]`, `:845`), SOC init/final parameters (`:145-146`), energy-balance over horizon (`:1285`), deferrable-load total energy + start-count constraints (`:2159`), thermal-battery temperature dynamics with heat-pump COP (`:291-311`).

**Horizon.** Default `opt_time_delta=24h` (`:43`, `:69`); `delta_forecast_daily` overrides; MPC mode requires `prediction_horizon >= 5×timestep` (`:3170-3172`). Receding-horizon, **deterministic** — no scenario tree, no robust formulation.

**Forecasts.** PV uses pvlib + Open-Meteo weather (temp, humidity, cloud cover, DNI — `forecast.py:304-311`). **Load forecast does NOT use weather.** `MLForecaster` is `skforecast.ForecasterRecursive` with AR lags + `add_date_features` only (hour/day/week — `machine_learning_forecaster.py:139-209`). This is a significant gap for a Bayesian/weather-correlation system like URA.

**License.** MIT (`README.md`).

**"Cruft vs core" boundary.** The pure algorithm is **`optimization.py` (3,247 LOC) + a slim adapter for params**. Deployment cruft = `web_server.py`, `command_line.py`, `connection_manager.py`, `retrieve_hass.py`, `websocket_client.py`, MQTT publishers, the add-on container, and the YAML/web config flow. A fork could keep `optimization.py` + `forecast.get_power_from_weather` and discard ~60% of the repo.

**Known limitations.** HA recorder DB performance issues for retrieving 2 days of load history; brittle API hangs (issue #648); complex config; deterministic-only (no uncertainty). Community complaints center on setup friction, not algorithm correctness.

## Thread 2: MPC literature

**Best practice** for residential PV+battery+TOU is **MILP-MPC with 24h receding horizon at 15-min resolution**, deterministic with re-solve every 15min absorbing forecast error ([MDPI 2023](https://www.mdpi.com/2313-0105/9/6/316), [Systematic Review 2025](https://www.mdpi.com/1996-1073/18/19/5262)). **Stochastic MPC outperforms deterministic** when forecast error is high ([ScienceDirect 2023](https://www.sciencedirect.com/science/article/pii/S0378778823009830), [Energy 2022](https://www.sciencedirect.com/science/article/abs/pii/S0306261922010509)) but at 5–20× compute cost. Reported savings vs no-optimization baselines: **15–35% bill reduction** typical; up to 81% in heavily TOU-arbitrage scenarios (review above). Canonical non-emhass open-source MPC refs: [hq-opensource/predictive-control](https://github.com/hq-opensource/predictive-control), [tobirohrer/building-energy-storage-simulation](https://github.com/tobirohrer/building-energy-storage-simulation), [do-mpc](https://github.com/do-mpc/do-mpc) (general toolbox).

## Thread 3: RL state

**Research-grade, not production.** Practical residential RL deployment "remains largely undemonstrated" ([Springer 2025](https://link.springer.com/article/10.1007/s42452-025-07529-6)). MPC beats RL on comfort-normalized energy savings in field trials ([arXiv 2510.01475](https://arxiv.org/abs/2510.01475)). Sample efficiency typically **months-to-years** of household data without behavior cloning from MPC ([ACM e-Energy 2025](https://dl.acm.org/doi/10.1145/3679240.3734605)). Common failure: distribution shift when weather regime changes. **Not viable as URA's primary control layer.**

## Thread 4: Weather-aware load forecasting

State-of-practice for 24h-ahead, 15-min residential load is **gradient-boosted trees (LightGBM/XGBoost) with weather + calendar exogenous features**, often ensembled with CatBoost ([Nature Sci Rep 2025](https://www.nature.com/articles/s41598-025-91767-6), [Energy 2025](https://www.sciencedirect.com/science/article/pii/S0360544225036230)). XGBoost-ANN ensembles reach MAPE ~9.7% on residential ([ScienceDirect 2025](https://www.sciencedirect.com/science/article/abs/pii/S0378779625000690)). Bayesian inference is **uncommon** as the headline forecaster in 2023–2025 papers; it's used for uncertainty quantification atop a point forecast. Recommendation: keep URA's Bayesian *correlation* discovery as feature engineering, but the predictor itself should be **LightGBM with weather exog** via `skforecast.ForecasterRecursive`. No HEMS-specific weather-aware load library exists — roll your own on skforecast.

## Recommendation (agent's original)

**Commit to: deterministic MILP-MPC, 24h horizon, 15-min step, re-solve every 15min.** Skip stochastic/RL until v6+.

**Adopt-as-backend, do NOT fork the whole project: vendor `emhass/optimization.py` only.** It's MIT, the MILP formulation is mature, and replacing it would burn 6+ months reimplementing battery/deferrable/thermal constraints. Wrap it behind URA's domain coordinators; feed it forecasts from URA's own data layer.

**Replace emhass's load forecaster with LightGBM + weather exog** (URA's Bayesian weather data is the differentiator — emhass leaves this on the table). Keep emhass's pvlib PV forecast.

**Discard:** emhass web server, MQTT, config flow, container, REST shim. URA already owns those surfaces.

---

## Post-research correction

The agent's "vendor emhass" recommendation was later invalidated by the coupling-layer recon. URA's Enphase control surface is reserve_soc (one number set every 5 min) + charge_from_grid (binary). A 96-bucket MILP plan is mostly waste for that surface — only the next-hour reserve_soc line of the plan ever gets used.

The right takeaway from this research is **Thread 4 only**: the LightGBM + weather-exog load forecaster is the gap. emhass's MILP optimizer is not the right tool given URA's actual coupling layer. See `PLANNING_v4.7.x_advanced_energy_management.md` for the final architecture.

---

**Sources cited (consolidated):**

- emhass GitHub: https://github.com/davidusb-geek/emhass
- MDPI 2023 (Batteries): https://www.mdpi.com/2313-0105/9/6/316
- MDPI 2025 (Energies, systematic review): https://www.mdpi.com/1996-1073/18/19/5262
- ScienceDirect 2023 (Energy & Buildings): https://www.sciencedirect.com/science/article/pii/S0378778823009830
- Energy 2022: https://www.sciencedirect.com/science/article/abs/pii/S0306261922010509
- Springer 2025: https://link.springer.com/article/10.1007/s42452-025-07529-6
- arXiv 2510.01475: https://arxiv.org/abs/2510.01475
- ACM e-Energy 2025: https://dl.acm.org/doi/10.1145/3679240.3734605
- Nature Sci Rep 2025: https://www.nature.com/articles/s41598-025-91767-6
- ScienceDirect 2025 (Energy): https://www.sciencedirect.com/science/article/pii/S0360544225036230
- ScienceDirect 2025 (Energy & Buildings): https://www.sciencedirect.com/science/article/abs/pii/S0378779625000690
- hq-opensource/predictive-control: https://github.com/hq-opensource/predictive-control
- tobirohrer/building-energy-storage-simulation: https://github.com/tobirohrer/building-energy-storage-simulation
- do-mpc: https://github.com/do-mpc/do-mpc
