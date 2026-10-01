# PLANNING — SAFETY-HAZARD-NEVER-CLEARS-1

Card: SAFETY-HAZARD-NEVER-CLEARS-1 ("humidity / freeze / overheat hazards never clear
until HA restart").

Tier: **Tier 2** (Feature-cycle; 2 framing-disjoint reviews + live validation).
Justification below.

Stacking: this plan is written **on top of** `feature/safety-humidity-junk-floor`
(SAFETY-HUMIDITY-JUNK-READING-1, in review, 4 ahead / 55 behind develop). That branch
stops the *bogus* low-humidity hazard from being CREATED; this plan is why one that DOES
get created never goes away. Both land before the hazard-lifecycle gap is closed.

---

## 0. Institutional context verified

### Code read end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/safety.py` — the
  entire hazard pipeline: §tables (176-234), `__init__` state (952-1030),
  `_async_sensor_state_changed` (1514-1557), `_evaluate_sensor_on_recovery` (1559-1603),
  `_process_sensor` (1631-1728), `_handle_binary_hazard` (1734-1789),
  `_check_flooding_escalation` (1791-1840), `_handle_numeric_hazard` (1846-1944),
  `_handle_temperature` (2009-2058), `_handle_humidity` (2064-2271),
  `_respond_to_hazard` (2277-2470 incl. anomaly block), `_async_periodic_check`
  (2655-2678), `clear_hazard` / `clear_all_hazards` (2732-2748), `get_safety_status`
  (2788-2804), `is_hazard_active` (3074-3084), `async_teardown` (3086-3119).
- `domain_coordinators/base.py:237` — default `is_hazard_active` returns False.
- `domain_coordinators/notification_manager.py:2996-3059` — cooldown re-evaluate path
  (`_re_evaluate_hazard` → `coordinator.is_hazard_active` → re-fire-or-idle). This is
  the ONLY consumer that currently makes an action out of "cleared" state.
- `domain_coordinators/signals.py:19,273` — `SIGNAL_SAFETY_HAZARD` payload shape
  (one-way "detected" signal; no companion "cleared" signal exists).
- `coordinator.py:145,1705` — SIGNAL_SAFETY_HAZARD dispatch wiring.
- `sensor.py:6667-6677` — `sensor.ura_safety_active_hazards` entity (reads
  `len(self._active_hazards)` via diagnostics; so a stuck entry inflates the count).

### Prior-art scan (REUSE-or-BUILD per piece)
Grep surfaces consulted: `const.py`, `config_flow.py`, `options_flow.py`,
`sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`,
`domain_coordinators/*.py`, `docs/Coordinator/SAFETY_COORDINATOR.md`,
`docs/planning/*safety*`, `docs/planning/kanban.data.yaml`.

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Clear path for humidity in-range | **REUSE** the same remove-key idiom used in `_handle_numeric_hazard` (safety.py:1917-1923) and `_handle_binary_hazard` (safety.py:1744-1754) — pop both `_active_hazards[key]` and `_hazard_occurrences[key]`, then `self._notify_entity_update()`. No new removal primitive. |
| Clear path for temperature in-range | **REUSE** same idiom. `_handle_temperature` currently returns `list[Hazard]`; clearing must happen in the handler regardless of what it returns (clear on the TYPE-wise negative branch; see §4). |
| Hysteresis offset | **NEW** named module constants (`FREEZE_CLEAR_OFFSET_F`, `OVERHEAT_CLEAR_OFFSET_F`, `HIGH_HUMIDITY_CLEAR_OFFSET_PCT`, `LOW_HUMIDITY_CLEAR_OFFSET_PCT`). No equivalent found (grep `CLEAR_OFFSET`, `HYSTERESIS` in `const.py` + `safety.py` returned nothing). Rung 1 (module constant): safety-semantics bounds; changing them should require review, exactly like `HUMIDITY_PLAUSIBLE_MIN_PCT` from the junk-floor branch. |
| Minimum hold-time before clear | **NEW** `HAZARD_MIN_HOLD_S` module constant (rung 1) — prevents a single sample on the "ok" side (noise) from instantly tripping a cleared → re-fired → cleared churn against NM. No existing equivalent. |
| "Cleared" dispatch signal | **DO NOT ADD** this cycle. NM already handles the lifecycle by polling `is_hazard_active` on cooldown-expiry (notification_manager.py:3034-3059). Adding a new signal is scope creep — park under `SAFETY-HAZARD-CLEARED-SIGNAL-1` if a future consumer wants push semantics. (Marginal-benefit decomposition — see §9.) |

### Prior planning docs consulted
- `docs/planning/PLANNING_freeze_safety_range_shift.md` — freeze threshold tuning,
  does NOT touch clear semantics.
- `docs/planning/PLANNING_zone_safety_alert_split.md` — zone-chip projection over the
  SAME tables; clear-on-recovery for the coordinator inherits automatically because
  `resolve_safety_bands()` reads the tables at call time (safety.py:242-254).
- `docs/planning/AUDIT_restart_safety_classification.md` — restart semantics for
  anomaly/response-time baselines; `_active_hazards` is NOT persisted (see §5).
- `docs/planning/kanban.data.yaml` — SAFETY-HUMIDITY-JUNK-READING-1 branch
  `feature/safety-humidity-junk-floor` currently in review; this plan stacks on top.

### Design doc
- `docs/Coordinator/SAFETY_COORDINATOR.md` — describes `_active_hazards` as the single
  source of truth; the lifecycle gap (humidity + temperature never remove) is **not**
  called out there and will be updated in the same ship.

### Memory bodies pulled
- `feedback_marginal_benefit_pushback` — governed §9 non-goal below.
- `feedback_suppression_needs_discharge` — hysteresis + minimum hold ARE the discharge
  for the clear-side suppression; documented as such in §4.
- `feedback_coincidental_equality_masks_concept_split` — "raise threshold" and "clear
  threshold" are the exact smell this warns about; forcing distinct constants.

### Config-first check
Can the problem be fixed by a knob turn alone? **No.** There is no live knob or options
field that reaches `_active_hazards` removal; the omission is in the code paths at
safety.py:2009-2058 and 2064-2271. The runtime `CONF_HUMIDITY_NORMAL_*_PCT`
overrides change *entry* thresholds but there is no *exit* path. Code change is
required. (The two new offset knobs land as module constants, rung 1 — not as live
Number entities — per Numbers-Get-Knobs.)

---

## 1. VERIFY FIRST — is it still real?

Reads to run BEFORE build dispatch (plan-reviewer re-runs them). I could not run
these in the planner environment (no shell tool); the planner records the commands;
reviewer records the OUTPUT below each one.

```bash
# A. Current coordinator view
/tmp/ha.sh 'states/binary_sensor.ura_safety_coordinator_safety_alert' | jq '{state, last_changed, last_updated}'
/tmp/ha.sh 'states/sensor.ura_safety_coordinator_safety_status' | jq '{state, worst_location: .attributes.worst_location, scope: .attributes.scope, hazards: .attributes.hazards}'
/tmp/ha.sh 'states/sensor.ura_safety_coordinator_safety_active_hazards' | jq '{state, hazards: .attributes.hazards}'

# B. Was the alert on for days? (72h window — any "off" transition means a clear DID happen)
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ); THEN=$(date -u -v-72H +%Y-%m-%dT%H:%M:%SZ)
/tmp/ha.sh "history/period/${THEN}?end_time=${NOW}&minimal_response&no_attributes&filter_entity_id=binary_sensor.ura_safety_coordinator_safety_alert,sensor.ura_safety_coordinator_safety_status" | jq '[.[0][] | {s: .state, t: .last_changed}]'

# C. Does the live source sensor behind the current worst_location now read in-range?
# (fill in the sensor_id from (A)'s worst hazard)
/tmp/ha.sh 'states/<worst_hazard_sensor_id>' | jq '{state, unit: .attributes.unit_of_measurement, lu: .last_updated}'

# D. Any writes to the hazards_detected table in the last 24h with a matching clear?
ssh ha "sqlite3 -readonly /config/universal_room_automation/data/universal_room_automation.db \
  'SELECT hazard_type, severity, location, datetime(detected_at,\"unixepoch\",\"localtime\") AS t FROM hazard_log WHERE detected_at >= strftime(\"%s\",\"now\",\"-24 hours\") ORDER BY detected_at DESC LIMIT 50;'"
```

**Discriminator.** The card is CONFIRMED if (A) shows a stuck advisory/warning on the
alert, (B) shows no transition back to normal across the 72h window, AND (C) shows
the live source sensor currently in-range. If any of those three fails, the card is
MOOT or SMALLER than claimed; stop and re-triage. **If a transition DID happen** (B
shows at least one off), the bug may be the stricter "sometimes clears, sometimes
doesn't" shape — triage before build.

---

## 2. Hazard-type table (how raised, how cleared TODAY)

| Hazard type | Raise site (file:line) | Clear site TODAY | Gap? |
|---|---|---|---|
| SMOKE (binary) | `_handle_binary_hazard` safety.py:1758 | `_handle_binary_hazard` safety.py:1744-1754 (`new_state != "on"` pops key) | OK |
| WATER_LEAK (binary) | `_handle_binary_hazard` safety.py:1762 | Same binary clear + `_leak_start_times.pop`, `_active_leak_sensors.discard` | OK |
| FLOODING (escalated) | `_check_flooding_escalation` safety.py:1791 + `_async_periodic_check` safety.py:2655 | Clears **implicitly** when the underlying leak sensors go off (binary clear removes them from `_active_leak_sensors`), but the FLOODING key `flooding:<loc>` is **not explicitly popped** when the escalation condition stops holding | **MINOR GAP** (secondary; §4-D) |
| CARBON_MONOXIDE (numeric) | `_handle_numeric_hazard` safety.py:1934 | safety.py:1917-1923 (severity None → pop) | OK |
| HIGH_CO2 (numeric) | same | same; also log-only rung pops key safety.py:1875-1878 | OK |
| HIGH_TVOC (numeric) | same | same; sustained tracker also cleared safety.py:1913 | OK |
| **FREEZE_RISK** (temp) | `_handle_temperature` safety.py:2022-2038 | **NONE** — handler only APPENDS when at/below threshold; nothing pops when value recovers | **PRIMARY GAP** |
| **OVERHEAT** (temp) | `_handle_temperature` safety.py:2040-2056 | **NONE** — same shape | **PRIMARY GAP** |
| **HIGH_HUMIDITY** (sustained ladder) | `_handle_humidity` safety.py:2192-2243 | Only `_humidity_above_since` + `_humidity_hazard_fired` cleared when value < low (safety.py:2244-2247); `_active_hazards["high_humidity:<loc>"]` is **never popped** | **PRIMARY GAP** |
| HIGH_HUMIDITY (swing rung) | `_handle_humidity` safety.py:2158-2182 | Swing-fired set discharged safety.py:2186-2187; hazard key never popped | **PRIMARY GAP** (same key) |
| **LOW_HUMIDITY** (universal) | `_handle_humidity` safety.py:2249-2269 | **NONE** — same shape as temperature | **PRIMARY GAP** |
| ROC / HIGH_*_ROC rate hazards | `_rate_detector.check_thresholds` → appended at safety.py:1712-1725 | **NONE** — rate hazards are keyed into `_active_hazards` by `_respond_to_hazard` and never popped; rate baselines are updated but the hazard entry is immortal | **SECONDARY GAP** (same mechanism — same fix shape; §4-E) |
| Manual `clear_hazard` / `clear_all_hazards` | n/a | safety.py:2732-2748 — **ZERO production callers** (grep found only tests + definitions) | Not a fix path |

**Operator-visible impact:** FREEZE_RISK, OVERHEAT, HIGH_HUMIDITY, LOW_HUMIDITY, and
rate hazards — once set — keep `get_safety_status()` pinned at advisory/warning/alert
until `async_teardown` runs (HA restart or reload). Matches the card.

---

## 3. Consumer map of `_active_hazards`

| Consumer | file:line | Trust (vs display) | What changes when a hazard clears |
|---|---|---|---|
| `active_hazards` property | safety.py:1032-1035 | Display | Dict shrinks |
| `get_safety_status()` | safety.py:2788-2804 | **Trust** (drives the status entity "critical/alert/warning/advisory/normal") | Returns "normal" when dict empty — the user-visible fix |
| `get_all_hazards_detail()` | safety.py:2806-2826 | Display (attribute on status + active_hazards sensors) | Row vanishes from attribute list |
| `get_water_leak_status()` | safety.py:2828-2847 | Display | Row vanishes if WATER_LEAK/FLOODING |
| `sensor.ura_safety_active_hazards` | sensor.py:6667-6677 | Display | Count decrements |
| `binary_sensor.ura_safety_alert` | binary_sensor (reads status) | **Trust** (dashboard tile; stuck ON today) | Flips to off when no hazards remain |
| Diagnostics counters block | safety.py:2420-2478 | Display / anomaly | `active_hazard_count` observation decrements; anomaly z-score tracks the drop (no new baseline risk — count baseline tolerates reductions). |
| `is_hazard_active(type, loc)` | safety.py:3074-3084 | **Trust** — consumed by `NotificationManager._re_evaluate_hazard` (notification_manager.py:3034-3059). | Returns False → NM returns to IDLE on next cooldown expiry; **re-fire is suppressed**. |
| `_respond_to_hazard` dedup | safety.py:2286-2297 | **Trust** — "same type:location already active" suppresses re-signal. | After a clear, the next entry back into the hazard band is a NEW event → re-fires `SIGNAL_SAFETY_HAZARD` → NM/HVAC/energy/security/music all re-receive it. |
| `SIGNAL_SAFETY_HAZARD` receivers | hvac.py:1378, energy.py:1113, security.py:711, music_following.py — grep'd | **Trust** (cross-coordinator overrides) | No "cleared" signal exists; receivers either time out their own grace or ignore. **Not changed this cycle.** |
| Zone-chip projection | aggregation.ZoneSafetyAlertSensor via `resolve_safety_bands()` safety.py:242-387 | **Trust** (per-zone chip color) | Inherits automatically — chip returns to green as soon as the sensor is in-range (zone-chip queries live state, not `_active_hazards`); the chip is actually consistent TODAY while the house tile is wrong. |

**Notification-storm concern (REAL).** Without hysteresis+hold, a sensor that
oscillates one point around the raise threshold would clear → re-raise → clear each
state_change. Each re-raise fires `SIGNAL_SAFETY_HAZARD` (safety.py:2328-2339) which
HVAC/energy/security/music receive AND NM pages the operator. The hysteresis offset
and minimum-hold knobs in §4 ARE the discharge for this suppression; the dedup check
at safety.py:2286-2291 is NOT sufficient because the clear deletes the dedup key.

---

## 4. Design — clear-on-recovery with hysteresis

**Falsifiable invariant.** For every hazard key currently in `_active_hazards`, there
exists a sequence of in-range sensor readings sustained ≥ `HAZARD_MIN_HOLD_S` that
removes the key. Equivalently: given a sensor that was above/below the raise
threshold, once it has been inside `[raise - clear_offset, raise]` (for high-side) or
`[raise, raise + clear_offset]` (for low-side) for ≥ `HAZARD_MIN_HOLD_S`, the key is
popped and `_notify_entity_update()` fires.

**Negation (what proves the fix broken):**
- Any `_handle_temperature` / `_handle_humidity` codepath where the sensor sits
  comfortably in-range for 10 minutes AND `_active_hazards` still contains the key
  → FAIL.
- An oscillating sensor at threshold±ε fires > 1 NM re-page per 10 minutes
  → FAIL (hysteresis storm).

### 4-A. `_handle_temperature` (FREEZE_RISK + OVERHEAT)

Add the symmetric clear branch for each hazard type. Use the same REMOVE idiom as
`_handle_numeric_hazard` safety.py:1917-1923.

```
# pseudocode shape — see builder brief for exact edits
freeze_key = f"{HazardType.FREEZE_RISK.value}:{location}"
freeze_raise = NUMERIC_THRESHOLDS[FREEZE_RISK][Severity.LOW]  # 45°F — least-strict
if freeze_key in self._active_hazards:
    if value >= freeze_raise + FREEZE_CLEAR_OFFSET_F:   # hysteresis
        _mark_above_since(freeze_key, now)              # min-hold timer
        if _held_above(freeze_key, now) >= HAZARD_MIN_HOLD_S:
            self._active_hazards.pop(freeze_key, None)
            self._hazard_occurrences.pop(freeze_key, None)
            self._active_above_since.pop(freeze_key, None)
            self._notify_entity_update()
    else:
        self._active_above_since.pop(freeze_key, None)  # fell back in — reset timer
```

OVERHEAT is the mirror. `_classify_severity` is already asymmetric (safety.py:1957-1966);
the clear-side mirrors that asymmetry — for FREEZE "clear" means value **above**
raise threshold; for OVERHEAT, **below**.

New instance state (co-located with `_humidity_above_since`):
`self._active_above_since: dict[str, datetime] = {}`. Keyed by hazard-key (not
entity_id — one sensor can carry both freeze and overheat state separately).

### 4-B. `_handle_humidity` — HIGH_HUMIDITY (sustained ladder + swing)

Clear in the existing `else: # Below all thresholds` branch at safety.py:2244-2247.
The branch already resets `_humidity_above_since` + `_humidity_hazard_fired`; it must
also pop the `_active_hazards` key when value <= `low - HIGH_HUMIDITY_CLEAR_OFFSET_PCT`
AND the min-hold has elapsed. Reuse the same `_active_above_since` dict.

Edge case to preserve: swing-rung hazards (safety.py:2158-2182) register as
`HIGH_HUMIDITY` same key — one clear path serves both. Swing's own one-shot flag at
safety.py:2186-2187 already discharges below `swing_floor`; clearing the hazard key
when below `low - CLEAR_OFFSET` is consistent (swing_floor is typically ≥ low).

### 4-C. `_handle_humidity` — LOW_HUMIDITY

Today LOW_HUMIDITY fires every state change below threshold (no sustain window). The
clear branch must pop when value >= `LOW_HUMIDITY_THRESHOLDS[LOW] + LOW_HUMIDITY_CLEAR_OFFSET_PCT`
for ≥ `HAZARD_MIN_HOLD_S`. Same remove idiom.

Interaction with the junk-floor branch: `feature/safety-humidity-junk-floor` adds
`HUMIDITY_PLAUSIBLE_MIN_PCT` that aborts the LOW branch for implausible readings
(reconnect zeros). The clear path must NOT be run from an implausible reading either
— guard the clear block behind the same plausibility check (reads cleaner as: do
nothing if below the plausibility floor, do raise/clear otherwise). Rebase order:
land junk-floor first, then this cycle rebases on it.

### 4-D. FLOODING key cleanup

When `_handle_binary_hazard` discards an entity from `_active_leak_sensors` (safety.py:1751),
also recompute whether `flooding:<loc>` can hold: if `_active_leak_sensors` is now
empty AND no sustained-single-sensor condition holds, pop `flooding:<loc>` keys
whose `location` matches. Secondary — small helper, no hysteresis needed (binary).

### 4-E. ROC rate hazards

Same shape as 4-A/B. In `_process_sensor` safety.py:1696-1728, after
`check_thresholds` returns results, enumerate the active-hazards keys of ROC
hazard types for this entity's location; if the latest 30-min rate magnitude is
below the raise rate minus `ROC_CLEAR_OFFSET_FRAC × raise_rate` for ≥
`HAZARD_MIN_HOLD_S`, pop. Keep this surgical — a small helper
`_clear_rate_hazards_if_quiet(entity_id, location, now)`.

### 4-F. Named knobs (Numbers-Get-Knobs — all **rung 1 module constants**)

In `safety.py` near NUMERIC_THRESHOLDS block:

| Constant | Default | Rung | Why constant, not entity |
|---|---|---|---|
| `FREEZE_CLEAR_OFFSET_F` | `3.0` | 1 | Safety-semantics bound — changing invites hysteresis-storm regressions; peer of raise thresholds. |
| `OVERHEAT_CLEAR_OFFSET_F` | `3.0` | 1 | Same. |
| `HIGH_HUMIDITY_CLEAR_OFFSET_PCT` | `3.0` | 1 | Peer of `HUMIDITY_THRESHOLDS[...]['low']`. |
| `LOW_HUMIDITY_CLEAR_OFFSET_PCT` | `3.0` | 1 | Peer of `LOW_HUMIDITY_THRESHOLDS`. |
| `HAZARD_MIN_HOLD_S` | `300.0` (5 min) | 1 | Anti-flap for the clear path; peer of `FLOODING_SUSTAINED_MINUTES`. |
| `ROC_CLEAR_OFFSET_FRAC` | `0.5` | 1 | Fraction of raise rate; conservative anti-flap. |

0 disables the respective offset (acceptance below).

---

## 5. Restart semantics

`_active_hazards` is a plain dict in `__init__` (safety.py:976). It is NOT persisted
(no save/restore in `async_teardown` safety.py:3086-3119 — the save calls are for
rate baselines and the AnomalyDetector only). Therefore: **a restart has always
"cleared" the dict** (that is literally the current workaround users rely on). This
cycle changes NO restart semantics — the dict is still ephemeral.

Boot-transient case: at boot, state_change events for every sensor fire as entities
hydrate. For sensors starting in-range (the common case) the new clear branch sees
"key not in `_active_hazards`" → no-op, correct. For sensors starting in-hazard,
the raise path fires exactly once (dedup prevents re-fire) and that is unchanged.
No boot-time clear noise is introduced.

The existing `_evaluate_sensor_on_recovery` (safety.py:1559-1603, v3.21.0 D3) already
routes recovery from `unavailable` → re-call the handler synchronously; because the
new clear logic lives inside those handlers, recovery-time clears Just Work and need
NO separate wiring.

---

## 6. Tier classification

**Tier 2** (2 framing-disjoint reviews + live validation + README write-back).

Justification: this changes the safety-coordinator hazard lifecycle (a trust surface
consumed by HVAC, energy, security, music, NM, dashboards). It is regression-prone
in the "could spam NM" shape — but the blast radius is contained:
- No new signal, no new consumer, no shared primitive outside safety.py.
- No DB schema change.
- No cross-coordinator contract change (receivers of `SIGNAL_SAFETY_HAZARD` see no
  new payload shape; the "cleared" direction is still polled via
  `is_hazard_active`).

That is below the Tier 2-DB default bar (no DAO change, no payload reshape, no
≥3-caller migration). The two framings are:

- **Review A — correctness + edge cases.** Each hazard type's clear branch; the
  hysteresis arithmetic; `_classify_severity` asymmetry for FREEZE vs OVERHEAT; the
  min-hold timer reset on fall-back; interaction with junk-floor plausibility guard.
- **Review B — anti-flap + cross-coordinator ripple.** Oscillating-sensor scenario
  (NM re-fire storm?), the dedup/clear/raise ordering, HVAC/energy/security
  receivers of `SIGNAL_SAFETY_HAZARD` after a clear→re-raise cycle, boot-transient,
  restart (dict re-initialized), zone-chip consistency (should become MORE
  consistent with the house tile, not less).

If Review A or B surfaces a trust-hierarchy ripple we missed, elevate to Tier 2-DB
(three framings) before deploy — Standing Policy per CLAUDE.md.

---

## 7. Deliverables + acceptance criteria

### D1 — Temperature clear branch (FREEZE_RISK + OVERHEAT) with hysteresis + min-hold
- **Verify:** given a sensor that fired FREEZE_RISK LOW at 44°F, writing 48.5°F for
  ≥ 5 min clears `freeze_risk:<loc>` from `_active_hazards` and
  `get_safety_status()` returns "normal" (if that was the only hazard).
- **Verify:** writing 46°F (inside offset band) for 5 min does NOT clear.
- **Verify (anti-flap):** oscillating 44.5↔46.0 at 10 s cadence fires exactly ONE
  `SIGNAL_SAFETY_HAZARD` over 10 min (the initial raise); no re-fire.
- **Test:** `test_safety_freeze_clear_on_recovery_with_hysteresis`,
  `test_safety_overheat_clear_on_recovery_with_hysteresis`,
  `test_safety_temp_clear_blocked_inside_offset_band`,
  `test_safety_temp_clear_min_hold_not_elapsed`,
  `test_safety_temp_clear_no_flap_under_oscillation`.
- **Live:** post-deploy, `sensor.ura_safety_coordinator_safety_status` transitions
  to "normal" within `HAZARD_MIN_HOLD_S + 60s` of the physical sensor returning to
  in-range, with no new NM pages in that window.

### D2 — Humidity clear branch (HIGH_HUMIDITY sustained + swing + LOW_HUMIDITY)
- **Verify:** HIGH_HUMIDITY MEDIUM raised at 86% in a "normal" room; sensor returns
  to 74% (`low - OFFSET = 78 - 3 = 75`, so 74 < 75) for ≥ 5 min → key popped,
  `_humidity_above_since`/`_humidity_hazard_fired` reset (unchanged by this cycle),
  status returns to "normal".
- **Verify:** at 77% (inside offset band) key is retained.
- **Verify:** LOW_HUMIDITY MEDIUM at 24%; return to 34% for 5 min clears key.
- **Verify:** reading below `HUMIDITY_PLAUSIBLE_MIN_PCT` (junk-floor branch) neither
  raises nor clears — the plausibility guard precedes the clear block.
- **Test:** `test_safety_high_humidity_clear_on_recovery_with_hysteresis`,
  `test_safety_high_humidity_swing_clear_shares_key`,
  `test_safety_low_humidity_clear_on_recovery_with_hysteresis`,
  `test_safety_humidity_clear_ignored_below_plausibility_floor` (requires junk-floor
  branch merged first).
- **Live:** replay the Study A episode class — if any humidity hazard appears, it
  must clear within the hold window of the sensor returning in-range.

### D3 — FLOODING key cleanup
- **Verify:** last leak sensor goes off → `_active_leak_sensors` empty → any
  `flooding:<loc>` keys are popped; sustained-single-sensor FLOODING keys are also
  reconciled when the specific sensor dries.
- **Test:** `test_safety_flooding_clears_when_last_leak_sensor_dries`.
- **Live:** test via `test_safety_hazard` service in observation mode first; verify
  the dashboard tile returns to "normal".

### D4 — ROC hazard clear
- **Verify:** after a rate hazard entry, 2 consecutive 30-min windows with rate
  magnitude below `(raise_rate × (1 - ROC_CLEAR_OFFSET_FRAC))` pop the key.
- **Test:** `test_safety_roc_clear_after_quiet_window`.
- **Live:** low priority — ROC fires rarely; validate in-suite only, note
  deferral if no organic ROC fires in validation window.

### D5 — Doc write-back
- Update `docs/Coordinator/SAFETY_COORDINATOR.md` with the lifecycle gap, the new
  constants, and the hysteresis invariant.
- Update `docs/QUALITY_CONTEXT.md` with a candidate bug class
  "Raised-but-never-cleared trust value" if one does not already exist.

---

## 8. Non-goals (explicit)

1. **No new `SIGNAL_SAFETY_HAZARD_CLEARED` dispatch.** NM already handles clear via
   `is_hazard_active` polling; adding a push signal is scope creep (§0 Prior-art,
   Marginal-benefit §9). Park under `SAFETY-HAZARD-CLEARED-SIGNAL-1` with the
   revival trigger "a consumer wants immediate push semantics on clear".
2. **No persistence of `_active_hazards` across restart.** Restart continues to
   clear the dict; this cycle only closes the in-process clear gap.
3. **No changes to raise thresholds** or to the junk-floor plausibility floor.
4. **No live-tunable Number entities** for the new offsets — they are safety-
   semantics bounds and belong at rung 1 (module constants).
5. **No changes to zone-chip projection code.** The projection reads live state and
   is already consistent; this cycle makes the house-tile match the chip, not
   vice-versa.

---

## 9. Marginal-benefit note

Decomposition: the SIMPLEST version is "pop the key when `_classify_severity` returns
None" (symmetric to `_handle_numeric_hazard`). That captures ~80% of the benefit —
the stuck tile clears. Marginal benefit of adding hysteresis + min-hold is the
anti-flap storm defense (NM pages). Marginal ingredient risk: 2 extra constants + 1
timer dict (`_active_above_since`), all local to `safety.py`, zero cross-coordinator
new paths. The anti-flap defense is cheap and pays for itself the first time a
sensor dithers at threshold; worth paying. Keep.

---

## 10. Plan completion / what we are explicitly deferring

- Push "cleared" signal — PARKED (new card: `SAFETY-HAZARD-CLEARED-SIGNAL-1`).
- Persistence of `_active_hazards` across restart — not needed; restart still
  works and now so does recovery.
- Live-tunable Number entities for the offsets — rejected per Numbers-Get-Knobs §4-F.
- Backfill of a one-time clear for hazards already stuck in the live instance at
  deploy time: HA restart (deploy script does one) will clear them; no code path
  needed.
