import { usePresenceData } from "../../hooks/usePresenceData";
import { CoordinatorCard } from "../layout/CoordinatorCard";
import { StatusBadge } from "../shared/StatusBadge";
import type { CSSProperties } from "react";

const zoneList: CSSProperties = {
  display: "flex",
  gap: "8px",
  flexWrap: "wrap",
};

const zoneChip: CSSProperties = {
  padding: "4px 10px",
  borderRadius: "8px",
  fontSize: "0.8rem",
  fontWeight: 500,
};

export function PresenceOverview() {
  const { houseState } = usePresenceData();
  const attrs = houseState.attributes as Record<string, unknown>;
  const zones = (attrs.zones ?? {}) as Record<string, string>;

  return (
    <CoordinatorCard
      title="Presence"
      badge={<StatusBadge value={houseState.state} />}
    >
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", fontSize: "0.85rem", color: "var(--ura-text-dim)" }}>
        <span>Confidence: {attrs.confidence as string}%</span>
        <span>Census: {attrs.census_count as string}</span>
        <span>Previous: {(attrs.previous_state as string)?.replace(/_/g, " ")}</span>
      </div>

      <div style={zoneList}>
        {Object.entries(zones).map(([name, status]) => (
          <span
            key={name}
            style={{
              ...zoneChip,
              background:
                status === "occupied"
                  ? "var(--ura-green)"
                  : "rgba(255,255,255,0.08)",
              color: status === "occupied" ? "#fff" : "var(--ura-text-dim)",
            }}
          >
            {name}
          </span>
        ))}
      </div>
    </CoordinatorCard>
  );
}
