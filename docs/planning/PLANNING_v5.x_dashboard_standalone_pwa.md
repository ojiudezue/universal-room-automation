# URA Dashboard v6.0 — Standalone PWA over HA WebSocket

**Version:** 1.0 (2026-05-21)
**Status:** Planning — awaiting build approval
**Supersedes (architecturally):** `PLANNING_v5.x_dashboard_v4_react_port.md` for ongoing iteration. v5.0 (panel_custom + hakit) stays shipped as a fallback; new iteration moves to the PWA.
**Recall hint:** "Standalone PWA dashboard" / "Resume dashboard PWA"

---

## TL;DR

Build a standalone Progressive Web App at **`ura.phalanxmadrone.com`** that talks directly to Home Assistant's WebSocket API. Drop `@hakit/core`, drop `panel_custom`, drop the iframe — gain real first-paint perf, custom state store with shallow-equality dedup, and iteration speed (push to webhost LXC, live in <5 s).

Reuses all existing v5.0 tab JSX and CSS verbatim. Replaces only the data layer (`useUraSensor` + `useCoordinatorSummary` → new `useEntity` backed by a Zustand store fed by a single shared WS connection with rAF-batched dispatch).

---

## Why now

User pain (2026-05-20): "Dashboard is slow. Like everything we have built with hakit."

Root causes the standalone PWA sheds:

| Issue | hakit / panel_custom cost | PWA fix |
|---|---|---|
| `useEntity` new object identity on every state_changed → every subscriber re-renders | Burst events cascade to 20+ re-renders per frame | Zustand store with shallow-equality dedup — only changed-entity subscribers re-render |
| No throttling (v6 removed it) | Sub-100ms event storms unbatched | rAF-batched dispatcher coalesces all events in one tick into one store update |
| HassConnect bootstraps via `window.top.hassConnection` (iframe parent) | 200-400ms startup overhead before our React runs | Direct WS connection, no iframe |
| `panel_custom` wraps us in HA's frontend shell + locale routing + service worker | Loads HA-frontend code we don't use | Standalone build, only what we ship |
| HACS deploy ceremony for every frontend tweak | ~30s + restart-not-needed-but-skill-does-it | `npm run deploy` → rsync to webhost in <5s |
| iOS Companion WKWebView caching + tap quirks | Patched in v4.6.13.4 but still finicky | Real Safari / Chrome on phone — no embed wrapper |

---

## Verified homelab infrastructure (read 2026-05-21)

| Component | Value | Source |
|---|---|---|
| Webhost LXC | CT 110 @ `192.168.13.137`, Ubuntu 24.04, Node 22.x, PM2, `okosisi` user | `homelab-automation/docs/webhost-lxc.md` |
| Webhost layout | `/var/www/<name>/`, PM2 process `<name>`, port 300x | same |
| Used ports | 3001 ziri · 3002 blackroots · 3003 africaaixprize · 3004 nduzi | `configs/webhost-pm2.md` |
| **Next free port for URA** | **3005** | derived |
| Caddy reverse proxy | CT 108 @ `192.168.13.103` w/ wildcard cert for `*.phalanxmadrone.com` | `homelab-automation/docs/webhost-lxc.md` |
| Cloudflare tunnel | id `5f2c189b-f10d-4cd9-bc6f-b67f14aa5d3e` ("madronehaos") | tunnel snapshot 2026-05-07 |
| HA public hostname | **`madronehaos.phalanxmadrone.com`** → `http://192.168.13.13:8123` via CF tunnel | tunnel snapshot 2026-05-07 |
| HA LAN hostname | `ha.phalanxmadrone.com` (split-horizon, Caddy → 13.13:8123) | `configs/snapshots/caddy/Caddyfile-*` |
| HA long-lived token (1y) | in `homelab-automation/.env` as `HA_TOKEN` | `.env` |
| Existing deploy script | `homelab-automation/scripts/webhost/deploy-static-site.sh` | repo |
| Deploy script flags | `--name --src --port --hostname --caddy --udm-dns --cf-tunnel --apply` | reading the script |

**Proposed dashboard subdomain:** `ura.phalanxmadrone.com`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Browser (phone / laptop)                                            │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ React 19 PWA (Vite, TypeScript, react-router for tab routing)   │ │
│ │  ┌──────────┐ ┌──────────┐ ┌──────────┐  ... 10 tabs            │ │
│ │  │ Home.tsx │ │ House.tsx│ │ ...      │                          │ │
│ │  │ useEntity│ │ useEntity│ │ useEntity│                          │ │
│ │  └────┬─────┘ └────┬─────┘ └────┬─────┘                          │ │
│ │       └──────────┬─┘─────────────┘                                │ │
│ │                  ▼                                                │ │
│ │       ┌─────────────────────┐                                     │ │
│ │       │ Zustand store       │  shallow-equality dedup             │ │
│ │       │ entities Map<id,…>  │  rAF batching                        │ │
│ │       └──────────┬──────────┘                                     │ │
│ │                  │                                                │ │
│ │       ┌──────────▼──────────┐                                     │ │
│ │       │ WS client (single)  │  reconnect, backoff, auth refresh   │ │
│ │       │ /api/websocket      │                                     │ │
│ │       └──────────┬──────────┘                                     │ │
│ └──────────────────│──────────────────────────────────────────────┘ │
└────────────────────│────────────────────────────────────────────────┘
                     │ wss://madronehaos.phalanxmadrone.com/api/websocket
                     ▼
        ┌────────────────────────┐
        │ Cloudflare Tunnel      │
        └───────────┬────────────┘
                    ▼
        ┌────────────────────────┐
        │ HA @ 192.168.13.13     │
        │ /api/websocket         │
        └────────────────────────┘
```

Static assets served via:
```
ura.phalanxmadrone.com → Cloudflare → CF Tunnel → Caddy CT 108 → Webhost CT 110:3005 (PM2 serve)
```

CORS / WebSocket: the PWA at `ura.phalanxmadrone.com` opens `wss://madronehaos.phalanxmadrone.com/api/websocket`. HA already allows WebSocket cross-origin when authenticated — this works today (verified by every HA Companion app).

---

## Repo + tooling decisions

| Decision | Value | Why |
|---|---|---|
| **Repo location** | **Separate repo** `~/Code/ura-dashboard-pwa/` → GitHub `ojiudezue/ura-dashboard-pwa` | Locked 2026-05-21 — keeps build/deploy cadence independent from URA Python; smaller blast radius for frontend-only experiments. Cross-repo coupling is just the entity-id schema documented in URA's `docs/TELEMETRY_LAYER.md`. |
| **Build tool** | Vite (same as dashboard-v3) | Familiar; React 19 support; static build → `dist/` |
| **State store** | Zustand 5.x | Tiny (~3 KB), `useSyncExternalStore` under the hood, supports custom equality |
| **Routing** | `react-router-dom` 6 with `HashRouter` | Hash-based avoids server-side rewrite rules on the static host. Tabs become `#/home`, `#/diagnostics`, etc. |
| **PWA tooling** | `vite-plugin-pwa` (Workbox-backed) | Generates manifest + service worker; supports `injectManifest` strategy for custom SW |
| **TypeScript** | strict | Inherits dashboard-v3 conventions |
| **Tests** | Vitest + Playwright | Vitest for the WS client + store; Playwright for end-to-end mobile + desktop |
| **Linting** | Same eslint config as dashboard-v3 | Consistent |

**Do NOT use:**
- `@hakit/core` (the thing we're escaping)
- `home-assistant-js-websocket` (1 MB+ dep with auth flow assumptions; we want a 100-LoC focused client)
- `redux-toolkit` / `react-query` for entity state (Zustand fits the pattern better)

---

## Auth strategy

Two-phase rollout. v6.0 ships with long-lived-token entry; v6.1 adds OAuth2.

### v6.0 — Long-lived token entry (ship day-1)
- First load: blank page with one input — "Paste your HA long-lived token"
- Token stored in `localStorage` under `ura.ll_token`
- WS auth sends `{"type":"auth","access_token":"<token>"}`
- "Sign out" button clears localStorage
- **Security note:** the token has full HA admin rights. PWA is at `ura.phalanxmadrone.com` (HTTPS-only via CF). localStorage is the standard pattern for SPAs; XSS risk is the standard SPA risk. We're not introducing new auth weakness.

### v6.1 — OAuth2 with refresh tokens (add 1-2 days later)
- HA supports OAuth2 with **URL-based client identification** — your app's URL IS the `client_id`. No registration step.
- Flow:
  1. PWA generates `state` (random) + `code_verifier` (PKCE optional but HA doesn't require it; we'll skip for simplicity).
  2. Redirect to `https://madronehaos.phalanxmadrone.com/auth/authorize?client_id=https://ura.phalanxmadrone.com&redirect_uri=https://ura.phalanxmadrone.com/auth/callback&state=<state>&response_type=code`.
  3. User logs into HA (or is already logged in) → HA shows "Authorize ura.phalanxmadrone.com to access your HA?" → user accepts.
  4. HA redirects to `https://ura.phalanxmadrone.com/auth/callback?code=<code>&state=<state>`.
  5. PWA POSTs to `https://madronehaos.phalanxmadrone.com/auth/token` with `grant_type=authorization_code&code=<code>&client_id=https://ura.phalanxmadrone.com` → response includes `access_token`, `refresh_token`, `expires_in`.
  6. Store both in localStorage; use `access_token` for WS auth.
  7. Refresh on expiry (1800s default): POST `/auth/token` with `grant_type=refresh_token&refresh_token=<rt>&client_id=https://ura.phalanxmadrone.com`.
- **Sign out** revokes refresh token via `POST /auth/token` with `token=<rt>&action=revoke`.
- Falls back to v6.0 token-entry screen if any of the above fails.

---

## WebSocket client design (`src/lib/ha-ws.ts`)

Single class, no abstractions. ~150 LoC.

```ts
type EntityState = {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
  last_changed: string;
  last_updated: string;
};

class HAWebSocket {
  private ws: WebSocket | null = null;
  private msgId = 1;
  private pending = new Map<number, (msg: any) => void>(); // id → resolver
  private onEvent: (ev: any) => void;
  private onStatus: (status: 'connecting' | 'connected' | 'auth_invalid' | 'disconnected') => void;
  private accessToken: string;
  private wsUrl: string;
  private reconnectAttempt = 0;

  constructor(opts: { wsUrl: string; accessToken: string; onEvent; onStatus });

  connect(): Promise<void>;            // open WS, auth, return when auth_ok
  callService(domain, service, target, data): Promise<any>;
  getStates(): Promise<EntityState[]>;
  subscribeStateChanges(): Promise<number>;  // returns subscription id
  unsubscribe(subscriptionId): Promise<void>;
  close(): void;

  // Private — reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s).
  // On auth_invalid: emit status, do NOT reconnect (user needs to re-auth).
  // On disconnect: reconnect, on success re-subscribe + re-fetch snapshot.
}
```

**Reconnect logic:**
- WebSocket close → exponential backoff (1s, 2s, 4s, 8s, 16s, capped at 30s).
- On reconnect-success: re-do auth, re-subscribe to state_changed, re-fetch full state snapshot, diff into store (so any state we missed during the disconnect populates correctly).
- Reset attempt counter on successful auth_ok.

**Why not `home-assistant-js-websocket`?** It bundles 1 MB+ including auth flow assumptions, internal connection management, and dependency on HA frontend types. We write 150 LoC and own every behavior.

---

## State store design (`src/lib/store.ts`)

Zustand store, singleton, fed by the WS client. ~120 LoC.

```ts
type Store = {
  entities: ReadonlyMap<string, EntityState>;  // immutable for shallow-eq dedup
  connectionStatus: 'init' | 'connecting' | 'connected' | 'auth_invalid' | 'disconnected';
  authError: string | null;

  // Internal — called by WS client
  _applySnapshot: (states: EntityState[]) => void;
  _applyEvent: (event: { data: { entity_id; new_state; old_state } }) => void;
  _setStatus: (s: Store['connectionStatus']) => void;
};
```

**rAF batching** (the perf win):
- WS client calls `_applyEvent` for every `state_changed` immediately.
- `_applyEvent` accumulates events into a private pending Map<entity_id, new_state>; if none scheduled, schedule a flush via `requestAnimationFrame`.
- Flush handler: clones the current entities Map, applies all pending events, calls `set({ entities: newMap })` ONCE.
- React subscribers re-render at most once per frame regardless of how many events landed.

**Custom equality for `useEntity`:**
```ts
export function useEntity(entityId: string): EntityState | null {
  return useStore(
    (s) => s.entities.get(entityId) ?? null,
    // Custom equality: compare state + attributes-hash, NOT object identity.
    // This is the dedup magic — even if Zustand handed us a new wrapper
    // object, if the underlying state + attrs didn't change, no re-render.
    (a, b) => a === b || (
      a != null && b != null
        && a.state === b.state
        && a.last_updated === b.last_updated
    ),
  );
}
```

---

## Hooks API

Drop-in replacements for the existing `dashboard-v3/src/data/*.ts` hooks. Same names, same return shapes — the 10 tabs port mechanically.

```ts
// src/data/useUraSensor.ts  (replaces dashboard-v3/src/data/useUraSensor.ts)

import { useEntity } from '../lib/store';

export function useUraSensorState(entityId: string): UraSensorReadout {
  const entity = useEntity(entityId);
  if (entity == null) return { state: null, loading: true, unavailable: false, attributes: null, last_updated: null };
  const unavailable = entity.state === 'unavailable' || entity.state === 'unknown';
  return { state: entity.state, loading: false, unavailable, attributes: entity.attributes, last_updated: entity.last_updated };
}

export function useUraSensorInt(entityId: string) { /* same shape, parses to int */ }
export function useUraSensorFloat(entityId: string) { /* same shape, parses to float */ }
export function useUraSensorAttrs<T>(entityId: string) { /* same shape */ }
```

`statusColors.ts` + `useCoordinatorSummary.ts` are copied verbatim — they only depend on `useUraSensor` which we re-implemented.

**Service calls** (new, for control surfaces):
```ts
import { useCallService } from '../lib/store';
const callService = useCallService();
await callService('switch', 'turn_off', { entity_id: 'switch.study_a_override_occupied' });
```

This is the seam where the dashboard's read-only controls bar finally becomes writable (the deferred item from v5.0).

---

## PWA shape

### `public/manifest.webmanifest`
```json
{
  "name": "URA Dashboard",
  "short_name": "URA",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#f5f7fb",
  "theme_color": "#1976d2",
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icons/icon-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

### `vite.config.ts` (PWA plugin)
- `registerType: 'autoUpdate'` — service worker checks for updates every page load, applies silently.
- `workbox.runtimeCaching`: 
  - Static assets (`/assets/*`): `CacheFirst` (hashed filenames, safe to cache forever)
  - `/icons/*`: `CacheFirst`
  - Everything else (HTML, manifest): `NetworkFirst` with 3s timeout falling back to cache (so a slow network doesn't break offline-shell)

### Install UX
- iOS Safari: user manually "Add to Home Screen" (Apple won't let us prompt). We add a small banner on first visit explaining the steps.
- Android Chrome: auto-prompts via `beforeinstallprompt` event; we capture it and trigger from a "Install" button.

---

## Deliverables

12 deliverables. v6.0 ships D1-D9. D10-D12 follow as v6.1.

### D1: Vite + React + TypeScript scaffolding
- New repo `~/Code/ura-dashboard-pwa/` (separate from `universal-room-automation/`).
- `git init` + initial commit; create GitHub repo `ojiudezue/ura-dashboard-pwa`.
- `package.json` (react 19, react-dom 19, react-router-dom 6, zustand 5, vite 6, vite-plugin-pwa 0.21, typescript 5.7, vitest, @playwright/test).
- `vite.config.ts` with PWA plugin, base `/`, build outDir `dist/`.
- `tsconfig.json` strict.
- Empty `App.tsx` + `main.tsx`.
- `.env.example` documenting `VITE_HA_WS_URL=wss://madronehaos.phalanxmadrone.com/api/websocket` and `VITE_HA_HTTP_URL=https://madronehaos.phalanxmadrone.com` (the WS + REST endpoints; not the token — that's user-entered).
- `npm run dev` runs locally; `npm run build` produces `dist/`.

**Acceptance:**
- `npm run dev` → blank page on `http://localhost:5173` with no console errors.
- `npm run build` → `dist/` with `index.html`, `assets/`, `manifest.webmanifest`, `sw.js`.

---

### D2: WebSocket client (`src/lib/ha-ws.ts`)
- Class `HAWebSocket` per spec above.
- `connect()`, `callService()`, `getStates()`, `subscribeStateChanges()`, `close()`.
- Reconnect with backoff.
- Vitest tests against a mock WS server (`mock-socket` package).

**Acceptance:**
- Vitest: 6+ tests cover connect happy-path, auth-invalid, disconnect-reconnect, message-id pairing, service call round-trip.
- Manual against live HA: open browser console at `https://ura.phalanxmadrone.com`, instantiate the client with the long-lived token, observe `auth_ok` + state snapshot received.

---

### D3: Zustand store + rAF batching (`src/lib/store.ts`)
- Store schema per spec.
- `_applySnapshot` populates entities Map.
- `_applyEvent` accumulates + schedules rAF flush.
- `useEntity(id)` hook with custom equality.
- `useCallService()` hook returns a stable function bound to the WS client.
- Vitest tests for: snapshot apply, event batching (10 events in one tick → 1 store update), custom equality (entity unchanged → hook returns referentially-equal value).

**Acceptance:**
- Test: dispatch 50 state_changed events for entity X in one tick → store updates once, `useEntity(X)` re-renders once.
- Test: entity Y's state unchanged across two snapshot applies → `useEntity(Y)` returns same reference.

---

### D4: Auth screen + long-lived-token storage
- Route `#/auth` shows a text input ("Paste your HA long-lived token").
- "Test connection" button instantiates the WS client + tries `auth_ok`.
- On success: persist token to `localStorage` (key: `ura.ll_token`), redirect to `#/home`.
- On `auth_invalid`: show error, leave the token field for retry.
- App root checks for stored token on mount; if missing, redirect to `#/auth`.
- "Sign out" link in any tab clears localStorage + redirects to `#/auth`.
- **v6.0 token source:** paste the homelab token from `homelab-automation/.env` `HA_TOKEN`. This token is shared with Ansible scripts; **D10 (v6.1)** will mint a dedicated `ura-dashboard-pwa` token via HA profile UI and swap so PWA revocability is independent of homelab automation.

**Acceptance:**
- Fresh load with empty localStorage → lands on `#/auth`.
- Paste valid token → redirects to `#/home` → entities load.
- Paste invalid token → error shown, no redirect.
- Sign out → back to `#/auth`, localStorage cleared.

---

### D5: Hooks layer (`src/data/`) — port from dashboard-v3
- Copy `dashboard-v3/src/data/statusColors.ts` verbatim.
- Copy `dashboard-v3/src/data/useCoordinatorSummary.ts` verbatim.
- New `dashboard-v3/src/data/useUraSensor.ts` reimplemented atop our Zustand store; same exports (`useUraSensorState`, `useUraSensorInt`, `useUraSensorFloat`, `useUraSensorAttrs`).
- `formatRelativeTime` + `formatClockTime` ported verbatim (pure date math).

**Acceptance:**
- TypeScript compile clean.
- Vitest: each hook returns expected shape against a populated store.

---

### D6: Migrate 10 tab components from dashboard-v3
- Copy `dashboard-v3/src/components/tabs/*.tsx` to `dashboard-pwa/src/components/tabs/`.
- Copy `dashboard-v3/src/components/layout/*.tsx` (Rail, MobileTabs, Shell).
- Copy `dashboard-v3/src/components/tabs-shell/TabShell.tsx` (the lazy-loaded switch).
- Copy `dashboard-v3/src/design/p6-shared.css` + `GlobalStyles.tsx`.
- Adjust imports from `dashboard-v3/src/data/*` → relative paths (mechanical).
- Wire `Shell` into `App.tsx` with `react-router` for hash-based tab routes.

**Acceptance:**
- All 10 tabs render at `http://localhost:5173/#/<tab>` with mock or live data.
- TypeScript clean.
- vite build green.

---

### D7: PWA manifest + service worker + icons
- Generate icons at 192, 512, maskable 512 (use the URA "U" mark).
- `public/manifest.webmanifest` per spec.
- `vite.config.ts` PWA plugin configured with autoUpdate + runtime caching rules.
- iOS install banner component (only shown on iOS Safari first visit, dismissable).

**Acceptance:**
- Chrome DevTools → Application → Manifest shows valid manifest with all icons.
- Lighthouse PWA audit ≥ 90.
- iOS install: "Add to Home Screen" produces a standalone app icon that launches at `#/home`.
- Android Chrome: install prompt fires.

---

### D8: Deploy script + first deploy
- `dashboard-pwa/scripts/deploy.sh` wraps the homelab deploy script:
  ```bash
  ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
  HOMELAB=~/Code/homelab-automation
  $HOMELAB/scripts/webhost/deploy-static-site.sh \
    --name ura-dashboard \
    --src $ROOT_DIR/dist \
    --port 3005 \
    --hostname ura.phalanxmadrone.com \
    --caddy --cf-tunnel \
    --apply
  ```
- Cloudflare tunnel ingress + DNS CNAME added (the homelab deploy script's `--cf-tunnel` documents the manual steps — we'll wire them via Cloudflare API directly in this script since the upstream automation is "not yet implemented" per its TODO).
- `npm run deploy` calls `scripts/deploy.sh`.

**Acceptance:**
- `npm run build && npm run deploy` succeeds; site reachable at `https://ura.phalanxmadrone.com`.
- Caddy snapshot + Cloudflare tunnel snapshot saved per the upstream pattern.
- PM2 status on webhost shows `ura-dashboard` running on port 3005.

---

### D9: Playwright validation script (live)
- `dashboard-pwa/scripts/playwright-live.mjs` similar to dashboard-v3's:
  - Navigates to `https://ura.phalanxmadrone.com`
  - Pastes long-lived token, waits for `auth_ok`
  - Cycles all 10 tabs, captures per-tab screenshots + perf metrics + console errors
  - Asserts no overflow at mobile viewport
- Adapted from `dashboard-v3/playwright-live.mjs` (no iframe wrangling needed — we're top-level).

**Acceptance:**
- All 10 tabs render with non-trivial content (>50 chars each).
- FCP < 200ms (target; baseline v5.0 was 232ms).
- Total transfer < 500 KB (target; v5.0 was 716 KB).
- Console errors: 0 URA-related.
- Mobile viewport (iPhone 13): no horizontal overflow.

---

### D10: OAuth2 flow + dedicated PWA token (v6.1)
- `/auth/callback` route handles `?code=&state=` redirect from HA.
- Token exchange + refresh-token persistence.
- Auth screen has "Sign in with Home Assistant" button (initiates OAuth) AND a "Use long-lived token" fallback (keeps D4 behavior).
- Refresh logic: 5 min before expiry, POST `/auth/token` with `grant_type=refresh_token`; on refresh-failure → fall through to re-auth.
- **PWA-dedicated long-lived token mint** (separate from OAuth path): document the procedure to create a `ura-dashboard-pwa` LL token via HA profile → Long-lived access tokens → "Create token", name it `ura-dashboard-pwa`, paste into the PWA auth screen. Replaces the shared homelab token. Revoke independently if the PWA is ever compromised. Add this as a **D4 follow-up step** in the deploy README so anyone re-deploying from scratch knows to use a dedicated token.

**Acceptance:**
- Fresh load → click "Sign in with HA" → redirected to HA login → accept → redirected back → entities load.
- Token expiry within 30 min after sign-in → automatic refresh, no user-visible reauth.

---

### D11: Service-call integration (controls go live)
- Sweep the 10 tabs for `disabled readOnly` patterns from v5.0's "controls bar read-only" deferral.
- Wire each control to `useCallService()` with the appropriate domain/service/target.
- Optimistic update: on click, immediately update the store's local copy; if HA replies with error, revert + show toast.
- Examples:
  - Override-vacant/occupied switches on Rooms tab → `switch.turn_on` / `switch.turn_off`
  - Anomaly-floor slider → `number.set_value`
  - Observation-mode toggle → `switch.turn_on` / `switch.turn_off`
  - Resume-now button on Appliance Coordinator (when D10 from appliance plan ships)

**Acceptance:**
- Force-vacant from the dashboard works on a real room (we tested this manually yesterday by calling the WS service directly; now the UI does it).
- Toggle observation mode → all coordinators reflect the change within one polling cycle.
- Network failure → toast appears, state reverts within 5 s.

---

### D12: Telemetry + perf budget hardening
- Add a perf marker on each tab mount + first useEntity resolve.
- Log to console + a `dashboard-pwa/perf.json` archive (rolling 100 measurements).
- Set up a CI step (or pre-commit hook) that runs Playwright + fails if FCP > 250ms or total-transfer > 600 KB on a clean build.
- Add 1-line URA WS event-rate counter for debugging (events/sec coming from HA).

**Acceptance:**
- Lighthouse PWA + Performance audits ≥ 90 on a clean build.
- Playwright run prints perf delta vs prior baseline; fails on regression.

---

## Implementation order + dependency graph

```
D1 (scaffolding)          ── independently
D2 (WS client)            ── needs D1; testable with mock WS
D3 (Zustand store)        ── needs D2 conceptually; can develop in parallel with D2
D4 (auth screen)          ── needs D2 + D3
D5 (hooks layer)          ── needs D3; mechanical port
D6 (10 tabs)              ── needs D5; mechanical migration
D7 (PWA manifest + SW)    ── parallel with D6; needs D1
D8 (deploy script)        ── needs D6 + D7
D9 (Playwright live val.) ── needs D8 (real deployed URL)
─── v6.0 ships ───
D10 (OAuth2)              ── parallel after D9; can ship as v6.1
D11 (service-call wiring) ── parallel with D10; per-tab incremental
D12 (perf hardening)      ── after D11 stable
```

**Ship plan:**
- **v6.0**: D1-D9 — long-lived-token auth, read-only dashboard, public at `ura.phalanxmadrone.com`
- **v6.1**: D10 (OAuth2)
- **v6.2**: D11 (service-call wiring, controls go live) + D12 (perf hardening)

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| HA WS auth model changes between versions | LOW | Pin to HA 2025+ behavior; the WS API contract has been stable since 2020 |
| Cloudflare WAF blocks WebSocket upgrade headers | LOW | CF supports WS natively; the HA Companion app already uses this path |
| Cross-origin WebSocket from `ura.phalanxmadrone.com` to `madronehaos.phalanxmadrone.com` fails | LOW | Same-parent-domain WS works without CORS issues; verified by other HA clients |
| Service worker caches stale shell during HA reauth flow | MEDIUM | `autoUpdate` strategy + `clients.claim()` in SW + version-stamped CSS/JS chunk URLs |
| Long-lived token in localStorage is XSS-exposed | KNOWN | Standard SPA pattern; HTTPS-only via CF; no third-party scripts loaded; OAuth2 v6.1 supersedes |
| Token refresh during OAuth (v6.1) racing with active WS | MEDIUM | Refresh in a critical section; on refresh-success, send `{type:"auth"}` over the existing WS to swap tokens (HA supports re-auth mid-session) |
| Reconnect storm if HA restarts (network hiccup) | LOW | Exponential backoff capped at 30s; reconnect only schedules ONE attempt at a time |
| iOS PWA install reluctance | MEDIUM | Banner explaining "Add to Home Screen"; works regardless of install (browser tab is fine) |
| Custom domain SSL cert via wildcard `*.phalanxmadrone.com` already exists | LOW | Verified via Caddy snapshots — same pattern as ziri / blackroots / etc. |
| Webhost LXC reboot loses PM2 dump | LOW | `pm2 save` after deploy (already in `deploy-static-site.sh`) |
| Single shared WS connection becomes a SPOF | LOW | Reconnect handles transient; for sustained outage the user sees the connection-status banner and can hard-refresh |
| Zustand store's Map cloning becomes a perf hotspot at 18,000 entities | LOW | Only updated entities flush through the dispatcher; the Map clone is O(events_per_frame), not O(total_entities) |
| Existing dashboard-v3 controls-bar markup uses `<input>` not React-controlled — wiring D11 requires refactor | MEDIUM | D11 acknowledges this; budget assumes 2-3 days for full sweep |

---

## Testing strategy

### Unit (Vitest)
- WS client: connect/disconnect/auth/service-call/event-handling, 12+ tests against `mock-socket`
- Zustand store: snapshot apply, event batching, dedup, custom equality
- Hooks: shape contract per existing dashboard-v3 tests (most of which port cleanly)

### Integration (Vitest + jsdom)
- Render a tab component with a populated mock store; assert it renders expected entity values
- Service-call optimistic update: call `useCallService`, assert store flips optimistically, then assert revert on simulated error

### End-to-end (Playwright)
- Live: `playwright-live.mjs` runs against `https://ura.phalanxmadrone.com` (D9)
- Local dev: `playwright-dev.mjs` runs against `npm run dev` with a mock HA WS server
- Visual diff vs P6 prototype: keep `dashboard-v3/playwright-shot.mjs` pattern alive

### Perf
- Lighthouse audit in CI (D12)
- Playwright captures FCP/DCL/transfer for each tab; perf-regression fails CI if FCP > 250ms

---

## Migration of existing 10 tabs (the "mechanical" claim)

For each tab `dashboard-v3/src/components/tabs/<Tab>.tsx`:

1. Copy file to `dashboard-pwa/src/components/tabs/<Tab>.tsx`
2. Update import paths from `../../data/useUraSensor` → same (relative paths preserve)
3. Update import paths from `../../data/statusColors` → same
4. Update import paths from `../../data/useCoordinatorSummary` → same
5. Diff: zero React tree changes, zero JSX changes, zero CSS changes
6. Quick smoke test: render against populated mock store, assert content matches v5.0 expected

Expected migration time: **15-30 minutes per tab × 10 = 5 hours**. Not the bottleneck.

The bottleneck is D2 + D3 (WS client + store). After those are right, the rest is rote.

---

## Hosting + DNS + tunnel setup

Step-by-step for D8:

1. **Build** locally:
   ```bash
   cd dashboard-pwa
   npm install
   npm run build  # → dist/
   ```

2. **Deploy via existing homelab script** (it does rsync + PM2 + Caddy + Cloudflare):
   ```bash
   ~/Code/homelab-automation/scripts/webhost/deploy-static-site.sh \
     --name ura-dashboard \
     --src ./dist \
     --port 3005 \
     --hostname ura.phalanxmadrone.com \
     --caddy --cf-tunnel \
     --apply
   ```

3. **Cloudflare tunnel ingress** — the upstream script docs the manual steps (it says "automation not yet implemented"); we'll automate in our wrapper:
   ```bash
   # Add to tunnel config via Cloudflare API
   curl -sH "Authorization: Bearer $CLOUDFLARE_API_TOKEN_WEBHOST" \
     "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/cfd_tunnel/$MADRONEHAOS_TUNNEL_ID/configurations" \
     -X PUT \
     -d @new-ingress.json
   
   # DNS CNAME (proxied)
   curl -sH "Authorization: Bearer $CLOUDFLARE_API_TOKEN_WEBHOST" \
     "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/dns_records" \
     -X POST \
     -d '{"type":"CNAME","name":"ura","content":"5f2c189b-f10d-4cd9-bc6f-b67f14aa5d3e.cfargotunnel.com","proxied":true}'
   ```
   Adding the CF-tunnel automation upstream-mergeable to `homelab-automation` would be a nice spin-off PR.

4. **Wildcard cert** already covers `*.phalanxmadrone.com` via Caddy CT 108. No new cert work.

5. **Verify**:
   ```bash
   curl -I https://ura.phalanxmadrone.com  # expect 200
   curl -I https://ura.phalanxmadrone.com/manifest.webmanifest  # expect 200
   ```

---

## Effort estimate

| Phase | Work | Time |
|---|---|---|
| D1 | Scaffolding | 0.5 d |
| D2 | WS client + tests | 1.5 d |
| D3 | Zustand store + tests | 1 d |
| D4 | Auth screen (LL token) | 0.5 d |
| D5 | Hooks layer | 0.5 d |
| D6 | 10 tabs migrated | 1 d |
| D7 | PWA manifest + SW + icons | 0.5 d |
| D8 | Deploy script + first live deploy | 1 d |
| D9 | Playwright live validation | 0.5 d |
| **v6.0 ship** | | **~7 days** |
| D10 | OAuth2 | 2 d |
| D11 | Service-call wiring across all tabs | 2-3 d |
| D12 | Perf hardening + CI | 0.5 d |
| **v6.1 + v6.2 ship** | | **+4-5 days** |
| **Total to controls-live** | | **~11-12 days** |

Realistic with normal interrupts: **2 weeks elapsed for v6.0**, **3 weeks for v6.2**.

---

## What's NOT in v6 (scope guards)

- **Replace v5.0 immediately.** v5.0 stays shipped in URA repo as fallback; old sidebar entry stays in HA. Until v6.0 is stable, the user has both options. Delete the `panel_custom` block in `__init__.py` only after v6.2 (controls live).
- **Push notifications.** PWA push is iOS-16.4+; defer to a later cycle if value clears.
- **Offline mode.** Service worker caches the shell, but live entity data requires WS. No offline state — explicit non-goal.
- **Camera streams.** Still deferred (same constraint as v5.0 — MJPEG in PWA iframe is messy; HA's camera dashboard handles it).
- **Custom domain on a public IP.** We're going through Cloudflare Tunnel (matches every other site in the homelab); no port forwards, no firewall changes.
- **Native iOS / Android apps.** PWA is the deliverable. If push notifications or deeper OS integration becomes needed, that's a future spike.

---

## Locked decisions (2026-05-21)

1. ✅ **Subdomain:** `ura.phalanxmadrone.com`
2. ✅ **Port:** `3005` on webhost LXC 110
3. ✅ **v6.0 token:** Reuse the existing homelab `.env` `HA_TOKEN` (1-year LL token, already minted). **v6.1 TODO:** mint a dedicated `ura-dashboard-pwa` LL token via the HA profile UI, swap the PWA over to it, leave the homelab token for the homelab-automation scripts. This isolates revocability — if the PWA is ever compromised, revoke its token without breaking Ansible runs.
4. ✅ **Repo decision:** Separate repo `ura-dashboard-pwa` (sibling project, NOT inside `universal-room-automation/`). Lives at `~/Code/ura-dashboard-pwa/`. Git pushed to a new GitHub repo.
5. ✅ **Mobile install banner:** Include (iOS-only, dismissable, ~50 LoC). See "Mobile install banner" section below.

Still open (resolve at D9 / D10):

- **WebKit Playwright + local-IP unreachability** — v5.0 hit this; v6 will test against the public CF tunnel URL which WebKit DOES reach. Verify tunnel-accessibility before D9.
- **OAuth2 redirect URI** — HA's "URL-based client identification" wants `client_id` to exactly match an HTTPS URL. Our `client_id` will be `https://ura.phalanxmadrone.com`. Confirm HA accepts this exact host string at D10 (it should — this is the URL-as-client-id mechanism HA documents).

---

## Mobile install banner (clarified)

Small dismissable strip shown ONLY to iOS Safari users who haven't already installed the PWA. Necessary because Apple refuses to fire `beforeinstallprompt` — without the banner, an iOS visitor has no idea this is an installable app.

Implementation (~50 LoC component):

```tsx
// src/components/InstallBanner.tsx
import { useEffect, useState } from "react";

const STORAGE_KEY = "ura.install_banner_dismissed_at";

function isIOS(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent);
}

function isStandalone(): boolean {
  // iOS sets navigator.standalone when launched from home screen;
  // also check display-mode media query for cross-browser truth.
  return (
    (navigator as any).standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches
  );
}

export function InstallBanner() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!isIOS()) return;
    if (isStandalone()) return;
    if (localStorage.getItem(STORAGE_KEY)) return;
    setShow(true);
  }, []);

  if (!show) return null;

  return (
    <div className="install-banner" role="dialog">
      <div>
        📲 <strong>Install URA</strong> — Tap{" "}
        <span className="ios-share-glyph">⎘</span> below, then{" "}
        <strong>Add to Home Screen</strong>
      </div>
      <button
        onClick={() => {
          localStorage.setItem(STORAGE_KEY, new Date().toISOString());
          setShow(false);
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
```

Style: sticky-bottom on mobile, dim background, accent border. Tap "Dismiss" → localStorage flag → never shown again on that device.

For Android Chrome, the existing `beforeinstallprompt` capture in `vite-plugin-pwa` handles auto-prompting. No banner needed on Android.

---

## Live-validation acceptance (post-D9 ship)

Open `https://ura.phalanxmadrone.com` on iPhone Safari. Expect:
1. Auth screen appears within 100ms of page load.
2. Paste token → tabs load within 500ms.
3. All 10 tabs render real entity values (not "—" except for genuinely-unavailable entities).
4. Tap any tab → switch within 100ms (no React.lazy delay since chunks are smaller).
5. Mobile viewport: zero horizontal overflow (we kept the v4.6.13.3 CSS fix).
6. iOS "Add to Home Screen" → launches standalone, no Safari chrome.
7. Console errors: zero URA-related.
8. Playwright (D9) reports FCP < 200ms, total transfer < 500 KB.

If 1-8 all hold: v6.0 is good. v6.1 (OAuth2) and v6.2 (controls) follow.

---

## Memory hooks (for future recall)

- "Resume URA dashboard PWA" → this doc
- "URA PWA deploy" → D8 hosting+DNS+tunnel section
- "URA PWA auth" → v6.0 LL token + v6.1 OAuth2 sections
- "URA PWA perf budget" → D9 + D12 sections (FCP < 200ms, transfer < 500 KB)
- "URA PWA token rotation" → D10 dedicated-token mint section

---

## References

- Existing dashboard: `dashboard-v3/` (the React port that will donate JSX + CSS to the PWA)
- Existing telemetry layer doc: `docs/TELEMETRY_LAYER.md` (the URA sensor surfaces the PWA reads)
- Homelab infra: `~/Code/homelab-automation/docs/webhost-lxc.md`
- Homelab deploy: `~/Code/homelab-automation/scripts/webhost/deploy-static-site.sh`
- Homelab env: `~/Code/homelab-automation/.env` (sourced by deploy script)
- Cloudflare tunnel snapshots: `~/Code/homelab-automation/configs/snapshots/cloudflare/madronehaos-tunnel-*.json`
- HA WebSocket API: `https://developers.home-assistant.io/docs/api/websocket`
- HA OAuth2 flow: `https://developers.home-assistant.io/docs/auth_api`
