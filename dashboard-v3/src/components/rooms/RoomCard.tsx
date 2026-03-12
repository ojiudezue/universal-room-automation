/**
 * Room card: compact header with key info, expandable for device controls.
 * Always shows: room name, health dot, occupancy icon, light count, temperature.
 * Expanded: light toggles, climate details.
 */
import { useState, useCallback } from "react";
import {
  Lightbulb, LightbulbOff, Thermometer, Activity,
  ChevronDown, ChevronUp,
} from "lucide-react";
import { formatState } from "../../hooks/useEntity";
import { useServiceCall } from "../../hooks/useService";
import { StatusBadge } from "../shared/StatusBadge";
import { color, space, radius, timing, type as typography } from "../../design/tokens";

interface LightData {
  id: string;
  name: string;
  state: string;
  brightness?: number;
}

interface ClimateData {
  id: string;
  name: string;
  state: string;
  currentTemp?: number;
  targetTemp?: number;
  hvacAction?: string;
}

interface Props {
  name: string;
  displayName: string;
  health: string;
  lights: LightData[];
  climate: ClimateData[];
  motionActive: boolean;
}

const healthColorMap: Record<string, string> = {
  excellent: color.status.green,
  good: color.status.green,
  ok: color.status.green,
  fair: color.status.yellow,
  poor: color.status.orange,
  very_poor: color.status.red,
};

export function RoomCard({ name, displayName, health, lights, climate, motionActive }: Props) {
  const [expanded, setExpanded] = useState(false);
  const { call } = useServiceCall();
  const healthColor = healthColorMap[health] ?? color.text.disabled;
  const lightsOn = lights.filter((l) => l.state === "on").length;
  const primaryClimate = climate[0];

  const toggleLight = useCallback(
    (entityId: string, currentState: string) => {
      call({
        domain: "light",
        service: currentState === "on" ? "turn_off" : "turn_on",
        target: { entity_id: entityId },
      });
    },
    [call]
  );

  return (
    <div
      style={{
        background: color.glass.bg,
        backdropFilter: color.glass.blur,
        WebkitBackdropFilter: color.glass.blur,
        border: `1px solid ${color.glass.border}`,
        borderLeft: `3px solid ${healthColor}`,
        borderRadius: radius.lg,
        overflow: "hidden",
      }}
    >
      {/* Header -- always visible */}
      <button
        style={{
          width: "100%",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: `${space.md}px`,
          cursor: "pointer",
          background: "none",
          border: "none",
          color: "inherit",
          fontFamily: "inherit",
          textAlign: "left",
          transition: `background ${timing.fast}`,
          minHeight: 44,
        }}
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-label={`${displayName} room controls`}
      >
        <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
          {/* Health dot */}
          <div style={{
            width: 8,
            height: 8,
            borderRadius: radius.full,
            background: healthColor,
            flexShrink: 0,
          }} />
          {/* Room name */}
          <span style={{
            fontSize: typography.size.base,
            fontWeight: typography.weight.semibold,
            color: color.text.primary,
          }}>
            {displayName}
          </span>
          {/* Motion indicator */}
          {motionActive && (
            <Activity
              size={12}
              style={{ color: color.status.green }}
              className="animate-pulse-glow"
            />
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
          {/* Light count chip */}
          {lightsOn > 0 && (
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              padding: "2px 8px",
              borderRadius: radius.sm,
              background: "rgba(255, 202, 40, 0.12)",
              color: color.status.yellow,
              fontSize: typography.size.xs,
              fontWeight: typography.weight.semibold,
            }}>
              <Lightbulb size={11} />
              {lightsOn}
            </span>
          )}
          {/* Temperature chip */}
          {primaryClimate?.currentTemp != null && (
            <span className="tabular" style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              padding: "2px 8px",
              borderRadius: radius.sm,
              background: "rgba(255, 255, 255, 0.05)",
              color: color.text.secondary,
              fontSize: typography.size.xs,
              fontWeight: typography.weight.semibold,
            }}>
              <Thermometer size={11} />
              {primaryClimate.currentTemp}&deg;
            </span>
          )}
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div style={{
          padding: `0 ${space.md}px ${space.md}px`,
          display: "flex",
          flexDirection: "column",
          gap: space.md,
          borderTop: `1px solid rgba(255, 255, 255, 0.04)`,
        }}>
          {/* Lights */}
          {lights.length > 0 && (
            <div>
              <div style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: typography.size.xs,
                fontWeight: typography.weight.semibold,
                color: color.text.tertiary,
                textTransform: "uppercase",
                letterSpacing: "0.6px",
                padding: `${space.sm}px 0 ${space.xs}px`,
              }}>
                <Lightbulb size={12} />
                Lights ({lightsOn}/{lights.length})
              </div>
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(90px, 1fr))",
                gap: space.xs,
              }}>
                {lights.map((l) => {
                  const isOn = l.state === "on";
                  const shortName = l.name
                    .replace(new RegExp(name.split("_").filter((w) => w.length > 2).join("|"), "gi"), "")
                    .replace(/^[\s_-]+|[\s_-]+$/g, "")
                    .replace(/_/g, " ")
                    .trim() || l.name.replace(/_/g, " ");

                  return (
                    <button
                      key={l.id}
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        gap: 4,
                        padding: `${space.sm}px ${space.xs}px`,
                        border: `1px solid ${isOn ? "rgba(255, 202, 40, 0.2)" : "rgba(255, 255, 255, 0.05)"}`,
                        borderRadius: radius.md,
                        background: isOn ? "rgba(255, 202, 40, 0.1)" : "rgba(255, 255, 255, 0.03)",
                        color: isOn ? color.status.yellow : color.text.tertiary,
                        cursor: "pointer",
                        fontFamily: "inherit",
                        transition: `all ${timing.fast}`,
                        minHeight: 44,
                        minWidth: 44,
                      }}
                      onClick={() => toggleLight(l.id, l.state)}
                      aria-label={`Toggle ${l.name}`}
                    >
                      {isOn ? <Lightbulb size={16} /> : <LightbulbOff size={16} />}
                      <span style={{
                        fontSize: "0.65rem",
                        fontWeight: typography.weight.medium,
                        textAlign: "center",
                        lineHeight: 1.2,
                        maxWidth: 72,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical",
                      }}>
                        {shortName}
                      </span>
                      {l.brightness != null && isOn && (
                        <span className="tabular" style={{
                          fontSize: "0.6rem",
                          color: "rgba(255, 202, 40, 0.7)",
                        }}>
                          {Math.round((l.brightness / 255) * 100)}%
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Climate */}
          {climate.map((c) => (
            <div key={c.id}>
              <div style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: typography.size.xs,
                fontWeight: typography.weight.semibold,
                color: color.text.tertiary,
                textTransform: "uppercase",
                letterSpacing: "0.6px",
                paddingBottom: space.xs,
              }}>
                <Thermometer size={12} />
                Thermostat
              </div>
              <div style={{
                display: "flex",
                alignItems: "center",
                gap: space.lg,
                padding: space.md,
                borderRadius: radius.md,
                background: "rgba(255, 255, 255, 0.03)",
              }}>
                {c.currentTemp != null && (
                  <div style={{ textAlign: "center", minWidth: 50 }}>
                    <div className="tabular" style={{
                      fontSize: typography.size["2xl"],
                      fontWeight: typography.weight.regular,
                      color: color.text.primary,
                      lineHeight: 1,
                    }}>
                      {c.currentTemp}&deg;
                    </div>
                    <div style={{
                      fontSize: "0.6rem",
                      color: color.text.tertiary,
                      textTransform: "uppercase",
                      letterSpacing: "0.3px",
                    }}>
                      current
                    </div>
                  </div>
                )}
                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: typography.size.sm }}>
                    <span style={{ color: color.text.secondary }}>Mode</span>
                    <StatusBadge value={c.state} />
                  </div>
                  {c.targetTemp != null && (
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: typography.size.sm }}>
                      <span style={{ color: color.text.secondary }}>Target</span>
                      <span className="tabular" style={{ fontWeight: typography.weight.semibold, color: color.text.primary }}>
                        {c.targetTemp}&deg;
                      </span>
                    </div>
                  )}
                  {c.hvacAction && (
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: typography.size.sm }}>
                      <span style={{ color: color.text.secondary }}>Action</span>
                      <StatusBadge value={c.hvacAction} />
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}

          {lights.length === 0 && climate.length === 0 && (
            <div style={{
              padding: space.md,
              color: color.text.tertiary,
              fontSize: typography.size.sm,
              textAlign: "center",
            }}>
              No controllable devices
            </div>
          )}
        </div>
      )}
    </div>
  );
}
