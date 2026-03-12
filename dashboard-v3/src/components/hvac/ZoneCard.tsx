/**
 * HVAC zone card: shows thermostat status, preset, temperature.
 */
import { useEntity, formatState } from "../../hooks/useEntity";
import { StatusBadge } from "../shared/StatusBadge";
import { GlassCard } from "../layout/GlassCard";
import { color, space, radius, type as typography } from "../../design/tokens";

interface Props {
  name: string;
  statusId: string;
  presetId: string;
}

export function ZoneCard({ name, statusId, presetId }: Props) {
  const status = useEntity(statusId);
  const preset = useEntity(presetId);
  const attrs = status.attributes as Record<string, unknown>;

  const currentTemp = (attrs.current_temperature ?? attrs.current_temp) as number | undefined;
  const targetTemp = (attrs.target_temperature ?? attrs.target_temp) as number | undefined;
  const humidity = (attrs.humidity ?? attrs.current_humidity) as number | undefined;
  const hvacAction = (attrs.hvac_action ?? attrs.action) as string | undefined;
  const setpointHigh = (attrs.setpoint_high ?? attrs.target_temp_high) as number | undefined;
  const setpointLow = (attrs.setpoint_low ?? attrs.target_temp_low) as number | undefined;

  return (
    <GlassCard title={name}>
      {/* Status + Preset badges */}
      <div style={{ display: "flex", gap: space.sm, alignItems: "center", flexWrap: "wrap" }}>
        <StatusBadge value={status.state} />
        <StatusBadge value={preset.state} />
      </div>

      {/* Temperature display */}
      {currentTemp != null && (
        <div style={{ textAlign: "center", padding: `${space.xs}px 0` }}>
          <div className="tabular" style={{
            fontSize: typography.size["3xl"],
            fontWeight: typography.weight.regular,
            color: color.text.primary,
            lineHeight: 1,
          }}>
            {currentTemp}&deg;
          </div>
          <div style={{
            fontSize: typography.size.xs,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.4px",
            marginTop: 4,
          }}>
            Current
          </div>
        </div>
      )}

      {/* Zone details */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {targetTemp != null && (
          <InfoRow label="Target" value={`${targetTemp}\u00B0`} />
        )}
        {setpointHigh != null && setpointLow != null && (
          <InfoRow label="Range" value={`${setpointLow}\u00B0 - ${setpointHigh}\u00B0`} />
        )}
        {humidity != null && (
          <InfoRow label="Humidity" value={`${humidity}%`} />
        )}
        {hvacAction && (
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "3px 0",
            fontSize: typography.size.base,
          }}>
            <span style={{ color: color.text.secondary }}>Action</span>
            <StatusBadge value={String(hvacAction)} />
          </div>
        )}
      </div>
    </GlassCard>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "3px 0",
      fontSize: typography.size.base,
    }}>
      <span style={{ color: color.text.secondary }}>{label}</span>
      <span className="tabular" style={{
        color: color.text.primary,
        fontWeight: typography.weight.medium,
      }}>
        {value}
      </span>
    </div>
  );
}
