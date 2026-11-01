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
