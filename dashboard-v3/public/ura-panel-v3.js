/**
 * URA Dashboard panel bootstrap web component.
 *
 * Registered via panel_custom in __init__.py. Receives `hass` from HA's
 * panel system and creates an iframe loading the React SPA from the
 * statically-served frontend-v3/index.html.
 *
 * v5.0 (2026-05-19): Removed the postMessage token bridge. @hakit/core
 * v6.x auto-inherits auth + WebSocket from window.top.hassConnection
 * inside same-origin iframes; no manual auth passthrough required.
 * Kept the hass property setter for HA's panel lifecycle, but it's a no-op
 * now — included as a defensive landing pad so HA doesn't error when
 * setting the property.
 *
 * Known caveat — issue #304 (open, panel_custom + iframe):
 *   HA destroys + recreates the iframe on tab return after backgrounding.
 *   hakit's suspend/resume can't recover cleanly because the React tree
 *   re-mounts but the WS may be in mid-reconnect. Mitigation reserved
 *   for v5.0.1: cache the iframe DOM node across disconnectedCallback /
 *   connectedCallback so the SPA isn't torn down. Tracking in
 *   docs/planning/DASHBOARD_BACKLOG.md.
 */
class URADashboardPanelV3 extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._iframe = null;
  }

  set hass(hass) {
    // No-op: hakit handles auth via window.top.hassConnection inheritance.
    // Stored only in case future panel features need it.
    this._hass = hass;
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    if (this._iframe) return; // guard against double-mount

    const style = document.createElement("style");
    style.textContent =
      ":host { display: block; height: 100%; }" +
      " iframe { border: 0; width: 100%; height: 100%; }";
    this.appendChild(style);

    this._iframe = document.createElement("iframe");
    this._iframe.src = "/universal_room_automation_panel_v3/index.html";
    this.appendChild(this._iframe);
  }
}

customElements.define("ura-dashboard-panel-v3", URADashboardPanelV3);
