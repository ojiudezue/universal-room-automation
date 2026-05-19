/**
 * Tab shell — renders the active P6 tab's content via dangerouslySetInnerHTML.
 *
 * Strategy: each .html file in this directory is a verbatim extract from
 * docs/dashboard-prototypes/v4/p6-light-styled.html, preserving class names
 * and structure. The CSS already lives in p6-shared.css (imported globally),
 * so the HTML renders correctly without any JSX conversion.
 *
 * Lucide SVGs use <use href="#lc-X"/> — the sprite must be present in the
 * DOM once. _lucide-sprite.html provides it, injected at the top of the
 * main content area.
 *
 * When tabs go live in dashboard cycle D3-D7, this file is gradually
 * replaced by per-tab React components with real entity wiring. The .html
 * fragments stay as visual reference.
 */
import type { TabId } from "../layout/Rail";
import { Diagnostics } from "../tabs/Diagnostics";
import { Energy } from "../tabs/Energy";
import { Home } from "../tabs/Home";
import { HVAC } from "../tabs/HVAC";
import { Zones } from "../tabs/Zones";
import { Rooms } from "../tabs/Rooms";
import { Presence } from "../tabs/Presence";
import { Safety } from "../tabs/Safety";

// Vite supports ?raw imports natively — each .html file is loaded as a string.
import lucideSprite from "./_lucide-sprite.html?raw";
import homeHtml from "./home.html?raw";
import house from "./house.html?raw";
import zonesHtml from "./zones.html?raw";
import roomsHtml from "./rooms.html?raw";
import energyHtml from "./energy.html?raw";
import hvacHtml from "./hvac.html?raw";
import presenceHtml from "./presence.html?raw";
import security from "./security.html?raw";
import safetyHtml from "./safety.html?raw";
import diagnosticsHtml from "./diagnostics.html?raw";

// TAB_HTML carries the legacy static fragments for tabs not yet ported to React.
// Kept around for visual reference / parity diffing. The Record key set
// shrinks as tabs port to React — currently 2 left.
const TAB_HTML: Record<
  Exclude<
    TabId,
    | "diagnostics"
    | "energy"
    | "home"
    | "hvac"
    | "zones"
    | "rooms"
    | "presence"
    | "safety"
  >,
  string
> = {
  house,
  security,
};
// Retained for visual reference / parity diffing as we keep porting.
void diagnosticsHtml;
void energyHtml;
void homeHtml;
void hvacHtml;
void zonesHtml;
void roomsHtml;
void presenceHtml;
void safetyHtml;

interface Props {
  active: TabId;
}

// The sprite needs to be rendered ONCE in the document — separate component
// avoids re-injection on every tab switch.
export function LucideSprite() {
  return <div dangerouslySetInnerHTML={{ __html: lucideSprite }} />;
}

// Tab sections in the P6 source use `class="tab"` (hidden by CSS) and only
// the visible one has `class="tab active"`. Since React already isolates the
// active tab (we only render its HTML), force the active class on whatever
// section opens the rendered fragment.
function withActiveClass(html: string): string {
  return html.replace(/class="tab"/, 'class="tab active"');
}

export function TabShell({ active }: Props) {
  // Ported tabs render via React components; the rest fall through to the
  // legacy static-HTML path. This is the seam for porting more tabs later —
  // add a case here per tab as it's converted.
  if (active === "diagnostics") {
    return <Diagnostics />;
  }
  if (active === "energy") {
    return <Energy />;
  }
  if (active === "home") {
    return <Home />;
  }
  if (active === "hvac") {
    return <HVAC />;
  }
  if (active === "zones") {
    return <Zones />;
  }
  if (active === "rooms") {
    return <Rooms />;
  }
  if (active === "presence") {
    return <Presence />;
  }
  if (active === "safety") {
    return <Safety />;
  }
  return <div dangerouslySetInnerHTML={{ __html: withActiveClass(TAB_HTML[active]) }} />;
}
