/**
 * Tab bar navigation -- sticky top bar with compact pill buttons.
 * Uses lucide-react icons (never emoji or SVG path literals).
 */
import {
  LayoutDashboard, Users, LayoutGrid, Zap,
  Thermometer, Shield, Activity,
} from "lucide-react";
import { color, space, radius, timing, zIndex, type as typography } from "../../design/tokens";

export type TabId =
  | "overview"
  | "presence"
  | "rooms"
  | "energy"
  | "hvac"
  | "security"
  | "diagnostics";

interface TabDef {
  id: TabId;
  label: string;
  icon: React.FC<{ size?: number }>;
}

const TABS: TabDef[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "presence", label: "Presence", icon: Users },
  { id: "rooms", label: "Rooms", icon: LayoutGrid },
  { id: "energy", label: "Energy", icon: Zap },
  { id: "hvac", label: "HVAC", icon: Thermometer },
  { id: "security", label: "Security", icon: Shield },
  { id: "diagnostics", label: "Diagnostics", icon: Activity },
];

interface Props {
  active: TabId;
  onChange: (id: TabId) => void;
}

const barStyle: React.CSSProperties = {
  position: "sticky",
  top: 0,
  zIndex: zIndex.tabBar,
  background: color.surface.base,
  backdropFilter: color.glass.blur,
  WebkitBackdropFilter: color.glass.blur,
  borderBottom: `1px solid ${color.glass.border}`,
  overflowX: "auto",
  WebkitOverflowScrolling: "touch",
  scrollbarWidth: "none",
};

const innerStyle: React.CSSProperties = {
  display: "flex",
  gap: 2,
  padding: `${space.sm}px ${space.md}px`,
  minWidth: "min-content",
};

function pillStyle(isActive: boolean): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 5,
    padding: `${space.sm}px ${space.md}px`,
    border: "none",
    borderRadius: radius.lg,
    background: isActive ? color.accent.primaryDim : "transparent",
    color: isActive ? color.accent.primary : color.text.tertiary,
    fontSize: typography.size.sm,
    fontWeight: typography.weight.medium,
    fontFamily: "inherit",
    cursor: "pointer",
    whiteSpace: "nowrap",
    transition: `all ${timing.fast} ${timing.easeOut}`,
    WebkitTapHighlightColor: "transparent",
    minHeight: 44,
    minWidth: 44,
  };
}

export function TabBar({ active, onChange }: Props) {
  return (
    <nav style={barStyle} aria-label="Dashboard tabs">
      <div style={innerStyle}>
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = tab.id === active;
          return (
            <button
              key={tab.id}
              style={pillStyle(isActive)}
              onClick={() => onChange(tab.id)}
              aria-label={tab.label}
              aria-selected={isActive}
              role="tab"
            >
              <Icon size={16} />
              <span
                style={{
                  display: "inline",
                  // Hide label on very small screens via media query in GlobalStyles
                }}
                className="tab-label-text"
              >
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>
      <style>{`
        @media (max-width: 520px) {
          .tab-label-text { display: none !important; }
        }
      `}</style>
    </nav>
  );
}
