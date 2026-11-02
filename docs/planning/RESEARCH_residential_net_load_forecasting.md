# RESEARCH — Residential day-ahead net-load forecasting (prior art for R1/R2 + EC tomorrow forecast)

**Filed:** 2026-11-01 · **Mode:** research only, no code · **Feeds:** `PLANNING_net_energy_program_R1_R7_R2.md` (rev 2) and `PLANNING_ec_savings_and_tomorrow_forecast.md`.

**Verification status, stated honestly:** one source was fetched in full (Predbat docs). Everything else was read from search-result snippets only. A snippet-only source is good enough to point at an idea. It is not good enough to quote a number from as a standard. Each row says which kind it is.

Fit key: **ADOPT** = do in the merged cycle · **LATER** = park with a revival trigger · **NO** = not for URA. Every verdict goes through marginal-benefit pushback: the simplest version first.

## 1. Model family: degree-day regression vs ML at the single-home, daily-total level

| Source | Idea | Fit |
|---|---|---|
| Veit et al., "Household Electricity Demand Forecasting – Benchmarking State-of-the-Art Methods" (2014), https://arxiv.org/pdf/1404.0200 (snippet) | At household level most methods barely beat persistence; MAPE ranges from 5% to over 100%. | **ADOPT as framing.** Every model we ship gets scored against a persistence baseline, not just against the legacy predictor. |
| "Load Forecasting for Households and Energy Communities: Are Deep Learning Models Worth the Effort?" (2025), https://arxiv.org/pdf/2501.05000 (snippet) | Uses same-day-last-week persistence as the baseline; deep models add little at small scale. | **ADOPT** weekly persistence as the baseline arm in the backtest and prediction log. **NO** to deep learning. |
| Gradient boosting for households (Saleptsis et al., 2025; URL not found) | Hybrid beats plain XGBoost/LightGBM and beats persistence. | **LATER.** No evidence it beats a CDD regression on one home's daily total, and the old LightGBM forecaster plan never paid off. Revival trigger: the corrected v1 still misses ASHRAE-style internal targets after 60 days of logged predictions. |
| EMHASS forecast docs, https://emhass.readthedocs.io/en/stable/forecasts.html and `/mlforecaster.html` (snippet) | Default load forecast is naive persistence; the ML option is a KNN regressor over 48 lags. | **NO** to adopting it. It is supporting evidence that a mature OSS energy manager starts from persistence. |

## 2. Temperature feature and balance point

| Source | Idea | Fit |
|---|---|---|
| PRISM (Fels et al., Princeton), ACEEE 1986 proceedings, https://www.aceee.org/files/proceedings/1986/data/papers/SS86_Panel9_Paper_30.pdf (snippet; which ACEEE paper is PRISM was not confirmed) | Degree-day change-point regression with the balance temperature chosen by best fit over a scan of reference temperatures. | **ADOPT.** Replace the fixed 65 °F base with a fitted balance point in the offline fit script. It is a constant change, not new runtime machinery. |
| ASHRAE RP-1050 Inverse Modeling Toolkit / Guideline 14-2023 (snippets); Manfren et al. 2025, https://art.torvergata.it/retrieve/e747d13b-5847-4374-a134-560993cfb000/1-s2.0-S030626192501880X-main.pdf (snippet) | 3-parameter cooling (3PC), 3PH and 5P change-point models; automated 3PC identification. | **ADOPT 3PC on daily mean temperature** (it is the same model as CDD-with-fitted-base). **NO** to 5P: the house is cooling-dominated and heating days are few. |
| Daily mean vs daily max vs hourly as the feature | No source found that compares them head to head. | **Unknown.** Settle it with our own backtest (rev-2 probe), and keep the feature consistent between fit and predict. That consistency is the bug being fixed. |

## 3. EV and other large flexible loads

| Source | Idea | Fit |
|---|---|---|
| Practitioner guide, https://esp32.co.uk/forecasting-solar-self-consumption-with-home-assistant-and-load-history/ (snippet; blog, weak) | Strip EV and other controllable loads out of the training baseline and forecast them separately from their schedule. | **ADOPT** in the simplest form: fit the non-EV base on temperature, and keep EV as its own term. The constant 18.58 kWh/day EV term is the weak part; replace it with a measured trailing mean (see rev-2 probe). Schedule-aware EV forecasting is **LATER**. No peer-reviewed source found. |

## 4. Bias correction from recent days

| Source | Idea | Fit |
|---|---|---|
| "Learning from Yesterday's Error" (2026), https://arxiv.org/pdf/2602.21757 (snippet; traffic demand, not electricity) | Exponential smoothing of recent forecast errors added to the forecast; the smoothing constant needs tuning. | **LATER** for the tuned version. **ADOPT** the simplest version only if the backtest shows a persistent monthly bias: a clamped trailing-mean residual over 7 days, behind a module-const kill switch. |
| ENTSO-E day-ahead bias correction, https://arxiv.org/abs/2302.11017v1 (snippet) | Simple time-series correction of a biased day-ahead load forecast. | **LATER.** Supporting reference for the above. |

## 5. PV forecast uncertainty in net load and battery decisions

| Source | Idea | Fit |
|---|---|---|
| Predbat customisation docs, https://springfall2008.github.io/batpred/customisation/ (**fetched in full**) | `pv_metric10_weight` blends the Solcast PV10 scenario into planning (0.15 recommended); `load_scaling` default 1.05 adds a load margin; `days_previous` averages past days of load with a filter that drops the lowest day. | **ADOPT for R2, not R1.** A pessimism blend (e.g. `pv_used = (1-w)*PV50 + w*PV10`) is the cheapest risk-aware input to a net-class decision. It is a decision input, so it belongs to the Tier-3 R2 cycle, with `w` as a knob whose 0 value reproduces today. For display (tomorrow forecast) show P10/P50 as a range. |
| Solcast PV / PV10 / PV90 definitions, https://kb.solcast.com.au/what-is-the-difference-between-pv-pv10-pv90 (snippet) | PV is the median; PV10 and PV90 are the lower and upper scenarios. | Reference only. Check our Solcast entities expose `estimate10` before designing on it. |
| Stochastic / robust MPC for reserve | No credible source found in this pass. | **NO.** Complexity before the basics are fixed. |

## 6. Evaluation metrics

| Source | Idea | Fit |
|---|---|---|
| ASHRAE Guideline 14 thresholds via https://web.eecs.utk.edu/~jnew1/publications/2016_ASHRAE_G14.pdf and https://arxiv.org/pdf/2603.01198 (snippets) | Hourly CV(RMSE) ≤ 30%, NMBE ±10%; monthly 15% / 5%. A dormitory paper (https://arxiv.org/pdf/2012.07748) cites daily 22% / 7%, but G14 itself may not define daily limits. | **ADOPT as internal targets**, not as a pass/fail standard. The commonly repeated "daily NMBE ±10% / CV 30%" figure is unverified. |
| LBNL acceptance criteria, https://buildings.lbl.gov/sites/default/files/AcceptanceCriteriaAndDocumentation%202019%2006%2030.pdf (snippet) | CV(RMSE) < 25%, NMBE < 0.5%, R² > 0.7 as recommended, explicitly not pass/fail. | Reference. |
| Synthesis | Report MAE, NMBE (bias), CV(RMSE) and skill vs weekly persistence. Avoid MAPE as the headline: it blows up on low-load days. | **ADOPT** in the D5 prediction log and the backtest. |

## What this changes in the plans (short)

1. Fix the temperature input so predict and fit use the same feature for the TARGET day (forecast daily mean, or max if the backtest says so). Already the R1-flip prerequisite.
2. Fit the balance point instead of fixing 65 °F (offline script, new constants).
3. EV term: measured trailing mean instead of a constant (simple), schedule-aware later.
4. Score against weekly persistence plus MAE/NMBE/CV(RMSE) in the prediction log.
5. PV10 pessimism weight: a decision-side idea, so it goes to R2 (Tier 3), default 0.
