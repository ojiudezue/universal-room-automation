# PLANNING — CIRCLING-SEVERITY-1

**Rev-2 (2026-08-12) — plan-review fix pass.** Plan review returned FIX-PLAN-FIRST. Adjudicated fixes applied in place: HIGH-1 (three missed dispatch-loss paths added to trace + D3 reframed as INV-M enforcement machinery), MEDIUM-1 (trace reconciled with D3 AC-1 which exercises the NM-raise path), MEDIUM-2 (reviewer C axis reframed as dispatch-loss modes, not per-house-state break), LOW-1 (D5 §6 docstring correction note), LOW-2 / build-pred #1 (D1 mandates `set_adjacency(EXTERIOR_ADJACENCY_GRAPH)` after linker construct), LOW-3 (open-track-at-restart one-liner), build-pred #2 (no per-track dispatcher signal exists in `exterior_track_linker.py`; D3 uses `async_track_time_interval` poll — pattern cited), build-pred #3 (D2 guest row reads the constant at test time). Operator adjudications preserved: **O1 = INV-M, O2 = no-widen, O3 = D3-only.**

**Card:** CIRCLING-SEVERITY-1 (kanban.data.yaml)
**Thread:** perimeter
**Founding case:** live track `xt-000001-695c9e` observed during v5.62.1 live validation on 2026-08-08 09:22 CDT: `back_yard → front_side_ptz → back_yard → front_side_ptz → back_yard`, 5 hops / 2 cameras / 133s, classified `circling`, `alert_count=0`. Track linking was correct (one track, not five alerts). No page fired.

## Result of trace (do this FIRST — it changes scope)

**The founding case is fixed-by-CONSOL-1 in home_day/home_evening for the happy path. The cycle collapses to VERIFICATION + TELEMETRY (D3) as the enforcement machinery for INV-M in the presence of residual dispatch-loss modes.** The trace below enumerates every reachable path from "event on a circling track" to "no `alert_count` increment" — including three modes the pre-review draft missed.

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

### Every reachable path from "event on a circling track" to "no alert_count increment"

`ExteriorTrack.alert_count` (`exterior_track_linker.py:103`) is incremented **only** by `note_alert_dispatched` (`:795`), which is called **only** from `perimeter_alert.py:1424` **inside the `dispatched_ok=True` branch** (after `nm.async_notify` succeeded and cooldown was reserved at `:1408`). The complete set of paths that reach `_async_handle_perimeter_trigger` but do NOT reach that increment:

**Pre-dispatch guards (skip before `_do_dispatch` even schedules):**

1. **Egress-suppression window** (`:1038-1047`, `EGRESS_SUPPRESSION_WINDOW_SECONDS`) — only after a household egress within N seconds; irrelevant to a mid-morning perimeter loop with no egress.
2. **Per-camera cooldown** (`:1053-1065`, `PERIMETER_ALERT_COOLDOWN_SECONDS = 300`) — fires only for the *2nd* hop on the same camera within 5 min. In the founding shape (2 unique cameras alternating), each camera's *first* hop dispatches; cooldown only mutes the re-hits. Result: `alert_count ≥ 2` (once per unique camera), not 0.
3. **In-flight guard** (`:1073-1079`) — same-camera re-fire during an outstanding async dispatch; not a silencing path across the track.
4. **NM missing / disabled** (`:1311-1317`) — config-level dead-letter; would silence *all* perimeter alerts, not `circling` specifically. WARN log only.

**Dispatch-loss modes (event was scheduled or entered `_do_dispatch`, but `dispatched_ok` never became True — HIGH-1 additions):**

5. **`nm.async_notify` raises** (`:1395-1399`) — the except-catch logs ERROR, `dispatched_ok` stays False, `note_alert_dispatched` is NEVER reached (`:1406` gates it). This is a real, silent-to-the-linker loss path: transient NM issues (channel misconfiguration, downstream service exception) produce a circling track with `alert_count=0` while ERROR log lines exist that no sensor surfaces.
6. **Teardown / HA-shutdown between schedule and dispatch** (`:1368-1370`) — `_do_dispatch` short-circuits if `not self._active or hass.is_stopping`, discards the in-flight marker, and returns *before* invoking NM. Any track whose only pending dispatch was in flight across teardown loses that dispatch entirely.
7. **Delayed dispatch cancelled during teardown** (`:1006-1013` cancels every unsub in `self._pending_dispatches` on teardown; scheduled via `async_call_later` at `:1442-1443` when `delay_s > 0`, which happens when the snapshot URL requires deferral per `_resolve_snapshot_url_and_delay` and no edge capture succeeded). Cancel means `_scheduled_dispatch` never fires → `_do_dispatch` never runs → `note_alert_dispatched` never called. A restart mid-track can leave the track's dispatches in `alert_count=0` even if the contextual severity was correctly HIGH.

**Why these matter for INV-M.** Paths 5-7 are silent to every existing sensor. They are exactly the residual loss modes that make INV-M ("circling dispatches ≥ 1 in every non-guest state") a real invariant to defend rather than a docstring wish. D3 (below) is the enforcement machinery: a passive 24h rolling counter that surfaces any `classify=="circling"` track with `alert_count==0` regardless of *which* of paths 5-7 caused it. **D3 is not a supplementary nicety — it is the backstop that makes INV-M honest in production.**

## Institutional context verified

### Greps run

- `rg -n 'circling|CIRCLING' custom_components/universal_room_automation/` → 3 files:
  - `const.py` (contextual severity override :1596, severity map :1751-1780, classifier threshold :1727)
  - `exterior_track_linker.py` (`classify` :681-704 producing `"circling"`, `alert_count` :103, `note_alert_dispatched` :777-797)
  - `perimeter_alert.py` (early classify for severity :1093-1106, continuation coercion :1152-1199, comment "approach/circling still alert" :1415, `note_alert_dispatched` call site :1424)
- `rg -n 'alert_count' custom_components/universal_room_automation/` → 1 write site (`exterior_track_linker.py:795`). **Sole increment path.**
- `rg -n 'note_alert_dispatched' custom_components/universal_room_automation/` → 1 caller for the person leg (`perimeter_alert.py:1424`, inside the `dispatched_ok=True` branch) and 1 for the vehicle leg (`:2556`).
- `rg -n 'PERIMETER_BURST_NIGHT_WINDOW|_is_in_alert_hours|_is_in_vehicle_alert_hours' …` → burst-demote night window still uses `(23,5)`; person alert-hours existence gate is gone; vehicle alert-hours gate is kept (§D6).
- `rg -n 'Severity\\.HIGH|Severity\\.CRITICAL' domain_coordinators/notification_manager.py` → HIGH and CRITICAL both bypass DND / non-critical gate at `:1584`, `:3668`; `:1502` starts ack/repeat only for CRITICAL. HIGH pages but does not repeat — acceptable for `circling` per the CONSOL-1 §6 intent.
- `rg -n 'async_dispatcher_send|SIGNAL_EXTERIOR' …` → the only dispatcher signal touching the linker is `SIGNAL_EXTERIOR_LINKER_READY` (a one-shot readiness signal, `domain_coordinators/signals.py:89`). **There is NO per-track-update dispatcher signal** — D3 must poll, not subscribe (build-pred #2 resolution).
- `rg -n 'async_track_time_interval' custom_components/universal_room_automation/sensor.py` → existing polling sensors use this pattern; canonical prior art is the MemoryEpisodeTotal sensor at `sensor.py:4407-4428` (5-min tick with `async_will_remove_from_hass` cleanup).

**REUSED (no new primitives proposed):**
- Contextual severity resolver — `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` at `const.py:1556-1635`.
- Circling classifier + `alert_count` — `exterior_track_linker.py:681-704` / `:103`.
- Severity map — `NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP` at `const.py:1751-1780`.
- Dispatch bookkeeping — `note_alert_dispatched` at `exterior_track_linker.py:777` (sole write to `alert_count`).
- Linker adjacency setter — `ExteriorTrackLinker.set_adjacency` fed by `EXTERIOR_ADJACENCY_GRAPH` (`const.py:1662-1718`); production wires this at setup, tests must too (build-pred #1).
- Polling sensor pattern — `sensor.py:4407-4428` (`async_track_time_interval` + `async_will_remove_from_hass` unsub).

**NEW:**
- One diagnostic sensor exposing `circling` tracks-with-zero-dispatches over the last N hours (see D3). Justified because paths 5-7 above are otherwise invisible; no existing sensor surfaces `alert_count==0` on a classified-circling track.
- One regression test module replaying the founding-case shape end-to-end (see D1). No existing test drives `circling → note_alert_dispatched` from a real per-camera event sequence.
- One per-state severity pin test file (see D2).
- (Conditional on O2 = widen — **currently NO per operator adjudication**) widening the contextual override's house-state set beyond `{home_day, home_evening}`.

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

- `feedback_no_fabrication.md` — informs the "verify override scope in source before proposing to widen it" posture.
- `feedback_marginal_benefit_pushback.md` — the O2 decision was resolved as no-widen precisely because CRITICAL fail-safe already dominates.
- `feedback_suppression_needs_discharge.md` — reviewed for the D3 sensor's reset semantics; the 24h rolling window is a re-fire, no persisted counter to de-sync.

### Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/exterior_track_linker.py` — classify (:681), alert bookkeeping (:777), ExteriorTrack (:95), set_adjacency wiring.
- `custom_components/universal_room_automation/perimeter_alert.py` — teardown cancel (`:1006-1023`), `_async_handle_perimeter_trigger` (:1028-1450), NM exception catch (`:1395-1399`), teardown short-circuit (`:1368-1370`), delayed schedule (`:1434-1445`), severity resolver (:1463-1495), burst-demote (:1828-1990), vehicle leg for parallel-structure sanity (:2331-2570).
- `custom_components/universal_room_automation/const.py` — CONSOL-1 §6 function (:1556-1635) including "Universal override" docstring at :1570-1573, severity map (:1751-1780), classifier constants (:1727-1735), adjacency graph (:1662-1718), night-window (:1458).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` — HIGH/CRITICAL routing sites at :1502, :1584, :2004, :3668.
- `custom_components/universal_room_automation/domain_coordinators/signals.py:89` — `SIGNAL_EXTERIOR_LINKER_READY` (readiness only, not per-update).
- `custom_components/universal_room_automation/sensor.py:4407-4428` — canonical `async_track_time_interval` polling-sensor pattern.

## Falsifiable invariant (up front)

**Adjudicated: O1 = INV-M.**

*A track classified `circling` at a perimeter camera dispatches at least once (`alert_count ≥ 1`) in every house state EXCEPT `guest`, provided the linker + NM are enabled.*

- Preserves the intentional `guest` carve-out.
- Explicitly covers `arriving` (currently `MEDIUM` — dispatches, but softest state) and `waking` (`CRITICAL` at perimeter).
- Honesty depends on catching residual dispatch-loss paths 5-7 above; D3 is the enforcement machinery.

INV-S and INV-W were considered and rejected per operator adjudication.

## Independent enumeration — every consumer of the `circling` classification

Regenerated by direct grep (do not trust the plan's list; reviewer re-runs `rg -n 'circling|CIRCLING'`):

1. **Producer:** `exterior_track_linker.py:681-704` `classify()` — returns `"circling"` when `revisit_count ≥ 1` OR (`camera_count ≥ EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS=3` AND `_is_non_monotonic(cams)`).
2. **Severity resolver early call (person, first alert path):** `perimeter_alert.py:1099-1111` — passes `track_class="circling"` into `_severity_for_current_house_state`.
3. **Contextual severity override:** `const.py:1596-1597` — the `HIGH` return in `{home_day, home_evening}`.
4. **Continuation coercion — RAISE branch:** `perimeter_alert.py:1188-1199` — coerced severity may only raise for `classification in ("approach", "circling")`.
5. **Severity map values (continuation lookup only):** `const.py:1753-1770` — `"circling"` column for `person` × 5 house states.
6. **Track bookkeeping:** `exterior_track_linker.py:795` writes `alert_count += 1`; :103 field default; :771 attribute exposed in `snapshot()` for diagnostics.
7. **Path narrative:** `perimeter_alert.py:1286-1306` — narrative enrichment runs for any multi-hop track; not classification-specific.
8. **Vehicle leg parallel — NOT in scope:** `perimeter_alert.py:2359-2378` uses `owning.alert_count > 0` as a demote-signal for cars but does NOT gate on `"circling"` classification.
9. **Constant:** `const.py:1727` `EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS = 3` — the classifier threshold.

## Numbers on the knob ladder

| Number | Current value | Rung | Rationale |
|---|---|---|---|
| `EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS` | 3 | **Module constant** | Changing this changes what `circling` *means*; drift must be review-visible. |
| `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` circling-override scope `{home_day, home_evening}` | as-is | **Module constant** (in function body) | Semantic policy — pinned by test rows per state. O2 = no-widen, so unchanged. |
| `NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP["person"]["…"]["circling"]` | see verbatim | **Module constant** | Every row test-pinned. |
| `PERIMETER_ALERT_COOLDOWN_SECONDS` | 300 | **Module constant** (existing) | NOT touched. |
| `CIRCLING_DIAG_LOOKBACK_HOURS` (new, D3) | 24 | **Module constant** | Behavioral observation window; promote to Number entity via follow-up if operator ever wants to tune live. |
| `CIRCLING_DIAG_POLL_INTERVAL_MINUTES` (new, D3) | 5 | **Module constant** | Matches the canonical `sensor.py:4407-4428` cadence — same rung as the pattern it copies. |

Kill switch (existing): `TRACK_LINK_WINDOW_S = 0` disables the entire linker/coercion layer. No new kill switch introduced.

## Operator adjudications (locked)

- **O1 = INV-M.** Circling dispatches ≥ 1 in every non-guest state.
- **O2 = no-widen.** CONSOL-1 §6 override scope stays `{home_day, home_evening}`.
- **O3 = D3-only.** No separate "raised-by-coercion" continuation counter.

## Non-goals (explicit)

- Not changing `PERIMETER_ALERT_COOLDOWN_SECONDS` or introducing per-classification cooldowns.
- Not touching the vehicle leg. Scoped to person.
- Not adding an ack/repeat engine to HIGH `circling` alerts.
- Not adding runtime instrumentation to "learn" circling frequencies — D3 is a passive counter reading existing snapshots.
- Not re-introducing an alert-hours existence gate on the person path.
- Not building any "monitor for N hours after ship" soak protocol. Event-count acceptance only.
- Not persisting the D3 counter across restarts (see D3 reset semantics + LOW-3 note).

## Deliverables

### D0 — Trace publication (documentation only)

Publish the trace above as-is. Operator adjudications are already locked in this rev-2 header.

#### Acceptance Criteria
- **Verify:** rev-2 header records O1 = INV-M, O2 = no-widen, O3 = D3-only.

### D1 — Add regression test replaying the founding-case shape

New test module `quality/tests/perimeter/test_circling_founding_case.py`. Drives `PerimeterAlertManager._on_perimeter_sensor_event` with the exact founding-case event sequence (`back_yard`, `front_side_ptz`, `back_yard`, `front_side_ptz`, `back_yard`), house_state = `home_day`, `persons_home = 1`, real `ExteriorTrackLinker` instance, spy NM.

**Wiring requirement (build-pred #1 / LOW-2):** the test MUST call `linker.set_adjacency(EXTERIOR_ADJACENCY_GRAPH)` immediately after construction, before feeding events. The bare constructor's empty adjacency graph would fork the founding-case sequence into 5 separate tracks (each hop unlinked), silently no-op the `classify == "circling"` oracle, and the assertions would pass on trivially-wrong track topology. Assert `len(linker.open_tracks) == 1` after event 3 as a topology-sanity precondition before checking classification.

Assertions:
- `linker.classify(track) == "circling"` at end of sequence.
- `track.alert_count >= 2` (one per unique camera on first hop; subsequent hops on same camera hit cooldown).
- Every dispatched severity is `Severity.HIGH` (CONSOL-1 override).
- The path narrative in the dispatched message contains all 5 hops in order.

**Wire-in anchor (mandatory):** the test asserts on `spy_nm.async_notify.call_args_list[i].kwargs["severity"] == Severity.HIGH` — enclosing behavioral anchor is `_do_dispatch`'s `nm.async_notify(**_kwargs)` at `perimeter_alert.py:1387`. Neuter drill: commenting out `perimeter_alert.py:1424` (`_linker.note_alert_dispatched(...)`) MUST make the `alert_count >= 2` assertion fail (proves the assertion is tied to the real write site).

#### Acceptance Criteria
- **Verify:** `pytest quality/tests/perimeter/test_circling_founding_case.py -v` all green.
- **Verify:** topology-sanity precondition (`len(linker.open_tracks) == 1`) proves adjacency is loaded — a test run with `set_adjacency` skipped MUST fail on this precondition, not silently pass the downstream asserts.
- **Verify:** neuter drill — remove `perimeter_alert.py:1424` → the `alert_count` assertion fails; restore.
- **Test:** `test_founding_case_home_day_dispatches_high`, `test_founding_case_alert_count_matches_unique_cameras`, `test_founding_case_narrative_lists_all_hops`, `test_founding_case_topology_precondition`.
- **Live:** covered by D4.

### D2 — Add per-house-state pin tests for circling severity

New test file `quality/tests/perimeter/test_circling_severity_per_state.py`. One test per house state in `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY`'s domain, calling the resolver directly with `camera_class="perimeter"`, `track_class="circling"`, `persons_home ∈ {0, 1, 2}`.

Rows pinned:
- `away/vacation/sleep/home_night` → `"CRITICAL"` (fail-safe rows).
- `home_day/home_evening` → `"HIGH"` (override).
- `arriving` → `"MEDIUM"` (row-7; circling NOT escalated).
- `waking` (perimeter) → `"CRITICAL"`.
- `guest` → the value of `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` **read at test time** (build-pred #3). The test asserts `result == NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY`, importing the constant — no hardcoded severity string. If the operator later re-tunes GUEST severity, this test tracks it automatically instead of blocking.

#### Acceptance Criteria
- **Verify:** `pytest quality/tests/perimeter/test_circling_severity_per_state.py -v` green.
- **Test:** `test_circling_severity_<state>` × 9.

### D3 — Diagnostic sensor: circling-tracks-with-zero-dispatches (last 24h)

**Purpose (HIGH-1 / MEDIUM-1 reframing):** this sensor is the **enforcement machinery for INV-M**. Every one of the residual dispatch-loss paths (trace paths 5-7 — NM-raise, teardown short-circuit, cancelled delayed dispatch) leaves a `circling` track with `alert_count == 0` and no other observable signal. Without D3, INV-M is a wish; with D3, INV-M is a live tripwire.

New sensor entity `sensor.perimeter_circling_zero_dispatch_24h`. Reads `ExteriorTrackLinker` snapshots (`snapshot()` API), counts tracks where `classify(t) == "circling"` AND `alert_count == 0` AND `started_at` within the last `CIRCLING_DIAG_LOOKBACK_HOURS = 24`.

**Update mechanism (build-pred #2 resolution):** poll pattern — `async_track_time_interval` at `CIRCLING_DIAG_POLL_INTERVAL_MINUTES = 5`, following the canonical prior art at `sensor.py:4407-4428`. **The linker does NOT emit a per-track-update dispatcher signal** — only `SIGNAL_EXTERIOR_LINKER_READY` (one-shot readiness). Subscribing to that signal for update refreshes would fire once at startup and never again. The polling sensor:

```python
async def async_added_to_hass(self):
    await super().async_added_to_hass()
    from homeassistant.helpers.event import async_track_time_interval
    from datetime import timedelta
    await self._refresh()
    async def _tick(_now):
        await self._refresh()
        self.async_write_ha_state()
    self._unsub = async_track_time_interval(
        self.hass, _tick, timedelta(minutes=CIRCLING_DIAG_POLL_INTERVAL_MINUTES)
    )

async def async_will_remove_from_hass(self):
    unsub = getattr(self, "_unsub", None)
    if unsub is not None:
        unsub()
    await super().async_will_remove_from_hass()
```

Value = integer count; attributes = up-to-10 offending `track_id`s (newest first) + `first_seen_at` each, `lookback_hours = 24`, `poll_interval_minutes = 5`.

**Reset semantics + LOW-3 note:** rolling 24h lookback based on live snapshot iteration; **no persisted counter**. Open tracks at HA restart are unrecoverable by design — the linker's in-memory state does not survive restart, and any dispatch loss that occurred pre-restart is not retroactively actionable. D3 is a **live tripwire**, not a durable audit ledger. Documented on the sensor description. If durable audit is ever required, that is a separate cycle (persisted `alert_count=0` classified-circling rows to the URA DB).

**Wire-in anchor (revised per build-pred #2 + #4):** the update callback registered by `async_track_time_interval` is the anchor. Test: replace `_tick`'s body with `pass` (source mutation) → inject a zero-dispatch circling track → advance the clock past one poll interval → sensor MUST stay at 0; restore → sensor MUST show 1. This proves the poll is the load-bearing update path.

#### Acceptance Criteria
- **AC-1:** with the D1 test wired to spy NM but with `spy_nm.async_notify` raising, `alert_count` stays at 0 (path 5), `classify == "circling"`, and D3 reports 1 with the track_id in attributes. **This exercises the NM-exception path the initial trace incorrectly called impossible — MEDIUM-1 reconciliation.**
- **AC-2:** with a normal D1 run (dispatches succeed), sensor value is 0.
- **AC-3:** teardown short-circuit path (path 6): schedule a delayed dispatch, invoke `async_will_remove_from_hass` on the perimeter manager before the delay fires, verify the track ends at `alert_count == 0` and D3 reports 1.
- **AC-4:** cancelled-delayed-dispatch path (path 7): as AC-3 but assert the `_pending_dispatches` unsub was called (spy on `unsub`); D3 still reports 1.
- **Sensor:** `sensor.perimeter_circling_zero_dispatch_24h` present in registry; state is integer ≥ 0; attribute `track_ids` is a list; attribute `lookback_hours == 24`; attribute `poll_interval_minutes == 5`.
- **Test:** `test_diag_sensor_counts_nm_exception_loss`, `test_diag_sensor_counts_teardown_loss`, `test_diag_sensor_counts_cancelled_delay_loss`, `test_diag_sensor_zero_when_dispatches_succeed`, `test_diag_sensor_poll_neuter_drill`.
- **Live:** the sensor is 0 within 5 min of restart on a house with no offending tracks; if it ever goes non-zero, NM emits a `MEDIUM` anomaly (reuse the existing URA anomaly detector pipe, not a new one).

### D4 — Live validation table (post-deploy)

Replay the founding-case shape live: two operator-triggered walks between `back_yard` and `front_side_ptz` (5 hops total, ≤ 3 min) during `home_day`. Table below is filled in on ship-day and written back into the README per CLAUDE.md.

| Criterion | Expected | Observed | Evidence |
|---|---|---|---|
| Linker attributes the loop to one track | 1 person track, 5 hops | | linker snapshot |
| Classification = `circling` | `classify(track) == "circling"` | | track attributes |
| Severity = HIGH | ≥ 1 NM dispatch at HIGH | | NM log line `severity=HIGH` |
| Dispatch paged | Phone received | | phone notification |
| `alert_count ≥ 2` | attributed to the owning track | | linker snapshot |
| D3 sensor at 0 after the walk | `sensor.perimeter_circling_zero_dispatch_24h == 0` | | entity state |

### D5 — DEFERRED (O2 = no-widen)

**Not built this cycle.** O2 adjudication = do not widen. Retained here as parked deliverable with revival trigger.

If a future cycle widens the `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` circling-override scope, that cycle **must in the same commit** correct the docstring at `const.py:1570-1573`, which currently reads *"Universal override (checked FIRST): any `track_class == 'circling'` at a `perimeter` camera returns HIGH — EXCEPT when the case tree would already emit CRITICAL for that (house_state, camera_class, persons_home) row"*. The word "Universal" is already misleading given the actual `hs in ("home_day", "home_evening")` scope at :1596; widening would make the mismatch worse. **LOW-1 requirement: D5, if it ever fires, includes the docstring fix.**

## Tier classification

**Tier 2-DB — three framing-disjoint reviews.** Justification: change touches severity routing on the person perimeter leg, cross-coordinator (linker ↔ perimeter_alert ↔ NM), safety-adjacent. Per operator standing policy (2026-06-08), regression-prone work defaults to Tier 2-DB.

- **Review A — local correctness + per-row severity integrity.** For every one of the 9 house states, verify the resolver returns the pinned severity for `(cc="perimeter", tc="circling", ph ∈ {0,1,2})` and that no arm above it short-circuits incorrectly. Verify the continuation-coercion RAISE branch (`perimeter_alert.py:1188-1199`) cannot demote circling. Verify D3's counter reads the same `alert_count` field that `note_alert_dispatched` writes (single source of truth). Verify D3's poll cadence + cleanup match the canonical pattern.
- **Review B — cross-coordinator / state-machine integrity + restart.** Trace: Frigate event → linker `record_event` → `classify` → perimeter_alert severity resolve → coercion → burst-demote → NM `async_notify` → `note_alert_dispatched`. Verify no double-emit on continuation. Verify D3 sensor state on restart matches the documented "live tripwire, not durable ledger" contract. Verify the "smart_alerts_enabled" switch does NOT silence HIGH `circling`. Verify vehicle leg unaffected. Verify D1's `set_adjacency` call actually loads the graph the linker uses in production.
- **Review C — test authority via real per-site source mutation + adversarial completeness on DISPATCH-LOSS MODES.** **Falsification axis reframed (MEDIUM-2): dispatch-loss modes, not house-state × classifier.** Reviewer C's job is to enumerate every reachable path from "circling event handled" to "`alert_count` not incremented" and confirm D3 catches each:

  1. Mutate `const.py:1596` (`"HIGH"` → `"LOW"`) → confirm D2 home_day/home_evening tests fail with specific messages; restore. (Anchors the CONSOL-1 override to test authority — this is the only per-state break in scope; per-state breaks for the CRITICAL-failsafe rows are infeasible by construction since the failsafe short-circuits before the override runs, and Review A owns the row-integrity check.)
  2. Mutate `perimeter_alert.py:1424` (comment out `note_alert_dispatched`) → confirm D1's `alert_count` assertion fails; restore.
  3. **Path 5 drill:** confirm D3 AC-1 fails if D3's `alert_count == 0` filter is inverted (`!= 0`); restore.
  4. **Path 6 drill:** confirm D3 AC-3 fails if the teardown short-circuit at `perimeter_alert.py:1368-1370` is neutered (short-circuit removed); restore. (This proves AC-3's oracle depends on the real teardown path, not a fixture-side skip.)
  5. **Path 7 drill:** confirm D3 AC-4 fails if the `_pending_dispatches` cancel loop at `:1006-1013` is neutered; restore.
  6. **Completeness sweep:** independently re-grep every consumer of `"circling"` and every write path to `alert_count`; any surface not covered by D1/D2/D3 is a finding. Also independently re-grep every early-return in `_async_handle_perimeter_trigger` and every `dispatched_ok = False` branch — any new dispatch-loss mode is a finding.

  Enforces `.pyc`-staleness discipline (`PYTHONDONTWRITEBYTECODE=1` + clear `__pycache__` before mutation runs).

## Verification steps (summary)

1. `pytest quality/tests/perimeter/test_circling_founding_case.py quality/tests/perimeter/test_circling_severity_per_state.py -v` — all green.
2. Reviewer-C mutation drills 1-5 above — each produces a specific test failure; all restored.
3. Full suite baseline diff vs `pre-review-v<version>` — no unrelated regressions.
4. Live replay per D4, table written back into `docs/readmes/README_v<version>.md`.
5. `sensor.perimeter_circling_zero_dispatch_24h` at 0 in steady state.

## Plan-completion tracking

Items intentionally deferred:
- Ack/repeat engine for HIGH `circling` alerts — deferred (would elevate HIGH toward CRITICAL semantics).
- Per-classification cooldowns — deferred (would need load-shed-style backpressure reasoning).
- D5 (widening the CONSOL-1 §6 circling override) — deferred by O2 adjudication; docstring-fix requirement noted for whenever D5 fires.
- Durable persisted audit of `alert_count=0` circling tracks — deferred; D3 is live-tripwire only per LOW-3.
- Extending the linker + severity treatment to `car`/`animal` `circling` — deferred; separate card (not yet created).
