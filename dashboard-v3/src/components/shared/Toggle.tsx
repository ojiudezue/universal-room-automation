/**
 * Entity toggle switch.
 * Calls turn_on/turn_off on the specified domain.
 */
import { useCallback } from "react";
import { color, timing } from "../../design/tokens";
import { useToggle } from "../../hooks/useService";

interface Props {
  entityId: string;
  currentState: string;
  domain?: string;
  label?: string;
  size?: "sm" | "md";
}

export function Toggle({
  entityId,
  currentState,
  domain = "switch",
  label,
  size = "md",
}: Props) {
  const { toggle, loading } = useToggle();
  const isOn = currentState === "on";

  const handleClick = useCallback(() => {
    if (!loading) {
      toggle(domain, entityId, currentState);
    }
  }, [toggle, domain, entityId, currentState, loading]);

  const w = size === "sm" ? 36 : 44;
  const h = size === "sm" ? 20 : 26;
  const thumbSize = size === "sm" ? 16 : 20;
  const thumbOffset = 2;
  const travel = w - thumbSize - thumbOffset * 2;

  const trackStyle: React.CSSProperties = {
    position: "relative",
    width: w,
    height: h,
    background: isOn ? color.accent.primary : "rgba(255, 255, 255, 0.12)",
    borderRadius: h / 2,
    cursor: loading ? "wait" : "pointer",
    border: "none",
    transition: `background ${timing.fast} ${timing.easeOut}`,
    WebkitTapHighlightColor: "transparent",
    flexShrink: 0,
    minHeight: 44,  // touch target
    minWidth: 44,
    display: "flex",
    alignItems: "center",
    padding: 0,
  };

  const thumbStyle: React.CSSProperties = {
    position: "absolute",
    top: (h - thumbSize) / 2,
    left: thumbOffset,
    width: thumbSize,
    height: thumbSize,
    background: isOn ? "#fff" : "rgba(255, 255, 255, 0.7)",
    borderRadius: "50%",
    transition: `transform ${timing.fast} ${timing.easeOut}`,
    transform: isOn ? `translateX(${travel}px)` : "translateX(0)",
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      {label && (
        <span style={{
          fontSize: size === "sm" ? "0.78rem" : "0.85rem",
          color: color.text.secondary,
        }}>
          {label}
        </span>
      )}
      <button
        style={trackStyle}
        onClick={handleClick}
        role="switch"
        aria-checked={isOn}
        aria-label={label ?? `Toggle ${entityId}`}
      >
        <div style={thumbStyle} />
      </button>
    </div>
  );
}
