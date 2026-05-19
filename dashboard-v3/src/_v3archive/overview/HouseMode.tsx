/**
 * House mode display with selector.
 * Shows current house state and allows changing it via script or input_select.
 */
import { useEntity, formatState } from "../../hooks/useEntity";
import { StatusBadge } from "../shared/StatusBadge";
import { color, space, radius, timing, type as typography } from "../../design/tokens";
import {
  Home, Moon, Sun, Plane, Coffee, UserCheck,
} from "lucide-react";

const HOUSE_STATE_ID = "sensor.ura_presence_coordinator_presence_house_state";

const MODE_ICONS: Record<string, React.FC<{ size?: number }>> = {
  home_day: Sun,
  home_evening: Coffee,
  home_night: Moon,
  sleep: Moon,
  away: Plane,
  vacation: Plane,
  arriving: UserCheck,
  waking: Sun,
  guest: UserCheck,
};

export function HouseMode() {
  const houseState = useEntity(HOUSE_STATE_ID);
  const state = houseState.state;
  const Icon = MODE_ICONS[state] ?? Home;

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: space.md,
    }}>
      <div style={{
        width: 40,
        height: 40,
        borderRadius: radius.md,
        background: "rgba(255, 255, 255, 0.06)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: color.accent.primary,
        flexShrink: 0,
      }}>
        <Icon size={22} />
      </div>
      <div style={{ flex: 1 }}>
        <div style={{
          fontSize: typography.size.xs,
          color: color.text.tertiary,
          textTransform: "uppercase",
          letterSpacing: "0.6px",
          fontWeight: typography.weight.medium,
        }}>
          House Mode
        </div>
        <div style={{
          fontSize: typography.size.lg,
          fontWeight: typography.weight.semibold,
          color: color.text.primary,
          textTransform: "capitalize",
        }}>
          {formatState(state)}
        </div>
      </div>
      <StatusBadge value={state} size="md" />
    </div>
  );
}
