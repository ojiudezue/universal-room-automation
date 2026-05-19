/**
 * useUraSensor — thin wrappers around @hakit/core's `useEntity` for URA sensors.
 *
 * Design notes (set the pattern for the remaining 9 tabs):
 *  - Each card calls its OWN hook per entity. hakit's `useEntity` is per-entity
 *    and tracks its own subscription. Don't try to batch into one mega-hook.
 *  - URA's "None-on-zero" contract: compliance_rate and similar can be the
 *    literal string "unknown" (Python None coerced to HA's UNAVAILABLE/UNKNOWN
 *    state). `useUraSensorInt` returns `null` for "unknown" / "unavailable" /
 *    non-numeric so callers can render "—" without conditional branches.
 *  - `returnNullIfNotFound: true` keeps the hook safe during HA reloads when an
 *    entity briefly disappears; callers see `null` instead of an exception.
 *  - Loading state: hakit doesn't expose an explicit "loading" flag at the
 *    entity level. The closest signal is "the entity ref is null AND the
 *    connection isn't yet ready". We expose `loading` as "entity not yet
 *    materialised", and `unavailable` as "entity present but HA reports
 *    unavailable/unknown".
 */
import { useEntity } from "@hakit/core";
import type { HassEntity } from "home-assistant-js-websocket";

export interface UraSensorReadout {
  /** Raw state string (e.g. "42", "unknown", "unavailable") or null when entity missing. */
  state: string | null;
  /** True while hakit hasn't materialised the entity yet (initial subscription). */
  loading: boolean;
  /** True when entity exists but HA reports it as unavailable/unknown. */
  unavailable: boolean;
  /** Pass-through attributes when present (typed loosely; callers narrow). */
  attributes: HassEntity["attributes"] | null;
  /** ISO timestamp HA last updated the entity (for relative-time formatting). */
  last_updated: string | null;
}

/**
 * Cast helper: hakit's `EntityName` type is `${AllDomains}.${string}` | "unknown".
 * Our entity IDs are runtime strings (read from a const), so we widen to the
 * union via an unchecked cast. This is the documented escape hatch for dynamic
 * IDs — hakit ships with a type narrowing flow we deliberately don't use here.
 */
function asEntityName(id: string): Parameters<typeof useEntity>[0] {
  return id as Parameters<typeof useEntity>[0];
}

/**
 * Base hook — returns the raw readout. Other helpers wrap this.
 *
 * IMPORTANT: do NOT call this conditionally. Hooks must be called in the same
 * order every render. If you have N optional entities, call N hooks every time.
 */
export function useUraSensorState(entityId: string): UraSensorReadout {
  const entity = useEntity(asEntityName(entityId), { returnNullIfNotFound: true });

  if (entity == null) {
    // Entity not (yet) found. hakit can't distinguish "loading" from "really
    // missing" cleanly at this layer; treat as loading. After HA finishes its
    // initial state fetch and the entity is still absent, downstream UI will
    // simply keep showing the placeholder — acceptable for v1.
    return {
      state: null,
      loading: true,
      unavailable: false,
      attributes: null,
      last_updated: null,
    };
  }

  const raw = (entity.state ?? "") as string;
  const unavailable = raw === "unavailable" || raw === "unknown" || raw === "";

  return {
    state: raw,
    loading: false,
    unavailable,
    attributes: entity.attributes ?? null,
    last_updated: entity.last_updated ?? null,
  };
}

/**
 * Returns the entity's state as an int, or null when missing / unknown /
 * non-parseable. Use for decisions_today, override_frequency, compliance_rate.
 */
export function useUraSensorInt(entityId: string): {
  value: number | null;
  loading: boolean;
} {
  const { state, loading, unavailable } = useUraSensorState(entityId);
  if (loading) return { value: null, loading: true };
  if (unavailable || state == null) return { value: null, loading: false };
  const parsed = Number.parseInt(state, 10);
  if (Number.isNaN(parsed)) return { value: null, loading: false };
  return { value: parsed, loading: false };
}

/**
 * Returns the entity's state as a float (e.g. db_size MB). Same null contract.
 */
export function useUraSensorFloat(entityId: string): {
  value: number | null;
  loading: boolean;
} {
  const { state, loading, unavailable } = useUraSensorState(entityId);
  if (loading) return { value: null, loading: true };
  if (unavailable || state == null) return { value: null, loading: false };
  const parsed = Number.parseFloat(state);
  if (Number.isNaN(parsed)) return { value: null, loading: false };
  return { value: parsed, loading: false };
}

/**
 * Returns typed extra_state_attributes for an entity. Generic T lets callers
 * specify a shape (e.g. for coordinator_summary's status_per_coordinator).
 */
export function useUraSensorAttrs<T = Record<string, unknown>>(
  entityId: string,
): { attrs: T | null; loading: boolean; unavailable: boolean } {
  const { attributes, loading, unavailable } = useUraSensorState(entityId);
  return {
    attrs: (attributes as T | null) ?? null,
    loading,
    unavailable,
  };
}

/**
 * Formats an ISO timestamp as a short relative string:
 *   - "just now"        (< 60s ago)
 *   - "5 min ago"       (< 60m ago)
 *   - "3 hr ago"        (< 24h ago)
 *   - "Jan 5"           (same year)
 *   - "Jan 5 2024"      (different year)
 * Returns "—" for null / unparseable.
 *
 * v1 uses Date.now() directly; deliberately not using a ticking ref hook so
 * timestamps don't shimmer-rerender every second. Re-renders happen when the
 * underlying entity updates, which is enough granularity for this dashboard.
 */
export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const deltaSec = Math.floor((Date.now() - t) / 1000);
  if (deltaSec < 0) return "just now";
  if (deltaSec < 60) return "just now";
  if (deltaSec < 3600) return `${Math.floor(deltaSec / 60)} min ago`;
  if (deltaSec < 86400) return `${Math.floor(deltaSec / 3600)} hr ago`;
  const d = new Date(t);
  const now = new Date();
  const month = d.toLocaleString("en-US", { month: "short" });
  const day = d.getDate();
  if (d.getFullYear() === now.getFullYear()) return `${month} ${day}`;
  return `${month} ${day} ${d.getFullYear()}`;
}

/**
 * Short clock-time form (HH:MM) for timeline rows. Used by Diagnostics decision
 * stream where we want compact wall-clock times rather than relative deltas.
 */
export function formatClockTime(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
