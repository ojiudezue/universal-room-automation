# Deploy Runbook — Bug Class #48 Sprint (2026-05-31)

**4 cycles staged, ready for sequential deploy + live validation.**

| Cycle | Tip | Branch | Live-validation depends on |
|---|---|---|---|
| v4.7.14.1 | `0e942f1` | `feature/v4.7.14.1-forgotten-phone-hotfix` | Forgotten-phone scenario (face-IDed person, phone absent) |
| v4.7.15 | `c15e816` | `feature/v4.7.15-universalize-bug-class-48` | Workday signals (HVAC defer engages during disagreement) |
| v4.7.15.1 | TBD when builder returns | `feature/v4.7.15.1-pattern-a-consumes-v4-7-14-1` | Same as v4.7.15 (Pattern A diagnostic; sibling tests must pass) |
| v4.7.16 | `83667cc` | `feature/v4.7.16-room-veto-density` | Per-room BLE tier diagnostic; D3 verdict is diagnostic-only this cycle |

**Sprint link:** `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md`

---

## 0. Pre-flight checks (5 min)

```bash
# Verify branch tips
for b in feature/v4.7.14.1-forgotten-phone-hotfix \
         feature/v4.7.15-universalize-bug-class-48 \
         feature/v4.7.15.1-pattern-a-consumes-v4-7-14-1 \
         feature/v4.7.16-room-veto-density; do
  echo "$b → $(git rev-parse --short $b 2>/dev/null)"
done

# Run a full local test sweep against integration base
cd /tmp/ura-v4715-1-integration
PYTHONPATH=quality python3 -m pytest quality/tests/test_v4713* \
                                       quality/tests/test_v4714* \
                                       quality/tests/test_v4715* \
                                       quality/tests/test_v4716* -v | tail -20

# Confirm develop tip is clean
git checkout develop
git log --oneline -3
git status --short
```

Expected: develop at `16cf47b` (or wherever it was when sprint started; no unmerged feature work).

---

## 1. Deploy v4.7.14.1 (first — smallest blast radius)

**Why first.** Closes v4.7.14's forgotten-phone gap. Clean merge to develop. No upstream dependencies.

```bash
# Merge feature → develop
git checkout develop
git merge feature/v4.7.14.1-forgotten-phone-hotfix --no-ff -m "v4.7.14.1: merge to develop pre-deploy"

# Verify
git log --oneline -3

# Deploy
./scripts/deploy.sh 4.7.14.1 \
  "Forgotten-phone hotfix — close H1 (census_count), H2 (phone_left_behind), H3 (tracking_status STALE/LOST)" \
  "$(cat docs/readmes/README_v4.7.14.1.md | head -40)"
```

**Live validation.** After HACS install + HA restart:

```python
# Check installed version
ha_get_state("update.universal_room_automation_update",
             fields=["attributes"],
             attribute_keys=["installed_version"])
# Expect: "v4.7.14.1"

# Check sensor surfaces new attributes (raw + trusted)
ha_get_state("sensor.ura_presence_coordinator_presence_house_state",
             fields=["attributes"],
             attribute_keys=["tracked_persons_count",
                             "tracked_persons_count_trusted",
                             "all_tracked_persons_away",
                             "excluded_persons"])
# Expect: both counts present, excluded_persons dict (empty unless someone
# has phone_left_behind=on or tracking_status=STALE/LOST right now)
```

**Pass criteria.** Sensor attributes present. House state correct. **Wait for ONE morning departure event** (or any home → away transition) before deploying next cycle.

---

## 2. Deploy v4.7.15 (architectural backbone)

**Why second.** Ships the shared veto helper + signal_consensus + HVAC defer gate. v4.7.15.1 depends on it. v4.7.16 has forward-references to it.

```bash
# Merge feature → develop. Predicted conflict: __init__ field block at presence.py:~634
# Resolution: include both v4.7.14.1's _excluded_persons AND v4.7.15's 7 fields.
# Already verified in integration worktree; integration commit shows the resolution.
git merge feature/v4.7.15-universalize-bug-class-48 --no-ff -m "v4.7.15: merge to develop pre-deploy"

# If conflict appears, copy resolution from /tmp/ura-v4715-1-integration's d654114 commit
# (presence.py:625-665 region — keep both sets of __init__ fields)

# Deploy
./scripts/deploy.sh 4.7.15 \
  "Universalize Bug Class #48 veto helper across room/zone/house/coordinator layers" \
  "$(cat docs/readmes/README_v4.7.15.md | head -50)"
```

**Live validation.** After HACS install + HA restart:

```python
# Check installed version
ha_get_state("update.universal_room_automation_update",
             attribute_keys=["installed_version"])
# Expect: "v4.7.15"

# NEW sensor exists
ha_get_state("sensor.ura_signal_consensus_confidence",
             fields=["state", "attributes"])
# Expect: state = 0.0-1.0 float; attributes include signal_consensus_band

# NEW switches exist (default ON)
ha_get_state(["switch.ura_hvac_consensus_defer_gate",
              "switch.ura_compliance_consensus_defer_gate"],
             fields=["state"])
# Expect: both "on"

# Mirror attributes on rich sensor
ha_get_state("sensor.ura_presence_coordinator_presence_house_state",
             attribute_keys=["signal_consensus", "consensus_band",
                             "last_veto_decision", "wake_blocked_ticks"])
# Expect: all four populated

# Existing standalone confidence sensor UNCHANGED
ha_get_state("sensor.ura_house_state_confidence",
             fields=["state"])
# Expect: still ~0.95
```

**Pass criteria.** All new entities present + populating. Wait until first observable HVAC defer event (consensus dips during workday signal disagreement) OR ~1 hour of stable operation before next deploy.

---

## 3. Deploy v4.7.15.1 (Pattern A reconciliation)

**Why third.** Refactors Pattern A to consume v4.7.14.1's H1/H2/H3 surfaces. Reduces architectural debt before v4.7.16's room-level work piles on. Pure refactor — no behavior change expected.

```bash
# Merge feature → develop. v4.7.15.1 was built on top of integration base
# (develop + v4.7.14.1 + v4.7.15), so its commits already include the resolutions.
git merge feature/v4.7.15.1-pattern-a-consumes-v4-7-14-1 --no-ff -m "v4.7.15.1: merge to develop pre-deploy"

# Deploy
./scripts/deploy.sh 4.7.15.1 \
  "Pattern A refactor — consume v4.7.14.1 H1/H2/H3 surfaces; delete parallel diagnostic invocation; source-invariant updates" \
  "$(cat docs/readmes/README_v4.7.15.1.md | head -40)"
```

**Live validation.**

```python
# Check installed version
ha_get_state("update.universal_room_automation_update",
             attribute_keys=["installed_version"])
# Expect: "v4.7.15.1"

# last_veto_decision mirror should still populate (Pattern A wired correctly)
ha_get_state("sensor.ura_presence_coordinator_presence_house_state",
             attribute_keys=["last_veto_decision"])
# Expect: dict with fired/confidence/reason/scope, scope="house_inference"

# Zero behavioral regression — sensor states + house state inference unchanged
# Compare against v4.7.15 baseline:
#   - house state same value
#   - signal_consensus in same band
#   - excluded_persons same set
```

**Pass criteria.** No regressions vs v4.7.15 baseline. Pattern A reflected in `last_veto_decision`.

---

## 4. Deploy v4.7.16 (room-level diagnostic)

**Why last.** Biggest blast radius (touches config_flow, const, sensor, presence, person_coordinator). D3 ships diagnostic-only this cycle. Predicted const-import conflict at `presence.py:44` is trivial.

```bash
# Merge feature → develop. Predicted conflict: const import block at presence.py:44.
# Resolution: include both v4.7.14.1's TRACKING_STATUS_ACTIVE AND v4.7.16's ENTRY_TYPE_ROOM.
# Alphabetical order:
#   ENTRY_TYPE_ROOM,  # v4.7.16 D3, D4
#   TRACKING_STATUS_ACTIVE,
git merge feature/v4.7.16-room-veto-density --no-ff -m "v4.7.16: merge to develop pre-deploy"

# If presence.py:44 conflict appears, edit to keep BOTH imports in alphabetical order.
# Verified trivial via sandbox merge in integration worktree.

# Deploy
./scripts/deploy.sh 4.7.16 \
  "Room-level veto + BLE-tier weighting via existing CONF_SCANNER_AREAS; D3 ships diagnostic-only" \
  "$(cat docs/readmes/README_v4.7.16.md | head -40)"
```

**Live validation.**

```python
# Check installed version
ha_get_state("update.universal_room_automation_update",
             attribute_keys=["installed_version"])
# Expect: "v4.7.16"

# New per-room signal inventory sensors exist
ha_search_entities(query="signal_inventory", limit=30)
# Expect: one per configured room (e.g., sensor.ura_room_living_room_signal_inventory)

# Verify ble_tier classification on at least 3 rooms
ha_get_state(["sensor.ura_room_master_bedroom_signal_inventory",
              "sensor.ura_room_living_room_signal_inventory",
              "sensor.ura_room_kitchen_signal_inventory"],
             fields=["state", "attributes"],
             attribute_keys=["ble_tier", "has_mmwave", "has_pir",
                             "has_camera", "has_ble_fallback_room"])
# Expect: states are human-readable labels;
#         master_bedroom likely Tier 1 (own scanner via bed_presence_*)
#         living_room likely Tier 0 (no Shelly per earlier audit)
#         kitchen tier depends on configuration
```

**Pass criteria.** Per-room sensors populating. Ble_tier values match operator's mental model of which rooms have BLE coverage.

---

## 5. Post-sprint observability (next 24-48h)

Watch for:

- **Bryant compliance violations** — should drop to near-zero (HVAC defer + better presence tracking)
- **House state oscillations** — `sensor.ura_coordinator_manager_last_activity` history should show single clean transitions, not bounces
- **`signal_consensus` band** — typically `high` during steady state; drops to `moderate` or `low` only during real signal disagreement
- **`_v4716_zone_verdicts` diagnostic data** — accumulates over the week; informs v4.7.17 threshold calibration

## Rollback procedure (if something breaks)

Each cycle has its own rollback in its README. Generally:

```bash
# HACS install of prior version
# Or git revert <merge-commit-sha> + deploy as patch version

# Disable specific behaviors via switches:
# - switch.ura_hvac_consensus_defer_gate → off  (v4.7.15 D6)
# - switch.ura_compliance_consensus_defer_gate → off  (v4.7.15 D6)
# - select.ura_presence_coordinator_house_state_override → away/home_day  (master override)
```

## Known limitations carried into the sprint

- v4.7.16 D3 verdict is **diagnostic-only this cycle** (per its plan §0.7). The `room_level_weighted` scope falls through to `VetoDecision(False, 0.0, ...)`. Flipping D3 from diagnostic to gating is **v4.7.17**'s job, informed by 1 week of real diagnostic data.
- v4.7.17 will also reconcile dataclass shapes (`RoomSignal` / 3-valued `VetoVerdict` vs `ReliableSignal` / 4-field `VetoDecision`).
- Standalone `sensor.ura_house_state_confidence` deprecation candidate **withdrawn** (per investigation memo §6.5 final decision). Both confidence sensors stay.

## Cycle-by-cycle test commands

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/test_v4714_1_forgotten_phone_hotfix.py -v
PYTHONPATH=quality python3 -m pytest quality/tests/test_v4715_universalize_veto.py -v
PYTHONPATH=quality python3 -m pytest quality/tests/test_v4716_room_veto_density.py -v
# v4.7.15.1 test path TBD when builder returns
```

## Sprint exit criteria

- All 4 cycles deployed without regression
- v4.7.15.1 source invariants protect against future architectural drift
- v4.7.16 D3 starts producing diagnostic data for v4.7.17
- Operator has confidence in the v4.7.15 HVAC defer behavior across at least 2 workday signal-disagreement windows
- Bryant compliance violation rate post-sprint ≤ 10% of pre-sprint baseline

---

**Generated:** 2026-05-30 evening (sprint complete, awaiting next-morning deploy)
**Runs:** ~2 hours wall-clock if all 4 cycles deploy clean back-to-back (4 × 30 min including HA restart + observation window)
