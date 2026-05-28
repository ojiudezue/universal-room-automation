# URA Website — Design + Build Brief

**For:** homelab project to design, build, and deploy
**Replaces:** https://universalroom.org/ (current rough attempt, v3.6-era content)
**Owner:** Oji Udezue (ojiudezue@github)
**Status:** Brief; pick up, design, ship. No back-and-forth needed.

---

## 1. The 30-second pitch

**Universal Room Automation (URA)** is a Home Assistant custom integration that turns a house into a self-managing system. Not a hub. Not a dashboard. **A coordinator layer that sits on top of Home Assistant and runs the house.**

Five domain coordinators (Presence, Safety, Security, Energy, HVAC) make decisions every 5 minutes using occupancy, weather, TOU electricity rates, battery state, solar forecast, and a 9-state house-state machine. Sub-second reactions where they matter (motion + intrusion); deliberate 5-min cycles where they don't (energy strategy, HVAC presets).

**Why it exists:** because most smart homes are 200 disconnected automations stapled together. URA is the missing operating system that coordinates them.

---

## 2. Audience

The site has to land for **three** distinct visitors, in order of priority:

| Audience | What they care about | What they need to leave with |
|---|---|---|
| **Home Assistant power user evaluating URA** | "Will this work with my hardware? Will it break my YAML automations?" | Clear hardware compatibility, install path (HACS), what URA replaces vs augments |
| **Smart-home-curious homeowner (no HA yet)** | "Can a system this complex actually be easier than what I have?" | Lifestyle benefit framing, screenshots, confidence-building proof points |
| **Developer / integrator** | "How does it work, what's the architecture, can I contribute?" | Repo link, architecture diagram, technical depth |

The hero serves audience 1 + 2; the deep-dive pages serve all three.

---

## 3. Core value propositions (lead the homepage with these 5)

**1. Person-aware, not motion-triggered.**
URA tracks who's in the house, who's in each room, and where each person is heading next. Lighting, music, climate, and security all respond to the *right person being in the right room at the right time*, not just "something moved." Multi-source presence (BLE, camera face-recognition, device tracker, geofence) — no single sensor failure can blind it.

**2. A house-state machine, not a calendar of automations.**
The whole house lives in one of 9 states: `home_day`, `home_evening`, `home_night`, `sleep`, `waking`, `arriving`, `away`, `guest`, `vacation`. Every coordinator (HVAC, lighting, music, security, notifications) reads that state and adjusts behavior automatically. Change one state, the whole house follows. Override it manually when you need to.

**3. Energy that actually saves money — with proof.**
URA's Energy Coordinator manages a 40 kWh Enphase battery + 19.4 kW solar array against TOU rates from a custom rate file. It decides reserve SOC, EV pause/resume, pool pump speed, smart plugs, and HVAC offsets every 5 minutes. Tracks cost in real time. Predicts your bill 7 days into the cycle. Verifiable arbitrage savings per cycle. (Live in one home for 18+ months.)

**4. HVAC that watches kWh, not just temperature.**
The HVAC Coordinator runs per-zone, applies seasonal presets keyed to house state, and detects AC overshoot from kWh-rate (not just temperature). If the AC kept burning power after reaching setpoint, URA nudges the setpoint up 1.5°F for 5 minutes. If that doesn't help, it does a controlled compressor reset. Daily cap so it never punishes the equipment.

**5. Local-first, observable, reversible.**
Everything runs locally inside Home Assistant. No URA cloud, no telemetry leaving the house. Every decision URA makes is logged with reason + timestamp. Every coordinator has an **Observation Mode** that lets you see what it *would* do without letting it actually do it. Every actuation has a kill switch. Disable URA tomorrow; HA goes back to vanilla — nothing on your hardware is permanently changed.

---

## 4. Site information architecture

```
/                              ← Homepage (hero + value props + CTAs)
/coordinators/                 ← Coordinator overview hub
├── /coordinators/presence/    ← Deep-dive: house state machine, multi-source presence
├── /coordinators/safety/      ← Deep-dive: 12 hazard types, NM cascade
├── /coordinators/security/    ← Deep-dive: arming logic, lock + cam aggregation
├── /coordinators/energy/      ← Deep-dive: battery strategy, TOU, arbitrage, grid cap (use ENERGY_MANAGEMENT_EXPLAINER.md content)
└── /coordinators/hvac/        ← Deep-dive: per-zone, AC ramp-down, energy constraint (use HVAC_MANAGEMENT_EXPLAINER.md content)
/architecture                  ← System architecture page (diagram + sub-system breakdown)
/install                       ← Installation walkthrough (HACS recommended path)
/dashboard                     ← PWA Dashboard showcase (link to https://ura.phalanxmadrone.com)
/docs                          ← Link out to GitHub docs/ folder (don't duplicate; just link)
/changelog                     ← Auto-generated from GitHub releases
/privacy                       ← Local-first + open-source statement
```

**Hard rule:** don't duplicate content from the GitHub docs/ folder. Always link to the canonical doc. Brief excerpt + "Read the full Energy Coordinator manual →" pattern.

---

## 5. Homepage content blocks (top to bottom)

### Block 1: Hero
- **Headline:** "Your house runs itself."
- **Subhead:** "Universal Room Automation is the coordinator layer that turns Home Assistant into a self-managing home. Five domain coordinators. One house-state machine. Local, observable, reversible."
- **Primary CTA:** "Install via HACS →" (links to install page)
- **Secondary CTA:** "See it run live" (links to PWA dashboard at https://ura.phalanxmadrone.com)
- **Visual:** subtle live system screenshot OR animated SVG showing the 5 coordinators ticking + house-state pill row

### Block 2: The "before vs after" frame (keep from current site)
Three columns, scannable:
- **Before URA:** "200 individual automations. Motion-triggered. Reacts to events one device at a time. No memory between rooms."
- **With URA:** "One state machine. Person-aware. Five coordinators making decisions every 5 minutes. Music follows you between rooms. The AC stops overshooting. The battery saves money."
- **Without disruption:** "Vanilla Home Assistant underneath. Existing automations keep working. Toggle URA off — house reverts. Observation Mode lets you watch before you commit."

### Block 3: The five coordinators (5 cards)
Each card: icon, name, 1-sentence summary, "Read the deep-dive →".

| Coordinator | One-line |
|---|---|
| **Presence** | Knows who's home, where they are, where they're going. 9-state house machine. |
| **Safety** | 12 hazard types from smoke to freeze to leak. Cascades alerts; never spams. |
| **Security** | Aggregates locks + cameras + entry sensors. Auto-arms on geofence. |
| **Energy** | 40 kWh battery + 19.4 kW solar managed against live TOU rates. Predicts your bill. |
| **HVAC** | Per-zone presets keyed to house state. Detects AC waste from kWh, not just temperature. |

### Block 4: "How it actually works" (technical credibility, 3 short subsections)

#### Decision cycles
"Every 5 minutes, each coordinator reads its inputs (occupancy, weather, prices, battery, solar forecast), runs its strategy, and emits service calls. Most actions are idempotent (re-applying the same preset is a no-op). When something needs faster response — intrusion, smoke alarm, motion entering an empty room — coordinators use direct event subscriptions: typical reaction time 2-5 seconds."

#### House state machine
"`home_day`, `home_evening`, `home_night`, `sleep`, `waking`, `arriving`, `away`, `guest`, `vacation`. State transitions are inferred from presence + clock + manual overrides. Every coordinator reads the current state and adjusts: HVAC picks a preset; Security decides what to arm; Music decides whether to auto-pause; Notifications decide whether to send to phones or media speakers."

#### Local-first
"All decisions, all data, all coordination — local to your Home Assistant. No URA cloud. No vendor lock-in. URA stores its own state in a SQLite database alongside HA's. Disable the integration and HA returns to default behavior — no leftover orphan automations, no broken devices."

### Block 5: Proof / production credentials
- Live install: **18+ months in one production home** (the developer's). Link to PWA dashboard.
- Test suite: **3,800+ automated tests** (`pytest quality/tests/`)
- Releases: **v4.6.15 current production**; ~50 releases since v4.5.0 cycle started
- Quality discipline: every release goes through Tier 1 / Tier 2 / Tier 2-DB review based on scope. (Brief one-liner here; link to QUALITY_CONTEXT.md.)
- Documentation: 4 user manuals + 2 technical explainers (link to /docs)

### Block 6: Live dashboard preview
- Screenshot of the URA PWA Dashboard (https://ura.phalanxmadrone.com) — Home tab, Energy tab, HVAC tab
- Caption: "The URA PWA Dashboard is a separate front-end that consumes URA's sensors over the Home Assistant WebSocket API. Standalone PWA (no panel_custom). Installable on iOS + Android. Source available."
- CTA: "View the dashboard live →"

### Block 7: Dual CTAs
- **For Home Assistant users:** "Install URA via HACS — 5 minutes" → /install
- **For developers:** "Read the source on GitHub" → repo

### Block 8: Privacy footer
Short, prominent:
"URA runs locally. No URA cloud. No telemetry. No accounts. Your house data stays in your house. Source code under MIT license."

---

## 6. Coordinator deep-dive pages (template)

Each of the 5 coordinator pages follows the SAME 6-section template (consistency = scannability across pages):

1. **What it does** (1 paragraph)
2. **How it makes decisions** (input → strategy → output, with a diagram if useful)
3. **Key concepts** (3-6 named patterns with definitions — e.g., for Energy: "TOU period classification", "Solar day class", "Arbitrage charge window", "Grid import cap", "Load shedding cascade")
4. **Configuration knobs** (the runtime sliders the user can tune — pull from the user manuals)
5. **Sensors + diagnostics** (what URA exposes for monitoring)
6. **Read the full manual →** (link to the canonical doc in GitHub)

**Source content:** the new docs I just shipped have everything you need:
- `docs/ENERGY_MANAGEMENT_EXPLAINER.md` — pull §1, §3, §5, §6, §10 verbatim for the Energy deep-dive
- `docs/HVAC_MANAGEMENT_EXPLAINER.md` — pull §1, §3, §4, §5, §9, §13 verbatim for the HVAC deep-dive
- `docs/user-manual/ENERGY_COORDINATOR.md` — runtime knob descriptions
- `docs/user-manual/HVAC_COORDINATOR.md` — runtime knob descriptions
- For Presence / Safety / Security: link to `docs/Coordinator/PRESENCE_COORDINATOR.md`, `SAFETY_COORDINATOR.md`, `SECURITY_COORDINATOR.md`. These are older design docs; mark the deep-dive pages as "Living docs — current as of v4.6.15" and don't over-extract.

---

## 7. Visual direction

**Tone:** confident, technical-but-warm, no smart-home cliché.

**What to avoid:**
- Stock photos of smiling families adjusting a thermostat
- "Tap your phone to control your home" hero-shot tropes
- Hub/Alexa/Google comparison tables
- Magic-words like "AI-powered" without substance

**What to embrace:**
- Real system screenshots (the PWA dashboard, HA device pages, the URA coordinator status sensors)
- Simple diagrams showing data flow (presence → house state → 5 coordinators)
- Code or YAML excerpts where they prove a point (e.g., "no YAML required for the typical install")
- Dark mode as primary (most HA users have dark UI muscle memory); light mode supported

**Color palette suggestion:** start from the URA PWA Dashboard's P6 palette (the live dashboard already exists; use the same vocabulary). Lift dark/light tokens from `~/Code/ura-dashboard-pwa/src/design/p6-shared.css` for consistency.

**Typography:** system fonts (`-apple-system`, Inter, etc.). Monospace for code/entity IDs (Menlo / JetBrains Mono).

**Animation:** restrained. The hero can have one subtle animated diagram. Inside pages: no parallax, no scroll-jacking. Smart-home buyers see enough of that elsewhere.

---

## 8. Tech recommendations

**Stack (suggestion, not mandatory):**
- **Framework:** Astro (static-first, perfect for content sites with occasional interactive bits). Or 11ty if Astro feels heavy.
- **Styling:** Tailwind + CSS variables for the design tokens
- **Hosting:** same homelab webhost the URA Dashboard uses (LXC 110 @ 192.168.13.137, served via PM2 + Caddy + Cloudflare Tunnel). Domain: `universalroom.org` (already owned).
- **Content source:** markdown files in the site repo, OR pull deep-dive content directly from the URA GitHub repo's `docs/` folder via build-time fetch (Astro can do this cleanly with Content Collections).
- **Analytics:** Plausible or self-hosted Umami if any. Stay privacy-consistent with URA's brand.
- **Search:** Pagefind (static, no server needed) for searching across the deep-dives.

**Don't suggest:**
- WordPress, Wix, Squarespace — wrong audience signal
- Next.js with full SSR — overkill for a content site
- Anything that requires running a JavaScript server

**Reuse from the URA Dashboard PWA repo (`~/Code/ura-dashboard-pwa/`):**
- Design tokens (`src/design/p6-shared.css`)
- Icon set (Lucide via SVG sprite)
- Component patterns (`Toast`, `OptionSelector`, `ToggleSwitch`) if interactive bits are needed (probably not for a content site)

---

## 9. SEO + meta

**Primary keyword target:** "Home Assistant automation coordinator" (long tail; HA users specifically).
**Secondary:** "smart home energy management", "person-aware home automation", "open source HEMS Home Assistant".
**Don't compete for:** "smart home" generic (Alexa/Google own this; pointless).

Per-page meta:
- Title: `URA — <page topic>` (e.g., `URA — Energy Coordinator`)
- Meta description: 150-160 chars, lead with the concrete value
- Open Graph image: per-page screenshot or diagram

`robots.txt`: allow everything. Open-source project, want to be found.

`sitemap.xml`: auto-generated. Include changefreq=monthly for deep-dives.

Schema.org: `SoftwareApplication` schema on the homepage with name, applicationCategory=`HomeAutomation`, operatingSystem=`Home Assistant`, offers=`free`.

---

## 10. Content NOT to include (out of scope for v1)

- Blog / news section — the GitHub releases page IS the changelog
- Forum / discussion — point to GitHub Discussions
- Newsletter signup — no list, don't pretend
- Comparison tables vs HA / OpenHAB / Hubitat — URA layers on top of HA; not a competitor
- Testimonials — single-install project today; honest about that
- Pricing — it's free + MIT
- "Enterprise" tier — not a thing

---

## 11. What to migrate from the current universalroom.org

**Keep the bones:**
- Linear narrative (problem → solution → proof → action)
- Dual-audience CTA (homeowner / developer)
- Local-first + privacy emphasis
- Concrete examples ("John," "Jane" — use real-sounding occupancy patterns)

**Update the content:**
- Version references (v3.6 → v4.6.15)
- Feature list (the v3.6-era list is now ~10% of what URA does; rebuild around the 5 coordinators)
- Test count (590 → 3,800+)
- Roadmap (the Q3 2026 / Q1 2027 dates are now in the past or imminent — replace with current v4.7.x queue)

**Drop:**
- "Coming soon" framing for things that have shipped (multi-person tracking, music following, camera intelligence — all live)
- v3.5.0 / v3.4.0 references — those are historical now

---

## 12. README.md update (separate deliverable, lives in the repo)

The brief includes a parallel README rewrite (see `/README.md` after this PR — committed alongside this brief). The README serves a different audience than the website: developers who land on the repo via GitHub search or a Home Assistant forum link. It needs to:
- State the current version honestly
- Describe what's actually in the box (the 5 coordinators)
- Point to the user manuals + explainers
- Show installation in 5 lines (HACS)
- Acknowledge it's a single-install production project (not pretend it's a community)

The README is shorter than the website; the website is the marketing surface, the README is the developer's entry point.

---

## 13. Acceptance criteria for the homelab project to mark this "done"

1. **Site live at https://universalroom.org/** replacing the current content.
2. **Homepage hero loads in <1s** on a mid-range mobile (Lighthouse Performance ≥ 90).
3. **All 5 coordinator deep-dive pages exist** (Presence, Safety, Security, Energy, HVAC).
4. **Live PWA Dashboard linked** from the homepage and Energy/HVAC deep-dives.
5. **README.md and the site agree** on version, coordinator count, install path, test count.
6. **Pagefind search works** across all deep-dives.
7. **Dark mode is default**, light mode supported, system preference respected.
8. **Privacy + local-first statement** prominent on homepage AND linked from footer.
9. **No tracking** other than self-hosted Plausible/Umami (optional). No Google Analytics. No Facebook pixels. No third-party script-loaders.
10. **Deploys via the homelab's existing CI** (whatever pattern is in use for other domains — match the URA Dashboard PWA's deploy.sh pattern if possible).

---

## 14. Open questions for the design phase (homelab project to decide)

These are NOT blocking — the homelab can decide either way and proceed:

1. **Astro vs 11ty?** Either works; pick what the homelab team prefers.
2. **Hosted on Vercel/Cloudflare Pages vs the homelab LXC?** The LXC has worked well for the PWA. Same domain owner. Probably stay homelab.
3. **Should the deep-dive content be auto-pulled from `docs/` at build time, or hand-curated copies?** Auto-pull keeps it in sync; hand-curated lets you write site-specific framing. Either works.
4. **Single page vs multi-page?** This brief assumes multi-page (better for SEO + scannability + bookmarking). A single-page-with-anchors would also work.

---

## 15. Source assets (where to pull content from)

| Asset | Location | Use for |
|---|---|---|
| Energy explainer | `docs/ENERGY_MANAGEMENT_EXPLAINER.md` | Energy deep-dive page |
| HVAC explainer | `docs/HVAC_MANAGEMENT_EXPLAINER.md` | HVAC deep-dive page |
| Energy user manual | `docs/user-manual/ENERGY_COORDINATOR.md` | Energy deep-dive "configuration" section |
| HVAC user manual | `docs/user-manual/HVAC_COORDINATOR.md` | HVAC deep-dive "configuration" section |
| Presence design | `docs/Coordinator/PRESENCE_COORDINATOR.md` | Presence deep-dive (older; light edit needed) |
| Safety design | `docs/Coordinator/SAFETY_COORDINATOR.md` | Safety deep-dive |
| Security design | `docs/Coordinator/SECURITY_COORDINATOR.md` | Security deep-dive |
| Vision | `docs/VISION_v7.md` | Hero copy inspiration |
| Roadmap | `docs/ROADMAP_v11.md` | Roadmap section content |
| Quality discipline | `docs/QUALITY_CONTEXT.md` | "How URA ships" proof section |
| Dashboard screenshots | `~/Code/ura-dashboard-pwa/dist/` (build first), OR live at https://ura.phalanxmadrone.com | Hero + dashboard section |
| Design tokens (CSS) | `~/Code/ura-dashboard-pwa/src/design/p6-shared.css` | Color palette consistency |

---

## 16. Ship cadence + ownership

- **Homelab project picks this up, designs, builds, deploys.** No structural sign-off needed; copy + content sign-off only.
- **Iterate in public.** Push to a staging URL early (e.g., `staging.universalroom.org`); show drafts to Oji every Friday until accepted.
- **No timeline pressure.** Production URA runs fine without this site; deliver when it's good.
- **Lifecycle:** site lives. Treat it like any other repo — branch, PR, deploy. The site rev independently of URA's release cadence (no need to update the site for every URA patch).

---

End of brief.
