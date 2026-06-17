# URA v5.5.2 — Continuous heat_cool enforcer + attain HOLD reason fix

Two live-found fixes from the EC/HVAC correctness audit.

## What ships

### Continuous heat_cool enforcer (HVAC)
Live-found: the upstairs zone `climate.up_hallway_zone_2` drifted `heat_cool`→`cool` (preset/ setpoints unchanged) and **no path restored it** — the OverrideArrester only reverts on a *manual-preset* override, and the old mode-restore loop only caught `off`. Now `_apply_house_state_presets` (`hvac.py`) restores `heat_cool` on **any** non-heat_cool mode for heat_cool-capable zones, every decision cycle. Keeps the pre-existing skips for egress-paused (`off`) and AC-reset (`off`) zones; wraps the write in the OverrideArrester suppress() handshake so it isn't read as a manual override.

**Operator-directed design (2026-06-16):** kept deliberately simple — restore heat_cool from any path, no freeze/emergency-heat special-casing, no Safety-Coordinator coupling. The operator works via preset ranges (heat_cool covers both heating and cooling via low/high bounds). **Behavioral note:** if the Safety Coordinator sets single-mode `heat` on a freeze, the enforcer reverts it to `heat_cool` next cycle (heat_cool still heats via the low setpoint). The queued follow-up `PLANNING_freeze_safety_range_shift.md` makes the freeze response range-based so this is moot.

### Attain HOLD reason-string fix (EC, observability)
`energy_battery.py:2031-2033` printed a contradictory `"SOC 71% reached target 80%"` while the attain HOLD latch held with SOC sagged below target. Reworded to `"holding at target 80% (SOC now 71%); reserve locked until boundary"`. No logic change.

## Review
Tier-2-DB, 3 framing-disjoint reviews + fix-up. The panel caught a CRITICAL safety regression (the build's unrequested 2h emergency-heat timer would clobber an ongoing freeze) and a full set of tautological tests — both resolved (machinery deleted per operator; tests rewritten to drive real code, orchestrator mutation-verified). 0 blocking findings at ship. Ledger: `docs/reviews/code-review/v5.5.2_heatcool_summary.md`.

## Accepted-as-designed / deferred
- **Single-mode `heat` from Safety is reverted to heat_cool** by the enforcer (operator-accepted; freeze-range follow-up queued).
- **B-MED-1 (deferred):** a thermostat that silently rejects `heat_cool` would have the enforcer re-issue `set_hvac_mode` every 5 min (harmless log noise) — tracked, add a downgrade-counter if observed.

## Live Validation — Validated 2026-06-16 (post-restart, v5.5.2 HACS-confirmed)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Enforcer holds heat_cool | **PASS** | All three heat_cool-capable zones hold `heat_cool` post-restart: `climate.up_hallway_zone_2`, `climate.back_hallway_zone_3`, `climate.thermostat_bryant_wifi_studyb_zone_1` (live read). The upstairs zone — the one that had drifted to `cool` (Gap 2) — is back on `heat_cool`. |
| L2 | No fight with egress / AC-reset | IN-SUITE | No egress-pause or AC-reset active at validation; the skips are code-confirmed + mutation-tested (`test_heatcool_enforcer.py`). |
| L3 | No write spam | IN-SUITE | Idempotent `!= heat_cool` guard prevents repeat writes; covered by the already-heat_cool test. |
| L4 | Attain reason wording | DEFERRED (no HOLD active) | At validation the battery was off-peak draining (`reason: "Off-peak drain — SOC 33% > target 10% (tomorrow excellent)"`), not in an attain HOLD. The reword is in-code + tested; will show on the next attain HOLD. |
| L5 | No HVAC regression | PASS | Zero new URA ERROR lines from the v5.5.2 boot (only the known benign DB-write-worker startup transient at 20:59); all zones healthy on `heat_cool`. |

**Verdict:** v5.5.2 deployed healthy; the headline enforcer (L1) validated live — all heat_cool-capable zones hold `heat_cool`, the upstairs `cool`-drift is corrected. L2/L3/L4 are in-code + mutation-tested, awaiting their live conditions. Cycle CLOSED.
