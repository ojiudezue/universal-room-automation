import { useHVACData } from "../../hooks/useHVACData";
import { useEnergyData } from "../../hooks/useEnergyData";
import { useHass } from "@hakit/core";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";

function fmt(v: string | undefined): string {
  if (!v || v === "unknown" || v === "unavailable") return "--";
  return v.replace(/_/g, " ");
}

export function HVACTab() {
  const { callService } = useHass();
  const hvac = useHVACData();
  const energy = useEnergyData();

  const toggleSwitch = (entityId: string, currentState: string) => {
    callService({
      domain: "switch" as never,
      service: (currentState === "on" ? "turn_off" : "turn_on") as never,
      target: { entity_id: entityId },
    });
  };

  return (
    <div>
      {/* Hero */}
      <div className="hero-section">
        <h1 className="hero-greeting">HVAC</h1>
        <StatusBadge value={hvac.mode.state} large />
      </div>

      {/* Controls */}
      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <GlassCard title="Controls" compact>
          <div className="list-item">
            <span className="toggle-label">Override Arrester</span>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <StatusBadge value={hvac.arresterState.state} />
              <button
                className={`toggle-switch ${hvac.arresterSwitch.state === "on" ? "toggle-switch-on" : ""}`}
                onClick={() => toggleSwitch(hvac.arresterSwitch.entity_id, hvac.arresterSwitch.state)}
                aria-label="Toggle arrester"
              />
            </div>
          </div>
          <div className="list-item">
            <span className="toggle-label">Observation Mode</span>
            <button
              className={`toggle-switch ${hvac.observationMode.state === "on" ? "toggle-switch-on" : ""}`}
              onClick={() => toggleSwitch(hvac.observationMode.entity_id, hvac.observationMode.state)}
              aria-label="Toggle observation mode"
            />
          </div>
        </GlassCard>

        <GlassCard title="Energy Constraint" badge={<StatusBadge value={energy.hvacConstraint.state} />} compact>
          <div style={{ fontSize: "0.82rem", color: "rgba(255,255,255,0.6)", lineHeight: 1.5 }}>
            {fmt(energy.hvacConstraint.attributes?.detail ?? energy.hvacConstraint.state)}
          </div>
          <div className="info-row">
            <span className="info-label">Load Shedding</span>
            <StatusBadge value={energy.loadShedding.state} />
          </div>
        </GlassCard>
      </div>

      {/* Zone Cards */}
      <div className="grid grid-3">
        {hvac.zones.map((zone) => {
          const attrs = zone.status.attributes ?? {};
          const currentTemp = attrs.current_temperature ?? attrs.current_temp;
          const targetTemp = attrs.target_temperature ?? attrs.target_temp;
          const humidity = attrs.humidity ?? attrs.current_humidity;
          const hvacAction = attrs.hvac_action ?? attrs.action;
          const setpointHigh = attrs.setpoint_high ?? attrs.target_temp_high;
          const setpointLow = attrs.setpoint_low ?? attrs.target_temp_low;

          return (
            <GlassCard key={zone.name} title={zone.name}>
              {/* Status + Preset */}
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <StatusBadge value={zone.status.state} />
                <StatusBadge value={zone.preset.state} />
              </div>

              {/* Temperature Display */}
              {currentTemp != null && (
                <div style={{ textAlign: "center", padding: "8px 0" }}>
                  <div style={{ fontSize: "2.8rem", fontWeight: 300, color: "rgba(255,255,255,0.95)", lineHeight: 1 }}>
                    {currentTemp}&deg;
                  </div>
                  <div className="metric-label" style={{ marginTop: 4 }}>Current</div>
                </div>
              )}

              {/* Zone Details */}
              {targetTemp != null && (
                <div className="info-row">
                  <span className="info-label">Target</span>
                  <span className="info-value">{targetTemp}&deg;</span>
                </div>
              )}
              {setpointHigh != null && setpointLow != null && (
                <div className="info-row">
                  <span className="info-label">Range</span>
                  <span className="info-value">{setpointLow}&deg; - {setpointHigh}&deg;</span>
                </div>
              )}
              {humidity != null && (
                <div className="info-row">
                  <span className="info-label">Humidity</span>
                  <span className="info-value">{humidity}%</span>
                </div>
              )}
              {hvacAction && (
                <div className="info-row">
                  <span className="info-label">Action</span>
                  <StatusBadge value={String(hvacAction)} />
                </div>
              )}
            </GlassCard>
          );
        })}
      </div>
    </div>
  );
}
