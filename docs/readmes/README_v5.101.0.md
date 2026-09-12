# v5.101.0 — Radically simplified first-run onboarding

**Type:** Feature cycle — a new user-facing capability: the first-run setup path
(integration → house → first room) is reshaped to an assistive, essentials-only
flow with area auto-detect-and-confirm, targeting ≥50% less operator cognitive load.
**Tier:** 3 (delicate — config-flow first-run path, silent-default-flip surface,
one-missed-site risk). Reviews: 1 Tier-2-DB PLAN review + **4 framing-disjoint BUILD
reviews (A round-trip/INV-1, B migration/D9-parity, C test-authority-via-mutation,
D adversarial-completeness)** + consolidated fix-up + orchestrator mutation-verify +
**fresh completeness re-review (= SHIP)**.
Plan: `docs/planning/PLANNING_onboarding_simplify.md`.
Audit: `docs/planning/AUDIT_first_run_onboarding.md`.
Knob inventory: `docs/planning/ONBOARDING_SIMPLIFY_D8_knob_inventory.md`.

## What shipped

A fresh install no longer walks the operator through a long, tuning-heavy form chain.
The reshaped create path is **essentials-only**, everything else is reachable (and
unchanged) in the Options flow:

- **Area auto-detect + confirm (D1).** New rooms pre-fill their sensors/actuators from
  the HA **area** via the entity registry (`entity_category is None` excludes the
  diagnostic-temp footgun; `hidden_by`/helper platforms excluded). When >1 candidate,
  a pure `_rank_area_candidates` ranks them (own-area > inherited; dedicated >
  actuator-shared; name-denylist internal/chip/rssi/battery) and the operator always
  confirms — never auto-committed. **Single-select** buckets (temp/humidity/lux) dedup
  to one suggested winner; **multi-select** buckets (motion/occupancy/covers/lights/
  fans) rank-only, never collapse (an FP2 with 4 occupancy zones pre-fills all 4).
- **Essentials chain (D3).** `room_setup` (name/type/area + conditional zone) →
  `room_class` (load-bearing classes up front: wet-room, guest-room — each with its
  implication stated, soft-defaulted from room type, never silently flipped) →
  `sensors_confirm` → `devices_confirm` → `room_summary`. Occupancy timeout is
  auto-derived from room type. Tuning constants are **off** the essentials path.
- **Continuous house→room ribbon (D4).** The House (integration) entry is minted
  **eagerly** the moment the energy step submits — via the internal
  `flow.async_init(source="integration_create")` pattern — then the flow continues
  straight into the first room, which links to the already-created House. A reachable
  **"Skip — add rooms later"** branch ends with a reassuring *"Home installed…"*
  message.
- **Room-type feature defaults (D2/D9).** A single `ROOM_TYPE_FEATURE_DEFAULTS`
  producer seeds feature enables (e.g. bathroom → wet-room + humidity-fan spike +
  humidity-fan presence-runtime) as **soft** defaults — an explicit operator choice
  always wins.
- **Assistive house step (D5).** Weather entity auto-detected and offered via
  `suggested_value`.
- **Legibility (D6/P7) + strings.** All new steps carry operator-facing copy in
  `strings.json` + `translations/en.json` (empty-bucket hints, a closing summary).

### Invariants this cycle guarantees (Tier-3, falsifiable)
- **INV-1** — the reshaped create path loses **no** option key vs the pre-cycle path
  (all 48 deferred keys remain reachable + round-trip in Options; consumer fallbacks
  verified equal).
- **INV-2** — **no** non-required selector is silently committed with a guessed value
  (cleared single-entity selectors persist EMPTY — uses `suggested_value`, not
  `default=`; the v5.37.1 back-fill hazard is NOT reintroduced).
- **INV-3** — essentials-derived values are deterministically derived; no room TYPE
  silently loses a feature default it had pre-cycle.
- **One-House** — every first-run path yields **exactly one** House entry (no zero —
  the prior zero-House dead path is closed; no double; no orphan), including the
  no-occupancy-sensor install that previously could not complete at all.

## Known-issue / not addressed
- **F6 (operator decision pending):** `_EXCLUDED_PLATFORMS` excludes `template` (and
  group) entities from auto-suggest. This house uses template occupancy + light
  groups, so those need manual add (no capability loss — selectors still allow manual
  pick). [Resolved at deploy per operator call: INCLUDE / KEEP-EXCLUDED — fill in.]
- **INV-3 test enforcement** anchors one bathroom key-set, not the full 48-key
  enumeration (would not catch a future 49th deferred key). Noted, accepted.
- B5 residual area-prefills (window/power/energy/cameras/scanner/egress) intentionally
  deferred to Options (Options-reachable, no capability loss) — dropped-fields table
  in the plan.

## Rollback
`pre-review-v5.101.0` tag = pre-fix baseline. No DB/schema change in this cycle, so
rollback is clean: HACS re-download the prior version + restart, or `git revert` the
onboarding commits on develop + redeploy. Existing rooms/House entries are untouched
(create-path-only change).

## Live validation — acceptance criteria (discriminating)
*(prospective — filled in with observed results after the post-deploy restart)*

- **L1 (restart resilience):** after HA restart URA loads, `ha_check_config` valid,
  **zero new URA ERROR** logs, config-flow handlers importable. Discriminator: a
  broken flow would leave the integration `setup_error`.
- **L2 (one-House on fresh first-run — THE invariant):** on a simulated/next fresh
  install, submitting the integration + energy steps creates **exactly one**
  `ENTRY_TYPE_INTEGRATION` entry titled `🏠 Home` **before** any room is committed.
  *Discriminator vs the pre-fix regression:* pre-fix the House was minted only after a
  room completed, so a no-occupancy install produced **zero** entries.
- **L3 (no-occupancy install completes):** a first run where no occupancy sensor is
  assignable still yields a working House + Coordinator Manager (via the Skip route),
  ending on the *"Home installed…"* message — not the old `not_supported` dead end.
- **L4 (essentials + auto-detect):** adding a room shows only the essentials steps;
  an area with a dimmable/color light persists `CONF_LIGHT_CAPABILITIES="full"`
  (entry-on brightness/color works); a bathroom seeds wet-room + humidity-fan spike +
  presence-runtime. *Discriminator:* a regression would leave light_capabilities
  absent (→ BASIC, no brightness) or the bathroom flags unset.
- **L5 (INV-2 live):** in an area with a candidate temp sensor, clearing the
  pre-filled temperature selector and submitting persists **no** temperature sensor
  (not the guessed value).
- **L6 (no capability loss):** a room created on the new path exposes the same deferred
  fields in Options as before (spot-check water-leak, window, cameras, scanner areas).
