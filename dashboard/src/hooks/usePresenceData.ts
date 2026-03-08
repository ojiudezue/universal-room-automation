import { useEntity } from "@hakit/core";
import { PRESENCE } from "../types/entities";

/** Subscribe to Presence Coordinator entities. */
export function usePresenceData() {
  const houseState = useEntity(PRESENCE.HOUSE_STATE);

  return { houseState };
}
