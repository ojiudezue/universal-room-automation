/**
 * Re-export @hakit/core's useEntity and useHass for consistent imports.
 * Also provides utility hooks for common patterns.
 */
export { useEntity, useHass } from "@hakit/core";

import { useHass } from "@hakit/core";
import { useMemo, useRef } from "react";

/** Entity state with attributes. */
export interface EntityState {
  state: string;
  attributes: Record<string, unknown>;
  last_changed?: string;
  last_updated?: string;
  entity_id?: string;
}

const EMPTY: EntityState = { state: "unavailable", attributes: {} };

/**
 * Get a specific entity from the global entity map.
 * More efficient than useEntity() when you only need to read state,
 * because it shares a single subscription.
 */
export function useEntityState(entityId: string): EntityState {
  const { getAllEntities } = useHass();
  const all = getAllEntities();
  return (all[entityId] as EntityState | undefined) ?? EMPTY;
}

/**
 * Filter entities by prefix with stable reference.
 * Uses a ref-based comparator to avoid unnecessary re-renders
 * when the entity list hasn't actually changed.
 */
export function useEntitiesByPrefix(prefix: string) {
  const { getAllEntities } = useHass();
  const allEntities = getAllEntities();
  const prevRef = useRef<string>("");

  return useMemo(() => {
    const entries = Object.entries(allEntities)
      .filter(([id]) => id.startsWith(prefix))
      .map(([id, e]) => ({
        entity_id: id,
        state: (e as EntityState).state,
        attributes: (e as EntityState).attributes ?? {},
        last_changed: (e as EntityState).last_changed,
        last_updated: (e as EntityState).last_updated,
      }));

    // Simple cache key to avoid recalc when entities haven't changed
    const key = entries.map(e => `${e.entity_id}:${e.state}`).join("|");
    if (key === prevRef.current) {
      return entries; // same data, but useMemo dep changed -- still returns new array
    }
    prevRef.current = key;
    return entries;
  }, [allEntities, prefix]);
}

/**
 * Format an entity state for display.
 */
export function formatState(state: string | undefined | null): string {
  if (!state || state === "unknown" || state === "unavailable") return "--";
  return state.replace(/_/g, " ");
}

/**
 * Format a numeric entity state.
 */
export function formatNumber(
  state: string | undefined | null,
  opts?: { prefix?: string; suffix?: string; decimals?: number }
): string {
  if (!state || state === "unknown" || state === "unavailable") return "--";
  const n = parseFloat(state);
  if (isNaN(n)) return state;
  const dec = opts?.decimals ?? (Math.abs(n) >= 100 ? 0 : Math.abs(n) >= 10 ? 1 : 2);
  return `${opts?.prefix ?? ""}${n.toFixed(dec)}${opts?.suffix ?? ""}`;
}

/**
 * Relative time string from ISO timestamp.
 */
export function timeAgo(iso: string | undefined): string {
  if (!iso) return "--";
  const ts = new Date(iso).getTime();
  if (isNaN(ts)) return "--";
  const diff = Date.now() - ts;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}
