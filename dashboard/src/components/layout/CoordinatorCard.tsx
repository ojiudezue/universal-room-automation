import type { CSSProperties, ReactNode } from "react";

const card: CSSProperties = {
  background: "var(--ura-card)",
  border: "1px solid var(--ura-card-border)",
  borderRadius: "12px",
  padding: "20px",
  display: "flex",
  flexDirection: "column",
  gap: "16px",
};

const headerStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};

const titleStyle: CSSProperties = {
  fontSize: "1.1rem",
  fontWeight: 600,
};

interface Props {
  title: string;
  badge?: ReactNode;
  children: ReactNode;
}

export function CoordinatorCard({ title, badge, children }: Props) {
  return (
    <div style={card}>
      <div style={headerStyle}>
        <span style={titleStyle}>{title}</span>
        {badge}
      </div>
      {children}
    </div>
  );
}
