# v3.9.5 — Dashboard v2: 7-Tab Glass Morphism Dashboard

## Summary
Complete rewrite of the URA React dashboard with Material Design 3 glass morphism styling, 7 functional tabs, per-tab atmospheric background images, and responsive layout. Includes code review fixes for security, performance, and accessibility.

## Changes

### Dashboard v2 Features
- **7 tabs**: Overview, Presence, Rooms, Energy, HVAC, Security, Diagnostics
- **Glass morphism UI**: Frosted glass cards with backdrop-filter blur over full-bleed background images
- **Per-tab backgrounds**: Curated Unsplash photos that crossfade between tabs
- **Responsive grid**: 1-column mobile, 2-column tablet, 3-4 column desktop
- **Tab caching**: Visited tabs stay mounted (preserves WebSocket subscriptions and scroll position)
- **Touch-first**: Large touch targets, scrollable tab bar, glanceable metrics

### Tab Content
- **Overview**: House state hero, person count, TOU/HVAC/Security quick stats, energy/cost summary, zone status
- **Presence**: Person cards with fusion state + transitions, zone occupancy chips, music following status
- **Rooms**: Ground/second floor plan viewer, light toggles, thermostat readouts
- **Energy**: Cost/import/export metrics, TOU/solar/battery cards, HVAC constraint, load shedding, Recharts forecast chart
- **HVAC**: Mode display, 3 zone cards with temps/presets/status, arrester + observation mode toggles
- **Security**: Armed state with alarm arm/disarm (with confirmation), lock controls (with confirmation), cameras grouped by inside/entry/outside
- **Diagnostics**: 4 coordinator enable/disable toggles, automation health per room, anomaly sensors, system info

### Code Quality (from review)
- PostMessage origin validation for auth security
- Entity data lookups memoized with `useMemo` to prevent render cascades
- Chart sample data memoized to prevent flicker
- Camera grouping uses mutually exclusive categorization
- Disarm/unlock actions require confirmation dialogs
- Tab buttons have proper ARIA labels and roles
- Temperature units not hardcoded (reads from entity attributes)
- Build script pre-cleans old assets to prevent stale file accumulation
- Vite config corrected (`emptyOutDir` instead of typo)

### Build
- Total frontend size: 2.6MB (including 7 background images + 2 floor plans)
- Locale cleanup strips non-English HAKit i18n files
- Recharts added for energy charts (~150KB gzipped)

## Files Changed
- `dashboard/` — Complete React SPA source (new v2)
- `custom_components/universal_room_automation/frontend/` — Built output with backgrounds + floor plans
- `docs/dashboard-tab-requirements.md` — Tab design requirements
