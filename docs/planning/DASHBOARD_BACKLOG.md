# Dashboard Backlog

Dashboard-specific tracking. Companion to `docs/BACKLOG.md` (URA Python cycles) and `docs/planning/PLANNING_v5.x_dashboard_v4_react_port.md` (the implementation plan).

**Recall hint:** "Dashboard backlog" or "Resume URA Dashboard v4"

---

## v5.0 — Foundation (in progress, branch `feature/dashboard-v5.0-foundation`)

### Shipped
- **D1 (commit `4e01fc9`)** — P6 light Navet-styled shell:
  - `Rail.tsx`, `MobileTabs.tsx`, `Shell.tsx` with body class system + mood gradients
  - 10 tabs registered with lazy-mount + visited-ref state
  - `p6-shared.css` imported as canonical (1607 LoC of P6 styles)
  - Dev-mode bypass for HassConnect (Playwright + visual iteration)
  - Visual diff vs P6 reference: passing at desktop + mobile (2 iteration rounds within 3-round cap)

### In flight — Tab content shell-out (D3-D7 fast pass with stubbed data)

Strategic shift 2026-05-19 (user directive): build out all 10 tabs with content using existing sensors + stubbed values for missing ones, BEFORE running the Python sensor cycles. Gets aesthetic completeness in front of user for validation. Stubs become live-wiring once Python cycles ship.

Per-tab status:
- [ ] Home tab content
- [ ] House tab content
- [ ] Zones tab content
- [ ] Rooms tab content
- [ ] Energy tab content
- [ ] HVAC tab content
- [ ] Presence tab content
- [ ] Security tab content
- [ ] Safety tab content
- [ ] Diagnostics tab content

### Deferred for after shell-out
- Knob + ControlsBar React primitives (defer until first tab needs them; CSS classes already exist in p6-shared.css)
- Status-hero card variant (defer to D3 Home tab build)
- Memoization regression fix (defer to D8 polish)

---

## v5.1+ — Background images variant

User chose v5.0 = P6 (no images). Background variant (P7) ships in v5.1+:
- Photo selection per tab (Unsplash currently; commit to `public/backgrounds/` for ship)
- Scrim opacity is already correct in P7 (no further adjustment needed per user advisory 2026-05-19)
- Theme toggle UI (so user can switch between P6 / P7 / dark variants without rebuild)

---

## Cross-cycle dependencies

The dashboard's React work depends on Python sensor work for live data. Order:
1. **v4.6.11** (already filed in `docs/BACKLOG.md`) — D3 anomaly persistence + LOW polish
2. **v4.6.11 Cycle A add-on** — attribute adds (`health_status`, `per_zone_breakdown`, `idle_duration`, `current_persons`, `source_breakdown`, `zone_limits`, `events_today_count`, `auto_dismissed_count`). ~70 LoC.
3. **v4.6.12 Cycle B** — net-new aggregator sensors (`ZoneMotionEventCountSensor`, `HouseSystemDemandSensor`, `EnergyGridDemandSensor`). ~120 LoC.
4. **v4.6.13 Cycle C** — coordinator telemetry sensor set (~80-100 LoC revised; queries existing `ura_activity_log`).
5. **D3-D7** dashboard live wiring of each tab.
6. **D8** dashboard polish + a11y + v5.0 ship.

Sensor audit details: `docs/planning/DASHBOARD_v5_sensor_audit.md`.

---

## Killed / out of scope

- **ETA home / commute time** — killed by user 2026-05-19. Don't surface even as a stub.
- **Wake zone button** — UI action only, no sensor needed.
- **Write queue pending depth** — internal queue state; only surface if ops needs it (not by default).

---

## Notes on activity_logger discovery (2026-05-19)

`activity_logger.py` + `ura_activity_log` table capture coordinator/action/room/zone/importance/description/details_json/entity_id/timestamp on every URA decision. This is the existing foundation for coordinator telemetry — the planned "decisions today / override freq" sensors are just queries against this table, not new logging infra.

Implication: original Cycle C estimate of ~280 LoC drops to ~80-100 LoC.

**One gap:** schema doesn't track outcomes explicitly. Two paths:
- (i) Proxy via `importance` for v5.0 (info=success, warning=partial, error=failure). Requires no schema change. Assumes emitters use importance consistently.
- (ii) Add `outcome` column to `ura_activity_log` for v5.1+ telemetry-quality cycle. Tier 2-DB schema migration.

Cycle C planning will decide; preference is (i) for v5.0 ship speed.
