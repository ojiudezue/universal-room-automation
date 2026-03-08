import type { ReactNode, CSSProperties } from "react";

interface Props {
  title?: string;
  subtitle?: string;
  badge?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  compact?: boolean;
  style?: CSSProperties;
  onClick?: () => void;
}

export function GlassCard({ title, subtitle, badge, actions, children, compact, style, onClick }: Props) {
  return (
    <div
      className={`glass-card${compact ? " glass-card-compact" : ""}`}
      onClick={onClick}
      style={{ ...(onClick ? { cursor: "pointer" } : {}), ...style }}
    >
      {(title || badge || actions) && (
        <div className="glass-card-header">
          <div>
            {title && <div className="glass-card-title">{title}</div>}
            {subtitle && <div className="glass-card-subtitle">{subtitle}</div>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {badge}
            {actions}
          </div>
        </div>
      )}
      {children}
    </div>
  );
}
