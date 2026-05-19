/**
 * Room transitions + zone occupancy display.
 */
import { useMemo } from "react";
import { ArrowRight, MapPin } from "lucide-react";
import { useEntity, timeAgo } from "../../hooks/useEntity";
import { color, space, radius, type as typography } from "../../design/tokens";

const HOUSE_STATE_ID = "sensor.ura_presence_coordinator_presence_house_state";

export function RoomTransitions() {
  const houseState = useEntity(HOUSE_STATE_ID);
  const attrs = houseState.attributes as Record<string, unknown>;

  const zoneOccupancy = useMemo(
    () => (attrs.zone_occupancy ?? attrs.zones ?? {}) as Record<string, number | string>,
    [attrs]
  );

  const transitions = useMemo(
    () =>
      ((attrs.recent_transitions ?? []) as Array<{
        person?: string;
        from?: string;
        to?: string;
        time?: string;
      }>).slice(0, 6),
    [attrs]
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Zone Occupancy Grid */}
      {Object.keys(zoneOccupancy).length > 0 && (
        <div>
          <div style={{
            fontSize: typography.size.xs,
            fontWeight: typography.weight.semibold,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.6px",
            marginBottom: space.sm,
          }}>
            Zone Occupancy
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(80px, 1fr))",
            gap: space.xs,
          }}>
            {Object.entries(zoneOccupancy).map(([zone, count]) => {
              const occupied = Number(count) > 0;
              return (
                <div
                  key={zone}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 2,
                    padding: `${space.sm}px ${space.xs}px`,
                    borderRadius: radius.md,
                    background: occupied ? "rgba(102, 187, 106, 0.1)" : "rgba(255, 255, 255, 0.03)",
                    border: `1px solid ${occupied ? "rgba(102, 187, 106, 0.2)" : "rgba(255, 255, 255, 0.04)"}`,
                  }}
                >
                  <span
                    className="tabular"
                    style={{
                      fontSize: typography.size.lg,
                      fontWeight: typography.weight.semibold,
                      color: occupied ? color.status.green : color.text.tertiary,
                    }}
                  >
                    {count}
                  </span>
                  <span style={{
                    fontSize: "0.6rem",
                    fontWeight: typography.weight.medium,
                    color: color.text.tertiary,
                    textTransform: "uppercase",
                    letterSpacing: "0.3px",
                    textAlign: "center",
                  }}>
                    {String(zone).replace(/_/g, " ")}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Recent Transitions */}
      {transitions.length > 0 && (
        <div>
          <div style={{
            fontSize: typography.size.xs,
            fontWeight: typography.weight.semibold,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.6px",
            marginBottom: space.sm,
          }}>
            Recent Transitions
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {transitions.map((t, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: space.sm,
                  padding: `${space.xs}px ${space.sm}px`,
                  fontSize: typography.size.sm,
                  color: color.text.secondary,
                }}
              >
                <span style={{ fontWeight: typography.weight.medium, minWidth: 60 }}>
                  {t.person}
                </span>
                <span style={{ color: color.text.tertiary }}>{t.from}</span>
                <ArrowRight size={10} style={{ color: color.text.tertiary }} />
                <span style={{ color: color.text.primary }}>{t.to}</span>
                {t.time && (
                  <span style={{
                    marginLeft: "auto",
                    fontSize: typography.size.xs,
                    color: color.text.tertiary,
                    flexShrink: 0,
                  }}>
                    {timeAgo(t.time)}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
