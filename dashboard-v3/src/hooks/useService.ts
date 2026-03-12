/**
 * Hook for calling Home Assistant services with loading/error state.
 */
import { useHass } from "@hakit/core";
import { useCallback, useState } from "react";

interface ServiceCallOptions {
  domain: string;
  service: string;
  target?: { entity_id: string | string[] };
  data?: Record<string, unknown>;
}

interface ServiceCallState {
  loading: boolean;
  error: string | null;
}

/**
 * Returns a typed callService function and loading state.
 * Wraps @hakit/core's callService with as-never casts
 * centralized in one place (avoids spreading `as never` everywhere).
 */
export function useServiceCall() {
  const { callService } = useHass();
  const [state, setState] = useState<ServiceCallState>({ loading: false, error: null });

  const call = useCallback(
    async (opts: ServiceCallOptions) => {
      setState({ loading: true, error: null });
      try {
        await callService({
          domain: opts.domain as never,
          service: opts.service as never,
          target: opts.target,
          serviceData: opts.data as never,
        });
        setState({ loading: false, error: null });
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Service call failed";
        setState({ loading: false, error: msg });
        console.error(`[URA] Service call failed: ${opts.domain}.${opts.service}`, err);
      }
    },
    [callService]
  );

  return { call, ...state };
}

/**
 * Quick toggle helper: calls turn_on/turn_off based on current state.
 */
export function useToggle() {
  const { call, loading } = useServiceCall();

  const toggle = useCallback(
    (domain: string, entityId: string, currentState: string) => {
      const service = currentState === "on" ? "turn_off" : "turn_on";
      return call({ domain, service, target: { entity_id: entityId } });
    },
    [call]
  );

  return { toggle, loading };
}
