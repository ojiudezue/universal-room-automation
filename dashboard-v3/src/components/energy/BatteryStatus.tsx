/**
 * Battery status with SoC gauge and strategy info.
 * Includes action button for reserve override.
 */
import { useEntity, formatNumber, formatState } from "../../hooks/useEntity";
import { EntityValue } from "../shared/EntityValue";
import { StatusBadge } from "../shared/StatusBadge";
import { color, space, radius, type as typography } from "../../design/tokens";
import { Battery, BatteryCharging } from "lucide-react";

const ENTITIES = {
  strategy: "sensor.ura_energy_coordinator_battery_strategy",
  decision: "sensor.ura_energy_coordinator_battery_decision",
  soc: "sensor.encharge_aggregate_soc",
  power: "sensor.encharge_aggregate_power",
};

export function BatteryStatus() {
  const strategy = useEntity(ENTITIES.strategy);
  const decision = useEntity(ENTITIES.decision);
  const soc = useEntity(ENTITIES.soc);
  const power = useEntity(ENTITIES.power);

  const socPct = parseFloat(soc.state) || 0;
  const powerW = parseFloat(power.state) || 0;
  const charging = powerW < -50;
  const discharging = powerW > 50;

  // SoC bar color
  const socColor =
    socPct > 50 ? color.status.green : socPct > 20 ? color.status.yellow : color.status.red;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
      {/* SoC gauge */}
      <div style={{ display: "flex", alignItems: "center", gap: space.md }}>
        <div style={{
          color: charging ? color.status.blue : discharging ? color.status.green : color.text.tertiary,
        }}>
          {charging ? <BatteryCharging size={24} /> : <Battery size={24} />}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 4,
          }}>
            <span className="tabular" style={{
              fontSize: typography.size.xl,
              fontWeight: typography.weight.semibold,
              color: color.text.primary,
            }}>
              {socPct.toFixed(0)}%
            </span>
            <span className="tabular" style={{
              fontSize: typography.size.sm,
              color: color.text.tertiary,
            }}>
              {charging ? "+" : discharging ? "-" : ""}{(Math.abs(powerW) / 1000).toFixed(1)} kW
            </span>
          </div>
          {/* SoC bar */}
          <div style={{
            width: "100%",
            height: 6,
            background: "rgba(255, 255, 255, 0.08)",
            borderRadius: 3,
            overflow: "hidden",
          }}>
            <div style={{
              width: `${socPct}%`,
              height: "100%",
              background: socColor,
              borderRadius: 3,
              transition: "width 500ms ease",
            }} />
          </div>
        </div>
      </div>

      {/* Strategy + Decision */}
      <div style={{ display: "flex", gap: space.md, flexWrap: "wrap" }}>
        <div>
          <div style={{
            fontSize: typography.size.xs,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            Strategy
          </div>
          <StatusBadge value={strategy.state} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{
            fontSize: typography.size.xs,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            Decision
          </div>
          <div style={{
            fontSize: typography.size.sm,
            color: color.text.secondary,
            marginTop: 2,
          }}>
            {formatState(decision.state)}
          </div>
        </div>
      </div>
    </div>
  );
}
