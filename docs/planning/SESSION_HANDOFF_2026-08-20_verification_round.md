# Session Handoff — 2026-08-20 (verification round)

**Supersedes** `SESSION_HANDOFF_2026-08-20.md` (written 00:20 today, **now partly WRONG** — see §2).
Board is source of truth (`docs/planning/kanban.data.yaml` → `KANBAN.md`); this doc carries the
narrative, the **corrections**, and the open decisions.

**Read this before touching HVAC or the EVSE drain-precedence machine.** Its main job is to stop
you re-deriving a mechanism that was refuted today at the cost of six agent investigations.

---

## 0. TL;DR for the next session

The day started with a "triple-verified" root cause for why the battery never drains overnight.
**It was wrong.** So were two of my own follow-on hypotheses. Real framing-disjoint verification
killed all three — and in the process surfaced **three genuine defects nobody was looking for**.

| | |
|---|---|
| **Nothing was built, deployed, or configured today.** | Working tree has board/doc changes only. |
| **Highest-value new find** | URA can lock itself out of its own thermostat preset control, indefinitely, with no self-recovery path. |
| **Operator's focus for next cycle** | "Calm any HVAC zone that doesn't have a person attached." |
| **Blocking decision** | Is `evse_battery_hold` demotion in scope for the DP fix? Without it the fix changes no behaviour. |

---

## 1. What the operator asked, and what changed

Operator's opening instruction: *"Re trace 1. Wasn't sure we were correct about the bug. Triple
verify."* — plus "check HA state and health" and "empirically check the HVAC Coordinator."

That skepticism was correct **three times over**. Approvals given during the session:

- **DP drain-target mis-sourcing** — "Card and fix. Approved." (scope caveat in §4)
- **Zone-3 occupancy chatter** — fix it
- **Blind anomaly metrics** — fix them
- **D2 canary** — "fix the canary if it has outlasted its use" (it has)
- **Zone-2 telemetry** — "if a problem" (it isn't; card closed)
- Routine-care dashboard + memory digest — approved earlier, **not started**, still queued

---

## 2. ⛔ THE CORRECTION ARC — do not re-derive these

### 2.1 The EVSE drain bug: REFUTED

**What the previous handoff asserted:** the drain-precedence (DP) machine drains toward a static
knob `_ev_battery_drain_soc` (=80) instead of the forecast target (=10), so the gate
`if soc <= drain_target_soc: already_below_target` sees `37 <= 80` and never transitions. Hence
no overnight drain.

**Why that "triple verification" was worthless:** it was **code + plan + README — three documents
restating one hypothesis.** It never asked whether the claimed gate could actually produce the
observed symptom.

**It can't.** `already_below_target` returns *inside* `EVAL_TRANSITION`, and the machine
immediately drops to `HOLD_ONLY` (`energy_drain_precedence.py:858-861`). It can never *rest* in
`hold_pre_eval`. The DP normally **cycles**: `HOLD_ONLY → (1 tick) HOLD_PRE_EVAL → (~eval_delay)
EVAL_TRANSITION → HOLD_ONLY`, spending most wall-clock in `hold_pre_eval`. So the observation
"state == hold_pre_eval" is equally consistent with `does_not_fit`, `l1_only`, `missing_inputs`,
`blind_hold`, and `force_charge_active`. **An observation shared by every candidate mechanism is
not evidence.**

**What actually happened (live, decisive):** the DP evaluated every 5 min all night — 105 state
changes 21:02→07:00, `dp_enabled: true`, `is_blind_hold: false` — and short-circuited at the
**L1-classification gate** (`energy_drain_precedence.py:652`, `charger_rate_kw <= 3.0`).
`decision.reason = "l1_only"` on *every* overnight snapshot, with `drain_hours` / `charge_hours` /
`computed_start_dt` all `null` — it exited **before any target arithmetic**. The drain target was
never consulted. **Setting the knob to 10 would have changed nothing.**

### 2.2 My own follow-on hypothesis: ALSO REFUTED

I then proposed that `charger_rate_kw` was fed by a dead/stale producer, making `l1_only` a
misclassification. **Wrong.** The 1.4 kW was physically real:

- `sensor.garage_a_power_minute_average` (Emporia CT — the actual producer via
  `energy_pool.py:168-182` → `current_charging_load_w` `:2286`): 1387–1416 W, 60 s updates,
  **never unavailable**
- `sensor.span_panel_car_charger_power` (independent SPAN breaker CT): 1412–1440 W, 5 s cadence

Two unrelated physical meters agreeing to ~1.5% cannot both be faked by a stale producer.
1425 W ÷ 240 V ≈ **5.9 A** = an L2 charger pinned at its ~6 A minimum. The same sensor reports
6450/6390/5048 W hourly means on other days.

**My specific reasoning error:** I cited the "11 kW grid import vs 8.4–10.3 kW house load" gap as
proof of a ~5 kW charger. The gap is 1–2.6 kW, which **corroborates** 1.4 kW. I had the arithmetic
backwards.

**Red herrings I chased — don't repeat:**
- `sensor.ura_energy_coordinator_ev_charge_rate_garage_{a,b}` being `unavailable` = **deliberate
  tombstones** from EV-SENSOR-CLEANUP-1 (`energy.py:9748-9755`), not a broken feed.
- `binary_sensor.ura_energy_coordinator_l1_charger_garage_a` reads the **Moes smart plugs**
  (`energy_const.py:258`), shares nothing with `charger_rate_kw`, and does not feed the DP gate.
  Pure naming collision.

**Real root cause: physical.** The EVSE ran ~6 A overnight and 23 A the next day (`switch.garage_a`:
`charging_rate: 23 A`, `max: 48 A`). Emporia amp limit or in-car charge-current setting.
**Operator has taken this** (removing Emporia's solar management; BMW set to charge on plug-in but
may be flaky). URA behaved to spec throughout.

### 2.3 Zone-2 "stale telemetry": BENIGN — my oracle error

I read `last_changed` as a freshness signal. **It isn't** — it only moves when the *state string*
changes. All three climate entities share `last_changed 12:15:17.095` to the sub-millisecond,
because all three went unavailable at 12:14:15 and restored at 12:15:17 on a Carrier cloud 504.
Discriminator applied and negative: `current_temperature` **did** advance (79→80 at 14:05).
Zone 2 was idle/`away` with nothing to report; zone 3 logged 59 rows over the same window only
because it was actively cooling — and when zone 3 went idle its cadence dropped identically.

> **Durable lesson:** `last_changed` is NOT a liveness oracle for climate entities.
> `last_reported` / `last_updated` is. Any future actuator stuck-poll trip-wire must key on
> `last_reported` age.

### 2.4 My "camera-only path" claim: RETRACTED (operator caught it)

I claimed zone_3 is driven by "camera + room-sensor" occupancy because it has a `zone_cameras`
attribute and empty `zone_persons`. Operator: *"Not sure we use camera for zone ops. Please
confirm."*

**`zone_cameras` does NOT feed HVAC zone occupancy.** Every use is diagnostic: reverse map
(`hvac.py:3276-3286`, docstring says "(diagnostic)"), sensor attrs (`hvac.py:3810`,
`hvac_zones.py:600-601`), face-arrival counter (`presence.py:4686`), and one read
(`presence.py:2138-2145`) reachable only from the D6 stale-occupancy failsafe where it can only
*veto* a >4 h force-away.

**But a camera IS in the path by a different route:** room **Garage Hallway** lists
`binary_sensor.staircase_person_occupancy` (Frigate person) in its **room** `occupancy_sensors`.
Room occupancy is a plain OR over motion+mmWave+occupancy (`coordinator.py:3134-3180`), rolled up
by `any_room_occupied` (`hvac_zones.py:146-148`). A per-room **config** choice, not a feature.
Measurably the noisiest input in that room: **89 on/off cycles/24h vs 53 for the PIR sibling.**

> **My error class:** inferred a mechanism from the *presence of an attribute*. Plumbing-vs-
> arithmetic — exactly what CLAUDE.md warns about.

**Operator has taken this**: removing that sensor, adding an mmWave/PIR-class one.
⚠️ **Re-measure after the swap** — it removes the noisiest single input but the other three
chattering corridors are unaffected.

### 2.5 Things that were checked and are FINE — don't re-investigate

- **Arrester works.** 15 detected / 14 reverted / 1 compromise reproduced *exactly* in a
  restart-free window. Restart caveat resolved properly (non-URA entity went `unknown` at both
  restarts; host `last_boot` unchanged).
- **`temp_arrester_override` 3.2 h suppression** — **operator did that deliberately and turned it
  off.** Not a stuck flag.
- **`overrides_compromised_today: 0`** — not a counter. Counts zones *currently* in compromise
  (`sensor.py:12742-12751`). Zero is correct. Naming defect only.
- **`heat_cool` invariant HOLDS** — no path writes `cool`/`heat`/`fan_only`/`auto`. Only `off`,
  always paired with a restore. Operator's belief confirmed.
- **HA health:** 42/42 URA entries loaded, v5.85.0 = available, one clean restart, exactly one URA
  ERROR in 24 h.

---

## 3. ✅ THE REAL FINDINGS (all new, none previously known)

### 3.1 🔴 URA locks itself out of preset control — `HVAC-MANUAL-PRESET-CONTRACT-1`

Operator's design spec: *"not use manual but use our presets as control… manual setpoint is messy.
What's allowed as manual is solar banking and pre-cool. But wonder if they escape back to preset
when they revert."*

**They don't.** 13 setpoint-write sites; **9 induce `manual` and never restore a preset.**
`hvac_predict.py` — owner of solar banking (S11 `:957`), pre-cool (S12 `:1047`), pre-heat
(S13 `:1286`) — contains **zero** `emit_set_preset_mode` calls. The only preset-restore in the
codebase is S7 (`hvac_override.py:3232`, AC soft nudge), and it is racy.

**The self-lockout:** `hvac_preset.py:202-217` `should_change_preset` returns `False` whenever
`current_preset == "manual"`. It's a **pure two-string function** — no `hass`, no entity_id, no
arrester ref — so it *cannot* consult provenance even in principle. The provenance tag exists
(`_suppress_kind`, `hvac_override.py:185`) but is consulted at exactly one place (`:1635-1638`, the
manual-passthrough **counter**) and has a **~5 s TTL** while `manual` persists for hours.

**Zone-1 stranding, attributed with high confidence** — AC soft nudge losing a write-ordering race:
```
01:42:05.138  sleep   70/75   <- S7 preset restore LANDS
01:42:05.647  manual  70/75   <- 509 ms later, clobbered. Last non-manual of the day.
```
`_restore_after_nudge` issues its setpoint restore `blocking=False` (`:3197-3204`) then immediately
emits the preset restore (`:3221-3237`); on a cloud-polled Bryant the setpoint lands *after* and
its `manual` side effect overwrites it. Then `_nudge_pre_preset` only snapshots a **non-manual**
preset (`:3083-3089`) — so every later nudge stored no snapshot and its restore did nothing.
**The repair mechanism disarms itself the first time it fails.** Result: 10.5 h of `manual` through
~6 h of `home_day`, ended by something outside URA.

**⚠️ Coupling:** S14 (`hvac.py:2974`) *deliberately* replaced a preset write with an indefinite raw
setpoint hold — and its comment dates it to **HVAC-PRESET-FLAP-1 (2026-08-11)**. The flap fix
created a permanent-manual writer. **Do not retune the flap without accounting for S14.**

### 3.2 🟠 Preset flap regressed — and moved zones — `HVAC-PRESET-FLAP-1` (back in `review`)

Shipped v5.73.0; organic hypothesis **VIOLATED**. Zone 2 (the original subject) is now clean —
zero flips in 4 h. **Zone 3 inherited it: 83 preset changes/24 h, 11 in the worst hour**, measured
at the thermostat (real cloud writes, not intent-sensor cosmetics).

**Mechanism resolved** (operator correctly recalled the dwell gate):
- **Zone entry dwell** `CONF_HVAC_ZONE_ENTRY_DWELL` = 3 (`hvac_const.py:372-373`), live 3.0,
  applied `hvac.py:1756-1766`. Comment: *"prevent preset flapping on brief transits."*
  **It carries `and effective_preset != "away"` — so it only damps away→home, by design.**
- **Vacancy grace** `hvac.py:1517-1553`, default 15, **live 10.0**; switches to
  `_vacancy_grace_constrained` (**live 5.0**) when `_energy_constraint_mode` in `("coast","shed")`.

Round trip: blip → occupied → `last_occupied_time` resets → 3-min dwell → `home` → grace of quiet →
`away`. ≈13 min, matching observation. **The 5-minute flips = coast mode halving the grace** — and
this card's original 2026-08-09 finding was "all inside coast mode."

**Chatter is four corridors, not one sensor:** breakfast_nook 62, kitchen_hallway_garage 55,
garage_hallway 49, kitchen_hallway 45 transitions/24 h.

**Verdict: primarily TUNING** on two existing knobs both at-or-below default and too short for a
12-room transit corridor, **plus one genuine gap** — no rate limit on the preset *write* itself
(`should_change_preset` is a bare 3-line comparison, no timestamp, no cooldown), and no per-room
min-on-time.

**Operator's design axis (verbatim):** *"if no one is assigned to a zone that maps to an hvac zone,
we have to treat it differently. Especially if it sees a lot of transit."* ⚠️ Composition trap the
operator flagged: zone_3 mixes pure-transit rooms **with Guest Bedroom 1** — a blanket
"transit zone = ignore quickly" rule would strand the guest bedroom.

**Empty `zone_persons` is load-bearing, not informational.** It makes three suppressions **inert**:
night-trust away-suppression (`hvac.py:1788-1795`), sleep veto (`aggregation.py:4017-4019`),
non-sleep person-home bias (`:4152-4154`). Zone 3 is *structurally* more prone to flipping away.

### 3.3 🟠 The detector that should have caught it is blind — `HVAC-ANOMALY-BLIND-1`

`sensor.ura_hvac_coordinator_hvac_anomaly` = `nominal`, 0 anomalies — but
`metrics_active_ratio: "2/5"`. `short_cycle_rate`, `comfort_deviation_hours`,
`egress_pause_frequency` all `sample_count: 0`. **The two metrics that would have caught the flap
(3.2) and the zone-2 comfort excursion have never received a sample.**

**Root cause is already in `docs/BACKLOG.md`** (CRITICAL, from the v4.6.10 Tier-2 review):
`AnomalyDetector._baselines` is an in-memory dict that resets to `{}` every restart, so
`minimum_samples=10` is structurally unreachable. **This card is the live evidence that its trigger
has fired.** Adjacent to WATCHDOG-INERT-1 (same "detector exists but is structurally inert" class).

### 3.4 🟡 D2 canary has outlasted its use — `D2-CANARY-GUEST-PREDICATE-1`

Firing ~4×/min, 3300+ since boot. **No code regression** — `guest_armed` is still exactly
`guest_room_gate_armed` or `False` in all three branches; no census term. The *assertion* is true;
the **guard premise is false and always was**. Its comment claims it sits inside an
`if guest_armed:` block — **no such block exists**; the chain runs unconditionally every tick, so
every normal no-guest cycle hits the `else`.

Git-dated decisively: predicate inverted `7f7c15d20` (08-16 19:35), canary planted `0e0ea97a2`
(08-16 22:18) — **2 h 45 m later.** Behaviourally **inert**: `_d5_guest_confidence`'s one consumer
(`presence.py:6302`) is itself gated on `guest_room_gate_armed`. **Not** the census-double-count
family. **Tier 1, log hygiene** (~5,700 WARNING lines/day into a 31 GB recorder).

Recommended: demote to `debug` **and** re-guard to `if guest_armed and not guest_room_gate_armed:`
— the check the author intended. Fix the misleading comment either way.

### 3.5 Smaller

- **`ARRESTER-CLOUDFLAP-FALSEPOS-1`** — Carrier 504 → all 3 zones drop together → phantom override
  booked 20 s after reconnect. Batched `cloud-flap-immunity` with
  BATTERY-RESERVE-CLOUD-ORACLE-FLAP-1 (identical fix shape: post-reconnect grace).
- **`RECORDER-BLOAT-LOGFLOOD-1`** — 31 GB for 7 days, flash at 51% life. Floods: mqtt.number 1030
  (Sonoff range mismatch), camera_census 4866 (Frigate `_2` class → FRIGATE-LEG-NAMING-1), Alexa
  ~2089, D2 canary 3300+.
- **`HVAC-GUEST-AS-ZONE-PERSON-1`** — operator's idea (§4).
- **UNCARDED:** `binary_sensor.kitchen_occupied` and `dining_room_occupied` pinned `off` 24 h
  despite the kitchen being high-traffic. Suspected dead config.

---

## 4. ⛳ OPEN DECISIONS

### 4.1 🔴 BLOCKING — is `evse_battery_hold` demotion in scope for the DP fix?

The DP fix was approved as "bind the drain target to the forecast." **That alone may not drain the
battery.** `evse_battery_hold` pins reserve to live SOC while the EV charges; DP's target enters a
`max()` fold, so `max(hold_reserve=SOC, dp=10)` = **SOC**. The hold swallows the lower target.

The parked memo `project_ev_drain_precedence_cycle.md` already names *"hold demoted to backstop"* as
intended design. **If demotion is out of scope, the acceptance criteria MUST NOT claim "battery
drains overnight"** — that would be exactly the undiscriminating criterion that caused this whole
misdiagnosis.

### 4.2 The DP design call — one number, three incompatible roles

`_ev_battery_drain_soc` serves three roles, **two pointing opposite directions**:

| Role | Sites | Semantics | Direction |
|---|---|---|---|
| **R1 pause ceiling** | `energy.py:5842`, `:5977` → `energy_pool.py:3224` | pause EV if SOC drops below X | higher = more protection |
| **R2 drain floor** | `energy.py:4271/4456/4522/4540/4555` → gate `:656` | drain down to X | **lower = more drain** |
| **R3 ride-proof floor** | `energy.py:3752`, `energy_pool.py:954/1435` | envelope lower bound must exceed X | higher = stricter |

At 80 both bad effects are maximal together. **"Bind DP to the forecast" is necessary but NOT
sufficient** — R1 stays at 80 and the EV still gets paused nightly.

**Recommended (d): split the roles.** R2 sources from a new helper returning
`compose_release_floor(self._battery, period)[0]` — **not** the bare `current_offpeak_drain_target()`,
because `compose_release_floor` already reconciles static reserve + `current_park_floor()`
(arbitrage/attain parks, inclement holds), and the EV drain-pause at `:5838` already uses exactly
this. Using the raw accessor re-introduces the parallel-re-derivation-blind-to-parks bug that
`energy_battery.py:289-292` closed. **This is the single most important design call in the cycle.**
R1 keeps the knob (rename the concept — the *name* caused the conflation); R3 follows R1.
**No new knobs.**

Options (a) delete / (b) `max(forecast, floor)` / (c) repurpose as charge-above were all evaluated
and **rejected** — (a) deletes the deep-discharge backstop `energy_pool.py:1790-1793` says must
remain; (b) is `max(10,80)=80`, **a no-op**; (c) duplicates `fill_priority_soc`.

**Provenance of the 80 (resolved):** `entry.options` holds `80.0` as a **float** — `number.py:1529`
writes `int()`, the options-flow `NumberSelector` yields floats ⇒ **written by the options flow,
not the slider**, and re-committed by any unrelated save. **`energy_fill_priority_soc` is ALSO 80.0**
— and fill-priority *is* the charge-above threshold. The operator's "80 was meant as charge-above"
maps onto a knob that already holds 80. **The drain knob at 80 is a conflated duplicate, not policy.**

**⚠️ Activation risk:** this fix *activates a dormant state machine.* DP has never transitioned in
production. `_apply_dp_transition`, the EVSE `switch.turn_off` dispatch (`:4936`), `_paused_by_dp`,
`_claim_pause_dispatch_owner("dp")`, the must-start-by timer — none has run organically at scale.
Live validation must watch **actuation**, not just the target value.

**⚠️ Highest-probability build error (make it an explicit non-goal):** `energy.py:5842`/`:5977` pass
the composed floor as `reserve_soc=` **and** the static knob as `soc_threshold=` side by side. A
builder "making it consistent" by pointing `soc_threshold` at the composed value would collapse
`soc_low = soc < 10` and **silently delete the deep-discharge backstop during peak windows.**

**Two blockers a planner MUST trace first:**
1. Do the four `energy_offpeak_drain_*` Number entities **live-apply** into
   `BatteryStrategy._drain_targets`, or only write `entry.options` (requiring reload)?
   `_drain_targets` is ctor-frozen (`energy_battery.py:464`); `__init__.py:5863-5867` lists them in
   the reload-suppress block, suggesting a live-apply path exists. **If none does, "the forecast
   target updates live" is FALSE.**
2. The numeric value of `DEFAULT_OFFPEAK_DRAIN_UNKNOWN` (the Solcast-dead fallback).

**Tier 3** — 10+ emission sites, value lands on the commanded Enphase reserve floor (cost AND
safety), area already carries B2a/B2b-ii/B2c-1/B2c-2 fix-ups and a Tier-3 cycle with a D-HIGH-1.
Framings A=per-site arithmetic, B=state-machine integrity + byte-identical R1/R3, C=**real per-site
source mutation** (8 named mutations on the card), D=adversarial completeness re-enumerating
**pre-existing** code. Plus **two plan reviews** before build.

**Test blindness explained:** `drain_target_soc=15` is a **literal in the fixture**
(`test_evse_drain_precedence_session_b2a.py:126-149`). **No test anywhere asserts what
`_DPInputs.drain_target_soc` is populated FROM.** The two tests touching it set it on a *fake*
coordinator — they assume the wiring they should prove (hollow-anchor pattern). T1 must use values
on **opposite sides of fixture SOC** so a wrong source yields `ALREADY_BELOW_TARGET` and the right
one yields a fit.

### 4.3 Operator's own tasks (do not action)

- Remove `binary_sensor.staircase_person_occupancy` from Garage Hallway; add mmWave/PIR-class.
  ⚠️ **Re-measure after** — three other corridors unaffected.
- Remove Emporia excess-solar management (rate-limits charging; URA should manage).
- BMW set to charge on plug-in but "may be flaky."

### 4.4 Carried over, untouched today

- **STEP 2-day forcing gate** — cloud routine `trig_01XZno8URQxUmuiNJczBjKaw`, **fires 2026-08-21
  09:00 CDT**. Flip `select.ura_chatter_mode` to `act` or declare moot. ⏰ **Tomorrow.**
- **Routine-care dashboard** (approved, probe GO) — not started.
- **Daily memory digest** (approved, use #3) — hand-test/D0 not started.

---

## 5. Recommended next cycle

**Scope HVAC-PRESET-FLAP-1 + HVAC-MANUAL-PRESET-CONTRACT-1 as ONE cycle.** They are two faces of one
preset-precedence defect: the flap is *too many* preset writes on zone 3; the contract violation is
preset writes *not happening* on zone 1 because `manual` blocks them. And the flap fix **created**
the S14 permanent-manual writer. Fixing either alone risks re-breaking the other.

Operator scoped the priority explicitly: *"lets focus on calming any hvac zone that doesn't have a
person attached."* So calming leads; `HVAC-GUEST-AS-ZONE-PERSON-1` is deferred behind it.

**Operator's guest idea** (`HVAC-GUEST-AS-ZONE-PERSON-1`): if a room carries `is_guest` and is
occupied, the guest becomes the zone's home person — lighting up the three suppressions that are
inert for zone 3. Operator's own caveat is the hard part: *"IFF they are actually around and don't
decay."* A synthetic person that never decays pins the zone `home` forever after one blip — worse
than today. Needs an explicit liveness/decay contract (suppression-needs-a-discharge class). It must
**not** reuse the house-level guest-MODE arming predicate — that's a different thing (see §3.4 and
the census/guest card cluster).

**Tier:** 2-DB minimum for the preset cycle (cross-coordinator, cost-impacting, shared primitive);
Tier 3 for DP.

---

## 6. Methodological lessons (worth memory entries)

1. **"Triple-verified" must mean three *framings*, not three documents.** Code + plan + README all
   restating one hypothesis is one verification wearing three hats.
2. **An observation shared by every candidate mechanism is not evidence.** `hold_pre_eval`
   discriminated nothing. Acceptance criteria must discriminate the fix from a *plausible different
   failure* — the CLAUDE.md corollary, violated here.
3. **Cross-meter agreement kills producer hypotheses fast.** Two independent physical meters at 1.5%
   ended the charger debate in one step.
4. **Don't infer mechanism from the presence of an attribute** (`zone_cameras`). Plumbing vs
   arithmetic.
5. **`last_changed` is not a liveness oracle** (§2.3).
6. **A fake whose attribute name matches production is not evidence production reads it**
   (§4.2 test blindness).
7. **The adjacency sweep earns its cost.** Four of six "new findings" were already known —
   HVAC-PRESET-FLAP-1 (shipped, this was a *violation* of its organic hypothesis, not a new card),
   the BACKLOG AnomalyDetector item, EV-GARAGE-A-NOCHARGE-1, FRIGATE-LEG-NAMING-1. Sweeping only
   the board would have missed the BACKLOG root cause entirely.

---

## 7. Live-state anchors (~2026-08-20 14:00–16:30 CDT)

- HA `core-2026.8.1`, HAOS 18.1. URA **42/42 entries loaded**. HACS installed = available =
  **v5.85.0**. One clean restart 00:12 CDT; no watchdog.
- **Envoy went unavailable 13:27 CDT**, cloud SOC fallback stale (age 1201 s > 600 s) → URA
  fail-safing `soc=None`, `energy_envoy_available=off`. Fail-safes correct.
- Recorder **31.7 GB / 7 days**, `disk_life_time: 51%`.
- Knobs: `ev_battery_drain_soc` **80**, `current_offpeak_drain_target` **10**,
  `fill_priority_soc` **80**, `reserve_soc` **10**, `vacancy_grace` **10.0**,
  `vacancy_grace_constrained` **5.0**, `zone_entry_dwell` **3.0**,
  `multi_day_horizon_enabled` **true**.
- HVAC zones: z1 `climate.thermostat_bryant_wifi_studyb_zone_1` (Entertainment + Master Suite, 10
  rooms, persons oji/ezinne, limits 70/77); z2 `climate.up_hallway_zone_2` (Upstairs, 11 rooms,
  persons ziri/jaya, 68/80); z3 `climate.back_hallway_zone_3` (Back Hallway, 12 rooms,
  **no persons**, 70/77, contains Guest Bedroom 1 + bathroom).
- `select.ura_chatter_mode` = **shadow**.

---

## 8. Repo state

- Branch `develop`. **No code changed. Nothing committed, nothing deployed.**
- Modified: `docs/planning/kanban.data.yaml` (+ rendered `KANBAN.md`, `kanban_board.html`),
  `.vibememo/counseling.jsonl`, this doc.
- **Board: 134 cards**, `meta.last_reconciled: '2026-08-20'`, renderer exit 0 (fresh).
- Applied a stuck operator disposition: `SENSOR-FANINDEP-1` → `approval: explicit` (had been
  queued since 08-18; `kanban_render.py --check` was returning exit 3).
- ⚠️ `scripts/kanban_render.py --check` at session start — **exit 3 = unapplied dispositions**
  (apply first), **exit 2 = stale**.

**Cards carrying the detail:** `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` (roles, provenance, invariants,
8 mutation anchors, 2 blockers), `HVAC-MANUAL-PRESET-CONTRACT-1`, `HVAC-PRESET-FLAP-1` (in
`review`), `HVAC-ANOMALY-BLIND-1`, `D2-CANARY-GUEST-PREDICATE-1`,
`HVAC-GUEST-AS-ZONE-PERSON-1`, `ARRESTER-CLOUDFLAP-FALSEPOS-1`, `RECORDER-BLOAT-LOGFLOOD-1`,
`EV-GARAGE-A-NOCHARGE-1` (operator's), `HVAC-STALE-ACTUATOR-FRESHNESS-1` (closed benign).
