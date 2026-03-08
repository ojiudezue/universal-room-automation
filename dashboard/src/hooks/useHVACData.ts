import { useEntity } from "@hakit/core";
import { HVAC } from "../types/entities";

export function useHVACData() {
  const mode = useEntity(HVAC.MODE);
  const arresterState = useEntity(HVAC.ARRESTER_STATE);
  const zone1Status = useEntity(HVAC.ZONE_1_STATUS);
  const zone2Status = useEntity(HVAC.ZONE_2_STATUS);
  const zone3Status = useEntity(HVAC.ZONE_3_STATUS);
  const zone1Preset = useEntity(HVAC.ZONE_1_PRESET);
  const zone2Preset = useEntity(HVAC.ZONE_2_PRESET);
  const zone3Preset = useEntity(HVAC.ZONE_3_PRESET);
  const arresterSwitch = useEntity(HVAC.ARRESTER_SWITCH);
  const observationMode = useEntity(HVAC.OBSERVATION_MODE);

  return {
    mode, arresterState,
    arresterSwitch, observationMode,
    zones: [
      { name: "Zone 1", status: zone1Status, preset: zone1Preset },
      { name: "Zone 2", status: zone2Status, preset: zone2Preset },
      { name: "Zone 3", status: zone3Status, preset: zone3Preset },
    ],
  };
}
