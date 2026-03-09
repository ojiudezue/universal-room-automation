# HomeAssistant Sensors Reference

## Sensor Types

### 1. Template Sensors
Template sensors use Jinja2 templates to create custom sensor values from existing entities.

**Location:** `configuration.yaml` or `sensors.yaml`

**Basic Template Sensor:**
```yaml
template:
  - sensor:
      - name: "Living Room Temperature F"
        unit_of_measurement: "°F"
        state: >
          {{ (states('sensor.living_room_temperature') | float * 9/5 + 32) | round(1) }}
        device_class: temperature

      - name: "Combined Power Usage"
        unit_of_measurement: "W"
        state: >
          {{ states('sensor.living_room_power') | float(0) +
             states('sensor.bedroom_power') | float(0) }}
        device_class: power
```

**Template Sensor with Attributes:**
```yaml
template:
  - sensor:
      - name: "System Status"
        state: >
          {% if states('sensor.cpu_usage') | float > 80 %}
            critical
          {% elif states('sensor.cpu_usage') | float > 60 %}
            warning
          {% else %}
            normal
          {% endif %}
        attributes:
          cpu_usage: "{{ states('sensor.cpu_usage') }}"
          memory_usage: "{{ states('sensor.memory_usage') }}"
          last_boot: "{{ states('sensor.last_boot') }}"
```

### 2. RESTful Sensors
Sensors that pull data from REST APIs.

**Basic REST Sensor:**
```yaml
sensor:
  - platform: rest
    name: "Weather API"
    resource: "https://api.weather.com/v1/current"
    headers:
      Authorization: "Bearer YOUR_TOKEN"
    value_template: "{{ value_json.temperature }}"
    json_attributes_path: "$.current"
    json_attributes:
      - humidity
      - pressure
      - wind_speed
    scan_interval: 300
```

### 3. Command Line Sensors
Sensors that execute shell commands.

```yaml
sensor:
  - platform: command_line
    name: "CPU Temperature"
    command: "cat /sys/class/thermal/thermal_zone0/temp"
    unit_of_measurement: "°C"
    value_template: "{{ value | float / 1000 | round(1) }}"
    scan_interval: 60
```

### 4. Custom Component Sensors (Python)
For complex logic requiring Python development.

**File Structure:**
```
custom_components/
└── my_sensor/
    ├── __init__.py
    ├── manifest.json
    └── sensor.py
```

**manifest.json:**
```json
{
  "domain": "my_sensor",
  "name": "My Custom Sensor",
  "documentation": "https://github.com/yourusername/my_sensor",
  "codeowners": ["@yourusername"],
  "requirements": [],
  "version": "1.0.0",
  "iot_class": "local_polling"
}
```

**sensor.py (Basic Example):**
```python
"""Platform for sensor integration."""
from datetime import timedelta
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the sensor platform."""
    add_entities([MyCustomSensor()])

class MyCustomSensor(SensorEntity):
    """Representation of a Custom Sensor."""

    def __init__(self):
        """Initialize the sensor."""
        self._attr_name = "My Custom Sensor"
        self._attr_unique_id = "my_custom_sensor_001"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_native_value = None

    def update(self):
        """Fetch new state data for the sensor."""
        # Add your logic here to fetch/calculate sensor value
        self._attr_native_value = 22.5
```

## Device Classes and State Classes

### Common Device Classes:
- `temperature` - Temperature sensors
- `humidity` - Humidity sensors
- `pressure` - Pressure sensors
- `power` - Power consumption
- `energy` - Energy consumption
- `battery` - Battery level
- `voltage` - Voltage
- `current` - Current
- `timestamp` - Date/Time
- `duration` - Duration

### State Classes:
- `measurement` - Instantaneous value (temperature, power)
- `total` - Monotonically increasing (total energy)
- `total_increasing` - Always increasing counter

## Advanced Template Techniques

### Availability Template:
```yaml
template:
  - sensor:
      - name: "Advanced Sensor"
        state: "{{ states('sensor.source') }}"
        availability: >
          {{ states('sensor.source') not in ['unavailable', 'unknown'] }}
```

### Icon Template:
```yaml
template:
  - sensor:
      - name: "Door Status"
        state: "{{ states('binary_sensor.door') }}"
        icon: >
          {% if is_state('binary_sensor.door', 'on') %}
            mdi:door-open
          {% else %}
            mdi:door-closed
          {% endif %}
```

### Trigger-based Template Sensors:
```yaml
template:
  - trigger:
      - platform: time_pattern
        minutes: "/5"
    sensor:
      - name: "5 Minute Average Power"
        unit_of_measurement: "W"
        state: >
          {{ states('sensor.power') | float(0) }}
```

## Best Practices

1. **Always provide fallback values** using the `float(0)` or `default()` filters
2. **Use unique_id** for sensors to enable customization in the UI
3. **Set appropriate device_class** for proper unit handling and visualization
4. **Use state_class** for sensors that should appear in statistics and energy dashboard
5. **Add availability templates** to prevent "unknown" states
6. **Use scan_interval** wisely to balance data freshness and system load
7. **For complex logic**, consider custom components instead of complex templates
8. **Always handle errors** in custom component sensors with try/except blocks
