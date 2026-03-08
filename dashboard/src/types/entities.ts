/** URA entity ID constants for type-safe HAKit useEntity() calls. */

// Energy Coordinator
export const ENERGY = {
  TOU_PERIOD: "sensor.ura_energy_coordinator_tou_period",
  TOU_RATE: "sensor.ura_energy_coordinator_tou_rate",
  TOU_SEASON: "sensor.ura_energy_coordinator_tou_season",
  BATTERY_STRATEGY: "sensor.ura_energy_coordinator_battery_strategy",
  BATTERY_DECISION: "sensor.ura_energy_coordinator_battery_decision",
  SOLAR_DAY_CLASS: "sensor.ura_energy_coordinator_solar_day_class",
  HVAC_CONSTRAINT: "sensor.ura_energy_coordinator_hvac_constraint",
  LOAD_SHEDDING: "sensor.ura_energy_coordinator_load_shedding",
  ENERGY_SITUATION: "sensor.ura_energy_coordinator_energy_situation",
  IMPORT_TODAY: "sensor.ura_energy_coordinator_energy_import_today",
  EXPORT_TODAY: "sensor.ura_energy_coordinator_energy_export_today",
  COST_TODAY: "sensor.ura_energy_coordinator_energy_cost_today",
  COST_CYCLE: "sensor.ura_energy_coordinator_energy_cost_this_cycle",
  PREDICTED_BILL: "sensor.ura_energy_coordinator_predicted_bill",
  FORECAST_TODAY: "sensor.ura_energy_coordinator_energy_forecast_today",
  FORECAST_ACCURACY: "sensor.ura_energy_coordinator_forecast_accuracy",
  TOTAL_CONSUMPTION: "sensor.ura_energy_coordinator_total_consumption",
  NET_CONSUMPTION: "sensor.ura_energy_coordinator_net_consumption",
  ENVOY_AVAILABLE: "binary_sensor.ura_energy_coordinator_energy_envoy_available",
  ENABLED: "switch.ura_energy_coordinator_enabled",
} as const;

// HVAC Coordinator
export const HVAC = {
  MODE: "sensor.ura_hvac_coordinator_mode",
  ARRESTER_STATE: "sensor.ura_hvac_coordinator_override_arrester_state",
  ZONE_1_STATUS: "sensor.ura_hvac_coordinator_zone_1_status",
  ZONE_2_STATUS: "sensor.ura_hvac_coordinator_zone_2_status",
  ZONE_3_STATUS: "sensor.ura_hvac_coordinator_zone_3_status",
  ZONE_1_PRESET: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_1",
  ZONE_2_PRESET: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_2",
  ZONE_3_PRESET: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_3",
  ARRESTER_SWITCH: "switch.ura_hvac_coordinator_override_arrester",
  OBSERVATION_MODE: "switch.ura_hvac_coordinator_hvac_observation_mode",
  ENABLED: "switch.ura_hvac_coordinator_enabled",
} as const;

// Presence Coordinator
export const PRESENCE = {
  HOUSE_STATE: "sensor.ura_presence_coordinator_presence_house_state",
  ENABLED: "switch.ura_presence_coordinator_enabled",
} as const;

// Security Coordinator
export const SECURITY = {
  ARMED_STATE: "sensor.ura_security_coordinator_security_armed_state",
  OPEN_ENTRIES: "sensor.ura_security_coordinator_security_open_entries",
  LAST_LOCK_SWEEP: "sensor.ura_security_coordinator_security_last_lock_sweep",
  EXPECTED_ARRIVALS: "sensor.ura_security_coordinator_security_expected_arrivals",
  ENABLED: "switch.ura_security_coordinator_enabled",
} as const;

// Notification Manager
export const NOTIFICATIONS = {
  ANOMALY_COUNT: "sensor.ura_notification_manager_anomaly_count",
  DELIVERY_RATE: "sensor.ura_notification_manager_delivery_rate",
} as const;

// Music Following
export const MUSIC = {
  ENABLED: "switch.ura_music_following_enabled",
} as const;
