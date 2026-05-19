/**
 * Left rail navigation — P6 light Navet-styled.
 * 10 tabs split across Overview / Systems / URA groups, matching
 * docs/dashboard-prototypes/v4/p6-light-styled.html.
 */
import {
  Home, Layers, Zap, Thermometer, Users, Shield,
  AlertTriangle, Activity,
} from "lucide-react";

export type TabId =
  | "home"
  | "house"
  | "zones"
  | "rooms"
  | "energy"
  | "hvac"
  | "presence"
  | "security"
  | "safety"
  | "diagnostics";

interface RailItem {
  id: TabId;
  label: string;
  icon: React.FC<{ size?: number; className?: string }>;
  chip?: string;
  section: "Overview" | "Systems" | "URA";
}

const ITEMS: RailItem[] = [
  { id: "home", label: "Home", icon: Home, section: "Overview" },
  { id: "house", label: "House", icon: Home, section: "Overview" },
  { id: "zones", label: "Zones", icon: Layers, chip: "5", section: "Overview" },
  { id: "rooms", label: "Rooms", icon: Layers, chip: "19", section: "Overview" },
  { id: "energy", label: "Energy", icon: Zap, section: "Systems" },
  { id: "hvac", label: "HVAC", icon: Thermometer, section: "Systems" },
  { id: "presence", label: "Presence", icon: Users, chip: "3/4", section: "Systems" },
  { id: "security", label: "Security", icon: Shield, section: "Systems" },
  { id: "safety", label: "Safety", icon: AlertTriangle, section: "Systems" },
  { id: "diagnostics", label: "Diagnostics", icon: Activity, section: "URA" },
];

interface Props {
  active: TabId;
  onChange: (id: TabId) => void;
}

export function Rail({ active, onChange }: Props) {
  // Group by section in render order
  const sections: Array<{ title: string; items: RailItem[] }> = [
    { title: "Overview", items: ITEMS.filter((i) => i.section === "Overview") },
    { title: "Systems", items: ITEMS.filter((i) => i.section === "Systems") },
    { title: "URA", items: ITEMS.filter((i) => i.section === "URA") },
  ];

  return (
    <aside className="rail" role="navigation" aria-label="Dashboard sections">
      <div className="rail-brand">
        <div className="rail-brand-mark">U</div>
        <div className="rail-brand-text">
          <strong>URA</strong>
          <span>v5.0 · p6 light</span>
        </div>
      </div>

      {sections.map(({ title, items }) => (
        <div key={title}>
          <div className="rail-section">{title}</div>
          {items.map((item) => {
            const Icon = item.icon;
            const isActive = item.id === active;
            return (
              <button
                key={item.id}
                className={`rail-link${isActive ? " active" : ""}`}
                onClick={() => onChange(item.id)}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon size={18} className="icon" />
                <span>{item.label}</span>
                {item.chip && <span className="rail-link-chip">{item.chip}</span>}
              </button>
            );
          })}
        </div>
      ))}
    </aside>
  );
}
