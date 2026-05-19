/**
 * Overview tab -- the landing page.
 * Compact layout showing house mode, presence, energy preview,
 * weather, and coordinator status at a glance.
 * Active controls: coordinator toggles, quick actions.
 */
import { useMemo } from "react";
import { useEntity, useEntitiesByPrefix, formatState } from "../../hooks/useEntity";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";
import { Toggle } from "../shared/Toggle";
import { HouseMode } from "../overview/HouseMode";
import { PresenceSummary } from "../overview/PresenceSummary";
import { EnergyPreview } from "../overview/EnergyPreview";
import { WeatherForecast } from "../overview/WeatherForecast";
import { color, space } from "../../design/tokens";
import {
  Eye, Zap, Thermometer, Shield, Activity, Bell,
} from "lucide-react";

const COORDINATORS = [
  { name: "Presence", enabledId: "switch.ura_presence_coordinator_enabled", stateId: "sensor.ura_presence_coordinator_presence_house_state", icon: Eye, color: color.status.green },
  { name: "Energy", enabledId: "switch.ura_energy_coordinator_enabled", stateId: "sensor.ura_energy_coordinator_energy_situation", icon: Zap, color: color.status.yellow },
  { name: "HVAC", enabledId: "switch.ura_hvac_coordinator_enabled", stateId: "sensor.ura_hvac_coordinator_mode", icon: Thermometer, color: color.status.blue },
  { name: "Security", enabledId: "switch.ura_security_coordinator_enabled", stateId: "sensor.ura_security_coordinator_security_armed_state", icon: Shield, color: color.status.red },
];

const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, 1fr)",
  gap: space.md,
};

const responsiveGrid = `
  @media (max-width: 600px) {
    .ov-grid-2 { grid-template-columns: 1fr !important; }
  }
`;

export function OverviewTab() {
  const healthSensors = useEntitiesByPrefix("sensor.ura_");

  // Count healthy rooms from automation_health sensors
  const healthStats = useMemo(() => {
    const ahSensors = healthSensors.filter(
      (e) => e.entity_id.includes("automation_health")
    );
    const healthy = ahSensors.filter(
      (e) => e.state === "excellent" || e.state === "good"
    ).length;
    return { total: ahSensors.length, healthy };
  }, [healthSensors]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      <style>{responsiveGrid}</style>

      {/* House Mode + Weather -- side by side */}
      <div className="ov-grid-2" style={gridStyle}>
        <GlassCard>
          <HouseMode />
        </GlassCard>
        <GlassCard title="Weather">
          <WeatherForecast />
        </GlassCard>
      </div>

      {/* Presence Summary */}
      <GlassCard title="Presence">
        <PresenceSummary />
      </GlassCard>

      {/* Energy Preview */}
      <GlassCard title="Energy">
        <EnergyPreview />
      </GlassCard>

      {/* Coordinator Status Grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
        gap: space.sm,
      }}>
        {COORDINATORS.map((c) => (
          <CoordinatorChip key={c.name} {...c} />
        ))}
      </div>

      {/* Quick stats bar */}
      <div style={{
        display: "flex",
        gap: space.md,
        flexWrap: "wrap",
        fontSize: "0.78rem",
        color: color.text.tertiary,
        padding: `0 ${space.xs}px`,
      }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Activity size={12} />
          {healthStats.healthy}/{healthStats.total} rooms healthy
        </span>
      </div>
    </div>
  );
}

/**
 * Compact coordinator status chip with inline toggle.
 */
function CoordinatorChip({
  name,
  enabledId,
  stateId,
  icon: Icon,
  color: accentColor,
}: {
  name: string;
  enabledId: string;
  stateId: string;
  icon: React.FC<{ size?: number }>;
  color: string;
}) {
  const enabled = useEntity(enabledId);
  const state = useEntity(stateId);
  const isOn = enabled.state === "on";

  return (
    <div
      style={{
        background: color.glass.bg,
        border: `1px solid ${color.glass.border}`,
        borderLeft: `3px solid ${isOn ? accentColor : color.text.disabled}`,
        borderRadius: 10,
        padding: `${space.sm}px ${space.md}px`,
        display: "flex",
        alignItems: "center",
        gap: space.sm,
        opacity: isOn ? 1 : 0.5,
        transition: "opacity 200ms ease",
      }}
    >
      <Icon size={16} style={{ color: isOn ? accentColor : color.text.disabled, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: "0.78rem",
          fontWeight: 600,
          color: color.text.primary,
        }}>
          {name}
        </div>
        <div style={{ marginTop: 1 }}>
          <StatusBadge value={state.state} />
        </div>
      </div>
      <Toggle
        entityId={enabledId}
        currentState={enabled.state}
        size="sm"
      />
    </div>
  );
}
