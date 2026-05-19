/**
 * Energy flow diagram showing Solar -> Battery -> Grid -> House.
 * Uses a simple SVG-based visual with animated flow indicators.
 */
import { useEntity, formatNumber } from "../../hooks/useEntity";
import { Sun, Battery, Zap, Home } from "lucide-react";
import { color, space, radius, type as typography } from "../../design/tokens";

const ENTITIES = {
  solarPower: "sensor.envoy_current_power_production",
  consumption: "sensor.envoy_current_power_consumption",
  batteryPower: "sensor.encharge_aggregate_power",
  batteryPercent: "sensor.encharge_aggregate_soc",
  gridPower: "sensor.envoy_net_power",
};

export function EnergyFlow() {
  const solar = useEntity(ENTITIES.solarPower);
  const consumption = useEntity(ENTITIES.consumption);
  const battery = useEntity(ENTITIES.batteryPower);
  const batteryPct = useEntity(ENTITIES.batteryPercent);
  const grid = useEntity(ENTITIES.gridPower);

  const solarW = parseFloat(solar.state) || 0;
  const consumW = parseFloat(consumption.state) || 0;
  const battW = parseFloat(battery.state) || 0;
  const battPct = parseFloat(batteryPct.state) || 0;
  const gridW = parseFloat(grid.state) || 0;

  // Determine flow directions
  const solarActive = solarW > 50;
  const battCharging = battW < -50;
  const battDischarging = battW > 50;
  const importing = gridW > 50;
  const exporting = gridW < -50;

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "1fr 1fr 1fr 1fr",
      gap: space.sm,
      alignItems: "center",
      padding: `${space.md}px 0`,
    }}>
      {/* Solar */}
      <FlowNode
        icon={<Sun size={22} />}
        label="Solar"
        value={`${(solarW / 1000).toFixed(1)} kW`}
        accentColor={solarActive ? color.status.yellow : color.text.disabled}
        active={solarActive}
      />

      {/* Battery */}
      <FlowNode
        icon={<Battery size={22} />}
        label="Battery"
        value={`${battPct.toFixed(0)}%`}
        subtitle={battCharging ? "Charging" : battDischarging ? "Discharging" : "Idle"}
        accentColor={battCharging ? color.status.blue : battDischarging ? color.status.green : color.text.disabled}
        active={battCharging || battDischarging}
      />

      {/* Grid */}
      <FlowNode
        icon={<Zap size={22} />}
        label="Grid"
        value={`${(Math.abs(gridW) / 1000).toFixed(1)} kW`}
        subtitle={importing ? "Importing" : exporting ? "Exporting" : "Neutral"}
        accentColor={importing ? color.status.red : exporting ? color.status.green : color.text.disabled}
        active={importing || exporting}
      />

      {/* House */}
      <FlowNode
        icon={<Home size={22} />}
        label="House"
        value={`${(consumW / 1000).toFixed(1)} kW`}
        accentColor={color.accent.primary}
        active={consumW > 100}
      />
    </div>
  );
}

function FlowNode({
  icon,
  label,
  value,
  subtitle,
  accentColor,
  active,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  subtitle?: string;
  accentColor: string;
  active: boolean;
}) {
  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: space.xs,
      padding: space.sm,
    }}>
      <div style={{
        width: 48,
        height: 48,
        borderRadius: radius.md,
        background: `${accentColor}14`,
        border: `1px solid ${accentColor}30`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: accentColor,
        transition: "all 200ms ease",
      }}>
        {icon}
      </div>
      <span className="tabular" style={{
        fontSize: typography.size.base,
        fontWeight: typography.weight.semibold,
        color: active ? color.text.primary : color.text.tertiary,
      }}>
        {value}
      </span>
      <span style={{
        fontSize: typography.size.xs,
        color: color.text.tertiary,
        textTransform: "uppercase",
        letterSpacing: "0.4px",
      }}>
        {label}
      </span>
      {subtitle && (
        <span style={{
          fontSize: "0.6rem",
          color: accentColor,
          fontWeight: typography.weight.medium,
        }}>
          {subtitle}
        </span>
      )}
    </div>
  );
}
