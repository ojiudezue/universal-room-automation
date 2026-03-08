import { useState, useMemo } from "react";
import { useHass } from "@hakit/core";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";

const BASE = "/universal_room_automation_panel";

export function RoomsTab() {
  const [floor, setFloor] = useState<"ground" | "second">("ground");
  const { getAllEntities, callService } = useHass();
  const allEntities = getAllEntities();

  // Memoize entity lookups
  const roomSensors = useMemo(() =>
    Object.entries(allEntities)
      .filter(([id]) => id.includes("automation_health") && id.startsWith("sensor."))
      .map(([id, e]) => ({
        id,
        name: e.attributes?.friendly_name ?? id,
        state: e.state,
        room: (e.attributes?.room_name ?? id.replace("sensor.ura_", "").replace("_automation_health", "")) as string,
      })),
    [allEntities]
  );

  const lights = useMemo(() =>
    Object.entries(allEntities)
      .filter(([id]) => id.startsWith("light.") && !id.includes("notification"))
      .map(([id, e]) => ({
        id,
        name: e.attributes?.friendly_name ?? id.replace("light.", ""),
        state: e.state,
      })),
    [allEntities]
  );

  const climates = useMemo(() =>
    Object.entries(allEntities)
      .filter(([id]) => id.startsWith("climate."))
      .map(([id, e]) => ({
        id,
        name: e.attributes?.friendly_name ?? id.replace("climate.", ""),
        state: e.state,
        currentTemp: e.attributes?.current_temperature as number | undefined,
        targetTemp: e.attributes?.temperature as number | undefined,
      })),
    [allEntities]
  );

  const toggleLight = (entityId: string, currentState: string) => {
    callService({
      domain: "light" as never,
      service: (currentState === "on" ? "turn_off" : "turn_on") as never,
      target: { entity_id: entityId },
    });
  };

  return (
    <div>
      <div className="hero-section">
        <h1 className="hero-greeting">Rooms</h1>
      </div>

      {/* Floor Plan Selection */}
      <div className="floor-tabs">
        <button
          className={`floor-tab ${floor === "ground" ? "floor-tab-active" : ""}`}
          onClick={() => setFloor("ground")}
        >
          Ground Floor
        </button>
        <button
          className={`floor-tab ${floor === "second" ? "floor-tab-active" : ""}`}
          onClick={() => setFloor("second")}
        >
          Second Floor
        </button>
      </div>

      {/* Floor Plan */}
      <GlassCard compact>
        <div className="floor-plan-container">
          <img
            className="floor-plan-img"
            src={`${BASE}/floorplans/${floor === "ground" ? "ground-floor" : "second-floor"}.png`}
            alt={`${floor === "ground" ? "Ground" : "Second"} floor plan`}
          />
        </div>
      </GlassCard>

      {/* Room Health Sensors */}
      {roomSensors.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <GlassCard title="Room Status" compact>
            {roomSensors.map(r => (
              <div className="info-row" key={r.id}>
                <span className="info-label">{r.room.replace(/_/g, " ")}</span>
                <StatusBadge value={r.state} />
              </div>
            ))}
          </GlassCard>
        </div>
      )}

      {/* Lights */}
      <div style={{ marginTop: 16 }}>
        <GlassCard title="Lights" subtitle={`${lights.filter(l => l.state === "on").length} on`} compact>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {lights.slice(0, 20).map(l => (
              <div className="list-item" key={l.id}>
                <span className="info-label" style={{ flex: 1 }}>{l.name}</span>
                <button
                  className={`toggle-switch ${l.state === "on" ? "toggle-switch-on" : ""}`}
                  onClick={() => toggleLight(l.id, l.state)}
                  aria-label={`Toggle ${l.name}`}
                />
              </div>
            ))}
            {lights.length === 0 && (
              <div style={{ color: "rgba(255,255,255,0.4)", fontSize: "0.85rem", textAlign: "center", padding: 16 }}>
                No light entities found
              </div>
            )}
          </div>
        </GlassCard>
      </div>

      {/* Climate */}
      {climates.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <GlassCard title="Thermostats" compact>
            <div className="grid grid-3">
              {climates.map(c => (
                <div className="zone-card" key={c.id}>
                  <div className="zone-header">
                    <span className="zone-name">{c.name}</span>
                    <StatusBadge value={c.state} />
                  </div>
                  {c.currentTemp != null && (
                    <div className="zone-detail">
                      <span>Current</span>
                      <span>{c.currentTemp}&deg;</span>
                    </div>
                  )}
                  {c.targetTemp != null && (
                    <div className="zone-detail">
                      <span>Target</span>
                      <span>{c.targetTemp}&deg;</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </GlassCard>
        </div>
      )}
    </div>
  );
}
