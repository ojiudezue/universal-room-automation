/**
 * Comfort score display placeholder.
 * Shows per-zone comfort metrics when available.
 */
import { color, space, type as typography } from "../../design/tokens";

export function ComfortScore() {
  // Comfort coordinator is not yet built (stubbed in config).
  // This component is a placeholder that shows when data becomes available.
  return (
    <div style={{
      padding: space.lg,
      textAlign: "center",
      color: color.text.tertiary,
      fontSize: typography.size.sm,
    }}>
      Comfort scoring will be available in a future update.
    </div>
  );
}
