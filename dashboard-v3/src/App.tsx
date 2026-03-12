/**
 * URA v3 Dashboard -- App root.
 * Tab-based SPA with lazy mounting and persistent state.
 */
import { useState, useRef } from "react";
import { Shell } from "./components/layout/Shell";
import { TabBar, type TabId } from "./components/layout/TabBar";
import { OverviewTab } from "./components/tabs/OverviewTab";
import { PresenceTab } from "./components/tabs/PresenceTab";
import { RoomsTab } from "./components/tabs/RoomsTab";
import { EnergyTab } from "./components/tabs/EnergyTab";
import { HVACTab } from "./components/tabs/HVACTab";
import { SecurityTab } from "./components/tabs/SecurityTab";
import { DiagnosticsTab } from "./components/tabs/DiagnosticsTab";

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
  // Track visited tabs for lazy mounting (keep alive once mounted)
  const visited = useRef<Set<TabId>>(new Set(["overview"]));

  const switchTab = (id: TabId) => {
    visited.current.add(id);
    setActiveTab(id);
  };

  return (
    <Shell tabBar={<TabBar active={activeTab} onChange={switchTab} />}>
      {(Object.keys(TAB_COMPONENTS) as TabId[]).map((tabId) => {
        if (!visited.current.has(tabId)) return null;
        const Component = TAB_COMPONENTS[tabId];
        return (
          <div
            key={tabId}
            style={{ display: tabId === activeTab ? "block" : "none" }}
            className="animate-fade-in"
          >
            <Component />
          </div>
        );
      })}
    </Shell>
  );
}
