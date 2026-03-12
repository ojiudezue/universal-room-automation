/**
 * Compact sparkline chart using Recharts.
 * Used for inline data trends in cards.
 */
import { ResponsiveContainer, AreaChart, Area, YAxis } from "recharts";
import { color } from "../../design/tokens";

interface Props {
  data: Array<{ value: number }>;
  height?: number;
  strokeColor?: string;
  fillColor?: string;
}

export function MiniChart({
  data,
  height = 32,
  strokeColor = color.accent.primary,
  fillColor = color.accent.primaryDim,
}: Props) {
  if (data.length < 2) return null;

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`miniGrad-${strokeColor}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={fillColor} stopOpacity={0.4} />
              <stop offset="95%" stopColor={fillColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis domain={["dataMin", "dataMax"]} hide />
          <Area
            type="monotone"
            dataKey="value"
            stroke={strokeColor}
            strokeWidth={1.5}
            fill={`url(#miniGrad-${strokeColor})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
