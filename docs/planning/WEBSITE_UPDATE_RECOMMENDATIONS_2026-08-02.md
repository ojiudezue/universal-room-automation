# universalroom.org — Update Recommendations (2026-08-02)

Handoff brief for the website agent. Source of truth for claims and copy:
the repo README (`README.md`, rewritten 2026-08-02) and `docs/readmes/`.
Current shipped version: **v5.46.1**. The site currently describes
**v4.6.15** — an 18-month content gap.

## 1. Hero — lead with the composition thesis (highest priority)

The site currently leads with features. Replace the hero with the
device→room composition claim, which is URA's actual differentiator:

> **Smart homes run on smart devices. People live in rooms.**
> URA composes your smart devices into rooms — you interact with *the
> humidity in the bathroom*, not *the reading from sensor 0x4f2a* — then
> builds upward: rooms into zones, zones into one house under a
> nine-state machine, with domain coordinators (presence, safety,
> security, energy, HVAC) riding across all three tiers.

Supporting line (keep from current positioning): *Local, observable,
reversible. Built on Home Assistant — it doesn't replace what you have.*

**Hero visual:** one diagram — device icons (PIR, mmWave, BLE, camera,
plug) flowing into a single room node; room nodes grouping into zones;
zones ringing one house-state circle (`home_day … sleep … away …
vacation`). Source diagrams exist in the repo at `docs/diagrams/`
(Mermaid + PDF: system_architecture, house_state_machine,
coordinator_signal_flow) — reuse rather than redraw.

**Tone guard:** make the point, don't overwhelm with it. One hero + one
short section; the rest of the site stays feature/proof oriented.

## 2. Version currency (quick win, do even if nothing else ships)

- Every "v4.6.15" reference → **v5.46.1** (pull dynamically from GitHub
  releases if the stack allows: `ojiudezue/universal-room-automation`).
- Refresh the changelog/what's-new section from the README's "Recent
  highlights (v5.x)" section. Headliners since the site was written:
  - **Multi-modal presence fusion doctrines** — extend-not-create,
    divergence-aware confidence, mmWave fan-corroboration demotion ("a
    ceiling fan can't impersonate a person").
  - **CameraResolver (v5.45.0)** — one physical camera seen by Frigate,
    UniFi Protect, Reolink resolves to one node via a correlation ladder
    (device → MAC → identifiers → name-stem → operator declaration;
    ambiguity never guesses).
  - **Notification Manager** — per-person channels (iMessage/BlueBubbles,
    WhatsApp, Pushover), severity digests, DND-bypassing critical alerts.
  - **Exterior-person escalation** — perimeter camera detection routed by
    house state (away/sleep → critical with snapshot; home → quiet digest).
  - **Verifiable energy savings** — battery TOU arbitrage, peak-avoidance
    and AC-ramp savings measured per cycle, not estimated.

## 3. New section: "Field Notes" (recurring content channel)

Create a writing/articles section so the site stops being a static
brochure. First post is ready in the repo:

- `docs/articles/mmwave_fans_transition_gate.md` — "Your Ceiling Fan Is
  Impersonating You: Hunting mmWave Phantom Presence." Publish as the
  canonical URL; an HA-community-forum post and r/homeassistant crosspost
  will link here. Keep the markdown structure; the probe-numbers tables
  can be lifted from `docs/planning/AUDIT_fan_signature_separability_probe.md`
  if the post wants more data depth.

Future pipeline for the same section (do not write yet, just leave room):
the queued cross-modal fusion paper / OSS library announcement
(`docs/planning/PLANNING_paper_and_oss_fusion_library.md`).

## 4. Proof surfaces (elevate, don't add)

- **Live dashboard demo** (https://ura.phalanxmadrone.com) — link it
  prominently from the hero, not buried. It is the best evidence the
  system is real and running.
- **Production stats line:** 18+ months in production, 40+ rooms, 7,900+
  tests. (Test count from the repo badge; update it when the badge moves.)
- Link the three manuals for depth-seekers: `docs/Coordinator/HOUSE_MANUAL.md`,
  `ZONE_MANUAL.md`, `CM_MANUAL.md` in the repo.

## 5. Structure echo — three tiers, then coordinators

Mirror the README's corrected framing (this was recently fixed in the
README and the site should match): URA is **rooms · zones · house** with
coordinators *riding across* the tiers — NOT "a bundle of five
coordinators." Any site section that leads with the coordinator list
should be reframed so tiers come first and coordinators are the
cross-cutting layer.

## 6. Do-not list

- Do not present URA as a replacement for Home Assistant — it composes
  on top; vanilla HA keeps working; toggling URA off reverts the house.
- Do not credit AI tooling anywhere on the site (matches repo policy).
- Do not invent screenshots/numbers — every stat above is sourced from
  the repo; if the site needs a number not listed here, ask rather than
  extrapolate.
