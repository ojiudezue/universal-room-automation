/**
 * Reusable glass card container.
 * Compact by default (v3 priority: information density).
 */
import type { ReactNode, CSSProperties } from "react";
import { color, space, radius, timing, type as typography } from "../../design/tokens";

interface Props {
  title?: string;
  subtitle?: string;
  badge?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  style?: CSSProperties;
  onClick?: () => void;
  /** Accent color for left border. */
  accent?: string;
  /** No padding variant for custom layouts. */
  flush?: boolean;
}

export function GlassCard({
  title,
  subtitle,
  badge,
  actions,
  children,
  style,
  onClick,
  accent,
  flush,
}: Props) {
  const cardStyle: CSSProperties = {
    background: color.glass.bg,
    backdropFilter: color.glass.blur,
    WebkitBackdropFilter: color.glass.blur,
    border: `1px solid ${color.glass.border}`,
    borderLeft: accent ? `3px solid ${accent}` : `1px solid ${color.glass.border}`,
    borderRadius: radius.lg,
    padding: flush ? 0 : `${space.md}px`,
    display: "flex",
    flexDirection: "column",
    gap: space.sm,
    transition: `border-color ${timing.fast} ${timing.easeOut}`,
    cursor: onClick ? "pointer" : undefined,
    ...style,
  };

  const headerStyle: CSSProperties = {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: flush ? `${space.md}px ${space.md}px 0` : undefined,
  };

  const titleStyle: CSSProperties = {
    fontSize: typography.size.base,
    fontWeight: typography.weight.semibold,
    color: color.text.primary,
    letterSpacing: "0.2px",
  };

  const subtitleStyle: CSSProperties = {
    fontSize: typography.size.xs,
    color: color.text.tertiary,
    marginTop: 1,
  };

  return (
    <div style={cardStyle} onClick={onClick}>
      {(title || badge || actions) && (
        <div style={headerStyle}>
          <div>
            {title && <div style={titleStyle}>{title}</div>}
            {subtitle && <div style={subtitleStyle}>{subtitle}</div>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
            {badge}
            {actions}
          </div>
        </div>
      )}
      {children}
    </div>
  );
}
