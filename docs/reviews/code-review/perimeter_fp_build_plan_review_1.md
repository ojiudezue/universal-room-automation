# Plan review 1: PLANNING_perimeter_fp_build_2026_11.md

**Reviewed:** commit 92713266 (rev 1). **Mode:** Tier 2-DB, one adversarial plan review (CLAUDE.md "Plan Review — TIERED").
**Reviewer:** ura-planner, 2026-11-08. Greps re-run on develop in the main checkout; the plan's own lists were treated as hypotheses.
**Docs read:** the plan in full; the code ranges cited below. HVAC and presence state-of-play docs not read: no HVAC or room-occupancy surface is touched (agreed with the plan's header). Memory `reference_protect_face_latency_async` read in full (it decides H4).

**Verdict: FIX-PLAN-FIRST.** Fixes applied to the plan as rev 2 in the same commit. After rev 2 the plan is BUILD.

**Scope verdict:** BROAD, not creeping. D7 (NM, WhatsApp truth) and D10 (egress cameras) are independent of the FP gates; they stay in the cycle but rev 2 asks for separate commits so either can be reverted alone.

---

## Findings

### HIGH

**H1. D5's settle wait is not inside the in-flight guard.** The plan says the settle runs "inside the existing in-flight guard so the second engine's edge cannot start a parallel dispatch". But `_dispatch_in_flight.add(cooldown_key)` happens at perimeter_alert.py:1509, after burst (:1295), snapshot (:1339) and enrichment (:1470). A settle placed after burst (gate order §3 item 2) runs with the key not yet in flight. The cooldown is reserved only after a successful dispatch, so the in-flight check at :1149 and the cooldown at :1110 both pass. The second engine's edge, which is the corroboration the settle waits for, then starts its own handler and dispatches at full severity. The first handler wakes, sees corroboration, and dispatches too. Result: two pages for one person. Bug class: Concurrent dispatch race / guard placed after the await.
*Repro:* switch on, rear_ptz eligible, Protect edge at t=0 (first alert), Frigate `_2` edge at t=+5 s, settle 8 s. Two `exterior_person` NM rows.
*Fix (rev 2):* add `cooldown_key` to `_dispatch_in_flight` before the settle `await`. Discard it on every exit from the settle: teardown, `is_stopping`, exception, and the hand-off to the normal :1509 path. Add a test that fires the sibling edge during the settle and asserts exactly one `async_notify` call.

**H2. D5's "first alert" test reads a field that is 0 on three early-return paths.** D5.4 uses `prior_alerts_in_window == 0` from the burst decision. `_evaluate_burst_demotion` initialises that field to 0 (:2235) and returns before counting when the gate is disabled (:2243), exemption-held (:2269) or outside the night window (:2288). With `PERIMETER_BURST_NIGHT_ONLY=True` (D4 NO-GO, or before the flip), every daytime alert reads "first", so D5 demotes repeats too, and the D5 acceptance bullet "repeat alert → unchanged by D5" fails in daytime.
*Repro:* 13:00, NIGHT_ONLY=True, a second rear_ptz alert 10 min after the first, Protect-only, eligible → D5 demotes it.
*Fix (rev 2):* D5 counts prior dispatched alerts itself from `_recent_alerts_by_camera` (:330, :2296) over `PERIMETER_BURST_WINDOW_S`. It does not read the burst decision. Add a test at 13:00 with NIGHT_ONLY=True.

**H3. `_rescan_siblings` re-subscribes the excluded camera leg after every boot.** perimeter_alert.py:2516-2549 runs once after HA_STARTED. It subscribes every resolver person leg not already in `_sensor_to_camera`. The camera-level Frigate leg that D1 deliberately dropped is not in that dict, so it gets subscribed and the street walker alerts again. That breaks INV-ZONE-LEG on every restart, and the D1 Live check would fail an hour after the deploy that enabled it. D1's site list (item 5) covers key derivation only and misses this wiring site. Bug class #53 (one missed site).
*Fix (rev 2):* D1 lists every wiring site and applies the same exclusion predicate at each: base union :490, resolver legs :493-497, `_2` safety net :504-512, legacy fallback :543-546, and `_rescan_siblings` :2532-2544. The check is one helper, `_is_excluded_zone_camera_leg(cam, eid, engine)`. Add a test that runs `_rescan_siblings` and asserts the `_2` leg stays unsubscribed.

**H4. D10.2's resident demote would act on a stale or latched face name.** Protect resolves a face name 40-80 s or more after the detection, and the websocket never pushes it (memory `reference_protect_face_latency_async`, measured 2026-08-29). At dispatch, the face leg for the current crossing usually has no name yet. What it may hold is a name latched from an earlier crossing. The freshness filter at :1419-1425 drops only legs older than the latch TTL and keeps legs with no timestamp ("lenient, display-only"). That is fine for an annotation and wrong for a severity decision. A stranger at the door within the latch TTL of a resident's earlier crossing is demoted to LOW under the resident's name. The plan's own open question 3 says the 0.9 egress identity probably lands after dispatch.
Marginal benefit: the plan says it "fires only on Protect-named faces" and "most resident crossings will still alert". The contextual LOW for home_day already covers the common daytime case (const.py:2589). The benefit is small, and the failure demotes a real stranger.
*Fix (rev 2):* D10.2 is PARKED. Revival trigger: an identity matched to the detection time (leg `event_start` within a named window of the edge) is readable before dispatch, measured by a probe. The "Identified" annotation is unchanged.

**H5. With D10.1 as written, co-viewing egress cameras still suppress each other.** D10.1 ignores only stamps whose key equals the alerting camera's key. madrone_g6_entry and front_door_aerial are adjacent (const.py:2734) and both watch the front entry. A visitor stamps egress on both. Each camera's own alert is then suppressed by the other camera's stamp, inside 120 s. D10's goal and its Live criterion fail for exactly the cameras in scope.
*Fix (rev 2):* when the alerting camera is dual-role (in both lists), stamps from any dual-role camera are ignored. Stamps from egress-only cameras (garage_a_2/b_2) still suppress. Perimeter-only cameras keep today's rule against all stamps. INV-EGRESS-SELF is restated to match. New test: `test_egress_dual_role_cross_stamp_not_suppressed`.

**H6 (found while folding in the operator's D10 policy). LOW does not mean "not pushed".** `exterior_person` is in `NM_SECURITY_HAZARDS` (const.py:2542). Any alert carrying a snapshot sets `_force_immediate_for_security_image` (notification_manager.py:1557-1560), which forces IMMEDIATE delivery (:1904-1909). Its channels then come from the per-person severity gate (:1888). So every LOW demote in this plan (D3/D4/D5/D6/D10.5) still pushes on whatever channels each person allows for LOW. The operator's "logged, not pushed" is not what LOW does today. *Fix (rev 2):* a config-first precondition. A read-only check of each person's LOW gate for `exterior_person` runs first; "no push" becomes a matrix setting, and if the matrix cannot express it, that gets a card. No second suppression path is added in this cycle.

### Operator additions (2026-11-08), folded into rev 2
- **D10 policy:** became D10.5. It pages only when the person is unknown AND corroborated. It reuses the `ura_person_egress_event` bus event (transit_validator.py:2005), `_resolve_face_legs`, `known_face_guests`, the `_recent_fires` NVR-family check and `has_recent_adjacent_activity`. When the second NVR is down it falls back to unknown-only. A bounded 90 s identity wait carries three explicit discharges: a known identity arrives, the deadline passes, or teardown. Demote-then-upgrade is parked. Doctrine conflict, flagged and not resolved: §5.5(a) allows de-escalation only at ≥ 0.9, so Frigate-only face matches still page. That is an operator decision (open Q6).
- **D11:** added as a Tier-3 deliverable on its own branch. It reuses `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`; no `SIGNAL_CAMERA_LIST_CHANGED` exists. Finding inside it: `async_discover` clears its maps before awaiting (camera_census.py:1057-1069), so a live rerun would hand `[]` to the occupancy path (sensor.py:2809, presence.py:5006/5014). The fix is an atomic build-then-swap `async_rediscover`. A single orchestrator fixes the order: rediscover, then perimeter rewire, then the transit signal.
- **sonoffwindow:** confirmed in the live registry. It is the same device as the camera, bare and Frigate. It wires as the configured base, tagged `frigate`. Side effect: a false "no `_2` sibling" WARN every boot (:513-525). Noted, not built.

### MEDIUM

**M1. D1 key overlay ordering and value.** The F7 tripwire (:573-584) and the linker allowlist (:607-612) call `_camera_key_for_sensor` during `_wire_camera`. So `_zone_key_overrides` must be filled before the first `_wire_camera` call, or the tripwire WARNs and the zone key is missing from the allowlist. The overlay value must also equal the lowercase Frigate camera name. That name is the key of `_frigate_last_event_id` (:806, read at :1779 and :3450) and of the new D2 cache. *Fix:* both requirements are stated in D1.

**M2. D1 map rung (a), the private Frigate config read, is the wrong trade.** It reads a private shape (`hass.data["frigate"][entry]["config"]`), and whether Frigate is loaded at URA setup depends on load order. The plan deliberately adds no dependency (the D9 reasoning). So the map can resolve differently from one boot to the next. The prefix rung plus an alias entry already cover every case, and open question 1 says the HomeLab naming convention makes the prefix exact. *Fix (SIMPLIFY):* drop rung (a). The prefix match is first, then the alias. Rung (a) is parked with a revival trigger: zone names that follow no convention and cannot be aliased.

**M3. D3 compares a sensor slug with a Frigate zone name.** `entered_zones` holds Frigate zone names. The D1 map holds HA sensor slugs. *Fix:* compare `slugify(name).lower()` on both sides, and test with a zone name that has a capital letter.

**M4. The D5 tracker cannot evaluate lazily from `_recent_fires`.** `_record_leg_fire` prunes `_recent_fires` to the last 60 s on every write (:2496). By the time the +60 s evaluation runs, the −60 s half of the window can already be gone. *Fix:* at alert time, record `(alert_ts, other_family_seen_in_lookback)`. At +60 s, add a forward scan, or use the next-fire hook. Also, the plan does not cite existing prior art: `_leg_fire_counts` / `_leg_sole_fire_counts` (:320-321, :2492-2510), surfaced at :2455-2470. They count edges per engine, look only backward and are not persisted, so they cannot serve as the tracker, but the institutional section must say why. Added to §0.2.

**M5. D7 item 2 over-specifies the six callers.** Only :2044 appends to `channels_fired` and logs. :5443 (`sent_any`) and :5470 (`sent`) gate the digest. :3102 (CRITICAL repeat), :4475 (menu reply) and :5796 (test send) do neither. Read literally ("all six ... log_notification only on True") the plan tells the builder to add new DB rows at three sites. The dry-run early return (:2450) has no specified result either. *Fix:* the plan gives a per-site table. Dry-run returns `True`, which keeps today's appends.

**M6. D7.4: `channels_fired` is per notify, not per recipient.** It is declared once at :1831, outside the person loop, so "use `channels_fired` for that recipient" would leak earlier recipients' channels. The change also alters `delivered` and `bucket_outcome` on persisted audit rows for every channel (:2088-2125). The D4a/D8 probes and the D1/D10 Live checks read those rows. *Fix:* build a per-recipient `fired_for_person` list. Record the semantic change and its first-row timestamp in the README so probes do not straddle it.

**M7. D10 config turns on deep-night vehicle alerts for the doorbells.** Vehicle and animal legs are wired from `perimeter_infos` (:827-858). Adding the three cameras to `perimeter_cameras` subscribes their vehicle legs. That reintroduces the "Garage_Doorbell_Vehicle" street noise at night, which D10.3 says is not built. *Fix:* dual-role cameras are skipped in the vehicle loop until PERIMETER-EGRESS-VEHICLE-ANIMAL-1 decides. Animal legs stay: they feed the linker only.

**M8. INV-FP-DEMOTE-ONLY is false as written.** It claims defaults are byte-identical, but D4's GO flip changes a default, D7 has no knob and changes `channels_fired`/log rows whenever the bridge is down, and D5's teardown during a settle drops a dispatch. *Fix:* carve-outs for D4 GO, D7 and teardown/shutdown are written into the invariant, so reviewer D can falsify the rest.

**M9. The vehicle path is not fenced.** It has its own severity (:2835-2853) and its own enrichment call (:2909). If the builder changes `enrich_dispatched_alert`'s default prompt instead of adding the verdict variant, D6 reaches vehicle alerts. *Fix:* non-goal plus a test: the vehicle enrichment call and its message are byte-identical with D6 in shadow or enforce.

### LOW

- **L1.** Rung labels: switches and the select are rung 3 (entity), not rung 2. Fixed in D3, D5, D6 and §4.
- **L2.** Unnamed numbers: the D2 24 h rolling window, the D5 Store delayed-save delay, the D10.1 window (existing `EGRESS_SUPPRESSION_WINDOW_SECONDS`, now cited). Named in rev 2: `PERIMETER_FRIGATE_BUS_WINDOW_S = 86400`, `PERIMETER_AGREEMENT_SAVE_DELAY_S = 30`.
- **L3.** D6 item 2 offers two mechanisms (the `prompt=` kwarg and `enrich_with_verdict`). Rev 2 picks one: `enrich_with_verdict` wraps `enrich_dispatched_alert(prompt=_VERDICT_PROMPT)`.
- **L4.** The census full scan (camera_census.py:1133) would admit every `*_person_occupancy` zone sensor as a camera, but only on installs with no configured camera lists (:1063-1072). Not this house. Noted for portability under D1.
- **L5.** D7's public config-entry check adds nothing when `has_service("wa_bridge","send_message")` already picked that domain. Harmless. Kept, marked as defensive.

---

## Checklist results

| Check | Result |
|---|---|
| Institutional context complete | Mostly. Missing the `_leg_sole_fire_counts` prior art (M4); added. Greps re-run: `zone_agree/single_source/vlm/ZONE_SENSORS` no perimeter hits confirmed; only `CENSUS_AGREEMENT_SINGLE="single_source"` const.py:2348 (different meaning, string reuse is harmless). |
| Invariants falsifiable | Yes, after the M8 carve-outs. INV-EGRESS-SELF restated (H5). INV-ZONE-LEG was falsified by H3. |
| Severity / suppression / dispatch sites (person) | Re-enumerated: egress return :1090, cooldown return :1135, in-flight return :1161, contextual :1190/:1199, linker coercion :1247-1281, burst :1302-1314, NM-absent return :1462, dispatch :1509-1638 (immediate or `async_call_later` :1635), teardown short-circuit :1513. The plan's gate slots are correct. The missed one is the in-flight placement (H1). |
| Vehicle leg | Severity :2835-2853, enrichment :2909, dispatch :2944-3033, own cooldown and in-flight (:2785-2800). Not fenced in rev 1 (M9). |
| Digest paths | Animal: linker feed only (:2620, :941), no NM. Vehicle out of hours: digest-only (:2761, :2823). NM person digest :5420-5480, covered by D7. None of the new gates reach them, which is correct. |
| D1 sensor→camera sites | Plan's 12 key sites confirmed. Missing: 5 wiring sites (H3), `_camera_class_for_sensor` :1711 (routes through `_camera_key_for_sensor`, OK), `_frigate_last_event_id` :3450 reader (M1), census full scan (L4). |
| D7 six callers | Confirmed :2044, :3102, :4475, :5443, :5470, :5796 in domain_coordinators/notification_manager.py; no callers outside NM. Per-site semantics differ (M5). |
| Knob ladder | All numbers named after L2; rung labels fixed (L1). |
| Acceptance discriminates | Mostly. D1, D3, D6 and D7 have explicit discriminators. Added: H1 one-notify test, H2 daytime-repeat test, H3 rescan test, H5 cross-stamp test. |
| Non-goals explicit | Yes; vehicle-path fence added (M9). |
| D9 revival trigger | Present and evaluable (second install, or D2's bus-silent WARN). |
| Marginal benefit | D10.2 fails it (H4, parked). D1 rung (a) fails it (M2, dropped). D3 is honestly justified as shadow-first. |

## Statistics

| Severity | Found | Fixed in plan rev 2 | Deferred |
|---|---|---|---|
| HIGH | 6 | 6 (H6 as a config-first precondition) | 0 |
| MEDIUM | 9 | 9 | 0 |
| LOW | 5 | 4 | 1 (L5 kept by choice) |

## Bug-class frequency

| Class | Findings |
|---|---|
| #53 one missed site | H3, M7, M9 |
| Guard placed after an await / concurrent dispatch | H1 |
| Default-value read as evidence (early-return field) | H2 |
| Display-grade data used for a trust decision | H4 |
| Wrong-scope comparison (key equality too narrow) | H5, M3 |
| Over-specified brief (instruction would add behaviour) | M5 |
| Per-call vs per-recipient scope | M6 |

**QUALITY_CONTEXT candidate:** "default-initialised decision field consumed downstream" (H2). A decision dict whose fields keep their initial values on early returns should not feed another gate. The consumer recomputes the value or the producer marks the field unset. Recommend adding it after the build confirms the pattern.
