/**
 * Coordinator health cards with enable/disable toggles.
 */
import { useEntity } from "../../hooks/useEntity";
import { StatusBadge } from "../shared/StatusBadge";
import { Toggle } from "../shared/Toggle";
import { color, space, radius, type as typography } from "../../design/tokens";
import { Eye, Zap, Thermometer, Shield } from "lucide-react";

const COORDINATORS = [
  { name: "Presence", enabledId: "switch.ura_presence_coordinator_enabled", stateId: "sensor.ura_presence_coordinator_presence_house_state", stateLabel: "House State", icon: Eye, accentColor: color.status.green },
  { name: "Energy", enabledId: "switch.ura_energy_coordinator_enabled", stateId: "sensor.ura_energy_coordinator_energy_situation", stateLabel: "Situation", icon: Zap, accentColor: color.status.yellow },
  { name: "HVAC", enabledId: "switch.ura_hvac_coordinator_enabled", stateId: "sensor.ura_hvac_coordinator_mode", stateLabel: "Mode", icon: Thermometer, accentColor: color.status.blue },
  { name: "Security", enabledId: "switch.ura_security_coordinator_enabled", stateId: "sensor.ura_security_coordinator_security_armed_state", stateLabel: "Armed State", icon: Shield, accentColor: color.status.red },
];

export function CoordinatorHealth() {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(2, 1fr)",
      gap: space.sm,
    }}
      className="coord-grid"
    >
      {COORDINATORS.map((c) => (
        <CoordinatorCard key={c.name} {...c} />
      ))}
      <style>{`
        @media (max-width: 600px) {
          .coord-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

function CoordinatorCard({
  name,
  enabledId,
  stateId,
  stateLabel,
  icon: Icon,
  accentColor,
}: (typeof COORDINATORS)[0]) {
  const enabled = useEntity(enabledId);
  const state = useEntity(stateId);
  const isOn = enabled.state === "on";

  return (
    <div style={{
      background: color.glass.bg,
      border: `1px solid ${color.glass.border}`,
      borderLeft: `3px solid ${isOn ? accentColor : color.text.disabled}`,
      borderRadius: radius.lg,
      padding: space.md,
      display: "flex",
      flexDirection: "column",
      gap: space.sm,
      opacity: isOn ? 1 : 0.5,
      transition: "opacity 200ms ease",
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
          <div style={{
            width: 32,
            height: 32,
            borderRadius: radius.full,
            background: `${isOn ? accentColor : color.text.disabled}18`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: isOn ? accentColor : color.text.disabled,
            flexShrink: 0,
          }}>
            <Icon size={16} />
          </div>
          <div>
            <div style={{
              fontSize: typography.size.base,
              fontWeight: typography.weight.semibold,
              color: color.text.primary,
            }}>
              {name}
            </div>
            <div style={{
              fontSize: typography.size.xs,
              color: color.text.tertiary,
            }}>
              {isOn ? "Active" : "Disabled"}
            </div>
          </div>
        </div>
        <Toggle entityId={enabledId} currentState={enabled.state} size="sm" />
      </div>

      {/* State */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        fontSize: typography.size.sm,
      }}>
        <span style={{ color: color.text.secondary }}>{stateLabel}</span>
        <StatusBadge value={state.state} />
      </div>

      {/* Last updated */}
      {state.last_updated && (
        <div style={{
          fontSize: typography.size.xs,
          color: color.text.tertiary,
        }}>
          Updated {new Date(state.last_updated).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </div>
      )}
    </div>
  );
}
