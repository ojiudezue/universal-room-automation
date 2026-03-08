import { useEntity } from "@hakit/core";
import { SECURITY } from "../types/entities";

export function useSecurityData() {
  const armedState = useEntity(SECURITY.ARMED_STATE);
  const openEntries = useEntity(SECURITY.OPEN_ENTRIES);
  const lastLockSweep = useEntity(SECURITY.LAST_LOCK_SWEEP);
  const expectedArrivals = useEntity(SECURITY.EXPECTED_ARRIVALS);

  return { armedState, openEntries, lastLockSweep, expectedArrivals };
}
