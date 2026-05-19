/**
 * Mobile horizontal tab strip — shown when body.mobile class active OR viewport ≤768px.
 * Mirrors the rail's 10 tabs as horizontally-scrollable pills.
 */
import {
  Home, Layers, Zap, Thermometer, Users, Shield, AlertTriangle, Activity,
} from "lucide-react";
import type { TabId } from "./Rail";

interface MobileTab {
  id: TabId;
  label: string;
  icon: React.FC<{ size?: number }>;
}

const TABS: MobileTab[] = [
  { id: "home", label: "Home", icon: Home },
  { id: "house", label: "House", icon: Home },
  { id: "zones", label: "Zones", icon: Layers },
  { id: "rooms", label: "Rooms", icon: Layers },
  { id: "energy", label: "Energy", icon: Zap },
  { id: "hvac", label: "HVAC", icon: Thermometer },
  { id: "presence", label: "Presence", icon: Users },
  { id: "security", label: "Security", icon: Shield },
  { id: "safety", label: "Safety", icon: AlertTriangle },
  { id: "diagnostics", label: "Diag", icon: Activity },
];

interface Props {
  active: TabId;
  onChange: (id: TabId) => void;
}

export function MobileTabs({ active, onChange }: Props) {
  return (
    <nav className="mobile-tabs" aria-label="Dashboard tabs">
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            className={isActive ? "active" : ""}
            onClick={() => onChange(tab.id)}
            aria-current={isActive ? "page" : undefined}
          >
            <Icon size={16} />
            <span>{tab.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
