# PLANNING: Room-Tier Fan Manual-Off Cooldown (narrow fix)

**Date:** 2026-07-26
**Author:** ura-planner
**Cycle type:** Feature cycle (Tier 2 recommended; Tier 2-DB argued below and rejected)
**Trigger incident:** Jaya Bedroom comfort fan (`fan.fanswitch_treat_wifi_jayabedroom`) could not be manually turned off — re-armed within ~30s. Root-caused to the room-tier temperature-fan path having no manual-off detection / cooldown, while the HVAC-tier `FanController` does.

---

## Institutional context verified

### Greps run + results

Prior-art surface: manual-off cooldown / re-arm suppression / fan handshake.

- `manual_off_cooldown` — matches in:
  - `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py:71` — `RoomFanState.manual_off_cooldown_until: str = ""` (dataclass field; ISO datetime string)
  - `hvac_fans.py:207-217` — external-off detection (`is_on and not any(_is_entity_on)`) sets `now + timedelta(hours=1)`
  - `hvac_fans.py:222-228` — reverse: fan turned on during cooldown clears cooldown
  - `hvac_fans.py:172` — cleared on `turn_off_all_managed()`
  - `hvac_fans.py:389-397` — early-return in `_evaluate_temp_fan` while cooldown live
  - `domain_coordinators/presence_fan_recheck.py:413-414, 992-1014` — READER: `_fan_in_manual_cooldown` reads the HVAC cooldown as a veto for `_fan_pause`. **The recheck path only knows about the HVAC cooldown; a room-tier cooldown would be invisible to it unless surfaced somewhere both can read.**
- `_fan_vacancy_start` — room-tier already carries per-fan timing state on the `RoomAutomation` instance (`automation.py:252`, used at :1576-1582) — **REUSE this pattern** for the room-tier cooldown storage.
- `DEFAULT_FAN_MANUAL_OFF` / cooldown constant — **NO existing constant.** HVAC-tier hard-codes `timedelta(hours=1)` inline at `hvac_fans.py:211`. **NEW constant needed**; also promote the HVAC-tier inline literal to the same constant to keep the two paths in lockstep (per CLAUDE.md "Numbers Get Knobs").
- `CONF_FAN_MANUAL_OFF` — no matches. **NEW** if we choose the config-flow rung (see rung decision below).
- `_is_hvac_managing_fans` — `automation.py:2142-2160` (defer check), used at `automation.py:1557` (temp-fan) and `actuator_reconciler.py:778`.
- `discover_fans` — `hvac_fans.py:105-156` (builds `room_to_zone` from `self._zone_manager.zones[].rooms`).
- `async_discover_zones` — `hvac_zones.py:221-428` (populates `zone.rooms` from `zone_cfg[CONF_ZONE_ROOMS]` in the Zone Manager entry, resolving entry_ids → room names via `entry_id_to_room_name`).

### Prior planning docs consulted (filename + relevance)

- `docs/planning/project_v4_7_22_fan_recheck_mode2_live.md` (memory) — the Mode-2 BLE-gated fan-pause/recheck (presence.py + presence_fan_recheck.py). This is the reader of HVAC cooldown at `presence_fan_recheck.py:413`.
- `docs/planning/project_v4_7_20_fan_noise_layer1_live.md` (memory) — Layer-1 silent hold/decay for fan-noise mmWave. Sets up the two-tier fan-actuation topology this doc lives inside.
- `docs/planning/project_fan_noise_mmwave_mitigation_backlog.md` (memory) — the layered fan-noise design that motivated the HVAC handshake fields (`fan_recheck_suppress_until`) on `RoomFanState`.
- `docs/planning/project_v4_7_25_hvac_presence_timer_knobs_live.md` (memory) — precedent for the CONF/Number persistence pattern if we choose the entity rung.

### Memory bodies pulled

- HVAC fans + presence coordination bodies (Mode-2 pause, Layer-1 hold/decay) — informs the "invisible to presence_fan_recheck" risk when a NEW room-tier cooldown exists.
- Silent-actuator failure memo — reminded to check whether reconciliation could re-arm behind the cooldown (`actuator_reconciler.py:778` already respects `_is_hvac_managing_fans`, but reconciler for room-owned fans is a separate check; must verify it doesn't stomp the cooldown).

### Design docs read

- `docs/Coordinator/HVAC.md` — TBD-check for fan-controller section (skimmed for the `_room_fans` invariant).
- `docs/Coordinator/PRESENCE.md` — TBD-check for the fan-recheck subsection.

### Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/automation.py:1542-1696` — `handle_temperature_based_fan_control` (the buggy site).
- `custom_components/universal_room_automation/automation.py:2142-2160` — `_is_hvac_managing_fans`.
- `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py:1-450` — full `FanController` incl. `discover_fans`, `update`, `_evaluate_temp_fan`, `turn_off_all_managed`.
- `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py:220-428` — `async_discover_zones` (the "extra step" trace).
- `custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py:395-415, 990-1014` — reader of HVAC cooldown.

---

## The "extra step" — resolved

**Question:** Jaya has `hvac_coordination_enabled=True`, `climate_entity=climate.up_hallway_zone_2`, and configured fans. Why did room-tier own the fan (30s re-arm proves HVAC did NOT manage it)?

**Answer.** `FanController.discover_fans` (hvac_fans.py:105-156) does NOT read the room-level `CONF_CLIMATE_ENTITY` or `CONF_HVAC_COORDINATION_ENABLED`. It builds its room-to-zone mapping SOLELY from `self._zone_manager.zones[room_name].rooms` (hvac_fans.py:115-117). That list is populated in `ZoneManager.async_discover_zones` (hvac_zones.py:221-360) from the **Zone Manager config entry's `zones[<zone>][CONF_ZONE_ROOMS]`** (hvac_zones.py:270-282) — a list of ROOM ENTRY IDs resolved to room names via `entry_id_to_room_name` (hvac_zones.py:236-242, 274). A zone is only registered if `zone_cfg.get(CONF_ZONE_THERMOSTAT)` is truthy (hvac_zones.py:265-267).

Therefore a room is HVAC-fan-managed **only if all of these hold**:

1. The Zone Manager entry has a zone whose `CONF_ZONE_ROOMS` list contains this room's entry_id.
2. That zone has `CONF_ZONE_THERMOSTAT` set.
3. The HVAC domain coordinator is enabled and has run `discover_zones()` + `discover_fans()`.
4. The room's entry has non-empty `CONF_FANS`.

`_is_hvac_managing_fans` (automation.py:2142-2160) then checks `room in fan_controller._room_fans`. If ANY of the four conditions fails (including a transient "coordinator not yet initialized during boot"), `_is_hvac_managing_fans` returns False → the room-tier `handle_temperature_based_fan_control` path OWNS the fan and re-arms every ~30s room-coordinator tick, with no cooldown.

**Diagnosis for Jaya specifically (to confirm on live during build):** the per-room `CONF_CLIMATE_ENTITY = climate.up_hallway_zone_2` is a *display / room-tier polling* value; it does not add Jaya to Zone Manager's zone→rooms list. The most likely truth is that Jaya's room entry_id is NOT in any Zone Manager zone's `CONF_ZONE_ROOMS` list (or the zone that mentions it lacks a `CONF_ZONE_THERMOSTAT`). Verify with:

```
ssh ha "python3 -c 'import json, glob;
for p in glob.glob(\"/config/.storage/core.config_entries\"):
    d=json.load(open(p));
    for e in d[\"data\"][\"entries\"]:
        if e[\"domain\"]!=\"universal_room_automation\": continue
        et=e[\"data\"].get(\"entry_type\")
        if et==\"zone_manager\":
            print(\"ZM zones=\", list(e[\"data\"].get(\"zones\",{}).keys()) or list((e.get(\"options\") or {}).get(\"zones\",{}).keys()))
            print(json.dumps({**(e.get(\"data\") or {}), **(e.get(\"options\") or {})}.get(\"zones\", {}), indent=2))
'"
```

Then confirm whether Jaya's entry_id appears in any zone's `zone_rooms`. This confirmation is the **first live-validation step of the fix cycle** — required BEFORE building, because if Jaya IS wired into ZM and HVAC just failed to discover, the bug is different (HVAC discovery failure, not a lacuna in room-tier).

### Recommendation (see "Scope decision" below)

Both (i) make room-tier safe and (ii) surface the mismatch. Room-tier lacking a cooldown is a **latent hazard for every room** that ends up on the room-tier path — Jaya is only the first observation. A surface-only fix (make the wiring alert) would still leave the re-arm bug for legitimately-room-tier rooms (HVAC coordination OFF is a valid configuration). Fix room-tier (D1), then a small diagnostic sensor / debug log to make silent-mismatch discoverable (D2). Diagnostic is Tier 1 blast radius, folded into the same cycle.

---

## Deliverables

### D1: Room-tier manual-off cooldown (the fix)

Port the HVAC-tier manual-off cooldown pattern (hvac_fans.py:207-217, :389-397) to `RoomAutomation.handle_temperature_based_fan_control` (automation.py:1542-1696).

**Add to `RoomAutomation.__init__` (near automation.py:252 next to `_fan_vacancy_start`):**

```
self._fan_manual_off_until: datetime | None = None
```

Datetime object (not ISO string) — the room-tier already stores `_fan_vacancy_start` as a `datetime` (automation.py:1577). Match the existing pattern; the HVAC-tier stores ISO because `RoomFanState` is serialized/logged as attrs — the room-tier per-instance state has no such need.

**In `handle_temperature_based_fan_control` (automation.py:1542+), immediately after the `CONF_HVAC_COORDINATION_ENABLED` defer and BEFORE the sleep-policy block:**

1. **Detect external turn-off.** Track `_last_seen_any_fan_on` (bool) on the instance. On entry, if we PREVIOUSLY saw any fan ON but NOW all fans are OFF and we did NOT issue an off-call this cycle, set `_fan_manual_off_until = dt_util.now() + timedelta(seconds=cooldown_s)`. (Symmetric to hvac_fans.py:207-217.) Log INFO with room_name + until.
2. **Detect manual-on reversal.** If `_fan_manual_off_until` is set and any fan is now ON (and we didn't just turn it on), CLEAR the cooldown. Log INFO. (Symmetric to hvac_fans.py:222-228.)
3. **Skip activation while live.** Before evaluating `speed_pct` / issuing turn-ON, if `dt_util.now() < _fan_manual_off_until`, `return`. Do NOT block turn-OFFs — an operator manually killing a fan mid-cooldown must still take effect.
4. **Kill switch semantics.** `cooldown_s == 0` disables the cooldown (today's behavior). This is the mandatory kill switch — a bad interaction with some room configuration must be reversible without a rollback.
5. **Update `_last_seen_any_fan_on` at bottom of the method** so next tick has the correct baseline.

**Update `RoomFanState.manual_off_cooldown_until` in-place at hvac_fans.py:211** to use the same NEW constant (see D3) instead of the inline `timedelta(hours=1)`. This keeps the two paths in lockstep.

**Preserve the existing HVAC handshake.** The `_is_hvac_managing_fans()` early-return at automation.py:1557 stays FIRST. If HVAC is managing, room-tier does nothing including cooldown tracking — that's HVAC's job. Only the room-owned path grows a cooldown.

### D2: Silent-mismatch diagnostic

Add a small runtime WARN log (once per room per boot, not per-tick — reuse `_LOGGER.warning` gated by an instance flag) when:

- `CONF_HVAC_COORDINATION_ENABLED == True` AND
- `CONF_CLIMATE_ENTITY` is set AND
- `_is_hvac_managing_fans()` returned False on this room-tier fan-eval call AND
- The room has non-empty `CONF_FANS`.

Message: `"Room %s expects HVAC fan management (hvac_coordination_enabled=True, climate_entity=%s) but is not in HVAC fan_controller._room_fans — room-tier is owning fans. Check Zone Manager zone_rooms wiring."`

No new sensor / entity. This is a diagnostic log only — enough to surface the config gap when a future room hits the same trap.

### D3: Named constant + rung placement

**Constant:** `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S: Final = 3600` (seconds; 1h to match hvac_fans.py:211).

**Rung placement decision — per CLAUDE.md "Numbers Get Knobs":**

| Rung | Fit for this number? | Verdict |
|---|---|---|
| Module constant (`const.py`) | Safety cooldown; changing it means "operator wants shorter/longer manual-off memory." Should this require a code review? YES — the value protects manual actions from being clobbered by both tiers. A misconfigured 60s value re-creates the exact bug. Low-frequency legitimate tuning. | **RECOMMENDED.** |
| Config field (per-room, options flow) | Per-room variation isn't justified — the semantic is "how long does the operator want their manual action respected across the WHOLE house." Adding to per-room options creates 40 knobs to keep in sync. | Reject. |
| Number entity (dashboard) | Would let operator turn it on the dashboard — but this isn't a policy the operator legitimately tunes by observation (unlike drain targets). If the cooldown is wrong, the fan re-arms silently and the operator won't notice on a dashboard. | Reject. |

**Placement:** `const.py`, in the fan-defaults block near line 706 (`DEFAULT_FAN_VACANCY_HOLD`). Cross-reference from `hvac_fans.py:211` (import + replace inline literal). Kill-switch (`0 = disabled`) documented on the constant.

If operator later requests operator-tunability, the promotion path is: constant → CONF_ field in options flow (single global knob under the "coordinator manager" entry, not per-room). Don't pre-build.

### D4: Reconciler audit

`actuator_reconciler.py:778` already defers via `_is_hvac_managing_fans()`. Audit whether it has a symmetric room-tier path that could re-arm the fan during cooldown (reconcile-on-return). If yes, teach reconciler to respect `_fan_manual_off_until`. **Read-only audit deliverable** — if reconciler doesn't re-arm room-owned fans within the cooldown window, no code change; document the finding. If it does, small mirror check.

---

## Acceptance criteria

### D1

- **Verify:** With `fan_control_enabled=True`, `hvac_coordination_enabled` in the room-owned state (either `False` OR `True`-but-not-in-Zone-Manager), turning off a fan whose room temp is `> fan_temp_threshold` does NOT re-arm within the cooldown window. Confirm at ≥90 seconds post-off (3 room-coordinator ticks).
- **Verify:** After `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S` elapses, the fan CAN re-arm if temp still ≥ threshold. Confirm at cooldown_s + 60s (one more tick).
- **Verify:** Manually turning the fan back ON during the cooldown window clears the cooldown; a subsequent temp-driven off/on cycle behaves normally.
- **Verify (safety):** An operator manual-off call issued DURING an active cooldown still shuts the fan off (cooldown doesn't block off-paths).
- **Verify (kill switch):** Setting `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S = 0` restores pre-fix behavior (fan re-arms in ≤30s).
- **Verify (HVAC precedence):** For a room where `_is_hvac_managing_fans()` returns True, the room-tier cooldown code path is NOT reached (defer at automation.py:1557 fires first). The HVAC-tier cooldown at hvac_fans.py:389 handles that room.
- **Test:** `quality/tests/test_fan_manual_off_cooldown_room_tier.py::test_room_tier_cooldown_blocks_rearm`, `::test_room_tier_cooldown_expires`, `::test_manual_on_clears_cooldown`, `::test_kill_switch_zero`, `::test_hvac_managed_skips_room_tier_cooldown`.
- **Mutation-anchor test:** In `test_room_tier_cooldown_blocks_rearm`, replace the check `dt_util.now() < self._fan_manual_off_until` with `False` (bypass) — the test MUST fail. Restore. This proves the test actually exercises the load-bearing site (Tier 3 discipline even at Tier 2).
- **Live:** For Jaya specifically post-deploy: turn off `fan.fanswitch_treat_wifi_jayabedroom` at a moment when Jaya room temp reads > 78. Confirm at 5 min the fan is still off (state.last_changed unchanged). Confirm at cooldown+2min it can re-arm.

### D2

- **Verify:** Boot log carries the WARN once for any room matching the mismatch predicate.
- **Verify:** Log fires at most once per room per HA restart (grep count == unique-mismatched-room count).
- **Live:** Confirm Jaya WARN appears in `home-assistant.log` after next restart (assuming the "extra step" diagnosis is correct — if it doesn't appear, the trap is elsewhere and the diagnostic itself surfaces the misdiagnosis, which is the point).

### D3

- **Verify:** `const.py` defines `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S`; `hvac_fans.py:211` imports and uses it (no `timedelta(hours=1)` literal remains in either file for this purpose).
- **Test:** `test_hvac_and_room_tier_share_manual_off_constant` — asserts the imported value is the same in both call sites.

### D4

- **Verify:** Audit note in cycle README stating whether reconciler was found to re-arm room-owned fans during cooldown, and the mitigation (if any).

---

## Tier classification

**Recommended: Tier 2 (feature-cycle, two framing-disjoint reviews + live validation).**

Argument for Tier 2:
- Blast radius is bounded to the room-tier fan path + one HVAC-tier literal promotion.
- Presence↔HVAC seam involvement is limited: presence_fan_recheck.py reads HVAC cooldown but is NOT taught about the room-tier cooldown in this cycle (it doesn't need to be — the room-tier path handles rooms HVAC doesn't manage; `_fan_pause` for those rooms is a separate flow that already vetoes on `no_fan_on`).
- No DB, no signal payloads, no shared-primitive change, no cross-coordinator ripple beyond the audited defer point.

Argument AGAINST elevating to Tier 2-DB (CLAUDE.md standing policy — regression-prone via cross-coordinator ripple):
- The two systems ARE at the presence↔HVAC fan seam, but this cycle does NOT change the seam semantics — it fills a hole in the room-tier arm of the seam. The reader in presence_fan_recheck.py:413 remains correct (it only ever needed to know about HVAC-tier cooldown, because room-owned rooms fall through `_is_hvac_managing_fans` gating in `_fan_pause` upstream — verify this assumption in Review B).

**Elevation trigger for Tier 2-DB:** If Review A or B finds that presence_fan_recheck.py can attempt a `_fan_pause` on a room-tier-owned fan (and thus needs to know about the new room-tier cooldown), elevate to Tier 2-DB and add a shared-cooldown accessor. This is the natural on-ramp to DOC 2 (`PLANNING_fan_actuation_shared_layer.md`).

### Review framings (Tier 2)

- **Review A — correctness + edge cases:** Manual-off detection accuracy (external vs internally-issued off), cooldown expiry math, kill-switch bypass, HVAC-defer precedence, `is_sleep_mode_active` + fan-sleep-policy interaction with cooldown, per-tick state transitions, cold-boot (fans already off at boot with no history), `_last_seen_any_fan_on` seeding.
- **Review B — cross-coordinator + presence-fan-recheck integration:** Verify presence_fan_recheck.py:413 still behaves correctly for room-tier-owned rooms (does it ever `_fan_pause` a room whose HVAC cooldown is empty but where a room-tier cooldown would now apply?). Reconciler re-arm (D4). Restart persistence (cooldown is intentionally in-memory only; verify no observable regression on quick restart — matches HVAC-tier).

---

## Files changed (summary)

- `custom_components/universal_room_automation/const.py` — add `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S`.
- `custom_components/universal_room_automation/automation.py` — `__init__` new instance fields; `handle_temperature_based_fan_control` cooldown logic; D2 diagnostic log.
- `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` — replace inline `timedelta(hours=1)` at :211 with the constant (D3 lockstep).
- `quality/tests/test_fan_manual_off_cooldown_room_tier.py` — NEW.

## Files read-only audited

- `custom_components/universal_room_automation/actuator_reconciler.py` (~:778).
- `custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py` (:395-415, :990-1014).

---

## Open decisions for operator

1. **Cooldown value.** 1h to match HVAC-tier. Confirm.
2. **D2 diagnostic verbosity.** WARN once per boot per room, or DEBUG only? WARN recommended so the config gap doesn't stay hidden.
3. **Elevate to Tier 2-DB?** Default Tier 2 recommended. Elevate if operator judges the presence↔HVAC fan seam has bitten us enough recently to justify the third framing.
