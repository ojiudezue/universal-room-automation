# Worklog — November 2026 session

## Release index (auto-appended at deploy)

- 2026-11-01 09:05 **v5.103.93** — v5.103.93: battery charge from a second local source when the main source drops (cards: ENVOY-STREAM-SOC-TIER-1)
- 2026-11-01 10:17 **v5.103.94** — v5.103.94: Energy Coordinator restore no longer zeroes today's counters after a slow boot (cards: EC-DB-RESTORE-TIMEOUT-1)

## 2026-11-01 session log
**Shipped:** v5.103.93 stream SOC tier (configured: battery_2 / load_power / 120 s; trusted) · v5.103.94 EC restore per-step timeouts (validated: counters survived restart).
**Config (no code):** 578 false tripped-breaker anomaly rows purged (backup .claude/tmp/) · power coverage: 17 rooms + house list re-mapped, 3 double counts removed, new helper sensor.sub_panel_unmonitored_energy_today (Vue balance − Vue 3B) at house level, ~94-99% expected · pre-arrival window 30 → 20 min.
**Built, awaiting gate:** reserve false-revert fix (Tier 3, 4 reviews + orchestrator mutation + name-diff clean) → operator go for v5.103.95 · BLE grace + fleet floor (3 reviews, fix-up done) → name-diff running.
**Findings:** OC slice-0 eval measured harness defects (AUDIT_oc_slice0_eval_validity.md); plan = live eval with intercepted writes + vision:157 context pack (OC-CONTEXT-PACK-1) · Jaya 06:34 vacancy = one-tick BLE blip with no re-arm (fix in BLE grace build) · HVAC borrows clean · zone sweep working as designed, card HVAC-ZONE-SWEEP-PURPOSE-AND-FIXES-1 · zone watts exist as room roll-up, zone-level loads excluded (ZONE-LIVE-POWER-ROLLUP-1) · READMEs .86-.88 validated retrospectively.
- 2026-11-01 11:01 **v5.103.95** — v5.103.95: no false "Envoy write reverted" page at the nightly Envoy drop (cards: EC-ENPHASE-CONNECTIVITY-RESILIENCE-1)
- 2026-11-01 11:06 **v5.103.96** — v5.103.96: a short Bluetooth blip no longer empties a room; BLE-leads floor scales with the fleet (cards: BLE-LOCATION-QUALITY-1,PERSON-BLE-WINS-OVER-STALE-GPS-1)
- 2026-11-01 11:46 **v5.103.97** — v5.103.97: zone power and energy include zone-level loads (cards: ZONE-LIVE-POWER-ROLLUP-1)

### 2026-11-01 afternoon
**Shipped:** v5.103.95 reserve false-revert (Tier 3) and v5.103.96 BLE grace + fleet floor — restarted 11:22, live. v5.103.97 zone power/energy incl. zone-level loads — installed, waiting for restart.
**Built, in validation:** zone sweep cleanup (per-zone opt-out, real-sweep log/counter, pre-arrival fan exemption, manual devices off-only, fans excluded) — reviews A/B fixed, full-suite name-diff running.
**Config (no code):** relays added to lights then REVERTED (operator: intent was energy; relay energy already counted / sub-metered); Samba mount reads keychain item `ura-samba` (CLAUDE.md + 2 skills); 4 credential backups moved to ~/.ura-backups; .gitignore rule; family map section on ura-v8 People (user-restricted to Oji), iCloud trackers; Puppet add-on installed (needs access_token, not started); ha-mcp screenshot mode enabled in .mcp.json (next session); Places installed via HACS (needs HA restart + one entry per person).
**Audits:** zone sweep effectiveness; security sweep + mop-up; OC live-eval plan rev 2 + D0 evidence (7 cases, C6 dropped).
**Cards:** SECURITY-LOCK-SWEEP-RETRY-CAP-1, FRONT-LOCK-OFFLINE-1 (new locks coming), GARAGE-COVER-FLAP-1, URAV8-ZONE-ENERGY-DISPLAY-1, ZONE-LIVE-POWER-ROLLUP-1 (shipped .97), OC-CONTEXT-PACK-1, HVAC-ZONE-SWEEP-PURPOSE-AND-FIXES-1.

### Operator approvals 2026-11-01 (ledger)
| Approval | Status |
|---|---|
| Deploy v5.103.93, configure stream SOC (battery_2 / load_power / 120) | done |
| Purge 583 false tripped-breaker rows | done (578; 5,242 older kept, backup) |
| Reserve-check false-page fix (option A, Tier 3) | shipped v5.103.95, live test tonight |
| BLE re-arm/grace + fleet fraction | shipped v5.103.96 |
| Power coverage config re-map (freezer→Kitchen, wine cooler→Butler Pantry, sub-panel unmonitored helper) | done |
| Pre-arrival window 30→20 min | done |
| Start carded work (zone sweep, zone power rollup, OC live eval) | sweep in validation; rollup shipped .97; OC plan rev 2 + D0 done, harness next |
| Zone sweep cleanup + fan-fight + manual devices (accept still-person risk, A) | built, name-diff running |
| Relays: energy only, not auto-on | lights reverted; energy already counted |
| Inovelli Master Bedroom light manual | already a manual switch |
| Retire expired OC cases | recorded in plan |
| Samba: keychain swap yes; rotate later; NO history rewrite | keychain swap done |
| Family map (per-person grid + shared map, People view, Oji only) | built; visual review pending screenshot engine |
| ha-mcp screenshot beta | Puppet installed; needs token + session restart |
| Install Places | downloaded; needs HA restart + per-person entries |
| Front lock | new locks coming (operator) |
- 2026-11-02 00:33 **v5.103.98** — v5.103.98: "Saved today" counts battery energy used at mid-peak and peak; cost per hour on the full rate (cards: EC-COST-AND-FORECAST-MATH-1)
- 2026-11-02 06:52 **v5.103.99** — v5.103.99: zone vacancy sweep honours per-zone opt-out, keeps pre-arrival fans, and turns off manual devices (cards: HVAC-ZONE-SWEEP-PURPOSE-AND-FIXES-1)
- 2026-11-02 07:49 **v5.103.100** — v5.103.100: savings can go negative; tomorrow's forecast on the local date with Solcast and per-period pricing; forecast accuracy log (cards: EC-COST-AND-FORECAST-MATH-1)

- 2026-11-02 (FYI from HomeLab session, no action): HA gained the Beszel Bridge add-on (2dc376b9_beszel-bridge v0.21.1.1, read-only hub user, Mosquitto), ~200 MQTT `sensor.beszel_*` entities at 30 s poll (21 systems), hourly `sensor.beszel_smart_*` (21 disks, from webhost CT 110 cron), and storage dashboard /lab-servers (script-generated by homelab scripts/ha/beszel_dashboard.py — do not hand-edit). Recorder: if DB growth matters, exclude beszel network_receive/transmit first (see RUNBOOK_recorder_excludes.md). Not URA-owned.
- 2026-11-03 17:24 **v5.103.101** — v5.103.101: night lights-out failsafe; alarm for a hung camera detector; ack no longer speaks when speech is off; AC savings totals survive restarts (cards: SHARED-SPACE-AUTO-OFF-FAILSAFE-1,CAMERA-SILENT-PRODUCER-TRIPWIRE-1,NM-ACK-TTS-IGNORES-DISABLE-1,HVAC-KWH-AVOIDED-TOTAL-NOT-MONOTONIC-1,TEST-DPM-WINTER-MONTH-COUPLED-1,ENERGY-TODAY-MIDNIGHT-FREEZE-1)
- 2026-11-03 21:35 **v5.103.102** — v5.103.102: Envoy status no longer stuck on "stale" (cards: ENVOY-FLAKINESS-181243-1)
- 2026-11-05 14:46 **v5.103.103** — v5.103.103 — Zone orphan-device cleanup no longer deletes devices that still have entities (cards: ZONE-ORPHAN-DEVICE-REMOVE-GUARD-1)
- 2026-11-05 15:41 **v5.103.104** — v5.103.104 — Room menu trimmed in Advanced mode too; per-room electricity rate removed (cards: ROOM-TYPE-TRIMMED-MENU-1)
- 2026-11-05 15:55 **v5.103.105** — v5.103.105 — Config-flow timing logs: DEBUG by default, WARNING only for slow steps (cards: CONFIG-FLOW-SLOW-ONBOARDING-1)
- 2026-11-07 14:00 **v5.104.0** — v5.104.0 — Ask the house by text: `diag` menu over iMessage / WhatsApp / HA app (cards: NM-INBOUND-HOUSE-QUERIES-1)
- 2026-11-07 18:21 **v5.105.0** — v5.105.0 — Garage remote lockout: SC lock regime (Phase 1) (cards: GARAGE-REMOTE-LOCKOUT-SCHEDULE-1)
- 2026-11-08 01:05 **v5.106.0** — v5.106.0 — SC "Never auto-lock" list + Away Lock (cards: SC-LOCK-SWEEP-EXCLUDE-1,SC-LOCK-REGIME-DOOR-LOCKS-1)
- 2026-11-08 09:14 **v5.106.1** — v5.106.1 — WhatsApp sends via ha-wa-bridge 3.x (`wa_bridge`) (cards: WA-BRIDGE-DOMAIN-1)
- 2026-11-08 13:03 **v5.106.2** — v5.106.2 — Inclement leftovers: TOU rate ranking, Envoy-blind outage counter, retired threat-list removal (cards: EC-STORM-FULLHOLD-DEGRADED-ENVOY-AVAILABLE-1,EC-BLIND-DEESCALATE-TOP-RATE-1)
- 2026-11-08 22:48 **v5.107.0** — v5.107.0 — Perimeter false-positive gates, egress cameras as perimeter alerts, truthful WhatsApp delivery (cards: PERIMETER-FP-STREET-NOISE-1)
- 2026-11-09 02:45 **v5.107.6** — v5.107.6 — Entry areas read from the egress tracker (cards: FACE-SOURCE-REGISTRY-DISCOVERY-1,PERIMETER-FRIGATE-SNAPSHOT-CAPTURE-NEVER-1,LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1,PERIMETER-IDENTITY-FOLLOWUP-1,LOCK-ENTRY-AREAS-WRONG-OBJECT-1)
- 2026-11-09 13:43 **v5.108.0** — v5.108.0 — Visitors present, and GUEST means a guest is staying (cards: GUEST-MODE-SPLIT-VISITORS-1)
- 2026-11-09 16:39 **v5.108.1** — v5.108.1: Frigate events straight from MQTT, and the face bridge on the live prefix (cards: PERIMETER-FRIGATE-MQTT-DIRECT-1,FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1)
- 2026-11-10 12:09 **v5.108.5** — v5.108.5: guest stay exit day veto (cards: GUEST-LEFT-BUTTON-READY-1,LOCK-BOOT-RECHECK-ENGAGE-1,HVAC-GUEST-EVIDENCE-RULE-1,GUEST-STAY-EXIT-DAY-VETO-1)
- 2026-11-10 17:51 **v5.108.6** — v5.108.6: Lock retry cap, optimizer meta never pages, dead anomaly metrics removed (cards: SECURITY-LOCK-SWEEP-RETRY-CAP-1,OPTIMIZER-META-NEVER-PAGES-1,ANOMALY-METRIC-DISPOSITION-1)
- 2026-11-10 18:39 **v5.108.7** — v5.108.7 — NM buttons refresh when the Notification Manager is ready (cards: NM-BUTTON-READY-PATTERN-1)
- 2026-11-11 07:00 **v5.108.8** — v5.108.8: Lights fade on every ambient path; faster, order-proof test suite (cards: LIGHT-TRANSITION-COVERAGE-1,SNAP1-FRIGATE-TRAVERSAL-1)
- 2026-11-11 14:00 **v5.108.9** — v5.108.9: Simpler forms: collapsed Advanced sections and plain-language text (cards: FORM-TEXT-PLAIN-PASS-1,PRESENCE-GEOFENCE-FIELD-DEAD-1,CLIMATE-BACKSTOP-SECTION-CLEAR-ON-ABSENT-1)
- 2026-11-11 19:12 **v5.108.10** — v5.108.10 — Battery charge source, per day (cards: EC-BATTERY-CHARGE-SOURCE-DAY-1)
- 2026-11-12 12:53 **v5.108.11** — v5.108.11 — Four Tier-1 fixes (cards: FAN-RECHECK-FORM-RESTORE-REVERT-1,SC-GEOFENCE-PERSON-SNAPSHOT-1,KANBAN-SHIP-FLOW-CARDS-1,EC-CFG-SELFHEAL-FALSE-CRITICAL-1)
- 2026-11-12 13:46 **v5.108.12** — v5.108.12 — Shared-space night failsafe runs in paused rooms (cards: SHARED-SPACE-AUTO-OFF-FAILSAFE-1)
- 2026-11-12 15:49 **v5.108.13** — v5.108.13 — EV rung-1 redirect cap; lock suspicious-arrival hold (cards: EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1,GARAGE-REMOTE-LOCKOUT-SCHEDULE-1)
- 2026-11-12 21:08 **v5.108.14** — v5.108.14 — Pre-arrival stands down when the zone is already cool; arrival pre-heat; Net Grid Today (cards: HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1,EC-IMPORT-TODAY-NET-AFTER-RESTART-1)
- 2026-11-12 21:53 **v5.108.15** — v5.108.15 — The exterior seam file actually loads (cards: EXTERIOR-SEAM-FILE-LOADER-1)
- 2026-11-13 01:14 **v5.108.16** — v5.108.16 — Person sightings, phase 1 (cards: INTERIOR-PATH-MAP-1)
