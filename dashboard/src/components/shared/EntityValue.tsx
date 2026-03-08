interface Props {
  label: string;
  value: string | number | null | undefined;
  unit?: string;
  color?: string;
}

export function EntityValue({ label, value, unit, color }: Props) {
  const display = value == null || value === "unknown" || value === "unavailable" ? "--" : value;
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value-sm" style={color ? { color } : undefined}>
        {display}
        {unit && value != null && value !== "unknown" && value !== "unavailable" && (
          <span style={{ fontSize: "0.75rem", fontWeight: 400, marginLeft: 2 }}>{unit}</span>
        )}
      </span>
    </div>
  );
}
