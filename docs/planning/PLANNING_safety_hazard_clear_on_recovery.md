# PLANNING — SAFETY-HAZARD-NEVER-CLEARS-1

Card: SAFETY-HAZARD-NEVER-CLEARS-1 ("humidity / freeze / overheat hazards never clear
until HA restart").

**Tier: Tier 2-DB** (elevated from Tier 2 in rev 2 — see §6). Three framing-disjoint
reviews + live validation + README write-back.

Stacking: the upstream branch `feature/safety-humidity-junk-floor`
(SAFETY-HUMIDITY-JUNK-READING-1) is now **merged to develop** (reviewer confirmed
2026-10-14, base `develop @ bfbfb53f7`). All file:line citations in this plan are
against **develop** and match the previously-cited "branch" lines (no drift).
Reviewers verify by:
`git -C /Users/okosisi/Code/universal-room-automation show develop:custom_components/universal_room_automation/domain_coordinators/safety.py`.

---

## Rev 4 — review resolution (operator approved widened scope 2026-10-14)

Resolves every finding in
`docs/reviews/code-review/plan_safety_hazard_clear_rev3_review.md` (verdict
FIX-REQUIRED: 1 HIGH, 4 MED, 1 LOW).

| Rev-3 finding | Severity | Resolution section | Scope |
|---|---|---|---|
| HIGH-1 — hold suppresses re-raise response for life-safety hazards (leak re-wet / CO relapse inside pending-clear window takes the `not is_new` early return and skips valve-close / HIGH response) | HIGH | §4-0-rev4 (life-safety raise-during-pending-clear is treated as NEW: full response re-runs; valve close re-fires; notifications stay throttled by existing `SafetyDeduplicator` at `safety.py:900`) + §4-invariant-rev4 (invariant adds "a real smoke/CO/leak response is NEVER suppressed by the clear-hold machinery") + D1/D6/D8 new tests `test_safety_leak_rewet_during_hold_reissues_response`, `test_safety_co_relapse_during_hold_reissues_response` | IN-SCOPE |
| MED-2 — §3 miscalls NM `_re_evaluate_hazard` a "Trust" consumer of `_active_hazards`; it is already inert (safety's `NotificationAction` at `:2413-2420` sets no `hazard_type`/`location` → `manager.py:1079` passes None → NM calls `is_hazard_active("", "")` at `notification_manager.py:3039`, which always returns False); the §4-G exact-match rewrite can't suppress a re-page because nothing reaches it today | MED | §3-rev4 (consumer map corrected: NM `_re_evaluate_hazard` is INERT today, Display-at-best — NOT a trust consumer); D4 NM-consumer verify dropped; new card **SAFETY-NM-REFIRE-UNWIRED** (wire `hazard_type`/`location` into the `NotificationAction`, verify NM round-trip) listed in §10 — **OUT OF SCOPE for this cycle** | OUT (card only) |
| MED-3 — ROC clear criterion undefined in z-score mode (`check_thresholds :727` raises by z-score once baselined, so there is no fixed `raise_rate`); and §4-H-rev3's "stale rate forever" rationale is wrong — `get_rate` returns None with no samples in the window (`safety.py:676-689`), not a stale value | MED | §2a-rev4 + §4-E-rev4 + §4-H-rev4: Hazard carries the raise-time `raise_rate` AND `raise_z` (whichever triggered); clear fires when the recomputed rate is **None** (no samples in window — the real backstop; corrects the "stale rate forever" rationale) **OR** below the fractional threshold against the stored raise-rate **OR** z-score below `(raise_z × (1 − ROC_CLEAR_OFFSET_FRAC))` in z-score mode. `ROC_STALE_SAMPLE_S` becomes a safety-net second check (bounded quiet). Rationale in §4-H-rev4 rewritten to reflect the actual `get_rate` None-return semantics | IN-SCOPE |
| MED-4 — §4-J introduces `_sensor_unavailable_since` but has no writer; `_process_sensor` returns early on unavailable at `:1538`, so the sweep can't observe it from inside the handler | MED | §4-J-rev4 (two writers, named): (a) stamp at the unavailable early-return at **`safety.py:1538`** when the sensor was previously in a raising-set for any `_active_hazards` key; (b) sweep re-polls `hass.states.get(sensor_id)` each tick as a backstop for sensors that disappeared without a state_changed event (e.g. entity removal). First real reading clears the entry via the existing `_evaluate_sensor_on_recovery` path. | IN-SCOPE |
| MED-5 — the known failing test (`test_tvoc_detection`) is at `quality/tests/test_safety_coordinator.py:804`, NOT `test_restart_safety_doctrine_1.py` as earlier wording implied; the defect is **test-only** (test seeds naive `datetime.utcnow()`, production already uses aware `dt_util.utcnow()` at `:1924`) | MED | §7-D6-rev4 adds the test-only fix: swap naive `datetime.utcnow()` → `dt_util.utcnow()` at `quality/tests/test_safety_coordinator.py:804`. **No production change.** | IN-SCOPE (test only) |
| LOW — §4-site-table doesn't name SMOKE at the `:1773` clear site | LOW | §4-site-table row 1 names SMOKE explicitly (SMOKE + WATER_LEAK share the binary clear) | IN-SCOPE |

**Falsifiable invariant addendum (life-safety priority).** Added to
§4-invariant-rev4: *under no reachable configuration does the clear-hold machinery
suppress a real `SMOKE`, `CARBON_MONOXIDE`, or `WATER_LEAK` response action* (valve
close, siren, HIGH-severity NM page). The notification cadence remains throttled by
the existing `SafetyDeduplicator` at `safety.py:900` — this plan does not add a second
throttle on top of that for life-safety hazards.

---

## Rev 3 — re-review fixes (map)

All file:line below are against the merged branch per the command above. Develop
working-tree equivalents verified via `Grep`: branch adds ~+25-30 lines in the
`_handle_numeric_hazard` region and ~+40 lines by `_async_periodic_check`.

| Finding | Fix section |
|---|---|
| NEW-H1 (HIGH) 2nd CO2 clear site — log-only rung at `safety.py:1895-1906` pops `co2:<loc>` immediately for `co2_low ≤ v < co2_medium`; the planned CO2 clear point `1500−100=1400` sits INSIDE that band so the immediate pop wins (repro: `1510 raise → 1490 log-only pop → 1510 raise`). | §4-I-rev3 (route through `_record_sensor_recovery` + hysteresis gate) + §4-site-table (every pop/del/clear site enumerated) |
| NEW-H2 (HIGH) `:roc` keys only arm `_hazard_clear_pending` on state_change; a spike-then-constant sensor fires nothing further → stuck forever | §4-H-rev3 (sweep recomputes 30-min rate from sample window; stale-sample backstop) — **superseded by §4-H-rev4** (recompute returns None with no samples; §4-H-rev4 uses None as primary clear signal + stale-sample backstop) + new knob `ROC_STALE_SAMPLE_S` + D5 extended |
| HIGH-2 ordering — register sensor + cancel pending clear BEFORE the `not is_new` early return at `~:2325-2330` | §4-0-rev3 (ordering made explicit) + D1 extra test. **Rev 4 refines:** for SMOKE/CO/WATER_LEAK, a raise arriving during pending-clear is also treated as NEW (full response re-runs). |
| Dead / removed / unavailable raising sensors — per-type policy | §4-J (new) + new knob `SENSOR_UNAVAILABLE_WINDOW_S` + D8 (new). **Rev 4 names the two writers.** |
| Invariant must survive hysteresis-band readings as legitimate hold (don't let reviewer D falsify it with intended behaviour) | §4-invariant-rev3 → **§4-invariant-rev4** (adds life-safety-response-never-suppressed clause) |
| Sweep sits OUTSIDE flooding `if self._active_leak_sensors` guard | §4-H-rev3 (explicit position); registration `:1222-1225`, body `:2696` |
| Stale `:1917-1923` citation → real severity-None pop `:1942-1950`; §0 line 45 cite `:1904-1946` → `:1942-1950` (and NEW-H1 site `:1895-1906`) | §0-rev3 (citation fixes) + §4-I-rev3 |
| LOW: `clear_hazard` (`~:2770-2775`) has zero callers, builds key w/o `:roc`, doesn't pop new dicts | §4-K (align minimally — KEEP+WIRE, not DELETE) |
| LOW: README note — `binary_sensor.<room>_air_quality`, `safety_alert`, hazard count linger up to `HAZARD_MIN_HOLD_S` longer | §7-D7-rev3 bullet |
| Pop-site completeness (Bug Class #53) — every write enumerated | §4-site-table |

### §4-site-table — every `_active_hazards` write on develop + post-cycle handling

| Site (develop line) | Today | After this cycle |
|---|---|---|
| `_handle_binary_hazard` **SMOKE + WATER_LEAK** clear `~:1773` (rev 4 names SMOKE explicitly — both binary types share this clear path) | pop `smoke:<loc>` / `water_leak:<loc>` + discard from `_active_leak_sensors` (leak only) | route through `_record_sensor_recovery` + hold `HAZARD_MIN_HOLD_S` (no hysteresis — binary); matches ladder (§4-D). **Rev 4:** a raise arriving while `_hazard_clear_pending[key]` is set is treated as NEW (§4-0-rev4) — valve close / HIGH response re-runs. |
| `_handle_numeric_hazard` **CO2 log-only rung pop** `:1895-1906` (NEW-H1) | immediate pop `high_co2:<loc>` when `co2_low ≤ v < co2_medium` | `v ≤ co2_medium − CO2_CLEAR_OFFSET_PPM` (= 1400) → `_record_sensor_recovery(key, eid, now)`; `1400 < v < 1500` → `_record_sensor_relapse(key, eid)` (inside hysteresis band, still contributing); logging preserved; pop happens only through `_try_clear_if_quiet`. (§4-I-rev3) |
| `_handle_numeric_hazard` **severity-None pop** `:1942-1950` (was mis-cited `:1917-1923`) | pop + pop occurrences + `_notify_entity_update` | replaced by `_record_sensor_recovery` + per-type offset gate (§4-I-rev3). **Rev 4:** CARBON_MONOXIDE relapse during pending-clear routes through §4-0-rev4 (full response re-runs). |
| `_respond_to_hazard` raise `~:2315-2330` | `_active_hazards[key] = hazard`; early return if `not is_new` | register sensor_id into `_hazard_raising_sensors[key]` + `_hazard_clear_pending.pop(key, None)` **BEFORE** the `not is_new` early return (§4-0-rev3); **rev 4:** for SMOKE/CO/WATER_LEAK, if `_hazard_clear_pending[key]` was set at entry, override `is_new=True` so the HIGH response re-runs (§4-0-rev4). |
| **Periodic sweep (new) `_async_periodic_check` body `:2696`** | — | pop all three dicts for keys with empty raising-set + elapsed hold; also recompute `:roc` rate and apply None-return + stale-sample backstop (§4-H-rev4); **positioned OUTSIDE the `if self._active_leak_sensors:` flooding guard** (§4-H-rev3) |
| `clear_hazard(type, loc)` `~:2770-2775` | pops `{type}:{loc}` only; zero production callers (grep: only self-definition) | §4-K: KEEP+WIRE — also pop `{type}:{loc}:roc`, `_hazard_raising_sensors[*]`, `_hazard_clear_pending[*]`. |
| `clear_all_hazards()` `~:2780+` | `_active_hazards.clear()` | also `.clear()` `_hazard_raising_sensors`, `_hazard_clear_pending`, `_sensor_unavailable_since` (§5) |
| `async_teardown` dict-clears `:3140-3160` | existing | add the three new dicts (§5) |

### §4-invariant-rev4 — hysteresis-safe + life-safety-priority falsifiable invariant

Two conjoint invariants, both must hold at all times:

**(I1) Residency invariant.** For every key `K` in `_active_hazards`, at ALL times
AT LEAST ONE of:

- **(a)** at least one sensor in `_hazard_raising_sensors[K]` currently reads **worse than
  the CLEAR line** (not the raise line) — i.e. for OVERHEAT, `v > raise − OFFSET`
  interpreted as "has not yet crossed the clear line"; for FREEZE_RISK, `v < raise + OFFSET`;
  for HIGH_HUMIDITY, `v > low − OFFSET`; for LOW_HUMIDITY, `v < low + OFFSET`; for
  HIGH_CO2/TVOC/CO, `v > medium − OFFSET`. **A reading inside the hysteresis band is on
  neither side of the invariant — it is a legitimate hold, not a violation.**
- **(b)** all sensors in `_hazard_raising_sensors[K]` read on the clear side but
  `now − _hazard_clear_pending[K] < HAZARD_MIN_HOLD_S`.
- **(c)** K ends in `:roc` AND one of:
  (c1) recomputed rate from the detector's sample window is **not None** AND
  magnitude ≥ `stored_raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)` for at least one
  contributing sensor; OR
  (c2) recomputed z-score ≥ `stored_raise_z × (1 − ROC_CLEAR_OFFSET_FRAC)` (z-score
  mode); OR
  (c3) any contributing sensor had a sample within the last `ROC_STALE_SAMPLE_S`
  (quiet-but-not-yet-stale backstop).

**(I2) Life-safety response invariant (rev 4).** Under NO reachable configuration
does the clear-hold machinery of this plan suppress a real `SMOKE`,
`CARBON_MONOXIDE`, or `WATER_LEAK` response action (valve close `:2650-2661`, siren,
HIGH-severity NM dispatch). Specifically: whenever `_respond_to_hazard` is entered
for one of those three types AND `_hazard_clear_pending[key]` is non-None at entry,
`is_new` is forced True and the full response path runs. Notification cadence stays
throttled by the existing `SafetyDeduplicator` at `safety.py:900`; this plan adds no
second throttle on top.

Reviewer D cannot falsify (I1-a) with an in-band reading because (a) explicitly
covers it. Negation set:
(1) all sensors on the clear side for ≥ HOLD and K still present → FAIL;
(2) oscillating sensor at threshold±ε fires > 1 `SIGNAL_SAFETY_HAZARD` per 10 min → FAIL;
(3) `:roc` key present AND recomputed rate is None (no samples in window) AND no
sample within `ROC_STALE_SAMPLE_S` → FAIL (clear must have fired);
(4) `_respond_to_hazard` with `is_new=False` returns without registering sensor_id
into the raising set → FAIL (first-raiser recovers → key wrongly pops);
(5) **(rev 4)** `_respond_to_hazard` for SMOKE/CO/WATER_LEAK with `is_new=False` AND
`_hazard_clear_pending[key]` set at entry AND HIGH response did NOT run → FAIL (I2).

### §4-0-rev4 — raise ordering + life-safety priority (HIGH-2 + rev-4 HIGH-1)

In `_respond_to_hazard` (`~:2315`), BEFORE the existing dedup/early-return at
`~:2325-2330`:

```
key = f"{hazard.type.value}:{hazard.location}" + (":roc" if hazard.from_roc else "")
self._hazard_raising_sensors.setdefault(key, set()).add(hazard.sensor_id)
had_pending_clear = key in self._hazard_clear_pending
self._hazard_clear_pending.pop(key, None)
existing = self._active_hazards.get(key)
is_new = existing is None or existing.severity != hazard.severity

# Rev 4 — life-safety priority: a re-wet / relapse during pending-clear MUST
# re-run the full HIGH response (valve close, siren, HIGH NM page). The
# SafetyDeduplicator at :900 continues to govern NM cadence.
if had_pending_clear and hazard.type in (
    HazardType.SMOKE,
    HazardType.CARBON_MONOXIDE,
    HazardType.WATER_LEAK,
):
    is_new = True

# ... existing path continues ...
if not is_new:
    return []   # early return — but set membership + pending-cancel ALREADY DONE
```

Explicit tests (D1 / D6 / D8 add):
- Two sensors A + B, same loc, same severity. A raises (`is_new=True`); B raises
  SAME severity (`is_new=False`, early return). After B's raise,
  `_hazard_raising_sensors[key] == {A, B}`. A returns in-range → key STAYS. B returns
  + hold elapsed → key pops. (D1 — unchanged from rev 3.)
- **Rev 4 HIGH-1 — leak re-wet during pending-clear:** raise WATER_LEAK (valve
  close observed via spy); leak sensor dries → `_hazard_clear_pending` armed; within
  the hold window, leak re-wets → assert valve-close response **runs again**;
  `SafetyDeduplicator` governs NM pages (not this plan).
- **Rev 4 HIGH-1 — CO relapse during pending-clear:** raise CARBON_MONOXIDE HIGH;
  value dips through CO offset → `_hazard_clear_pending` armed; within hold, value
  spikes back above raise → HIGH response path runs again.

### §4-H-rev4 — periodic sweep: ROC clear uses None-return + stored raise rate/z (MED-3)

**Position + non-`:roc` keys** — unchanged from §4-H-rev3 (sweep after flooding
block closes, outside the `if self._active_leak_sensors:` guard; registration at
`~:1222-1225`; body at `~:2696`).

**`:roc` keys — corrected clear criterion (MED-3).** The rate detector raises in
two modes:
1. Threshold mode — fixed `raise_rate` per rate type (table ≈ `:600-620`).
2. **z-score mode** — once baselined, `check_thresholds :727` raises when the
   z-score exceeds the configured z threshold; no fixed `raise_rate`.

Therefore, at raise time, the Hazard carries BOTH the triggering rate magnitude
AND the triggering z-score (whichever branch fired). Store on the Hazard dataclass
as `raise_rate: float | None` and `raise_z: float | None` (one of the two is
non-None depending on the branch).

For each contributing sensor_id in the sweep:

1. Query `_rate_detector.get_rate(sensor_id, rate_type, window)` from the stored
   sample window (`safety.py:676-689`).
2. **If `get_rate` returns None** (no samples inside the window — the real
   semantics; corrects rev-3's "stale rate forever" rationale): treat as implicit
   recovery → `_record_sensor_recovery(key, sensor_id, now)`.
3. Else if the stored `raise_rate` is non-None AND
   `|recomputed_rate| < stored_raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)` →
   `_record_sensor_recovery(...)`.
4. Else if the stored `raise_z` is non-None AND the detector exposes a current
   z-score (via a small accessor on the baselined window) AND
   `|current_z| < stored_raise_z × (1 − ROC_CLEAR_OFFSET_FRAC)` →
   `_record_sensor_recovery(...)`.
5. Else if `now − last_sample_time ≥ ROC_STALE_SAMPLE_S` → `_record_sensor_recovery(...)`
   (safety-net backstop; redundant with step 2 whenever step 2 fires because
   `get_rate` goes None, but kept as a bounded-quiet guarantee).
6. Then standard set-empty + hold-elapsed check in `_try_clear_if_quiet`; pop all
   three dicts + fire `_notify_entity_update()`.

**Why None is the primary clear signal, not stale-rate.** `get_rate` at
`safety.py:676-689` returns None when the sample window is empty. Rev 3 described
this as "the recompute returns the stale rate forever" — that was wrong. The real
semantics is `None`, which is cleanly interpretable as "no evidence of ongoing
rate hazard" and is the correct primary clear trigger. `ROC_STALE_SAMPLE_S` is
retained as a safety-net second check for cases where the detector buffers an
old sample inside the window beyond the typical sample cadence.

**Unavailable contributors — see §4-J-rev4.**

### §4-I-rev3 — CO2 / TVOC / CO: BOTH pop sites routed through recovery

(Unchanged from rev 3; see rev-3 section below.) Rev 4 adds the §4-0-rev4
life-safety override for CARBON_MONOXIDE — a relapse during pending-clear
re-runs the HIGH response.

### §4-J-rev4 — Dead / removed / unavailable raising sensors (writers named per MED-4)

Per-type policy evaluated in the periodic sweep (unchanged from rev 3):

| Hazard type | On sensor_id unavailable / removed |
|---|---|
| `SMOKE`, `CARBON_MONOXIDE`, `WATER_LEAK` | **fail-safe keep** — sensor stays in `_hazard_raising_sensors[key]`; key does NOT clear from this cause; log once per transition. A missing life-safety signal is treated as unresolved. |
| `HIGH_HUMIDITY`, `LOW_HUMIDITY`, `FREEZE_RISK`, `OVERHEAT`, `HIGH_CO2`, `HIGH_TVOC`, `HVAC_FAILURE` | **drop after `SENSOR_UNAVAILABLE_WINDOW_S`** — if `hass.states.get(sensor_id)` is None/unavailable continuously for the window, discard from the raising-set and run the set-empty + hold check. |

**Where `_sensor_unavailable_since` is written (MED-4).** Two writers:

1. **Primary — stamp at the state-handler unavailable early return at `safety.py:1538`.**
   `_process_sensor` returns early when the state is unavailable; before that
   return, if `sensor_id` currently appears in any `_hazard_raising_sensors[*]`
   and `_sensor_unavailable_since` has no entry for it, stamp
   `_sensor_unavailable_since[sensor_id] = now`.
2. **Backstop — the periodic sweep polls `hass.states.get(sensor_id)` once per
   tick** for every sensor currently in any raising-set. Entities that disappear
   without emitting a final state_changed (e.g. config-entry removal, HA restart
   mid-mount) are caught here. If the state is None or `STATE_UNAVAILABLE` and
   `_sensor_unavailable_since` has no entry for that sensor_id, stamp `now`.

The entry is cleared on the next real value: `_evaluate_sensor_on_recovery`
(unavailable→value) already re-enters the hazard handlers, and those handlers call
`_record_sensor_recovery` / `_record_sensor_relapse` which both discard
`_sensor_unavailable_since[sensor_id]` as a side effect.

Implementation: new `self._sensor_unavailable_since: dict[str, datetime]` tracks
per-sensor first-unavailable time. Teardown + `clear_all_hazards` clear it.

Rung-1 constants:

| Constant | Default | Why |
|---|---|---|
| `SENSOR_UNAVAILABLE_WINDOW_S` | 900 (15 min) | Longer than any legitimate transient (Zigbee/BLE drop, Wi-Fi hiccup) but short enough not to warehouse stale hazards indefinitely. |
| `ROC_STALE_SAMPLE_S` | 900 (15 min) | NEW-H2 safety-net second check (primary clear trigger is `get_rate` returning None — §4-H-rev4). Longer than one periodic tick (1 min); shorter than any legitimate idle for a sensor whose rate was recently extreme. |

### §4-K — `clear_hazard` manual API (LOW)

`clear_hazard(type, loc)` at `~:2770-2775` has **zero production callers** (verified by
`Grep "clear_hazard"` across `custom_components/universal_room_automation` → only the
definition itself). Decision: **KEEP + WIRE** (not DELETE — per Supersession three-bucket;
not a footgun, small to maintain, a plausible future service-call surface). Update it to:

- build both `f"{type}:{loc}"` AND `f"{type}:{loc}:roc"` keys;
- pop both from `_active_hazards`, `_hazard_occurrences`, `_hazard_raising_sensors`,
  `_hazard_clear_pending`;
- clear any `_sensor_unavailable_since` entries whose sensor_id was in the raising-set.

`clear_all_hazards()` at `~:2780+` likewise `.clear()`s all four new dicts.

### §0-rev3 — code-read citations updated

- `_handle_numeric_hazard` CO2/TVOC/CO: **severity-None pop at `:1942-1950`** (NOT `:1917-1923`);
  **CO2 log-only rung pop at `:1895-1906`** (NEW-H1 site introduced by the junk-floor branch).
- Line 45 of the §0 code-reads list is corrected accordingly (develop offsets:
  severity-None `:1915-1923`, log-only `:1870-1878`).
- `_async_periodic_check` registration at `~:1222-1225` (added — body cite `:2696` unchanged
  and correct).
- `is_hazard_active` at `:3112` correct (develop `:3074`).
- `clear_hazard` at `~:2770-2775` correct (develop `:2732`); zero callers confirmed.
- `_respond_to_hazard` early return at `~:2325-2330` (added — was ambiguous "`:2315-2325`").

### §7-D7-rev3 — README operator-visible note

Append to D7 doc-writeback:

> **Operator-visible timing change (soak extension).**
> `binary_sensor.<room>_air_quality`, `binary_sensor.<room>_safety_alert`, and the
> `sensor.ura_safety_active_hazards` count will stay ON for up to `HAZARD_MIN_HOLD_S`
> (default 300s) after the physical sensor returns to the clear band. ROC-raised
> hazards extend by up to `ROC_STALE_SAMPLE_S + HAZARD_MIN_HOLD_S` (default 1200s)
> when the originating sensor goes silent after a spike. Any operator automation keyed
> on the off-transition of these entities must tolerate the delay. Record under
> "Operator-visible changes" in `README_v<version>.md` and in
> `docs/Coordinator/SAFETY_COORDINATOR.md`.
>
> **Life-safety priority (rev 4):** SMOKE / CARBON_MONOXIDE / WATER_LEAK response
> actions (valve close, siren, HIGH NM page) are NEVER suppressed by the clear-hold
> machinery. A re-wet / relapse during the pending-clear window re-runs the full
> response path; NM page cadence remains governed by the existing
> `SafetyDeduplicator` at `safety.py:900`.

### D8 — Unavailable / removed raising sensor policy (new)

- **Verify (life-safety keep):** raise SMOKE at loc X via sensor A; set A unavailable for
  30 min; key STILL present; `is_hazard_active("smoke","x")` returns True; no clear signal.
- **Verify (comfort drop):** raise HIGH_HUMIDITY via A + B; set A unavailable for
  `SENSOR_UNAVAILABLE_WINDOW_S + 60s`; A dropped from `_hazard_raising_sensors[key]`;
  if B is in-range and hold elapsed, key pops; else stays until B satisfies.
- **Verify (recovery before window):** A unavailable 10 min then returns in-range → treated
  normally via `_record_sensor_recovery`; `_sensor_unavailable_since[A]` cleared;
  no spurious drop.
- **Verify (writer at :1538, rev 4):** sensor A contributes to a HIGH_HUMIDITY key; A
  transitions to `unavailable` → state handler early-returns at `:1538` → assert
  `_sensor_unavailable_since[A]` was stamped.
- **Verify (writer in sweep, rev 4):** sensor B contributes to a HIGH_HUMIDITY key; B's
  entity is removed from the state machine (no state_changed emitted) →
  `hass.states.get("sensor.b")` returns None → next sweep tick stamps
  `_sensor_unavailable_since[B]`.
- **Test:** `test_safety_smoke_keeps_key_when_sensor_unavailable`,
  `test_safety_humidity_drops_contributor_after_unavailable_window`,
  `test_safety_unavailable_contributor_restored_before_window_resumes_normally`,
  `test_safety_unavailable_since_stamped_at_state_handler_early_return`,
  `test_safety_unavailable_since_stamped_by_sweep_when_entity_removed`.

### D1 extra (HIGH-2 ordering + rev-4 life-safety override)

- **Verify (register-before-early-return):** two sensors A + B, same location, same
  severity. A raises (`is_new=True`, A added). B raises SAME severity → early return at
  `~:2325-2330` — **BUT** B must already be in `_hazard_raising_sensors[key]` AND
  `_hazard_clear_pending[key]` cancelled BEFORE the early return. A returns in-range →
  key STAYS. B returns + hold → key pops.
- **Verify (rev 4 — leak re-wet during hold reissues response):** raise WATER_LEAK;
  valve-close observed via spy on `_execute_valve_close` (or the equivalent HIGH
  response hook); leak sensor dries → `_hazard_clear_pending` armed; within
  `HAZARD_MIN_HOLD_S`, leak re-wets → **assert valve-close spy was called a second
  time**; assert `SafetyDeduplicator :900` governs NM page cadence (not this plan).
- **Test:** `test_safety_second_raise_registers_sensor_even_when_not_is_new`,
  `test_safety_leak_rewet_during_hold_reissues_response`.

### D5 extended (NEW-H2 ROC — corrected rev 4)

- **Verify (ROC None-return primary clear, rev 4):** fire ONE
  `temperature_rise_extreme` event raising `overheat:<loc>:roc`; advance HA time by
  `HAZARD_MIN_HOLD_S + 60s` with ZERO new state_changed events on the contributing
  sensor; `get_rate` returns None (empty window) → sweep calls
  `_record_sensor_recovery` → key pops.
- **Verify (ROC stale-sample safety-net, rev 4):** craft a scenario where
  `get_rate` returns a non-None value from an aged in-window sample but
  `now − last_sample_time ≥ ROC_STALE_SAMPLE_S` → sweep clears via the safety-net
  branch.
- **Verify (ROC recompute below fraction):** inject follow-up readings that produce
  a recomputed rate below `stored_raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)`; key
  pops via recompute, not None-return.
- **Verify (ROC z-score mode, rev 4):** baselined window → z-score raise fires with
  `raise_z` stored on Hazard; subsequent samples produce z below
  `stored_raise_z × (1 − ROC_CLEAR_OFFSET_FRAC)` → key pops.
- **Test:** `test_safety_roc_clears_on_get_rate_none`,
  `test_safety_roc_clears_on_stale_sample_safety_net`,
  `test_safety_roc_clears_on_recomputed_rate_below_fraction`,
  `test_safety_roc_clears_on_z_score_below_fraction`.

### Rev 3 knobs — append to §4-F

| Constant | Default | Rung | Why |
|---|---|---|---|
| `ROC_STALE_SAMPLE_S` | 900 | 1 (module const) | NEW-H2 ROC safety-net second check (primary clear is `get_rate` None per §4-H-rev4). |
| `SENSOR_UNAVAILABLE_WINDOW_S` | 900 | 1 (module const) | §4-J-rev4 drop gate (comfort hazards only). |

---

## Rev 2 — plan-review fixes (map)

| Finding | Fix section |
|---|---|
| HIGH-1 (ROC keys collide with binary/type clears) | §2a (ROC key suffix), §4-E, §4-G (consumer sweep: `is_hazard_active`) |
| HIGH-2 (per-sensor clear pops per-location key → storm) | §4-0 (per-key contributor set) + §4-A/B/C updated |
| HIGH-3 (sensor steady-in-range never fires state_change) | §4-H (periodic clear sweep in `_async_periodic_check`) + D5 test |
| MEDIUM-4 (CO2/TVOC/CO flap at threshold — same mechanism) | §4-I (bring into same hysteresis + hold); non-goal removed |
| MEDIUM-5 (humidity clear thresholds + outdoor + 2h window) | §4-B rewritten against resolved per-room thresholds |
| MEDIUM-6 (timer dict lifecycle: set-if-absent, teardown, severity-correct raise ref) | §4-0, §4-A clarifications, §5 teardown list |
| MEDIUM-7 (D4 contradiction MIN_HOLD vs 2×30min) | §7 D4 rewritten |
| MEDIUM-8 (acceptance must discriminate; count signals) | §7 all Ds state SIGNAL_SAFETY_HAZARD count assertions |
| LOW-9 (NM dedup embeds value → no storm protection) | §3 note + §9 pushed to "only defence is hysteresis" |
| LOW-10 (zone-chip reads live state — verify) | §3 verified at `aggregation.py:4560-4620` |
| LOW-11 (stale line citations) | all §§ re-cited against branch |
| Verify-first | §1 rewritten around recorded episodes (Garage A, Study A) |
| Tier elevation | §6 Tier 2-DB with 3 framings |

---

## 0. Institutional context verified

### Code read end-to-end during scoping (develop @ bfbfb53f7)

- `domain_coordinators/safety.py` — hazard pipeline. Key sites:
  - rate thresholds table (temperature_rise/humidity_rise → `WATER_LEAK`, `OVERHEAT`, `HVAC_FAILURE`), approx `:616-631` of the detector block
  - z-score branch at `check_thresholds :727` (rev 4 — MED-3)
  - `get_rate` returns None with no samples in window at `:676-689` (rev 4 — MED-3)
  - state-handler unavailable early return at `:1538` (rev 4 — MED-4 writer site)
  - `_handle_temperature` ≈ `:2036-2088`
  - `_handle_humidity` ≈ `:2091-2301`, normal-ladder resolution ≈ `:2136-2154`, `else` clear tracker ≈ `:2275-2278`, `LOW_HUMIDITY` branch ≈ `:2280-2300`
  - `_handle_numeric_hazard` **CO2 log-only rung pop (NEW-H1) at `:1895-1906`**; **severity-None pop at `:1942-1950`**; `dt_util.utcnow()` call at `:1924` (rev 4 — MED-5)
  - `_handle_binary_hazard` **SMOKE + WATER_LEAK clear** ≈ `:1773` (rev 4 names SMOKE)
  - `_respond_to_hazard` key `type:location` at ≈ `:2315`, dedup/early-return at `~:2325-2330` (rev 3), HIGH valve-close response at `:2650-2661` (rev 4 — HIGH-1 anchor)
  - `_async_periodic_check` registration `~:1222-1225`, body `≈ :2696-2718`
  - `is_hazard_active` substring/endswith matching ≈ `:3112-3126`
  - `clear_hazard` / `clear_all_hazards` ≈ `:2770-2790` — zero production callers
  - `async_teardown` clears dicts ≈ `:3140-3160`
- `domain_coordinators/notification_manager.py`:
  - `_re_evaluate_hazard` at `:3019-3059` — calls `is_hazard_active(hazard_type or "", location or "")` at `:3039`. **Rev 4 — MED-2:** `hazard_type` and `location` arrive as None in current code because safety's `NotificationAction` at `safety.py:2413-2420` does NOT populate them, and `manager.py:1079` passes the Nones through. `is_hazard_active("", "")` always returns False, so NM `_re_evaluate_hazard` is INERT today. §3-rev4 corrects the "Trust" classification; D4's NM-consumer assertion is dropped; wiring is tracked as separate card SAFETY-NM-REFIRE-UNWIRED (out of scope).
  - `_is_deduplicated` at `:3802-3825` — key is `f"{coordinator_id}:{title}:{location or ''}"`. The title embeds the sensor value, so NM dedup gives **zero storm protection** when the value drifts by 1 unit. Hysteresis + hold is the only defence.
  - `SafetyDeduplicator` at `safety.py:900` — rev-4 anchor: the existing throttle that governs NM-page cadence for the life-safety re-run path.
- `aggregation.py:4560-4620` — `ZoneSafetyAlertSensor` reads bands live via
  `safety.resolve_safety_bands()` + `evaluate_zone_chip()`; does NOT read `_active_hazards`.
- `coordinator.py:145,1705` — `SIGNAL_SAFETY_HAZARD` dispatch wiring (unchanged).
- `quality/tests/test_safety_coordinator.py:804` — `test_tvoc_detection` seeds a
  naive `datetime.utcnow()`; production uses aware `dt_util.utcnow()` at
  `safety.py:1924`. Test-only fix in D6-rev4 (rev 4 — MED-5).

### Prior-art scan (REUSE-or-BUILD per piece)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Clear path for humidity in-range | **REUSE** remove idiom from `_handle_numeric_hazard` (`:1942-1950`) + `_handle_binary_hazard` (`:1773`) — pop both `_active_hazards[key]` and `_hazard_occurrences[key]`, then `_notify_entity_update()`. |
| Clear path for temperature in-range | **REUSE** same idiom; clear in the handler on the type-wise negative branch (§4-A). |
| Hysteresis offsets | **NEW** module constants per §4-F. Rung 1. |
| Minimum hold | **NEW** `HAZARD_MIN_HOLD_S` (default 300s) rung 1. |
| Per-key raising-sensor set | **NEW** `self._hazard_raising_sensors: dict[str, set[str]]` — fixes HIGH-2. |
| Per-key hold timer | **NEW** `self._hazard_clear_pending: dict[str, datetime]` — fixes MEDIUM-6. |
| Life-safety override on raise during pending-clear (rev 4) | **NEW** §4-0-rev4 — small branch in `_respond_to_hazard` forces `is_new=True` for SMOKE/CO/WATER_LEAK when `_hazard_clear_pending[key]` was set at entry. No new throttle (SafetyDeduplicator :900 remains). |
| Stored `raise_rate` + `raise_z` on Hazard (rev 4) | **NEW** two fields on the Hazard dataclass; populated by the rate detector at raise time; consumed by §4-H-rev4 sweep. |
| ROC-key suffix | **NEW** rate-raised hazards keyed `type:location:roc`. Fixes HIGH-1. |
| Periodic clear sweep | **NEW** branch inside `_async_periodic_check` at `:2696`. Fixes HIGH-3. |
| ROC None-return primary clear + stale-sample safety-net (rev 4) | **NEW** §4-H-rev4 + `ROC_STALE_SAMPLE_S` constant. Fixes NEW-H2 with correct `get_rate` semantics. |
| Unavailable-contributor policy (rev 3/4) | **NEW** `_sensor_unavailable_since` + `SENSOR_UNAVAILABLE_WINDOW_S`; two named writers at `:1538` + sweep. §4-J-rev4. |
| "Cleared" dispatch signal | **DO NOT ADD** — park `SAFETY-HAZARD-CLEARED-SIGNAL-1`. |
| NM `_re_evaluate_hazard` wiring (hazard_type + location into NotificationAction) | **OUT OF SCOPE (rev 4)** — new card SAFETY-NM-REFIRE-UNWIRED. |

### Prior planning docs consulted

- `docs/planning/PLANNING_freeze_safety_range_shift.md` — freeze tuning only.
- `docs/planning/PLANNING_zone_safety_alert_split.md` — zone-chip; LOW-10 reads live state.
- `docs/planning/AUDIT_restart_safety_classification.md` — `_active_hazards` is ephemeral.
- `docs/planning/kanban.data.yaml` — SAFETY-HUMIDITY-JUNK-READING-1 upstream (merged).

### Design docs / coordinator manual

- `docs/Coordinator/SAFETY_COORDINATOR.md` — lifecycle gap not called out; updated in D6/D7.

### Config-first check

No live knob reaches `_active_hazards` removal. Code change required. New offsets land as
rung-1 module constants per Numbers-Get-Knobs.

---

## 1. VERIFY FIRST — rewritten around recorded episodes (as of 2026-10-01 03:05Z)

**Live status is now normal** (no stuck hazard this instant). The card is not
discredited — it was proven by the recorded episodes below. The build gate is
"recorded episodes exist AND match the mechanism described in §2," not "a hazard is
stuck right now."

### Recorded episodes (ground truth)

```bash
ssh ha "sqlite3 -readonly /config/universal_room_automation/data/universal_room_automation.db \
  'SELECT hazard_type, severity, location, sensor_id,
          datetime(detected_at,\"unixepoch\",\"localtime\") AS t_start,
          (cleared_at - detected_at)/60.0 AS mins
     FROM hazard_log
    WHERE detected_at >= strftime(\"%s\",\"now\",\"-7 days\")
    ORDER BY mins DESC LIMIT 20;'"
```

Known episodes to replay in acceptance:

| Episode | Sensor | Value | Latched for | Started |
|---|---|---|---|---|
| LOW_HUMIDITY Garage A | `sensor.occupancy_lux_temp_humidity_garagea_humidity` | 30.0 (exactly at threshold) | 759 min | 2026-09-26 05:12 local |
| LOW_HUMIDITY Study A | (study-a humidity sensor) | 0.0 (junk — see upstream branch) | 659 min | 2026-09-27 04:35 local |
| HIGH_CO2 MEDIUM Study A flap | study-a CO2 | 1500-1502 ppm | ~20 raises in 7 min | 2026-09-29 00:04-00:11 local |

**Discriminator.** The build ships if, replaying any of the above sensor traces against
the modified handler (unit test fixtures), the resulting `_active_hazards` dict is
empty after the sensor returns to in-range for ≥ `HAZARD_MIN_HOLD_S`, AND the number
of `SIGNAL_SAFETY_HAZARD` dispatches across the flap window is exactly 1 (not ~20).

---

## 2. Hazard-type table (how raised, how cleared TODAY — develop lines)

| Hazard type | Raise site | Clear site TODAY | Gap? |
|---|---|---|---|
| SMOKE (binary) | `_handle_binary_hazard` | binary clear ≈ `:1773` (shared with WATER_LEAK — rev 4 names SMOKE) | OK |
| WATER_LEAK (binary) | `_handle_binary_hazard` | binary clear ≈ `:1773` + `_leak_start_times.pop` | OK (rev 4 — re-wet during pending-clear is handled via §4-0-rev4 life-safety override) |
| FLOODING (escalated) | `_check_flooding_escalation` + `_async_periodic_check :2696` | Implicit via leak clear; **key `flooding:<loc>` not explicitly popped** | MINOR GAP (§4-D) |
| CARBON_MONOXIDE / HIGH_CO2 / HIGH_TVOC (numeric) | `_handle_numeric_hazard` | **two** pop sites: severity-None `:1942-1950` AND CO2 log-only rung `:1895-1906` (NEW-H1) — **no hysteresis, no hold** → flaps at threshold AND the log-only pop beats hysteresis for CO2 | **PRIMARY GAP** (§4-I-rev3; MEDIUM-4; NEW-H1); CO relapse during pending-clear handled by §4-0-rev4 (rev 4 — HIGH-1) |
| **FREEZE_RISK** (temp) | `_handle_temperature :2036` | NONE — append-only | PRIMARY GAP (§4-A) |
| **OVERHEAT** (temp) | `_handle_temperature :2036` | NONE | PRIMARY GAP (§4-A) |
| **HIGH_HUMIDITY** (sustained + swing) | `_handle_humidity :2091` ladder `:2192+`, swing `:2158-2182` | `_humidity_above_since`/`_humidity_hazard_fired` reset at `else` `:2275-2278`; `_active_hazards["high_humidity:<loc>"]` never popped | PRIMARY GAP (§4-B) |
| **LOW_HUMIDITY** (universal) | `_handle_humidity` LOW branch ≈ `:2280-2300` | NONE | PRIMARY GAP (§4-C) |
| Rate-of-change hazards (see §2a-rev4) | `_rate_detector.check_thresholds` (threshold OR z-score mode `:727`) → appended in `_process_sensor` → routed through `_respond_to_hazard :2315` | NONE — never popped; stuck forever when source goes silent (NEW-H2) | PRIMARY GAP (§4-E-rev4 + §4-H-rev4) |
| Manual `clear_hazard` / `clear_all_hazards` | n/a | `:2770-2790` — zero production callers | §4-K (KEEP+WIRE) |

### 2a-rev4. ROC key collision (HIGH-1) + z-score mode (MED-3)

There are **no separate ROC hazard types**. The rate detector maps rates to the
*existing* `HazardType` values (per the detector THRESHOLDS block ≈ `:600-620`):

| Rate | Raises | Collides with type-wise clear path for |
|---|---|---|
| `temperature_rise_extreme` | `HazardType.OVERHEAT` | `_handle_temperature` overheat clear (§4-A) |
| `temperature_drop` / `temperature_rise` (season-gated) | `HazardType.HVAC_FAILURE` | — (no type-wise clear in this plan) |
| `humidity_rise` | `HazardType.WATER_LEAK` | `_handle_binary_hazard` leak clear `:1773` AND the binary leak hazard key |

**Decision — key suffix.** Rate-raised hazards are keyed `f"{type.value}:{location}:roc"`
in `_active_hazards`, `_hazard_occurrences`, `_hazard_raising_sensors`, and
`_hazard_clear_pending`. Rationale over "match by sensor_id/origin": origin matching
requires every consumer to be audited for the join; the suffix is a one-point change at
the key constructor in `_respond_to_hazard` plus a one-point update in
`is_hazard_active`.

**Consumer sweep (§4-G) required.** `is_hazard_active :3112` currently matches by
substring (`:3116`) and by `endswith(f":{location}")` — the `:roc` suffix defeats
`endswith`, which would cause consumers to think a rate hazard has cleared and
silently drop re-fire. Update: strip a trailing `:roc` before comparison.

**Rev 4 — z-score mode (MED-3).** `check_thresholds :727` raises by z-score when a
sensor's baseline window is populated; the raise is not keyed to a fixed
`raise_rate`. The Hazard dataclass therefore carries BOTH `raise_rate: float | None`
AND `raise_z: float | None` populated at raise time (one of the two is non-None
depending on the branch). Clear logic in §4-H-rev4 reads these stored values.

---

## 3. Consumer map of `_active_hazards` (rev 4 — MED-2 correction)

| Consumer | file:line (develop) | Trust/Display | Change when hazard clears |
|---|---|---|---|
| `active_hazards` property | `safety.py` property near init | Display | Dict shrinks |
| `get_safety_status()` | `safety.py` status block | **Trust** (safety status entity) | Returns "normal" when empty |
| `is_hazard_active(type, loc)` | `:3112` (substring `:3116`) | Display today (see note below) | Returns False → **Must strip `:roc` for the equality branch** (§4-G). |
| `_respond_to_hazard` dedup | `:2315-2330` | **Trust** — "same key already active" suppresses re-signal | After clear, next entry back into band is a NEW event → re-fires `SIGNAL_SAFETY_HAZARD`. Rev 3: sensor registration + pending-cancel happen BEFORE this early return. **Rev 4:** life-safety override forces `is_new=True` for SMOKE/CO/WATER_LEAK during pending-clear. |
| `SIGNAL_SAFETY_HAZARD` receivers (hvac/energy/security/music) | grep'd | **Trust** (cross-coordinator overrides) | No cleared signal; receivers rely on grace. Unchanged. |
| Zone chip `ZoneSafetyAlertSensor` | `aggregation.py:4560-4620` | **Trust** | Reads **live sensor state**, not `_active_hazards`. Unchanged. |
| `sensor.ura_safety_active_hazards` | `sensor.py` active-hazards sensor | Display | Count decrements (user-visible delay — see §7-D7-rev3). |
| NM `_re_evaluate_hazard` | `notification_manager.py:3019-3059`, call to `is_hazard_active` at `:3039` | **INERT today (rev 4 — MED-2):** safety's `NotificationAction` at `safety.py:2413-2420` does NOT populate `hazard_type` / `location`; `manager.py:1079` passes None; NM calls `is_hazard_active("", "")` which always returns False. Not a Trust consumer in the current build. The §4-G exact-match rewrite therefore cannot suppress a CO re-page because nothing reaches it today. Tracked as separate card **SAFETY-NM-REFIRE-UNWIRED** (§10, out of scope). | n/a until wired |

**NM dedup is NOT storm protection.** `_is_deduplicated` at
`notification_manager.py:3802-3825` builds its key as
`f"{coordinator_id}:{title}:{location}"`. Titles embed the sensor value, so a
drifting-value flap defeats dedup entirely. Hysteresis + minimum hold on the raise
path is the only defence (and is the mechanism specified in §4-I-rev3). The
existing `SafetyDeduplicator` at `safety.py:900` governs NM-page cadence for the
rev-4 life-safety re-run path.

---

## 4. Design — clear-on-recovery with hysteresis

### Falsifiable invariant

**(Superseded by §4-invariant-rev4 above — adds the life-safety response invariant.
The §4-invariant-rev4 statement is the authoritative one; D re-reads it.)**

### 4-0. New state (fixes HIGH-2 + MEDIUM-6; rev 4 life-safety override)

Added in `__init__`:

```
self._hazard_raising_sensors: dict[str, set[str]] = {}  # key -> set of sensor_ids
self._hazard_clear_pending: dict[str, datetime] = {}    # key -> first-all-in-range time
self._sensor_unavailable_since: dict[str, datetime] = {}  # rev 3; writers §4-J-rev4
```

Lifecycle rules (ordering per §4-0-rev4 above):

- **On raise** (`_respond_to_hazard :2315` — BEFORE the `not is_new` early return at
  `~:2325-2330`): snapshot `had_pending_clear = key in self._hazard_clear_pending`;
  `_hazard_raising_sensors[key].add(hazard.sensor_id)`;
  `_hazard_clear_pending.pop(key, None)`. **Rev 4:** if `had_pending_clear` AND
  `hazard.type in (SMOKE, CARBON_MONOXIDE, WATER_LEAK)`, force `is_new = True` so
  the HIGH response runs.
- **On per-sensor in-range** (new helper `_record_sensor_recovery(key, sensor_id, now)`):
  discard `sensor_id` from `_hazard_raising_sensors[key]`. If the set is now empty,
  set `_hazard_clear_pending[key] = now` **if not already set** (set-if-absent).
- **On per-sensor out-of-range** (new helper `_record_sensor_relapse(key, sensor_id)`):
  re-add `sensor_id` to the set; `_hazard_clear_pending.pop(key, None)`.
- **On pop** (clear/raise-replaces/manual clear): pop all three dicts for the key.
- **On teardown** (`async_teardown` dict-clear block): clear all three (§5).

Clear is only authorised when `_hazard_raising_sensors[key]` is empty AND
`now - _hazard_clear_pending[key] >= HAZARD_MIN_HOLD_S`.

### 4-A. `_handle_temperature` (`:2036`) — FREEZE_RISK + OVERHEAT

Mirror branches. For FREEZE_RISK, `freeze_key = f"freeze_risk:{location}"` (no `:roc`):

- If `_classify_severity(FREEZE_RISK, value) is not None` (sensor still in freeze
  band): `_record_sensor_relapse(freeze_key, entity_id)` (safe no-op if key absent).
- Elif `freeze_key in self._active_hazards` AND
  `value >= raise_threshold(FREEZE_RISK, Severity.LOW) + FREEZE_CLEAR_OFFSET_F`:
  `_record_sensor_recovery(freeze_key, entity_id, now)`.
- Else: inside offset band — no state change on the clear machinery.

OVERHEAT mirrors (recovery = `value <= raise_threshold(OVERHEAT, Severity.LOW) - OVERHEAT_CLEAR_OFFSET_F`).

The actual pop is centralised in `_try_clear_if_quiet(key, now)` (shared helper), called
after `_record_sensor_recovery` and also from the periodic sweep (§4-H-rev4). It checks the
set-empty-and-hold-elapsed condition, pops the three dicts, and fires
`_notify_entity_update()`.

Note on raise-threshold reference (MEDIUM-6): the clear threshold is anchored to the
**LOW severity rung** (least-strict raise), independent of what severity actually
raised the key.

### 4-B. `_handle_humidity` (`:2091`) — HIGH_HUMIDITY (sustained + swing)

Thresholds **must be the per-room resolved values** (`:2136-2154`), not raw
`HUMIDITY_THRESHOLDS` — the operator-tuned normal-ladder knobs
(`CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT`, `_MEDIUM_PCT`, `_HIGH_PCT`) govern raise AND
clear symmetrically.

**Early return ordering (MEDIUM-5).** The outdoor-room guard at `:2087` (`return hazards`)
runs BEFORE any clear machinery — if an outdoor sensor ever ended up with a
HIGH_HUMIDITY key (shouldn't, but defensively), outdoor returns early. Decision:
accept the asymmetry; outdoor rooms are excluded from the ladder entirely, so no clear
is needed. If a legacy key exists, it is pruned on next restart (ephemeral dict).

Clear site: the existing `else` branch at `:2275-2278` already resets
`_humidity_above_since` + `_humidity_hazard_fired`. Augment:

- Below `thresholds["low"]`: call `_record_sensor_recovery(f"high_humidity:{location}", entity_id, now)`
  only when `value <= thresholds["low"] - HIGH_HUMIDITY_CLEAR_OFFSET_PCT`.
- In the `>= low` branch: call `_record_sensor_relapse(...)`.
- `_try_clear_if_quiet` then checks hold.

Swing hazards share the key `high_humidity:<location>` — one clear path. Swing one-shot
flag at `:2186-2187` continues to discharge independently.

**D2 sustained-window note.** The acceptance test does NOT need to simulate 2h of
real time; it drives `_handle_humidity` with monotonically advancing `now` arguments
and asserts: raise after `window_hours` elapsed → clear after
`HAZARD_MIN_HOLD_S` elapsed from the first in-range reading. The 2h is only a *raise*
precondition.

### 4-C. `_handle_humidity` — LOW_HUMIDITY (`:2280-2300`)

Fires on every state change below `LOW_HUMIDITY_THRESHOLDS`. Clear:

- If `low_severity is None` AND `value >= LOW_HUMIDITY_THRESHOLDS[Severity.LOW] + LOW_HUMIDITY_CLEAR_OFFSET_PCT`:
  `_record_sensor_recovery(f"low_humidity:{location}", entity_id, now)`.
- Else if `low_severity is not None`: `_record_sensor_relapse(...)`.

Plausibility guard: when the junk-floor branch rejects a value below
`HUMIDITY_PLAUSIBLE_MIN_PCT`, neither recovery nor relapse is called — the sample is
dropped.

### 4-D. FLOODING key cleanup

When `_handle_binary_hazard` discards an entity from `_active_leak_sensors` (`:1773`
region), also recompute: if `_active_leak_sensors` is empty, pop any
`flooding:<loc>` keys for that location. No hysteresis (binary).

### 4-E-rev4. ROC rate hazards (fixes HIGH-1; MED-3 — store rate/z on Hazard)

- In `_process_sensor`, mark rate-detector results with a flag; in
  `_respond_to_hazard :2315` build `key = f"{hazard.type.value}:{hazard.location}:roc"`
  when the flag is set.
- At raise time, populate `hazard.raise_rate` AND `hazard.raise_z` from the
  triggering branch of `check_thresholds` (one or the other non-None depending on
  whether threshold or z-score mode fired). These two fields drive the §4-H-rev4
  clear logic.
- Periodic sweep (§4-H-rev4) handles indefinitely-quiet rate hazards via
  `get_rate` returning None (primary) + rate-below-fraction OR z-below-fraction OR
  stale-sample safety-net (secondary).

### 4-F. Named knobs (rung-1 module constants)

| Constant | Default |
|---|---|
| `FREEZE_CLEAR_OFFSET_F` | 3.0 |
| `OVERHEAT_CLEAR_OFFSET_F` | 3.0 |
| `HIGH_HUMIDITY_CLEAR_OFFSET_PCT` | 3.0 |
| `LOW_HUMIDITY_CLEAR_OFFSET_PCT` | 3.0 |
| `CO2_CLEAR_OFFSET_PPM` | 100 |
| `TVOC_CLEAR_OFFSET_PPB` | 50 |
| `CO_CLEAR_OFFSET_PPM` | 2 |
| `ROC_CLEAR_OFFSET_FRAC` | 0.5 |
| `HAZARD_MIN_HOLD_S` | 300 (5 min) |
| `ROC_STALE_SAMPLE_S` (rev 3) | 900 |
| `SENSOR_UNAVAILABLE_WINDOW_S` (rev 3) | 900 |

0 disables the respective offset but hold still applies.

### 4-G. `is_hazard_active` suffix-aware (fixes HIGH-1 consumer)

Rewrite at `:3112`:

```
def is_hazard_active(self, hazard_type: str, location: str) -> bool:
    exact = f"{hazard_type}:{location}"
    for active_key in self._active_hazards:
        base = active_key[:-4] if active_key.endswith(":roc") else active_key
        if base == exact:
            return True
    return False
```

Removes the substring (`in`) match (Bug Class #22-adjacent — e.g. `"co" in "co2"`
returned True). **Rev 4 note (MED-2):** this rewrite is correct and future-proof,
but today's NM `_re_evaluate_hazard` never reaches it with a real
`hazard_type`/`location` — see §3-rev4. Keep the rewrite; it is a prerequisite for
the SAFETY-NM-REFIRE-UNWIRED follow-up card.

### 4-H. Periodic clear sweep (fixes HIGH-3; superseded by §4-H-rev4 above)

**See §4-H-rev4 for the authoritative description** (None-return primary clear;
stored-rate / stored-z fractional checks; stale-sample safety-net;
unavailable-contributor handling via §4-J-rev4; outside the flooding guard).

### 4-I. CO2 / TVOC / CO (fixes MEDIUM-4; superseded by §4-I-rev3 above)

**See §4-I-rev3 for the authoritative description** (BOTH pop sites — severity-None
at `:1942-1950` AND the NEW-H1 CO2 log-only rung at `:1895-1906` — are routed
through the shared recovery helper so the log-only pop no longer beats hysteresis).
**Rev 4:** CARBON_MONOXIDE relapse during pending-clear is governed by §4-0-rev4
(HIGH response re-runs; SafetyDeduplicator :900 throttles NM pages).

---

## 5. Restart semantics

`_active_hazards`, `_hazard_occurrences`, `_hazard_raising_sensors`,
`_hazard_clear_pending`, and `_sensor_unavailable_since` (rev 3) are ephemeral; all five
cleared in `async_teardown` (`:3140-3160`) alongside the existing teardown clears.
`clear_all_hazards()` also clears all five. Boot-transient behaviour unchanged — raises
fire exactly once per severity transition; the clear pending-timer only arms after a
raise has already occurred.

`_evaluate_sensor_on_recovery` (unavailable→value) already re-enters
`_handle_temperature` / `_handle_humidity` / `_handle_numeric_hazard`; the new clear
logic lives inside those handlers so recovery-from-unavailable just works.

---

## 6. Tier classification — **Tier 2-DB** (elevated rev 2)

Three framing-disjoint reviews:

- **Review A — correctness + arithmetic + edge cases.** Clear-band arithmetic for every
  hazard type; LOW-rung anchoring independent of raised severity; outdoor early-return
  interaction; junk-floor plausibility interaction; CO2/TVOC/CO units; **NEW-H1 CO2
  log-only rung hysteresis gate** (rev 3); sign of OVERHEAT vs FREEZE_RISK offsets;
  `_classify_severity` asymmetry; **rev 4 — §4-0-rev4 life-safety override
  arithmetic + the stored `raise_rate` / `raise_z` fields + the §4-J-rev4 writer at
  `:1538`.**
- **Review B — key semantics + consumer migration (the DB-shaped risk).** Every write to
  `_active_hazards` uses the right key shape (`:roc` where appropriate); every reader
  handles the new keys; the three new dicts are popped on every raise/replace/manual-clear/teardown
  path. HIGH-2 ordering: sensor_id registration + pending-cancel BEFORE the
  `not is_new` early return; **rev 4 — the life-safety override DOES rerun the full
  HIGH response path for SMOKE/CO/WATER_LEAK when `had_pending_clear` was true at
  entry; MED-2 §3-rev4 consumer correction (NM `_re_evaluate_hazard` is inert
  today — the §4-G rewrite is still correct and future-proof).**
- **Review C — anti-flap + cross-coordinator ripple + test authority + completeness.**
  Oscillating-sensor storm scenarios count exactly ONE `SIGNAL_SAFETY_HAZARD`;
  HVAC/energy/security/music receivers behave correctly across a raise→clear→re-raise
  cycle; boot/restart; periodic-sweep test uses time advancement with no state_changed
  events; **NEW-H2 ROC clears via `get_rate` None-return (rev 4 primary) + stale-sample
  safety-net + z-score branch**; **rev 4 — leak-rewet-during-hold test; CO
  relapse-during-hold test; `_sensor_unavailable_since` stamped at `:1538` AND by
  the sweep; test_tvoc_detection test-only `dt_util.utcnow()` fix at
  `quality/tests/test_safety_coordinator.py:804`**; mutation drill — commenting out
  `_try_clear_if_quiet` OR the periodic sweep OR the §4-0-rev3 pre-early-return
  registration OR the §4-0-rev4 life-safety override OR the §4-I-rev3 log-only
  hysteresis gate OR the §4-J-rev4 unavailable drop each fails a specific named test.
  **Re-enumerate EVERY `_active_hazards.pop/del/clear` site in the file against
  §4-site-table** (Bug Class #53 completeness).

---

## 7. Deliverables + acceptance criteria (discriminating; count signals)

### D1 — Temperature clear (FREEZE_RISK + OVERHEAT) with hysteresis + hold + contributor set

- **Verify (clear):** FREEZE_RISK LOW raised at 44F, writing 48.5F for ≥ 5 min pops
  `freeze_risk:<loc>`; `get_safety_status()` returns normal.
- **Verify (hysteresis):** 46F held 5 min does NOT clear.
- **Verify (two sensors, HIGH-2):** two freeze sensors at location X both raise; one
  returns to 48.5F while the other stays at 42F; after 10 min the key is STILL present;
  when the second also returns, hold timer starts from the LATER recovery; clear after
  5 more min.
- **Verify (register-before-early-return, rev 3):** two sensors A + B, same loc, same
  severity. A raises first (is_new=True). B raises SAME severity → early return at
  `~:2325-2330` — but B must already be in `_hazard_raising_sensors[key]` and
  `_hazard_clear_pending[key]` cancelled. A then returns in-range → key STAYS. B returns
  + hold → key pops.
- **Verify (anti-flap, discriminating):** oscillating 44.5↔46.0 at 10 s cadence over
  10 min — **assert exactly 1 `SIGNAL_SAFETY_HAZARD` dispatched** (the initial raise),
  not re-dispatches. Spy on the dispatcher.
- **Verify (cross+hold):** sensor crosses clear line and holds < HOLD → no clear, no
  re-signal; crosses and holds ≥ HOLD then re-enters band → exactly ONE new signal.
- **Test:** `test_safety_freeze_clear_on_recovery_with_hysteresis`,
  `test_safety_overheat_clear_on_recovery_with_hysteresis`,
  `test_safety_temp_clear_blocked_inside_offset_band`,
  `test_safety_temp_clear_waits_for_all_contributing_sensors`,
  `test_safety_second_raise_registers_sensor_even_when_not_is_new`,
  `test_safety_temp_no_flap_signal_count_under_oscillation`,
  `test_safety_temp_cross_without_hold_does_not_clear`.
- **Live:** `sensor.ura_safety_coordinator_safety_status` returns to normal within
  `HAZARD_MIN_HOLD_S + 120s` of the physical sensor returning in-range; zero new NM
  pages in that window.

### D2 — Humidity clear (HIGH_HUMIDITY sustained + swing + LOW_HUMIDITY)

- **Verify (resolved thresholds):** test uses `CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT`-based
  thresholds, not raw `HUMIDITY_THRESHOLDS["normal"]`.
- **Verify (sustained raise + clear):** inject readings with monotonically advancing
  `now` over `window_hours` + hold; one raise signal, one implicit clear (no clear
  signal exists; assert `_active_hazards` empty and `get_safety_status()` normal).
- **Verify (replay Garage A episode):** feed the recorded trace; assert key clears and
  signal count across the episode = 1.
- **Verify (replay Study A 0.0 episode):** with junk-floor branch applied, 0.0 readings
  are dropped (no raise, no clear) and a subsequent legitimate 25% raises exactly once.
- **Verify (swing shares key):** swing-raised HIGH_HUMIDITY clears via the same `:low -
  OFFSET` path.
- **Test:** `test_safety_high_humidity_clear_uses_resolved_normal_thresholds`,
  `test_safety_high_humidity_swing_clear_shares_key`,
  `test_safety_low_humidity_clear_on_recovery_with_hysteresis`,
  `test_safety_low_humidity_replay_garage_a_episode_single_signal`,
  `test_safety_humidity_clear_ignored_below_plausibility_floor`,
  `test_safety_humidity_outdoor_room_returns_early_before_clear_block`.

### D3 — FLOODING key cleanup

- **Verify:** last leak sensor goes off → `_active_leak_sensors` empty →
  `flooding:<loc>` keys popped.
- **Test:** `test_safety_flooding_clears_when_last_leak_sensor_dries`.

### D4 — ROC hazard clear (rev 4 — stored rate/z + None-return primary)

- **Verify:** rate-raised OVERHEAT keyed `overheat:<loc>:roc` with `raise_rate`
  populated; when `get_rate` returns None in a subsequent sweep tick, key pops
  after `HAZARD_MIN_HOLD_S`.
- **Verify:** when `get_rate` returns a non-None value below
  `stored_raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)` AND holds, key pops.
- **Verify (z-score mode):** baselined window raises with `raise_z` populated and
  `raise_rate = None`; z-score decays below `stored_raise_z × (1 − ROC_CLEAR_OFFSET_FRAC)` →
  key pops.
- **Verify (HIGH-1):** a type-wise temperature return to in-range does NOT pop the
  `:roc` key; and a `:roc` humidity-rise does NOT share a key with a binary water-leak
  hazard.
- **Verify (HIGH-1 consumer, future-proof):** `is_hazard_active("overheat", "<loc>")`
  returns True while only the `:roc` key is present. (NM `_re_evaluate_hazard`
  consumer is inert today — tracked as SAFETY-NM-REFIRE-UNWIRED; this verify is
  against the fixed `is_hazard_active` directly, not through NM.)
- **D4 scope correction (rev 4 — MED-2):** removed earlier assertion that NM
  `_re_evaluate_hazard` round-trips through `is_hazard_active` — that path is
  inert today.
- **Test:** `test_safety_roc_overheat_uses_roc_suffix_key`,
  `test_safety_roc_does_not_collide_with_binary_water_leak`,
  `test_safety_is_hazard_active_ignores_roc_suffix`,
  `test_safety_roc_clear_after_quiet_window`.

### D5 — Periodic sweep (fixes HIGH-3; extended rev 4 for NEW-H2 + MED-3)

- **Verify:** raise temperature hazard; advance HA time by `HAZARD_MIN_HOLD_S + 60s`
  WITHOUT firing any sensor state_changed event (sensor is reading in-range at the
  moment of raise's final state_change and never changes again); key is popped by the
  periodic sweep.
- **Verify (rev 4 — ROC None-return primary):** fire ONE `temperature_rise_extreme`
  event raising `overheat:<loc>:roc`; advance HA time by `HAZARD_MIN_HOLD_S + 60s`
  with ZERO new state_changed events on the contributing sensor; `get_rate` returns
  None → key pops.
- **Verify (rev 4 — ROC stale-sample safety-net):** construct a case where
  `get_rate` returns a non-None aged value AND
  `now − last_sample_time ≥ ROC_STALE_SAMPLE_S` → key pops via safety-net branch.
- **Verify (ROC recompute below fraction):** inject follow-up readings producing a
  recomputed rate below `stored_raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)`; key pops.
- **Test:** `test_safety_periodic_sweep_clears_steady_in_range_sensor`,
  `test_safety_roc_clears_on_get_rate_none`,
  `test_safety_roc_clears_on_stale_sample_safety_net`,
  `test_safety_roc_clears_on_recomputed_rate_below_fraction`,
  `test_safety_roc_clears_on_z_score_below_fraction`.

### D6 — CO2 / TVOC / CO hysteresis (fixes MEDIUM-4 + NEW-H1 rev 3 + MED-5 test fix rev 4)

- **Verify (replay Study A CO2 flap):** feed the recorded 00:04-00:11 trace at
  1500-1502 ppm; **assert `SIGNAL_SAFETY_HAZARD` dispatched exactly 1 time** across the
  window, key present throughout.
- **Verify (NEW-H1 log-only pop no longer races):** sequence `1510 → 1490 → 1510 → 1490`
  at 10s cadence; between every raise and the subsequent 1490 reading, assert
  `_active_hazards["high_co2:<loc>"]` is still present; SIGNAL count = 1 over the loop.
- **Verify (CO2 clear via log-only path):** readings `1510 (raise) → 1395` for
  `HAZARD_MIN_HOLD_S` → key pops.
- **Verify (CO2 clear via main path):** readings `1510 (raise) → 950` for
  `HAZARD_MIN_HOLD_S` → key pops via severity-None path at `:1942-1950`.
- **Verify (rev 4 — CO relapse during pending-clear reissues HIGH response):** raise
  CARBON_MONOXIDE HIGH; value dips through CO offset for 60s (hold not yet
  elapsed) → `_hazard_clear_pending` armed; value spikes back above raise within hold
  → assert HIGH response spy was called a second time; SafetyDeduplicator :900
  governs NM page cadence.
- **Test (rev 4 — MED-5 test-only fix):** fix
  `quality/tests/test_safety_coordinator.py:804` `test_tvoc_detection` to seed
  `dt_util.utcnow()` (aware) instead of `datetime.utcnow()` (naive) — production
  already uses `dt_util.utcnow()` at `safety.py:1924`. No production change.
- **Test:** `test_safety_co2_hysteresis_single_signal_under_threshold_flap`,
  `test_safety_co2_log_only_rung_does_not_pop_inside_hysteresis_band`,
  `test_safety_co2_clear_via_log_only_recovery_below_offset`,
  `test_safety_co2_clear_via_severity_none_path`,
  `test_safety_tvoc_clear_requires_offset_and_hold`,
  `test_safety_co_clear_requires_offset_and_hold`,
  `test_safety_co_relapse_during_hold_reissues_response`,
  (fix) `test_tvoc_detection` → use `dt_util.utcnow()`.

### D7 — Doc write-back

- Update `docs/Coordinator/SAFETY_COORDINATOR.md` with: lifecycle gap, the new keys
  (`:roc` suffix), the contributor-set + pending-timer + unavailable-sensor model, the
  shared offsets, the periodic sweep (with None-return primary clear + stale-sample
  safety-net + z-score branch), the §4-J-rev4 per-type unavailable policy and the two
  named writers, and the **§4-0-rev4 life-safety override**.
- Candidate QUALITY_CONTEXT bug class: "Raised-but-never-cleared trust value" (if
  not already present).
- **Operator-visible timing change (rev 3):** `binary_sensor.<room>_air_quality`,
  `binary_sensor.<room>_safety_alert`, and `sensor.ura_safety_active_hazards` stay ON
  for up to `HAZARD_MIN_HOLD_S` (300s) longer than today; ROC-raised hazards up to
  `ROC_STALE_SAMPLE_S + HAZARD_MIN_HOLD_S` (1200s). Called out in `README_v<version>.md`
  under "Operator-visible changes".
- **Life-safety priority (rev 4):** SMOKE / CARBON_MONOXIDE / WATER_LEAK response
  actions are never suppressed by the clear-hold machinery; SafetyDeduplicator :900
  governs NM page cadence.

### D8 — Unavailable / removed raising sensor policy (rev 3; §4-J-rev4)

- **Verify (life-safety keep):** SMOKE raised via sensor A; A unavailable 30 min; key
  present; `is_hazard_active("smoke","x")` True.
- **Verify (comfort drop):** HIGH_HUMIDITY raised via A+B; A unavailable
  `SENSOR_UNAVAILABLE_WINDOW_S + 60s`; A dropped from raising-set; key pops if B in-range
  and hold elapsed.
- **Verify (recovery before window):** A unavailable 10 min then returns in-range →
  treated normally; `_sensor_unavailable_since[A]` cleared.
- **Verify (rev 4 — writer at `:1538`):** sensor A contributes to a HIGH_HUMIDITY key;
  A transitions to `unavailable` → state handler early-returns at `:1538` → assert
  `_sensor_unavailable_since[A]` was stamped.
- **Verify (rev 4 — writer in sweep):** sensor B contributes to a HIGH_HUMIDITY key;
  B's entity is removed from the state machine → `hass.states.get("sensor.b")`
  returns None → next sweep tick stamps `_sensor_unavailable_since[B]`.
- **Test:** `test_safety_smoke_keeps_key_when_sensor_unavailable`,
  `test_safety_humidity_drops_contributor_after_unavailable_window`,
  `test_safety_unavailable_contributor_restored_before_window_resumes_normally`,
  `test_safety_unavailable_since_stamped_at_state_handler_early_return`,
  `test_safety_unavailable_since_stamped_by_sweep_when_entity_removed`.

---

## 8. Non-goals

1. No new `SIGNAL_SAFETY_HAZARD_CLEARED` dispatch — park `SAFETY-HAZARD-CLEARED-SIGNAL-1`.
2. No persistence of `_active_hazards` across restart.
3. No changes to raise thresholds or to the junk-floor plausibility floor.
4. No live-tunable Number entities for the new offsets.
5. No changes to zone-chip projection code — reads live state (LOW-10).
6. (Rev 3) No deletion of `clear_hazard` — KEEP+WIRE per §4-K.
7. **(Rev 4) No wiring of `hazard_type` / `location` into safety's `NotificationAction`.**
   NM `_re_evaluate_hazard` is inert today and remains inert at the end of this
   cycle; the wire-up is tracked as a separate card
   **SAFETY-NM-REFIRE-UNWIRED** (§10). The §4-G `is_hazard_active` rewrite in this
   cycle is a correctness prerequisite for that future card.

---

## 9. Marginal-benefit note

Simplest version = "pop at severity None" (symmetric to today's numeric clear) —
captures the stuck-tile symptom but fails under the Study A 1500ppm flap AND
NEW-H1 (log-only pop beats hysteresis) AND NEW-H2 (spike-then-constant ROC never
clears) AND the life-safety re-wet case (a leak that re-wets during a 300s hold
would NOT re-run valve-close — rev-4 HIGH-1). The hysteresis + hold +
contributor-set + periodic-sweep (with None-return primary + stale-sample
safety-net + z-score branch) + unavailable-contributor policy + **life-safety
override** machinery is the minimum discharge that resolves ALL plan-review HIGHs
AND the rev-3 HIGHs AND the rev-4 HIGH together. NM dedup does not help; its key
embeds the drifting value (§3).

---

## 10. Plan completion / explicit deferrals

- Push "cleared" signal — PARKED `SAFETY-HAZARD-CLEARED-SIGNAL-1`.
- Persistence of `_active_hazards` across restart — not needed.
- Live-tunable Number entities for offsets — rejected (rung 1 constants).
- Backfill one-time clear for already-stuck hazards at deploy time — HA restart
  (deploy script performs one) clears the dict.
- (Rev 3) `clear_hazard` deletion — rejected (KEEP+WIRE per §4-K).
- **(Rev 4) `NotificationAction` hazard_type / location wiring + NM
  `_re_evaluate_hazard` round-trip** — PARKED as new card
  **SAFETY-NM-REFIRE-UNWIRED**. Scope: populate `hazard_type` and `location` on
  safety's `NotificationAction` emits (`safety.py:2413-2420`); verify
  `manager.py:1079` passes them through; add a D4-style NM round-trip test that
  asserts `_re_evaluate_hazard` returns True while the hazard is active and False
  after clear. Prerequisite (§4-G `is_hazard_active` rewrite) ships in THIS cycle.
  **Update 2026-10-15: BUILT** as SAFETY-NM-REFIRE-UNWIRED-1 (branch
  `feature/safety-nm-refire`; ships in the next release, version stamped at
  deploy). See `docs/planning/PLANNING_safety_nm_refire.md` Rev 4/4.1: D1 wires
  `hazard_type`/`location`, D2 makes `is_hazard_active` hold-aware (post-ACK
  gate only), D6 sorts the flooding location. The plan's D5 (stop the unacked
  repeat loop on clear) was WITHDRAWN — unacked life-safety alerts
  latch until acked; `_repeat_alert` is unchanged.
