import { useMemo } from "react";
import { useHass } from "@hakit/core";
import { usePresenceData } from "../../hooks/usePresenceData";
import { useEnergyData } from "../../hooks/useEnergyData";
import { useHVACData } from "../../hooks/useHVACData";
import { useSecurityData } from "../../hooks/useSecurityData";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good Morning";
  if (h < 17) return "Good Afternoon";
  if (h < 21) return "Good Evening";
  return "Good Night";
}

function fmt(v: string | undefined): string {
  if (!v || v === "unknown" || v === "unavailable") return "--";
  return v.replace(/_/g, " ");
}

function fmtNum(v: string | undefined, prefix = "", suffix = ""): string {
  if (!v || v === "unknown" || v === "unavailable") return "--";
  const n = parseFloat(v);
  if (isNaN(n)) return v;
  return `${prefix}${n.toFixed(n >= 100 ? 0 : 2)}${suffix}`;
}

export function OverviewTab() {
  const { getAllEntities } = useHass();
  const { houseState } = usePresenceData();
  const energy = useEnergyData();
  const hvac = useHVACData();
  const security = useSecurityData();

  // Count persons home (memoize to avoid recomputing on every entity update)
  const allEntities = getAllEntities();
  const persons = useMemo(() =>
    Object.entries(allEntities)
      .filter(([id]) => id.startsWith("person."))
      .map(([id, e]) => ({ id, state: e.state, name: e.attributes?.friendly_name ?? id })),
    [allEntities]
  );
  const homeCount = persons.filter(p => p.state === "home").length;
  const awayCount = persons.filter(p => p.state !== "home").length;

  const activeZones = hvac.zones.filter(z =>
    z.status.state !== "idle" && z.status.state !== "unknown" && z.status.state !== "unavailable"
  ).length;

  return (
    <div>
      {/* Hero */}
      <div className="hero-section">
        <h1 className="hero-greeting">{getGreeting()}</h1>
        <StatusBadge value={houseState.state} large />
      </div>

      {/* Quick Stats Row */}
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <span className="metric-value">{homeCount}</span>
          <span className="metric-label">Home</span>
          {awayCount > 0 && (
            <span style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.4)" }}>
              {awayCount} away
            </span>
          )}
        </div>
        <div className="stat-card">
          <StatusBadge value={energy.touPeriod.state} />
          <span className="metric-label">TOU</span>
          <span style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.5)" }}>
            {fmtNum(energy.touRate.state, "$", "/kWh")}
          </span>
        </div>
        <div className="stat-card">
          <StatusBadge value={hvac.mode.state} />
          <span className="metric-label">HVAC</span>
          <span style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.5)" }}>
            {activeZones}/{hvac.zones.length} zones
          </span>
        </div>
        <div className="stat-card">
          <StatusBadge value={security.armedState.state} />
          <span className="metric-label">Security</span>
          <span style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.5)" }}>
            {security.openEntries.state} open
          </span>
        </div>
      </div>

      {/* Detail Cards */}
      <div className="grid grid-2">
        {/* Energy Summary */}
        <GlassCard title="Energy" badge={<StatusBadge value={energy.situation.state} />} compact>
          <div className="info-row">
            <span className="info-label">Solar</span>
            <StatusBadge value={energy.solarClass.state} />
          </div>
          <div className="info-row">
            <span className="info-label">Cost Today</span>
            <span className="info-value">{fmtNum(energy.costToday.state, "$")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Import</span>
            <span className="info-value">{fmtNum(energy.importToday.state, "", " kWh")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Export</span>
            <span className="info-value">{fmtNum(energy.exportToday.state, "", " kWh")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Battery</span>
            <span className="info-value">{fmt(energy.batteryStrategy.state)}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Predicted Bill</span>
            <span className="info-value">{fmtNum(energy.predictedBill.state, "$")}</span>
          </div>
        </GlassCard>

        {/* HVAC + Security */}
        <GlassCard title="Climate & Security" compact>
          <div className="section-title">HVAC Zones</div>
          {hvac.zones.map((z) => (
            <div className="info-row" key={z.name}>
              <span className="info-label">{z.name}</span>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <StatusBadge value={z.status.state} />
                <span style={{ fontSize: "0.75rem", color: "rgba(255,255,255,0.5)" }}>
                  {fmt(z.preset.state)}
                </span>
              </div>
            </div>
          ))}
          <div className="divider" />
          <div className="section-title">Security</div>
          <div className="info-row">
            <span className="info-label">Open Entries</span>
            <span className="info-value">{security.openEntries.state}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Last Lock Sweep</span>
            <span className="info-value" style={{ fontSize: "0.8rem" }}>
              {security.lastLockSweep.state !== "unknown"
                ? new Date(security.lastLockSweep.state).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                : "--"}
            </span>
          </div>
        </GlassCard>
      </div>

      {/* Persons */}
      <div style={{ marginTop: 16 }}>
        <GlassCard title="People" compact>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {persons.map(p => (
              <div className="person-card" key={p.id}>
                <div
                  className="person-avatar"
                  style={{ background: p.state === "home" ? "var(--status-green)" : "var(--status-yellow)" }}
                >
                  {p.name.charAt(0).toUpperCase()}
                </div>
                <div className="person-info">
                  <div className="person-name">{p.name}</div>
                  <div className="person-detail">{fmt(p.state)}</div>
                </div>
                <StatusBadge value={p.state} />
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
