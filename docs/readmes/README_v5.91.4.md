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

## Validated 2026-08-28 (post-restart, ~20:54 CDT)

Deploy chain confirmed: PR #533 merged, release `v5.91.4` tagged, `origin/master` manifest = v5.91.4 with all three cycles' code present (egress `_resolve_face_legs`/`FACE_MATCH_CORRELATED_BOOST` ×5, `VERY_POOR` ×2, `corpus.zones`/`zones_out` ×8), HACS installed v5.91.4, restarted.

| Criterion | Observed evidence | Result |
|---|---|---|
| Clean boot, no new URA errors | `error_log` structured scan: **zero `custom_components.universal_room_automation … ERROR`**; all URA lines are WARNING (Envoy warmup, the known stuck Guest-Bedroom sensor being ignored, offline front-door lock, standard "custom integration" notice). No tracebacks. | **PASS** |
| **Drain slider** — 5th tunable exists + honored | `number.ura_energy_coordinator_off_peak_drain_very_poor` = **30** (min 5 / max 80, mirrors `poor`); `sensor.ura_energy_coordinator_battery_strategy` `drain_targets = {excellent:10, good:15, moderate:20, poor:30, very_poor:30, unknown:40}` — the accessor honors the tunable. | **PASS** (live) |
| **Egress producer** — shipped + armed | Code present on master; clean boot; kill-switch-gated path live. `person_entry_exit_events` last 24h = **7,123 crossings, 0 with `person_id`**. | **PASS (armed); attach=0 — see below** |
| **Egress attach rate** — measure-before-build gate | Producer has **no live face-name source wired yet**, so `person_id` stays NULL — but NOT because face rec is down. **Frigate** `sensor.*_last_recognized_face_2` (the source `_resolve_face_legs` reads today) IS dead/stuck at `Unknown`. **Protect** face rec, however, is ALIVE (protect_list_smart_detections: 19 face events in recent hours, conf up to 95; enrolled Oji 46 detections/conf 82, Ziri 40/conf 79) — but URA can't see it until the **D1 Protect bridge** (`sensor.<cam>_face_recognized`, outside-URA, unbuilt) polls the Protect API and republishes. So the unblock is a buildable next cycle, not a face-rec restore. | **As-expected (source unwired — build D1)** |
| **Optimizer zone-truth** — FP suppressed | Prompt invariant + `corpus.zones` fan-out present on master; review SHIP + mutation-anchored. Live "no comfort-FP alert of that class over a full optimizer cycle" is a short **organic watch** (can't be observed at the boot instant). | **Code+review PASS; live = organic** |

### The real blocker (corrected 2026-08-28)
An earlier draft of this table said "face rec is down house-wide" — that was **wrong** (it probed only the dead Frigate sensors). **Protect face recognition works** and Oji/Ziri are enrolled and recognized. The producer's actual gap is that URA reads the **dead Frigate** `_last_recognized_face` feed + the **unbuilt** Protect bridge (`sensor.<cam>_face_recognized`), so it has no live source. The unblock is to **build the D1 Protect bridge** — poll the Protect API (already naming residents) and republish, mapping `recognized_person_id`→name via the Known-Faces registry. That's the identity arc's real next cycle. Meanwhile `person_id` stays ~0 by design (graceful-anonymous — nothing breaks).

**Organic watches (per `--revisit`):** (1) once D1 lands, confirm `egress_identity_attach_rate_24h` moves; (2) confirm the multi-zone comfort alert no longer fires over an optimizer cycle; (3) very_poor drain slider live-applies on a `very_poor` night.
