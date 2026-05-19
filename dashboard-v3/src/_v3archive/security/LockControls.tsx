/**
 * Lock controls with confirm-to-unlock pattern.
 */
import { useState, useCallback } from "react";
import { Lock, Unlock } from "lucide-react";
import { formatState } from "../../hooks/useEntity";
import { useServiceCall } from "../../hooks/useService";
import { color, space, radius, timing, type as typography } from "../../design/tokens";

interface LockData {
  id: string;
  name: string;
  state: string;
}

interface Props {
  locks: LockData[];
}

export function LockControls({ locks }: Props) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const { call } = useServiceCall();

  const handleToggle = useCallback(
    (entityId: string, currentState: string) => {
      if (currentState === "locked") {
        // Require confirmation to unlock
        if (confirmingId === entityId) {
          call({ domain: "lock", service: "unlock", target: { entity_id: entityId } });
          setConfirmingId(null);
        } else {
          setConfirmingId(entityId);
          setTimeout(() => setConfirmingId(null), 5000);
        }
      } else {
        call({ domain: "lock", service: "lock", target: { entity_id: entityId } });
      }
    },
    [confirmingId, call]
  );

  if (locks.length === 0) return null;

  const lockedCount = locks.filter((l) => l.state === "locked").length;
  const allLocked = lockedCount === locks.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
      {locks.map((l) => {
        const isLocked = l.state === "locked";
        const isConfirming = confirmingId === l.id;
        const accentColor = isLocked ? color.status.green : color.status.red;

        return (
          <div
            key={l.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: space.md,
              padding: `${space.md}px`,
              borderRadius: radius.md,
              border: `1px solid ${isLocked ? "rgba(102, 187, 106, 0.15)" : "rgba(239, 83, 80, 0.15)"}`,
              background: isLocked ? "rgba(102, 187, 106, 0.05)" : "rgba(239, 83, 80, 0.05)",
              borderLeft: `3px solid ${accentColor}`,
            }}
          >
            {/* Icon */}
            <div style={{
              width: 36,
              height: 36,
              borderRadius: radius.full,
              background: `${accentColor}18`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: accentColor,
              flexShrink: 0,
            }}>
              {isLocked ? <Lock size={18} /> : <Unlock size={18} />}
            </div>

            {/* Info */}
            <div style={{ flex: 1 }}>
              <div style={{
                fontSize: typography.size.base,
                fontWeight: typography.weight.semibold,
                color: color.text.primary,
              }}>
                {l.name.replace(/_/g, " ")}
              </div>
              <div style={{
                fontSize: typography.size.xs,
                color: color.text.tertiary,
                textTransform: "uppercase",
                letterSpacing: "0.4px",
              }}>
                {formatState(l.state)}
              </div>
            </div>

            {/* Action */}
            <button
              style={{
                padding: `${space.sm}px ${space.lg}px`,
                border: `1px solid ${isConfirming ? color.status.red : "rgba(255, 255, 255, 0.1)"}`,
                borderRadius: radius.md,
                background: isConfirming ? "rgba(239, 83, 80, 0.12)" : "rgba(255, 255, 255, 0.06)",
                color: isConfirming ? color.status.red : color.text.secondary,
                fontSize: typography.size.sm,
                fontWeight: typography.weight.semibold,
                fontFamily: "inherit",
                cursor: "pointer",
                transition: `all ${timing.fast}`,
                minHeight: 36,
                minWidth: 44,
              }}
              onClick={() => handleToggle(l.id, l.state)}
              aria-label={isLocked ? `Unlock ${l.name}` : `Lock ${l.name}`}
            >
              {isLocked ? (isConfirming ? "Confirm?" : "Unlock") : "Lock"}
            </button>
          </div>
        );
      })}
    </div>
  );
}
