/**
 * statusColors — shared display helpers for the P6 dashboard.
 *
 * Extracted from Diagnostics.tsx so Energy / Home / HVAC / Safety / Security
 * tabs all map URA coordinator status the same way. Keep this in lock-step
 * with `status_per_coordinator[*].status` values produced by
 * `sensor.ura_coordinator_manager_coordinator_summary` (see
 * coordinator_manager `_compute_coordinator_summary`).
 *
 *   nominal   → green   (.status-green / badge "healthy")
 *   advisory  → orange  (.status-orange / badge "attention")
 *   alert     → red     (.status-red / badge "alert")
 *   critical  → red     (.status-red / badge "critical")
 *   <missing> → no card class, "unknown" badge
 *
 * Number formatting (`num`) and time formatting (`formatClockTime`) live here
 * so loading / unavailable states render the same "—" placeholder across
 * every tab — no per-card divergence.
 */

/** Maps coordinator status → CSS modifier class for the surrounding .card. */
export function statusToCardClass(status: string | undefined): string {
  switch (status) {
    case "nominal":
      return "status-green";
    case "advisory":
      return "status-orange";
    case "alert":
    case "critical":
      return "status-red";
    default:
      return "";
  }
}

/** Maps coordinator status → label + badge color used in the card header. */
export function statusToBadge(
  status: string | undefined,
): { label: string; cls: string } {
  switch (status) {
    case "nominal":
      return { label: "healthy", cls: "green" };
    case "advisory":
      return { label: "attention", cls: "orange" };
    case "alert":
      return { label: "alert", cls: "red" };
    case "critical":
      return { label: "critical", cls: "red" };
    default:
      return { label: "unknown", cls: "" };
  }
}

/**
 * Render a number or "—" placeholder. Optional suffix (e.g. " kW", "%") is
 * appended when the value is present, so callers can pass `num(v, " kW")`
 * instead of branching on null.
 */
export function num(value: number | null, suffix = ""): string {
  if (value == null) return "—";
  return `${value}${suffix}`;
}

/**
 * Short clock-time form (HH:MM, 24h). Used by Diagnostics' decision stream
 * and the Energy / Home tabs' compact timestamp columns.
 *
 * NOTE: this is a re-export of the implementation in useUraSensor.ts to keep
 * a single source of truth — Diagnostics was previously importing it from
 * useUraSensor directly. Both import paths now resolve to the same impl.
 */
export { formatClockTime } from "./useUraSensor";
