import { useMemo } from "react";
import { useHass } from "@hakit/core";
import { useSecurityData } from "../../hooks/useSecurityData";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";

function fmt(v: string | undefined): string {
  if (!v || v === "unknown" || v === "unavailable") return "--";
  return v.replace(/_/g, " ");
}

const ENTRY_KEYWORDS = ["door", "entry", "front", "garage", "gate"];
const INSIDE_KEYWORDS = ["indoor", "inside", "living", "kitchen", "office", "bedroom"];

function categorizeCamera(name: string): "entry" | "inside" | "outside" {
  const lower = name.toLowerCase();
  // Priority: entryway > inside > outside (mutually exclusive)
  if (ENTRY_KEYWORDS.some(k => lower.includes(k))) return "entry";
  if (INSIDE_KEYWORDS.some(k => lower.includes(k))) return "inside";
  return "outside";
}

export function SecurityTab() {
  const { getAllEntities, callService } = useHass();
  const security = useSecurityData();
  const allEntities = getAllEntities();

  // Memoize entity lookups
  const cameras = useMemo(() => {
    const all = Object.entries(allEntities)
      .filter(([id]) => id.startsWith("camera."))
      .map(([id, e]) => ({
        id,
        name: e.attributes?.friendly_name ?? id.replace("camera.", ""),
        state: e.state,
        category: categorizeCamera(e.attributes?.friendly_name ?? id),
      }));
    return {
      outside: all.filter(c => c.category === "outside"),
      entry: all.filter(c => c.category === "entry"),
      inside: all.filter(c => c.category === "inside"),
    };
  }, [allEntities]);

  const locks = useMemo(() =>
    Object.entries(allEntities)
      .filter(([id]) => id.startsWith("lock."))
      .map(([id, e]) => ({
        id,
        name: e.attributes?.friendly_name ?? id.replace("lock.", ""),
        state: e.state,
      })),
    [allEntities]
  );

  const alarmPanels = useMemo(() =>
    Object.entries(allEntities)
      .filter(([id]) => id.startsWith("alarm_control_panel."))
      .map(([id, e]) => ({
        id,
        name: e.attributes?.friendly_name ?? id,
        state: e.state,
      })),
    [allEntities]
  );

  const toggleLock = (entityId: string, currentState: string) => {
    callService({
      domain: "lock" as never,
      service: (currentState === "locked" ? "unlock" : "lock") as never,
      target: { entity_id: entityId },
    });
  };

  const armAlarm = (entityId: string, mode: string) => {
    callService({
      domain: "alarm_control_panel" as never,
      service: mode as never,
      target: { entity_id: entityId },
    });
  };

  return (
    <div>
      <div className="hero-section">
        <h1 className="hero-greeting">Security</h1>
        <StatusBadge value={security.armedState.state} large />
      </div>

      {/* Quick Stats */}
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <span className="metric-value">{security.openEntries.state}</span>
          <span className="metric-label">Open Entries</span>
        </div>
        <div className="stat-card">
          <span className="metric-value-sm">
            {security.lastLockSweep.state !== "unknown" && security.lastLockSweep.state !== "unavailable"
              ? new Date(security.lastLockSweep.state).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
              : "--"}
          </span>
          <span className="metric-label">Last Lock Sweep</span>
        </div>
        <div className="stat-card">
          <span className="metric-value">{security.expectedArrivals.state}</span>
          <span className="metric-label">Expected Arrivals</span>
        </div>
      </div>

      {/* Alarm Controls */}
      {alarmPanels.length > 0 && (
        <GlassCard title="Alarm Panel" badge={<StatusBadge value={alarmPanels[0].state} />} compact style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {["alarm_arm_home", "alarm_arm_away", "alarm_arm_night", "alarm_disarm"].map(mode => (
              <button
                key={mode}
                onClick={() => {
                  if (mode === "alarm_disarm" && !window.confirm("Disarm the alarm?")) return;
                  armAlarm(alarmPanels[0].id, mode);
                }}
                style={{
                  padding: "8px 16px", border: "var(--glass-border)", borderRadius: "var(--radius-md)",
                  background: mode === "alarm_disarm" ? "rgba(229,115,115,0.15)" : "rgba(255,255,255,0.06)",
                  color: mode === "alarm_disarm" ? "var(--status-red)" : "rgba(255,255,255,0.8)",
                  cursor: "pointer", fontFamily: "inherit", fontSize: "0.82rem", fontWeight: 500,
                }}
              >
                {mode.replace("alarm_", "").replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Locks */}
      {locks.length > 0 && (
        <GlassCard title="Locks" compact style={{ marginBottom: 16 }}>
          {locks.map(l => (
            <div className="list-item" key={l.id}>
              <span style={{ fontSize: "0.9rem", color: "rgba(255,255,255,0.85)" }}>{l.name}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusBadge value={l.state === "locked" ? "on" : "off"} label={l.state} />
                <button
                  onClick={() => {
                    if (l.state === "locked" && !window.confirm(`Unlock ${l.name}?`)) return;
                    toggleLock(l.id, l.state);
                  }}
                  style={{
                    padding: "6px 14px", border: "var(--glass-border)", borderRadius: "var(--radius-sm)",
                    background: l.state === "locked" ? "rgba(129,199,132,0.15)" : "rgba(229,115,115,0.15)",
                    color: l.state === "locked" ? "var(--status-green)" : "var(--status-red)",
                    cursor: "pointer", fontFamily: "inherit", fontSize: "0.78rem", fontWeight: 600,
                  }}
                >
                  {l.state === "locked" ? "Unlock" : "Lock"}
                </button>
              </div>
            </div>
          ))}
        </GlassCard>
      )}

      {/* Cameras — mutually exclusive grouping */}
      <div className="grid grid-3">
        {(["outside", "entry", "inside"] as const).map(group => {
          const cams = cameras[group];
          const title = group === "entry" ? "Entryways" : group.charAt(0).toUpperCase() + group.slice(1);
          return (
            <GlassCard key={group} title={title} subtitle={`${cams.length} cameras`} compact>
              {cams.length > 0 ? cams.map(c => (
                <div className="list-item" key={c.id}>
                  <span className="info-label">{c.name}</span>
                  <StatusBadge value={c.state === "recording" ? "active" : fmt(c.state)} />
                </div>
              )) : (
                <div style={{ color: "rgba(255,255,255,0.3)", fontSize: "0.82rem" }}>No cameras</div>
              )}
            </GlassCard>
          );
        })}
      </div>
    </div>
  );
}
