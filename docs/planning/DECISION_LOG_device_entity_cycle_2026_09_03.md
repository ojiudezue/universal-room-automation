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

| 9 | **SCOPE-DOWN D2** — consolidate only the genuine duplicate-authoring (music_following 3 sites, notification_manager 3 sites) + the base.py model race; DEFER the full one-DeviceInfo-per-identity consolidation (100+ inline sites: hvac 38, CM 23, energy 22, presence 21) to a separate parked hygiene item | Plan-review found INV-2 was a 10× larger diff than estimated and it is NOT what causes the split (the split is the branch-forwarding, fixed by D1). Marginal-benefit + keeps the cycle Tier-2-sized. **This is a scope call I made — flagging for your audit.** | park (revive as hygiene cycle) |
| 10 | **`ReconcileHealthSensor` + `IntegrationHouseStateSensor` STAY on the INTEGRATION entry** | Both resolve to `(DOMAIN, "integration")` = Whole House (verified AST). The plan wrongly listed ReconcileHealthSensor as a migration target — moving it would MANUFACTURE the split defect on the one clean device. | — |
| 11 | **The 10 `aggregation.py`-hosted coordinator entities need a CM-side setup split, not a branch-move** | `async_setup_aggregation_sensors/_binary_sensors` hard-return on non-INTEGRATION entry_type, so the branch-move idiom can't reach them. Build must split a `async_setup_cm_hosted_aggregation_*` called from the CM entry. Higher-surface than the D0 estimate, still LOW-MED risk (unique_ids SAFE). | — |

| 12 | **Build fix-up dispatched** after 2 framing-disjoint build-reviews (A correctness+mutation, B lifecycle+setup-order) both FIX-REQUIRED | B1 (CRITICAL) binary-sensor class-name collision — CM grabbed the Whole-House SafetyAlert/SecurityAlert pair, orphaning the coordinator pair + making a NEW split; B2 (CRITICAL) HA sets up entries concurrently so the 8 per-person CM sensors skip every boot → `async_at_started`; B3 (HIGH) D-NEST cold-boot sweep for room/zone; A-HIGH-1 5 v460 tests unupdated; A-HIGH-2 the exactly-once (_2-prevention) guard was deleted not replaced + wire-in unanchored. All in the D1b aggregation-split — the delicate part. | — |
| 13 | **Validator full-suite name-diff is the test authority, NOT the builder's -k report** | The builder's `-k "device or defrag…"` filter MISSED test_v460_d4_d5_registration.py → it reported 3 (wrong) failures and missed 5 real cycle-introduced ones. Not dishonesty — a scoping miss. Every build report's test claims get validator-confirmed via full name-diff before ship. | — |
| 14 | **`CoordinatorEnabledSwitch` (switch.py:236) latent second-authoring of coordinator device identity — ACCEPT this cycle, card latent** | Both reviewers: the identifier/name/model are parameterized; all 7 call sites match canon exactly, so no model race is reachable today. But it's a genuine second author — a future divergent literal wouldn't be caught. Card it (folds into the parked DEVICE-INFO-HELPER-CONSOLIDATION-1). | card |
| 15 | **Pre-existing shadowing noted (not this cycle):** `OccupantCountSensor` defined twice in sensor.py (:1807 house, :2917 room) — the later wins, so aggregation.py:218 builds the room class with (hass,entry) args | Present on develop unchanged (A verified). Out of scope; card separately as a latent bug. | card (separate) |

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
