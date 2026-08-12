# PLANNING — CONSOL-1: Alerting-stack consolidation + universal llmvision

**Rev:** 2 (rev-1 → NEEDS-REVISION plan review, all 9 findings adopted; see §16 record)
**Card:** CONSOL-1 (docs/planning/kanban.data.yaml:1485)
**Status:** DRAFT rev-2 for adjudication before build dispatch
**Tier proposed:** Tier 2-DB (three framing-disjoint code reviews + Review-D live validation + README write-back). See §12.
**Predecessors merged live:** SNAP-1 (v5.63.0, local file capture into
`/media/ura/snapshots`), NM-IMAGE-1 (v5.71.0, `NM_SECURITY_HAZARDS`
frozenset + two-site force-immediate predicate + gate mirror), RESACC-1
(v5.65.0, resolver accuracy suite).
**Operator rulings ratified (2026-08-07, cards + `PLANNING_perimeter_consolidation.md` §Operator rulings):**
1. Config-home = Option C (Perimeter Alerting stays top-level; internal
   WHAT/WHEN vs WHO/HOW split; future "Security" umbrella deferred).
2. Universal llmvision enrichment on ALL camera alerting, enriched per
   DISPATCHED alert (post cooldown/dedup), never per raw detection.
3. Day/night is NOT a valid boundary for person alerting — the 23–05
   existence window is REMOVED; severity is contextual. Exception:
   deep-night VEHICLE window retained (renamed in D6, see §6/§D6).
4. Doorbell WhatsApp automation is MIGRATE-THEN-RETIRE.

---

## §1 — Institutional context verified

**Prior planning + audit docs pulled (full body):**
- `docs/planning/PLANNING_perimeter_consolidation.md` (operator rulings 2026-08-07).
- `docs/planning/AUDIT_ha_side_alerting_reconciliation.md`.
- `docs/planning/PLANNING_nm_image_delivery.md` + `docs/readmes/README_v5.71.0.md`.
- `docs/planning/PLANNING_snap1_at_detection_snapshots.md` + README_v5.63.0.
- Kanban cards CONSOL-1, SNAP-1, TEST-1, TEST-2, RESACC-1
  (kanban.data.yaml:1485, :1517, :1701, :1718, and RESACC-1 above).

**Code surfaces greped / read end-to-end:**
- `custom_components/universal_room_automation/perimeter_alert.py`
  — person handler `_async_handle_perimeter_trigger` (:963); the
  four `_is_in_alert_hours` consumers listed in §5-S4; snapshot
  resolution (`_resolve_snapshot_url_and_delay` :1389,
  `_await_edge_capture` :1177); person NM emit (:1258); LEGACY
  person call (:1291); vehicle handler `_async_handle_vehicle_trigger`
  (:2224); vehicle NM emit (:2275) — verified in rev-2 as :2275, not
  :2286 as rev-1 stated; LEGACY vehicle call (:2305); Frigate cache (:678).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py`
  — `async_notify` (:1186), `_force_immediate_for_security_image`
  predicate (:1235), gate-mirror kwarg (:3529 / :3579), `_send_whatsapp`
  (:2023).
- `custom_components/universal_room_automation/const.py:1409-1451`
  — `NM_SECURITY_HAZARDS` frozenset + kill-switch semantics; named
  `NM_ROUTE_REASON_*` constants (:1446-1451) — the site where
  `NM_ROUTE_REASON_ENRICHED` and `NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH`
  land (§14#3). Severity tables :1330, :1460.
- `config_flow.py:3012-3093` (Perimeter Alerting step), :2591-2596
  (Configure Settings menu registration), :7482-7537 (`default_notifications`).
- HA live artifact (D0.1 gate — extracted, not fabricated): doorbell
  automation invocation shape from live `/config/automations.yaml`.

**Proposed additions — REUSED vs NEW table:**

| Proposed | REUSED / NEW | Rationale / file:line |
|---|---|---|
| `enrich_dispatched_alert(...)` in a new `perimeter_enrichment.py` | NEW | No `enrich`/`llmvision` grep hits in URA code |
| `CONF_PERIMETER_ENRICHMENT_ENABLED` (bool, default OFF; §D4 M4 promote gate) | NEW | Cost-gated opt-in; no equivalent |
| `CONF_PERIMETER_ENRICHMENT_PROVIDER` (str, default `"llmvision"`) | NEW | Provider abstraction |
| `CONF_PERIMETER_ENRICHMENT_CAMERAS` (list; default empty pre-promote, doorbell pair post-promote) | NEW | Per-camera allowlist |
| `CONF_PERIMETER_ENRICHMENT_MODEL` (str, default `"gpt-4o-mini"`) | NEW | Pinned by D0.2 (see §D3) |
| `CONF_PERIMETER_ENRICHMENT_MAX_TOKENS` (int, default `1500`) | NEW | Pinned by D0.2 |
| `perimeter_enrichment_timeout_s` Number entity (default `4.0`, min 1.0, max 15.0) | NEW rung-3 | D0.2 observed max ~2.0s; 4.0s = 2× headroom |
| `LLMVISION_ENRICHMENT_KILL` (module const, default False) | NEW rung-1 | Hard kill switch |
| `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` (function over (house_state, camera_class, track_class, persons_home) → Severity) | REUSED shape of :1460; NEW function | Replaces removed 23–05 existence gate |
| `NM_ROUTE_REASON_ENRICHED` (str) | NEW | Defined beside :1446-1451 constants (§14#3) |
| `NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH` (str) | NEW | Same neighborhood |
| `CONF_PERIMETER_VEHICLE_HOURS_START` / `_END` (rename of `CONF_PERIMETER_ALERT_HOURS_START/_END`) | REUSED knob shape; renamed | §6/§D6 — vehicle-only, policy not protocol |
| Migration: strip retired `CONF_PERIMETER_ALERT_{NOTIFY_SERVICE,TARGET}`; rename `_HOURS_START/_END` → vehicle-scoped keys with value carry-over | REUSED option-strip pattern | §D6 |

No `docs/Coordinator/*.md` entry exists for perimeter or NM.

---

## §2 — Falsifiable invariant

**INV-CONSOL-1 (single-thread invariant, extends INV-XP):**

> Under any legal config a single physical exterior camera event
> produces **exactly ONE** notification thread across the four
> historical stacks (URA perimeter NM, URA legacy notify leg, HA
> doorbell automation, HA G4 blueprint) — AND llmvision failure NEVER
> silences, delays past the wall-clock timeout, or duplicates that
> single thread.

Two falsifying observations, either kills ship:
1. Doubled thread from one physical event post-retire (adversary: check
   the abandoned-enrichment-call race — see INV-ENRICH-NEVER-SILENCES).
2. "Daytime gap" — an event that today pages via the doorbell automation
   outside the retired 23–05 window producing ZERO threads post-retire.

**Load-bearing sub-invariants (each mutation-anchored in D3):**
- **INV-ENRICH-BUDGETED:** llmvision wall-clock > `timeout_s` → NM
  dispatch fires at t=timeout without the description, byte-identical
  to the enrichment-OFF payload for that event.
- **INV-ENRICH-NON-EMPTY (rev-2 #1):** llmvision returning `None`,
  empty string `""`, or whitespace-only `response_text` counts as a
  FAILURE — adapter returns `None`, caller uses base message, ledger
  stamps `route_reason = NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH`.
  An empty description must NEVER be concatenated into the outgoing
  message (empty-tail leak would be silent regression of P2 parity).
- **INV-ENRICH-NEVER-SILENCES (rev-2 #1, restated):** for each of the
  THREE failure classes below, NM dispatch fires WITHOUT the description
  and no exception escapes the caller. The three enumerated classes:
  (a) **exception** — adapter raise or provider 5xx / HomeAssistantError;
  (b) **timeout** — wall-clock exceeds `timeout_s` (adapter cancels the
  underlying call, see §D3 cancel-contract);
  (c) **empty** — provider returns None/""/whitespace-only response_text
  (INV-ENRICH-NON-EMPTY).
  Each class has its own targeted mutation-anchored test in §D3.

---

## §3 — Design overview

**One router, one message, one snapshot, one enrichment step.**
Enrichment is ONE new stage between snapshot resolution
(`perimeter_alert.py:1177`) and NM dispatch (`:1258` person, `:2275`
vehicle), on the caller side so NM stays provider-agnostic.

```
edge detect → cooldown/dedup gate → severity coercion (contextual §6)
  → capture snapshot (SNAP-1 pipeline, already live)
    → enrichment (this cycle: gated + timeout + fall-through, cancel-on-timeout)
      → NM.async_notify(snapshot_path=..., message=base±enriched, route_reason=...)
        → force-immediate predicate (NM-IMAGE-1, already live)
```

---

## §4 — D0 (probe/measurement gate — MEASURE BEFORE YOU BUILD)

**D0.1 — Extract WORKING doorbell automation invocation shape** into
`docs/planning/AUDIT_llmvision_doorbell_shape.md`. Verified return
shape from the live provider (paste-through into §D3): the llmvision
`image_analyzer` service returns
```python
{"response_text": "<str>"}
```
The adapter's contract is: call the service, read `response_text`,
apply INV-ENRICH-NON-EMPTY, return `str | None`.

**D0.2 — LLM latency distribution on real snapshots** into
`docs/planning/AUDIT_llmvision_latency_probe.md`. Probe already run
(rev-2): on `gpt-4o-mini` with `max_tokens=1500` against 20 recent
`/media/ura/snapshots` files, observed **max ~2.0s** wall-clock,
error rate < 5%. Decisions frozen from this probe:
- Model: `gpt-4o-mini` (D3 pins).
- max_tokens: 1500 (D3 pins).
- `timeout_s` default: 4.0 (2× observed max headroom; still tunable
  rung-3 via Number entity).

**D0.3 — Cost accounting** into the same latency-probe doc:
project calls/day at default-OFF vs the post-promote default state.
Feeds the M4 promote gate in §D4.

**D0.4 (rev-2 #8) — Doorbell live-side hotfix (OPERATOR-GATED).**
Parity P2 requires observing the doorbell automation's message quality
live. If the automation is currently degraded (missing image /
broken llmvision call / any state the operator has already flagged),
apply a small live hotfix so P2 is measured against a WORKING baseline,
not against a broken one. Offer made; execution gated on operator
"yes, fix it" — otherwise document as "P2 measured against
last-known-good sample" and proceed.

**D0.5 (rev-2 #8) — Dormant-automations inventory** into
`docs/planning/AUDIT_ha_dormant_automations.md`. BEFORE §D7 deletes
anything, enumerate the 12 H5 automations by
`id + alias + last_triggered` from the live `automations.yaml`. This
is the audit-trail source of truth for the delete PR; a missing entry
in the audit → do NOT delete it.

**Gates:**
- D0.1 gates D3 (no adapter without the extracted shape).
- D0.2 gates D3 defaults (model/max_tokens/timeout).
- D0.3 feeds M4 promote gate (§D4).
- D0.4 gates P2 evidence quality (§7).
- D0.5 gates D7 (no delete without prior enumeration).

---

## §5 — Emission-site enumeration (S-style; plan review MUST re-grep)

**URA (repo, in-scope):**

| S# | Surface | File:line (verified rev-2) | Disposition |
|---|---|---|---|
| S1 | Person NM emit — `_async_handle_perimeter_trigger` | perimeter_alert.py:1258 | Enrichment call inserted between :1177 (snapshot) and :1258 (NM emit) |
| S2 | Vehicle NM emit — `_async_handle_vehicle_trigger` (**rev-2 #3: corrected :2286 → :2275**) | perimeter_alert.py:2275 | Same enrichment call |
| S3 | Legacy dispatch — `_async_send_legacy_notification` (**rev-2 #9: both call sites named**) | perimeter_alert.py:**:1291** (person leg) and **:2305** (vehicle leg) | RETIRE — code-dead v(N), delete v(N+1); vehicle-path no-legacy test required (§D1) |
| S4 | Existence-window gate + all `_is_in_alert_hours` consumers (**rev-2 #3: full enumeration**) | perimeter_alert.py:**:968** (person handler in-window gate — the actual short-return site; correction from rev-1's :637-643); **:1687**, **:1696** (decision + shadow-dict emits — telemetry callers; drop the field entirely from the person shape); **:2041** (vehicle handler in-window gate — RETAINED, renamed) | See per-consumer disposition below |
| S5 | NM `async_notify` | notification_manager.py:1186 | Unchanged; enrichment string is concatenated by CALLER into `message` |
| S6 | Force-immediate predicate + gate mirror | notification_manager.py:1235, :3579 | Unchanged; MUST NOT be defeated by enrichment failure — INV-ENRICH-NEVER-SILENCES pins this |
| S7 | Config-flow `default_notifications` step | config_flow.py:7482-7537 | Unchanged (Option C — WHO/HOW here) |
| S8 | Config-flow Perimeter Alerting step | config_flow.py:3012-3093 | ADD enrichment + `_MODEL` + `_MAX_TOKENS` fields; REMOVE legacy `_NOTIFY_SERVICE`/`_TARGET`; RENAME `_HOURS_START/_END` → vehicle-scoped (§D6) |

**S4 per-consumer disposition (rev-2 #3):**

| Consumer | Line | Post-cycle behavior |
|---|---|---|
| Person handler in-window short-return | :968 | REMOVED. Person path no longer consults hours; contextual severity §6 replaces it. |
| Person decision dict emit | :1687 | `_is_in_alert_hours` field removed from person decision payload; dashboard readers updated to consume severity/route_reason instead. |
| Person shadow dict emit (telemetry) | :1696 | Same — drop the field from person shadow-dict shape; add `severity_tier` for observability parity. |
| Vehicle handler in-window gate | :2041 | RETAINED. Renamed helper `_is_in_vehicle_alert_hours(now)` reading the renamed keys (§D6). |

**HA-side (repo-external, `/config/`, in-scope for retire):**

| H# | Surface (rev-2 #3: corrected + expanded) | Disposition |
|---|---|---|
| H1 | `Doorbell Detection WhatsApp Alert` automation | MIGRATE-THEN-RETIRE (§7 gate; §D5) |
| H2 | **G4 Doorbell Analysis** (rev-2 #3: was mistyped "G6") — blueprint path `blueprints/automation/balloob/ai-camera-analysis.yaml`; entities `binary_sensor.madrone_g6_entry_motion_2`, `camera.madrone_g6_entry` (the "g6" here is the CAMERA model — Unifi G6 Doorbell — not the blueprint name; retain both spellings verbatim in the delete PR to avoid grep miss) | MIGRATE-THEN-RETIRE folded into enrichment on that camera |
| H3 | `Phase 1: All Detections — Dual System (AI)` — automations.yaml body **~lines 7870-7930** (rev-2 #3), **TWO llmvision references** in that body (both service calls must be captured in the deletion diff) | DELETE (OFF since 2026-02-18) |
| H4 | `Phase 1: Known Person — Dual System` (3 F1 face sensors) | DELETE (OFF) |
| H5 | 12 dormant HVAC/presence/arrester/guest automations — enumerated in D0.5 | DELETE gated by D0.5 audit |
| H6 | `packages/zone_monitoring.yaml` — 4 per-event mobile-push counter automations | §8 in-code tripwire |
| H7 | Zone1/Zone3 Inactivity Alert + Multi-Zone Daily Summary + Reset | §8 |
| H8 | Frigate MQTT bridge | KEEP |

---

## §6 — Contextual severity (rev-2 #4 — TOTAL over 9 HouseState values)

Inputs unchanged from rev-1: `(house_state, camera_class, track_class, persons_home)`.

**`NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` — total table.** Every
one of the 9 `HouseState` values has an explicit row; a `case _:` arm
returns `CRITICAL` (fail-safe) for any value the compiler adds later.

| # | house_state | camera_class | track_class | persons_home | Severity |
|---|---|---|---|---|---|
| 1 | `away` | any | any | any | CRITICAL |
| 2 | `vacation` | any | any | any | CRITICAL |
| 3 | `sleep` | any | any | any | CRITICAL |
| 4 | `home_night` | any | any | any | CRITICAL |
| 5a | `home_day` | perimeter | `circling` | any | HIGH (override) |
| 5b | `home_day` | perimeter | `approach` OR `linger` | ≥1 | MEDIUM |
| 5c | `home_day` | perimeter | `first_sighting` | ≥1 | LOW |
| 5d | `home_day` | egress | any | ≥1 | LOW (expected foot traffic) |
| 5e | `home_day` | any | any | 0 | HIGH (nobody home but state says home_day — anomaly) |
| 6 | `home_evening` | perimeter | `circling` | any | HIGH |
| 6b | `home_evening` | perimeter | `approach` OR `linger` | ≥1 | MEDIUM |
| 6c | `home_evening` | perimeter | `first_sighting` | ≥1 | LOW |
| 6d | `home_evening` | egress | any | ≥1 | LOW |
| 6e | `home_evening` | any | any | 0 | HIGH |
| 7 | `arriving` (**rev-2 #4**) | any | any | any | MEDIUM ("likely the operator approaching" — not silenced, not CRITICAL) |
| 8 | `waking` (**rev-2 #4**) | perimeter | any | any | CRITICAL (perimeter breach while household is booting-up is still after-hours by intent) |
| 8b | `waking` | egress | any | any | MEDIUM |
| 9 | `guest` | any | any | any | `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` (:1455) |
| — | unknown / missing / None / any future HouseState value | any | any | any | CRITICAL (fail-safe, `case _:` arm) |

**Universal override (checked FIRST, ahead of the case tree):** any
`track_class == circling` at a `perimeter` camera → HIGH regardless of
house_state, EXCEPT when the case tree would already emit CRITICAL
(CRITICAL wins). Encoded as the first branch of the function.

Vehicle keeps `_async_handle_vehicle_trigger`'s existing shape; the
renamed deep-night window (§D6) gates ONLY that path.

**Retained non-severity knobs:** `CONF_EXTERIOR_SNAPSHOT_OFFSET_S`,
`PERIMETER_ALERT_COOLDOWN_SECONDS`.

---

## §7 — Migrate-then-retire: doorbell automation parity checklist

(rev-2 #5: NO calendar windows.)

Doorbell automation stays ENABLED at v(N). §D5-step-1 (disable) fires
when the ledger observation gate below is met. §D5-step-2 (delete
from yaml) fires when the second gate is met.

**§D5-step-1 gate — the N=5 rule:** the retire is authorized when
FIVE consecutive organic front-door person events are all P1-P7-clean
by ledger observation (each event: exactly one URA NM ledger row +
one confirmed WhatsApp arrival with image AND description AND
`route_reason=force_immediate_security_image` OR
`NM_ROUTE_REASON_ENRICHED`, AND no second thread). Ledger-observable,
no calendar wait. If event #k fails any of P1-P7, the counter RESETS
and the failure is treated as a real regression finding (fix, re-ship,
re-count).

**§D5-step-2 gate:** another N=5 consecutive events observed with the
automation DISABLED (i.e. after step-1) all delivering exactly one
thread → step-2 executed at the **next release opportunity** (not
calendar-scheduled).

**Parity table (measured, not timed):**

| P# | Criterion | Evidence oracle |
|---|---|---|
| P1 | WhatsApp arrives WITH image, within seconds of detection | Ledger `route_reason=force_immediate_security_image`; WhatsApp receipt ≤5s of `notification_log.dispatched_at` |
| P2 | Message body contains an llmvision description of comparable quality | Side-by-side operator spot-check over the N=5 window; D0.4 hotfix ensures baseline is real |
| P3 | Vehicle deep-night event pages with image | One 23–05 vehicle event within the window → URA NM row + WhatsApp with image |
| P4 | Animal detection: linker records episode; no operator page | Linker episode row present; NM row absent |
| P5 | Front-door coverage OUTSIDE retired 23–05 window pages via URA | Ledger row `hazard_type=exterior_person`, `house_state ∈ home_day/home_evening`, image attached |
| P6 | Enrichment failure fall-through observed at least once | Ledger `route_reason=NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH` OR operator engages `LLMVISION_ENRICHMENT_KILL` and observes P1 still holds |
| P7 | INV-CONSOL-1 single-thread | Operator: one WhatsApp thread on phone per physical event |

**Parity-window double-page note (rev-2 L4):** during the parity
window (both stacks live), the operator WILL see one WhatsApp per
stack per event = two WhatsApps per front-door person. This is the
expected shape of the migration window and is called out in
README_v<version>.md so it is not mistaken for a bug.

---

## §8 — zone_monitoring pager stack — in-code tripwire (rev-2 #5)

**No calendar observation window.** At v(N):
- Toggle `input_boolean.zone{1,3}_monitoring_active` OFF (reversible).
- Add an **in-code NM tripwire**: URA subscribes to the zone_monitoring
  `notify.mobile_app_*` invocation path (or, more cheaply, to a
  synthesized state-change on the four counter automations' `last_triggered`
  attribute) and fires a `URA_ZONE_MONITORING_LEAK` MEDIUM NM
  notification once per fired counter (with per-day dedup). If the
  tripwire never fires — the yaml is quiescent by evidence, not by
  calendar. Follow-up commit strips the notify actions when the
  tripwire has produced 0 leak notifications between ship and any
  next URA release; auto-closes without an operator watch.

Yaml unchanged this cycle. Retirement of the counters/template
sensors is out-of-scope (§11).

---

## §9 — Knobs on the ladder

| Knob | Rung | Home | Kill-switch |
|---|---|---|---|
| `LLMVISION_ENRICHMENT_KILL` | 1 (module const) | `const.py` | `True` → adapter no-ops → identical to `_ENABLED=False` |
| `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` default table | 1 | `const.py` | n/a (policy) |
| `CONF_PERIMETER_ENRICHMENT_ENABLED` | 2 | `config_flow.py` Perimeter step | `False` = adapter never called |
| `CONF_PERIMETER_ENRICHMENT_PROVIDER` | 2 | same | n/a |
| `CONF_PERIMETER_ENRICHMENT_CAMERAS` | 2 | same | `[]` = adapter never called |
| `CONF_PERIMETER_ENRICHMENT_MODEL` | 2 | same | n/a (default `gpt-4o-mini`) |
| `CONF_PERIMETER_ENRICHMENT_MAX_TOKENS` | 2 | same | n/a (default 1500) |
| `perimeter_enrichment_timeout_s` | 3 (Number entity) | `number.py` | min 1.0 caps runaway; operator turns |
| `CONF_PERIMETER_VEHICLE_HOURS_START/_END` | 2 | `config_flow.py` (renamed from `CONF_PERIMETER_ALERT_HOURS_START/_END`; §D6) | operator-tunable policy |

---

## §10 — Deliverables + acceptance criteria

### D0 — Probe/measurement (§4)
`AUDIT_llmvision_doorbell_shape.md`, `AUDIT_llmvision_latency_probe.md`,
`AUDIT_ha_dormant_automations.md`, optional live doorbell hotfix
executed (D0.4). All required before their gated deliverables open.

### D1 — Retire the legacy notify leg (rev-2 #9)
Delete BOTH `_async_send_legacy_notification` call sites — **:1291
(person)** and **:2305 (vehicle)**. Keep the method one release as
code-dead; log one-shot ERROR when legacy keys populated.
- **Verify:** `grep -n '_async_send_legacy_notification(' perimeter_alert.py`
  returns 0 call sites; method definition remains once (code-dead).
- **Test:** `test_perimeter_alert_person_leg_no_legacy` — event on
  person path, legacy keys set → 0 legacy calls, 1 ERROR log at setup.
- **Test:** `test_perimeter_alert_vehicle_leg_no_legacy` (rev-2 #9 —
  explicit vehicle-path no-legacy test; rev-1 missed this) — event on
  vehicle path with legacy keys → 0 legacy calls.
- **Live:** ERROR fires once at setup iff operator still has keys.

### D2 — Remove existence-window gate (person); contextual severity function (S4, §6)
- **Verify:** `:968` no longer short-returns on out-of-window; person
  telemetry emits at `:1687`/`:1696` drop the `_is_in_alert_hours`
  field and add `severity_tier`.
- **Test:** `test_perimeter_daytime_dispatches_home_day_low`.
- **Test:** `test_perimeter_daytime_away_critical`.
- **Test:** `test_perimeter_circling_overrides_house_state`.
- **Test:** `test_perimeter_waking_perimeter_critical` (rev-2 #4).
- **Test:** `test_perimeter_arriving_medium` (rev-2 #4).
- **Test:** `test_perimeter_home_day_persons_home_zero_high` (row 5e).
- **Test:** `test_perimeter_inwindow_byte_identical_for_away` — event
  in old 23–05 window with `house_state=away` still CRITICAL,
  payload byte-identical modulo the dropped `_is_in_alert_hours` field.
- **Test:** `test_contextual_severity_total_over_house_states` —
  iterate every `HouseState` value, assert no `KeyError` and every
  returned severity is a legal `Severity` enum member.

### D3 — Universal llmvision enrichment (S1, S2) — rev-2 #2 + #7

New `perimeter_enrichment.py` provider adapter:

```python
async def enrich_dispatched_alert(
    hass, snapshot_path: str, camera_entity_id: str
) -> str | None:
    # 1. Kill switch (rung 1) + config gate (rung 2) → return None early.
    # 2. Call llmvision `image_analyzer` via hass.services.async_call
    #    with model=CONF_PERIMETER_ENRICHMENT_MODEL (default gpt-4o-mini),
    #    max_tokens=CONF_PERIMETER_ENRICHMENT_MAX_TOKENS (default 1500),
    #    image_file=snapshot_path (verified working shape from D0.1).
    # 3. Wrap in asyncio.wait_for(..., timeout=perimeter_enrichment_timeout_s).
    # 4. Return shape from provider (verified D0.1):
    #        {"response_text": "<str>"}
    # 5. INV-ENRICH-NON-EMPTY: text = (result.get("response_text") or "").strip()
    #    if not text: return None
    #    return text
    # 6. On asyncio.TimeoutError | Exception: _LOGGER.warning(...); return None.
```

Called from BOTH S1 (`:1258` caller side) and S2 (`:2275` caller side)
BEFORE `nm.async_notify`. Result concatenation into `message` uses a
base-message template with an enrichment slot (rev-2 L3):

```
base = "Perimeter Alert — Person Detected on {entity_id} at {hh:mm:ss}."
if enriched:  message = f"{base}\n\n{enriched}"
else:         message = base
```

`route_reason` set by caller: `NM_ROUTE_REASON_ENRICHED` on success,
`NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH` on any of the three
failure classes when enrichment was enabled + allowlisted; falls back
to the pre-cycle route_reason path when enrichment was gated off.

**Abandoned-call contract (rev-2 #2 ADJUDICATED — cancel-immediately):**
- `asyncio.wait_for` on timeout cancels the underlying task via
  native coroutine cancellation. We accept that:
  - The provider MAY still bill for the cancelled call (cheapest
    correct option — the alternative "wait forever, retry later" is
    strictly worse for the operator's phone).
  - A cancelled task **cannot late-deliver** into the alert path — the
    coroutine reference is dropped and the caller has already passed
    `nm.async_notify`. This makes the double-dispatch race **structurally
    dead**: no `if not cancelled` gate needed at the call site.
- **Alternatives considered and rejected:**
  1. "Detach + wait for late result, deliver as follow-up message" —
     introduces synthetic-time seam + a rare-fire late-completion path.
     Marginal-benefit pushback: enrichment latency is single-shot and
     small; late follow-up trains the operator to expect a second
     buzz per event. Rejected.
  2. "Cache latest late result for next event on same camera" — cache
     invalidation on a rare path; camera identity is not enough (scene
     differs). Rejected.
  3. "Return partial result on timeout" — provider API returns only on
     completion; no partial available. Rejected as impossible.
- Test that pins the contract: `test_enrichment_late_completion_never_double_dispatches`
  (see below).

**Tests (each is a mutation-anchored oracle — neuter the guard, one
specific test fails):**
- **INV-ENRICH-BUDGETED:** `test_enrichment_timeout_falls_through` —
  provider hangs 10s, `timeout_s=2`, NM emit called at ≤2.2s with
  base message; byte-identity vs enrichment-OFF payload.
- **INV-ENRICH-NEVER-SILENCES / exception:** `test_enrichment_exception_falls_through`
  — provider raises `HomeAssistantError` → NM emit with base message +
  `route_reason=NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH`.
- **INV-ENRICH-NON-EMPTY (rev-2 #1 — new test):**
  `test_enrichment_empty_response_falls_through` — parametrized over
  `[None, "", "   ", "\n\t"]` returned as `response_text` → adapter
  returns None; NM emit with base message + failure route_reason;
  message body does NOT contain a trailing separator/whitespace tail.
- **Cancel contract (rev-2 #2 — new test):**
  `test_enrichment_late_completion_never_double_dispatches` — the
  provider coroutine records how many `nm.async_notify` calls occur
  under two scheduled orderings: (a) timeout fires FIRST at t=2s,
  provider completes at t=3s; (b) provider completes at t=1.9s,
  wait_for returns success. Both orderings assert exactly ONE
  `nm.async_notify` call. Mutation drill: remove the `wait_for` wrap
  and rely on the coroutine directly → the test that pins scenario
  (a) MUST turn red.
- `test_enrichment_disabled_byte_identical` — enrichment OFF, payload
  byte-identical to pre-cycle NM call.
- `test_enrichment_vehicle_path_enriched` — parity for S2.
- `test_enrichment_only_when_snapshot_path_present` — URL-fallback
  event (no `snapshot_path`) → adapter never called.
- **Empty-snapshot test (rev-2 L1):** `test_enrichment_missing_snapshot_no_call`
  — `snapshot_path` is None OR empty string OR path doesn't exist →
  adapter returns None early, NM emit with base message.
- **Concurrency statement (rev-2 L2):** two concurrent events on
  different cameras invoke the adapter independently; each has its
  own `wait_for` scope; no shared state in the adapter module (no
  module-level counters, no shared client instance beyond what
  hass.services provides). Pinned by
  `test_enrichment_two_cameras_concurrent_isolated`.

- **Live:** first enriched organic event carries image + description;
  dispatch within `timeout_s + 1s` of detection.

### D4 — Config-flow Option C surfacing (S7, S8) — with M4 promote gate (rev-2 M4)

- **Ships default OFF.** `CONF_PERIMETER_ENRICHMENT_ENABLED` = False,
  `CONF_PERIMETER_ENRICHMENT_CAMERAS` = [] at v(N).
- **M4 promote gate — explicit:** after **14 full days of ledger data**
  post-D3 (measured by ledger row timestamps, not calendar), the
  operator reviews the D0.3-projected cost against actual dispatched
  alerts. If within budget, promote defaults to `_ENABLED=True` +
  `_CAMERAS=[doorbell_pair]` in a hotfix release. This is written in
  §D4 as a named follow-up gate so it is not silently forgotten.
- **Verify:** Perimeter Alerting step now shows: cameras + egress +
  snapshot offset + enrichment {enabled,provider,cameras,model,max_tokens} +
  cross-reference line ("Delivery configured under NM → Persons");
  legacy `_NOTIFY_SERVICE`/`_TARGET` gone; `_HOURS_*` renamed vehicle-
  scoped (§D6).
- **Test:** `test_config_flow_perimeter_option_c_roundtrip`.
- **Test:** `test_config_flow_perimeter_legacy_keys_stripped_on_load`.
- **Test:** `test_config_flow_perimeter_vehicle_hours_migrated` (rev-2 #6).
- **Live:** operator toggles enrichment, reload, next event enriched.

### D5 — HA doorbell + G4 migrate-then-retire (H1, H2) — rev-2 #5
Two-step, both gates ledger-observed per §7 (N=5 rule). No calendar.

### D6 — Schema drop v(N+1) for retired keys + vehicle-window rename (rev-2 #6)

**Removed keys:** `CONF_PERIMETER_ALERT_NOTIFY_SERVICE`, `_TARGET`.

**Renamed keys (values carried over):**
- `CONF_PERIMETER_ALERT_HOURS_START` → `CONF_PERIMETER_VEHICLE_HOURS_START`
- `CONF_PERIMETER_ALERT_HOURS_END`   → `CONF_PERIMETER_VEHICLE_HOURS_END`
- Helper rename: `_is_in_alert_hours` → `_is_in_vehicle_alert_hours`,
  consulted ONLY from S4 vehicle site :2041.

**Rationale for RENAMED not DELETED (rev-2 #6 adjudicated):** the
deep-night vehicle window is *policy* (operator's negative-signal
design: "a vehicle at my house at 3am is suspicious"), not *protocol*.
Removing operator tunability would force a code round-trip for a
threshold change the operator legitimately turns. Values migrate: at
`async_setup_entry`, if the old keys are present and the new keys are
absent, copy old → new and log INFO per key.

- **Verify:** `const.py` and `config_flow.py` show only the renamed
  vehicle-scoped keys; `_HOURS_*` alert-hours grep returns 0 hits
  outside the migration shim.
- **Test:** `test_options_migration_strips_retired_perimeter_keys`.
- **Test:** `test_options_migration_renames_hours_keys_to_vehicle`
  — options with old keys populated → after load, new keys hold the
  values, old keys absent.
- **Test:** `test_vehicle_alert_hours_gate_uses_renamed_helper` —
  neuter `_is_in_vehicle_alert_hours` at S4 :2041 → the vehicle
  in-window test turns red (mutation-anchored).

### D7 — HA dormant automations delete (H3–H5)
Gated by D0.5. Verify pre-delete grep against
`AUDIT_ha_dormant_automations.md` matches; delete matching entries
plus `packages/upzone_zone2_package.yaml` and
`packages/back_hallway_hvac.yaml`.
- **Verify:** post-delete grep in `automations.yaml` for
  `*_person_occupancy` and across `packages/` returns 0.

### D8 — zone_monitoring toggle-off + in-code tripwire (§8)
- **Verify:** both input_booleans OFF; tripwire subscribed at setup
  (log INFO on subscribe); NM notification `URA_ZONE_MONITORING_LEAK`
  MEDIUM registered.
- **Live:** dashboard push-per-event on interior camera motion stops;
  tripwire silent → auto-close of yaml notify strip in follow-up.

### D9 — TEST-1 boot-time shadow diff — DEFER
Deferred to resolver micro-cycle (accounted, not dropped).

### D10 — TEST-2 "Send Test Perimeter Alert" button (folded)
Fires canned event through the full stack at MEDIUM severity (§14#4)
using a bundled sample snapshot.

---

## §11 — Explicit non-goals

- iMessage attachments (SNAP-1 BB gap — BlueBubbles integration
  structurally drops them).
- BlueBubbles integration changes.
- Face-recognition escalation.
- Retiring `packages/zone_monitoring.yaml` counters/template sensors.
- Changes to NM persons/channels/severity gates themselves.
- Animal-detection paging beyond the linker episode.

---

## §12 — Tier justification

**Proposed: Tier 2-DB.** Framings unchanged from rev-1:
- Review A — correctness + edge cases (contextual severity totality
  incl. every HouseState row §6; three enrichment failure classes
  §2; `snapshot_path` empty-vs-None vs NM predicate at
  `notification_manager.py:1423`).
- Review B — cross-coordinator + lifecycle + migration (D6 option-
  strip AND rename; NM persons/channels unchanged; boot-settle;
  teardown; `is_stopping` guard on adapter).
- Review C — surfaces + duplication invariant + per-site mutation
  drills on S1, S2, S3-person, S3-vehicle, S4-vehicle, S6; triple-
  path fixture proving INV-CONSOL-1.
- Review D — live validation + README write-back with §7 parity
  table.

**§12b — Why NOT Tier 3.** Subtractive on legacy paths, additive on
one new stage at two enumerated emit sites, LOUD failure mode
(missed notification is user-visible on operator's phone). Escalate
if plan review finds a third emit site or a shared-primitive change
missed here.

---

## §13 — Sequencing

1. D0 probes (§4) — D0.1 gates D3; D0.5 gates D7; D0.4 gates P2.
2. D1 + D2 + D4 (default OFF) + D6 rename+strip — one release.
3. D3 — depends on D0.1/D0.2.
4. D5-step-1 — ledger N=5 gate per §7.
5. D5-step-2 — next release after ledger N=5 clean-observed.
6. D7 — sequenced with D5-step-2 for one HA restart.
7. D8 — with the URA release; yaml changes strictly later (in-code
   tripwire auto-closes).
8. D10 — with D3.
9. M4 promote gate — after 14 full days of ledger data post-D3.
10. D9 — DEFERRED.

---

## §14 — Open design points → dispositions

1. **Enrichment default.** Default OFF at ship; M4 promote gate
   after 14 full days ledger data (rev-2 M4).
2. **G4 folding.** ADOPTED — fold entirely into enrichment (rev-2 #3
   corrected G6→G4).
3. **`NM_ROUTE_REASON_ENRICHED` (rev-2 #7 — ADOPTED).** Defined beside
   the NM-IMAGE-1 route-reason constants at const.py:1446-1451, next
   to `NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH`. Dashboards
   consume `route_reason ∈ {…, NM_ROUTE_REASON_ENRICHED,
   NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH}` to distinguish
   enrichment success/failure without touching message body shape.
4. **Test-alert button (D10) severity — MEDIUM.**
5. **§8 zone_monitoring bundling — in-cycle toggle + in-code tripwire.**
6. **Deep-night vehicle window — RENAMED not removed (rev-2 #6).**

---

## §15 — Plan-review checklist

(Unchanged from rev-1 — reviewer verifies with greps, not trust.)

---

## §16 — Plan-review record

### Rev-1 review — VERDICT: NEEDS-REVISION (2026-08-11)

Nine findings + adjudications. All adopted in rev-2.

| # | Finding | Rev-2 disposition |
|---|---|---|
| 1 | INV-ENRICH-NON-EMPTY missing; INV-ENRICH-NEVER-SILENCES vague on failure classes | §2 restated to enumerate 3 classes; new NON-EMPTY sub-invariant; D3 test added |
| 2 | Model/max_tokens/timeout unpinned; abandoned-call race unspecified | §D3 pins `gpt-4o-mini` + 1500 + 4.0s; cancel-immediately contract with rationale for rejecting 3 alternatives; new test `test_enrichment_late_completion_never_double_dispatches`; verified return shape `{"response_text": ...}` pasted in §D3 and §4 |
| 3 | S2 wrong line; S4 incomplete; H2 misnamed; H3 body span missing | §5 corrected: S2 → :2275, S4 → :968 + :1687, :1696, :2041 with per-consumer disposition; H2 → G4 with blueprint path; H3 body ~7870-7930 with two llmvision refs noted |
| 4 | Severity table not total; ARRIVING/WAKING missing | §6 total table over 9 HouseState values with explicit rows; ARRIVING=MEDIUM, WAKING=CRITICAL(perimeter)/MEDIUM(egress); `case _:` fail-safe CRITICAL |
| 5 | §7/§D5/§8 used calendar windows | Ledger-observed gates: N=5 rule for D5-step-1/step-2; §8 in-code tripwire with auto-close |
| 6 | Vehicle window keys: keep/rename/drop unresolved | RENAMED to `CONF_PERIMETER_VEHICLE_HOURS_START/_END` with value migration; helper renamed; new migration test |
| 7 | `NM_ROUTE_REASON_ENRICHED` uncommitted | ADOPTED (§14#3, §1 REUSED table, §9); pair with FAILED_FALL_THROUGH |
| 8 | Missing D0.4 (doorbell hotfix) and D0.5 (dormant enum) | D0.4 OPERATOR-GATED with offer already made; D0.5 blocks D7 |
| 9 | §D1 only named one legacy call site; missed vehicle | Both sites named (:1291 person, :2305 vehicle); vehicle-path no-legacy test added |

**M4 (folded):** ship default OFF; explicit 14-days-of-ledger-data
promote gate in §D4.

**L1–L5 (folded):**
- L1: empty-snapshot test → `test_enrichment_missing_snapshot_no_call` (§D3).
- L2: concurrency statement → §D3 + `test_enrichment_two_cameras_concurrent_isolated`.
- L3: base-message template with enrichment slot → §D3 shows template.
- L4: parity-window double-page README note → §7 last paragraph.
- L5: (implicit — plan-review record kept in doc) → §16 itself.
