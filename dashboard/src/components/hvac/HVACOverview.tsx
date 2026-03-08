import { useHVACData } from "../../hooks/useHVACData";
import { CoordinatorCard } from "../layout/CoordinatorCard";
import { StatusBadge } from "../shared/StatusBadge";
import { EntityValue } from "../shared/EntityValue";
import type { CSSProperties } from "react";

const zoneGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
  gap: "12px",
};

const zoneCard: CSSProperties = {
  background: "rgba(255,255,255,0.03)",
  borderRadius: "8px",
  padding: "12px",
  display: "flex",
  flexDirection: "column",
  gap: "8px",
};

const zoneHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  fontSize: "0.9rem",
  fontWeight: 600,
};

const metricsRow: CSSProperties = {
  display: "flex",
  gap: "16px",
  flexWrap: "wrap",
};

export function HVACOverview() {
  const data = useHVACData();
  const arresterAttrs = data.arresterState.attributes as Record<
    string,
    unknown
  >;

  return (
    <CoordinatorCard
      title="HVAC Coordinator"
      badge={<StatusBadge value={data.mode.state} />}
    >
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        <EntityValue label="Arrester" value={data.arresterState.state} />
        <EntityValue
          label="Energy Coast"
          value={(arresterAttrs.energy_coast as boolean) ? "Yes" : "No"}
        />
        <EntityValue
          label="Energy Offset"
          value={arresterAttrs.energy_offset as string}
          unit="F"
        />
      </div>

      <div style={zoneGrid}>
        {data.zones.map((zone, i) => {
          const presetAttrs = zone.preset.attributes as Record<
            string,
            unknown
          >;
          return (
            <div key={i} style={zoneCard}>
              <div style={zoneHeader}>
                <span>{(presetAttrs.zone_name as string) ?? `Zone ${i + 1}`}</span>
                <StatusBadge value={zone.preset.state} />
              </div>
              <div style={metricsRow}>
                <EntityValue
                  label="Mode"
                  value={zone.status.state}
                />
                <EntityValue
                  label="Temp"
                  value={presetAttrs.current_temperature as string}
                  unit="F"
                />
                <EntityValue
                  label="High"
                  value={presetAttrs.target_temp_high as string}
                  unit="F"
                />
                <EntityValue
                  label="Low"
                  value={presetAttrs.target_temp_low as string}
                  unit="F"
                />
              </div>
              <div style={{ fontSize: "0.75rem", color: "var(--ura-text-dim)" }}>
                {presetAttrs.hvac_action as string} | Overrides: {presetAttrs.overrides_today as string ?? "0"}
              </div>
            </div>
          );
        })}
      </div>
    </CoordinatorCard>
  );
}
