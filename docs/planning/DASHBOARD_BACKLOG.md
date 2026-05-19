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

## v5.0.x — Dashboard performance polish (user-flagged 2026-05-19)

User feedback at v4.6.10.1 mount preview: "Fidelity is good. Performance is still not amazing."

Tactical optimizations to investigate before D8 polish ship:

1. **Locale chunk explosion.** Vite build produces ~40 locale chunks (af/ar/bg/bn/bs/ca/...) at 100-400KB each from date-fns. The `resolve.alias` in vite.config.ts redirects to en-US but Vite is still emitting them. Investigate: stricter alias pattern, manualChunks override, or explicit date-fns/locale/en-US import only.
2. **Initial bundle size.** index-*.js is ~330KB; hakit-*.js is ~294KB. Combined first-paint ~620KB. Acceptable but trim where possible (tree-shake unused @hakit/core exports; lazy-load tabs not yet visited).
3. **`useEntity` re-render footprint** (when live wiring lands in D3-D7). Per @hakit/core v6 research: returns new object identity on every entity update, no built-in throttle. Plan `React.memo` with custom equality on card components OR use `useSubscribeEntity` directly with selector equality.
4. **Iframe overhead.** `panel_custom` + iframe doubles React/JS execution context vs. direct mount. Defer until v5.0.x decides whether to keep iframe (with issue #304 mitigation) or refactor to direct web-component mount.

LoC: investigation pass first (~1h), then targeted fixes (~50-100 LoC). Tier 1.

---

## v5.0.1 — hakit issue #304 mitigation (panel_custom iframe-recreation)

Filed 2026-05-19 from @hakit/core research. Open issue: https://github.com/shannonhochkins/ha-component-kit/issues/304

**Problem:** When the URA Dashboard tab is backgrounded in HA for >5 min and then returned to, HA's `panel_custom` machinery destroys and recreates the iframe. hakit's React tree re-mounts but the WebSocket may be mid-reconnect, leading to `subscribeUsers: failed to fetch users 3` errors. User has to hard-refresh.

**Maintainer status:** can't reproduce on ingress (HAKit add-on path); `panel_custom` path acknowledged as not their test target.

**Mitigation strategy options:**
1. **Cache the iframe DOM node in the web component.** In `ura-panel-v3.js`, store `this._iframe` and re-attach it in `connectedCallback` rather than creating a fresh one. Survives HA's destroy/recreate of the custom element if the element itself gets reused.
2. **Detect the failure mode in main.tsx.** On HassConnect mount, if status remains `pending` with `subscribeUsers` error >5s, force `window.location.reload()`. Auto-recovery instead of user-driven hard-refresh.
3. **Switch to direct mount (no inner iframe).** Render React app directly into the web component (or its shadow root). Removes the iframe entirely → bug doesn't apply. Larger refactor.

**Recommend option 1 first** (smallest blast radius). Option 2 as a safety net. Option 3 if 1+2 don't fully solve.

**Acceptance test:** Open URA Dashboard, switch to another HA tab, leave for 10 minutes, switch back. Dashboard should reconnect within 3 seconds without hard-refresh.

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

## @hakit/core v6 research findings (2026-05-19)

Documented during dashboard mount preview (v4.6.10.1). Key facts to preserve:

**Auth model:**
- hakit v6 auto-inherits from `window.top.hassConnection` when same-origin
- localStorage key is literally `"hassTokens"` with `AuthData` shape (not URA's prior `{type, hassUrl, access_token, token_type}` — that shape gets *rejected*)
- Three valid auth paths: inherited (best), `hassToken` prop (long-lived), saved tokens (fallback)
- Set `windowContext: window.top` in HassConnect options when iframed

**Performance:**
- `useEntity` returns new object identity on every entity update
- v6 removed `throttle` parameter — no built-in rate-limit
- For 50+ entity dashboards, plan `React.memo` with custom equality or use `useSubscribeEntity` directly

**Breaking changes from v4 → v6 to handle in D3-D7 live wiring:**
- `useStore` → `useHass`
- `HassContext` / `HassContextProps` removed
- `getConfig`/`getServices`/`getUser`/`getStates` direct methods removed — use store subscriptions
- ButtonCard/SensorCard: no auto domain prefix, no `unitOfMeasurement` prop
- TimeCard: explicit `entity` prop required
- Light entity: `kelvin` → `color_temp_kelvin`
- framer-motion removed
- Breakpoints moved from `@hakit/core` to `ThemeProvider` (in `@hakit/components`)

**Entity name typing:**
- `EntityName = DefaultEntityName | "unknown"` where `DefaultEntityName = "${AllDomains}.${string}"`
- String literals typecheck against template literal type
- Variable strings need `as EntityName` cast
- Optional: `sync-user-types` script in hakit core to generate strict union from live HA — would give autocomplete + strict typing if we add it to URA's build

**Open issue blocking us:** [#304 — HassConnect Suspend/Resume](https://github.com/shannonhochkins/ha-component-kit/issues/304). See v5.0.1 entry above.

---

## Notes on activity_logger discovery (2026-05-19)

`activity_logger.py` + `ura_activity_log` table capture coordinator/action/room/zone/importance/description/details_json/entity_id/timestamp on every URA decision. This is the existing foundation for coordinator telemetry — the planned "decisions today / override freq" sensors are just queries against this table, not new logging infra.

Implication: original Cycle C estimate of ~280 LoC drops to ~80-100 LoC.

**One gap:** schema doesn't track outcomes explicitly. Two paths:
- (i) Proxy via `importance` for v5.0 (info=success, warning=partial, error=failure). Requires no schema change. Assumes emitters use importance consistently.
- (ii) Add `outcome` column to `ura_activity_log` for v5.1+ telemetry-quality cycle. Tier 2-DB schema migration.

Cycle C planning will decide; preference is (i) for v5.0 ship speed.
