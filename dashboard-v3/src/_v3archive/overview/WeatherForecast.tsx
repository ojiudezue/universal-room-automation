/**
 * Compact weather display for the Overview tab.
 * Reads weather.* entity for current conditions and forecast.
 */
import { useMemo } from "react";
import { Cloud, Droplets, Wind, Thermometer } from "lucide-react";
import { useEntitiesByPrefix } from "../../hooks/useEntity";
import { color, space, type as typography } from "../../design/tokens";

export function WeatherForecast() {
  const weatherEntities = useEntitiesByPrefix("weather.");

  const weather = useMemo(() => {
    // Pick the first weather entity (usually weather.home or weather.forecast_home)
    const w = weatherEntities.find(
      (e) => !e.entity_id.includes("template") && e.state !== "unavailable"
    );
    if (!w) return null;

    const attrs = w.attributes;
    return {
      state: w.state,
      temp: attrs.temperature as number | undefined,
      humidity: attrs.humidity as number | undefined,
      windSpeed: attrs.wind_speed as number | undefined,
      tempUnit: (attrs.temperature_unit as string) ?? "F",
    };
  }, [weatherEntities]);

  if (!weather) {
    return (
      <div style={{ color: color.text.tertiary, fontSize: typography.size.sm }}>
        No weather data
      </div>
    );
  }

  const weatherIcon = getWeatherEmoji(weather.state);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: space.md }}>
      {/* Current conditions icon */}
      <div style={{
        fontSize: "1.8rem",
        lineHeight: 1,
        flexShrink: 0,
      }}>
        {weatherIcon}
      </div>

      {/* Temperature */}
      <div style={{ flexShrink: 0 }}>
        <div className="tabular" style={{
          fontSize: typography.size.xl,
          fontWeight: typography.weight.semibold,
          color: color.text.primary,
          lineHeight: 1.1,
        }}>
          {weather.temp != null ? `${Math.round(weather.temp)}` : "--"}
          <span style={{ fontSize: typography.size.sm, color: color.text.tertiary }}>
            {"\u00B0"}{weather.tempUnit}
          </span>
        </div>
        <div style={{
          fontSize: typography.size.sm,
          color: color.text.secondary,
          textTransform: "capitalize",
        }}>
          {weather.state.replace(/-/g, " ")}
        </div>
      </div>

      {/* Details */}
      <div style={{
        display: "flex",
        gap: space.md,
        marginLeft: "auto",
        fontSize: typography.size.sm,
        color: color.text.tertiary,
      }}>
        {weather.humidity != null && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <Droplets size={13} />
            {weather.humidity}%
          </span>
        )}
        {weather.windSpeed != null && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <Wind size={13} />
            {Math.round(weather.windSpeed)}mph
          </span>
        )}
      </div>
    </div>
  );
}

/** Map HA weather state to a simple text icon indicator. */
function getWeatherEmoji(state: string): string {
  const map: Record<string, string> = {
    sunny: "\u2600\uFE0F",
    "clear-night": "\u{1F319}",
    cloudy: "\u2601\uFE0F",
    partlycloudy: "\u26C5",
    rainy: "\u{1F327}\uFE0F",
    snowy: "\u{1F328}\uFE0F",
    "snowy-rainy": "\u{1F328}\uFE0F",
    windy: "\u{1F32C}\uFE0F",
    fog: "\u{1F32B}\uFE0F",
    hail: "\u{1F327}\uFE0F",
    lightning: "\u26A1",
    "lightning-rainy": "\u26A1",
    pouring: "\u{1F327}\uFE0F",
    exceptional: "\u26A0\uFE0F",
  };
  return map[state] ?? "\u{1F324}\uFE0F";
}
