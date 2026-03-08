import { useEnergyData } from "../../hooks/useEnergyData";
import { CoordinatorCard } from "../layout/CoordinatorCard";
import { StatusBadge } from "../shared/StatusBadge";
import { EntityValue } from "../shared/EntityValue";
import type { CSSProperties } from "react";

const grid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
  gap: "16px",
};

const section: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "12px",
};

const sectionTitle: CSSProperties = {
  fontSize: "0.8rem",
  fontWeight: 600,
  color: "var(--ura-accent)",
  textTransform: "uppercase",
  letterSpacing: "0.5px",
  borderBottom: "1px solid var(--ura-card-border)",
  paddingBottom: "4px",
};

export function EnergyOverview() {
  const data = useEnergyData();
  const constraint = data.hvacConstraint.attributes as Record<string, unknown>;

  return (
    <CoordinatorCard
      title="Energy Coordinator"
      badge={<StatusBadge value={data.situation.state} />}
    >
      <div style={section}>
        <span style={sectionTitle}>Time of Use</span>
        <div style={grid}>
          <EntityValue label="Period" value={data.touPeriod.state} />
          <EntityValue label="Rate" value={data.touRate.state} unit="$/kWh" />
          <EntityValue label="Solar" value={data.solarClass.state} />
        </div>
      </div>

      <div style={section}>
        <span style={sectionTitle}>Battery</span>
        <div style={grid}>
          <EntityValue label="Strategy" value={data.batteryStrategy.state} />
          <EntityValue
            label="SOC"
            value={constraint.soc as string}
            unit="%"
          />
          <EntityValue
            label="Envoy"
            value={data.envoyAvailable.state === "on" ? "Online" : "Offline"}
            color={
              data.envoyAvailable.state === "on"
                ? "var(--ura-green)"
                : "var(--ura-red)"
            }
          />
        </div>
      </div>

      <div style={section}>
        <span style={sectionTitle}>HVAC Constraint</span>
        <div style={grid}>
          <EntityValue label="Mode" value={data.hvacConstraint.state} />
          <EntityValue
            label="Offset"
            value={constraint.offset as string}
            unit="F"
          />
          <EntityValue
            label="Forecast High"
            value={constraint.forecast_high_temp as string}
            unit="F"
          />
          <EntityValue
            label="Forecast Low"
            value={constraint.forecast_low_temp as string}
            unit="F"
          />
          <EntityValue
            label="Max Runtime"
            value={constraint.max_runtime_minutes as string}
            unit="min"
          />
        </div>
      </div>

      <div style={section}>
        <span style={sectionTitle}>Today</span>
        <div style={grid}>
          <EntityValue
            label="Import"
            value={data.importToday.state}
            unit="kWh"
          />
          <EntityValue
            label="Export"
            value={data.exportToday.state}
            unit="kWh"
          />
          <EntityValue
            label="Cost"
            value={data.costToday.state}
            unit="$"
          />
          <EntityValue
            label="Forecast"
            value={data.forecastToday.state}
            unit="kWh"
          />
        </div>
      </div>

      <div style={section}>
        <span style={sectionTitle}>Load Shedding</span>
        <StatusBadge value={data.loadShedding.state} />
      </div>
    </CoordinatorCard>
  );
}
