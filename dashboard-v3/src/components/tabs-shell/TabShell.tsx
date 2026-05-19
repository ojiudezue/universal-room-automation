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
import diagnostics from "./diagnostics.html?raw";

const TAB_HTML: Record<TabId, string> = {
  home, house, zones, rooms, energy, hvac, presence, security, safety, diagnostics,
};

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
  return <div dangerouslySetInnerHTML={{ __html: withActiveClass(TAB_HTML[active]) }} />;
}
