# v5.53.0 — Exterior Track Linking (perimeter person de-dup + path-aware alerts)

Plan: docs/planning/PLANNING_exterior_track_linking.md. Adjacency:
AUDIT_exterior_camera_adjacency_probe.md (operator-ratified, 27 edges,
vision-verified via MAP_exterior_camera_paths.md). Detection-engine
context: AUDIT_exterior_camera_detection_settings.md.

## What ships

- **ExteriorTrackLinker**: space-time linking of perimeter person/car/
  animal detections into tracks (operator-declared adjacency, 180s link
  window, 300s idle close). No re-identification. Dual-source liveness:
  frigate_events bus + binary-sensor fallback with cross-source dedup.
- **Demote-never-silence alerting** (post-review redesign): every event
  that passes the per-camera cooldown gate DISPATCHES. Same-track
  continuations may be severity-demoted ONLY on confident multi-camera
  pass_by classification; circling/approach escalate; first alert of any
  track and all single-hop/unconfident cases keep today's severity
  exactly. Severity floor LOW-with-path-narrative — never silence.
  INV-XP (one CRITICAL per camera per cooldown while away) preserved.
- **Path narratives** in NM messages: "utilities → rear · 16 min · person".
- **Census sensors** (Security Coordinator device): Outside: People /
  Vehicles / Animals Being Tracked, Outside: Unidentified People, plus
  disabled-by-default Outside: Open Tracks (diagnostic) with per-track
  paths + per-camera unlinked-event counters.
- **Memory**: completed tracks → `exterior_track` episodes (source_ref
  deduped) via the write queue.
- **Controls (operator-named)**: `Exterior Path Tracking` (fire axe —
  OFF drains all open tracks instantly, census zeroes, per-camera
  alerting byte-identical to pre-cycle) and `Path Aware Notifications`
  (judgment layer only — OFF = classic severity, louder never silent).
  Both default ON, restore-"off"-only, suppressed_since preserved,
  cross-entry deferred restore via SIGNAL_EXTERIOR_LINKER_READY.

## Review ledger (Tier 2-DB + adversarial 4th + focused 5th)

- A correctness: 1 CRIT (default-config away-CRITICAL demotion) + 4 HIGH.
- B lifecycle: 3 HIGH (no periodic sweep; untracked episode tasks;
  phantom dedup claim).
- C test-authority (independent mutation battery): 2 HIGH silent-green
  sites.
- D adversarial completeness: 3 CRIT with concrete repros (loiterer
  silenced; distinct second person silenced; camera's first alert
  deleted) + compound NM-ack hazard + broken kill switch.
- ALL fixed in the consolidated fix-up (demote-never-silence redesign);
  each D-CRIT repro encoded as a fail-before/pass-after test.
- Focused review of the control surface: SHIP, MEDIUM-1 (instant drain)
  + LOW-1 (cross-entry restore race) fixed in-cycle.
- Orchestrator: suppress-path deletion verified by grep; ratified graph
  content-verified against the probe doc; first-alert guard + both
  switch gates mutation-red personally; cross-file asyncio pollution
  found and fixed; py39-exec-safe annotation regression caught by
  name-diff after a piped gate masked it (gate memory updated).

Tests: cycle 73; full suite 8184 passed, 19 pre-existing failures
(name-diffed vs develop baseline), zero new.

## Deferred (tracked)

ura-v8 dashboard cards; severity-map cycle-2 refinements for car/animal
NM wiring + deep-night vehicle policy; seam-split telemetry rider;
adjacency config-flow elevation (rung 2) if live edits wanted; LOW-2
(is_on True while unavailable) accepted.

## Live Validation (prospective)

- **Live:** linker active post-restart; both switches ON on the Security
  Coordinator device; census sensors 0 or plausible.
- **Live:** next organic multi-camera person → ONE open track visible in
  diagnostic attrs; NM message carries the path string; alert count ≤
  distinct cameras; NO camera's first alert missing.
- **Live:** away/sleep single-camera event severity UNCHANGED vs
  pre-cycle (CRITICAL family) — the A-CRIT-1 regression check.
- **Live:** flip Exterior Path Tracking OFF → census zeroes immediately,
  episode written; ON → resumes. suppressed_since attr present while OFF.
- **Live:** `exterior_track` episode row within 24h with path attrs.
- **Live:** zero new URA ERROR lines in first hour.
