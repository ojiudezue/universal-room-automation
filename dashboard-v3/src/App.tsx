/**
 * URA Dashboard v5.0 — App root (P6 light Navet-styled).
 * 10 tabs across Overview / Systems / URA groups per dashboard v4 fulcrum P2.
 * Tab content for v5.0 D1 is stub placeholders; live wiring per D3-D7.
 */
import { useState } from "react";
import { Shell } from "./components/layout/Shell";
import { TabShell, LucideSprite } from "./components/tabs-shell/TabShell";
import type { TabId } from "./components/layout/Rail";

export default function App() {
  const [active, setActive] = useState<TabId>("home");

  return (
    <>
      {/* Lucide SVG sprite mounted once at app root */}
      <LucideSprite />
      <Shell active={active} onChange={setActive}>
        <TabShell active={active} />
      </Shell>
    </>
  );
}
