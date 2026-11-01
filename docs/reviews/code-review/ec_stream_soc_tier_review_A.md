# EC stream SOC tier — Review A (local correctness)

Branch feature/ec-stream-soc-tier @ d36ba1f5a, base f9a2ff33c (three-dot verified). Targeted suite: 321 passed (test_ec_stream_soc_tier + test_ec_degraded_data_p1).

Verdict: **SHIP** (no CRITICAL/HIGH/MEDIUM). LOWs below.

## Findings

| Sev | Where | Finding | Class |
|---|---|---|---|
| LOW | energy_battery.py:1549 | Third caller of `_read_stream_soc(check_trust=False)` (D2 tier-disagreement snapshot) omits `now=now` although `now` is in scope. It mutates `_stream_last_read_at` / `_stream_prev_value` / settle state with wall-clock `utcnow()` while the evaluator uses the tick `now`. Harmless in production (both aware, ms apart; settle respected so no junk leaks into the disagreement value), but mixes clocks in tests that inject `now`. Fix: pass `now=now`. | consistency |
| LOW | config_flow.py ~6170 + merge `{**options, **user_input}`; strings.json help | Builder choice (7): blanking an already-set max age keeps the old value (merge resurrects it); only `0` clears. Help text says "Leave blank or 0", true for first-time setup only. 0 is a working off path, so no trap. Optional: pop the key when blank (solar-override pattern). | UX / Bug Class #63-adjacent |
| LOW | energy_battery.py `_battery_capacity_kwh` (pre-existing) | Unit test is `uom in ("kWh","kwh")`, else /1000. A capacity entity in "KWh"/unitless reports 1000x too small → slew bound huge → backstop fails OPEN (weaker, never refuses good values). This house = 40000 Wh → 40 kWh, correct. | pre-existing |
| LOW (doc) | PLANNING_ec_source_failover_class.md:304 | Older R3 help text conflicts with B2a §1/§2. Code follows B2a (binding). Strike line 304. | doc drift |

## Builder choices judged

1. Key in EC_CONSTRUCTION_ENTITY_KEYS: **correct**. Value is read once at construction (energy.py:349); `__init__.py:8658` reloads the parent on change. Only consumer of the set is that reload diff. No code treats members as entity ids.
3. Quarantine exit = 2 agreements → `unproven` (count reset in `_set_stream_trust`) → 3 more: **correct**, matches D2.5 "never easier than first earn" (5 ≥ 3).
4. Lapse with `_stream_last_agree_at is None` → lapsed: **correct and fail-closed**. Unreachable in practice: `trusted` is only entered via earn, which sets the stamp; restore maps trusted→unproven.
5. `_stream_prev_value = None` on every early return: **correct**, implements RC-1. Arm (a) already covers the unavailable case.
6. A step >3 pp between successful reads arms settle (60 s delay): **acceptable**. Physics max is 0.64 pp per 30 s, so a >3 pp gap needs ≥2.3 min between successful reads, and any None read in between nulls prev (no arm).
7. Blank keeps old value: see LOW above.

## Per-site arithmetic and truth tables

**Slew** (`_stream_within_slew`): rate = 30.72/40·100/3600 = 0.02133 pp/s → 0.64 pp/30 s, 1.28 pp/min (matches plan). Capacity None/≤0 → BATTERY_CAPACITY_KWH (LOW-R3-2) ✓. No native ref → abstain ✓. `elapsed` clamped ≥0 ✓. Runs only on check_trust=True ✓ (MEDIUM-R3-1). Reference written only on native-served path (:1110-1116), never re-anchored by stream/LKG ✓.

| case | ref | stream | elapsed | bound | result |
|---|---|---|---|---|---|
| 1 pp step | 40 | 41 | 30 s | 3.64 | serve |
| junk 0 | 36 | 0 | 30 s | 3.64 | refuse |
| 8 pp error | 40 | 48 | 4 min | 8.12 | refuse |
| 8 pp error | 40 | 48 | 5 min | 9.4 | serve (documented residual) |

**Settle** (`_read_stream_soc`): arm (a) sets seen flag on unknown/unavailable, next numeric read arms `last_changed + 60` ✓; arm (b) requires `changed > prev_read_at` AND prev not None AND jump >3 ✓; same-tick second read cannot re-arm (changed ≤ prev_read_at) ✓; naive/missing `last_changed` → now (arms full window, fail-closed) ✓; window cleared once `now ≥ until` ✓. Settle runs before trust, so both comparison and serving reads honour it (INV-SF7) ✓.

**Max age**: `_parse_stream_max_age_s` None/""/junk/≤0 → None → constant 0 → mode b ✓; 120.0 → 120 ✓. Validator: blank ok, 0 ok, 29.9 reject, 30 ok, negative reject, NaN accepted by form but parses to None (mode b) — harmless. Selector max 3600 ✓.

**Earn/quarantine**: agreement = delta ≤ 3 pp, ≥60 s spacing (reused). unproven → trusted at count ≥3 ✓; divergence resets count and quarantines at 2 from unproven or trusted ✓; lapse in read path only on check_trust=True ✓ (LOW-R3-3).

**Restore**: trusted→unproven, quarantined→quarantined, unproven→unproven, else init unproven ✓.

**Diag attrs**: since/fresh_s reset on every trust transition; accumulate only while unproven AND native fresh; `disabled`/not-unproven → None/0 ✓.

**Strings**: label, max-age help, stream-entity help, heartbeat wording, step-description sentence match B2a verbatim in strings.json and translations/en.json ✓.

## Must-fix list
None. Recommended in-cycle (LOW, ≤5 LoC): pass `now=now` at energy_battery.py:1549.
