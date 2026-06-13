# URA v5.4.2 — Cosmetic: rename + reorder the HVAC pre-conditioning master switch

Pure UX/naming change (no logic). Operator-requested 2026-06-13 to disambiguate the v5.4.0 master toggle from the sub-features it gates.

## What changed
- `switch.ura_hvac_coordinator_hvac_pre_conditioning` display name: **"HVAC Pre-Conditioning" → "28 · HVAC Predictive Conditioning"**.
  - The `28 ·` ordinal prefix slots it into the HVAC Coordinator device's numbered ordering **before** the conditioning sub-features it gates: `28 · HVAC Predictive Conditioning` (master) → `30 · Per-Zone HVAC Control` → `35 · Pre-Arrival Conditioning`.
- Config-flow field label + helper text updated to "HVAC Predictive Conditioning" for consistency.

No entity_id / unique_id / CONF key change (those stay `hvac_pre_conditioning_enabled`), so options state and the switch's persisted toggle are unaffected. The switch remains the master gate over weather pre-cool, pre-heat, solar banking, and pre-arrival.

## Live Validation
- [ ] Device card shows "28 · HVAC Predictive Conditioning", sorted before "30 · Per-Zone HVAC Control" and "35 · Pre-Arrival Conditioning".
- [ ] Switch state preserved across the rename (unique_id unchanged); toggling still gates predictive pre-conditioning.

*Replaced with observed results post-restart.*
