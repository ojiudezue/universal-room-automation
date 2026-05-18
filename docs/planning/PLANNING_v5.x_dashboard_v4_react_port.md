# PLANNING v5.x — Dashboard v4 React Port

**Status:** Scoped, ready to start (2026-05-18). Design cycle closed.
**Tier:** Tier 2 multi-cycle (4 weeks of focused dashboard work, broken into ~7-8 sub-cycles)
**Predecessor design work:** 9 HTML prototypes at `docs/dashboard-prototypes/v4/`, P6 selected as winner 2026-05-18
**Recall hint:** "Resume URA Dashboard v4" or "Resume dashboard work"
**Companion memory:** `project_dashboard_v4` — the design decisions in compact form

---

## Why this plan exists at all

User feedback at design close, captured verbatim:
> *"I think dashboard plans tend to get ignored because it's not python or deployed via HACS. We need a full plan and we need to persist it."*

This document exists specifically to defeat that drift. The dashboard is a **first-class URA deliverable** alongside Python integration cycles, not a side project. It versions with URA, ships in URA releases (`dashboard-v3/dist/` committed and served as an HA panel), and has acceptance criteria for every deliverable just like a Tier 2 Python cycle.

User also said:
> *"A bit concerned you can actually get this done but willing to try."*

This plan is sized to that concern — modest claims, sub-cycles small enough to ship visible wins weekly, sensor gaps surfaced upfront before they become mid-port surprises.

---

## TL;DR

Port the locked P6 fulcrum (Light theme, styled, 10 tabs) to the existing `dashboard-v3/` React app over ~3-4 weeks. Each tab is a sub-cycle with live-wired sensors + acceptance criteria. Three Python mini-cycles inside URA proper unblock specific sensor surfaces.

**Hard checkpoints:**
1. **D1 Foundation ships** — tokens.ts extension, Knob/ControlsBar primitives, Shell — within first week
2. **At least one tab ships fully live-wired** within week 2 (Home or Diagnostics — pick the smallest)
3. **All 10 tabs at minimum-viable** by end of week 3
4. **Polish + perf pass + accessibility** in week 4, then **v5.0.0 dashboard ship** committed to URA repo

If at any of those checkpoints the work is materially behind, **stop and reassess scope** — don't drag a half-finished v4 through six months.

---

## Origin

- 2026-05-17 design session generated 9 prototypes (P1–P9)
- P2 (Level Tabs) selected as structural fulcrum
- P4 added Navet styling pass + Safety tab
- P5/P7/P9 added per-tab background images (deferred — flavor pass post-v5)
- P6 selected as final theme on 2026-05-18 — light, styled, no images
- User asked for one final iteration on P6 with status-color-as-visual-hero hierarchy applied to person cards (Home + Presence tabs). Shipped in final P6 commit.

The 9 prototypes are visual reference, not code. The React port starts from `dashboard-v3/` with its existing token system + `@hakit/core` data layer.

---

## Existing foundation (dashboard-v3/)

| Layer | What's there | Reuse % |
|---|---|---|
| Build | Vite 6 + React 19 + TypeScript 5 | 100% |
| HA data | `@hakit/core` 4.0 (`useEntity` subscriptions) | 100% |
| Icons | `lucide-react` | 100% |
| Charts | `recharts` | 100% |
| Design tokens | `src/design/{tokens.ts, GlobalStyles.tsx, global.css}` | **needs P6 extension** |
| Components | `src/components/` | needs Knob, ControlsBar, status-hero card variants |
| Shell | tab swap + viewport toggle | needs P6 Navet rail styling |
| Lazy-tab + visited-ref | Per v3 critique | **also needs the memoization fix flagged in v2 critique** |

Estimate at design close: 80% of structural plumbing already there. This plan validates that estimate.

---

## Deliverables

### D1: Foundation — tokens + primitives + shell port (week 1)

**Goal:** Get the visual base of P6 reproducible in React. No tab content yet — just the chrome.

**Sub-deliverables:**
- **D1.1** Extend `dashboard-v3/src/design/tokens.ts` with the P6 light theme (off-white surfaces `#f3f4f8`, dark slate text, accent `#1976d2`, status colors that read on light, pastel mood gradients per tab)
- **D1.2** Port the **per-tab mood gradient system** — body class drives the radial-gradient mesh active per tab. 10 mood gradients (one per tab).
- **D1.3** New `<Knob />` primitive — compact knob card with label + value + interaction (slider/toggle/select). Used by every tab's `.controls-bar`.
- **D1.4** New `<ControlsBar />` primitive — 12-col grid of `<Knob />`s with the left accent edge.
- **D1.5** Port the **Shell** (rail + mobile tabs + status bar + viewport handling). Rail active indicator: 4px accent bar on the left edge of active nav item.
- **D1.6** Port the **status-hero card variant** — name eyebrow → bold large status-colored value → context sub. New component variant, not the default; opt-in per card.
- **D1.7** Fix the memoization regression flagged in the v2 critique (broken `useMemo` deps). Profile before/after with React DevTools to confirm the fix.

### Acceptance Criteria D1
- **Verify:** open `dashboard-v3/` dev server; rail + tabs render with P6 light styling (off-white surface, accent bars, leading icons, pill buttons)
- **Verify:** mood gradient changes per active tab — pulse-check Home (blue+violet) vs Energy (amber+orange) vs Presence (green+pink)
- **Verify:** `<Knob />` + `<ControlsBar />` render in Storybook or a temporary `/dev` route with at least 3 example knob types (slider, toggle, select)
- **Verify:** status-hero card variant renders correctly when given props for a "person away" example — bold yellow status text, name eyebrow, context sub
- **Verify:** lazy-tab works — switching tab doesn't re-render the prior tab's content; visited refs persist
- **Test:** React DevTools profiler shows no unnecessary re-renders on tab switch (memoization fix verified)
- **Live:** `npm run build` produces a clean `dist/` with no TypeScript errors

### LoC budget D1
~600 LoC new + ~150 LoC tokens.ts extension + ~80 LoC global.css extension. ~4-5 days.

---

### D2: Sensor gap audit + URA mini-cycles (week 1, parallel to D1)

**Goal:** Surface and close the sensor gaps the prototypes assume exist before they bite during tab rebuilds.

**Sub-deliverables (PYTHON cycles inside URA proper, not React work):**
- **D2.1** Audit every "live value" referenced in P6 prototype HTML. Categorize: (a) exists today, (b) extension of existing entity (attribute add), (c) needs new sensor.
- **D2.2** Routine awareness confidence — check if existing `sensor.universal_room_automation_<person>_likely_next_room` already exposes a confidence attribute. If not, scope a Tier 1 cycle to add it.
- **D2.3** Decisions-stream — Diagnostics tab shows a recent coordinator decisions feed. Check if any existing event log surfaces this; if not, defer to v5.1 (Diagnostics tab launches with what's available; rich decisions feed added later).
- **D2.4** Safety detector summary — Safety coordinator likely exposes individual detector entities. Build an aggregator sensor surfacing per-detector status grid if needed. Tier 1 URA Python cycle.

### Acceptance Criteria D2
- **Verify:** sensor-gap audit doc filed at `docs/planning/DASHBOARD_v4_sensor_audit.md`
- **Verify:** each gap categorized as a/b/c with file:line refs
- **Verify:** any new sensors needed are scoped as Python mini-cycles with their own LoC + test budgets
- **Decide:** which gaps block which tabs — schedule the Python mini-cycles to ship BEFORE the dependent tab rebuild

### LoC budget D2
~0 React LoC; ~150 prod + ~80 test LoC across the Python mini-cycles, sized per gap. ~2-3 days of investigation + initial sensor builds.

---

### D3: Home tab (week 2, smallest tab, ships first)

**Goal:** First fully live-wired tab. Validates the foundation works end-to-end. Smallest scope first to deliver a visible win.

**Sub-deliverables:**
- **D3.1** Top control bar: mode · anomaly floor · battery reserve · scenes · notify toggles (5 knobs, all wired to URA entities)
- **D3.2** People row — 4 person cards using the status-hero variant (Jaya away yellow-bold, Oji home green-bold pattern). `useEntity('sensor.universal_room_automation_<person>_*')`.
- **D3.3** System status cards (1-3 rows depending on prototype): coordinator health, anomaly summary, energy at-a-glance, HVAC at-a-glance
- **D3.4** Mood gradient active (Home = blue+violet pastel)

### Acceptance Criteria D3
- **Verify:** Home tab renders against live URA data; all 5 control knobs adjustable and persist their changes via service calls
- **Verify:** person cards reflect real `previous_location` / `state` / `confidence` values (note: fixes the "previous_location stuck at unknown" issue user flagged 2026-05-18 — that's a Python issue, not a dashboard issue, but the dashboard surfaces the fixed values once the URA fix ships)
- **Verify:** mood gradient applies correctly
- **Verify:** mobile viewport renders without horizontal scroll
- **Live:** dev server demo session with user, confirm before moving to D4

### LoC budget D3
~250 LoC React + ~50 LoC for any tab-specific hooks. ~2-3 days.

---

### D4: Diagnostics tab (week 2, smallest "infrastructure" tab)

**Goal:** Second tab ships. Diagnostics is comparatively static (per-coordinator status + reload buttons) — exercises the rail + status visualization without complex live charts.

**Sub-deliverables:**
- **D4.1** Top knob row: anomaly floor · routine awareness floor · DB maintenance · observation mode (all) · telemetry toggles
- **D4.2** Per-coordinator status grid: name, state (running/degraded/error), uptime, reload button, anomaly ack
- **D4.3** "Alerts" section (folded in from the dropped Alerts tab) — recent system events
- **D4.4** Mood gradient (Diagnostics = red+blue)

### Acceptance Criteria D4
- **Verify:** all 12 coordinator cards render with live state
- **Verify:** reload button per coordinator works via `homeassistant.reload_config_entry` service
- **Verify:** anomaly ack button per row works
- **Live:** clicking reload on a single coordinator should NOT trigger the CM-reload entity-storm pattern (per 2026-05-18 incident) — verify URA exposes a per-coordinator reload service

### LoC budget D4
~280 LoC React + per-coordinator reload service if missing. ~2-3 days.

---

### D5: Energy + HVAC tabs (week 2-3, the data-heavy duo)

**Goal:** Ship the two tabs that surface URA's most-asked features. Both use recharts.

**Sub-deliverables:**
- **D5.1** Energy tab: top knob row + battery+grid+solar flow viz + per-room top-consumers + cost surface (use the v4.6.8-shipped `whole_house_cost_today` + `zone_*_energy_cost_today` sensors)
- **D5.2** HVAC tab: top knob row + per-zone setpoint cards with ± controls + comfort weighting · setback economy · routine influence · severity floor knobs
- **D5.3** HVAC zone cards use status-color for the active mode (cooling=blue, heating=red, idle=neutral)

### Acceptance Criteria D5
- **Verify:** energy flow visualization animates correctly with live numbers (recharts) — solar produced today, grid imported, battery charge/discharge
- **Verify:** HVAC per-zone setpoint adjustment fires real `climate.set_temperature` service calls
- **Verify:** the v4.6.8 cost sensors render correctly (`rate_source: ec_tou`, `rate_used` shown in card detail)
- **Verify:** mood gradients (Energy = amber+orange, HVAC = cool-blue+warm-orange)

### LoC budget D5
~500 LoC React (recharts integration + zone-card variant). ~4-5 days.

---

### D6: Presence + Security + Safety tabs (week 3)

**Goal:** Three coordinator-driven tabs. Safety is the new tab from P4 — requires the D2.4 sensor gap closure first.

**Sub-deliverables:**
- **D6.1** Presence tab: 5 top knobs + 4 person cards (status-hero variant) + per-room music-following toggles + zone occupancy grid
- **D6.2** Security tab: 5 top knobs + arm panel (with 5-sec confirm) + per-lock unlock (with 5-sec confirm) + camera grid + recent events
- **D6.3** Safety tab: 5 top knobs + detector grids (smoke/CO/water/freeze/garage) + recent events timeline + emergency response sequence

### Acceptance Criteria D6
- **Verify:** Presence per-room music-following toggle persists across page reload (entry.options or RestoreEntity backed)
- **Verify:** Security arm/unlock confirm dialogs gate destructive actions
- **Verify:** Safety detector grid renders all detectors with battery + last-test + state
- **Verify:** Safety tab sensor audit (D2.4) findings are in production before this tab ships
- **Verify:** mood gradients (Presence = green+pink, Security = blue+purple, Safety = warm)

### LoC budget D6
~600 LoC React. ~5-6 days.

---

### D7: Spaces + Zones + Rooms tabs (week 3-4)

**Goal:** The three space-hierarchy tabs from the P2 fulcrum. These are the highest-volume tabs (31 rooms in production).

**Sub-deliverables:**
- **D7.1** Spaces (Aggregated) tab — zone-strip filter + rooms-expand-in-place
- **D7.2** Zones tab — per-zone hero cards (Master Suite, Entertainment, Upstairs, Back Hallway, Outside)
- **D7.3** Rooms tab — dense grid of all 31 rooms with per-room controls (light toggle, climate ±1°, "more" → full room)
- **D7.4** Auto-onboard discipline — rooms rendered from a data array (one entity registry query), new URA room added → appears in correct zone on next render

### Acceptance Criteria D7
- **Verify:** Rooms tab renders all 31 rooms at viewport ≥1200px without performance issues (React DevTools profiler: <16ms render time)
- **Verify:** mobile viewport renders rooms as a scrollable single-column list
- **Verify:** adding a new URA room (test by config-flow creation) results in the new room appearing in the right zone on next dashboard load — no code change required
- **Verify:** mood gradients (Spaces/Rooms = green+teal, Zones = same family)

### LoC budget D7
~450 LoC React + entity-registry hook. ~4-5 days.

---

### D8: Polish + perf + accessibility + ship (week 4)

**Goal:** Production hardening. v5.0.0 dashboard release commits the React app + `dist/` into the URA integration as an HA panel.

**Sub-deliverables:**
- **D8.1** Cross-tab perf audit (React DevTools profiler) — no tab renders >16ms in steady state
- **D8.2** Accessibility pass — keyboard nav + ARIA labels + color contrast (WCAG AA on light theme)
- **D8.3** Mobile polish — 480px breakpoint validation across all 10 tabs
- **D8.4** Build artifact integration — `dashboard-v3/dist/` committed to URA repo; served as an HA panel via the integration's setup
- **D8.5** README in `dashboard-v3/` documenting how to build + the panel registration path
- **D8.6** v5.0.0 release notes — dashboard is the headline feature, called out as a major URA milestone

### Acceptance Criteria D8
- **Verify:** all 10 tabs pass perf budget at production data volume (31 rooms, all coordinators live)
- **Verify:** color contrast checker passes WCAG AA for all status colors on light surface
- **Verify:** keyboard-only navigation works across the rail + within each tab
- **Verify:** mobile breakpoint validated on iOS Safari (the user's primary mobile)
- **Verify:** `dist/` committed; HA panel renders the dashboard at `/ura-dashboard` (or similar route)
- **Verify:** v5.0.0 deploys via `./scripts/deploy.sh` with the dashboard build as part of the cycle
- **Live:** user can navigate to the URA panel in HA frontend and use it instead of the v3 dashboard for at least 1 full day before declaring "shipped"

### LoC budget D8
~150 LoC React (polish + panel registration) + integration changes. ~3-5 days.

---

## Out of scope (explicit — DO NOT scope-creep)

- **Background image variants (P5/P7/P9)** — deferred to v5.1+ flavor pass. v5.0 ships P6 styled, no images.
- **Dark theme + Material theme variants (P4/P8)** — deferred to v5.2+ user-toggle feature.
- **New sensor families** beyond what D2 audit identifies — if a tab needs a sensor that doesn't exist + can't be built in a sub-day, that tab launches with the available data + a documented "coming in v5.1" stub.
- **Decisions-stream rich feed** — Diagnostics ships with what's available; rich feed deferred to v5.1.
- **Voice / Assist integration** — out of v4 scope entirely.
- **Multi-user dashboard customization** — URA is single-user (per `feedback_single_user_no_backcompat`); each user's dashboard config doesn't need partitioning.
- **Theme-switcher UI** — v5.0 is light-only. Toggle added in v5.2.

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Sensor gaps discovered mid-port stall a tab | HIGH | D2 sensor audit ships in week 1 ahead of tab rebuilds. Block tab D6.3 (Safety) on D2.4 closure. |
| Memoization regression (v2 critique) means perf is bad on day 1 | MEDIUM | D1.7 explicitly fixes; perf profiled before-after with React DevTools. |
| 4-week estimate slips to 8 weeks | MEDIUM | Hard checkpoints at week 1, 2, 3 — if any slip materially, stop and reassess scope. Cut Safety tab to v5.1 if necessary. |
| Dashboard plan gets ignored because it's not Python | HIGH (user-flagged) | This planning doc + memory entry + integration-of-dashboard-build into URA's `./scripts/deploy.sh` pipeline. Dashboard versions with URA. |
| User loses confidence mid-port | MEDIUM | Ship ONE tab fully live by end of week 2 (D3 Home). Visible wins early. |
| Per-tab background-image deferral becomes "never ships" | LOW | Memoryd as v5.1+ work; not scoped into v5.0 critical path. |

---

## Cost summary

| Deliverable | Days | LoC (prod + style) | LoC (test) | Tier |
|---|---|---|---|---|
| D1 Foundation | 4-5 | ~830 | ~100 | — |
| D2 Sensor audit + Python mini-cycles | 2-3 | ~150 (Python) | ~80 (Python) | 1 |
| D3 Home tab | 2-3 | ~250 | ~50 | — |
| D4 Diagnostics tab | 2-3 | ~280 | ~60 | — |
| D5 Energy + HVAC | 4-5 | ~500 | ~80 | — |
| D6 Presence + Security + Safety | 5-6 | ~600 | ~100 | — |
| D7 Spaces + Zones + Rooms | 4-5 | ~450 | ~80 | — |
| D8 Polish + ship | 3-5 | ~150 | ~50 | — |
| **Total** | **~26-35 days** | **~3,060** | **~600** | 2 (Tier 2 overall, with Tier 1 Python sub-cycles) |

That's 5-7 weeks at full focus, or ~3-4 weeks of focused dashboard-only work with the rest of URA on slow burn.

---

## Versioning + Release

This work ships as **URA v5.0.0** (major version bump from v4.6.x). Per URA's deploy pipeline:
- Each sub-cycle (D1-D8) can be its own minor release (v4.7.0, v4.7.1, ...) building toward the v5.0.0 ship, OR they can all roll into a single v5.0.0
- Recommend the latter — v5.0 = "Dashboard v4 ships" — to make the milestone unmistakable
- `dashboard-v3/dist/` lives in the URA repo and is committed; HA panel registration happens in the integration's Python setup
- Deploy.sh learns to run `npm run build` in `dashboard-v3/` before staging the React `dist/`

---

## Open questions before D1 starts

1. **HA panel registration path** — does URA already register an HA frontend panel for the v3 dashboard? If yes, the registration code already exists and just needs the v4 dist to swap in. If no, this is part of D1.5 or D8.4.
2. **Storybook vs `/dev` route** — for D1.3-D1.6 primitive validation, do we want to bring Storybook into the build, or just expose a `/dev` route in the React app for component previews?
3. **Sensor audit scope** — should D2 be done by me (Claude) or delegated to a focused agent run? Either way, the output is the audit doc.
4. **Cut-line scoring** — if week 3 checkpoint is at risk, which tab gets cut to v5.1 first? Recommend: Safety (because it depends on D2.4 sensor work), then Spaces (because it overlaps with Zones+Rooms).

---

## Recall hint

To pick up this thread: **"Resume URA Dashboard v4"** or **"Resume dashboard work"**

Both route to this planning doc + the `project_dashboard_v4` memory file + the prototypes at `docs/dashboard-prototypes/v4/`.
