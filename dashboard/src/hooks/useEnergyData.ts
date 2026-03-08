import { useEntity } from "@hakit/core";
import { ENERGY } from "../types/entities";

export function useEnergyData() {
  const touPeriod = useEntity(ENERGY.TOU_PERIOD);
  const touRate = useEntity(ENERGY.TOU_RATE);
  const touSeason = useEntity(ENERGY.TOU_SEASON);
  const batteryStrategy = useEntity(ENERGY.BATTERY_STRATEGY);
  const batteryDecision = useEntity(ENERGY.BATTERY_DECISION);
  const solarClass = useEntity(ENERGY.SOLAR_DAY_CLASS);
  const hvacConstraint = useEntity(ENERGY.HVAC_CONSTRAINT);
  const loadShedding = useEntity(ENERGY.LOAD_SHEDDING);
  const situation = useEntity(ENERGY.ENERGY_SITUATION);
  const importToday = useEntity(ENERGY.IMPORT_TODAY);
  const exportToday = useEntity(ENERGY.EXPORT_TODAY);
  const costToday = useEntity(ENERGY.COST_TODAY);
  const costCycle = useEntity(ENERGY.COST_CYCLE);
  const predictedBill = useEntity(ENERGY.PREDICTED_BILL);
  const forecastToday = useEntity(ENERGY.FORECAST_TODAY);
  const forecastAccuracy = useEntity(ENERGY.FORECAST_ACCURACY);
  const totalConsumption = useEntity(ENERGY.TOTAL_CONSUMPTION);
  const netConsumption = useEntity(ENERGY.NET_CONSUMPTION);
  const envoyAvailable = useEntity(ENERGY.ENVOY_AVAILABLE);

  return {
    touPeriod, touRate, touSeason,
    batteryStrategy, batteryDecision,
    solarClass, hvacConstraint, loadShedding,
    situation, importToday, exportToday,
    costToday, costCycle, predictedBill,
    forecastToday, forecastAccuracy,
    totalConsumption, netConsumption,
    envoyAvailable,
  };
}
