/**
 * Formatted entity value display.
 * Shows a label + value pair in compact row format.
 */
import { color, type as typography } from "../../design/tokens";

interface Props {
  label: string;
  value: string | number | null | undefined;
  unit?: string;
  accent?: string;
  inline?: boolean;
}

export function EntityValue({ label, value, unit, accent, inline }: Props) {
  const display =
    value == null || value === "unknown" || value === "unavailable"
      ? "--"
      : String(value);

  if (inline) {
    return (
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "3px 0",
        fontSize: typography.size.base,
      }}>
        <span style={{ color: color.text.secondary }}>{label}</span>
        <span
          className="tabular"
          style={{
            color: accent ?? color.text.primary,
            fontWeight: typography.weight.medium,
          }}
        >
          {display}
          {unit && display !== "--" && (
            <span style={{
              fontSize: typography.size.xs,
              fontWeight: typography.weight.regular,
              marginLeft: 2,
              color: color.text.tertiary,
            }}>
              {unit}
            </span>
          )}
        </span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 60 }}>
      <span style={{
        fontSize: typography.size.xs,
        fontWeight: typography.weight.medium,
        color: color.text.tertiary,
        textTransform: "uppercase",
        letterSpacing: "0.6px",
      }}>
        {label}
      </span>
      <span
        className="tabular"
        style={{
          fontSize: typography.size.md,
          fontWeight: typography.weight.semibold,
          color: accent ?? color.text.primary,
        }}
      >
        {display}
        {unit && display !== "--" && (
          <span style={{
            fontSize: typography.size.xs,
            fontWeight: typography.weight.regular,
            marginLeft: 2,
            color: color.text.tertiary,
          }}>
            {unit}
          </span>
        )}
      </span>
    </div>
  );
}
