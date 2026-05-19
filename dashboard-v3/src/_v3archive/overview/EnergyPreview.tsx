/**
 * Compact energy preview for the Overview tab.
 * Shows solar, cost, battery, and predicted bill in a tight grid.
 */
import { useEntity, formatNumber } from "../../hooks/useEntity";
import { EntityValue } from "../shared/EntityValue";
import { StatusBadge } from "../shared/StatusBadge";
import { color, space } from "../../design/tokens";
import { Zap, Sun, Battery, DollarSign } from "lucide-react";

const ENERGY = {
  SITUATION: "sensor.ura_energy_coordinator_energy_situation",
  COST_TODAY: "sensor.ura_energy_coordinator_energy_cost_today",
  PREDICTED_BILL: "sensor.ura_energy_coordinator_predicted_bill",
  SOLAR_CLASS: "sensor.ura_energy_coordinator_solar_day_class",
  BATTERY_STRATEGY: "sensor.ura_energy_coordinator_battery_strategy",
  IMPORT_TODAY: "sensor.ura_energy_coordinator_energy_import_today",
  EXPORT_TODAY: "sensor.ura_energy_coordinator_energy_export_today",
  FORECAST_TODAY: "sensor.ura_energy_coordinator_energy_forecast_today",
  TOU_PERIOD: "sensor.ura_energy_coordinator_tou_period",
  TOU_RATE: "sensor.ura_energy_coordinator_tou_rate",
};

export function EnergyPreview() {
  const situation = useEntity(ENERGY.SITUATION);
  const costToday = useEntity(ENERGY.COST_TODAY);
  const predictedBill = useEntity(ENERGY.PREDICTED_BILL);
  const solarClass = useEntity(ENERGY.SOLAR_CLASS);
  const battery = useEntity(ENERGY.BATTERY_STRATEGY);
  const importToday = useEntity(ENERGY.IMPORT_TODAY);
  const exportToday = useEntity(ENERGY.EXPORT_TODAY);
  const forecastToday = useEntity(ENERGY.FORECAST_TODAY);
  const touPeriod = useEntity(ENERGY.TOU_PERIOD);
  const touRate = useEntity(ENERGY.TOU_RATE);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
      {/* Top row: key metrics */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: space.sm,
      }}>
        <EntityValue label="Cost Today" value={formatNumber(costToday.state, { prefix: "$" })} />
        <EntityValue label="Pred. Bill" value={formatNumber(predictedBill.state, { prefix: "$" })} accent={color.accent.primary} />
        <EntityValue label="Solar Fcst" value={formatNumber(forecastToday.state, { suffix: " kWh" })} />
        <EntityValue label="Export" value={formatNumber(exportToday.state, { suffix: " kWh" })} />
      </div>

      {/* Bottom row: status badges */}
      <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap", alignItems: "center" }}>
        <StatusBadge value={situation.state} />
        <StatusBadge value={touPeriod.state} />
        <StatusBadge value={solarClass.state} />
        <StatusBadge value={battery.state} />
        <span className="tabular" style={{
          fontSize: "0.75rem",
          color: color.text.tertiary,
          marginLeft: "auto",
        }}>
          {formatNumber(touRate.state, { prefix: "$", suffix: "/kWh" })}
        </span>
      </div>
    </div>
  );
}
