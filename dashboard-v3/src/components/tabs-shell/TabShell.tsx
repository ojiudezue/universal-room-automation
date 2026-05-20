/**
 * Tab shell — routes the active tab id to its React component.
 *
 * v5.0.2 perf: each tab is lazy-loaded via React.lazy + Suspense so first
 * paint only downloads the active tab's code chunk. Home is the default
 * landing tab, so its chunk gets pre-fetched on idle to avoid a Suspense
 * flash for the most common navigation.
 *
 * Lucide SVGs use <use href="#lc-X"/> — the sprite must be present in the
 * DOM once. _lucide-sprite.html provides it; LucideSprite() mounts it.
 *
 * The static .html fragments at dashboard-v3/src/components/tabs-shell/*.html
 * remain as the visual reference that the React ports were diffed against.
 */
import { lazy, Suspense } from "react";
import type { TabId } from "../layout/Rail";

const Diagnostics = lazy(() =>
  import("../tabs/Diagnostics").then((m) => ({ default: m.Diagnostics })),
);
const Energy = lazy(() =>
  import("../tabs/Energy").then((m) => ({ default: m.Energy })),
);
const Home = lazy(() =>
  import("../tabs/Home").then((m) => ({ default: m.Home })),
);
const House = lazy(() =>
  import("../tabs/House").then((m) => ({ default: m.House })),
);
const HVAC = lazy(() =>
  import("../tabs/HVAC").then((m) => ({ default: m.HVAC })),
);
const Zones = lazy(() =>
  import("../tabs/Zones").then((m) => ({ default: m.Zones })),
);
const Rooms = lazy(() =>
  import("../tabs/Rooms").then((m) => ({ default: m.Rooms })),
);
const Presence = lazy(() =>
  import("../tabs/Presence").then((m) => ({ default: m.Presence })),
);
const Safety = lazy(() =>
  import("../tabs/Safety").then((m) => ({ default: m.Safety })),
);
const Security = lazy(() =>
  import("../tabs/Security").then((m) => ({ default: m.Security })),
);

// Lucide sprite still mounts statically from the .html fragment.
import lucideSprite from "./_lucide-sprite.html?raw";

interface Props {
  active: TabId;
}

// The sprite needs to be rendered ONCE in the document — separate component
// avoids re-injection on every tab switch.
export function LucideSprite() {
  return <div dangerouslySetInnerHTML={{ __html: lucideSprite }} />;
}

function renderTab(active: TabId) {
  switch (active) {
    case "diagnostics":
      return <Diagnostics />;
    case "energy":
      return <Energy />;
    case "home":
      return <Home />;
    case "house":
      return <House />;
    case "hvac":
      return <HVAC />;
    case "zones":
      return <Zones />;
    case "rooms":
      return <Rooms />;
    case "presence":
      return <Presence />;
    case "safety":
      return <Safety />;
    case "security":
      return <Security />;
  }
}

// Suspense fallback: matches the page-header skeleton so tab-switch doesn't
// look broken while the lazy chunk loads. The fallback IS visible on the
// VERY first paint of a never-visited tab; cached tabs (HA frontend caches
// chunk URLs) load synchronously and skip the fallback.
function TabSuspenseFallback() {
  return (
    <section className="tab active">
      <header className="page-header">
        <div>
          <h1 className="page-title">Loading…</h1>
          <div className="page-subtitle dim">…</div>
        </div>
      </header>
    </section>
  );
}

export function TabShell({ active }: Props) {
  return (
    <Suspense fallback={<TabSuspenseFallback />}>{renderTab(active)}</Suspense>
  );
}
