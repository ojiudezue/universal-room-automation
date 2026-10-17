# EC storm Stage E: `.preonset_floor` test-reference classification (Rev 3 N3)

Plan: `PLANNING_ec_storm_stage_e.md` §E2 acceptance ("Test-reference classification").
File: `quality/tests/test_ec_stage_b_preonset_precharge.py`. Classified BEFORE editing, against the
§E2.4 split: **TARGET** = the value (`preonset_target`, set across the 12 h buy horizon);
**REGISTERED** = the floor actually registered this tick (`preonset_floor`, INV-8 (i) `now >= T − 4 h`
or (ii) `now >= min(S)`).

Shared fixture change (expected diff): `WSW` Onset 15:00 → **05:00** (2 h ahead of `NOW` 03:00). INV-9
buys only in the frozen schedule S (h_req cheapest slots closest to T); with SOC 40 → target 80,
h_req = 2, S = {03:00, 04:00}, so every "buy at NOW" assertion keeps its meaning and every `WSW` floor
assertion is REGISTERED (inside both (i) and (ii)). The 12 h case moves to the Stage E tests.

| Ref (test) | Situation after the change | Class | Assertion change |
|---|---|---|---|
| `test_preonset_floor_registered_before_onset` (:555) | 18:00, Onset 21:00 (3 h), option off | REGISTERED | none |
| `test_preonset_handoff_at_onset` (:566, :569) | 20:00 (1 h); then active full hold | REGISTERED | none |
| `test_preonset_floor_none_outside_lead` (:577, :581) | 19 h / 12 h 01 m ahead: both None | REGISTERED | none |
| same (:583) | exactly 12 h ahead | **TARGET** | `preonset_target == 80`, `preonset_floor is None`, `_tick_reserve_floor is None` (plan-stated diff) |
| `test_preonset_lead_zero_disables` (:591, :595) | lead 0 → None; Onset 04:00 at 03:05 | REGISTERED | none |
| `test_preonset_watch_floor_uncorroborated` (:602, :607) | watch Onset 09:00 → retimed **05:00** | REGISTERED | retime only (6 h would be value-only and no buy) |
| `test_preonset_forecast_raise_only` (:616, :620) | `WSW` (2 h), option off | REGISTERED | none (fixture retime) |
| `test_preonset_polygon_excluded` (:629) | polygon: None | REGISTERED | none |
| `test_preonset_partial_hold_takes_max` (:641) | WSW +10 h → retimed **+3 h** | REGISTERED | retime only (+10 h registers nothing) |
| `test_preonset_precharge_gates` (:722) | every refusal case | **TARGET** (+ REGISTERED where Onset ≤ 4 h) | `preonset_target is not None` always; registered asserted except `not_bottom` / new `hour_not_in_schedule`. Onsets 09:00 → 05:00 (ineligible, uncorroborated watch), 13:00 → 04:00 (degraded_stale) |
| `test_preonset_negatives_not_classify_error` (:761, :763) | 20 h → None; then 11 h ahead | :761 REGISTERED; :763 **TARGET** | `preonset_target == 80`, `preonset_floor is None` |
| `test_preonset_memory_survives_feed_loss` (:920) | `WSW` (1 h at 04:00) | REGISTERED | none (fixture retime) |
| `test_reserve_row_carries_tick_preonset_floor` (:980) | 18:00 / 21:00 | REGISTERED | none |
| `test_preonset_config_extremes` (:996) | `WSW` (2 h) | REGISTERED | none (fixture retime) |
| `test_preonset_uncorroborated_watch_partial_gt_knob` (:1004) | watch 6 h ahead | **TARGET** | `preonset_target == 90` |
| `test_preonset_floor_reads_live_slider` / `_slider_extremes` (:1095-1113, `_tick_reserve_floor`) | `WSW` (2 h) | REGISTERED | none (fixture retime) |
| `test_preonset_buy_reports_forecast_confirmed_fusion_direct` (:1337) | fusion direct | TARGET + REGISTERED | Onset +6 h → +1 h; passes `_tou` + `preonset_buy_schedule={}`; asserts `preonset_target == 80` and `preonset_floor == 80` |
| `test_review_c_active_full_hold_shadows_prepare_fields` (:1688) | active full hold | REGISTERED | none |
| `test_inclement_preonset_attr_shape` (:948-960) | attr | (attr) | rewritten to the new exact dict; adds the 4-12 h `active: false` case |
| other retimes (no `.preonset_floor` ref) | `reason` text 15:00 → 05:00; `reached_never_reengages` wsw2 14:00 → 05:00; `blind_hold_and_release` 11:00 → 05:00; `degraded_fresh_decision_control` 13:00 → 05:00 | — | buy-timing moves to the schedule (plan) |

Number-entity / listener refs (:1046-1090) name the slider key, not the decision field: unaffected.
