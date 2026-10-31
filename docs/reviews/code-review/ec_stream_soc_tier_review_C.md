# Review C (test authority, per-site source mutation) — ec-stream-soc-tier @ d36ba1f5a (base f9a2ff33c)

Method: 105 independent single-site mutations (own enumeration from the diff, not the builder's script), each run against
test_ec_stream_soc_tier.py + test_ec_degraded_data_p1.py + test_ec_role_defaults_rev5.py (362 tests, ~4 s), bytecode cleared
each run, file restored in finally. Worktree clean afterwards. Script: scratchpad/_c_drill_rc.py (outside repo).
Baseline: 362 passed.

## Result summary
- RED: 83 sites with a SPECIFIC named test failing. GREEN: 18 (triaged below). 2 not-applicable (ambiguous anchor, re-run separately).
- Requested special sites: ALL RED except the two noted in F2/F3.

## Special sites
| Site | Mutation | Test that went RED |
|---|---|---|
| native-ref write energy_battery.py:1115 | drop value write | test_stream_entity_unset_byte_identical_shipped_constants, TestSlew::rejects_zero_after_20_min (8 fail) |
| native-ref write :1116 | drop ts write | same (8 fail) |
| native-ref only when stream configured (INV-SF4 inverse) | guard write by _stream_tier_configured | test_stream_entity_unset_byte_identical_shipped_constants |
| native-ref re-anchored by stream (LKG-style) | stream path writes native ref | TestSlew / TestSettle family (3 fail) |
| tier label :1521 `"stream": "local_stream"` | ->"lkg" / ->None | TestD1StreamTier::test_tier_map_and_disagreement_include_stream, TestMaxAge::..._serves_when_native_down (2 fail) |
| `_soc_source_last="stream"` :1131 | ->"lkg" | 27 fail incl. TestMaxAge::test_stream_stale_last_reported_rejected |
| get_status attr wiring :8420 `**stream_trust_diag_attrs()` | removed | test_stream_unproven_native_fresh_attribute_counts, test_stream_entity_unset_byte_identical_shipped_constants |
| diag since_iso / native_fresh accumulate / acc_at set / acc_at reset / lazy since init | each neutered | test_stream_unproven_native_fresh_attribute_counts (each) |
| EVSE blind-guard stand-down: coordinator `blind_hold_active` energy.py:4376 (`and soc is None`) | drop SOC clause | test_blind_hold_and_evse_guard_stand_down_when_stream_serves |
| stream bypass in resolver :1127 | stream=None | 35 fail |
| serving read check_trust True->False | | 17 fail (test_stream_unproven_at_boot_not_served ...) |
| INV-SF4 shipped constants | TIER_ENABLED False/EARN/LAPSE/MARGIN/SETTLE changed | test_shipped_stream_constants (+behaviour tests) |

All other sites (trust machine, earn N, lapse, quarantine exit, restore mapping, settle arm a/b + conjuncts, RC-1 prev reset,
slew call/margin/capacity/elapsed, per-house max age, mode a/b co-witness, ctor wiring, _parse_stream_max_age_s, options
validation, schema key, construction-keys membership, strings/en.json) are RED with a named test.

## GREEN rows (untested or equivalent)
| # | Site | Mutation | Verdict |
|---|---|---|---|
| F1 | energy_battery.py ~2102 `self._stream_div_count = 0` on agreement | removed | UNTESTED (MEDIUM): "consecutive divergence" semantics unproven; non-consecutive divergences could accumulate to quarantine when QUARANTINE_TICKS>1. Needs test: div, agree, div must not quarantine. |
| F2 | energy_pool.py:759 `blind = snapshot_reader()`; energy.py:5303 `_tick_is_blind_hold`; :5048 shadow | `blind=True` / drop `_bat_soc is None` | UNTESTED in target set (MEDIUM): the stand-down test goes through the property fallback via a shim with no snapshot method; production guard reads the DP-tick snapshot. Pre-existing code, but the new tier's stand-down on the snapshot path has no anchor here (may be covered by other suites, out of scope). |
| F3 | energy.py:4372 blind_hold_active `except: soc = None` | ->50.0 | UNTESTED (LOW, pre-existing fail-closed branch). |
| F4 | energy_battery.py:1850 unit guard `unit != "%"` | removed | UNTESTED (MEDIUM): "unit exactly %" guard has no test in these files (pre-existing guard; may be tested elsewhere). |
| F5 | energy_battery.py:1852 range guard 0..100 (stream read; 1372 is the native one) | removed | UNTESTED (MEDIUM): out-of-range stream value not asserted refused. |
| F6 | `changed = now` fallback when last_changed missing/naive | neutered | UNTESTED (LOW): with None it would raise inside a "never raises" read. |
| F7 | stream_trust_diag_attrs unconfigured guard | removed | Equivalent (counters stay None/0 when unconfigured). |
| F8 | `_set_stream_trust` resets `_stream_unproven_native_fresh_s` / sets `_since` | removed | UNTESTED (LOW, diagnostic only; stale accumulated seconds survive quarantine->unproven). |
| F9 | slew `>` vs `>=` | boundary | UNTESTED boundary (LOW). |
| F10 | slew elapsed-exception ->True; lapse exception ->False | | UNTESTED defensive branches (LOW). |
| F11 | options-flow `errors["base"]` and unparseable-input branch | removed | UNTESTED (LOW; NumberSelector blocks non-numeric in UI). |
| F12 | cmp read `now=now` threading | removed | Equivalent under tests (clock patches utcnow); production-identical. |
| E | slew rate max->min | | EQUIVALENT: BATTERY_MAX_CHARGE_KW == BATTERY_MAX_DISCHARGE_KW == 30.72 (energy_const.py:2410-2411). Also equivalent: lapse last_agree-None branch, lapse `return None` (falls to non-trusted return), earn-cond `unproven` check, arm-b `prev_read_at is not None`, settle clear-after-expiry, settle reset on unavailable, set_trust same-state noop. |

## Verdict
No load-bearing site of the new feature is wholly unanchored: native-reference write, local_stream label, get_status attr wiring,
INV-SF4 path, trust machine, settle, slew, lapse, restore, options flow are all RED on neuter. Test authority does not
trigger FIX-REQUIRED; recommend adding tests for F1, F2 (snapshot path), F4, F5 before ship (~5-10 lines each); F6-F11 LOW.
