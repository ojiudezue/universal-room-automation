# PLANNING — EV fill-priority SOC re-pause band (EV-FILL-PRIORITY-SOC-CHATTER-1)

- Card: `EV-FILL-PRIORITY-SOC-CHATTER-1` (`docs/planning/kanban.data.yaml:126-161`)
- Thread: energy
- Tier: **Tier 3** (elevated 2026-10-15 — see §14). Four framing-disjoint
  code reviews (A local / B integration / C per-site mutation / D adversarial
  completeness) + two framing-disjoint plan reviews already run.
- **Rev 3 (2026-10-15d)** — resolves every finding from the two Tier-3 plan
  reviews (completeness F1-F8; build-prediction 1-13) appended to
  `docs/reviews/code-review/plan_ev_fill_priority_buffer_review.md`. All
  resolutions follow the orchestrator rulings dated 2026-10-15 (summarised
  below each in §13). Design direction (option A: resume at 80, re-pause only
  below 77) unchanged. The §5.4 global `any()` design is **WITHDRAWN** in
  favour of a per-charger peer term at the arbitrage hand-off gate.
- Operator decision 2026-10-15b: **APPROVED option A** — resume at 80%, re-pause
  only below 77%. Buffer applies ONLY after a prior SOC-reached resume.
- Prior approval 2026-10-15 ("see if config fixes these first") already
  discharged: `CONF_ENERGY_FILL_PRIORITY_SOC` (`energy_const.py:1077-1079`) is
  a single symmetric threshold.
- Not to be confused with `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` — different
  owner (`arbitrage`), different mechanism.

## 1. Institutional context verified

### Code surveyed end-to-end (Rev 3 — re-greps done against develop HEAD 3d34bba0f)
- `energy_const.py:1065-1094` — fill-priority defaults + conf key, drain/plug
  grace, surplus-pct knob. `safety_margin_kwh=1.0` kWh forecast-side band.
- `energy_const.py:1337-1504` — SOC-ladder validator; fill-priority invariant #4.
- `energy_pool.py` (EV path, `EVPool`):
  - `:585` init `_paused_by_fill_priority: set[str] = set()`.
  - `:589` `_fill_priority_solar_ok`, `:600` `_fill_priority_would_hold` —
    cross-tick publications read by the arbitrage release path.
  - `:2668-2921` `determine_fill_priority_actions`.
    - `:2756-2766` **INERT branch** (peak / off_peak-night / mid_peak-post-peak)
      — discards every id from `_paused_by_fill_priority` + returns. D1 clear.
    - `:2768-2772` pause condition `soc < soc_threshold and forecast_healthy`.
    - `:2773` `resume_soc_met = soc >= soc_threshold`.
    - `:2776-2778` publishes `_fill_priority_would_hold` (consumer `:3153`).
      **UNCHANGED in Rev 3** (per orchestrator ruling withdrawing the §5.4
      `any()` design).
    - `:2780` top of `for evse_id, config in self._evse.items()`.
    - `:2785-2793` force-charge branch — D3 unconditional pop lives here.
    - `:2836` excess-solar deferral.
    - `:2844-2864` pause action + membership add + dispatch claim.
    - `:2865-2919` resume branch. `:2866` gate = `resume_soc_met or
      forecast_decayed`; `:2871-2888` peer-held clear WITHIN FP-set guard
      (unaffected by Rev 3); `:2893-2896` untrusted-SOC refusal; `:2916`
      terminal discard — D4-adjacent latch SET site.
  - `:3120-3178` arbitrage release — peer gate `:3120-3136` already includes
    `_paused_by_fill_priority` (reader). Hand-off gate at `:3151-3155`;
    writer `self._paused_by_fill_priority.add(evse_id)` at `:3156`. **Rev 3
    adds ONE per-id peer term to the gate at :3151-3155** (see §5.4).
  - `:3491-3540` EV `release_all_fill_priority`. Writer `:3497`; untrusted-SOC
    **re-add** at `:3525` (misnamed "plug mirror" in Rev 2 — corrected here).
  - `:4018-4067` PLUG `release_all_fill_priority`. **Early `return` at
    `:4027-4032` when `grid_charge_on`.** Writer at `:4034` (discard), `:4054`
    (untrusted-SOC re-add). D4-plug clear MUST precede the `:4027` early
    return.
  - `:4384-4561` PLUG `determine_fill_priority_actions` on `PlugPool`.
    - `:3634` `_paused_by_fill_priority: set[str] = set()` init on `PlugPool`.
    - `:4392` `force_charge_active` is a KWARG parameter (not
      `_is_force_charge_active()` — EV-only method).
    - `:4441-4446` INERT branch — D1-plug clear.
    - `:4448-4451` pause / resume gates. Local var is `pause_conditions`
      (NOT `pause_conditions_global` — plug has no global publish).
    - `:4451` `resume_soc_met` computed here.
    - `:4453` top of `for entity_id in self._plugs:`.
    - `:4458-4466` force-charge branch (plug) — D3-plug.
    - `:4515-4559` resume branch. `:4516` resume gate; `:4529-4535` grid-charge
      M1 held-resume (`continue` — no resume happens; latch is NOT set).
    - `:4558` terminal discard — latch SET site (plug).
    - `:4537-4540` untrusted-SOC refusal (plug).
  - **Plug has NO `_fill_priority_would_hold`.** Builder MUST NOT add one.
- `energy.py`:
  - `:6582` `if not self._observation_mode:` — gates the WHOLE FP execution
    block. Else-branch (observation mode active) does NOT call FP. **F2
    discharge site lives in this else-branch (see §5.3.3 D6).**
  - `:6776-6845` EV call site; `:6817` invokes `determine_fill_priority_actions`
    with keyword args (no `repause_band_pct` today).
  - `:6842` calls `self._ev.release_all_fill_priority()` on excess-solar OFF.
  - `:6942-6970` plug call site. `:6968` calls plug `release_all_fill_priority`.
  - `:1845-1905` `_restore_registry_owner_lists` restores the EV FP set from
    KV (10h staleness guard). **The restore is a `_paused_by_fill_priority`
    WRITER and is now listed in §8.** The latch (`_recently_released_by_
    fill_priority`) is NOT persisted.
- `energy_pool_owners.py`:
  - `:234-339` EV pause-owner registry (tou, grid_cap, battery_drain, dp,
    arbitrage, load_shed, fill_priority, proactive_offpeak, blind_window).
  - `:310-312` EV FP owner declaration — `persistence_key=
    "evse_fill_priority_paused"`, `persistence_kind="list"`.
  - `:393-400` plug FP owner declaration — NO persistence key (RAM-only).
- `number.py` ~`:1840-1885` — `CONF_ENERGY_FILL_PRIORITY_SOC` number entity;
  minimum = 50.
- `sensor.py:10506`, `energy.py:1814, 5669, 5811, 7834, 8801, 8914, 10728,
  11348` — all additive READERS of `_paused_by_fill_priority` (classifier /
  diagnostics). Unaffected by an additive latch.

### Grep-verified existing hysteresis / band patterns
- Forecast-side band: `forecast_healthy >= X` vs `forecast_decayed <=
  X - safety_margin` (`energy_pool.py:2719-2731`, mirror `:4414-4424`).
  Ingredient: `DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH = 1.0 kWh`.
- `EV_PAUSE_DISPATCH_GRACE_SECONDS = 30.0` — unrelated.
- `EV_BATTERY_DRAIN_COOLDOWN_SECONDS = 3600` — different owner.

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

### Call-site activity-log row shape (B2#9 ground truth)
`_log_charger_actuation` (`energy.py` ~`:7860-7895`) writes rows with
`coordinator='energy_pool'`, `action=<service name>` (e.g. `switch.turn_off`),
`entity_id=<switch>`, and `description` of the form `kind=… pause_owners=…`.
**There is no `fill_priority_pause` / `fill_priority_release` row type.** L1
queries use `description LIKE '%fill_priority%'`, joined to recorder SOC.

## 2. The problem (measured)

With `fill_priority_soc = 80`:
- Pause when `SOC < 80` and solar healthy → EV turns off.
- SOC climbs on battery charge to 80 → `resume_soc_met` true → EV resumes.
- 11.6-11.7 kW EV draw drops SOC to 79 within one tick → re-pause.
- Loop at ~5-minute cadence (3 toggles/hour on 10-11 19:26:45Z garage_a; same
  pattern 10-09; 2 of 7 logged days).

## 3. Falsifiable invariant

> **INV-1 (no-chatter band — SOC-strict).** With `grid_charge_on=False`,
> `force_charge_active=False`, `fill_priority_inert=False`,
> `forecast_healthy=True`, and SOC held in the half-open band
> `[soc_threshold - repause_band_pct, soc_threshold)` after a prior
> **SOC-reached** fill-priority resume for that id (latch live, no intervening
> discharge event D1-D6 or restart), no EV or plug SHALL transition
> `_paused_by_fill_priority` membership in either direction on any tick.
> Boundary: **SOC exactly equal to `soc_threshold - repause_band_pct`
> (e.g. 77.0 with defaults) is INSIDE the band and does NOT pause**; SOC
> strictly below the floor (e.g. 76.9) pauses on the next tick. (Gate is
> `soc < effective_floor`.)
>
> **INV-2 (first pause unchanged).** The FIRST pause below `soc_threshold`
> for an id with no live latch remains UNCHANGED (`soc < soc_threshold`).
> This includes the first pause of a NEW fill window after an overnight
> inert interval, the first tick after an observation-mode exit, and the
> first tick after any D1-D6 discharge.
>
> **INV-3 (floor pause).** With SOC strictly below `effective_floor` and
> solar healthy, a pause SHALL fire on the next tick regardless of prior
> resume history. The band is a hysteresis, not a hold-off.
>
> **INV-4 (develop byte-identity on the no-latch path).** An **unlatched
> charger** behaves byte-identically to develop on EVERY path — the FP
> pause/resume gates, the arbitrage hand-off at `:3151-3155`, the arbitrage
> release at `:3168-3172`, the `release_all_fill_priority` sweep, the
> excess-solar deferral, and the per-pool restore. The only new reads of
> the latch are: (i) the FP-owner's own re-pause gate for its own latched
> ids, (ii) the arbitrage hand-off's one-term per-id peer check for that
> same id. No sibling-id behaviour changes.
>
> **Exemptions (preserve pre-existing develop behaviour — Rev 3 B2#7).**
> The invariant does NOT require releasing an FP claim in these legal
> develop paths:
> - **Untrusted-SOC refusal** (`:2893-2896`, plug `:4537-4540`) — FP keeps
>   its claim at SOC ≥ threshold.
> - **Plug `grid_charge_on` held-resume** (`:4529-4535` `continue`).
> - **Charge-onset deferral** (`_charge_on_or_defer` and
>   `_proactive_offpeak_holds` interactions) — FP's claim may linger one
>   tick while the ensure-on funnel defers.
> - **Peer-held release path** (`:2871-2888`, plug `:4515-4522`) — FP drops
>   its claim but the device stays OFF under another owner.
> - **Arbitrage hand-off membership** (`:3156`) persists until FP's next
>   tick resolves it. Rev 3 only adds a **per-id latch-peer term** at the
>   gate (`:3151-3155`) to suppress the hand-off for the latched id;
>   non-latched siblings are unaffected (INV-4).

Observations that would FALSIFY INV-1:
- A `switch.turn_off`/`turn_on` row pair in `ura_activity_log` with
  `coordinator='energy_pool'`, `description LIKE '%fill_priority%'`, same
  switch entity, within one tick, while recorder SOC stayed in `[77, 80)`
  AND no inert-period boundary intervened.
- `paused_by_fill_priority` attribute flipping present→absent→present within
  the same SOC band inside 10 minutes.

Discriminating observation (INV-1 vs INV-2): after an overnight off_peak-night
inert interval, a FIRST-tick pause at SOC=79 in the morning off_peak-daylight
slice MUST fire — if it does not, D1 regressed.

## 4. Knob ladder

| Knob | Name | Default | Rung | Why |
|---|---|---|---|---|
| Re-pause SOC band (pct) | `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT` | **3** | **Rung 1 (module constant)** | Stability margin, not per-deployment policy. `0` disables (legacy, kill switch). Change requires code review. |

`CONF_ENERGY_FILL_PRIORITY_SOC` unchanged (min=50, max=100, default=80 per
`number.py` ~`:1840-1885`).

## 5. Design (spec — do not build until this plan is accepted)

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
- **Re-pause** (latch live for the id): latch alone suppresses re-pause.
  The below-floor sweep (D5) is the SOLE authority on when the latch
  releases on SOC drop; the consumer does not re-evaluate the floor. (Build-
  prediction #6 resolution — one authority, mutation-testable.)

Resume edge at `:2773` / `:4451` UNCHANGED (`soc >= soc_threshold`).
Membership-based discrimination is wrong (terminal resume at `:2916`/`:4558`
clears the FP set) — a dedicated latch is required.

### 5.3 Latch — producer, consumers, discharge sites

Two sibling latches, one per pool class:

```
# On EVPool.__init__ next to self._paused_by_fill_priority (:585):
self._recently_released_by_fill_priority: dict[str, float] = {}
# On PlugPool.__init__ next to its sibling set (:3634):
self._recently_released_by_fill_priority: dict[str, float] = {}
```

Value = `_time.monotonic()` at set time (diagnostics only; dict membership
is the gate). **RAM-only. NOT persisted. NOT registered as an
`OwnerDeclaration`** — the latch is not a pause owner and must not leak into
`_stronger_peer_holds` or the classifier (B1#4 build-prediction fix,
orchestrator ruling: do NOT persist).

Consequence of RAM-only: on restart, the EV FP set IS restored
(`energy_pool_owners.py:310-312`, `energy.py:1845-1905`) but the latch is
not. For any id in the restored FP set that would be in the re-pause band
on the first post-boot tick, the FP owner takes **at most one extra toggle
per restart** (one first-pause edge). Acceptable — the restore itself is a
producer and is listed in §8.

#### 5.3.1 Producer (resume-reason discriminator — B1 F4)

ONLY the SOC-reached terminal resume sets the latch. Discriminator = the
local `resume_soc_met` bool computed at `:2773` (EV) / `:4451` (plug).
(B2#10: it is COMPUTED at :2773/:4451 and READ at :2866/:4516.)

- EV path, immediately before `:2916` terminal discard:
  ```
  if resume_soc_met:
      self._recently_released_by_fill_priority[evse_id] = _time.monotonic()
  self._paused_by_fill_priority.discard(evse_id)
  ```
- Plug path, immediately before `:4558` terminal discard: mirror block
  (same `if resume_soc_met: ...[entity_id] = ...`).
- `forecast_decayed`-only resumes DO NOT set the latch; the forecast side
  carries `DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH` hysteresis.
- Grid-charge M1 held-resume at `:4529-4535` sets nothing (the `continue`
  is pre-resume; A6 asserts).

#### 5.3.2 Consumer (one-authority design — B2#6)

Inside `determine_fill_priority_actions`, replacing the pause-condition
expression at `:2844` (EV) and `:4493` (plug):

```
is_latched = evse_id in self._recently_released_by_fill_priority
if is_latched:
    pause_this_tick = False
else:
    pause_this_tick = pause_conditions_global  # EV; plug: pause_conditions
```

The excess-solar deferral (`:2836`) and the `_fill_priority_would_hold`
publish (`:2776`) continue to use the GLOBAL `pause_conditions_global` /
`pause_conditions` — this swap is **scoped to the pause gate only** (B2#11
build-prediction fix).

The consumer does NOT re-check the floor. D5 is the sole authority that
pops the latch when SOC drops below `effective_floor`; after D5 runs, a
latched id either has SOC ≥ `effective_floor` or `soc is None`. (B2#6 fix:
one authority, mutation-testable — see C3 below.)

Band clamp (LOW 10): computed once at D5:
`effective_floor = max(0, soc_threshold - repause_band_pct)`.

#### 5.3.3 Discharge sites

Every discharge site pops the latch via
`self._recently_released_by_fill_priority.pop(id, None)` (or
`.clear()` for sweep sites).

| # | Site (EV) | Site (plug) | When latch cleared | Rationale |
|---|---|---|---|---|
| D1 | **Inert branch top**, `:2763` loop before `return actions` | `:4443` loop before `return actions` | For every id in `list(self._recently_released_by_fill_priority)`, pop. | Peak / off_peak-night / mid_peak-post-peak run DAILY → inert branch is the daily discharge. Without D1, a 13:00 latch survives overnight and suppresses the 08:00 next-day first pause at SOC 79. |
| D2 | **Top of per-id loop**, inserted at `:2781` immediately after `:2780 for evse_id, config in self._evse.items():` | `:4454` top of `for entity_id in self._plugs:` | If id is latched AND held by any peer owner (see peer set below), pop the latch; fall through to normal processing. | A steal starts a new session — the latch's "most recent resume was SOC-reached" invariant no longer applies. |
| D3 | Force-charge branch, `:2785` — **unconditional `pop` immediately after `if force_charge_active:`, OUTSIDE the `if evse_id in self._paused_by_fill_priority` guard** | `:4458` mirror (plug `force_charge_active` is the KWARG per `:4392`) | Any time force-charge activates for the id. | Force-charge must reset FP state regardless of FP-set membership so the next SOC drop below `soc_threshold` after force-charge clears pauses on the FIRST tick (first-pause edge). |
| D4 | `release_all_fill_priority` EV — `self._recently_released_by_fill_priority.clear()` at the **head of the function (:3493)**, BEFORE any writer. | `release_all_fill_priority` plug — `self._recently_released_by_fill_priority.clear()` **BEFORE the `if grid_charge_on: return` early return at `:4027-4032`** (i.e. inserted at `:4026`). | Excess-solar toggle OFF path (called from `energy.py:6842` / `:6968`). | FP is not called at all after `release_all` returns; the latch must not survive into the next toggle-ON window. The plug early return at `:4027` means the clear MUST precede it, else the latch survives a toggle-OFF while grid-charge is on and suppresses the first pause at the next toggle-ON. (B2#3 fix.) |
| D5 | **Below-floor sweep** — dedicated loop at the HEAD of `determine_fill_priority_actions`, **AFTER the inert branch's `return` (so unreachable if inert) but BEFORE `pause_conditions_global` and the `_fill_priority_would_hold` publish at `:2776`** (EV sweep inserted between `:2766` and `:2768`; plug sweep inserted between `:4446` and `:4448`). | mirror | For every id in `list(self._recently_released_by_fill_priority)`: if `soc is not None and soc < effective_floor`, pop. If `soc is None`, leave untouched (no-op). | Band floor is satisfied; next pause must fire normally. Running for OFF chargers too (car full / unplugged) ensures a latch doesn't survive an afternoon of SOC decay below floor. D5 is the SOLE authority (B2#6) — consumer no longer re-checks floor. Pinned to a single location (B2#5) so `_fill_priority_would_hold` publishes with latch state already correctly settled for the tick. |
| D6 | **Observation-mode discharge** at `energy.py:6582` else-branch (when `self._observation_mode is True`): `self._ev._recently_released_by_fill_priority.clear()` and `self._plug._recently_released_by_fill_priority.clear()`. | — | Every tick during observation mode. | Observation mode bypasses the WHOLE FP block (energy.py:6582 gate), so D1 and D5 never run. A latch set before observation mode would otherwise survive a multi-day observation window. Simplest reachable site is the else-branch of the existing `if not self._observation_mode:` gate (B1 F2 fix); runs once per tick for the duration of observation mode and discharges cleanly on exit by having nothing to clear. |

**Peer set for D2 (orchestrator ruling B1 F4 — dp and proactive_offpeak count
as steals):**
- EV peers: `_paused_by_grid_cap`, `_paused_by_battery_drain`, `_paused_by_us`,
  `_paused_by_arbitrage`, `_paused_by_load_shed`, `_paused_by_blind_window`,
  `_paused_by_dp`, `_proactive_offpeak_holds`.
- Plug peers: `_paused_by_us`, `_paused_by_battery_drain`, `_paused_by_load_shed`,
  `_proactive_offpeak_holds`.

**Prune on EVSE removal (B1 F7):** `_prune_removed_evses`
(`energy_pool.py:1221`) pops the latch for each removed id. Plug analogue
pops the plug latch. (Harmless today — `self._evse` iteration bounds reads —
but recorded to keep framing D from relitigating it.)

**No car-session discharge is specified (B1 F8 — accepted):** a latch set
at 08:30 for an EVSE that goes OFF (car leaves) survives to a 15:00 replug
at SOC 78 (D5 only fires below 77). Cost bounded ≤ `repause_band_pct` SOC.
Intended.

A terminal RESUME on `resume_soc_met` RE-SETS the latch (producer); any
subsequent SOC drop below `effective_floor` clears it via D5. All other
pause-owner reads of `_paused_by_fill_priority` (`:2245, :2602, :3135,
:3452, :3547, :3882, :3987` + the `energy.py` / `sensor.py` additive
readers listed in §1 and §8) are UNAFFECTED — the new latch is additive.

### 5.4 Arbitrage hand-off ruling — per-charger peer term (B1 F1 / B2 #2)

**ORCHESTRATOR RULING:** the global `any()` design in Rev 2 is
**WITHDRAWN**. Reason: `_fill_priority_would_hold` is read ONCE per tick at
`:3153` and consumed per-id at the hand-off (`:3151-3155`); a global `any()`
would make `would_hold=False` whenever ANY EVSE is latched, which turns off
the hand-off for the **unlatched sibling** garage charger — regressing the
EV-ARBITRAGE-RELEASE-IGNORES-FILL-PRIORITY-1 flap for siblings (two-charger
house is a legal config).

**Rev 3 ruling:** keep `_fill_priority_would_hold` at `:2776-2778`
**UNCHANGED** (global). Add ONE per-id peer term to the hand-off gate at
`energy_pool.py:3151-3155`:

```
if (
    not state["is_on"]
    and self._fill_priority_would_hold
    and not self._is_force_charge_active()
    and evse_id not in self._recently_released_by_fill_priority  # NEW
):
    self._paused_by_fill_priority.add(evse_id)
    ...
```

Properties:
- **Per-charger.** Only the latched id is exempted from the hand-off; the
  unlatched sibling continues to be handed off exactly as develop does.
- **Byte-identical on the no-latch path.** `evse_id not in {}` is always
  `True` → the compound gate is unchanged (INV-4).
- **No new publication.** Zero new writers; latch is read, not written.
- **`_fill_priority_would_hold` publisher at `:2776` is unmodified.** Plug
  has no `_fill_priority_would_hold` (B2#10) — do NOT add one.

**Leave `_fill_priority_would_hold` publisher (:2776) UNCHANGED.** The
Rev-2 proposal to make the publisher latch-aware is withdrawn (orchestrator
ruling).

**Note on D2 interaction.** D2 pops the latch whenever arbitrage owns the
id (`_paused_by_arbitrage` is a D2 peer). A latched id can therefore almost
never reach the hand-off; the new peer term is defence-in-depth for the
narrow window where arbitrage releases on the SAME tick as the latch
reaches the arbitrage-release call site (ordering: D2 runs inside
`determine_fill_priority_actions`, arbitrage runs separately in
`determine_arbitrage_actions`). Keeping the term is cheap (one token) and
makes the gate self-documenting under per-site mutation (framing C).

### 5.5 `_paused_by_fill_priority` producer list (complete — B2#4 restore,
B1 F6 corrected labels)

Writers (every file:line):
- `energy_pool.py:2764` (EV FP inert `.discard`), `:2787` (force-charge
  discard), `:2819` (manual override discard), `:2851` (pause add), `:2880`
  (peer steal discard inside FP guard), `:2916` (terminal discard).
- `energy_pool.py:3156` (**arbitrage hand-off** — writer OUTSIDE FP).
- `energy_pool.py:3497` (EV `release_all` discard), `:3525` (EV `release_all`
  **untrusted-SOC re-add** — misnamed "plug mirror" in Rev 2; corrected).
- `energy_pool.py:4034` (plug `release_all` discard), `:4054` (plug
  `release_all` **untrusted-SOC re-add**). The plug `release_all` is
  `:4018-4067` (NOT `:3525`).
- `energy_pool.py:4444, :4460, :4486, :4501, :4523, :4558` — plug FP owner.
- **`energy.py:1845-1905` `_restore_registry_owner_lists`** — the KV restore
  of `evse_fill_priority_paused` (EV only; plug FP set is RAM-only). This
  WRITER was missing from Rev 2 §8. (B2#4 fix.)

Writers of `_recently_released_by_fill_priority` (NEW, this cycle):
- EV terminal `resume_soc_met` branch adjacent to `:2916`.
- Plug terminal `resume_soc_met` branch adjacent to `:4558`.
- D1-D6 are POPPERS/CLEARERS only; never SET.
- No consumer modifies the dict.

### 5.6 Restart / reload behaviour (B2#4 corrected)

- **EV `_paused_by_fill_priority` set IS persisted** (KV, `persistence_key=
  "evse_fill_priority_paused"`, 10h staleness guard). The restore at
  `energy.py:1845-1905` is a writer (§5.5).
- **Plug `_paused_by_fill_priority` set is RAM-only** (no persistence key
  at `energy_pool_owners.py:393-400`).
- **Both latches (`_recently_released_by_fill_priority`) are RAM-only.** Not
  persisted. Not registered as owner declarations.

Consequence: after a restart, a resumed EV in the band comes back as "latch
cold" — if the restored FP set does not already hold it, FP's next tick takes
one first-pause edge toggle inside the band. **At most one extra toggle per
restart.** Acceptable; the restart test asserts exactly this.

### 5.7 Validator / ladder invariant #4

Unaffected; a unit test asserts
`0 <= DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT < DEFAULT_FILL_PRIORITY_SOC`
at import time (Q1 orchestrator ruling preserved).

## 6. Acceptance criteria

| ID | Criterion | Verify |
|---|---|---|
| A1 | INV-1 holds in-suite: forecast_healthy, no peers, SOC walked 80→79→80→79 over four ticks, prior SOC-reached resume → zero membership transitions after first resume. **Test calls `determine_fill_priority_actions` WITHOUT `repause_band_pct=` (uses production default = 3).** | Test — pause/release counts flat |
| A2 | INV-2 holds: fresh EVSE at SOC=78, no live latch, pauses on tick 1 | Test |
| A3 | INV-3 (floor) holds: post-resume at SOC=76.9 pauses on tick 1; **SOC=77.0 does NOT pause** (gate `soc < effective_floor`; B2#1 fix). Mutation-testable: commenting out the D5 pop at `soc < 77` makes A3 FAIL (because consumer no longer re-checks floor — one authority). | Test |
| A4 | Band=0 reproduces legacy chatter. Band value reaches production via **module-attribute access at call time** (`energy_const.DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT`) OR via a kwarg whose default is resolved by reading the module attribute at call time (NOT a bare `from .energy_const import X` captured at import). The builder MUST pick one and A4's monkeypatch must target the SAME surface. | Test — monkeypatch the chosen surface; assert ≥1 pause/release pair within 2 ticks across SOC 80↔79 |
| A5 | Band=100 (band > threshold, clamped to 0 at D5) does NOT prevent first pause: SOC=50 fresh EVSE pauses | Test |
| A6 | Plug mirror parity (EV + plug paths show matching ledger shape); grid_charge_on M1 held-resume at `:4529-4535` does NOT set the latch | Test — both pools |
| A7 | **Force-charge clears the latch unconditionally** (D3): with latch live at SOC=79, flip `force_charge_active=True` for one tick then False — on the next tick, SOC still 79, FP pauses at 79 (first-pause edge, legacy `soc < soc_threshold`) | Test |
| A8 | Cross-owner steal clears the latch at D2: drain pauses the EVSE at SOC=79 while latch live → next tick with drain still owning: latch popped. When drain releases at SOC=78: FP pauses on the first-pause edge. **dp and `_proactive_offpeak_holds` also count as steals (B1 F4).** | Test — one case per peer in the D2 peer set |
| A9 | `fill_priority_inert` releases cleanly AND discharges the latch (D1): set latch at 13:00 → enter off_peak-night → inert branch runs → latch dict empty on exit → simulated morning off_peak-daylight at SOC=79 pauses on tick 1 (overnight repro from B1 F1). **Test calls `determine_fill_priority_actions` WITHOUT `repause_band_pct=`.** | Test — explicit day-boundary oracle |
| A10 | Forecast decay/recover does not spuriously latch: SOC=78, forecast_decayed → resume (reason=forecast decayed) → latch NOT set → forecast recovers healthy at SOC=78 → FP pauses on tick 1 (legacy edge) | Test |
| A11 | D5 below-floor sweep runs for OFF chargers: EVSE OFF, latch live, SOC drops 79→76 while OFF → latch dict empty next tick | Test |
| A12 | D5 no-op on SOC=None: latch live, SOC source None for one tick → latch unchanged → SOC recovers to 78 → re-pause gate still gated by latch (no toggle) | Test |
| A13 | Arbitrage hand-off respects the per-id latch: drive the REAL arbitrage release leg (`determine_arbitrage_actions`, hand-off at `:3151-3155`). **Two-EVSE case (B1 F1 / B2 #2):** garage_a latched at SOC 78 ON (car full); garage_b arbitrage-paused at SOC 78; off_peak daylight; arbitrage releases → `:3151-3155` adds garage_b to `_paused_by_fill_priority` (unchanged develop behaviour, INV-4) and does NOT add garage_a (new peer term, INV-1). No mock — exercise the real coordinator path. | Test — real `determine_arbitrage_actions` + real FP tick |
| A14 | Restart (B2#4): seed `evse_fill_priority_paused` KV with an id at SOC in the band; call `_restore_registry_owner_lists`; latch dict is empty post-restore; next FP tick resolves normally (at most one first-pause-edge toggle). | Test |
| A15 | Observation-mode discharge (B1 F2 / D6): set latch at 13:00; enter observation mode for 10 ticks; exit → latch dict empty; at SOC 79 on the next normal tick, FP pauses (first-pause edge). | Test — fakes `energy.py` observation-mode branch |
| A16 | Prune on EVSE removal (B1 F7): remove an id with latch live → `_prune_removed_evses` pops the latch for that id. | Test |
| L1 | **Live (first charging day post-deploy, with L2 positive control satisfied):** `ura_activity_log` rows with `coordinator='energy_pool'` AND `description LIKE '%fill_priority%'` AND `entity_id=<garage switch>`, joined to recorder SOC history: ZERO `switch.turn_off` → `switch.turn_on` within 10 min where recorder SOC stayed in `[77, 80)`. **Report breakdown by `pause_owners` in description** so a non-fill-priority toggle (arbitrage/drain) is not misread as an FP regression. | DB query (B2#9: real row shape) |
| L2 | **Live POSITIVE CONTROL (mandatory for L1/L3 to be non-vacuous — B1 F7 accepted):** on the same day, ≥1 row with `description LIKE '%fill_priority%'` matching a FIRST-pause pattern (switch turn_off while recorder SOC was `< 80` AND no fill-priority turn_on row for that id in the prior 15 min). If zero, report L1/L3 as "not exercised" rather than PASS. | DB query |
| L3 | **Live (conditional on L2):** `anomaly_log.ev_toggle_tripwire` rows for the first full charging day = 0 **attributable to fill_priority** (filter by `pause_owners` in the tripwire's own description; a rung-1 tripwire row is NOT a regression of this cycle). | Same query as `EC-EV-TOGGLE-TRIPWIRE-1` disposition, with pause-owner filter |

## 7. Config-extreme tests (B2#13 — with expected values)

Defaults: `fill_priority_soc=80`, `repause_band_pct=3`, so `effective_floor=77`.
`fill_priority_soc` minimum per `number.py` ~`:1857` is **50**.

| Config | effective_floor | SOC 50 fresh | SOC 49 fresh | SOC 47 latched | SOC 46.9 latched | SOC 77.0 latched | SOC 76.9 latched |
|---|---|---|---|---|---|---|---|
| soc=80, band=3 (defaults) | 77 | pause (A2) | pause | n/a | n/a | **no transition (A3)** | **pause (A3)** |
| soc=80, band=0 (kill switch) | 80 | pause | pause | n/a | n/a | pause (legacy) | pause (legacy) |
| soc=80, band=100 (clamped to 0 → floor 0) | 0 | pause (A5) | pause | — | — | n/a (latched below floor impossible unless SOC<0) | — |
| soc=80, band=−5 (clamped to 0 — defensive) | 0 | pause | pause | — | — | — | — |
| soc=50 (slider min), band=3 | 47 | pause | pause (first-pause edge below threshold) | **no transition** | **pause** | n/a | n/a |
| soc=50, band=0 | 50 | first-pause edge | pause | pause (legacy) | pause (legacy) | n/a | n/a |

Notes:
- `band=0` is byte-identical to develop (A4 kill-switch).
- `band ≥ threshold`: `effective_floor` clamps to 0; while latched above 0,
  no re-pause fires. Reachable only through the kwarg (constant is 3).
- `band < 0`: `max(0, …)` clamps to 0; floor = threshold → effectively legacy
  behaviour (every tick below threshold pauses, latched or not — D5 pops the
  latch on every tick where SOC < threshold).
- Forecast unhealthy during latch → A10.
- Grid-charge ON during plug resume (M1) → A6; no latch set.

## 8. Producer / Consumer map (updated — B1 F6 corrected, B2#4 restore added)

### `_paused_by_fill_priority` (existing)
- **Producers (writers):** `energy_pool.py:2764, :2787, :2819, :2851, :2880,
  :2916, :3156` (arbitrage hand-off), `:3497, :3525` (EV `release_all`
  discard + untrusted-SOC re-add), `:4034, :4054` (plug `release_all` discard
  + untrusted-SOC re-add), `:4444, :4460, :4486, :4501, :4523, :4558`.
  **`energy.py:1845-1905` KV restore** (EV only).
- **Consumers (behavioural readers in `energy_pool.py`):** `:2245, :2602,
  :3135, :3268, :3413, :3452, :3547, :3882, :3987` — precedence gates in
  drain / arbitrage / load_shed / blind_window / cooldown.
- **Consumers (additive display / classifier readers):** `sensor.py:10506`,
  `energy.py:1814, 5669, 5811, 7834, 8801, 8914, 10728, 11348`. Unaffected by
  the latch.
- **Dependency health:** SOC via `BatteryStrategy.soc` + Envoy LKG fallback
  (shipped v5.103.39); forecast via `WeatherProviderManager`.

### `_fill_priority_would_hold` (existing — UNCHANGED in Rev 3)
- **Producer:** `energy_pool.py:2776-2778` — global, latch-blind. Rev 3
  does NOT modify this publisher (orchestrator ruling withdrawing §5.4
  `any()` design).
- **Consumer:** `energy_pool.py:3153` (arbitrage release hand-off), guarded
  per-id by the new latch peer term at `:3151-3155` (§5.4).

### `_recently_released_by_fill_priority` (NEW)
- **Producer:** terminal resume branch where `resume_soc_met is True` (EV
  `:2916` adjacency + plug `:4558` adjacency). No other owner may set it.
- **Consumers:**
  - Re-pause gate in `determine_fill_priority_actions` (per-id, EV + plug) —
    the ONLY behavioural consumer that changes decisions.
  - Arbitrage hand-off peer term at `:3151-3155` (per-id, read-only).
- **Dischargers (pop/clear):** D1 (inert), D2 (cross-owner steal at loop
  top), D3 (force-charge, unconditional), D4 (`release_all_fill_priority`
  head), D5 (below-floor sweep, every non-inert tick), D6 (observation-mode
  else-branch at `energy.py:6582`), prune on EVSE removal.
- **Trust tier:** behavioural (controls dispatch); not a display value.
- **Persistence:** RAM-only. Not registered as `OwnerDeclaration`.

## 9. Non-goals

- Minimum-hold timer (parked).
- Changing `fill_priority_soc` default (80 stays; min 50 unchanged).
- Changing resume condition (still `soc >= soc_threshold`).
- Touching `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1`.
- Validator / ladder invariant #4 edit.
- `EVSE-SOLAR-STOP-CONDITIONS-1`.
- Persistence of either latch across reload.
- Per-EVSE `_fill_priority_would_hold` publication.
- Adding `_fill_priority_would_hold` to plug (B2#10).
- Car-session discharge (accepted B1 F8 — latch survives a session gap).
- Making the latch a registered `OwnerDeclaration` (explicitly forbidden,
  B1 F3 orchestrator ruling).

## 10. Open questions — orchestrator rulings (preserved from Rev 1/2 with
Rev-3 notes)

- **Q1 (validator rule):** no validator entry; a unit-test import-time
  assertion covers it. Runtime also clamps via `max(0, soc_threshold - band)`
  (§5.3.2 / D5) so inversion is impossible. **PRESERVED.**
- **Q2 (latch TTL):** **no TTL.** Discharged by D1 (inert daily), D2
  (cross-owner steal), D3 (force-charge), D4 (`release_all` toggle-OFF), D5
  (SOC-below-floor every non-inert tick), D6 (observation-mode every tick in
  that mode), and `_prune_removed_evses`. D1 is the daily anchor; D6 covers
  the one path (observation mode) where FP is not called at all. **PRESERVED.**
- **Q3 (sensor surface):** no new sensor. **PRESERVED.**
- **Q4 (ride-along cycle):** standalone cycle. **PRESERVED.**

## 11. Tier-3 code-review framings

- **A — local correctness + edge cases:** band arithmetic, `max(0, …)` clamp
  at D5, latch set/clear sites D1-D6, FIRST vs RE-pause discrimination (via
  latch, not membership), module-attribute vs kwarg-at-call-time surface
  (A4), SOC=77.0 boundary (A3), SOC=None no-op (A12), prune (A16).
- **B — integration / state-machine integrity:** drain, arbitrage (hand-off
  at `:3151-3155` with the new per-id peer term — INV-4 byte-identity for
  unlatched siblings), grid_cap, load_shed, blind_window, force-charge,
  excess-solar, observation-mode, restart (A14/A15 assert both). INV-2
  (first pause of new fill window after inert interval, A9) and INV-3 (A3)
  hold. All Rev-3 §3 exemptions documented.
- **C — test authority via REAL per-site source mutation:** per-site
  mutation drill — neuter each of D1/D2/D3/D4/D5/D6 and the latch-set site
  one at a time (comment out the single pop/clear/set), run suite, confirm a
  SPECIFIC test fails (A1→producer; A3→D5; A7→D3; A8→D2; A9→D1; A14→restore
  symmetry; A15→D6). Any site whose mutation leaves the suite green is an
  untested site. **Mutation-ordering invariant:** because D5 is the sole
  authority for the floor pop (consumer no longer re-checks floor), D5's
  mutation MUST fail A3; neutering only the consumer floor-check cannot
  pass A3 (there is no consumer floor-check). Plug mirror diffed line-for-
  line against EV path; A13 drives the REAL arbitrage path (no mock).
- **D — adversarial completeness / diff-blind:** state INV-1..INV-4 in
  falsifiable form; re-enumerate the ENTIRE emission/decision surface
  (writers of `_paused_by_fill_priority` across `energy_pool.py` +
  `energy.py` restore; readers of the new latch at the FP gate and the
  arbitrage hand-off; D1-D6 reachability under every call-gate — inert,
  excess-solar OFF, observation mode, restart). Legal-config repros for
  every proposed leak (e.g. "two chargers, garage_a latched + ON, garage_b
  arbitrage-paused, off_peak daylight, SOC 78: arbitrage release must hand
  garage_b to FP; must NOT hand garage_a").

## 12. Report

- **Path:** `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_ev_fill_priority_soc_buffer.md`
- **Rev 3 scope:** plan edits only. Design direction unchanged; the §5.4
  `any()` design withdrawn in favour of a per-charger peer term at
  `:3151-3155`. All completeness F1-F8 and build-prediction 1-13 findings
  resolved; orchestrator rulings applied verbatim.
- **Tier:** Tier 3.
- **Headline invariants:** INV-1 (no transition in `[77, 80)` while latched)
  with SOC=77 INSIDE the band (no pause); INV-2 (first pause unchanged);
  INV-3 (SOC<77 pauses); INV-4 (unlatched charger byte-identical to develop
  on every path).

## 13. Review-resolution table (Rev 3)

Review sources: `docs/reviews/code-review/plan_ev_fill_priority_buffer_review.md`,
"Tier 3 plan review 1 (completeness)" F1-F8 and "Tier 3 plan review 2
(build-prediction)" 1-13. Each resolution verified against develop HEAD
3d34bba0f at the cited lines (see §1).

### Completeness review 1 (F1-F8)

| # | Sev | Finding | Resolution | Orchestrator ruling applied | Verified at |
|---|---|---|---|---|---|
| F1 | MED | §5.4 global `any()` regresses unlatched sibling at arbitrage hand-off | **§5.4 rewritten.** Withdraw `any()`; `_fill_priority_would_hold` publisher at `:2776-2778` UNCHANGED. Add ONE per-id peer term at the hand-off gate `:3151-3155`: `and evse_id not in self._recently_released_by_fill_priority`. Byte-identical for unlatched ids (INV-4). A13 extended to the two-EVSE case. | Per-charger check at `:3151-3155`; leave `_fill_priority_would_hold` (:2776) unchanged; withdraw `any()`. | `:3151-3155`, `:2776-2778` |
| F2 | MED | Observation mode bypasses D1/D5 → stale latch survives | **D6 added** (§5.3.3). Site: `energy.py:6582` else-branch (observation-mode active): `self._ev._recently_released_by_fill_priority.clear()` and plug sibling. Runs every tick during observation mode; cleanly empty on exit. A15 asserts. | Clear all latches when FP block is skipped for observation mode at `energy.py` ~6582; simplest reachable site is the existing else-branch; justified in §5.3.3 D6. | `energy.py:6582` |
| F3 | MED | §5.6 "RAM-only" is false — EV FP set is KV-persisted; forbid registering latch as owner | **§5.3 and §5.6 corrected.** EV FP set persistence via `energy_pool_owners.py:310-312` + restore `energy.py:1845-1905` acknowledged (new §8 writer). Latch is RAM-only, NOT persisted, NOT an `OwnerDeclaration`. Consequence: at most one first-pause-edge toggle per restart in the band. A14 asserts. | Do NOT persist the latch; state consequence (one extra toggle per restart in band); state the restore IS a producer; do NOT register latch as pause owner. | `energy_pool_owners.py:310-312`, `energy.py:1845-1905` |
| F4 | LOW | D2 peer set omits `_paused_by_dp` and `_proactive_offpeak_holds` | **D2 peer set extended** (§5.3.3): EV peers now include `_paused_by_dp` and `_proactive_offpeak_holds`; plug peers include `_proactive_offpeak_holds`. A8 extended per-peer. | dp and `_proactive_offpeak_holds` count as steals (clear). | §5.3.3 peer list |
| F5 | LOW | Plug D4 placement before `grid_charge_on` early return | **D4-plug anchor pinned to `:4026`** — the `.clear()` is inserted BEFORE the `if grid_charge_on: return` at `:4027-4032`. §5.3.3 says so explicitly. | Plug release-all clear goes BEFORE the grid-charge early return (~4019/~4027). | `:4019-4032` |
| F6 | LOW | `:3525` label is wrong ("plug mirror"); readers list incomplete | **§5.5 and §1 corrected.** `:3525` is the EV `release_all_fill_priority` **untrusted-SOC re-add**. Plug `release_all` is `:4018-4067` (writers `:4034`, `:4054`). Additive readers (`sensor.py:10506`, `energy.py:1814/5669/5811/7834/8801/8914/10728/11348`) enumerated in §8. | Fix the `:3525` mislabel. | §5.5, §8 |
| F7 | LOW | Latch not pruned on EVSE removal | **§5.3.3 "Prune" note added** — `_prune_removed_evses` (`energy_pool.py:1221`) pops the latch for each removed id (plug analogue). A16 asserts. | Document as accepted. | `:1221` |
| F8 | LOW | No car-session discharge | **§5.3.3 and §9 state this is intended.** Latch survives a session gap; cost ≤ `repause_band_pct` SOC. | Document as accepted. | §5.3.3, §9 |

### Build-prediction review 2 (#1-#13)

| # | Sev | Finding | Resolution | Orchestrator ruling applied | Verified at |
|---|---|---|---|---|---|
| 1 | HIGH | §7 "SOC exactly 77 pauses" contradicts INV-1 | **§7 config-extremes table corrected and INV-1 restated.** SOC=77.0 is INSIDE `[77, 80)` → **no transition** while latched; SOC=76.9 pauses (INV-3). A3 updated. | SOC 77 does NOT pause; 76.9 does; fix §7 and INV-1 consistently. | §3 INV-1, §6 A3, §7 |
| 2 | HIGH | Global `any()` regresses unlatched sibling (same as F1) | **§5.4 rewritten** — per-charger peer term at `:3151-3155`; publisher `:2776` unchanged. A13 covers two-EVSE case. | (See F1.) | `:3151-3155` |
| 3 | HIGH | D4 plug anchor wrong (`:3525` is EV); early return at `:4027` | **D4-plug anchor pinned to `:4026`** (BEFORE the `:4027` early return). §5.3.3 and §8 corrected. | Plug clear BEFORE grid-charge early return; fix `:3525` mislabel. | `:4019-4032`, `:3525` |
| 4 | MED | §5.6 claim that FP set is RAM-only is false | **§5.3 and §5.6 corrected** (see F3). KV restore acknowledged; latch stays RAM-only. A14 asserts. | Do NOT persist latch; state consequence; restore IS a producer. | `energy_pool_owners.py:310-312`, `energy.py:1845-1905` |
| 5 | MED | D5 position contradicts itself ("HEAD" vs `:2780`-ish) | **D5 pinned to a single location** — inserted between `:2766` and `:2768` (EV) / `:4446` and `:4448` (plug): AFTER the inert `return`, BEFORE `pause_conditions_global` and the `_fill_priority_would_hold` publish. | (B2#5 — single location pinned; publisher reads latch state settled for the tick.) | §5.3.3 D5 |
| 6 | MED | D5 and consumer floor-check redundant → C mutation drill reports untested | **One authority: D5 is the sole floor pop; the consumer is `pause_this_tick = False if is_latched else legacy`** — the consumer does NOT re-check the floor. A3 mutation-anchored to D5 (neutering D5 fails A3; there is no consumer floor check to neuter). | Name ONE authority between D5 and the latched floor check; remove redundancy; each site mutation-testable. | §5.2, §5.3.2, §5.3.3 D5 |
| 7 | MED | Tier invariant clause (1) is false on develop | **Exemption list added to §3** — untrusted-SOC refusal, plug grid_charge_on hold, charge-onset deferral, peer-held release path, arbitrage hand-off membership. Added **INV-4** ("unlatched charger byte-identical to develop on every path"). "Forecast healthy" dropped from (1); it is irrelevant to resume. | List legitimate develop exemptions; add "an unlatched charger behaves byte-identically to develop on every path". | §3 INV-1..INV-4 + exemptions |
| 8 | MED | A4 contradicts itself; hollow if bare `from … import …` | **A4 rewritten** — band value reaches production via module-attribute access at call time (`energy_const.X`) OR kwarg whose default is RESOLVED at call time by reading the module attribute (not a bare import captured at import time). A1 and A9 call `determine_fill_priority_actions` WITHOUT `repause_band_pct=` (exercise shipped default). At least one test drives the `energy.py:6817` call site (new A-test in C framing). | Band reaches production via module-attribute access (energy_const.DEFAULT_... read at call time) OR kwarg default resolved at call time; A1/A9 call without kwarg; one test drives energy.py ~6817. | §6 A1/A4/A9, `energy.py:6817` |
| 9 | MED | L1/L2 cannot execute — no `fill_priority_pause` row type exists | **§6 L1-L3 rewritten against real row shapes:** `coordinator='energy_pool'`, `description LIKE '%fill_priority%'`, `entity_id=<switch>`, joined to recorder SOC. Breakdown by `pause_owners` in description. L2 positive control retained and sharpened. L3 attributes tripwire rows by `pause_owners`. | Real `ura_activity_log` row shapes (pause_owners in description) joined with recorder SOC; breakdown by pause owner; positive control kept. | `energy.py:7860-7895`, §6 L1-L3 |
| 10 | LOW | Anchor errors | **§1 and §5.3.1 corrected.** `resume_soc_met` is COMPUTED at `:2773`/`:4451`, READ at `:2866`/`:4516`. Plug local var is `pause_conditions` (not `pause_conditions_global`). Plug has no `_fill_priority_would_hold` and MUST NOT get one. Plug force-charge is a KWARG parameter at `:4392`, not `_is_force_charge_active()`. | Fix anchors. | §1, §5.3.1, §5.3.2 |
| 11 | LOW | §5.3.2 may be swapped globally | **§5.3.2 explicitly scoped** — the swap replaces ONLY the pause-condition expression at the pause gate (`:2844` / `:4493`); excess-solar deferral (`:2836`) and the `_fill_priority_would_hold` publish (`:2776`) keep using `pause_conditions_global`. | (Implicit in orchestrator §5.3.2 scope; stated explicitly.) | §5.3.2 |
| 12 | LOW | A13 "mock arbitrage release path" is hollow | **A13 rewritten** — drives the REAL `determine_arbitrage_actions` + hand-off at `:3151-3155`, with the two-EVSE case from B2#2. No mock. | A13 drives the real arbitrage path. | §6 A13 |
| 13 | LOW | Config extremes lack expected values and omit SOC slider minimum (50) | **§7 table added** — pass/fail per cell at `soc=80` and `soc=50` (slider min); each band=0/3/100/−5 column has an expected result at every row. Floor arithmetic shown. | Specify expected values for config extremes (SOC slider minimum 50). | §7 |

## 14. Tier elevation (2026-10-15, orchestrator)

**Tier 3** (was Tier 2-DB). The operator flagged this code as sensitive;
plan review Rev 1 proved the one-missed-site failure mode (two unreachable
latch clears); Rev 2 found a sibling regression in the proposed `any()`
design and an observation-mode discharge gap. EV pause ownership is a
multi-owner arbitration (fill-priority, arbitrage, drain-precedence, force
charge, grid-charge clamp, dp, proactive off-peak); a missed discharge
silently costs money (EV drains the home battery). Process: two framing-
disjoint plan reviews (completeness F1-F8 and build-prediction 1-13),
four code reviews (A local, B integration/state-machine, C per-site
mutation drill, D adversarial completeness with legal-config repros
including pre-existing code), config-extreme tests (`fill_priority_soc` at
its minimum of 50, band 0, band ≥ threshold, negative band), orchestrator
mutation re-run before deploy, operator checkpoint before deploy.

**Falsifiable invariants (D's targets):** INV-1, INV-2, INV-3, INV-4 per §3,
with explicit exemptions listed. D re-enumerates writers of
`_paused_by_fill_priority` (`energy_pool.py` producers + the `energy.py`
restore) and readers of the new latch; produces legal-config repros for any
candidate leak.
