# v3.12.4 — Dashboard Performance Optimization

## Problem
Both v2 and v3 dashboards had severe performance issues causing sluggish UI:
- `getAllEntities()` triggered full re-renders on ANY entity state change (~10-50/sec)
- Visited tabs stayed mounted with active WebSocket subscriptions even when hidden
- `useEntitiesByPrefix("sensor.")` scanned 1000+ entities on every render
- Zero `React.memo()` usage — every parent re-render cascaded to all children
- Energy hook subscribed to 19 entities consumed by 3+ tabs simultaneously

## Fixes Applied (Both Dashboards)

### 1. Active-tab-only rendering
Removed `visited` ref pattern. Only the active tab component is mounted. Inactive tabs are unmounted, releasing all WebSocket subscriptions. Reduces active hooks by 5-7x.

### 2. Targeted entity subscriptions
- **v2**: New `useEntitiesByDomain()` and `useEntitiesByPrefix()` hooks with ref-based stable memoization (only returns new reference when filtered subset actually changes)
- **v3**: New `useStableEntitiesByPrefix()` hook with same stability pattern
- Replaced `getAllEntities()` with targeted calls (`sensor.ura_*`, `switch.ura_*`, `light.*`, etc.)
- v3 DetectionLayers: `sensor.*` → `sensor.bermuda` + `sensor.ble_*`
- v3 MusicFollowing: `switch.*` → `switch.ura_music_following`
- v3 AnomalyList: `sensor.*` → `sensor.ura_*`

### 3. Granular energy hooks (v2)
Split `useEnergyData()` (19 entities) into:
- `useEnergyOverview()` — 9 entities for OverviewTab
- `useHvacEnergy()` — 2 entities for HVACTab
- `useEnergyFull()` — 19 entities only for EnergyTab

### 4. React.memo on leaf components
- **v2**: StatusBadge, EntityValue, GlassCard, CoordinatorCard
- **v3**: 30+ components including StatusBadge, GlassCard, RoomCard, FlowNode, PersonCard, CoordinatorChip, ZoneCard, CameraItem, etc.

### 5. useCallback on event handlers
All event handlers passed as props wrapped in `useCallback` (toggleLight, switchTab, expand handlers, service calls)

### 6. Static style extraction
Inline style objects moved to module-level constants for components rendered in loops

### 7. setTimeout leak fixes
SecurityTab (v2), AlarmControls/LockControls/ActionButton (v3) — timeout IDs stored in refs with cleanup on unmount

### 8. Static CSS (v3)
GlobalStyles component's `<style>` tag content moved to importable `global.css` file

## Expected Impact
- ~10-50x reduction in render volume (from eliminating hidden tab subscriptions + targeted entity prefixes)
- Eliminates GC pressure from inline style objects in loops
- Prevents memory leaks from orphaned setTimeout callbacks
