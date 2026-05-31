# v4.7.15 — Universalize the Bug Class #48 Veto Helper

**Tier:** 2-DB (three parallel reviewers — to be dispatched before deploy)
**Predecessors shipped:** v4.7.13 (sleep-state zone aggregator fallback), v4.7.14 (away-state house-inference veto)
**Successor:** v4.7.16 — room-level veto + Bermuda-density weighting via `CONF_SCANNER_AREAS`
**Status:** built; awaiting review. **DO NOT DEPLOY YET.**

---

## 1. What changes for the operator

This cycle promotes the Bug-Class-#48 trust-hierarchy fix from two ad-hoc inline
implementations (v4.7.13 zone aggregator SLEEP, v4.7.14 house inference AWAY)
into a shared helper, then plugs it in at four more places: zone aggregator
non-sleep states, house inference WAKING transitions, GUEST exit, and HVAC
+ compliance defer gates driven by a new `signal_consensus` metric.

### New entities

- `sensor.ura_signal_consensus_confidence` — float 0.0-1.0 measuring **input
  agreement**, not state confidence. 1.0 = inputs in steady agreement; ≤0.6 means
  Bug-Class-#48-shape disagreement is active.
- `switch.ura_hvac_consensus_defer_gate` — default ON. When ON, HVAC defers
  preset writes when consensus < 0.5 AND the last house-state transition was < 30 s ago.
- `switch.ura_compliance_consensus_defer_gate` — default ON. When ON, compliance
  violation anomalies are suppressed when consensus < 0.6 sustained ≥ 60 s.

### New attributes on `sensor.ura_presence_house_state` (the rich canonical sensor)

- `signal_consensus` — mirrors the dedicated sensor's value.
- `signal_consensus_band` — decorative: `"high"` (≥0.85) / `"moderate"` (≥0.6) / `"low"` (≥0.3) / `"degraded"`.
- `signal_consensus_inputs` — snapshot of the 4 boolean disagreement contributors.
- `consensus_low_since` — ISO timestamp when consensus first dropped below 0.6 (or `null`).
- `last_veto_decision` — `{fired, confidence, reason, scope}` from the D1 shared helper.
- `wake_blocked_ticks` — count of SLEEP → WAKING transitions blocked by the D3 sustained-signal gate.

### Untouched, preserved

- `sensor.ura_house_state_confidence` — engine confidence (different dimension); entity-ID unchanged.
- `sensor.ura_presence_house_state` attribute `confidence` — engine confidence; unchanged.
- v4.7.13 zone aggregator Layer 2 (SLEEP) behaviour — unchanged.
- v4.7.14 house inference AWAY veto behaviour — unchanged (helper added in parallel; engine veto branch preserved).
- `SIGNAL_HOUSE_STATE_CHANGED` dispatcher payload shape `{old_state, new_state, trigger, confidence}` — unchanged.

---

## 2. HVAC defer behaviour — exact details

The gate has two phases — **engage** and **hold/release** — driven by an
internal latch `HVACCoordinator._d6_gate_engaged`.

**Engage** (latch flips `False → True`) when **both** are true:

- `presence._signal_consensus < 0.5`, **AND**
- last house-state transition < 30 s ago (read via `presence._last_transition_time`,
  which is updated by `_record_outcome` at the transition-accept block).

On engage, `_apply_house_state_presets()` skips the entire apply cycle with an
info-level log line
`"v4.7.15 D6: HVAC defer gate ENGAGED — consensus=X, secs_since_transition=Y"`,
increments `hvac._d6_deferrals_today`, and returns early.

**Hold / release** (asymmetric hysteresis). Once engaged, the gate STAYS engaged
on every subsequent tick — deferring all writes — until `consensus >= 0.7`.
Each held tick logs `"v4.7.15 D6: HVAC preset write deferred (hysteresis hold) — consensus=X < 0.7"`
and increments `_d6_deferrals_today`. When consensus recovers `>= 0.7`, the gate
DISENGAGES (latch flips `True → False`), logs
`"v4.7.15 D6: HVAC defer gate DISENGAGED — consensus=X recovered above 0.7"`,
and lets the preset apply run normally.

This asymmetric 0.5/0.7 design prevents a 0.45 ↔ 0.55 consensus oscillation
inside the 30s window from flipping the gate on/off as consensus crosses the
single threshold.

**What gets paused, specifically:**

- Per-zone preset assignment based on the `target_preset` for the current house state (away / home / sleep / vacation).
- v3.17.0 Zone Intelligence overrides (D1 vacancy, D5 duty cycle, D6 stale-failsafe).
- v4.2.2 zone entry-dwell checks.
- v4.7.13 sleep-state preset-flip suppression.
- The mode-restoration block (off → heat_cool) at the top of `_apply_house_state_presets` (deliberate — we don't want to act on mistrusted house state).

**What is NOT paused** (i.e., critical-event bypass):

- Safety-coordinator hazard paths (CO2, fire, smoke). Those run via the safety
  coordinator's own service-call paths, not through `_apply_house_state_presets`.
- Egress window pause (`_egress_manager.is_paused`) — that's a hard pause already.
- v4.7.7 AC Nudge / AC Reset — those run on their own decision loops.
- Fan controller (`hvac_fans.py`) — separate decision loop.

---

## 3. Compliance suppression behaviour — exact details

When **both** are true:

- `presence._signal_consensus < 0.6`, **AND**
- `presence._consensus_low_since` is non-None AND `now - _consensus_low_since >= 60 s`

…then `_emit_compliance_violation_anomaly()` returns early with an INFO log
line `"v4.7.15 D6: Compliance violation suppressed — consensus=X sustained for Ys"`.

The DB row is NOT written; the ActivityLogger emit is NOT fired.

**Important:** the existing 60 s dedup window inside the compliance flow
remains separate. Plan-side reviewer B is expected to verify the two 60 s
windows don't interlock badly.

---

## 4. Rollback procedure (no HA restart needed)

If post-deploy observation surfaces a regression:

1. **Disable the HVAC defer gate:**
   - Open HA → Settings → Devices → URA: HVAC Coordinator
   - Toggle `HVAC Consensus Defer Gate` OFF
   - HVAC reverts to v4.7.14 preset-write behaviour immediately.

2. **Disable the compliance defer gate:**
   - Open HA → Settings → Devices → URA: Coordinator Manager
   - Toggle `Compliance Consensus Defer Gate` OFF
   - Compliance violations resume at v4.7.14 cadence immediately.

3. D5 sensors are passive — they keep publishing values but nothing acts on
   them. No rollback needed for D5 alone.

4. D1-D4 are pure refactors with preserved behaviour. If a regression is
   isolated to D1-D4, full revert to v4.7.14 via
   `scripts/deploy.sh` rollback is the path.

Both gates re-read the toggle every call — no HA restart, no reload required.

---

## 5. Pre-deploy snapshots (capture before running deploy.sh)

```bash
# 1. Median house_state_log rows/hour over prior 72 h
sqlite3 /Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db \
  "SELECT COUNT(*) / 72.0 AS rph FROM house_state_log
   WHERE created_at >= datetime('now', '-72 hours');"

# 2. Median compliance_log rows/hour over prior 72 h
sqlite3 .../universal_room_automation.db \
  "SELECT COUNT(*) / 72.0 AS rph FROM compliance_log
   WHERE timestamp >= datetime('now', '-72 hours');"

# 3. Current sensor.ura_house_state_confidence value (steady-state ~0.85-0.95)
ha state get sensor.ura_house_state_confidence

# 4. Existence check (will be NEW after deploy)
ha state get sensor.ura_signal_consensus_confidence  # expect: not_found
```

Record these into the cycle's review doc so post-deploy comparison is possible.

---

## 6. Post-deploy live-validation checklist (within 1 h of restart)

Exact entity attribute probes:

- [ ] `sensor.ura_signal_consensus_confidence` exists, returns a float in `[0.0, 1.0]`.
- [ ] `sensor.ura_presence_house_state` attribute `signal_consensus` is the SAME number as the dedicated sensor's state (within rounding).
- [ ] `sensor.ura_presence_house_state` attribute `signal_consensus_band` is one of `"high" | "moderate" | "low" | "degraded"`.
- [ ] `sensor.ura_presence_house_state` attribute `last_veto_decision` is a dict with keys `{fired, confidence, reason, scope}`.
- [ ] `switch.ura_hvac_consensus_defer_gate` exists, is `on` (default).
- [ ] `switch.ura_compliance_consensus_defer_gate` exists, is `on` (default).
- [ ] At least one row in `house_state_log` with non-zero, NOT NULL `state` and `confidence` columns within 1 h of restart (payload-shape integrity check).
- [ ] No new ERROR-level log lines mentioning v4.7.15 in HA core log.

### Overnight observation (24 h workday-empty + sleep window)

- [ ] Zero `away → arriving → home_day → away` bounces during the empty-house window in `sensor.ura_coordinator_manager_last_activity`.
- [ ] During a ghost-presence event (phones away, cameras firing), `sensor.ura_signal_consensus_confidence` drops below 0.6 within one inference cycle.
- [ ] HVAC preset write count over the empty-house window drops ≥75% vs pre-deploy baseline.
- [ ] `sensor.ura_hvac_coordinator_compliance` attribute `d6_deferrals_today` increments by ≥1 over the window.
- [ ] Compliance violation row count in `compliance_log` drops ≥50% vs pre-deploy baseline.
- [ ] No false `SLEEP → WAKING` transitions in the SLEEP window despite perimeter-camera person blips.
- [ ] No single-frame `GUEST → HOME_*` flips logged.

---

## 7. Cross-cycle relationship

- **v4.7.14.1 (forgotten-phone hotfix, sibling)** plugs into D1 by extending Pattern A with additional carve-outs (`phone_left_behind`, STALE tracker). Build that sibling cycle re-uses the D1 helper signature as-shipped here.
- **v4.7.16 (room-level veto + scanner-density weighting, successor)** adds a new "room_occupancy" scope to the D1 helper and wires up sparse-room weighting via the existing `CONF_SCANNER_AREAS` infrastructure. The helper's fall-through behaviour (`fired=False` for unknown scopes) means v4.7.16 lands additively.
- See `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` for the full architectural arc.

---

## 8. The helper signature (load-bearing contract for v4.7.16)

```python
def should_veto_due_to_reliable_signals(
    self,
    *,
    reliable_signals: List[ReliableSignal],
    transient_signals: List[TransientSignal],
    state_context: Dict[str, Any],
) -> VetoDecision:
    ...
```

`state_context["scope"]` is the dispatch key. Patterns shipped today:

- `"house_inference"` (Pattern A, v4.7.14 AWAY veto)
- `"zone_aggregator"` (Pattern B SLEEP v4.7.13 / Pattern C non-sleep v4.7.15 D2)
- `"waking_transition"` (Pattern D, v4.7.15 D3 sustained-signal WAKING gate)
- `"guest_exit"` (Pattern E, v4.7.15 D3 GUEST exit persistence)

Unknown / unmatched scope returns `VetoDecision(fired=False, ...)` so adding a
new caller is a no-op until a matching pattern is added.

`VetoDecision` fields (frozen dataclass, four fields as shipped):
`fired: bool`, `confidence: float`, `reason: str`, `scope: str = ""`.

> **Future contract evolution (v4.7.15.1+).** v4.7.16 D3 records a `scope="room_level_weighted"` verdict
> for diagnostics only (per v4.7.16 plan §0.7). When v4.7.17+ flips that
> diagnostic to gating, `ReliableSignal` is expected to gain an optional
> `weight: float = 1.0` field and `VetoDecision` to gain an optional
> `defer_to_consensus: bool = False` flag so a Pattern F handler can
> express "weighted weight insufficient, fall back to multi-tier consensus."
> Until that cycle, calling the helper with `scope="room_level_weighted"`
> falls through to `VetoDecision(fired=False, ...)` — forward-compatible
> but not semantically meaningful.

---

## 9. Plan items NOT implemented in this cycle (intentional deferrals)

Per `docs/planning/PLANNING_v4.7.15_universalize_bug_class_48_veto.md` §4 (out of scope):

- Room-level veto via `CONF_SCANNER_AREAS` weighting → v4.7.16 D2-D4.
- Per-room `CONF_DISABLE_CAMERA_PRESENCE` opt-out → v4.7.16 D5 (operator-confirmed deferral).
- `sensor.ura_house_state_confidence` deprecation → withdrawn from roadmap per plan §14 D5.
- Frigate vs Protect durability audit → separate cycle.
- Camera motion (non-person) signal classification → separate cycle.

---

## 10. Known limitations

- The `D6 HVAC defer gate` engages when the last house-state transition was within 30 s AND consensus < 0.5. It stays engaged (defers writes) until consensus recovers >= 0.7 (asymmetric hysteresis upper threshold). If the system has been steady-state for hours and consensus suddenly drops, the gate will NOT engage — by design (the gate targets transition-driven disagreement; steady-state disagreement is a different shape and needs separate diagnosis).
- `signal_consensus` reads `_camera_occupied` and `_room_occupied` via private attribute access on zone trackers. If a future cycle refactors those dicts, the consensus calc must be updated in lockstep.
- `_first_positive_zone_occupied_since` resets to None on ANY `any_zone_occupied=False`. A brief False blip wipes accumulated sustained seconds — by design (per plan D3 acceptance).
- **Helper contract scope gap (v4.7.16 D3 diagnostic-only).** v4.7.16 D3 calls the helper with `scope="room_level_weighted"` for diagnostic purposes (per its own plan §0.7 — D3 is intentionally diagnostic-only until v4.7.17 flips it to gating). The v4.7.15 helper does NOT recognise that scope and falls through to `VetoDecision(fired=False, ...)`. Diagnostic recorder will log a constant-False signal for that scope until v4.7.17+ adds a Pattern F handler (plus the contract-evolution noted in §8). This is intentional cross-cycle sequencing, not a bug.
- **Boot-race in `hvac._apply_house_state_presets` D6 stale failsafe.** During cold boot, if HVAC's preset-apply tick fires before PresenceCoordinator is registered with `coordinator_manager.coordinators`, the call to `presence.check_zone_occupancy_confidence` falls back to `(0, 0)` and the failsafe forces `effective_preset='away'` for that one cycle. v4.7.14's behaviour was to use HVAC's local helper synchronously. The 5-15 second boot window where this matters is bounded by the next `_run` tick (typically 30-60 s later) and is the conservative direction.

---

## 11. Build manifest

Files changed (commit-by-commit):

- `custom_components/universal_room_automation/domain_coordinators/presence.py` — D1, D3, D4, D5
- `custom_components/universal_room_automation/aggregation.py` — D2
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — D4 caller rewire, D6 HVAC gate, D6 init fields
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` — D6 compliance gate
- `custom_components/universal_room_automation/sensor.py` — D5 dedicated sensor + mirror attributes + signal_consensus_band helper
- `custom_components/universal_room_automation/switch.py` — D6 HVACConsensusDeferGateSwitch + ComplianceConsensusDeferGateSwitch
- `custom_components/universal_room_automation/const.py` — VERSION bump
- `custom_components/universal_room_automation/manifest.json` — version bump
- `quality/tests/test_v4715_universalize_veto.py` — 67 tests (D1-D6 + sibling preservation)
- `docs/readmes/README_v4.7.15.md` — this file
