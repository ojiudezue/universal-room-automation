/**
 * Color-coded status badge for entity states.
 * Maps HA states to semantic colors via design tokens.
 */
import { stateColorMap, color, radius, type as typography } from "../../design/tokens";

interface Props {
  value: string;
  label?: string;
  size?: "sm" | "md";
}

export function StatusBadge({ value, label, size = "sm" }: Props) {
  const bgColor = stateColorMap[value] ?? color.text.disabled;

  const style: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    padding: size === "sm" ? "2px 8px" : "4px 12px",
    borderRadius: radius.md,
    fontSize: size === "sm" ? typography.size.xs : typography.size.sm,
    fontWeight: typography.weight.semibold,
    textTransform: "uppercase",
    letterSpacing: "0.4px",
    lineHeight: 1.4,
    backgroundColor: bgColor,
    color: "#fff",
    whiteSpace: "nowrap",
  };

  return (
    <span style={style}>
      {label ?? value.replace(/_/g, " ")}
    </span>
  );
}
