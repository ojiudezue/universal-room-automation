# PLANNING — HVAC-PRESET-FLAP-1: Off-Phase Setpoint + Mechanism Honesty

**Card:** `HVAC-PRESET-FLAP-1` (docs/planning/kanban.data.yaml:622)
**Sibling (shipped):** `ARREST-COMFORT-1` Cycle A (v5.69.0) — owns the S1-S13 preset/temp write gate table and the `_d3_skipped_this_tick` relabel flag. This cycle LAYERS INSIDE that machinery; it does not redesign it.
**Operator direction (2026-08-11):** fix "**2+1**" — Fix 2 (off-phase setpoint) plus the honesty half of Fix 1 (make the duty off-phase legible as an ENERGY action, not a presence failure). NON-GOAL: retune the duty values / window (Fix 3, audit-gated) and NON-GOAL: occupancy-conditional duty.
**Status:** planning-only. No code changes in this cycle.
**Tier (proposed):** **Tier 2-DB** — one adversarial plan review before build dispatch. Not Tier 3: the change is bounded to the D5 forced-away site + the S1 chokepoint path (which already have Tier-3 hardening from v5.69.0). The falsifiable invariant is small-surface. See §7.
**Probe status:** `docs/planning/AUDIT_hvac_duty_cycle_frequency.md` returned 2026-08-10 (Q1: ~8.7 forced-away/day, coast-window bound, 67 % occupied; Q2: not a recent regression). Audit gates ONLY the Fix-3 tuning cycle (NON-GOAL here). This cycle is **mechanism honesty**, and the audit's occupancy split (67 %) is the direct evidence for shipping it.

---

## 1. Falsifiable invariant (up-front)

> **INV-OFFPHASE-HONESTY.** In an occupied zone (`bool(zone.persons)` True, resolved on the same tick), while the duty limiter has forced the off-phase (`zone.runtime_exceeded` True) AND the D3 comfort-delay guard did NOT skip the forced-away this tick (`_d3_skipped_this_tick` False), the following BOTH hold:
> 1. **Setpoint.** The effective cooling ceiling written to the zone's thermostat is `home_target_high + COMFORT_OFFPHASE_OFFSET_F`, where `home_target_high` is `PresetManager.get_seasonal_setpoints("home", …)` cool-leg for the current season. It is NEVER equal to the seasonally-configured `away` cool-leg (typically 80 °F).
> 2. **User-visible surface.** No user-visible URA attribute or emitted preset writes "away" for the duration of the off-phase. The reason ledger row for the write reads `runtime_exceeded_offphase` and carries `duty_cycle_off_phase: True` in `details_json`. A sensor attribute (`duty_cycle_off_phase`) exposes the same bool for dashboarding.
>
> The invariant is inert when: (a) `zone.persons` is empty (real vacancy — off-phase → `away` is honest and unchanged), (b) `_d3_skipped_this_tick` True (comfort-delay owns the tick), (c) house_state is `sleep` (D5 sleep-exempt, unchanged), (d) shed_active True (§3.5 — shed dominates), (e) night-trust suppression fired this tick (:1643-1710 `continue`s before D5).

Falsification observations (any one falsifies):
1. Occupied zone, `runtime_exceeded` True: `climate.<entity>.attributes.target_temp_high` reads `≠ home_target_high + OFFSET` (either the away 80 °F ceiling OR an unclamped write).
2. Occupied zone, `runtime_exceeded` True: `climate.<entity>.attributes.preset_mode` == `"away"` for any tick during the off-phase.
3. `sensor.<zone>_preset` (or the coordinator's zone-preset attribute) reports the zone as away while `zone.persons` non-empty.
4. Shed-active zone held at `home + OFFSET` instead of the tighter shed away-ceiling (regression: shed must dominate).
5. Actual vacancy (`bool(zone.persons)` False) held at `home + OFFSET` (regression: unoccupied zone must still be surrendered to the away ceiling).
6. Off-phase write path emitted via a legacy inline `climate.set_temperature` / `set_preset_mode` bypassing `hvac_setpoint.emit_*` (unroutable through the S-gate machinery).

The plan-review pass (§7) owns re-enumerating every D5 forced-away consumer AND every `set_preset_mode` emit site against INV-OFFPHASE-HONESTY.

---

## 2. Institutional context verified

### 2.1 Prior planning docs / memory bodies consulted
- Card `HVAC-PRESET-FLAP-1` (kanban.data.yaml:622-713) — mechanism proven, THREE retractions read and not re-litigated: `RETRACTION_2_max_runtime_minutes` (not the cap), `RETRACTION_3_two_writers` (one writer, duty cycling as designed), `LEDGER_RETRACTION_2026_08_09` (`details_json` not `details`).
- `docs/planning/PLANNING_arrester_comfort_delay.md` rev-2 — §3.4 D3 coast-precedence guard, §3.7 S1-S13 per-site verdict table, §4.6 knob ladder, §8 single-accessor invariant.
- `docs/planning/AUDIT_hvac_duty_cycle_frequency.md` — Q1 (8.7 forced-away/day, 67 % occupied, coast-bound); Q2 (long-standing, not v5.47→v5.64 regression). Gate satisfied for mechanism-honesty scoping (does NOT gate Fix 3 tuning, which is NON-GOAL).
- Memory: `feedback_no_fabrication` (Ecobee preset-mode adjudication in §3.6), `feedback_suppression_needs_discharge` (off-phase discharge = duty window rolls, backstop = the accumulator itself), `feedback_marginal_benefit_pushback` (§5), `battery_soc_envoy_not_span` (no new SOC read — this cycle does not gate on SOC).
- Design doc: `docs/Coordinator/HVAC.md` — reviewed, no new coordinator responsibility (this cycle refines an existing D5 branch behavior).

### 2.2 Greps run + prior-art disposition

| Proposed | Grep target | Result | Disposition |
|---|---|---|---|
| Off-phase forced-away site | `runtime_exceeded` / `effective_preset = "away"` | Exists — `hvac.py:1575-1604` (D5 branch inside preset-apply loop) | **REUSE** — refactor the `else: effective_preset = "away"` limb (:1604) to route through a new sibling helper `_apply_duty_off_phase(zone, target_preset)` that writes the OFFSET ceiling via `emit_set_temperature` and does NOT set `effective_preset = "away"`. |
| Seasonal home cool-leg | `get_seasonal_setpoints` | Exists — `hvac_preset.py:118` (returns `(cool, heat)` per season/preset) | **REUSE** — helper calls `self._preset_manager.get_seasonal_setpoints("home", now)` for the current season; sums `cool + COMFORT_OFFPHASE_OFFSET_F`. No new baseline row. |
| Setpoint write chokepoint | `emit_set_temperature` | Exists — `hvac_setpoint.py:121` (freeze-floor + deadband + `gate=` param) | **REUSE** — off-phase write MUST route through it. Gate: mirror the S1 `_s1_gate` (`comfort_delay_active(zone_id)` when reason ∈ defer-set). New site tag `S14_duty_off_phase`. |
| Preset write chokepoint | `emit_set_preset_mode` | Exists — `hvac_setpoint.py:180` | **NO NEW USE** — the off-phase branch STOPS emitting a preset-mode change (keeps preset at `target_preset`, typically `home`). Existing S1 site keeps the preset write for the non-off-phase branches. |
| Arrester suppress on setpoint write | `self._override_arrester.suppress(...)` | Exists — `hvac.py:1793` (called before the S1 preset emit) | **REUSE** — the off-phase branch must `suppress(zone.climate_entity, kind="temp")` before its `emit_set_temperature` so the arrester does not self-revert (mirror of the concession-grant pattern in ARREST-COMFORT-1 §2.2 row 2). |
| Reason ladder | `preset_change_reason = "runtime_exceeded"` | Exists — `hvac.py:1759` | **REUSE + EXTEND** — off-phase writes emit a NEW distinct code `runtime_exceeded_offphase` (see §3.3 discriminator rationale). Add `duty_cycle_off_phase: True` to `details_json`. |
| Reason relabel flag | `_d3_skipped_this_tick` | Exists — `hvac.py:1574` | **REUSE** — the off-phase branch is the *else* of the D3 guard; when it fires, `_d3_skipped_this_tick` is False by construction (only set inside the `if _cd_active and …:` arm on :1602). The relabel machinery (:1780-1790) is UNCHANGED. |
| User-visible attribute | `zone.preset_mode`, `sensor.<zone>_preset` | Zone attribute drives the coordinator's zone-preset sensor | **REUSE** — since we no longer emit `set_preset_mode` "away", `zone.preset_mode` remains `home`. New attribute `duty_cycle_off_phase: bool` added to the existing per-zone sensor (see §3.3, D3). |
| Bypass site check — `set_preset_mode` inline | rg `set_preset_mode` in `custom_components/` | Migrated by ARREST-COMFORT-1 rev-2 §3.7 to `emit_set_preset_mode` (3 sites at time of migration) | **VERIFY DURING BUILD** — re-grep before dispatch to confirm no post-v5.69.0 regressions. This cycle does not add an inline site. |
| Ecobee preset-modes discovery | `attr_preset_modes`, `preset_modes` attr | Third-party integration — URA reads whatever the entity exposes; no hard-coded list in URA source | **NO NEW CUSTOM PRESET** — see §3.6 adjudication. This cycle does not attempt to add a new Ecobee preset (`eco`, `comfort`, etc.); it removes the preset-write from the off-phase path entirely. |

**All new symbols namespaced `COMFORT_OFFPHASE_*` / `duty_cycle_off_phase*`** — no collision with `OVERRIDE_*`, `COMFORT_*` (ARREST-COMFORT), or `DUTY_CYCLE_*`.

### 2.3 Code locations surveyed end-to-end
- `hvac.py` :1420-1620 (D5 duty branch + D3 comfort-delay guard); :1712-1856 (reason-ladder derivation, S1 gate call).
- `hvac_setpoint.py` :1-230 (both chokepoints, gate semantics, deferred-write ledger row).
- `hvac_preset.py` :55-120 (season / baseline map, `get_seasonal_setpoints`, `get_preset_for_house_state`).
- `hvac_const.py` :380-420 (duty knobs, ARREST-COMFORT knob namespace pattern to mirror).
- Sensor surface: `sensor.py` (zone-preset sensor) — off-phase attribute add site (resolve exact class during build; see §8 open point 1).

---

## 3. Design

### 3.1 Config-vs-code adjudication (operator's cheapest-candidate question)

The card asked whether the fix could be **CONFIG** (e.g. a dedicated preset in the seasonal baseline map — tighten `away` to `home + 2 °F`, or add a new `eco` preset row). **Verdict: NO, it must be code + one new knob.** Evidence:

1. The seasonal baseline map at `hvac_preset.py:55-68` is keyed `(season, preset)`. The `away` preset row is legitimately consumed by the **real-vacancy** path (`vacant_past_grace`, `stale_occupancy`) via the SAME D5 loop's other branches. Tightening the `away` row globally would collapse actual vacancy conservation (~80 °F → ~home+2) — a large-blast-radius unintended edit falsifying INV #5.
2. Adding a new preset name (e.g. `eco`) and mapping the D5 off-phase to it requires the target thermostat to *support* that preset (Ecobee's `preset_modes` list is device-emitted, and URA does not fabricate). Attempting to set an unsupported preset either raises or silently no-ops depending on integration — a fragile substrate for a safety-adjacent cycling behavior. **No-fabrication rule applies: without reading the actual `climate.<zone>.attributes.preset_modes` for each configured thermostat, we cannot commit to a preset name. Do NOT do that.**
3. The **honest** signal for "duty limiter cycling us" is not a preset at all — it is a setpoint held at `home + small_offset` so the compressor coasts, with a boolean attribute that says so. This is exactly what the invariant demands.

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
1. Compute `cool_baseline, heat_baseline = self._preset_manager.get_seasonal_setpoints(target_preset, now)` (see §3.5 last row for the target_preset generalization).
2. `high = cool_baseline + self.comfort_offphase_offset_f`; `low = heat_baseline` (no unilateral heat drop; `emit_set_temperature`'s deadband invariant will raise `high` if it collides with `low + MIN_DEADBAND`).
3. `self._override_arrester.suppress(zone.climate_entity, kind="temp")` (mirror ARREST-COMFORT §2.2 row 2 pattern).
4. Build `_s14_gate` — a zero-arg closure returning `comfort_delay_active(zone_id)` for consistency with S1. Per-reason defer-set: `runtime_exceeded_offphase` IS in the defer-set (aligns with S1's treatment of `runtime_exceeded`). Rationale: if the operator has an active comfort-delay grant on the zone, we still owe the human ownership of the tick; deferring the off-phase write means the grant's post-suppress temperature stands.
5. Call `emit_set_temperature(hass, zone.climate_entity, target_temp_low=low, target_temp_high=high, freeze_active=self.freeze_active, gate=_s14_gate, site="S14_duty_off_phase", zone_id=zone_id, reason=reason)`.
6. Return the callee's bool.

**Call site:** replace `hvac.py:1604` — inside the D5 branch, on the `else:` limb where `effective_preset = "away"` used to be written. New shape:
```
else:
    if zone_vacant_past_grace:
        effective_preset = "away"          # real vacancy still wins (INV #5)
    elif not self.hvac_offphase_honesty_enabled:
        effective_preset = "away"          # kill-switch: pre-cycle behavior
    else:
        written = await self._apply_duty_off_phase(zone, target_preset)
        if not written:
            continue                         # deferred by comfort-delay gate
        # DO NOT set effective_preset = "away"; leave it as target_preset so
        # the S1 preset path is a no-op (should_change_preset returns False).
        zone_runtime_offphase_this_tick = True
```

Semantics guarantee:
- `effective_preset` remains `target_preset` (typically `home`), so the S1 preset-emit path is skipped by `should_change_preset` (:1717). No two-writer race. INV #2 held by construction.
- The `zone_vacant_past_grace` branch on the same loop (:1463) is UNAFFECTED — real vacancy still routes to `effective_preset = "away"` and the S1 preset write. INV #5 held.
- Kill-switch OFF byte-identically restores pre-cycle behavior.

### 3.3 D2 — Ledger + D3 attribute honesty (Fix 1 half)

**Ledger row.** Add a **synthetic `preset_change_suppressed` row** at the D5 off-phase site (mirror of the night-trust suppression row at `hvac.py:1687-1709`), episode-gated on a new per-(zone, house_state) cache `_offphase_logged` so a standing off-phase emits ONE row per episode rather than one per tick:
- `action="preset_change_suppressed"`
- `reason="runtime_exceeded_offphase"` — **distinct code** (not the pre-existing `runtime_exceeded` code used by the historical `preset_change` rows). Rationale: post-deploy DB queries need to prove the migration cleanly; keeping the same code and only relying on `details_json.duty_cycle_off_phase` forces every analysis query to JSON-parse. One extra vocabulary word saves N future queries.
- `details_json.duty_cycle_off_phase = True`
- `details_json.would_have_written_preset = "away"` (evidence for the reviewer, one line)
- `details_json.setpoint_high_written = high`
- `details_json.persons` echoed for episode correlation with the night-trust rows (LIVE at tick time; verified by test).
- S14 chokepoint's own `emit_set_temperature` still emits its usual set-temperature ledger row (existing behavior — verify at build).

**Sensor attribute.** Add `duty_cycle_off_phase: bool` to the existing per-zone preset sensor's `extra_state_attributes` (surface: resolve exact class during build via `rg 'zone.*preset' sensor.py`; see §8 open point 1). Value: `bool(zone.runtime_exceeded and bool(zone.persons) and not _d3_skipped_this_tick)`. Dashboards / templates can drive a chip off this without reading the ledger.

**Rule of thumb applied:** distinct reason CODE so the ledger query is unambiguous; the operator-facing chip is a plain-English boolean.

### 3.4 D4 — Restart / boot behavior

- Off-phase state is NOT persisted across restart. On boot, `zone.runtime_exceeded` is re-derived from live compressor accumulation as it is today; the first off-phase write after boot naturally re-enters `_apply_duty_off_phase` on the tick the accumulator crosses the cap. No RestoreEntity change.
- `_offphase_logged` cache resets on coord init (matches the `_night_trust_logged` reset pattern at `hvac.py:1659`); one boot-transient extra ledger row per zone per episode is acceptable (documented in the README validation section as expected).
- Kill-switch state IS persisted (Switch-entity persistence machinery). If `hvac_offphase_honesty_enabled` is False at boot, coordinator logs a WARN so the operator sees the disabled state on every restart.
- Kill-switch flipped OFF mid-episode: the next D5 tick takes the pre-cycle limb (`effective_preset = "away"`); the S1 preset write emits and the `_offphase_logged` cache is stale but harmless.

### 3.5 D5 — Precedence table (spec'd, not inferred)

| Condition | Behavior | Cite |
|---|---|---|
| `sleep` house_state | D5 branch skipped entirely (unchanged) | hvac.py:1575 pre-existing gate |
| `shed_active` True | Off-phase branch STILL fires but the S14 write must NOT relax any tighter shed-emitted ceiling. **Concrete predicate**: `high = min(cool_baseline + OFFSET, current_shed_target_high)` when `shed_active` and a shed target is present on the coordinator; else `high = cool_baseline + OFFSET` unchanged. Reviewer to sharpen the shed-target accessor at build (§8 open point 3). | rev-2 shed dominance principle |
| `_d3_skipped_this_tick` True | D3 comfort-delay owns the tick; D5 off-phase branch does NOT fire this tick (the `if _cd_active and …:` arm returns without running the else). Unchanged from ARREST-COMFORT §3.4. | hvac.py:1588-1602 |
| `zone_vacant_past_grace` True + off-phase concurrent | The `zone_vacant_past_grace` branch runs FIRST (:1463) and sets `effective_preset = "away"`. In the D5 else-limb, an explicit `if zone_vacant_past_grace: effective_preset = "away"` short-circuit preserves the away preset write. Falsification #5 covers this. | new — this cycle |
| `freeze_active` True | `emit_set_temperature` already applies the freeze floor + deadband; no override needed. `low` is computed from the season's home-heat baseline so no unilateral drop below the current heat setpoint. | hvac_setpoint.py:58-63 |
| Night-trust suppression (home_night / waking / sleep flanks) | The night-trust branch at :1643-1710 `continue`s the loop BEFORE the D5 branch is reached — so off-phase during night-trust never emits either the S1 preset write OR the new S14 setpoint write. Reviewer to confirm this is the desired behavior (INV inertness clause (e)) and add a test that asserts NO S14 emit during night-trust with `runtime_exceeded=True`. | hvac.py:1643-1710 |
| Guest / vacation preset (target_preset ≠ home) | Recompute `high` from `get_seasonal_setpoints(target_preset, now)` cool-leg + OFFSET, not hard-coded `home`. Helper signature takes `target_preset`. Vacation off-phase becomes vacation-high + OFFSET — same honesty principle. Guard: if `get_seasonal_setpoints` returns None for the (season, target_preset) pair (unknown preset), fall back to pre-cycle behavior (`effective_preset = "away"`) and log a one-shot WARN. | hvac_preset.py:55-68 |

### 3.6 Ecobee preset-mode adjudication (no-fabrication check)

The card asked "a distinct preset name if the thermostat supports it, or keep preset but expose a `duty_cycle_off_phase: true` attr". Adjudication:

- URA does not have a hard-coded list of Ecobee preset names in source. `emit_set_preset_mode` calls `climate.set_preset_mode` with whatever string the caller passes; validation is delegated to the target integration.
- Neither the assistant nor the reviewers should CLAIM a specific preset (e.g. `"eco"`, `"comfort"`) is Ecobee-supported without reading `climate.<entity>.attributes.preset_modes` for each configured thermostat. That live read is an operator or builder task, not a planning-time claim.
- **Chosen path (attr-based honesty).** Keep the preset at `target_preset` (typically `home`) and expose the boolean attribute + distinct ledger reason. Zero risk of an unsupported-preset service call, zero fabrication about integration behavior. This is the cheaper honesty half and it fully satisfies INV item 2.
- If a future cycle wants a per-zone Ecobee "eco" or custom-comfort preset, that becomes a config-flow decision informed by a live `preset_modes` probe per zone — parked as a Cycle-B follow-up with evidence trigger: "operator wants the thermostat's own LCD to show something other than `home` during off-phase".

### 3.7 Non-goals (explicit, per plan-review discipline)

- **Retune duty values / window.** `DUTY_CYCLE_COAST`, `DUTY_CYCLE_SHED`, `DUTY_CYCLE_WINDOW_SECONDS` unchanged. Card's Fix 3, audit-gated (audit exists but did not conclude a tuning target; separate cycle).
- **Occupancy-conditional duty.** No change to WHEN the limiter trips. Same 75 %/20-min cap regardless of occupancy.
- **New preset name (`eco`, `comfort`, custom).** §3.6.
- **Multi-thermostat-per-zone.** Same probe-derived simplification as ARREST-COMFORT-1 (measured zero multi-thermostat zones); one climate entity per zone.
- **Battery-SOC gating of off-phase.** This cycle does not read SOC. The off-phase itself is the duty limiter working as designed; battery-aware relaxation is a SEPARATE conversation (parent card option (c), parked).
- **Change to the S1 preset-write path.** Untouched. This cycle only adds S14 alongside S1 for the runtime_exceeded off-phase.

---

## 4. Knob ladder (per "Numbers Get Knobs")

| Constant | Rung | Default | Range | Kill-switch semantics |
|---|---|---|---|---|
| `COMFORT_OFFPHASE_OFFSET_F` | **RUNG 3 — Number entity, persisted** | `2.0` °F | `[0.0, 6.0]` step 0.5 | `0.0` = no offset above home ceiling → off-phase writes the home ceiling itself → cooling may STILL trigger, reducing off-phase effectiveness; useful for diagnosis but NOT the feature-disable knob. |
| `CONF_COMFORT_OFFPHASE_OFFSET_F` | (companion) | — | — | Config key for options-flow persistence. |
| `DEFAULT_COMFORT_OFFPHASE_OFFSET_F` | (companion) | `2.0` | — | Seeded into the Number entity on first boot. |
| `MIN/MAX_COMFORT_OFFPHASE_OFFSET_F` | (companion) | `0.0` / `6.0` | — | Number entity bounds. |
| `hvac_offphase_honesty_enabled` | **RUNG 3 — Switch entity, persisted** | `True` | on/off | **Feature kill-switch.** `False` → D5 else-branch reverts to writing `effective_preset = "away"` (pre-cycle behavior byte-identical). Boot-WARN log emitted when False so operator sees it on every restart. |

Why RUNG 3 for both: the offset is legitimately tuneable by observation ("kids still uncomfortable, bump to 3 °F"); the kill-switch is the correct rung for a *behavioral-migration* toggle so a regression in the wild is one dashboard tap away from mitigated. RUNG 1 (module constant only) would require a code deploy to back out — unacceptable for a change in the D5 cycling hot-path.

---

## 5. Marginal-benefit decomposition

Simplest version = **just the honesty half** (D3 sensor attribute + distinct ledger reason, KEEP the `preset=away` write). Cost ~30 LoC. Benefit: dashboards can discriminate; operator no longer misreads as presence failure.

Fix-2 addition (off-phase setpoint) = ~60 LoC + one new knob + one new S-gate site. Marginal benefit: kids at 76-78 °F during off-phase instead of 80 °F on an 80 °F evening. **This is the entire operator-cited comfort cost** from the parent card ("upstairs held at 79-80F with two kids in it after a 24h absence on a 96F day"). Marginal risk: one new setpoint-write site, but it inherits the S1 chokepoint machinery byte-for-byte and adds no new ingredient (no synthetic time, no cross-coordinator state, no rare-fire path — it fires as often as `runtime_exceeded` does, which the audit measured at 8.7×/day).

**Verdict:** ship 2+1 together. The marginal comfort benefit clearly outweighs the marginal wiring risk, and shipping honesty alone would repeatedly re-raise the temperature complaint without addressing it. This is exactly the operator's stated split.

**Parked (not this cycle):** battery-SOC-conditioned off-phase relaxation (parent card option (c)); per-thermostat custom preset (§3.6 evidence trigger); Fix-3 duty retuning (audit-gated, no target yet).

---

## 6. Deliverables + acceptance criteria

### D1: `_apply_duty_off_phase` helper + D5 call-site rewire
Refactor `hvac.py:1575-1620` D5 branch to invoke the new helper on the else-limb; helper routes through `emit_set_temperature` with an S14 gate.

**Acceptance criteria**
- **Verify:** unit test with occupied zone + `runtime_exceeded=True` + `_d3_skipped_this_tick=False` + kill-switch ON observes ONE `hass.services.async_call("climate", "set_temperature", …)` with `target_temp_high == home_cool + 2.0` and ZERO `set_preset_mode` calls.
- **Verify:** unit test with `zone_vacant_past_grace=True` + `runtime_exceeded=True` observes the S1 `set_preset_mode("away")` call and ZERO S14 setpoint writes (real-vacancy dominance, INV #5).
- **Verify:** unit test with `_d3_skipped_this_tick=True` observes ZERO S14 writes (comfort-delay owns the tick).
- **Verify:** unit test with `shed_active=True` — emitted `target_temp_high` <= the shed baseline for the season (shed dominance predicate).
- **Verify:** unit test with `freeze_active=True` — `emit_set_temperature` deadband invariant holds; no low-leg drop below current heat.
- **Verify:** unit test with `target_preset="vacation"` — helper reads vacation cool baseline + OFFSET (not hardcoded home).
- **Verify:** unit test with night-trust suppression active — ZERO S14 writes.
- **Test:** `TestDutyOffPhaseSetpoint::test_writes_home_plus_offset`, `test_yields_to_vacant_past_grace`, `test_yields_to_comfort_delay`, `test_shed_dominates`, `test_freeze_deadband_honored`, `test_vacation_target_preset`, `test_night_trust_short_circuits`.
- **Sensor:** during a duty off-phase, `climate.<zone>.attributes.target_temp_high` reads `home_cool + 2.0`; `climate.<zone>.attributes.preset_mode` reads `home` (or the current house-state preset), NEVER `away`.
- **Live:** during the 21:00-01:00Z coast window, on a zone that trips `runtime_exceeded` with occupants present, observe `climate.thermostat_upstairs.attributes.target_temp_high` step to `home_cool + 2.0`, NOT to 80, and remain there for the off-phase; `preset_mode` unchanged.

### D2: Ledger reason + episode-gated suppressed-preset row
Add the `preset_change_suppressed` row with `reason=runtime_exceeded_offphase`, `details_json.duty_cycle_off_phase=True`, `details_json.setpoint_high_written`, episode-gated on `_offphase_logged`.

**Acceptance criteria**
- **Verify:** a 30-tick simulated off-phase episode produces exactly ONE `preset_change_suppressed` row (not 30).
- **Verify:** the row carries `reason="runtime_exceeded_offphase"` and `details_json.duty_cycle_off_phase is True`.
- **Verify:** the row's `persons` list matches the tick's live persons (not a config snapshot).
- **Test:** `TestOffphaseLedger::test_one_row_per_episode`, `test_reason_string`, `test_persons_live_not_static`.
- **Live:** query `ura_activity_log` after a coast-window off-phase; expect ≥1 row per (zone, episode) with the new reason; no historical `preset_change` rows with `reason=runtime_exceeded` for the same episode window (proves migration is clean and no double-emit).

### D3: `duty_cycle_off_phase` sensor attribute
Add boolean attribute to the existing per-zone preset sensor.

**Acceptance criteria**
- **Verify:** attribute is True iff `zone.runtime_exceeded and bool(zone.persons) and not _d3_skipped_this_tick`.
- **Verify:** attribute is False when the zone is genuinely vacant (real away).
- **Test:** `TestDutyOffPhaseAttr::test_true_during_occupied_offphase`, `test_false_during_true_vacancy`.
- **Live:** the resolved zone-preset sensor entity_id shows `duty_cycle_off_phase: true` in attributes during an observed off-phase episode; the friendly value/state remains `home`.

### D4: Knob wiring (`COMFORT_OFFPHASE_OFFSET_F` Number + `hvac_offphase_honesty_enabled` Switch)
Number + Switch entities persisted via the existing entity-persistence machinery (mirror `ComfortGraceMinutesNumber` from ARREST-COMFORT-1).

**Acceptance criteria**
- **Verify:** setting the Number to 3.0 updates `HVACCoordinator.comfort_offphase_offset_f` without a restart; the next off-phase write uses 3.0.
- **Verify:** flipping the Switch OFF causes the next off-phase to write `effective_preset = "away"` (pre-cycle path). Restart with the Switch OFF emits a boot-WARN log.
- **Test:** `TestOffphaseKnobs::test_offset_live_read`, `test_kill_switch_reverts_to_preset_write`, `test_kill_switch_boot_warn`.
- **Live:** operator tap of the Number tile changes the ceiling on the next off-phase (observable via the target_temp_high step).

### D5: README v-next validation table
Post-deploy Live rows for D1/D2/D3/D4 (per "Record Live Validation Back Into the README" mandate) — one row per acceptance criterion above, marked PASS/FAIL with observed evidence.

---

## 7. Tier proposal + review protocol

**Tier 2-DB** with the plan-review pre-gate (per operator's 2026-08-11 Plan Review policy).

Rationale for NOT Tier 3:
- The change lives inside a hot-path (D5) but ADDS a code path parallel to the existing S1 chokepoint, which already has Tier-3 hardening from v5.69.0 (per-site mutation authority, single-accessor SOC, gate-composition contract). The new S14 is a mirror; the Tier-3 machinery it inherits does not need re-litigation.
- The falsifiable invariant is small-surface (one added write site, one removed write site, one attribute, one ledger row). Compare to ARREST-COMFORT-1 Cycle A (S1-S13 grew a whole gate table).
- No new cross-coordinator surface (no energy strategy change, no presence, no compliance).

**Adversarial plan review MUST re-verify (with `git grep`, not trust):**
1. Every current call site of `emit_set_preset_mode` (rev-2 §3.7 catalog): confirm none is a legacy inline `set_preset_mode` post-v5.69.0.
2. Every current site setting `effective_preset = "away"` inside `hvac.py`: confirm the exhaustive list matches §3.5 precedence table (D5 else-limb, D6 stale-occupancy, `zone_vacant_past_grace`) and no fourth site exists that this cycle would silently break.
3. That `_d3_skipped_this_tick`'s exit-invariant (only True inside the D3 arm, False in the else-limb) actually holds — the plan asserts this by construction; the reviewer must confirm the source matches at the shipped commit.
4. That the shed-dominance predicate (§3.5 row 2) is sharpened concretely enough for the builder to write a passing test — the plan proposes `min(cool_baseline + OFFSET, current_shed_target_high)` conditional on a shed accessor; reviewer to confirm the accessor exists on the coordinator or flag it as a build-input.
5. That the vacation / guest target_preset generalization (§3.5 last row) is complete — every house_state that maps to a non-`home` non-`away` preset via `HOUSE_STATE_PRESET_MAP` is handled, including the None-return fallback.
6. Ecobee preset-mode adjudication (§3.6): confirm no site in the plan silently assumes an integration-specific string.

If ANY of the above surfaces a gap, the plan is fixed BEFORE build dispatch (per the process rule that made this policy).

**Build-phase reviews** follow the standard Tier 2-DB three framing-disjoint pattern (correctness + edge cases / cross-coordinator + precedence / test-authority via per-site source mutation). Live validation Review D confirms observed values via `climate.<entity>.attributes` reads and a `ura_activity_log` query per D2.

---

## 8. Open points (for adversarial plan review to close)

1. **Sensor entity resolution.** D3's "existing per-zone preset sensor" needs to be resolved to a concrete class in `sensor.py` during build; if no such sensor exposes zone-preset today (i.e. only the coordinator attribute exists), the reviewer must decide: add a new sensor, OR expose the attribute on an existing zone-scoped sensor. Not a blocker to plan approval; is a builder-input point.
2. **Ledger discriminator retention.** The plan proposes `reason="runtime_exceeded_offphase"` as a distinct code for cleanliness. Alternative: keep `reason="runtime_exceeded"` and rely on `details_json.duty_cycle_off_phase` — one fewer vocabulary word, one more JSON query in every downstream analysis. Reviewer to weigh; plan defaults to the distinct code.
3. **Shed-dominance accessor.** §3.5 row 2 references `current_shed_target_high` — a coordinator accessor the plan proposes but has not verified exists in this session. Reviewer to grep for the shed target attribute and either confirm the accessor OR sharpen the predicate to whatever shed layer actually emits (e.g. "trust that shed's own `emit_set_temperature` ran first on the same tick and don't overwrite it" — requires ordering guarantee that may or may not hold).
4. **Off-phase during night-trust.** §3.5 last-but-one row asserts night-trust `continue`s before D5 — visually confirmed at :1710. Reviewer to verify no other early-return between night-trust suppression and the D5 branch could invalidate this ordering claim under any house_state configuration.

---

## 9. Change surface summary

**Files touched (predicted):**
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` (D5 else-limb rewire + new `_apply_duty_off_phase` helper + episode-gated ledger emit + `_offphase_logged` cache; ~80 LoC)
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py` (new `COMFORT_OFFPHASE_*` constants block; ~15 LoC)
- `custom_components/universal_room_automation/number.py` (new `ComfortOffphaseOffsetNumber` mirror of `ComfortGraceMinutesNumber`; ~40 LoC)
- `custom_components/universal_room_automation/switch.py` (new `HvacOffphaseHonestyEnabledSwitch`; ~30 LoC)
- `custom_components/universal_room_automation/sensor.py` (add `duty_cycle_off_phase` attribute to existing zone-preset sensor; ~10 LoC)
- `quality/tests/test_hvac_offphase.py` (new; ~250 LoC covering D1-D4 criteria)
- `docs/readmes/README_v<next>.md` (pre-deploy prospective + post-deploy validated)

**Backward compatibility.** Kill-switch OFF byte-identically restores pre-cycle behavior. Config-entry migration: none (both new knobs seeded at default on first boot, same pattern as ARREST-COMFORT-1 Cycle A).

---

## 10. Report (per orchestrator brief)

**Invariant.** INV-OFFPHASE-HONESTY (§1) — occupied + runtime_exceeded + not-D3-skipped ⇒ ceiling == home_target_high + OFFSET AND no user-visible surface says "away".

**Deliverables.** D1 helper + call-site rewire; D2 ledger row + distinct reason; D3 sensor attribute; D4 offset knob + kill-switch; D5 README validation write-back.

**Config-vs-code adjudication (§3.1 verdict).** CODE. A pure config edit to the seasonal baseline map corrupts the real-vacancy path (INV #5). A new preset name violates No-Fabrication about Ecobee's `preset_modes` list. The scoped fix is: remove the `preset=away` write from the off-phase branch, replace with a setpoint write at `home + OFFSET`, expose the mechanism as an attribute + distinct ledger reason. One new operator knob (offset, RUNG 3) + one kill-switch (RUNG 3).

**Open points (§8).** Sensor entity resolution, ledger discriminator choice, shed-dominance accessor sharpening, night-trust ordering re-verification — all closable in adversarial plan review before build dispatch.
