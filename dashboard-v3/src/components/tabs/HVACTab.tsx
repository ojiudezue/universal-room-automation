/**
 * HVAC tab -- zone status, presets, arrester controls, constraints,
 * zone intelligence summary.
 */
import { useEntity, formatState } from "../../hooks/useEntity";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";
import { Toggle } from "../shared/Toggle";
import { EntityValue } from "../shared/EntityValue";
import { ZoneCard } from "../hvac/ZoneCard";
import { PresetStatus } from "../hvac/PresetStatus";
import { color, space, radius, type as typography } from "../../design/tokens";
import { Brain, Thermometer } from "lucide-react";

/**
 * Zone display order matches physical thermostat zone numbers:
 *   Zone 1 = climate.thermostat_bryant_wifi_studyb_zone_1 → URA zone_2
 *   Zone 2 = climate.up_hallway_zone_2                    → URA zone_3
 *   Zone 3 = climate.back_hallway_zone_3                  → URA zone_1
 */
const ZONES = [
  {
    name: "Zone 1 (Entertainment)",
    statusId: "sensor.ura_hvac_coordinator_zone_2_status",
    presetId: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_2",
  },
  {
    name: "Zone 2 (Upstairs)",
    statusId: "sensor.ura_hvac_coordinator_zone_3_status",
    presetId: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_3",
  },
  {
    name: "Zone 3 (Back Hallway)",
    statusId: "sensor.ura_hvac_coordinator_zone_1_status",
    presetId: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_1",
  },
];

export function HVACTab() {
  const mode = useEntity("sensor.ura_hvac_coordinator_mode");
  const hvacConstraint = useEntity("sensor.ura_energy_coordinator_hvac_constraint");
  const outdoorTemp = useEntity("sensor.patio_temperature");
  const ziSensor = useEntity("sensor.ura_hvac_coordinator_hvac_zone_intelligence");
  const ziSwitch = useEntity("switch.ura_hvac_coordinator_zone_intelligence");

  const ziAttrs = ziSensor.attributes as Record<string, unknown>;
  const zonesOccupied = (ziAttrs.zones_occupied ?? 0) as number;
  const zonesAwayOverride = (ziAttrs.zones_away_override ?? []) as string[];
  const zonesPreArrival = (ziAttrs.zones_pre_arrival ?? []) as string[];
  const zonesSolarBanking = (ziAttrs.zones_solar_banking ?? []) as string[];
  const zonesRuntimeLimited = (ziAttrs.zones_runtime_limited ?? []) as string[];
  const vacancySweeps = (ziAttrs.total_vacancy_sweeps_today ?? 0) as number;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Enhanced Header */}
      <div style={headerStyle}>
        <div style={headerLeftStyle}>
          <StatusBadge value={mode.state} size="md" />
          {hvacConstraint.state !== "unavailable" && hvacConstraint.state !== "unknown" && (
            <StatusBadge value={hvacConstraint.state} label={`Constraint: ${formatState(hvacConstraint.state)}`} size="md" />
          )}
        </div>
        <div style={headerRightStyle}>
          {outdoorTemp.state !== "unavailable" && (
            <span style={headerMetricStyle}>
              <Thermometer size={13} />
              {outdoorTemp.state}&deg;F outdoor
            </span>
          )}
          <span style={headerMetricStyle}>
            <Brain size={13} />
            ZI: {ziSwitch.state === "on" ? "Active" : "Off"}
          </span>
          <span style={headerMetricStyle}>
            {ZONES.length} zones
          </span>
        </div>
      </div>

      {/* Zone Intelligence Card */}
      <GlassCard
        title="Zone Intelligence"
        accent={ziSwitch.state === "on" ? color.accent.primary : color.text.disabled}
        actions={
          <Toggle
            entityId="switch.ura_hvac_coordinator_zone_intelligence"
            currentState={ziSwitch.state}
            size="sm"
          />
        }
      >
        {/* Summary row */}
        <div style={ziSummaryRowStyle}>
          <EntityValue label="Occupied" value={zonesOccupied} />
          <EntityValue label="Away Override" value={zonesAwayOverride.length} />
          <EntityValue label="Vacancy Sweeps" value={vacancySweeps} />
        </div>

        {/* Conditional detail rows */}
        {zonesPreArrival.length > 0 && (
          <div style={ziDetailRowStyle}>
            <StatusBadge value="active" label="Pre-Arrival" />
            <span style={ziDetailTextStyle}>{zonesPreArrival.join(", ")}</span>
          </div>
        )}
        {zonesSolarBanking.length > 0 && (
          <div style={ziDetailRowStyle}>
            <StatusBadge value="mid_peak" label="Solar Banking" />
            <span style={ziDetailTextStyle}>{zonesSolarBanking.join(", ")}</span>
          </div>
        )}
        {zonesRuntimeLimited.length > 0 && (
          <div style={ziDetailRowStyle}>
            <StatusBadge value="shed" label="Runtime Limited" />
            <span style={ziDetailTextStyle}>{zonesRuntimeLimited.join(", ")}</span>
          </div>
        )}
      </GlassCard>

      {/* Controls + Constraints */}
      <GlassCard title="Controls & Constraints">
        <PresetStatus />
      </GlassCard>

      {/* Zone Cards */}
      <div
        className="hvac-zones"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: space.md,
        }}
      >
        {ZONES.map((z) => (
          <ZoneCard key={z.name} {...z} />
        ))}
      </div>

      <style>{`
        @media (max-width: 900px) {
          .hvac-zones { grid-template-columns: repeat(2, 1fr) !important; }
        }
        @media (max-width: 600px) {
          .hvac-zones { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

// Extracted static styles
const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  flexWrap: "wrap",
  gap: space.sm,
};

const headerLeftStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: space.sm,
};

const headerRightStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: space.lg,
  flexWrap: "wrap",
};

const headerMetricStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  fontSize: typography.size.sm,
  color: color.text.tertiary,
};

const ziSummaryRowStyle: React.CSSProperties = {
  display: "flex",
  gap: space.xl,
  flexWrap: "wrap",
};

const ziDetailRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: space.sm,
  paddingTop: space.xs,
  borderTop: `1px solid rgba(255, 255, 255, 0.04)`,
};

const ziDetailTextStyle: React.CSSProperties = {
  fontSize: typography.size.sm,
  color: color.text.secondary,
};
