# My Integration Template

This is a template for creating a custom HomeAssistant integration.

## Structure

- `__init__.py` - Integration setup and entry point
- `manifest.json` - Integration metadata
- `const.py` - Constants and configuration keys
- `config_flow.py` - UI configuration flow
- `coordinator.py` - Data update coordinator for efficient polling
- `sensor.py` - Sensor platform implementation
- `strings.json` - UI translations

## Customization Steps

1. **Replace all instances of "My Integration" and "my_integration"** with your integration name
2. **Update manifest.json:**
   - Change `domain` to your integration domain (lowercase, underscores)
   - Update `name`, `documentation`, and `codeowners`
   - Add any required Python packages to `requirements`
   - Set appropriate `iot_class`

3. **Implement device communication:**
   - Create an API client (optionally in `api.py`)
   - Update `coordinator.py` to fetch real data from your device
   - Update `_test_connection` in `config_flow.py`

4. **Customize sensors:**
   - Modify `sensor.py` to add/remove sensors as needed
   - Update device classes, units, and state classes appropriately
   - Add additional platforms (switch, light, etc.) if needed

5. **Update device info:**
   - In `sensor.py`, update the `DeviceInfo` with manufacturer, model, etc.

6. **Test your integration:**
   - Copy to `custom_components/your_domain/`
   - Restart HomeAssistant
   - Add integration via UI

## Adding Additional Platforms

To add switches, lights, or other platforms:

1. Add the platform to `PLATFORMS` in `__init__.py`:
```python
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]
```

2. Create the platform file (e.g., `switch.py`) following the pattern in `sensor.py`

3. Implement the platform-specific entities

## Best Practices

- Use the coordinator for data fetching to avoid duplicate API calls
- Always implement proper error handling
- Set unique_id for all entities to enable customization
- Use DeviceInfo to group entities under a single device
- Follow HomeAssistant naming conventions and code style
