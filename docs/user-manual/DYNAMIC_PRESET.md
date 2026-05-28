# Dynamic Preset Override Source — User Manual

**Feature area:** Energy Coordinator (CM device)
**Last updated:** 2026-05-28 (v4.7.1)
**Scope:** every control, sensor, switch, and form field related to Dynamic Preset Override Source

This is a task-oriented manual: skim the section headings to find what you need, read the troubleshooting recipes when something feels wrong.

---

## 1. What Dynamic Preset does

Dynamic Preset adjusts your per-zone HVAC setpoint ranges based on how hot today is expected to be, compared to your baseline.

**Why this matters:** the default seasonal ranges in URA (e.g., home cool high = 77°F in summer) were designed for a "typical" day. On a day when it's 97°F apparent temperature outside vs. a 77°F baseline, running at 77°F means your AC will never keep up — and you're fighting your thermostat all day. On a mild 68°F day, that same 77°F target is wasteful.

Dynamic Preset shifts the allowed setpoint range automatically, once per EC decision cycle (~5 min), without requiring you to manually change any thermostat preset.

**Key facts:**
- Off by default. You opt in the master switch and each zone separately.
- Per-zone. Each zone can have different bucket ranges and offset.
- Composable. Guest Mode overrides (priority 50) always win over Dynamic Preset (priority 30) when both are active.
- Cross-restart safe. The active bucket and transition timestamp survive HA restarts.

---

## 2. How bucket classification works

URA fetches today's apparent-temperature forecast high from the WeatherProviderManager. It then computes a per-zone delta:

```
delta = apparent_forecast_high − zone_home_cool_high (your zone's baseline)
```

That delta maps to one of four thermal load buckets:

| Bucket | Condition | Meaning |
|---|---|---|
| `cool` | δ ≤ −2°F | Cooler than baseline; loosen cooling setpoints |
| `mild` | −2°F < δ ≤ +8°F | Near baseline; use calibrated defaults |
| `hot` | +8°F < δ ≤ +18°F | Noticeably hotter; tighten cooling setpoints |
| `extreme` | δ > +18°F | Much hotter than baseline; maximum cooling effort |

The boundaries (−2, +8, +18) are user-tunable in the CM options flow. When no forecast is available, the zone stays at its current bucket (or `unknown` at startup).

---

## 3. Flap prevention: dwell timer + hysteresis

Forecast apparent temperature can wobble slightly between EC ticks. Two guards prevent unnecessary thermostat changes:

**Dwell timer (default: 60 min)**
A bucket transition fires only if the current bucket has been stable for at least 60 minutes. If the forecast puts you in `hot` for 5 minutes and then back to `mild`, no transition fires.

**Hysteresis (default: ±2°F)**
Entering a tighter bucket (e.g., mild → hot) requires only that the classification agrees. Exiting a tighter bucket (e.g., hot back to mild) requires the delta to fall past the boundary by an extra 2°F. This makes the hysteresis asymmetric: easy to go tighter, hard to relax.

Example: you're in `hot` (boundary at +8°F). To transition down to `mild`, the delta must fall to ≤ +6°F (8 − 2 hysteresis), not just ≤ +8°F.

Both the dwell and hysteresis values are adjustable via the Number entities on the Energy Coordinator device.

---

## 4. Setup: step by step

### Step 1 — Verify WeatherProviderManager is active

Dynamic Preset depends on `sensor.ura_weather_apparent_forecast_high` being available (non-unavailable, non-unknown). If this sensor shows `unavailable`, configure at least a Primary weather entity in:

**Settings → Devices & Services → URA Coordinator Manager → Configure → Energy step → Weather Providers**

### Step 2 — Enable the master switch

On the Energy Coordinator device page, turn on:

```
switch.ura_energy_coordinator_dynamic_preset_enabled
```

This is the global kill-switch. All zones are still off until you opt in each one.

### Step 3 — Configure each zone via config flow

For each zone you want to manage:

1. Go to **Settings → Devices & Services → URA: Zone Manager → Configure**
2. Select the zone in question
3. Choose **Zone Dynamic Preset** from the menu

The form has these fields:

| Field | Default | Purpose |
|---|---|---|
| Enable for this zone | Off | Zone-level opt-in |
| Offset (°F) | 0.0 | Added to zone's home_high for sleep_high computation |
| Reset offset on guest state | On (checked by default) | Zero offset when house_state = guest |
| Enable sleep preset override | Off | Also emit sleep-preset range overrides |
| Cool bucket — home low / high | — | Setpoints for `cool` bucket, home preset (required when enabled) |
| Mild bucket — home low / high | — | Setpoints for `mild` bucket, home preset (required when enabled) |
| Hot bucket — home low / high | — | Setpoints for `hot` bucket, home preset (required when enabled) |
| Extreme bucket — home low / high | — | Setpoints for `extreme` bucket, home preset (required when enabled) |
| Sleep high per bucket | — | Sleep preset high for each bucket (when sleep override enabled) |

All four bucket rows (home low/high) are required when the zone is enabled. The config flow validates this and returns an error if any bucket is missing.

**Suggested starting values for a Texas summer (baseline = 77°F home cool high):**

| Bucket | Home low | Home high |
|---|---|---|
| Cool | 72 | 75 |
| Mild | 73 | 77 |
| Hot | 74 | 78 |
| Extreme | 75 | 80 |

### Step 4 — Tune dwell and hysteresis

On the Energy Coordinator device page:

- `number.ura_energy_coordinator_dynamic_preset_dwell_minutes` — how long a bucket must be stable before transitioning (default 60, range 15–240)
- `number.ura_energy_coordinator_dynamic_preset_hysteresis` — extra delta required to exit a tighter bucket (default 2.0, range 0.5–5.0)

Higher dwell = more stable, slower to react to forecast changes. Higher hysteresis = less flapping on bucket boundaries.

### Step 5 — Observe

After the next EC tick (≤5 min), check:

- `sensor.ura_energy_coordinator_dynamic_preset_bucket_{zone_id}` — current bucket (e.g., `sensor.ura_energy_coordinator_dynamic_preset_bucket_master_suite`)
- `sensor.ura_energy_coordinator_dynamic_preset_range_{zone_id}` — resolved cool range as "low–high °F" or "default" (when no override active)
- `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` — global count of zones with active overrides

---

## 5. Sleep preset override

When **Enable sleep preset override** is checked for a zone, Dynamic Preset also emits a sleep-preset range override in addition to the home preset. The sleep high is auto-derived:

```
sleep_high = max(74°F, home_high − 1) + zone_offset
```

The sleep floor (74°F) prevents the computed value from dropping below a safe sleeping setpoint regardless of your zone config. The `−1` creates a natural 1°F tighter sleep target than the home preset.

Per-bucket sleep highs can also be explicitly configured in the zone form if you prefer manual control over the auto-derive.

---

## 6. Zone offset

The per-zone offset (default 0°F) is added to the zone's home_high when computing the sleep_high. It is also applied to all range values emitted for that zone, so zones in structurally hotter rooms (south-facing, poor insulation) can be configured tighter.

If **Reset offset on guest state** is enabled, the offset is zeroed whenever `house_state == 'guest'` — useful if your guest behavior naturally prefers more comfort.

---

## 7. Interaction with Guest Mode

If both Dynamic Preset and Guest Mode actuation are active for a zone:

- Dynamic Preset emits at priority **30**
- Guest Mode emits at priority **50**

The `OverrideEngine` applies highest-priority-wins per field. On an overlap, Guest Mode's `cool_low` and `cool_high` replace Dynamic Preset's values for that field.

Sensor `sensor.ura_energy_dynamic_preset_effective_range_{zone_id}` shows the resolved range after composition — it reflects the Guest Mode override, not the raw Dynamic Preset value.

---

## 8. Cross-restart safety

The active bucket and the timestamp of the last bucket transition are persisted via `RestoreEntity` on `sensor.ura_energy_dynamic_preset_active_bucket_{zone_id}`.

On the first EC tick after HA restarts:
1. The sensor restores its last state from HA's storage.
2. It injects the bucket + transition timestamp into `DynamicPresetOverrideSource`.
3. The dwell timer resumes from the original timestamp — if the bucket was 45 minutes into a 60-minute dwell before restart, it only needs 15 more minutes, not a full 60.

This prevents "flap storms" at restart where every zone transitions unnecessarily because the dwell counter reset.

---

## 9. Observation mode

Dynamic Preset computes and emits overrides regardless of URA's observation mode. The override values are always visible in the sensors.

Observation mode gating for HVAC actuation (actually applying `set_temperature` to the thermostat) is the HVAC Coordinator's responsibility, not Dynamic Preset's. This follows URA's standard "compute always, actuate gated" pattern (Bug Class #23).

---

## 10. Troubleshooting

### "Sensors show 'unknown' after enabling"

Check `sensor.ura_weather_apparent_forecast_high`. If unavailable or unknown:
- Confirm a weather entity is configured in CM → Configure → Energy → Weather Providers.
- Confirm the weather entity itself is not unavailable.
- Wait one EC cycle (≤5 min) after configuring.

### "Active bucket never changes from mild"

Check whether the dwell timer is blocking a transition. The bucket must be stable for `dwell_minutes` before a transition fires. If the forecast delta is near a boundary and oscillating, the hysteresis may also be blocking. Temporarily set `dwell_minutes` to 15 and `hysteresis_f` to 0.5 while diagnosing, then restore.

### "Effective range shows 'default' even though zone is opted in and bucket is set"

This is correct when the current bucket is `cool` and your cool-bucket range equals your zone's configured baseline. The sensor shows `default` when the override does not change the range. Set a distinct cool-bucket low/high to see a non-default value.

### "Zone bucket reverted to 'unknown' after HA restart"

If the sensor was unavailable at shutdown (e.g., WPM was not yet up when HA shutdown), there is no state to restore. It will re-classify on the next EC tick. This is expected and not a bug.

### "Number entity slider value isn't being respected"

The dwell and hysteresis Number entities persist their values across restarts via RestoreEntity. However, the EC reads these values from CM entry options at config-flow time, not from the live Number entity state. This is a known gap (deferred to post-review backlog). Workaround: after changing a Number entity, trigger a reload of the URA CM integration entry — the new value will be picked up from the Number entity's restored state on the next load.

---

## 11. Entity reference

### Switch

| Entity ID | Purpose |
|---|---|
| `switch.ura_energy_coordinator_dynamic_preset_enabled` | Master enable. All zones inert when off. |

### Numbers

| Entity ID | Default | Range | Unit |
|---|---|---|---|
| `number.ura_energy_coordinator_dynamic_preset_dwell_minutes` | 60 | 15–240 | min |
| `number.ura_energy_coordinator_dynamic_preset_hysteresis` | 2.0 | 0.5–5.0 | °F |

### Sensors (global)

| Entity ID | Type | Shows |
|---|---|---|
| `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` | Count | Number of zones with an active non-baseline override |

### Sensors (per zone, substituting `{zone_id}` with your canonical zone identifier, e.g. `master_suite`)

| Entity ID | Shows |
|---|---|
| `sensor.ura_energy_coordinator_dynamic_preset_bucket_{zone_id}` | Current bucket: cool / mild / hot / extreme / unknown |
| `sensor.ura_energy_coordinator_dynamic_preset_range_{zone_id}` | Resolved cool range "low–high °F" or "default" |

---

## 12. Dispatcher signals (for advanced automation use)

If you want to trigger HA automations on Dynamic Preset events, listen to these dispatcher signals via a custom integration or URA's event bus:

| Signal | When fires | Payload keys |
|---|---|---|
| `ura_dynamic_preset_transitioned` | Zone bucket changes | `zone_id`, `previous_bucket`, `new_bucket`, `delta_f`, `now_iso` |
| `ura_dynamic_preset_overrides_updated` | After each EC tick when overrides change | (no payload) |

Note: these are internal HA dispatcher signals, not HA events on the event bus. Direct HA automation triggers from these signals require a custom listener.
