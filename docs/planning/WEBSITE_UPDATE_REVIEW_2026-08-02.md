# Review of WEBSITE_UPDATE_RECOMMENDATIONS_2026-08-02

Reviewed 2026-08-02 against the live site (`~/Code/universal-room-website`, pure HTML+CSS, no build step) and this repo.

**Verdict: the brief is well-grounded and mostly correct — its structural instincts are right and its sourcing discipline is good. But it contains one factual error that must not reach the site, one framing error, and one recommendation that is impractical for this stack.**

---

## ❌ Must fix before anything ships

### 1. The test count is wrong — "7,900+ tests" vs. an actual badge of 3,800
The brief says *"Production stats line: 18+ months in production, 40+ rooms, 7,900+ tests. (Test count from the repo badge…)"*.

The README badge reads **`tests-3800`**. The claim overstates by ~2×.

This is the sharpest issue because the brief's own do-not list says *"Do not invent screenshots/numbers — every stat above is sourced from the repo."* Publishing 7,900 would put a false, checkable claim on a public marketing site for a project whose whole positioning is *verifiable*. **Use 3,800+, or drop the number.**

### 2. "40+ rooms" is unverified
Not present in the README. Either source it or cut it. (For a single residence, "40+ rooms" also invites scepticism — if it counts logical rooms/areas rather than physical ones, say so, or the number reads as inflated.)

### 3. "The site currently describes v4.6.15 — an 18-month content gap"
**The site is ~2 months old** (`index.html` last modified 2026-05-28; cut over from Gamma.app 2026-05-27). The *version string* is stale; the *content* is not 18 months old.

This looks like the "18+ months in production" stat leaking into a different claim. It matters because it mischaracterises the work: this is **a version-number refresh plus additive sections**, not a rewrite of stale content. Scoping it as the latter invites unnecessary churn on copy that is currently fine.

---

## ⚠️ Overstated

### 4. "The site currently leads with features" — it does not
The live hero reads:

> **Your house runs itself.**
> URA turns each room into software, aggregates them into zones, then runs the whole house as one system. Local, observable, reversible. Built on Home Assistant — it doesn't replace what you have.

That is **already the composition thesis** — room → zone → house, in one sentence, in plain language. The brief's premise that the hero is feature-led is inaccurate.

The proposed replacement is a good *hook* ("Smart homes run on smart devices. People live in rooms.") but the body that follows is longer and considerably more jargon-dense — *"nine-state machine"*, *"domain coordinators riding across all three tiers"*, *"sensor 0x4f2a"*. For a hero aimed at people deciding whether to keep reading, that is a step backwards in clarity. The brief seems to sense this itself, since it immediately adds a "tone guard."

**Recommendation:** keep the current hero structure (outcome → composition → guarantees). Optionally adopt the "People live in rooms" line as a *kicker above* the H1. Move the nine-state/coordinator detail into the section below, where the brief's structural point (§5) is genuinely right.

### 5. "Elevate, don't add" — but the stats line is an addition
There are currently **no** production stats on the page. That's fine, but call it what it is: new content requiring verification (see #1, #2), not elevation of something already there.

---

## 🔧 Impractical as specified

### 6. "Pull version dynamically from GitHub releases if the stack allows"
It doesn't. The site is **pure static HTML/CSS with no build step**, served by `npx serve` on webhost LXC 110. Doing this dynamically means client-side JS hitting the GitHub API on every page load: unauthenticated rate limits (60/hr/IP), a hard dependency on GitHub being reachable, and a version that renders blank when it isn't — on a page whose entire pitch is *local and reliable*.

**Better:** hardcode `v5.46.1`, and add a release-time step to the deploy script that rewrites the version string. If dynamic is genuinely wanted later, do it at build/deploy time, not in the browser.

---

## ✅ Correct — adopt as written

- **Version references are stale.** Confirmed: the site shows `v4.5.0` and `v4.6.15`; current is `v5.46.1`. Fix regardless of what else ships.
- **The live dashboard is not linked.** Verified absent from `index.html`. This is the single best piece of evidence the system is real, and it's missing. Highest-value quick win on the page.
- **There is no writing/articles section.** Verified absent. The blog is genuinely new surface, and the first post already exists (`docs/articles/mmwave_fans_transition_gate.md`, 128 lines).
- **§5's reframing is right.** The current H2 *"Five coordinators, riding above the rooms"* does lead with the coordinator list. Tiers-first with coordinators as the cross-cutting layer matches the corrected README framing.
- **Reuse existing diagrams** rather than redrawing — `docs/diagrams/` confirmed to contain `system_architecture`, `house_state_machine`, `coordinator_signal_flow` in both `.mmd` and `.pdf`.
- **The do-not list is sound** — no HA-replacement framing, no AI tooling credit, no invented numbers. (Ironically violated by its own test count.)

---

## Suggested scope, in order

1. **Version refresh** (v4.5.0 / v4.6.15 → v5.46.1) — 10 minutes, do it standalone.
2. **Link the live dashboard** prominently — 10 minutes, highest evidential value.
3. **Add the blog** — new `/notes/` section + first post. See implementation plan.
4. **Reframe the coordinator section** tiers-first (§5).
5. **Optional hero kicker** — do *not* replace the hero wholesale.
6. **Stats line last**, only with corrected numbers (3,800+ tests; 18+ months; rooms figure sourced or dropped).
