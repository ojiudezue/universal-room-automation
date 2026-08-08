# PLANNING — SNAP-1: At-Detection Perimeter Snapshots (local-file delivery)

**Status:** Ready-to-build. All design decisions ratified by operator.
**Tier:** 2-DB (see §3). **Prereq of:** CONSOL-1 (llmvision enrichment).
**Ships:** standalone, before CONSOL-1.

---

## 0. Problem statement (verified live)

Perimeter alerts arrive text-only or with a stale image, for two verified
reasons:

1. **URL-not-file delivery.** `NotificationManager._send_whatsapp`
   (`domain_coordinators/notification_manager.py:1940-1971`) passes
   `media_url` to `whatsapp.send_message`; `_send_imessage`
   (`:1973-2004`) passes `attachment=<url>` to `bluebubbles.send_message`.
   The URL is `_absolutize(...)`'d against
   `hass.config.external_url` / `internal_url` inside
   `perimeter_alert.py::_absolutize` (`:1949-1976`). This requires the URL
   to be externally fetchable and auth-exempt at the moment the receiving
   integration fetches it — for URA's setup it is not, so images drop.
   The operator's own working `automations.yaml` doorbell alert uses
   **`media_path`** to a local file (verified against
   `/config/custom_components/whatsapp/__init__.py:90-160`, which accepts
   both `media_url` and `media_path`; `media_path` reads locally, gated
   by `hass.config.is_allowed_path`).
2. **Stale frame.**
   `perimeter_alert.py::_resolve_snapshot_url_and_delay` (`:1149-1210`)
   falls back to the camera's live `entity_picture` plus
   `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` (default 5s). Even the Frigate leg
   returns a URL that renders live (the `notifications` proxy returns the
   *stored* event snapshot for Frigate, which is fine — the operator's
   complaint is about the ubiquitous fallback path and the native
   `_2`/Reolink/Amcrest/Dahua legs). Operator: "a shot from when it
   happened/fired, not seconds later when code runs for alerting."

---

## 1. Institutional context verified

### 1.1 Prior-art grep (REUSED / NEW per proposed identifier)

| Proposed | Verdict | Evidence |
|---|---|---|
| `PERIMETER_SNAPSHOT_DIR` | **NEW** | Grepped `SNAPSHOT` in `const.py` — only `SCAN_INTERVAL_PERSON_SNAPSHOTS` (unrelated), `CONF_EXTERIOR_SNAPSHOT_OFFSET_S`, `FRIGATE_SNAPSHOT_LABELS`, `FRIGATE_SNAPSHOT_ID_TTL_S`. No dir constant exists. Default `"/media/ura/snapshots"`. |
| `PERIMETER_SNAPSHOT_RETENTION_AGE_H` | **NEW** | No retention constant in `const.py`. Default `168` (1 week). Rung: **module constant** — safety/disk-hygiene bound, tuning requires code review. |
| `PERIMETER_SNAPSHOT_RETENTION_COUNT` | **NEW** | Runaway backstop only (age is primary). Default e.g. `5000`. Rung: **module constant**. |
| `PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE` | **NEW** | Distinct from resolver's identity-preference order (`_sensor_platforms` in `perimeter_alert.py:153`+); this orders by IMAGE FIDELITY, not identity. Rung: **module constant** tuple — reordering has behavioral consequences worth review. Default: `("frigate_event", "protect_thumb", "live_grab")`. |
| `PERIMETER_SNAPSHOT_KILL_LEGACY_URL` | **NEW** | Kill switch reverting to the current `media_url`/`attachment=<url>` behavior. Rung: **module constant** boolean; flipping equals rolling back. |
| `_capture_at_detection_snapshot` (helper on `PerimeterAlertManager`) | **NEW** | No existing capture helper. Sibling of `_resolve_snapshot_url_and_delay` (`:1149`). |
| `_prune_snapshot_dir` (helper) | **NEW** | No prune helper exists. |
| Frigate event id cache | **REUSED** | `self._frigate_last_event_id` (`perimeter_alert.py:160`); TTL `FRIGATE_SNAPSHOT_ID_TTL_S=120` (`const.py:1436`). SNAP-1 downloads the JPEG from the URL shape already built at `:1194-1196`. |
| Camera-key collapse for "ONE snapshot per alert" | **REUSED** | `_camera_key_for_sensor` (`perimeter_alert.py:1174`+ via `_strip_person_family_suffixes` `:1220`). |
| `_absolutize` | **REUSED for HTTP fetches** (Frigate/Protect internal API calls need absolutization for `session.get`); **BYPASSED for delivery** (we hand the notify integrations a local path, not a URL). |
| `CONF_EXTERIOR_SNAPSHOT_OFFSET_S` | **REUSED as fallback-only** (`:1200-1201`) — still governs live-grab timing when at-detection capture is unavailable. |

### 1.2 Planning docs consulted

- `docs/planning/PLANNING_perimeter_consolidation.md` — full read. D3 (enrichment decorator) explicitly depends on a **local `image_file`** for llmvision (line 70, 165, 389, 509). SNAP-1 is that prerequisite. FRIG2SNAP-1 card (frigate2 instance snapshot resolution) is subsumed here — see §2 D1.
- `docs/readmes/README_v5.58.1.md` — full read. Hotfix cache TTL/case-key fixes are preserved; SNAP-1 layers on top.
- `docs/readmes/README_v5.58.0.md` — skimmed for prior perimeter-cycle scope.

### 1.3 Design docs

- `docs/Coordinator/PERIMETER_ALERT.md` — read if present; else use
  `perimeter_alert.py` module docstring (`:1-70`) as authority. (Coord
  doc directory checked; note here if absent.)

### 1.4 Code locations surveyed

- `custom_components/universal_room_automation/perimeter_alert.py`
  end-to-end for the D4 snapshot path (`:1146-1210`), the Frigate event
  bus subscriber (`:531-565`), `_on_perimeter_event` rising-edge dispatch
  (`:2062-2121`), `_absolutize` (`:1949-1976`), and
  `_get_snapshot_offset` (`:1978-1990`).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py`
  channel builders `_send_whatsapp` (`:1940`), `_send_imessage`
  (`:1973`), `_send_companion` snapshot threading (`:1931-1933`),
  Pushover `attachment_url` (`:1857-1885`).
- `custom_components/universal_room_automation/camera_census.py` — camera
  platform classification (`:47-48`, `:366-398`, `:549-558`). SNAP-1's
  per-engine capture branches key off the same platform tags
  (`CAMERA_PLATFORM_FRIGATE`, `CAMERA_PLATFORM_UNIFI`,
  `_CAMERA_PLATFORM_REOLINK`, `_CAMERA_PLATFORM_DAHUA`), plus
  `frigate2`/`protect2` fused-sibling variants.
- `/config/custom_components/whatsapp/__init__.py:90-160` (installed
  integration) — confirmed `media_path` accepted, gated by
  `hass.config.is_allowed_path`.
- `/config/automations.yaml` "Doorbell Detection WhatsApp Alert" —
  confirmed working reference using `media_path` to a local file.

### 1.5 Memory bodies pulled

- `project_v5_5_0_inclement_weather_shipped.md`, `feedback_no_fabrication.md`,
  `feedback_measure_before_build.md` (probe-first — SNAP-1 satisfied by
  the pre-cycle live verification of the two root causes; no additional
  probe required).

### 1.6 Explicitly NOT verified (flagged)

- **`/media` allowed-path status.** HA's default `media_dirs` is
  `{"local": "/media"}`, which SHOULD make `/media/ura/snapshots` an
  allowed path for `is_allowed_path`. **This has not been verified on
  the live instance** as part of this planning doc — D1 includes a
  runtime assertion at manager setup (fail-loud, kill-switch fallback)
  rather than assume.
- **UniFi Protect thumbnail API.** The exact service/API on the
  installed `unifiprotect` integration for retrieving the smart-detect
  event thumbnail is **NOT verified in this planning doc**. The Protect
  leg is specified in D2 as **"live grab fallback, pending
  verification"** — D2 explicitly requires the builder to read the
  installed Protect integration source and cite file:line before
  wiring; if unavailable the leg falls through to the native live-grab
  branch. Do NOT ship a fabricated Protect API.

---

## 2. Deliverables

### D1 — Snapshot directory + local-file delivery contract

Establish `/media/ura/snapshots` as the on-disk write target with:
- `mkdir(parents=True, exist_ok=True)` at `PerimeterAlertManager` setup.
- Runtime assertion `hass.config.is_allowed_path(PERIMETER_SNAPSHOT_DIR)`;
  on failure log ERROR ONCE and set an internal flag that forces the
  `PERIMETER_SNAPSHOT_KILL_LEGACY_URL` fallback for delivery (never
  crash setup).
- Assert dir is NOT under `hass.config.path("www")` (privacy invariant
  — see §4).
- New `NotificationManager` channel-builder parameter
  `snapshot_path: str | None` threaded alongside the existing
  `snapshot_url`. `_send_whatsapp` uses `media_path` when
  `snapshot_path` is set (drops `media_url`); `_send_imessage` uses
  local attachment path per BlueBubbles integration contract (builder
  reads installed BB source to confirm exact key — do not fabricate).
  Companion `data.image` and Pushover `attachment` accept file paths
  per their documented behavior — builder verifies.
- Legacy URL path preserved behind
  `PERIMETER_SNAPSHOT_KILL_LEGACY_URL=True`.

**Frigate2 subsumption (retires FRIG2SNAP-1):** the URL currently built
at `perimeter_alert.py:1194-1196` is the DEFAULT-instance shape only;
D1's Frigate leg (see D2) must derive the instance id from
`camera_census` platform tag (`frigate` vs `frigate2`) and build
`/api/frigate/<instance_id>/notifications/<event_id>/snapshot.jpg` for
non-default instances before downloading.

#### Acceptance Criteria
- **Verify:** `NotificationManager._send_whatsapp` payload includes
  `media_path` (not `media_url`) whenever `snapshot_path` is passed;
  bytewise-equal legacy payload when kill switch is `True`.
- **Verify:** setup logs ERROR + engages fallback if `/media/ura/snapshots`
  is not an allowed path.
- **Sensor:** existing `sensor.<...>_channel_health` for whatsapp/imessage
  stays green across ≥3 alerts post-deploy.
- **Test:** `test_snap1_media_path_delivery`, `test_snap1_allowed_path_fallback`,
  `test_snap1_kill_switch_legacy_url`.
- **Live:** real perimeter alert arrives with photo on BOTH WhatsApp
  AND iMessage; file lives under `/media/ura/snapshots`; nothing new
  written under `/config/www` (see D4).

### D2 — At-detection capture, tiered by engine

Add `_capture_at_detection_snapshot(sensor_entity_id, camera_key) -> str | None`
returning an absolute local path or `None` (graceful degradation, never
raises to caller). Precedence per `PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE`:

1. **Frigate / Frigate2 leg** — when
   `self._frigate_last_event_id[cam_key]` is fresh (existing TTL logic
   at `:1181-1189`), HTTP-download the stored event snapshot via the
   Frigate proxy URL (instance-aware, see D1) using `aiohttp` +
   `hass.helpers.aiohttp_client.async_get_clientsession`. Write bytes
   to `<dir>/<cam_key>_<eventid>.jpg`. This is Frigate's best-scoring
   frame OF the event — not a live grab.
2. **UniFi Protect leg** — **VERIFY BEFORE BUILDING.** Builder reads
   `/config/custom_components/unifiprotect/` for the smart-detect
   event-thumbnail API and cites file:line in the D2 build commit. If
   verified: fetch and write to `<dir>/<cam_key>_<eventts>.jpg`. If NOT
   verifiable: mark the Protect leg as fall-through to (3) and document
   the gap in the cycle README; do NOT invent a call.
3. **Native (Reolink / Amcrest / Dahua / anything without an event
   API)** — capture on the **RISING EDGE** in `_on_perimeter_event`
   (`:2062-2121`) BEFORE the dispatch task is scheduled, via
   `camera.snapshot` service to `<dir>/<cam_key>_<rising_ts>.jpg`, then
   pass the path into `_async_handle_perimeter_trigger`. This decouples
   capture time from dispatch/cooldown/llmvision delay — the operator's
   core requirement.

**ONE snapshot per collapsed camera-key per alert.** Fusion of N legs
via `_camera_key_for_sensor` produces a single file selected by
`PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE`; secondary engines that fire
within the cooldown window are dropped (do not overwrite the chosen
frame).

#### Acceptance Criteria
- **Verify:** for a Frigate person alert, capture happens with
  `delay_s == 0` and the file predates the notify dispatch.
- **Verify:** native-leg rising-edge capture timestamp is within
  ≤1s of the state-change event; NOT delayed by cooldown.
- **Verify:** frigate2-hosted camera (verified via `camera_census`
  platform tag) resolves a snapshot; builder cites the instance id
  used.
- **Verify:** two engines firing within cooldown produce EXACTLY ONE
  file for the camera key.
- **Test:** `test_snap1_frigate_event_download`,
  `test_snap1_frigate2_instance_url`, `test_snap1_native_rising_edge_capture`,
  `test_snap1_engine_precedence_dedup`,
  `test_snap1_protect_leg_gap_fallthrough` (documenting the pending-verify
  posture).
- **Live:** a frigate2 camera alert arrives with an attached photo (was
  IMPOSSIBLE before SNAP-1); a Reolink/native camera alert's attached
  photo timestamp matches the rising-edge time, not dispatch time.

### D3 — Retention: age-primary, count-backstop

Implement `_prune_snapshot_dir()`:
- On EVERY successful capture (write): prune files older than
  `PERIMETER_SNAPSHOT_RETENTION_AGE_H` (168h) in the dir; if file count
  still exceeds `PERIMETER_SNAPSHOT_RETENTION_COUNT`, drop oldest by mtime.
- Additionally: `async_track_time_interval` sweep every 6h (idempotent
  safety net for low-traffic days where no capture triggers prune).
- All I/O via `hass.async_add_executor_job` to keep the event loop
  clean; log at INFO on prune with count + freed bytes.

#### Acceptance Criteria
- **Verify:** files with mtime older than 168h are deleted within one
  capture cycle or one 6h sweep.
- **Verify:** count-cap prune only fires when file count exceeds
  backstop.
- **Test:** `test_snap1_retention_age_prune`,
  `test_snap1_retention_count_backstop`, `test_snap1_retention_periodic_sweep`.
- **Live:** 24h after deploy the directory contains only files with
  mtime within the 168h window; disk free stays healthy (spot-check
  `df` on `/media`).

### D4 — Privacy assertions + disk safety

- Setup-time assertion: `PERIMETER_SNAPSHOT_DIR` is NOT under
  `hass.config.path("www")`; if it is, log ERROR and force kill switch
  ON (never write). This is the load-bearing privacy invariant — the
  reason we're moving off `/config/www` (the 682MB `doorbell_alerts`
  pile purged 2026-08-07).
- Prune-on-write + periodic sweep (D3) covers the disk-runaway axis.
- Structured log line on every capture:
  `PerimeterSnapshot: wrote=<path> bytes=<n> engine=<tag>`
  — cheap ledger for post-deploy audit.

#### Acceptance Criteria
- **Verify:** no new files under `/config/www` post-deploy (find test
  in Live check).
- **Verify:** privacy-invariant test passes when dir is misconfigured
  to a `www` subpath.
- **Test:** `test_snap1_privacy_invariant_rejects_www_path`.
- **Live:** `find /config/www -newer <deploy_ts> -type f` returns zero
  URA-authored files 24h after deploy.

### D5 — Kill switch + observability

- `PERIMETER_SNAPSHOT_KILL_LEGACY_URL` (module constant) — when `True`
  the manager reverts to today's `media_url`/`attachment=<url>` path.
  Both the `is_allowed_path` failure and the `www` privacy failure
  auto-engage the kill switch.
- Add `sensor.perimeter_snapshot_last_capture` (path + engine + age)
  and increment an existing NM channel-health counter on
  capture-failure. Reuse existing `NotificationManager._update_channel_health`
  pattern rather than inventing a new sink.

#### Acceptance Criteria
- **Verify:** flipping kill switch and reloading returns bytewise-equal
  payload to pre-SNAP-1.
- **Sensor:** `sensor.perimeter_snapshot_last_capture` updates on every
  alert.
- **Test:** `test_snap1_kill_switch_bytewise_equivalence`.
- **Live:** sensor reflects the most recent alert's engine tag.

---

## 3. Tier classification — Tier 2-DB

**Why 2-DB:** SNAP-1 modifies the hardened NM delivery path (WhatsApp +
iMessage payload shape) AND the perimeter alerting rising-edge dispatch
path. Failure modes are cross-coordinator (perimeter → NM → external
integrations) and regression-prone (channel-health, payload shape,
timing).

**Three framing-disjoint reviews:**

- **Review A — Delivery-path correctness + payload shape.** Bytewise
  compare `_send_whatsapp` / `_send_imessage` payloads pre vs post for
  BOTH the file-present and file-absent branches; verify kill switch
  round-trip; verify graceful degradation on capture failure.
- **Review B — Perimeter engine legs + rising-edge timing +
  cross-instance URL correctness.** Trace each leg (Frigate default,
  Frigate2, Protect, native) to a written file; verify per-engine
  precedence dedup; verify native-leg capture is truly on the rising
  edge (not deferred by the async dispatch task); verify frigate2 URL
  shape against `camera_census` instance tagging.
- **Review C — Disk/privacy invariants + retention + test authority.**
  Confirm no writes under `/config/www` under any config path; confirm
  age-prune is age-primary and count is backstop-only; confirm tests
  drive real production capture code (not their own file I/O);
  confirm the `is_allowed_path` failure path fully engages kill switch.

Framings are disjoint per Tier 2-DB rules; the "DB" name is historical
(no schema change here) but the regression-prone criteria fire.

**Live Validation (Review D):** post-restart, a real person walks past
each engine class (Frigate, frigate2, native) within an hour; the
resulting messages carry photos; `/media/ura/snapshots` contains the
files; `/config/www` grows by zero URA files.

---

## 4. Disk-safety + privacy summary

- **Web-served path assertion:** `/config/www` is `/local/*` on HA's
  anonymous HTTP interface. `/media` is auth-gated (media browser +
  media source). Setup rejects any config placing the snapshot dir
  under `www`.
- **Prune-on-write** (every capture) + **periodic 6h sweep** (idempotent
  safety net).
- **Age-primary, count-backstop.** 168h age = operator ratified; count
  cap exists only to prevent pathological runaway (thousands of files
  in an hour would still be pruned by count between age sweeps).
- **Executor-jobbed I/O** — event loop stays clean.

---

## 5. Plan-completion / deferral accounting

Nothing in this plan is deferred at planning time. Items explicitly out
of scope (tracked elsewhere):
- **CONSOL-1** (llmvision enrichment) — separate cycle; consumes
  SNAP-1's local-file output.
- **Companion `data.image` and Pushover `attachment` local-file
  behavior** — builder must verify exact contract for each and record
  in the cycle README; if either integration cannot accept a local
  path, document and fall back to the URL form ONLY for that channel
  (WhatsApp + iMessage local-file delivery is the ratified must-ship).
- **UniFi Protect thumbnail API leg** — builds only if verifiable
  against installed integration source; otherwise D2 leg (2) falls
  through to (3) live grab and the gap is tracked as
  `SNAP-1-followup-protect-thumb`.

---

## 6. Falsifiable top-level invariant

> Under `PERIMETER_SNAPSHOT_KILL_LEGACY_URL=False`, every perimeter
> alert that a channel could carry an image on carries a **local file**
> whose capture timestamp is at or before the rising-edge event
> timestamp, and NO URA process writes to `/config/www`.

Review D falsifies this by walking past each engine class and diffing
`find /config/www` + inspecting message attachments + comparing capture
mtime to the recorder's binary_sensor state-change timestamp.
