# PLANNING — CONSOL-1: Alerting-stack consolidation + universal llmvision

**Card:** CONSOL-1 (docs/planning/kanban.data.yaml:1485)
**Status:** DRAFT for adversarial plan review (ONE pass, per Tier 2 plan-review policy)
**Tier proposed:** Tier 2-DB (three framing-disjoint code reviews + live validation).
See §12 for the case; not proposing Tier 3 (see §12b for why not).
**Date:** 2026-08-11
**Predecessors merged live:** SNAP-1 (v5.63.0, local file capture into
`/media/ura/snapshots`), NM-IMAGE-1 (v5.71.0, `NM_SECURITY_HAZARDS`
frozenset + two-site force-immediate predicate + gate mirror), RESACC-1
(v5.65.0, resolver accuracy suite).
**Operator rulings ratified (2026-08-07, ref cards + `PLANNING_perimeter_consolidation.md` §Operator rulings):**
1. Config-home = Option C surfacing (Perimeter Alerting stays a
   top-level config step; internal detection-vs-delivery split; named
   trigger for a future "Security" umbrella not yet earned).
2. Universal llmvision enrichment on ALL camera alerting (perimeter +
   egress, all severity tiers), enriched per DISPATCHED alert (post
   cooldown/dedup), not per raw detection.
3. Day/night is NOT a valid boundary for person alerting — the 23–05
   existence window is REMOVED; severity derives from the contextual
   model (house_state × camera class × track classification). Exception
   retained: deep-night VEHICLE window (`_async_handle_vehicle_trigger`
   — hour IS the signal there).
4. Doorbell WhatsApp automation is MIGRATE-THEN-RETIRE (it carries
   daytime front-door coverage + llmvision + vehicle/animal classes).

---

## §1 — Institutional context verified

**Prior planning + audit docs pulled (full body):**
- `docs/planning/PLANNING_perimeter_consolidation.md` (draft the operator
  ruled on 2026-08-07; §Operator rulings block is the load-bearing
  restatement of scope for this cycle).
- `docs/planning/AUDIT_ha_side_alerting_reconciliation.md` (retirement
  list, double-paging verdict §2, zone_monitoring per-event pager stack).
- `docs/planning/PLANNING_nm_image_delivery.md` + `docs/readmes/README_v5.71.0.md`
  (NM-IMAGE-1: `NM_SECURITY_HAZARDS`, force-immediate predicate,
  gate mirror, named route reasons).
- `docs/planning/PLANNING_snap1_at_detection_snapshots.md` +
  README_v5.63.0 (snapshot capture engines, `/media/ura/snapshots`,
  bluebubbles-attachment gap).
- Kanban cards CONSOL-1, SNAP-1, TEST-1, TEST-2, RESACC-1 (folded
  scope) — kanban.data.yaml:1485, :1517, :1701, :1718.

**Code surfaces greped / read end-to-end:**
- `custom_components/universal_room_automation/perimeter_alert.py`
  — `_async_handle_perimeter_trigger` (:963), snapshot resolution
  (`_resolve_snapshot_url_and_delay` :1389, `_await_edge_capture` :1177),
  NM dispatch site (:1258), vehicle path (:2224 with dispatch :2286),
  legacy leg (`_async_send_legacy_notification` — grep confirmed at
  :1754 per audit), Frigate event cache (:678).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py`
  — `async_notify` (:1186), `_force_immediate_for_security_image`
  predicate (:1235), gate-mirror (`force_immediate_for_security_image`
  arg, :3529 / :3579), `_send_whatsapp` (:2023) — `media_path` and
  `snapshot_path` threading already present.
- `custom_components/universal_room_automation/const.py:1409-1451`
  — `NM_SECURITY_HAZARDS` frozenset (rung-1 kill switch),
  named `NM_ROUTE_REASON_*` constants, hazard severity tables
  (:1460 `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE`, :1330
  track severity map).
- `config_flow.py:3012-3093` (Perimeter Alerting step; legacy
  `CONF_PERIMETER_ALERT_NOTIFY_SERVICE`/`_TARGET`, `_HOURS_START/END`,
  snapshot offset), :2591-2596 (Configure Settings menu registration),
  :7482-7537 (`default_notifications`).
- HA live artifact (not in-repo): the WORKING doorbell automation
  invocation shape (llmvision service name + argument shape). This is
  NOT in the repo — it lives in `/config/automations.yaml`. Extraction
  is a hard **D0 gate** (§4) so the enrichment adapter is built against
  the real service, not a fabricated signature (No-Fabrication rule).

**Proposed additions — REUSED vs NEW table:**

| Proposed | REUSED / NEW | Rationale / file:line |
|---|---|---|
| `enrich_dispatched_alert(...)` in a new `perimeter_enrichment.py` provider adapter | NEW | No `enrich`/`llmvision` grep hits in URA code; single choke point matches the "one router" invariant |
| `CONF_PERIMETER_ENRICHMENT_ENABLED` (bool, default OFF) | NEW | Cost-gated opt-in; no equivalent in `const.py`/`config_flow.py` |
| `CONF_PERIMETER_ENRICHMENT_PROVIDER` (str, default `"llmvision"`) | NEW | Provider abstraction (only `llmvision` implemented v1) |
| `CONF_PERIMETER_ENRICHMENT_CAMERAS` (list, default = today's 2 doorbell cams if `_ENABLED`; else empty) | NEW | Cost & privacy per-camera allowlist |
| `perimeter_enrichment_timeout_s` (Number entity, default 4.0) | NEW rung-3 (live-tunable via dashboard, persisted) | Latency budget the operator legitimately tunes by observation |
| `LLMVISION_ENRICHMENT_KILL` (module const, default False) | NEW rung-1 | Hard kill switch; a bad provider release must be defeatable without a config reload |
| `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` (small function over the existing house_state map + linker track class) | REUSED shape of :1460 map; NEW function | Replaces removed 23–05 existence gate |
| Migration: strip retired `CONF_PERIMETER_ALERT_NOTIFY_SERVICE/_TARGET/_HOURS_START/_HOURS_END` | REUSED option-strip pattern from prior deprecation cycles | one-version-late schema drop; §D6 |

Design docs read: none dedicated to perimeter (perimeter_alert.py
docstring + the two ref docs are canonical). No `docs/Coordinator/*.md`
entry for perimeter or NM.

---

## §2 — Falsifiable invariant

**INV-CONSOL-1 (single-thread invariant, extends INV-XP):**

> Under any legal config (any severity schedule, any enrichment
> on/off, any camera set, any llmvision latency, any llmvision
> failure mode) a single physical exterior camera event produces
> **exactly ONE** notification thread across all four historical
> stacks (URA perimeter NM, URA legacy notify leg, HA doorbell
> automation, HA G6 blueprint) — AND llmvision failure NEVER
> silences, delays past the wall-clock timeout, or duplicates that
> single thread.

Two falsifying observations, either kills ship:
1. A physical event that today dispatches ONE thread producing TWO
   after retire (unlikely — retirement is subtractive; adversary would
   look for a doubled emit inside `async_notify` when `snapshot_path`
   is set AND enrichment appended a message tail, or a race where the
   enrichment coroutine itself dispatches).
2. A physical event that today paged (via doorbell automation, outside
   the retired 23–05 window) dispatching ZERO threads after retire
   ("daytime gap" — the operator-visible regression the migration
   sequencing exists to prevent).

Two additional load-bearing sub-invariants (each pinned by a
mutation-anchored test in D3):
- **INV-ENRICH-BUDGETED:** llmvision hang > timeout → NM dispatch
  fires at t=timeout without the description, byte-identical to the
  enrichment-OFF payload for that event.
- **INV-ENRICH-NEVER-SILENCES:** any llmvision exception (adapter
  raise, provider 5xx, config missing) → NM dispatch fires without
  the description; ledger row carries a distinct `route_reason`
  (`enrichment_failed_fall_through`); no exception propagates to the
  caller.

---

## §3 — Design overview

**One router, one message, one snapshot, one enrichment step.**
Extends NM-IMAGE-1's "one predicate, two suppression sites, one
gate mirror" shape — enrichment is added as ONE new stage between
snapshot resolution (`perimeter_alert.py:1177`) and NM dispatch
(`perimeter_alert.py:1258`), on BOTH person and vehicle dispatch paths
(the vehicle handler at :2224 has the identical shape and MUST get the
same call — enumeration in §5).

Runtime shape:
```
edge detect → cooldown/dedup gate → severity coercion (contextual §6)
  → capture snapshot (SNAP-1 pipeline, already live)
    → **enrichment (this cycle, gated + timeout + fall-through)**
      → NM.async_notify(snapshot_path=..., message=base+enriched)
        → force-immediate predicate (NM-IMAGE-1, already live)
```

Enrichment is placed AFTER cooldown/dedup gates on purpose (operator
ruling 2 — "per DISPATCHED alert, not per raw detection"). It reads
`snapshot_path` (SNAP-1's file); the URL fallback path is NOT
enriched in v1 (llmvision needs a local file, and we should not
force a URL-fetch just to feed it).

---

## §4 — D0 (probe/measurement gate — MEASURE BEFORE YOU BUILD)

Per the "empirically-gated cycle" checklist, three questions gate the
enrichment deliverable and cannot be answered from mental model:

**D0.1 — Extract the WORKING doorbell automation invocation shape.**
Read `/config/automations.yaml` (via ha-mcp `ha_get_state` on the
automation, or ssh cat) and record the exact llmvision service name,
argument keys, and the `image_file`/`image_entity`/`camera_entity`
input shape. Commit the extracted YAML block into
`docs/planning/AUDIT_llmvision_doorbell_shape.md`. This is the
adapter's contract source. **Do not code the adapter from the docs of
the llmvision integration alone — audit the working call.**

**D0.2 — LLM latency distribution on real snapshots.**
One-shot read-only probe: pick 20 recent files from
`/media/ura/snapshots` (~1 week retention per SNAP-1), invoke the
real llmvision service against each, record wall-clock latency +
success/error. Report p50 / p90 / p99 / max + error rate into
`docs/planning/AUDIT_llmvision_latency_probe.md`. Gates:
- If p90 > 8s or error rate > 20%: pause D3 and reconsider budget/
  default-OFF policy (enrichment is likely more cost than value in
  the alert path).
- If p90 ≤ 4s and error rate < 5%: 4s default timeout stands.
- Intermediate: retimeout per data.

**D0.3 — Cost accounting.**
Multiply the average dispatched-alert rate (from `notification_log`
`hazard_type IN ('exterior_person','exterior_vehicle')` last 14d)
by the projected enable state (default-OFF vs default-ON for the two
current doorbell cams). Report projected calls/day. Gate: if the
default-ON policy for the current two cams exceeds ~50 calls/day
sustained, keep default OFF.

**D0 is not a runtime feature**; it produces two markdown audits and
is thrown away. Nothing else in this plan may be BUILT until D0.1
lands (D0.2/D0.3 gate only D3 defaults, not the rest of the cycle).

---

## §5 — Emission-site enumeration (S-style; independent re-run required in plan review)

Every alert-emitting surface being consolidated OR touched. The plan
review MUST re-grep these independently (per Plan Review Tier 2 rule);
this list is a hypothesis.

**URA (repo, in-scope):**
| S# | Surface | File:line | Disposition |
|---|---|---|---|
| S1 | Person dispatch — `PerimeterAlertManager._async_handle_perimeter_trigger` NM emit | perimeter_alert.py:1258 | Add enrichment call between :1177 and :1258; retain snapshot_path |
| S2 | Vehicle dispatch — `_async_handle_vehicle_trigger` NM emit | perimeter_alert.py:2286 | Same enrichment call; deep-night window per operator ruling 3 is RETAINED here |
| S3 | Legacy dispatch — `_async_send_legacy_notification` | perimeter_alert.py:1754 | RETIRE (deprecation → code-dead v(N) → delete v(N+1)); already gated by NM-primary path |
| S4 | Existence-window gate (person) | perimeter_alert.py:637-643 (per prior planning doc line-ref; verify in review) | REMOVE gate; the clock-window is DROPPED entirely from person path (operator ruling 3) |
| S5 | NM `async_notify` | notification_manager.py:1186 | Payload shape unchanged; `message` field is where the enrichment string is concatenated at S1/S2 CALLER side (NOT inside NM — keeps NM provider-agnostic) |
| S6 | Force-immediate predicate | notification_manager.py:1235 + gate mirror :3579 | UNCHANGED; enrichment must not defeat it (INV-ENRICH-NEVER-SILENCES — enrichment failure still dispatches with snapshot_path → predicate still TRUE) |
| S7 | Config-flow `default_notifications` step | config_flow.py:7482-7537 | UNCHANGED (persons/channels live here per Option C split) |
| S8 | Config-flow Perimeter Alerting step | config_flow.py:3012-3093 | ADD enrichment fields; REMOVE legacy notify_service/target + hours_start/end fields (Option C internal WHAT/WHEN partition) |

**HA-side (repo-external, `/config/`, in-scope for retire):**
| H# | Surface | Disposition |
|---|---|---|
| H1 | `Doorbell Detection WhatsApp Alert` automation | MIGRATE-THEN-RETIRE (§7 parity checklist gates disable; delete after 48h observed) |
| H2 | `G6 Doorbell Analysis` blueprint on `binary_sensor.madrone_g6_entry_motion_2` | MIGRATE-THEN-RETIRE (folded into universal-llmvision on that camera) |
| H3 | `Phase 1: All Detections — Dual System (AI)` (14 F1 `*_person_occupancy` refs) | DELETE (already OFF since 2026-02-18) |
| H4 | `Phase 1: Known Person — Dual System` (3 F1 face sensors) | DELETE (already OFF; face-recog is out-of-scope follow-up per audit §5.5) |
| H5 | 12 dormant HVAC/presence/arrester/guest automations | DELETE (per audit §5.1) |
| H6 | `packages/zone_monitoring.yaml` — 4 per-event mobile-push counter automations (Zone1/3 motion + person) | DISPOSITION §8 |
| H7 | Zone1/Zone3 Inactivity Alert + Multi-Zone Daily Summary + Reset (packages/zone_monitoring.yaml) | DISPOSITION §8 |
| H8 | Frigate MQTT bridge (both topics) | KEEP (URA-owned since v5.44.0) |

**Explicit non-goals (§11):** iMessage attachments (BB integration
structurally drops them — SNAP-1 verification results captured that);
BlueBubbles integration changes; face-recognition escalation
(separate cycle per audit §5.5).

---

## §6 — Contextual severity (replacing the day/night window)

**Inputs (all already computed elsewhere; consumed here):**
- `house_state` (HouseState StrEnum — already the key for
  `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE` at const.py:1460).
- `person-home-count` (NM already knows this — via the trusted-count
  reader used for guest latch, v5.16.0).
- Camera CLASS (`perimeter` vs `egress` — already partitioned by the
  two config lists `CONF_PERIMETER_CAMERAS` / `CONF_EGRESS_CAMERAS`).
- Detection CLASS (`person` vs `vehicle` vs `animal` — the vehicle
  path is already separated; animal remains linker-only per Cycle-2).
- Track classification (`approach` / `linger` / `circling` / `first
  sighting` from the ExteriorTrackLinker — already available via
  `linker.find_owning_track` / `path_string`, consumed at :1215).

**Contextual severity table (default; module const, rung-1):**

`NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` — a small function
(not a static dict) taking `(house_state, camera_class, track_class,
persons_home)` → Severity. Defaults derived from operator ruling 3:

| house_state | camera_class | track_class | persons_home | Severity |
|---|---|---|---|---|
| away / vacation / sleep / home_night | perimeter | any | any | CRITICAL |
| away / vacation | egress | approach OR linger | any | CRITICAL |
| home_day / home_evening | perimeter | first_sighting | ≥1 | LOW |
| home_day / home_evening | perimeter | approach OR linger | ≥1 | MEDIUM |
| home_day / home_evening | egress | approach | ≥1 | LOW (expected foot traffic) |
| any | perimeter | circling | any | HIGH (override; independent of house_state) |
| guest | any | any | any | `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` (already extracted at const.py:1455) |
| unknown / missing | any | any | any | CRITICAL (fail-safe) |

Vehicle keeps its existing `_async_handle_vehicle_trigger` shape;
deep-night window is retained THERE per operator ruling 3, unchanged.

**Retired knobs (schema-strip in v(N+1)):**
- `CONF_PERIMETER_ALERT_HOURS_START`, `_HOURS_END` (const.py:1165-1168,
  defaults :1171) — removed entirely from person path; the 23–05
  window is gone.
- `CONF_PERIMETER_ALERT_NOTIFY_SERVICE`, `_TARGET` — removed (§D6).

**Retained:**
- `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` (still used by URL fallback path).
- `PERIMETER_ALERT_COOLDOWN_SECONDS` (5-min per-camera; audit §2
  confirmed the doorbell no-cooldown was a defect not a feature).
- Vehicle deep-night window (unchanged).

---

## §7 — Migrate-then-retire: doorbell automation parity checklist

Doorbell automation stays ENABLED during v(N) — this cycle's ship —
until the parity table below is PASS on organic events. Only then does
D5-step-1 (disable, keep in yaml) execute; D5-step-2 (delete) fires 48h
after that.

**URA must prove, live, on organic front-door events:**
| P# | Parity criterion | Evidence |
|---|---|---|
| P1 | WhatsApp message arrives WITH image, within seconds of detection | Ledger row `route_reason=force_immediate_security_image` + WhatsApp receipt timestamp within 5s of `notification_log.dispatched_at` |
| P2 | Message body contains an llmvision description string of comparable quality to the doorbell automation's | Side-by-side spot check: 5 consecutive front-door events, both stacks firing, operator confirms URA's enrichment is acceptable |
| P3 | Vehicle detection paged with image (deep-night window retained) | One post-deploy 23–05 vehicle event: URA NM row + WhatsApp with image |
| P4 | Animal detection: URA linker records episode; no operator page (per operator's implicit "person + vehicle only" preference — the doorbell automation's animal leg is NOT restored) | linker episode row present; NM notification_log row absent |
| P5 | Front-door coverage OUTSIDE the retired 23–05 window (was doorbell-only) — one daytime event pages via URA NM | notification_log row w/ `hazard_type=exterior_person`, `house_state ∈ home_day/home_evening`, image attached |
| P6 | Failure fall-through: at least one llmvision timeout/error observed → NM still dispatched with image, no gap | ledger row `route_reason=enrichment_failed_fall_through` present at least once OR the operator manually kills the adapter and observes P1 still holds |
| P7 | INV-CONSOL-1 single-thread: one physical event → one WhatsApp thread on ops phone | Operator observation over the parity window |

Only when P1–P7 are all PASS (recorded in README_v<version>.md's
Live Validation table) does D5-step-1 execute. This is the operator's
explicit hedge against the daytime-gap regression class.

---

## §8 — zone_monitoring pager stack disposition

Per audit §5.3 + operator's silence-tolerance for interior push-per-event
noise, this cycle:
- Turns `input_boolean.zone{1,3}_monitoring_active` OFF at v(N)
  (config-only change, reversible in one click).
- Does NOT strip the yaml (`packages/zone_monitoring.yaml`) at v(N).
- 2-week observation window post-ship. If quiet, follow-up commit
  strips the `notify.mobile_app_*` action from the 4 counter
  automations. If counters + template sensors + utility_meters go
  unused (verified by grep of dashboards + URA), the whole yaml
  retires in a separate commit — NOT in this cycle.

**Rationale for splitting:** the retire risk is subtractive and
observable within 2 weeks; keeping the yaml disabled costs zero live
behavior and lets a fast rollback be a boolean toggle. Retirement of
counters is a broader dashboard-touching change; it doesn't belong
bundled with the alerting consolidation.

---

## §9 — Knobs on the ladder

Every new number lands on the rung its governance requires (Numbers
Get Knobs, operator 2026-07-16).

| Knob | Rung | Home | Why this rung |
|---|---|---|---|
| `LLMVISION_ENRICHMENT_KILL` | 1 (module const) | `const.py` | Hard kill switch; a bad llmvision release must be defeatable via code review, not a slider |
| `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` (default table) | 1 (module const) | `const.py` | Safety-adjacent policy; changes require review |
| `CONF_PERIMETER_ENRICHMENT_ENABLED` | 2 (config flow) | `config_flow.py` Perimeter Alerting step | Per-deployment enable — infrequent, persistent |
| `CONF_PERIMETER_ENRICHMENT_PROVIDER` | 2 (config flow) | same | Structure; changes only when provider abstraction expands |
| `CONF_PERIMETER_ENRICHMENT_CAMERAS` | 2 (config flow) | same | Per-camera allowlist; operator-managed set |
| `perimeter_enrichment_timeout_s` | 3 (Number entity) | `number.py`, persisted via Number-persistence machinery, default 4.0, min 1.0, max 15.0 | Operator legitimately tunes this by observation once D0.2 latency distribution is known |

Kill semantics documented on each knob:
- `LLMVISION_ENRICHMENT_KILL = True` → adapter is a no-op returning
  None; identical to `CONF_PERIMETER_ENRICHMENT_ENABLED = False`.
- `CONF_PERIMETER_ENRICHMENT_CAMERAS = []` → nothing enriched, adapter
  never called.

---

## §10 — Deliverables + acceptance criteria

### D0 — Probe/measurement (§4)
`AUDIT_llmvision_doorbell_shape.md` + `AUDIT_llmvision_latency_probe.md`
committed BEFORE D3 opens. Gates §4.

### D1 — Retire the legacy notify leg (S3)
Delete `_async_send_legacy_notification` call sites; keep the method
one release as code-dead; log one-shot ERROR when legacy keys set.
- **Verify:** grep for `_async_send_legacy_notification(` returns 0
  call sites in `perimeter_alert.py`.
- **Test:** `test_perimeter_alert_legacy_leg_retired` — with legacy
  keys set, setup logs ONE ERROR and no legacy call on an event.
- **Live:** log grep on restart shows ERROR iff operator still has
  keys; NM dispatches every event.

### D2 — Remove existence-window gate; contextual severity function (S4, §6)
- **Verify:** the 23–05 branch at `perimeter_alert.py:637-643` no
  longer short-returns; it either sets no gate or passes hour data
  to the severity function.
- **Test:** `test_perimeter_daytime_dispatches_home_day_low` — event
  outside old window, `house_state=home_day`, `persons_home=2`, first
  sighting → dispatched at LOW.
- **Test:** `test_perimeter_daytime_away_critical` — same conditions
  but `house_state=away` → CRITICAL.
- **Test:** `test_perimeter_circling_overrides_house_state` — HIGH
  regardless of house_state.
- **Test:** `test_perimeter_inwindow_byte_identical` — an event in
  the OLD 23–05 window with `house_state=away` still coerces to
  CRITICAL; payload byte-identical to today.

### D3 — Universal llmvision enrichment (S1, S2)
New `perimeter_enrichment.py` provider adapter with a single
`async def enrich_dispatched_alert(hass, snapshot_path, camera_entity_id)
-> str | None`. Called from BOTH `_async_handle_perimeter_trigger`
(:1258 CALLER SIDE — enrichment happens BEFORE the `nm.async_notify`
call, adapter result is concatenated into `message`) AND
`_async_handle_vehicle_trigger` (:2286 CALLER SIDE).
- Hard timeout via `asyncio.wait_for` (default from Number entity, 4.0s).
- Any exception → `_LOGGER.warning` + return None; caller uses base
  message.
- Route reason on failure: caller stamps `route_reason=
  enrichment_failed_fall_through` when adapter returns None while
  enabled+allowlisted (feeds into ledger row via the existing NM
  route_reason plumbing — verify shape in review).
- **Verify:** grep confirms enrichment call is BEFORE `nm.async_notify`
  on both S1 and S2 paths.
- **Test (INV-ENRICH-BUDGETED):** `test_enrichment_timeout_falls_through`
  — provider hangs 10s, timeout 2s, NM.async_notify called at ≤2.2s
  with base message; asserts byte-identity vs enrichment-OFF payload
  for the same event.
- **Test (INV-ENRICH-NEVER-SILENCES):** `test_enrichment_exception_falls_through`
  — provider raises `HomeAssistantError`, NM.async_notify called with
  base message + `route_reason=enrichment_failed_fall_through`.
- **Test:** `test_enrichment_disabled_byte_identical` — enrichment
  OFF, payload byte-identical to pre-cycle NM call.
- **Test:** `test_enrichment_vehicle_path_enriched` — vehicle
  dispatch invokes adapter (parity with person path).
- **Test:** `test_enrichment_only_when_snapshot_path_present` —
  URL-fallback event (no `snapshot_path`) skips adapter.
- **Live:** first enriched organic event carries an image + a
  description; latency budget adhered (dispatch within `timeout + 1s`
  of detection).

### D4 — Config-flow Option C surfacing (S7, S8)
- **Verify:** Perimeter Alerting step now shows: perimeter cameras +
  egress cameras + snapshot offset + enrichment
  {enabled,provider,cameras} + cross-reference line
  ("Delivery configured under NM → Persons"); legacy service/target/
  hours fields GONE from schema.
- **Test:** `test_config_flow_perimeter_option_c_roundtrip` — save,
  reload, RestoreEntity round-trip.
- **Test:** `test_config_flow_perimeter_legacy_keys_stripped_on_load`
  — options with legacy keys stripped on `async_setup_entry` migration.
- **Live:** operator flips enrichment ON via the Perimeter step,
  reload, next event enriched.

### D5 — HA doorbell + G6 migrate-then-retire (H1, H2)
Two-step, gated by §7 parity checklist.
- Step 1: DISABLE (not delete) both automations after §7 P1–P7 all PASS.
- Step 2: DELETE from `/config/automations.yaml` after 48h observed silent.
- **Verify (staged):** live `automations.yaml` shows the two present-
  but-disabled after step 1; deleted after step 2.

### D6 — Schema drop v(N+1) for retired keys (S3, S4)
- **Verify:** `CONF_PERIMETER_ALERT_NOTIFY_SERVICE`, `_TARGET`,
  `_HOURS_START`, `_HOURS_END` removed from `const.py` (kept as
  historical comment) and from `config_flow.py`; `async_setup_entry`
  option-strip runs on load with an INFO log per stripped key.
- **Test:** `test_options_migration_strips_retired_perimeter_keys`.

### D7 — HA dormant automations delete (H3–H5)
Delete the 14 dormant automations + Phase-1 pair (H3, H4, H5) from
`/config/automations.yaml`, and delete
`packages/upzone_zone2_package.yaml` + `packages/back_hallway_hvac.yaml`.
Zeroes automation-layer F1 exposure.
- **Verify:** grep in live `automations.yaml` for `*_person_occupancy`
  and across `packages/` returns 0 matches.
- **Live:** HA restart clean; no `automation.*` referenced by URA
  is missing.

### D8 — zone_monitoring toggle-off (H6, first step only) (§8)
- **Verify:** both `input_boolean.zone{1,3}_monitoring_active` are
  OFF post-deploy; yaml unchanged.
- **Live:** dashboard push-per-event on interior camera motion stops.
- Follow-up (NOT this cycle): 2wk quiet → yaml notify strip → yaml delete.

### D9 — TEST-1 boot-time shadow diff (folded per kanban) — DEFER
The kanban card TEST-1 folds "into CONSOL-1" as a WARN-if-shrunk
tripwire against the resolver leg set. This cycle already ships against
a resolver validated by RESACC-1 v5.65.0; the shadow-diff is a
resolver-cycle follow-up, not an alerting-cycle deliverable. Explicitly
deferred to its own micro-cycle. Reason recorded here so it is not
silently dropped.

### D10 — TEST-2 "Send Test Perimeter Alert" button (folded per kanban)
New Button entity that fires a canned event through the full
consolidated stack (capture → enrichment → NM → all channels) using
a bundled sample snapshot file. Would have caught the media_url bug
instantly per SNAP-1 kanban.
- **Verify:** button appears under URA device, single press
  produces exactly ONE WhatsApp arrival on the operator phone with
  an image and (when enrichment ON) a description.
- **Test:** `test_perimeter_test_alert_button_endtoend` —
  press invokes the same code path as a real event.
- **Live:** press pre-deploy and post-migration confirms channel
  delivery without waiting for a real intrusion.

---

## §11 — Explicit non-goals

- iMessage attachments — BB integration structurally drops them
  (SNAP-1 verification `bluebubbles/__init__.py:49-90` POSTs only
  `{addresses,message,method}`). Tracked as SNAP-1-followup-bluebubbles-
  attachment; not this cycle.
- BlueBubbles integration changes (bluebubbles → server API, direct
  attachment upload path, etc.). Separate scope.
- Face-recognition escalation (audit §5.5, Phase-1 Known Person
  successor). Separate cycle referenced from
  `PLANNING_exterior_person_escalation.md`.
- Retiring `packages/zone_monitoring.yaml` counters/template sensors
  (§8 — split to a 2-week-later follow-up).
- Changes to NM persons/channels/severity gates themselves — this
  cycle only CONSUMES them (Option C boundary).
- Anything on the animal detection path beyond the linker episode
  (audit-confirmed the doorbell automation covered animal via a page
  the operator has not asked to preserve; parity checklist P4
  explicitly does NOT restore it).

---

## §12 — Tier justification

**Proposed tier: Tier 2-DB (three framing-disjoint code reviews +
Review-D live validation + README write-back).**

Triggers (Tier 2-DB standing policy, "regression-prone"):
- Cross-coordinator ripple: perimeter_alert ↔ NM ↔ house_state ↔
  ExteriorTrackLinker (contextual severity reads all three; NM-IMAGE-1
  predicate depends on `snapshot_path` truthiness).
- Retirement of a shared primitive path (`_async_send_legacy_notification`)
  with live-config consumers.
- Adds a NEW ingredient to the alert path (an LLM call) — a latency
  ingredient by definition, precisely the class MARGINAL-BENEFIT
  PUSHBACK exists for. Enrichment is opt-in with a mandatory failure
  contract (§2 sub-invariants) exactly because this is a categorically
  risky ingredient.

Framings (disjoint):
- **Review A — correctness + edge cases.** Contextual severity table
  totality (every house_state, incl. unknown/missing/None → CRITICAL
  fail-safe); enrichment timeout + failure fall-through paths;
  daytime cooldown behavior; INV-XP preserved; `snapshot_path` empty
  string vs None handling matches NM predicate at
  `notification_manager.py:1423` (rev-2 MED-4).
- **Review B — cross-coordinator + lifecycle + migration.** Option-
  strip migration for D6 retired keys; NM channel/persons config
  unchanged; boot-settle gate for enrichment (must not fire during
  the boot suppression window); teardown of new enrichment provider
  on entry unload; `is_stopping` guard on the adapter path.
- **Review C — surfaces + duplication invariant + test authority.**
  Config-flow round-trips (D4); INV-CONSOL-1 single-thread invariant
  proven by a triple-path fixture (URA + emulated doorbell + emulated
  G6 all pointed at the same event → exactly ONE `notify.*` call
  after D5-step-1). Per-site mutation drills on S1, S2, S6 (each
  neuter → one specific test fails; a green suite = untested site).
- **Review D (live validation).** README write-back with the §7
  parity checklist as the Live table. INV-ENRICH-* validated organically
  (P6 requires observing one real llmvision failure OR one operator-
  forced kill).

**§12b — Why NOT Tier 3.** Tier 3 exists for delicate shared-primitive
changes threading a value through many emission sites where ONE missed
path is a silent cost/safety loss (the v5.5.3 arbitrage-reserve
class). CONSOL-1 is subtractive on legacy paths, additive on a single
new stage on two enumerated emit sites, and its failure modes are
LOUD (a missed notification is user-visible on the operator's phone,
not silent). The falsifiable invariant is proven by a single triple-
path fixture, not by re-enumerating an invariant across a large
surface. Escalate to Tier 3 if the plan review finds a THIRD emit
site or a shared-primitive change missed here.

---

## §13 — Sequencing

1. **D0 probe** (§4) — 20-min task. Must land before D3 opens.
2. **D1 + D2 + D4** (subtractive URA changes + Option C surface). Ship
   together — small blast radius.
3. **D3 enrichment** — depends on D0.1 adapter shape.
4. **D5 step-1** (disable doorbell + G6) — depends on §7 parity
   PASS on organic events.
5. **D5 step-2** (delete) — 48h after step-1.
6. **D6 schema drop** — one release AFTER D1/D2/D4 land.
7. **D7 dormant delete** — can ship any time; sequenced with D5-step-2
   for one HA restart.
8. **D8 zone_monitoring toggle** — ship with the URA release; yaml
   changes strictly later.
9. **D10 test-alert button** — ship with D3.
10. **D9 shadow-diff** — DEFERRED (§D9).

Peer-cycle ordering: this cycle sequences BEFORE the F1-sunset
audit's remaining work (D7 zeros the automation-layer F1 exposure).
Ships AFTER RESACC-1 (already merged, v5.65.0).

---

## §14 — Open design points (for plan review to close)

1. **Enrichment default.** Default OFF (recommended, marginal-benefit
   pushback — cost-gated opt-in) OR default ON for the two current
   doorbell cams only (preserves current UX). Answer depends on D0.3.
2. **G6 folding.** Fold entirely into universal-llmvision on that
   camera (recommended — one enrichment path) OR keep G6 as a
   second enrichment adapter dedup'd against NM. Recommend fold.
3. **route_reason for successful enrichment.** Add a new named
   constant `NM_ROUTE_REASON_ENRICHED` or leave routing invisible
   and record enrichment presence only via a `message` shape check?
   Recommend NEW named constant (parity with NM-IMAGE-1's named
   route reasons; helps dashboards).
4. **Test-alert button (D10) severity.** Fires at what severity?
   MEDIUM (matches guest/home_day defaults) — a CRITICAL test alert
   trains the operator to ignore CRITICAL. Recommend MEDIUM.
5. **§8 zone_monitoring bundling.** In-cycle (D8 as scoped: toggle
   only, yaml later) OR fully out-of-cycle (a separate 2-week-later
   micro-cycle). Recommend in-cycle for the toggle only.
6. **Deep-night vehicle window retention** — confirm the existing
   knob names/defaults survive the const.py cleanup untouched.

---

## §15 — Plan-review checklist (Tier 2 plan review, ONE pass)

Reviewer verifies with greps, not trust:
- §1 institutional context complete; every proposed field REUSED/NEW
  cell justified.
- §2 invariant is falsifiable (both failing observations concrete).
- §5 emission-site enumeration independently re-greped (person emit,
  vehicle emit, legacy leg, existence-window gate, NM `async_notify`
  callers with `hazard_type` in `NM_SECURITY_HAZARDS`); ANY missed
  site is a plan finding.
- §6 severity table total — every `HouseState` value in a cell (incl.
  ARRIVING, WAKING, GUEST) OR falls through to the fail-safe CRITICAL.
- §9 every new number on the knob ladder with a rung + kill-switch
  semantics.
- Acceptance criteria testable (each Test/Live line has a concrete
  oracle).
- §11 non-goals explicit; nothing sneaked in.
- §D9 deferred item accounted for in a follow-up.
- §14 open points do not hide a fork the builder must guess through.

Plan findings fixed IN THIS DOC before any build dispatch.
