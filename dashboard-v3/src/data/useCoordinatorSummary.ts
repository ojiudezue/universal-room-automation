/**
 * useCoordinatorSummary — typed accessor for the coordinator-manager summary
 * sensor used by Diagnostics, Energy, Home, and the per-coordinator tabs.
 *
 * The summary lives at `sensor.ura_coordinator_manager_coordinator_summary`
 * and carries `extra_state_attributes` populated by
 * `coordinator_manager._compute_coordinator_summary`. Every tab that needs
 * "is this coordinator healthy?" reads this — DO NOT duplicate the SummaryAttrs
 * shape inline.
 *
 * Loading semantics: the returned `attrs` is null while the entity hasn't
 * materialised yet (HA initial-fetch in progress) AND when the entity reports
 * unavailable/unknown. Callers render "—" placeholders in both cases; the
 * `loading` and `unavailable` booleans are passed through for tabs that want
 * to draw a different shimmer/empty state.
 */
import { useUraSensorAttrs } from "./useUraSensor";

/** Status produced by coordinator_manager for each registered coordinator. */
export interface PerCoordinatorStatus {
  status: "nominal" | "advisory" | "alert" | "critical" | string;
  active_anomalies: number;
  enabled: boolean;
}

/**
 * Shape of `sensor.ura_coordinator_manager_coordinator_summary`'s
 * `extra_state_attributes`. Optional fields tolerate older URA versions that
 * may not emit a given key — callers must null-check.
 */
export interface SummaryAttrs {
  health_status?: "green" | "orange" | "red" | string;
  status_per_coordinator?: Record<string, PerCoordinatorStatus>;
  house_state?: string;
  coordinators_registered?: number;
  coordinators_active?: number;
  decisions_today?: number;
  conflicts_resolved_today?: number;
}

/** Stable entity id — single point of truth for the summary sensor. */
export const COORDINATOR_SUMMARY_SENSOR =
  "sensor.ura_coordinator_manager_coordinator_summary";

/**
 * Wraps `useUraSensorAttrs<SummaryAttrs>` so call sites can do:
 *
 *   const { attrs, loading, unavailable } = useCoordinatorSummary();
 *
 * without re-importing the shape or re-typing the entity id.
 */
export function useCoordinatorSummary(): {
  attrs: SummaryAttrs | null;
  loading: boolean;
  unavailable: boolean;
} {
  return useUraSensorAttrs<SummaryAttrs>(COORDINATOR_SUMMARY_SENSOR);
}
