/**
 * Energy cost tracking: today, cycle, predicted bill.
 */
import { useEntity, formatNumber } from "../../hooks/useEntity";
import { EntityValue } from "../shared/EntityValue";
import { color, space, type as typography } from "../../design/tokens";
import { DollarSign, TrendingUp } from "lucide-react";

const ENTITIES = {
  costToday: "sensor.ura_energy_coordinator_energy_cost_today",
  costCycle: "sensor.ura_energy_coordinator_energy_cost_this_cycle",
  predictedBill: "sensor.ura_energy_coordinator_predicted_bill",
  importToday: "sensor.ura_energy_coordinator_energy_import_today",
  exportToday: "sensor.ura_energy_coordinator_energy_export_today",
  totalConsumption: "sensor.ura_energy_coordinator_total_consumption",
  netConsumption: "sensor.ura_energy_coordinator_net_consumption",
};

export function CostTracker() {
  const costToday = useEntity(ENTITIES.costToday);
  const costCycle = useEntity(ENTITIES.costCycle);
  const predictedBill = useEntity(ENTITIES.predictedBill);
  const importToday = useEntity(ENTITIES.importToday);
  const exportToday = useEntity(ENTITIES.exportToday);
  const totalConsumption = useEntity(ENTITIES.totalConsumption);
  const netConsumption = useEntity(ENTITIES.netConsumption);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
      {/* Predicted bill -- hero metric */}
      <div style={{ display: "flex", alignItems: "center", gap: space.md }}>
        <div style={{
          width: 40,
          height: 40,
          borderRadius: 10,
          background: "rgba(130, 177, 255, 0.12)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: color.accent.primary,
          flexShrink: 0,
        }}>
          <TrendingUp size={20} />
        </div>
        <div>
          <div style={{
            fontSize: typography.size.xs,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            Predicted Bill
          </div>
          <div className="tabular" style={{
            fontSize: typography.size.xl,
            fontWeight: typography.weight.bold,
            color: color.accent.primary,
          }}>
            {formatNumber(predictedBill.state, { prefix: "$" })}
          </div>
        </div>
      </div>

      {/* Cost breakdown */}
      <EntityValue label="Cost Today" value={formatNumber(costToday.state, { prefix: "$" })} inline />
      <EntityValue label="This Cycle" value={formatNumber(costCycle.state, { prefix: "$" })} inline />

      {/* Energy volumes */}
      <div style={{
        borderTop: `1px solid rgba(255, 255, 255, 0.05)`,
        paddingTop: space.sm,
        marginTop: space.xs,
      }}>
        <EntityValue label="Import Today" value={formatNumber(importToday.state, { suffix: " kWh" })} inline />
        <EntityValue label="Export Today" value={formatNumber(exportToday.state, { suffix: " kWh" })} inline />
        <EntityValue label="Net Consumption" value={formatNumber(netConsumption.state, { suffix: " kWh" })} inline />
        <EntityValue label="Total Consumption" value={formatNumber(totalConsumption.state, { suffix: " kWh" })} inline />
      </div>
    </div>
  );
}
