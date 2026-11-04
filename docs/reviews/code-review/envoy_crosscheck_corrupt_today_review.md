# Review: fix/envoy-crosscheck-corrupt-today (ENVOY-FLAKINESS-181243-1)

Tier 1, framing A (local correctness and blast radius). Commit 82ecc84e vs develop.
Verdict: **SHIP**

## Findings

| # | Sev | Where | Finding | Bug class |
|---|-----|-------|---------|-----------|
| 1 | clear | energy.py:3860 | Units hold. `_get_lifetime_consumption` returns MWh (energy.py:3370-3372), and the existing delta math already uses x1000 (energy.py:3851). Live case: 34412.04 >= 34.412*1000*0.5 = 17206, so it skips. Real case: 40 kWh vs 17206, so the check still runs. | n/a |
| 2 | LOW (accepted) | energy.py:3860 | New install or new Envoy with a small lifetime counter: when lifetime < 2x today (e.g. lifetime 10 kWh, today 6 kWh), the check is skipped and any flag is cleared. The window is only the first day or two of a fresh counter's life. The skipped check is advisory (it feeds the "stale" display plus an anomaly row), so suppressing it for that period is acceptable. A lifetime of 0 also skips, which is the right result. | coincidental-scale edge |
| 3 | clear | energy.py:3867 | Clearing the flag cannot hide an anomaly raised elsewhere. Every writer of `_envoy_data_anomaly_at` is init (energy.py:1056) or inside this function (3867, 3889, 3907). The only readers are display/status in sensor.py:14704 and :14772. | #53 checked |
| 4 | clear | energy.py:3911 | The reboot re-seed branch sits below the guard, so a lifetime-scale "today" can no longer satisfy `envoy_today > our_delta*2` and re-seed every snapshot. Before this change, the corrupt value could not reach re-seed either, because re-seed only runs in the `<5%` branch. A genuine post-reboot re-seed (today is a small kWh value) is unaffected. | n/a |
| 5 | clear | energy.py:3853 | `_last_crosscheck_hour` is stamped before the guard, so a skipped check runs once per hour, the same as before. No log spam (debug level). | n/a |
| 6 | clear | consumers | The only other consumer of the today entity is the anomaly payload `entity_id` (energy.py:3964), which the guard doesn't reach. The daily consumption calculation does not read it. | n/a |
| 7 | LOW | test file | The two tests cover the corrupt case and a genuine divergence. No boundary test exactly at ratio 0.5. That is optional and not required. | n/a |

## Stats
CRITICAL 0 / HIGH 0 / MEDIUM 0 / LOW 2 (both accepted, none needing a fix).
