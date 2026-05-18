# URA Dashboard v4 — Visual Prototypes

Three competing prototypes for the post-v3 URA dashboard. All share the same
design language (conservative dark glass, Navet-refined density, no hue
washes) and the same per-tab control surface — what varies is **how the
house → zone → room hierarchy is presented**.

## How to view

Open any `.html` file directly in a browser. No build, no server, no
dependencies. The page renders desktop layout by default; toggle to mobile
with the viewport pill in the top-right.

```
open docs/dashboard-prototypes/v4/p1-aggregated.html
```

## The three hypotheses

| File | Hypothesis | Status |
|---|---|---|
| `p1-aggregated.html` | **Aggregated Spaces** — one tab, zone strip, rooms expand in place | Reference |
| `p2-level-tabs.html` | **Level Tabs** — House / Zones / Rooms as sibling tabs | **Fulcrum — picked 2026-05-17** |
| `p3-hub-and-detail.html` | **Home Hub + Rooms Detail** — Home is the spatial canvas; Rooms is the dense grid | Reference |
| `p4-navet-styled.html` | **P2 + Safety tab + Navet styling pass** — leading-icon containers, top-edge highlights, pill actions, section accent bars, rail active indicator | Iteration on fulcrum (dark) |
| `p5-navet-with-bg.html` | **P4 + per-tab background images** — airy thematic photos with scrim | Iteration on fulcrum (dark + images) |
| `p6-light-styled.html` | **P4 in light theme** — off-white surfaces, dark slate text, pastel mood gradients | Iteration (light) |
| `p7-light-with-bg.html` | **P5 in light theme** — light surfaces + per-tab background photos with light scrim | Iteration (light + images) |
| `p8-material-styled.html` | **P4 in material theme** — medium-tone (less dark) surfaces with paper-grain dot texture overlay | Iteration (material) |
| `p9-material-with-bg.html` | **P5 in material theme** — medium-tone + paper texture + per-tab background photos | Iteration (material + images) |

## Shared assumptions (all three)

- **Devices:** desktop (≥1200px) primary, mobile (≤480px) secondary. No tablet hero.
- **Visual:** v3 dark glass kept. Status colors as accent only. No per-domain hue *washes*, but each tab gets a unique **background mood gradient** (radial-mesh, no images, no perf cost) to break up the flat dark blue.
- **Status/control balance:** per-tab **controls at the top** (knob row right under the page header). Per-card controls stay at the bottom of the card. No long-press unless warranted. Strong POV on what is necessary — no control spam.
- **URA power surfaces (in priority order):** coordinator function+health → routine awareness → key predictions → anomaly surfacing. Everything else → notifications/diagnostics.
- **Auto-onboard:** every prototype renders rooms from a data array. New URA room → appears in the right zone next render. No hand-laid HTML.
- **Alerts tab:** dropped; folded into Diagnostics as a top section.

## What you'll see (per-tab knob count)

| Tab | Knobs in controls bar | Per-card controls |
|---|---|---|
| Home | 5 (mode · anomaly floor · battery reserve · scenes · toggles) | inline on system cards |
| Spaces / Rooms | 3-4 (sort · scope · whole-house · auto-onboard) | per-room: light · setpoint ± · more |
| Energy | 5 (battery reserve · grid cap · EV max · battery mode · manual shed) | none — already in knob row |
| HVAC | 5 (system mode · house setpoint · pre-cool aggressiveness · coast threshold · URA modes triad) | per-zone: setpoint ± · mode pill |
| Presence | 5 (music master · BLE floor · transition smoothing · census mode · auto-guest) | per-person: override location · music per-room toggle |
| Security | 5 (arm mode · auto-arm on leave · auto-arm at sleep · lock-after-motion · camera privacy) | per-lock: unlock (with 5s confirm) |
| Diagnostics | 5 (anomaly floor · routine floor · DB maintenance · observation mode · telemetry) | per-coordinator: enable · restart |

## Per-tab control surface (committed — same across all 3)

| Tab | Controls (only these) |
|---|---|
| Home | House mode selector · "All lights off" |
| Spaces/Rooms | Per-room: light toggle (all lights) · climate setpoint ±1° · "more" → full room |
| Energy | Battery reserve override (slider) · "Shed loads now" |
| HVAC | Per-zone: setpoint ±1° · mode cycle · arrester toggle (global) |
| Presence | Person location override · music-following per room |
| Security | Arm (away/home/night) with confirm · lock/unlock with confirm |
| Diagnostics | Per-coordinator: enable · "reload integration" · anomaly ack |

## Mocked data

Each file bakes in realistic mocked URA values: 4 people, 5 zones, ~20 rooms
(subset of the 31-room production layout for prototype legibility),
plausible sensor values keyed to current evening hours. Values are static
HTML strings — no JS data layer. The React port will replace these with
live `useEntity` subscriptions.

## After review

You pick a winner. The v3.1 React build extends `dashboard-v3/src/design/tokens.ts`
+ adds new shared components — no new repo, no parallel app.

---

*Generated 2026-05-17. v3 source of truth: `dashboard-v3/`.*
