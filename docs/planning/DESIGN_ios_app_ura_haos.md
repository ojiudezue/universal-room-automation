# iOS App for HAOS + URA — High-Level Design

**Date:** 2026-07-11 · **Status:** Design doc, no build implied · **Audience:** solo operator; sequel to `COMMERCIALIZATION_options.md` Play #1 (Paid companion app).

## Institutional context verified

- **`docs/planning/COMMERCIALIZATION_options.md` (2026-07-02, read in full)** — this doc is the direct downstream of Play #1 ("URA for iOS"). Key constraints inherited: (a) integration stays free/MIT on HACS, (b) app sells *convenience* (Nabu Casa pattern), not the integration, (c) **prerequisite gate: HACS distribution + ≥100 active installs before paid app work begins** — this design is therefore a *blueprint*, not a build authorization, (d) sequence: PWA Pro tier first, then native iOS, (e) remote-access piggybacks Nabu Casa; no relay to build.
- **`docs/dashboard-prototypes/v4/README.md` + P6 fulcrum (2026-05-17)** — nine HTML prototypes exist. **P6 light Navet-styled is the picked fulcrum** and its 1607 LoC of `p6-shared.css` is canonical. The iOS app inherits its visual language (light theme, mood gradients per tab, top-bar knob row, no per-domain hue washes, 3-word glanceability). Tab set locked: Home / House / Zones / Rooms / Energy / HVAC / Presence / Security / Safety / Diagnostics.
- **`docs/planning/DASHBOARD_v5_sensor_audit.md` (2026-05-19)** — 169 sensor classes inventoried; ~40 already-exist, ~10 attribute-adds, ~6 net-new, ~6 UI fiction. This is the app's data contract; the iOS app must not require sensors the audit hasn't accounted for.
- **`docs/planning/DASHBOARD_BACKLOG.md`** — v5.0 React PWA foundation branch `feature/dashboard-v5.0-foundation` already has the P6 shell (Rail, MobileTabs, Shell, 10 lazy-mount tabs, HassConnect dev bypass). The iOS work should NOT duplicate this — it consumes the same sensor contract.
- **HA WebSocket API** — verified via developers.home-assistant.io: 3-phase auth handshake (`auth_required` → `auth` → `auth_ok`), `subscribe_events` (raw bus, e.g. `state_changed`), `subscribe_trigger` (structured), `call_service`, `get_states`, ping/pong; optional `coalesce_messages` supported_feature for bulk delivery. Explicit delta streaming (`subscribe_entities` with compressed patches) is used by the frontend — not documented in the summary I pulled; treat as needs-verification-in-code before implementation.
- **HAKit** (github.com/home-assistant/HAKit, Apache-2.0) — official Swift library, WebSocket + REST, mTLS support, auto-reconnect on network change, Starscream dependency on older iOS. Actively maintained (© 2026). This is the correct primitive; no need to hand-roll a WS client.
- **HA native `mobile_app` integration** — server-side component that a native app registers against for: device registration, push notification routing (APNs via HA Cloud or self-hosted), remote sensor push from device, and encrypted payloads. Details need reading the integration source before building — the developer docs page I pulled was thin.

## 1. Transport architecture

**Recommendation: HA WebSocket (via HAKit) as the primary transport, plus HA `mobile_app` integration for push + device-side sensors. No MQTT.**

### Why WebSocket over MQTT

| Concern | WebSocket (HAKit) | MQTT |
|---|---|---|
| Auth for remote | Long-lived access tokens or OAuth via HA; Nabu Casa TLS URL works out of the box | No first-class remote-auth story; needs broker-side ACLs + separate TLS |
| API surface | Full HA: entity states, service calls, config, events, history | Only what HA publishes to MQTT (partial, requires MQTT discovery + statestream config) |
| URA fit | URA exposes ~600 HA entities + services — WS reads them natively; **no URA-side change required** | Would need URA to also publish to MQTT (redundant surface, new bug class) |
| Push (background) | Not push — WS drops when app suspends. Use `mobile_app` push for background | Broker push works, but iOS still suspends the socket; APNs is required anyway |
| Battery | Fine for foreground; disconnect on background and rely on APNs | Same reality once iOS suspension is honored |
| Deployment | Zero extra infra | Requires broker (Mosquitto add-on) + bridge config + ACL maintenance |

**Verdict:** MQTT solves no problem URA has and adds a broker to the customer-side install. The one thing MQTT would win — real background delivery — is not actually a WS-vs-MQTT question on iOS; both need APNs. HA already has the APNs path (`mobile_app` + HA Cloud), so we take it.

### Concrete transport layout

1. **Foreground / active session:** HAKit WebSocket → `subscribe_events` for `state_changed` scoped to the entity IDs the current tab needs (audit says ~40 already-exist sensors cover most surfaces). If `subscribe_entities` (compressed delta stream) is available on the server version, prefer it — verify in HA core before shipping.
2. **Background / lock-screen:** register the device via `mobile_app` on first launch; URA-side NM channels (BlueBubbles/WhatsApp today) get a **new "URA iOS push" channel** that fires an APNs notification via HA Cloud for CRITICAL anomalies + user-subscribed events. This is additive, not a replacement — respects the NM audit gaps (per-person mute, safe-word ack) tracked in MEMORY.
3. **History / analytics:** reuse HA's REST `/api/history/period` and `/api/logbook` first. URA's own SQLite DB is NOT exposed over HTTP today; **do not** build a URA-specific HTTP endpoint in v1 — it would fork the auth model. If the savings-report screen (Commercialization Play #2 preview) needs URA-DB queries the HA history API can't answer, add a *read-only* URA WebSocket API command handler (`ura/history/*`) under HA's existing auth — one surface, no new port.
4. **Config flows:** **explicit non-goal in v1.** HA config flows are server-rendered forms; the app deep-links to the HA frontend (`homeassistant://navigate/config/integrations/dashboard`) for onboarding, zone-manager setup, and destructive ops. This matches the commercialization framing ("app makes URA legible for day-to-day, not for setup").

### MQTT re-open criteria

Only revisit MQTT if a specific customer segment demands (a) sub-100ms local push with app foreground guaranteed, or (b) offline-LAN operation with no HA Cloud. Neither is on the roadmap.

## 2. URA-specific app concerns

- **Tier mirroring.** The tab set (House / Zones / Rooms / Coordinators) MUST mirror URA's model — this is the whole legibility pitch. P6 already committed to it; the iOS app inherits the same tab spine.
- **3-word glanceability.** URA's label style guide applies. Every card title and status pill is ≤3 words. This is non-negotiable for a mobile surface.
- **Observability surfaces are cards, not deep dives.** Existing sensors that became first-class in the last 6 releases each get a Home-tab card: `sensor.<room>_unavailable_entities` (v5.7.2 actuator visibility), optimizer reasoning (v5.0.x — with the write-flood scars documented), health sensors (Sensor-Health), coordinator health summary. No new backend work for v1 — the audit already priced these.
- **Config CANNOT move to iOS.** Confirmed above. Zone delete, room onboarding, integration adds, credential entry — all deep-link. The app owns: monitoring, day-to-day control (light toggle, setpoint ±1°, house mode), NM feed, savings report.
- **NM feed = app's killer surface.** URA already has 5 NM channels. Adding "URA iOS push" as a 6th channel means the app becomes the primary alert consumer without replacing anything. Per-person mute + safe-word ack (the 2026-05-30 NM audit gaps) matter here — do NOT ship the app without at least per-person mute or the abuse surface duplicates existing NM problems on a new channel.
- **Actuator failure visibility.** The v5.7.2 silent-actuator-failure surfacing (memory: 2026-07-02) gives the app a specific "device down" card that a raw HA app cannot render — this is a concrete differentiator to feature in App Store screenshots.

## 3. Auth / multi-user / remote

- **Auth:** HA long-lived access token for MVP (per-device, revocable from HA UI). Migrate to OAuth `authorize_code` flow before public launch — HA supports it and the security bar for a paid app is higher than a personal one.
- **Multi-user:** HA `person` maps 1:1 to app account. The app reads `person.*` entities to know who's home; per-user preferences (which rooms to pin, which NM categories to receive) live in the HA `.storage` under a URA-owned namespace OR in a URA config entry — decide during prototype; leaning toward URA config entry so preferences survive app reinstall.
- **Remote access:** Nabu Casa URL is the default and only supported path in v1. VPN + reverse proxy are documented as "advanced, unsupported" — the commercialization doc explicitly said "piggyback on HA's existing remote/Nabu Casa URL rather than building a relay," so no relay.
- **Commercial tie-in:** Nabu Casa costs the user ~$6.50/mo. Bundling assumption in Play #1 pricing ($3-6/mo app) must NOT assume Nabu Casa — sell to Nabu Casa customers first (they've already crossed the pay-for-convenience psychological line). Non-Nabu users get a "requires HA remote access" wall in-app with a link.

## 4. UI sketch

**Framework:** SwiftUI + HAKit. Not from-scratch — HAKit's reconnect + mTLS + Starscream handling is exactly what a hand-rolled client would spend 3 months getting wrong.

**Screens (mirror P6 tab set, minus what makes no sense on mobile):**

1. **House dashboard (Home tab).** Status hero: house mode, active anomalies, 5/5 coordinators healthy, decisions today, routine confidence. One card per system light.
2. **Rooms grid (Rooms + House tabs collapsed).** 19 rooms in the audit — grid of tiles, occupied/idle badge, current persons, lights count. Tap → room detail.
3. **Room detail.** Light toggle (all lights), setpoint ±1° (for HVAC rooms), presence provenance (motion/mmwave/occupancy split from v4.7.19), unavailable entities warning.
4. **Zones + HVAC.** Per-zone: setpoint ±1°, mode cycle, coast-mode badge, arrester toggle. HVAC system demand, pre-cool status.
5. **Energy strategy.** $ today, kWh solar, battery %, TOU period, active pre-cool, battery reserve slider (the one write-heavy control — confirm via double-tap).
6. **Alerts / NM feed.** Chronological. Per-alert: coordinator origin, severity, ack. Per-person / per-category mute toggles.
7. **System health / Diagnostics.** Per-coordinator health, anomaly floor, DB maintenance, observation-mode toggle, restart button behind confirm.

**Interactions:** every write action confirms except light toggle. Lock/unlock, arm, reserve-slider commit, restart — 5s hold-to-confirm. This mirrors the P6 "no long-press unless warranted" rule.

**What we DON'T build on mobile:** the Safety tab (P6 has it; Safety is Diagnostics-adjacent — collapse in v1), full Presence tab (collapse into per-room card), config surfaces (deep-link).

## 5. Prototype path

**Recommended: option (b) — extend the existing PWA foundation first, native iOS second.**

Rationale: The React PWA on `feature/dashboard-v5.0-foundation` already has the shell, the sensor contract is audited, and Play #1 in the commercialization doc explicitly said "Pro PWA tier first, weeks not months, no App Store gate, validate willingness-to-pay." Building a SwiftUI throwaway when a testable PWA is 80% shelled would burn the runway on the wrong bet.

### Milestones

- **M1 — PWA read-only "Pro tier" (~2-3 weeks).** Wire the House, Rooms, and Energy tabs to live entities (the ~40 already-exist sensors). No writes. Ship behind a feature flag to universalroom.org demo. Success = 10 non-operator users can navigate their own house.
- **M2 — PWA write actions + NM feed (~2 weeks).** Light toggles, setpoint ±1°, house mode, NM feed subscription. Confirm-on-write UX. Success = one non-operator user runs their house from PWA for 1 week without opening HA UI.
- **M3 — SwiftUI native shell + HAKit (~3-4 weeks).** New Xcode project. HAKit WebSocket wired to House + Rooms tabs (parity with M1 read-only). Register with HA `mobile_app` for device ID + APNs. Success = TestFlight build renders live house on 3 devices.
- **M4 — Native writes + push (~3 weeks).** Port M2 actions. Add "URA iOS push" NM channel (URA-side, ~1 planning cycle). Per-person mute on the app side. Success = TestFlight users report accurate CRITICAL alerts with acceptable dedup.

**Gate before M3:** the commercialization doc's ≥100-active-installs prerequisite. If HACS distribution hasn't materialized, stop after M2 — the PWA IS the product.

**Deferred (v2+):** Zone-manager onboarding in-app, savings-report cloud tie-in (Play #2), Apple Watch complications, Siri Shortcuts, HomeKit bridge.

## Open questions

1. Does the HA WebSocket API version deployed today support `subscribe_entities` with compressed deltas? Verify against HA core before M1 wire-up — it changes payload sizing math.
2. Preferences storage: URA config entry vs HA `.storage` namespace? Decide during M1.
3. `mobile_app` push without Nabu Casa — is self-hosted APNs viable, or is Nabu Casa a hard requirement for non-Nabu customers? Read the `mobile_app` integration source.
4. Does the P6 light theme survive iOS Dynamic Type + Dark Mode? Prototype a single card in SwiftUI at M3 kickoff before committing to full port.
