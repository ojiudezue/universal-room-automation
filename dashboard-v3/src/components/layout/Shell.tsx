/**
 * App shell: wraps the tab bar and tab content area.
 * Provides the background layer and overall layout structure.
 */
import { type ReactNode } from "react";
import { color, space, zIndex } from "../../design/tokens";

interface Props {
  tabBar: ReactNode;
  children: ReactNode;
}

const shellStyle: React.CSSProperties = {
  position: "relative",
  minHeight: "100dvh",
  background: `linear-gradient(180deg, ${color.surface.base} 0%, #060612 100%)`,
};

const contentStyle: React.CSSProperties = {
  position: "relative",
  zIndex: zIndex.base,
  padding: `${space.md}px ${space.md}px ${space["3xl"]}px`,
  maxWidth: 1400,
  margin: "0 auto",
};

export function Shell({ tabBar, children }: Props) {
  return (
    <div style={shellStyle}>
      {tabBar}
      <main style={contentStyle} role="tabpanel">
        {children}
      </main>
    </div>
  );
}
