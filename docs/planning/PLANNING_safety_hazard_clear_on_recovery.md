# PLANNING — SAFETY-HAZARD-NEVER-CLEARS-1

Card: SAFETY-HAZARD-NEVER-CLEARS-1 ("humidity / freeze / overheat hazards never clear
until HA restart").

**Tier: Tier 2-DB** (elevated from Tier 2 in rev 2 — see §6). Three framing-disjoint
reviews + live validation + README write-back.

Stacking: this plan is written on top of `feature/safety-humidity-junk-floor`
(SAFETY-HUMIDITY-JUNK-READING-1, in review). All file:line citations below are **against
the branch `feature/safety-humidity-junk-floor`** (lines drifted ~+25-30 vs develop).
Reviewers verify by:
`git -C /Users/okosisi/Code/universal-room-automation show feature/safety-humidity-junk-floor:custom_components/universal_room_automation/domain_coordinators/safety.py`.

---

## Rev 3 — re-review fixes (map)

All file:line below are against the feature branch per the command above. Develop
working-tree equivalents verified via `Grep`: branch adds ~+25-30 lines in the
`_handle_numeric_hazard` region and ~+40 lines by `_async_periodic_check`.

| Finding | Fix section |
|---|---|
| NEW-H1 (HIGH) 2nd CO2 clear site — log-only rung at `safety.py:1895-1906` pops `co2:<loc>` immediately for `co2_low ≤ v < co2_medium`; the planned CO2 clear point `1500−100=1400` sits INSIDE that band so the immediate pop wins (repro: `1510 raise → 1490 log-only pop → 1510 raise`). | §4-I-rev3 (route through `_record_sensor_recovery` + hysteresis gate) + §4-site-table (every pop/del/clear site enumerated) |
| NEW-H2 (HIGH) `:roc` keys only arm `_hazard_clear_pending` on state_change; a spike-then-constant sensor fires nothing further → stuck forever | §4-H-rev3 (sweep recomputes 30-min rate from sample window; stale-sample backstop) + new knob `ROC_STALE_SAMPLE_S` + D5 extended |
| HIGH-2 ordering — register sensor + cancel pending clear BEFORE the `not is_new` early return at `~:2325-2330` | §4-0-rev3 (ordering made explicit) + D1 extra test |
| Dead / removed / unavailable raising sensors — per-type policy | §4-J (new) + new knob `SENSOR_UNAVAILABLE_WINDOW_S` + D8 (new) |
| Invariant must survive hysteresis-band readings as legitimate hold (don't let reviewer D falsify it with intended behaviour) | §4-invariant-rev3 (restated against CLEAR threshold, three-arm disjunction) |
| Sweep sits OUTSIDE flooding `if self._active_leak_sensors` guard | §4-H-rev3 (explicit position); registration `:1222-1225`, body `:2696` |
| Stale `:1917-1923` citation → real severity-None pop `:1942-1950`; §0 line 45 cite `:1904-1946` → `:1942-1950` (and NEW-H1 site `:1895-1906`) | §0-rev3 (citation fixes) + §4-I-rev3 |
| LOW: `clear_hazard` (`~:2770-2775`) has zero callers, builds key w/o `:roc`, doesn't pop new dicts | §4-K (align minimally — KEEP+WIRE, not DELETE) |
| LOW: README note — `binary_sensor.<room>_air_quality`, `safety_alert`, hazard count linger up to `HAZARD_MIN_HOLD_S` longer | §7-D7-rev3 bullet |
| Pop-site completeness (Bug Class #53) — every write enumerated | §4-site-table |

### §4-site-table — every `_active_hazards` write on the branch + post-cycle handling

| Site (branch line) | Today | After this cycle |
|---|---|---|
| `_handle_binary_hazard` leak clear `~:1773` | pop `water_leak:<loc>` + discard from `_active_leak_sensors` | route through `_record_sensor_recovery` + hold `HAZARD_MIN_HOLD_S` (no hysteresis — binary); matches ladder (§4-D). |
| `_handle_numeric_hazard` **CO2 log-only rung pop** `:1895-1906` (NEW-H1) | immediate pop `high_co2:<loc>` when `co2_low ≤ v < co2_medium` | `v ≤ co2_medium − CO2_CLEAR_OFFSET_PPM` (= 1400) → `_record_sensor_recovery(key, eid, now)`; `1400 < v < 1500` → `_record_sensor_relapse(key, eid)` (inside hysteresis band, still contributing); logging preserved; pop happens only through `_try_clear_if_quiet`. (§4-I-rev3) |
| `_handle_numeric_hazard` **severity-None pop** `:1942-1950` (was mis-cited `:1917-1923`) | pop + pop occurrences + `_notify_entity_update` | replaced by `_record_sensor_recovery` + per-type offset gate (§4-I-rev3) |
| `_respond_to_hazard` raise `~:2315-2330` | `_active_hazards[key] = hazard`; early return if `not is_new` | register sensor_id into `_hazard_raising_sensors[key]` + `_hazard_clear_pending.pop(key, None)` **BEFORE** the `not is_new` early return (§4-0-rev3) |
| **Periodic sweep (new) `_async_periodic_check` body `:2696`** | — | pop all three dicts for keys with empty raising-set + elapsed hold; also recompute `:roc` rate and apply stale-sample backstop; **positioned OUTSIDE the `if self._active_leak_sensors:` flooding guard** (§4-H-rev3) |
| `clear_hazard(type, loc)` `~:2770-2775` | pops `{type}:{loc}` only; zero production callers (grep: only self-definition) | §4-K: KEEP+WIRE — also pop `{type}:{loc}:roc`, `_hazard_raising_sensors[*]`, `_hazard_clear_pending[*]`. |
| `clear_all_hazards()` `~:2780+` | `_active_hazards.clear()` | also `.clear()` `_hazard_raising_sensors`, `_hazard_clear_pending`, `_sensor_unavailable_since` (§5) |
| `async_teardown` dict-clears `:3140-3160` | existing | add the three new dicts (§5) |

### §4-invariant-rev3 — hysteresis-safe falsifiable invariant

For every key `K` in `_active_hazards`, at ALL times AT LEAST ONE of:

- **(a)** at least one sensor in `_hazard_raising_sensors[K]` currently reads **worse than
  the CLEAR line** (not the raise line) — i.e. for OVERHEAT, `v > raise − OFFSET`
  interpreted as "has not yet crossed the clear line"; for FREEZE_RISK, `v < raise + OFFSET`;
  for HIGH_HUMIDITY, `v > low − OFFSET`; for LOW_HUMIDITY, `v < low + OFFSET`; for
  HIGH_CO2/TVOC/CO, `v > medium − OFFSET`. **A reading inside the hysteresis band is on
  neither side of the invariant — it is a legitimate hold, not a violation.**
- **(b)** all sensors in `_hazard_raising_sensors[K]` read on the clear side but
  `now − _hazard_clear_pending[K] < HAZARD_MIN_HOLD_S`.
- **(c)** K ends in `:roc` AND (recomputed 30-min rate magnitude ≥
  `raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)` for at least one contributing sensor) OR
  (any contributing sensor had a sample in the last `ROC_STALE_SAMPLE_S`).

Reviewer D cannot falsify (a) with an in-band reading because (a) explicitly covers it.
Negation set: (1) all sensors on the clear side for ≥ HOLD and K still present → FAIL;
(2) oscillating sensor at threshold±ε fires > 1 `SIGNAL_SAFETY_HAZARD` per 10 min → FAIL;
(3) `:roc` key present AND no sample within `ROC_STALE_SAMPLE_S` AND rate recompute below
fractional threshold → FAIL; (4) `_respond_to_hazard` with `is_new=False` returns without
registering sensor_id into the raising set → FAIL (first-raiser recovers → key wrongly pops).

### §4-0-rev3 — raise ordering (HIGH-2)

In `_respond_to_hazard` (`~:2315`), BEFORE the existing dedup/early-return at `~:2325-2330`:

```
key = f"{hazard.type.value}:{hazard.location}" + (":roc" if hazard.from_roc else "")
self._hazard_raising_sensors.setdefault(key, set()).add(hazard.sensor_id)
self._hazard_clear_pending.pop(key, None)
existing = self._active_hazards.get(key)
is_new = existing is None or existing.severity != hazard.severity
# ... existing path continues ...
if not is_new:
    return []   # early return — but set membership + pending-cancel ALREADY DONE
```

Explicit test (D1 add): two sensors A + B, same location, same severity. A raises
(`is_new=True`); B raises SAME severity (`is_new=False`, early return). After B's raise,
`_hazard_raising_sensors[key] == {A, B}`. Then A returns in-range → key STAYS (B still
contributing). B returns + hold elapsed → key pops.

### §4-H-rev3 — periodic sweep (position + ROC recompute + stale backstop)

**Position.** `_async_periodic_check` body is `~:2696`. The sweep lives **after the
flooding block closes**, at the outer function scope — NOT inside
`if self._active_leak_sensors:`. The flooding guard scopes only the flooding-escalation
block; the clear sweep must run every tick regardless of leak state. Registration
remains the existing 1-minute `async_track_time_interval` at `~:1222-1225`.

**Non-`:roc` keys.** As rev 2 — pop three dicts when raising-set empty AND hold elapsed.

**`:roc` keys (NEW-H2).** For each contributing sensor_id:

1. Query the rate detector for a recomputed 30-min rate from its stored sample window.
2. If recomputed |rate| < `raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)` →
   `_record_sensor_recovery(key, sensor_id, now)`.
3. If the detector reports no sample for ≥ `ROC_STALE_SAMPLE_S` → treat as implicit
   recovery (spike-then-constant produces zero events; the mathematical rate decays).
   Call `_record_sensor_recovery(key, sensor_id, now)`.
4. Then standard set-empty + hold-elapsed check; pop all three dicts + fire
   `_notify_entity_update()`.

**Why both recompute AND stale backstop.** The two cases are orthogonal — a single-shot
spike landing in the stored window will never produce follow-up samples, so the
recompute returns the stale rate forever; the stale backstop is the only way out.
Conversely, a slowly-declining rise produces samples but should clear via recompute, not
stale. One lever alone leaves one gap.

**Unavailable contributors — see §4-J.**

### §4-I-rev3 — CO2 / TVOC / CO: BOTH pop sites routed through recovery

The branch has **two** `_active_hazards.pop` sites inside `_handle_numeric_hazard`:

- **Severity-None pop `:1942-1950`** (main clear path).
- **CO2 log-only rung pop `:1895-1906`** (NEW-H1; added by the junk-floor branch's
  NM-Cycle-A rework). This pops `high_co2:<loc>` the instant `v` dips below
  `CONF_CO2_MEDIUM_PPM` (= 1500 live) while `v` ≥ `co2_low` (= ~1000).

With the planned CO2 clear point at `1500 − CO2_CLEAR_OFFSET_PPM = 1400`, **every**
reading in `[1000, 1500)` passes through the log-only branch and the immediate pop at
`:1895-1906` races and WINS over the hysteresis gate. Reproducible loop:
`1510 raise → 1490 log-only pop → 1510 raise → ...` as fast as the sensor publishes.

**Fix for BOTH sites** — remove the raw `.pop(key, None)` and replace with the shared
`_record_sensor_recovery` / `_record_sensor_relapse` + `_try_clear_if_quiet` helper
pattern:

- Severity-None (`:1942-1950`): `v ≤ threshold(type, LOW) − offset(type)` →
  `_record_sensor_recovery(key, eid, now)`; still above raise → `_record_sensor_relapse`;
  in-band → no-op.
- CO2 log-only (`:1895-1906`): `v ≤ co2_medium − CO2_CLEAR_OFFSET_PPM` (= 1400) →
  `_record_sensor_recovery(high_co2_key, eid, now)`; `1400 < v < 1500` →
  `_record_sensor_relapse(high_co2_key, eid)` (sensor is on the HIGH side of its clear
  line, still contributing). Logging line preserved. `_hazard_occurrences` +
  `_notify_entity_update` fire through `_try_clear_if_quiet`.

**Why not just gate the existing pop with `v ≤ 1400`.** That would leave `[1400, 1500)`
silent (no raise emission, no clear emission). The main-path pop at `:1942-1950` would
still clear on the next sample ≤ co2_low, but the stuck-key window reopens whenever the
sensor hovers in `[1400, 1500)`. Routing both sites through the helper closes the loop.

### §4-J — Dead / removed / unavailable raising sensors (new)

Per-type policy evaluated in the periodic sweep:

| Hazard type | On sensor_id unavailable / removed |
|---|---|
| `SMOKE`, `CARBON_MONOXIDE`, `WATER_LEAK` | **fail-safe keep** — sensor stays in `_hazard_raising_sensors[key]`; key does NOT clear from this cause; log once per transition. A missing life-safety signal is treated as unresolved. |
| `HIGH_HUMIDITY`, `LOW_HUMIDITY`, `FREEZE_RISK`, `OVERHEAT`, `HIGH_CO2`, `HIGH_TVOC`, `HVAC_FAILURE` | **drop after `SENSOR_UNAVAILABLE_WINDOW_S`** — if `hass.states.get(sensor_id)` is None/unavailable continuously for the window, discard from the raising-set and run the set-empty + hold check. |

Implementation: new `self._sensor_unavailable_since: dict[str, datetime]` tracks per-sensor
first-unavailable time; cleared on next real value. Sweep reads it. Teardown + `clear_all_hazards`
clear it.

Rung-1 constants:

| Constant | Default | Why |
|---|---|---|
| `SENSOR_UNAVAILABLE_WINDOW_S` | 900 (15 min) | Longer than any legitimate transient (Zigbee/BLE drop, Wi-Fi hiccup) but short enough not to warehouse stale hazards indefinitely. |
| `ROC_STALE_SAMPLE_S` | 900 (15 min) | NEW-H2 backstop. Longer than one periodic tick (1 min); shorter than any legitimate idle for a sensor whose rate was recently extreme. |

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

### D8 — Unavailable / removed raising sensor policy (new)

- **Verify (life-safety keep):** raise SMOKE at loc X via sensor A; set A unavailable for
  30 min; key STILL present; `is_hazard_active("smoke","x")` returns True; no clear signal.
- **Verify (comfort drop):** raise HIGH_HUMIDITY via A + B; set A unavailable for
  `SENSOR_UNAVAILABLE_WINDOW_S + 60s`; A dropped from `_hazard_raising_sensors[key]`;
  if B is in-range and hold elapsed, key pops; else stays until B satisfies.
- **Verify (recovery before window):** A unavailable 10 min then returns in-range → treated
  normally via `_record_sensor_recovery`; `_sensor_unavailable_since[A]` cleared;
  no spurious drop.
- **Test:** `test_safety_smoke_keeps_key_when_sensor_unavailable`,
  `test_safety_humidity_drops_contributor_after_unavailable_window`,
  `test_safety_unavailable_contributor_restored_before_window_resumes_normally`.

### D1 extra (HIGH-2 ordering)

- **Verify (register-before-early-return):** two sensors A + B, same location, same
  severity. A raises (`is_new=True`, A added). B raises SAME severity → early return at
  `~:2325-2330` — **BUT** B must already be in `_hazard_raising_sensors[key]` AND
  `_hazard_clear_pending[key]` cancelled BEFORE the early return. A returns in-range →
  key STAYS. B returns + hold → key pops.
- **Test:** `test_safety_second_raise_registers_sensor_even_when_not_is_new`.

### D5 extended (NEW-H2 ROC)

- **Verify (ROC stale-sample):** fire ONE `temperature_rise_extreme` event raising
  `overheat:<loc>:roc`; advance HA time by `ROC_STALE_SAMPLE_S + HAZARD_MIN_HOLD_S + 60s`
  with ZERO new state_changed events on the contributing sensor (spike-then-constant);
  key pops via sweep's stale-sample backstop.
- **Verify (ROC recompute):** inject follow-up readings that produce a recomputed 30-min
  rate below `raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)`; key pops via recompute, not stale.
- **Test:** `test_safety_roc_clears_on_stale_sample_window`,
  `test_safety_roc_clears_on_recomputed_rate_below_fraction`.

### Rev 3 knobs — append to §4-F

| Constant | Default | Rung | Why |
|---|---|---|---|
| `ROC_STALE_SAMPLE_S` | 900 | 1 (module const) | NEW-H2 ROC backstop. |
| `SENSOR_UNAVAILABLE_WINDOW_S` | 900 | 1 (module const) | §4-J drop gate (comfort hazards only). |

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

### Code read end-to-end during scoping (branch `feature/safety-humidity-junk-floor`)

- `domain_coordinators/safety.py` — hazard pipeline. Key sites (branch lines):
  - rate thresholds table (temperature_rise/humidity_rise → `WATER_LEAK`, `OVERHEAT`, `HVAC_FAILURE`), approx `:616-631` of the detector block
  - `_handle_temperature` ≈ `:2036-2088` (branch `:2036` landmark)
  - `_handle_humidity` ≈ `:2091-2301` (branch `:2091` landmark), normal-ladder resolution ≈ `:2136-2154`, `else` clear tracker ≈ `:2275-2278`, `LOW_HUMIDITY` branch ≈ `:2280-2300`
  - `_handle_numeric_hazard` **CO2 log-only rung pop (NEW-H1) at `:1895-1906`**; **severity-None pop at `:1942-1950`** (rev-3 correction; prior cite `:1904-1946` / `:1917-1923` was WRONG)
  - `_handle_binary_hazard` leak clear ≈ `:1773` (branch `:1773` landmark)
  - `_respond_to_hazard` key `type:location` at ≈ `:2315`, dedup/early-return at `~:2325-2330` (rev 3)
  - `_async_periodic_check` registration `~:1222-1225`, body `≈ :2696-2718` (rev 3 adds registration cite)
  - `is_hazard_active` substring/endswith matching ≈ `:3112-3126` (branch `:3112`, substring at `:3116`)
  - `clear_hazard` / `clear_all_hazards` ≈ `:2770-2790` — `clear_hazard` has **zero production callers** (rev 3 grep verified)
  - `async_teardown` clears dicts ≈ `:3140-3160`
- `domain_coordinators/notification_manager.py`:
  - `_re_evaluate_hazard` at `:3019-3059` — re-fires CRITICAL via `async_notify` while `is_hazard_active` returns True.
  - `_is_deduplicated` at `:3802-3825` — dedup key is `f"{coordinator_id}:{title}:{location or ''}"`. The **title is the raw hazard message with the value embedded** (e.g. `"high_co2 1502 ppm"` vs `"high_co2 1501 ppm"`), so NM dedup gives **zero storm protection** when the value drifts by 1 unit. Documented in §3 and §9; hysteresis + hold is the only defence.
- `aggregation.py:4560-4620` — `ZoneSafetyAlertSensor` reads bands via
  `safety.resolve_safety_bands()` + `evaluate_zone_chip()` over **live sensor state**; it does
  NOT read `_active_hazards`. LOW-10 verified.
- `coordinator.py:145,1705` — `SIGNAL_SAFETY_HAZARD` dispatch wiring (unchanged).

### Prior-art scan (REUSE-or-BUILD per piece)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Clear path for humidity in-range | **REUSE** remove idiom from `_handle_numeric_hazard` (`:1942-1950` — corrected rev 3) + `_handle_binary_hazard` (`:1773`) — pop both `_active_hazards[key]` and `_hazard_occurrences[key]`, then `_notify_entity_update()`. |
| Clear path for temperature in-range | **REUSE** same idiom; clear in the handler on the type-wise negative branch (§4-A). |
| Hysteresis offsets | **NEW** module constants (`FREEZE_CLEAR_OFFSET_F`, `OVERHEAT_CLEAR_OFFSET_F`, `HIGH_HUMIDITY_CLEAR_OFFSET_PCT`, `LOW_HUMIDITY_CLEAR_OFFSET_PCT`, `CO2_CLEAR_OFFSET_PPM`, `TVOC_CLEAR_OFFSET_PPB`, `CO_CLEAR_OFFSET_PPM`, `ROC_CLEAR_OFFSET_FRAC`). Rung 1 — safety-semantics peers of raise thresholds. |
| Minimum hold | **NEW** `HAZARD_MIN_HOLD_S` (default 300s) rung 1. |
| Per-key raising-sensor set | **NEW** `self._hazard_raising_sensors: dict[str, set[str]]` — fixes HIGH-2. Keyed on the same `type:location[:roc]` key used in `_active_hazards`. |
| Per-key hold timer | **NEW** `self._hazard_clear_pending: dict[str, datetime]` — set-if-absent on first in-range reading, popped on any out-of-range reading, cleared on raise/removal paths. Fixes MEDIUM-6. |
| ROC-key suffix | **NEW** rate-raised hazards keyed `type:location:roc` to avoid colliding with binary/numeric type-wise clear paths. Fixes HIGH-1. |
| Periodic clear sweep | **NEW** branch inside `_async_periodic_check` at `:2696`, OUTSIDE the `if self._active_leak_sensors:` flooding guard (rev 3). Fixes HIGH-3. |
| ROC stale-sample backstop + rate recompute (rev 3) | **NEW** sweep extension + `ROC_STALE_SAMPLE_S` constant. Fixes NEW-H2. |
| Unavailable-contributor policy (rev 3) | **NEW** `_sensor_unavailable_since` + `SENSOR_UNAVAILABLE_WINDOW_S`; §4-J. |
| "Cleared" dispatch signal | **DO NOT ADD** — NM polls via `is_hazard_active`. Park `SAFETY-HAZARD-CLEARED-SIGNAL-1`. |

### Prior planning docs consulted

- `docs/planning/PLANNING_freeze_safety_range_shift.md` — freeze tuning only.
- `docs/planning/PLANNING_zone_safety_alert_split.md` — zone-chip; LOW-10 reads live state.
- `docs/planning/AUDIT_restart_safety_classification.md` — `_active_hazards` is ephemeral.
- `docs/planning/kanban.data.yaml` — SAFETY-HUMIDITY-JUNK-READING-1 upstream branch.

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

## 2. Hazard-type table (how raised, how cleared TODAY — branch lines)

| Hazard type | Raise site | Clear site TODAY | Gap? |
|---|---|---|---|
| SMOKE (binary) | `_handle_binary_hazard` | binary clear ≈ `:1773` | OK |
| WATER_LEAK (binary) | `_handle_binary_hazard` | binary clear ≈ `:1773` + `_leak_start_times.pop` | OK |
| FLOODING (escalated) | `_check_flooding_escalation` + `_async_periodic_check :2696` | Implicit via leak clear; **key `flooding:<loc>` not explicitly popped** | MINOR GAP (§4-D) |
| CARBON_MONOXIDE / HIGH_CO2 / HIGH_TVOC (numeric) | `_handle_numeric_hazard` | **two** pop sites: severity-None `:1942-1950` AND CO2 log-only rung `:1895-1906` (NEW-H1) — **no hysteresis, no hold** → flaps at threshold AND the log-only pop beats hysteresis for CO2 | **PRIMARY GAP** (§4-I-rev3; MEDIUM-4; NEW-H1) |
| **FREEZE_RISK** (temp) | `_handle_temperature :2036` | NONE — append-only | PRIMARY GAP (§4-A) |
| **OVERHEAT** (temp) | `_handle_temperature :2036` | NONE | PRIMARY GAP (§4-A) |
| **HIGH_HUMIDITY** (sustained + swing) | `_handle_humidity :2091` ladder `:2192+`, swing `:2158-2182` | `_humidity_above_since`/`_humidity_hazard_fired` reset at `else` `:2275-2278`; `_active_hazards["high_humidity:<loc>"]` never popped | PRIMARY GAP (§4-B) |
| **LOW_HUMIDITY** (universal) | `_handle_humidity` LOW branch ≈ `:2280-2300` | NONE | PRIMARY GAP (§4-C) |
| Rate-of-change hazards (see §2a) | `_rate_detector.check_thresholds` → appended in `_process_sensor` → routed through `_respond_to_hazard :2315` | NONE — never popped; stuck forever when source goes silent (NEW-H2) | PRIMARY GAP (§4-E; HIGH-1; NEW-H2 via §4-H-rev3) |
| Manual `clear_hazard` / `clear_all_hazards` | n/a | `:2770-2790` — zero production callers | §4-K (KEEP+WIRE) |

### 2a. ROC key collision (HIGH-1 — resolution)

There are **no separate ROC hazard types**. The rate detector maps rates to the
*existing* `HazardType` values (per the detector THRESHOLDS block ≈ `:600-620`):

| Rate | Raises | Collides with type-wise clear path for |
|---|---|---|
| `temperature_rise_extreme` | `HazardType.OVERHEAT` | `_handle_temperature` overheat clear (§4-A) |
| `temperature_drop` / `temperature_rise` (season-gated) | `HazardType.HVAC_FAILURE` | — (no type-wise clear in this plan) |
| `humidity_rise` | `HazardType.WATER_LEAK` | `_handle_binary_hazard` leak clear `:1773` AND the binary leak hazard key |

Without discrimination, a type-wise clear (temperature returning in-range) would pop a
rate-raised overheat key owned by a different, still-firing mechanism; a humidity-rise
rate hazard would share the key `water_leak:<location>` with the actual binary leak
sensor and either path's clear would erase the other.

**Decision — key suffix.** Rate-raised hazards are keyed `f"{type.value}:{location}:roc"`
in `_active_hazards`, `_hazard_occurrences`, `_hazard_raising_sensors`, and
`_hazard_clear_pending`. Rationale over "match by sensor_id/origin": origin matching
requires every consumer to be audited for the join; the suffix is a one-point change at
the key constructor in `_respond_to_hazard` plus a one-point update in
`is_hazard_active`.

**Consumer sweep (§4-G) required.** `is_hazard_active :3112` currently matches by
substring (`:3116`) and by `endswith(f":{location}")` — the `:roc` suffix defeats
`endswith`, which would cause NM to think a rate hazard has cleared and silently drop
re-fire. Update: strip a trailing `:roc` before comparison, so NM's query
`is_hazard_active("overheat", "study_a")` still returns True for a `:roc` overheat.

---

## 3. Consumer map of `_active_hazards` (updated)

| Consumer | file:line (branch) | Trust/Display | Change when hazard clears |
|---|---|---|---|
| `active_hazards` property | `safety.py` property near init | Display | Dict shrinks |
| `get_safety_status()` | `safety.py` status block | **Trust** (safety status entity) | Returns "normal" when empty |
| `is_hazard_active(type, loc)` | `:3112` (substring `:3116`) | **Trust** — NM `_re_evaluate_hazard` consumer at `notification_manager.py:3038` | Returns False → NM returns to IDLE at next cooldown expiry. **Must strip `:roc` for the equality branch** (§4-G). |
| `_respond_to_hazard` dedup | `:2315-2330` | **Trust** — "same key already active" suppresses re-signal (`is_new = existing is None or existing.severity != hazard.severity`) | After clear, next entry back into band is a NEW event → re-fires `SIGNAL_SAFETY_HAZARD`. Rev 3: sensor registration + pending-cancel happen BEFORE this early return. |
| `SIGNAL_SAFETY_HAZARD` receivers (hvac/energy/security/music) | grep'd | **Trust** (cross-coordinator overrides) | No cleared signal; receivers rely on grace. Unchanged. |
| Zone chip `ZoneSafetyAlertSensor` | `aggregation.py:4560-4620` | **Trust** | Reads **live sensor state** via `safety.resolve_safety_bands()` + `evaluate_zone_chip()`; does NOT read `_active_hazards`. LOW-10 verified — unchanged. |
| `sensor.ura_safety_active_hazards` | `sensor.py` active-hazards sensor | Display | Count decrements (user-visible delay — see §7-D7-rev3). |

**NM dedup is NOT storm protection.** `_is_deduplicated` at `notification_manager.py:3802-3825`
builds its key as `f"{coordinator_id}:{title}:{location}"`. Titles embed the sensor
value ("high_co2 1502 ppm" vs "1501 ppm"), so a drifting-value flap defeats dedup
entirely. The live Study A CO2 episode on 2026-09-29 00:04-00:11 fired ~20
SIGNAL_SAFETY_HAZARD + ~20 pages at 1500-1502 ppm. **Hysteresis + minimum hold on the
raise path is the only defence** (and is the mechanism specified in §4-I-rev3).

---

## 4. Design — clear-on-recovery with hysteresis

### Falsifiable invariant

**(Superseded by §4-invariant-rev3 above — three-arm disjunction that treats in-band
readings as a legitimate hold, not a violation. The §4-invariant-rev3 statement is the
authoritative one; D re-reads it.)**

### 4-0. New state (fixes HIGH-2 + MEDIUM-6)

Added in `__init__`:

```
self._hazard_raising_sensors: dict[str, set[str]] = {}  # key -> set of sensor_ids
self._hazard_clear_pending: dict[str, datetime] = {}    # key -> first-all-in-range time
self._sensor_unavailable_since: dict[str, datetime] = {}  # rev 3; §4-J
```

Lifecycle rules (ordering per §4-0-rev3 above):

- **On raise** (`_respond_to_hazard :2315` — BEFORE the `not is_new` early return at
  `~:2325-2330`): `_hazard_raising_sensors[key].add(hazard.sensor_id)`;
  `_hazard_clear_pending.pop(key, None)` (any pending clear is cancelled by a new raise).
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
after `_record_sensor_recovery` and also from the periodic sweep (§4-H-rev3). It checks the
set-empty-and-hold-elapsed condition, pops the three dicts, and fires
`_notify_entity_update()`.

Note on raise-threshold reference (MEDIUM-6): the clear threshold is anchored to the
**LOW severity rung** (least-strict raise), independent of what severity actually
raised the key. Documented in the pop helper's docstring to avoid future "freeze
raised HIGH at 32F clears at 48F not 35F" confusion.

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

### 4-E. ROC rate hazards (fixes HIGH-1; NEW-H2 handled in §4-H-rev3)

- In `_process_sensor`, mark rate-detector results with a flag; in
  `_respond_to_hazard :2315` build `key = f"{hazard.type.value}:{hazard.location}:roc"`
  when the flag is set.
- In the per-sensor clear path for the matching entity, if the 30-min rate magnitude
  is below `(raise_rate * (1 - ROC_CLEAR_OFFSET_FRAC))` compute recovery against the
  `:roc` key.
- Periodic sweep (§4-H-rev3) handles indefinitely-quiet rate hazards via recompute +
  stale-sample backstop (NEW-H2).

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

Removes the substring (`in`) match that was already Bug Class #22-adjacent (e.g.
`"co" in "co2"` returned True by accident). Documented in the diff commit.

### 4-H. Periodic clear sweep (fixes HIGH-3; superseded by §4-H-rev3 above)

**See §4-H-rev3 for the authoritative description** (position outside flooding guard;
ROC recompute + stale-sample backstop; unavailable-contributor handling). The rev 2
sketch below is retained for provenance.

Extend `_async_periodic_check :2696`. After the existing flooding block, add:

```
# Sweep pending clears for sensors steady in-range (no state_change needed)
expired = [k for k, t in self._hazard_clear_pending.items()
           if (now - t).total_seconds() >= HAZARD_MIN_HOLD_S
           and not self._hazard_raising_sensors.get(k)]
for key in expired:
    self._active_hazards.pop(key, None)
    self._hazard_occurrences.pop(key, None)
    self._hazard_raising_sensors.pop(key, None)
    self._hazard_clear_pending.pop(key, None)
if expired:
    self._notify_entity_update()
```

The periodic tick is 1 minute (`:1222-1225` registration). Test fixture D5 advances HA time
with `async_fire_time_changed` without firing any state_changed event and asserts the
key clears within one tick after `HAZARD_MIN_HOLD_S`.

### 4-I. CO2 / TVOC / CO (fixes MEDIUM-4; superseded by §4-I-rev3 above)

**See §4-I-rev3 for the authoritative description** (BOTH pop sites — severity-None at
`:1942-1950` AND the NEW-H1 CO2 log-only rung at `:1895-1906` — are routed through
the shared recovery helper so the log-only pop no longer beats hysteresis).

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

The reviewer recommended Tier 2-DB because key semantics (`type:location` → `type:location[:roc]`
plus a three-dict contributor/pending/unavailable model) are consumed by multiple downstream
coordinators via `is_hazard_active` and `SIGNAL_SAFETY_HAZARD`. This is a classic
trust-hierarchy ripple risk even though no DB DAO is touched. Three framing-disjoint
reviews:

- **Review A — correctness + arithmetic + edge cases.** Clear-band arithmetic for every
  hazard type; LOW-rung anchoring independent of raised severity; outdoor early-return
  interaction; junk-floor plausibility interaction; CO2/TVOC/CO units; **NEW-H1 CO2
  log-only rung hysteresis gate** (rev 3); sign of OVERHEAT vs FREEZE_RISK offsets;
  `_classify_severity` asymmetry.
- **Review B — key semantics + consumer migration (the DB-shaped risk).** Every write to
  `_active_hazards` (`:1895-1906` CO2 log-only, `:1942-1950` severity-None, `:2315` raise,
  periodic flooding block, periodic clear sweep) uses the right key shape (`:roc` where
  appropriate); every reader (`is_hazard_active :3112`, `get_safety_status`,
  `active_hazards` property, `get_all_hazards_detail`, `get_water_leak_status`,
  sensor.py active-hazards readers) handles the new keys; NM `_re_evaluate_hazard`
  round-trips correctly through the updated `is_hazard_active`;
  `_hazard_raising_sensors`, `_hazard_clear_pending`, `_sensor_unavailable_since` are
  popped on every raise/replace/manual-clear/teardown path (no leak that would starve
  the clear). **HIGH-2 ordering: sensor_id registration + pending-cancel BEFORE the
  `not is_new` early return** (rev 3).
- **Review C — anti-flap + cross-coordinator ripple + test authority + completeness.**
  Oscillating-sensor storm scenarios (Garage A 30%, Study A 1500ppm) count exactly ONE
  `SIGNAL_SAFETY_HAZARD`; HVAC/energy/security/music receivers behave correctly across
  a raise→clear→re-raise cycle; boot/restart; periodic-sweep test uses time advancement
  with no state_changed events; **NEW-H2 spike-then-constant stale-sample backstop
  clears `:roc` keys** (rev 3); mutation drill — commenting out `_try_clear_if_quiet`
  OR the periodic sweep OR the §4-0-rev3 pre-early-return registration OR the §4-I-rev3
  log-only hysteresis gate OR the §4-J unavailable drop each fails a specific named test.
  **Re-enumerate EVERY `_active_hazards.pop/del/clear` site in the file against §4-site-table**
  (Bug Class #53 completeness).

---

## 7. Deliverables + acceptance criteria (discriminating; count signals)

### D1 — Temperature clear (FREEZE_RISK + OVERHEAT) with hysteresis + hold + contributor set

- **Verify (clear):** FREEZE_RISK LOW raised at 44F, writing 48.5F for ≥ 5 min pops
  `freeze_risk:<loc>`; `get_safety_status()` returns normal.
- **Verify (hysteresis):** 46F held 5 min does NOT clear.
- **Verify (two sensors, HIGH-2):** two freeze sensors at location X both raise; one
  returns to 48.5F while the other stays at 42F; after 10 min the key is STILL present;
  when the second also returns, hold timer starts from the LATER recovery; clear after
  5 more min. Assert `_hazard_raising_sensors["freeze_risk:x"]` set membership at each step.
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

### D4 — ROC hazard clear (contradiction resolved)

**Decision (MEDIUM-7):** use the shared `HAZARD_MIN_HOLD_S` + rate below
`(raise_rate × (1 - ROC_CLEAR_OFFSET_FRAC))`. Drop the "2 consecutive 30-min windows"
language. The 30-min-window property is a property of the rate detector's input
sampling, not of the clear criterion.

- **Verify:** rate-raised OVERHEAT keyed `overheat:<loc>:roc`; when 30-min rate magnitude
  drops below the fractional threshold and holds for `HAZARD_MIN_HOLD_S`, key pops.
- **Verify (HIGH-1):** a type-wise temperature return to in-range does NOT pop the
  `:roc` key; and a `:roc` humidity-rise does NOT share a key with a binary water-leak
  hazard.
- **Verify (HIGH-1 consumer):** NM `_re_evaluate_hazard` querying
  `is_hazard_active("overheat", "<loc>")` returns True while only the `:roc` key is
  present.
- **Test:** `test_safety_roc_overheat_uses_roc_suffix_key`,
  `test_safety_roc_does_not_collide_with_binary_water_leak`,
  `test_safety_is_hazard_active_ignores_roc_suffix`,
  `test_safety_roc_clear_after_quiet_window`.

### D5 — Periodic sweep (fixes HIGH-3; extended rev 3 for NEW-H2)

- **Verify:** raise temperature hazard; advance HA time by `HAZARD_MIN_HOLD_S + 60s`
  WITHOUT firing any sensor state_changed event (sensor is reading in-range at the
  moment of raise's final state_change and never changes again); key is popped by the
  periodic sweep.
- **Verify (NEW-H2 ROC stale-sample, rev 3):** fire ONE `temperature_rise_extreme`
  event raising `overheat:<loc>:roc`; advance HA time by `ROC_STALE_SAMPLE_S +
  HAZARD_MIN_HOLD_S + 60s` with ZERO new state_changed events on the contributing
  sensor; key pops via stale-sample backstop.
- **Verify (NEW-H2 ROC recompute, rev 3):** inject follow-up readings producing a
  recomputed 30-min rate below `raise_rate × (1 − ROC_CLEAR_OFFSET_FRAC)`; key pops via
  recompute, not stale.
- **Test:** `test_safety_periodic_sweep_clears_steady_in_range_sensor` using
  `async_fire_time_changed` only — no `async_set` on sensor between the recovery read
  and the clear; `test_safety_roc_clears_on_stale_sample_window`;
  `test_safety_roc_clears_on_recomputed_rate_below_fraction`.

### D6 — CO2 / TVOC / CO hysteresis (fixes MEDIUM-4 + NEW-H1 rev 3)

- **Verify (replay Study A CO2 flap):** feed the recorded 00:04-00:11 trace at
  1500-1502 ppm; **assert `SIGNAL_SAFETY_HAZARD` dispatched exactly 1 time** across the
  window (down from the live ~20), key present throughout.
- **Verify (NEW-H1 log-only pop no longer races, rev 3):** sequence
  `1510 → 1490 → 1510 → 1490` at 10s cadence; between every raise and the subsequent
  1490 reading, assert `_active_hazards["high_co2:<loc>"]` is **still present**
  (log-only branch now routes 1490 through `_record_sensor_relapse`, not an immediate
  pop); SIGNAL count = 1 over the loop.
- **Verify (CO2 clear via log-only path):** readings `1510 (raise) → 1395` for
  `HAZARD_MIN_HOLD_S` → key pops (the 1395 reading hits the log-only branch and now
  calls `_record_sensor_recovery` since `1395 ≤ 1400`).
- **Verify (CO2 clear via main path):** readings `1510 (raise) → 950` for
  `HAZARD_MIN_HOLD_S` → key pops via the severity-None path at `:1942-1950`.
- **Test:** `test_safety_co2_hysteresis_single_signal_under_threshold_flap`,
  `test_safety_co2_log_only_rung_does_not_pop_inside_hysteresis_band`,
  `test_safety_co2_clear_via_log_only_recovery_below_offset`,
  `test_safety_co2_clear_via_severity_none_path`,
  `test_safety_tvoc_clear_requires_offset_and_hold`,
  `test_safety_co_clear_requires_offset_and_hold`.

### D7 — Doc write-back

- Update `docs/Coordinator/SAFETY_COORDINATOR.md` with: lifecycle gap, the new keys
  (`:roc` suffix), the contributor-set + pending-timer + unavailable-sensor model, the
  shared offsets, the periodic sweep (with ROC recompute + stale-sample backstop), and
  the §4-J per-type unavailable policy.
- Candidate QUALITY_CONTEXT bug class: "Raised-but-never-cleared trust value" (if
  not already present).
- **Operator-visible timing change (rev 3):** `binary_sensor.<room>_air_quality`,
  `binary_sensor.<room>_safety_alert`, and `sensor.ura_safety_active_hazards` stay ON
  for up to `HAZARD_MIN_HOLD_S` (300s) longer than today; ROC-raised hazards up to
  `ROC_STALE_SAMPLE_S + HAZARD_MIN_HOLD_S` (1200s). Called out in `README_v<version>.md`
  under "Operator-visible changes".

### D8 — Unavailable / removed raising sensor policy (rev 3; §4-J)

- **Verify (life-safety keep):** SMOKE raised via sensor A; A unavailable 30 min; key
  present; `is_hazard_active("smoke","x")` True.
- **Verify (comfort drop):** HIGH_HUMIDITY raised via A+B; A unavailable
  `SENSOR_UNAVAILABLE_WINDOW_S + 60s`; A dropped from raising-set; key pops if B in-range
  and hold elapsed.
- **Verify (recovery before window):** A unavailable 10 min then returns in-range →
  treated normally; `_sensor_unavailable_since[A]` cleared.
- **Test:** `test_safety_smoke_keeps_key_when_sensor_unavailable`,
  `test_safety_humidity_drops_contributor_after_unavailable_window`,
  `test_safety_unavailable_contributor_restored_before_window_resumes_normally`.

---

## 8. Non-goals

1. No new `SIGNAL_SAFETY_HAZARD_CLEARED` dispatch — park `SAFETY-HAZARD-CLEARED-SIGNAL-1`.
2. No persistence of `_active_hazards` across restart.
3. No changes to raise thresholds or to the junk-floor plausibility floor.
4. No live-tunable Number entities for the new offsets.
5. No changes to zone-chip projection code — reads live state, already consistent (LOW-10).
6. (Rev 3) No deletion of `clear_hazard` — KEEP+WIRE per §4-K (not DELETE).

(Previous non-goal "CO2/TVOC/CO out of scope" is **removed** — MEDIUM-4 brings them in
under D6, same mechanism; rev 3 brings NEW-H1 under the same mechanism.)

---

## 9. Marginal-benefit note

Simplest version = "pop at severity None" (symmetric to today's numeric clear) —
captures the stuck-tile symptom but **fails under the live Study A 1500ppm flap**
(~20 signals/pages) AND fails NEW-H1 (log-only pop beats hysteresis for CO2) AND fails
NEW-H2 (spike-then-constant ROC never clears). The hysteresis + hold + contributor-set
+ periodic-sweep (with ROC recompute + stale-sample backstop) + unavailable-contributor
policy machinery is the minimum discharge that resolves ALL plan-review HIGHs AND the
rev-3 HIGHs together; NM dedup does not help because its key embeds the drifting value
(§3). Keep.

---

## 10. Plan completion / explicit deferrals

- Push "cleared" signal — PARKED `SAFETY-HAZARD-CLEARED-SIGNAL-1`.
- Persistence of `_active_hazards` across restart — not needed.
- Live-tunable Number entities for offsets — rejected (rung 1 constants).
- Backfill one-time clear for already-stuck hazards at deploy time — HA restart
  (deploy script performs one) clears the dict.
- (Rev 3) `clear_hazard` deletion — rejected (KEEP+WIRE per §4-K).
