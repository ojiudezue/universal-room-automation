# Test Wave 2 D7 slice 1 - Review C (test authority via real mutation)

Head 7b227bbe0. Baseline (unmutated): 47 passed (all residue + pair anchors + safeword). Each drill: hand-mutate ONE
site in the donor/victim/helper, clear __pycache__, PYTHONDONTWRITEBYTECODE=1, `-m ""`, run the named anchor, restore (try/finally).

| Site | Mutation | Anchor test | Result |
|---|---|---|---|
| R1 test_identity_fusion_d2_d3_d4 `_scope_real_ha_patches` | drop autouse decorator | test_donor_leaves_no_residue[identity_fusion] | RED |
| R2 test_hvac_fan_control import block | import_scope(prefixes=()) | test_donor_leaves_no_residue[hvac_fan_control] | RED (probe assertion fails, verified cause) |
| R3 test_chatter_detector | remove mp.undo() | test_donor_leaves_no_residue[chatter_detector] | RED |
| R4 test_ac_ramp_master_option_persistence | attrs=True -> prefixes=() | test_donor_leaves_no_residue[ac_ramp...] | RED |
| P1 test_perimeter_alert_nm_routing | remove `_scheduled.clear()` | test_victim_green_after_donor[perimeter -> exterior_cycle2] | RED |
| P2 test_bathroom_exhaust_occupancy_and_resend | import_scope neutered | test_victim_green_after_donor[bathroom -> dp_drain_target_value_stamp] | RED |
| V1 test_v4715_universalize_veto victim fix | revert BOTH patch.dict sites to patch.object(_pm) | pair[oc_pillar_a_handshake -> v4715] | RED |
| V2 test_nm_image_delivery | unpin `_d7_naive_nm_clock` | pair[v5_17_1_part3_seams -> nm_image_delivery] | RED |
| V3 test_envoy_auto_derive | drop `_d7_truthy_entity_registry` autouse | pair[onboarding_simplify_slice1 -> envoy_auto_derive] | RED |
| B1 test_safeword_window | `_now()` -> datetime.utcnow() | test_duke_45m_parses | RED |
| I1 `_d7_isolation.import_scope` | remove key pop/restore loops in finally | test_donor_leaves_no_residue[hvac_fan_control] | RED |

Note: V1 file has TWO identical fix sites (lines ~1352, ~1449). My first attempt mutated only the first and was GREEN;
this is expected (second site still pins) and shows each site is individually redundant, not unanchored - reverting
both (as the builder's drill does) is RED. Note for the builder: no single-site anchor for those two.
In-suite sandbox drill `-k "victim_fix_reverted and v4715"` also passes (KILLED).

GREEN rows on a complete mutation: none. 11/11 RED. Tree clean (only untracked review A/B/C docs).
Verdict: SHIP (test authority holds for sampled sites).
