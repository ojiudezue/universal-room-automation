/**
 * URA Dashboard v5.0 — App root (P6 light Navet-styled).
 * 10 tabs across Overview / Systems / URA groups per dashboard v4 fulcrum P2.
 * Tab content for v5.0 D1 is stub placeholders; live wiring per D3-D7.
 */
import { useState, useRef } from "react";
import { Shell } from "./components/layout/Shell";
import type { TabId } from "./components/layout/Rail";

function TabPlaceholder({ id, label }: { id: TabId; label: string }) {
  return (
    <div style={{ padding: "var(--space-lg)" }}>
      <h1 style={{
        fontSize: "var(--text-xl)",
        fontWeight: 700,
        margin: "0 0 var(--space-md)",
        color: "var(--text-primary)",
      }}>
        {label}
      </h1>
      <p style={{ color: "var(--text-secondary)" }}>
        Tab <code>{id}</code> — placeholder. Live-wired content lands in D3-D7.
      </p>
    </div>
  );
}

const TAB_LABELS: Record<TabId, string> = {
  home: "Home",
  house: "House",
  zones: "Zones",
  rooms: "Rooms",
  energy: "Energy",
  hvac: "HVAC",
  presence: "Presence",
  security: "Security",
  safety: "Safety",
  diagnostics: "Diagnostics",
};

const ALL_TABS = Object.keys(TAB_LABELS) as TabId[];

export default function App() {
  const [active, setActive] = useState<TabId>("home");
  const visited = useRef<Set<TabId>>(new Set(["home"]));

  const switchTab = (id: TabId) => {
    visited.current.add(id);
    setActive(id);
  };

  return (
    <Shell active={active} onChange={switchTab}>
      {ALL_TABS.map((tabId) => {
        if (!visited.current.has(tabId)) return null;
        return (
          <div
            key={tabId}
            style={{ display: tabId === active ? "block" : "none" }}
          >
            <TabPlaceholder id={tabId} label={TAB_LABELS[tabId]} />
          </div>
        );
      })}
    </Shell>
  );
}
