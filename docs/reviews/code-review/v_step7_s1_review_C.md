# Step 7 S1 review C (test authority, per-site source mutation), 6b0401670

~77 independent single-site (or documented paired) mutations of production source against
quality/tests/test_egress_edge_anchor.py (39 tests, baseline green). Tree clean, HEAD unchanged.

## RED (named test) - sample
lead<=0 guard -> test_lead_zero_noop_golden; provenance filter -> test_provenance_gate_direct[ble-None];
live_face_legs -> test_synthetic_only_face_never_anchors; MIN_TIER -> test_min_tier_knob_gates;
lower bound -> test_exit_called_entry_named_arrived; upper bound -> test_edge_after_upper_bound_t_plus_46;
truncation -> test_truncated_ring_no_anchor; counted/stale/boot -> test_stale_and_boot_edges_ignored[kw*];
pair block / partners / pairs parse / canonical map -> test_partner_edge_blocks, test_pair_guard_*, test_parse_pairs_invalid_ignored;
notif bar `>=`, verb, anchor passed, identity_role, nameable, D8a edge_anchor -> test_exit_called_entry_named_arrived;
exception path -> test_edge_read_raises_notice_unchanged; INV-SEC identity_confidence override -> RED;
tripwire s1-cover / any-anchored / stale / min-arrivals / severity / nightly op / db delegate -> RED.
Combined persons=None + own-edge=kept -> test_other_persons_edge_never_anchors RED.

## GREEN (untested) - findings
| # | Sev | Site | Note |
|---|---|---|---|
| 1 | MEDIUM | tracker `async_edge_anchor_tripwire` LEAD<=0 guard | test_tripwire_quiet_before_s1_rows sets LEAD=0 but the pre-S1 row already makes it quiet: hollow. With LEAD 0 and covered rows + 3 arrivals the NM pages while feature is OFF (INV-NOOP). |
| 2 | MEDIUM | presence.py diagnostics dict `edge_anchor_*` (named, error) | test checks LayerCounters only, not the presence layer-diagnostics output; removal GREEN across 189 tests. |
| 3 | MEDIUM | config_flow CONF_EGRESS_CONFUSABLE_PAIRS field | removal GREEN; no options-flow round-trip test. |
| 4 | LOW | tripwire `counted is True` and `in_boot_window` arrival filters | tests vary only source_stale. |
| 5 | LOW | tripwire `since` window days | x100 GREEN. |
| 6 | LOW | INV-SEC `person_id = anchor slug` override | GREEN: test uses person_id == slug (Bug Class #63 coincidental equality); only identity_confidence override is caught. |
| 7 | LOW | notify name `display_of(person_id or slug)` | no test where person_id != anchor slug. |
| 8 | LOW | `mine[-1]` vs `mine[0]` (lead_s with 2 edges) | untested. |
| 9 | LOW | direction guard; presence None; census.egress_identity_enabled in anchor | equivalent/redundant (resolver already abstains); no direct test. |
| 10 | INFO | persons filter, own-edge filter, kinds query / kept-kind, no-own return | each GREEN alone (mutually covering, defence in depth); paired mutation RED. Not a finding. |
| 11 | INFO | notif-bar `>=` removal | inert: const import-check keeps 0.75 >= bar. |

## Verdict: FIX-REQUIRED (minor)
Fix 1-3 (small tests). 4-8 are fix-in-cycle LOWs.
