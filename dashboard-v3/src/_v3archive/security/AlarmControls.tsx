/**
 * Alarm control panel with arm/disarm mode buttons.
 */
import { useState, useCallback } from "react";
import { Shield, ShieldCheck, ShieldAlert, ShieldOff } from "lucide-react";
import { useServiceCall } from "../../hooks/useService";
import { StatusBadge } from "../shared/StatusBadge";
import { color, space, radius, timing, type as typography } from "../../design/tokens";

interface AlarmPanel {
  id: string;
  name: string;
  state: string;
}

interface Props {
  panel: AlarmPanel;
}

const MODES = [
  { service: "alarm_arm_home", haState: "armed_home", label: "Home", icon: ShieldCheck, color: color.status.blue },
  { service: "alarm_arm_away", haState: "armed_away", label: "Away", icon: ShieldAlert, color: color.status.red },
  { service: "alarm_arm_night", haState: "armed_night", label: "Night", icon: Shield, color: color.status.blue },
  { service: "alarm_disarm", haState: "disarmed", label: "Disarm", icon: ShieldOff, color: color.status.green, confirm: true },
];

export function AlarmControls({ panel }: Props) {
  const { call, loading } = useServiceCall();
  const [confirmingDisarm, setConfirmingDisarm] = useState(false);

  const handleArm = useCallback(
    (service: string, needsConfirm?: boolean) => {
      if (needsConfirm) {
        if (confirmingDisarm) {
          call({
            domain: "alarm_control_panel",
            service,
            target: { entity_id: panel.id },
          });
          setConfirmingDisarm(false);
        } else {
          setConfirmingDisarm(true);
          setTimeout(() => setConfirmingDisarm(false), 5000);
        }
      } else {
        call({
          domain: "alarm_control_panel",
          service,
          target: { entity_id: panel.id },
        });
      }
    },
    [confirmingDisarm, call, panel.id]
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Current state */}
      <div style={{ display: "flex", alignItems: "center", gap: space.md }}>
        <StatusBadge value={panel.state} size="md" />
        <span style={{
          fontSize: typography.size.sm,
          color: color.text.tertiary,
        }}>
          {panel.name}
        </span>
      </div>

      {/* Mode buttons */}
      <div
        className="alarm-btn-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: space.sm,
        }}
      >
        {MODES.map((mode) => {
          const Icon = mode.icon;
          const isActive = panel.state === mode.haState;
          const isConfirming = mode.confirm && confirmingDisarm;

          return (
            <button
              key={mode.service}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: space.sm,
                padding: `${space.md}px ${space.sm}px`,
                border: `1px solid ${isActive ? mode.color : "rgba(255, 255, 255, 0.08)"}`,
                borderRadius: radius.lg,
                background: isActive ? `${mode.color}14` : "rgba(255, 255, 255, 0.03)",
                color: isActive ? mode.color : color.text.tertiary,
                cursor: loading ? "wait" : "pointer",
                fontFamily: "inherit",
                transition: `all ${timing.fast}`,
                minHeight: 44,
              }}
              onClick={() => handleArm(mode.service, mode.confirm)}
              disabled={loading}
              aria-label={isConfirming ? `Confirm ${mode.label}` : mode.label}
            >
              <Icon size={20} />
              <span style={{
                fontSize: typography.size.xs,
                fontWeight: typography.weight.semibold,
                textTransform: "uppercase",
                letterSpacing: "0.4px",
              }}>
                {isConfirming ? "Confirm?" : mode.label}
              </span>
            </button>
          );
        })}
      </div>

      <style>{`
        @media (max-width: 500px) {
          .alarm-btn-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>
    </div>
  );
}
