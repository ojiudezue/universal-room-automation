# v5.91.4 — Egress-identity producer + very_poor drain slider + optimizer zone-truth

**Cards:** `EGRESS-IDENTITY-JOIN-GAP-1`, `OFFPEAK-DRAIN-VERYPOOR-SLIDER-1`, `OPTIMIZER-COMFORT-HVAC-ZONE-MAPPING-FP-1`, `OPTIMIZER-CORPUS-ZONES-EMPTY-1`
**Tier:** batched — egress (Tier 2-DB, 3 framing-disjoint reviews + fix-up + orchestrator verify), drain slider (Tier 2, 1 review), optimizer (Tier 1 ×2, mutation-anchored + 1 SHIP review).
**Merges:** `feature/egress-identity-producer@3a84c165d` + `feature/offpeak-drain-verypoor-slider@93e2af3c5` + `feature/optimizer-corpus-zones@754059697` → develop.

Three disjoint-surface cycles batched into one restart (camera-census+transit / energy config-number / optimizer LLM-context — no interaction).

## 1. Egress-identity producer (the 6.0.0 foundation)

**Problem:** `person_id` has been NULL on all ~7,010 egress crossings for 5.5 months — the old code demanded the *door* camera itself recognize a face within 60s, and door/garage cameras rarely recognize (overhead, motion, back-of-head). Every identity-driven feature is blocked on this producer.

**Solution:** fuse an **interior** recognized face near the crossing instead of requiring the same camera stem. Concretely:
- **D2a** — new `_resolve_face_legs(base_name)` accessor on the census enumerates all NAME-carrying face legs (`sensor.<base>_last_recognized_face[_2]` Frigate + `sensor.<base>_face_recognized[_2]` Protect bridge) with engine + device tags. The old `_resolve_face_entity_id` is UNCHANGED (Frigate-only) — Protect coupling lives only in the new accessor, behind the kill switch.
- **D2b** — `_resolve_egress_face_identity(cam, ts, direction)` fuses over the UNION of the egress camera's own stem ∪ interior-adjacent cameras, inside a **direction-keyed asymmetric window** (`delta = T_face − T_crossing`; exit `[-180, +30]s`, entry `[-60, +300]s`; measured medians -53s / +14s inside). Agreement model: **HIGH 0.9** = ≥2 legs, same canonical slug, DIFFERENT physical cameras (`base_stem`); **CORRELATED 0.75** = same camera, two engines; **MEDIUM 0.6** = single leg; **abstain (person_id=None)** whenever ≥2 distinct names are in-window.
- **D3** — observability on the census sensor via an in-memory 24h-windowed outcome deque: `egress_identity_attach_rate_24h`, `_ambiguity_rate_24h`, `_abstain_rate_24h`, `_correlated_boost_count_24h`, `_last_attach`, `_agreement_class_last`.

**Safety posture:** `person_id` is **advisory** (consumers accept NULL); identity confidence is a SEPARATE field — the existing crossing `confidence` on both bus and DB is byte-identical; the whole path is kill-switch-gated and touches nothing but the egress row (the review-flagged guest-count/presence widening was reverted). D1 (Protect poll bridge) is outside URA; the producer resolves against Frigate today and gains Protect when the bridge publishes.

**Reviews:** 3 framing-disjoint (A correctness/falsifier-arithmetic, B async/lifecycle/blast-radius, C test-authority via per-site mutation) → 15 findings (2+3 HIGH) all fixed in one consolidated pass; orchestrator personally verified the base_stem predicate + widening revert; wire-in anchor confirmed RED-on-neuter. Record: `docs/reviews/code-review/` (egress). Consumer map + safety doctrine: `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md §5`.

### Acceptance criteria
- **Verify:** `_independent` keys on `base_stem` only (HIGH unreachable without a different-camera pair).
- **Verify:** old `_resolve_face_entity_id` candidate set is Frigate-only (no Protect leak into its 5 callers).
- **Test:** 53 cycle tests pass; wire-in behavioral test goes RED when the `_record("attached", …)` call site is neutered.
- **Live (measure-first):** post-restart, run the face-rate probe against the garage/family-room path — the real named-face production rate is the gate on every downstream consumer. Then confirm `person_id` begins populating on `person_entry_exit_events` and `sensor.<census>.egress_identity_attach_rate_24h` moves above 0 (or, if face rec is still down house-wide, that attach+ambiguity are both ~0 — the producer-dead signature, not a bug).
- **Live:** the 4 display consumers (`PersonsEntered/ExitedTodaySensor`, `LastPersonEntry/ExitSensor`) show real names instead of "unidentified" once identity is stamped.

## 2. very_poor off-peak drain slider

**Problem:** v5.91.2 made the `very_poor` solar-quality drain target *accept* live updates, but there was no Number ENTITY for it — only 4 of the 5 quality tiers had a slider, so `very_poor` fell to a hardcoded fallback the operator couldn't reach.

**Solution:** add the 5th slider (`CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR`, default 30, rung-3 Number), mirroring the four existing OffPeakDrain sliders across all 5 sites (const/default, Number `_conf_map` ×2, config-flow selector, setup-loop + reload-suppression allowlist, consumer map). The strategy accessor already accepts `very_poor` (v5.91.2), so a tuned value reaches the decision. Default 30 mirrors `poor`; operator can tune toward 40.

**Review:** 1 pass — production mirror complete + fallback-swap value-safe (both defaults 30); one test-infra miss (2 AST-slice loader stubs) fixed.

### Acceptance criteria
- **Verify:** `number.<...>_offpeak_drain_very_poor` exists, range 15-80/5, default 30.
- **Live:** setting the slider on a `very_poor` night live-applies to `sensor.ura_energy_coordinator_battery_strategy` `drain_targets["very_poor"]` (no hardcoded fallback).

## 3. Optimizer zone-truth (multi-zone comfort false-positive)

**Problem:** the Tier-2 LLM optimizer emitted a false-positive comfort finding — "multiple rooms share a thermostat → loss of independent zonal control" — firing 8+ times back-to-back. But URA zones are an arbitrary software layer intentionally mapped onto FIXED physical HVAC/thermostat zones (3 Carrier thermostats serving ~40 rooms); independent HVAC control finer than a thermostat is physically impossible. The optimizer was flagging the intended architecture, because it was inferring the thermostat→zone structure from names alone (`corpus.zones` was never populated).

**Solution (both):** (a) add the HVAC design invariant to `OPTIMIZER_LLM_SYSTEM_PROMPT`; (b) the robust fix — populate `corpus.zones` from the live merged `ZoneManager.zones` (thermostat fan-out: `{hvac_zone, thermostat, rooms}`), so the optimizer reasons on ground truth, killing the whole class of name-inference errors. Fail-safe: leaves `zones=[]` and never raises on the tick.

**Review:** prompt invariant mutation-anchored; corpus.zones — 1 SHIP review (fail-safe verified across 3 guard layers, mutation-anchored, 0 new failures).

### Acceptance criteria
- **Verify:** `corpus.zones` is populated (non-empty) and the fan-out appears in the serialized prompt body.
- **Live:** the "multiple rooms on one thermostat" comfort finding no longer fires (no `URA Optimizer — comfort` alert of that class over a full optimizer cycle).

## Pre-deploy gate
0 conflict markers; py_compile clean on all changed modules; 250 cycle tests pass; full-suite name-diff = 0 new FAILED/ERROR vs develop (the ~61 pre-existing wall-clock/order-pollution failures unchanged).

## Live Validation — to be recorded post-restart (Validated <date>)
_This section is replaced with the observed results table after the HA restart, per the validation-ledger rule._
