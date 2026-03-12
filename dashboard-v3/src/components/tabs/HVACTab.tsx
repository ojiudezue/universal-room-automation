/**
 * HVAC tab -- zone status, presets, arrester controls, constraints.
 */
import { useEntity } from "../../hooks/useEntity";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";
import { ZoneCard } from "../hvac/ZoneCard";
import { PresetStatus } from "../hvac/PresetStatus";
import { color, space, type as typography } from "../../design/tokens";

const ZONES = [
  {
    name: "Zone 1 (Entertainment)",
    statusId: "sensor.ura_hvac_coordinator_zone_1_status",
    presetId: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_1",
  },
  {
    name: "Zone 2 (Upstairs)",
    statusId: "sensor.ura_hvac_coordinator_zone_2_status",
    presetId: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_2",
  },
  {
    name: "Zone 3 (Back Hallway)",
    statusId: "sensor.ura_hvac_coordinator_zone_3_status",
    presetId: "sensor.ura_hvac_coordinator_hvac_zone_preset_zone_3",
  },
];

export function HVACTab() {
  const mode = useEntity("sensor.ura_hvac_coordinator_mode");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: space.md,
      }}>
        <StatusBadge value={mode.state} size="md" />
        <span style={{
          fontSize: typography.size.sm,
          color: color.text.tertiary,
        }}>
          {ZONES.length} zones configured
        </span>
      </div>

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
