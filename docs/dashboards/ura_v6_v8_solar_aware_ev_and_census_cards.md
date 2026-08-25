# ura-v6 / ura-v8 — Solar-Aware EV panel + House Census card

**Status:** ✅ **APPLIED LIVE 2026-08-24** (both writes `write_committed:true, post_write_verified:true`).
**Ask (operator 2026-08-24):** *"ura v6 and ura v8 need more information from EVSE Solar Aware
charging sensors. Enrich the EVSE panel. Consider aesthetics. ura v8 needs information about census
— property count, interior house count, perimeter count, identified people count and interior path
route and predicted next room."*

Same staging precedent as `ura_v8_energy_ev_detail_card.md`: cards designed against live state,
templates verified with `ha_eval_template` BEFORE applying, applied via `ha_config_set_dashboard`
`python_transform` (never a `.storage` hand-edit). Markdown cards carry an explicit `entity_id:`
watch-list because the templates reach entities through Jinja **variables**, which the markdown
card's literal-id auto-detection would miss (the card would sit stale until an unrelated repaint —
the bug caught on the sibling EV detail card).

## What was applied

| Dashboard | View / section | Card |
|---|---|---|
| `ura-v8` | `views[2]` (Energy & EV) `sections[8]` — appended | ☀️ Solar-Aware EV Charging |
| `ura-v8` | `views[3]` (People) — **new section inserted at index 0** | 👥 House Census |
| `ura-v6` | `views[1]` (Energy) `sections[6]` (EV Control) — appended | ☀️ Solar-Aware EV Charging |

v6 already has its own Presence tab; per the operator's ask, census was added to v8 only.

## Card 1 — ☀️ Solar-Aware EV Charging (v6 + v8, identical)

Narrative-first, conditional-render style (matches the EV detail card design rationale). Surfaces
the *currently-shipped* solar-aware charging signals:

- excess-solar active + which EVSEs (`ev_charging_status.excess_solar_active` / `excess_solar_evses`)
- solar now + today's class + remaining kWh + tomorrow's class (`battery_strategy.solar_production`,
  `.solar_day_class`, `.tomorrow_solar_class`, `solar_day_class.forecast_remaining_kwh`)
- battery SOC + reserve floor (`battery_strategy.soc` / `.reserve_soc`)
- off-peak drain target (`battery_strategy.current_offpeak_drain_target`) — what DP will drain toward
- fill-priority hold target + whether solar is OK yet (`.fill_priority_target_soc` /
  `.fill_priority_solar_ok`)
- battery/arbitrage phase for context (`.arbitrage_phase`)

**Watch-list:** `sensor.ura_energy_coordinator_ev_charging_status`,
`sensor.ura_energy_coordinator_battery_strategy`, `sensor.ura_energy_coordinator_solar_day_class`.

**NOTE — future enrichment:** the new solar-follow **amp-modulation** telemetry
(`solar_follow_surplus_kw`, `solar_follow_state`, per-EVSE `solar_follow_original_amps`,
`solar_follow_blind_since`) does NOT exist yet — that cycle (`EVSE-SOLAR-FOLLOW-AMPS-1`) is not
shipped. When it ships, add those four attributes to this card (they live on
`sensor.ura_energy_coordinator_ev_charging_status`).

## Card 2 — 👥 House Census (v8 People tab, top section)

Counts row (all from `total_persons_on_property` attributes — one authoritative producer, avoids the
per-camera double-count):

- 🏠 Inside (`inside_count`) · 🌳 Perimeter (`outside_count`) · 👤 On property (state)
- ✅ Identified (`identified_total`) · ❓ Unidentified (`unidentified_total`) · 🎯 Confidence
  (`census_confidence`)

Per-person "Where & where next": each identified person's current room (`occupant_count`
`persons_locations`), predicted next room (`<person>_likely_next_room`), per-person accuracy
(`house_next_room_accuracy` `per_person_accuracy`), and a compact interior path trail (last 4 rooms
of `<person>_current_path` `recent_path`, reversed to read oldest→now).

**Watch-list:** `total_persons_on_property`, `occupant_count`, `census_confidence`,
`house_next_room_accuracy`, and per-person `_likely_next_room` + `_current_path` for
ezinne / oji_udezue / jaya / ziri.

## Verified render at apply time (2026-08-24, 3 people home)

Census: Inside 3 · Perimeter 0 · On property 3 · Identified 3 · Unidentified 0 · Confidence Medium;
per-person e.g. `Oji Udezue · Master Bedroom → Receiving Room · 23% acc / ↳ Master Bathroom →
Master Bedroom → Study B → Master Bedroom`. Solar-Aware EV: `○ No excess-solar charging` · Solar
0.6 kW Excellent · Battery 72% reserve 10% · drain target 10% · hold EV until 80% ⏳ solar not yet OK
· phase Discharge.

## Acceptance criteria (live)

- **Verify:** both cards render without template error on their tabs (confirmed: `post_write_verified`).
- **Verify:** the EVSE card grows the ⚡/☀️ lines only when `excess_solar_active` is true.
- **Verify:** the census card re-renders on state change (explicit `entity_id:` watch-list present).
- **Live (organic):** on a sunny midday with an EV plugged, the EVSE card shows "Charging on surplus";
  when solar-follow ships, the amp-modulation attributes are added.
