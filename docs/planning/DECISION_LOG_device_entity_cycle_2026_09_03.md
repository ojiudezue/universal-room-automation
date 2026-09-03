# Decision Log — Device/Entity De-fragmentation Cycle (2026-09-03)

Operator mandate: drive to completion at **Tier 2**, don't over-Tier; **final "mondo" orchestrator + live review** across all deliverables before the ship gate; **operator holds only the ship decision**; I make reasonable adjudications and log them here for audit at the ship gate.

Every autonomous call I make in this cycle is recorded below (newest last). At the ship gate I present this log + the mondo review + live validation.

## Adjudications

| # | Decision | Rationale | Reversible? |
|---|---|---|---|
| 1 | **Tier 2** for the cycle, NOT Tier 3 | Operator calibration; nesting/consolidation/naming/has_entity_name are low-risk (identifiers stable → no re-registration). | — |
| 2 | **De-fragmentation deliverable gets a hard acceptance gate** (entity_id + unique_id preserved, 0 new `_2`, entity count stays 4626, no orphans, live-registry verified) despite Tier 2 | The ownership migration is the one real `_2`/orphan hazard on a live 4626-entity system; the gate is the minimal safeguard, not Tier-3 ceremony. | — |
| 3 | **D4 naming = Option 3** (distinction from nesting; rooms untouched, no renames) | Operator-decided. Zero room-device churn; resolves the defect without cosmetic churn. | via config later |
| 4 | **`SECURITY-CENSUS-UNKNOWN-WIRE-1` → parked** (defer + measure) | Operator call: auto-lock is only as safe as the unknown-count FP/FN rate; measure first. Revive: measure FP/FN then wire. | yes (revive) |
| 5 | **`LAST-RESIDENT-EGRESS-ARM-1` → parked** (parsimony) | Operator call: existing all-away arm covers it; marginal gain (arm a few min earlier) doesn't pay for the ingredient risk + is gated on the ~0%-attach producer. Revive: producer lands + measured arm-lag gap. | yes (revive) |

| 6 | **De-frag confirmed a plain relocation (no migration hook)** | D0 registry probe: 17-entity migration set, **17 SAFE / 0 BLOCKED** — all unique_ids entry-independent, so re-homing the config_entry_id re-registers in place with no `_2` mint. Split counts matched the screenshots exactly. Downgrades D1 risk from MEDIUM to LOW-MEDIUM. | — |
| 7 | **Do NOT "clean up" the space in `..._person_oji udezue_next_room_accuracy`** | Literal space is SAFE as-is; any string change would mint a `_2`. Hands off during D2/D3. | — |
| 8 | **Delete both dead `coordinator_music_following` device records** (CM + PARENT, 0 entities each) | Retired identity, zero entities, safe. Via registry, not a code no-op. | irreversible — verified 0 entities first |

_(appended as the cycle proceeds — plan/review/build adjudications, fix-up calls, any scope trims)_

## Deliverables (from the plan, de-frag-led)
- **D0** — live registry probe: which entities are owned by the parent entry vs the CM entry (measure-before-build).
- **D1 (elevated)** — de-fragment coordinator devices: forward all coordinator platforms from the CM entry only; parent entry hosts only Whole House; delete the dead `URA: Music Following` device. **Hard acceptance gate (see #2).**
- **D2** — consolidate `_*_device_info()` helpers into `_devices.py`; kill inline dups (music-following 3×, NM 3×).
- **D3** — fix the model first-writer-wins race (`base.py` vs sensor helpers).
- **D-NEST** — restore device nesting via `dr.async_update_device(via_device_id=…)` (coordinators → CM → Whole House; zones → Whole House).
- **D5** — `has_entity_name` per-entity audit.
- **D6** — reload-safety (device-registry writes only; census-toggles precedent).

## Ship gate (what the operator sees)
1. This decision log (all adjudications).
2. The mondo cross-cutting review outcome.
3. Live post-deploy validation: device tree nests correctly, **0 `_2` entities, entity count 4626 preserved, no orphans**, coordinator devices single-entry-owned, no new "Error adding entity None", clean boot.
