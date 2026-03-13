# v3.14.3: Grid Import Shows Net Position (Import/Export)

**Date:** 2026-03-13
**Branch:** develop -> main

## Problem

Predicted Grid Import sensor was clamped to `max(0, ...)` — it could never go negative. On a sunny day (150 kWh solar, 31 kWh consumption), it showed 0.0 instead of showing that you're exporting ~108 kWh to the grid.

## Fix

Track grid export (solar surplus after covering consumption + charging battery) and return `import - export`. Negative = net export to grid.

Example: 150 kWh solar, 28 kWh consumption, 40 kWh battery at 30%:
- Daytime: 14 kWh consumed, 136 kWh surplus. Battery absorbs 28 kWh, exports 108 kWh.
- Night: 14 kWh consumed, battery (full at 40 kWh) covers all.
- Net: 0 + 0 - 108 = **-108 kWh** (net export)
