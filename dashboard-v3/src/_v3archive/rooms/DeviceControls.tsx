/**
 * Shared device control components used within room cards.
 * Placeholder for future extensibility (fans, covers, media players, etc.)
 */
import { Power } from "lucide-react";
import { useServiceCall } from "../../hooks/useService";
import { color, space, radius, timing, type as typography } from "../../design/tokens";

interface GenericToggleProps {
  entityId: string;
  name: string;
  state: string;
  domain: string;
}

export function GenericDeviceToggle({ entityId, name, state, domain }: GenericToggleProps) {
  const { call, loading } = useServiceCall();
  const isOn = state === "on";

  return (
    <button
      style={{
        display: "flex",
        alignItems: "center",
        gap: space.sm,
        padding: `${space.sm}px ${space.md}px`,
        border: `1px solid ${isOn ? "rgba(102, 187, 106, 0.2)" : "rgba(255, 255, 255, 0.05)"}`,
        borderRadius: radius.md,
        background: isOn ? "rgba(102, 187, 106, 0.08)" : "rgba(255, 255, 255, 0.03)",
        color: isOn ? color.status.green : color.text.tertiary,
        cursor: loading ? "wait" : "pointer",
        fontFamily: "inherit",
        transition: `all ${timing.fast}`,
        minHeight: 44,
        width: "100%",
      }}
      onClick={() =>
        call({
          domain,
          service: isOn ? "turn_off" : "turn_on",
          target: { entity_id: entityId },
        })
      }
      aria-label={`Toggle ${name}`}
      disabled={loading}
    >
      <Power size={14} />
      <span style={{
        flex: 1,
        fontSize: typography.size.sm,
        fontWeight: typography.weight.medium,
        textAlign: "left",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}>
        {name.replace(/_/g, " ")}
      </span>
      <span style={{
        fontSize: typography.size.xs,
        fontWeight: typography.weight.semibold,
        textTransform: "uppercase",
      }}>
        {isOn ? "ON" : "OFF"}
      </span>
    </button>
  );
}
