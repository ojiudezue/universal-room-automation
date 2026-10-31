# EC stream SOC tier: Review D (adversarial completeness, diff-blind)

Branch `feature/ec-stream-soc-tier` @ d36ba1f5a, base f9a2ff33c (three-dot). Plan: `PLANNING_ec_source_failover_class.md` rev 3.1, INV-SF2..SF8.
HVAC/presence docs not applicable (energy-only change).

## Falsifiable invariant attacked
"No `_read_stream_soc(check_trust=True)` result reaches `battery_soc` unless it is numeric, unit %, fresh per the house max age, outside every reconnect settle window, inside the native-referenced slew bound, and `trusted` (earned by N=3 spaced agreements since boot, restore or quarantine, last agreement within 6 h). With the stream unset, behaviour equals develop."

## Surface re-enumerated (whole repo, not just diff)
Readers of the stream entity: only `_read_stream_soc` (energy_battery.py:1803). Callers: `battery_soc` serve (:1127, check_trust=True), D2 snapshot (:1549, False), `_evaluate_stream_divergence` (:2066, False). Tier labels: `SOC_TRUSTED_TIERS` (:119), `_tick_soc_source` capture (:6384), `_envoy_offline_tier_text` (energy.py:3536). Restore: energy.py:1866 → `restore_stream_trust_snapshot` (:2125); agree/div counts and `_stream_last_agree_at` are not persisted (good). `envoy_available` (:3813) does not read the stream (INV-SF3 holds). `SOC_STREAM_TIER_ENABLED` has one reader (:1799).

## Findings

| # | SEV | Class | Site | Finding |
|---|---|---|---|---|
| D-HIGH-1 | HIGH | #53-style missed arm path / INV-SF7 leak | energy_battery.py:1826 (`_stream_prev_value = None` on every early return) + :1850-1859 (arm (b) requires `prev_value is not None`) | A second, unobserved reconnect inside an active settle window does not re-arm settle. Every read during settle returns early and nulls `prev_value`, so arm (b) is dead until settle ends; the junk value is served when the first settle expires. **Repro (legal config, shipped constants):** stream trusted, native down 60 min (ref 36, slew bound ~80 pp); observed drop; reconnect at t1 with 50 (settle to t1+60); a second sub-tick blip at t1+30 leaves value 0 (last_changed t1+30); read at t1+61 returns `(0.0, "stream")`, 29 s before the second reconnect's settle would end. Verified by a scratch test. The same nulling also disables arm (b) after ANY early return (stale read in mode "a", co-witness miss), so a jump right after one missed read is never detected. Native outages of 37+ min are measured (232 min max), at which point slew no longer catches 0 vs 50. **Fix:** do not null `prev_value` on the settle early-return (keep the last numeric value), and re-arm/extend settle whenever `last_changed` moves past the settle anchor while inside the window. Add a test for this exact sequence. |
| D-MED-1 | MEDIUM | config combinatorics / concept split (#63) | config_flow.py:7504-7520 (no stream != native check; max 3600) + energy_battery.py:1883-1886 | Stream entity may be set to the native SOC entity itself (or a same-path sibling that freezes with it). It earns trust instantly (delta 0), then while native is FROZEN (stale > 300 s, still numeric) the stream path serves the same frozen value as trusted tier `stream` for up to the stream max age (3600 legal), bypassing the primary-staleness gate, the 5-min LKG cap and the cloud-tier grid-charge withhold. **Repro (verified):** stream=`battery_soc` entity, max age 3600, co-witness unset (optional in mode "a"); earn 3 agreements; native stops reporting 40 min → `(80.0, "stream")`. The help text warns but nothing enforces. **Fix:** options-flow reject stream == native entity; consider capping effective stream max age at `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` (300) or requiring a co-witness when max age > 300. |
| D-LOW-1 | LOW | doc drift | energy.py:1859-1863 | Comment says an absent key restores as default `trusted`; code now inits/restores `unproven`. |
| D-LOW-2 | LOW | INV-SF4 literal | energy_battery.py:8420 | `stream_trust_diag_attrs` adds two new attribute keys to the strategy sensor even with the stream unset (values None / 0). Resolver output, tier labels and `stream_trust` are unchanged; only the key set differs. Accept or gate on configured. |
| D-LOW-3 | LOW | pre-existing helper | energy_battery.py:5030 | `_battery_capacity_kwh` treats a unitless kWh capacity (e.g. "40", uom "") as Wh → 0.04 kWh → slew rate ~768 pp/s, slew guard off. Pre-existing; only matters if the capacity entity lacks a unit. |
| D-LOW-4 | LOW | observation | :1883-1886 | Max age 30 with a 30 s poll: intermittent stale reads alternate stream/LKG (LKG re-anchored, no None) and each stale read feeds D-HIGH-1's arm-(b) blindness. Min 30 is allowed by form; help text says ~4x poll. |

## Cleared (holds because)
- Stream unset: `_stream_tier_configured` False → every stream path returns before state mutation; `_soc_native_last_*` internal only; `stream_trust_state` = `disabled` (INV-SF4 holds except D-LOW-2).
- Earn after restore during outage: `trusted`→`unproven` on restore (:2136); no compares while native is None (:2067) → never served. Counts not persisted.
- Quarantine during outage: compare abstains; stays quarantined; exit goes via `unproven` with count reset in `_set_stream_trust` (:2011) → needs 2 + 3 agreements.
- Native returns mid-settle: native tier wins at :1109 before the stream is read; settle state irrelevant.
- Realtime reconnect at the prior value after 8 min (10-29 23:14-23:22): if observed unavailable, settle arms from `last_changed`; if the entity stayed numeric-stale, mode "a" refuses on `last_reported` until the first fresh report; that first report (pre-drop value) is fresh by definition and inside slew (13 pp at 8 min). Serves one poll of a possibly 3-5 pp stale value, no worse than LKG. Not a leak against INV-SF2..SF8 as written.
- Max age 0, co-witness unset: mode "b" refuses every read (:1890) → never earned, never served = develop.
- Capacity unset / ≤0: falls back to 40 kWh constant (:1934).
- Lapse: checked on every serving read (:1898); `_stream_last_agree_at` updated only on agreeing compares.
- INV-SF3: cloud never in `SOC_TRUSTED_TIERS`; `envoy_available` probes local entities only.

## Invariant checklist
| Inv | Verdict |
|---|---|
| INV-SF2 | PASS |
| INV-SF3 | PASS |
| INV-SF4 | PASS (LOW-2 attr keys) |
| INV-SF5 | PASS |
| INV-SF6 | PASS |
| INV-SF7 | **LEAK** (D-HIGH-1) |
| INV-SF8 | PASS when configured; D-MED-1 shows mode "a" without co-witness lets a frozen same-path stream serve |

## Verdict: FIX-REQUIRED
Must fix: D-HIGH-1 (settle re-arm during active window / prev_value nulling) with a mutation-anchored test; D-MED-1 (reject stream == native; cap or co-witness rule for max age > 300). Fix LOW-1 in the same pass.

## Re-check d1b06da71 (fix-up; diff d36ba1f5a..d1b06da71)

Worktree `.claude/worktrees/revD-d1b06` @ d1b06da71. Repros: `quality/tests/test_zz_reviewD_repro.py` there (untracked, scratch). Stream test files: 341 passed (`test_ec_stream_soc_tier.py` + `test_ec_degraded_data_p1.py`).

### Prior findings
| # | Status | Evidence |
|---|---|---|
| D-HIGH-1 | CLOSED | Original repro (`test_D1_...`) now returns `(None, 'none')` at t1+61. Two changes close it: `_stream_prev_value` is kept on early returns, and a change inside the window re-arms (`anchor < changed < until`, energy_battery.py:1871-1879). |
| B-HIGH-1 | CLOSED | `test_D5`: 5-min reads, SOC falling 2 pp per tick with native down. Every read serves `(v, "stream")`. Arm (b) bound is 1.28 pp/min × elapsed + 3, about 9.4 pp per 5 min (`_soc_slew_bound_pp`, :1951). |
| D-MED-1 | **NOT CLOSED on the live house (hollow guard)** | See D2-MED-1. |
| D-LOW-1 | CLOSED | energy.py:1859 comment fixed. |

### Hunting for new holes the fixes could add
- **Prev value never cleared + long gap.** Not a bypass. Arm (b) measures elapsed from `prev_read_at` (the last READ, stamped on every call at :1828), not from when `prev_value` was observed. A reconnect after 40 min of stale-numeric reads therefore gets a bound of about 9.4 pp (one read interval), not 54 pp. That is tighter than the native-referenced slew backstop. The only side effect is extra arming: during a co-witness miss `prev_value` stays frozen while real SOC moves. The cost is a 60 s settle delay, and the settle return sets prev, so it heals itself. Junk reads arm via (a).
- **Junk-read settle.** Junk is never served. Each junk read re-arms (a), the same as `unavailable` did before. Legit reads that follow get one 60 s settle. No starvation.
- **D2-LOW-1: the extension can stall the stream (fails safe).** The window extends whenever `last_changed` lands in `(anchor, until)`. If reads come less than 60 s apart and SOC changes less than 60 s apart (a 1 pp step on 40 kWh means more than 24 kW sustained; max 30.72 kW is legal), the settle never expires. Repro `test_D3[3]`: reconnect, then a read every 15 s and -1 pp every 45 s for 10 min. Result: 0 of 40 reads served. Control `[6]` (a change every 90 s): 37 of 40 served. With 5-min decision reads the window always expires between reads, so this is unreachable at that cadence. The failure direction is safe: the stream is withheld and the house falls to LKG or the blind hold. It is not a leak against INV-SF7. Optional fix: cap the extension at the first anchor + N×settle.

### D2-MED-1: the stream==native guard never fires on derived-Envoy installs
config_flow.py:6274-6282 compares the stream against `_sf.get(CONF_ENERGY_BATTERY_SOC_ENTITY)`, where `_sf` merges `entry.data`, `entry.options` and the user input. No form field sets that key. The native entity is derived at runtime: `__init__.py:3841` calls `derive_envoy_config(serial)`, which `setdefault`s it into the runtime dict (energy_const.py:1739), and that value is never persisted. The live entry carries neither `energy_battery_soc_entity` nor the stream key (read from `.storage/core.config_entries`). So `_sf_native` is None, and the check silently passes on this house and on any auto-derived install. Bug class #53 / #62 shape: the guard exists but is wired to a key that is empty in production. The heartbeat rule closes the original repro, since max age 3600 without a heartbeat is now rejected. It does not close the variant below.
**Repro (runtime, `test_D4`):** stream = the native entity `sensor.envoy_<serial>_battery`, heartbeat = any live sensor, max age 3600. The options flow accepts this because native is not in the entry. Earn 3 agreements, then native stops reporting for 40 min while the heartbeat stays live. Result: `(80.0, "stream")`, a frozen native value served as trusted tier `stream` past the 300 s primary gate.
**Fix (either):** (a) in the options flow, resolve native as the configured key OR `derive_envoy_config(serial)[CONF_ENERGY_BATTERY_SOC_ENTITY]` (the same source `__init__` uses). (b) Better, add a runtime guard in `_stream_tier_configured` / the constructor: stream eid == `self._entities["battery_soc"]` → tier disabled with one WARNING. (b) also covers entries saved before this guard existed and edits made outside the flow, which is the operator's "runtime gap" question. It matters for the same reason: the flow does not see the effective native entity.
Test anchor: a constructor/read test where stream == `entity_config["battery_soc"]` must return None. Also an options-flow test with the native key ABSENT from the entry but derivable.

### Invariant checklist (re-check)
| Inv | Verdict |
|---|---|
| INV-SF2..SF6 | PASS |
| INV-SF7 | PASS (D-HIGH-1 closed; D2-LOW-1 fails safe) |
| INV-SF8 | **LEAK** via D2-MED-1 (stream==native + heartbeat + max age above 300 accepted on a derived install) |

### Verdict: FIX-REQUIRED (narrow)
Must fix: D2-MED-1. Add the runtime stream==native guard (preferred) or resolve the derived native in the options flow, with a test that fails if the guard is removed. Optional: D2-LOW-1 extension cap. Re-verify by running `test_D4` (it should pass once the guard is in).
