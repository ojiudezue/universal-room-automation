# EC stream SOC tier — Review B (integration / state machine / restart)

Branch `feature/ec-stream-soc-tier` @ d36ba1f5a, base f9a2ff33c (verified = merge-base). Plan rev 3.1 + B2a + checkpoint.
Targeted tests: test_ec_stream_soc_tier / test_ec_degraded_data_p1 / test_ec_role_defaults_rev5 = 362 passed. Tree left clean.

## Verdict: FIX-REQUIRED (1 HIGH)

### B-HIGH-1 — settle arm (b) is elapsed-blind; at real read spacing it refuses every other serve and flaps the blind hold
Bug class: suppression of a legitimate action / #63 (the plan's "30 s tick" assumption vs the real 5-min decision tick, `energy_const.py:183`).
`energy_battery.py` `_read_stream_soc`, arm (b): `changed > prev_read_at and abs(value - prev_value) > DEFAULT_SOC_STREAM_SLEW_MARGIN_PCT` (fixed 3 pp, no elapsed term). Between two reads 5 min apart, a battery moving >= 0.6 pp/min (>= ~7.2 kW net on 40 kWh, well under the 30.72 kW physics bound) always trips it; `last_changed` is ~10-30 s old, so `now < changed + 60` and the read returns None. RC-1 then resets prev to None, so the next read serves: alternation.
Repro (run in a scratch test against the branch, real BatteryStrategy): earn trust, native down, stream with max_age=120, reads every 300 s, stream 80→76→72→68→64 (lc = now−10 s). Observed:
`[(80,'stream'), (80,'lkg'), (72,'stream'), (72,'lkg'), (64,'stream')]`.
Every other read serves a stale LKG (80 when the stream says 76). LKG max age is 300 s (`DEFAULT_SOC_LKG_MAX_AGE_S`), so any jitter above 300 s turns those reads into None → `blind_hold_active` True → EVSE blind guard / DP blind hold / strategy blind hold engage and release on alternating ticks. The same arm suppresses every other earn/quarantine comparison while native is up at high power (slower earn, not unsafe).
Fix: make the arm-(b) jump threshold physics-scaled, the same bound the slew backstop uses: `abs(value - prev_value) > rate_pp_s * (changed - prev_read_at or now - prev_read_at) + margin` (the 36 s 0-class junk still exceeds it). Add a test: steady 4 pp / 5 min discharge, native down, every read served.

### MEDIUM / LOW
- B-LOW-1 `energy.py:1859-1862` restore comment still says absent row "restores as the default `trusted`"; now `unproven`. Doc drift.
- B-LOW-2 INV-SF4 near-miss: stream unset still changes two surfaces — the persisted `battery_soc_stream_trust` blob now saves `"unproven"` (was `"trusted"`), and the strategy sensor gains `stream_unproven_since: None`, `stream_unproven_native_fresh_s: 0`. Neither is consumed by decision code (grep: only `energy.py:1866/2376` and the attr dict), and B2a §5 sanctions the attrs. Not behavioural; record it so INV-SF4's wording ("every trust attribute identical") is accurate.
- B-LOW-3 Options clearing: a blank NumberSelector is absent from `user_input`, and the `{**options, **user_input}` merge keeps the old value, so an operator cannot clear 120 back to "blank"; they must type 0. The help text says "Leave blank or 0". Also 0 vs unset is a `_norm_cm_opt` diff (`__init__.py:7791`) → one needless parent reload on a semantically no-op save. Same behaviour as the existing stream entity fields; suggest the help say "set 0 to turn off".
- B-INFO `_set_stream_trust` (→ `hass.async_create_task`) is now reachable from the serving read (lapse), i.e. any `battery_soc` consumer, not just the tick evaluator. All consumers found run on the loop; no executor caller found. Note only.

## Cleared (holds because)
- Kill switch True: only reader is `_stream_tier_configured` (`energy_battery.py:1799`), which still requires the entity; unset → every stream path returns early; evaluator returns before touching state. `_soc_native_last_*` internal only. INV-SF4 holds for resolver output / tier / `_soc_source_last` / `stream_trust`="disabled".
- A2 consumers: blind hold, `blind_hold_active` (`energy.py:4342`), snapshot, EVSE guard (`energy_pool.py:745-761`), DP all key on SOC None; a served stream makes them stand down as the checkpoint ruled. `soc_tier_trusted` already contained "stream" → D2a/D3/D4 treat it as trusted. `envoy_available` untouched.
- Restart: persisted trusted→unproven, quarantined stays, stale/absent row → init unproven; lapse anchor / settle / native ref not persisted, and none can serve without fresh native agreement after boot. Quarantine exit routes through unproven with agree_count reset (`_set_stream_trust`), so recovery is never easier than first earn.
- Parent reload: new key added to `EC_CONSTRUCTION_ENTITY_KEYS` alongside the two existing stream fields; same `_schedule_parent_reload` path, not in the suppress set. Consistent with existing behaviour; parent-reload hazard is the documented daytime operator step. Migration: missing key → `ec.get` None → `_parse_stream_max_age_s` None → mode "b".
- Async: no new awaits, no blocking I/O; all new reads are `hass.states.get`.
