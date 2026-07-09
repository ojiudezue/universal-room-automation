# PLANNING — Fan / Humidity Room-Device Toggle Symmetry (design-only)

**Status:** DESIGN ONLY. Do not build until reconcile-on-return (v5.8.0) is deployed and live-validated.
**Author:** ura-planner
**Date:** 2026-07-05
**Cycle size:** hygiene / consolidation (see Tier recommendation §5).

---

## 0. TL;DR — this cycle is smaller than it first appears

The operator ask was framed as "add `FanControlSwitch` + `HumidityControlSwitch` because only `ClimateAutomationSwitch` / `CoverAutomationSwitch` exist today." **Institutional-context verification proves the switches already exist** as `RoomComfortFanControlSwitch` (`switch.py:4398`) and `RoomHumidityFanControlSwitch` (`switch.py:4413`), shipped in the bathroom-exhaust intelligence cycle D6 (planning doc `PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md:410-432`). They subclass a shared `_RoomBooleanOptionSwitch` base (`switch.py:4345`) that already:
- Reads seed default from merged `entry.data + entry.options` (`_read_default`, `switch.py:4360-4365`).
- Uses `RestoreEntity` for restart persistence (`switch.py:4367-4373`).
- Handles Bug Class #52 unavailable/unknown last-state correctly: `if last_state.state in ("on", "off")` — anything else falls back to `_read_default()` (`switch.py:4370-4373`). **Guard is already in place.**
- Mirrors writes back into `entry.options` on toggle (`_mirror_options`, `switch.py:4375-4385`).
- Is registered in the platform's `async_setup_entry` at `switch.py:317-318`.

The real gaps are (a) **naming symmetry / discoverability**, (b) **stale documentation** in the reconcile-on-return plan §6.9 that says these switches don't exist, and (c) **an unverified single-source-of-truth invariant** across the four `CONF_*` consumers. This cycle closes those three gaps. No new entities.

---

## 1. Institutional context verified

### 1.1 Greps run + REUSED/NEW annotations for every proposed surface

| Proposed surface | Verdict | Evidence |
|---|---|---|
| Per-room comfort-fan toggle switch entity | **REUSED — SHIPPED.** `RoomComfortFanControlSwitch` at `switch.py:4398-4410`, registered at `switch.py:317`. Slug `comfort_fan_control`, display "Comfort Fan Control", entity_category CONFIG, RestoreEntity, options writeback. Grep: `grep -n "class RoomComfortFanControlSwitch" custom_components/…/switch.py` → 1 hit. |
| Per-room humidity-fan toggle switch entity | **REUSED — SHIPPED.** `RoomHumidityFanControlSwitch` at `switch.py:4413-4428`, registered at `switch.py:318`. Slug `humidity_fan_control`, defaults `DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED` (True). |
| Shared base for options-writeback boolean switches | **REUSED.** `_RoomBooleanOptionSwitch` at `switch.py:4345-4395`. Bug Class #52 guard already correct (`:4370`). |
| `CONF_FAN_CONTROL_ENABLED` config field | **REUSED.** `const.py:591`. Default False. Present in config_flow at `:1848` and options_flow at `:8038`. |
| `CONF_HUMIDITY_FAN_CONTROL_ENABLED` config field | **REUSED.** `const.py:604`. Default via `DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED = True` (`const.py:605`). Present in config_flow at `:1850` and options_flow at `:8042`. |
| New `CONF_*` for the toggles | **NOT NEEDED.** Both already exist. The switch surface is a live mirror; the CONF is the persisted seed. This is the settled URA pattern for room-device boolean toggles (mirrored by `AutoRecoverySwitch` v5.8.0 D2.12 and `RoomFanRecheckEnabledSwitch`). |
| Any config-flow / options-flow change | **NOT NEEDED for D1/D2.** The fields already exist and are default-populated. D3 (naming realignment) may touch config_flow section labels only — see §3. |
| Rename to drop the `Room` prefix (align with `ClimateAutomationSwitch`) | **NEW — but DEFERRED (see §5 Out of Scope).** Renaming a shipped entity slug breaks entity_id stability. |

### 1.2 Prior planning docs consulted

- `docs/planning/PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md` (full read of the D6 room-device switch section, lines 410-432, 146, 158, 367-368). This is the doc that shipped the two switches. This cycle inherits its patterns.
- `docs/planning/PLANNING_reconcile_on_return.md` (§6.9 exclusion note lines 953-959, §7 sequencing lines 963-994). **§6.9 is stale — it says `FanControlSwitch` / `HumidityControlSwitch` "do not exist today" as operator-facing switches. They do (shipped in D6). This cycle's D3 corrects that note.** D2.12 also touches `automation.py` fan paths per the reconcile-on-return build (`AutoRecoverySwitch` gate), so ordering matters (see §5).
- `docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md` (grep of `CONF_FAN_CONTROL_ENABLED` reads) — confirmed line 418 precedence: "OPERATOR wins → Forbidden from touching this room." Consumer semantics unchanged by this cycle.
- `docs/planning/PLANNING_fan_noise_mitigation_layer2_actuation.md` (line 259) — same precedence, same semantics.
- `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md` (line 61) — presence path is a "do-not-touch" REUSED consumer of the CONF; this cycle preserves that.

### 1.3 Memory bodies pulled

- `project_session_pickup_2026_07_04.md` — flags "Fan/humidity toggle-symmetry backlog" as an open item; classifies reconcile-on-return as Tier 3, D2.7-D2.12, design-only, ships FIRST. This planning doc is the operator's follow-up.
- `project_v5_5_0_inclement_weather_shipped.md` — Bug Class #53 (computed-but-not-consumed) — informs the "single source of truth" audit in D2.

### 1.4 Design docs read

- None applicable (`docs/Coordinator/*.md` does not have a room-device-switch design doc; the shared pattern lives in the D6 planning doc referenced above).

### 1.5 Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/switch.py:300-329` (platform setup / entity list)
- `custom_components/universal_room_automation/switch.py:3407-3606` (sibling automation switches: `AutomationSwitch`, `ClimateAutomationSwitch`, `CoverAutomationSwitch`, `AutoRecoverySwitch`)
- `custom_components/universal_room_automation/switch.py:4337-4429` (D6 room-device toggles + `_RoomBooleanOptionSwitch` base)
- `custom_components/universal_room_automation/const.py:586-620` (Step 5 climate & fans + bathroom-exhaust CONF block)
- `custom_components/universal_room_automation/config_flow.py:1828-1858` (fan step schema in setup flow)
- `custom_components/universal_room_automation/config_flow.py:8028-8060` (fan step schema in options flow)
- `custom_components/universal_room_automation/automation.py:1542-1580` (comfort-fan control entry point — reads `CONF_FAN_CONTROL_ENABLED` at `:1549`)
- `custom_components/universal_room_automation/automation.py:1710-1760` (humidity-fan control — reads `CONF_HUMIDITY_FAN_CONTROL_ENABLED` at `:1749-1751`)
- `custom_components/universal_room_automation/actuator_reconciler.py:670-685` (reconciler comfort-fan gate — reads `CONF_FAN_CONTROL_ENABLED` at `:677`)
- `custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py:34, 242, 614` (presence rechecker reads the CONF — MERGED options at `:242`, `:614`)
- `custom_components/universal_room_automation/binary_sensor.py:754` (humidity-fan CONF read for a sensor attribute)

### 1.6 CONF read-site inventory (mandatory for the single-source-of-truth audit)

**`CONF_FAN_CONTROL_ENABLED` read sites (excluding the switch itself, tests, and docs):**

| # | File:line | Reads from | Notes |
|---|---|---|---|
| 1 | `automation.py:1549` | `self.config.get(...)` | `self.config` is initialized from `entry.data ∪ entry.options`. The switch writeback into `entry.options` propagates on reload but may not on every mid-runtime toggle unless the RoomAutomation object refreshes `self.config` on options-update. **Audit item D2.a.** |
| 2 | `actuator_reconciler.py:677` | `cfg.get(...)` where `cfg` is a merged dict (verify D2.a) | v5.8.0 D2.12 code — needs same audit. |
| 3 | `domain_coordinators/presence_fan_recheck.py:242` | `merged.get(...)` — explicitly a merged dict | Presumed correct — verify `merged` reflects post-toggle state. **Audit item D2.b.** |
| 4 | `domain_coordinators/presence_fan_recheck.py:614` | `merged.get(...)` | Same as above. |

**`CONF_HUMIDITY_FAN_CONTROL_ENABLED` read sites:**

| # | File:line | Reads from | Notes |
|---|---|---|---|
| 5 | `automation.py:1749-1751` | `self.config.get(...)` | Same `self.config` refresh question as #1. **Audit item D2.a.** |
| 6 | `binary_sensor.py:754` | `self.entry.options.get(...)` (verify exact form) | Diagnostic surface. Verify it re-renders on options update. |

**Total: 6 CONF read sites** that must be verified against a single source of truth after the switch is toggled at runtime. **The four `self.config`-based reads (`automation.py:1549`, `:1749-1751`, `actuator_reconciler.py:677`) are the highest-risk sites** — if `self.config` is a snapshot taken at coordinator init and not refreshed on `async_update_entry`, the switch will *appear* to work (options changes) but the automation will keep using the stale snapshot until reload. This is a **Bug Class #53 candidate** (computed-but-not-consumed) and is the entire reason this cycle needs a plan.

---

## 2. Decision: switch + config-flow field, or switch only?

**Decision: KEEP BOTH.** The switch is the operator-facing live surface; the config-flow field is the persisted install-time seed and the source used by `_read_default()` on first-ever startup (before any RestoreEntity state exists). Removing the config-flow field would break the install-time UX (operator toggles it at room-create time) and would break the D6 shipped semantics (config-flow default of `True` for humidity, `False` for comfort). Removing the switch would revert the ask.

**Justification:** the settled URA pattern (D6 comfort/humidity, v5.8.0 D2.12 auto-recovery, fan-recheck v4.7.22) is: **CONF field = seed + install-time UX; switch = live operator surface; `entry.options` = single persisted source of truth; consumers read merged config (which reflects options writeback).** This cycle preserves that pattern and audits its integrity.

---

## 3. Deliverables

### D1 — Documentation-only correction: reconcile-on-return §6.9 stale note

**What:** Edit `docs/planning/PLANNING_reconcile_on_return.md` §6.9 (lines 953-959) to reflect that `RoomComfortFanControlSwitch` and `RoomHumidityFanControlSwitch` SHIPPED in the bathroom-exhaust cycle D6, and cross-reference this planning doc as the follow-up.

**Why:** future planners re-reading §6.9 will re-propose already-shipped work. This is a five-minute correction that saves a future cycle from institutional-context waste.

**Acceptance criteria:**
- **Verify:** `docs/planning/PLANNING_reconcile_on_return.md` §6.9 no longer says "have no operator-facing per-room switch." Instead, it points at `switch.py:4398, 4413` and at this planning doc.
- **Verify:** the pointer is bidirectional — this doc's §1.2 already cites §6.9; §6.9 must cite this doc's filename.

### D2 — Single-source-of-truth audit for the six CONF read sites

**What:** for each of the six CONF read sites enumerated in §1.6, verify that a runtime switch toggle propagates within one reconciliation cycle (≤2s). If any site reads a stale snapshot, wire the switch's `_mirror_options` (or the entry's own `async_on_unload(entry.add_update_listener(...))` hook) to refresh the affected consumer.

**Sub-deliverables:**
- **D2.a** — verify `self.config` freshness in `automation.py` (three sites). Read `RoomAutomation.__init__` and any `options_updated` handler in `coordinator.py`. If `self.config` is a snapshot with no refresh, add an update listener that refreshes it. Document the finding in the cycle README (either "verified fresh — no change needed" or "wired refresh").
- **D2.b** — verify `merged` freshness in `presence_fan_recheck.py:242, 614`. `merged` is built inline per call — LIKELY fresh, but confirm the call is invoked per-cycle, not once at coordinator setup.
- **D2.c** — verify `actuator_reconciler.py:677` `cfg` freshness (v5.8.0 D2.12 code — inspect after reconcile-on-return deploys).
- **D2.d** — verify `binary_sensor.py:754` re-renders on options update. HA `SensorEntity` state re-computes on `async_update` — verify the sensor's update trigger reads from live options, not a cached copy.

**Acceptance criteria:**
- **Verify:** for each of the six sites, cite file:line and state "fresh" (no fix needed) or "wired via <mechanism>".
- **Test:** `test_room_toggle_writeback_propagates_to_consumers` — set up a room with `CONF_FAN_CONTROL_ENABLED=True` in options, exercise `automation.handle_temperature_based_fan_control(...)` (should proceed past guard), then toggle `switch.<room>_comfort_fan_control` OFF via the same code path used by the switch (`_mirror_options(False)`), re-invoke `handle_temperature_based_fan_control(...)`, assert early-return at the guard. Same test for `handle_humidity_based_fan_control`.
- **Test:** `test_presence_fan_recheck_reads_current_option` — parallel test for the `presence_fan_recheck.py` sites.
- **Live:** with the running HA instance, toggle `switch.<test-room>_comfort_fan_control` OFF while a fan is running; within 60s, `sensor.<room>_last_action` shows no further comfort-fan writes (the guard early-returns). Restore switch ON, verify comfort-fan control resumes on the next handler tick.
- **Live:** same test for `switch.<test-room>_humidity_fan_control` in a wet room.
- **Live (Bug Class #52 regression):** stop HA, edit `.storage/core.restore_state` to set `switch.<room>_comfort_fan_control` state to `unavailable`, restart. On startup the switch state MUST be the CONF-derived default (not OFF). Assert entity attribute or `sensor.<room>_last_action` first tick reflects CONF-derived value.

### D3 — Section-label consistency in config_flow (optional polish, low risk)

**What:** the fan step in `config_flow.py:1848-1852` presents `CONF_FAN_CONTROL_ENABLED` labeled by its default translation key. The label is inconsistent with the shipped device-card switch names ("Comfort Fan Control", "Humidity Fan Control"). Update `strings.json` / translation files so the config-flow label matches the switch's `_attr_name` ("Comfort Fan Control" and "Humidity Fan Control") for operator recognizability.

**Acceptance criteria:**
- **Verify:** `strings.json` (and `translations/en.json` if present) sets the labels to match the switch display names for both fields, in both the setup flow and the options flow.
- **Live:** open the URA options flow → Climate & Fans step → the two toggles show the same display strings as the corresponding device switches.

**NOTE:** D3 is nice-to-have. If the translation surface is riskier than expected on inspection, drop D3 and ship D1+D2 only.

---

## 4. Falsifiable invariant this cycle must preserve

**Invariant:** for every room `R` and every CONF `C ∈ {CONF_FAN_CONTROL_ENABLED, CONF_HUMIDITY_FAN_CONTROL_ENABLED}`, after any toggle of `switch.<R>_<slug>` at time `t`, every read of `C` in any coordinator, sensor, or automation path returns the toggled value for all reads at times ≥ `t + 2s` (single reconciliation cycle), and no read ever returns a value inconsistent with the current `switch` state (modulo the sub-2s propagation window).

If D2 audit shows any of the six sites can serve a stale value indefinitely, that's a HIGH finding and the propagation fix ships in the same cycle.

---

## 5. Tier recommendation

**Recommended: Tier 2 (two framing-disjoint reviews + live validation).** Not Tier 1 despite the small surface, and not Tier 2-DB / Tier 3 despite touching fan paths.

**Why not Tier 1:** D2 touches `automation.py` fan gates (indirectly, via propagation wiring) and the invariant is a cross-coordinator ripple property (Bug Class #53 candidate across 6 read sites). Per the CLAUDE.md "regression-prone" heuristic (June 2026 standing policy: "trust-hierarchy ripple ... shared primitive consumed by multiple coordinators"), a single-review pass could easily miss one of the six read sites.

**Why not Tier 2-DB / Tier 3:** No DB migration, no schema change, no persisted-record shape change, no dispatched-event payload change, no strategy/decision-logic change. The switches and CONF fields already exist; consumer semantics are unchanged. This is a **plumbing verification cycle**, not a new-capability or shared-primitive-modification cycle. Tier 3 is reserved for changes with a load-bearing falsifiable invariant across an enumeration-heavy surface (e.g. reserve-floor propagation across 7 emission sites); this cycle's invariant is honest but only 6 read sites deep, all local to the room-tier, and the failure mode ("stale gate for one reload cycle") is annoying not dangerous.

**Two review framings (per Tier 2 protocol):**
- **Review A — correctness + edge cases:** every one of the 6 CONF read sites verified against the runtime propagation mechanism; Bug Class #52 unavailable→OFF guard re-verified; the D3 label change reviewed for translation-key drift.
- **Review B — async lifecycle + interaction with in-flight cycles:** (i) does `entry.options` writeback fire an `async_update_entry` listener that could re-trigger a coordinator reload? (ii) does D2's refresh listener overlap with the reload-suppression stack (v4.7.26/v4.7.27)? (iii) does the Auto-Recovery switch's writeback (v5.8.0 D2.12) collide with these switches' writeback under a burst toggle?

### 5.1 Ordering / merge interaction with v5.8.0 reconcile-on-return

**v5.8.0 ships FIRST.** Per the 2026-07-04 pickup note, reconcile-on-return is Tier 3 design-only right now; it will build → review → deploy before this cycle starts. Interaction points:

1. **`actuator_reconciler.py:677` is v5.8.0 code.** D2.c cannot be audited until v5.8.0 lands. This cycle's D2.c audit is BLOCKED-BY v5.8.0 deploy.
2. **`AutoRecoverySwitch` (v5.8.0 D2.12) uses the same `_RoomBooleanOptionSwitch`-adjacent pattern** but appears to be a bespoke class (`switch.py:3579-3599`), not a subclass of `_RoomBooleanOptionSwitch`. Review B must check whether this cycle should refactor `AutoRecoverySwitch` onto the shared base for symmetry — RECOMMENDATION: **do not refactor.** `AutoRecoverySwitch` has additional Bug Class #52 documentation and a different default posture; leave it alone. Symmetry is not worth the risk to a safety primitive that just shipped.
3. **Merge conflict risk:** both cycles touch `switch.py` (entity registration list at `:317-320`) and `PLANNING_reconcile_on_return.md`. Low risk — D1 edits are additive text; the switch registration list is stable.
4. **Test infrastructure overlap:** v5.8.0 D2.8 asserts zero DB writes per reconcile. D2 tests here should assert zero DB writes per switch toggle as well, using the same DB-spy fixture v5.8.0 introduces (REUSE, don't duplicate).

**Sequencing:** ship this cycle AFTER v5.8.0 is live-validated, so D2.c can inspect the actual shipped `actuator_reconciler.py:677` code.

---

## 6. Out of scope

1. **Renaming the shipped entity slugs** from `comfort_fan_control` / `humidity_fan_control` to drop the (nonexistent) `Room` prefix or align with `climate_automation` / `cover_automation` naming. Renaming breaks entity_id stability and requires a repair issue. Not worth it — the display names ("Comfort Fan Control", "Humidity Fan Control") are already clear.
2. **New Number entities** for fan thresholds, timeouts, or runtimes. Explicitly out of scope per operator brief.
3. **Any change to fan control SEMANTICS** — sleep policy, HVAC coordination handoff, vacancy hold, temperature thresholds, humidity thresholds, spike detection, presence runtime. This cycle is plumbing only. All fan-logic changes belong in their own cycles (fan-noise Layer-2, fan-humidity toggle, etc.).
4. **Refactoring `AutoRecoverySwitch` onto `_RoomBooleanOptionSwitch`.** See §5.1.2.
5. **Adding a `HumidityFanRecheckEnabledSwitch` or similar** — no operator ask, no known use case.
6. **Any changes to the HVAC-coordinator fan path** (`hvac_fans.py`). The D6 cycle already collapsed the HVAC humidity path onto the room path. Comfort fans still have a room-vs-HVAC split which is deliberately unchanged by this cycle.

---

## 7. Deferred / not doing (plan completion tracking template)

| Item | Status | Notes |
|---|---|---|
| D1 §6.9 correction | PLANNED | 5-min edit; low risk. |
| D2.a `automation.py` self.config freshness | PLANNED | Highest-risk site; may need update-listener wiring. |
| D2.b `presence_fan_recheck.py` merged freshness | PLANNED | Likely no-op verify. |
| D2.c `actuator_reconciler.py` cfg freshness | PLANNED — BLOCKED BY v5.8.0 | Cannot audit until reconciler ships. |
| D2.d `binary_sensor.py:754` re-render | PLANNED | Likely no-op verify. |
| D3 label consistency | OPTIONAL | Drop if translation surface is riskier than expected. |
| Slug rename to strip `Room` prefix | OUT OF SCOPE | Entity_id stability. |
| `AutoRecoverySwitch` refactor onto shared base | OUT OF SCOPE | Safety primitive; leave alone. |
