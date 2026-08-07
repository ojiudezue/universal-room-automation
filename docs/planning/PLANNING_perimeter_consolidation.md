# PLANNING — Perimeter Notification + Identification Consolidation

**Status:** DRAFT for operator ratification (2026-08-07). The **surfacing
question in §3 is explicitly for the operator to rule on** — three real
options are presented with a recommendation, not a fait accompli.

**Motivation.** `AUDIT_ha_side_alerting_reconciliation.md` (2026-08-06)
confirmed a three-stack duplication on the front-door/garage path plus a
14-automation dormant Writer-B carcass and a live per-event zone-monitoring
pager layer. Perimeter alerts today can dispatch through:
1. URA `PerimeterAlertManager` → NM (`exterior_person`, 23:00–05:00, 5-min
   cooldown per camera, snapshot);
2. URA `PerimeterAlertManager._async_send_legacy_notification` (legacy
   `notify.<service>` direct — `perimeter_alert.py:1754`, gated by
   `CONF_PERIMETER_ALERT_NOTIFY_SERVICE` / `_TARGET` in config-flow's
   Perimeter Alerting step, `config_flow.py:3057-3069`);
3. HA `automations.yaml` "Doorbell Detection WhatsApp Alert" (llmvision
   enrichment, 24/7, no cooldown — the only DAYTIME perimeter pager
   currently);
4. HA G6 Doorbell Analysis (blueprint AI notify on the F2 entry motion
   sensor).

Simultaneously the identification-side twin (`PLANNING_exterior_track_
linking.md` cycle-3 resolver-legs note) is consolidating exterior
per-camera identification. This cycle is the **notification-side twin** of
that work: one router, one message, one snapshot pipeline, one config
surface — while preserving the doorbell automation's formatting/enrichment
as PRIOR ART to keep, not reinvent.

---

## Institutional context verified

Greps run + prior art:

- `CONF_PERIMETER_ALERT_HOURS_START/END`, `_NOTIFY_SERVICE`, `_NOTIFY_TARGET`
  — REUSED (retire/repurpose scope): `const.py:1165-1168`.
- `DEFAULT_PERIMETER_ALERT_START=23`, `DEFAULT_PERIMETER_ALERT_END=5`,
  `PERIMETER_ALERT_COOLDOWN_SECONDS=300` — REUSED: `const.py:1171-1173`.
- `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` (+ MIN/MAX/DEFAULT) — REUSED:
  `const.py:1365`.
- Perimeter step (Alert Start/End Hour, Notification Service, Notification
  Target, Exterior snapshot offset) — READ: `config_flow.py:3012-3093`;
  registered in the Configure Settings menu at `config_flow.py:2591-2596`
  alongside `global_sensors`, `energy_sensors`, `person_tracking`,
  `default_notifications`, `camera_census`, `perimeter_alerting`.
- `default_notifications` step (integration-level `CONF_NOTIFY_SERVICE` /
  `CONF_NOTIFY_TARGET` / `CONF_NOTIFY_LEVEL`) — READ: `config_flow.py:7482-7537`
  (NOT NM's persons/channels config — that lives elsewhere in NM options).
- NM surfaces (persons + channel enables + per-severity gates) — REUSED:
  `CONF_NM_*` imports at `config_flow.py:45-84`
  (`CONF_NM_PERSONS`, `CONF_NM_PERSON_WHATSAPP_PHONE`,
  `CONF_NM_PERSON_IMESSAGE_HANDLE`, `CONF_NM_WHATSAPP_ENABLED`,
  `CONF_NM_IMESSAGE_ENABLED`, `CONF_NM_COMPANION_ENABLED`,
  `CONF_NM_PUSHOVER_ENABLED`, `CONF_NM_TTS_ENABLED`, `CONF_NM_LIGHTS_ENABLED`,
  per-channel severity gates). Exterior payload already routes through NM
  channel builders w/ snapshot passthrough (`perimeter_alert.py:864-892`,
  `notification_manager.py` `_send_whatsapp/_send_imessage/_send_pushover/
  _send_companion` snapshot threading — audit doc line 20-21).
- Severity-by-house-state map + track severity map — REUSED (repurposed as
  the daytime/nighttime SEVERITY schedule): `const.py:1203-1214` and
  `1330-1359`.
- Adjacency graph + track linker + `note_alert_dispatched` — REUSED
  (unchanged by this cycle): `const.py:1223-1297`, `perimeter_alert.py:920-937`.
- `PLANNING_exterior_track_linking.md` — READ (full body). The identification
  consolidation twin. Cycle-3 resolver-legs note is the sequencing peer.
- `AUDIT_ha_side_alerting_reconciliation.md` — READ (full body). Source of
  the retirement list and the daytime-coverage caveat.
- Live doorbell automation — READ (via audit's summary of live
  `/config/automations.yaml`): llmvision image description + WhatsApp send
  to `14258299520`, queued max 10, no cooldown, 24/7. Message shape is the
  PRIOR ART the NM enrichment decorator must equal-or-exceed.
- G6 Doorbell Analysis — READ (audit): balloob/ai-camera-analysis blueprint
  on `binary_sensor.madrone_g6_entry_motion_2`.

**Proposed new fields (NEW justification required for each — see §5):**
| Proposed | REUSED / NEW | Rationale |
|---|---|---|
| Severity schedule (in-window vs out-of-window) | REUSED shape of `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE` + existing hours knobs | Re-frames existence-window into a per-tier schedule — no new axis, just repurposed semantics |
| `CONF_PERIMETER_ENRICHMENT_ENABLED` | NEW | No equivalent found (grepped `enrich`, `llmvision` in const.py/config_flow.py — zero URA hits) |
| `CONF_PERIMETER_ENRICHMENT_PROVIDER` (`llmvision` \| `none`) | NEW | Provider-agnostic knob; llmvision is the only supported provider today |
| `CONF_PERIMETER_ENRICHMENT_CAMERAS` (subset — cost gate) | NEW | Doorbell automation only enriches 2 cameras today; do not silently 9x the LLM call rate |
| `perimeter_alert.NM_DAYTIME_SEVERITY` map (retire the hours knobs OR repurpose them; see §3) | REUSED map, NEW default cell | Replaces the hardcoded "outside window → no alert" behavior |

Design docs read: none dedicated for perimeter (perimeter_alert.py docstring
+ the two planning docs above are the canonical prior art).

Prior planning docs consulted (headers skimmed, bodies pulled where
relevant): `PLANNING_exterior_track_linking.md` (FULL), `PLANNING_exterior_
person_escalation.md` (headers — INV-XP invariant), `AUDIT_ha_side_alerting
_reconciliation.md` (FULL), `AUDIT_frigate1_sunset.md` (referenced from
audit — F1 exposure).

---

## Design overview

**One router, one message, one snapshot.** NM becomes the sole perimeter
notification path. The `PerimeterAlertManager` retains detection, cooldown
(INV-XP), track linking, and severity coercion — it just no longer has an
alternate legacy dispatch and no longer has an existence-window gate.

Three consequences:

### 1. NM as sole router — retire the legacy leg

`_async_send_legacy_notification` (`perimeter_alert.py:1754`) and the pair
of legacy config fields (`CONF_PERIMETER_ALERT_NOTIFY_SERVICE`, `_TARGET`)
are deleted after a one-version deprecation:
- v(N): schema still accepts the fields; setup logs a one-shot ERROR if
  they are populated ("legacy perimeter notify path is retired — configure
  NM channels instead; ignoring `notify.<x>`"). Path is code-dead.
- v(N+1): keys removed from schema; a migration in
  `async_setup_entry` strips them from `entry.options` on load.

Revert story: a single-file revert restores `_async_send_legacy_notification`
+ the two schema fields; no data migration required to go backward within
one version.

### 2. Daytime tier — the 23–5 window becomes a SEVERITY SCHEDULE

Today the window is existence-gated at
`_async_handle_perimeter_trigger` step 1 (`perimeter_alert.py:637-643`) —
outside the window, alerts do not dispatch at all. This is precisely why
the doorbell automation is BOTH a duplicate (inside window) AND load-bearing
daytime coverage (outside window).

**Redesign:** step 1 no longer gates dispatch — it selects a severity tier.
- Inside window (default 23–5): today's `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_
  BY_HOUSE_STATE` table applies unchanged. Away/sleep/home_night = CRITICAL.
- Outside window: a NEW `NM_HAZARD_EXTERIOR_PERSON_DAYTIME_SEVERITY_BY_
  HOUSE_STATE` table applies. Defaults:
  - `away`/`vacation` → HIGH (real signal — nobody home)
  - `home_day`/`home_evening` → MEDIUM (person expected — enrichment
    carries the value)
  - `sleep`/`home_night` → CRITICAL (still after-hours by house state,
    even if outside the clock window)
- The track-severity-map coercion (`const.py:1330-1359`) runs on top
  identically — it already keys on house_state and handles all cells.
  The 23–5 clock knob remains only to shift the "assume-day-alerts-are-
  quieter" threshold; a follow-up cycle can retire the clock knob entirely
  once the house_state severity table has been observed to carry the load.

**No daytime gap.** Every event that today would have been dropped by the
window check now dispatches at the daytime tier through NM, with
enrichment if enabled — exactly replacing the doorbell automation's role.

**Cadence guard.** `PERIMETER_ALERT_COOLDOWN_SECONDS` (5min) still binds,
per camera-key, on top of the daytime tier. This is a REDUCTION in paging
frequency vs the current doorbell automation (no cooldown at all) — the
audit called that lack a defect, not a feature. Called out for operator
review; if the doorbell path today fires more than once per 5 min in a
typical delivery event, we may need a daytime-cooldown variant.

### 3. LLM-vision enrichment as an optional NM decorator

Preserve the doorbell automation's message quality. Add a small enrichment
step in `PerimeterAlertManager._async_handle_perimeter_trigger` between
snapshot resolution (§5 of that method) and NM dispatch (§6):

- Gated by `CONF_PERIMETER_ENRICHMENT_ENABLED` (default OFF; operator
  opts in) + per-camera allowlist `CONF_PERIMETER_ENRICHMENT_CAMERAS`
  (default = the 2 cameras the doorbell automation currently covers).
- Provider abstraction (`CONF_PERIMETER_ENRICHMENT_PROVIDER`, initial
  value `"llmvision"`) so we can swap later; adapter file
  `perimeter_enrichment.py` with a single `async_describe(snapshot_url,
  camera_entity_id) -> str | None`.
- Time budget: single-shot call with a hard timeout (default 4s). Failure
  MUST fall through — the alert dispatches without the description, never
  blocks. Enrichment error rate is a diagnostic sensor attr, not an alert.
- Result concatenates into the NM `message` field ONLY (title unchanged,
  snapshot pipeline unchanged). This keeps the channel builders'
  attachment/media handling identical.

### 4. Snapshot pipeline single-sourced

Already true today — `_resolve_snapshot_url_and_delay` (perimeter_alert.py:999)
handles Frigate `event_id` + entity_picture fallback and NM's channel
builders (whatsapp `media_url`, imessage `attachment`, pushover
`attachment_url`, companion `data.image`) thread it. The retired doorbell
automation's `hass.services.call("notify.whatsapp", ...)` with its own
snapshot fetch goes away for free.

---

## Retirement list (from the audit — action per item)

Ordered by risk to live behavior; each item names its replacement and
revert story.

| # | Item | Replaced by | Migration | Revert |
|---|---|---|---|---|
| 1 | `_async_send_legacy_notification` + `CONF_PERIMETER_ALERT_NOTIFY_SERVICE/_TARGET` | NM `async_notify` (already primary) | v(N) deprecation ERROR + code-dead; v(N+1) schema drop + option strip | git revert; no data move |
| 2 | HA doorbell WhatsApp automation | NM daytime tier + enrichment decorator | Ship §2+§3 → live-validate 1 event per tier through NM → **disable** doorbell automation → observe 48h → **delete** | Re-enable the automation (kept in `automations.yaml` disabled for one release) |
| 3 | G6 Doorbell Analysis (blueprint) | Same enrichment decorator (fold in) OR keep as single-camera enrichment | Enrichment enabled for `madrone_g6_entry` → disable G6 automation | Re-enable |
| 4 | 4× `zone_monitoring` per-event pagers (Zone1/3 motion + person counters) | Nothing — URA census/substrate covers monitoring | Turn `input_boolean.zone{1,3}_monitoring_active` OFF; if quiet 2 wks, strip `notify.mobile_app_*` action from the yaml; final: delete the whole `packages/zone_monitoring.yaml` if counters are no-value | Toggle the input_boolean back ON |
| 5 | 14 dormant automations (Phase-1 dual-system pair; 12 dormant HVAC/presence/arrester/guest; UpZone 2.0 package) | Already replaced by URA (long dormant) | Delete from `automations.yaml` and drop `packages/{upzone_zone2_package,back_hallway_hvac}.yaml` | git revert on HA config |
| 6 | Zone inactivity + daily-summary pushes | URA diagnostics (out of scope for this cycle — mark for follow-up) | Not migrated in this cycle | n/a |

**Keep:** Frigate MQTT bridge (URA-owned since v5.44.0).

**F1 sunset exposure:** items 5 (Phase-1 pair) hold the sole live-config
reference to the 14 F1 `*_person_occupancy` sensors + 3 F1 face sensors
(`AUDIT_ha_side_alerting_reconciliation.md:91-94`). Retiring them
zeroes the automation-layer F1 exposure — this cycle should be sequenced
BEFORE the F1 sunset (see §4).

---

## §3 — THE USABILITY QUESTION (operator decides)

Where should the consolidated perimeter config live after the legacy
fields die and the enrichment/severity-schedule knobs land? Three real
options; recommendation follows.

Common to all three: the **legacy fields (`_NOTIFY_SERVICE` / `_TARGET`)
are REMOVED** — the question is only where the surviving fields live.

Surviving fields:
- Perimeter cameras + egress cameras (WHAT to watch — detection)
- Alert-hours window start/end (WHEN the CRITICAL tier applies)
- Exterior snapshot offset (HOW the snapshot is captured)
- Enrichment enabled + provider + camera allowlist (HOW the message is
  built) — NEW
- Severity schedule table — CODE-side (module const), not exposed as
  options (rung-1: "safety bounds require code review" per Numbers Get
  Knobs). Operator changes it via PR, not slider.

### Option A — Keep "Perimeter Alerting" step where it is (recommended)

Perimeter Alerting step in the Configure Settings menu retains the fields;
legacy service/target REMOVED; enrichment fields ADDED. NM persons/channels
inherit from Default Notifications / NM settings (no duplication).

- Discoverability: HIGH. Operator muscle memory; sits next to Camera
  Census — matches "if I care about perimeter, it's here" mental model.
- Cognitive model: This step becomes "perimeter DETECTION + WHEN it
  escalates + ENRICHMENT policy". Delivery (WHO/HOW) is elsewhere (NM).
  Clean split.
- Orphan risk: LOW — one place to look; NM persons/channels are shared
  infra.
- Migration: trivial — existing 23/5 + offset=5 keys carry through
  unchanged; legacy service/target keys stripped on load (§1).
- Dashboard/ura-v8 implications: matches current Security tab layout
  (perimeter panel is a first-class surface).

### Option B — Move everything under Default Notifications / NM

Perimeter Alerting step retired entirely; its fields fold into a
per-hazard section of NM settings (or an "Exterior" subsection).

- Discoverability: MEDIUM. Single notification home is philosophically
  clean, but perimeter detection + camera picking gets pulled away from
  Camera Census which stays where it is — creates a NEW split.
- Cognitive model: unifies delivery, but blurs detection vs delivery
  (the Perimeter step today is really 60% detection/40% delivery).
- Orphan risk: MEDIUM — cameras still configured in Camera Census, so
  the operator now has to touch TWO places to change perimeter behavior.
- Migration: requires renaming keys + a config-flow step deletion (with
  the associated back-compat option-strip). More churn than A.
- Dashboard: no benefit.

### Option C — Hybrid split: Perimeter Alerting keeps WHAT/WHEN, NM keeps WHO/HOW

Perimeter Alerting step keeps cameras + window + severity-schedule
description + snapshot offset + enrichment toggle/provider/camera-allowlist
(the whole "detection + escalation policy" surface). NM settings keeps
persons + channel enables + per-channel severity gates. Each dialog gets a
one-line cross-reference ("Delivery configured under NM → Persons",
"Perimeter escalation policy under Configure Settings → Perimeter Alerting").

- Discoverability: HIGH once the cross-reference lines are in place.
- Cognitive model: cleanest split of the three (detection vs delivery is
  a real distinction; forcing them together is what created the doorbell
  duplication in the first place).
- Orphan risk: LOW — cross-references guarantee neither dialog is a dead
  end.
- Migration: same as A (trivial).
- Dashboard: A and C are indistinguishable to the dashboard.

### Recommendation: **Option C** (with **Option A** as the pragmatic fallback)

Rationale: the audit's core lesson is that "delivery" (WhatsApp target,
llmvision call) was living inside the perimeter automation and creating
duplication. Making detection-vs-delivery an EXPLICIT split at the config
surface makes the same mistake harder to re-introduce (a future cycle can't
casually add a second WhatsApp target inside Perimeter Alerting because
"delivery is elsewhere" is signposted right in the dialog).

**A is a very close second** — it costs one cross-reference line and
matches muscle memory more strongly. If the operator's read is that "I'll
never conflate detection and delivery again" is obvious enough not to need
signposting, A is the lower-friction choice.

**B is not recommended** — it fragments perimeter config across two menus
(Camera Census stays where it is) for a philosophical unification that
buys nothing concrete.

Operator ruling requested on: A vs C. B available if we've missed a
reason to prefer it.

---

## §4 — Sequencing

Relative to peer cycles:

1. **Before F1 sunset.** Item #5 (retire the 14 dormant automations,
   including the two Phase-1 automations) zeroes the automation-layer F1
   exposure. Doing this cycle first means the sunset audit's remaining
   scope is only Frigate-substrate work.
2. **After `PLANNING_exterior_track_linking.md` cycle-3 resolver-legs.**
   Track linking's cross-camera identity is the substrate the daytime
   severity tier's `approach`/`circling` cells lean on. Ship cycle-3 →
   validate resolver → then this cycle (severity schedule + enrichment)
   inherits a stable identity layer. If the operator wants this cycle
   FIRST for daytime coverage urgency, we ship it with the current
   linker (cycle-1 is live and stable) and the resolver-legs improvement
   layers cleanly on top.
3. **Recommended order:** cycle-3 resolver-legs → this cycle → F1 sunset
   → zone_monitoring package retirement (item #4, optional last).

**Tier classification:** Tier 2-DB (three framing-disjoint reviews) per the
"regression-prone" standing policy. Justification:
- Cross-coordinator ripple: perimeter_alert ↔ NM ↔ house_state (severity
  table) ↔ ExteriorTrackLinker.
- Retires a shared primitive path (the legacy notify leg) with
  live-config consumers.
- Behavioral change to a long-standing gate (existence-window → severity
  schedule) that other observed behavior has come to depend on (operator's
  daily doorbell pings originate from the outside-window HA automation, not
  URA — reshaping this changes the operator-visible cadence).

**Reviewer framings (disjoint):**
- Reviewer A — correctness + edge cases (severity schedule cells for every
  house_state incl. missing/unknown; enrichment timeout + failure fall-
  through; daytime cooldown behavior; INV-XP preserved).
- Reviewer B — cross-coordinator + lifecycle + migration (option-strip
  migration for retired keys; NM channel/persons unchanged; boot-settle
  gate for daytime tier; teardown of new enrichment provider).
- Reviewer C — surfaces + duplication invariant (config-flow diff round-
  trips; the "exactly ONE notification per perimeter event" invariant proven
  by a triple-path fixture — URA + doorbell automation + G6 all pointed at
  the same event should still yield one notification via NM after the
  doorbell/G6 automations are disabled).

**Falsifiable invariant (Reviewer D if elevated to Tier 3):**
> Under any legal config (any window, any severity schedule, any
> enrichment on/off, any camera set) a single physical perimeter event
> produces at most ONE notification thread across all four stacks combined,
> proven by a fixture that emits the same event through the URA
> perimeter path, the retired-but-still-in-code doorbell path (as a
> negative test), and the G6 automation path.

---

## Deliverables + acceptance criteria

### D1 — Retire the legacy notify leg

Delete `_async_send_legacy_notification` call sites; keep the method one
version as code-dead; log one-shot ERROR when the legacy config keys are
non-empty.

- **Verify:** grep for `_async_send_legacy_notification(` in
  `perimeter_alert.py` returns ZERO invocation sites (definition may remain
  one release).
- **Test:** `test_perimeter_alert_legacy_leg_retired` — configure the
  legacy keys, assert ERROR log fires ONCE at setup and no legacy call is
  made on a perimeter event.
- **Live:** log grep on restart shows the ERROR only if the operator still
  has the keys set; NM dispatches every perimeter event.

### D2 — Severity schedule (in-window / out-of-window)

Add `NM_HAZARD_EXTERIOR_PERSON_DAYTIME_SEVERITY_BY_HOUSE_STATE` in
`const.py`; rewire `_async_handle_perimeter_trigger` step 1 to select tier
instead of gating existence.

- **Verify:** window check no longer returns; it selects a table.
- **Test:** `test_perimeter_daytime_dispatch_home_day_away` — event
  outside window with house_state=away dispatches at HIGH; home_day
  dispatches at MEDIUM; none are silenced.
- **Test:** `test_perimeter_inwindow_unchanged` — inside-window behavior
  is byte-identical to today (severity, cooldown, snapshot).
- **Live:** first outside-window person event after deploy dispatches an
  NM `exterior_person` notification at the daytime tier.

### D3 — Enrichment decorator (llmvision, optional, per-camera)

New `perimeter_enrichment.py` provider adapter. Gated by
`CONF_PERIMETER_ENRICHMENT_ENABLED` + `_PROVIDER` + `_CAMERAS`. 4s hard
timeout; failure falls through cleanly.

- **Verify:** message field contains the description string only when
  enrichment is enabled AND the camera is in the allowlist AND the call
  succeeds within timeout.
- **Test:** `test_enrichment_timeout_falls_through` — provider hangs 6s;
  NM notify is called at t=4s WITHOUT the description; no exception.
- **Test:** `test_enrichment_disabled_byte_identical` — enrichment OFF
  yields a byte-identical NM payload to today's.
- **Live:** first enriched event body carries a description string
  visually equivalent to the retired doorbell automation's format.

### D4 — Config-flow surfacing per operator decision (§3)

Implements Option A OR B OR C per operator ruling. Legacy fields removed
from schema in v(N+1).

- **Verify:** config-flow diff shows the chosen surface; round-trip via
  RestoreEntity preserves all values.
- **Test:** `test_config_flow_perimeter_surfacing_option_<X>` — the chosen
  option's fields save, load, and are consumed by
  `PerimeterAlertManager.async_setup`.
- **Live:** operator opens the chosen surface, changes one knob (e.g.
  enrichment toggle), reloads integration, observed behavior changes on
  the next event.

### D5 — Retire the HA-side automations (staged)

Doorbell WhatsApp automation and G6 Doorbell Analysis DISABLED (not
deleted) at ship. 48h observed → deleted in a follow-up commit.

- **Verify (staged):** live `automations.yaml` shows the two automations
  present but disabled after step 1; deleted after step 2.
- **Live:** the triple-path fixture invariant (one physical event → one
  notification thread) holds against the HA instance the entire staging
  window.

### D6 — Retire the 14 dormant automations + Phase-1 pair

Delete from `automations.yaml`; delete `packages/upzone_zone2_package.yaml`
and `packages/back_hallway_hvac.yaml`. F1 automation-layer exposure → 0.

- **Verify:** grep in the live `automations.yaml` for
  `*_person_occupancy` returns ZERO matches; the same grep across `packages/`
  returns ZERO.
- **Live:** HA restart is clean; no automation.* entity referenced by
  URA is missing.

### D7 — Zone_monitoring per-event pagers (optional last)

Turn `input_boolean.zone{1,3}_monitoring_active` OFF; if 2 weeks quiet,
strip `notify.mobile_app_*` from the four counter automations; ultimately
retire the whole `packages/zone_monitoring.yaml` if counters aren't
consumed anywhere.

- **Verify:** dashboard pushes per interior camera motion event stop
  arriving after the input_boolean flip.
- **Live:** operator confirms silence for the 2wk window before yaml
  changes.

### Cross-cutting acceptance (the invariant)

- **Test:** `test_perimeter_triple_path_dedup_fixture` — synthesize the
  same physical person event on all three stacks (URA sensor rising edge,
  emulated doorbell automation trigger, emulated G6 blueprint trigger).
  After D5-step-1, assert exactly ONE `notify.*` call issues; after
  D5-step-2, assert exactly ONE NM channel dispatch. Fails LOUDLY if a
  second thread appears.
- **Live:** at least one confirmed multi-stack physical event post-deploy
  (organic front-door delivery) produces exactly ONE thread on ops phone.
- **No-daytime-gap criterion:** the first HIGH-severity outside-window
  event after deploy dispatches an NM notification within the same
  latency budget the retired doorbell automation observed (~seconds).
  Regression is defined as a daytime event that would have paged before
  but is silent after.

---

## Open questions for operator (beyond §3)

1. **Surfacing choice:** A, B, or C? (Recommendation: C, fallback A.)
2. **Daytime cooldown:** the retired doorbell automation had NO cooldown;
   the URA path has a 5-min per-camera cooldown. Is 5 min acceptable for
   the daytime tier (recommended: yes, the audit called the no-cooldown
   path a defect), or should the daytime tier get a shorter cooldown
   (e.g. 60 s) to match "delivery event burst" behavior?
3. **Enrichment default:** default OFF (recommended — cost gate, opt-in)
   or default ON for the two current doorbell cameras only? OFF matches
   Marginal-Benefit Decomposition; ON matches "preserve current UX".
4. **G6 Doorbell Analysis:** fold entirely into the enrichment decorator
   (recommend) OR keep as a single-camera enrichment pager and dedupe
   against NM by camera? Recommend fold.
5. **Sequencing:** ship cycle-3 resolver-legs FIRST (recommended), or
   ship this cycle first for daytime-coverage urgency?
6. **Retirement of zone_monitoring package (D7):** in scope for this
   cycle, or split to its own follow-up?

---

## Not in scope

- Face-recognition escalation (see `PLANNING_exterior_person_escalation.md`
  follow-up rider — the Known-Person automation's disabled function has
  no URA successor yet and belongs in a separate cycle).
- Zone inactivity / daily-summary push retirement (audit item 4b — URA
  diagnostics coverage is not fully proven for these).
- Any change to NM persons/channels/severity gates themselves; this cycle
  only CONSUMES them.

---

## Operator rulings (2026-08-07)

1. **Surfacing: OPTION C** (ratified as "A plus the explicit
   detection/delivery boundary + cross-references" — same dialog
   location, same discoverability).
2. **llmvision enrichment is UNIVERSAL** across camera-based alerting
   (perimeter + egress, all severity tiers), not a daytime feature.
   Cost guard: enrich per DISPATCHED alert (post-cooldown/dedup), never
   per raw detection.
3. **Day/night is not a valid boundary for person alerting.** The 23-5
   existence window is REMOVED entirely; severity derives from the
   contextual model (house state × camera class × track classification)
   — "where and how it's used to advance the goal." The alert-hours
   fields migrate to severity-schedule semantics or are dropped.
   Exception retained: the deep-night VEHICLE window (operator's own
   negative-signal design, where the hour IS the signal) — standing
   unless separately reconsidered.
