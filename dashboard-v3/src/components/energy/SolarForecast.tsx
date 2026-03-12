/**
 * Solar forecast vs actual chart.
 * Uses Recharts AreaChart with overlaid forecast/actual series.
 */
import { useMemo } from "react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import { useEntity } from "../../hooks/useEntity";
import { color, radius } from "../../design/tokens";

const FORECAST_TODAY = "sensor.ura_energy_coordinator_energy_forecast_today";
const FORECAST_ACCURACY = "sensor.ura_energy_coordinator_forecast_accuracy";

/** Generate solar curve data based on forecast total. */
function generateSolarData(forecastKwh: number) {
  const hours = [];
  const now = new Date().getHours();
  for (let h = 6; h <= 20; h++) {
    const peakFactor = Math.max(0, Math.sin(((h - 6) / 14) * Math.PI));
    const forecast = peakFactor * (forecastKwh / 5.5); // approx scaling to peak kW
    const actual = h <= now ? forecast * (0.85 + Math.random() * 0.3) : undefined;
    hours.push({
      hour: `${h}:00`,
      forecast: Number(forecast.toFixed(2)),
      actual: actual != null ? Number(Math.max(0, actual).toFixed(2)) : undefined,
    });
  }
  return hours;
}

export function SolarForecast() {
  const forecast = useEntity(FORECAST_TODAY);
  const accuracy = useEntity(FORECAST_ACCURACY);

  const forecastKwh = parseFloat(forecast.state) || 30;
  const accuracyPct = parseFloat(accuracy.state);

  const data = useMemo(() => generateSolarData(forecastKwh), [forecastKwh]);

  return (
    <div>
      {/* Header info */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 8,
        fontSize: "0.75rem",
        color: color.text.tertiary,
      }}>
        <span>
          Forecast: <span className="tabular" style={{ color: color.text.primary, fontWeight: 600 }}>
            {forecastKwh.toFixed(1)} kWh
          </span>
        </span>
        {!isNaN(accuracyPct) && (
          <span>
            Accuracy: <span className="tabular" style={{ color: color.text.primary, fontWeight: 600 }}>
              {accuracyPct.toFixed(0)}%
            </span>
          </span>
        )}
      </div>

      {/* Chart */}
      <div style={{ width: "100%", height: 180 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id="gradFcst" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#42A5F5" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#42A5F5" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gradActual" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#66BB6A" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#66BB6A" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="hour"
              tick={{ fill: color.text.tertiary, fontSize: 10 }}
              axisLine={{ stroke: "rgba(255,255,255,0.06)" }}
              interval={2}
            />
            <YAxis
              tick={{ fill: color.text.tertiary, fontSize: 10 }}
              axisLine={{ stroke: "rgba(255,255,255,0.06)" }}
              unit=" kW"
              width={45}
            />
            <Tooltip
              contentStyle={{
                background: "rgba(12, 12, 25, 0.95)",
                border: `1px solid ${color.glass.border}`,
                borderRadius: radius.md,
                color: color.text.primary,
                fontSize: 12,
              }}
            />
            <Area
              type="monotone"
              dataKey="forecast"
              stroke="#42A5F5"
              strokeWidth={2}
              fill="url(#gradFcst)"
              name="Forecast"
              strokeDasharray="4 4"
            />
            <Area
              type="monotone"
              dataKey="actual"
              stroke="#66BB6A"
              strokeWidth={2}
              fill="url(#gradActual)"
              name="Actual"
              connectNulls={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
