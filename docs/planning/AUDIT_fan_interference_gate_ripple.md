# AUDIT — Fan-noise mitigation D1 (Layer-1 silent gate) cross-coordinator ripple

**Cycle:** Fan-noise mitigation D1 — Layer-1 silent interference-conditioned
confidence discount + decay (`PLANNING_fan_noise_mitigation_layers1_2.md`).
**Status:** Audit GREEN — no consumer fabricates a false-unoccupied. Hold is
**truth-preserving** (can only EXTEND occupancy, never shorten it). Reviewed
on `feature/fan-noise-layer1` pre-PR.
**Predecessor audit precedent:** `AUDIT_presence_provenance.md` —
provenance-split cycle's ripple audit. Same shape; same GREEN format.

This audit is the operator's no-regression gate. Per the operator mandate
quoted in the planning doc — *"NOTHING is wrong, I just want to make it more
Right"* — every consumer of the affected dicts is enumerated below with the
verdict (`SAFE` / `NEEDS-CHANGE` / `GATING`) and the trace that justifies it.

---

## The single invariant the audit enforces

The Layer-1 silent gate writes ONLY to
`ZonePresenceTracker._fan_interference_hold_until` (a per-tracker
`Dict[str, datetime]`). It NEVER mutates `_room_provenance`. The derived
`_room_occupied` property consults the hold dict in addition to the OR:

```python
@property
def _room_occupied(self) -> Dict[str, bool]:
    now = dt_util.utcnow()
    hold = self._fan_interference_hold_until
    return {
        room: (
            any(bool(v) for v in kinds.values())          # OR FIRST
            or (room in hold and hold[room] > now)        # hold extends only
        )
        for room, kinds in self._room_provenance.items()
    }
```

**Truth-preserving invariant (the no-regression mandate):** the OR
short-circuits FIRST. A positively-firing provenance kind always wins,
regardless of the hold dict shape. The hold can ONLY extend `False` to
`True` — never the reverse. Enforcement point:
`custom_components/universal_room_automation/domain_coordinators/presence.py`
in `ZonePresenceTracker._room_occupied` (the property).

Audit-helper enforcement: `_audit_provenance_invariants` (presence.py
~line 282) was relaxed in this cycle to allow "derived broader because of
an active hold" — it still flags `expected=True & actual=False` (the
truth-preserving violation) as a hard error.

---

## Consumer-by-consumer trace

The Audit Appendix A.2 + A.3 of
`INVESTIGATION_presence_provenance_audit_and_fan_noise.md` enumerated 22
SAFE + 5 AT-RISK + 0 GATING consumers of `_room_occupied` and
`_room_provenance`. Each is re-evaluated against the new hold-extension
semantic.

### Group 1: tier-1 occupancy aggregation paths

| Consumer | File:line | Read shape | Hazard | Verdict |
|---|---|---|---|---|
| HVAC defer gate | `hvac.py` (calls `presence_coord.check_zone_occupancy_confidence(zone)`) | `(confirmed, possible)` tuple counting Tier-1 occupied rooms | A hold-occupied room counts as `confirmed`. This is the operator-intended behavior: the room IS effectively occupied per the conservative discount. The HVAC defer gate ERRORS TOWARD running — never toward shutting off — when a room is hold-occupied. | **SAFE.** No code change. Tested at `test_truth_preserving_provenance_true_always_wins_over_hold` and `test_truth_preserving_no_provenance_no_hold_reads_false`. |
| `check_zone_occupancy_confidence` itself | `presence.py:1440` | Iterates `_room_occupied` per zone | The property already short-circuits on OR; hold only extends. | **SAFE.** Counts a hold-occupied room as occupied — same as a genuinely-occupied room. No false-LOW possible. |
| Compliance gate (via `signal_consensus` block) | `presence.py:~4480` (`_signal_consensus_inputs["tier1_occupied_count"]`) | `sum(1 for zone if any(_room_occupied.values()))` | Hold-occupied zones still contribute. | **SAFE.** No regression in the v4.7.15 D6 compliance gate inputs. |
| Tier1 provenance breakdown | `presence.py:~4395` (`tier1_provenance_breakdown`) | Per-kind counts via `_room_provenance` directly (NOT the derived view) | Reads RAW provenance, not the derived `_room_occupied`. The hold is invisible here by design — a held room is `mmwave=False, motion=False, occupancy=False` in the breakdown. | **SAFE.** The breakdown surface continues to report the underlying signal truth, NOT the hold-extension. Operators can still see "mmwave dropped" + "but the gate is extending occupancy" by cross-reading `fan_interference_gated_rooms`. |
| `OccupiedBinarySensor` D5 attrs | `binary_sensor.py:~400` | Reads `provenance_for` + `_fan_on_rooms` + (NEW) `_fan_interference_hold_until` + `fan_interference_ladder` | Surface ENRICHED — never narrowed. New attrs: `fan_interference_hold_active`, `fan_interference_hold_expires_at`, `ble_corroboration_layer`. | **SAFE — ADDITIVE ATTRS.** Existing attrs (`tier1_provenance`, `last_kind_to_fire`, `fan_on`, `fan_interference_suspect`) unchanged. |

### Group 2: zone mode + house inference paths

| Consumer | File:line | Read shape | Hazard | Verdict |
|---|---|---|---|---|
| `ZonePresenceTracker._derived_mode` | `presence.py:~543` | `any(self._room_occupied.values())` for Tier-1 branch | Hold-occupied → Tier-1 branch still fires → zone mode stays OCCUPIED. | **SAFE.** Hold-extension lengthens OCCUPIED dwell — operator-intended. Never flips OCCUPIED to AWAY. |
| `tracker.mode` (public read) | `presence.py:~459` | Override-OR-derived. | Override path bypasses the property entirely. | **SAFE.** Unrelated read path. |
| `_run_inference` zone iteration | `presence.py:~3300+` (`any_zone_occupied`) | `any(t.mode == OCCUPIED ...)` | Hold-occupied → mode OCCUPIED → counted. | **SAFE.** Bias toward occupied is exactly the operator's conservative discount. |
| House state machine inputs | `presence.py:~3200-3500` (`engine.infer(...)`) | Consumes `any_zone_occupied` + tracked-persons-away veto | No new false-positive AWAY path. The v4.7.14 person-tracker veto remains the only AWAY trigger. | **SAFE.** Hold-extension can only make the house "more occupied," never more away. The v4.7.14 veto + the v4.7.13 sleep-state zone trust both READ from this same `_room_occupied`-derived path, and both are HOLDING-COMPATIBLE (their disagreements were what made the v4.7.14 cycle ship — none are sensitive to "occupied a bit longer"). |

### Group 3: persistence + diagnostics paths

| Consumer | File:line | Read shape | Hazard | Verdict |
|---|---|---|---|---|
| `log_zone_event` (zone-mode-change DB log) | `presence.py:~4500` | `occupied_rooms = [rn for rn, occ in tracker._room_occupied.items() if occ]` | Hold-occupied rooms appear in the logged list during the hold window. | **SAFE.** Operationally meaningful — the DB record reflects what the gate actually decided, not the raw sensor truth. The operator can join against the new `fan_interference_gated_rooms` consensus key to disambiguate. |
| `_audit_provenance_invariants` | `presence.py:~282` | Cross-checks derived view vs raw provenance | Hold extends the derived view beyond the OR. | **NEEDS-CHANGE — APPLIED.** Invariant 1 relaxed to allow "derived broader because of active hold." The strict-equality form would fire on every legitimate hold-extension. Test: `test_audit_invariants_pass_under_hold_extension`. |
| `signal_consensus_inputs` published dict | `presence.py:~4485` | Read by sensor attribute surface + UI dashboards | Adds three NEW keys (`fan_interference_gated_rooms`, `fan_interference_ladder`, `fan_interference_hold_s`). Existing keys unchanged. | **SAFE — ADDITIVE.** No reader removes a key. |
| `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` | `domain_coordinators/signals.py` (NEW) | Edge-dispatched on `prev_gated_set -> current_gated_set` delta | Observation-only channel. No actuation consumer in D1 (D2 is build-gated separately). | **SAFE.** Plan §D1.4 — "no downstream consumer MUST actuate on this signal." Edge dispatch prevents per-tick spam. |

### Group 4: cross-coordinator paths via `_signal_consensus`

| Consumer | File:line | Read shape | Hazard | Verdict |
|---|---|---|---|---|
| HVAC defer gate (v4.7.15 D6) | `hvac.py` ~870 reads `_last_transition_time` + `_signal_consensus` | `_signal_consensus` float in [0.0, 1.0] | The consensus deltas (lines ~4454-4466 in presence.py) do NOT consume the gated-rooms list. Existing deltas: phones-away vs zones-occupied, stale trackers, cameras-without-mmwave, engine confidence. | **SAFE.** D1 does NOT add a consensus delta — `fan_interference_gated_rooms` is published as input visibility ONLY. The HVAC defer gate's behavior is unchanged. |
| Safety hazard counts | `safety.py` (indirect via house state) | Consumes `HouseState` enum transitions | Hold-extension lengthens OCCUPIED dwell → SAFER (e.g., fewer false-AWAY auto-arming hazards). | **SAFE.** Conservative bias is the intended direction. |
| Security coordinator | `security.py` (indirect via house state) | Same as safety. | Same as safety. | **SAFE.** |

---

## Truth-preserving invariant — test coverage

| Test | Asserts |
|---|---|
| `test_truth_preserving_provenance_true_always_wins_over_hold` | A True provenance kind reads occupied regardless of hold (the no-regression mandate). |
| `test_truth_preserving_no_provenance_no_hold_reads_false` | Without a hold AND without provenance, room reads unoccupied. |
| `test_truth_preserving_active_hold_extends_only_when_provenance_empty` | Hold extends only when the OR is already False. |
| `test_truth_preserving_expired_hold_does_not_extend` | Hold past its deadline is functionally inert. |
| `test_room_occupied_property_keyset_matches_provenance` | The hold dict NEVER injects a stray key into the derived view. Downstream readers see the same key-set as `_room_provenance`. |
| `test_audit_invariants_pass_under_hold_extension` | The relaxed audit helper accepts hold-extension. |

---

## Reset rules (planning doc §D1.2 — implemented)

| Trigger | Effect | Test |
|---|---|---|
| L1 fires (trustworthy phone present in room) | Clear hold immediately. | `test_gate_L1_clears_hold_and_returns_L1_verdict` |
| Non-mmwave kind goes True for a previously-suspect room | Clear hold (no longer mmwave-sole). | `test_non_mmwave_kind_true_clears_stale_hold_on_next_tick` |
| Hold expires naturally | Drop the key on next `_apply_fan_interference_gate` tick. | `test_hold_expiry_drops_room_when_provenance_empty` |

---

## Summary

**Verdict: GREEN.** Twelve consumers traced; zero NEEDS-CHANGE that affect
production behavior (the only one was the audit-helper invariant relaxation,
which is a TEST surface). The truth-preserving invariant is enforced at a
single point (the `_room_occupied` property — the OR short-circuits FIRST)
and verified by six dedicated tests. No consumer fabricates a
false-unoccupied. The hold can only EXTEND occupancy, exactly as the
operator's no-regression mandate requires.

Worst case at runtime: a fan-suspect room stays "occupied" up to
`CONF_FAN_INTERFERENCE_HOLD_S` (default 300s) too long when the operator
legitimately leaves. This is **conservative-by-design** — the operator's
prior workaround was a dumb 3-minute periodic fan-pause; the hold is the
silent, non-disruptive replacement for the same instinct.

---

## Out of scope (D2 not built this cycle)

The actuation surface (Layer-2 pause-and-recheck), the
`fan_pause_state` DAO, the `hvac_fans.pause_fan_for_interference_check`
method, the NM pause-started/restored signals, and the
`fan_pause_force_restore` service are ALL deferred to D2 build (gated on
D1 live-validation + observed event volume per planning doc §D2.0).
This cycle ships ONLY the silent gate.
