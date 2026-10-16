# Plan review 5 — EC storm/blind Rev 3.2 delta (completeness + build-prediction)

**Target:** `docs/planning/PLANNING_ec_storm_and_blind_decisions.md`, branch `plan/ec-storm-rev32` (173c6a87a, 88cec18e9), diff vs develop 0c514280e.
**Scope:** Rev 3.2 delta only: §D-B2a eligibility column, polygon immediate top-up leg, fusion gate at `inclement.py:593-598` / `:642-646`, INV-6(iii)/(vi), D-B7 Storm Guard trip-wire.
**Read first:** HVAC/presence state-of-play docs not applicable (energy only).
**Verdict:** PROCEED after fixes. 0 CRITICAL, 2 HIGH, 5 MEDIUM, 4 LOW.

## Verified claims (greps re-run)

| Claim | Result |
|---|---|
| `decision.grid_precharge` has one decision reader | TRUE. `energy_battery.py:5790` (full_hold block). Display readers: `:2805` attr, `sensor.py:9383` passthrough. `:4083` is a comment. |
| Construction sites | TRUE. Computed at `inclement.py:593` (warn) and `:642` (corroborated off-peak watch); literal False at `:521, :621, :676, :687, :703`. |
| No new CFG writer | TRUE. Both legs exit through `_result` (`:5833` degraded variant, `:5850`). The v5.103.66 governor is the `RESERVE_SET_VALUE_WRITERS` AST allowlist (`energy_const.py:2307`); no topology change, lint unaffected. |
| Byte-identical with option off (fusion) | TRUE for fusion: both expressions start `self._grid_precharge_on_hold and`, so the new conjunct never evaluates. See M1 for the classifier side. |
| Blind refusal applies unchanged | TRUE. `_precharge_refused_on_blind` (`:4106`) sits inside the `grid_precharge` branch, so it covers the immediate leg at every TOU. |
| Cloud withhold | The full-hold leg passes `cloud_withhold_exempt=True` (`:5844`, `:5858`), so the `_result` chokepoint (`:6317-6324`) does not withhold it. Pre-existing; the immediate leg inherits it at peak. |
| Arbitrage/attain precedence | full_hold short-circuits at `:5787` before the TOU/arbitrage branches, so the immediate leg preempts arbitrage the same way full_hold already does. That is consistent with D-B6 yielding (D-B6 is not a full hold). |
| `_send_nm_alert` | TRUE, `energy.py:9532`, async, severity map includes `"medium"`. |
| Anomaly shape | `_emit_anomaly` (`energy_write_verify.py:1152`) is a write-verify method with severity plumbing. The closer precedent for an EC-level point-in-time anomaly is the circuit-anomaly block at `energy.py:9590-9611` (`AnomalyEvent(coordinator="energy", type="energy.circuit_…", …)`). See L3. |

## HIGH

**H1. The cap window and the cost bound are per alert ID, but the plan prices them per event.** The cap is `start ≤ now ≤ min(end, start + 60)` with `start = Onset or Sent` (D-B1, plan line 286), keyed on "some verified-local polygon contributor". Two reachable cases break "≤ ~10 kWh peak import per house-covering warning":
(a) NWS often issues a new SVW (new ID, new Onset) as a storm line moves or re-intensifies. Each new ID opens a fresh 60-minute window, so a two-hour storm can yield two or three windows at peak.
(b) An `Update` message (kept by D-B1) may carry a new Onset/Sent. Whether an SVW update keeps the original Onset is not verified in the plan; I could not verify it either. If it does not, every update restarts the cap.
INV-6(vi) as written stays true (each alert is within its own cap), so Review D cannot catch this; only the stated price is wrong. Fix: either (1) state per-alert semantics and re-price as "≤ 10 kWh per alert ID, ≤ N per storm", or (2) key the cap on the earliest start among verified-local polygon contributors active within a lookback (stateful, so it needs the restart story the plan currently avoids). Before choosing, run a read-only probe over the NWS history already used in `AUDIT_nws_alert_history_lakeway.md` for SVW Update-vs-Onset behavior and same-day follow-up IDs. Marginal-benefit note: (1) is the simple version; take it unless the probe shows 3+ windows per storm are common.

**H2. A falsifier will flag legitimate behavior when the two legs interleave.** INV-6 falsifier: "more than one CFG on→off transition per latch episode." Legal sequence: a WSW is in the prepare set with the D-B6 latch engaged (CFG on, bottom rate). A verified-local SVW starts, full_hold short-circuits, and the immediate leg keeps CFG on. At cap expiry the full_hold block returns BACKUP `holding charge`, which turns CFG off while the SVW is still active. The SVW ends, D-B6 resumes, and CFG turns on again. The latch episode now has two on→off transitions. A builder reading the falsifier will either suppress the legitimate D-B6 resume or write a test that is red for a correct trace. The plan also doesn't say whether the D-B6 latch advances (to `"reached"`) on ticks where full_hold shadows it and SOC crosses `preonset_floor` there. Fix: scope the falsifier to "per latch episode on ticks where D-B6 owns the emission". State that latch transitions are evaluated in fusion every tick, independent of which leg emits. Add a test with the interleaved trace.

## MEDIUM

**M1. The byte-identical proof covers fusion only; the new aggregation runs in the classifier for every option value.** `precharge_eligible` and `polygon_topup_active` are computed inside `AlertClassifier.classify` (they are `AlertClassification` fields). Any exception there drops to `classify_error`, which is `allow_discharge` (`energy_battery.py:2690-2697`). That loses a real warn hold on an option-off tick, a safety regression caused by a cost feature. Examples: tz-naive vs tz-aware arithmetic in `start + timedelta(cap)`, or a row tuple unpacked with 4 vs 5 columns. The golden hour-sweep won't catch it unless its inputs include malformed or edge alerts. Fix: compute the two fields in a guarded helper that falls back to False/False (never raises into classify). Add a golden case with odd Onset/Ends formats, and a mutation that raises in the helper and must leave the hold intact.

**M2. The eligible watch rows rarely reach the full-hold path.** Corroboration needs `condition_stormy` (`inclement.py:637-639`), and `_STORM_CONDITIONS` (`weather_manager.py:73-77`) has no `snowy`, `clear` or cold state: only `snowy-rainy` comes close. A Hard Freeze, Extreme Cold or Wind Chill Watch will almost never corroborate, so its "eligible" column only matters through D-B6's forecast confirmation. The table is not wrong, but the control case "corroborated Winter Storm Watch → True" in `test_severe_thunderstorm_watch_never_precharges` is synthetic, and the evidence table implies reach it doesn't have. Fix: add one line to D-B2a saying which leg each eligible watch row can actually fire on.

**M3. Live (e3) can produce a false negative.** It looks for a `reserve_write` row whose reason contains `— pre-charging`. When the reserve is already at `decision.reserve_floor` (the BACKUP-hold tick before already wrote it), the deadband suppresses the reserve write while CFG still turns on, so no row appears for a real pre-charge. Use the CFG switch state history and the decision `reason`/`charge_from_grid` key (ground truth) instead. Keep the reserve row only as a secondary signal.

**M4. The immediate leg imports at peak with no grid-import ceiling.** The arbitrage grid-import guard (`energy_battery.py:3262-3267`, `arbitrage_grid_import_guard_kw`) covers arbitrage only. A ~10 kW charge plus a summer-afternoon AC load during an SVW is new peak exposure; off-peak exposure already existed. Either confirm the service and breaker headroom (operator item) or state explicitly that no import guard applies and why. Today the plan is silent.

**M5. The D-B7 trip-wire re-fires on every restart while Storm Guard stays on.** "Once at the first tick after setup if it reads on" with a RAM latch gives one NM notice plus one anomaly row per HA restart. This install has had restart storms (memory: restart storm is live). If the operator deliberately enables Storm Guard, that becomes NM spam. Fix: dedupe across restart using a persisted last-notified state (a RestoreEntity attr or a DB lookup for the latest `storm_guard_enabled` row since the last off). Or make the boot-time case log-only and fire NM only on an observed transition. Update `test_storm_guard_tripwire_on_at_boot_fires_once` to pin the chosen semantics across two simulated setups.

## LOW

- **L1.** The plan cites "`DEFAULT_STORM_CHARGE_THRESHOLD` 90, `inclement.py:597`". `:597` actually reads `self._storm_charge_threshold` (constructor arg, default 90), while the emission site gates on `DEFAULT_STORM_CHARGE_THRESHOLD` (`energy_battery.py:5792`). These are two named thresholds that happen to be equal, so tests should pin both or the plan should name the split.
- **L2.** The "~10 kW observed charge rate" behind the +19 pp and ≤10 kWh figures has no cited source (entity/history). Cite the measurement or mark it an estimate. It sizes the operator decision in §14 item 5.
- **L3.** The anomaly type `storm_guard_enabled` breaks the `energy.<x>` prefix convention used by EC anomalies (`energy.py:9601`). Use `energy.storm_guard_enabled` and copy the `energy.py:9590-9611` shape, not `_emit_anomaly` (which carries write-verify severity semantics).
- **L4.** No attribute exposes `precharge_eligible` / `polygon_topup_active`, so a "not observed" Live (e3) can't be told apart from a gate that never evaluates. Add both as diagnostic attrs beside `inclement_grid_precharge` (`energy_battery.py:2805`). Display only.

## Hollow-test and day/time traps

- `test_polygon_topup_cap_expires` at 59/61 min must drive `now` through the classifier, not monkeypatch `polygon_topup_active`. Otherwise the cap-window mutation can't go red.
- The cap boundary uses `≤` on both ends. Pin `now == start + cap` (inclusive) and a DST-crossing SVW (start 01:30 local on fall-back night) so tz-aware arithmetic is exercised. A late-night SVW is plausible.
- `test_polygon_topup_verified_local_any_tou` should parametrize season. In shoulder/winter there is no `peak`, so "any TOU" must be shown for `mid_peak` too.
- `test_precharge_option_off_byte_identical` is hollow unless the pre-change golden includes the M1 edge inputs. Capture it before the classifier change, as the plan says.

## Severity summary

| Severity | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 2 (H1 cap/cost per-alert, H2 falsifier vs interleaved legs) |
| MEDIUM | 5 |
| LOW | 4 |

Bug classes: computed-but-unpriced bound (H1); invariant over-scoped / falsifier ambiguity (H2); new code on the no-op path (M1, Bug Class "byte-identical on no-op path"); display-vs-ground-truth acceptance (M3); restart-dedupe (M5).
