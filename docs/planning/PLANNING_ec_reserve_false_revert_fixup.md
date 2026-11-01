# PLANNING: EC reserve false "write reverted" fix-up (nightly Envoy drop)

Card: **EC-ENPHASE-CONNECTIVITY-RESILIENCE-1** (phase-2 fix-up; phase 2 shipped v5.103.89).
Operator approved option A on 2026-11-01. Tier 3 (see section 8). Status: **plan rev 2**. It addresses plan reviews `docs/reviews/code-review/ec_reserve_false_revert_plan_review_1.md` + `_2.md` (both FIX-PLAN). Changelog in section 11.

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
| Memories `reference_ec_reserve_verifiable_backout_knob`, `feedback_suppression_needs_discharge`, `feedback_coincidental_equality_masks_concept_split` | body | Backout-knob precedent; every deferral needs a discharge (applied to the parked N6); "landed" vs "witnessed" is exactly a concept split (section 3.1) |

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
| `reserve_last_landed(_at)` (= `_reserve_last_ok_value/_at`) as the "witness confirmed" input | **REJECTED**. See 3.1: it is stamped on cloud-API APPLIED, not on a local reading |
| Remembered witness confirmation `_reserve_witness_confirm` (value, at) on the verifier | **NEW**. No equivalent after the greps above + `grep -n witness energy_write_verify.py` (only `_witness_compare`, a cloud-matched divergence emitter, and `trusted_local_reserve`) |
| Cloud-oracle staleness test: oracle raw value equals the value recorded at first confirmation | **NEW** field in the memory; reuses `_read_oracle_raw` |
| Same-tick defer (rev-1 D2) | **DROPPED** (review 2 H2), parked in section 9 |

Config-first: no knob fixes this. `RESERVE_LOCAL_WITNESS_ENABLED=False` would remove D3 and make paging worse. Disabling the reserve oracle removes all reversion detection. Option B (accept the false page) was offered and declined.

## 1.4 Measure-first probe (rev 2, run 2026-11-01, read-only `ssh ha` against the recorder)
Script: count `homeassistant_start` events, cloud-oracle state transitions, and native reserve-sensor states per night, 21:00-23:15 CDT. Recorder retention is **7 days** (oldest row 2026-10-25 05:12 CDT), so 14 nights were not available. Seven nights were measured, 10-25..10-31. The 10-24 instance predates the recorder.

| Night | Restarts in window | Cloud value at 21:00 | Cloud transitions in window | Local reserve |
|---|---|---|---|---|
| 10-25 | 0 | 90 | →20 at 21:00:50 (cloud fresh) | 20 at 21:00, unavailable 23:06 |
| 10-26 | 0 | 10 | →20 at 21:02:03 (fresh) | 20 at 21:01, unavailable 23:06 |
| 10-27 | 0 | 10 | →30 at 21:00:53 (fresh) | 30 at 21:00, unavailable 23:06 |
| **10-28 (page 23:12)** | 0 | 10 | none until →30 at 23:13:37 | 30 at 21:00, unavailable 23:09 |
| 10-29 | 0 | 10 | none (stale all window; no page that night, the sweep path was not reached) | 30 at 21:00, unavailable 23:06 |
| **10-30 (page 23:06)** | 0 | 10 | none until →20 at 23:08:25 | 20 at 21:00, unavailable 23:04 |
| **10-31 (page 23:11)** | 0 | 10 | none until →15 at 23:12:33 | 15 at 21:00, unavailable 23:07 |

Findings:
- **P1.** In all 3 recorded false pages, the cloud showed **one unchanged value** (10.0) from before the command until after the page. Rev-2 condition 4 (cloud value == the value recorded at first confirmation) holds on every false night.
- **P2.** The local drop happens every night at 23:04-23:09.
- **P3.** Restarts: 5 in 7 days, **0** inside 21:00-23:15. Cloud `unavailable`/`unknown` rows: 10 in 7 days, **0** inside the window.

So the rev-1 `last_changed` design would have worked on these 7 nights, but it has the structural restart hole (review H1). The value-based design is immune to both restarts and blips. Re-run this probe as a Live fallback (D1 Live).

## 2. Falsifiable invariants

**INV-F1 (no false REVERTED after a witnessed landing).** Take the reserve surface, a commanded ledger (C, T_c), and a trusted local reading strictly within `RESERVE_DISPATCH_DEADBAND_PCT` of C observed at some time t_w ≥ T_c. When that first confirmation for (C, T_c) is stamped, the cloud oracle reads raw value V. Assume no later trusted local reading at or beyond the deadband, and that the cloud oracle still reads V. Then no `write_reverted` anomaly or `alert_type="reverted"` NM fires for (C, T_c) in ANY reachable path while the native reserve sensor reason is `"unavailable"`, **including after an HA restart** once the memory has re-stamped post-boot.

**INV-F2 (real reversions still page), the converse.** Each case below must still fire `write_reverted` + NM:
- (a) **Envoy available:** a trusted local reading ≥ deadband away from C clears the memory (D1). The sweep then sees `_local_confirms` False and the path is pre-cycle. Unchanged.
- (b) **Envoy unavailable, cloud moved:** the cloud raw value ≠ V. The memory does not apply and the sweep pages on that tick. Unchanged latency.
- (c) **Revert hidden by an unchanged cloud:** a revert lands at any point after the last confirming sweep (during the up-to-one-tick gap before the drop, or during the outage), and it sets exactly V, or the cloud never reflects it. Detection is **deferred, not lost**: the first trusted local reading after the Envoy returns is ≥ deadband away from C, so the memory clears and the next sweep pages. **Bound = (last confirming sweep → drop, ≤ 1 tick) + outage duration (586/714-min outages measured) + 1 tick.** An A→B→A cloud sequence during the outage falls in the same class. This is the only detection the fix gives up.
- (d) **Never landed (10-24 shape):** no trusted confirm after T_c, so there is no memory and the page fires as today, with no delay.
- (e) **Restart:** the memory is RAM-only, so after a restart it is None. The ledger (C, T_c) is restored (energy.py:2105-2107). Until the first post-boot confirming sweep, the result is fail-closed (pages as today). After it re-stamps, V is the post-boot cloud raw value. The cloud does not change on restart if it was stale before, so INV-F1 coverage resumes. Probe P3: no restarts in the window in 7 nights. A restart **during** the Envoy outage leaves no re-stamp, so the page can fire (accepted residual R3).

**INV-F3 (byte-identity).** With `RESERVE_WITNESS_MEMORY_ENABLED=False`, `_sweep_surface` behaves exactly as on develop @ 284add37c. The CFG and storage_mode surfaces are untouched in all configurations.

### 2.3 Deliberate narrowing of phase-2 INV-R3
Phase-2 D3 acceptance said "local unavailable → existing CRITICAL". This plan changes that **only** for the reserve sweep site, and only under INV-F1's conjunction. The phase-2 doc gets a one-line pointer to this plan in the same commit as the build.

## 3. Producer and consumer checks

### 3.1 Producer: what counts as "the witness confirmed"
- **`reserve_last_landed` (`_reserve_last_ok_value/_at`).** Producer energy.py:9803-9805, inside `_record_reserve_dispatch`, stamped when `status is WriteStatus.APPLIED`. APPLIED means the cloud write call returned OK. **It is not a local reading.** It is also stamped at the same instant as the attempt, so on every applied dispatch `_reserve_last_ok_at ≥ commanded_at` holds trivially. **The card's literal rule would therefore mask the 10-24 never-landed case**: the 23:11 re-issue was APPLIED while local read 11 against 15. This is a coincidental-equality concept split (landed by API vs witnessed by gateway). REJECTED as the input.
- **NEW `_reserve_witness_confirm`.** A small dataclass on the `WriteVerifier`:
  - `value: float`
  - `first_at: datetime` (aware UTC)
  - `last_at: datetime` (aware UTC)
  - `cloud_at_first: float`, the oracle raw value from `_read_oracle_raw(oracle)` at the first stamp.

  RAM-only, `None` initially.
- **Stamp/clear step: its own method `_witness_memory_step(battery)`.** It is the FIRST statement of `_sweep_surface` for the reserve surface, **above the STALE fast path (:1021)**. It runs on every sweep regardless of record status or the verify window. That ordering is load-bearing (review 1 M1 / review 2 M1): a contrary reading seen while the record is STALE must still clear. Placing it before the window is defensive only. Steps:
  1. `(C, T_c) = _commanded_ledger(battery, reserve)`. If either is None, set memory None, cache nothing, and return.
  2. **Exactly one** read per sweep: `soc = self._read_soc_via_resolver(battery)`, then `local, reason = self.trusted_local_reserve(battery, C, soc)`. Cache `(C, T_c, local, reason)` on `self._sweep_witness` for the gate in the same sweep. Neither `_local_confirms` nor `trusted_local_reserve` is called a second time for the memory.
  3. **Confirm:** `local is not None and abs(local − C) < RESERVE_DISPATCH_DEADBAND_PCT`.
     - If the memory is None, or `memory.value != C`, or `memory.first_at < T_c`, create a new memory `(C, now, now, cloud_at_first=_read_oracle_raw(oracle))`. If the oracle raw value is None, do not create one.
     - Otherwise set `last_at = now` only (V is kept from the first stamp).
  4. **Contrary:** `local is not None` and |local − C| ≥ deadband → memory None.
  5. **Untrusted, not contrary:** any `reason` other than `"local"` → no change.

  **"Envoy down" defined concretely:** `reason == "unavailable"`. That means the State is missing, its state is `unavailable`/`unknown`, or it is non-numeric (energy_write_verify.py:549-555). This check happens before any SOC check. `low_soc_guard`, `soc_unknown_high`, `fallback_only`, `unresolved`, `disabled` and `error` are all *untrusted*: they neither stamp, nor clear, nor qualify.
- **Dependency health.** Probe P2: the native reserve sensor confirms within about 1 min of the 21:00 write and drops at 23:04-23:09 nightly. The SOC resolver feeds the low-SOC guard. Since v5.103.93 it may serve the stream SOC during a native outage, but by then `reason` is already `"unavailable"`, so the stream cannot stamp. No change.
- **Cloud oracle staleness (rev 2, value-based).** The gate qualifies only while `float(_read_oracle_raw(oracle)) == memory.cloud_at_first`. `oracle` is the same eid `_oracle_entity_for(surface)` returned in this sweep, and a None read means no qualification. `last_changed`, `last_updated` and `last_reported` are **not used**. A restart or an `unavailable`→same-value blip re-reads the same V, so the gate survives both (review 1 H1(a)). Probe P1 confirms that V was unchanged on all 3 false nights.

### 3.2 Consumers
| Consumer | file:line | Trust/display |
|---|---|---|
| `_witness_confirmed_for(oracle_raw)` (NEW helper, reads `self._sweep_witness` + memory) → reserve sweep D3 gate | energy_write_verify.py:1192-1199 (extended) | TRUST: page or not |
| Diagnostic attributes `reserve_witness_confirm` (float/null), `reserve_witness_confirm_first_at` / `_last_at` (ISO string/null), `reserve_witness_cloud_at_first` (float/null) in the verifier attrs block | energy_write_verify.py ~2859-2930 | DISPLAY |
| `_check` (:826-955, mismatch NM :955) and `schedule` self-heal starvation (NM :769) | — | **Not consumers** (non-goal N1) |

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

`energy.py` 5528/5661/5760 are comments only (deadband notes). Neighbouring emitters, which **the builder must not change** (review 1 enumeration, re-run with `grep -n 'alert_type=' energy_write_verify.py`):
- 680 `cloud_write_leg_unavailable`
- 769 `self_heal_starvation`
- 955 `_check` mismatch
- 1542 `dispatch_failed`
- 1594 `write_churn`
- 1670 `ev_toggle_tripwire`
- 2089 `reserve_enforced_divergence`
- 2487 `hardware_noncompliance`
- 2680/2730 pending ladder Plan reviewers: re-run `grep -rn 'alert_type=' energy_write_verify.py` independently.

## 5. Deliverables

### D1: Remembered witness confirmation at the sweep D3 gate
- Add the `_witness_memory_step` described in 3.1. It is the first statement of `_sweep_surface` for the reserve surface, above :1021. Kill switch `RESERVE_WITNESS_MEMORY_ENABLED`: when False the step returns immediately and the helper returns False.
- **Gate:** at :1195, replace `self._local_confirms(battery, commanded)` with `self._local_confirms(battery, commanded) or self._witness_confirmed_for(commanded, commanded_at, oracle_raw)`. The helper returns True iff all of the following hold:
  1. the switch is on;
  2. the memory is not None, `memory.value == C`, and `memory.first_at >= T_c` (aware datetimes; a naive or None T_c returns False);
  3. the cached `self._sweep_witness` is for the same (C, T_c) and its `reason == "unavailable"`;
  4. `float(oracle_raw) == memory.cloud_at_first`. `oracle_raw` is the value already read at :1039 in this sweep.

  The helper never raises (it fails to False).
- The ordering is unchanged: after the coalesce, before pending suppression, and the pending episode still wins (R1-M7). It reuses `STATUS_CLOUD_STALE` + `_note_cloud_stale("sweep", ...)`, so there is no new anomaly type and the existing per-desire latch applies.
- A change in the ledger value moves T_c, so `first_at < T_c` and an old memory can never satisfy a new command.

**Test authority (review 2 L4).** Tests drive the real `WriteVerifier._sweep_surface` / `reversion_sweep`. States are set with `hass.states.async_set` (native reserve sensor, cloud number) under the time freezer. The `_commanded_ledger` fields are seeded on the battery stub the way the restore path writes them (energy.py:2105-2107). Assertions are on the `_emit_anomaly` call (`write_reverted` vs `reserve_cloud_oracle_stale`) and on the `_maybe_fire_nm` call or its absence, never on `rec.status` alone.

**Acceptance**
- **Verify (fix, 10-30 replay):** C=20, T_c=21:00:38, local 20 at 21:00:46, cloud 10. At 23:06 local is `unavailable` → `reserve_cloud_oracle_stale`, no `write_reverted`, no NM.
- **Verify (discriminator, 10-24 never-landed):** local 11 the whole time, C=15 → no memory → `write_reverted` + NM.
- **Verify (real revert, Envoy down, cloud moved):** memory (15, V=10). Cloud set to 12 → page.
- **Verify (contrary reading):** memory set, then trusted local 10 with C=15 → memory None → the next sweep with local unavailable pages.
- **Verify (contrary while STALE):** record STALE, memory (15), local reads 10 → memory None. Then a same-value `schedule(15)` revives the record, the Envoy drops, the cloud is 10 → page. Test `test_contrary_while_stale_clears_memory`.
- **Verify (untrusted ≠ contrary):** `low_soc_guard` → memory unchanged, and the helper is False while it holds. A non-numeric local state counts as `unavailable` (qualifies).
- **Verify (boundary):** local exactly C±2 → no stamp (strict).
- **Verify (seeded-ledger restart):** fresh verifier, ledger restored (C=20, T_c=21:00), cloud `async_set` 10 at boot (22:00, after T_c), local 20 → the first post-boot sweep stamps V=10 → local `unavailable` at 23:06 → no page. Second case: restart with local already `unavailable` → page (fail-closed, R3). Test `test_restart_seeded_ledger_rewitness_then_drop_no_page`, `test_restart_during_outage_pages`.
- **Verify (cloud blip):** cloud `unavailable` then back to 10 → still qualifies. Cloud `unavailable` at the sweep → `oracle_raw` None → the sweep returns at :1041 (unchanged).
- **Verify (attribute-only cloud update):** attributes change, value 10 → qualifies.
- **Verify (one read per sweep):** spy `trusted_local_reserve` → exactly 1 call from the memory step, plus `_local_confirms`'s own existing call at the gate.
- **Test file `quality/tests/test_ec_reserve_false_revert_fixup.py`:** the tests above plus `test_witnessed_then_envoy_drop_no_page`, `test_never_landed_still_pages`, `test_cloud_moved_after_command_pages`, `test_contrary_local_clears_memory`, `test_low_soc_guard_neither_stamps_nor_qualifies`, `test_deadband_boundary_no_stamp`, `test_ledger_value_change_invalidates_memory`, `test_pending_episode_still_wins`, `test_kill_switch_byte_identical`.
- **Mutation anchors (framing C):**
  1. drop condition 4 (cloud == V) → `test_cloud_moved_after_command_pages` RED;
  2. drop the clear-on-contrary → `test_contrary_local_clears_memory` RED;
  3. **move the memory step below the STALE fast path** → `test_contrary_while_stale_clears_memory` RED;
  4. substitute `_reserve_last_ok_*` for the memory → `test_never_landed_still_pages` RED;
  5. key V freshly on each stamp instead of first-only → `test_cloud_moved_after_command_pages` variant (cloud moves while local is still live, then drop) RED.
- **Live (review 1 M3 / LOW-3):** at the next nightly drop where the cloud is stale, `notification_log` has no `reverted` row, and `anomaly_log` has ≤1 `reserve_cloud_oracle_stale` (site=sweep) for that desire. Verifier attrs at ~23:10: `reserve_witness_confirm` = commanded, `T_c ≤ first_at ≤ last_at ≤ drop time`, and `reserve_witness_cloud_at_first` = the stale cloud value. Discriminator: if the memory never stamped, the attrs are null and the page fires. **Fallback** if no stale-cloud drop happens before close: the in-suite 10-30 replay is the accepted proof, and the README table records "proved in-suite, no live stale night", plus the section 1.4 probe re-run.

### D2: Docs
Phase-2 plan pointer (2.3), and the README for the release with a live table. No board edits beyond the card's `next`.

## 6. Knobs
| Name | Default | Rung | Why | Kill-switch semantics |
|---|---|---|---|---|
| `RESERVE_WITNESS_MEMORY_ENABLED` | True | 1, module const (energy_const.py) | Trust-hierarchy change on a CRITICAL path; changing it should need review (backout precedent `RESERVE_LOCAL_WITNESS_ENABLED`) | False = D1 off, pre-fix-up D3 |
| Deadband | — | — | REUSED `RESERVE_DISPATCH_DEADBAND_PCT` (2) | — |

No memory max-age knob. Staleness is judged by the cloud value being unchanged, not by age. A cap would re-open the false page on long outages (586/714-min drops were measured). The age-bounded design is parked; revival trigger: any live real revert detected late by more than one Envoy outage.

## 7. Config-extreme / combinatorial cases
| # | Configuration | Expected |
|---|---|---|
| X1 | `RESERVE_LOCAL_WITNESS_ENABLED=False`, memory switch True | `trusted_local_reserve` → `disabled` → never stamps → helper False → pre-cycle |
| X2 | Both switches False, grace 0 | byte-identical (INV-F3) |
| X3 | Native reserve sensor unconfigured (`fallback_only`) | never stamps, never qualifies |
| X4 | Reserve oracle unset | sweep returns at :1037 (unchanged) |
| X5 | Observation mode on | sweep runs as today; D1 classifies only (no dispatch interaction) |
| X6 | C = 100 nudge target (99 rests) | memory keyed on the ledger value; nudge value ≠ C → strict deadband applies as in D3 |

## 8. Tier
**Tier 3.** It changes whether a cost-and-safety CRITICAL fires on the battery reserve surface, it extends a phase-2 Tier-3 trust gate, and it narrows a prior invariant. It needs two plan reviews (completeness; adversarial build-prediction), a build by `ura-super-builder`, four build reviews (A local, B state machine/restart/byte-identity, C per-site mutation with anchors D1(1-5), D falsify INV-F1 **and** INV-F2(a-e) with legal-config repros), orchestrator mutation re-run, and the operator pre-deploy checkpoint. Deploy risk: LOW (alert path only, never actuates).

## 9. Non-goals
- **N1** `_check` "not applied" and `schedule` self-heal starvation keep live-only D3. No false instance of either at the nightly drop has been seen since v5.103.89. Revival trigger: one proven-false instance.
- **N2** Page text that separates never-landed from reverted (card note (a)). Carded as a residual, not in this cycle.
- **N3** No change to dispatch, rule G/T/L, the pending ladder, D4, CFG or storage_mode.
- **N4** No use of the v5.103.93 stream as a reserve witness. Stream binding to the Envoy serial (RG-L2) stays a separate residual.
- **N5** No persistence of the memory across restart.
- **N6 (parked, was rev-1 D2):** the one-shot same-tick re-dispatch deferral. Under D1 it only delays true pages (review 2 H2). With D1, the 3 recorded false pages are covered by the memory. **Revival trigger:** a live false page with no witness memory and a same-value re-send in the same tick.

## 10. Residuals stated
- **R1** (rev 2: closed) Cloud blips no longer matter, because the comparison is value-based.
- **R3** A restart during the Envoy outage means no post-boot stamp, so it pages as today (fail-closed).
- **R2** INV-F2(c): a revert after the last confirming sweep that leaves the cloud at V is detected only when the Envoy returns. Bound ≤ 1 tick + outage + 1 tick.

## 11. Rev 2 changelog
- HIGH (both reviews): `last_changed ≤ T_c` replaced by a value-based cloud-staleness check (V recorded at first confirm), plus the measure-first probe (section 1.4) and seeded-ledger restart tests.
- Review 2 H2: D2 and its knob dropped, parked as N6.
- M1 (both): the memory step is its own method above the STALE return, with one `trusted_local_reserve` read per sweep cached for the gate (r2 M4). "Envoy down" defined concretely. Types pinned (r2 M3). Mutation anchor 3 re-anchored on the ordering (r2 M2). INV-F2(c) bound fixed (r1 M2).
- Live check uses first/last stamps and has an in-suite fallback (r1 M3/L3). Line references corrected (r1 L2). Attributes are ISO strings (r2 L3). Tests use `hass.states.async_set` + freezer and assert the anomaly and NM calls (r2 L4). L2 evidence comes from the probe.
