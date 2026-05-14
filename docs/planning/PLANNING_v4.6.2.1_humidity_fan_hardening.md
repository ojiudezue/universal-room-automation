# PLANNING v4.6.2.1 — Humidity Fan Hardening

**Status:** Plan complete, ready to implement
**Tier:** Tier 1 hotfix (≤4 files, single bug class with companion cleanups, no schema/lifecycle changes)
**Predecessor:** v4.6.2 (Routine Awareness — currently in 7-day soak from 2026-05-13)
**Soak-safety:** Touches only the humidity-fan branch of `automation.py` and `hvac_fans.py`. No interaction with routine awareness (B6/B7), regime detector, or D7 accuracy consumer. Safe to ship during v4.6.2 soak.

## Why

Audit during v4.6.2 soak surfaced four issues in the humidity-fan control path:

1. **No max runtime cap.** If a humidity sensor sticks high, or humidity legitimately stays above threshold for hours (cooking on a wet day, laundry drying), the fan runs indefinitely. No safety cutoff exists in either code path.
2. **`CONF_HUMIDITY_FAN_TIMEOUT` is misnamed and misbehaved.** Reading `automation.py:1641-1665`: `_humidity_fan_triggered_time` is set on the **first** activation and only reset on turn-off. The `elapsed >= timeout` gate is therefore a **minimum-runtime gate** (fan must have run at least 10 min before being allowed off), not the "off-delay after humidity drops" the name implies. In steady state it's a no-op; once humidity dips, elapsed is already hours.
3. **No hysteresis in `automation.py` Path A.** Single-threshold compare (`>=` on, `<` off + timeout) → fan can chatter near 60% RH if humidity oscillates. Path B (HVAC-managed) has proper 60/50 hysteresis but those thresholds are **hardcoded** — user's `CONF_HUMIDITY_FAN_THRESHOLD` is silently ignored when HVAC coordination is on.
4. **Three independent encodings of "60".** `const.py:503 DEFAULT_HUMIDITY_THRESHOLD=60`, `hvac_const.py:252 DEFAULT_HUMIDITY_FAN_ON=60`, literal `60` in `automation.py:1636`'s `.get(..., 60)` fallback. Silent drift risk.

## Scope

### A. New config: max runtime (the user's actual ask)

| CONF | Default | Range | Unit | Helper text |
|---|---|---|---|---|
| `CONF_HUMIDITY_FAN_MAX_RUNTIME` | `DEFAULT_HUMIDITY_FAN_MAX_RUNTIME = 3600` (60 min) | 600–14400 (10 min–4 hr) | seconds | "Maximum continuous humidity-fan runtime. Forces off if humidity stays elevated longer than this — protects against stuck humidity sensors and runaway runs. Set higher for laundry rooms; lower for bathrooms." |

Applies in **both** Path A and Path B. Track per-room `_humidity_on_since` timestamp; force-off + suppress re-trigger for one cycle when exceeded.

### B. Hysteresis correctness

| CONF | Default | Range | Notes |
|---|---|---|---|
| `DEFAULT_HUMIDITY_FAN_HYSTERESIS` (constant, not user-tunable in v4.6.2.1) | 10 (% RH) | — | OFF threshold = ON threshold − hysteresis |

Applied in **both** Path A and Path B. Path B currently has 10% baked in (60→50); promote to a derived value of `threshold - hysteresis` so it tracks user config.

### C. Path B respects user config

`_evaluate_humidity_fan` in `hvac_fans.py` reads room config `CONF_HUMIDITY_FAN_THRESHOLD` (falling back to `DEFAULT_HUMIDITY_THRESHOLD`) instead of the hardcoded `DEFAULT_HUMIDITY_FAN_ON`. Wire the room config through `_register_room_fans` into `RoomFanState`.

### D. Consolidate "60" defaults

Drop `DEFAULT_HUMIDITY_FAN_ON` and `DEFAULT_HUMIDITY_FAN_OFF` from `hvac_const.py`. Both paths import `DEFAULT_HUMIDITY_THRESHOLD` and `DEFAULT_HUMIDITY_FAN_HYSTERESIS` from `const.py`. Remove the literal `60` fallback in `automation.py:1636-1637` — read default from the constant.

### Out of scope (deferred)

- **Rename `CONF_HUMIDITY_FAN_TIMEOUT`** to `CONF_HUMIDITY_FAN_MIN_RUNTIME`. Would require options-flow migration and is cosmetic. Document the corrected semantics in the form helper text instead; leave the key alone.
- **Live Number entity for max-runtime tunable.** Form field only in v4.6.2.1. Promote later if user wants live tuning.
- **Per-room humidity-fan max-runtime override.** Single value covers the install for now.
- **Stuck-sensor diagnostic / anomaly emit** when max-runtime fires. Could plug into the v4.6.1 `save_anomaly_event` path — defer to v4.6.3 anomaly migration cycle to keep this hotfix tight.

## Deliverables

### D1 — `CONF_HUMIDITY_FAN_MAX_RUNTIME` + `DEFAULT_HUMIDITY_FAN_MAX_RUNTIME`

Add CONF + DEFAULT to `const.py`. Add form field to `config_flow.py` `async_step_climate` (room flow) and the matching options-flow step at `config_flow.py:5471-5479` area. Helper text per scope table above.

**Acceptance Criteria**
- **Verify:** Config flow shows a "Humidity Fan Max Runtime" field with default 60 min, range 10–240 min.
- **Verify:** Options flow round-trips the value (set 90 min, save, reload form, see 90 min).
- **Test:** `test_humidity_fan_max_runtime_default_60min` in `quality/tests/test_v4621_humidity_fan_hardening.py`.

### D2 — Max-runtime enforcement in Path A (`automation.py`)

Add state field `_humidity_on_since: datetime | None` separate from `_humidity_fan_triggered_time` (which retains its current min-runtime semantics — see D5). Set on every vacant→on transition; clear on every on→off transition. At top of `handle_humidity_based_fan_control`, if fan is currently on AND `_humidity_on_since` is set AND `(now - _humidity_on_since) >= max_runtime`: force off, clear `_humidity_on_since` and `_humidity_fan_triggered_time`, log INFO with reason, return.

**Acceptance Criteria**
- **Verify:** With humidity stuck at 75% and max_runtime=3600, fan turns off at t≈60min and stays off until humidity drops below OFF threshold + a fresh activation.
- **Verify:** Fan does NOT re-activate immediately on the next cycle (suppression — humidity must drop below OFF threshold first).
- **Test:** `test_max_runtime_force_off`, `test_max_runtime_suppresses_immediate_retrigger`, `test_max_runtime_resets_after_humidity_drop_below_off`.
- **Live:** After deploy, watch any room with `humidity_fans` configured; INFO log entry `humidity_fan_max_runtime_exceeded` should appear if any fan exceeds the cap, and the fan entity should be `off` in HA.

### D3 — Hysteresis in Path A

Replace single-threshold compare with: ON if `humidity >= threshold`; stay-on if currently on AND `humidity > (threshold - DEFAULT_HUMIDITY_FAN_HYSTERESIS)`; OFF otherwise (subject to min-runtime gate D5). Preserve existing turn-on call site; restructure the elif branch.

**Acceptance Criteria**
- **Verify:** With threshold=60: humidity oscillating 58↔62 keeps fan steady (no chatter).
- **Verify:** With threshold=60: humidity drops to 49 → fan turns off (subject to min-runtime).
- **Test:** `test_hysteresis_no_chatter_near_threshold`, `test_hysteresis_off_below_off_threshold`.

### D4 — Path B (hvac_fans.py) respects user config + max-runtime + hysteresis tracks threshold

Plumb `humidity_fan_threshold` and `humidity_fan_max_runtime` into `RoomFanState` at construction (read from merged room config in `_register_room_fans`). Add `humidity_on_since: datetime | None` field. `_evaluate_humidity_fan` uses `room_fan.humidity_fan_threshold` (ON) and `threshold - DEFAULT_HUMIDITY_FAN_HYSTERESIS` (OFF). Max-runtime check added to the humidity branch in the main evaluate loop (around `hvac_fans.py:236-244`): if currently on AND elapsed > max_runtime, force off + clear `humidity_on_since`.

**Acceptance Criteria**
- **Verify:** Room with HVAC coordination ON and `CONF_HUMIDITY_FAN_THRESHOLD=70`: fan does not activate until humidity ≥ 70 (currently it activates at 60).
- **Verify:** Max-runtime cap fires in Path B identically to Path A.
- **Test:** `test_hvac_fans_uses_user_threshold`, `test_hvac_fans_max_runtime_force_off`, `test_hvac_fans_hysteresis_tracks_user_threshold`.
- **Live:** With HVAC coordination enabled, change `CONF_HUMIDITY_FAN_THRESHOLD` via options flow and verify fan activation point moves accordingly.

### D5 — Documentation-only: clarify `CONF_HUMIDITY_FAN_TIMEOUT` semantics

Update strings.json helper text for `humidity_fan_timeout`: "Minimum continuous runtime before the fan is allowed to turn off after humidity drops below threshold. Prevents short-cycling." No code or default change; key + behavior preserved to avoid migration churn.

**Acceptance Criteria**
- **Verify:** Form helper text reads "Minimum continuous runtime…" not "Timeout before turning off…".

### D6 — Consolidate "60" defaults

- Remove `DEFAULT_HUMIDITY_FAN_ON` and `DEFAULT_HUMIDITY_FAN_OFF` from `hvac_const.py`.
- Add `DEFAULT_HUMIDITY_FAN_HYSTERESIS: Final = 10` to `const.py`.
- `hvac_fans.py` imports `DEFAULT_HUMIDITY_THRESHOLD` and `DEFAULT_HUMIDITY_FAN_HYSTERESIS` from `..const`.
- `automation.py:1636-1637`: replace literal `60` and `600` fallbacks with `DEFAULT_HUMIDITY_THRESHOLD` and `DEFAULT_HUMIDITY_FAN_TIMEOUT` constants (both already imported).

**Acceptance Criteria**
- **Verify:** Grepping the codebase for the literal `60` near `humidity` returns no surviving fallback sites.
- **Test:** `test_humidity_defaults_single_source_of_truth` — AST-walks `hvac_fans.py` and `automation.py` and asserts no module-level or fallback literal `60` near humidity-fan logic.

## Files touched

- `const.py` — add `CONF_HUMIDITY_FAN_MAX_RUNTIME`, `DEFAULT_HUMIDITY_FAN_MAX_RUNTIME`, `DEFAULT_HUMIDITY_FAN_HYSTERESIS`
- `domain_coordinators/hvac_const.py` — remove `DEFAULT_HUMIDITY_FAN_ON`/`OFF`
- `automation.py` — max-runtime gate, hysteresis, constant cleanup (~30 LoC net)
- `domain_coordinators/hvac_fans.py` — plumb config to `RoomFanState`, max-runtime gate, hysteresis from user threshold (~40 LoC)
- `config_flow.py` — new form field in climate step + options flow (~15 LoC)
- `strings.json` + `translations/en.json` — helper text for new field; clarified text for `humidity_fan_timeout`
- `quality/tests/test_v4621_humidity_fan_hardening.py` — new test file (~120 LoC)

## Cost

- Production: ~90 LoC across 5 files
- Tests: ~120 LoC
- Tier 1 review (one staff-engineer pass, mental execution required)

## Risks

1. **Path B plumbing.** `RoomFanState` construction is in `_register_room_fans`; need to verify merged config has the room's `CONF_HUMIDITY_FAN_THRESHOLD` reachable. Mitigation: read in the same `merged.get(...)` block at `hvac_fans.py:112-130`.
2. **`_humidity_on_since` vs `_humidity_fan_triggered_time`.** Two state fields with overlapping meaning is a code-smell. Justified because they encode different gates (max vs min). Document clearly in code comments.
3. **Suppression after max-runtime fires.** If we don't suppress, the next cycle sees humidity > threshold and re-turns-on immediately — defeating the cap. Suppression must require humidity to drop below the OFF threshold (`threshold - hysteresis`) before allowing reactivation. This is the v4.5.18 stale-signal gate shape (require a fresh signal of "things changed" before re-firing).
4. **Default of 60 min.** Reasonable for bathrooms / typical use; conservative enough not to interrupt a long shower or load of laundry. User can tune up to 240 min for utility rooms. Worth a config helper sentence noting the trade-off.
5. **No anomaly emit on cap-fire.** A repeating max-runtime cap-fire on the same room IS evidence of a stuck sensor and ought to surface. Deferred to v4.6.3 (folds neatly into the anomaly touchpoint migration). For v4.6.2.1, INFO log is sufficient.

## Review checklist

- [ ] Path A and Path B both honor `CONF_HUMIDITY_FAN_THRESHOLD` (no hardcoded 60)
- [ ] Path A and Path B both apply max-runtime cap
- [ ] Path A has hysteresis (currently single-threshold)
- [ ] `_humidity_on_since` reset on every on→off (otherwise stale state across cycles)
- [ ] Re-trigger suppression after cap-fire (humidity must drop < OFF threshold first)
- [ ] No new module-level imports that could trigger Bug Class #34
- [ ] Tests cover: chatter, max-runtime cap, suppression, user-threshold-respected, defaults consolidated
- [ ] Strings/translations updated for new field + clarified timeout helper text

## Live validation post-deploy

1. Open HA → Configuration → Universal Room Automation → any room with `humidity_fans` configured → Climate step → confirm "Humidity Fan Max Runtime" field is visible with default 60 min.
2. Watch a bathroom for one shower cycle: fan should turn on at threshold, run during shower, turn off ~10 min after humidity drops below `threshold - 10`. No chatter near 60%.
3. (Synthetic) Force a humidity sensor stuck-high (or set max_runtime to 600s for a test room): confirm fan turns off at the cap and INFO log `humidity_fan_max_runtime_exceeded` fires.
4. With HVAC coordination ON: change `CONF_HUMIDITY_FAN_THRESHOLD` to 70%, reload entry, confirm fan activation point shifts (does NOT still activate at 60%).
5. No regression in normal humidity-fan behavior across the four family bedrooms (none have humidity_fans, so this is a no-op there — confirms no crash).
