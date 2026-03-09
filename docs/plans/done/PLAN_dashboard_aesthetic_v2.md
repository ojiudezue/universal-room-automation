# Plan: Dashboard Aesthetic V2 — Room Cards, Pop-ups, Transparency

**Date:** 2026-03-02
**Status:** Research complete, not yet implemented
**Prerequisite:** Dashboard Overhaul v1 (deployed 2026-03-02, 8 views)

## Aesthetic References

### 1. polamoros/home-assistant-cards
- **Repo:** https://github.com/polamoros/home-assistant-cards
- Custom `button-card` templates: `room_card`, `room_card_action`, `room_card_action_badge`
- 154px tall room cards with colored circular icon bg, name, state (temp/humidity), vertical action column
- Badge system: green (#22c55e), blue (#3b82f6), orange (#f97316), red (#ef4444)
- Action buttons: 36px circles with 100% border-radius, badge overlays
- Typography: name 19px/600, state 12px/500, sub_state 12px/400
- Card background: `var(--card-background-color)`, actions bg: `var(--primary-background-color)` with 14px radius

### 2. deconstructionalism gist
- **Gist:** https://gist.github.com/deconstructionalism/0e110a14477393d671bbb579006db506
- Full transparency: `rgba(0,0,0,0)` card backgrounds — cards float over view background
- Bubble Card pop-ups for room drill-downs (hash-based: `#batcave`, `#living-room`)
- `room-summary-card` for area-based device grouping with light count badges
- `navbar-card` for navigation, `plotly-graph` for data viz
- Sections layout with `max_columns: 4`, `grid_options: {columns: full, rows: 4}`
- Bubble separator cards with icons as visual dividers

## Proposed Enhancements

### A. Room Cards (replace linear room sections)
Replace 23 full-section room entries in Rooms view with polamoros-style compact room cards:
- Each room = 1 button-card with name, occupied state, temp, humidity, action buttons (lights, climate)
- 4-column grid → all 23 rooms visible without scrolling
- Requires: button-card templates registered as dashboard resources

### B. Bubble Card Pop-ups (drill-down instead of scroll)
- Each room card taps → Bubble Card pop-up with full room detail
- Hash routing: `#kitchen`, `#master-bedroom`, etc.
- Pop-up contains: entities list, automation health, history graph, trigger/action log
- Eliminates the 23-section Rooms view entirely

### C. Full Transparency Layer
- Set view-level `background` to gradient or image
- All cards: `background: rgba(0,0,0,0)` or `rgba(var(--rgb-card-background-color), 0.3)`
- Creates depth/layering effect

### D. Room Summary Cards
- Use `room-summary-card` (HACS) for area-based grouping
- Shows device counts, light states, climate in compact format
- Alternative to button-card room cards if simpler

## Implementation Order
1. Register button-card templates as inline dashboard resource
2. Build room card template adapted for URA entities
3. Replace Rooms view with grid of room cards + bubble pop-ups
4. Apply transparency layer to all views
5. Add room-summary-card as alternative/complement

## Prerequisites
- button-card v7.0.1 (installed)
- card-mod v4.2.1 (installed)
- Bubble Card v3.1.1 (installed)
- room-summary-card (check if installed, may need HACS install)
