# Plan review: interior ledger floor (§1b), framing 1 COMPLETENESS, 2026-11-17

Target: `docs/planning/PLANNING_vision_interior_sightings.md` §1b (:54-294), knobs :919-920. Base: develop @ ef6149950.
Presence/HVAC state-of-play docs not required (no presence-sensor or HVAC surface touched beyond room records).

**Verdict: PLAN-FIX-REQUIRED**

| # | Sev | Finding |
|---|---|---|
| 1 | HIGH | Q4 Select decision (:294) is bolted on, not integrated. §1b.2 (:95), INV-IV-FLOOR (:153-163), F-D0 measures (:176-190), F-D1 helper/tests (:194-212), knob tables (:245-252, :919) and Q4 row (:1100) all still specify min-only. Missing: `window_max` window length and its knob, Select persistence/restore (RestoreEntity / Number-persistence path), which value lifts while the Select is unavailable at boot, INV clause for strategy switch mid-window, tests + mutation for the switch, and per-strategy D0 gates. "`interior_floor` rows" do not exist; the plan defines only `interior_lift` rows (:218). |
| 2 | HIGH | Premise: `AUDIT_arc_day_validation_2026_11_17.md:20` — 19/19 terms `applied=false reason=unknown`. `reason="unknown"` is emitted only when `state == STATE_UNKNOWN` (`crossing_ledger.py:446`), so the ledger was never `known` all day. The floor acts only while known (:112, :127), so it is inert today and F-c (:180) measures against a near-zero known fraction. Plan must name this dependency, require a ledger-known-fraction gate in F-D0, and card the never-known root cause first. |
| 3 | MED | Stale anchors: `CrossingVisionShadow.census_tick` is now `crossing_vision.py:1859` (plan :214, :285 say 1222-1235; v5.108.36 + ships moved it, +872 lines); interior_vision helpers drifted (+12: `member_liveness` :61, `group_bodies_nvr` :78, `group_liveness` :100, `build_room_records` :149). Re-anchor on current develop; base c6230ade (:61, :163) is obsolete for the byte-identical clause. |
| 4 | MED | Contract §6: the plan's conformance table (:400-428) has no ledger-floor row — new F4→F2 path via `L`, crossing_vision as a new pinned reader of `get_room_sightings` (`_layer_guard_engine.py:244-247`; plan cites :121 / test :610, actual pin dict :244, test :632), seam with crossing plan P2-D2 owner. |
| 5 | MED | Foyer overlap → Frigate `foyer_floor` zone (arc map :157) absent from §1b; F-b (:178) and the overlap list (:101) omit foyer. State the zone's dependency (Frigate restart before D0 replay is meaningful) and whether D0 data pre-dates it. |
| 6 | LOW | F-D3 "RAM latches" + restart: input-zero window (24 h) resets on every restart; state that consequence. |

Holds: lift/credit mechanics match `crossing_ledger.py:345-417`; non-goals explicit (:256-261); rung-1 knobs justified; no parked-plan trigger found (grep of docs/planning).
