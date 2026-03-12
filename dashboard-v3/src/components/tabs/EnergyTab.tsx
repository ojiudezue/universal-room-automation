/**
 * Energy tab -- solar, battery, grid, cost, forecast.
 * Compact information-dense layout with energy flow diagram.
 */
import { useEntity, formatNumber, formatState } from "../../hooks/useEntity";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";
import { EntityValue } from "../shared/EntityValue";
import { EnergyFlow } from "../energy/EnergyFlow";
import { SolarForecast } from "../energy/SolarForecast";
import { BatteryStatus } from "../energy/BatteryStatus";
import { CostTracker } from "../energy/CostTracker";
import { color, space, type as typography } from "../../design/tokens";

const ENTITIES = {
  situation: "sensor.ura_energy_coordinator_energy_situation",
  touPeriod: "sensor.ura_energy_coordinator_tou_period",
  touRate: "sensor.ura_energy_coordinator_tou_rate",
  touSeason: "sensor.ura_energy_coordinator_tou_season",
  solarClass: "sensor.ura_energy_coordinator_solar_day_class",
  forecastAccuracy: "sensor.ura_energy_coordinator_forecast_accuracy",
  envoy: "binary_sensor.ura_energy_coordinator_energy_envoy_available",
  hvacConstraint: "sensor.ura_energy_coordinator_hvac_constraint",
  loadShedding: "sensor.ura_energy_coordinator_load_shedding",
};

export function EnergyTab() {
  const situation = useEntity(ENTITIES.situation);
  const touPeriod = useEntity(ENTITIES.touPeriod);
  const touRate = useEntity(ENTITIES.touRate);
  const touSeason = useEntity(ENTITIES.touSeason);
  const solarClass = useEntity(ENTITIES.solarClass);
  const envoy = useEntity(ENTITIES.envoy);
  const hvacConstraint = useEntity(ENTITIES.hvacConstraint);
  const loadShedding = useEntity(ENTITIES.loadShedding);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Status bar */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: space.sm,
        flexWrap: "wrap",
      }}>
        <StatusBadge value={situation.state} size="md" />
        <StatusBadge value={touPeriod.state} />
        <StatusBadge value={solarClass.state} />
        <span className="tabular" style={{
          fontSize: typography.size.sm,
          color: color.text.tertiary,
          marginLeft: "auto",
        }}>
          {formatNumber(touRate.state, { prefix: "$", suffix: "/kWh" })}
          {" \u00B7 "}
          {formatState(touSeason.state)}
        </span>
      </div>

      {/* Energy Flow Diagram */}
      <GlassCard title="Power Flow">
        <EnergyFlow />
      </GlassCard>

      {/* Battery + Cost -- side by side */}
      <div
        className="energy-2col"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: space.md,
        }}
      >
        <GlassCard title="Battery">
          <BatteryStatus />
        </GlassCard>
        <GlassCard title="Cost">
          <CostTracker />
        </GlassCard>
      </div>

      {/* TOU + Constraints */}
      <div
        className="energy-2col"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: space.md,
        }}
      >
        <GlassCard title="TOU & Solar">
          <EntityValue label="Period" value={formatState(touPeriod.state)} inline />
          <EntityValue label="Rate" value={formatNumber(touRate.state, { prefix: "$", suffix: "/kWh" })} inline />
          <EntityValue label="Season" value={formatState(touSeason.state)} inline />
          <EntityValue label="Solar Class" value={formatState(solarClass.state)} inline />
          <EntityValue
            label="Envoy"
            value={envoy.state === "on" ? "Online" : "Offline"}
            accent={envoy.state === "on" ? color.status.green : color.status.red}
            inline
          />
        </GlassCard>

        <GlassCard title="Constraints">
          <div style={{ marginBottom: space.xs }}>
            <div style={{
              fontSize: typography.size.xs,
              color: color.text.tertiary,
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              marginBottom: 4,
            }}>
              HVAC Constraint
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
              <StatusBadge value={hvacConstraint.state} />
              <span style={{ fontSize: typography.size.sm, color: color.text.secondary }}>
                {formatState(String(hvacConstraint.attributes?.detail ?? hvacConstraint.state))}
              </span>
            </div>
          </div>
          <div>
            <div style={{
              fontSize: typography.size.xs,
              color: color.text.tertiary,
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              marginBottom: 4,
            }}>
              Load Shedding
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
              <StatusBadge value={loadShedding.state} />
              <span style={{ fontSize: typography.size.sm, color: color.text.secondary }}>
                {formatState(String(loadShedding.attributes?.detail ?? loadShedding.state))}
              </span>
            </div>
          </div>
        </GlassCard>
      </div>

      {/* Solar Forecast Chart */}
      <GlassCard title="Solar: Forecast vs Actual">
        <SolarForecast />
      </GlassCard>

      <style>{`
        @media (max-width: 700px) {
          .energy-2col { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}
