# Review D (adversarial completeness, diff-blind): census deconfliction P2 + crossing ledger

Branch `feature/census-deconfliction-p2-ledger` @ `ed9229c5`, diff base `3ec3f4d2` (merge-base with develop, verified).
Framing D only. Read: both plans (§4 invariants in full), presence state of play, sensor fleet classes, identity manual §5.5, arc drift analysis.
No code changed. No suite run.

## Invariant checklist

| Invariant | Verdict | Evidence |
|---|---|---|
| INV-P2-AWAY-LATENCY | PASS | The only new work on the census path is `_compute_awareness` (`camera_census.py:6576`): sync, no await, all inside try/except. `TrustFields` is built from ints (`len()`, clamped ints), so it cannot raise outside the try. The `SIGNAL_CENSUS_UPDATED` payload (`camera_census.py:1868-1900`) is untouched, and so are `_handle_census_update`, the boot seed and `total_persons`/`unidentified_count`/`identified_count`. The new `SIGNAL_RESIDENCY_EVENT` (`presence.py:5331`) has one subscriber, `_on_residency_event`, which arms a timer and never dispatches a house or census signal. `get_residents_home` (`presence.py:5446`) is a pure read. Nothing new calls `_run_inference`. |
| INV-P2-AWARE-NO-TRUST | PASS | Every `aware_*`/`count_provenance` reader is `get_house_census` (`presence.py:5985`). Its only caller is `_CensusAwarenessSensor._view` (`sensor.py:4224`), through `view_for_class(display)`. `view_for_class` (`presence.py:6010`) requires the class to be in the promoted AND legal sets (legal = {display, notification}, `const.py:6564`) and the switch state to be exactly `on`. house_state/security/hvac/comfort can never return awareness under any edit of the promoted set. `states.get(` hits for the new entity ids: only `view_for_class` reading the switch. The new sensors have no reader in URA. No `asdict`/serialisation of `CensusZoneResult` exists, so no DB column or payload carries the new fields. |
| INV-P2-AWARE-DECONFLICT | PASS | `census_deconflict.py:117`: `aware = vis if vision_leads else guest_cam`. `vision_leads` is the rung-1 const (False). `aware_total = identified + guest_cam = clamped_total` (`camera_census.py:6560-6566`, since the ceiling is at least `identified`), so it is byte-equal to trust. |
| INV-DEDUP | PASS (as built) | One guest term (the ledger) combined by max (`guest_terms_max`). Residents are subtracted once, inside `guest_vis = L − R`. Overlapping door cameras use max within the door group (`transit_validator.py:1307`). A same-direction cluster gives one term, and a late same-direction joiner gives none (`crossing_vision.py:_join_cluster`). Ledger and camera values are selected, never summed. |
| INV-SINGLE-WRITER | PASS | `deconflict_house` and `census_tick` are called only from `_compute_awareness`, which is called only from `_apply_enhanced_house_census` (grep). |
| INV-P2-DISCHARGE | PASS with LOW lag (D-L1) | Every surplus is cleared by the anchor (`crossing_ledger.py:_anchor`), by the departure reconcile, or by `set_unknown` on switch off, kill or cap 0. Boot starts unknown. Stuck and anchor-zero trip-wires are wired to NM. |
| INV-NO-NAME / IDENTITY | PASS | `aware_identified` is a copy of the trust union. Vision supplies only `people_count` ints. Reconcile `person` comes read-only from the residency record. |

## Config-boundary sweep

| Knob | Extreme | Result |
|---|---|---|
| `LEDGER_EMPTY_RESET_S` | 0 | Anchors on the first passing sample. Discharge gets faster. Safe. |
| `LEDGER_EVAL_S` | 0 | The interval clamps to 1 s, but the freshness bar is `2*0` and fails on every sample, so the ledger can never anchor and is unknown forever. Safe direction, but undocumented (D-L2). |
| `RECONCILE_LEAD/LAG` | 0/0 | Reconcile off. The surplus waits for the anchor (as documented). |
| `STUCK_S` / `ANCHOR_ZERO_S` / `DISAGREE_PERSIST_N` | 0 | Off, as documented. |
| `DISAGREE_FLAG_MIN` | 0 / negative | Only diff 0 is "agree"; with a negative value everything is disagree. This changes metadata only. |
| Promoted class set | add security/house_state/hvac | Not in the legal set, so trust. |
| Downgrade switch | off / unavailable / before added | trust in every case (the check is `st.state != "on"`). |
| Cap 0 / kill / switch off | — | `_ledger_disabled` sets the ledger unknown, `census_tick` returns `(None, False)`, which is case D. |
| Enhanced census off | — | `census_tick` is never called, so the ledger is never known and awareness falls back to trust (D-L3). |

## Findings

**D-M1 MEDIUM, goal fidelity (dormant behind `VISION_LEADS=False`)**: the anchor clears guests who are still and off camera. The anchor (`crossing_ledger.py:_sample_ok`) needs camera bodies 0 and no Tier-1 **rising edge** for 1 h. Levels are ignored by design. A guest asleep in a bedroom without a camera, held by a ZK/ZX radar (level on, no edges) or not seen by a motion-class ZV, satisfies the predicate. Repro: R=2, guest arrives with an entry term so L=3. At 23:00 everyone is in bedrooms, interior cameras read 0 and there are no edges. At 00:00 the anchor sets L=R=2, and `guest_vis` reads 0 while the guest is home. Each night with a guest adds an anchor residue of +1, so drift bar a (≥80% zero residue, |residue|≤1) fails in any week with an overnight guest. F-LEAD then cannot be reached, which blocks the arc goal (census accuracy). The undercount is in the safe direction and nothing is shipped wrong today. Card it before CD4. Options: block the anchor on any Tier-1 *level* in a non-resident-attributed room at night, or score bar a only on anchors during AWAY.

**D-L1 LOW (#53-adjacent), a late exit cancels a reconcile it never paid for.** `apply_term` appends exits to `_exit_es` before the unknown/late checks (`crossing_ledger.py`, `if direction == DIRECTION_EXIT: self._exit_es.append`). Repro: resident A exits at E. The vision outcome lands after an anchor at E+Δ (Δ < timeout+wait), so the term is recorded `late` and not applied. A's geofence departure lands at t_e > anchor with t_e − E ≤ 900 s. The anchor set L=R (A still counted), so after the departure guest_vis=1. `judge_reconcile` finds E in the window and cancels, and the phantom guest stays until the next anchor (≤1 h on an empty house). Fix: append only exits that were applied (or late exits whose E ≥ the pending t_e − LEAD and that postdate the anchor). This is bounded, display-only and dormant.

**D-L2 LOW**: with `LEDGER_EVAL_S=0` the ledger can never anchor (freshness `2*eval_s`). The code comment does not document what 0 means. Document it, or floor the freshness at the 1 s interval.

**D-L3 LOW**: with enhanced census off, the ledger stays unknown, and `crossing_ledger_anchor_zero` pages after 48 h with a remedy that blames cameras and room sensors. Suppress the page, or name the cause, when no `census_tick` has been seen.

**D-N1 note (F-LEAD only)**: `R = max(residents_home, identified_count)` (`camera_census.py:_resident_term`) is a max, not a set union. When `recognized_set` holds a tracked non-resident, `aware_guests` can label an unseen resident as the guest. `aware_total` stays correct. Recheck at CD4.

**D-N2 note**: `aware_vision_status` defaults to `switch_off` when no producer is registered, even if the switch is on. Display only.

## Consumer census (trust vs awareness)

The existing readers of `total_persons`, `unidentified_count`, `identified_count`, `census.last_result` and `persons_in_house` attributes (presence `_handle_census_update`, boot seed, PLB, CensusMismatchSensor, the four census sensors, house_status, SC auto-follow, lock regime, perimeter severity) read only the trust fields. Their values are unchanged, because the producer assigns the new fields alone and leaves the existing ones as develop does. Every reader of `get_house_census`, `view_for_class` and `aware_*` is the two new display sensors, so all are awareness readers.

## Verdict: **SHIP**

There are no CRITICAL or HIGH findings, and every load-bearing invariant holds over the whole surface. Card D-M1 as a precondition for CD4/F-LEAD. D-L1 to D-L3 are small fix-in-cycle candidates.
