# URA Sensor Remap Worksheet — 2026-06-10

All steps: HA → Settings → Devices & Services → Universal Room Automation
→ [room entry] → Configure. ~10–15 minutes total, 5 rooms.

Source: 2026-06-09 live audit (v5.3.1 `energy_sensors_dead` flags + WARNING
logs + entity sweep). Only 6 persistent dead references exist — the old
"18 renamed SPAN circuits" memo is stale; most self-resolved.

---

## [ ] 1. Garage A  (biggest win — restores EVSE circuit visibility)

Step: **Energy**

- REMOVE  `sensor.span_panel_garage_a_evse_consumed_energy`
- ADD     `sensor.span_panel_car_charger_consumed_energy`

Step: **Devices / Power** (same circuit, power side)

- REMOVE  `sensor.span_panel_garage_a_evse_power`
- ADD     `sensor.span_panel_car_charger_power`

Why: SPAN circuit renamed "Garage A EVSE" → "Car Charger".
Verified exact match — energy counters identical to the decimal.

---

## [ ] 2. Media Room Closet

Step: **Energy**

- REMOVE  `sensor.media_room_closet_energy_today`
  (self-reference — URA's own output sensor inherited a deleted
  source's entity_id; circular, permanently unknown)
- ADD     `sensor.switch_shelly1pmgen3_wifi_mediacloset_energy`

---

## [ ] 3. Jaya Bedroom (Bedroom 4)

Step: **Energy**

- REMOVE  `sensor.seeedstudio_mmwave_kit_047d34_existence_energy`
  (radar "presence energy" % — never was a kWh sensor; device also offline)
- ADD     nothing (no real circuit candidate exists)

---

## [ ] 4. Study B

Step: **Sensors** (illuminance)

- REMOVE  `sensor.mmwave_lux_wifi_esphome_studyb_ambient_light`
- ADD     `sensor.mmwave_lux_wifi_esphome_studyb_veml7700_ambient_light`

Why: ESPHome firmware rename; device alive (reads ~0.57 lx).

---

## [ ] 5. Game Room

Step: **Devices**

- REMOVE (or leave + fix TV first)  `sensor.game_room_tv_power`

Why: `media_player.tv_samsung_wifi_gameroom` integration is offline —
no candidate until the TV integration is repaired.

---

## Not your problem (FYI only)

- 5 Shelly refs (Guest Bath 1/2, Jaya Bath, Media, Stair Closet) warned at
  boot only — all back online, no action.
- 3 orphaned energy-coordinator DB circuit baselines ('Battery Power',
  'Span Left Subpanel Power', 'Span Left Unknown Power') — internal DB
  cleanup, handled in a future hygiene commit.
- ~130 orphaned `span_panel_none_* / unmapped_tab_*` entities — unavailable,
  unreferenced, cosmetic.

## After you finish

Rooms 1–2 should flip `energy_sensors_dead` → false within a cycle and the
upstairs zone energy should start accruing. Tell Claude "span remap done"
for a live verification pass.
