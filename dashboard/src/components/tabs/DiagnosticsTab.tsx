import { useHass } from "@hakit/core";
import { ENERGY, HVAC, PRESENCE, SECURITY } from "../../types/entities";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";

function fmt(v: string | undefined): string {
  if (!v || v === "unknown" || v === "unavailable") return "--";
  return v.replace(/_/g, " ");
}

interface CoordinatorInfo {
  name: string;
  enabledId: string;
  stateId: string;
  stateLabel: string;
}

const COORDINATORS: CoordinatorInfo[] = [
  { name: "Presence", enabledId: PRESENCE.ENABLED, stateId: PRESENCE.HOUSE_STATE, stateLabel: "House State" },
  { name: "Energy", enabledId: ENERGY.ENABLED, stateId: ENERGY.ENERGY_SITUATION, stateLabel: "Situation" },
  { name: "HVAC", enabledId: HVAC.ENABLED, stateId: HVAC.MODE, stateLabel: "Mode" },
  { name: "Security", enabledId: SECURITY.ENABLED, stateId: SECURITY.ARMED_STATE, stateLabel: "Armed State" },
];

export function DiagnosticsTab() {
  const { getAllEntities, callService } = useHass();
  const allEntities = getAllEntities();

  const getEntity = (id: string) => allEntities[id] ?? { state: "unavailable", attributes: {}, last_updated: "" };

  const toggleCoordinator = (entityId: string, currentState: string) => {
    callService({
      domain: "switch" as never,
      service: (currentState === "on" ? "turn_off" : "turn_on") as never,
      target: { entity_id: entityId },
    });
  };

  // Find automation health sensors
  const healthSensors = Object.entries(allEntities)
    .filter(([id]) => id.includes("automation_health") && id.startsWith("sensor."))
    .map(([id, e]) => ({
      id,
      name: e.attributes?.friendly_name ?? id,
      state: e.state,
      lastUpdated: e.last_updated,
    }));

  // Find anomaly/notification sensors
  const anomalySensors = Object.entries(allEntities)
    .filter(([id]) => id.includes("anomaly") || id.includes("notification_manager"))
    .map(([id, e]) => ({
      id,
      name: e.attributes?.friendly_name ?? id,
      state: e.state,
    }));

  // URA version from any coordinator entity
  const uraEntity = Object.entries(allEntities)
    .find(([id]) => id.startsWith("sensor.ura_"));
  const uraVersion = uraEntity?.[1]?.attributes?.integration_version ?? "unknown";

  return (
    <div>
      <div className="hero-section">
        <h1 className="hero-greeting">Diagnostics</h1>
        <div style={{ fontSize: "0.85rem", color: "rgba(255,255,255,0.5)", marginTop: 8 }}>
          URA v{fmt(String(uraVersion))}
        </div>
      </div>

      {/* Coordinators */}
      <GlassCard title="Coordinators" style={{ marginBottom: 16 }}>
        <div className="grid grid-2">
          {COORDINATORS.map(c => {
            const enabled = getEntity(c.enabledId);
            const state = getEntity(c.stateId);
            return (
              <div className="zone-card" key={c.name}>
                <div className="zone-header">
                  <span className="zone-name">{c.name}</span>
                  <button
                    className={`toggle-switch ${enabled.state === "on" ? "toggle-switch-on" : ""}`}
                    onClick={() => toggleCoordinator(c.enabledId, enabled.state)}
                    aria-label={`Toggle ${c.name}`}
                  />
                </div>
                <div className="info-row">
                  <span className="info-label">{c.stateLabel}</span>
                  <StatusBadge value={state.state} />
                </div>
                <div className="info-row">
                  <span className="info-label">Status</span>
                  <span className="info-value" style={{ fontSize: "0.82rem" }}>
                    {enabled.state === "on" ? "Active" : "Disabled"}
                  </span>
                </div>
                {state.last_updated && (
                  <div className="info-row">
                    <span className="info-label">Last Update</span>
                    <span className="info-value" style={{ fontSize: "0.78rem" }}>
                      {new Date(state.last_updated).toLocaleTimeString([], {
                        hour: "2-digit", minute: "2-digit", second: "2-digit",
                      })}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </GlassCard>

      {/* Automation Health */}
      {healthSensors.length > 0 && (
        <GlassCard title="Automation Health" subtitle="Per-room diagnostics" compact style={{ marginBottom: 16 }}>
          {healthSensors.map(s => (
            <div className="list-item" key={s.id}>
              <span className="info-label">{String(s.name).replace("URA ", "").replace(" Automation Health", "")}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusBadge value={s.state} />
                {s.lastUpdated && (
                  <span style={{ fontSize: "0.7rem", color: "rgba(255,255,255,0.35)" }}>
                    {new Date(s.lastUpdated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                )}
              </div>
            </div>
          ))}
        </GlassCard>
      )}

      {/* Anomalies */}
      {anomalySensors.length > 0 && (
        <GlassCard title="Notifications & Anomalies" compact>
          {anomalySensors.map(s => (
            <div className="list-item" key={s.id}>
              <span className="info-label">{String(s.name).replace("URA ", "")}</span>
              <span className="info-value">{fmt(s.state)}</span>
            </div>
          ))}
        </GlassCard>
      )}

      {/* System Info */}
      <div style={{ marginTop: 16 }}>
        <GlassCard title="System" compact>
          <div className="info-row">
            <span className="info-label">Integration Version</span>
            <span className="info-value">{fmt(String(uraVersion))}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Dashboard Version</span>
            <span className="info-value">2.0</span>
          </div>
          <div className="info-row">
            <span className="info-label">Total Entities</span>
            <span className="info-value">
              {Object.keys(allEntities).filter(id => id.includes("ura_")).length} URA
            </span>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
