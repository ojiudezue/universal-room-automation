import { useMemo } from "react";
import { useEnergyData } from "../../hooks/useEnergyData";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";

function fmtNum(v: string | undefined, prefix = "", suffix = ""): string {
  if (!v || v === "unknown" || v === "unavailable") return "--";
  const n = parseFloat(v);
  if (isNaN(n)) return v;
  return `${prefix}${n.toFixed(n >= 100 ? 0 : 2)}${suffix}`;
}

function fmt(v: string | undefined): string {
  if (!v || v === "unknown" || v === "unavailable") return "--";
  return v.replace(/_/g, " ");
}

// Generate sample forecast data for visual demonstration
function getSampleForecastData() {
  const hours = [];
  for (let h = 6; h <= 20; h++) {
    const solar = Math.max(0, Math.sin((h - 6) / 14 * Math.PI) * 8 + (Math.random() - 0.5) * 1.5);
    const forecast = Math.max(0, Math.sin((h - 6) / 14 * Math.PI) * 7.5);
    hours.push({
      hour: `${h}:00`,
      actual: Number(solar.toFixed(1)),
      forecast: Number(forecast.toFixed(1)),
    });
  }
  return hours;
}

export function EnergyTab() {
  const energy = useEnergyData();
  // Memoize sample data to prevent chart flicker on re-renders
  const chartData = useMemo(() => getSampleForecastData(), []);

  return (
    <div>
      {/* Hero */}
      <div className="hero-section">
        <h1 className="hero-greeting">Energy</h1>
        <StatusBadge value={energy.situation.state} large />
      </div>

      {/* Key Metrics Row */}
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <span className="metric-value">{fmtNum(energy.costToday.state, "$")}</span>
          <span className="metric-label">Cost Today</span>
        </div>
        <div className="stat-card">
          <span className="metric-value">{fmtNum(energy.importToday.state, "", "")}</span>
          <span className="metric-label">Import kWh</span>
        </div>
        <div className="stat-card">
          <span className="metric-value">{fmtNum(energy.exportToday.state, "", "")}</span>
          <span className="metric-label">Export kWh</span>
        </div>
        <div className="stat-card">
          <span className="metric-value">{fmtNum(energy.predictedBill.state, "$")}</span>
          <span className="metric-label">Predicted Bill</span>
        </div>
      </div>

      {/* TOU + Solar + Battery Row */}
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        {/* TOU */}
        <GlassCard title="Time of Use" compact>
          <div className="info-row">
            <span className="info-label">Period</span>
            <StatusBadge value={energy.touPeriod.state} />
          </div>
          <div className="info-row">
            <span className="info-label">Rate</span>
            <span className="info-value">{fmtNum(energy.touRate.state, "$", "/kWh")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Season</span>
            <span className="info-value">{fmt(energy.touSeason.state)}</span>
          </div>
        </GlassCard>

        {/* Solar */}
        <GlassCard title="Solar" badge={<StatusBadge value={energy.solarClass.state} />} compact>
          <div className="info-row">
            <span className="info-label">Forecast</span>
            <span className="info-value">{fmtNum(energy.forecastToday.state, "", " kWh")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Accuracy</span>
            <span className="info-value">{fmtNum(energy.forecastAccuracy.state, "", "%")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Envoy</span>
            <StatusBadge value={energy.envoyAvailable.state} />
          </div>
        </GlassCard>

        {/* Battery */}
        <GlassCard title="Battery" compact>
          <div className="info-row">
            <span className="info-label">Strategy</span>
            <StatusBadge value={energy.batteryStrategy.state} />
          </div>
          <div className="info-row">
            <span className="info-label">Decision</span>
            <span className="info-value" style={{ fontSize: "0.8rem" }}>{fmt(energy.batteryDecision.state)}</span>
          </div>
        </GlassCard>
      </div>

      {/* Grid & Consumption */}
      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <GlassCard title="Grid" compact>
          <div className="metric-row">
            <div className="metric">
              <span className="metric-value">{fmtNum(energy.importToday.state)}</span>
              <span className="metric-label">Import kWh</span>
            </div>
            <div className="metric">
              <span className="metric-value">{fmtNum(energy.exportToday.state)}</span>
              <span className="metric-label">Export kWh</span>
            </div>
          </div>
          <div className="info-row">
            <span className="info-label">Net Consumption</span>
            <span className="info-value">{fmtNum(energy.netConsumption.state, "", " kWh")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Total Consumption</span>
            <span className="info-value">{fmtNum(energy.totalConsumption.state, "", " kWh")}</span>
          </div>
        </GlassCard>

        <GlassCard title="Cost Tracking" compact>
          <div className="info-row">
            <span className="info-label">Today</span>
            <span className="info-value">{fmtNum(energy.costToday.state, "$")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">This Cycle</span>
            <span className="info-value">{fmtNum(energy.costCycle.state, "$")}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Predicted Bill</span>
            <span className="info-value" style={{ fontWeight: 700, color: "var(--md-primary)" }}>
              {fmtNum(energy.predictedBill.state, "$")}
            </span>
          </div>
        </GlassCard>
      </div>

      {/* Constraints & Load Shedding */}
      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <GlassCard title="HVAC Constraint" badge={<StatusBadge value={energy.hvacConstraint.state} />} compact>
          <div style={{ fontSize: "0.82rem", color: "rgba(255,255,255,0.6)", lineHeight: 1.5 }}>
            {fmt(energy.hvacConstraint.attributes?.detail ?? energy.hvacConstraint.state)}
          </div>
        </GlassCard>

        <GlassCard title="Load Shedding" badge={<StatusBadge value={energy.loadShedding.state} />} compact>
          <div style={{ fontSize: "0.82rem", color: "rgba(255,255,255,0.6)", lineHeight: 1.5 }}>
            {fmt(energy.loadShedding.attributes?.detail ?? energy.loadShedding.state)}
          </div>
        </GlassCard>
      </div>

      {/* Solar Forecast Chart */}
      <GlassCard title="Solar: Forecast vs Actual" subtitle="Sample data - will connect to history">
        <div className="chart-container">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="gradForecast" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8AB4F8" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#8AB4F8" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradActual" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#81C784" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#81C784" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis
                dataKey="hour" tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 11 }}
                axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
              />
              <YAxis
                tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 11 }}
                axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                unit=" kW"
              />
              <Tooltip
                contentStyle={{
                  background: "rgba(20,20,35,0.95)", border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 12, color: "#E6E1E5", fontSize: 13,
                }}
              />
              <Area
                type="monotone" dataKey="forecast" stroke="#8AB4F8" strokeWidth={2}
                fill="url(#gradForecast)" name="Forecast"
              />
              <Area
                type="monotone" dataKey="actual" stroke="#81C784" strokeWidth={2}
                fill="url(#gradActual)" name="Actual"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </GlassCard>
    </div>
  );
}
