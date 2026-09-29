# AUDIT — URA v8 dashboard (`/ura-v8`), 2026-09-28

**Type:** read-only audit. Nothing on HA, in the dashboard, or in code was changed.
**Snapshot:** live HA ~22:40–22:50 CDT 2026-09-28 (house in `sleep`, no sun). Dashboard config hash from
`ha_config_get_dashboard(url_path="ura-v8")`, 7 views: Now, Residence, Energy & EV, People, Security, Climate, Health.
**Method:** every entity id in the config was extracted by regex (955 unique) and checked against
`.storage/core.entity_registry` (Samba mount) and live state. Ground truth from the HA recorder
(`ssh ha` → `/config/home-assistant_v2.db`, read-only) and the URA DB `energy_daily` table.
HVAC mechanics were checked against `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (read in full) and the
code at the cited lines. Every entity id below was confirmed to exist (registry + live state) unless marked MISSING.
All proposed Jinja was test-rendered against the live instance with `ha_eval_template`.

Installed custom cards (HACS, verified): button-card 7.0.1, mushroom 5.2.3, auto-entities 1.16.1, apexcharts-card 2.2.3,
mini-graph-card 0.13.0, bubble-card 3.4.1, power-flow-card-plus 0.3.7, card-mod 4.2.1, layout-card, stack-in-card,
vertical-stack-in-card, status-card, navbar-card, plotly, sankey, Advanced Camera Card, and others. Every card below uses
only core cards or these.

---

## 0. Headline findings

1. **Now → "Net Energy" is garbage, and the cause is upstream.** It shows
   `sensor.ura_energy_coordinator_energy_forecast_today` = **−73.7 kWh**. That is Solcast (126.3) minus a predicted
   consumption that swung **55 → 500 kWh within today alone** (recorder, 13 samples) and **1,234 / 2,003 / 2,274 kWh** on
   earlier days. Real use is about **185–225 kWh/day** (URA `energy_daily`, Aug–Sep). Root cause: the Envoy
   `sensor.envoy_482543015950_energy_production_today` sometimes reports the **lifetime** counter (~18,000 kWh) instead
   of today's total. Those days are stored in `energy_daily.consumption_kwh` (14,646 / 15,583 / 15,897 kWh on 08-20,
   08-28 and 08-30) and then averaged into the day-of-week history (`energy_forecast.py:312-350`). It is also shown
   with the opposite sign to "Net Tomorrow" on the Energy tab.
2. **Now → "Cost Today" shows $0.11. The real cost so far is $3.71–3.77.** The tile uses
   `sensor.universal_room_automation_predicted_cost_today`: confidence 0, "collecting", based on 0.8 kWh of predicted
   grid use. The measured value is `sensor.ura_energy_coordinator_energy_cost_today` (**$3.71**), with 42.5 kWh imported
   so far.
3. **"House Draw" (Now, Energy, Residence hero) silently reads 0 when the Envoy drops out.** Today the Envoy production
   feed was unavailable **54 %** of the time and stuck at `0.0` for **6.6 daylight hours**. `net_consumption` was
   unknown **68 %** of the time. The card code turns any missing value into 0, so the number looks valid while it is
   wrong. The SPAN mains total is available 87 % of the time, and URA's own energy code already uses it as house load
   (`energy.py:4368-4375`).
4. **Security → "All egress windows and exterior doors closed" is false confidence.** 20 of the 26 listed window
   sensors are not reporting. Two door contact ids are dead (renamed), and one of them, the Garage A door, is **open
   right now** (`binary_sensor.openclose_zigbee_garageadoor1_contact` = on).
5. **The Climate tab has no zone timers, but the data exists.** Since v5.103.20 each
   `sensor.ura_hvac_coordinator_zone_{1,2,3}_status` carries `hvac_release_at`, `hvac_empty_since` and
   `pending_arm_rooms`. Each per-room `binary_sensor.<room>_<room>_hvac_occupied` carries `release_at`,
   `hvac_vacancy_hold_s` and `rule`. A ready-to-paste zone-timer card (test-rendered live) is in §2.1.

Live anomalies to look at (not dashboard bugs):
- `alarm_control_panel.elkm1_area_1` has been **`triggered`** since 19:22:49, which is HA restart time. The Security
  tile will show "Triggered".
- `binary_sensor.ura_energy_coordinator_ec_sub_switches_synced` = off (`mismatch_alert: true`).

---

## 1. Bugs — wrong or dead data (prioritized)

### P0 — wrong numbers shown as fact

| # | Tab / card | Entity | Live value | Ground truth | What is wrong |
|---|---|---|---|---|---|
| B1 | Now → Today's Outlook → "Cost Today" | `sensor.universal_room_automation_predicted_cost_today` | **$0.11** (`raw_net_kwh` 0.8, `confidence` 0, "collecting") | `sensor.ura_energy_coordinator_energy_cost_today` = **$3.71**; `energy_import_today` = 42.5 kWh | Wrong entity: a broken prediction (`aggregation.py:2154+`, similar-days net) instead of the measured cost |
| B2 | Now → "Net Energy" | `sensor.ura_energy_coordinator_energy_forecast_today` | **−73.7 kWh** | Real use 185–225 kWh/day; production ~95–116 kWh/day | Poisoned producer (see §0.1). Also a sign clash: this sensor is **positive = export** (`energy_forecast.py:246`), while "Net Tomorrow" on the Energy tab reads `raw_net_kwh` as **positive = import** (`aggregation.py:2174-2182`). No sign or unit hint on the tile |
| B3 | Now → "Solar Forecast" | `sensor.solcast_pv_forecast_forecast_today` | 126.3 kWh (all day, including at night) | Measured production (daily delta of the Envoy counter): 09-22 116, 09-23 86, 09-24 94, 09-25 94, 09-26 109, 09-27 96, 09-28 105 kWh vs Solcast 131/117/123/130/118/122/126 → **Solcast runs ~20 % high** (actual/forecast mean ≈ 0.81) | Right entity, but it shows the whole-day total at 10 pm with no "left today" and no bias note. `sensor.ura_energy_coordinator_solar_day_class` attr `forecast_remaining_kwh` (0.0 now) is the better "what's left" figure |
| B4 | Now + Energy → "House Draw" hero; Residence hero label `⚡ … kW` | JS: `envoy_…_current_power_production + envoy_…_current_battery_discharge + ura_energy_coordinator_net_consumption` | 8.0 kW now; unavailable→0 fallback | SPAN `sensor.span_panel_current_power` + `_2` = 8.1–8.5 kW now; at 18:43 the formula gave 9.1 kW vs SPAN 11.4 kW | Inputs unavailable 54–68 % of today and `v()` turns them into 0 without saying so. The label also says "solar 0.0" at noon while the feed is stuck. Use SPAN for the headline number and show the Envoy split only when it is live (YAML §2.4) |
| B5 | Energy → "Solar Now" hero | `sensor.envoy_482543015950_current_power_production` | `Number('unavailable')` → **"NaN kW"** | — | No guard |
| B6 | Energy → "Battery SOC" hero | `sensor.envoy_482543015950_battery` | shows "unavailable%" when the Envoy flaps | `sensor.ura_energy_coordinator_battery_strategy` attr `soc` stays numeric (`soc_source: envoy`) | Use the EC value, which holds the last good reading |
| B7 | Energy → "Solar & Consumption (24h)" graph | `sensor.envoy_482543015950_current_power_consumption` | **unavailable** (no data today) | SPAN mains | The consumption line is dead. Replace with a SPAN stacked series (§2.4) |
| B8 | Security → Openings & Egress (markdown + entity-filter) | `binary_sensor.openclose_zigbee_garageadoor_contact`, `binary_sensor.openclose_zigbee_balcony_contact` | **MISSING** (not in registry) | Renamed to `binary_sensor.openclose_zigbee_garageadoor1_contact` (**on = open now**) and `binary_sensor.openclose_zigbee_balcony2_contact` (off) | Dead ids, so an open door reads as "all closed" |
| B9 | Security → Openings & Egress | 26 `binary_sensor.*_egress_window_open` | **20 of 26 unavailable** | — | The "All … closed" sentence counts only `on` and ignores 20 silent sensors. Show "N not reporting" (§2.6). Also remove `binary_sensor.doorlock_kwikset_zwave_frontentry_current_status_of_the_door` (unavailable) and use `lock.doorlock_kwikset_zwave_frontentry` (also unavailable: the Z-Wave lock is offline) |

### P1 — dead references / misleading labels

| # | Where | Problem | Fix |
|---|---|---|---|
| B10 | Residence → 27 `room_card` tiles (`variables.co`) + room pop-ups | `sensor.<room>_current_occupants` **MISSING** for 27 rooms. The real id is `sensor.<room>_identified_people` (26 rooms); Study A is `sensor.studya_room_device_current_occupants`. Cards fall back to "Occupied/Empty" and never show who is there | Rename: av_closet, breakfast_nook, butler_pantry, exercise_room_closet, exercise_room, game_room, garage_a, garage_b, garage_hallway, guest_bedroom_1_closet, guest_bedroom_1, jaya_bathroom, jaya_bedroom_bedroom_4, kitchen, kitchen_hallway_garage, kitchen_pantry, laundry, master_bathroom, master_toilet_master_toilet, media_room_closet, media_room, oji_vanity, receiving_room, study_a_closet, ziri_bathroom, ziri_bedroom_bedroom_5 → `sensor.<same>_identified_people`; study_a → `sensor.studya_room_device_current_occupants` |
| B11 | Now → "Occupied Now" (auto-entities `binary_sensor.*_occupied`) | The wildcard also matches the 43 `*_hvac_occupied` diagnostics and `binary_sensor.ura_presence_coordinator_house_occupied`: **11 rows for 4 occupied rooms** right now (verified live) | Add excludes (§3 snippet) |
| B12 | Residence → AV Closet pop-up | `switch.switch_shelly1pmgen3_wifi_avcloset` **MISSING**; the device was replaced by `switch.av_closet_shelly1pmminig4_avcloset` | Swap the id. The CLAUDE.md troubleshooting example still names the old id |
| B13 | Residence pop-ups | **183 references to integration-disabled entities** (`*_energy_saving_active`, `*_hvac_cooling/_heating`, `*_fan_should_run`, `*_fans_on`, `*_lights_on`, 2 `zone_outside_*`) | auto-entities drops them, so nothing breaks, but they are noise. Delete them from the includes |
| B14 | Climate → "Compliance" tile | `sensor.ura_hvac_coordinator_hvac_compliance` = 2 is **overrides today**, not a rate (`sensor.py:12447-12448`) | Rename to "Overrides today" or drop it (it duplicates `hvac_override_frequency`) |
| B15 | Energy → "Predicted Bill" tile | `sensor.ura_energy_coordinator_predicted_bill` = unknown ("Learning (5 days)", `utility_kwh` 0) | Hide until numeric (visibility condition, §2.4) |
| B16 | Health → "Bayesian Accuracy" | `sensor.ura_coordinator_manager_bayesian_prediction_accuracy` = 0.0856 (a fraction, no unit) | Show as % in a markdown/template, or drop |
| B17 | Energy → "Forecast Consumption" tile | `sensor.ura_energy_coordinator_forecasted_consumption` = 200.0 (poisoned producer, B2) | Remove until the producer is fixed |
| B18 | Energy → "Force Charge 30m" | Same button appears twice (EV Detail + Energy Controls) | Keep one |

### Upstream producer defects surfaced by this audit (code, not dashboard — needs cards)

- **Envoy "today" counter reports lifetime values → poisoned daily history.** `energy_daily` rows 08-20, 08-28 and 08-30
  have `solar_production_kwh` 14,554 / 15,537 / 15,787 and `consumption_kwh` 14,646 / 15,583 / 15,897. The 09-24 and
  09-25 rows have `solar_production_kwh = 0.0`. These feed `restore_consumption_history` / `record_actual_consumption`
  (`energy_forecast.py:736-774`, `energy.py:2264-2272, 2840`). Everything built on it is affected:
  `energy_forecast_today`, `forecasted_consumption`, `forecasted_energy_import` (37.7), `forecast_accuracy` (33.2 %,
  status stale).
- **Possible second effect (from reading the code; its effect on decisions is not verified):** drain precedence builds
  `house_load_kw` as `max(live SPAN, predicted_consumption_kwh / 24)` under the default `max_span_r1`
  (`energy.py:4377-4394`). A poisoned 2,274 kWh prediction gives a 95 kW "house load". That would shrink the drain-time
  estimate (`energy_drain_precedence.py:678`). Measure it before carding it as a bug.
- `sensor.universal_room_automation_whole_house_cost_today` = **$1,153.61** and `whole_house_power` = unknown (its only
  source is the dead Envoy consumption feed). Neither is on v8. **Do not add them.**
- `sensor.universal_room_automation_predicted_energy_today` / `predicted_cost_today` (0.8 kWh / $0.11 vs 43 kWh / $3.77
  actual): the similar-days predictor is not usable yet.

---

## 2. Additions per tab (ready to paste)

All snippets are sections-view `grid` sections. The Jinja in each was test-rendered against live HA on 2026-09-28.

### 2.1 Climate — zone timers (the operator's main ask)

**Mechanics this card follows** (state-of-play §3.1–3.2, code `hvac_zones.py:1025-1133`, `:1910-1931`, `hvac.py:2460-2465`):
- A room is **HVAC-occupied** from its own evidence clock. In `home_day`/`home_evening` the room is released at last
  evidence + a hold that depends on room type (closet 60 s, generic/utility/media/garage 120 s, bath/common 180 s,
  bedroom 240 s, hallway 0). In `sleep`/`waking` the night hold applies (bedroom/media 30 min … closet 5 min).
- The **zone frees** at `hvac_release_at`, the latest release across its rooms. It is `null` while any room still has
  live evidence.
- The **zone goes Away** at release + vacancy delay: knob 48 `number.ura_hvac_coordinator_48_zone_vacancy_delay_minutes`
  (5), or knob 49 `…_49_zone_vacancy_delay_energy_saving_minutes` (5) when the HVAC energy mode is `coast`/`shed`. The
  exit run fires at release + delay + 2 s. The Away write still needs the zone to be "established"
  (`conditioning_retreat_ok`), so the card says "Away ~" and not "Away at".
- **Entry wait** (D5): after an Away write, a new room arms only after knob 47
  `number.ura_hvac_coordinator_zone_entry_dwell` (1 min) of steady evidence. Rooms waiting are in `pending_arm_rooms`.
  A room that comes back within the return window (knob 52 `number.ura_hvac_coordinator_52_return_window_min`, 10) arms
  at once.

```yaml
type: grid
column_span: 2
cards:
  - type: heading
    heading: Zone Timers
    icon: mdi:timer-outline
  - type: markdown
    entity_id:
      - sensor.ura_hvac_coordinator_zone_1_status
      - sensor.ura_hvac_coordinator_zone_2_status
      - sensor.ura_hvac_coordinator_zone_3_status
      - sensor.ura_hvac_coordinator_hvac_zone_preset_zone_1
      - sensor.ura_hvac_coordinator_hvac_zone_preset_zone_2
      - sensor.ura_hvac_coordinator_hvac_zone_preset_zone_3
      - sensor.ura_hvac_coordinator_governed_thermostat_borrows
    content: >-
      {% set zones = [('zone_1','Main + Master'),('zone_2','Upstairs'),('zone_3','Back Hall')] %}
      {% set em = state_attr('sensor.ura_hvac_coordinator_mode','energy_constraint_mode') %}
      {% set g = (states('number.ura_hvac_coordinator_49_zone_vacancy_delay_energy_saving_minutes')
                  if em in ['coast','shed']
                  else states('number.ura_hvac_coordinator_48_zone_vacancy_delay_minutes')) | float(5) %}
      {% set bw = state_attr('sensor.ura_hvac_coordinator_governed_thermostat_borrows','active_borrows') or [] %}
      {% set kn = {'nudge':'AC nudge','compromise':'Halfway hold','banking':'Pre-cool','preheat':'Pre-heat','egress_pause':'Window pause'} %}
      {% for zid, name in zones %}
      {% set s = 'sensor.ura_hvac_coordinator_' ~ zid ~ '_status' %}
      {% set occ = state_attr(s,'any_room_hvac_occupied') %}
      {% set rel = state_attr(s,'hvac_release_at') %}
      {% set empty = state_attr(s,'hvac_empty_since') %}
      {% set pend = state_attr(s,'pending_arm_rooms') or [] %}
      **{{ name }}** · {{ states('sensor.ura_hvac_coordinator_hvac_zone_preset_' ~ zid) | replace('_',' ') | title }}
      · {{ state_attr(s,'current_temperature') }}° → {{ state_attr(s,'target_temp_low') }}–{{ state_attr(s,'target_temp_high') }}°

      {% if pend %}⏳ Entry wait: {{ pend | join(', ') }}
      {% elif occ and not rel %}🟢 In use
      {% elif occ and rel %}{% set r = as_datetime(rel) %}{% set a = r + timedelta(minutes=g) %}🟡 Frees {{ as_local(r).strftime('%-I:%M') }} · Away ~{{ as_local(a).strftime('%-I:%M %p') }} ({{ ((a - now()).total_seconds()/60) | round(0) | int }} min)
      {% elif empty %}{% set a = as_datetime(empty) + timedelta(minutes=g) %}{% if a > now() %}🟠 Empty · Away in {{ ((a - now()).total_seconds()/60) | round(0) | int }} min{% else %}⚪ Empty since {{ as_local(as_datetime(empty)).strftime('%-I:%M %p') }}{% endif %}
      {% else %}⚪ Empty{% endif %}
      {% for x in bw if x.zone == zid %} · 🔁 {{ kn.get(x.kind, x.kind) }} until {{ as_local(as_datetime(x.expires_at)).strftime('%-I:%M %p') }}{% endfor %}

      {% endfor %}
      _Away delay {{ g | int }} min · entry wait {{ states('number.ura_hvac_coordinator_zone_entry_dwell') }} min · return window {{ states('number.ura_hvac_coordinator_52_return_window_min') }} min_
```
Live render (22:47): *Main + Master · Sleep · 77° → 70–75° / 🟢 In use · Upstairs · Manual · 78° → 68–71° / 🟢 In use ·
🔁 Pre-cool until 12:04 AM · Back Hall · Away · 78° → 66–80° / ⚪ Empty since 10:32 PM.* This also explains the
Upstairs "Manual": it is a live S12 pre-cool borrow, not a human change.

Markdown re-renders on referenced state changes and once a minute (`now()`), so the countdown has 1-minute resolution.
A seconds-level countdown would need button-card JS with `triggers_update: all`. It isn't worth the cost.

**Per-room HVAC holds** (which room is keeping a zone on, and until when):

```yaml
type: grid
column_span: 2
cards:
  - type: heading
    heading: Rooms Holding HVAC
    icon: mdi:home-thermometer
  - type: custom:auto-entities
    show_empty: false
    sort:
      method: friendly_name
    card:
      type: entities
      state_color: true
    filter:
      include:
        - entity_id: binary_sensor.*_hvac_occupied
          state: 'on'
          options:
            secondary_info: last-changed
      exclude:
        - entity_id: binary_sensor.*hallway*
```
(Each row's attributes `rule`, `hvac_vacancy_hold_s`, `release_at`, `source` = `evidence`/`held`/`pending` open in the
more-info dialog. Hallways are always off by design, which is why they are excluded.)

**Fast response stats** (all attrs verified on `sensor.ura_hvac_coordinator_mode`):

```yaml
type: markdown
content: >-
  {% set m = 'sensor.ura_hvac_coordinator_mode' %}
  **Quick response** {{ 'on' if is_state('switch.ura_hvac_coordinator_31_fast_room_response','on') else 'off' }}
  · {{ state_attr(m,'fast_entry_runs_today') }} in / {{ state_attr(m,'fast_exit_runs_today') }} out today
  · {{ (state_attr(m,'transit_filtered_today') or {}).values() | sum }} walk-throughs ignored
  · {{ (state_attr(m,'quick_returns_today') or {}).values() | sum }} quick returns
```
(`transit_filtered_today` and `quick_returns_today` are per-zone dicts, e.g. `{'zone_3': 3}`, so they are summed.
Test-rendered live: "6 in / 4 out · 0 walk-throughs · 3 quick returns".)

**No entity exists for:** a per-zone "away due at" value. The helper `zone_away_due_at()` exists
(`hvac_zones.py:1925-1931`) but is not published as an attribute. The card computes it from `hvac_release_at` + knob.
Adding `hvac_away_due_at` to the zone-status attrs (`hvac_zones.py:1046`) would remove the card-side math.

### 2.2 Climate — arrester

Available (verified live): `switch.ura_hvac_coordinator_override_arrester` (on);
`sensor.ura_hvac_coordinator_override_arrester_state` (`idle|grace_period|compromise|active|disabled`, attrs `zones{state,
overrides_today, last_direction}`, `immune_persons_configured`, `immune_holds_active{zone:{user, started_ts}}`,
`temp_arrester_override_active`, `temp_arrester_override_suppressed_since`); `sensor.ura_hvac_coordinator_hvac_arrester_status`
(`overrides_today`, `overrides_compromised_today`, `planned_action`); `switch.ura_hvac_coordinator_temp_arrester_override`
(attr `suppressed_since`; 6 h cap per state-of-play §7).

```yaml
type: grid
cards:
  - type: heading
    heading: Manual Changes
    icon: mdi:hand-back-left
  - type: markdown
    entity_id:
      - sensor.ura_hvac_coordinator_override_arrester_state
      - sensor.ura_hvac_coordinator_hvac_arrester_status
      - switch.ura_hvac_coordinator_temp_arrester_override
      - switch.ura_hvac_coordinator_override_arrester
    content: >-
      {% set a = 'sensor.ura_hvac_coordinator_override_arrester_state' %}
      {% set st = 'sensor.ura_hvac_coordinator_hvac_arrester_status' %}
      {% set tao = 'switch.ura_hvac_coordinator_temp_arrester_override' %}
      {% set lbl = {'idle':'Watching','grace_period':'Waiting','compromise':'Meeting halfway','override_active':'Change seen','active':'Change seen','disabled':'Off'} %}
      **Guard** {{ 'on' if is_state('switch.ura_hvac_coordinator_override_arrester','on') else 'off (log only)' }}
      · {{ lbl.get(states(a), states(a)) }} · {{ state_attr(st,'overrides_today') }} changes today
      ({{ state_attr(st,'overrides_compromised_today') }} met halfway)

      {% if is_state(tao,'on') %}{% set t0 = as_datetime(state_attr(tao,'suppressed_since')) %}🔓 **Manual changes stick** until ~{{ as_local(t0 + timedelta(hours=6)).strftime('%-I:%M %p') if t0 else '6 h' }}{% endif %}

      {% set ih = state_attr(a,'immune_holds_active') or {} %}
      {% if ih %}{% for z, h in ih.items() %}🛡️ {{ h.get('user') }} holding {{ z }}
      {% endfor %}{% else %}No protected holds{% endif %}

      {% for zn, z in (state_attr(a,'zones') or {}).items() %}- **{{ zn }}** — {{ lbl.get(z.get('state'), z.get('state')) }} · {{ z.get('overrides_today') }} today{% if z.get('last_direction') %} · last {{ z.get('last_direction') }}{% endif %}
      {% endfor %}
  - type: tile
    entity: switch.ura_hvac_coordinator_temp_arrester_override
    name: Keep my changes
    features:
      - type: toggle
```
(Use `.get()` on the zone dicts. Plain `z.last_direction` fails under strict templates when the key is missing.)

**No entity exists for:**
- **Grace / compromise time left.** The timers live in `_grace_timers` (set at `hvac_override.py:2319`, `:3608`,
  `:3675`) and `_compromise_timers`. Only the state name is published (`get_arrester_detail`, `hvac_override.py:7114-7131`).
  The durations are fixed (severe 2 min → revert; normal 5 min → compromise, capped at 15 min, `hvac_const.py:365-368,
  595-596`), but the fire time is not exposed. Closest fix: stamp `grace_until` / `compromise_until` per zone inside
  `get_arrester_detail`.
- **Recent detections list (time, delta, zone).** It exists only as `ura_activity_log` `override_detected` rows and the
  in-memory `last_detection_for()` (`hvac_override.py:3561`). The dashboard can show only counts and `last_direction`.

### 2.3 Climate — knobs the operator tunes by watching

```yaml
type: grid
cards:
  - type: heading
    heading: Zone Timing
    icon: mdi:tune-vertical
  - type: tile
    entity: number.ura_hvac_coordinator_48_zone_vacancy_delay_minutes
    name: Away delay
    features: [{type: numeric-input, style: buttons}]
  - type: tile
    entity: number.ura_hvac_coordinator_zone_entry_dwell
    name: Entry wait
    features: [{type: numeric-input, style: buttons}]
  - type: tile
    entity: number.ura_hvac_coordinator_52_return_window_min
    name: Return window
    features: [{type: numeric-input, style: buttons}]
  - type: tile
    entity: switch.ura_hvac_coordinator_31_fast_room_response
    name: Quick response
```

### 2.4 Energy & Now — corrected energy cards

**Replace the Now "Today's Outlook" tiles (B1–B3):**

```yaml
type: grid
cards:
  - type: heading
    heading: Today
    icon: mdi:calendar-today
  - type: tile
    entity: sensor.ura_energy_coordinator_energy_cost_today
    name: Cost so far
  - type: tile
    entity: sensor.ura_energy_coordinator_energy_import_today
    name: From grid
  - type: markdown
    entity_id:
      - sensor.solcast_pv_forecast_forecast_today
      - sensor.ura_energy_coordinator_solar_day_class
      - sensor.universal_room_automation_predicted_energy_tomorrow
    content: >-
      ☀️ **Solar left** {{ state_attr('sensor.ura_energy_coordinator_solar_day_class','forecast_remaining_kwh') | float(0) | round(0) | int }}
      of {{ states('sensor.solcast_pv_forecast_forecast_today') | float(0) | round(0) | int }} kWh
      <small>(forecast runs ~20 % high)</small>

      🔮 **Tomorrow** ~{{ state_attr('sensor.universal_room_automation_predicted_energy_tomorrow','raw_net_kwh') | float(0) | round(0) | int }} kWh from grid
      · ${{ states('sensor.universal_room_automation_predicted_cost_tomorrow') | float(0) | round(2) }}
  - type: tile
    entity: sensor.ura_presence_coordinator_next_state
    name: Next state
```
Drop "Net Energy" (`energy_forecast_today`) from every tab until the Envoy-today poisoning is fixed and history is
cleaned. When it comes back, label it "Solar minus use" and show the sign in words, not as a bare negative number.

**House Draw hero — SPAN headline, Envoy split only when live (B4). Replace `custom_fields.pv` and `label` on Now and
Energy:**

```yaml
type: custom:button-card
template: hero
entity: sensor.span_panel_current_power
name: House Draw
icon: mdi:home-lightning-bolt
variables:
  color: orange
triggers_update:
  - sensor.span_panel_current_power
  - sensor.span_panel_current_power_2
  - sensor.envoy_482543015950_current_power_production
  - sensor.envoy_482543015950_current_battery_discharge
  - sensor.ura_energy_coordinator_net_consumption
custom_fields:
  pv: >-
    [[[ var w=0,n=0; ['sensor.span_panel_current_power','sensor.span_panel_current_power_2'].forEach(function(e){
      var s=states[e]; if(s && !isNaN(parseFloat(s.state))){ w+=parseFloat(s.state); n++; } });
      return n ? (w/1000).toFixed(1)+' kW' : '—'; ]]]
label: >-
  [[[ function v(e){var s=states[e]; return (s && !isNaN(parseFloat(s.state))) ? parseFloat(s.state) : null;}
    var p=v('sensor.envoy_482543015950_current_power_production'),
        d=v('sensor.envoy_482543015950_current_battery_discharge'),
        n=v('sensor.ura_energy_coordinator_net_consumption');
    if(p===null || d===null || n===null) return 'Solar data offline';
    return 'solar '+p.toFixed(1)+' · batt '+(d>0?'out ':'in ')+Math.abs(d).toFixed(1)+' · grid '+(n<0?'out ':'in ')+Math.abs(n).toFixed(1); ]]]
grid_options:
  columns: full
```
Apply the same SPAN sum to the Residence hero label (`⚡ … kW`).

**Solar Now / Battery SOC guards (B5, B6):**

```yaml
# Solar Now hero
custom_fields:
  pv: "[[[ var x=parseFloat(entity.state); return isNaN(x) ? 'Offline' : x.toFixed(1)+' kW'; ]]]"
# Battery SOC hero — switch entity to the EC strategy sensor
entity: sensor.ura_energy_coordinator_battery_strategy
custom_fields:
  pv: "[[[ var s=entity.attributes.soc; return (s===null||s===undefined) ? '—' : s+'%'; ]]]"
label: "[[[ var a=entity.attributes; return 'floor '+a.reserve_soc+'% · '+(a.arbitrage_phase==='n/a'?'no grid charge':a.arbitrage_phase); ]]]"
```

**24 h graph with a live consumption line (B7), apexcharts-card (installed):**

```yaml
type: custom:apexcharts-card
graph_span: 24h
header:
  show: true
  title: Solar vs House (24h)
apex_config:
  chart: {height: 220}
series:
  - entity: sensor.span_panel_current_power
    name: House R
    type: area
    stack_group: house
    transform: "return x / 1000;"
    unit: kW
    group_by: {func: avg, duration: 10min}
  - entity: sensor.span_panel_current_power_2
    name: House L
    type: area
    stack_group: house
    transform: "return x / 1000;"
    unit: kW
    group_by: {func: avg, duration: 10min}
  - entity: sensor.envoy_482543015950_current_power_production
    name: Solar
    type: line
    unit: kW
    group_by: {func: avg, duration: 10min}
```
Gaps in the solar line then honestly show Envoy outages instead of a flat zero.

**Predicted Bill — hide while learning (B15):**

```yaml
type: tile
entity: sensor.ura_energy_coordinator_predicted_bill
name: Bill forecast
visibility:
  - condition: state
    entity: sensor.ura_energy_coordinator_predicted_bill
    state_not: unknown
```

**EC entities worth adding** (verified live; none are on v8 today):

| Entity | Live | Why |
|---|---|---|
| `sensor.ura_energy_coordinator_tou_period` / `sensor.ura_energy_coordinator_tou_rate` | off_peak / $0.0435 | "What does power cost right now" — the most-asked question, missing |
| `sensor.ura_energy_coordinator_energy_cost_today` / `_this_cycle` | $3.71 / $21.97 | Measured cost (replaces B1) |
| `sensor.ura_energy_coordinator_energy_import_today` / `_export_today` | 42.5 / 0.76 kWh | Measured grid in/out |
| `binary_sensor.ura_energy_coordinator_energy_envoy_available` + `sensor.ura_energy_coordinator_envoy_status` | on / online | Warning chip when solar data is offline (it flaps: 54 % unavailable today) |
| `sensor.ura_energy_coordinator_inclement_state` | none | Storm hold state, useful when it isn't "none" (conditional chip) |
| `binary_sensor.ura_energy_coordinator_ev_charge_onset_gate_open` / `_ev_charge_onset_active_deferred` | off / on | Why the EV hasn't started overnight |
| `switch.ura_energy_coordinator_grid_import_cap`, `switch.ura_energy_coordinator_evse_solar_aware_charging`, `switch.ura_energy_coordinator_battery_aware_ev_charging` | on / on / on | Main controls missing from "Energy Controls" |
| `number.ura_energy_coordinator_fill_priority_soc` (80), `number.ura_energy_coordinator_arbitrage_charge_lead_time` (180), `number.ura_energy_coordinator_off_peak_drain_{excellent,good,moderate,poor,very_poor}` (10/15/20/30/30) | — | The knobs actually turned by hand (memory: lead-time 360→180 was a pure knob turn) |
| `binary_sensor.ura_energy_coordinator_ec_sub_switches_synced` | **off** (`mismatch_alert: true`) | A problem-class sensor currently alarming, with no surface on v8 |

```yaml
type: grid
cards:
  - type: heading
    heading: Right Now
    icon: mdi:cash-clock
    badges:
      - type: entity
        entity: binary_sensor.ura_energy_coordinator_energy_envoy_available
        show_state: true
        visibility:
          - condition: state
            entity: binary_sensor.ura_energy_coordinator_energy_envoy_available
            state: 'off'
      - type: entity
        entity: sensor.ura_energy_coordinator_inclement_state
        show_state: true
        visibility:
          - condition: state
            entity: sensor.ura_energy_coordinator_inclement_state
            state_not: none
  - type: tile
    entity: sensor.ura_energy_coordinator_tou_period
    name: Rate period
  - type: tile
    entity: sensor.ura_energy_coordinator_tou_rate
    name: Rate now
  - type: tile
    entity: sensor.ura_energy_coordinator_energy_cost_today
    name: Cost today
  - type: tile
    entity: sensor.ura_energy_coordinator_energy_export_today
    name: To grid
  - type: entities
    title: Battery Plan
    entities:
      - entity: number.ura_energy_coordinator_fill_priority_soc
        name: EV waits until
      - entity: number.ura_energy_coordinator_arbitrage_charge_lead_time
        name: Charge lead time
      - entity: number.ura_energy_coordinator_off_peak_drain_good
        name: Drain to (good)
      - entity: switch.ura_energy_coordinator_grid_import_cap
        name: Grid cap
      - entity: switch.ura_energy_coordinator_evse_solar_aware_charging
        name: EV on solar
```

### 2.5 People / Presence — useful entities not shown

Verified live:

| Entity | Live | Why add |
|---|---|---|
| `sensor.universal_room_automation_{oji_udezue,ezinne,jaya,ziri}_location` | Receiving Room / Master Bathroom / Jaya Bedroom / Away | Clean room name. The "Where is Everyone" buttons show `_current_path` (truncated "Receiving Room → Media → Recei…") |
| `binary_sensor.ura_presence_coordinator_guest_mode` | off | Guest mode is a major state change with no surface |
| `binary_sensor.ura_presence_coordinator_house_sleeping` | on | Simple "asleep" chip |
| `sensor.universal_room_automation_last_person_entry` / `_last_person_exit` (timestamps, attr `person_id`, `egress_camera`) | 22:05 / 21:06 | Arrival/departure feed |
| `sensor.universal_room_automation_persons_entered_today` / `_exited_today` | 15 / 12 | Daily traffic |
| `binary_sensor.universal_room_automation_{oji_udezue,ezinne,jaya,ziri}_phone_left_behind` | off | Show only when on |
| `sensor.ura_presence_coordinator_signal_consensus_confidence` | 0.9 | Better "how sure" figure than `census_confidence` = low |
| `sensor.universal_room_automation_last_perimeter_alert` | 22:41 | Security tie-in |

```yaml
type: grid
column_span: 2
cards:
  - type: heading
    heading: Who's Where
    icon: mdi:account-group
    badges:
      - type: entity
        entity: binary_sensor.ura_presence_coordinator_guest_mode
        show_state: true
        visibility:
          - condition: state
            entity: binary_sensor.ura_presence_coordinator_guest_mode
            state: 'on'
      - type: entity
        entity: binary_sensor.ura_presence_coordinator_house_sleeping
        show_state: true
  - type: tile
    entity: sensor.universal_room_automation_oji_udezue_location
    name: Oji
    icon: mdi:account
  - type: tile
    entity: sensor.universal_room_automation_ezinne_location
    name: Ezinne
    icon: mdi:account
  - type: tile
    entity: sensor.universal_room_automation_jaya_location
    name: Jaya
    icon: mdi:account
  - type: tile
    entity: sensor.universal_room_automation_ziri_location
    name: Ziri
    icon: mdi:account
  - type: custom:auto-entities
    show_empty: false
    card:
      type: entities
      title: Phone left home
    filter:
      include:
        - entity_id: binary_sensor.universal_room_automation_*_phone_left_behind
          state: 'on'
  - type: markdown
    entity_id:
      - sensor.universal_room_automation_last_person_entry
      - sensor.universal_room_automation_last_person_exit
    content: >-
      {% set i = 'sensor.universal_room_automation_last_person_entry' %}{% set o = 'sensor.universal_room_automation_last_person_exit' %}
      ⬅️ **In** {{ as_local(as_datetime(states(i))).strftime('%-I:%M %p') if states(i) not in ['unknown','unavailable'] else '—' }}{% if state_attr(i,'person_id') %} · {{ state_attr(i,'person_id') | replace('person.','') | title }}{% endif %}
      · ➡️ **Out** {{ as_local(as_datetime(states(o))).strftime('%-I:%M %p') if states(o) not in ['unknown','unavailable'] else '—' }}{% if state_attr(o,'person_id') %} · {{ state_attr(o,'person_id') | replace('person.','') | title }}{% endif %}
      · {{ states('sensor.universal_room_automation_persons_entered_today') }} in / {{ states('sensor.universal_room_automation_persons_exited_today') }} out today
```

### 2.6 Security — honest openings summary (B8, B9)

Replace the two dead contact ids with `binary_sensor.openclose_zigbee_garageadoor1_contact` and
`binary_sensor.openclose_zigbee_balcony2_contact` in both the markdown list and the `entity-filter`. Then change the
headline so silent sensors are counted:

```jinja
{% set ow = [ ...same 26 window ids... ] %}
{% set od = ['binary_sensor.openclose_zigbee_garageadoor1_contact','binary_sensor.garage_b_protect_sensor_contact',
             'binary_sensor.openclose_aquara_zigbee_patiohallway_contact','binary_sensor.openclose_aquara_zigbee_studybpatio_contact',
             'binary_sensor.openclose_zigbee_balcony2_contact','binary_sensor.openclose_aquara_zigbee_garagehallway_contact'] %}
{% set open = (ow + od) | select('is_state','on') | list %}
{% set silent = (ow + od) | reject('is_state',['on','off']) | list %}
{% if open %}**Open now:** {{ open | map('state_attr','friendly_name') | join(', ') }}{% else %}**Nothing open**{% endif %}
{% if silent %} · ⚠️ {{ silent | count }} not reporting{% endif %}
```
(`binary_sensor.garage_b_protect_sensor_contact` is also unavailable right now, so it will show in the silent count.)

---

## 3. Layout and aesthetics

**Hierarchy (Now tab).** Top to bottom today: greeting, weather hero, 4 outlook tiles, House Draw hero, **Music (24-speaker
group + live players)**, House State hero, Security Score hero, Battery hero, At a Glance, Occupied Now. On a phone
that is 6+ screens before "who's home", and five 180 px heroes each carry one number.
- Put **status first**: one "At a Glance" row (house state, people, rooms, EV, HVAC) directly under the greeting.
  Status-card (installed) or four `badge_state` buttons already exist; move them up.
- Merge **House State / Security / Battery** heroes into a 3-up row at `columns: 4` each (`rows: 2`) instead of three
  full-width heroes.
- Move **Music** to its own view or a Bubble pop-up (`#music`) opened from a small chip. It is the largest block on the
  landing tab and not URA state.

**Duplicates to remove.**
- House State hero appears on Now, People and the Residence header. Keep Now + Residence.
- House Draw appears on Now and Energy with identical code. Keep Energy; on Now show a compact tile.
- Security Score appears on Now and Security.
- People: "Presence Integrity" repeats `census_confidence` and `unexpected_person_detected` from "Presence Signals".
  Delete that section.
- Climate: "Zone Intelligence" button and "Per-Zone Control" tile are the **same switch**
  (`switch.ura_hvac_coordinator_zone_intelligence`). "kWh Avoided Today" tile repeats the AC Ramp Savings table.
- Energy: "Force Charge 30m" appears twice.

**Consistency.** Three control idioms sit side by side on Climate and Energy: button-card `switch` template (8-column),
core `tile` with toggle, and markdown prose. Pick **tile + toggle feature** for all switches. It is native, compact and
theme-aware, and matches the rest of the new cards. The `columns: 8` switch buttons leave a 4-column gap on each row;
use `columns: 6`.

**Density on Climate.** Three full-width thermostat cards take most of the tab. Put them in one row at `columns: 4`
each, or swap to `tile` + `target-temperature` + `climate-preset-modes` features. Then Zone Timers and Manual Changes
(§2.1–2.2) go directly under the HVAC hero.

**Naming (operator style: ≤3 words, no jargon).** Suggested renames:

| Current | Suggested |
|---|---|
| Temp Override Arrester (heading) | Manual Changes |
| Let my manual changes stick | Keep my changes |
| HVAC egress-window pause | Window pause |
| AC Ramp-Down (Energy-Aware) | AC ease-off |
| Predictive Conditioning | Pre-cool |
| Dynamic Preset Auto-Adjust | Auto presets |
| Custom Preset Ranges | Preset ranges |
| Zone Intelligence / Per-Zone Control | Zone control (one card) |
| Vacancy Auto-Off | Empty-zone off |
| Force-charge EVSEs 30 min | Charge EV now |
| EV TOU Mgmt | EV rate timing |
| Census Confidence | Headcount sure? |
| Bayesian Accuracy | Guess accuracy |
| Reconcile Health | (drop — unclear) |
| Study B / Zone 1 · Upstairs Hallway · Back Hallway (thermostats) | Main + Master · Upstairs · Back Hall (match URA zone names) |
| Climate markdown words "arrester", "compromised", "nudge", "planned" | "guard", "met halfway", "AC nudge", drop "planned" |
| Energy markdown "Fill-priority", "Off-peak drain target", "Arb target", "Attain" | "EV waits for battery", "Night drain to", "Grid charge to", drop "Attain" |

**Occupied Now fix (B11):**
```yaml
filter:
  include:
    - entity_id: binary_sensor.*_occupied
      state: 'on'
  exclude:
    - entity_id: binary_sensor.*_camera_occupied
    - entity_id: binary_sensor.*_hvac_occupied
    - entity_id: binary_sensor.ura_*
    - entity_id: binary_sensor.zone_*
```

**Mobile.** Sections views with `max_columns: 3` collapse to one column on phones. `column_span: 2` does nothing
there, so section **order** is the whole layout. Put the Energy Dashboard built-ins (sankey, distribution,
devices-graph; four full-width heavy cards) last or in a sub-view. The navbar-card is installed; a bottom navbar would
let the seven tabs be one thumb away on phone.

**Residence room pop-ups.** Each pop-up's entities list names ~13 per-room entities, and about half are disabled
(B13). After trimming, the pop-ups show only live rows. The room cards' `co` fix (B10) will make the small label say
who is in the room ("Oji") instead of "Occupied".

---

## 4. Not done / limits

- Screenshots were not taken (dashboard screenshot beta not used), so the aesthetics critique comes from the config
  and card sizes, not a rendered view.
- The Residence view (3,602 YAML lines) was checked by automated entity-reference validation plus the room-card template
  and one pop-up. The other 40 pop-ups were not read line by line.
- The drain-precedence `house_load_kw` effect of the poisoned prediction (§1, upstream) was traced from code only.
  Its effect on actual DP decisions is not measured.
- No cards were minted. Suggested cards: (a) Envoy today→lifetime leak into `energy_daily` + consumption history clean-up;
  (b) publish `hvac_away_due_at` on zone status; (c) publish arrester `grace_until` / `compromise_until`;
  (d) the v8 dashboard fix batch itself (§1 P0/P1).
