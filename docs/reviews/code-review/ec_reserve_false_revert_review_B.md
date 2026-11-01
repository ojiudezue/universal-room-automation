# EC reserve false-revert fix-up — Review B (integration / state-machine integrity)

Branch `fix/ec-reserve-false-revert` @ 80b755e45, base 8e2e9b7b7 (merge-base verified). Plan rev 2.
Not HVAC/presence; the HVAC/presence state-of-play docs don't apply.

## Findings

| SEV | Site | Finding |
|---|---|---|
| LOW | energy_write_verify.py:2900-2911 | Four new diagnostics attrs (`reserve_witness_*`). They are display-only and null when there is no memory. The attribute dict is not byte-identical to pre-fix, but that is cosmetic. Bug class: none (noted for recorder attr growth). |
| none | — | No CRITICAL/HIGH/MEDIUM. |

## Branch-by-branch (holds because)

- **STALE fast path (:1133):** the step runs above it and only mutates `_reserve_witness_confirm` / `_sweep_witness`. The record, coalesce map, latches and counts are untouched, so the STALE return is unchanged.
- **Window / oracle-None / unit-mismatch / matched / STALE-retire / stale-desire returns:** these are unchanged and all precede the gate. The matched branch still clears `_cloud_stale_sweep_latch`.
- **B-MED-2 coalesce (`was_reverted`):** precedes the gate, so it is unchanged. A standing REVERTED never re-classifies (pre-existing).
- **Pending-episode suppression:** `not is_pending_episode_active` still ANDs the whole disjunction (:1305), so the pending episode wins (`test_pending_episode_still_wins`).
- **Oracle-stale anomaly:** reuses `STATUS_CLOUD_STALE` + `_note_cloud_stale("sweep")` and the per-desire latch. There is no new anomaly type.
- **`_check` / `schedule` self-heal starvation / re-dispatch ladder:** not consumers (N1). The grep shows `_witness_confirmed_for` is called only at :1310.
- **No-op path, switch on, no witness:** the step adds read-only state reads (`battery_soc` property, Envoy sensor, oracle). `trusted_local_reserve` is side-effect-free (:543-592). With no memory the gate returns False, so classification is identical to pre-fix (`test_kill_switch_byte_identical`, `test_never_landed_*`).
- **Ledger T_c movement:** every `_last_reserve_level_at` writer is anchor-gated (energy.py:5682/5778/10000 via `_anchor_moves`, energy_battery.py:8197 via `ledger_anchor_moves`), so a same-value re-send does not invalidate the memory spuriously. The parked N6 is consistent with this.
- **Restart:** the memory and `_sweep_witness` live in RAM and start as None. The ledger is restored (energy.py:2107). The result fails closed until a post-boot re-witness (`test_restart_seeded_ledger_rewitness_then_drop_no_page`, `test_restart_during_outage_pages`, the accepted residual R3).
- **Observation mode:** classification is the same (`test_x5`).
- **write_route cloud/local:** the oracle eid and the compare path are unchanged. The stamp needs a non-None oracle raw, so an unset oracle means no stamp (`test_x4`).
- **v5.103.93 stream tier:** not a witness (N4). `trusted_local_reserve` is untouched.

## Discharge (suppression needs a discharge)

The memory clears on any trusted contrary reading (≥ deadband), including while STALE (`test_contrary_while_stale_clears_memory`), and when the ledger goes None. The gate is inert on a ledger value or stamp change (`mem.value`/`first_at < T_c`) and as soon as the cloud reads anything other than V (`test_cloud_moved_*`). A starved real revert that is hidden by an unchanged cloud is bounded by: last confirming sweep, plus the outage, plus one tick. When the Envoy returns with a contrary value, the memory clears and the next sweep pages (`test_revert_hidden_by_unchanged_cloud_detected_on_envoy_return`; plan R2). The discharge exists and is tested.

## Tests

282 passed, run from the worktree: `test_ec_reserve_false_revert_fixup.py` plus the reserve-oracle / write-verify / cloud-stale files.

## Verdict: SHIP
