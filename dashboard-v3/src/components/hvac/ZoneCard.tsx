/**
 * HVAC zone card: shows thermostat status, preset, temperature,
 * zone presence state, duty cycle, and continuous occupancy.
 */
import React from "react";
import { useEntity, formatState } from "../../hooks/useEntity";
import { StatusBadge } from "../shared/StatusBadge";
import { GlassCard } from "../layout/GlassCard";
import { color, space, radius, type as typography } from "../../design/tokens";

interface Props {
  name: string;
  statusId: string;
  presetId: string;
}

export const ZoneCard = React.memo(function ZoneCard({ name, statusId, presetId }: Props) {
  const status = useEntity(statusId);
  const preset = useEntity(presetId);
  const attrs = status.attributes as Record<string, unknown>;

  const currentTemp = (attrs.current_temperature ?? attrs.current_temp) as number | undefined;
  const targetTemp = (attrs.target_temperature ?? attrs.target_temp) as number | undefined;
  const humidity = (attrs.humidity ?? attrs.current_humidity) as number | undefined;
  const hvacAction = (attrs.hvac_action ?? attrs.action) as string | undefined;
  const setpointHigh = (attrs.setpoint_high ?? attrs.target_temp_high) as number | undefined;
  const setpointLow = (attrs.setpoint_low ?? attrs.target_temp_low) as number | undefined;

  // Zone Intelligence attributes
  const zonePresenceState = attrs.zone_presence_state as string | undefined;
  const dutyCyclePct = attrs.runtime_duty_cycle_pct as number | undefined;
  const continuousOccupiedHours = attrs.continuous_occupied_hours as number | undefined;
  const occupiedRooms = (attrs.occupied_rooms ?? []) as string[];
  const roomCount = attrs.room_count as number | undefined;

  return (
    <GlassCard title={name}>
      {/* Status + Preset badges */}
      <div style={badgeRowStyle}>
        <StatusBadge value={status.state} />
        <StatusBadge value={preset.state} />
        {zonePresenceState && (
          <StatusBadge value={zonePresenceState} label={formatState(zonePresenceState)} />
        )}
      </div>

      {/* Temperature display */}
      {currentTemp != null && (
        <div style={tempDisplayStyle}>
          <div className="tabular" style={tempValueStyle}>
            {currentTemp}&deg;
          </div>
          <div style={tempLabelStyle}>
            Current
          </div>
        </div>
      )}

      {/* Duty cycle progress bar */}
      {dutyCyclePct != null && (
        <div style={dutyCycleContainerStyle}>
          <div style={dutyCycleHeaderStyle}>
            <span style={{ color: color.text.secondary }}>Duty Cycle</span>
            <span className="tabular" style={dutyCycleValueStyle}>
              {dutyCyclePct.toFixed(0)}%
            </span>
          </div>
          <div style={dutyCycleTrackStyle}>
            <div
              style={{
                height: "100%",
                width: `${Math.min(dutyCyclePct, 100)}%`,
                borderRadius: 2,
                background:
                  dutyCyclePct > 85
                    ? color.status.red
                    : dutyCyclePct > 65
                    ? color.status.orange
                    : color.accent.primary,
                transition: "width 300ms ease",
              }}
            />
          </div>
        </div>
      )}

      {/* Zone details */}
      <div style={detailsStyle}>
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
          <div style={infoRowContainerStyle}>
            <span style={{ color: color.text.secondary }}>Action</span>
            <StatusBadge value={String(hvacAction)} />
          </div>
        )}
        {occupiedRooms.length > 0 && (
          <InfoRow
            label="Active"
            value={occupiedRooms.join(", ")}
          />
        )}
        {roomCount != null && (
          <InfoRow label="Rooms" value={`${occupiedRooms.length}/${roomCount}`} />
        )}
        {continuousOccupiedHours != null && continuousOccupiedHours > 0 && (
          <InfoRow
            label="Occupied"
            value={
              continuousOccupiedHours >= 1
                ? `${continuousOccupiedHours.toFixed(1)}h`
                : `${Math.round(continuousOccupiedHours * 60)}m`
            }
          />
        )}
      </div>
    </GlassCard>
  );
});

const InfoRow = React.memo(function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={infoRowContainerStyle}>
      <span style={{ color: color.text.secondary }}>{label}</span>
      <span className="tabular" style={infoRowValueStyle}>
        {value}
      </span>
    </div>
  );
});

// Extracted static styles
const badgeRowStyle: React.CSSProperties = {
  display: "flex",
  gap: space.sm,
  alignItems: "center",
  flexWrap: "wrap",
};

const tempDisplayStyle: React.CSSProperties = {
  textAlign: "center",
  padding: `${space.xs}px 0`,
};

const tempValueStyle: React.CSSProperties = {
  fontSize: typography.size["3xl"],
  fontWeight: typography.weight.regular,
  color: color.text.primary,
  lineHeight: 1,
};

const tempLabelStyle: React.CSSProperties = {
  fontSize: typography.size.xs,
  color: color.text.tertiary,
  textTransform: "uppercase",
  letterSpacing: "0.4px",
  marginTop: 4,
};

const dutyCycleContainerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 3,
};

const dutyCycleHeaderStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  fontSize: typography.size.base,
};

const dutyCycleValueStyle: React.CSSProperties = {
  color: color.text.primary,
  fontWeight: typography.weight.medium,
};

const dutyCycleTrackStyle: React.CSSProperties = {
  height: 4,
  borderRadius: 2,
  background: "rgba(255, 255, 255, 0.08)",
  overflow: "hidden",
};

const detailsStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 3,
};

const infoRowContainerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "3px 0",
  fontSize: typography.size.base,
};

const infoRowValueStyle: React.CSSProperties = {
  color: color.text.primary,
  fontWeight: typography.weight.medium,
};
