import { useState, useRef } from "react";
import { OverviewTab } from "./components/tabs/OverviewTab";
import { PresenceTab } from "./components/tabs/PresenceTab";
import { RoomsTab } from "./components/tabs/RoomsTab";
import { EnergyTab } from "./components/tabs/EnergyTab";
import { HVACTab } from "./components/tabs/HVACTab";
import { SecurityTab } from "./components/tabs/SecurityTab";
import { DiagnosticsTab } from "./components/tabs/DiagnosticsTab";

type TabId = "overview" | "presence" | "rooms" | "energy" | "hvac" | "security" | "diagnostics";

interface TabDef {
  id: TabId;
  label: string;
  bg: string;
  icon: string; // SVG path
}

const BASE = "/universal_room_automation_panel";

const TABS: TabDef[] = [
  {
    id: "overview", label: "Overview", bg: "michele-lana.jpg",
    icon: "M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z",
  },
  {
    id: "presence", label: "Presence", bg: "niranjan-udas.jpg",
    icon: "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
  },
  {
    id: "rooms", label: "Rooms", bg: "thanos-pal.jpg",
    icon: "M4 5h7v6H4zm9 0h7v6h-7zM4 13h7v6H4zm9 0h7v6h-7z",
  },
  {
    id: "energy", label: "Energy", bg: "daniil-silantev.jpg",
    icon: "M7 2v11h3v9l7-12h-4l4-8z",
  },
  {
    id: "hvac", label: "HVAC", bg: "vasco-sanchez.jpg",
    icon: "M15 13V5c0-1.66-1.34-3-3-3S9 3.34 9 5v8c-1.21.91-2 2.37-2 4 0 2.76 2.24 5 5 5s5-2.24 5-5c0-1.63-.79-3.09-2-4z",
  },
  {
    id: "security", label: "Security", bg: "moritz-kindler.jpg",
    icon: "M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z",
  },
  {
    id: "diagnostics", label: "Diagnostics", bg: "homa-appliances.jpg",
    icon: "M19.5 3.5L18 2l-1.5 1.5L15 2l-1.5 1.5L12 2l-1.5 1.5L9 2 7.5 3.5 6 2v14H3v3c0 1.66 1.34 3 3 3h12c1.66 0 3-1.34 3-3V2l-1.5 1.5z",
  },
];

const TAB_COMPONENTS: Record<TabId, React.FC> = {
  overview: OverviewTab,
  presence: PresenceTab,
  rooms: RoomsTab,
  energy: EnergyTab,
  hvac: HVACTab,
  security: SecurityTab,
  diagnostics: DiagnosticsTab,
};

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  // Track which tabs have been visited so we can lazily mount but keep alive
  const visited = useRef<Set<TabId>>(new Set(["overview"]));

  const switchTab = (id: TabId) => {
    visited.current.add(id);
    setActiveTab(id);
  };

  return (
    <div className="app-shell">
      {/* Background layers — crossfade via opacity */}
      {TABS.map(tab => (
        <div
          key={tab.id}
          className="bg-layer"
          style={{
            backgroundImage: tab.id === activeTab ? `url(${BASE}/backgrounds/${tab.bg})` : undefined,
            opacity: tab.id === activeTab ? 1 : 0,
          }}
        />
      ))}

      <div className="bg-scrim" />

      {/* Tab navigation */}
      <nav className="tab-bar">
        <div className="tab-bar-inner">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`tab-pill${tab.id === activeTab ? " tab-active" : ""}`}
              onClick={() => switchTab(tab.id)}
              aria-label={tab.label}
              aria-selected={tab.id === activeTab}
              role="tab"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d={tab.icon} />
              </svg>
              <span className="tab-label">{tab.label}</span>
            </button>
          ))}
        </div>
      </nav>

      {/* Tab content — keep visited tabs mounted to preserve state/subscriptions */}
      <main className="tab-content" role="tabpanel">
        {TABS.map(tab => {
          if (!visited.current.has(tab.id)) return null;
          const Component = TAB_COMPONENTS[tab.id];
          return (
            <div key={tab.id} style={{ display: tab.id === activeTab ? "block" : "none" }}>
              <Component />
            </div>
          );
        })}
      </main>
    </div>
  );
}
