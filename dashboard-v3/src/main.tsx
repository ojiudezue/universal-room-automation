/**
 * URA v3 Dashboard entry point.
 * Handles HA authentication via postMessage from the panel iframe,
 * then mounts the app inside HassConnect from @hakit/core.
 */
import React, { useState, useEffect } from "react";
import ReactDOM from "react-dom/client";
import { HassConnect } from "@hakit/core";
import App from "./App";
import { GlobalStyles } from "./design/GlobalStyles";
import { color, type as typography } from "./design/tokens";

function Root() {
  const [hassUrl, setHassUrl] = useState<string | null>(null);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      // Only accept messages from same origin
      if (event.origin !== window.location.origin) return;
      if (event.data?.type === "ura-auth" && event.data.hassUrl) {
        const tokenData = {
          hassUrl: event.data.hassUrl,
          access_token: event.data.access_token,
          token_type: event.data.token_type,
          expires: Date.now() + 1800000,
          clientId: "",
          expires_in: 1800,
          refresh_token: "",
        };
        try {
          localStorage.setItem("hassTokens", JSON.stringify(tokenData));
        } catch {
          // localStorage may be blocked in iframe context
        }
        setHassUrl(event.data.hassUrl);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  if (!hassUrl) {
    return (
      <>
        <GlobalStyles />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            height: "100dvh",
            color: color.text.secondary,
            fontSize: typography.size.md,
            fontFamily: typography.family,
            background: "#060612",
          }}
        >
          <div style={{ textAlign: "center" }}>
            <div
              className="animate-spin"
              style={{
                width: 24,
                height: 24,
                border: `2px solid ${color.glass.border}`,
                borderTop: `2px solid ${color.accent.primary}`,
                borderRadius: "50%",
                margin: "0 auto 12px",
              }}
            />
            Connecting to Home Assistant...
          </div>
        </div>
      </>
    );
  }

  return (
    <HassConnect hassUrl={hassUrl}>
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
