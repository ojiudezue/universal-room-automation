# PLANNING — Bathroom Exhaust Intelligence + Humidity Fan Unification

**Version:** v5 (2026-06-22 — BUILD-READY; finalizes the last open questions: Q10 KEEP existing `DEFAULT_TARGET_TEMP_HEAT/COOL` const names; Q11 the demoted group is an EXPANDED `section("HVAC and Comfort Range")` (not collapsed/hidden); Q12 DEFER the Optimization-Coordinator Comfort-dimension wiring to the OC's own cycle, doc-note only. Supersedes v4 of 2026-06-22 PM which reframed the v3 D8 removal into a DEMOTE+RELABEL+WIRE.)
**Status:** BUILD-READY (all open questions Q1–Q12 resolved/defaulted; design settled with operator; do not re-litigate)
**Operator note (no pre-build config fix needed):** the zone "Entertainment + Master Suite" is a known vestigial NO-OP (a leftover combined-zone artifact predating the multi-zone→single-HVAC mapping; its two real zones "Entertainment" + "Master Suite" are both well-configured with `climate.thermostat_bryant_wifi_studyb_zone_1`). The D8 climate-fallback gate is therefore ALREADY satisfied by the real zones; deletion of the no-op zone is deferred (regression risk, no attention).
**Owner area:** Room-level automation (`automation.py`) + HVAC fans coordinator (`domain_coordinators/hvac_fans.py`) + room-device entity surfaces (`switch.py`, `binary_sensor.py`, `sensor.py`) + config/options flow (`config_flow.py`) + room coordinator entity-tracking (`coordinator.py`) + zone-thermostat fallback (`aggregation.py`)
**Tier:** **Tier 3** — Delicate Shared-Primitive, FOUR framing-disjoint reviews incl. adversarial-completeness D, + operator pre-deploy checkpoint
**Cycle shape:** single version, single Tier-3 cycle; all deliverables ship together

---

## v3 → v4 changelog (what changed in this revision)

Operator REVERSED the v3 D8 "remove redundant room-climate config" framing after a live audit and reflection on what the per-room climate fields are actually FOR. The three fields are NOT redundant — they are the only legitimate per-room comfort-evaluation knobs. v4 reframes D8 as **demote-and-wire**, not remove:

1. **`CONF_CLIMATE_ENTITY` — KEEP, demote in form ordering.** The operator explicitly values the `aggregation.py:3715-3725` zone-thermostat FALLBACK as resilience. The live audit found two zones without an explicit `CONF_ZONE_THERMOSTAT`: **"Outside"** (expected — no HVAC; the fallback may also return None there, which is fine) and **"Entertainment + Master Suite"** (a combined zone; operator will set its thermostat to `climate.thermostat_bryant_wifi_studyb_zone_1` SEPARATELY, outside this cycle, as a config-side fix). Because the fallback stays meaningful, the field is KEPT and the fallback logic in `aggregation.py` is NOT touched. The field is DEMOTED to the bottom of the renamed step so the step reads fans-first, climate-as-backstop.
2. **`CONF_TARGET_TEMP_COOL` + `CONF_TARGET_TEMP_HEAT` — KEEP, RELABEL as comfort range [low, high], WIRE both bounds into the score sensors.** Operator framing: a zone follows HC presets and has no comfort *desire* of its own, so the per-room targets are the legitimate home for "what temperature I'd actually like." The two values are reframed as a **comfort range** — `CONF_TARGET_TEMP_HEAT` = comfort-range LOW (min comfortable temp); `CONF_TARGET_TEMP_COOL` = comfort-range HIGH (max comfortable temp). Form fields RELABEL accordingly (e.g. "Comfort Range — Low (°F)" / "Comfort Range — High (°F)"). NO new CONF keys; reuse the existing two.
3. **THE FIX — wire BOTH bounds into the scorers.** Today only the COOL/high bound is read (`ComfortScoreSensor._get_setpoint` `sensor.py:1287-1291`; `EnergyEfficiencyScoreSensor._get_setpoint` `sensor.py:1395-1399`); `CONF_TARGET_TEMP_HEAT` is collected-but-never-read (Bug Class #53 — computed-but-not-consumed). v4 D8 updates both score sensors to grade against the comfort RANGE: in-range = comfortable; deviation BELOW the low bound (too cold) and ABOVE the high bound (too warm) both penalize. Operator explicitly wants the lower threshold scored "for completeness."
4. **Dead-code hygiene retained.** Delete `should_coordinate_with_hvac` (`automation.py:1809-1824`, zero callers, graphify-confirmed). Independent of keeping `CONF_CLIMATE_ENTITY`. This is the ONLY REMOVED item in v4 D8.
5. **D7 rename target changes from "Fans" to "Climate & Fans".** Since the climate entity + comfort range stay, the step keeps a climate aspect. The step renders **fans-first** (the three toggles + humidity-fan controls + wet-room flag + collapsed spike-advanced section), then the demoted **climate backstop** (comfort-range low/high + climate-entity fallback) at the BOTTOM.
6. **Institutional-context table updated.** The three "REMOVED CONF" rows are dropped. Two REUSED rows for the existing `CONF_TARGET_TEMP_COOL/HEAT` are added (relabel + wire-in, not new CONFs). `CONF_CLIMATE_ENTITY` row moves to REUSED (KEEP + demote). One REMOVED row remains: the dead `should_coordinate_with_hvac` method.
7. **Invariant I3 rewritten.** v3's "zone HVAC resolution preserved by removal" is replaced with: "comfort-range scoring uses both bounds; climate fallback unchanged."
8. **Reviewer-C mutation site updated.** v3's "neuter the repointed setpoint reader" becomes "neuter the low-bound scoring path, confirm a test fails." v3's "zone-thermostat-coverage gate enforcement" mutation site is dropped (no gate in v4).
9. **Reviewer-B + Reviewer-D enumeration updated.** Pre-removal gate, zone-creation post-removal hardening, and "stale-keys ignored" round-trip checks are DROPPED (no removal). Reviewer D's adversarial enumeration retains its v2 humidity-fan scope plus the NEW comfort-range edge cases (low > high, equal bounds, missing bound, deviation below low scored equally with deviation above high).
10. **Tier-3 framing UNCHANGED.** Four framing-disjoint reviews + operator pre-deploy checkpoint. The "shared primitive" character of v4 D8 is the comfort-range now feeding two score sensors (one missed bound = silently wrong score = Bug Class #53), so Tier 3 still applies — just for "wire both bounds correctly" rather than "remove gracefully."

(v1 → v2 and v2 → v3 changelogs preserved below verbatim for historical record.)

## v2 → v3 changelog (what changed in the prior revision)

Operator-approved after a context-wide audit of the per-room HVAC/climate config in the renamed Fans step (D7). Promotes the v2 "PARKED" climate-field item from a deferred future cycle into a first-class deliverable **D8** (REMOVAL framing — SUPERSEDED by v4; see v3 → v4 above):

1. **NEW D8 — Remove redundant room-level climate config.** Audit completed:
   - `CONF_TARGET_TEMP_HEAT` — **zero production readers** (grep clean across the package: only `const.py:584` def, `config_flow.py:194/1743/7749-7750` form surfaces). Delete outright.
   - `CONF_TARGET_TEMP_COOL` — read ONLY by `ComfortScoreSensor` (`sensor.py:1287-1291`) and `EnergyEfficiencyScoreSensor` (`sensor.py:1395-1399`) as a scoring setpoint. Must REPOINT those two score sensors onto a zone-sourced setpoint (zone range targets `target_temp_high/low` or the per-room comfort sliders) BEFORE deleting `CONF_TARGET_TEMP_COOL`.
   - `CONF_CLIMATE_ENTITY` — five read sites; functional dependency is exactly ONE:
     - `should_coordinate_with_hvac` (`automation.py:1814`) — **dead method**, zero callers in production code (graphify confirms internal-only references). Delete method + field read.
     - `_get_builtin_target_entities` (`coordinator.py:803`) — only adds to an entity-tracking set; harmless. Drop the branch.
     - `config_flow.py:1666` (create flow `_collect_entities`) and `:8481` (options flow mirror) — same harmless entity-tracking adds. Drop both branches.
     - `aggregation.py:3715-3725` — the ONE functional use: FALLBACK for zone-thermostat resolution when `CONF_ZONE_THERMOSTAT` is absent on the zone. Removing `CONF_CLIMATE_ENTITY` here is safe **only after** every zone has an explicit `CONF_ZONE_THERMOSTAT` — hence the D8 PRE-REMOVAL GATE.
     - `config_flow.py:7686-7704` (options-flow climate-step submit handler) — auto-populates a zone's `CONF_ZONE_THERMOSTAT` from the room's `CONF_CLIMATE_ENTITY` if the zone is missing one. This implicit bootstrap path goes away with D8; the gate (now-and-forever) replaces it.
2. **D7 "PARKED" note retracted.** The v2 plan parked `CONF_CLIMATE_ENTITY` + `CONF_TARGET_TEMP_COOL/HEAT` removal as a future audit. D8 supersedes that paragraph. D7's rename to "Fans" is now clean — NO climate/thermostat fields remain in the renamed step. D7 ships strictly cosmetic + label-side.
3. **Reviewer-B framing extended.** B must additionally verify that **removing** these three config keys (D8) does not break RestoreEntity / options-reload for existing entries: stale keys in stored entry data must be ignored by the new schema (HA replays stored data → unrecognized keys are dropped, NOT errored). B walks every existing-entry path (config-flow reconfigure, options-flow re-edit, integration reload, parent-entry reload).
4. **Reviewer-D adversarial enumeration extended.** D must additionally enumerate:
   - Any zone config entry lacking an explicit `CONF_ZONE_THERMOSTAT` post-D8 → broken zone HVAC resolution (the orphan-fan analog for D8).
   - A NEW zone created post-D8 (after `config_flow.py:7686-7704` is removed) — the auto-bootstrap path is gone; verify the zone-creation flow requires `CONF_ZONE_THERMOSTAT` explicitly (or surface as an open question for the build to enforce).
   - Any future code path that might re-introduce a `CONF_CLIMATE_ENTITY` lookup as a "convenience fallback" — explicit grep gate in CI is recommended (post-D8: zero `CONF_CLIMATE_ENTITY` references package-wide).
5. **Institutional-context table extended with REMOVAL rows** (the three deleted CONFs + the deleted method). These are formally "REMOVED" not REUSED/NEW; they get their own row tag.

(v1 → v2 changes preserved below verbatim.)

## v1 → v2 changelog (what changed in the prior revision)

Operator-settled decisions formalized — do NOT re-litigate:

1. **Decouple framing strengthened (D1).** Humidity/exhaust fans are ALWAYS room-owned, **independent of both `CONF_HVAC_COORDINATION_ENABLED` and `CONF_FAN_CONTROL_ENABLED`.** The existing HVAC-managed early-return at `automation.py:1700-1703` is deleted outright. The motivating repro is the **orphan-fan state** (HVAC-coord ON + comfort-fan OFF leaves humidity fan with neither owner) — promoted from afterthought to I1's headline reachable-state.
2. **Three toggles in a renamed "Fans" step (B).**
   - Toggle #1: rename `CONF_HVAC_COORDINATION_ENABLED` label to **"Enable HVAC-Managed Fans"** (it is fans-only — verified, sole consumer is `_is_hvac_managing_fans`).
   - Toggle #2: keep `CONF_FAN_CONTROL_ENABLED`, relabel **"Enable Comfort Fan Control"** (room-owned if #1 off, HVAC if #1 on).
   - Toggle #3: **NEW `CONF_HUMIDITY_FAN_CONTROL_ENABLED`** — explicit on/off for the humidity-fan automation. Default ON; auto-default ON when wet-room. When OFF, humidity fans are not automated by URA.
3. **NEW `CONF_WET_ROOM` flag (C).** Boolean adjacent to toggle #3 in the Fans step. Defaults True when `CONF_ROOM_TYPE == ROOM_TYPE_BATHROOM`, else False. Operator opt-in for laundry/mudroom. Gates D-spike defaults, D-presence-runtime defaults, and D-sleep-exemption. **Replaces** v1's "bathroom-type only" derived gate — explicit operator-controllable flag is cleaner than implicit room-type semantics. **Decision settled: do NOT mint new room types (toilet/laundry); `ROOM_TYPE_UTILITY ≠ laundry`.**
4. **Spike detection re-prioritized (D).** **EMA baseline is PRIMARY** (not `window_min`). Adaptive per-room EMA of humidity; trigger when `current ≥ baseline + Δ` (default Δ **+10pp**, α default ~45 min). Warm-up fallback to the absolute threshold (~20-30 min post boot/reload). Absolute `CONF_HUMIDITY_FAN_THRESHOLD` (60% default) is KEPT as a configurable fallback + OR companion. Baseline-relative OFF (turn off near baseline). **Clear EMA/spike buffer on fan-off** (re-arm). EMA α + Δ live in a **collapsed `section()`** in the Fans step (REUSE pattern from `fan_recheck_advanced` at `config_flow.py:2993`). Both α and Δ are exposed (not hard-hidden).
5. **Presence/usage-proportional post-vacancy runtime (E).** Model on `automation.guest_toilet_automation2`: `min(base + factor × occupancy_duration, cap)`. Operator-confirmed defaults: base 60s, factor 30s/min, cap 600s. Read URA's `_became_occupied_time` (`coordinator.py:152/1534/1588`), not a raw sensor. Gated by `CONF_WET_ROOM` (not by room_type).
6. **Room-DEVICE surface cleanup folded in (F → D6).** Per-room **Comfort Fan Control** + **Humidity Fan Control** switches (surface toggles #2/#3 as room-device entities); exhaust **state sensors** "Humidity Fan Should Run" / "Humidity Fan Active"; **scope-rename** `Fan Should Run` / `Fans On Count` → comfort-scoped names (split if they currently mix humidity). `RoomFanRecheck*` untouched. `"40 · Fan Control"` (`switch.py:3060`) on the HVAC-Coordinator device is global-master and OUT OF SCOPE except optional label tweak.
7. **Step rename (G → D7).** Room config step `async_step_climate` (`config_flow.py:1718`) and its options-flow mirror (`:7680`) **renamed "Fans"**. (v2 parked the climate-field removal; v3 promoted it to D8 removal; v4 reverses to demote-and-reframe so D7 renames to **"Climate & Fans"** — see v3 → v4.)
8. **Independence invariant restated.** Humidity/exhaust automation runs **independent of `CONF_FAN_CONTROL_ENABLED` AND independent of `CONF_HVAC_COORDINATION_ENABLED`**. The only gates on the humidity path are `CONF_HUMIDITY_FAN_CONTROL_ENABLED` (toggle #3) + the per-knob enables (spike, presence-runtime) + `CONF_WET_ROOM` (for sleep-exemption and default-on of spike/presence-runtime).

---

## Falsifiable invariant (state up front — Tier 3 discipline)

> **I1 (Exactly-One-Owner of every humidity fan across the full cross-product).**
> For every room with `CONF_HUMIDITY_FANS` non-empty, in every reachable state in the cross-product of:
>   `CONF_HVAC_COORDINATION_ENABLED ∈ {True, False}` × `CONF_FAN_CONTROL_ENABLED ∈ {True, False}` × `CONF_HUMIDITY_FAN_CONTROL_ENABLED ∈ {True, False}` × `CONF_WET_ROOM ∈ {True, False}` × `hvac_action ∈ {heating, cooling, idle, off}` × `house_state ∈ {home, away, sleep, home_night, waking}` × `fan_physically_on ∈ {True, False}` at the boundary,
> the room's humidity-fan entities are driven by **exactly one** controller — **never both** (dual-control fight) and **never neither** (orphan).
>
> After D1 ships, the room-level path (`automation.py::handle_humidity_based_fan_control`) is the **sole** controller when `CONF_HUMIDITY_FAN_CONTROL_ENABLED=True`. When toggle #3 is False, NO automated controller acts on humidity fans (the operator owns them manually). The HVAC path neither writes to nor reads humidity-fan state in any branch.

> **Orphan-fan reachable state (today's bug; I1's headline falsifier):**
> With `CONF_HVAC_COORDINATION_ENABLED=True` + `CONF_FAN_CONTROL_ENABLED=False`, today's code path is: room-path defers at `automation.py:1700-1703` via `_is_hvac_managing_fans()` → HVAC path runs `turn_off_all_managed` (`hvac.py:942` else-branch) which only acts on comfort fans → humidity fan is in the "neither owner" state. v2 deletes this branch, eliminating the orphan.

> **I2 (Comfort-fan path unchanged).**
> Rooms with `CONF_FANS` (comfort/ceiling) retain the existing HVAC-vs-room split **byte-for-byte** on the no-op path. No comfort-fan code path, no actuation order, no signal ordering changes as a side-effect of D1/D2/D3/D4/D5. D6 only ADDS entities and renames; D6 does NOT alter what gets actuated. **D8 (v4) does NOT touch comfort-fan code.**

> **I3 (Comfort-range scoring uses both bounds; climate fallback unchanged — REWRITTEN in v4).**
> Post-D8, every `ComfortScoreSensor` and `EnergyEfficiencyScoreSensor` reads BOTH `CONF_TARGET_TEMP_HEAT` (comfort-range LOW) AND `CONF_TARGET_TEMP_COOL` (comfort-range HIGH). No reachable code path scores against only one bound. Scoring rule: when `low ≤ temp ≤ high` → no temperature penalty (in-range); when `temp < low` → penalty proportional to `(low - temp)`; when `temp > high` → penalty proportional to `(temp - high)`. The `aggregation.py:3715-3725` zone-thermostat FALLBACK from `CONF_ZONE_THERMOSTAT` → `CONF_CLIMATE_ENTITY` is preserved byte-for-byte (v3's removal is REVERSED). No CONF key is collected-but-unread post-D8.

Reviewer D's sole job: produce a concrete legal-config repro that falsifies I1, I2, **or I3**.

---

## Tier classification

**Tier 3 — Delicate Shared-Primitive (FOUR framing-disjoint reviews + operator pre-deploy checkpoint).**

Justification (per CLAUDE.md Tier 3 triggers):

- **Shared primitive whose ownership migrates across coordinators.** Humidity fans are currently driven by TWO paths (`hvac_fans.py` humidity block + `automation.py` room path) selected by `_is_hvac_managing_fans()`. D1 collapses to ONE path. The failure mode of an ownership migration is exactly the Tier 3 shape — "one missed reachable state where the new owner doesn't drive AND the old owner already stopped" → orphan. Identical in shape to Bug Class #53 (computed-but-not-consumed).
- **Comfort-AND-safety adjacent.** Stuck-on bathroom exhaust at 3am = noise complaint; stuck-off exhaust during shower = mould/IAQ; ignored max-runtime cap = stuck-sensor runaway. The v4.6.2.x hardening (max-runtime cap, hysteresis, suppression, anchor seeding) MUST survive the migration intact.
- **Multi-coordinator + multi-surface ripple.** Touches `automation.py`, `hvac_fans.py`, `config_flow.py` (climate→"Climate & Fans" rename + new step contents + options mirror + room-climate DEMOTE + comfort-range RELABEL in D8), `switch.py` (new room-device switches), `binary_sensor.py` / `sensor.py` (new state sensors + scope-renames + D8 score-sensor WIRE-IN of both comfort-range bounds), sleep-policy semantics. Three independent toggles interact combinatorially with `CONF_WET_ROOM` — Tier-3 combinatorial discipline applies.
- **Operator-flagged delicate area** with multi-fix-up history (v4.6.2.1/.2/.3/.4 P3a/P3b/P3c anchor-clearing fix-ups across two minor versions to get the existing two-path semantics right).
- **D8 (v4) elevates further:** wiring a second collected-but-unread bound (`CONF_TARGET_TEMP_HEAT`) into two score sensors is exactly Bug Class #53 in reverse — one missed reader = the original gap; one missed bound on the new code path = a silently asymmetric scorer that penalizes only too-hot, not too-cold. Tier 3 stays.

### Reviewer framings (must be disjoint)

- **A — local correctness.** Hysteresis, min-runtime gate, max-runtime cap, suppression, anchor clearing, EMA arithmetic + α correctness + warm-up fallback, spike Δ comparator, presence-runtime formula bounds, cross-field validation (`presence_runtime_cap_s ≤ max_runtime`, `Δ` ≥ noise floor). NumberSelector min/max bounds. **D8 additions (v4):** verify the comfort-range scorer is correctly bi-directional — temp BELOW the low bound penalizes by `(low - temp) × penalty_per_degree`, temp ABOVE the high bound penalizes by `(temp - high) × penalty_per_degree`, temp in `[low, high]` produces zero temperature penalty. Verify defensive handling of pathological configs: `low > high` (form validator should reject; if it slips through, the scorer must NOT crash and should pick a safe fallback such as `min(low, high)`/`max(low, high)`), `low == high` (legal — degenerate range, zero in-range band), one bound missing from older entries (use the surviving bound + module-level default for the missing side).
- **B — state-machine + ownership migration integrity.** Walk the FULL cross-product (toggle #1 × #2 × #3 × wet_room × hvac_action × house_state × fan_pre_on). For each reachable transition: exactly-one-owner holds; no double-emit of turn_on/turn_off; no anchor wipe under runtime toggle flips; restart with fan ON seeds anchor exactly once in the new sole owner; deleting the `:1700-1703` branch does not strand a pre-existing `_humidity_on_since` across upgrade. **D8 additions (v4):** verify existing config entries (which carry `CONF_TARGET_TEMP_HEAT`/`CONF_TARGET_TEMP_COOL` already, just unread on the heat side) load cleanly into the relabeled form fields — no schema change, only label/help-text changes; verify `aggregation.py:3715-3725` zone-thermostat fallback is unchanged (`git diff aggregation.py::_get_zone_thermostat` shows no semantic change); verify the dead-method delete (`should_coordinate_with_hvac`) has zero callers via grep + graphify.
- **C — test authority via REAL per-site source mutation.** For each load-bearing site (room-path entry, sleep-policy branch, EMA-baseline branch, EMA warm-up fallback, spike-trigger branch, presence-runtime branch, wet-room gate, toggle #3 gate, max-runtime cap, suppression-clear, anchor-seed, **D8 (v4): comfort-range LOW-bound scoring path in ComfortScoreSensor, LOW-bound scoring path in EnergyEfficiencyScoreSensor, HIGH-bound scoring path in each (sanity), comfort-range cross-field validator if added**), the reviewer neuters ONE site in production source, runs the suite, confirms a SPECIFIC test fails, restores. Aggregate monkeypatch is insufficient. Sites whose bypass leaves the suite green are unacceptable. **D8 mutation focus (v4 named site):** neuter the LOW-bound scoring path (e.g. force the scorer to ignore `CONF_TARGET_TEMP_HEAT` and grade only against `CONF_TARGET_TEMP_COOL`); a SPECIFIC test (`test_d8_comfort_score_penalizes_too_cold`) MUST fail. If it does not, the low-bound is not tested and the cycle is unacceptable.
- **D — adversarial completeness / diff-blind.** Re-enumerates ALL emission/decision sites that touch `humidity_fans`, `CONF_TARGET_TEMP_COOL`, and `CONF_TARGET_TEMP_HEAT` across the ENTIRE repo (not just the diff — includes pre-existing code, per v5.5.3 precedent). States I1/I2/I3 in falsifiable form, produces concrete legal-config reachable repros for any leak. Specifically asked to enumerate at minimum:
  - HVAC coordinator stop/disable mid-cycle while humidity fan ON
  - Options-flow runtime change of `CONF_HVAC_COORDINATION_ENABLED` (any of the 8 reachable transitions of the 3 toggles)
  - Options-flow runtime change of `CONF_HUMIDITY_FANS` (add/remove entities mid-cycle)
  - Options-flow runtime change of `CONF_WET_ROOM`
  - Options-flow runtime change of `CONF_HUMIDITY_FAN_CONTROL_ENABLED` while fan is ON (must turn off cleanly OR leave running with cap armed — settled = leave running with cap armed, do NOT force-off on toggle-off)
  - Parent-entry reload mid-shower
  - Room-entry reload mid-shower
  - Fan turned on/off externally during sleep (bathroom & non-bathroom)
  - Spike fired while suppressed by max-runtime cap (suppression wins)
  - Presence-runtime fired with no humidity sensor configured (impossible by construction; verify)
  - EMA warm-up window crossed mid-shower
  - Toggle #3 OFF + toggle #1 ON + toggle #2 OFF (must NOT orphan — must be operator-owns-manual)
  - Two adjacent toggles flipped within one coordinator tick
  - **D8 (v4) — Any reachable code path in ComfortScoreSensor or EnergyEfficiencyScoreSensor that reads only ONE of the two comfort-range bounds (must be zero post-D8 — repo-wide grep gate + AST inspection of the two `_get_setpoint` methods, now likely renamed to `_get_comfort_range` returning `(low, high)`).**
  - **D8 (v4) — Pathological comfort-range configs: `low > high` (inverted), `low == high` (degenerate), `low` or `high` unset on an old entry that predates v4. For each, what does the scorer return? Crash? None? Asymmetric penalty? Verify the form validator catches the inverted case and the scorer degrades gracefully on the missing-bound case.**
  - **D8 (v4) — Any code path that previously assumed `CONF_TARGET_TEMP_COOL` was a single "setpoint" rather than the high bound of a range (e.g. attribute names like `setpoint` in the score sensor's `extra_state_attributes` at `sensor.py:1347` — must be renamed to `comfort_range_high` / `comfort_range_low` or otherwise disambiguated to avoid stale dashboard semantics).**
  - **D8 (v4) — `aggregation.py:3715-3725` zone-thermostat fallback: confirm UNCHANGED. Any reviewer-perceived "this fallback is dead because the room field is demoted" is a misread — the fallback stays. Reviewer D produces a `git diff` of the function as evidence.**
  - **D8 (v4) — `should_coordinate_with_hvac` deletion: confirm zero callers package-wide (grep + graphify), and that no `__all__` export or runtime introspection (`hasattr(obj, "should_coordinate_with_hvac")`) depends on it.**

---

## Institutional context verified

### Greps run + REUSED/NEW/REMOVED tally

For every proposed knob / entity / surface / removal, the verification result:

| Proposed item | REUSED / NEW / REMOVED | Evidence |
|---|---|---|
| Humidity-fan entity list | **REUSED** | `CONF_HUMIDITY_FANS` — `const.py:478`; surfaced `config_flow.py:1104`, `:7383` |
| Absolute humidity threshold (kept as OR companion to EMA) | **REUSED** | `CONF_HUMIDITY_FAN_THRESHOLD` — `const.py:590`, `config_flow.py:1750`/`:7783` |
| Min-runtime / off-delay gate | **REUSED** | `CONF_HUMIDITY_FAN_TIMEOUT` — `const.py:591`, `DEFAULT_HUMIDITY_FAN_TIMEOUT=600` `const.py:654` |
| Max-runtime cap | **REUSED** | `CONF_HUMIDITY_FAN_MAX_RUNTIME` — `const.py:592`, default `3600` `const.py:655` |
| Hysteresis | **REUSED** | `DEFAULT_HUMIDITY_FAN_HYSTERESIS=10` — `const.py:656` (constant; keep) |
| Room-type taxonomy | **REUSED** | `CONF_ROOM_TYPE` `const.py:306`, `ROOM_TYPE_BATHROOM` `:318`, `ROOM_TYPE_UTILITY` `:321`, `ROOM_TYPE_GENERIC` `:323`. **No new room types minted** (settled). |
| HVAC-coordination toggle (relabel only) | **REUSED** | `CONF_HVAC_COORDINATION_ENABLED` — `const.py:582`, `config_flow.py:1739`/`:7739`. Verified sole consumer is `_is_hvac_managing_fans` (`automation.py:1811/1832`) + label rename to "Enable HVAC-Managed Fans". |
| Comfort-fan toggle (relabel only) | **REUSED** | `CONF_FAN_CONTROL_ENABLED` — `const.py:585`, `config_flow.py:1746`/`:7755`, `automation.py:1501`. Label rename to "Enable Comfort Fan Control". |
| Sleep policy (constants + branch) | **REUSED** | `CONF_FAN_SLEEP_POLICY` + `FAN_SLEEP_OFF` (`automation.py:109`, branch `:1706-1719`). D4 wraps this branch in `CONF_WET_ROOM` guard rather than adding a new flag. |
| Sleep-mode active probe | **REUSED** | `is_sleep_mode_active()` — `automation.py:500` |
| Per-room occupied-duration source for D-presence-runtime | **REUSED** | `_became_occupied_time` on per-room coordinator — `coordinator.py:152`, `:1534`, `:1588-1589`, `:2127`. D3 reads via existing coordinator surface; NO new sensor. |
| Reload-mid-cycle anchor seeding | **REUSED** | `automation.py:1731-1736` (v4.6.2.3). Survives D1 unchanged; serves as the upgrade-migration mechanism for fans physically ON at upgrade. |
| `section()` collapsed-subsection pattern | **REUSED** | `from homeassistant.data_entry_flow import section`, `{"collapsed": True}`. 10 existing uses; nearest analog `fan_recheck_advanced` at `config_flow.py:2993`/`:3085`. Used for D-EMA advanced subsection. |
| Per-room device entities (switches/sensors) | **REUSED pattern** | `FanShouldRunBinarySensor` (`binary_sensor.py:679`, registered `:185`); `FansOnCountSensor` (`sensor.py:955`, registered `:461`). D6 adds parity siblings for humidity. |
| `_is_hvac_managing_fans` helper | **REUSED (kept)** | `automation.py:1826-1844`. Still consulted by comfort-fan paths; humidity path STOPS calling it (the `:1700-1703` early-return is deleted). Helper itself is NOT deleted. |
| Zone-thermostat resolution (UNCHANGED in v4) | **REUSED** | `CONF_ZONE_THERMOSTAT` — `const.py:901`; primary read `aggregation.py:3714`; fallback to `CONF_CLIMATE_ENTITY` at `:3715-3725` is PRESERVED byte-for-byte. `hvac_zones.py:265/368` discovery sites unchanged. |
| **`CONF_CLIMATE_ENTITY` (D8 — KEEP + DEMOTE)** | **REUSED** | `const.py:581`; form surfaces `config_flow.py:1736`/`:7733-7734`. KEPT for the `aggregation.py:3715-3725` zone-thermostat FALLBACK (operator values as resilience; live audit found two zones leaning on it — "Outside" expected, "Entertainment + Master Suite" operator will fix config-side). D8 (v4) DEMOTES the form field to the BOTTOM of the renamed step (last field or small low-priority group). Fallback logic UNCHANGED. The `coordinator.py:803` + `config_flow.py:1666`/`:8481` entity-tracking-set branches are harmless and KEPT. |
| **`CONF_TARGET_TEMP_COOL` (D8 — KEEP + RELABEL + WIRE)** | **REUSED** | `const.py:583`; form `config_flow.py:1740`/`:7743-7744`; readers `sensor.py:1287-1291` (ComfortScore), `:1395-1399` (EnergyEfficiency). D8 (v4) RELABELS form field to "Comfort Range — High (°F)" (semantic: max comfortable temp). Already wired into both score sensors as the upper bound. No const change. |
| **`CONF_TARGET_TEMP_HEAT` (D8 — KEEP + RELABEL + WIRE)** | **REUSED (currently collected-but-unread — Bug Class #53; D8 fixes)** | `const.py:584`; form `config_flow.py:194/1743/7749-7750`. Zero production readers TODAY. D8 (v4) RELABELS form field to "Comfort Range — Low (°F)" (semantic: min comfortable temp) AND wires it into BOTH score sensors as the lower bound (the fix). No const change. |
| **`CONF_HUMIDITY_FAN_CONTROL_ENABLED`** | **NEW** | Grep `const.py` / `config_flow.py` for `HUMIDITY_FAN_CONTROL` / `humidity_fan_control` — zero matches. Toggle #3. Default `True`; auto-default `True` when `CONF_WET_ROOM=True`. Justification: explicit operator control of humidity automation is required for the cross-product cleanup; no existing knob carries this semantic. |
| **`CONF_WET_ROOM`** | **NEW** | Grep `const.py` / `config_flow.py` for `WET_ROOM` / `wet_room` — zero matches. Boolean. Default `True` iff `CONF_ROOM_TYPE == ROOM_TYPE_BATHROOM`, else `False`. Operator opts in for laundry/mudroom. Replaces implicit room-type gate from v1. |
| **`CONF_HUMIDITY_FAN_SPIKE_ENABLED`** | **NEW** | No existing constant. Default `True` when `CONF_WET_ROOM=True`, else `False`. Gates D2. |
| **`CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT`** | **NEW** | EMA `current ≥ baseline + Δ` trigger. Default `10` (pp). Bounds `3-30`. |
| **`CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S`** | **NEW** | EMA time constant in seconds. Default `2700` (~45 min). Bounds `300-14400`. Exposed in collapsed `section()` ("Advanced — humidity baseline"). |
| **`CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE`** | **NEW** | Enum `{ema, window_min}`. **Default `ema`** (changed from v1). `window_min` retained as a fallback option (NOT a dead enum — both implemented). |
| **`CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED`** | **NEW** | Gates D3. Default `True` when `CONF_WET_ROOM=True`, else `False`. |
| **`CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S`** | **NEW** | Constant floor. Default `60`. Bounds `0-600`. |
| **`CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S`** | **NEW** | Seconds added per minute of occupancy. Default `30`. Bounds `0-300`. |
| **`CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S`** | **NEW** | Hard cap. Default `600`. Bounds `60-3600`. Validated `≤ CONF_HUMIDITY_FAN_MAX_RUNTIME`. |
| Per-room humidity state sensors (D6) | **NEW** | `HumidityFanShouldRunBinarySensor`, `HumidityFanActiveBinarySensor` — no existing entities. Parity siblings of `FanShouldRunBinarySensor`. |
| Per-room Comfort Fan Control switch (D6) | **NEW** | Surfaces toggle #2 as room-device switch (room-device parity for options-flow toggle). Justification: device card visibility of the toggle the operator is most likely to flip per-room. |
| Per-room Humidity Fan Control switch (D6) | **NEW** | Surfaces toggle #3 as room-device switch. |
| Comfort-scoped renames `Fan Should Run` / `Fans On Count` (D6) | **REUSED (rename only)** | Confirm comfort-fan-only scope; if currently mixing humidity entities, split. Entity-id stability handled per CLAUDE.md best practices. |
| **`should_coordinate_with_hvac` method** | **REMOVED (D8)** | `automation.py:1809-1824` — zero callers in production code (graphify-confirmed; only internal-only/test-only references in graph.json). Delete method body. Independent of keeping `CONF_CLIMATE_ENTITY`. |

**Total (v4): 19 REUSED, 11 NEW, 1 REMOVED method.** (v3's 3 REMOVED CONF rows are dropped; `CONF_CLIMATE_ENTITY`, `CONF_TARGET_TEMP_COOL`, `CONF_TARGET_TEMP_HEAT` are now REUSED — keep/demote, keep/relabel/wire, and keep/relabel/wire respectively. The score-sensor WIRE-IN of `CONF_TARGET_TEMP_HEAT` is a code change against existing const, not a new const.)

**Operator-side config follow-up (not a deliverable):** zone "Entertainment + Master Suite" lacks an explicit `CONF_ZONE_THERMOSTAT`; operator will set it to `climate.thermostat_bryant_wifi_studyb_zone_1` separately. Zone "Outside" legitimately has no HVAC and will continue to resolve via fallback (or None — both fine). Noted here so reviewers don't flag the two zones as a cycle-blocker.

### Prior planning docs consulted

- `docs/planning/PLANNING_v4.6.2.1_humidity_fan_hardening.md` — the cap/hysteresis/suppression contract that D1 must preserve byte-for-byte on the no-op path.
- `docs/planning/PLANNING_fan_noise_mode2_ble_pause_recheck.md` — confirms `_is_hvac_managing_fans()` is the HVAC↔room handshake we're modifying; fan-recheck mechanism is comfort-only, unaffected.
- `docs/planning/PLANNING_fan_noise_mitigation_layer2_actuation.md`, `PLANNING_fan_noise_mitigation_layers1_2.md` — comfort-fan noise mitigation; orthogonal to humidity. Confirms `CONF_FANS` semantics MUST NOT change (I2).
- `docs/planning/PLANNING_fan_trust_state_extension.md` — night-trust speed cap is comfort-only (`_apply_night_trust_speed_cap` `hvac_fans.py:376`). D1 does not ripple into trust-cap path.
- `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` — presence/fan actuation history.
- `docs/planning/PLANNING_hvac_presence_timer_knobs_and_options_writeback_retrofit.md` (v4.7.25) — options-writeback pattern. D5 follows this (options = sole source of truth + live read-through, no `__init__`-time caching).
- `docs/planning/PLANNING_part2_ec_hc_options_writeback_retrofit.md` — same options-writeback pattern.
- `docs/planning/PLANNING_v4.7.5_zone_manager_ux.md` + `docs/planning/PLANNING_v4.5.4_room_config_cleanup.md` — prior zone-vs-room config audits; relevant precedent for D8's room-climate DEMOTION (not removal in v4).
- `docs/readmes/README_v5.3.2.md`, BACKLOG.md, v4.6.3 reviews A/B — established v4.6.2.x hardening invariants.

### Memory bodies pulled

- Operator backlog memo: `project_powerview_and_humidity_fan_followups` — origin of this cycle.
- v4.7.25 presence-timer knobs (LIVE) — pattern for form-field knobs + live read-through + bidirectional clamp.
- CM reload-suppression cycle stack — options-writeback discipline; no parent-entry reloads to validate.
- "Number Fields = Form Fields" operator feedback — D5 surfaces are config_flow NumberSelector form fields, NOT NumberEntity platform registrations. (D6 separately adds genuine SwitchEntity / BinarySensorEntity registrations for room-device surfaces.)
- Tier 3 v5.5.3 Arbitrage-WAIT memo — precedent that 3 framing-disjoint reviews can all converge on a missing site; D adversarial-completeness pass is non-negotiable here. D re-enumerates pre-existing code too, not just the diff. **D8 (v4) falls in this shape too: `CONF_TARGET_TEMP_HEAT` is exactly Bug Class #53 (collected-but-not-consumed) and the fix is wiring one missed reader site per scorer — D enumerates both score sensors to confirm both bounds are read.**
- Comfort-sliders memory (per CLAUDE.md MEMORY.md "Comfort sliders → Optimization Coordinator") — comfort-slider Numbers are vestigial today and earmarked for the Optimization Coordinator. v4 D8 does NOT depend on them; the comfort-range high/low fields live on the room config entry and the scorers read them directly.

### Design docs read

- `docs/Coordinator/` — directory absent (verified Glob). HVAC-fans design lives in v4.6.2.x README + reviews; consulted those instead.

### Code locations surveyed end-to-end

- `automation.py::handle_humidity_based_fan_control` — `:1665-1807` (full body, verified `:1700-1703` deletion target)
- `automation.py::_is_hvac_managing_fans` — `:1826-1844` (kept)
- `automation.py::should_coordinate_with_hvac` — `:1809-1824` (**D8 deletion target — zero production callers**)
- `automation.py` sleep-mode + policy imports — `:109`, `:500`, `:1706-1719` (D4 wraps this branch)
- `automation.py` `_humidity_*` state init — `:186-191`
- `automation.py` `_fan_is_actually_on` — `:1650-1663`
- `automation.py::_evaluate_temp_fan` (comfort-fan path, MUST NOT change) — `:1501-…`
- `hvac_fans.py::discover_fans` — `:126-189` (humidity discovery sites `:151`, `:157-160`, `:170-176` — all deletion targets)
- `hvac_fans.py::update` humidity block — `:325-374` (deletion target)
- `hvac_fans.py::_evaluate_humidity_fan` — `:608-636` (deletion target)
- `hvac_fans.py::_set_fan_state` — `:653-686` (kept, comfort-only)
- `config_flow.py::async_step_climate` (CREATE) — `:1718-…` (rename to "Climate & Fans" + add toggle #3 + `CONF_WET_ROOM` + 7 D-knobs + RELABEL `CONF_TARGET_TEMP_COOL/HEAT` as comfort-range high/low + DEMOTE `CONF_CLIMATE_ENTITY` + comfort-range pair to the BOTTOM of the step). **NO field deletions in v4.**
- `config_flow.py::_collect_entities` create-flow — `:1660-1667` (UNCHANGED in v4 — `CONF_CLIMATE_ENTITY` branch at `:1666` KEPT)
- `config_flow.py` options-flow climate mirror — `:7680-…` (rename + DEMOTE; `:7686-7704` climate→zone-thermostat auto-bootstrap handler KEPT — operator values it as resilience; form fields at `:7733-7734/7743-7744/7749-7750` RELABELED, NOT removed)
- `config_flow.py` options-flow `_collect_entities` mirror — `:8478-8482` (UNCHANGED in v4)
- `config_flow.py` humidity-fan surfaces — `:114`, `:200-211`, `:1104`, `:1750-1758`, options `:7383-7384`, `:7783-7798`
- `config_flow.py::fan_recheck_advanced` `section()` analog — `:2993`, `:3085`
- `binary_sensor.py::FanShouldRunBinarySensor` — `:679`, registered `:185` (D6 adds humidity siblings + comfort-scope rename)
- `sensor.py::FansOnCountSensor` — `:955`, registered `:461` (D6 comfort-scope verify/rename)
- `sensor.py::ComfortScoreSensor._get_setpoint` — `:1287-1291` (**D8 WIRE-IN target in v4: replace single-setpoint return with comfort-range `(low, high)` — read BOTH `CONF_TARGET_TEMP_HEAT` and `CONF_TARGET_TEMP_COOL`; native_value + extra_state_attributes consume both bounds for bi-directional scoring**)
- `sensor.py::EnergyEfficiencyScoreSensor._get_setpoint` — `:1395-1399` (**D8 WIRE-IN target in v4: same as above**)
- `sensor.py::EnergyEfficiencyScoreSensor._get_zone_for_room` — `:1377-1393` (unchanged; informational only — D8 v4 does NOT repoint setpoint onto zone targets)
- `sensor.py` `extra_state_attributes` of both scorers — `:1346-1356` (and EnergyEfficiency analog): `"setpoint"` attribute should be replaced with `"comfort_range_low"` + `"comfort_range_high"` to avoid stale single-setpoint dashboard semantics
- `switch.py::HVACFanControlSwitch` — `:3060`, registered `:228` (HVAC-Coordinator device; OUT OF SCOPE except optional relabel)
- `coordinator.py::_became_occupied_time` — `:152`, `:1534`, `:1588-1589`, `:2127`
- `coordinator.py::_get_builtin_target_entities` — `:760, :803` (**UNCHANGED in v4 — `CONF_CLIMATE_ENTITY` branch at `:803` KEPT**)
- `aggregation.py::_get_zone_thermostat` (zone resolution) — `:3710-3725` (**UNCHANGED in v4 — `:3715-3725` fallback to `CONF_CLIMATE_ENTITY` PRESERVED; reviewer B produces `git diff` as evidence**)
- `domain_coordinators/hvac_zones.py` — `:265`, `:368` (CONF_ZONE_THERMOSTAT consumers; unchanged)
- `const.py` humidity-fan + room-type + toggle constants — `:306-324`, `:478`, `:582`, `:585`, `:590-592`, `:653-656`
- `const.py` D8-relevant constants (v4 — KEPT, no const changes) — `:581` (`CONF_CLIMATE_ENTITY`), `:583` (`CONF_TARGET_TEMP_COOL`), `:584` (`CONF_TARGET_TEMP_HEAT`), `:901` (`CONF_ZONE_THERMOSTAT`)
- `domain_coordinators/presence_fan_recheck.py` — confirmed CONF_FAN_CONTROL_ENABLED consumer (`:34`, `:242`, `:614`) is comfort-only; D1 does NOT change semantics there.

---

## Deliverables

### D1 — Decouple: humidity fans ALWAYS room-owned, independent of toggles #1 and #2

**What:** Make `automation.py::handle_humidity_based_fan_control` the sole controller for `CONF_HUMIDITY_FANS`. Remove the HVAC-coordinator humidity path entirely. Comfort fans (`CONF_FANS`) keep their existing HVAC-vs-room split unchanged (I2). Humidity automation runs **independent of `CONF_HVAC_COORDINATION_ENABLED` and `CONF_FAN_CONTROL_ENABLED`**; it is gated ONLY by the new `CONF_HUMIDITY_FAN_CONTROL_ENABLED` (toggle #3) + per-knob enables.

**Code changes (specified, not coded):**

1. **`automation.py`**
   - Delete the HVAC-managing early-return at `:1700-1703` (and the obsolete comment block `:1687-1699` documenting the v4.6.4 P3b clear behavior). The humidity path now ALWAYS runs.
   - Add a single guard at the top of `handle_humidity_based_fan_control` (after the `humidity_fans` / `humidity is None` early-return at `:1683-1685`): `if not self.config.get(CONF_HUMIDITY_FAN_CONTROL_ENABLED, True): return`. (Default True preserves behavior for entries without the new field; auto-default by `CONF_WET_ROOM` is set at config-flow submit time, not runtime.)
   - `_is_hvac_managing_fans()` is RETAINED — comfort-fan paths still consult it.

2. **`hvac_fans.py`** — humidity removal:
   - In `discover_fans()` (`:126-189`): drop `humidity_fans = merged.get(CONF_HUMIDITY_FANS, [])` (`:151`), drop the `hfan_list` derivation (`:157-160`), drop `humidity_fan_entities=hfan_list` from the `RoomFanState` construction (`:170`), drop `humidity_fan_threshold` and `humidity_fan_max_runtime` from the dataclass init (`:171-176`). Adjust the empty-skip condition at `:153-154` / `:162-163` to `if not fan_list` only.
   - Delete the entire humidity block in `update()` (`:325-374`).
   - Delete `_evaluate_humidity_fan` (`:608-636`).
   - Remove `humidity_fan_entities`, `humidity_fan_threshold`, `humidity_fan_max_runtime`, `humidity_on_since`, `humidity_cap_suppressed` from `RoomFanState`.
   - Remove `CONF_HUMIDITY_FANS`, `CONF_HUMIDITY_FAN_THRESHOLD`, `CONF_HUMIDITY_FAN_MAX_RUNTIME`, `DEFAULT_HUMIDITY_THRESHOLD`, `DEFAULT_HUMIDITY_FAN_MAX_RUNTIME`, `DEFAULT_HUMIDITY_FAN_HYSTERESIS` from `hvac_fans.py` imports IF no other site in that file consumes them post-deletion.

3. **Orphan-fan migration (settled — no new migration code):** The existing reload-mid-cycle anchor seeding (`automation.py:1731-1736`) handles "fan ON at upgrade-time in a previously-HVAC-managed room": first room-path eval seeds the anchor, max-runtime cap arms. B-review verifies `_humidity_on_since` is not pre-populated during setup before first eval; if it is, add explicit migration code (open question Q5).

4. **Toggle #3 OFF semantics (settled):** when `CONF_HUMIDITY_FAN_CONTROL_ENABLED=False`, the function returns early WITHOUT touching fan state. If the fan is physically ON at the moment of toggle-off, it STAYS ON (operator owns it manually). No force-off on toggle-off. Anchor state is NOT cleared (so re-enabling later picks up where it left off; max-runtime cap re-arms via reload-seed if needed).

**Acceptance criteria:**
- **Verify (I1):** `grep -n "humidity_fan\|CONF_HUMIDITY_FAN" hvac_fans.py` returns ZERO matches post-D1.
- **Verify (I1):** `grep -n "_is_hvac_managing_fans" automation.py` shows zero calls inside `handle_humidity_based_fan_control` body (function still called by comfort paths).
- **Verify (I2):** `git diff` for comfort-fan code paths in `hvac_fans.py` (`_evaluate_temp_fan`, `_apply_night_trust_speed_cap`, `_set_fan_state`, `suppress_room_until`, `snapshot_room_fan`) shows NO semantic changes — only humidity-field removals from `RoomFanState`.
- **Verify (I2):** `git diff automation.py::_evaluate_temp_fan` and `domain_coordinators/presence_fan_recheck.py` show no change.
- **Verify (orphan elimination):** with toggles #1=ON, #2=OFF, #3=ON, humidity above threshold, in-suite test asserts ONE turn_on call from `automation.py` and ZERO from `hvac_fans.py`. Pre-D1 this same scenario asserts ZERO turn_on calls from either (the orphan repro).
- **Test:** `test_humidity_fan_single_owner_invariant` parameterized over the **full I1 cross-product** (toggle #1 × #2 × #3 × wet_room × hvac_action × house_state × fan_pre_on, pruning unreachable cells with explicit comment): exactly one turn_on or turn_off per tick, issuer is always `automation.py` when #3=True; zero actuations when #3=False.
- **Test:** `test_humidity_fan_orphan_state_eliminated` — toggle #1=ON, #2=OFF, #3=ON, humidity>threshold → exactly one turn_on from `automation.py`. (Replays the pre-D1 orphan repro.)
- **Test:** `test_humidity_fan_ownership_migration_reload_seed` — fan ON at boot under previously-HVAC-managed config, `_humidity_on_since=None`; first room-path eval seeds anchor (line `:1731-1736`) and does not re-issue turn_on.
- **Test:** `test_humidity_fan_hvac_coordination_toggled_at_runtime` — flip toggle #1 False→True→False with fan running; max-runtime cap stays armed across both transitions (no anchor wipe from the deleted `:1700-1703` branch).
- **Test:** `test_humidity_fan_control_disabled_no_actuation` — toggle #3=False, humidity>threshold, fan OFF → no turn_on. Toggle #3=False, humidity>threshold, fan physically ON → no turn_off, no anchor mutation.
- **Test:** `test_humidity_fan_control_re_enabled_after_disable` — fan ON during disabled window, re-enable → next eval re-seeds anchor and arms cap correctly.
- **Live:** post-deploy, trigger a high-humidity event in (a) a non-HVAC-coordinated bathroom and (b) an HVAC-coordinated bathroom; both fire from `automation.py` log lines (`humidity_fan_*` debug/info), NOT from `HVAC Fans: ... humidity_fan_*`. Search HA log for `HVAC Fans:.*humidity_fan` post-restart → ZERO hits.
- **Live:** observe a humidity fan physically ON at restart in a previously-HVAC-coordinated room; within one room-eval cycle (≤ 60s) log emits `humidity_fan_reload_seeding`.
- **Live:** toggle #3 OFF on a running fan via options-flow; confirm fan stays ON, no log line about forcing off; toggle back ON; next eval re-seeds anchor.

### D2 — Humidity spike detection (EMA-baseline primary, additive to absolute threshold)

**What:** Adaptive per-room EMA baseline of humidity. Trigger spike when `current ≥ baseline + Δ` (default Δ = 10 pp, α default ~45 min via `CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S=2700`). Fires in ADDITION to the absolute threshold (logical OR). Warm-up: until baseline converges (~3 × α / 60 ≈ first 20-30 min after boot/reload, or until sample count ≥ N where N derived from α), fall back to the absolute threshold only. Baseline-relative OFF (turn off when humidity returns to ~baseline + small margin). Clear EMA + sample state on fan-off.

**Code changes (specified):**

1. **`automation.py`** — add per-room state on the room coordinator: `_humidity_ema: float | None`, `_humidity_ema_samples: int`, `_humidity_ema_warmup_seen_at: datetime | None` (timestamp of first sample post-reset; used for warm-up gate).
2. On each `handle_humidity_based_fan_control` entry (after the toggle #3 gate, before existing threshold logic), if `CONF_HUMIDITY_FAN_SPIKE_ENABLED=True`, update EMA: `α_per_sample = 1 - exp(-Δt / α_s)`; `ema = α_per_sample × humidity + (1-α_per_sample) × ema`. Increment `_humidity_ema_samples`. If `_humidity_ema_warmup_seen_at is None`, set it now.
3. **Warm-up gate:** spike trigger is DISARMED until `(now - _humidity_ema_warmup_seen_at).total_seconds() ≥ α_s/2` (heuristic — half a time constant; reviewer A may tighten). During warm-up, the absolute threshold is the sole ON-trigger; the existing path is byte-identical.
4. Post-warm-up, spike fires when `humidity - ema ≥ CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT`. ON branch becomes: `if humidity >= threshold OR spike_fired:` — same turn_on path, same anchor seeding, same max-runtime cap.
5. **Baseline-relative OFF (additive to absolute hysteresis):** OFF condition becomes `fan_is_on AND (humidity ≤ off_threshold OR (spike_was_trigger AND humidity ≤ ema + Δ_off))` where `Δ_off` = small constant (recommend Δ/2 = 5 pp). Reviewer A to validate this does not race the min-runtime gate.
6. **Re-arming (settled):** on fan-OFF (via off-threshold, baseline-relative OFF, or max-runtime cap), reset `_humidity_ema = None`, `_humidity_ema_samples = 0`, `_humidity_ema_warmup_seen_at = None`. Next ON event starts a fresh baseline.
7. **`window_min` mode (alternative `CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE=window_min`):** implemented as fallback — rolling deque of `(ts, humidity)`, window = `α_s` (reused as window-seconds in this mode); baseline = `min(h in window)`. Same warm-up rules apply (`samples ≥ 2`). Both modes are implemented (no dead enum).
8. Spike trigger is gated by `CONF_HUMIDITY_FAN_SPIKE_ENABLED`. EMA state is not maintained when disabled.
9. **EMA α + Δ exposed in a collapsed `section()`** in the renamed "Climate & Fans" step — see D5 / D7. Pattern: REUSE `from homeassistant.data_entry_flow import section`, `{"collapsed": True}` per `fan_recheck_advanced` (`config_flow.py:2993`).

**Acceptance criteria:**
- **Verify:** when `CONF_HUMIDITY_FAN_SPIKE_ENABLED=False`, code path is byte-identical to D1 (no EMA state mutation).
- **Verify:** warm-up gate produces zero spike triggers in the first `α_s/2` seconds post-reset.
- **Test:** `test_humidity_spike_fires_below_absolute_threshold_after_warmup` — α=300s (test override), threshold=70, baseline EMA converges to 45 over ~150s, then sample rises 45→55 in 60s → fan turns on (spike) without humidity reaching 70.
- **Test:** `test_humidity_spike_warmup_blocks_premature_fire` — first sample 60% (baseline still 60% trivially), instant 65% sample within warm-up → NO spike (warm-up active); same scenario post-warm-up → spike fires.
- **Test:** `test_humidity_spike_disabled_no_op` — same sequence with flag False, fan stays off.
- **Test:** `test_humidity_spike_does_not_double_fire` — once spike triggered + fan in min-runtime gate, falling-then-rising humidity does NOT re-trigger (existing `_humidity_fan_triggered_time` semantics).
- **Test:** `test_humidity_spike_post_cap_suppression_wins` — max-runtime cap fires, `_humidity_cap_suppressed=True`; spike trigger does NOT bypass suppression.
- **Test:** `test_humidity_spike_rearm_clears_ema_on_fan_off` — fan turns off via off-threshold; `_humidity_ema is None` afterward; next sample seeds a fresh baseline.
- **Test:** `test_humidity_spike_window_min_mode_parity` — same shower sequence under `baseline_mode=window_min`: spike fires; baseline = window-min not EMA.
- **Test:** `test_humidity_spike_baseline_relative_off` — post-shower, humidity drops to `ema + 4` (below Δ_off=5) → fan turns off after min-runtime even if absolute off_threshold not crossed.
- **Sensor:** no new sensor required by D2 itself (D6 adds the visibility entities). Optional one-shot `_LOGGER.info("humidity_fan_spike_triggered: baseline %.1f -> %.1f in %ds (mode=%s)")` for live observability.
- **Live:** run a hot shower in a bathroom configured with `threshold=75`, `Δ=10`, `α=2700s`, after the room has been idle ≥ 25 min (warm-up complete). Exhaust fires on the rising edge well before humidity reaches 75. Spike info line present.
- **Live:** observe `_humidity_ema` evolution via debug log (optional) during a non-shower day; baseline tracks ambient drift within ~Δ.

### D3 — Presence/usage-proportional post-vacancy runtime (gated by `CONF_WET_ROOM`)

**What:** Port `automation.guest_toilet_automation2` into URA: after the room becomes vacant, keep exhaust running for `min(BASE_S + PER_MIN_S × occupancy_minutes, CAP_S)` seconds. Gated by `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED` (D4 default: True iff `CONF_WET_ROOM=True`).

**Code changes (specified):**

1. Read `occupancy_minutes` from existing `_became_occupied_time` (`coordinator.py:152`). On `occupied → vacant` edge, snapshot `occupancy_minutes = (vacant_at - became_occupied_time) / 60`, compute `post_run_s = min(BASE_S + PER_MIN_S × occupancy_minutes, CAP_S)`, store `_humidity_presence_runtime_until = now + post_run_s`.
2. In `handle_humidity_based_fan_control`, before the existing OFF branch (`:1790`): if `_humidity_presence_runtime_until is not None AND now < _humidity_presence_runtime_until AND not _humidity_cap_suppressed`, keep fan ON (skip OFF branch). Existing ON path always wins when humidity/spike still elevated.
3. Clear `_humidity_presence_runtime_until` on: cap-fire, explicit turn_off after window expires, wet-room flag toggled off mid-window.
4. **Wet-room gate:** when `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED=False`, branch is skipped (byte-identical to D2).

**Edge cases (must test):**
- Vacancy fires while humidity still > threshold → ON path keeps fan on; presence-runtime takes effect after humidity drops.
- Re-entry during presence-runtime window → `_became_occupied_time` resets per existing coordinator behavior; on NEXT vacancy edge, recompute post-run with the longer occupancy.
- Room has no humidity sensor → `handle_humidity_based_fan_control` early-returns at `:1684` (humidity None); presence-runtime CANNOT fire by construction. D-review verifies.
- Max-runtime cap during presence-runtime → cap wins; suppression armed; window cleared.

**Acceptance criteria:**
- **Verify:** `CAP_S` default (600) < `CONF_HUMIDITY_FAN_MAX_RUNTIME` default (3600). Config-flow validator rejects `CAP_S > MAX_RUNTIME` at submit time.
- **Test:** `test_presence_runtime_short_visit` — 1 min occupancy → 60 + 30 = 90s post-vacancy run.
- **Test:** `test_presence_runtime_long_visit` — 20 min occupancy → min(60 + 600, 600) = 600s (cap hit).
- **Test:** `test_presence_runtime_disabled_no_op` — flag off, fan turns off normally at off-threshold.
- **Test:** `test_presence_runtime_max_runtime_wins` — humidity stuck high, max-runtime fires while presence-runtime would extend; cap wins.
- **Test:** `test_presence_runtime_no_humidity_sensor_dormant` — no `CONF_HUMIDITY_SENSOR` → no state mutation.
- **Test:** `test_presence_runtime_reentry_resets_window` — vacancy → re-enter at 30s → re-vacate at 5min; final post-run uses 5-min occupancy.
- **Test:** `test_presence_runtime_wet_room_toggled_off_clears_window` — wet_room flipped False mid-window → window cleared.
- **Live:** validate with operator's actual guest-toilet bathroom: 5-min visit produces ~3.5-min post-vacancy fan run (60 + 5×30 = 210s). Observe via fan entity `last_changed`.

### D4 — `CONF_WET_ROOM` flag + sleep-exemption + default cascade

**What:**
1. **`CONF_WET_ROOM`** is a new boolean form field placed ADJACENT to toggle #3 in the renamed "Climate & Fans" step (D5/D7). Default: `True` iff `CONF_ROOM_TYPE == ROOM_TYPE_BATHROOM`; else `False`. Operator opts in per-room for laundry/mudroom.
2. **Default cascade:** at config-flow submit time:
   - `CONF_HUMIDITY_FAN_CONTROL_ENABLED` defaults `True` iff `CONF_WET_ROOM=True`, else `True` anyway (operator's existing humidity fan config should keep working — toggle defaults ON regardless, but it auto-presents as ON for wet-rooms with friendlier visibility).
   - `CONF_HUMIDITY_FAN_SPIKE_ENABLED` defaults `True` iff `CONF_WET_ROOM=True`, else `False`.
   - `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED` defaults `True` iff `CONF_WET_ROOM=True`, else `False`.
3. **Sleep-policy exemption:** in `automation.py::handle_humidity_based_fan_control` at `:1706-1719`, the existing `FAN_SLEEP_OFF` force-off branch is wrapped in `if not self.config.get(CONF_WET_ROOM, False):`. Wet-room exhausts ignore the comfort-fan sleep policy — they remain governed only by absolute threshold + spike + presence-runtime + max-runtime cap. Operator framing: "a 3am toilet exhaust must not be blocked by sleep policy."

**Acceptance criteria:**
- **Verify:** grep `automation.py` for the `FAN_SLEEP_OFF` branch — wrapped in `CONF_WET_ROOM` guard.
- **Test:** `test_wet_room_exhaust_runs_through_sleep` — house in sleep, FAN_SLEEP_OFF set, wet-room humidity > threshold → exhaust ON. Max-runtime cap still fires at 3600s.
- **Test:** `test_non_wet_room_humidity_fan_sleep_policy_unchanged` — generic room with humidity fan, FAN_SLEEP_OFF, humidity > threshold → force-off per existing v3.18.1 semantics (no regression).
- **Test:** `test_spike_default_off_for_non_wet_room` — config entry with `CONF_WET_ROOM=False` and no explicit spike flag → spike NOT armed.
- **Test:** `test_spike_default_on_for_wet_room_bathroom` — config entry with `room_type=BATHROOM` (auto wet_room=True) → spike armed at defaults.
- **Test:** `test_wet_room_auto_default_from_room_type_bathroom` — submitting form with `room_type=BATHROOM` → `CONF_WET_ROOM=True` in submitted data.
- **Test:** `test_wet_room_auto_default_from_room_type_utility_is_false` — `room_type=UTILITY` → `CONF_WET_ROOM=False` (operator must opt in for laundry; safer default per operator decision).
- **Live:** in a wet-room, force humidity above threshold during the active sleep window; fan turns on and stays on. In a non-wet-room with humidity fan + FAN_SLEEP_OFF, verify the same humidity reading produces a force-off log line.

### D5 — Config-flow / options-flow surfaces (new fields + collapsed advanced subsection)

**What:** Add the new fields into the (renamed) "Climate & Fans" step and mirror in options-flow. Pattern: NumberSelector / BooleanSelector / SelectSelector. Follow v4.7.25 options-writeback discipline (options = sole source of truth; live read-through each cycle).

**Field placement** (information hierarchy: fans-first, climate-backstop-last):

| Section | Form field | Type | Default | Min/Max | Notes |
|---|---|---|---|---|---|
| **Fans (top)** | Toggle #1 `CONF_HVAC_COORDINATION_ENABLED` (relabel "Enable HVAC-Managed Fans") | Boolean | existing | — | Relabel only |
| | Toggle #2 `CONF_FAN_CONTROL_ENABLED` (relabel "Enable Comfort Fan Control") | Boolean | existing | — | Relabel only |
| | Toggle #3 `CONF_HUMIDITY_FAN_CONTROL_ENABLED` | Boolean | `True` | — | Master enable for humidity automation |
| | `CONF_WET_ROOM` | Boolean | derived from room_type (D4) | — | Adjacent to toggle #3 |
| | `CONF_HUMIDITY_FAN_SPIKE_ENABLED` | Boolean | derived (D4) | — | Spike trigger master |
| | `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED` | Boolean | derived (D4) | — | Post-vacancy timer master |
| | `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S` | Number | 60 | 0-600 | seconds |
| | `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S` | Number | 30 | 0-300 | seconds per minute occupied |
| | `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S` | Number | 600 | 60-3600 | validated `≤ CONF_HUMIDITY_FAN_MAX_RUNTIME` |
| | Existing `CONF_HUMIDITY_FANS`, `CONF_HUMIDITY_FAN_THRESHOLD`, `CONF_HUMIDITY_FAN_TIMEOUT`, `CONF_HUMIDITY_FAN_MAX_RUNTIME` | various | existing | — | Kept |
| | Existing `CONF_FANS`, `CONF_FAN_SLEEP_POLICY` | various | existing | — | Kept |
| | **collapsed `section("Advanced — humidity baseline")`:** | | | | |
| | `CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT` | Number | 10 | 3-30 | % RH above baseline |
| | `CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S` | Number | 2700 | 300-14400 | seconds (EMA time constant) |
| | `CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE` | Select | `ema` | enum | `{ema, window_min}` — both implemented |
| **HVAC and Comfort Range (bottom — DEMOTED in v4)** | `CONF_TARGET_TEMP_HEAT` (RELABEL "Comfort Range — Low (°F)") | Number | existing default | typical 60-75 | Comfort-range low bound; wired into score sensors (D8) |
| | `CONF_TARGET_TEMP_COOL` (RELABEL "Comfort Range — High (°F)") | Number | existing default | typical 70-82 | Comfort-range high bound; wired into score sensors (D8) |
| | `CONF_CLIMATE_ENTITY` (KEEP, last field) | Entity selector | existing | — | Optional fallback for zone-thermostat resolution (`aggregation.py:3715-3725`); see D8 |

**Cross-field validator (D8):** at form submit, validate `CONF_TARGET_TEMP_HEAT ≤ CONF_TARGET_TEMP_COOL` (low ≤ high). Reject submit with a clear error if inverted. `low == high` is legal (degenerate range; zero in-range band).

**Live read-through:** all new knobs read via `self.config.get(...)` each cycle (no `__init__`-time caching), matching the existing humidity-fan-knob pattern at `automation.py:1721-1723`. Options changes take effect on next tick without reload (no parent-entry reload — per CLAUDE.md "Parent-entry reload → watchdog restart hazard").

**Acceptance criteria:**
- **Verify:** form-submit validator rejects `PRESENCE_RUNTIME_CAP_S > HUMIDITY_FAN_MAX_RUNTIME`.
- **Verify:** form-submit validator rejects `CONF_TARGET_TEMP_HEAT > CONF_TARGET_TEMP_COOL` (comfort-range inverted).
- **Verify:** options flow surfaces all new fields; defaults pre-populated from current entry data.
- **Verify:** no NumberEntity / platform-Number registration in `number.py` for the D5 knobs ("Number Fields = Form Fields"). (D6 separately adds switches/sensors as platform entities; that is intentional.)
- **Verify:** collapsed `section("Advanced — humidity baseline")` uses the same import/pattern as `fan_recheck_advanced` (`config_flow.py:2993`).
- **Verify (v4):** form renders fans-first / climate-last. UI/screenshot confirmation that the three climate-backstop fields appear at the BOTTOM of the step (or in a small low-priority labeled group such as `section("HVAC and Comfort Range")`).
- **Test:** `test_config_flow_bathroom_defaults` — submitting `room_type=BATHROOM` → `CONF_WET_ROOM=True`, `spike_enabled=True`, `presence_runtime_enabled=True` in entry data.
- **Test:** `test_options_flow_writeback_live` — change `spike_delta_pct` 10 → 14 via options; next humidity-fan eval reads 14 (no reload).
- **Test:** `test_form_rejects_cap_above_max_runtime` — submit `presence_runtime_cap_s=4000, max_runtime=3600` → form error.
- **Test:** `test_form_rejects_inverted_comfort_range` — submit `target_temp_heat=78, target_temp_cool=72` → form error.
- **Test:** `test_form_baseline_mode_both_modes_accepted` — submit `baseline_mode=ema` AND `baseline_mode=window_min` separately, both produce valid entries.
- **Live:** open room config entry in HA UI, options flow shows the renamed "Climate & Fans" step + fans-first ordering + new subsection + collapsed advanced section + climate-backstop trio at bottom; change a knob; next coordinator log line reflects new value within one cycle. No watchdog restart.

### D6 — Room-DEVICE entity surface cleanup

**What:** The ROOM device today exposes comfort + presence fan entities but ZERO humidity/exhaust control or state. Add the missing humidity surfaces and tighten the comfort-fan entity scoping.

**Changes:**

1. **NEW switches on the room device:**
   - **Comfort Fan Control** switch — backs `CONF_FAN_CONTROL_ENABLED` (toggle #2). Surfaces the options-flow toggle as a device-card entity per CLAUDE.md HA best practices (entity_id stability, RestoreEntity, options-writeback on toggle).
   - **Humidity Fan Control** switch — backs `CONF_HUMIDITY_FAN_CONTROL_ENABLED` (toggle #3). Same pattern.
   - Pattern reference: `HVACFanControlSwitch` (`switch.py:3060`) for the writeback structure, BUT these new switches are ROOM-device-scoped, not HVAC-Coordinator-device-scoped. Register alongside existing room switches in `switch.py::async_setup_entry`.
2. **NEW per-room binary sensors:**
   - **`HumidityFanShouldRunBinarySensor`** — `True` iff the room-path logic WOULD turn the fan on right now (humidity ≥ threshold OR spike OR presence-runtime active), gated by toggle #3 and not currently suppressed. Parity sibling of `FanShouldRunBinarySensor` (`binary_sensor.py:679`).
   - **`HumidityFanActiveBinarySensor`** — `True` iff the controller is actively driving the fan (currently in the ON state with anchor set). Distinct from "physically on" (operator override is `should_run=False AND active=False AND fan.state=on` → user-controlled).
   - Register in `binary_sensor.py::async_setup_entry` alongside `FanShouldRunBinarySensor` (`:185`).
3. **Scope-rename existing comfort entities:**
   - `FanShouldRunBinarySensor` → confirm scope is comfort-fan-only. If it currently OR's in humidity-fan state, **split** into comfort-only and the new humidity sensor. Display name → "Comfort Fan Should Run". Entity ID transition handled per CLAUDE.md HA best practices (avoid breaking dashboards — recommend keeping entity_id stable, only changing `_attr_name`).
   - `FansOnCountSensor` (`sensor.py:955`) → confirm count is comfort-fan-only. If it currently includes humidity fans, exclude them and rename display to "Comfort Fans On Count". Same entity-id stability guidance.
   - `RoomFanRecheck*` — UNTOUCHED (already clearly presence-scoped).
   - `HVACFanControlSwitch` (`switch.py:3060`) on the HVAC-Coordinator device — OUT OF SCOPE except optional label refinement to "HVAC-Managed Fans (Global)" to disambiguate from the new room-device Comfort Fan Control switch.

**Acceptance criteria:**
- **Verify:** new room-device switches appear on each room device card; toggling writes back to the entry options (live read-through validates).
- **Verify:** new humidity sensors appear on each room device that has `CONF_HUMIDITY_FANS` configured; absent on rooms without.
- **Verify:** scope audit — `FanShouldRunBinarySensor` / `FansOnCountSensor` source reads only `CONF_FANS` (not `CONF_HUMIDITY_FANS`).
- **Verify:** entity_ids of the renamed comfort sensors are unchanged (only `_attr_name` updated).
- **Test:** `test_humidity_fan_should_run_sensor_tracks_eval` — toggle #3 ON, humidity ramps above threshold → sensor flips True; toggle #3 OFF → sensor flips False even if humidity still high.
- **Test:** `test_humidity_fan_active_sensor_distinguishes_operator_override` — fan physically ON via operator manual action while controller has not driven it → `should_run` follows logic, `active=False`.
- **Test:** `test_humidity_fan_should_run_respects_suppression` — post-cap suppression armed → sensor reads False even if humidity above threshold.
- **Test:** `test_comfort_fan_should_run_excludes_humidity` — populate both `CONF_FANS` and `CONF_HUMIDITY_FANS`; force humidity-on but comfort-off → `FanShouldRunBinarySensor` (comfort-scoped) reads False; new `HumidityFanShouldRunBinarySensor` reads True.
- **Test:** `test_room_device_comfort_switch_writeback` — toggle Comfort Fan Control switch on device → `CONF_FAN_CONTROL_ENABLED` in options updated; restart → switch state restored.
- **Test:** `test_room_device_humidity_switch_writeback` — same for Humidity Fan Control.
- **Live:** open a room device card in HA UI post-deploy: confirm new Comfort Fan Control + Humidity Fan Control switches; confirm new humidity sensors; confirm renamed comfort sensors carry comfort-scoped display name but same entity_id.

### D7 — Rename room "Climate" step → "Climate & Fans" (v4 — fans-first information hierarchy)

**What:** Rename `async_step_climate` (`config_flow.py:1718`) and its options-flow mirror (`:7680`) to **"Climate & Fans"** (display label + step id where safe; entity-id and translation-key stability per HA best practices). Since v4 D8 KEEPS the per-room climate entity + the comfort-range pair (with the pair RELABELED + WIRED in D8), the step keeps a climate aspect — hence the dual name.

**Information hierarchy (settled with operator):**
1. **Fans FIRST:** the three toggles (HVAC-managed / comfort / humidity) + humidity-fan controls + `CONF_WET_ROOM` flag + collapsed `section("Advanced — humidity baseline")`.
2. **HVAC and Comfort Range LAST:** the demoted comfort-range pair (`CONF_TARGET_TEMP_HEAT` low / `CONF_TARGET_TEMP_COOL` high) + `CONF_CLIMATE_ENTITY` fallback selector. May optionally live inside a small `section("HVAC and Comfort Range")` group for visual demotion.

**v4 update:** the v3 plan removed `CONF_CLIMATE_ENTITY` + `CONF_TARGET_TEMP_COOL/HEAT` outright (and renamed the step to "Fans"). v4 REVERSES the removal — fields KEPT and demoted, step renamed to "Climate & Fans" instead of "Fans" to reflect the surviving climate aspect.

**Acceptance criteria:**
- **Verify:** step ID change (if applied) does not break existing config entries (HA replays stored entry data through current schema).
- **Verify:** translations updated (`translations/en.json` step name to "Climate & Fans").
- **Verify (v4):** the step renders **fans-first / climate-last**. UI snapshot or test introspection of the form-schema ordering confirms the three toggles + humidity controls appear ABOVE the comfort-range pair + `CONF_CLIMATE_ENTITY`.
- **Verify (v4):** post-D7+D8 the step still contains the three climate-backstop fields — they are demoted, NOT removed.
- **Test:** `test_renamed_step_accepts_legacy_entries` — load an entry created under "climate" step name; reload via options flow; submit; no validation errors; all three climate-backstop fields still saved/restored correctly.
- **Test:** `test_renamed_step_field_ordering_fans_first` — introspect the form schema keys for the renamed step; assert that the three toggles + humidity fields precede `CONF_TARGET_TEMP_HEAT`/`CONF_TARGET_TEMP_COOL`/`CONF_CLIMATE_ENTITY` in the schema iteration order.
- **Live:** open an existing room's options flow; verify the step header reads "Climate & Fans"; verify fans-first ordering; verify comfort-range fields carry the new "Comfort Range — Low (°F)" / "Comfort Range — High (°F)" labels; verify `CONF_CLIMATE_ENTITY` appears at the bottom; existing values still saved/restored.

### D8 — Reframe + demote room-climate config; WIRE comfort-range low bound into score sensors (REVISED in v4)

**What:** The per-room HVAC/climate config in the renamed step is NOT redundant — it is the legitimate home for per-room "what temperature I'd actually like" (comfort range) and a useful zone-thermostat fallback. v4 REVERSES the v3 removal framing into a **demote + reframe + wire-in**:

- **`CONF_CLIMATE_ENTITY` — KEEP.** The `aggregation.py:3715-3725` zone-thermostat fallback is valued resilience. DEMOTE the form field to the bottom of the renamed step. NO code changes to the fallback. NO changes to `coordinator.py:803`, `config_flow.py:1666`/`:8481`, or `config_flow.py:7686-7704`.
- **`CONF_TARGET_TEMP_COOL` + `CONF_TARGET_TEMP_HEAT` — KEEP + RELABEL as comfort range [low, high].** `CONF_TARGET_TEMP_HEAT` becomes "Comfort Range — Low (°F)" (min comfortable temp); `CONF_TARGET_TEMP_COOL` becomes "Comfort Range — High (°F)" (max comfortable temp). NO new CONF keys.
- **THE FIX — WIRE BOTH BOUNDS into the score sensors.** Today `CONF_TARGET_TEMP_HEAT` is collected-but-never-read (Bug Class #53). Update `ComfortScoreSensor` and `EnergyEfficiencyScoreSensor` to grade against the comfort RANGE: in-range = no temperature penalty; below low or above high = proportional penalty.
- **Dead-code hygiene retained.** Delete `should_coordinate_with_hvac` (`automation.py:1809-1824`, zero callers).

**Falsifiable invariant (D8-specific, v4):** I3 above — post-D8, both score sensors read BOTH comfort-range bounds; the climate-entity fallback in `aggregation.py:3715-3725` is unchanged; no CONF key is collected-but-unread.

**Ordered steps (mirror as acceptance criteria below):**

1. **Step 1 — Delete `should_coordinate_with_hvac` (dead code).**
   - Delete the method body at `automation.py:1809-1824`. Confirm zero callers (grep + graphify).
   - Drop any now-unused imports inside the method's import block.
   - **No CONF changes in this step.**

2. **Step 2 — RELABEL the comfort-range form fields.**
   - In `config_flow.py::async_step_climate` (`:1718-…`) — change the human label / help text for `CONF_TARGET_TEMP_HEAT` to "Comfort Range — Low (°F)" and `CONF_TARGET_TEMP_COOL` to "Comfort Range — High (°F)". Field key + storage key UNCHANGED (CONF identifiers stay the same).
   - Same in the options-flow mirror (`:7680-…`).
   - Add the cross-field validator: reject submit if `target_temp_heat > target_temp_cool` (inverted comfort range). `low == high` is legal.
   - Update `translations/en.json` for the two field labels + help text.

3. **Step 3 — DEMOTE `CONF_CLIMATE_ENTITY` + the comfort-range pair to the BOTTOM of the renamed step.**
   - Reorder the form schema in `async_step_climate` so that toggles + humidity-fan fields + wet-room + collapsed advanced section render BEFORE the comfort-range pair, and `CONF_CLIMATE_ENTITY` renders LAST.
   - Same in the options-flow mirror.
   - Optionally wrap the three demoted fields in `section("HVAC and Comfort Range", {"collapsed": False})` for visual demotion (operator preference; reviewer cosmetic).
   - **NO field deletions. NO logic changes to the fallback at `aggregation.py:3715-3725`.**

4. **Step 4 — WIRE the comfort-range LOW bound into `ComfortScoreSensor`.**
   - Refactor `ComfortScoreSensor._get_setpoint` (`sensor.py:1287-1291`) into `_get_comfort_range` returning `(low: float, high: float)`. Read BOTH `CONF_TARGET_TEMP_HEAT` and `CONF_TARGET_TEMP_COOL` from `{**entry.data, **entry.options}`. Defaults: low = existing `DEFAULT_TARGET_TEMP_HEAT`, high = existing `DEFAULT_TARGET_TEMP_COOL` (or a single module-level `DEFAULT_COMFORT_RANGE_LOW`/`HIGH` pair if cleaner — open question Q10).
   - Update `native_value` (`sensor.py:1293-1323`): temperature component becomes:
     - if `low ≤ temp ≤ high` → `temp_score = 100` (in-range, no penalty)
     - elif `temp < low` → `temp_score = max(0, 100 - (low - temp) × 10)` (too cold; same 10 pts/°F slope as today's single-setpoint formula)
     - elif `temp > high` → `temp_score = max(0, 100 - (temp - high) × 10)` (too warm; same slope)
     - Defensive: if `low > high` (validator slipped), fall back to `min(low, high)` as low and `max(low, high)` as high — never crash.
   - Update `extra_state_attributes` (`sensor.py:1346-1356`): replace `"setpoint": setpoint` with `"comfort_range_low": low` + `"comfort_range_high": high` to avoid stale single-setpoint dashboard semantics.

5. **Step 5 — WIRE the comfort-range LOW bound into `EnergyEfficiencyScoreSensor`.**
   - Same refactor on `EnergyEfficiencyScoreSensor._get_setpoint` (`sensor.py:1395-1399`) → `_get_comfort_range`. Same bi-directional scoring rule applied to its fallback temperature branch (the "no HVAC data" path noted at `sensor.py:1364-1365`: "Within 2 F of target = 90, within 5 F = 70, else 50" — generalized to "within `[low, high]` = 90; within `[low - 3, high + 3]` = 70; else 50", or pick the closer bound for the deviation).
   - Update its `extra_state_attributes` analogously.

**Cross-deliverable notes:**
- D8 makes D7's rename land cleanly: "Climate & Fans" reflects the surviving climate aspect AND the demoted fans-first ordering.
- D8 is INDEPENDENT of D1-D4 humidity-fan logic — none of the relabeled config keys touch the humidity-fan path. D8's risk surface is the score sensors (I3) + form-ordering correctness.
- D8 ships in the same cycle as D1-D7 (single Tier-3 ship).
- **Operator-side config follow-up (NOT a deliverable):** the zone "Entertainment + Master Suite" lacks explicit `CONF_ZONE_THERMOSTAT`; operator will set it to `climate.thermostat_bryant_wifi_studyb_zone_1` separately. The "Outside" zone legitimately has no HVAC.

**Acceptance criteria:**
- **Verify (Step 1):** `grep -rn "should_coordinate_with_hvac" custom_components/` → zero hits.
- **Verify (Step 2):** form field labels read "Comfort Range — Low (°F)" / "Comfort Range — High (°F)" in both create and options flows; help text updated; CONF keys unchanged.
- **Verify (Step 2):** form-submit validator rejects inverted ranges (`target_temp_heat > target_temp_cool`).
- **Verify (Step 3):** form schema ordering in `async_step_climate` + options mirror places the three climate-backstop fields LAST.
- **Verify (Step 3, NO-CHANGE evidence):** `git diff aggregation.py::_get_zone_thermostat` shows zero semantic change (only context lines or none). Same for `coordinator.py::_get_builtin_target_entities`, `config_flow.py::_collect_entities` (both flows), and the `config_flow.py:7686-7704` climate→zone-thermostat auto-bootstrap handler.
- **Verify (Steps 4-5):** both `ComfortScoreSensor` and `EnergyEfficiencyScoreSensor` read BOTH `CONF_TARGET_TEMP_HEAT` and `CONF_TARGET_TEMP_COOL`. `grep -n "CONF_TARGET_TEMP_HEAT" sensor.py` returns hits in both scorers. No CONF key is collected-but-unread post-D8.
- **Verify (Steps 4-5):** scorer `extra_state_attributes` exposes `"comfort_range_low"` + `"comfort_range_high"` (not a single `"setpoint"`).
- **Test:** `test_d8_dead_method_removed` — `hasattr(RoomAutomation, "should_coordinate_with_hvac") is False`.
- **Test:** `test_d8_comfort_range_relabel_persists` — load an entry with `target_temp_heat=68, target_temp_cool=76`; options-flow surfaces both fields under the new labels; submit unchanged; values round-trip.
- **Test:** `test_d8_form_rejects_inverted_comfort_range` — submit `target_temp_heat=78, target_temp_cool=72` → form error.
- **Test:** `test_d8_form_accepts_degenerate_equal_range` — submit `target_temp_heat=74, target_temp_cool=74` → accepted (degenerate range, zero in-range band, scorer still well-defined).
- **Test:** `test_d8_comfort_score_in_range_zero_penalty` — config `low=70, high=76`, temp=73 → temp_score=100 (in-range).
- **Test:** `test_d8_comfort_score_penalizes_too_cold` — config `low=70, high=76`, temp=65 → temp_score = max(0, 100 - (70 - 65) × 10) = 50. **This is the C-mutation anchor test:** if the build neuters the low-bound branch (e.g. only penalizes above high), this test FAILS.
- **Test:** `test_d8_comfort_score_penalizes_too_warm` — config `low=70, high=76`, temp=81 → temp_score = max(0, 100 - (81 - 76) × 10) = 50. (Sanity: high-bound path still works.)
- **Test:** `test_d8_comfort_score_symmetric_penalty_both_bounds` — `temp_score(low=70, high=76, temp=65) == temp_score(low=70, high=76, temp=81)` (both 5°F outside, both 50).
- **Test:** `test_d8_comfort_score_defensive_inverted_range_does_not_crash` — config `low=78, high=70` (would-be inverted; bypass validator in test) → scorer returns a numeric value without raising; internally normalizes via `min`/`max`.
- **Test:** `test_d8_comfort_score_missing_bound_uses_default` — config has `target_temp_cool=76` but no `target_temp_heat` (older legacy entry) → scorer uses module-level `DEFAULT_TARGET_TEMP_HEAT` for the low bound, scorer well-defined.
- **Test:** `test_d8_energy_efficiency_score_uses_comfort_range` — analogous to ComfortScore; both bounds consumed by the fallback temperature branch when zone data is unavailable.
- **Test:** `test_d8_energy_efficiency_score_penalizes_too_cold` — analogous to ComfortScore C-mutation anchor; low-bound branch tested independently.
- **Test:** `test_d8_score_sensor_attrs_expose_both_bounds` — `extra_state_attributes` includes `"comfort_range_low"` + `"comfort_range_high"`; does NOT include legacy single `"setpoint"` key.
- **Test:** `test_d8_climate_entity_fallback_unchanged` — set up a zone with NO `CONF_ZONE_THERMOSTAT` but a room in it with `CONF_CLIMATE_ENTITY=climate.foo`; `aggregation.py::_get_zone_thermostat` returns `climate.foo` (proves the fallback is byte-for-byte preserved).
- **Test:** `test_d8_collected_but_unread_audit` — AST inspection: every CONF key in the renamed step's schema is read by at least one production code site (no Bug Class #53 regressions).
- **Live:** post-deploy, open any room's options flow → step header reads "Climate & Fans"; fans render at top; comfort-range fields render at bottom under the new labels; `CONF_CLIMATE_ENTITY` selector is the last field. Change `CONF_TARGET_TEMP_HEAT` from default to 71; within one coordinator cycle the room's `comfort_score` sensor `extra_state_attributes.comfort_range_low` reads `71`.
- **Live:** ComfortScoreSensor + EnergyEfficiencyScoreSensor for rooms whose current temp is below `CONF_TARGET_TEMP_HEAT` show a non-100 temperature component (proves the low-bound is actually grading, not silently ignored).
- **Live:** zone HVAC continues to operate (`hvac_zones.py` discovery + `aggregation.py` zone-thermostat resolution) unchanged. For any zone relying on the `CONF_CLIMATE_ENTITY` fallback (today: "Outside", "Entertainment + Master Suite" pre-operator-fix), `aggregation.py::_get_zone_thermostat` still returns the room-climate-entity. HA log search for any new "missing thermostat" warning attributable to URA → ZERO hits.
- **Live:** HA log search for `should_coordinate_with_hvac` post-restart → ZERO hits.

---

## Plan completion tracking

**In scope (this cycle, single Tier-3 ship):** D1, D2, D3, D4, D5, D6, D7, **D8 (v4 — reframe + demote + wire, NOT removal)** — all EIGHT MUST ship together.
- D1 alone leaves the system temporarily worse (loses HVAC-coord humidity path with no replacement for the orphan-eliminating reframing).
- D2-D5 alone are non-deliverable without D1 (would entrench dual-controller split).
- D6 (room-device surfaces) is required to make toggle #3 + the new humidity behavior discoverable per-room. Shipping without D6 leaves the operator with options-flow-only visibility.
- D7 (rename to "Climate & Fans") + D8 (demote + relabel + wire) are paired — the rename reflects the post-D8 fans-first / climate-last reality.
- **D8 (v4)** is independent of D1-D4 but folded in to clean up the form ordering and fix the collected-but-unread `CONF_TARGET_TEMP_HEAT` (Bug Class #53). NO config removal, NO PRE-REMOVAL GATE.

**Explicitly deferred (account here, do NOT silently drop):**

- **`ROOM_TYPE_TOILET` / `ROOM_TYPE_LAUNDRY` constants.** D4 uses `CONF_WET_ROOM` operator opt-in instead. Adding new room-type constants requires updating `ROOM_TYPE_TIMEOUTS` (`const.py:675`), `ROOM_TYPE_FAILSAFE_DURATIONS` (`:700`), `ROOM_TYPE_RECHECK_FACTOR` (`:448`), and the config-flow dropdown. Out of scope. Tracked: backlog memo "bathroom exhaust intelligence follow-ups."
- **HVAC supervisory awareness of exhaust state (relax conditioning while venting).** Operator: "revisit only if a powerful exhaust proves to fight HVAC." Tracked: backlog.
- ~~**Moving / removing `CONF_CLIMATE_ENTITY` + `CONF_TARGET_TEMP_COOL/HEAT` from the renamed Fans step.**~~ **v3: PROMOTED to D8 (removal). v4: REVERSED — fields KEPT, demoted, relabeled, wired. No longer a removal.**
- **Operator-side config fix for zone "Entertainment + Master Suite" missing `CONF_ZONE_THERMOSTAT`.** Operator will set to `climate.thermostat_bryant_wifi_studyb_zone_1` outside this cycle. Not a code deliverable.
- **Per-room humidity-fan diagnostic attributes** beyond the two D6 binary sensors (e.g. `trigger_reason`, `current_ema_baseline`, `presence_runtime_remaining_s` as sensor attributes). Useful but not load-bearing for I1. Tracked: candidate hygiene v+1.
- **Pre-existing dead path at `automation.py:1509` / `hvac_fans.py:308`** noted in `_apply_night_trust_speed_cap` comment (`policy=off` when HVAC manages fans). Comfort-only, orthogonal. Not touched.
- **`HVACFanControlSwitch` (`switch.py:3060`) label refinement** to "HVAC-Managed Fans (Global)". Optional cosmetic; ship only if zero risk to existing dashboards. If skipped, tracked as cosmetic backlog.
- **Comfort-slider persistence + read-path.** v3 D8 Step-2 contemplated routing setpoint reads through `ComfortTempMax`/`ComfortTempMin` Numbers. v4 D8 does NOT depend on comfort sliders — the comfort range lives directly on the room config entry. Comfort-slider work remains tracked separately under the Optimization Coordinator (per MEMORY.md "Comfort sliders → Optimization Coordinator").

---

## Risks + open questions for operator (surface BEFORE build)

1. **Q1 — Spike re-arming policy.** Settled per operator: **clear EMA + sample state on fan-off.** Document here for D-reviewer reference.
2. **Q2 — EMA warm-up gate length.** Spec uses `α_s / 2` (≈22 min at α=2700s) as warm-up. Operator confirm? Tighter (`α_s / 4`) means earlier spike-arm but noisier baseline. Reviewer A may revise.
3. **Q3 — Baseline-relative OFF threshold.** Spec uses `Δ_off = Δ / 2`. Operator confirm? Or fixed pp value?
4. **Q4 — Toggle #3 OFF semantics on a running fan.** Settled per operator: **leave running, no force-off, no anchor wipe.** Operator owns the fan manually until re-enabled.
5. **Q5 — Migration determinism for `_humidity_on_since` at upgrade.** D1 relies on reload-mid-cycle anchor seeding (`automation.py:1731-1736`). B-review verifies `_humidity_on_since` is None at first eval post-upgrade in all reachable paths. If any setup path pre-populates it, add explicit migration code in the build.
6. **Q6 — `CONF_WET_ROOM` default for `ROOM_TYPE_UTILITY`.** Spec defaults `False` (operator opts in; utility rooms are not always laundry — mechanical closets exist). Operator confirm safer default?
7. **Q7 — Sleep-exemption blast radius.** D4 bypasses `FAN_SLEEP_OFF` for wet-rooms. Confirm no other path silently turns off humidity fans during sleep. Reviewer D enumerates; flag now so operator confirms intent.
8. **Q8 — D6 entity-id stability for renamed comfort sensors.** Recommended: keep entity_ids stable, only update `_attr_name`. If operator wants entity_ids renamed too, that is a breaking change for dashboards/automations — flag now.
9. **Q9 — Optional `HVACFanControlSwitch` label refinement (D6).** Ship cosmetic relabel or defer to hygiene? Currently planned as optional within D6.
10. **Q10 (v4 REVISED) — D8 default constants for the comfort-range bounds.** Today `DEFAULT_TARGET_TEMP_HEAT` and `DEFAULT_TARGET_TEMP_COOL` exist (used as form defaults). v4 D8 scorers fall back to these when the entry omits a bound. Operator confirm: keep the existing two `DEFAULT_TARGET_TEMP_*` constants AS-IS, OR introduce a new pair `DEFAULT_COMFORT_RANGE_LOW`/`HIGH` for semantic clarity (rename-only, same values)? Recommendation: keep existing names to minimize churn; rename is optional cosmetic.
11. **Q11 (v4 NEW) — D8 form-grouping for the demoted climate-backstop fields.** Three options for visual demotion: (a) just place them last in the schema, no grouping; (b) wrap in an expanded `section("HVAC and Comfort Range")`; (c) wrap in a collapsed `section("HVAC and Comfort Range", {"collapsed": True})`. Operator preference?
12. **Q12 (v4 NEW) — Optimization Coordinator coupling.** v4 D8 wires the comfort range into the two score sensors. The Optimization Coordinator's Comfort dimension (per MEMORY.md) will eventually consume these scores. Should v4 D8 also surface the comfort range as a coordinator-readable signal (e.g. an attribute on a per-room sensor) for the Optimization Coordinator to consume directly, or defer that wiring to the Optimization Coordinator's own cycle? Recommendation: defer — D8's scope is scorer correctness, not OC integration.

---

## Suggested cycle naming

`v?.?.?` — single-version ship, all EIGHT deliverables. Tier 3 review (3 framings + adversarial-completeness D). Budget 1 build + 1-2 fix-up rounds, proportional to v4.6.2.x history in this area. Operator pre-deploy checkpoint mandatory (Tier 3). **v4 D8 has no PRE-REMOVAL GATE** (nothing is removed beyond the dead method) — the operator pre-deploy checkpoint focuses on the comfort-range scoring correctness (both bounds wired, symmetric penalty, defensive on inverted/degenerate configs) and the fans-first form ordering.
