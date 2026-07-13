# PLANNING — EV charge-start dead-band fix

Drain-release floor reconciliation + L1/L2 policy parity.

**Status:** planning (version stamped at deploy).
**Author-orchestrator context:** post-audit 2026-07-12. Root cause already
investigated at `~/.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/project_ev_charge_start_deadband.md` and re-verified in source (line
numbers below are re-greppable as of this file's date). Operator decisions
2026-07-12 are binding — see §"Operator decisions" of the invocation memo.

**Cost impact.** The night of 2026-07-11→12 the EV pulled ~2.5 kWh over off_peak
and only via an external nudge at 02:00 that URA silently re-killed at 03:01:34.
On a typical off_peak (00–14, 21–24 in summer at $0.0435/kWh vs $0.1618 peak),
missing a full ~7 h charge session is roughly $2–4/day of price differential — a
cost-AND-safety-shape regression, per Tier-3 policy.

---

## 0. Institutional context verified

Every claim below was re-greppable against `develop` at the time of this file.
Line numbers **will** drift — re-verify before build.

### 0.1 Prior art re-verified in source

| Anchor cited in the memo | Verified location | Notes |
|---|---|---|
| v4.7.28 off-peak ensure-on | `energy_pool.py:613-635` | `2c: ensure-on. Re-issue turn_on idempotently each tick`; carry-over guard at `:558-570` cedes to `_paused_by_battery_drain` — the site being vetoed |
| EV drain pause gate | `energy_pool.py:987-1013` (window shifted +1 vs memo's `~988`) | `battery_discharging = battery_power_w < -100`; `soc_low = battery_soc < soc_threshold`; both must hold |
| EV drain release gate | `energy_pool.py:1015-1084` | `battery_out_of_capacity = ... battery_soc <= reserve_soc + 2` at :1028; solar-gated `soc_recovered` at :1042-1046 |
| Docstring premise cited as broken | `energy_pool.py:1030-1041` | Text: "overnight EV charge is reserve-gated → guaranteed grid" |
| `reserve_soc` threaded into drain | `energy.py:2867` (`getattr(self._battery, "reserve_soc", None)`) | This is the exact injection site the fix must widen. `energy.py:2945` mirrors for plug drain — same `getattr` shape. |
| `_ev_battery_drain_soc` config threading | `energy.py:293-298` (`CONF_ENERGY_EV_BATTERY_DRAIN_SOC`) | `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD=50` (`energy_const.py:568`) |
| Cooldown constant | `energy_const.py:570` (`EV_BATTERY_DRAIN_COOLDOWN_SECONDS = 3600`) | Consumed at pool `:970`, `:1935` |
| Plug drain mirror | `energy_pool.py:1863-2015` | Method signature at `:1863-1871`; pause gate `:1885-1890`; release gate `:1965-2013` |
| Drain-target machinery | `energy_battery.py:198-204` (`_drain_targets` dict), `:650-652` (`_get_offpeak_drain_target(tomorrow_class)`), `:3051` (`classify_tomorrow_solar()`), consumer at `:3114-3131` | Values from `energy_const.py:455-459` — excellent=10, good=15, moderate=20, poor=30, unknown=40 |
| `reserve_soc` attribute | `energy_battery.py:189` (init); `DEFAULT_RESERVE_SOC` = 10 (per `_drain_targets` fallback constants) | Public attr `self.reserve_soc` |
| Solar-replenishing gate (v5.5.5 D2) | `energy.py:2848-2868`, `energy_battery.py:1697` (`expected_solar_surplus_now_pct`) | Uses `DEFAULT_EV_SOLAR_REPLENISH_SURPLUS_PCT` (`energy_const.py`) OR live `battery_power_w > +100W` |
| v5.5.5 reviewer miss anchor | `docs/reviews/code-review/v5.5.5_evse_reviewD_completeness.md:33` and `:47` | Reviewer D cleared `battery_drain` on "Correct (D2 intent)" — the miss to correct. |
| v4.7.28 shipping notes | `docs/readmes/README_v4.7.28.md` | Off-peak ensure-on live |
| Skills consulted | `.claude/skills/ura-energy-strategy-reference/SKILL.md`, `.claude/skills/ura-energy-invariants-campaign/SKILL.md` | §7 and §Phase 0–2 respectively load-bearing here |

### 0.2 A pre-existing parity gap surfaced during verification (must fix)

`energy.py:2941-2947` — the plug drain call site — **does NOT pass**
`solar_replenishing`, unlike the EV site at `energy.py:2863-2869`. Plug
`determine_battery_drain_actions` defaults `solar_replenishing=False`
(`energy_pool.py:1870`). Consequence: today the plug path can only release via
`battery_out_of_capacity` (reserve_soc + 2 gate) — the exact gate that traps the
EV. Once we thread the live floor into the EV path, the plug path will still be
strictly worse unless we mirror both fixes there. This is exactly the "Bug Class
#53 one-missed-site" shape the plan must close.

### 0.3 Reuse vs new — proposal-level

| Proposed change | REUSED / NEW | Justification |
|---|---|---|
| Effective release-floor computation `max(reserve_soc, current_offpeak_drain_target)` | REUSED — `_get_offpeak_drain_target` at `energy_battery.py:650`; `reserve_soc` at `:189`; `classify_tomorrow_solar` at `:3051` | No new constant or CONF — thread a value already computed every cycle |
| Accessor `BatteryStrategy.current_offpeak_drain_target()` returning today's applicable target | NEW (small — 5-8 LoC) | The two-day-horizon-aware target used at `:3114` is not exposed; adding a pure read-through method is cheaper than re-deriving in `energy.py` |
| Plug drain call to pass `solar_replenishing` | REUSED — same computation already done at `energy.py:2848-2862` for the EV | Delete the pre-existing L1/L2 gap |
| Optional debounce (D-decision, see §6) | Either NEW `_battery_discharge_persist_ticks` (2-tick hysteresis) OR "release-side sticky at effective floor" (0 LoC state, 3 LoC gate) | Present recommendation; operator picks |
| Optional diagnostic attribute `current_release_floor` on battery-strategy sensor | REUSED sensor + attr surface (`sensor.py` battery_strategy attrs); NEW attribute key | Only add if cheap and does not require new sensor/CONF |

**No new CONF_*, no new switch/number/button, no schema change.** This cycle is a
per-call-site parameter reconciliation — the minimum viable fix.

### 0.4 Prior planning docs & memory bodies consulted

- `docs/planning/PLANNING_arbitrage_wait_inclement_floor.md` — structural cousin
  (two-floors-never-reconciled shape, closed v5.5.3); confirms the mental model.
- `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md` — where the
  "solar surplus %" helper we reuse originally landed.
- Memory: `project_ev_charge_start_deadband` (root-cause investigation, not
  built) — this cycle's primary source.
- Memory: `project_ev_offpeak_cycle_pickup` — v4.7.28 ship notes.
- Memory: `project_inclement_arbitrage_wait_floor_gap` — RESOLVED v5.5.3, cited
  as the analogous fix pattern.
- Memory: `project_battery_soc_envoy_not_span` — SOC source is Envoy; nothing in
  this fix disturbs the SOC read path.
- Memory: `project_ev_pause_post_peak_midpeak_decision` — durable EV philosophy
  ("solar-first → never drain battery into car → off_peak grid cheapest") —
  this fix restores that promise for the overnight path.
- Review: `docs/reviews/code-review/v5.5.5_evse_reviewD_completeness.md` §L33 —
  the review miss being corrected.

### 0.5 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py`
  L163-1090 (EVSE class up through drain release), L1740-2020 (plug class + drain).
- `custom_components/universal_room_automation/domain_coordinators/energy.py`
  L285-320 (config threading), L1130-1300 (restore + reason string), L2820-2960
  (both drain call sites), L4180-4290 (arbitrage-mirror carry-over).
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py`
  L1-210 (init), L640-660 (drain-target getter), L1690-1710 (solar-surplus
  helper), L3040-3160 (off-peak drain branch — the emitter that decides where
  the battery parks).

---

## 1. Falsifiable invariant (Phase 0 gate)

Write into this doc verbatim; Pass D's only job is to break it.

> **INV-EV-DEADBAND.** *For every EV-charging device (L2 EVSE listed in
> `_evse`, or L1 plug listed in `_plugs` with role "EV charger"), during
> `off_peak` when:*
> 1. *the battery is at or above its effective release floor
>    `F = max(reserve_soc, current_offpeak_drain_target())` (with equality
>    inside a ±2%-SOC hysteresis band), AND*
> 2. *`battery_power_w > -100 W` averaged over the release-side hysteresis
>    window (see §6), AND*
> 3. *no other URA pause owner is active for that device* — `_paused_by_us`,
>    `_paused_by_grid_cap`, `_paused_by_arbitrage`, `_paused_by_fill_priority`,
>    `_paused_by_load_shed` are all False for it, AND
> 4. *no operator "OFF" state is present (external control off; force-charge not
>    revoked; entity not `unavailable`),*
>
> *no URA gate may keep that device OFF for longer than **one 5-minute decision
> cycle**. The device must be commanded ON by `determine_battery_drain_actions`
> release path or the v4.7.28 ensure-on carry-over must not skip it because of a
> stale `_paused_by_battery_drain` membership.*

**Falsified by** any legal-config, reachable state in which all four conditions
hold at tick N and the device is still OFF at tick N+2 (giving one tick for
release, one for ensure-on to fire). Concrete D-repro shape must include: today's
solar_class, drain target from the table, reserve_soc, actual SOC, actual
battery_power_w, and the pause-owner set snapshot.

### 1.1 How each reviewer framing falsifies INV-EV-DEADBAND

- **Pass A (local correctness)** — verify at each release site that
  `reserve_soc + 2` in the emitted comparison has been replaced with the
  effective-floor value, and that the effective-floor computation is arithmetic-
  correct across `(reserve_soc, current_offpeak_drain_target) ∈ {below, equal,
  above}` reserve.
- **Pass B (state-machine + integration)** — trace: drain-pause engages (dusk)
  → battery parks at floor F → release fires within 1 tick → ensure-on turns ON
  next tick → EV runs the rest of off_peak → peak hits at 16:00 → TOU pause
  (`_paused_by_us`) commands OFF cleanly → cycle repeats next day. No
  bookkeeping stragglers; restart-safe (`evse_battery_drain_paused` DAO restore
  at `energy.py:1150-1159` must NOT re-arm on a state that has been released).
- **Pass C (test authority)** — mutation-anchored per site: for each edited
  `reserve_soc + 2` (EV path + plug path + potentially the plug's `solar_recovered`
  gate at `:1971`), neuter that one arithmetic and confirm a NAMED test fails.
  Aggregate monkeypatch of the effective-floor helper is NOT sufficient.
- **Pass D (adversarial completeness)** — re-enumerate ALL `reserve_soc + 2`
  literals AND all `_paused_by_battery_drain` mutation sites (grep from §4), and
  every `soc_low`/`battery_discharging` gate. Break INV-EV-DEADBAND with a
  minimum-2-slider legal-config repro. Also check for the SYMMETRIC failure
  (over-releasing at night, sub-reserve): if `current_offpeak_drain_target()` is
  ever `< reserve_soc` (excellent class = 10 == reserve default; DO NOT
  regress).

---

## 2. Tier classification

**Recommended tier: Tier 3 (four framing-disjoint reviews including adversarial
completeness Pass D).**

Justification:
- **Trust-hierarchy ripple.** Battery ↔ TOU ↔ EVSE ↔ plugs — the exact axis
  CLAUDE.md's standing-policy elevates to Tier 3.
- **Bug Class #53 shape.** Two floors (static reserve vs live drain target)
  never reconciled — same class the v5.5.3 arbitrage-WAIT fix closed under
  Tier 3, where Pass D (and only D) caught a pre-existing 7th unclamped site.
  This cycle has a directly analogous risk: a plug mirror already differs
  from the EV path pre-fix (§0.2).
- **Cost-AND-safety-impacting.** Silent overnight failure to charge (already
  seen live). One missed site → the operator still wakes to an uncharged car.
- **The invariant is one-missed-site falsifiable.** INV-EV-DEADBAND is
  violated by *any* reachable path that keeps the device off — exactly the
  shape that D exists to enumerate.

Operator MAY downgrade to Tier 2-DB (three framings) if D+A+B are executed
sequentially by the same reviewer and D is skipped — do NOT skip; the whole
reason this file exists is that v5.5.5 shipped without D catching it.

**Pre-review baseline tag:** `git tag pre-review-v<version>` before any review
fix-ups (per CLAUDE.md §Pre-Review).

---

## 3. Deliverables and acceptance criteria

### D1 — Effective release floor threaded into EV drain release

**Change.** Compute `F = max(self.reserve_soc, self.current_offpeak_drain_target())`
in `energy.py`'s EV drain call site (`energy.py:2863-2869`) and pass it as
`reserve_soc=F` — RENAMED at the pool boundary to `effective_release_floor` in
the signature docstring but WITHOUT a Python parameter rename (would ripple to
tests; keep the kwarg name to preserve the diff surface). Alternatively, add a
new kwarg `effective_release_floor` alongside the existing `reserve_soc` and
prefer it when non-None — decide during Pass A which is smaller.

**Files:**
- `domain_coordinators/energy_battery.py` — NEW method
  `current_offpeak_drain_target()` (public), REUSES `_get_offpeak_drain_target`
  and `classify_tomorrow_solar`. Include the multi-day-horizon-aware `max(D+1,
  D+2)` logic already used at `:3107-3112` so the accessor matches the emitter.
- `domain_coordinators/energy.py:2863-2869` — compute F and pass to EV drain.
- No change to `energy_pool.py`'s signature — `reserve_soc` kwarg semantics
  become "the floor at which drain release triggers", not "the static reserve".
  Update docstring (`energy_pool.py:883-908`) accordingly.

### Acceptance Criteria
- **Verify:** On a night with `tomorrow_class ∈ {good, moderate, poor,
  unknown}` (drain target > 10), once battery SOC parks at floor F ± 2 and
  battery_power_w > -100 W, `_paused_by_battery_drain.discard(evse_id)` fires
  within one 5-min tick, `switch.turn_on` is dispatched by the same or next
  tick, and the EVSE stays ON for the remainder of off_peak.
- **Verify:** On `tomorrow_class = excellent` (drain target = 10 = reserve
  default), behavior is byte-identical to today (reserve+2 = 12 = drain+2).
- **Sensor:** `sensor.ura_battery_strategy` attribute `reserve_soc` unchanged
  (still the static). NEW attribute `current_offpeak_drain_target` (int)
  reflects the value threaded into the release. (Optional — see D5.)
- **Test:** `test_battery_drain_release_uses_effective_floor` (new) — matrix
  over 5 solar classes × 3 SOC positions (below F−3, at F, at F+3) confirming
  release fires exactly when SOC ≥ F and battery is not discharging.
- **Live (post-deploy):** During the first `off_peak` after HA restart with a
  non-excellent solar class, recorder shows the EVSE state transitions
  `off → on` within 5–10 min of the sensor's `state` attribute reflecting
  `off_peak` and SOC being at/above F. Recorder query:
  ```
  ha_get_history entity_id=switch.garage_a hours=8
  ha_get_history entity_id=sensor.ura_battery_strategy hours=8
  ha_get_state entity_id=sensor.ura_energy_coordinator_ev_status
  ```
  Attribute `pause_reason_human` for `switch.garage_a` MUST NOT show
  "battery drain protection (paused)" (verified string at `energy_pool.py:1663`)
  during off_peak once F is reached.

### D2 — Effective release floor threaded into PLUG drain release (parity)

**Change.** Same fix at the plug drain call site (`energy.py:2941-2947`).
Additionally: add the missing `solar_replenishing=solar_replenishing` kwarg
that the EV call site already computes and passes — the pre-existing L1/L2 gap
from §0.2. Reuse the same `solar_replenishing` local computed at
`energy.py:2848-2862` for the EV call; do not re-compute.

**Files:**
- `domain_coordinators/energy.py:2941-2947` — pass `reserve_soc=F` and
  `solar_replenishing=solar_replenishing`.
- `domain_coordinators/energy_pool.py:1863-2015` — no signature change; docstring
  update mirrors D1.

### Acceptance Criteria
- **Verify:** Both Moes plugs designated as EV chargers (per operator: L1
  plugs at 1.5 kW; entities determined by config, not hardcoded here) release
  from `_paused_by_battery_drain` under the same tick-conditions as garage_a/b.
- **Test:** `test_plug_drain_release_parity_with_evse` — the SAME parametrized
  fixture used in D1 drives both EV and plug controllers and asserts identical
  release timing.
- **Live:** Recorder shows a Moes plug (operator will name the entity in the
  README write-back) transitions `off → on` in lockstep with an L2 EVSE
  during a first non-excellent off_peak after deploy.

### D3 — Cooldown-courtesy behavior preserved (no-op deliverable, must be verified)

**Change.** Explicitly none. Operator decision 2026-07-12 #2: URA re-kill of an
externally-started charge at cooldown expiry is fine.

**Files:** none.

### Acceptance Criteria
- **Verify (regression):** the code path at `energy_pool.py:961-978` (Option B
  manual-override → cooldown 3600s) is unchanged; a targeted test
  `test_manual_override_still_cooldowns_after_deadband_fix` confirms that when
  drain conditions still hold and cooldown expires, URA re-issues `turn_off`.

### D4 — Debounce rider decision (open, present with recommendation)

**The concern.** After D1 lands, the pause boundary sits exactly at floor F.
When the EV turns ON, its ~10-40 A draw is house-load to Envoy → battery may
briefly discharge > 100 W → pause gate at `energy_pool.py:987-994` sees
`battery_discharging AND soc_low` (SOC still < 50 by default threshold) → re-pauses at
the next tick → the release fires again next tick → **oscillation candidate**.

**Reachability analysis.** The pause gate requires SOC < `soc_threshold`
(default 50). At floor F ≤ 40 (unknown), SOC is definitionally below 50 →
soc_low is True. `battery_discharging` triggers on any tick sampling a >100 W
discharge — the `battery_power_w` reading is instantaneous, not smoothed, per
memory search. The EV going ON at 2.26 kW WILL pull the battery briefly (the
`_evse_battery_hold_active` mechanism, `energy_pool.py:305,323`, then commands
`reserve_level = current SOC` on the NEXT battery decision cycle, so the
battery holds its SOC and lets grid cover EV — but that's a lagged response).
Therefore **oscillation IS reachable at the 5-min tick** in the window between
"EV commanded ON" and "battery reacts by holding" (typically 5–15 min due to
Enphase cloud actuation lag; see `ATTAIN_MIN_REMAINING_MIN` context in
`ura-energy-strategy-reference` §4.3).

**Smallest stabilizer options.**

1. **Release-side sticky at effective floor.** When SOC ≤ F within the ±2%
   hysteresis band, do NOT re-engage the drain pause even if
   `battery_discharging` is true, because at the floor the battery has nothing
   left to protect — its own reserve mechanism (via `_evse_battery_hold_active`)
   will command hold; the drain rule is redundant and destructive. Estimated
   3–5 LoC in `energy_pool.py:987-994` (add `and battery_soc > F + 2` to the
   pause gate).
2. **Discharge-persistence hysteresis.** Require `battery_power_w < -100 W`
   for N consecutive ticks (N=2) before engaging the pause. Estimated
   ~10 LoC + a small `_battery_discharge_persist` counter dict per device.
3. **Do nothing.** Accept 1-tick oscillation. Rejected — that's exactly the
   failure mode operators experience as "flicker".

**Recommendation: Option 1 (release-side sticky at floor).** It is the smallest
change, targets the specific reachability path identified above, and does NOT
generalize to a debounce that would mask other pause-worthy conditions. It also
preserves the pause behavior at higher SOC (where drain protection has actual
work to do). Present at the operator checkpoint (§6) with Option 2 as fallback.

### Acceptance Criteria (if D4 = Option 1 confirmed by operator)
- **Verify:** After the release fires and the EV turns ON, no `switch.turn_off`
  originating from `battery_drain` fires again during the same off_peak window
  unless SOC drops below F−2. Recorder query: filter `switch.garage_a` state
  transitions in the 30 min after first ON; expect at most 1 ON, 0 subsequent
  drain-source OFFs. `_paused_by_battery_drain` should be empty at every tick
  observed in that window.
- **Test:** `test_no_reflap_at_floor_when_ev_pulls_battery_transient` — simulate
  SOC=F, then commanded ON, then next-tick battery_power_w=-500 W → assert pause
  NOT re-engaged.

### D5 — Optional: diagnostic attribute on battery-strategy sensor (LOW)

**Change.** Add `current_offpeak_drain_target: int` and
`effective_release_floor: int` attributes to the existing battery-strategy
sensor attribute payload (build in `energy_battery.get_status`, surfaced by
`sensor.py` reusing the existing attribute-forwarding surface — no new sensor
entity, no new CONF).

**Rationale.** Cheap (< 5 LoC), directly answers "why did the EV turn on / not
turn on last night" from the recorder without needing the DB. Include only if
Pass A/B agree it costs no ripple.

### Acceptance Criteria
- **Sensor:** `sensor.ura_battery_strategy` attributes include the two new
  keys; values match the values threaded into the drain calls that tick.
- **Live:** Recorder query at any off_peak minute:
  ```
  ha_get_state entity_id=sensor.ura_battery_strategy
  # attributes.current_offpeak_drain_target == the value in the table for today's class
  # attributes.effective_release_floor == max(reserve_soc, current_offpeak_drain_target)
  ```

---

## 4. Enumeration — every site the fix touches or that could hide the next miss

Paste from grep. (Re-run before build; line numbers WILL drift.)

```bash
grep -n "_paused_by_battery_drain\b" \
  custom_components/universal_room_automation/domain_coordinators/energy_pool.py
grep -n "reserve_soc\s*+\s*2\b" \
  custom_components/universal_room_automation/domain_coordinators/energy_pool.py
grep -n "battery_out_of_capacity\|soc_recovered" \
  custom_components/universal_room_automation/domain_coordinators/energy_pool.py
grep -n "determine_battery_drain_actions" \
  custom_components/universal_room_automation/domain_coordinators/energy.py
grep -n "solar_replenishing" \
  custom_components/universal_room_automation/domain_coordinators/
```

Expected as of this file:
- `reserve_soc + 2` literal — **2 sites**: `energy_pool.py:1028` (EV),
  `energy_pool.py:1971` (plug). BOTH must consume F.
- `determine_battery_drain_actions` call sites — **2 sites**: `energy.py:2863`
  (EV), `energy.py:2941` (plug). Both must pass F AND `solar_replenishing`.
- `_paused_by_battery_drain` mutation sites — several per class (add/discard);
  none of these are floor sites but Pass D re-enumerates to be sure nothing
  new sneaks in.

**Anti-patterns to grep during Pass D:**
- Any `reserve_soc + N` literal with N ≠ 2 — unlikely but a place for a copy-
  paste bug.
- Any place `getattr(self._battery, "reserve_soc", None)` is used to gate a
  release (grep on the full string). Each such site is a candidate to instead
  read the effective floor.
- Any code path that reads `self._battery.reserve_soc` directly and compares to
  SOC without the drain-target reconciliation.

---

## 5. Test plan

### 5.1 Config-boundary corners (Phase 3 in the invariants campaign)

Two independent knobs: `reserve_soc` and `current_offpeak_drain_target`. Test
all four corners plus the excellent-class no-op:

| reserve_soc | drain target | tomorrow_class | Effective floor F | Expected release SOC ≥ | Notes |
|---:|---:|---|---:|---:|---|
| 10 | 10 | excellent | 10 | 12 | byte-identical to today |
| 10 | 15 | good | 15 | 17 | primary bug case |
| 10 | 20 | moderate | 20 | 22 | primary bug case |
| 10 | 30 | poor | 30 | 32 | primary bug case |
| 10 | 40 | unknown | 40 | 42 | conservative default |
| 25 | 20 | moderate | 25 | 27 | inversion: reserve > target; effective = reserve |
| 20 | 20 | moderate | 20 | 22 | equality |

For each row, fabricate a pytest parametrize case in
`quality/tests/test_energy_pool_drain_release.py` (create if missing; verify
against `ls quality/tests/ | grep -iE "energy_pool|drain"` before creating).

### 5.2 Mutation-anchored per-site (Phase 4)

Sites and their anchoring tests:

| Site | Neuter | Anchoring test |
|---|---|---|
| `energy_pool.py:1028` (EV release) | Revert `<= F + 2` back to `<= reserve_soc + 2` | `test_battery_drain_release_uses_effective_floor` fails on the good/moderate/poor rows |
| `energy_pool.py:1971` (plug release) | Same revert on plug | `test_plug_drain_release_parity_with_evse` fails |
| `energy.py:2863-2869` (EV call) | Pass `reserve_soc=self._battery.reserve_soc` (raw, no F) | `test_battery_drain_release_uses_effective_floor` fails |
| `energy.py:2941-2947` (plug call) | Same raw-reserve for plug | `test_plug_drain_release_parity_with_evse` fails |
| `energy.py:2941-2947` (plug `solar_replenishing`) | Drop the kwarg (defaults to False) | `test_plug_soc_recovered_path_respects_solar` fails |

Every mutation must produce a **named** failing test whose message mentions the
site being neutered. If any mutation leaves the suite green, that site is
untested — the fix does not ship until the test is added or the site is
justified in writing as unreachable.

### 5.3 Regression / no-flap

- `test_no_reflap_at_floor_when_ev_pulls_battery_transient` (D4 anchor).
- `test_excellent_class_byte_identical_to_pre_fix` — pin the `tomorrow_class =
  excellent` behavior to today's exact call trace.
- `test_manual_override_still_cooldowns_after_deadband_fix` (D3 anchor).
- `test_restore_evse_battery_drain_paused_across_restart` — DAO restore path at
  `energy.py:1150-1159` unchanged; a device restored into `_paused_by_battery_drain`
  from the DAO must be released on the FIRST post-restart tick if conditions
  hold. Do NOT regress the restore.

### 5.4 Write-volume concern (Bug Class from optimizer flood incident)

The fix changes when `switch.turn_on/off` fires but does NOT add per-tick DB
writes. Confirm no new DAO writes in the changed paths. Include:
- `test_no_new_db_writes_per_tick` — patch the DAO layer and count writes for
  10 simulated ticks; must equal the pre-fix count.

---

## 6. Change control — Tier 3 protocol

Per §2, four framing-disjoint reviews. Framings:
- **A — local correctness.** Arithmetic + kwarg plumbing per site.
- **B — state-machine + integration.** Restart (DAO restore), no-flap over a
  full off_peak → peak → off_peak cycle, interaction with
  `_evse_battery_hold_active` and arbitrage-CHARGE (which uses its own
  `_paused_by_arbitrage`, so must be independent — verify no accidental
  release-blocks the arbitrage set).
- **C — test authority via source mutation.** Table in §5.2 must produce
  FAIL-on-neuter for every load-bearing site.
- **D — adversarial completeness.** Falsify INV-EV-DEADBAND across the whole
  file, not the diff. Grep for every `reserve_soc + N`, every
  `_paused_by_battery_drain` mutation, every `solar_replenishing` consumer.
  Produce a concrete legal-config repro for any leak.

**Orchestrator independent verification before deploy (MANDATORY per
CLAUDE.md).** Human orchestrator personally:
1. Re-runs the greps in §4 and diffs against the counts in this doc.
2. Re-runs the §5.2 mutation on `energy_pool.py:1028` and confirms `≥1 failed`
   in pytest.
3. Reads every `reserve_soc + 2` (or successor arithmetic) in
   `energy_pool.py` and confirms each consumes F, not the raw reserve.

**Operator checkpoint BEFORE deploy.** Surface:
- The §1 invariant, verbatim.
- Pass D completeness table (each reachable path PASS/LEAK).
- The §5.2 mutation results.
- D4 debounce decision — confirm Option 1 (or override to Option 2 / none).
- Cost impact framing: with the fix, expected first-night saving ≈ full off_peak
  charge on a car that was un-charged pre-fix.

**Ship, then live validation, then README write-back.** Standard
`./scripts/deploy.sh <version> <summary> <notes>`. Live validation criteria
already stated per-deliverable above. README `Validated <date>` table MUST
carry: EVSE state transitions, plug state transitions, sensor attribute
snapshots, and the observed floor F for the night validated.

---

## 7. Explicit non-goals

- **No general EVSE refactor.** No pause-owner set consolidation, no rename of
  `_paused_by_*` sets, no touching load-shed dormancy.
- **No cooldown behavior change.** Operator decision 2026-07-12 #2 — do NOT
  fix "URA silently re-kills at cooldown expiry"; that is intentional.
- **No new user-facing config knob.** The effective floor is derived from
  existing config (reserve_soc + drain-target table). If the operator wants to
  tune, they tune the drain-target table via existing surface.
- **No change to `_evse_battery_hold_active`** (`energy_pool.py:305,323`).
  It is the load-side mechanism that makes the fix safe; touching it is a
  separate cycle.
- **No load-shed enablement.** Dormant per operator directive.
- **No SPAN vs Envoy SOC-source change.** Envoy remains authoritative.

---

## 8. Rollback plan

Because the diff is per-call-site parameter reconciliation with no schema or
signal change, rollback is `./scripts/deploy.sh <previous>` — no forward-only
data migration to reverse. The `evse_battery_drain_paused` DAO row shape is
unchanged; devices restored into that set on a rolled-back binary will behave
as they did pre-fix.

If D5 (diagnostic attributes) is included, the attributes disappear on
rollback — this is harmless (no consumer depends on them).

Regression trip-wire (in-code per CLAUDE.md "no soak watching"):
- If `_paused_by_battery_drain` holds ANY device for > 6 hours in a single
  `off_peak` (i.e., > 72 consecutive ticks) — NM-notify. Track in a new
  candidate cycle if not already covered (verify against
  `ura-presence-reliability-campaign` / existing anomaly-emit surface — do NOT
  add here without checking; scope creep).

---

## 9. Open questions for the operator

1. **D4 debounce decision.** Confirm Option 1 (release-side sticky at floor)
   vs Option 2 (2-tick discharge-persistence hysteresis) vs "no debounce, ship
   D1+D2 only". Recommendation in §D4: Option 1.
2. **D5 diagnostic attributes.** Ship in this cycle or defer? Cheap but broadens
   the diff.
3. **Plug entity list for L1/L2 parity live validation.** Which Moes plugs are
   currently designated as EV chargers (config-driven, not hardcoded here)? The
   README write-back table needs the exact entity_ids to validate D2 live.
4. **Solar class this week.** For the first post-deploy night, is
   `tomorrow_class` expected to be non-excellent (i.e., will the fix be
   observable at all on night 1)? If the forecast is "excellent" for the first
   night post-deploy, the fix is byte-identical and D1 acceptance can only be
   proven by test — schedule live-validation for a first non-excellent night.
5. **Tier confirmation.** Confirm Tier 3 (four framings). §2 recommends it;
   flag if the operator wants to run Tier 2-DB instead and skip Pass D
   (strongly not advised given v5.5.5 D-review miss).
