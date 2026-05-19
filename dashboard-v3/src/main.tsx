/**
 * URA Dashboard v5.0 entry point.
 *
 * Auth strategy (per @hakit/core v6.0.2 research 2026-05-19):
 *   hakit's HassConnect auto-inherits HA's auth + WebSocket connection from
 *   window.top.hassConnection when running inside a same-origin iframe.
 *   No postMessage token bridge needed; the localStorage["hassTokens"] shape
 *   URA v3 was writing didn't match hakit's AuthData shape anyway and would
 *   have been rejected.
 *
 *   `windowContext: window.top` makes hakit's breakpoints/resize use the
 *   parent HA frontend's window so media queries fire correctly while we
 *   render inside the iframe.
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { HassConnect } from "@hakit/core";
import App from "./App";
import { GlobalStyles } from "./design/GlobalStyles";
import "./design/p6-shared.css";

function Root() {
  // v5.0: dev-mode bypass for Vite dev iteration (Playwright + visual diff).
  // import.meta.env.DEV is true during `npm run dev` but false in production
  // build. ?dev query param forces it on a deployed instance for debugging.
  const isDev =
    import.meta.env.DEV ||
    new URLSearchParams(window.location.search).has("dev");

  if (isDev) {
    return (
      <>
        <GlobalStyles />
        <App />
      </>
    );
  }

  // Production: mount HassConnect. hakit reads window.top.hassConnection
  // for auth + WebSocket inheritance. hassUrl must be a valid origin string
  // (hakit sanitizes via new URL(hassUrl).origin internally).
  const hassUrl = window.location.origin;

  return (
    <HassConnect
      hassUrl={hassUrl}
      options={{
        // Use the parent HA frontend's window for breakpoints/resize so
        // media queries reflect the actual viewport, not the iframe's.
        windowContext: window.top ?? window,
      }}
    >
      <GlobalStyles />
      <App />
    </HassConnect>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
