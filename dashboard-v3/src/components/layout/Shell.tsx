/**
 * App shell — P6 light Navet-styled.
 * Two-pane layout: left rail (>768px) or top mobile-tabs (≤768px), main content.
 * Body classes applied: body.navet body.light, plus data-active-tab attribute
 * for per-tab mood gradients (see p6-shared.css body[data-active-tab="..."]).
 */
import { useEffect, type ReactNode } from "react";
import { Rail, type TabId } from "./Rail";
import { MobileTabs } from "./MobileTabs";

interface Props {
  active: TabId;
  onChange: (id: TabId) => void;
  children: ReactNode;
}

// Threshold below which P6's mobile collapse (rail → top-strip + denser knobs)
// kicks in. Matches docs/dashboard-prototypes/v4/shared.css @media (max-width: 768px).
const MOBILE_MAX = 768;

export function Shell({ active, onChange, children }: Props) {
  // Lock P6 finish: body.navet body.light, plus data-active-tab for mood gradients.
  useEffect(() => {
    const body = document.body;
    body.classList.add("navet", "light");
    body.dataset.activeTab = active;
  }, [active]);

  // Auto-toggle body.mobile based on viewport width so P6's mobile CSS rules
  // (rail collapse, knob span overrides, etc.) apply correctly without manual
  // viewport-toggle interaction.
  useEffect(() => {
    const sync = () => {
      document.body.classList.toggle("mobile", window.innerWidth <= MOBILE_MAX);
    };
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);

  return (
    <div className="app">
      <Rail active={active} onChange={onChange} />
      <main className="main">
        <MobileTabs active={active} onChange={onChange} />
        {children}
      </main>
    </div>
  );
}
