# URA Commercialization Options

**Date:** 2026-07-02 · **Status:** Decision doc, no build implied · **Constraint:** solo/small operator; HA community norms forbid paywalling the integration itself.

## Grounding: what URA actually has to sell

- **The integration is the moat, not the product.** 5 domain coordinators, ~57k LOC, 3,800+ tests, 18+ months production — but 600+ entities and 30+ config entries per install is *hostile* to non-experts. The complexity gap is the monetizable surface.
- **Quantifiable dollar value.** The Energy coordinator (TOU battery strategy, EVSE solar charging, load awareness) produces measurable monthly savings — the rare smart-home feature that can literally "pay for itself."
- **Existing seeds:** universalroom.org, a live demo dashboard, and a standalone React PWA dashboard repo (installable on iOS/Android).
- **Community-norm precedent is clear:** Frigate (free OSS core + Frigate+ paid model-tuning subscription, from $5) and Nabu Casa (free HA + paid cloud convenience) are both accepted. The norm violated is *gating the integration*; selling convenience, cloud services, or service labor around a free core is fine.

## Ranked plays (by achievability for a solo operator)

### 1. Paid companion app — "URA for iOS" (the operator's idea, refined)

**Model:** Integration stays free/MIT on HACS. Sell a polished app (subscription, ~$3–6/mo or one-time + IAP) that makes URA *configurable and legible*: guided room/zone onboarding, coordinator dashboards, savings reports, push alerts, remote tuning. Power users keep using raw HA entities free — the classic Nabu Casa "pay for convenience" split.

**Why it fits:** URA's biggest adoption blocker (600 entities, 30 config entries) becomes the pitch. The PWA dashboard already exists — ship a **"Pro" PWA tier first** (weeks, no App Store gate), validate willingness-to-pay, then wrap native iOS (and Apple-home-platform later). Remote access can piggyback on HA's existing remote/Nabu Casa URL rather than building a relay.

**Effort/risk:** Medium. Main risks: remote-auth UX, App Store review, and the app only sells if the free integration first gets real HACS distribution (today it has ~1 install). **Norm compatibility: high** (exact Nabu Casa pattern).

**First step:** Publish URA to HACS default + announce on HA community forum; instrument the existing PWA to learn which screens matter. No paid app until ≥100 active installs exist to sell to.

### 2. "URA Cloud" — energy-savings reports + tuned intelligence (Frigate+ analog)

**Model:** Optional subscription cloud service: monthly "your house saved $X" reports, utility tariff library (TOU rate plans maintained server-side), fleet-tuned Bayesian priors/forecast models, off-site config backup. Free integration works fully offline; cloud makes it smarter and provable.

**Why it fits:** URA already persists decisions/energy snapshots to its own SQLite DB — the raw material for reports exists. The energy coordinator is the one feature with a dollar-denominated ROI story, and Frigate+ proves the community accepts "paid tuning/data services on top of free local core."

**Effort/risk:** Medium-high — real backend infra, billing, privacy story, and ongoing tariff-data maintenance. Best sequenced *after* Play 1 establishes users and an app to surface the reports in. **Norm compatibility: high.**

**First step:** Prototype the savings report as a free local sensor/monthly notification from the existing DB. If users screenshot-share it, the cloud version has demand.

### 3. Concierge setup + curated hardware kit (Konnected-style, revenue now)

**Model:** Flat-fee remote "URA install" service ($300–800: sensor audit, room/zone config, tuning) and/or a curated bundle (mmWave + BLE + energy sensors known to work) with URA pre-configured. Sell labor and curation, not code.

**Why it fits:** URA's config depth means an expert hour is genuinely worth money; the operator *is* the expert. Zero code required; funds the app runway; every paid install is a case study and feature-gap discovery engine.

**Effort/risk:** Low effort, low risk, but **does not scale** (trades hours for dollars) and creates support tail. **Norm compatibility: high** (services around OSS are universally accepted — this is the Red Hat/Konnected pattern).

**First step:** Put a "Get URA installed" waitlist form on universalroom.org this week. Price discovery costs nothing.

## Recommendation

Sequence, don't choose: **(3) concierge waitlist now** (validates demand, funds runway) → **(1) HACS distribution + Pro PWA → iOS app** (the scalable core bet) → **(2) URA Cloud** once there's a user base worth a subscription. The single prerequisite for everything: URA must first become a *distributed* free integration with a real install base — commercialization of a one-house project is premature until then.
