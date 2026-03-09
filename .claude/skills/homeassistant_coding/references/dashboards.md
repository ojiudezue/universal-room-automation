# HomeAssistant Dashboards (Lovelace) Reference

## Dashboard Structure

Dashboards are configured in the UI or via YAML in `ui-lovelace.yaml` or dashboard-specific files.

**Basic Dashboard Structure:**
```yaml
title: My Home
views:
  - title: Home
    path: home
    icon: mdi:home
    cards:
      # Cards go here
```

## Core Card Types

### 1. Entities Card
Display multiple entities in a list.

```yaml
type: entities
title: Living Room
entities:
  - entity: light.living_room
    name: Main Light
  - entity: sensor.living_room_temperature
  - entity: sensor.living_room_humidity
  - type: divider
  - entity: switch.tv
    icon: mdi:television
```

**With Secondary Info:**
```yaml
type: entities
entities:
  - entity: light.bedroom
    secondary_info: last-changed
  - entity: sensor.bedroom_temp
    secondary_info: entity-id
```

### 2. Gauge Card
Visual gauge for numeric sensors.

```yaml
type: gauge
entity: sensor.cpu_usage
name: CPU Usage
unit: "%"
min: 0
max: 100
severity:
  green: 0
  yellow: 60
  red: 80
```

### 3. Button Card
Interactive button for entities.

```yaml
type: button
entity: light.living_room
name: Living Room Light
icon: mdi:lightbulb
tap_action:
  action: toggle
hold_action:
  action: more-info
```

### 4. Glance Card
Compact view of multiple entities.

```yaml
type: glance
title: Quick View
entities:
  - entity: light.kitchen
  - entity: light.bedroom
  - entity: light.living_room
  - entity: sensor.temperature
show_name: true
show_state: true
```

### 5. History Graph Card
Display history of entities.

```yaml
type: history-graph
title: Temperature History
entities:
  - entity: sensor.living_room_temperature
  - entity: sensor.bedroom_temperature
hours_to_show: 24
refresh_interval: 0
```

### 6. Markdown Card
Display formatted text.

```yaml
type: markdown
content: |
  ## Welcome Home
  Current time: {{ now().strftime('%H:%M') }}

  Temperature: {{ states('sensor.temperature') }}°C
title: Info
```

### 7. Picture Elements Card
Interactive image with overlays.

```yaml
type: picture-elements
image: /local/floorplan.png
elements:
  - type: state-icon
    entity: light.living_room
    tap_action:
      action: toggle
    style:
      top: 50%
      left: 30%
  - type: state-label
    entity: sensor.living_room_temperature
    style:
      top: 60%
      left: 30%
```

### 8. Conditional Card
Show cards based on conditions.

```yaml
type: conditional
conditions:
  - entity: light.living_room
    state: "on"
card:
  type: entities
  entities:
    - light.living_room
    - sensor.living_room_brightness
```

### 9. Horizontal/Vertical Stack
Group multiple cards together.

```yaml
type: vertical-stack
cards:
  - type: button
    entity: light.kitchen
  - type: entities
    entities:
      - sensor.kitchen_temperature
      - sensor.kitchen_humidity
```

### 10. Grid Card
Arrange cards in a grid layout.

```yaml
type: grid
columns: 2
square: false
cards:
  - type: button
    entity: light.bedroom
  - type: button
    entity: light.living_room
  - type: gauge
    entity: sensor.cpu_usage
  - type: gauge
    entity: sensor.memory_usage
```

## Custom Cards (HACS)

### Installing Custom Cards
1. Install HACS (Home Assistant Community Store)
2. Go to HACS → Frontend
3. Search and install custom card
4. Add resource reference

### Popular Custom Cards

**Mini Graph Card:**
```yaml
type: custom:mini-graph-card
entities:
  - sensor.temperature
  - sensor.humidity
hours_to_show: 24
points_per_hour: 2
line_width: 2
smoothing: true
```

**Button Card (Custom):**
```yaml
type: custom:button-card
entity: light.living_room
name: Living Room
icon: mdi:lightbulb
color: auto
tap_action:
  action: toggle
styles:
  card:
    - height: 100px
  name:
    - font-size: 14px
```

**Mushroom Cards:**
```yaml
type: custom:mushroom-light-card
entity: light.living_room
show_brightness_control: true
show_color_control: true
use_light_color: true
```

**ApexCharts Card:**
```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Power Consumption
series:
  - entity: sensor.power_consumption
    type: line
    stroke_width: 2
    curve: smooth
```

## Advanced Dashboard Techniques

### View with Badges:
```yaml
views:
  - title: Home
    badges:
      - entity: person.john
      - entity: sensor.temperature
      - entity: alarm_control_panel.home
    cards:
      # cards here
```

### Theme per View:
```yaml
views:
  - title: Dark Room
    theme: dark
    cards:
      # cards here
```

### Visibility Conditions:
```yaml
views:
  - title: Admin
    visible:
      - user: admin_user_id
    cards:
      # admin cards
```

### Card Mod (Custom Styling):
```yaml
type: entities
entities:
  - entity: light.living_room
card_mod:
  style: |
    ha-card {
      background: rgba(0,0,0,0.3);
      border-radius: 15px;
    }
```

## Responsive Design Tips

### Using Grid for Responsive Layout:
```yaml
type: grid
columns: 3  # Auto-adjusts on mobile
square: false
cards:
  # cards here
```

### Panel View (Full Width):
```yaml
views:
  - title: Security Cameras
    panel: true
    cards:
      - type: picture-glance
        camera_image: camera.front_door
        entities: []
```

## Dashboard Organization Best Practices

1. **Use Views for Different Areas:** Create separate views for rooms or functions
2. **Group Related Entities:** Use stack cards to group related controls
3. **Consistent Icon Usage:** Use Material Design Icons (mdi:) for consistency
4. **Conditional Displays:** Show cards only when relevant using conditional cards
5. **Mobile-First Design:** Test on mobile devices, as most interactions happen there
6. **Performance:** Limit heavy cards (cameras, graphs) per view
7. **Logical Flow:** Order cards by frequency of use (top = most used)
8. **Use Badges Sparingly:** Reserve for most important status indicators

## YAML Mode vs UI Mode

### Enabling YAML Mode:
```yaml
# configuration.yaml
lovelace:
  mode: yaml
  resources:
    - url: /local/custom-card.js
      type: module
```

### Multiple Dashboards:
```yaml
# configuration.yaml
lovelace:
  mode: storage
  dashboards:
    lovelace-mobile:
      mode: yaml
      title: Mobile
      icon: mdi:cellphone
      show_in_sidebar: true
      filename: mobile.yaml
```

## Useful Jinja2 Templates in Cards

### Time-based Greeting:
```yaml
type: markdown
content: |
  {% set hour = now().hour %}
  {% if hour < 12 %}
    Good morning!
  {% elif hour < 18 %}
    Good afternoon!
  {% else %}
    Good evening!
  {% endif %}
```

### Dynamic Content:
```yaml
type: markdown
content: |
  ## System Status
  {% if states('sensor.cpu_usage') | float > 80 %}
    ⚠️ High CPU Usage
  {% else %}
    ✅ System Normal
  {% endif %}
```
