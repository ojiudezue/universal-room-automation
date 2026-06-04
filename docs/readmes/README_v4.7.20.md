# v4.7.20 — Fan-noise mitigation Layer-1 (silent interference-conditioned hold + decay)

**Feature cycle (Tier-2-DB, three framing-disjoint reviews + fix-up).** Promotes
the v4.7.19 OBSERVATION-ONLY fan-interference diagnostic into an actual SILENT
gate: when a room is fan-interference-suspect, hold last-known occupancy under a
decay timer instead of dropping to unoccupied. No device actuation — the
fan-pause actuation rung (Layer-2) remains design-only and build-gated on this
going live. Reviews: A = correctness + state-machine invariants, B = async /
lifecycle / restart / cross-coordinator ripple, C = new surfaces + config
round-trip + test-fixture authority. 0 CRITICAL; all 6 HIGH fixed. Review docs:
`docs/reviews/code-review/fan_noise_layer1_review_{A,B,C}*.md`; ripple audit:
`docs/planning/AUDIT_fan_interference_gate_ripple.md`.

## The problem — observed interference wasn't yet acted on

v4.7.19 could SEE the classic fan-stirred-air false positive (mmwave trips on
moving air, no other Tier-1 kind agrees) and flagged the room as
`fan_interference_suspect` — but it changed nothing. A fan-driven mmwave never
goes quiet, so the room kept reading "occupied" off a single fooled sensor. The
operator's old fix was a dumb periodic fan-pause, which he found "disconcerting."

## The fix — a truth-preserving silent gate (D1)

When a room is fan-suspect (fan on + mmwave is the SOLE positive Tier-1 kind +
the 3-layer BLE ladder finds no corroboration), the gate holds last-known
occupancy under a decay timer rather than letting the room drop. Crucially the
hold is **truth-preserving** — it can only EXTEND occupancy, never shorten it:

- `ZonePresenceTracker._fan_interference_hold_until: Dict[str, datetime]` — a
  per-room hold expiry. The derived `_room_occupied` view is
  `any(provenance.values()) OR (room in hold and hold[room] > now)`. The
  provenance OR **short-circuits first**, so any positively-firing kind always
  wins regardless of the hold. Worst case across every downstream consumer
  (HVAC defer gate, compliance, house inference) is "a fan-suspect room stays
  occupied a bit too long" — never a false-unoccupied. Independently confirmed
  by two reviewers + the 12-consumer ripple audit (GREEN, upheld).
- `_audit_provenance_invariants` relaxed to allow hold-extension while still
  hard-flagging the only true regression shape (`expected=True & actual=False`).

### The 3-layer BLE corroboration ladder

Decides whether to trust a suspect mmwave before holding:
1. **L1 — room BLE present** (`is_room_direct_ble`): phone is HERE → trust, no
   hold needed. A positive L1 also CLEARS any stale hold (H-A1).
2. **L2 — adjacent configured BLE room present** (new `CONF_ADJACENT_ROOMS`):
   the drift case (a phone flipping interchangeably between neighbouring rooms)
   → lean occupied, hold under decay, do NOT pause.
3. **L3 — zone-wide BLE absence** (`tracker._ble_occupied` False): nobody in the
   zone → mmwave is almost certainly fan/pet interference → eligible to discount.
   The only layer that also rejects PETS.

Phone-left-behind persons are excluded from the BLE-corroboration denominator
(v4.7.14.1 H2 carve-out; fails OPEN when that sensor is disabled).

## New surfaces

| Surface | What |
|---|---|
| `CONF_ADJACENT_ROOMS` | Per-room neighbour list (SelectSelector, install + reconfigure). Blank → falls back to L1+L3, no crash. |
| `CONF_FAN_INTERFERENCE_HOLD_S` + `DEFAULT_FAN_INTERFERENCE_HOLD_S = 300` | Hold/decay duration (range 60–1800). |
| `number.FanInterferenceHoldNumber` | RestoreEntity slider on the Presence Coordinator device. Seeded from CM `entry.options` at init and mirrors operator changes back to options (URA-mirror pattern — survives backup-restore / fresh install). |
| `binary_sensor.<room>_occupied` attrs | `fan_interference_hold_active`, `fan_interference_hold_expires_at`, `ble_corroboration_layer`. |
| `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` | Edge-dispatched once on no-hold→hold (subscriber arrives with Layer-2). |

Kill switch: reuses the existing `D3_DIAGNOSTIC_ENABLED` — off drains all holds
and disables flagging + gating (H-A2).

## Fix-up (post-review)

| ID | Sev | Resolution |
|---|---|---|
| H-A1 | HIGH | L1 positive corroboration now clears a stale hold within one tick. |
| H-A2 | HIGH | Flipping `D3_DIAGNOSTIC_ENABLED` off drains every `_fan_interference_hold_until` so the property can't read a stranded hold. |
| H-A3 | HIGH | Lowering the duration re-clamps existing expiries to `min(existing, now+new)`. |
| B-H1 | HIGH | Hold duration seeded from CM `entry.options` at init + mirrored back on operator change (durable across restore). |
| B-H2 | HIGH | Signal/dispatcher imports hoisted to module top (out of a debug-swallowed `except`). |
| B-H3 | HIGH | `log_zone_event` tags hold-extended rooms `(hold)` so DB forensics distinguish them from real fires. |
| B-M1 | MED | Adjacency resolution cached (`_adjacency_cache`, rebuilt on discovery only) — O(1) per tick, no per-tick config-entry walk. |
| C1 | LOW | Hollow audit test rewritten to genuinely drive the violation case. |

7 LOW/MED deferred (all runtime-safe; see review docs' fix-up status).

## Files changed

| File | What |
|---|---|
| `domain_coordinators/presence.py` | `_fan_interference_hold_until` + `_apply_fan_interference_gate` (L1/L2/L3 ladder + reset rules) + truth-preserving `_room_occupied` + adjacency cache + options-seed + edge dispatch + `log_zone_event` hold-tag. |
| `number.py` | `FanInterferenceHoldNumber` (RestoreEntity + options mirror). |
| `binary_sensor.py` | hold/ladder attrs on `OccupiedBinarySensor`. |
| `config_flow.py` | `CONF_ADJACENT_ROOMS` selector (install + reconfigure). |
| `const.py` | `CONF_ADJACENT_ROOMS`, `CONF_FAN_INTERFERENCE_HOLD_S`, `DEFAULT_FAN_INTERFERENCE_HOLD_S`. |
| `domain_coordinators/signals.py` | `SIGNAL_FAN_INTERFERENCE_GATE_FIRED`. |
| `quality/tests/test_fan_interference_gate_layer1.py` | 22 tests (gate truth table, truth-preserving invariant, ladder, decay, CONF round-trip). |

## Migration

Additive CONF knobs only. **No DB migration.** Layer-2 (fan-pause actuation,
`fan_pause_state` DAO) is deferred.

## Live validation (post-restart)

1. **Gate present, silent:** `binary_sensor.<room>_occupied` carries
   `fan_interference_hold_active` / `ble_corroboration_layer`. No URA-attributable
   fan/climate state change from the gate (it does not actuate).
2. **Truth-preserving:** no log line matching `_room_occupied=False but
   any(_room_provenance)=True` (the audit's regression shape).
3. **Hold tunable durable:** set the `FanInterferenceHoldNumber`, restart, confirm
   the value persists (mirrored to entry.options, not reverted to 300).
4. **Clean logs:** zero ERROR matching `fan_interference | _fan_interference_hold`.

## Acceptance

```yaml
version: v4.7.20
hypotheses:
  - id: H1
    name: no_gate_errors
    description: |
      The Layer-1 fan-interference gate raises no ERROR-level logs. Covers the
      gate compute path, the BLE ladder, the decay/clear path, and the options
      seed/mirror. Any ERROR here is a regression in the gate or its lifecycle.
    query:
      kind: ha_log_count
      source: error_log
      search: "fan_interference"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
  - id: H2
    name: no_truth_preserving_violation
    description: |
      The truth-preserving invariant is never violated: no room ever reads
      _room_occupied=False while its provenance OR is True. The audit helper
      flags exactly this shape; it must never appear in logs. This is the
      no-false-unoccupied guarantee that protects the HVAC/compliance/safety
      ripple.
    query:
      kind: ha_log_count
      source: error_log
      search: "_room_occupied=False but"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```

## Rollback

HACS install v4.7.19 — removes the gate + hold and restores the
observation-only diagnostic. The hold dict is in-memory only and the new CONF
knobs are additive, so rollback is clean either direction; a lost hold simply
re-evaluates from live provenance.
