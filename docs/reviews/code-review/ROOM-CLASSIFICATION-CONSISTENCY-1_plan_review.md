# Plan review — ROOM-CLASSIFICATION-CONSISTENCY-1 (Option A), 2026-09-14

**Type:** Tier 2-DB adversarial PLAN review (before build). **Verdict: FIX-PLAN-FIRST** → re-scoped.

## Findings
- **CRITICAL-1** — TWO outdoor coercion sites; plan named only the display one (safety.py:428).
  The load-bearing one (safety.py:1319-1323) was built by NM Cycle A (A4/H1/B-HIGH-1) to SUPPRESS
  outdoor humidity hazards; "retire the coercion" would resume real NM pages. Bug Class #53.
- **HIGH-1** — ROOM_TYPE_OUTDOOR room-dropdown bullet = footgun (one click disables freeze+overheat
  alerting for a room). Dropped.
- **HIGH-2** — "no knobs, just an enum member" WRONG: room_type keys 5 tables (const.py:1171/1196/765/
  1207/1232); each needs a fall-through decision.
- **HIGH-3** — wiring basement activates 4 behaviours incl. un-knobbed LOW NM page at 65% RH
  (safety.py:2209). Not neutral.
- **MEDIUM-1** — D3 byte-identical unprovable without stating is_outdoor-before-garage/bathroom precedence.
- **MEDIUM-2** — "nothing typed basement" needs a live .storage check, not a grep assertion.
- **MEDIUM-3** — D4 fence was a tautology; must cover _handle_humidity + mutation drill on :1319.
- **MEDIUM-4** — 3 prior planning docs own the surfaces (zone_safety_alert_split, nm_overhaul_2026_07,
  onboarding_simplify) + 2 existing tests already pin basement behaviour — all uncited.

## Live-config check (settles value)
`.storage/core.config_entries`: 0 rooms typed `basement`, 0 zones flagged `outdoor` (46 entries).
→ D2/D3 have ZERO current consumer; both net-negative until a real consumer exists.

## Disposition
- **D1 (documentation)** BUILT → `docs/architecture/ROOM_CLASSIFICATION.md`, all corrections folded in.
- **D2 (basement) / D3 (outdoor coercion)** PARKED with config triggers + the review's safety-test
  requirements attached for revival.
- Bug classes: #53 (one-missed-site), #63 (coincidental equality: utility==garage timeout).
