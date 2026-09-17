# AUDIT — Thermostat write/read paths, funnel-vs-bypass inventory

Date: 2026-09-16
Trigger: HIGH-2 (DPM `_async_apply_preset_overrides` bypasses effective_preset) + HVAC-THERMOSTAT-ABSTRACTION-1 finding (7 raw `climate.set_hvac_mode` calls) + zone_1 manual<->away oscillation with an unidentified re-manual writer. Operator hypothesis: nudges + borrow + DPM all bypass the URA "preset write" funnel; a `ZoneThermostat` handle should govern every push and pull.

READ-ONLY: no code changed. Every path is cited at file:line.

## 0. Funnels under test

`custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py`

- `emit_set_temperature` (hvac_setpoint.py:182) — freeze-floor + deadband guard, comfort-delay gate, single `services.async_call("climate","set_temperature", ...)` at :235.
- `emit_set_preset_mode` (hvac_setpoint.py:241) — comfort-delay gate; RESUME-then-PIN escape hatch for Bryant "manual" anonymous holds (:308-366). Two raw `services.async_call` sites at :311 (RESUME) and :327 (PIN), retry at :348, all INSIDE the funnel.

There is NO `emit_set_hvac_mode` today. Every `climate.set_hvac_mode` call in the integration is by definition a raw write.

## 1. PUSH inventory (every URA-originated climate service call)

### 1a. Through the funnel (21 sites)

| # | File:line | Verb | Purpose | Site tag |
|---|---|---|---|---|
| 1 | hvac.py:2275 | preset_mode | House-state preset apply | S1 |
| 2 | hvac.py:2568 | set_temperature | DPM preset-override apply (loop, per zone) | S10_dpm_apply |
| 3 | hvac_predict.py:962 | set_temperature | Pre-cool / pre-heat predictor emit | S11 |
| 4 | hvac_predict.py:1023 | preset_mode | Predictor preset write | (predictor) |
| 5 | hvac_predict.py:1143 | set_temperature | Predictor S12 | S12 |
| 6 | hvac_predict.py:1427 | set_temperature | Predictor S13 | S13 |
| 7 | hvac_predict.py:1490 | set_temperature | Predictor (banking / mid-bank finish) | (predict) |
| 8 | hvac_predict.py:1539 | preset_mode | Predictor preset restore | (predict) |
| 9 | hvac_override.py:3321 | set_temperature | Override / arrester setpoint path | S3 |
| 10 | hvac_override.py:3475 | preset_mode | Severe-override REVERT (post-compromise) — reads `_cmp_token.pre_preset` | S4_revert |
| 11 | hvac_override.py:4041 | preset_mode | Override preset write | (S?) |
| 12 | hvac_override.py:4351 | set_temperature | Soft-nudge START (+°F bump) | S5_nudge_start |
| 13 | hvac_override.py:4523 | set_temperature | Soft-nudge RESTORE (setpoint back) | S6 |
| 14 | hvac_override.py:4560 | preset_mode | Soft-nudge RESTORE (preset back, snapshot-restore) | S7 |
| 15 | hvac_override.py:5735 | set_temperature | (compromise / re-emit) | (S?) |
| 16 | hvac_override.py:5761 | preset_mode | (compromise / re-emit) | (S?) |
| 17 | hvac_override.py:6141 | set_temperature | (compromise apply) | (S?) |
| 18 | hvac_override.py:6165 | preset_mode | (compromise apply) | (S?) |
| 19 | hvac_egress.py:667 | preset_mode | Egress excursion emit | (egress) |
| 20 | hvac_egress.py:795 | preset_mode | Egress RESUME preset restore | egress_resume |
| 21 | hvac_excursion.py:1131 | preset_mode | Startup-audit NUDGE preset restore (drop-row path) | startup_audit_nudge_preset_restore |

All 21 pass through `emit_set_temperature` / `emit_set_preset_mode` and inherit the freeze-floor guard, deadband invariant, comfort-delay gate, and the RESUME-then-PIN escape (preset path only).

### 1b. Raw / bypass (7 sites — ALL `set_hvac_mode`)

| # | File:line | Verb | Purpose | Notes |
|---|---|---|---|---|
| B1 | hvac.py:1731 | set_hvac_mode | Heat_cool enforcer (drift revert) | Wrapped in `suppress()`; blocking=True |
| B2 | hvac_egress.py:682 | set_hvac_mode "off" | Egress PAUSE — turn zone off | Wrapped in `auto_release_on_incomplete` CM (excursion bookkeeping) but the wire write itself is raw |
| B3 | hvac_egress.py:778 | set_hvac_mode saved_mode | Egress RESUME — restore mode before preset | Preset half at :795 IS funnelled; mode half is not |
| B4 | hvac_override.py:3447 | set_hvac_mode heat_cool | Override revert helper — heat_cool re-assert (pre-preset revert) | Sibling of B1; different call site |
| B5 | hvac_override.py:3816 | set_hvac_mode "off" | AC RESET off | blocking=True |
| B6 | hvac_override.py:3934 | set_hvac_mode target_mode | AC RESET restore | blocking=True |
| B7 | hvac_override.py:3969 | set_hvac_mode target_mode | AC RESET restore retry | attempt<=2 |

**Bypass count matches HVAC-THERMOSTAT-ABSTRACTION-1's 7-site finding exactly. All are `set_hvac_mode`. There is NO chokepoint for hvac_mode today.**

Additionally: `coordinator.py:1130` executes arbitrary AI-rule actions through `services.async_call(domain, service, data)`. Direct `climate.{set_temperature,set_preset_mode,set_hvac_mode}` are refused at :1107-1123 (D-HIGH-2 fix-up, 2026-08-10), but chained routes via `automation.trigger` / `scene.turn_on` / `script.turn_on` / `homeassistant.turn_on` REMAIN OPEN — the comment at :1096-1106 documents this as a known accepted gap awaiting the "route-through-chokepoints" upgrade.

### 1c. Chokepoint-internal raw calls (NOT bypasses)

Inside the funnel; each is the funnel's OWN service call, not a caller escaping it:

- hvac_setpoint.py:235 (`emit_set_temperature`'s call)
- hvac_setpoint.py:311 (RESUME preset clear)
- hvac_setpoint.py:327 (PIN preset)
- hvac_setpoint.py:348 (PIN retry)

## 2. PULL inventory (thermostat state reads)

There is **no ZoneThermostat read helper**. State reads are scattered `hass.states.get(<climate_entity>)` calls followed by ad-hoc `.attributes.get(...)` for:

- `preset_mode` — read at hvac_setpoint.py:174 (`_needs_resume_first`), hvac_override.py:3800, hvac_override.py:4287-4302 (nudge pre-preset snapshot), hvac_excursion.py bookkeeping paths.
- `hold_activity` — read only at hvac_setpoint.py:174 (`_needs_resume_first`). This is the only site that reads it; the pin fix is gated on it.
- `preset_modes` (capability list) — read at hvac_setpoint.py:171 (capability check for RESUME support).
- `state` (hvac_mode) — read via `zone.hvac_mode` on the `ZoneState` produced by `_zone_manager` (populated from `hass.states` inside `zone_manager`) and, ad-hoc, at hvac_override.py:3925 (`pre_state.state`), hvac_override.py:3955 (`state.state` verify), etc.
- `target_temp_low` / `target_temp_high` — read via `zone.target_temp_high` (ZoneState) at every emit site.

There is no centralized "read the truth about zone X" primitive. Callers reach for `hass.states.get()` or `zone.<attr>` interchangeably; the `hold_activity` read exists in exactly one place.

## 3. Operator claims — CONFIRM / REFUTE

### (a) "Nudges don't use the funnel"
**REFUTED.** Every nudge write goes through the funnel:

- Nudge START — `emit_set_temperature` at hvac_override.py:4351 (site S5_nudge_start), gated by comfort_delay, wrapped in excursion CM.
- Nudge RESTORE (setpoint) — `emit_set_temperature` at hvac_override.py:4523 (site S6), ALLOW path.
- Nudge RESTORE (preset, snapshot-restore) — `emit_set_preset_mode` at hvac_override.py:4560 (site S7), blocking=True.
- Startup-audit NUDGE preset restore — `emit_set_preset_mode` at hvac_excursion.py:1131.

The write side is fully funnelled. The manual-lockout side effect exists at Bryant/cloud, not at a URA bypass.

### (b) "Borrow doesn't use the funnel" / "maybe borrow should use it"
**REFUTED-BUT-INTERESTING.** The "borrow" primitive (`begin_excursion` / `return_excursion` in `hvac_excursion.py`) is BOOKKEEPING ONLY — it opens/closes a governed-excursion row, drives NM latches, and provides `auto_release_on_incomplete`. It emits ZERO climate service calls; the ACTUAL wire writes are done by the caller (nudge / compromise / egress / preheat), which THEN wraps the write in a borrow. The prior-art comment at hvac_setpoint.py:293-297 already records this: "NONE of the 11 setpoint-writing functions reference `borrow` and ... `return_excursion` emits no writes at all".

So "should borrow use the funnel?" is the wrong shape. The right question is the operator's second half: should the funnel and the borrow be composed into ONE governed-write API (a `ZoneThermostat.write(...)` that opens the excursion, applies guards, emits the service call, and closes/keeps the excursion in one shot)? That is the design HVAC-THERMOSTAT-ABSTRACTION-1 exists to explore.

### (c) "`_async_apply_preset_overrides` (hvac.py:2479, DPM) bypasses effective_preset"
**PARTIALLY CONFIRMED — the bypass is SEMANTIC, not a chokepoint bypass.**

The wire write at hvac.py:2568 IS funnelled — it calls `emit_set_temperature` with the S10_dpm_apply site + comfort-delay gate. It is NOT a raw `services.async_call`.

What HIGH-2 flags is different: DPM computes the emitted `(low, high)` by taking a `baseline` from `_preset_manager.get_seasonal_setpoints(target_preset)` and then overlaying `ec._dynamic_preset_overrides` via `OverrideEngine.resolve_range()`. It writes SETPOINTS ONLY. It does not write `set_preset_mode`, and it does not consult whatever `effective_preset` a caller-side helper would compute; it re-runs its own preset-resolution (`get_preset_for_house_state`) at line 2479 against `self._house_state`. Any code path that has already narrowed the preset to a different `effective_preset` (post-egress, post-arrester, override-driven) gets its intent silently overwritten at the setpoint layer while `preset_mode` on the thermostat stays whatever it was.

That is a caller-composition defect (DPM has its own opinion about preset), NOT a funnel-bypass defect. The funnel cannot fix it — the funnel is verb-scoped (`set_temperature` / `set_preset_mode`), not intent-scoped (`write_effective_preset`).

## 4. Funnel-vs-bypass summary table

| Verb | Funnel sites | Bypass sites | Chokepoint exists? |
|---|---:|---:|---|
| `set_preset_mode` | 10 | 0 | YES (`emit_set_preset_mode`) |
| `set_temperature` | 11 | 0 | YES (`emit_set_temperature`) |
| `set_hvac_mode` | 0 | 7 | **NO** |
| **Totals** | **21** | **7** | 2 of 3 verbs funnelled |

Bypass rate: 7 / 28 = 25 % of URA-originated climate writes bypass a chokepoint. **All 25 % is one verb.**

## 5. Abstraction sizing (`ZoneThermostat`)

If a `ZoneThermostat(zone_id)` handle owned every push+pull, migration count is bounded by:

- Push: 28 sites (21 funnel + 7 bypass). All 21 funnel sites already flow through 2 helpers — trivially wrappable.
- Pull: ~6 distinct attributes read from ~8-10 call sites. `hold_activity` is a single-caller today; `preset_mode` / `state` / target_temps are the volume.

Load-bearing bypasses (must-govern for the abstraction to be complete):

1. `set_hvac_mode` verb (7 sites, especially egress PAUSE off + AC RESET off/restore) — currently unguarded by comfort-delay, freeze-floor is n/a, but a `_supports_heat_cool` capability check is duplicated inline at hvac.py:1726, hvac_override.py:3444, and via helper elsewhere.
2. DPM apply's implicit preset opinion (hvac.py:2479-2483) — a `ZoneThermostat.apply_effective_preset(preset, overrides)` would eliminate the "which preset does this caller think we're in" ambiguity.
3. Nudge / restore preset side-effect (Bryant flips preset -> "manual" on any set_temperature) — currently handled by snapshot-restore at S7. The abstraction could bake the snapshot+restore into a single `nudge()` primitive instead of requiring every caller to remember it.

## 6. Re-sequencing verdict

**Recommendation: SPLIT the work; move Phase 1 of HVAC-THERMOSTAT-ABSTRACTION-1 EARLIER (ahead of step-4-B), keep HIGH-2 as a separate step-4-B point-gate.**

- Phase 1 (advance NOW, small): add `emit_set_hvac_mode` as a peer funnel entry and migrate the 7 raw sites. This is a mechanical, easily-mutation-verified change (Tier 2 protocol), it closes the ONLY verb-scoped gap, and it retires the "3 out of 3 verbs are governed" surface so any future audit can assert it in one grep. Basis: bypass count = 7 / 7 is the same verb; all sites already have `suppress()` handshakes; freeze-floor doesn't apply to mode; comfort-delay probably shouldn't gate egress/AC-reset (safety > comfort), so the funnel would accept a `gate=None` for those sites explicitly — an intentional, per-site decision, not a silent bypass. This is a natural extension, not a rebuild.
- HIGH-2 stays in step-4-B as a point-gate on DPM's preset resolution: either (a) make DPM consult a caller-agnostic `effective_preset` primitive, or (b) have DPM emit a `set_preset_mode` alongside its `set_temperature` when the resolved preset differs from the thermostat's current preset. The funnel cannot express this; it's caller-side intent composition, not wire guarding. Folding it into HVAC-THERMOSTAT-ABSTRACTION-1 Phase 1 would balloon the abstraction from "3 verbs, one chokepoint each" to "verbs + intent composition" — the Tier-3 shape the marginal-benefit rule tells us to avoid on a first pass.
- Phase 2 of HVAC-THERMOSTAT-ABSTRACTION-1 (a full `ZoneThermostat.write_effective_preset(...)` that composes preset + setpoints + borrow) is the correct home for HIGH-2 IF Phase 1 lands cleanly and the DPM point-gate proves insufficient. Park it with the "if the point-gate leaks again, escalate" trigger.

## 7. Dependency: zone_1 manual<->away oscillation producer (HVAC-ZONE1-MANUAL-OSCILLATION-1)

The audit cannot close on whether the abstraction WOULD govern the re-manual writer without knowing who the writer is. Two possibilities:

- **URA writer** — it is already one of the 21 funnelled sites (most likely S4_revert at hvac_override.py:3475 or S1 at hvac.py:2275 or S10_dpm_apply at hvac.py:2568). In that case the abstraction is orthogonal to the oscillation and the fix belongs in the caller's precedence logic, not in the funnel.
- **Bryant-cloud writer** — the thermostat itself is oscillating (schedule re-entry, cloud state divergence). No URA abstraction can govern this.

A 24-hour clean read (log every URA emit + every Bryant `hold_activity` transition) is required to disambiguate. Recommended: run that read BEFORE dispatching HVAC-THERMOSTAT-ABSTRACTION-1 Phase 1, so that if the writer turns out to be Bryant-cloud we don't over-scope Phase 1 to try to catch a writer that isn't ours.

## 8. Recommendations (summary)

1. Advance **HVAC-THERMOSTAT-ABSTRACTION-1 Phase 1** (add `emit_set_hvac_mode` + migrate 7 sites) ahead of step-4-B. Tier 2, small blast radius, 7 mutation-verifiable sites. Do NOT fold HIGH-2 into it.
2. Keep **HIGH-2 (DPM preset bypass)** as a step-4-B point-gate on `_async_apply_preset_overrides`.
3. Park a Phase 2 `ZoneThermostat` design card (governed-write API composing funnel + borrow + snapshot-restore). Trigger: HIGH-2 point-gate leaks OR a second DPM-shaped intent bypass surfaces.
4. Block Phase 1 dispatch on the zone_1 24-hour read result — need to know if the re-manual writer is URA or Bryant.
5. (Adjacent) The `coordinator.py:1130` AI-rule chained-route gap (documented at :1096-1106) is a KNOWN OPEN escape hatch that Phase 1 does NOT close and Phase 2 also does not close without additional design. Not in scope for this audit; noted so it is not silently re-discovered.
