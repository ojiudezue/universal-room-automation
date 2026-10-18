# Test Wave 2 D7 slice 2 - Review C (test authority via hand-applied source mutation)

Head e8081ab98. Each row: one mutation applied to real source, matching anchor run with
URA_D7_HYGIENE=1 + PYTHONDONTWRITEBYTECODE=1 (pycache cleared), source restored (try/finally).

| site | mutation | test | result |
|---|---|---|---|
| `_d7_isolation.restore_clocks_after_test` | `monkeypatch.setattr(t, attr, getattr(t, attr))` -> `pass` | test_restore_clocks_after_test_undoes_set_now_writes | RED |
| `_d7_isolation.other_dt_modules` | return `[]` always | test_other_dt_modules_returns_parent_attr_when_it_diverges | RED |
| `import_scope` -> `_restore_parent_attrs` call | call -> `pass` | test_import_scope_removes_parent_attr_of_popped_child + ..._restores_parent_attr_of_replaced_child | RED (both) |
| donor scoping: comfort_fan_away_veto_behavioral | `import_scope(attrs=True)` -> `prefixes=()` | test_donor_leaves_no_residue[...comfort_fan_away_veto...] | RED |
| donor scoping: carrier_freshness | same | test_donor_leaves_no_residue[test_carrier_freshness.py] | RED |
| `zzz_v318_hvac_sensors` scoping | `import_scope(attrs=True)` -> `prefixes=()` | whole test_d7_donor_hygiene.py (46 pass, 1 skip) | **GREEN - untested** |
| victim pin b2b_i `other_dt_modules` pin (dp_pause test) | remove pin loop, donor fixed | pair bathroom_exhaust -> b2b_i::test_force_charge_preempts_dp_pause_release | GREEN (expected: retired non-discriminating) |
| same pin, plus bathroom_exhaust donor unscoped | both neutered | same pair | RED |
| bathroom_exhaust donor unscoped, pin intact | donor neutered only | same pair | GREEN (pin masks donor; donor covered by residue drill) |

## Findings
- MEDIUM (Bug class #62-adjacent, untested site): `test_zzz_v318_hvac_sensors.py` scoping is
  not in `DONOR_PROBES`, `_DRILLS` or any DONOR_VICTIMS entry. Un-scoping it leaves the whole
  hygiene suite green. Add a DONOR_PROBES entry + `_DRILLS` entry (same shape as carrier_freshness).
- LOW: the requested "dp_drain victim-side pin" does not exist in test_dp_drain_target_value_stamp.py
  (no dt pin, not touched since cdb717ef1 stat). The actual victim pins are in evse b2b_i / b2b_ii /
  b2c2_fixup; the b2b_i pin was drilled (row above). dp_drain's victim node stays green only by
  the donor fixes + those evse pins; it has no direct pin drill.
- Note: the victim pin and donor fix mask each other pairwise (consistent with e8081ab98's retirement
  of those pair drills); only the combined mutation is RED.

Verdict: FIX-REQUIRED (small): add zzz_v318 anchor. Everything else holds.
