/**
 * Anomaly and notification sensor list.
 */
import { useMemo } from "react";
import { AlertTriangle, Bell, CheckCircle, Heart } from "lucide-react";
import { useEntitiesByPrefix, formatState } from "../../hooks/useEntity";
import { color, space, radius, type as typography } from "../../design/tokens";

function healthColor(state: string): string {
  switch (state) {
    case "excellent":
    case "good":
      return color.status.green;
    case "fair":
      return color.status.yellow;
    case "poor":
      return color.status.orange;
    case "very_poor":
      return color.status.red;
    default:
      return color.text.disabled;
  }
}

function healthIcon(state: string) {
  switch (state) {
    case "excellent":
    case "good":
      return CheckCircle;
    case "fair":
    case "poor":
    case "very_poor":
      return AlertTriangle;
    default:
      return Heart;
  }
}

export function AnomalyList() {
  const allSensors = useEntitiesByPrefix("sensor.");

  // Automation health sensors
  const healthSensors = useMemo(
    () =>
      allSensors
        .filter((e) => e.entity_id.includes("automation_health"))
        .map((e) => ({
          id: e.entity_id,
          name: String(e.attributes.friendly_name ?? e.entity_id)
            .replace("URA ", "")
            .replace(" Automation Health", ""),
          state: e.state,
          lastUpdated: e.last_updated,
        })),
    [allSensors]
  );

  // Anomaly / notification sensors
  const anomalySensors = useMemo(
    () =>
      allSensors
        .filter(
          (e) =>
            e.entity_id.includes("anomaly") ||
            e.entity_id.includes("notification_manager")
        )
        .map((e) => ({
          id: e.entity_id,
          name: String(e.attributes.friendly_name ?? e.entity_id).replace("URA ", ""),
          state: e.state,
        })),
    [allSensors]
  );

  // Health summary
  const healthyCt = healthSensors.filter(
    (s) => s.state === "excellent" || s.state === "good"
  ).length;
  const fairCt = healthSensors.filter((s) => s.state === "fair").length;
  const poorCt = healthSensors.filter(
    (s) => s.state === "poor" || s.state === "very_poor"
  ).length;
  const totalCt = healthSensors.length;
  const healthPct = totalCt > 0 ? Math.round((healthyCt / totalCt) * 100) : 100;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      {/* Automation Health */}
      {healthSensors.length > 0 && (
        <div>
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: space.sm,
          }}>
            <span style={{
              fontSize: typography.size.xs,
              fontWeight: typography.weight.semibold,
              color: color.text.tertiary,
              textTransform: "uppercase",
              letterSpacing: "0.6px",
            }}>
              Automation Health
            </span>
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              fontSize: typography.size.sm,
              fontWeight: typography.weight.semibold,
              color: poorCt > 0 ? color.status.red : fairCt > 0 ? color.status.yellow : color.status.green,
            }}>
              <Heart size={13} />
              {healthyCt}/{totalCt} healthy
            </span>
          </div>

          {/* Health bar */}
          <div style={{
            width: "100%",
            height: 5,
            background: "rgba(255, 255, 255, 0.08)",
            borderRadius: 3,
            overflow: "hidden",
            marginBottom: space.sm,
          }}>
            <div style={{
              width: `${healthPct}%`,
              height: "100%",
              background: poorCt > 0 ? color.status.red : fairCt > 0 ? color.status.yellow : color.status.green,
              borderRadius: 3,
              transition: "width 500ms ease",
            }} />
          </div>

          {/* Health tile grid */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))",
            gap: space.xs,
          }}>
            {healthSensors.map((s) => {
              const Icon = healthIcon(s.state);
              const hc = healthColor(s.state);
              return (
                <div
                  key={s.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: space.sm,
                    padding: `${space.sm}px ${space.md}px`,
                    borderRadius: radius.sm,
                    background: "rgba(255, 255, 255, 0.03)",
                    borderLeft: `2px solid ${hc}`,
                  }}
                >
                  <Icon size={13} style={{ color: hc, flexShrink: 0 }} />
                  <span style={{
                    fontSize: typography.size.sm,
                    fontWeight: typography.weight.medium,
                    color: color.text.secondary,
                    flex: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {s.name}
                  </span>
                  {s.lastUpdated && (
                    <span style={{
                      fontSize: "0.6rem",
                      color: color.text.tertiary,
                      flexShrink: 0,
                    }}>
                      {new Date(s.lastUpdated).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Anomalies & Notifications */}
      {anomalySensors.length > 0 && (
        <div>
          <div style={{
            fontSize: typography.size.xs,
            fontWeight: typography.weight.semibold,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.6px",
            marginBottom: space.sm,
          }}>
            Notifications & Anomalies
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: space.sm,
          }}>
            {anomalySensors.map((s) => {
              const isAlert = parseFloat(s.state) > 0;
              return (
                <div
                  key={s.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: space.md,
                    padding: space.md,
                    borderRadius: radius.md,
                    background: isAlert ? "rgba(255, 167, 38, 0.06)" : "rgba(255, 255, 255, 0.03)",
                    border: `1px solid ${isAlert ? "rgba(255, 167, 38, 0.2)" : "rgba(255, 255, 255, 0.05)"}`,
                  }}
                >
                  <div style={{
                    width: 32,
                    height: 32,
                    borderRadius: radius.full,
                    background: isAlert ? "rgba(255, 167, 38, 0.15)" : "rgba(255, 255, 255, 0.06)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: isAlert ? color.status.orange : color.text.tertiary,
                    flexShrink: 0,
                  }}>
                    {s.name.toLowerCase().includes("anomaly")
                      ? <AlertTriangle size={15} />
                      : <Bell size={15} />}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{
                      fontSize: typography.size.sm,
                      fontWeight: typography.weight.medium,
                      color: color.text.secondary,
                    }}>
                      {s.name}
                    </div>
                    <div style={{
                      fontSize: typography.size.xs,
                      color: color.text.tertiary,
                      fontWeight: typography.weight.semibold,
                    }}>
                      {formatState(s.state)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
