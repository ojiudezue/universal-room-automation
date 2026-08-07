# URA Kanban — single source of truth

**Purpose:** one durable board for bursty multi-thread work, so nothing lives only in chat.
**Rule (capture-first):** every operator push AND every pre-planning idea I generate lands here
as a card *in the same turn*, before acting — Inbox first, unprocessed. Chat is lossy;
this file is not. Reflected live at the Artifact board (URL in MEMORY.md).

**Card schema** — the fields exist to fight conceptual entropy; fill Origin, Why, and Next
even when terse:
- **Status / Thread / Origin** (chat date + the originating push, the pointer I usually lose)
- **Why** (rationale) · **Constraints** (stated-in-passing musts) · **Parked-alts** (+ why)
- **Refinement** (append-only `challenge → sharpened form` — the dialectic that improved the surviving idea; stops backsliding to the naive version)
- **Knobs** (named configurables — Numbers-Get-Knobs ledger) · **Next** (single next action) · **Refs**

Columns: 📥 Inbox · 🧭 Pre-planning · 📝 Planned · 🔨 In progress · 🔍 Review · 🚀 Shipped(organic-open) · ⏸️ Waiting-on-operator · 🅿️ Parked

_Last reconciled: 2026-08-07 (SECC-1 promoted; refinement trails added to SNAP-1/RESACC-1/TRANSIT-1)._

---

## 🔨 In progress

_(none — resolver-legs shipped; next build not started pending decisions on SNAP-1)_

## 🔍 Review

_(none)_

## 📝 Planned (spec ratified, not built)

### CONSOL-1 — Perimeter consolidation cycle
- **Thread:** camera/perimeter · **Origin:** 2026-08-07 "retire redundant manager surface… I need to weigh in" → 4 rulings ratified.
- **Why:** three parallel alerting stacks (URA NM, HA-side doorbell automation, zone_monitoring pagers) duplicate delivery.
- **Rulings (locked):** Option C surfacing (= A enhanced); **universal llmvision** on ALL camera alerting; **contextual severity** replaces the 23:00–05:00 day/night window (vehicle deep-night window retained); Perimeter Alerting **stays a specific top-level config step** (named trigger: create a Security config home only when a 2nd security-config surface would join the menu).
- **Constraints:** doorbell automation carries **daytime front-door coverage** + llmvision + vehicle/animal classes — must be preserved (migrate-then-retire, not delete).
- **Refs:** PLANNING_perimeter_consolidation.md (4 rulings appended); AUDIT_ha_side_alerting_reconciliation.md (7-item retirement list).
- **Next:** fold SNAP-1 + TEST-1/2 into this cycle's planning doc; Tier 2-DB.

### SNAP-1 — Snapshot mirror-and-improve
- **Thread:** camera/perimeter · **Origin:** 2026-08-07 "still no images" → "Mirror and improve… shot from when it fired, not seconds later" → "does it cleanup… I approve the purge."
- **Why:** URA sends `media_url` (URL fetch) → images dropped; and any live grab is stale.
- **Design:** (a) **mirror** = snapshot to a local file, attach as file to every channel (`media_path` WhatsApp / local `attachment` BlueBubbles / `image` companion / file Pushover) — kills external_url/fetch dependency. (b) **at-detection frame**, tiered: Frigate **event snapshot** (`api/events/<id>/snapshot.jpg`, best-frame) > Protect event thumbnail > native **rising-edge capture** (grab at `_on_perimeter_event`, not at dispatch). (c) **retention/cleanup + privacy**: write OUTSIDE `/config/www` (web-served, no auth) e.g. `/config/ura_snapshots` in `allowlist_external_dirs`; prune-on-write + nightly sweep.
- **Knobs:** `PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE` (Frigate-event > Protect-thumb > live); `PERIMETER_SNAPSHOT_RETENTION_COUNT` (~200); `PERIMETER_SNAPSHOT_RETENTION_AGE_H` (~48).
- **Constraints:** ONE snapshot per collapsed camera-key per alert even with N corroborating engines; llmvision runs on the local file.
- **Parked-alts:** continuous pre-roll frame buffer (exact-timestamp even for native) — revisit if rising-edge frames still look late for fast walkers.
- **Refinement:**
  - my first read "external_url unset" → operator "find how I do it for WhatsApp" → found doorbell automation uses `media_path` (local file); root cause reframed to media_url-vs-media_path.
  - "just mirror the automation" → operator "shot from when it fired, not seconds later" → mirroring alone insufficient (camera.snapshot is *also* a live grab); escalated to at-detection event frame.
  - operator "does it cleanup? I bet we need to" → added retention + the privacy finding (out of web-served `/config/www`).
  - operator "one snapshot even with multiple integrations — which one?" → snapshot engine precedence (at-detection fidelity, not identity order).
- **Decisions pending (operator):** dir `/config/ura_snapshots`? retention 200/48h? fold TRANSIT-1 in or separate?
- **Refs:** perimeter_alert.py `_resolve_snapshot_url_and_delay`, notification_manager.py `_send_whatsapp` (media_url), frigate views.py NotificationsProxyView.

## 🧭 Pre-planning (idea, not yet a plan)

### RESACC-1 — Resolver accuracy test suite
- **Thread:** camera/resolver · **Origin:** 2026-08-07 "much more interested in accuracy of the task of the resolver… accuracy means alerting will be better."
- **Why:** the resolver feeds census (interior) + transit (traversal) + perimeter (exterior) — one accuracy suite validates all three.
- **Design:** hand-built ground-truth table (camera → {sensor×engine×family, room}); measure **precision + recall per camera**; adversarial near-miss pairs (armcrest vs armcrestpooloverhead, back_yard vs _2, shared stems → no bleed); registry-perturbation replay (disable/rename/F1→F2/new-cam); live self-audit surface (0-leg camera, legs spanning >1 area, >1 camera-key).
- **Refinement:**
  - my testing proposals were delivery-focused (shadow diff, test button) → operator "much more interested in accuracy of the *task* of the resolver… accuracy means alerting will be better" → reframed to resolver-accuracy-first (precision/recall vs ground truth).
  - realized the same resolver feeds census + transit + perimeter → one accuracy suite validates all three, not just alerting.
- **Next:** hand-build the ground-truth table from live registry (fixture-before-automation), commit it, then build the diff.

### TEST-1 — Boot-time shadow diff (legacy vs resolver leg set)
- **Thread:** camera/resolver · **Origin:** 2026-08-07 "we took hardened surface and gave it new methods. Something is bound to fail."
- **Why:** live tripwire for silent coverage shrinkage — catches what unit tests miss.
- **Next:** ~30 LoC in the consolidation build: WARN if a camera's new leg set doesn't superset the legacy base+`_2`.

### TEST-2 — "Send Test Perimeter Alert" button
- **Thread:** camera/perimeter · **Origin:** 2026-08-07 same.
- **Why:** delivery layer crosses into 3rd-party services; only a live end-to-end send proves it. Would have caught the media_url bug instantly.
- **Next:** button entity → sends a canned snapshot through all 4 channels.

### TRANSIT-1 — Interior traversal: upgrade transit_validator to resolve_detection_legs
- **Thread:** presence/traversal · **Origin:** 2026-08-07 "we built exterior tracking in the inspiration of interior census/known-persons room traversal. Find it. See if resolver can improve it."
- **Why:** transit_validator checkpoints fire from ~one integration's person sensor; multi-engine legs = denser/earlier checkpoints = more path_confirmed, fewer no_camera_data. Already half-wired (uses census.resolve_cross_platform_sensors).
- **Refs:** transit_validator.py (v3.5.2); known-person face path writes `Frigate_KnownPerson_*` snapshots.
- **Refinement:**
  - I asserted "path tracking is exterior-only" → operator "we built exterior tracking in the *inspiration* of interior census / known-persons room traversal. Find it." → located transit_validator; corrected my framing and found it already half-uses the resolver (census cross-platform), so the upgrade is small.
- **Next:** decide fold-into-SNAP-1-cycle vs own follow-on.

### FRIG2SNAP-1 — frigate2 instance-id snapshot URL
- **Thread:** camera · **Origin:** 2026-08-07 (found mid-investigation).
- **Why:** snapshot endpoint is instance-scoped (`/api/frigate/<instance>/notifications/…`); URA builds only default-instance shape → **frigate2-hosted cameras can't resolve a snapshot at all**. Latent since prefix-split.
- **Next:** fold into SNAP-1 (subsumed if we switch to event-snapshot download).

### KP-ESCALATE-1 — Known-person / face-alert path (no URA successor)
- **Thread:** camera/security · **Origin:** 2026-08-07 (discovered via purged `Frigate_KnownPerson_*` files) + AUDIT rec #5.
- **Why:** face-recognition paging has no URA successor; belongs in perimeter NM, not a revived Phase-1 automation.
- **Refs:** PLANNING_exterior_person_escalation.md (follow-up).

### KHOST-1 — Homelab-hosted board, generated from KANBAN.md
- **Thread:** dashboarding/infra · **Origin:** 2026-08-07 "make url live on webhost (homelab) as a new simple page project… design it better… give yourself eyes like playwright so you can iterate the design yourself."
- **Why:** the Artifact is hand-maintained HTML that can drift from KANBAN.md (the exact anti-pattern this skill warns against). A **generated** board (KANBAN.md → HTML, pure function of the source) can't drift; homelab-hosted = durable, bookmarkable, infra-native.
- **Design:** generator (pandoc or a small script) KANBAN.md → static board; serve on homelab (follow `~/Code/ura-dashboard-pwa` / gitea-pages pattern; candidate `kanban.phalanxmadrone.com`); auto-rebuild on KANBAN.md change; **Playwright for self-iterated visual design** (node v25 + playwright 1.62 present; needs `npx playwright install chromium`).
- **Constraints:** the generated page must be a pure function of KANBAN.md (no hand-editing the output — kills the drift anti-pattern); refinement trails + all columns render.
- **Decisions pending (operator):** hosting mechanism (reuse the PWA/Vercel path vs homelab static via caddy/nginx)? subdomain?
- **Next:** install playwright chromium; prototype the MD→board generator; screenshot-iterate the design; then wire homelab serve.

### SECC-1 — Interior cams in the exterior open-tracks diagnostic
- **Thread:** camera/security · **Origin:** 2026-08-07 "Saw the outside open tracks diagnostic in SecC has interior cameras in it. Mistake?" (dropped for hours; recovered via the kanban — the canonical capture-failure example).
- **Why:** the exterior open-tracks diagnostic should only reflect perimeter/egress cameras; interior cams appearing there is either a display leak or an observe-scope leak past the allowlist.
- **Next:** verify against `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` whether interior cams still surface post-allowlist; if display-only, scope the attr; if observe-scope, it's a linker allowlist gap.
- **Refs:** exterior_track_linker.py `set_allowed_cameras`; sensor.py `ExteriorOpenTracksDiagnosticSensor`.

## ⏸️ Waiting on operator

- **F1-SUNSET** — go/no-go (reminder Aug 8). Steps 1–6 remote (mine), step 7 = unplug NUC. Readiness = organic one-alert-per-multi-engine-traversal (now readable via coverage-by-engine). Ref: AUDIT_frigate1_sunset.md.
- **P1/P3 preset verdict** — I owe the post-Writer-B flap re-measurement, then re-eval. Origin: "Yes re evaluate and come back."
- **SNAP-1 decisions** — dir / retention default / transit fold-in (see SNAP-1).
- **Physical:** Envoy power-cycle (daily reserve wedge, self-heals but recurs); Ziri-3 sensor power-cycle (off-network since Aug 4); optional Protect sensitivity 50→60 on seam cams; DB VACUUM button press (~900MB reclaim awaits).

## 🅿️ Parked (deliberate, with revisit-trigger)

- **Pre-roll frame buffer** (SNAP-1) — revisit if rising-edge frames look late for fast walkers.
- **Anticipatory TOU tick** — revisit if boundary-lag data shows real cost.
- **Adjacency config-flow** (rung-1) — export/import semantics approved as *adjacency-as-data* (TOU-rates pattern); queued, not scheduled.
- **Security config home** — create only when a 2nd security-config surface would join the top menu (CONSOL-1 named trigger).

## 🚀 Shipped — organic validation open

- **v5.59.0 resolver-legs** (2026-08-07) — live PASS (zero multi-key WARN, zero `_2` storm, zero URA ERROR, telemetry attr present). **Open:** one-alert-per-multi-engine-traversal + `leg_firing_by_camera` populate on first real exterior event (= also F1-sunset readiness). Ref: README_v5.59.0.md.
- **v5.57.0 / v5.58.0 / v5.58.1** — arrester immunity + Temp Arrester Override + ramp persistence / Protect person legs / snapshot TTL hotfix. Immune persons SET (`person.oji_udezue`, confirmed live).

## 📥 Inbox (raw, unprocessed)

_(empty — SECC-1 promoted to Pre-planning 2026-08-07)_

## Broader backlog (own docs, not this session)

EV drain-precedence (queued) · Load-shedding foundations (vision doc first) · Fusion paper (gated) · Shipwatch v1.2.0 deploy.sh hook · Forecaster wire-up (LightGBM+BatteryStrategy) · Dashboarding workstream (ura-v6 rebuild + PWA) · Memory week-one gate + first coordinator-consumer proposal. See BACKLOG_*.md + memory bodies.
