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

// Vite supports ?raw imports natively — each .html file is loaded as a string.
import lucideSprite from "./_lucide-sprite.html?raw";
import home from "./home.html?raw";
import house from "./house.html?raw";
import zones from "./zones.html?raw";
import rooms from "./rooms.html?raw";
import energy from "./energy.html?raw";
import hvac from "./hvac.html?raw";
import presence from "./presence.html?raw";
import security from "./security.html?raw";
import safety from "./safety.html?raw";
import diagnosticsHtml from "./diagnostics.html?raw";

// TAB_HTML carries the legacy static fragments for tabs not yet ported to React.
// Kept around (incl. diagnosticsHtml) as the visual reference for future ports.
const TAB_HTML: Record<Exclude<TabId, "diagnostics">, string> = {
  home, house, zones, rooms, energy, hvac, presence, security, safety,
};
// Retained for visual reference / parity diffing during the next 9 tab ports.
void diagnosticsHtml;

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
  return <div dangerouslySetInnerHTML={{ __html: withActiveClass(TAB_HTML[active]) }} />;
}
