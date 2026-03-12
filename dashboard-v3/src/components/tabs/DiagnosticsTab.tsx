/**
 * Diagnostics tab -- coordinator health, anomalies, system info.
 */
import { useMemo } from "react";
import { Cpu, Settings, Activity, Power } from "lucide-react";
import { useHass } from "@hakit/core";
import { GlassCard } from "../layout/GlassCard";
import { CoordinatorHealth } from "../diagnostics/CoordinatorHealth";
import { AnomalyList } from "../diagnostics/AnomalyList";
import { color, space, radius, type as typography } from "../../design/tokens";

interface EntityLike {
  state: string;
  attributes: Record<string, unknown>;
}

export function DiagnosticsTab() {
  const { getAllEntities } = useHass();
  const allEntities = getAllEntities() as Record<string, EntityLike>;

  const systemInfo = useMemo(() => {
    const uraEntity = Object.entries(allEntities).find(([id]) => id.startsWith("sensor.ura_"));
    const uraVersion = uraEntity?.[1]?.attributes?.integration_version ?? "unknown";
    const uraEntityCount = Object.keys(allEntities).filter((id) => id.includes("ura_")).length;
    const totalEntities = Object.keys(allEntities).length;

    // Count active coordinators
    const coordSwitches = ["switch.ura_presence_coordinator_enabled", "switch.ura_energy_coordinator_enabled", "switch.ura_hvac_coordinator_enabled", "switch.ura_security_coordinator_enabled"];
    const activeCoords = coordSwitches.filter(
      (id) => (allEntities[id] as EntityLike | undefined)?.state === "on"
    ).length;

    return {
      version: String(uraVersion),
      uraEntities: uraEntityCount,
      totalEntities,
      activeCoords,
      totalCoords: coordSwitches.length,
    };
  }, [allEntities]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Header stats */}
      <div style={{
        display: "flex",
        gap: space.lg,
        flexWrap: "wrap",
        fontSize: typography.size.sm,
        color: color.text.tertiary,
      }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Cpu size={13} />
          URA v{systemInfo.version}
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Settings size={13} />
          {systemInfo.uraEntities} URA entities
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Power size={13} />
          {systemInfo.activeCoords}/{systemInfo.totalCoords} coordinators active
        </span>
      </div>

      {/* Coordinator Cards */}
      <CoordinatorHealth />

      {/* Automation Health + Anomalies */}
      <GlassCard title="Health & Anomalies">
        <AnomalyList />
      </GlassCard>

      {/* System Info */}
      <GlassCard title="System">
        <div
          className="sys-grid"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, 1fr)",
            gap: space.sm,
          }}
        >
          <SystemItem icon={<Cpu size={14} />} label="Integration" value={`v${systemInfo.version}`} />
          <SystemItem icon={<Settings size={14} />} label="Dashboard" value="v3.0" />
          <SystemItem icon={<Activity size={14} />} label="URA Entities" value={String(systemInfo.uraEntities)} />
          <SystemItem icon={<Power size={14} />} label="Total HA Entities" value={String(systemInfo.totalEntities)} />
        </div>
        <style>{`
          @media (max-width: 500px) {
            .sys-grid { grid-template-columns: 1fr !important; }
          }
        `}</style>
      </GlassCard>
    </div>
  );
}

function SystemItem({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: space.md,
      padding: space.md,
      borderRadius: radius.md,
      background: "rgba(255, 255, 255, 0.03)",
      color: color.text.tertiary,
    }}>
      {icon}
      <div style={{ display: "flex", flexDirection: "column" }}>
        <span style={{
          fontSize: typography.size.xs,
          color: color.text.tertiary,
          textTransform: "uppercase",
          letterSpacing: "0.4px",
        }}>
          {label}
        </span>
        <span className="tabular" style={{
          fontSize: typography.size.base,
          fontWeight: typography.weight.semibold,
          color: color.text.primary,
        }}>
          {value}
        </span>
      </div>
    </div>
  );
}
