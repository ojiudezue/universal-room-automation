/**
 * URA Dashboard panel wrapper.
 * Receives `hass` object from HA's panel system, creates an iframe,
 * and passes the auth token via postMessage so the React app can connect.
 */
class URADashboardPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._iframe = null;
    this._iframeReady = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._iframe && this._iframeReady) {
      this._sendAuth();
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    const style = document.createElement("style");
    style.textContent = `:host { display: block; height: 100%; } iframe { border: 0; width: 100%; height: 100%; }`;
    this.appendChild(style);

    this._iframe = document.createElement("iframe");
    // Serve the React SPA from the registered static path
    this._iframe.src = "/universal_room_automation_panel/index.html";
    this._iframe.addEventListener("load", () => {
      this._iframeReady = true;
      this._sendAuth();
    });
    this.appendChild(this._iframe);
  }

  _sendAuth() {
    if (!this._hass || !this._iframe || !this._iframeReady) return;
    this._iframe.contentWindow.postMessage(
      {
        type: "ura-auth",
        hassUrl: this._hass.auth.data.hassUrl,
        access_token: this._hass.auth.accessToken,
        token_type: "Bearer",
      },
      window.location.origin
    );
  }
}

customElements.define("ura-dashboard-panel", URADashboardPanel);
