import React, { useState, useEffect } from "react";
import ReactDOM from "react-dom/client";
import { HassConnect } from "@hakit/core";
import App from "./App";
import "./styles/globals.css";

function Root() {
  const [hassUrl, setHassUrl] = useState<string | null>(null);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      // Validate origin matches the parent window to prevent token injection
      if (event.origin !== window.location.origin) return;
      if (event.data?.type === "ura-auth" && event.data.hassUrl) {
        // Store the token so home-assistant-js-websocket can pick it up
        const tokenData = {
          hassUrl: event.data.hassUrl,
          access_token: event.data.access_token,
          token_type: event.data.token_type,
          expires: Date.now() + 1800000, // 30 min
          clientId: "",
          expires_in: 1800,
          refresh_token: "",
        };
        try {
          localStorage.setItem(
            "hassTokens",
            JSON.stringify(tokenData)
          );
        } catch {
          // localStorage may be blocked in iframe
        }
        setHassUrl(event.data.hassUrl);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  if (!hassUrl) {
    return (
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        color: "var(--md-on-surface-variant)",
        fontSize: "1.1rem",
      }}>
        Connecting to Home Assistant...
      </div>
    );
  }

  return (
    <HassConnect hassUrl={hassUrl}>
      <App />
    </HassConnect>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
