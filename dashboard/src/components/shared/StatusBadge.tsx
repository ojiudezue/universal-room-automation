const colorMap: Record<string, string> = {
  off_peak: "var(--status-green)",
  mid_peak: "var(--status-yellow)",
  peak: "var(--status-red)",
  normal: "var(--status-green)",
  coast: "var(--status-yellow)",
  pre_cool: "var(--status-blue)",
  pre_heat: "var(--status-orange)",
  shed: "var(--status-red)",
  disabled: "rgba(255,255,255,0.25)",
  idle: "var(--status-green)",
  unknown: "rgba(255,255,255,0.25)",
  unavailable: "rgba(255,255,255,0.15)",
  home_day: "var(--status-green)",
  home_evening: "var(--status-green)",
  home_night: "var(--status-blue)",
  sleep: "var(--status-blue)",
  away: "var(--status-yellow)",
  vacation: "var(--status-orange)",
  arriving: "var(--status-green)",
  waking: "var(--status-green)",
  guest: "var(--status-green)",
  active: "var(--status-green)",
  grace_period: "var(--status-yellow)",
  compromise: "var(--status-orange)",
  excellent: "var(--status-green)",
  good: "var(--status-green)",
  fair: "var(--status-yellow)",
  poor: "var(--status-orange)",
  very_poor: "var(--status-red)",
  armed_home: "var(--status-blue)",
  armed_away: "var(--status-red)",
  armed_night: "var(--status-blue)",
  disarmed: "var(--status-green)",
  pending: "var(--status-yellow)",
  triggered: "var(--status-red)",
  on: "var(--status-green)",
  off: "rgba(255,255,255,0.25)",
  home: "var(--status-green)",
  not_home: "var(--status-yellow)",
  self_consumption: "var(--status-green)",
  reserve: "var(--status-blue)",
  grid_charge: "var(--status-yellow)",
};

interface Props {
  value: string;
  label?: string;
  large?: boolean;
}

export function StatusBadge({ value, label, large }: Props) {
  const color = colorMap[value] ?? "rgba(255,255,255,0.25)";
  return (
    <span
      className={`status-badge${large ? " status-badge-lg" : ""}`}
      style={{ backgroundColor: color, color: "#fff" }}
    >
      {label ?? value.replace(/_/g, " ")}
    </span>
  );
}
