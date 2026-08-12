# PLANNING — HVAC-PRESET-FLAP-1: Off-Phase Setpoint + Mechanism Honesty

**Card:** `HVAC-PRESET-FLAP-1` (docs/planning/kanban.data.yaml:622)
**Sibling (shipped):** `ARREST-COMFORT-1` Cycle A (v5.69.0) — owns the S1-S13 preset/temp write gate table and the `_d3_skipped_this_tick` relabel flag. This cycle LAYERS INSIDE that machinery; it does not redesign it. **This cycle appends S14 to §3.7 of the sibling plan (D0 below).**
**Operator direction (2026-08-11):** fix "**2+1**" — Fix 2 (off-phase setpoint) plus the honesty half of Fix 1 (make the duty off-phase legible as an ENERGY action, not a presence failure). NON-GOAL: retune the duty values / window (Fix 3, audit-gated) and NON-GOAL: occupancy-conditional duty.
**Status:** planning-only. No code changes in this cycle.
**Tier (proposed):** **Tier 2-DB** — one adversarial plan review before build dispatch. Contingent on the rev-2 edits landing (§10). **Reviewer's Tier-3-if-not warning (verbatim from review record):** *"Tier stays 2-DB contingent on these landing"* — if any of the 8 rev-2 edits below regress or are silently dropped, elevate to Tier 3 (four framing-disjoint reviews) before build dispatch.
**Revision:** rev-2 (2026-08-11) — folds one Tier-2-DB adversarial plan review (NEEDS-REVISION with 8 binding edits). Review record §10.
**Probe status:** `docs/planning/AUDIT_hvac_duty_cycle_frequency.md` returned 2026-08-10 (Q1: ~8.7 forced-away/day, coast-window bound, 67 % occupied; Q2: not a recent regression). Audit gates ONLY the Fix-3 tuning cycle (NON-GOAL here). This cycle is **mechanism honesty**, and the audit's occupancy split (67 %) is the direct evidence for shipping it.

---

## 1. Falsifiable invariant (up-front)

> **INV-OFFPHASE-HONESTY.** In an occupied zone (`zone.any_room_occupied` True on this tick — the LIVE dynamic occupancy property, NOT the static `zone_persons` config list), while the duty limiter has forced the off-phase (`zone.runtime_exceeded` True) AND the D3 comfort-delay guard did NOT skip the forced-away this tick (`_d3_skipped_this_tick` False), the following BOTH hold:
> 1. **Setpoint.** The effective cooling ceiling written to the zone's thermostat is `home_target_high + COMFORT_OFFPHASE_OFFSET_F`, where `home_target_high` is `PresetManager.get_seasonal_setpoints(target_preset, now)` cool-leg for the current season and current target preset. It is NEVER equal to the seasonally-configured `away` cool-leg (typically 80 °F).
> 2. **User-visible surface.** No user-visible URA attribute or emitted preset writes "away" for the duration of the off-phase. The ledger row reads `reason=runtime_exceeded_offphase` and carries `duty_cycle_off_phase: True` in `details_json`. A sensor attribute (`duty_cycle_off_phase`) exposes the same bool on `HVACZonePresetSensor` (sensor.py:11411).
>
> The invariant is INERT when:
> (a) `zone.any_room_occupied` False (real vacancy — off-phase → `away` is honest and unchanged);
> (b) `_d3_skipped_this_tick` True (comfort-delay owns the tick);
> (c) house_state is `sleep` (D5 sleep-exempt, unchanged);
> (d) `shed_active` True (§3.5 — shed dominates via tick ordering, order-proof test in D1);
> (e) night-trust suppression fired this tick (`hvac.py:1710` `continue` short-circuits before D5);
> (f) `COMFORT_OFFPHASE_OFFSET_F == 0.0` — admitted degenerate DIAGNOSTIC config (offset 0 collapses the ceiling to the raw home cool baseline, which may still permit compressor demand; this is a legitimate diagnosis mode, NOT an INV violation). Boot INFO log emitted when read at 0.0.

Falsification observations (any one falsifies):
1. Occupied zone (`any_room_occupied=True`), `runtime_exceeded` True, offset > 0: `climate.<entity>.attributes.target_temp_high` reads `≠ home_target_high + OFFSET` (either the away 80 °F ceiling OR an unclamped write).
2. Occupied zone, `runtime_exceeded` True: `climate.<entity>.attributes.preset_mode` == `"away"` for any tick during the off-phase.
3. `HVACZonePresetSensor` state == `away` while `zone.any_room_occupied` True.
4. Shed-active zone: an S14 setpoint write executed AFTER a same-tick shed write silently RAISES the ceiling above the shed-emitted ceiling (order-proof failure — shed dominance regression).
5. Actual vacancy (`zone.any_room_occupied` False) held at `home + OFFSET` (regression: unoccupied zone must still be surrendered to the away ceiling).
6. Off-phase write path emitted via a legacy inline `climate.set_temperature` / `set_preset_mode` bypassing `hvac_setpoint.emit_*` (unroutable through the S-gate machinery).
7. **D6 stale_occupancy branch dominance violated.** With `stale_occupancy=True` (D6 stuck-sensor branch at `hvac.py:1518`), the D5 else-limb executed S14 instead of preserving `effective_preset = "away"` with `reason="stale_occupancy"` on the S1 preset write (would MASK the stuck-sensor NM signal — critical diagnosability regression).
8. **Within-grace vacancy dominance violated.** Zone is vacant but WITHIN grace (`any_room_occupied=False` but `zone_vacant_past_grace=False`, i.e. just-emptied) with `runtime_exceeded=True`: S14 executed with `home + OFFSET` (spends grid coasting an empty room while the grace resolves; must fall through to pre-cycle preset behavior).

The plan-review pass (§7) owns re-enumerating every D5 forced-away consumer AND every `set_preset_mode` emit site against INV-OFFPHASE-HONESTY.

---

## 2. Institutional context verified

### 2.1 Prior planning docs / memory bodies consulted
- Card `HVAC-PRESET-FLAP-1` (kanban.data.yaml:622-713) — mechanism proven, THREE retractions read and not re-litigated: `RETRACTION_2_max_runtime_minutes` (not the cap), `RETRACTION_3_two_writers` (one writer, duty cycling as designed), `LEDGER_RETRACTION_2026_08_09` (`details_json` not `details`).
- `docs/planning/PLANNING_arrester_comfort_delay.md` rev-2 — §3.4 D3 coast-precedence guard, §3.7 S1-S13 per-site verdict table (this cycle APPENDS S14; see D0), §4.6 knob ladder, §8 single-accessor invariant.
- `docs/planning/AUDIT_hvac_duty_cycle_frequency.md` — Q1 (8.7 forced-away/day, 67 % occupied, coast-bound); Q2 (long-standing, not v5.47→v5.64 regression).
- Memory: `feedback_no_fabrication` (Ecobee preset-mode adjudication in §3.6; shed accessor fabrication caught in rev-2), `feedback_suppression_needs_discharge` (off-phase discharge = duty window rolls, backstop = the accumulator itself), `feedback_marginal_benefit_pushback` (§5), `battery_soc_envoy_not_span` (no new SOC read).
- Design doc: `docs/Coordinator/HVAC.md` — reviewed, no new coordinator responsibility.

### 2.2 Greps run + prior-art disposition

| Proposed | Grep target | Result | Disposition |
|---|---|---|---|
| Off-phase forced-away site | `runtime_exceeded` / `effective_preset = "away"` | Exists — `hvac.py:1575-1604` (D5 branch inside preset-apply loop) | **REUSE** — refactor the `else: effective_preset = "away"` limb (:1604) to route through a new sibling helper `_apply_duty_off_phase`. |
| Seasonal home cool-leg | `get_seasonal_setpoints` | Exists — `hvac_preset.py:118` | **REUSE** — helper calls `self._preset_manager.get_seasonal_setpoints(target_preset, now)`. |
| Setpoint write chokepoint | `emit_set_temperature` | Exists — `hvac_setpoint.py:121` (freeze-floor + deadband + `gate=` param) | **REUSE** — off-phase write MUST route through it. New site tag `S14_duty_off_phase`. |
| Preset write chokepoint | `emit_set_preset_mode` | Exists — `hvac_setpoint.py:180` | **NO NEW USE** — off-phase branch stops emitting a preset-mode change. |
| Arrester suppress on setpoint write | `self._override_arrester.suppress(...)` | Exists — `hvac.py:1793` | **REUSE** — off-phase branch must `suppress(zone.climate_entity, kind="temp")` before the emit. |
| Reason ladder | `preset_change_reason = "runtime_exceeded"` | Exists — `hvac.py:1759` | **EXTEND** — new distinct code `runtime_exceeded_offphase` for S14 emits (see §3.3 discriminator rationale). |
| Reason relabel flag `_d3_skipped_this_tick` | `_d3_skipped_this_tick` | Exists — **initialized `False` at `hvac.py:1574`; set `True` ONLY inside the `if _cd_active and …:` arm at `hvac.py:1602`**. Exit-invariant of the D3 arm: never True on the else-limb. | **REUSE** — the plan asserts this by construction; reviewer confirms cite. |
| Live-occupancy attribute | `zone.any_room_occupied` | Exists — dynamic per-tick property populated by the ZoneManager from live occupancy sources | **REUSE** — all predicates in this plan read `zone.any_room_occupied`. **`zone.persons` is NOT a real attribute; `zone_persons` is the STATIC config list at `hvac_const.py:342` — reading it as "current occupants" is A-CRIT-1 shape (fixed in rev-2 across §1, §3.2, §3.3, §6, §10, and the details_json field per M6).** |
| User-visible attribute surface | `sensor.py` zone-preset sensor | Exists — **`HVACZonePresetSensor` at `sensor.py:11411`**, `extra_state_attributes` dict at `sensor.py:11443-11469` (open point 1 closed in rev-2) | **REUSE** — add `duty_cycle_off_phase` key to that dict (~:11456). |
| Bypass site check — `set_preset_mode` inline | rg `set_preset_mode` in `custom_components/` | Migrated by ARREST-COMFORT-1 rev-2 §3.7 to `emit_set_preset_mode` (3 sites) | **VERIFY DURING BUILD** — re-grep before dispatch. |
| Ecobee preset-modes discovery | `attr_preset_modes`, `preset_modes` attr | No hard-coded list in URA source | **NO NEW CUSTOM PRESET** — §3.6. |
| Shed target accessor | `shed.*target|shed_setpoint|shed_ceiling|_shed_target|load_shed.*temp` in `domain_coordinators/` | Grep run in rev-2 — hits in `energy.py:7059-7092` describe shed *targets* (level enum) and shed *actions*; **NO coordinator-level `current_shed_target_high` numeric accessor exposed to HVACCoordinator was found.** The rev-1 `min(cool_baseline + OFFSET, current_shed_target_high)` mitigation would have FABRICATED an accessor. | **REVISED** — shed dominance is enforced by **tick ordering + order-proof behavioral test**, NOT by a fabricated accessor. See §3.5 shed row + D1 test `test_shed_write_survives_s14`. |

**All new symbols namespaced `COMFORT_OFFPHASE_*` / `duty_cycle_off_phase*`** — no collision with `OVERRIDE_*`, `COMFORT_*` (ARREST-COMFORT), or `DUTY_CYCLE_*`.

### 2.3 Code locations surveyed end-to-end
- `hvac.py` :1420-1620 (D5 duty branch + D3 comfort-delay guard, `_d3_skipped_this_tick` init at :1574 + set at :1602, D6 stale_occupancy at :1518, `zone_vacant_past_grace` at :1463); :1712-1856 (reason-ladder derivation, S1 gate call).
- `hvac_setpoint.py` :1-230 (both chokepoints, gate semantics, deferred-write ledger row).
- `hvac_preset.py` :55-120 (season / baseline map, `get_seasonal_setpoints`, `get_preset_for_house_state`).
- `hvac_const.py` :342 (`CONF_ZONE_PERSONS` — CONFIRMED static config list, NOT live occupancy), :392-420 (duty knobs, ARREST-COMFORT knob namespace).
- `sensor.py` :11411-11469 (`HVACZonePresetSensor`, `extra_state_attributes`).
- `energy.py` :7059-7092, :7174 (shed action machinery — no coordinator-exposed numeric shed ceiling).

---

## 3. Design

### 3.1 Config-vs-code adjudication (operator's cheapest-candidate question)

The card asked whether the fix could be **CONFIG**. **Verdict: NO, it must be code + one new knob.** Evidence:

1. The seasonal baseline map at `hvac_preset.py:55-68` is keyed `(season, preset)`. The `away` preset row is legitimately consumed by the **real-vacancy** path (`vacant_past_grace`, `stale_occupancy`) via other branches in the SAME D5 loop. Tightening the `away` row globally would collapse actual vacancy conservation (~80 °F → ~home+2) — large-blast-radius, falsifies INV #5.
2. Adding a new preset name (e.g. `eco`) and mapping the D5 off-phase to it requires the target thermostat to *support* that preset. Ecobee's `preset_modes` list is device-emitted; URA does not fabricate. **No-fabrication rule applies.**
3. The **honest** signal is not a preset at all — it is a setpoint held at `home + small_offset` so the compressor coasts, with a boolean attribute + distinct ledger reason. This is what the invariant demands.

Therefore: **code** — reroute the D5 forced-away branch to write a `set_temperature` ceiling instead of `set_preset_mode` "away", with ONE new operator knob (`COMFORT_OFFPHASE_OFFSET_F`, default 2.0 °F) + one kill-switch.

### 3.2 D1 — Off-phase setpoint helper

New helper on `HVACCoordinator` (private to `hvac.py`):

```
async def _apply_duty_off_phase(
    self, zone, target_preset: str, *, reason: str = "runtime_exceeded_offphase",
) -> bool:
    """Route the D5 duty-limiter off-phase through a setpoint write instead
    of a preset write. Returns True if a write was issued, False if the
    S14 gate deferred (mirrors emit_set_preset_mode's contract).
    """
```

Behavior:
1. Compute `cool_baseline, heat_baseline = self._preset_manager.get_seasonal_setpoints(target_preset, now)`. If None (unknown preset), return False and log one-shot WARN (fall through to pre-cycle preset behavior at the call site).
2. `high = cool_baseline + self.comfort_offphase_offset_f`; `low = heat_baseline` (no unilateral heat drop; `emit_set_temperature`'s deadband invariant raises `high` if it collides with `low + MIN_DEADBAND`).
3. `self._override_arrester.suppress(zone.climate_entity, kind="temp")`.
4. Build `_s14_gate` — a zero-arg closure returning `comfort_delay_active(zone_id)`. Per-reason defer-set: `runtime_exceeded_offphase` IS in the defer-set (aligns with S1's treatment of `runtime_exceeded`).
5. Call `emit_set_temperature(hass, zone.climate_entity, target_temp_low=low, target_temp_high=high, freeze_active=self.freeze_active, gate=_s14_gate, site="S14_duty_off_phase", zone_id=zone_id, reason=reason)`.
6. Return the callee's bool.

**Call site: `hvac.py:1604` — the D5 else-limb.** New shape (rev-2 M2 expansion — dominance short-circuit list is EXHAUSTIVE):

```
else:
    # rev-2: dominance short-circuits BEFORE _apply_duty_off_phase.
    # Any True predicate here means an existing branch owns this tick;
    # we preserve the pre-cycle `effective_preset = "away"` path so the
    # correct reason (stale_occupancy / vacant_past_grace) fires on S1.
    if (
        stale_occupancy                              # D6 stuck-sensor (:1518) — INV #7
        or zone_vacant_past_grace                    # real vacancy — INV #5
        or not zone.any_room_occupied                # within-grace vacancy — INV #8
        or not self.hvac_offphase_honesty_enabled    # kill-switch OFF
    ):
        effective_preset = "away"
    else:
        written = await self._apply_duty_off_phase(zone, target_preset)
        if not written:
            continue                                 # deferred by comfort-delay gate
        # DO NOT set effective_preset = "away"; leave it as target_preset
        # so the S1 preset path is a no-op (should_change_preset False).
        zone_runtime_offphase_this_tick = True
```

Semantics guarantee:
- `effective_preset` remains `target_preset` (typically `home`), so the S1 preset-emit path is skipped by `should_change_preset` (:1717). No two-writer race. INV #2 held by construction.
- All four dominance short-circuits preserve the pre-cycle reason on the S1 preset write path (stale_occupancy → `stuck-sensor NM signal via reason-ladder`; vacant_past_grace → `vacant_past_grace`; within-grace vacancy → `runtime_exceeded` unchanged from today; kill-switch → `runtime_exceeded` unchanged from today). No signal is silently masked.

### 3.3 D2 — Ledger + D3 attribute honesty (Fix 1 half)

**Ledger row.** Synthetic `preset_change_suppressed` row at the D5 off-phase site (mirror of the night-trust suppression row at `hvac.py:1687-1709`), episode-gated on a new per-(zone, house_state) cache `_offphase_logged`:
- `action="preset_change_suppressed"`
- `reason="runtime_exceeded_offphase"` (**distinct code** — rev-2 open-point-2 adjudication kept: post-deploy DB queries prove the migration without JSON parsing).
- `details_json.duty_cycle_off_phase = True`
- `details_json.would_have_written_preset = "away"`
- `details_json.setpoint_high_written = high`
- `details_json.home_persons` — **rev-2 M6 adjudication**: live list of `zone_persons` entries whose `person.<entity>.state == "home"` at emit tick (mirrors the night-trust row shape at `hvac.py:1706` verbatim). NEVER the static `zone_persons` config list; NEVER a synthesized `zone.persons` attribute that does not exist.

**Sensor attribute.** Add `duty_cycle_off_phase: bool` to `HVACZonePresetSensor.extra_state_attributes` at `sensor.py:~11456` (inside the existing dict, adjacent to `preset_mode`). Value:

```python
"duty_cycle_off_phase": bool(
    zone.runtime_exceeded
    and zone.any_room_occupied
    and not getattr(hvac, "_d3_skipped_current_tick", False)
),
```

If exposing `_d3_skipped_this_tick` cross-tick is impractical (it is a local in the preset-apply loop), the builder promotes it to `HVACCoordinator._d3_skipped_current_tick` per-zone dict updated each tick — one-line change adjacent to the existing per-tick assignment.

**Rule of thumb applied:** distinct reason CODE for ledger clarity; live `home_persons` list for episode correlation and to avoid the CRIT-shape confusion with static config.

### 3.4 D4 — Restart / boot behavior + episode discharge (B3/B4 fix-up adjudication)

- Off-phase state is NOT persisted across restart. On boot, `zone.runtime_exceeded` is re-derived from live accumulation. The first post-boot tick that crosses the cap re-enters `_apply_duty_off_phase`.
- `_offphase_logged` cache resets on coord init (matches `_night_trust_logged` at `hvac.py:1659`); one boot-transient extra ledger row per zone per episode is acceptable (documented in the README validation section).
- Kill-switch state IS persisted. If `hvac_offphase_honesty_enabled` False at boot, coordinator logs WARN.
- If `COMFORT_OFFPHASE_OFFSET_F == 0.0` at boot, coordinator logs INFO (INV inertness clause (f) — legitimate diagnostic).
- Kill-switch flipped OFF mid-episode: the next D5 tick takes the dominance short-circuit (`effective_preset = "away"`); `_offphase_logged` cache is stale but harmless.

**Episode granularity (B4 fix-up adjudication):** episode-gating is
**per-(zone, house_state)** — exactly ONE `preset_change_suppressed` row
per house_state occupancy of the off-phase condition, discharged on
house_state transition. This is NOT a rolling-window episode:
runtime_exceeded flapping True→False→True inside the same house_state
produces ONE row across the whole span (matches the sibling
`_night_trust_logged` behavior). The paired throttle discharge
(`_last_offphase_emit`) fires when `runtime_exceeded` clears OR
house_state transitions.

**Ceiling-held-until-next-preset-transition (B3 fix-up adjudication —
option (a), doc-only):** by design, once the S14 helper writes the
`home + OFFSET` ceiling and later `runtime_exceeded` clears, URA
does NOT emit a "resume" `set_temperature` back to the raw home cool
baseline. The ceiling holds at `home + OFFSET` until the next preset
transition (the S1 preset write path on any house_state or preset
change re-emits the range for the new preset). Rationale: an
edge-detector re-emit would introduce a NEW writer to the shared S1
chokepoint machinery for pennies of comfort benefit (the operator
notices `home + 2°F` for a coast tail, not a comfort event), and
would defeat the throttle map's purpose. Trade-off accepted per
Marginal-Benefit Decomposition. Acceptance criterion covered by
`test_ceiling_held_until_next_preset_transition` in D1 (verify no
`set_temperature` call fires when `runtime_exceeded` drops False
without a preset transition).

### 3.5 D5 — Precedence table (spec'd, not inferred; rev-2 rows added)

| Condition | Behavior | Cite |
|---|---|---|
| `sleep` house_state | D5 branch skipped entirely (unchanged) | hvac.py:1575 pre-existing gate |
| **`shed_active` True (rev-2 revision)** | S14 does NOT consult a numeric shed accessor (none exists — see §2.2 shed row). Dominance is enforced by **tick ordering**: the shed layer writes `set_temperature` earlier in the same tick sweep; the S14 write MUST NOT execute AFTER a same-tick shed write on the same entity. Two implementation options for the builder to pick between with a source read: (a) an explicit `if self.shed_active: return False` early-return in `_apply_duty_off_phase` (simplest, most conservative — off-phase silent during shed); (b) confirm via source read that shed's own tick already forced the ceiling below `home + OFFSET` and let S14 run harmlessly (only if a builder-time grep confirms shed always runs first AND writes a strictly lower ceiling). **Default recommendation: (a).** Order-proof behavioral test `test_shed_write_survives_s14` in D1 asserts that with `shed_active=True`, either no S14 emit occurs OR a shed-emitted `target_temp_high` observed at end-of-tick is not raised by S14. | rev-2 adjudication — no fabricated accessor |
| `_d3_skipped_this_tick` True | D3 comfort-delay owns the tick; D5 off-phase branch does NOT fire (the `if _cd_active and …:` arm returns without running the else). Unchanged from ARREST-COMFORT §3.4. | hvac.py:1588-1602 (init False at :1574, True at :1602) |
| **`stale_occupancy` True (rev-2 row — D6 stuck-sensor at hvac.py:1518)** | Dominance short-circuit fires (§3.2 predicate list). `effective_preset` stays `"away"`; the reason ladder emits `reason="stale_occupancy"` on the S1 preset write; the `_stuck_signal_nm` NM fire (:1534-1551) STILL executes because D6 sets its own flags. S14 does NOT run. **This is critical: masking stale_occupancy would suppress the stuck-sensor NM alert.** Falsification #7. | hvac.py:1518, :1755 |
| `zone_vacant_past_grace` True + off-phase concurrent | The `zone_vacant_past_grace` branch runs FIRST (:1463) and sets `effective_preset = "away"`. In the D5 else-limb, the dominance short-circuit preserves that away preset write. INV #5. | hvac.py:1463 |
| **`zone.any_room_occupied` False AND `zone_vacant_past_grace` False (rev-2 row — within-grace vacancy)** | Zone just emptied, D1 grace window not yet expired, but `runtime_exceeded` True. Dominance short-circuit fires (`not zone.any_room_occupied`). Preset falls through to pre-cycle `"away"` on the S1 path with `reason="runtime_exceeded"`. Rationale: coasting an empty room at `home + OFFSET` spends grid uselessly; the correct behavior is the pre-cycle preset flap while the grace resolves — behavior identical to today. Falsification #8. | hvac.py:1456-1461 (grace derivation), rev-2 M2 |
| `freeze_active` True | `emit_set_temperature` already applies the freeze floor + deadband; no override needed. `low` from season's home-heat baseline so no unilateral drop below current heat. | hvac_setpoint.py:58-63 |
| Night-trust suppression (home_night / waking / sleep flanks) | Night-trust branch at :1643-1710 `continue`s the loop BEFORE D5 is reached. Off-phase during night-trust emits neither S1 nor S14. Reviewer confirms no other early-return between night-trust and D5 that could invalidate this ordering. INV inertness clause (e). | hvac.py:1643-1710 |
| Guest / vacation preset (target_preset ≠ home) | Recompute `high` from `get_seasonal_setpoints(target_preset, now)` cool-leg + OFFSET. Helper signature takes `target_preset`. Vacation off-phase becomes vacation-high + OFFSET. Guard: if `get_seasonal_setpoints` returns None, helper returns False and logs one-shot WARN; call site falls through to `effective_preset = "away"` (pre-cycle). | hvac_preset.py:55-68 |

### 3.6 Ecobee preset-mode adjudication (no-fabrication check)

Unchanged from rev-1: attr-based honesty; no new custom preset name; no fabrication of Ecobee `preset_modes` support. See §3.1 item 2.

### 3.7 Non-goals (explicit)

- **Retune duty values / window.** `DUTY_CYCLE_COAST`, `DUTY_CYCLE_SHED`, `DUTY_CYCLE_WINDOW_SECONDS` unchanged.
- **Occupancy-conditional duty.** No change to WHEN the limiter trips.
- **New preset name.** §3.6.
- **Multi-thermostat-per-zone.** Same probe-derived simplification as ARREST-COMFORT-1.
- **Battery-SOC gating of off-phase.** This cycle does not read SOC.
- **Change to the S1 preset-write path.** Untouched. This cycle only adds S14 alongside S1.

---

## 4. Knob ladder (per "Numbers Get Knobs")

| Constant | Rung | Default | Range | Kill-switch / degenerate semantics |
|---|---|---|---|---|
| `COMFORT_OFFPHASE_OFFSET_F` | **RUNG 3 — Number entity, persisted** | `2.0` °F | `[0.0, 6.0]` step 0.5 (**MIN 0.0 kept, rev-2 M7**) | `0.0` = admitted degenerate DIAGNOSTIC config: the off-phase ceiling collapses to the raw home cool baseline; cooling demand may still trigger. INV inertness clause (f) covers this. Boot INFO log emitted when read at 0.0. |
| `CONF_COMFORT_OFFPHASE_OFFSET_F` | (companion) | — | — | Config key for options-flow persistence. |
| `DEFAULT_COMFORT_OFFPHASE_OFFSET_F` | (companion) | `2.0` | — | Seeded into the Number entity on first boot. |
| `MIN_COMFORT_OFFPHASE_OFFSET_F` / `MAX_COMFORT_OFFPHASE_OFFSET_F` | (companion) | `0.0` / `6.0` | — | Number entity bounds. |
| `hvac_offphase_honesty_enabled` | **RUNG 3 — Switch entity, persisted** | `True` | on/off | **Feature kill-switch.** `False` → D5 else-branch takes the dominance short-circuit and writes `effective_preset = "away"` (pre-cycle behavior byte-identical). Boot-WARN log emitted when False. |

Why RUNG 3: the offset is legitimately tuneable by observation; the kill-switch is the correct rung for a *behavioral-migration* toggle so a regression in the wild is one dashboard tap away from mitigated.

---

## 5. Marginal-benefit decomposition

Simplest version = **just the honesty half** (D3 attribute + distinct ledger reason, KEEP the `preset=away` write). ~30 LoC.

Fix-2 addition (off-phase setpoint) = ~60 LoC + one knob + one S-gate site. Marginal benefit: kids at 76-78 °F during off-phase instead of 80 °F on an 80 °F evening. Marginal risk: one new setpoint-write site inheriting the S1 chokepoint machinery byte-for-byte; fires ~8.7×/day per audit (frequent path — organically observable).

**Verdict:** ship 2+1 together. Marginal comfort benefit clearly pays for the marginal wiring risk.

**Parked:** SOC-conditioned off-phase relaxation (parent card option (c)); per-thermostat custom preset (§3.6); Fix-3 duty retuning (audit-gated, no target yet).

---

## 6. Deliverables + acceptance criteria

### D0: Append S14 row to `PLANNING_arrester_comfort_delay.md` §3.7
Mechanical edit to the sibling plan's per-site verdict table: add `S14_duty_off_phase | emit_set_temperature | DEFER | reason=runtime_exceeded_offphase` row with a one-line note that this site is introduced by HVAC-PRESET-FLAP-1. Ensures §3.7 remains the single source of truth for gate-site enumeration.

**Acceptance criteria**
- **Verify:** `PLANNING_arrester_comfort_delay.md` §3.7 contains an S14 row with DEFER verdict, reason `runtime_exceeded_offphase`, and a cross-ref to this plan.
- **Live:** N/A (documentation deliverable).

### D1: `_apply_duty_off_phase` helper + D5 call-site rewire
Refactor `hvac.py:1575-1620` D5 branch: dominance short-circuit list (§3.2) then helper on the else-limb; helper routes through `emit_set_temperature` with S14 gate.

**Acceptance criteria**
- **Verify:** unit test with `zone.any_room_occupied=True` + `runtime_exceeded=True` + `_d3_skipped_this_tick=False` + kill-switch ON + not shed observes ONE `climate.set_temperature` call with `target_temp_high == home_cool + 2.0` and ZERO `set_preset_mode` calls.
- **Verify:** `zone_vacant_past_grace=True` + `runtime_exceeded=True` observes S1 `set_preset_mode("away")` and ZERO S14 writes (INV #5).
- **Verify:** `_d3_skipped_this_tick=True` observes ZERO S14 writes.
- **Verify:** `stale_occupancy=True` observes S1 `set_preset_mode("away")` with ledger `reason="stale_occupancy"` AND the `_stuck_signal_nm` fire executes AND ZERO S14 writes (INV #7).
- **Verify:** `any_room_occupied=False` AND `zone_vacant_past_grace=False` (within-grace vacancy) + `runtime_exceeded=True` observes ZERO S14 writes; behavior matches pre-cycle (S1 `set_preset_mode("away")`, `reason="runtime_exceeded"`) (INV #8).
- **Verify:** `shed_active=True`: order-proof — a shed-emitted `target_temp_high` observed at end-of-tick is NOT raised by S14 (either S14 short-circuited on shed_active per §3.5 option (a), OR the observed final ceiling is `<= shed_target_high`).
- **Verify:** `freeze_active=True` — `emit_set_temperature` deadband invariant holds.
- **Verify:** `target_preset="vacation"` — helper reads vacation cool baseline + OFFSET.
- **Verify:** night-trust suppression active — ZERO S14 writes.
- **Test:** `TestDutyOffPhaseSetpoint::test_writes_home_plus_offset`, `test_yields_to_vacant_past_grace`, `test_yields_to_comfort_delay`, `test_yields_to_d6_stale_occupancy`, `test_yields_to_within_grace_vacancy`, `test_shed_write_survives_s14`, `test_freeze_deadband_honored`, `test_vacation_target_preset`, `test_night_trust_short_circuits`.
- **Sensor:** during a duty off-phase, `climate.<zone>.attributes.target_temp_high` reads `home_cool + 2.0`; `climate.<zone>.attributes.preset_mode` reads `home` (or the current house-state preset), NEVER `away`.
- **Live:** during the 21:00-01:00Z coast window, on a zone that trips `runtime_exceeded` with `zone.any_room_occupied=True`, observe `climate.thermostat_upstairs.attributes.target_temp_high` step to `home_cool + 2.0`, NOT 80; `preset_mode` unchanged.
- **Live (B5 fix-up):** post-B1 throttle fix, verify on the real Bryant thermostat that the `hold_activity` manual echo emitted after `SUPPRESS_TTL_SECONDS` does NOT register as an operator manual. Concretely: during an active off-phase episode, the arrester's per-zone override counter (`sensor.ura_hvac_arrester_overrides_today_<zone_id>` or the zone_preset attribute `overrides_today`) MUST stay flat — the throttle map prevents re-emitting the SAME `(low, high)` pair every tick, keeping the URA-emitted write inside a single `SUPPRESS_TTL_SECONDS` window. If the counter increments during an S14 hold, the throttle is over-emitting and the write is landing outside the suppress TTL.
- **Live (B3 fix-up):** when `runtime_exceeded` clears mid-house_state (episode ends without a preset transition), verify NO `set_temperature` write fires — the ceiling holds at `home + OFFSET` until the next preset transition by design. Check `ura_activity_log` for the absence of a follow-on `preset_change` / setpoint restore in the minutes after the tail-end of an episode; observe `climate.<zone>.attributes.target_temp_high` remains at `home + OFFSET` until the next house_state or preset flip.

### D2: Ledger reason + episode-gated suppressed-preset row
Add the `preset_change_suppressed` row with `reason=runtime_exceeded_offphase`, `details_json.duty_cycle_off_phase=True`, `details_json.setpoint_high_written`, `details_json.home_persons` (live list per §3.3), episode-gated on `_offphase_logged`.

**Acceptance criteria**
- **Verify:** a 30-tick simulated off-phase episode produces exactly ONE `preset_change_suppressed` row.
- **Verify:** the row carries `reason="runtime_exceeded_offphase"` and `details_json.duty_cycle_off_phase is True`.
- **Verify:** `details_json.home_persons` matches the LIVE `person.<entity>.state == "home"` filter over `zone_persons` at tick time, NOT the static `zone_persons` config list.
- **Test:** `TestOffphaseLedger::test_one_row_per_episode`, `test_reason_string`, `test_home_persons_live_not_static_config`.
- **Live:** query `ura_activity_log` after a coast-window off-phase; expect ≥1 row per (zone, episode) with the new reason; no `preset_change` rows with `reason=runtime_exceeded` for the same episode window.

### D3: `duty_cycle_off_phase` sensor attribute
Add boolean to `HVACZonePresetSensor.extra_state_attributes` (sensor.py:~11456).

**Acceptance criteria**
- **Verify:** attribute is True iff `zone.runtime_exceeded and zone.any_room_occupied and not _d3_skipped_current_tick`.
- **Verify:** attribute is False when the zone is genuinely vacant (`any_room_occupied=False`).
- **Test:** `TestDutyOffPhaseAttr::test_true_during_occupied_offphase`, `test_false_during_true_vacancy`.
- **Live:** `sensor.ura_hvac_zone_preset_<zone_id>` attributes show `duty_cycle_off_phase: true` during an observed off-phase episode; the friendly state remains `home`.

### D4: Knobs (`COMFORT_OFFPHASE_OFFSET_F` Number + `hvac_offphase_honesty_enabled` Switch)
Persisted entities mirroring `ComfortGraceMinutesNumber` from ARREST-COMFORT-1.

**Acceptance criteria**
- **Verify:** setting Number to 3.0 updates `HVACCoordinator.comfort_offphase_offset_f` without restart; the next off-phase write uses 3.0.
- **Verify:** flipping Switch OFF → next off-phase takes the dominance short-circuit and writes `effective_preset = "away"` (pre-cycle path). Restart with Switch OFF emits boot-WARN.
- **Verify (rev-2 M7):** setting Number to `0.0` — helper still executes (INV inertness (f)), writes `target_temp_high == home_cool + 0.0`, and boot with `0.0` emits INFO log (NOT WARN — 0 is a legitimate diagnostic, not a violation).
- **Test:** `TestOffphaseKnobs::test_offset_live_read`, `test_kill_switch_reverts_to_preset_write`, `test_kill_switch_boot_warn`, `test_offset_zero_is_diagnostic_not_violation`.
- **Live:** operator tap of the Number tile changes the ceiling on the next off-phase.

### D5: README v-next validation table
Post-deploy Live rows for D0/D1/D2/D3/D4 per the "Record Live Validation Back Into the README" mandate — one row per acceptance criterion, marked PASS/FAIL with observed evidence.

---

## 7. Tier proposal + review protocol

**Tier 2-DB** with the plan-review pre-gate (per operator's 2026-08-11 Plan Review policy) — **contingent on the 8 rev-2 edits (§10) landing in this plan before build dispatch**. Reviewer's Tier-3 warning verbatim: *"Tier stays 2-DB contingent on these landing"* — otherwise elevate to Tier 3.

Rationale for NOT Tier 3 (contingent):
- S14 mirrors S1's Tier-3-hardened chokepoint machinery from v5.69.0.
- Small-surface invariant (one added write site, one removed write site, one attribute, one ledger row).
- No new cross-coordinator surface.

**Adversarial plan review MUST re-verify (with `git grep`, not trust):** items unchanged from rev-1 §7 items 1-6 + rev-2 additions:
7. Every current site setting `effective_preset = "away"` inside `hvac.py`: confirm the §3.2 dominance short-circuit list is EXHAUSTIVE (D6 stale_occupancy at :1518, zone_vacant_past_grace at :1463, D5 else-limb at :1604; the D3 arm at :1588-1602 does NOT set effective_preset to away, it skips forced-away).
8. Confirm `zone.any_room_occupied` is the dynamic per-tick property (grep the ZoneManager) and NOT a static/derived-once value; confirm there is no other `zone.persons` attribute silently populated by anyone.

**Build-phase reviews:** standard Tier 2-DB three framing-disjoint pattern (correctness + edge cases / cross-coordinator + precedence / test-authority via per-site source mutation). Live validation Review D confirms observed values via `climate.<entity>.attributes` reads and a `ura_activity_log` query per D2.

---

## 8. Open points (rev-2 status)

1. ~~Sensor entity resolution.~~ **CLOSED (rev-2 M5).** `HVACZonePresetSensor` at `sensor.py:11411`; attribute added to `extra_state_attributes` at ~:11456.
2. ~~Ledger discriminator retention.~~ **CLOSED (rev-2 M4 adjudication).** Distinct code `runtime_exceeded_offphase` kept.
3. ~~Shed-dominance accessor sharpening.~~ **CLOSED (rev-2 M3).** No fabricated accessor; tick ordering + order-proof behavioral test `test_shed_write_survives_s14`; default recommendation option (a) (`if self.shed_active: return False`).
4. ~~Off-phase during night-trust — ordering re-verification.~~ **STANDING (verify at build):** reviewer confirms no early-return between :1710 (night-trust `continue`) and :1575 (D5 gate) that could invalidate the ordering claim under any house_state configuration.

---

## 9. Change surface summary

**Files touched (predicted):**
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` (D5 else-limb rewire + dominance short-circuit + `_apply_duty_off_phase` helper + episode-gated ledger emit + `_offphase_logged` cache + `_d3_skipped_current_tick` per-zone dict; ~90 LoC)
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py` (`COMFORT_OFFPHASE_*` constants block; ~15 LoC)
- `custom_components/universal_room_automation/number.py` (`ComfortOffphaseOffsetNumber`; ~40 LoC)
- `custom_components/universal_room_automation/switch.py` (`HvacOffphaseHonestyEnabledSwitch`; ~30 LoC)
- `custom_components/universal_room_automation/sensor.py` (add `duty_cycle_off_phase` attribute to `HVACZonePresetSensor.extra_state_attributes` at ~:11456; ~5 LoC)
- `quality/tests/test_hvac_offphase.py` (new; ~300 LoC covering D1-D4 criteria incl. rev-2 additions)
- **`docs/planning/PLANNING_arrester_comfort_delay.md` (rev-2 D0 — append S14 row to §3.7; ~5 LoC)**
- `docs/readmes/README_v<next>.md` (pre-deploy prospective + post-deploy validated)

**Backward compatibility.** Kill-switch OFF byte-identically restores pre-cycle behavior. No config-entry migration.

---

## 10. Report + rev-2 review record

### 10.1 Report (per orchestrator brief)

**Invariant.** INV-OFFPHASE-HONESTY (§1) — `zone.any_room_occupied` True + `runtime_exceeded` True + not-D3-skipped ⇒ ceiling == `home_target_high + OFFSET` (from `target_preset`) AND no user-visible surface says "away".

**Deliverables.** D0 append S14 to ARREST-COMFORT §3.7; D1 helper + call-site rewire w/ EXHAUSTIVE dominance short-circuit; D2 ledger row + distinct reason + LIVE `home_persons`; D3 sensor attribute on `HVACZonePresetSensor`; D4 knobs (offset RUNG 3 + kill-switch RUNG 3); D5 README validation write-back.

**Config-vs-code adjudication (§3.1 verdict).** CODE. Config edit corrupts real-vacancy (INV #5); new preset name violates No-Fabrication. Scoped fix: remove `preset=away` write from off-phase, replace with `set_temperature` at `home + OFFSET`, expose via attribute + distinct ledger reason. One new knob + one kill-switch.

**Open points (§8).** All rev-1 open points closed in rev-2 except night-trust ordering re-verification (standing, verify at build).

### 10.2 Rev-2 plan-review record

**Reviewer disposition:** NEEDS-REVISION. Tier warning: *"Tier stays 2-DB contingent on these landing."*

| # | Rev-2 edit (binding) | Disposition |
|---|---|---|
| M1 | **A-CRIT-1 shape**: GLOBAL replace `zone.persons` → `zone.any_room_occupied` (6 occurrences: §1 invariant + inertness (a), §3.2 predicate list, §3.3 D3 attribute expression, §6 D1+D3 acceptance criteria, §10 report). Root cause: `zone.persons` is not a real attribute; `zone_persons` is the static config list at `hvac_const.py:342`. | **APPLIED** across §1, §3.2, §3.3, §6, §10; §2.2 adds a dedicated grep row confirming `any_room_occupied` as the live per-tick property; §2.3 pins `zone_persons` cite to `hvac_const.py:342` with CONFIRMED "static config list" note. |
| M2 | **Exhaustive dominance short-circuit** in §3.2 else-limb: `stale_occupancy or zone_vacant_past_grace or not zone.any_room_occupied or not hvac_offphase_honesty_enabled` BEFORE `_apply_duty_off_phase`; add §3.5 rows for D6 stale_occupancy (hvac.py:1518 — away dominates, ledger reason `stale_occupancy` unmasked) and within-grace vacancy; falsifications #7/#8; tests `test_yields_to_d6_stale_occupancy` + `test_yields_to_within_grace_vacancy`. | **APPLIED** — §3.2 code shape rewritten with the 4-predicate short-circuit; §3.5 gains two new rows; §1 falsification list gains #7 (stale_occupancy masking = stuck-sensor NM regression) and #8 (within-grace vacancy energy waste); D1 acceptance criteria gain both tests. |
| M3 | **Shed dominance**: no fabricated `current_shed_target_high` accessor. Grep the shed layer; if no coordinator-visible accessor exists, document dominance as **tick ordering + order-proof behavioral test** (a shed write in the same tick survives the S14 write). | **APPLIED** — grep run (§2.2 shed row): `energy.py:7059-7092`, `energy.py:7174` describe shed level enum + actions, NO numeric shed ceiling accessor exposed to HVACCoordinator. §3.5 shed row rewritten: default recommendation option (a) (`if self.shed_active: return False` early-return in `_apply_duty_off_phase`); order-proof test `test_shed_write_survives_s14` in D1. Rev-1's `min(cool_baseline + OFFSET, current_shed_target_high)` mitigation retracted as fabricated. |
| M4 | **Explicit deliverable + §9 file entry**: append S14 row (DEFER, reason `runtime_exceeded_offphase`) to `PLANNING_arrester_comfort_delay.md` §3.7. | **APPLIED** — new D0 deliverable added with acceptance criterion; §9 file surface adds the sibling-plan edit. |
| M5 | **Close open point 1**: `HVACZonePresetSensor` at `sensor.py:11411`, attribute placement in `extra_state_attributes` at ~:11456. | **APPLIED** — §2.2 sensor row cites `sensor.py:11411` + `:11443-11469` (extra_state_attributes dict); §3.3 sensor sub-section pins insertion at ~:11456; §8 item 1 marked CLOSED. |
| M6 | **details_json field adjudicated**: `home_persons` (live list, matches night-trust row shape at `hvac.py:1706`) — NEVER the static config list. | **APPLIED** — §3.3 ledger sub-section pins `details_json.home_persons` as the LIVE `person.<entity>.state == "home"` filter over `zone_persons`; D2 gains `test_home_persons_live_not_static_config`. |
| M7 | **Knob adjudicated**: keep MIN 0.0, add INV inertness clause (f) "offset=0 = admitted degenerate diagnostic config, INV #1 inert" + matching D4 test — 0 is a legitimate diagnostic, NOT a violation. | **APPLIED** — §1 invariant gains inertness clause (f); §4 knob table keeps MIN 0.0 with degenerate semantics; §3.4 boot behavior gains INFO log at 0.0; D4 gains `test_offset_zero_is_diagnostic_not_violation`. |
| M8 | **§2.2 row 7 citation fix**: `_d3_skipped_this_tick` initialized `False` at `hvac.py:1574`, set `True` ONLY in the `if _cd_active and …:` arm at `hvac.py:1602`. | **APPLIED** — §2.2 row rewritten with precise :1574 (init) + :1602 (set) cites; §3.5 D3 row echoes same cite; §2.3 code-survey list adds :1574 + :1602 anchors. |

**Rev-2 completeness re-enumeration:** the §3.2 dominance short-circuit list is now the AUTHORITATIVE enumeration for D5 else-limb behavior. Any future D5 branch that forces `effective_preset` must be added to §3.5 AND to the short-circuit list AND to the falsification set — this is called out in §7 review item 7 so the pre-build reviewer checks it.
