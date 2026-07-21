# URA Dashboard v5 — Round 5 build-out

Round 5 is the operator-approved artifact **URA · Dashboard V — People**
(claude.ai artifact `8868dc9d-d5d1-4377-bb1b-b65b832fc797`, approved
2026-07-17). That artifact established the design language and the People
(Home) tab. This build reproduces the approved tab faithfully and builds
out its sibling tabs in the same language.

## What was approved (the design system)

- **Dark, warm, mobile-first.** Background `#141312`, tiles `#1d1c1a`,
  accents ember `#ff7a59`, honey `#ffb547`, sage `#8fbf8f`, sky `#8fb8c9`,
  alert `#ff5c4d`. Note: this supersedes the earlier white-bg lineage —
  the approved Round 5 artifact is dark.
- **System font stack** (SF Pro Text), tabular numerals everywhere,
  uppercase letterspaced tier labels, tight negative letterspacing on
  big numbers.
- **Idioms:** greeting + attention headline, people chips (avatar +
  name + location), 4-column tile grid, wide 2-span "Now · Next" tiles,
  2-span zone cards with occupancy border, gradient attention banner,
  fixed bottom nav with badge.

## What this build adds

`v5-dashboard.html` — ONE self-contained file (no CDNs, no build), six
tabs, all rendered from a single `URA` data object at the top of the
script so wiring to live entities later is mechanical:

| Tab | Content |
|---|---|
| Home | Faithful reproduction of the approved People tab |
| Rooms | All 40 rooms, zone-grouped cards: occupancy, temp, light/fan/climate state |
| Energy | Battery SOC + strategy, TOU period, BAEC / EV Charging Plan, EVSE, solar, grid |
| Climate | HVAC zones, presets, per-zone targets, warm/cool room extremes |
| Safety | Hazards, doors and locks, camera presence policy, alerts |
| System | Coordinator health, fan-recheck counters, write-verify, versions, DB queue |

Desktop (≥900px): the bottom nav becomes a top bar and the content
column widens to a multi-column grid; mobile keeps the approved 480px
single-column layout.

Placeholder data is modeled on the real house (40 rooms, zones like
Master Suite and Entertainment, battery strategy `self_consumption`,
EV Charging Plan `hold_only`, v5.19.x). This is a design prototype —
nothing is wired.

## How to view

```
open docs/dashboard-prototypes/v5/v5-dashboard.html
```

---

*Generated 2026-07-20. Predecessor: `../v4/` (p2 Level Tabs was the v4 fulcrum).*
