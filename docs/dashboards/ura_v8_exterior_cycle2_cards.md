# ura-v8 dashboard cards — exterior cycle 2

**Status:** prepared, NOT applied. The ura-v8 dashboard lives HA-side at
`.storage/lovelace.ura_v8` (storage-mode); it is not tracked in this repo.
Per operator direction, cards are staged here and applied post-review as
a live step (edit via HA Lovelace UI or a targeted `.storage` patch).

## Feasibility audit (2026-08-06)

Read via mounted `~/ha-config/.storage/lovelace.ura_v8`:

| Ask | Feasibility | Notes |
|---|---|---|
| a) Security tab "Exterior activity" markdown card | ✅ Feasible | Consumes `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` attrs (`open_tracks`, `counts`) — sensor already exists as of v5.53.0 |
| b) egress open/close sensors card | ✅ Already present | Security tab already has an "Openings & Egress" markdown + entity-filter section covering all `*_egress_window_open` and exterior door contacts |
| b) active-notification badge | ⚠️ Partial | `sensor.ura_security_coordinator_security_armed_state` exposes `active_alert` attr and is already rendered as the hero card's label; a dedicated badge in the Now tab is a small addition |
| c) front-door doorbell duplicate | ❌ Not reproduced | Security tab currently has exactly ONE doorbell picture-entity (`camera.garage_doorbell_lite_low_resolution_channel`, named "Garage Doorbell"). No sibling "front-door doorbell" card is present. Either the duplicate was already removed, or the operator was viewing a different dashboard revision. Recommend confirming with operator before editing. |

## Card 1 — Security tab "Exterior activity" markdown

Insert before the "Openings & Egress" section (i.e. as a new `section` in
the `sections` array, index ~2, right after the Armed State hero card).

```yaml
type: grid
column_span: 2
cards:
  - type: heading
    heading: Exterior activity
    heading_style: title
    icon: mdi:map-marker-path
  - type: markdown
    grid_options:
      columns: full
    content: |-
      {%- set attrs = state_attr('sensor.ura_security_coordinator_outside_open_tracks_diagnostic', 'open_tracks') or [] -%}
      {%- set counts = state_attr('sensor.ura_security_coordinator_outside_open_tracks_diagnostic', 'counts') or {} -%}
      {%- if attrs | length == 0 -%}
      **Perimeter quiet.**
      {%- else -%}
      **{{ attrs | length }} open track(s)** — person {{ counts.get('exterior_person_tracks_active', 0) }} · vehicle {{ counts.get('exterior_vehicle_tracks_active', 0) }} · animal {{ counts.get('exterior_animal_tracks_active', 0) }}
      {% for t in attrs -%}
      - **{{ '🚶' if t.label == 'person' else ('🚗' if t.label == 'car' else '🐾') }} {{ t.label }}** ({{ t.classification }}) — {{ t.path }} · last cam: `{{ t.last_camera }}` · alerts: {{ t.alert_count }}{% if t.identified %} · **identified**{% endif %}
      {% endfor %}
      {%- endif -%}
```

Consumers:

- `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` —
  disabled by default; enable via the entity registry before applying
  the card, otherwise `state_attr` returns None and the markdown reads
  "Perimeter quiet." indefinitely.

## Card 2 — Now tab active-notification badge (optional)

Append to the Now view's badge row (small hero-level indicator):

```yaml
type: entity
entity: sensor.ura_security_coordinator_security_armed_state
name: Active security alert
icon: mdi:shield-alert
visibility:
  - condition: state
    entity: sensor.ura_security_coordinator_security_armed_state
    attribute: active_alert
    state: true
```

`active_alert` is an existing attribute of the armed-state sensor. If the
Now tab's badge grid does not support the `visibility` field on plain
`type: entity` cards in this HA version, fall back to a `custom:button-card`
templated hero (`security_score` template already in use) with the same
visibility condition.

## Card 3 — Egress open/close sensors

**No change needed.** The Security tab already carries an
"Openings & Egress" markdown card + entity-filter glance covering all
`*_egress_window_open` and exterior door contacts. If the operator wants
that card promoted to the Now tab as a badge summary, use:

```yaml
type: entity
entity: binary_sensor.ura_hvac_coordinator_entertainment_master_suite_egress_window_open
name: Egress open
icon: mdi:window-open
```

...repeated per zone (three exist as of v8: entertainment_master_suite,
upstairs, back_hallway).

## Card 4 — Front-door doorbell duplicate

**Not found in current ura-v8** (audited 2026-08-06 against
`~/ha-config/.storage/lovelace.ura_v8`). If the operator can point to
the specific card or a dashboard revision that still has it, the fix is
to delete the redundant `type: picture-entity` block whose entity is
`camera.garage_doorbell_lite_low_resolution_channel` and keep only one.

## Application procedure

1. Enable the diagnostic sensor:
   Settings → Devices & services → Universal Room Automation → Entities
   → find "Outside: Open Tracks (diagnostic)" → toggle Enable.
2. Open Lovelace → ura-v8 dashboard → Edit dashboard.
3. Security view → add section → paste YAML from **Card 1** above.
4. Now view → add badge → paste **Card 2** (or fall back per note).
5. Save. Verify:
   - Diagnostic sensor state = 0 when perimeter is quiet.
   - Markdown renders "Perimeter quiet." with no tracks.
   - Force a test: trigger any perimeter camera person BS → within 3
     minutes, markdown shows the track with path narrative.
