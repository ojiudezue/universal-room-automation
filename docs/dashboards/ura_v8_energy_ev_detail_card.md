# ura-v8 — EV Charging Detail card (Energy & EV tab)

**Status:** staged, NOT applied. Per the `ura_v8_exterior_cycle2_cards.md` precedent, cards are staged
here and applied post-review as a live step. `ura-v8` lives HA-side at `.storage/lovelace.ura_v8`.

**Ask (operator 2026-08-09):** *"add an EV charging detail card to the Ura v8 energy tab. Style well.
Detail cards are a bit sensor words vomit. Best judgement because of space though."*

## Design rationale — what this deliberately does NOT do

The sibling **Battery Strategy Detail** card (section 7) is the pattern being improved on. It renders
four dense lines of `**Label:** {{ value }}` separated by `·` and `|`, **unconditionally** — so
`None`, `unavailable`, and irrelevant fields all take up space and the reader has to parse noise to
find signal. That is the "word vomit" failure mode.

Three rules applied here:

1. **Narrative first, numbers second.** The top line says what is happening in words a human
   already understands. `pause_reason_human` exists precisely for this and nothing on the dashboard
   consumed it before now.
2. **Conditional rendering — a field earns its line.** `must_start_by`, `force_charge_until`,
   excess-solar and fill-priority only render when they are actually set/active. On a normal idle
   evening the card is three lines; during a solar surge or a deadline it grows.
3. **One row per endpoint, not one line per attribute.** There are **four** chargeable endpoints
   (2 Emporia EVSEs + 2 Moes smartplug sockets), so a table beats prose.

**Deliberately omitted** (available but noise): `paused_by_energy`, `paused_by_grid_cap`,
`paused_by_battery_drain`, `paused_by_arbitrage`, `paused_by_fill_priority` — these are the *inputs*
to `pause_reason_human`, already summarised by it; `cooldowns`, `evse_config`, `pause_dispatch_state`,
`proactive_offpeak_holds`; every `shadow_*` and `last_eval_snapshot` field (shadow-eval telemetry, not
operator-facing); raw SPAN lifetime counters (`consumed_energy` in the tens of millions of Wh — a
number with no decision attached).

## Live values at design time (2026-08-09)

| Endpoint | is_on | status | charging | reason |
|---|---|---|---|---|
| garage_a | True | Standby | False | idle |
| garage_b | False | Standby | False | off |
| moes socket 1 | — | — | — | **TOU peak/mid-peak pause** |
| moes socket 2 | — | — | — | **TOU peak/mid-peak pause** |

`plan = hold_only` since 2026-08-07 · `must_start_by_dt = None` · `excess_solar_active = False` ·
`fill_priority_target_soc = 80` · EVSE A `Connected`, EVSE B `Disconnected`.

## The card

Insert as a new section immediately **after** "Battery Strategy Detail" (index 8), so the two
strategy-detail cards sit together and the graph/forecast sections stay below.

```yaml
type: grid
cards:
  - type: heading
    heading: EV Charging Detail
    heading_style: title
    icon: mdi:ev-station
  - type: markdown
    content: >-
      {%- set s = 'sensor.ura_energy_coordinator_ev_charging_status' -%}
      {%- set p = 'sensor.ura_energy_coordinator_ev_charging_plan' -%}
      {%- set reasons = state_attr(s,'pause_reason_human') or {} -%}
      {%- set a = state_attr(s,'garage_a') or {} -%}
      {%- set b = state_attr(s,'garage_b') or {} -%}
      {%- set st = states(s) -%}
      {%- set icon = '⚡' if st == 'charging' else ('⏸' if st == 'paused' else '○') -%}
      ## {{ icon }} {{ st | replace('_',' ') | title }}
      {%- set live = reasons.values() | reject('in', ['idle','off','charging']) | list | unique | list %}
      {% if live %}{{ live | join(' · ') }}{% else %}No active holds{% endif %}

      | | Plug | State | Rate |
      |---|---|---|---|
      | **Garage A** | {{ 'yes' if states('sensor.garage_a_evse_emporia_wifi_garagea_status') == 'Connected' else '—' }} | {{ a.get('energy_status','?') | title }} | {{ states('sensor.ura_energy_coordinator_ev_charge_rate_garage_a') | float(0) | round(1) }} kW |
      | **Garage B** | {{ 'yes' if states('sensor.garage_b_evse_emporia_wifi_garageb_status') == 'Connected' else '—' }} | {{ b.get('energy_status','?') | title }} | {{ states('sensor.ura_energy_coordinator_ev_charge_rate_garage_b') | float(0) | round(1) }} kW |
      {%- set socks = reasons | dictsort | rejectattr('0','in',['garage_a','garage_b']) | list %}
      {%- if socks %}
      | **Outlets** ({{ socks | count }}) | — | {{ socks[0][1] }} | — |
      {%- endif %}

      {% set plan = states(p) -%}
      **Plan:** {{ plan | replace('_',' ') | title }}
      {%- set since = state_attr(p,'since') %}
      {%- if since %} · held {{ ((now() - (since | as_datetime)).total_seconds() / 3600) | round(0) | int }}h{% endif %}
      {%- set msb = state_attr(p,'must_start_by_dt') %}
      {%- if msb %} · **must start by {{ (msb | as_datetime | as_local).strftime('%-I:%M %p') }}**{% endif %}
      {%- set fc = state_attr(s,'force_charge_until_iso') %}
      {%- if fc %}

      🔒 **Forced charge** until {{ (fc | as_datetime | as_local).strftime('%-I:%M %p') }}
      {%- endif %}
      {%- if state_attr(s,'excess_solar_active') %}

      ☀️ **Excess solar** — charging on surplus{% set es = state_attr(s,'excess_solar_evses') %}{% if es %} ({{ es | join(', ') }}){% endif %}
      {%- endif %}
      {%- set fp = state_attr(s,'fill_priority_target_soc') %}
      {%- if fp and plan not in ['hold_only'] %} · fill target {{ fp }}%{% endif %}
```

## Behaviour by scenario

| Scenario | Card renders |
|---|---|
| Idle evening (today) | heading + "TOU peak/mid-peak pause" + 3-row table + `Plan: Hold Only · held 48h` — **~6 lines** |
| Charging on solar | adds the ☀️ line and the fill target |
| Deadline pending | adds **must start by 6:30 AM** inline on the plan line |
| Operator forced charge | adds the 🔒 line |

Growth is proportional to how much is actually going on, which is the property the battery card lacks.

## Acceptance criteria

- **Verify:** on a normal idle evening the card is ≤ 7 rendered lines and contains no `None`,
  `unavailable`, or `unknown`.
- **Verify:** the headline reason line reflects `pause_reason_human`, de-duplicated (both Moes sockets
  share one reason → shown once, not twice).
- **Verify:** `must_start_by`, `force_charge_until`, excess-solar and fill-target lines are **absent**
  when their underlying attributes are `None`/False.
- **Verify:** plug column reads from the Emporia EVSE status entity, not from `is_on` (which is the
  URA-side enable flag, not the physical connection — Garage A is currently `is_on: True` with the car
  `Connected` but `energy_status: idle`, and those are three different facts).
- **Live:** renders without a template error on the Energy & EV tab after apply.

## Apply step (not yet done)

Storage-mode dashboard — do **not** hand-edit `.storage/lovelace.ura_v8` while HA is running (it is
held in memory and will be clobbered). Apply via the Lovelace UI (Raw configuration editor) or the
websocket `lovelace/config/save` path.
