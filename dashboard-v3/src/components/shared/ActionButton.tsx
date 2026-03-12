/**
 * Button that triggers an HA service call.
 * Shows loading state during execution and confirm state for destructive actions.
 */
import { useState, useCallback, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { color, space, radius, timing, type as typography } from "../../design/tokens";
import { useServiceCall } from "../../hooks/useService";

interface Props {
  label: string;
  icon?: ReactNode;
  domain: string;
  service: string;
  entityId: string;
  data?: Record<string, unknown>;
  variant?: "default" | "primary" | "danger";
  /** Require a second click to confirm. */
  confirm?: boolean;
  /** Confirm timeout in ms (default 5000). */
  confirmTimeout?: number;
  disabled?: boolean;
  compact?: boolean;
}

export function ActionButton({
  label,
  icon,
  domain,
  service,
  entityId,
  data,
  variant = "default",
  confirm = false,
  confirmTimeout = 5000,
  disabled = false,
  compact = false,
}: Props) {
  const { call, loading } = useServiceCall();
  const [confirming, setConfirming] = useState(false);

  const handleClick = useCallback(() => {
    if (disabled || loading) return;

    if (confirm && !confirming) {
      setConfirming(true);
      setTimeout(() => setConfirming(false), confirmTimeout);
      return;
    }

    setConfirming(false);
    call({ domain, service, target: { entity_id: entityId }, data });
  }, [disabled, loading, confirm, confirming, confirmTimeout, call, domain, service, entityId, data]);

  const bgMap = {
    default: "rgba(255, 255, 255, 0.06)",
    primary: color.accent.primaryDim,
    danger: "rgba(239, 83, 80, 0.12)",
  };

  const colorMap = {
    default: color.text.secondary,
    primary: color.accent.primary,
    danger: color.status.red,
  };

  const borderMap = {
    default: color.glass.border,
    primary: "rgba(130, 177, 255, 0.2)",
    danger: "rgba(239, 83, 80, 0.25)",
  };

  const style: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: space.xs,
    padding: compact ? `${space.xs}px ${space.sm}px` : `${space.sm}px ${space.lg}px`,
    border: `1px solid ${confirming ? colorMap[variant] : borderMap[variant]}`,
    borderRadius: radius.md,
    background: confirming ? `${colorMap[variant]}22` : bgMap[variant],
    color: colorMap[variant],
    fontSize: compact ? typography.size.xs : typography.size.sm,
    fontWeight: typography.weight.semibold,
    fontFamily: "inherit",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
    transition: `all ${timing.fast} ${timing.easeOut}`,
    whiteSpace: "nowrap",
    minHeight: 36,
    minWidth: 44,
    textTransform: "uppercase",
    letterSpacing: "0.3px",
  };

  return (
    <button
      style={style}
      onClick={handleClick}
      disabled={disabled || loading}
      aria-label={confirming ? `Confirm ${label}` : label}
    >
      {loading ? (
        <Loader2 size={compact ? 12 : 14} className="animate-spin" />
      ) : (
        icon
      )}
      {confirming ? "Confirm?" : label}
    </button>
  );
}
