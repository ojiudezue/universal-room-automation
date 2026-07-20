# PLANNING — NotificationManager Overhaul (2026-07)

**Date opened:** 2026-07-20
**Revised:** 2026-07-20 (post-critique REVISE verdict — revisions 1-10 applied; see revision log at bottom)
**Author:** ura-planner
**Foundation audits:**
- 2026-07-20 "would-have-sent" 7-day volume audit (488 pages / 70/day avg / 191 peak) — also measured the CO2/TVOC distributions cited in A4/A5 provenance.
- 2026-05-30 NM gap audit (NM-1..NM-6 backlog)
- 2026-07-20 hass-ans reference-study (token-bucket, criticality→channel matrix, restart-safe ack registry)

**Operator sequencing directive (verbatim, 2026-07-20):** *"Quieting and SNR are higher priority than safe word... it's a sub part of the NM workflow. We have to sort out true critical to get there."* → Sequence A→B→C stands; no hoist of B2 (safe-word ack registry) ahead of Cycle A. Getting the CRITICAL signal set correct (Cycle A) is prerequisite to giving CRITICAL machinery (Cycle B) something worth being brutal about.

**Mode:** HANDS-OFF multi-cycle pipeline. Operator authorization is *not* required between cycles; the pipeline continues to the next cycle after live validation of the previous cycle unless a genuinely destructive action is proposed.

**Pipeline preconditions (safety):**
1. Per-person channel targets (`CONF_NM_PERSON_PUSHOVER_KEY`, `CONF_NM_PERSON_IMESSAGE_HANDLE`, `CONF_NM_PERSON_WHATSAPP_PHONE`) **remain blank across all of Cycles A and B** and are only populated after Cycle C's dry-run/audit UX ships and validates. Belt to the suspenders of the B0 minimal dry-run gate.
2. The minimal dry-run gate (`CONF_NM_DRY_RUN`) ships in **Cycle B** (B0), not Cycle C, because Cycle B's live validation fires synthetic CRITICALs through the real send path — safe only with an in-code short-circuit at every `hass.services.async_call` site in the emit path. Cycle C builds the full routing/audit UX on top.

**Minimal-deferral rule:** Any deliverable deferred requires a written justification and forward-tracking home in the cycle's plan-completion accounting. Silent drops prohibited.

**Live-exercise posture:** NM in de-facto observe mode (`CONF_NM_ENABLED=true` + blank per-person targets). Combined with the B0 dry-run gate, two independent safety layers during the pipeline.

---

## Institutional context verified

### Files read end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` (2613 LoC; lines 1-1417 read in-session, remainder via grep)
- `docs/Coordinator/NOTIFICATION_MANAGER.md` (1.0 design doc, 2026-01-24 — pre-implementation)
- 2026-07-20 would-have-sent audit + 2026-05-30 NM audit memo + 2026-07-20 hass-ans reference study

### Grep survey for reuse
| Proposed knob / component | Result | Evidence |
|---|---|---|
| Per-severity dedup windows | **REUSED** | `NM_DEDUP_{CRITICAL,HIGH,MEDIUM,LOW}` at `const.py:1314-1317`; `DEDUP_WINDOWS` at `notification_manager.py:136-141` |
| CRITICAL repeat cadence | **REUSED** (split in B1) | `NM_CRITICAL_REPEAT_INTERVAL=30` at `const.py:1320`; consumer at `notification_manager.py:1301` |
| Safe-word ack | **REUSED** | `CONF_NM_SAFE_WORD` + `safe_word_configured` (line 489); `async_acknowledge` (line 1354) cancels repeat + starts cooldown |
| Per-person delivery preference | **REUSED** | `CONF_NM_PERSON_DELIVERY_PREF` (line 748+) |
| Digest infrastructure | **REUSED** | `_setup_digest_timers` + `_digest_unsubs` (line 219, 520) |
| Quiet hours | **REUSED** | `_is_quiet_hours` at line 687; CRITICAL bypass implemented |
| Silence-until | **REUSED** | `_silence_until` (line 268); line 693-699 |
| Kill switch | **REUSED** | `async_suppress_messaging` (line 299) |
| Sensor room-type filter | **REUSED** | `_sensor_room_types` at `safety.py:1605` |
| Fan-spike EMA / swing-trigger pattern | **REUSED** | `const.py:631` |
| Optimizer daily digest | **REUSED** | `optimization_daily_digest` |
| Anomaly-type discriminator | **REUSED** | v4.7.12 `AnomalyType` + `AnomalyEvent` (line 930-966) |
| Token-bucket rate limiter | **NEW** | Design-doc §7's `NotificationRateLimiter` not in live code. Cycle B builds fresh. |
| Recipient-owned criticality→channel matrix | **NEW — Cycle C** | Current model is global severity-per-channel |
| Restart-safe ack registry | **PARTIAL / EXTEND** | `get_persistence_state` / `restore_persistence_state` (line 444+); Cycle B extends |
| Dry-run gate (minimal) | **NEW — Cycle B (B0)** | Hoisted from Cycle C |
| Dry-run full audit UX | **NEW — Cycle C** | Builds on B0 |
| Per-recipient DND-bypass lists | **NEW — Cycle C** | |
| Boot-burst guard | **NEW — Cycle B (B4)** | 2026-05-30 audit risk |
| Hazard-type as 3rd matrix axis | **NEW — Cycle C** (decision item 3) | NM-6 |
| "Mute one person's one channel fast" shortcut | **NEW — Cycle C (C4)** | NM-1 UX |

### Dedup-key intent (per 2026-05-30 audit body)
The dedup key `{event_type}:{location}` (not per-person) is **deliberately preserved** — the 2026-05-30 audit body treats per-person dedup as a NON-goal (a single household hazard should coalesce across recipients, not fan out). Per-recipient rate control belongs in Cycle B's token bucket, not the dedup layer.

### Prior planning docs consulted
- `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md` — skimmed; not NM-relevant.
- No prior NM planning docs — first substantive NM planning cycle.

### Memory bodies pulled
- Memory entry "NM BlueBubbles + WhatsApp Audit 2026-05-30": NM-1..NM-6 all addressed (NM-1 → C4 UX, NM-2 → B1/B2, NM-3 → B3, NM-4 → B0 + C2, NM-5 → C3, NM-6 → C1 per decision item 3).

### Design doc read
- `docs/Coordinator/NOTIFICATION_MANAGER.md` v1.0 — predates implementation.

### Discrepancies (audit / design doc / live code)
1. Design doc §7 `NotificationRateLimiter` not in live code — Cycle B builds fresh.
2. Audit-cited severity site (`energy.py:4890`) trusted; builder re-greps at edit (A1 acceptance).
3. `NM_CRITICAL_REPEAT_INTERVAL=30` is brutal for non-life-safety, BUT `async_acknowledge` already cancels repeats on ack — real fix is subtype cadence (B1) + upstream demotion (Cycle A).
4. Design doc says iMessage = MCP; live uses `bluebubbles.send_message` (line 1094). Cycle C updates doc.

---

## Cross-coordinator ripple (revision 9)

Cycle A touches two coordinators outside NM. Pointer lines added at builder time:
- **A2 (optimizer HIGH/CRIT → optimization_daily_digest):** cross-post to any current optimizer planning/backlog doc and to the OC memory entry.
- **A6 (energy_battery D2-lag fix):** cross-post to `docs/planning/PLANNING_enphase_cloud_reliance.md` (currently active per gitStatus).

Pointer format: *"NM overhaul Cycle A ripple: A2 re-routes optimizer HIGH/CRIT findings from NM to `optimization_daily_digest`; A6 fixes D2-lag metric source (entity age → `last_reported`). See docs/planning/PLANNING_nm_overhaul_2026_07.md."*

---

## Falsifiable-invariant table

| Cycle | Invariant |
|---|---|
| A | Post-deploy 7-day would-page count for the seven audit-covered noise classes **≤ 15% of pre-deploy baseline for that class**, AND **no single (coordinator, hazard_type) class exceeds 2× its pre-deploy weekly rate** (revision 5), AND every audit-preserved signal (water leak, Envoy write-verify CRIT, AC Reset FAILED, Envoy Offline) still routes to NM at prior severity. |
| B | (i) A CRITICAL acked via safe word never fires again in the same episode across any channel/recipient across a mid-episode HA restart. (ii) Life-safety CRITICAL (smoke, CO, fire, water_leak, flooding, intrusion, freeze_risk) always repeats at ≤ 30 s regardless of any operator setting short of the kill switch. (iii) Non-life-safety CRITICAL repeats at ≥ 300 s. (iv) In any 60 s window, no channel sends more than `NM_RATE_BUCKET_CAPACITY` messages including repeats; overflow queued/coalesced, never silently dropped. (v) Within 5 s of NM startup, ≤ 1 alert per (coordinator, hazard_type) fires from `restore_persistence_state` replay. **(vi) With `CONF_NM_DRY_RUN=true`, zero outbound `hass.services.async_call` invocations to any notification service (Pushover / Companion / WhatsApp / iMessage / TTS / Lights) in any reachable emit path.** |
| C | (i) Every emitted notification's routing decision is deterministically explainable from `(sender, hazard_type, severity, recipient) → channel-set` via the per-recipient matrix (hazard_type is optional 3rd axis — decision item 3), with quiet-hours + DND-bypass applied last. (ii) Structured audit log records every routing decision under dry-run; `notification_log` write-rate ±25% vs pre-deploy baseline (revision 6). (iii) DND-bypass honored: alert whose recipient has the alert's severity in `dnd_bypass_severities` fires during quiet hours regardless of threshold. |

---

## Numbers-Get-Knobs ladder placement

| Number | Cycle | Rung | Home | Why |
|---|---|---|---|---|
| `TRIPPED_BREAKER_THRESHOLD_SECONDS` (300→900) | A | Module constant | `energy_circuits.py:19` | Fitted to compressor duty cycle |
| `NORMALLY_LOADED_THRESHOLD_W` (5.0) | A | Module constant | `energy_circuits.py:21` | Hardware calibration |
| Breaker severity demote (HIGH→INFO/anomaly-only) | A | Module constant | `energy_circuits.py:316-331` neighborhood | Class-level policy |
| `LOCK_UNAVAILABLE_DEDUP_S=86400` | A | Module constant | new in `safety.py` | Dead-device suppression |
| Humidity ladder ceilings (78/85/92) | A | Module constants | `const.py:631` neighborhood | Fitted to house norms |
| Humidity swing-trigger EMA params | A | Module constants | `const.py` (fan-spike area) | Model coefficients |
| Outdoor sensor exclusion (patio) | A | `_sensor_room_types` extension | `safety.py:1605` | Structural classification |
| `CO2_LOG_ONLY_CEILING_PPM=1200` | A | Module constant | `const.py` | Fitted to Study A p90 (see A4 provenance) |
| `TVOC_SUSTAINED_S=1800`, `TVOC_ABSOLUTE_HIGH=1500` | A | Module constants | `const.py` | Fitted to Master Bath p99=994 / max=1244 (A5 provenance) |
| D2-lag metric source | A | Code fix | `energy_battery.py:1262-1345` | Bug fix |
| `CONF_NM_DRY_RUN` | **B (B0 minimal gate) + C (full UX)** | Switch entity + options-flow default | `switch.py` + options flow | Kill-switch: `true` = zero outbound |
| `NM_REPEAT_INTERVAL_LIFE_SAFETY=30`, `NM_REPEAT_INTERVAL_NON_LIFE_SAFETY=300` | B | Module constants | `const.py` | Safety-tier |
| Token-bucket capacity per channel | B | Module constant default + Number entity | `const.py` + Number | Live-tunable (paging fatigue) |
| Token-bucket refill rate | B | Module constant default + Number entity | as above | Live-tunable |
| `NM_OVERFLOW_QUEUE_MAX` | B | Module constant | `const.py` | Safety valve |
| `NM_BOOT_SETTLE_S=60` | B | Module constant | `const.py` | Class-level |
| Per-recipient criticality × channel (× optional hazard_type) matrix | C | Options flow | `config_flow.py` + `options_flow.py` | Per-deployment structure |
| DND-bypass recipient lists | C | Options flow | as above | Per-deployment |
| "Mute person's channel fast" shortcut (NM-1) | C | Button / Service per (person, channel) | `button.py` + service | Frequent operator action |

---

## Tier classification

| Cycle | Tier | Justification |
|---|---|---|
| A | **Tier 2** | Multiple files, coordinator settings + routing, no shared-primitive rewrite. Two disjoint reviews (A=correctness + preserved-signals; B=cross-coordinator + no regression in HVAC/safety/energy). |
| B | **Tier 2-DB (elevated)** | Paging path, safety-CRITICAL contract, new shared token-bucket primitive, extends ack registry (schema-adjacent), hosts the minimal dry-run gate whose completeness is Bug-Class-#53 territory. Three disjoint reviews: A=life-safety CRITICAL correctness per subtype; B=async lifecycle + restart resilience + ack-registry persistence + kill-switch interactions; C=token-bucket math + overflow queue + rate-cap invariant proof per site + **minimal-gate completeness proof (every `async_call` in emit path guarded)**. |
| C | **Tier 3 (adopted per revision 10)** | The full dry-run zero-outbound invariant is a Bug-Class-#53 total-invariant across a broader routing surface (matrix, DND-bypass, hazard-type axis, structured audit log). Four disjoint reviews: A=routing-matrix correctness for every (sender, hazard, severity, recipient) tuple; B=async/RestoreEntity round-trip + backward compat + write-volume regression; C=test authority via real per-site source mutation of every `hass.services.async_call` inside NM (missed site = ship-block); **D=adversarial completeness** — state the invariant "under `CONF_NM_DRY_RUN=true`, no reachable NM code path emits an outbound service call to any notification service" in falsifiable form and BREAK it; D re-enumerates the entire NM emit surface *including pre-existing sites the diff didn't touch* (D-HIGH-1 v5.5.3 precedent). Config-boundary combinatorial testing across (severity × hazard_type × recipient × DND-bypass × dry-run). Orchestrator does independent re-grep + real-source-mutation on the load-bearing site before ship. **Tier-3 operator checkpoint before deploy** (mandatory). |

Tier-3 adoption rationale (revision 10): marginal cost of a fourth adversarial-completeness pass is small; marginal risk of a dry-run leak is silent breach of the "targets blank / dry-run gates everything" safety posture the entire pipeline depends on. Bug-Class-#53 precedent (v5.5.3 D-HIGH-1) is exactly the failure shape Tier 3 exists to catch.

---

## Cycle A — "Quiet the noise"

**Goal:** Cut 7-day would-page volume ~85% (488 → 3-6/day) by fixing seven noisy classes without losing any preserved signal.

### A1. Tripped-breaker: window + severity
- `TRIPPED_BREAKER_THRESHOLD_SECONDS` 300 → 900 (`energy_circuits.py:19`).
- Route tripped-breaker at INFO/anomaly-only (not NM). Builder re-greps audit-cited severity site (`energy.py:4890`) before edit.
- **Acceptance:** would-page tripped-breaker 7-day ≤ 5 (baseline 344).

### A2. Optimizer findings → digest
- Optimizer HIGH/CRIT → `optimization_daily_digest`; narrow allowlist for genuinely user-actionable HIGH (allowlist owned by optimizer).
- **Cross-post pointer added (revision 9).**
- **Acceptance:** `notification_log` shows 0 optimizer-source rows outside digest window.

### A3. Lock-unavailable dedup 1/day
- `LOCK_UNAVAILABLE_DEDUP_S=86400`; dedup key `(security, lock_unavailable, entity_id)`.
- **Acceptance:** ≤ 1/lock/day (baseline 81/wk).

### A4. Humidity ladder + outdoor exclusion + swing trigger
- Extend `_sensor_room_types` (`safety.py:1605`) with `outdoor`; safety-ladder excludes `outdoor`.
- Normal ladder 70/80/90 → 78/85/92; 78 rung log-only.
- Swing trigger reusing fan-spike EMA (`const.py:631`); ΔRH >X%/Y-min emits MEDIUM even below ceiling.
- **Acceptance:** patio (mean 77%) 0 pages 7-day; synthetic 20%/10-min indoor spike still emits.

### A5. CO2 + TVOC ladders + misclassified sensor removal
- **CO2 provenance (revision 4):** 2026-07-20 audit — Study A p50=871 / p90=1200 / max=1713 ppm. `CO2_LOG_ONLY_CEILING_PPM=1200` = p90 of normal occupied range.
- **TVOC provenance (revision 4):** Master Bath p50=36 / p90=145 / p99=994 / max=1244. `TVOC_ABSOLUTE_HIGH=1500` above observed max — only genuine novel extremes fire. `TVOC_SUSTAINED_S=1800` mirrors humidity-ladder pattern.
- Remove `sensor.test_kidde_co2_level` (test rig) and dimmer internal-temp from safety discovery (`safety.py:192` per audit).
- **Acceptance:** CO2/TVOC 7-day pages ≤ 3 combined; two removed entities no longer in discovery; synthetic real Kidde CO emit still fires.

### A6. D2-lag metric fix
- `energy_battery.py:1262-1345`: entity age → `last_reported`.
- **Cross-post pointer added (revision 9)** to `PLANNING_enphase_cloud_reliance.md`.
- **Acceptance:** 7-day pages ≤ 1 (baseline 3/wk); synthetic `last_reported` freeze still fires.

### A7. Preserved-signal regression fixture
- Fixture list (water leak, Envoy write-verify CRIT, AC Reset FAILED, Envoy Offline); synthetic emit each; each reaches `async_notify` at pre-cycle severity.

### A Acceptance (cycle-level)
- **Live/MCP:** Drive each of 7 noise classes; assert `notification_log` matches A1-A6 targets.
- **Live/MCP:** Fire each preserved signal (A7); severity preserved.
- **Sensor:** `sensor.ura_notification_manager.notifications_today ≤ 6` on 24h post-deploy; optimizer rows only in digest window.
- **Live:** 24h report includes per-(coordinator, hazard_type) class count vs baseline (revision 5 invariant check).

---

## Cycle B — "Safety rails" (with hoisted minimal dry-run gate)

**Goal:** CRITICAL semantics safe + non-fatiguing; ship minimal dry-run gate so B's own live exercise is safe.

### B0. Minimal `CONF_NM_DRY_RUN` gate (revision 1)
- `CONF_NM_DRY_RUN` boolean (options-flow default false; Switch entity for live toggle).
- Insert `if self._dry_run_active: _log_dry_run(...); return` at **every** `hass.services.async_call` site in the emit path: `_send_pushover`, `_send_companion`, `_send_whatsapp`, `_send_imessage`, `_send_tts`, `_trigger_alert_lights` → `_run_light_pattern` (all emit-triggered light service calls; NOT the teardown `_restore_alert_lights` — that must always run so state is honest).
- `_log_dry_run` writes minimal row (timestamp, coordinator, severity, channel, would-have-target) to `notification_log` via additive `ADD COLUMN dry_run=0` migration.
- **This is the minimal gate.** Cycle C builds full structured audit-log UX + routing-decision explainability on top.
- **Invariant B(vi)** proven by Review C real-source-mutation per site.

### B1. Life-safety subtype + per-subtype cadence
- `NM_LIFE_SAFETY_HAZARDS = {"smoke","fire","carbon_monoxide","co","water_leak","flooding","intrusion","freeze_risk"}` in `const.py`.
- Split `NM_CRITICAL_REPEAT_INTERVAL` → `NM_REPEAT_INTERVAL_LIFE_SAFETY=30`, `NM_REPEAT_INTERVAL_NON_LIFE_SAFETY=300`.
- Modify `_schedule_repeat` (line 1296) to select cadence from `_active_alert_data["hazard_type"]`.
- **Invariants B(ii)+(iii)** proven by per-site source mutation.

### B2. Safe-word ack registry with restart resilience
- Extend `get_persistence_state` / `restore_persistence_state` with `ack_registry: dict[event_key, {"acked_at": iso, "safe_word_verified": bool}]`.
- `event_key = (coordinator_id, hazard_type, location, alert_episode_id)`; episode id at `_enter_alerting`.
- Safe-word verified in `_handle_pushover_webhook` / `_handle_bb_webhook` / `_handle_whatsapp_reply` writes registry AND cancels repeat across all channels.
- Restart: `restore_persistence_state` refuses REPEATING for acked episodes.
- **Write-volume regression (revision 6):** pre-deploy snapshot of `notification_log` (and any new ack-registry table) row rates by (coordinator, severity); post-deploy ±25% comparison per optimizer write-flood precedent. Registry writes are once per episode-ack — expected small delta; proving is the point.
- **Invariant B(i)** proven by mid-episode HA restart test.

### B3. Token-bucket rate limiter
- Per-recipient + per-channel + global buckets; continuous refill; overflow → bounded FIFO (`NM_OVERFLOW_QUEUE_MAX`); life-safety bypasses.
- Buckets tunable via Number entities.
- **Invariant B(iv)** proven by adversarial storm test.

### B4. Boot-burst guard
- `async_setup` completion installs `NM_BOOT_SETTLE_S=60` window collapsing per-`(coordinator, hazard_type)` to one emit.
- **Invariant B(v)** proven by boot-storm test.

### B Acceptance (cycle-level)
- **Live/MCP:** Fire synthetic smoke CRITICAL with `CONF_NM_DRY_RUN=true`; `notification_log` shows dry-run rows at 30 s cadence until safe-word ack via MCP-driven webhook; assert **zero real `hass.services.async_call` to notification services** (HA log capture).
- **Live/MCP:** Fire synthetic non-life-safety CRITICAL (`test_synth`); 300 s cadence observed.
- **Live/MCP:** Storm test — 20 MEDIUM in 5 s; `overflow_queue_depth` non-zero, drains at refill.
- **Live/MCP:** Mid-episode HA restart; ack registry replays; no duplicate.
- **Sensor:** `sensor.ura_notification_manager` gains `dry_run_active`, `overflow_queue_depth`, `bucket_capacity_remaining_per_channel`, `active_ack_registry_size`.
- **Live:** README write-back records observed cadence per subtype, bucket behavior, and write-volume comparison (revision 6).

---

## Cycle C — "Routing + full dry-run UX + DND-bypass" (Tier 3)

**Goal:** Replace global severity-per-channel routing with per-recipient (× optional hazard_type) matrix; promote dry-run to first-class audit UX; formalize DND-bypass; ship NM-1 mute shortcut.

### C1. Per-recipient criticality × channel (× optional hazard_type) matrix — decision on revision 3
- **Decision: adopt hazard_type as an OPTIONAL third axis in Cycle C**, severity × channel as default view (matrix collapses to 2D when hazard-type axis unset).
- **Justification:** NM-6 is real (operator has legitimate need for "route water_leak differently than intrusion for spouse X"); incremental schema cost is small (nullable third key); deferring to Cycle D would ship a Cycle C that has to be re-migrated later — worse than one migration now. The 2D-default preserves UX simplicity for households that don't need the extra axis.
- Options-flow: per person, `{severity → {channel → bool}}` plus optional `{hazard_type → {severity → {channel → bool}}}` overrides.
- Backward compat: legacy `CONF_NM_*_SEVERITY` → equivalent matrix via migration function.
- `_channel_qualifies` replaced by `_route_for_recipient(recipient, hazard_type, severity)`.
- **Invariant C(i)** proven by deterministic routing test over full tuple space (config-boundary combinatorial).

### C2. Full dry-run / audit UX (builds on B0)
- Structured audit log: extend `notification_log` (or add `notification_audit_log`) — per-recipient channel-set decisions, quiet-hours applied, DND-bypass applied, dedup outcome, rate-bucket outcome.
- Query surface: sensor attribute + service to retrieve last N routing decisions.
- **Invariant C(ii)** proven by Review C real-source-mutation of every `hass.services.async_call` inside NM AND Review D adversarial-completeness re-enumeration (Tier-3).
- **Write-volume regression (revision 6):** pre-deploy `notification_log` row rate by (coordinator, severity); post-deploy ±25% comparison. Audit rows are per routing decision (potentially many per notification) — this is exactly the risk this check exists for.

### C3. Per-recipient DND-bypass lists
- `dnd_bypass_severities: set[Severity]` (default `{CRITICAL}` — preserves existing).
- Quiet-hours filter rewritten: `if severity in recipient.dnd_bypass_severities: emit; else respect quiet-hours`.
- **Invariant C(iii)** proven by boundary test.

### C4. NM-1 "mute one person's one channel fast" shortcut (revision 7)
- First-class UX for the frequent 2 AM operation: per (person, channel), Button (or service) `nm.mute_person_channel(person_id, channel, duration_minutes=60)`.
- Sets per-`(person, channel)` silence-until; `_route_for_recipient` respects it before matrix lookup.
- Companion mute-all-person and mute-all-channel buttons.
- **Justification:** the matrix UX (options-flow) is too slow for the "Bathroom X won't stop" case; shortcut lives on person/channel entities + in Companion actions.
- **Acceptance:** MCP-driven service call mutes; subsequent alert to that (person, channel) suppressed; other channels for same person still fire; expiry auto-clears.

### C Acceptance (cycle-level)
- **Live/MCP:** With `CONF_NM_DRY_RUN=true`, sweep synthetic (severity × hazard_type × recipient) tuples; assert zero notification-service `hass.services.async_call`; audit log matches expected decisions.
- **Live/MCP:** Legacy config (no matrix set) produces routing identical to pre-cycle for fixture tuples.
- **Live/MCP:** DND-bypass — MEDIUM during quiet hours fires only for recipients with MEDIUM in bypass.
- **Live/MCP:** NM-1 shortcut — mute + per-channel scope + expiry.
- **Sensor:** `sensor.ura_notification_manager` gains `routing_matrix_configured_recipients`, `active_mutes_per_person`.
- **Test:** Options-flow → RestoreEntity round-trip for matrix + DND lists + hazard-type overrides.
- **Live:** README write-back with 24h routing-decision distribution + write-volume comparison (revision 6).
- **Tier-3 operator checkpoint before deploy** (mandatory).

---

## Pipeline sequencing + gates

1. Build & Tier-2 review of Cycle A → deploy → live-validate → README write-back → advance.
2. Build & Tier-2-DB review of Cycle B (including B0 minimal dry-run gate) → deploy → live-validate (dry-run ON for synthetic CRITICALs) → README write-back → advance.
3. Build & Tier-3 review of Cycle C → **operator checkpoint** → deploy → live-validate → README write-back → close pipeline.
4. **Only after Cycle C validates**, per-person channel targets may be populated (pipeline precondition #1 released).

**No operator checkpoints between A and B.** Tier-3 checkpoint before C deploy is mandatory.

**Baseline snapshot before Cycle A build starts:** capture 7-day (coordinator, hazard_type, severity) row counts from `notification_log` (+ would-page baseline) as `pre-review-vN.M.P` tag artifact.

---

## Deferred-work register

Empty at plan open. Cycles populate on close.

---

## Revision log (post-critique, 2026-07-20)

| # | Revision | Where landed |
|---|---|---|
| 1 | Hoist minimal `CONF_NM_DRY_RUN` gate to Cycle B (B0); pipeline precondition #1 keeps per-person targets blank until Cycle C validates | Header preconditions; Cycle B B0; invariant B(vi); Grep table row; Numbers-Get-Knobs row |
| 2 | Operator sequencing directive quoted verbatim; A→B→C stands, no B2 hoist | Header |
| 3 | **Decision:** hazard_type = optional 3rd matrix axis in Cycle C (adopted, not deferred) | Cycle C section C1; Grep table |
| 4 | CO2 + TVOC threshold provenance cited from 2026-07-20 audit distributions | Cycle A A4/A5; Numbers-Get-Knobs table |
| 5 | Cycle A invariant strengthened: "no single class exceeds 2× its pre-deploy weekly rate" | Falsifiable-invariant table row A; Cycle A acceptance |
| 6 | Write-volume regression (pre/post ±25%) added to B (ack registry) and C (audit rows) | Cycle B B2 + acceptance; Cycle C C2 + acceptance; invariant C(ii) |
| 7 | NM-1 "mute one person's one channel fast" as first-class shortcut | Cycle C new C4; Numbers-Get-Knobs |
| 8 | Dedup-key intent `{event_type}:{location}` (not per-person) deliberately preserved per 2026-05-30 audit body | Institutional context, dedicated subsection |
| 9 | Cross-coordinator ripple for A2 (optimizer) and A6 (energy_battery) cross-posted | New "Cross-coordinator ripple" section; A2 + A6 pointer lines |
| 10 | **Decision:** Cycle C elevated to Tier 3 with 4th adversarial-completeness pass on dry-run zero-outbound invariant | Tier classification row C; Cycle C pipeline gate; C-level acceptance operator checkpoint |
