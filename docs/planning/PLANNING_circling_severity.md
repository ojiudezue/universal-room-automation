# PLANNING — CIRCLING-SEVERITY-1

**Card:** CIRCLING-SEVERITY-1 (kanban.data.yaml)
**Thread:** perimeter
**Founding case:** live track `xt-000001-695c9e` observed during v5.62.1 live validation on 2026-08-08 09:22 CDT: `back_yard → front_side_ptz → back_yard → front_side_ptz → back_yard`, 5 hops / 2 cameras / 133s, classified `circling`, `alert_count=0`. Track linking was correct (one track, not five alerts). No page fired.

## Result of trace (do this FIRST — it changes scope)

**The founding case is fixed-by-CONSOL-1 in home_day/home_evening. The cycle collapses to VERIFICATION + TELEMETRY + two narrow operator decisions on the CONSOL-1 override's edges. There is no known un-fixed silencing path for `circling` on the person leg today.** This section is proof-of-work; the invariant + deliverables below rest on it.

### Gating path that produced alert_count=0 at v5.62.1

Under v5.62.1, `PerimeterAlertManager._on_perimeter_sensor_event` began with an **alert-hours existence gate** on the person path (a hard clock-time gate defaulting to 23:00–05:00 via `PERIMETER_BURST_NIGHT_WINDOW`-shape helpers). 09:22 CDT fell OUTSIDE that window → every event on the track returned before dispatch → `note_alert_dispatched` never called → `ExteriorTrack.alert_count` stayed at 0. Track linking was unaffected (the linker's `record_event` runs upstream of the alert manager), which is why the track existed but produced zero alerts. This matches the card's "probably correct-by-design (daytime + occupied + outside the 23:00-05:00 window)" hypothesis — but the hypothesis is now moot because CONSOL-1 removed that gate.

### What CONSOL-1 (v5.73.0) changed

- `custom_components/universal_room_automation/perimeter_alert.py:1032` — comment: *"(CONSOL-1 §D2) Alert-hours existence gate REMOVED for the person path. Severity is contextual (see §6 / D2 contextual severity function). Vehicle path retains its own window via `_is_in_vehicle_alert_hours`."*
- Person severity is now resolved by `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(house_state, camera_class, track_class, persons_home)` — a total function over all 9 house states with a `case _:` fail-safe returning `CRITICAL`.
- The function's circling override at `const.py:1596-1597`:
  ```python
  if cc == "perimeter" and tc == "circling" and hs in ("home_day", "home_evening"):
      return "HIGH"
  ```
- CRITICAL-first fail-safe at `const.py:1586-1587` short-circuits `away/vacation/sleep/home_night` to `CRITICAL` *before* the override even runs — so `circling` in those states pages at CRITICAL, not HIGH.
- `waking + perimeter` → `CRITICAL` (`const.py:1627-1628`); `arriving` → `MEDIUM` regardless of `circling` (`const.py:1620-1622`); `guest` → `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` regardless of `circling` (`const.py:1631-1632`).
- HIGH is a real page: DND-bypass and full channel routing are keyed off `severity in (Severity.CRITICAL, Severity.HIGH)` at `notification_manager.py:1584` and `:3668`.

### Continuation coercion never demotes circling

`perimeter_alert.py:1119-1206` (§4b severity-map coercion, Tier 3 fix-up):

- **First alert of any track (`alert_count == 0`)** → coercion is skipped, contextual severity is kept as-is (`:1171-1173`).
- **Continuation + `approach`/`circling`** → coerced value from `NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP` may only RAISE, never lower (`:1188-1199`). The map's `home_day/circling = MEDIUM` (`const.py:1757`) is below the contextual `HIGH`, so severity stays HIGH.
- Kill switch: `TRACK_LINK_WINDOW_S == 0` disables the whole block (`:1139`), and the operator "Path Aware Notifications" switch `linker.smart_alerts_enabled` (`:1143`) disables just the judgment layer — both fall through to the contextual severity, which still pages on `circling` in home_day.

### alert_count = 0 is now impossible for `circling` in the founding scenario

`ExteriorTrack.alert_count` (`exterior_track_linker.py:103`) is incremented **only** by `note_alert_dispatched` (`:795`), which is called **only** from `perimeter_alert.py:1424` **inside the successful-dispatch branch** (after `nm.async_notify` succeeded and cooldown was reserved at `:1408`). Under CONSOL-1, the person path no longer has any pre-dispatch existence gate; the only paths that skip dispatch are:

1. Egress-suppression window (`:1038-1047`, `EGRESS_SUPPRESSION_WINDOW_SECONDS`) — only after a household egress within N seconds; irrelevant to a mid-morning perimeter loop with no egress.
2. Per-camera cooldown (`:1053-1065`, `PERIMETER_ALERT_COOLDOWN_SECONDS = 300`) — this fires only for the *2nd* hop on the same camera within 5 min. In the founding shape (2 unique cameras alternating), each camera's *first* hop dispatches; cooldown only mutes the re-hits. Result: `alert_count ≥ 2` (once per unique camera), not 0.
3. In-flight guard (`:1073-1079`) — same-camera re-fire during an outstanding async dispatch; not a silencing path across the track.
4. NM disabled (`:1311-1317`) — a config-level dead-letter; would silence *all* perimeter alerts, not `circling` specifically.

## Institutional context verified

### Greps run

- `rg -n 'circling|CIRCLING' custom_components/universal_room_automation/` → 3 files:
  - `const.py` (contextual severity override :1596, severity map :1751-1780, classifier threshold :1727)
  - `exterior_track_linker.py` (`classify` :681-704 producing `"circling"`, `alert_count` :103, `note_alert_dispatched` :777-797)
  - `perimeter_alert.py` (early classify for severity :1093-1106, continuation coercion :1152-1199, comment "approach/circling still alert" :1415, `note_alert_dispatched` call site :1424)
- `rg -n 'alert_count' custom_components/universal_room_automation/` → 1 write site (`exterior_track_linker.py:795`). **Sole increment path.**
- `rg -n 'note_alert_dispatched' custom_components/universal_room_automation/` → 1 caller for the person leg (`perimeter_alert.py:1424`, inside the `dispatched_ok=True` branch) and 1 for the vehicle leg (`:2556`).
- `rg -n 'PERIMETER_BURST_NIGHT_WINDOW|_is_in_alert_hours|_is_in_vehicle_alert_hours' …` → burst-demote night window still uses `(23,5)`; person alert-hours existence gate is gone; vehicle alert-hours gate is kept (§D6).
- `rg -n 'Severity\\.HIGH|Severity\\.CRITICAL' domain_coordinators/notification_manager.py` → HIGH and CRITICAL both bypass DND / non-critical gate at `:1584`, `:3668`; `:1502` starts ack/repeat only for CRITICAL. HIGH pages but does not repeat — acceptable for `circling` per the CONSOL-1 §6 intent (the override deliberately returns HIGH, not CRITICAL, in home_day/home_evening).

**REUSED (no new primitives proposed):**
- Contextual severity resolver — `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` at `const.py:1556-1635`.
- Circling classifier + `alert_count` — `exterior_track_linker.py:681-704` / `:103`.
- Severity map — `NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP` at `const.py:1751-1780`.
- Dispatch bookkeeping — `note_alert_dispatched` at `exterior_track_linker.py:777` (sole write to `alert_count`).

**NEW:**
- One diagnostic sensor exposing `circling` tracks-with-zero-dispatches over the last N hours (see D3). Justified because no existing sensor surfaces this — the founding-case defect was invisible except by manual DB inspection.
- One regression test module replaying the founding-case shape end-to-end (see D2). No existing test drives `circling → note_alert_dispatched` from a real per-camera event sequence.
- (Conditional on operator decision O2) widening the contextual override's house-state set beyond `{home_day, home_evening}`.

### CONSOL-1 severity table rows for `circling` (verbatim)

From `const.py:1596-1635` (override + relevant house-state arms) and `:1751-1778` (severity map, "person" section):

```python
# const.py: contextual severity function, circling-relevant rows
if hs in ("away", "vacation", "sleep", "home_night"):
    return "CRITICAL"                                              # circling → CRITICAL (fail-safe wins)
if cc == "perimeter" and tc == "circling" and hs in ("home_day", "home_evening"):
    return "HIGH"                                                  # ← the override
if hs == "arriving":
    return "MEDIUM"                                                # circling not escalated
if hs == "waking":
    if cc == "perimeter":
        return "CRITICAL"                                          # circling → CRITICAL (perimeter arm)
    return "MEDIUM"
if hs == "guest":
    return NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY                # circling not escalated
# case _: unknown / None
return "CRITICAL"

# const.py: NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP["person"] — used only for CONTINUATION coercion
"away":       {"pass_by": "MEDIUM",   "approach": "HIGH",     "circling": "CRITICAL"}
"sleep":      {"pass_by": "MEDIUM",   "approach": "HIGH",     "circling": "CRITICAL"}
"vacation":   {"pass_by": "MEDIUM",   "approach": "HIGH",     "circling": "CRITICAL"}
"home_night": {"pass_by": "LOW",      "approach": "MEDIUM",   "circling": "HIGH"}
"home_day":   {"pass_by": "DIGEST",   "approach": "LOW",      "circling": "MEDIUM"}
# NB: no home_evening / arriving / waking / guest rows → coercion no-ops for those states
```

### Docs read

- `docs/planning/PLANNING_consol_1_alerting_llmvision.md` — CONSOL-1 §D2 (contextual severity replaces alert-hours), §6 (rev-2 TOTAL table + circling override scope).
- `docs/reviews/code-review/v5.73.0_consol_presetflap_nmbb.md` — CONSOL-1 review record; confirms circling override was **deliberately narrowed** to `{home_day, home_evening}` after plan-review A1 (2026-08-11) rejected a wider collapse as "fabricated citation." Any widening here must justify itself, not treat that narrowing as an oversight.
- `docs/readmes/README_v5.73.0.md` — ship notes for CONSOL-1.

### Memory bodies pulled

- `feedback_no_fabrication.md` — informs the "verify override scope in source before proposing to widen it" posture below.
- `feedback_marginal_benefit_pushback.md` — the D0 operator decision is intentionally framed as "what MARGINAL coverage does widening buy" rather than "widen by default."
- `feedback_suppression_needs_discharge.md` — reviewed for the diag sensor's reset semantics (D3).

### Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/exterior_track_linker.py` — classify (:681), alert bookkeeping (:777), ExteriorTrack (:95).
- `custom_components/universal_room_automation/perimeter_alert.py` — `_on_perimeter_sensor_event` (:1030-1450), severity resolver (:1463-1495), burst-demote (:1828-1990), vehicle leg for parallel-structure sanity (:2331-2570).
- `custom_components/universal_room_automation/const.py` — CONSOL-1 §6 function (:1556-1635), severity map (:1751-1780), classifier constants (:1727-1735), night-window (:1458).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` — HIGH/CRITICAL routing sites at :1502, :1584, :2004, :3668.

## Falsifiable invariant (up front)

State ONE and only one. The three options below are ordered wide→narrow. Recommended = **INV-M**; operator picks at kickoff.

- **INV-S (strong):** *A track classified `circling` NEVER produces `alert_count == 0` in any reachable house state, provided NM is enabled and the track has ≥1 event.* — Bans silencing circling everywhere, including `guest` and any future state. Requires either widening the CONSOL-1 override or a separate floor. Directly conflicts with the CONSOL-1 §6 rev-2 narrowing.

- **INV-M (medium — recommended):** *A track classified `circling` at a perimeter camera dispatches at least once (`alert_count ≥ 1`) in every house state EXCEPT `guest`, provided the linker + NM are enabled.* — Preserves the intentional `guest` carve-out; forces `arriving` (currently MEDIUM, dispatches but is the softest state) into scope for verification and forces us to prove home_day/home_evening/waking/away/vacation/sleep/home_night all fire.

- **INV-W (weak — verification-only cycle):** *In `home_day` and `home_evening`, a `circling` perimeter track dispatches at least once at severity ≥ HIGH.* — Exactly the founding-case shape. Cleanest bar to prove; leaves every other house state's `circling` behavior implicit (relies on the CRITICAL fail-safe rows to cover them).

**Operator decision O1: pick INV-S / INV-M / INV-W before build dispatch.** Default if silent = INV-M.

## Independent enumeration — every consumer of the `circling` classification

Regenerated by direct grep (do not trust the plan's list; reviewer re-runs `rg -n 'circling|CIRCLING'`):

1. **Producer:** `exterior_track_linker.py:681-704` `classify()` — returns `"circling"` when `revisit_count ≥ 1` OR (`camera_count ≥ EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS=3` AND `_is_non_monotonic(cams)`).
2. **Severity resolver early call (person, first alert path):** `perimeter_alert.py:1099-1111` — passes `track_class="circling"` into `_severity_for_current_house_state`.
3. **Contextual severity override:** `const.py:1596-1597` — the `HIGH` return in `{home_day, home_evening}`.
4. **Continuation coercion — RAISE branch:** `perimeter_alert.py:1188-1199` — coerced severity may only raise for `classification in ("approach", "circling")`.
5. **Severity map values (continuation lookup only):** `const.py:1753-1770` — `"circling"` column for `person` × 5 house states.
6. **Track bookkeeping:** `exterior_track_linker.py:795` writes `alert_count += 1`; :103 field default; :771 attribute exposed in `snapshot()` for diagnostics.
7. **Path narrative:** `perimeter_alert.py:1286-1306` — narrative enrichment runs for any multi-hop track; not classification-specific, but the founding case's message would have said "Person track — back_yard → front_side_ptz → back_yard → ..."
8. **Vehicle leg parallel — NOT in scope:** `perimeter_alert.py:2359-2378` uses `owning.alert_count > 0` as a demote-signal for cars but does NOT gate on `"circling"` classification. Named here so reviewer B confirms no cross-leg contamination.
9. **Constant:** `const.py:1727` `EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS = 3` — the classifier threshold.

Anywhere `circling` is *consumed* other than the sites above is a defect this plan does not cover — reviewers must add it to the enumeration.

## Numbers on the knob ladder

| Number | Current value | Rung | Rationale |
|---|---|---|---|
| `EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS` | 3 | **Module constant** | Changing this changes what `circling` *means*; drift must be review-visible. Not exposed. |
| `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` circling-override house-state set `{home_day, home_evening}` | as-is | **Module constant** (embedded in the function body) | Semantic policy — pinned by test rows per house state. Widening requires code review + a new pinned row per added state. If operator chooses O2 to widen, the widened set stays in code, not in options. |
| `NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP["person"]["…"]["circling"]` | see verbatim table above | **Module constant** | Same reason as above; every row test-pinned. |
| `PERIMETER_ALERT_COOLDOWN_SECONDS` | 300 | **Module constant** (existing) | NOT touched by this cycle. Cooldown interaction with a circling loop is a documented, intentional property (D2 acceptance criterion). |
| Diag-sensor lookback window (D3) | 24h | **Module constant** (new) | Behavioral observation window; if operator wants to tune it live later, promote to a Number entity via a follow-up (Numbers-Get-Knobs: start at the lowest-ceremony rung that fits the change). |

Kill switch (existing): `TRACK_LINK_WINDOW_S = 0` disables the entire linker/coercion layer; contextual severity still fires. No new kill switch introduced.

## Operator decisions the plan needs

- **O1 — Invariant strength (INV-S / INV-M / INV-W).** Default INV-M. Decide at kickoff so reviewer D (adversarial completeness) knows exactly what to falsify.
- **O2 — Widen the circling override's house-state set?** Today: `{home_day, home_evening}`. Options: leave narrow; add `arriving` (currently MEDIUM); add `guest` (currently GUEST_SEVERITY constant). Marginal benefit is low — CRITICAL fail-safe already covers the states where `circling` matters most (away/vacation/sleep/home_night), and the CONSOL-1 review record explicitly rejected a wider collapse. **Recommendation: do NOT widen.** If operator disagrees, each added state needs its own test row and a rationale in the CONSOL-1 §6 revision note.
- **O3 — Should CONTINUATION events on a `circling` track have their own dedicated telemetry (a counter of "raised-by-coercion" hops), or is the diagnostic sensor (D3) sufficient?** Recommendation: D3 alone.

## Non-goals (explicit)

- Not changing `PERIMETER_ALERT_COOLDOWN_SECONDS` or introducing per-classification cooldowns. The 5-min per-camera cooldown is intentional; a circling loop of two cameras still produces ≥ 2 dispatches per 10-min window, which is the correct cadence.
- Not touching the vehicle leg (`_on_vehicle_perimeter_sensor_event`). CIRCLING-SEVERITY-1 is scoped to person.
- Not adding an ack/repeat engine to HIGH `circling` alerts. Repeats stay CRITICAL-only per CONSOL-1 §6 intent.
- Not adding runtime instrumentation to "learn" circling frequencies — the D3 sensor is a passive counter reading existing linker snapshots, not a new signal.
- Not re-introducing an alert-hours existence gate on the person path. CONSOL-1 §D2 deleted it deliberately; the whole point of the contextual severity function was to replace clock-time gating with state-aware severity.
- Not building any "monitor for N hours after ship" soak protocol. Event-count acceptance only.

## Deliverables

### D0 — Trace + operator decision confirmation (documentation only)

Publish the trace above (this doc's "Result of trace" section) as the trace artifact. Present O1/O2/O3 to operator; capture decisions inline before D1 begins. If operator picks INV-W and rejects widening (default), D4 shrinks to "verify home_day/home_evening only."

#### Acceptance Criteria
- **Verify:** operator's O1 pick recorded in this doc.
- **Verify:** O2 decision (widen / do-not-widen) recorded with rationale.

### D1 — Add regression test replaying the founding-case shape

New test module `quality/tests/perimeter/test_circling_founding_case.py`. Drives `PerimeterAlertManager._on_perimeter_sensor_event` with the exact founding-case event sequence (`back_yard`, `front_side_ptz`, `back_yard`, `front_side_ptz`, `back_yard`), house_state = `home_day`, `persons_home = 1`, real `ExteriorTrackLinker` instance (adjacency graph from `EXTERIOR_ADJACENCY_GRAPH`), spy NM. Asserts:

- `linker.classify(track) == "circling"` at end of sequence (i.e. the linker correctly attributes the loop).
- `track.alert_count >= 2` (one per unique camera on first hop; subsequent hops on same camera hit cooldown).
- Every dispatched severity is `Severity.HIGH` (CONSOL-1 override applies; continuation coercion may only raise, and the map's `home_day/circling=MEDIUM` is below HIGH, so it stays HIGH).
- The path narrative in the dispatched message contains all 5 hops in order (proves narrative enrichment on the founding-case shape).

**Wire-in anchor (mandatory):** the test asserts on `spy_nm.async_notify.call_args_list[i].kwargs["severity"] == Severity.HIGH` for at least one dispatched call — the enclosing behavioral anchor is `_do_dispatch`'s `nm.async_notify(**_kwargs)` at `perimeter_alert.py:1387`. Neuter drill: commenting out `perimeter_alert.py:1424` (`_linker.note_alert_dispatched(...)`) MUST make the `alert_count >= 2` assertion fail (proves the assertion is tied to the real write site, not a fixture-side counter).

#### Acceptance Criteria
- **Verify:** `pytest quality/tests/perimeter/test_circling_founding_case.py -v` all green.
- **Verify:** neuter drill — remove `perimeter_alert.py:1424` → the `alert_count` assertion fails with a specific error; restore.
- **Test:** `test_founding_case_home_day_dispatches_high`, `test_founding_case_alert_count_matches_unique_cameras`, `test_founding_case_narrative_lists_all_hops`.
- **Live:** covered by D4.

### D2 — Add per-house-state pin tests for circling severity

New test file `quality/tests/perimeter/test_circling_severity_per_state.py`. One test per house state in `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY`'s domain (9 states), calling the resolver directly with `camera_class="perimeter"`, `track_class="circling"`, `persons_home ∈ {0, 1, 2}` where the resolver's arm depends on it. Asserts exact severity name per row. This is a lock-file test: if a future edit changes the circling severity for any state, this test breaks loudly.

Rows pinned:
- `away/vacation/sleep/home_night` → `"CRITICAL"` (fail-safe rows).
- `home_day/home_evening` → `"HIGH"` (override).
- `arriving` → `"MEDIUM"` (row-7; circling NOT escalated — this is the intended behavior per CONSOL-1 §6 rev-2).
- `waking` (perimeter) → `"CRITICAL"`.
- `guest` → `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` (whatever the constant currently is — read at test time).

If operator chose O2 to widen, corresponding rows update as part of the same test file in D5.

#### Acceptance Criteria
- **Verify:** 9 rows × exact severity name; `pytest quality/tests/perimeter/test_circling_severity_per_state.py -v` green.
- **Test:** `test_circling_severity_<state>` × 9.

### D3 — Diagnostic sensor: circling-tracks-with-zero-dispatches (last 24h)

New sensor entity `sensor.perimeter_circling_zero_dispatch_24h` (URA convention: `sensor.<domain>_<metric>`). Reads `ExteriorTrackLinker` snapshots (existing `snapshot()` API at `exterior_track_linker.py:~750`), counts tracks where `classify(t) == "circling"` AND `alert_count == 0` AND `started_at` within the last `CIRCLING_DIAG_LOOKBACK_HOURS = 24` (new module constant, rung 1). Value = integer count; attributes = list of the offending `track_id`s (up to 10, newest first) plus `first_seen_at` for each.

**Why this exists:** the founding-case defect was invisible except by manual DB inspection. A non-zero value on this sensor is a live tripwire that a future regression re-introduces silencing.

**Reset semantics:** rolling 24h lookback based on snapshot iteration; no persisted counter that could de-sync across restarts. On restart, tracks that closed before restart are gone from the linker (per `TRACK_CLOSE_IDLE_S`), so the sensor naturally returns to 0 until a fresh offender appears — this is correct (an alert we can't retroactively fire isn't actionable). Documented on the sensor.

**Wire-in anchor:** update-callback registered on the same signal `ExteriorTrackLinker` already emits when a track is created/updated (do not add a new signal). Test: neuter the signal registration → sensor stays at 0 despite an injected zero-dispatch circling track → assertion fires. Restore.

#### Acceptance Criteria
- **Verify:** with the D1 test wired to spy NM but with `spy_nm.async_notify` raising, `alert_count` stays at 0, `classify == "circling"`, and the sensor value is 1 with the track_id in attributes.
- **Verify:** with a normal D1 run (dispatches succeed), sensor value is 0.
- **Sensor:** `sensor.perimeter_circling_zero_dispatch_24h` present in registry; state is integer ≥ 0; attribute `track_ids` is a list; attribute `lookback_hours` == 24.
- **Test:** `test_diag_sensor_counts_zero_dispatch_circling`, `test_diag_sensor_zero_when_dispatches_succeed`, `test_diag_sensor_neuter_drill`.
- **Live:** the sensor is 0 within 5 min of restart on a house with no offending tracks (baseline confirmed); if it ever goes non-zero, NM emits a `MEDIUM` anomaly (existing anomaly wiring pattern — reuse the URA anomaly detector, not a new pipe).

### D4 — Live validation table (post-deploy)

Replay the founding-case shape live: two operator-triggered walks between `back_yard` and `front_side_ptz` (5 hops total, ≤ 3 min) during `home_day`. Then table below is filled in on ship-day and written back into the README per CLAUDE.md.

| Criterion | Expected | Observed | Evidence |
|---|---|---|---|
| Linker attributes the loop to one track | `sensor.exterior_open_tracks` shows 1 person track with 5 hops | | linker snapshot attributes |
| Classification = `circling` | `classify(track) == "circling"` in track attributes | | `state_attr('…','tracks')[0]['classification']` |
| Severity = HIGH | ≥ 1 NM dispatch at HIGH within the walk | | NM log line `PerimeterAlertManager: NM notify dispatched … severity=HIGH` |
| Dispatch actually paged | Phone receives the alert | | phone notification screenshot |
| `alert_count ≥ 2` | attributed to the owning track | | linker snapshot `alert_count` field |
| Diag sensor stays at 0 | `sensor.perimeter_circling_zero_dispatch_24h` == 0 after the walk | | entity state |

### D5 (conditional on O2 = widen) — Update CONSOL-1 §6 override scope

If (and only if) operator picks O2 to widen: edit `const.py:1596-1597` to add the chosen state(s), extend D2's per-state pinned rows accordingly, add a §6 revision note to the CONSOL-1 planning doc explaining what changed and why (this note must NOT cite anything the operator didn't actually say — the earlier attempt at widening was rejected as "fabricated citation").

## Tier classification

**Tier 2-DB — three framing-disjoint reviews.** Justification: change touches severity routing on the person perimeter leg, which is cross-coordinator (linker ↔ perimeter_alert ↔ NM) and safety-adjacent (a false-negative here is a silent page loss). Per operator standing policy (2026-06-08), regression-prone work defaults to Tier 2-DB even when the DB triggers don't fire.

- **Review A — local correctness + per-row severity integrity.** For every one of the 9 house states, verify the resolver returns the pinned severity for `(cc="perimeter", tc="circling", ph ∈ {0,1,2})` and that no arm above it short-circuits incorrectly. Verify the continuation-coercion RAISE branch (`perimeter_alert.py:1188-1199`) cannot demote circling in any code path. Verify D3's counter reads the same `alert_count` field that `note_alert_dispatched` writes (single source of truth).
- **Review B — cross-coordinator / state-machine integrity + restart.** Trace: Frigate event → linker `record_event` → `classify` → perimeter_alert severity resolve → coercion → burst-demote → NM `async_notify` → `note_alert_dispatched`. Verify no double-emit on continuation. Verify D3 sensor state survives restart per its documented reset semantics. Verify the "smart_alerts_enabled" switch does NOT silence HIGH `circling` (it falls through to contextual severity). Verify vehicle leg unaffected.
- **Review C — test authority via real per-site source mutation + adversarial completeness.** Reviewer C personally mutates `const.py:1596` (change `"HIGH"` → `"LOW"`) and confirms D2's home_day/home_evening tests fail with a specific message; restores. Mutates `perimeter_alert.py:1424` (comment out `note_alert_dispatched` call) and confirms D1's `alert_count` assertion fails; restores. Independently re-greps every consumer of `"circling"` — including any surface D2 does not pin — and reports missed sites as findings. Enforces `.pyc`-staleness discipline (`PYTHONDONTWRITEBYTECODE=1` + clear `__pycache__` before mutation runs).

**Reviewer C's completeness pass is the falsification pass for the invariant chosen in O1.** If INV-M is chosen, reviewer C must construct at least one reachable legal-config scenario in each of the 9 house states (except guest) where a `circling` track would end at `alert_count = 0`, and show that D1/D2/D3 catch it.

## Verification steps (summary)

1. `pytest quality/tests/perimeter/test_circling_founding_case.py quality/tests/perimeter/test_circling_severity_per_state.py -v` — all green.
2. Reviewer-C mutation drill on `const.py:1596` and `perimeter_alert.py:1424` — both mutations produce specific test failures; both restored.
3. Full suite baseline diff vs `pre-review-v<version>` — no unrelated regressions.
4. Live replay per D4, table written back into `docs/readmes/README_v<version>.md`.
5. `sensor.perimeter_circling_zero_dispatch_24h` at 0 in steady state.

## Plan-completion tracking

Items intentionally deferred:
- Ack/repeat engine for HIGH `circling` alerts — deferred (out of scope; would elevate HIGH toward CRITICAL semantics).
- Per-classification cooldowns — deferred (see non-goals; would need its own cycle with load-shed-style backpressure reasoning).
- Widening the CONSOL-1 §6 circling override — deferred UNLESS operator O2 picks it (D5).
- Extending the linker + severity treatment to `car`/`animal` `circling` — deferred; a separate card (does not exist yet) should scope non-person circling if the operator wants it.

---

## Adjudication (orchestrator, 2026-08-13, under operator's "proceed unless you need decisions")

- **O1 = INV-M** (recommended default; INV-S rejected as over-strong for guest state, INV-W under-tests).
- **O2 = NO widening** — aligns with the CONSOL-1 review record's explicit rejection of a wider
  circling collapse; CRITICAL fail-safe already owns the high-stakes states.
- **O3 = D3 diagnostic sensor alone** — a coercion counter is marginal telemetry without a consumer.

Operator may override any of these before or after build; all three are cheap to revisit.
