# PLANNING — Exterior Person Escalation (perimeter_alert ↔ NotificationManager)

**Tier:** 2 (feature cycle) — elevated per standing "3 framing-disjoint reviews for regression-prone work" policy. Change threads perimeter detections into NM's severity / DND / bucket / dedup machinery; a mis-wire silently drops security alerts.
**Branch:** `feature/exterior-person-escalation`
**Scope target:** ≤ ~5 files touched.

---

## Institutional context verified

**Files read end-to-end:**
- `custom_components/universal_room_automation/perimeter_alert.py` (334 LoC) — current flat notify path, egress suppression window (120s), per-camera cooldown (`PERIMETER_ALERT_COOLDOWN_SECONDS`), alert-hour window, camera resolution via `CameraIntegrationManager.resolve_configured_cameras`.
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` lines 1–1318 (async_notify entry point, DND / bypass / bucket / dedup / boot-settle machinery). `async_notify(coordinator_id, severity: Severity, title, message, hazard_type=None, location=None, source_anomaly_id=None)`.

**Greps run (existence checks):**
- `CONF_PERIMETER_*` in `const.py:1062,1104-1107` — REUSED: existing knobs `CONF_PERIMETER_CAMERAS`, `CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_ALERT_HOURS_{START,END}`, `CONF_PERIMETER_ALERT_NOTIFY_SERVICE`, `CONF_PERIMETER_ALERT_NOTIFY_TARGET`.
- `house_state` accessor pattern — REUSED: canonical pattern at `domain_coordinators/energy.py:6814-6832` (`hass.data[DOMAIN]["coordinator_manager"].house_state` StrEnum); documented as mirror of `notification_manager.py:2614-2624`. Fan-recheck / fan_veto same source.
- `CameraIntegrationManager` — REUSED at `camera_census.py:184,355`; already in use by perimeter_alert. `platform` attr distinguishes `"frigate"` vs `"unifiprotect"` (`camera_census.py:129,665`).
- `is_life_safety_hazard` at `notification_manager.py:132` — the safety-floor helper. Exterior_person is NOT life-safety; will not use the floor bypass.
- `Severity` enum + `NM_CHANNELS_KNOWN` + `_recipient_bypasses_dnd` / `_route_for_recipient` / `_gate_channels_for_notify` — REUSED (routing matrix / mute / DND-bypass all inherited automatically once we call `async_notify`).
- Grep `perimeter` in `notification_manager.py` — NONE. No prior wiring; the two systems are disjoint today (the operator-observed defect).
- Grep `snapshot|attachment` in NM — NM `async_notify` currently has NO snapshot/attachment param. NEW param needed (small extension).

**External API verified (WebFetch):** Frigate HA integration exposes `/api/frigate/notifications/<event_id>/snapshot.jpg` and `.../thumbnail.jpg` (multi-instance form: `/api/frigate/<client-id>/notifications/<event_id>/...`). Snapshot is inherently at-detection-time. Ref: https://docs.frigate.video/integrations/home-assistant/.

**Prior planning consulted:**
- `docs/planning/PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md` (active Tier-3) — no perimeter overlap.
- `docs/planning/PLANNING_presence_pair_guest_latch_veto_gap.md` — GUEST semantics: GUEST is a house-state where non-owners are present; operator-decide row below reflects that (visitor + owner-away paranoia).
- No prior perimeter/security planning docs exist (grep `docs/planning/*perimeter*`, `*security*` → empty). Rung-2a auto-security-follow is a note-only future hook.

**Design docs:** No `docs/Coordinator/perimeter*.md` or `docs/Coordinator/security*.md`. Perimeter alerting lives at module scope, not as a full coordinator.

**Memory bodies pulled:** `feedback_no_fabrication.md`, `feedback_marginal_benefit_pushback.md`, `feedback_parsimonious_room_config.md`, `Numbers Get Knobs` placement ladder.

**Not-invented tally:** 1 NEW notification class name, 1 NEW options-flow knob (snapshot offset), 1 NEW severity-mapping dict (module const). Everything else REUSED.

---

## Falsifiable invariant (for Reviewer D framing)

> **INV-XP:** Under any legal config, when `PerimeterAlertManager` observes a person-detection ON transition on a configured perimeter sensor AND the alert-hours window is open AND no egress crossing occurred inside `EGRESS_SUPPRESSION_WINDOW_SECONDS` AND the per-camera cooldown has expired AND `house_state ∈ {AWAY, VACATION, SLEEP}` AND `NotificationManager.enabled` AND not `messaging_suppressed`, then `NotificationManager.async_notify` is invoked exactly once with `severity ≥ CRITICAL` and a snapshot URL threaded through — and no phone-channel path can fire more than once per camera per `PERIMETER_ALERT_COOLDOWN_SECONDS` regardless of what NM's internal dedup / bucket / boot-settle machinery decides on top.

Reviewer D falsifies by enumerating legal-config combinations (cooldown 60s + NM bucket empty; global DND on + no per-recipient bypass; NM dry-run; legacy `perimeter_alert_notify_service` set; boot-settle window open at first detection; house_state=GUEST; snapshot offset large enough to race the cooldown).

---

## Deliverables

### D1: New NM notification class `exterior_person`

- `const.py`: NEW `NM_HAZARD_EXTERIOR_PERSON: Final = "exterior_person"`; NEW `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE` module-const dict (rung-1 — safety-adjacent, review-gated to change) — see mapping table below.
- Passed as `hazard_type=` on the `async_notify` call so existing routing-matrix hazard overrides (`CONF_NM_PERSON_HAZARD_OVERRIDES`) apply.
- NOT added to `NM_LIFE_SAFETY_HAZARDS` (not smoke/CO/water/freeze/intrusion-armed): it must obey token buckets, dedup, boot-settle, and DND per operator choice.

### D2: House-state → severity mapping

Read `hass.data[DOMAIN]["coordinator_manager"].house_state` via the canonical accessor pattern (`energy.py:6814-6832`). Coerce to string; fail-safe rule below.

| house_state | severity | rationale |
|---|---|---|
| AWAY | CRITICAL | intruder-plausible; must reach phone floors |
| VACATION | CRITICAL | same, extended absence |
| SLEEP | CRITICAL | occupants can't observe |
| GUEST | **MEDIUM** | non-owners on premises; likely legitimate visitors coming/going but owner should still notice — operator-decide, plan default MEDIUM; knob to override if noisy |
| HOME_DAY | LOW | expected foot traffic; digest row only |
| HOME_EVENING | LOW | expected; digest |
| ARRIVING | LOW | inbound occupant — near-100% self-triggered |
| WAKING | LOW | occupants active; digest |
| **unknown / empty / any other** | CRITICAL | **fail-safe: unknown state is treated as away** (canonical never-drop rule) |

The GUEST default is captured as a module const `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` so a follow-up cycle can flip it to LOW without a mapping-table churn.

### D3: Route via NM, preserve cooldown + egress suppression

Refactor `_async_handle_perimeter_trigger`:
1. Existing gates (alert-hours, egress window, per-camera cooldown) run FIRST — unchanged. **Perimeter owns cadence; NM's dedup/bucket run on top as a second gate but do NOT replace it.** Rationale: cooldown is a per-camera physical-world rate limit that operators reason about intuitively; NM dedup is per-title hash within a severity window. Stacking is safe because they are semantically different — no "double-cooldown pathology" because the perimeter gate is the OUTER, tighter one for this class (5min) and NM dedup for CRITICAL (`NM_DEDUP_CRITICAL`) will typically be shorter; if a future const flip inverts that, the outer cooldown still bounds phone rate.
2. Look up house_state → severity via D2.
3. Resolve snapshot URL via D4.
4. Look up NM: `hass.data[DOMAIN].get("notification_manager")`. If present AND `.enabled`: call `nm.async_notify(coordinator_id="perimeter_alert", severity=<mapped>, title=..., message=..., hazard_type=NM_HAZARD_EXTERIOR_PERSON, location=<camera_entity_id>)` with snapshot threaded via D5 param.
5. If NM absent OR disabled: fall through to legacy `_async_send_notification` path using `CONF_PERIMETER_ALERT_NOTIFY_SERVICE` (deprecated fallback). Log at INFO on first fallback per manager lifetime.
6. **Legacy override rationale** (rung-1 decision): if `CONF_PERIMETER_ALERT_NOTIFY_SERVICE` is explicitly set AND NM is enabled, still route via NM (NM primary) AND ALSO emit a one-shot deprecation WARNING log per manager lifetime pointing the operator at the NM Persons config. No silent behavior change for existing installs — but the operator gets nudged. Kill switch: if the operator wants pure legacy, they disable NM (`CONF_NM_ENABLED=False`).
7. `_last_alert[entity_id] = now` still recorded regardless of NM outcome (preserves the outer cooldown even if NM drops the call).

### D4: Snapshot resolution with configurable offset

Determine platform via `CameraIntegrationManager.get_platform_for(camera_entity_id)` (returns `"frigate"` or `"unifiprotect"` — camera_census.py:665).

**Frigate path (preferred — detection-time frame is native):**
- Frigate raises an HA event when detections start; the `event_id` is the stable snapshot key. **Build task:** verify the exact event bus name and payload shape used by our installed Frigate HA integration (typical name: `frigate_events` with `after.id`) — write a 5-line probe under `docs/planning/AUDIT_frigate_event_shape.md` BEFORE building D4 (Measure-Before-You-Build). Cache the last event_id per person-binary-sensor camera; construct URL `/api/frigate/notifications/<event_id>/snapshot.jpg`. `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` is **ignored on this path** — snapshot is inherently at-detection-time.
- If no event_id has been seen for this camera yet (edge case: person_binary_sensor flipped but the event dispatch hasn't been captured), fall through to live path.

**Live fallback path (UniFi Protect, or Frigate with no cached event_id):**
- Fire `camera.snapshot` service to a temp file OR use the camera's `entity_picture` URL. `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` (default 5, rung-2 options flow) MAY be honored by delaying the snapshot capture by that many seconds after trigger — operator's stated purpose: "grab a slightly delayed snapshot ... say 5 seconds prior to the time of firing? Configurable." (Interpreted: the notification FIRES ~offset seconds after the trigger so the still frame is closer to the detection moment despite acquisition lag. Semantics documented on the knob.)
- If snapshot resolution fails, notify WITHOUT the attachment — never block the alert on snapshot failure.

### D5: Thread snapshot into NM

Extend `NotificationManager.async_notify` signature with `snapshot_url: str | None = None` (fully backward-compatible default). Threaded into channel-specific payload builders where the channel supports attachments:
- Pushover: `attachment_url` field (native support).
- Companion (HA mobile): `data.image` field.
- WhatsApp / iMessage (BlueBubbles): `data.media` / `attachments` — verify supported field names at build time in the respective channel builders already present in NM.
- TTS / lights: ignored.

Every touched channel builder is edited to a) pass through when present, b) no-op when None. **Build task:** grep-verify the exact per-channel builder methods in NM before edit (they live below line 1318 of notification_manager.py — not read in this planning pass; grep `_send_pushover|_send_companion|_send_whatsapp|_send_imessage`).

### D6 (note-only, no build): Rung-2a security auto-follow hook

Once armed-away / auto-security-follow ships, an `exterior_person` NM emission while `security_state = ARMED_AWAY` is the pre-alarm signal — the security coordinator will subscribe to a dispatch we can add here (`SIGNAL_NM_EXTERIOR_PERSON`). Not built in this cycle; a one-line comment placeholder in the emit site is acceptable.

---

## Knob table

| Name | Rung | Home | Default | Kill switch | Notes |
|---|---|---|---|---|---|
| `NM_HAZARD_EXTERIOR_PERSON` | 1 | `const.py` module const | `"exterior_person"` | n/a | hazard_type key; changing = code review |
| `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE` | 1 | `const.py` module const dict | see D2 table | fallback to CRITICAL | mapping edits require review (safety-adjacent) |
| `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY` | 1 | `const.py` module const | `MEDIUM` | — | extracted knob so GUEST default can flip without touching the whole table |
| `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` | 2 | options flow (integration entry) | `5` | set to `0` = no delay, live-frame path | ignored when Frigate event snapshot available; semantics documented in strings.json |
| (reused) `CONF_PERIMETER_ALERT_NOTIFY_SERVICE` | 2 | options flow | (existing) | leave blank | deprecated fallback; NM is primary when enabled |

No new Number/Select/Switch entities this cycle (marginal-benefit check: the snapshot offset is set-once, not observation-tuned).

---

## Files changed

1. `custom_components/universal_room_automation/perimeter_alert.py` — refactor `_async_handle_perimeter_trigger`, add house-state lookup, snapshot resolver, NM primary + legacy fallback branch. ~+100 LoC.
2. `custom_components/universal_room_automation/const.py` — 3 module consts + 1 CONF key + default. ~+15 LoC.
3. `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` — `async_notify` gains `snapshot_url` kw; 4 channel builders thread it through. ~+30 LoC.
4. `custom_components/universal_room_automation/options_flow.py` — add `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` number selector (0-60, default 5) to the perimeter-alert section. ~+10 LoC. (Verify existing perimeter section exists; if not, place with other perimeter knobs.)
5. `custom_components/universal_room_automation/translations/en.json` + `strings.json` — labels for new knob and semantics note.
6. Tests: `quality/tests/test_perimeter_alert_nm_routing.py` (NEW).

No DB schema changes. No new sensors/entities. No new signals (D6 hook deferred).

---

## Acceptance criteria

### D1/D2/D3 — routing
- **Verify:** unit test — trigger perimeter detection with house_state=AWAY, assert `NotificationManager.async_notify` called exactly once with `severity=CRITICAL`, `hazard_type="exterior_person"`, `location=<camera_entity_id>`.
- **Verify:** same trigger with house_state=HOME_DAY → `severity=LOW`.
- **Verify:** house_state=None → severity=CRITICAL (fail-safe).
- **Test:** `test_perimeter_alert_nm_routing.py::test_severity_maps_by_house_state` (parametrized, 8 rows).
- **Test:** `test_perimeter_alert_nm_routing.py::test_perimeter_cooldown_bounds_phone_rate` — 3 detections within cooldown window → 1 async_notify call.
- **Test:** `test_perimeter_alert_nm_routing.py::test_egress_suppression_preserved`.
- **Test:** `test_perimeter_alert_nm_routing.py::test_legacy_fallback_when_nm_disabled` — NM disabled, legacy notify service still fires.
- **Test:** `test_perimeter_alert_nm_routing.py::test_legacy_and_nm_both_set_prefers_nm_with_deprecation_warning`.

### D4/D5 — snapshot
- **Test:** `test_perimeter_alert_nm_routing.py::test_frigate_snapshot_url_when_event_cached` — event_id cached → URL `/api/frigate/notifications/<id>/snapshot.jpg` threaded through `snapshot_url` kw.
- **Test:** `test_perimeter_alert_nm_routing.py::test_snapshot_offset_honored_for_live_fallback`.
- **Test:** `test_perimeter_alert_nm_routing.py::test_snapshot_failure_does_not_block_alert`.

### Live acceptance (post-restart)
- **Live:** trigger a real perimeter camera person detection while `sensor.house_state = AWAY` (or force via developer tools) → phone (Pushover / Companion) receives notification with attached snapshot within ~10s; `sensor.nm_last_notification` shows `hazard_type=exterior_person, severity=CRITICAL`.
- **Live:** repeat within 5min → NO second phone alert (outer cooldown).
- **Live:** trigger while `house_state = HOME_DAY` → NO phone alert; row appears in `notification_log` with `channel=<digest recipient's channel>` and severity=LOW; visible in dashboard's daily digest at next flush.
- **Live:** verify `sensor.nm_diagnostics` `by_severity["CRITICAL"]` incremented and `by_channel["pushover"]` (or configured) incremented.
- **Live:** grep HA logs for `PerimeterAlertManager: alert processed` — should be 1:1 with NM emit for AWAY trigger.

Post-Live: write results back into `README_v<version>.md` per MANDATORY ledger rule.

---

## Review tiering — 3 framing-disjoint

- **Reviewer A — correctness + house-state coercion + severity table:** every branch of D2 mapping; unknown-state fail-safe; enum coercion parity with `energy.py:6814`; hazard_type override interaction (`CONF_NM_PERSON_HAZARD_OVERRIDES`).
- **Reviewer B — race conditions + cooldown/dedup stacking + legacy fallback + NM lifecycle:** what if NM `async_setup` hasn't run when first detection fires (boot-settle window)? What if the legacy service is called AND NM primary in a bad code path (double-emit)? Restart mid-cooldown restores.
- **Reviewer D (adversarial completeness):** falsifies INV-XP above. Concrete repros required. Enumerate every path where an AWAY-perimeter detection could be silently downgraded below CRITICAL or dropped: `messaging_suppressed`, `dry_run_active`, quiet-hours + no bypass + no digest recipient, bucket empty + not life-safety-hazard, per-camera cooldown collision with NM boot-settle, unknown-house-state coercion path. Also re-enumerate for the LEGACY-only install (NM disabled) that a phone still gets hit via the fallback.

Per Tier-2 policy: Reviewers A + B + D run in parallel with disjoint framings. If any CRITICAL/HIGH: fix, re-verify affected surface, re-run D's enumeration.

---

## Deferred / not built

- **D6 auto-security-follow signal wiring** — deferred to security coordinator cycle. Placeholder comment only in emit site.
- **Real drain of NM overflow for exterior_person** — inherits Cycle B honest-drop semantics; not this cycle.
- **Per-camera severity override** (e.g. driveway = MEDIUM even when AWAY) — not asked for; capture in backlog if operator observes noise.
- **Snapshot attachment for TTS/lights** — n/a by channel semantics.
