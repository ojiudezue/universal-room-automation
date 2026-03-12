# URA Dashboard v2 Critique

## Executive Summary

The existing dashboard (v2) is a solid foundation with good visual design language and real-time HA entity integration. However, it falls short on the three stated priorities: **compactness**, **unveiling URA's power**, and **actionability**. The dashboard is largely a passive status display with too much vertical space wasted on hero sections and insufficient interactive controls.

---

## What Works Well (Keep These)

1. **Glass morphism design language** -- The dark glass card aesthetic with backdrop-filter blur is visually polished and appropriate for a home automation control panel. The color token system (status-green, status-yellow, etc.) is well-defined.

2. **StatusBadge component** -- The color-mapped badge system with its comprehensive state-to-color mapping (44 states) is a strong pattern. It provides instant visual recognition of entity states.

3. **Tab-based architecture with lazy mounting** -- The `visited` ref pattern that keeps tabs mounted after first visit preserves WebSocket subscriptions and entity state. This is a smart performance optimization.

4. **Security tab confirmation patterns** -- The two-step confirm for unlocking doors and disarming alarms is an excellent safety UX pattern. The 5-second timeout is appropriate.

5. **Room card expand/collapse** -- The expandable room cards with light toggle controls are a good start for actionability.

6. **Entity ID constants (types/entities.ts)** -- Centralizing entity IDs is essential for maintainability and provides a clean contract between the HA backend and the frontend.

7. **Per-tab background images with crossfade** -- Adds visual polish and contextual theming per section.

---

## Critical Issues

### 1. Extreme Vertical Space Waste (Priority: Compact)

Every tab opens with a large "hero section" that consumes 120-160px of vertical space just to display a greeting/title and a single status badge. On mobile, this pushes actual content below the fold.

**Evidence:**
- `hero-section { padding: 32px 16px 24px; }` = ~80px padding alone
- `hero-greeting { font-size: 2rem; }` + `StatusBadge large` + `hero-stats` below = another 80px
- Total: ~160px wasted on "Good Morning" + a badge

**Impact:** On a 667px iPhone screen, after the tab bar (~52px) and hero section (~160px), only ~455px remains for actual content. Nearly 25% of the viewport is consumed by decorative header.

**Recommendation:** Collapse hero to a single 40px inline header row with title, key status badge, and quick stats on the same line.

### 2. Passive Display, Minimal Actionability (Priority: Active)

Of the 7 tabs, only 3 have any interactive controls:
- **Rooms**: Light toggles (good, but hidden behind expand)
- **HVAC**: Two toggle switches (arrester, observation mode)
- **Security**: Lock/unlock, arm/disarm (the best-implemented action UI)

Missing actions across the dashboard:
- **Overview**: No house mode selector, no quick toggles for anything
- **Presence**: No person location override, no music following toggles
- **Energy**: No battery reserve override, no manual load shedding trigger
- **Diagnostics**: Coordinator toggles exist but no ability to reload, restart, or trigger diagnostics

**Impact:** Users can look at things but rarely do things. This makes the dashboard a status board, not a control panel.

### 3. Information Density is Low (Priority: Compact)

Cards use generous padding (24px in `.glass-card`, 16px gap between items) and large font sizes. The information-per-pixel ratio is poor.

**Evidence:**
- GlassCard padding: 24px (compact: 16px)
- Grid gap: 16px everywhere
- Info rows: 6px padding + 0.85rem font = each row occupies ~36px
- Energy tab: 4 stat cards + 3 info cards + 2 constraint cards + chart = user must scroll significantly
- Most cards show 3-5 data points when they could show 8-10

**Recommendation:** Reduce base card padding to 12px, use 8px grid gap, use 0.8rem base font for data rows. Target 50% more data visible per viewport.

---

## Tab-by-Tab Analysis

### Overview Tab

**Strengths:** Greeting adds warmth; quick stats row is useful; person list shows basics.

**Weaknesses:**
- No weather forecast (spec requires it)
- No house mode selector (spec says "Active: mode selector, quick toggles")
- No energy prediction (expected solar, expected excess, expected cost)
- Person list at bottom is the same as Presence tab -- redundant
- Energy summary card duplicates the full Energy tab with less detail
- No coordinator quick-status indicators

**Missing per spec:** Weather, house mode selector, energy prediction, coordinator status chips, quick toggles.

### Presence Tab

**Strengths:** Person cards show entity pictures, source, transitions. BLE and motion sensor lists are comprehensive. Music following section present.

**Weaknesses:**
- No property/guest count (census data from Census v2)
- No sensor fusion summary (what the combined picture looks like)
- Camera "activity" only shows recording/streaming cameras -- should show detection events
- No person location override action
- Music following entries are not toggleable from this view
- Zone occupancy tiles are too large at 90px min-width; could be a compact grid
- BLE devices list shows raw sensor entities, not people-to-room mapping

**Missing per spec:** Guest count, fusion summary, location overrides, camera detection events.

### Rooms Tab

**Strengths:** Floor plan images, expandable cards with light toggles and climate info, health status dots.

**Weaknesses:**
- Room-to-entity matching is fragile (word-matching on entity IDs) -- misses entities with non-standard naming
- Floor plan is a static image with no room overlays or clickable regions
- Room cards collapsed state shows almost nothing (name + light count chip)
- No device counts beyond lights and climate
- No automation trigger status per room
- All rooms on a single grid regardless of floor selection -- floor tabs don't filter

**Missing per spec:** Interactive floor plan overlay, device controls beyond lights, automation health per room clearly visible.

### Energy Tab

**Strengths:** Most data-rich tab. Uses Recharts for solar forecast chart. TOU, solar, battery, grid, and cost tracking cards. Load shedding and HVAC constraint visible.

**Weaknesses:**
- Chart uses **sample data**, not actual solar history -- "will connect to history" note still present
- No energy flow diagram (solar->battery->grid->house visual)
- No battery SoC gauge or charge/discharge rate
- No Solcast forecast vs actual overlay (chart shows random data)
- Grid card duplicates stat cards above (import/export shown twice)
- No battery reserve override action
- No real-time power flow values (current watts, not just daily kWh)

**Missing per spec:** Energy flow diagram, real Solcast data integration, battery reserve override, real-time power metrics.

### HVAC Tab

**Strengths:** Zone cards show temperatures, has toggle controls for arrester and observation mode. Clean layout.

**Weaknesses:**
- No pre-cool/coast/shed mode indication per zone (just "status" badge)
- No comfort scores
- No zone demand visualization
- No HVAC mode control (cannot change between heat/cool/auto)
- No temperature override controls (cannot set target temp)
- Zone cards don't show which thermostat(s) belong to them
- Missing daily outcome sensor data

**Missing per spec:** Mode controls, temperature overrides, comfort scores, zone demand, pre-conditioning status.

### Security Tab

**Strengths:** Best-implemented action tab. Camera categorization (inside/outside/entry), lock cards with confirm-to-unlock, alarm panel with all arm modes. Good stat cards.

**Weaknesses:**
- Camera thumbnails load from entity_picture but may be stale (no refresh mechanism)
- No entry alert history or recent events
- Camera cards don't link to camera streams
- No door/window contact sensor display (only lock entities shown)

**Missing per spec:** Entry alerts, contact sensors, camera stream access.

### Diagnostics Tab

**Strengths:** Coordinator cards with enable/disable toggles, automation health grid with progress bar, anomaly cards, system info.

**Weaknesses:**
- No sensor reliability metrics
- No automation execution stats (last run, success rate)
- No log viewer or recent error display
- Health tiles show only state + last updated time, not detailed breakdown
- Anomaly cards are too generic -- just show entity state with icon

**Missing per spec:** Sensor reliability, execution stats, detailed health breakdown.

---

## Code Quality Issues

### 1. Duplicated Utility Functions

`fmt()` and `fmtNum()` are copy-pasted into OverviewTab, PresenceTab, EnergyTab, HVACTab, and SecurityTab. Should be a single shared module.

### 2. getAllEntities() Memoization Problem

Multiple tabs call `getAllEntities()` on every render, then run `useMemo()` with `allEntities` as the dependency. Since `getAllEntities()` returns a new object reference on every render, the memos effectively never cache -- they recompute every time.

```typescript
// This recalculates every render because allEntities is a new reference each time
const persons = useMemo(() =>
  Object.entries(allEntities).filter(...).map(...),
  [allEntities]  // <-- new reference every render
);
```

This is a significant performance issue when there are hundreds of entities.

### 3. Unsafe Type Assertions

Heavy use of `as never` casts to work around @hakit/core types:
```typescript
callService({
  domain: "light" as never,
  service: "turn_off" as never,
  ...
});
```

This suppresses TypeScript's type checking entirely. Should use a properly typed wrapper.

### 4. Inline Styles Mixed with CSS Classes

The codebase mixes CSS classes (globals.css) with inline `style={{}}` props inconsistently. The `CoordinatorCard`, `EnergyOverview`, and `HVACOverview` components use CSSProperties objects, while tabs use className. This creates maintenance confusion.

### 5. No Loading States

No skeleton screens, spinners, or loading indicators when entities haven't loaded yet. If `getAllEntities()` returns an empty object initially, every tab shows "No data" empty states before data arrives.

### 6. Dead Components

`CoordinatorCard.tsx`, `EnergyOverview.tsx`, `HVACOverview.tsx`, and `PresenceOverview.tsx` appear to be leftover v1 components that are no longer imported by any tab. They reference CSS variables (`--ura-card`, `--ura-accent`, `--ura-text-dim`) that don't exist in globals.css.

### 7. Single Monolithic CSS File

globals.css is 892 lines of flat CSS with no scoping, organization, or CSS module isolation. Class name collisions are likely as the dashboard grows.

---

## Visual Design Assessment

### Strengths
- Consistent dark glass morphism aesthetic
- Good use of color semantics (green=good, red=alert, etc.)
- Per-tab background images add visual variety
- Tab bar is well-designed with pill-style buttons

### Weaknesses
- **Low contrast in secondary text**: `rgba(255,255,255,0.3)` and `rgba(255,255,255,0.4)` used extensively for labels and timestamps. On a glass background with potentially bright background images, these are likely below 4.5:1 contrast ratio.
- **Font sizes too small in places**: `0.62rem` (10px), `0.65rem` (10.4px), `0.68rem` (10.9px), `0.7rem` (11.2px) all violate the 12px minimum body text guideline.
- **No focus rings**: The CSS has no `focus-visible` styles. Keyboard navigation is invisible.
- **!important overrides**: `.tab-active` and `.floor-tab-active` use `!important`, indicating specificity issues.
- **No reduced-motion support**: The `pulse-motion`, `pulse-confirm`, and `pulse-recording` animations have no `prefers-reduced-motion` query.

---

## Performance Concerns

1. **7 background images loaded at mount** -- All tab background images are referenced via CSS `backgroundImage`. While only the active one is visible, browsers may preload or partially load all of them.

2. **All entity subscriptions active simultaneously** -- Once a tab is visited, its `useEntity()` hooks remain active even when hidden. With ~20 explicit entity subscriptions (across 4 hooks) plus the `getAllEntities()` wildcard, this could create significant WebSocket traffic.

3. **No code splitting** -- All 7 tabs and their dependencies are in a single bundle. The `visited` lazy-mount pattern helps with DOM rendering but not bundle size.

4. **Recharts imported for Energy tab only** -- Recharts is a large library (~150KB gzipped) but loaded in the main bundle even when the user never visits the Energy tab.

---

## Summary of Priorities for v3

| Priority | Issue | Impact |
|----------|-------|--------|
| 1 | Remove hero sections, compress card padding | 40% more content visible |
| 2 | Add action controls to every tab | Dashboard becomes a control panel |
| 3 | Add missing features (weather, flow diagram, mode selector) | Spec compliance |
| 4 | Fix getAllEntities() memoization | Major perf improvement |
| 5 | Add loading/skeleton states | Better perceived performance |
| 6 | Improve contrast and accessibility | Readability + compliance |
| 7 | Consolidate duplicated code | Maintainability |
| 8 | Connect real data to charts | Replace sample data |
