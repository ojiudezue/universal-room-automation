# PLANNING: EC reserve false "write reverted" fix-up (nightly Envoy drop)

Card: **EC-ENPHASE-CONNECTIVITY-RESILIENCE-1** (phase-2 fix-up; phase 2 shipped v5.103.89).
Operator approved option A on 2026-11-01. Tier 3 (see section 8). Status: plan rev 1, awaiting the two plan reviews.

## 0. Problem in one paragraph

Four false CRITICAL `Envoy write reverted: reserve_soc` pages in 8 days (10-24 23:11, 10-29 23:12, 10-30 23:06, 10-31 23:11), each on 4 channels, each at the nightly ~23:05 native Envoy drop. In three of them the native Envoy reserve sensor (`sensor.envoy_482543015950_reserve_battery_level`) read the commanded value within 7-14 s of the 21:00 write. The cloud number (`number.iq_battery_hacs_battery_reserve`) stayed at a stale 10.0. While the local reading was live, the phase-2 D3 gate classified each sweep as `STATUS_CLOUD_STALE`. When the Envoy dropped, `trusted_local_reserve` returned `(None, "unavailable")`, so `_local_confirms` returned False and the sweep fell through to REVERTED + NM, once 0.3 s after a same-value re-send (10-30). The cloud caught up 1-2 minutes after each page. The fourth case (10-24) differs: the local reading was 11 against a commanded 15 the whole time, so the write had not landed and the divergence was real. Only the page text was wrong. This plan must keep paging that case.

## 1. Institutional context verified

### 1.1 Prior art read
| Source | Read | Relevance |
|---|---|---|
| `docs/planning/kanban.data.yaml` card EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 | full card: INSTANCE_2026_10_24/30/31, soak_exit_2026_10_29, `next` | Defines the proposed rule and the 4 instances (timelines quoted in section 0) |
| `docs/planning/PLANNING_ec_reserve_oracle_phase2.md` | D3 section (296-320), INV-R1..R4 (92-101), trust rule (70), consumer table (146-153), knob table (411-426), producer note (179) | D3 is the site being extended. INV-R2 is the invariant this fix-up completes. INV-R3 ("local unavailable → existing CRITICAL") is the clause this plan deliberately narrows (section 2.3) |
| `docs/readmes/README_v5.103.89.md` | live criteria | Criterion 3 ("zero false CRITICAL when the local witness confirms") was VIOLATED at the 10-29 soak exit |
| `docs/readmes/README_v5.103.93.md` | full | Stream tier = a second **SOC** source (`sensor.envoy_482543015950_battery_2`). Not a reserve witness. Relevant only through `_read_soc_via_resolver`, which feeds the low-SOC guard inside `trusted_local_reserve` (section 3.1). No scope added |
| `docs/planning/AUDIT_envoy_core_fix_2026_10_4_match.md` | as briefed | The nightly production.json hang is upstream. An Envoy-side fix does not remove the verifier's exposure to a stale cloud, so this fix-up is still needed |
| `docs/planning/AUDIT_ec_selfheal_resends_root_cause_2026_10_18.md` | cited by card | The "cloud-oracle stall" residual was predicted there |
| Memories `reference_ec_reserve_verifiable_backout_knob`, `feedback_suppression_needs_discharge`, `feedback_coincidental_equality_masks_concept_split` | body | Backout-knob precedent; every deferral needs a discharge (D2); "landed" vs "witnessed" is exactly a concept split (section 3.1) |

HVAC/presence state-of-play docs: not applicable (energy-only surface).

### 1.2 Greps (run 2026-11-01 on develop @ 284add37c)
```
grep -rn '"write_reverted"\|alert_type="reverted"\|STATUS_REVERTED' custom_components/.../domain_coordinators/
  energy_write_verify.py:55   STATUS_REVERTED = "reverted"
  energy_write_verify.py:1174 was_reverted = (rec.status == STATUS_REVERTED)
  energy_write_verify.py:1178 rec.status = STATUS_REVERTED
  energy_write_verify.py:1218 "write_reverted" (anomaly)
  energy_write_verify.py:1234 alert_type="reverted" (NM)
grep -rln write_reverted custom_components quality/tests
  energy.py (comments only: 5528, 5661, 5760), energy_write_verify.py,
  test_ec_reserve_oracle_phase2.py, test_energy_write_verification.py, test_energy_pause_release_hygiene.py
grep -rn '_reserve_last_ok_value\s*=\|_reserve_last_ok_at\s*=' → energy.py:9804-9805 ONLY
grep -n 'WITNESS_MEMORY\|REDISPATCH_GRACE' energy_const.py → 0 hits
grep -n 'RESERVE_LOCAL_WITNESS_ENABLED\|RESERVE_DISPATCH_DEADBAND_PCT' energy_const.py → 584, 581
grep -n 'last_changed' energy_write_verify.py → 0 hits (last_updated used for display at 2906/2916)
HA core.py:2315  last_changed = old_state.last_changed if same_state else None   (installed .venv-ha)
```

### 1.3 REUSE / BUILD verdicts
| Piece | Verdict |
|---|---|
| Local trust predicate | **REUSED** `WriteVerifier.trusted_local_reserve` energy_write_verify.py:521-571 (unchanged) |
| Strict-deadband confirm | **REUSED** `_local_confirms` :573-589 (unchanged, now also called by the stamp) |
| CLOUD_STALE classification + per-desire latch | **REUSED** `_note_cloud_stale` :591-614, `STATUS_CLOUD_STALE` |
| Commanded ledger (value, commanded_at) | **REUSED** `_commanded_ledger` :1316 (`_last_reserve_level_at` moves only on value change, energy.py:2115 comment) |
| Attempt stamp for the same-tick guard | **REUSED** `battery._reserve_last_attempt_value/_at` energy.py:9797-9798 (every dispatch, all four points) |
| `reserve_last_landed(_at)` (= `_reserve_last_ok_value/_at`) as the "witness confirmed" input | **REJECTED**. See 3.1: it is stamped on cloud-API APPLIED, not on a local reading |
| Remembered witness confirmation `_reserve_witness_confirm` (value, at) on the verifier | **NEW**. No equivalent after the greps above + `grep -n witness energy_write_verify.py` (only `_witness_compare`, a cloud-matched divergence emitter, and `trusted_local_reserve`) |
| Same-tick defer latch `_revert_defer_key` | **NEW**. Nothing in the sweep references the attempt stamp today |
| Cloud-oracle staleness test via `State.last_changed` | **NEW** read, no new entity |

Config-first: no knob fixes this. `RESERVE_LOCAL_WITNESS_ENABLED=False` would remove D3 and make paging worse. Disabling the reserve oracle removes all reversion detection. Option B (accept the false page) was offered and declined.

## 2. Falsifiable invariants

**INV-F1 (no false REVERTED after a witnessed landing).** Take the reserve surface, a commanded ledger (C, T_c), and a trusted local reading strictly within `RESERVE_DISPATCH_DEADBAND_PCT` of C observed at some time t_w ≥ T_c. Assume no later trusted local reading at or beyond the deadband, and that the cloud oracle's `last_changed` is ≤ T_c. Then no `write_reverted` anomaly or `alert_type="reverted"` NM fires for (C, T_c) in ANY reachable path, including when the native reserve sensor is unavailable or unknown, and including the tick in which C is re-dispatched.

**INV-F2 (real reversions still page), the converse.** Each case below must still fire `write_reverted` + NM:
- (a) **Envoy available:** a trusted local reading ≥ deadband away from C clears the memory (D1). The sweep then sees `_local_confirms` False and the path is pre-cycle. Unchanged.
- (b) **Envoy unavailable, cloud moved:** someone changes the reserve in the Enphase app after T_c, so the cloud state changes and `last_changed > T_c`. The memory does not apply and the sweep pages on that tick. Unchanged latency.
- (c) **Envoy unavailable, cloud unchanged at a value ≠ C:** an external change to the same stale value produces no observable event. It is indistinguishable from staleness. Detection is **deferred, not lost**: the first trusted local reading when the Envoy returns is ≥ deadband away from C, so the memory clears and the next sweep pages. Bound = Envoy outage duration + one tick. This is the only detection the fix gives up, and section 6 states it.
- (d) **Never landed (10-24 shape):** no trusted confirm after T_c, so there is no memory and the page fires as today. D2 can delay it by at most one tick, once per (C, T_c).
- (e) **Restart:** the memory is RAM-only. After restart it is None, which is fail-closed (pre-cycle behaviour).

**INV-F3 (byte-identity).** With `RESERVE_WITNESS_MEMORY_ENABLED=False` and `RESERVE_REVERT_REDISPATCH_GRACE_S<=0`, `_sweep_surface` behaves exactly as on develop @ 284add37c. The CFG and storage_mode surfaces are untouched in all configurations.

### 2.3 Deliberate narrowing of phase-2 INV-R3
Phase-2 D3 acceptance said "local unavailable → existing CRITICAL". This plan changes that **only** for the reserve sweep site, and only under INV-F1's conjunction. The phase-2 doc gets a one-line pointer to this plan in the same commit as the build.

## 3. Producer and consumer checks

### 3.1 Producer: what counts as "the witness confirmed"
- **`reserve_last_landed` (`_reserve_last_ok_value/_at`).** Producer energy.py:9803-9805, inside `_record_reserve_dispatch`, stamped when `status is WriteStatus.APPLIED`. APPLIED means the cloud write call returned OK. **It is not a local reading.** It is also stamped at the same instant as the attempt, so on every applied dispatch `_reserve_last_ok_at ≥ commanded_at` holds trivially. **The card's literal rule would therefore mask the 10-24 never-landed case**: the 23:11 re-issue was APPLIED while local read 11 against 15. This is a coincidental-equality concept split (landed by API vs witnessed by gateway). REJECTED as the input.
- **NEW `_reserve_witness_confirm = (value, at)`.** Producer: a stamp step at the top of the reserve `_sweep_surface`, **before** the verify-window early return at :1034. That ordering is needed because the 21:00:14 confirmation falls inside the first window. Arithmetic: read `(C, T_c) = _commanded_ledger`. If `_local_confirms(battery, C)` is True, set `(C, now)`. If `trusted_local_reserve` returns a numeric local with `|local − C| ≥ deadband`, clear to None (the contrary reading). On reasons `unavailable`, `low_soc_guard`, `soc_unknown_high`, `fallback_only`, `unresolved`, `disabled` or `error`, leave it unchanged. Untrusted is not contrary, so it neither stamps nor clears.
- **Dependency health:** the native reserve sensor is healthy except during the nightly drop (card recounts). Its 7-14 s apply lag was measured in 3 instances. The SOC resolver feeds the low-SOC guard. Since v5.103.93 it can serve the stream SOC during a native outage, but the reserve sensor is down at the same time, so the stream has no path to creating a stamp. Noted and left alone.
- **Cloud oracle staleness:** `hass.states.get(oracle).last_changed`. HA keeps `last_changed` across same-state writes (`homeassistant/core.py:2315`). In all three false instances the cloud value had not changed since before T_c (10-22: stale since 18:27). A cloud transition through `unavailable` resets `last_changed`, so the predicate fails closed and pages (pre-existing behaviour, residual R1).

### 3.2 Consumers
| Consumer | file:line | Trust/display |
|---|---|---|
| `_witness_confirmed_for(battery, C, T_c, oracle_eid)` (NEW helper) → reserve sweep D3 gate | energy_write_verify.py:1192-1199 (extended) | TRUST: page or not |
| Same-tick defer (D2) | energy_write_verify.py, before :1173 | TRUST: one-tick deferral |
| Diagnostic attribute `reserve_witness_confirm(_at)` in the verifier attrs block | energy_write_verify.py ~2859-2930 | DISPLAY |
| `_check` MISMATCH (:702-789) and `schedule` starvation (:586-621) | — | **Not consumers** (non-goal N1) |

## 4. Emission-site enumeration (write_reverted / reverted NM)
Exactly one emission site exists: `_sweep_surface` → `_emit_anomaly(..., "write_reverted")` :1216-1220 and `_maybe_fire_nm(..., alert_type="reverted")` :1225-1235. It is reached only after this sequence:
1. STALE fast path (:1021)
2. ledger None (:1030)
3. verify window (:1034)
4. oracle missing or unreadable (:1036-1041)
5. UNIT_MISMATCH (:1046)
6. matched/UNMAPPED (:1065)
7. desire-matches-oracle retire (:1095)
8. stale-desire retire (:1144-1166)
9. B-MED-2 coalesce (:1173-1186)
10. D3 live confirm (:1192)
11. pending-episode suppression (:1209)

`energy.py` 5528/5661/5760 are comments only (deadband notes). Neighbouring CRITICAL emitters on the same surface, which **the builder must not change**: `_check` `write_verification_failed` (:769-789), `schedule` self-heal starvation (:586-621), pending ladder `pending_write_stuck/standdown` (:2526+), D4 `reserve_enforced_divergence` (:1006). Plan reviewers: re-run `grep -rn 'alert_type=' energy_write_verify.py` independently.

## 5. Deliverables

### D1: Remembered witness confirmation at the sweep D3 gate
- Stamp step (3.1), reserve surface only, placed before the window return. Kill switch `RESERVE_WITNESS_MEMORY_ENABLED`. When False: no stamp, and the helper returns False.
- Gate: replace `self._local_confirms(battery, commanded)` at :1195 with `self._local_confirms(battery, commanded) or self._witness_confirmed_for(battery, commanded, commanded_at, oracle)`. The helper returns True iff all of the following hold:
  1. the switch is on;
  2. the memory is not None and `memory.value == C` and `memory.at ≥ T_c`;
  3. `trusted_local_reserve` currently returns `(None, "unavailable")` (the live witness is down, not untrusted for another reason);
  4. the oracle state's `last_changed ≤ T_c`.
- The ordering is unchanged: after the coalesce, before pending suppression, and the pending episode still wins (R1-M7). It reuses `STATUS_CLOUD_STALE` + `_note_cloud_stale("sweep", …)`, so there is no new anomaly type. The existing per-desire latch keeps it to one row per episode.
- The commanded ledger changing value moves T_c, so an old memory can never satisfy a new command.

**Acceptance**
- **Verify (fix):** replay 10-30. C=20, T_c=21:00:38. Local 20 at 21:00:46. Cloud 10, last_changed 18:00. At 23:06 local is unavailable → status CLOUD_STALE, zero `write_reverted`, zero NM.
- **Verify (discriminator, 10-24 never-landed):** local 11 the whole time, C=15 → no memory → `write_reverted` + NM fire. (With `_reserve_last_ok_*` as the input this test would go green-suppressed. That is the regression this test pins.)
- **Verify (real revert, Envoy down, cloud moved):** memory (15, ≥T_c). Cloud changes 15→10 with last_changed > T_c → page.
- **Verify (contrary reading):** memory set, then trusted local 10 (C=15) → memory cleared → next sweep with local unavailable pages.
- **Verify (untrusted ≠ contrary):** local in `low_soc_guard` → memory unchanged, and the helper is False while it is `low_soc_guard` (only `unavailable` qualifies).
- **Verify (boundary):** local exactly C±2 → no stamp (strict, R2-M4).
- **Verify (restart):** memory None after a fresh verifier → pages as today.
- **Verify (cloud unavailable→10 blip after T_c):** last_changed > T_c → pages (fail-closed, R1).
- **Test:** `test_false_revert_fixup.py::test_witnessed_then_envoy_drop_no_page`, `::test_never_landed_still_pages`, `::test_cloud_moved_after_command_pages`, `::test_contrary_local_clears_memory`, `::test_low_soc_guard_neither_stamps_nor_qualifies`, `::test_deadband_boundary_no_stamp`, `::test_restart_memory_none_fail_closed`, `::test_ledger_value_change_invalidates_memory`, `::test_pending_episode_still_wins`, `::test_kill_switch_byte_identical`.
- **Mutation anchors (framing C):** (1) drop the `last_changed ≤ T_c` clause → `test_cloud_moved_after_command_pages` RED; (2) drop the clear-on-contrary → `test_contrary_local_clears_memory` RED; (3) move the stamp below the window return → `test_witnessed_then_envoy_drop_no_page` RED; (4) substitute `_reserve_last_ok_*` for the memory → `test_never_landed_still_pages` RED.
- **Live:** at the next nightly drop where the cloud is stale, `notification_log` has no `reverted` row. `anomaly_log` has ≤1 `reserve_cloud_oracle_stale` (site=sweep) for that desire. The verifier attrs show `reserve_witness_confirm` = commanded with `_at` ≈ 21:00. The discriminator: under a different failure (e.g. memory never stamped), the attribute is null and the page still fires.

### D2: Never judge REVERTED in the tick of a same-value re-dispatch (one-shot)
- Before the REVERTED stamp at :1173 (after the D1 stamp and the window check), check two conditions: `battery._reserve_last_attempt_value == C`, and `now − battery._reserve_last_attempt_at < RESERVE_REVERT_REDISPATCH_GRACE_S`. If both hold and `_revert_defer_key != (C, T_c)`, set the key and return with no status change, no anomaly and no NM.
- **Discharge:** the deferral is one-shot per (C, T_c). The next sweep evaluates normally even if the re-send repeats every tick (raises are exempt from rule G, so a per-tick re-send is reachable). That bounds the delay to one decision tick (≤300 s). A new (C, T_c) resets the key.

**Acceptance**
- **Verify:** re-send at t, sweep at t+0.3 s, cloud still stale, no memory → no page. Next tick with cloud still stale → page.
- **Verify:** re-sends every tick for 3 ticks → the page fires on tick 2 (one-shot discharge).
- **Verify:** re-send of a different value → no deferral (the ledger has moved anyway).
- **Test:** `::test_same_tick_redispatch_defers_once`, `::test_per_tick_resend_cannot_starve_page`, `::test_grace_zero_disables`.
- **Mutation:** remove the one-shot key → `test_per_tick_resend_cannot_starve_page` RED (it hangs as no-page).
- **Live:** in `ura_activity_log`, no `reserve_write` row is followed by a `reverted` notification within 1 s.

### D3: Docs
Phase-2 plan pointer (2.3), and the README for the release with a live table. No board edits beyond the card's `next`.

## 6. Knobs
| Name | Default | Rung | Why | Kill-switch semantics |
|---|---|---|---|---|
| `RESERVE_WITNESS_MEMORY_ENABLED` | True | 1, module const (energy_const.py) | Trust-hierarchy change on a CRITICAL path; changing it should need review (backout precedent `RESERVE_LOCAL_WITNESS_ENABLED`) | False = D1 off, pre-fix-up D3 |
| `RESERVE_REVERT_REDISPATCH_GRACE_S` | 120 | 1, module const | "Same tick" = the sweep runs ≤1 s after dispatch inside one decision cycle. 120 s is well under the 300 s tick, so it can never span two ticks | ≤0 disables D2 |
| Deadband | — | — | REUSED `RESERVE_DISPATCH_DEADBAND_PCT` (2) | — |

No memory max-age knob. Staleness is judged by `last_changed`, not by age. A cap would re-open the false page on long outages (586/714-min drops were measured). The age-bounded design is parked; revival trigger: any live real revert detected late by more than one Envoy outage.

## 7. Config-extreme / combinatorial cases
| # | Configuration | Expected |
|---|---|---|
| X1 | `RESERVE_LOCAL_WITNESS_ENABLED=False`, memory switch True | `trusted_local_reserve` → `disabled` → never stamps → helper False → pre-cycle |
| X2 | Both switches False, grace 0 | byte-identical (INV-F3) |
| X3 | Native reserve sensor unconfigured (`fallback_only`) | never stamps, never qualifies |
| X4 | Reserve oracle unset | sweep returns at :1037 (unchanged) |
| X5 | Observation mode on | sweep runs as today; D1/D2 classify only (no dispatch interaction) |
| X6 | C = 100 nudge target (99 rests) | memory keyed on the ledger value; nudge value ≠ C → strict deadband applies as in D3 |
| X7 | Grace ≥ 300 | still one-shot, so the bound is one tick; documented as not useful |

## 8. Tier
**Tier 3.** It changes whether a cost-and-safety CRITICAL fires on the battery reserve surface, it extends a phase-2 Tier-3 trust gate, and it narrows a prior invariant. It needs two plan reviews (completeness; adversarial build-prediction), a build by `ura-super-builder`, four build reviews (A local, B state machine/restart/byte-identity, C per-site mutation with anchors D1(1-4)+D2, D falsify INV-F1 **and** INV-F2(a-e) with legal-config repros), orchestrator mutation re-run, and the operator pre-deploy checkpoint. Deploy risk: LOW (alert path only, never actuates).

## 9. Non-goals
- **N1** `_check` "not applied" and `schedule` self-heal starvation keep live-only D3. No false instance of either at the nightly drop has been seen since v5.103.89. Revival trigger: one proven-false instance.
- **N2** Page text that separates never-landed from reverted (card note (a)). Carded as a residual, not in this cycle.
- **N3** No change to dispatch, rule G/T/L, the pending ladder, D4, CFG or storage_mode.
- **N4** No use of the v5.103.93 stream as a reserve witness. Stream binding to the Envoy serial (RG-L2) stays a separate residual.
- **N5** No persistence of the memory across restart.

## 10. Residuals stated
- **R1** A cloud entity blip (unavailable→same value) after T_c resets `last_changed`, so it pages as today (fail-closed).
- **R2** INV-F2(c): an external change to exactly the stale cloud value during an Envoy outage is detected only when the Envoy returns.
