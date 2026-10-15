# PLANNING — EV fill-priority SOC re-pause band (EV-FILL-PRIORITY-SOC-CHATTER-1)

- Card: `EV-FILL-PRIORITY-SOC-CHATTER-1` (`docs/planning/kanban.data.yaml:126-161`)
- Thread: energy
- Tier: **Tier 2-DB** — changes an EV pause owner (`fill_priority`), interacts with
  drain / arbitrage / load_shed / breaker / excess-solar precedence. Three framing-disjoint
  reviews before ship. Not Tier 3.
- **Rev 2 (2026-10-15c)** — rewrites §5.3 and §6 to resolve all seven FIX-REQUIRED
  findings + three LOWs from the Rev-1 plan review
  (`docs/reviews/code-review/plan_ev_fill_priority_buffer_review.md`). Design direction
  (option A: resume at 80, re-pause only below 77) is unchanged. See §13
  Review-resolution table.
- Operator decision 2026-10-15b: **APPROVED option A** — resume at 80%, re-pause only
  below 77%. Buffer applies ONLY after a resume. First pause below 80% is unchanged.
- Prior approval 2026-10-15 ("see if config fixes these first") already discharged:
  `CONF_ENERGY_FILL_PRIORITY_SOC` (`energy_const.py:1077-1079`) is a single threshold
  used symmetrically for pause and resume — moving it only moves the chatter point.
- Not to be confused with `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` — different owner
  (`arbitrage`), different mechanism.

## 1. Institutional context verified

### Code surveyed end-to-end (Rev-1 unchanged + Rev-2 additions)
- `energy_const.py:1065-1094` — fill-priority defaults + conf key, drain/plug grace,
  surplus-pct knob.
- `energy_const.py:1337-1504` — SOC-ladder validator; fill-priority invariant #4.
- `energy_pool.py` (EV path, `EVPool`):
  - `:585` init `_paused_by_fill_priority: set[str] = set()` — RAM-only.
  - `:589` `_fill_priority_solar_ok`, `:600` `_fill_priority_would_hold` — cross-tick
    publications read by the arbitrage release path.
  - `:2668-2921` `determine_fill_priority_actions`.
    - `:2756-2766` **INERT branch** (peak / off_peak-night / mid_peak-post-peak) —
      discards every id from `_paused_by_fill_priority` + returns. Rev-2 finding 1
      pins the latch clear here.
    - `:2768-2772` pause condition `soc < soc_threshold and forecast_healthy`.
    - `:2773` `resume_soc_met = soc >= soc_threshold`.
    - `:2776-2778` publishes `_fill_priority_would_hold` (consumed by arbitrage
      release at `:3153`; see §8).
    - `:2780` top of `for evse_id, config in self._evse.items()` — Rev-2 finding 2
      pins the cross-owner-steal clear here.
    - `:2785-2793` force-charge branch — Rev-2 finding 3 moves the clear OUT of
      the `if evse_id in self._paused_by_fill_priority` guard.
    - `:2844-2864` pause action + membership add + dispatch claim.
    - `:2865-2919` resume branch (`:2866` gate = `resume_soc_met or forecast_decayed`;
      `:2871-2888` cross-owner-steal clear WITHIN the FP-set guard; `:2916` terminal
      discard). Rev-2 finding 4 sets the latch ONLY when the resume reason is
      `resume_soc_met` (discriminator = the local bool at `:2866`/`:2911`).
  - `:3120-3178` arbitrage release — reads `_fill_priority_would_hold` at `:3153`
    and WRITES `_paused_by_fill_priority.add(evse_id)` at `:3156` (hand-off; see
    finding 5).
  - `:3491-3547` `release_all_fill_priority` — called when excess-solar toggle is
    OFF; writer at `:3496` and `:3525` (plug mirror sibling) listed in §8.
  - `:3225-3278` sensor surface for FP state.
- `energy_pool.py:4384-4561` — PLUG mirror `determine_fill_priority_actions` on
  `PlugPool`.
  - `:3634` sibling `_paused_by_fill_priority: set[str] = set()` init on `PlugPool`
    (per Rev-2 LOW 8: a separate dict is required on each class).
  - `:4441-4446` INERT branch (plug) — Rev-2 finding 1 clear site.
  - `:4448-4451` pause/resume gates.
  - `:4453` top of `for entity_id in self._plugs:` — Rev-2 finding 2 (plug variant).
  - `:4458-4466` force-charge branch (plug) — Rev-2 finding 3 (plug variant).
  - `:4515-4559` resume branch (plug); `:4529-4535` grid-charge M1 held-resume
    (does NOT set the latch — correct, since no resume happened).
  - `:4558` terminal discard.
- `energy.py:6776-6845`, `:6942-6970` — call sites for `determine_fill_priority_actions`
  and `release_all_fill_priority` on both pools.

### Grep-verified existing hysteresis / band patterns
- Forecast-side band already exists:
  `forecast_healthy >= X` vs `forecast_decayed <= X - safety_margin`
  (`energy_pool.py:2719-2731`, mirror `:4414-4424`). The ingredient is
  `DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH = 1.0 kWh` in `energy_const.py:1078`.
- `EV_PAUSE_DISPATCH_GRACE_SECONDS = 30.0` (`energy_const.py:1072`) — unrelated.
- `EV_BATTERY_DRAIN_COOLDOWN_SECONDS = 3600` — different owner; parked.

### Prior-art scan verdict (REUSE vs NEW)
- `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT` — **NEW**. No SOC-side band
  on any pause owner today.
- Pause/release machinery — **REUSE**: `_paused_by_fill_priority`, dispatch
  claim/release, `_charge_on_or_defer`, cross-owner precedence gate.
- Sensor surface — **REUSE**: `paused_by_fill_priority` set is the observable
  discriminator.

### Config-first discharge
`CONF_ENERGY_FILL_PRIORITY_SOC` is the only operator knob and is a single
symmetric threshold. A code change is required.

## 2. The problem (measured)

With `fill_priority_soc = 80`:
- Pause when `SOC < 80` and solar healthy → EV turns off.
- SOC climbs on battery charge to 80 → `resume_soc_met` true → EV resumes.
- 11.6-11.7 kW EV draw drops SOC to 79 within one tick → re-pause.
- Loop at ~5-minute cadence (3 toggles/hour on 10-11 19:26:45Z garage_a; same
  pattern 10-09; 2 of 7 logged days).

## 3. Falsifiable invariant

> **INV-1:** With `grid_charge_on=False`, `force_charge_active=False`,
> `fill_priority_inert=False`, `forecast_healthy=True`, and SOC held in the
> half-open band `[soc_threshold - repause_band_pct, soc_threshold)` after a
> prior fill-priority **SOC-reached** resume, no EV or plug SHALL transition
> `_paused_by_fill_priority` membership in either direction on any tick.
>
> **INV-2 (counter-invariant):** The FIRST pause below `soc_threshold`
> (no live `_recently_released_by_fill_priority` latch for that id) remains
> UNCHANGED — the band applies ONLY on the re-pause-after-SOC-resume path.
> This includes the first pause of a NEW fill window after an overnight inert
> interval (finding 1).
>
> **INV-3 (floor):** With SOC `< soc_threshold - repause_band_pct` and solar
> healthy, a pause SHALL fire on the next tick regardless of prior-resume
> history. The band is a hysteresis, not a hold-off.

Observations that would FALSIFY INV-1:
- A `fill_priority_release` row in `ura_activity_log` followed by a
  `fill_priority_pause` row for the same `switch` entity within one tick while
  SOC was recorded in `[77, 80)` **AND** no inert-period boundary intervened.
- `paused_by_fill_priority` attribute flipping present→absent→present within
  the same SOC band inside 10 minutes.

Discriminating observation (INV-1 vs INV-2 — per Producer AND Consumer rule):
after an overnight off_peak-night inert interval, a FIRST-tick pause at SOC=79
in the morning off_peak daylight slice MUST fire — if it does not, finding 1
regressed.

## 4. Knob ladder

| Knob | Name | Default | Rung | Why |
|---|---|---|---|---|
| Re-pause SOC band (pct) | `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT` | **3** | **Rung 1 (module constant)** | Stability margin, not per-deployment policy. `0` disables (legacy, kill switch). Change requires code review. |

Related `CONF_ENERGY_FILL_PRIORITY_SOC` unchanged.

## 5. Design (do not build — spec only)

### 5.1 Add module constant

`energy_const.py` after `:1078`:

```
# EV-FILL-PRIORITY-SOC-CHATTER-1: resume → re-pause SOC hysteresis.
# After a fill-priority RESUME on the SOC-reached edge, suppress re-pause
# until SOC falls below (fill_priority_soc - DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT).
# The FIRST pause below fill_priority_soc (no live latch) is unchanged.
# Forecast-decay resumes do NOT set the latch; the forecast side has its
# own band (DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH).
# 0 disables (legacy single-threshold behaviour).
DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT: Final = 3
```

### 5.2 Pause-site change (EV path + plug mirror)

Current EV pause gate (`energy_pool.py:2768-2772`) and plug equivalent
(`:4448-4451`) use `soc < soc_threshold`. Spec: split FIRST-pause vs RE-pause
using a dedicated **latch** keyed on evse_id / plug entity_id.

- **First pause** (no live latch for the id): keep `soc < soc_threshold`.
- **Re-pause** (latch live for the id): require
  `soc < max(0, soc_threshold - repause_band_pct)`.

Resume edge at `:2773` and `:4451` UNCHANGED (`soc >= soc_threshold`).

Membership-based discrimination is wrong (terminal resume at `:2916`/`:4558`
clears the FP set). A dedicated latch is required.

### 5.3 Latch — producer, consumers, discharge sites (RESOLVES FINDINGS 1-6)

Two sibling latches, one per pool class — see LOW 8:

```
# On EVPool.__init__ next to self._paused_by_fill_priority (:585):
self._recently_released_by_fill_priority: dict[str, float] = {}
# On PlugPool.__init__ next to its sibling set (:3634):
self._recently_released_by_fill_priority: dict[str, float] = {}
```

Value = `_time.monotonic()` at set time; used for diagnostics / future TTL
if ever reintroduced. Membership (`id in dict`) is the gate.

#### 5.3.1 Producer (FINDING 4 — resume reason discriminator)

ONLY the SOC-reached terminal resume sets the latch. Discriminator = the
local `resume_soc_met` bool computed at `:2866`/`:4516`, re-referenced at
the point of set.

- EV path, immediately before `:2916` terminal discard:
  ```
  if resume_soc_met:
      self._recently_released_by_fill_priority[evse_id] = _time.monotonic()
  self._paused_by_fill_priority.discard(evse_id)
  ```
- Plug path, immediately before `:4558` terminal discard: mirror block
  (same `if resume_soc_met: ...[entity_id] = ...`).
- `forecast_decayed`-only resumes DO NOT set the latch; the forecast side
  already carries `DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH` hysteresis.
- The grid-charge M1 held-resume at `:4529-4535` sets nothing (no resume
  happened) — asserted in A6.

#### 5.3.2 Consumer

The re-pause gate inside the SAME function, only. No cross-coordinator read.

```
effective_floor = max(0, soc_threshold - repause_band_pct)  # clamp (LOW 10)
is_latched = evse_id in self._recently_released_by_fill_priority
if is_latched:
    pause_this_tick = (soc is not None and soc < effective_floor
                       and forecast_healthy)
else:
    pause_this_tick = pause_conditions_global  # legacy edge
```

#### 5.3.3 Discharge sites (every site named, with REACHABLE line + behaviour)

Every clear site runs for EVERY latched id (iterate
`list(self._recently_released_by_fill_priority)`), unconditional on
membership in `_paused_by_fill_priority`, and MUST pop the latch via
`self._recently_released_by_fill_priority.pop(id, None)`.

| # | Site (EV) | Site (plug) | When latch cleared | Rationale |
|---|---|---|---|---|
| D1 | **Inert branch top**, `:2763` loop | `:4443` loop | For every id in the latch dict, pop. Executes before the `return actions`. | **FINDING 1** — peak / off_peak-night / mid_peak-post-peak run DAILY. The inert branch IS the daily discharge; without this, a 13:00 latch survives overnight and suppresses an 08:00 next-day first pause at SOC 79. This supersedes orchestrator Q2's "no TTL — already discharged": Q2 holds **only because of D1**. |
| D2 | **Top of per-id loop**, inserted at `:2781` before any other work (loop body `for evse_id, config in self._evse.items():` at `:2780`) | Inserted at `:4454` top of `for entity_id in self._plugs:` | If `id in self._recently_released_by_fill_priority` AND id appears in any peer pause-owner set (`_paused_by_grid_cap`, `_paused_by_battery_drain`, `_paused_by_us`, `_paused_by_arbitrage`, `_paused_by_load_shed`, `_paused_by_blind_window`; plug peers: `_paused_by_us`, `_paused_by_battery_drain`, `_paused_by_load_shed`), pop the latch; do NOT `continue` — fall through to normal processing so FP's own pause/release still runs idempotently. | **FINDING 2** — Rev-1's named site `:2871-2888` sits inside `elif evse_id in self._paused_by_fill_priority` which is False for any latched id. The top-of-loop site is REACHABLE for every id regardless of membership. |
| D3 | Force-charge branch, `:2785` | `:4458` | **FINDING 3** — move the latch clear OUTSIDE the `if evse_id in self._paused_by_fill_priority` guard: unconditionally `self._recently_released_by_fill_priority.pop(evse_id, None)` immediately after the `if force_charge_active:` line, then run the existing membership-gated FP-set discard inside. | A force-charge override must reset FP state regardless of the FP set, so the next SOC drop below `soc_threshold` after force-charge clears pauses on the FIRST tick, not after another band's worth of drain. |
| D4 | `release_all_fill_priority` (`:3491-3547`, writer at `:3496`) | plug sibling (`:3525`) | At the top: `self._recently_released_by_fill_priority.clear()`. | Excess-solar toggle OFF path — FP is not called at all after this; the latch must not survive into the next toggle-ON window. |
| D5 | **Below-floor sweep** — a dedicated loop at the HEAD of `determine_fill_priority_actions` (EV at `:2780`-ish, plug at `:4453`-ish), running for every id in `list(self._recently_released_by_fill_priority)` on EVERY tick, regardless of `is_on`, excess-solar deferral, or untrusted-SOC refusal: `if soc is not None and soc < effective_floor: pop`. If `soc is None`, leave the latch untouched (no-op). | mirror | **FINDING 6** — the band floor is satisfied; the next pause must fire normally. Runs for OFF chargers too (car full / unplugged) so a latch doesn't survive an afternoon of SOC decay. Explicit no-op on `soc is None` so an SOC outage never spuriously clears. |

A terminal RESUME on `resume_soc_met` RE-SETS the latch (producer); any
subsequent SOC drop below `effective_floor` clears it via D5. All other
pause-owner reads of `_paused_by_fill_priority` (`:2245, :2602, :3135,
:3452, :3547, :3882, :3987`) are UNAFFECTED — the new latch is additive.

### 5.4 Arbitrage hand-off ruling (FINDING 5)

Two publications feed the arbitrage release path and two writers of
`_paused_by_fill_priority` live outside `determine_fill_priority_actions`:

- Producer: `self._fill_priority_would_hold` at `:2776-2778`.
- Writer-outside-FP: `energy_pool.py:3156` (arbitrage hand-off) and
  `energy_pool.py:3525` (`release_all_fill_priority` siblings — plug mirror).

**Ruling:** `_fill_priority_would_hold` is global today; make the latch
INFORM its truth so arbitrage does NOT re-add a latched EVSE inside the
band. Replace `:2776-2778` with:

```
self._fill_priority_would_hold = bool(
    pause_conditions_global
    and not force_charge_active
    and not any(
        _id in self._recently_released_by_fill_priority
        for _id in self._evse
    )
)
```

Rationale: `_fill_priority_would_hold` is read ONCE per tick at `:3153`;
if any latched EVSE exists, arbitrage's hand-off intent is "would NOT
hold inside the band" (the whole point of the band). This preserves the
INV-1 no-transition rule — the hand-off at `:3156` cannot add a latched
EVSE to the FP set because the gate at `:3153` is False.

**Alternative considered + rejected:** per-EVSE `would_hold` — larger
surface, two new publications, forces every arbitrage call site to iterate.
The global-latch-awareness is byte-identical on the no-latch path
(no_latch → `any()` is False → expression unchanged).

**No conflict with arbitrage's own pause ownership:** `:3156` is the ONLY
site where arbitrage writes `_paused_by_fill_priority`. The guard at `:3151`
already requires `not state["is_on"] and self._fill_priority_would_hold`.
With the ruling, both gates compose: `would_hold=False` for any
latched id → hand-off cannot fire → latched id stays released → FP's own
tick re-asserts normal below-floor pause. The arbitrage set
(`_paused_by_arbitrage`) is untouched.

### 5.5 Producer/consumer map additions (FINDING 5 — producer list completeness)

Writers of `_paused_by_fill_priority` (every file:line):
- `energy_pool.py:2787, :2819, :2851, :2880, :2916` — FP owner itself.
- `energy_pool.py:3156` — **arbitrage hand-off** (previously missing from
  the §8 producer list).
- `energy_pool.py:3496, :3525` — **`release_all_fill_priority`** (previously
  missing from §8). `:3525` is the plug mirror writer called from the EV-side
  excess-solar OFF sweep.
- `energy_pool.py:4444, :4460, :4486, :4501, :4523, :4558` — plug FP owner.

Writers of `_recently_released_by_fill_priority` (NEW):
- EV terminal `resume_soc_met` branch adjacent to `:2916`.
- Plug terminal `resume_soc_met` branch adjacent to `:4558`.
- D1-D5 discharge sites (pop/clear only; never set).
- `_fill_priority_would_hold` publisher at `:2776` READS it (consumer).

### 5.6 Restart / reload behaviour

Both the FP set and the latch are RAM-only; a reload erases them, treating
the first post-boot tick as a first pause. Acceptable (§5.4 of Rev-1,
preserved).

### 5.7 Validator / ladder invariant #4

Unaffected; a unit test asserts
`0 <= DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT < DEFAULT_FILL_PRIORITY_SOC`
at import time (Q1 orchestrator ruling preserved).

## 6. Acceptance criteria

| ID | Criterion | Verify |
|---|---|---|
| A1 | INV-1 holds in-suite: forecast_healthy, no peers, SOC walked 80→79→80→79 over four ticks, prior SOC-reached resume → zero membership transitions after first resume | Test — pause/release counts flat |
| A2 | INV-2 holds: fresh EVSE at SOC=78, no live latch, pauses on tick 1 | Test |
| A3 | INV-3 (floor) holds: post-resume at SOC=76 pauses on tick 1 | Test |
| A4 | Band=0 reproduces legacy chatter. **Builder MUST** either (a) pass band as kwarg to `determine_fill_priority_actions` (default = module constant, mirroring `safety_margin_kwh`) OR (b) have `energy_pool.py` reference the constant via module attribute (`energy_const.DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT`) so a `monkeypatch.setattr(energy_const, …, 0)` works. **A `from .energy_const import …` bare binding is forbidden** (LOW 9 — hollow anchor) | Test with (a) kwarg or (b) module-attr access path |
| A5 | Band=100 (band > threshold) does NOT prevent first pause: SOC=50 fresh EVSE pauses | Test |
| A6 | Plug mirror parity (EV + plug paths show matching ledger shape); grid_charge_on M1 held-resume at `:4529-4535` does NOT set the latch | Test — both pools |
| A7 | **Force-charge clears the latch unconditionally** (FINDING 3 restated): with latch live at SOC=79, flip `force_charge_active=True` for one tick then False — on the next tick, SOC still 79, FP pauses at 79 (first-pause edge, legacy `soc < soc_threshold`) | Test (replaces Rev-1 A7's contradictory "clears below floor" wording) |
| A8 | Cross-owner steal clears the latch at D2 (top of loop): drain pauses the EVSE at SOC=79 while latch live → next tick with drain still owning: latch popped. When drain releases at SOC=78: FP pauses on the first-pause edge | Test |
| A9 | `fill_priority_inert` releases cleanly AND discharges the latch (D1): set latch at 13:00 → enter off_peak-night → inert branch runs → latch dict empty on exit → simulated morning off_peak-daylight at SOC=79 pauses on tick 1 (overnight repro from FINDING 1) | Test — explicit day-boundary oracle |
| A10 | Forecast decay/recover does not spuriously latch: SOC=78, forecast_decayed → resume (reason=forecast decayed) → latch NOT set → forecast recovers healthy at SOC=78 → FP pauses on tick 1 (legacy edge) | Test (FINDING 4) |
| A11 | D5 below-floor sweep runs for OFF chargers: EVSE OFF, latch live, SOC drops 79→76 while OFF → latch dict empty next tick | Test |
| A12 | D5 no-op on SOC=None: latch live, SOC source None for one tick → latch unchanged → SOC recovers to 78 → re-pause gate still gated by latch | Test |
| A13 | Arbitrage hand-off respects latch: `_fill_priority_would_hold=False` whenever any EVSE is latched; `:3156` does NOT add a latched EVSE to `_paused_by_fill_priority` | Test — mock arbitrage release path |
| L1 | **Live (first charging day post-deploy, with L2 positive control satisfied):** `ura_activity_log` shows ZERO `fill_priority_pause` rows for a garage charger within 10 minutes of a prior `fill_priority_release` row for the same `switch` while SOC remained in `[77, 80)` | DB query |
| L2 | **Live POSITIVE CONTROL (mandatory for L1/L3 to be non-vacuous — FINDING 7):** on the same day, at least ONE `fill_priority_pause` row exists where the preceding sensor state had SOC `< 80` **AND** no `fill_priority_release` row for that id in the prior 15 min (= a first pause). If zero, report "not exercised" rather than PASS on L1/L3. | DB query |
| L3 | **Live (conditional on L2):** `anomaly_log.ev_toggle_tripwire` rows for the first full charging day = 0 | Same query as `EC-EV-TOGGLE-TRIPWIRE-1` disposition |

## 7. Config-extreme tests

- **Band = 0** → legacy chatter reproduces (A4, kill-switch).
- **Band = 100** → first pause still fires (A5).
- **Band = `fill_priority_soc`** → floor = 0; re-pause only on empty battery.
- **Band > `fill_priority_soc`** → clamped to 0 (LOW 10, `max(0, …)`).
- **Negative band** → clamped to 0 (defensive, LOW 10).
- **Threshold edges:** SOC exactly 77 (floor) pauses; SOC exactly 80 resumes
  (unchanged).
- **Forecast unhealthy during latch** → A10.
- **Grid-charge ON during resume (plug M1)** → A6; no latch set.

## 8. Producer / Consumer map (updated per FINDING 5)

### `_paused_by_fill_priority` (existing)
- **Producers (writers):** `energy_pool.py:2787, :2819, :2851, :2880, :2916,
  :3156` (arbitrage hand-off — new entry), `:3496, :3525` (`release_all`
  siblings — new entries), `:4444, :4460, :4486, :4501, :4523, :4558`.
- **Consumers (readers):** `energy_pool.py:2245, :2602, :3135, :3268, :3413,
  :3452, :3547, :3882, :3987` — precedence gates in drain / arbitrage /
  load_shed / blind_window / cooldown and the sensor-surface serializer.
- **Dependency health:** SOC via `BatteryStrategy.soc` + Envoy LKG fallback
  (shipped v5.103.39); forecast via `WeatherProviderManager`.

### `_fill_priority_would_hold` (existing)
- **Producer:** `energy_pool.py:2776-2778` (updated per §5.4 to be
  latch-aware).
- **Consumer:** `energy_pool.py:3153` (arbitrage release hand-off decision).

### `_recently_released_by_fill_priority` (NEW)
- **Producer:** terminal resume branch where `resume_soc_met is True` (EV
  `:2916` adjacency + plug `:4558` adjacency). No other owner may set it.
- **Consumers:**
  - Re-pause gate in `determine_fill_priority_actions` (per-id, EV + plug).
  - `_fill_priority_would_hold` publisher (`:2776`, aggregate via `any()`).
- **Dischargers (pop/clear):** D1 (inert), D2 (cross-owner steal top-of-loop),
  D3 (force-charge, unconditional), D4 (`release_all_fill_priority`), D5
  (below-floor sweep, every tick).
- **Trust tier:** behavioural (controls dispatch); not a display value.

## 9. Non-goals

- Minimum-hold timer (parked).
- Changing `fill_priority_soc` default (80 stays).
- Changing resume condition (still `soc >= soc_threshold`).
- Touching `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1`.
- Validator / ladder invariant #4 edit.
- `EVSE-SOLAR-STOP-CONDITIONS-1`.
- Persistence of either set or latch across reload.
- Per-EVSE `_fill_priority_would_hold` publication (rejected §5.4).

## 10. Open questions — orchestrator rulings (preserved from Rev 1 with Rev-2 notes)

- **Q1 (validator rule):** no validator entry; a unit-test import-time
  assertion covers it. Runtime also clamps via `max(0, soc_threshold - band)`
  (§5.3.2) so inversion is impossible. **PRESERVED.**
- **Q2 (latch TTL):** **no TTL. PRESERVED, with explicit grounding** — the
  latch is discharged daily by the INERT branch (D1 — FINDING 1 fix),
  immediately by cross-owner steal (D2), force-charge (D3), excess-solar
  toggle OFF (D4), and SOC-below-floor on every tick (D5). D1 is the daily
  discharge; without finding 1's fix Q2 would be wrong. With D1 in, a TTL is
  redundant and adds a time-coupled ingredient.
- **Q3 (sensor surface):** no new sensor; if an existing EC diagnostics
  attribute dict already lists fill-priority pause state, add one key
  `fill_priority_in_repause_latch` there; otherwise skip. **PRESERVED.**
- **Q4 (ride-along cycle):** standalone cycle. **PRESERVED.**

## 11. Tier-2-DB review framings

- **A — local correctness + edge cases:** band arithmetic, `max(0, …)` clamp,
  latch set/clear sites (D1-D5), FIRST vs RE-pause discrimination (via latch,
  not membership), kwarg-vs-module-attr monkeypatch surface (A4).
- **B — cross-coordinator / pause-owner integrity:** drain, arbitrage
  (hand-off at `:3156` with the updated `_fill_priority_would_hold`),
  grid_cap, load_shed, blind_window, force-charge, excess-solar all still
  consult `_paused_by_fill_priority` identically; INV-2 (first pause of a
  new fill window after inert interval, A9) and INV-3 (A3) hold.
- **C — test authority + plug-mirror parity + restart:** per-site mutation
  (comment out the latch pop at D1-D5 one at a time, confirm a specific test
  (A9/A8/A7/A6/A11) fails); plug mirror diffed line-for-line against EV path;
  reload-wipes-latch is tested and documented.

## 12. Report

- **Path:** `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_ev_fill_priority_soc_buffer.md`
- **Rev 2 scope:** plan edits only. Design direction unchanged. All seven
  FIX-REQUIRED findings + three LOWs resolved; orchestrator Q1-Q4 preserved,
  with Q2 explicitly grounded on finding-1's D1 clear site.
- **Tier:** Tier 2-DB.
- **Invariant (headline):** with SOC held in `[77, 80)` after a prior
  **SOC-reached** fill-priority resume and no competing owner / inert
  condition, no EV or plug transitions `_paused_by_fill_priority` in either
  direction. First pause below 80 (no live latch, including the morning
  after an inert overnight) and re-pause below 77 both still fire.

## 13. Review-resolution table

Review source: `docs/reviews/code-review/plan_ev_fill_priority_buffer_review.md`
(FIX-REQUIRED). Each finding verified against `energy_pool.py` at the cited
lines (see §1 "Code surveyed end-to-end"). All seven HIGH/MED findings and
three LOWs are addressed in-plan — no deferrals.

| # | Sev | Finding | Resolution (section) | Verified at |
|---|---|---|---|---|
| 1 | HIGH | Inert branch has no latch clear → stale latch suppresses next-day first pause | **D1** (§5.3.3): iterate `list(self._recently_released_by_fill_priority)` and pop every id inside the inert branch before `return actions`, on BOTH pools. Overnight repro walked explicitly in A9. Q2 "no TTL" reasserted BECAUSE D1 is the daily discharge. | EV `:2756-2766`, plug `:4441-4446` |
| 2 | HIGH | Named cross-owner-steal site `:2871-2888` is inside the `elif evse_id in self._paused_by_fill_priority` guard → unreachable in latched state | **D2** (§5.3.3): new check at the TOP of the per-id loop (EV `:2780`, plug `:4453`): if id is latched AND held by any peer owner (EV peers: `_paused_by_grid_cap/_battery_drain/_us/_arbitrage/_load_shed/_blind_window`; plug peers: `_paused_by_us/_battery_drain/_load_shed`), pop the latch and fall through. A8 asserts. | EV `:2780` loop head, plug `:4453` loop head; peers at `:2871-2879` (EV) / `:4518-4522` (plug) |
| 3 | MED | Force-charge clear sits inside `if evse_id in self._paused_by_fill_priority` guard; and A7 wording was self-contradictory | **D3** (§5.3.3) — move the latch pop OUTSIDE the membership guard (unconditional on `if force_charge_active:`). A7 restated: force-charge toggles on then off at SOC=79 → FP pauses at 79 on the next tick (first-pause edge). | EV `:2785-2793`, plug `:4458-4466` |
| 4 | MED | Latch set on forecast_decayed resumes, not only SOC resumes → forecast-only chatter | **§5.3.1** — producer discriminator is `resume_soc_met` (local bool at EV `:2866`, plug `:4516`); forecast_decayed resumes do NOT set the latch. A10 asserts. | EV `:2866`/`:2911-2912`, plug `:4516`/`:4551-4553` |
| 5 | MED | `_fill_priority_would_hold` is global/latch-blind → arbitrage hand-off at `:3156` could re-pause a latched EVSE; §8 producer list missed `:3156` and `:3525` | **§5.4** — `_fill_priority_would_hold` becomes latch-aware (false if any EVSE is latched); the single-site `any()` check is byte-identical on the no-latch path. Per-EVSE alternative rejected (reason stated). §5.5/§8 producer list adds `:3156`, `:3496`, `:3525`. A13 asserts. No conflict with `_paused_by_arbitrage` (untouched). | Producer `:2776-2778`; consumer `:3153`; hand-off `:3156`; release_all `:3496/:3525` |
| 6 | MED | Below-floor clear had no specified location/semantics | **D5** (§5.3.3) — explicit sweep at HEAD of `determine_fill_priority_actions` (both pools), runs every tick for every latched id regardless of `is_on` / excess-solar deferral / untrusted-SOC refusal. `soc is None` → no-op. A11 + A12 assert. | EV `:2780` head, plug `:4453` head |
| 7 | MED | Live criteria not discriminating (zero-rows satisfied by a vacuous day) | **§6 L1-L3 rewritten** — L2 is now a MANDATORY positive control (≥1 first pause below 80 on the same day). If L2 fails, L1/L3 report "not exercised" rather than PASS. | §6 L1/L2/L3 |
| 8 | LOW | Plug path latch ambiguity ("same latch") | **§5.3** — per-instance dict, one on `EVPool.__init__` (`:585`) and one on `PlugPool.__init__` (`:3634`). Spelled out. | `:585`, `:3634` |
| 9 | LOW | A4 monkeypatch hygiene — hollow if `energy_pool` has `from .energy_const import …` | **§6 A4** — builder MUST use either kwarg (`determine_fill_priority_actions(…, repause_band_pct=…)`, default = constant — matches `safety_margin_kwh` pattern) OR module-attribute access (`energy_const.DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT`). Bare `from .energy_const import …` is forbidden. | §6 A4 |
| 10 | LOW | Clamp wording — negative band not clamped if ever kwarg | **§5.3.2 + §7** — `effective_floor = max(0, soc_threshold - repause_band_pct)` at consumption. Negative band test added to §7. | §5.3.2, §7 |
