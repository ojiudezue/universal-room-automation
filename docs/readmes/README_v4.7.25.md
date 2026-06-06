# URA v4.7.25 — HVAC Presence-Timer Knobs

**Release date:** 2026-06-06
**Tier:** Tier 2 (two parallel framing-disjoint staff-engineer reviews — A: correctness + edge cases + cross-field validation; B: async + HA lifecycle + reload race — plus live validation)
**Scope:** Exposes three previously hardcoded/invisible HVAC presence timers as
BOTH config-flow form fields (a collapsed `presence_timing` section) AND device
Number entities on the HVAC Coordinator card, adds a Reset-to-defaults button,
and retrofits the pre-existing zone-entry-dwell Number with the missing
persistence path (Bug Class #32). The `entry.options` of the Coordinator-Manager
entry is the single source of truth; each Number writes back via
`async_update_entry` and pushes its value to the live HVAC attr so the next
decision cycle picks it up immediately.

**Files:**
- `custom_components/universal_room_automation/number.py`
- `custom_components/universal_room_automation/button.py`
- `custom_components/universal_room_automation/switch.py`
- `custom_components/universal_room_automation/config_flow.py`
- `custom_components/universal_room_automation/strings.json`
- `custom_components/universal_room_automation/translations/en.json`
- `quality/tests/test_hvac_presence_timer_knobs.py` (NEW)
- `quality/tests/test_v4510_hvac_tunables_and_labels.py`
- `quality/tests/test_v4521_hc_device_ordering.py`

---

## Trigger

Three HVAC presence timers governed real comfort/energy behavior but were
invisible to the operator:

- **Vacancy grace (normal)** — how long a zone waits, while occupied-then-vacant,
  before backing off to Away.
- **Vacancy grace (energy-saving)** — the shorter grace used during an
  energy-coast/shed regime (`hvac.py` `energy_constrained` branch).
- **Max occupancy hours** — the dwell ceiling after which a continuously-"occupied"
  zone is treated as stuck.

Two were hardcoded; the zone-entry-dwell Number existed but had **no persistence
path** — setting it did nothing across a reload (Bug Class #32). This cycle makes
all four operator-tunable and durable.

---

## Headline Changes

- **Three new Number entities on the HVAC Coordinator device:**
  - `48 · Vacancy Grace (min)` — 0–60 min, `CONF_HVAC_VACANCY_GRACE_MINUTES`,
    pushes `hvac._vacancy_grace`.
  - `49 · Vacancy Grace — Energy Saving (min)` — 0–60 min,
    `CONF_HVAC_VACANCY_GRACE_CONSTRAINED`, pushes `hvac._vacancy_grace_constrained`.
  - `50 · Max Occupancy Hours (h)` — 1–24 h, `CONF_HVAC_MAX_OCCUPANCY_HOURS`,
    pushes `hvac._max_occupancy_hours`.
  All `NumberMode.BOX`, `EntityCategory.CONFIG`, no RestoreEntity (options is the
  sole store, avoiding config-form shadowing).
- **Zone-entry-dwell persistence retrofit (Bug Class #32).** The pre-existing
  `47 · Zone Entry Dwell (min)` Number now writes back to options and pushes
  `hvac._zone_entry_dwell` live, so it survives reload.
- **Collapsed config-flow section.** `async_step_coordinator_hvac_settings` gains
  a `presence_timing` section holding all four fields (flattened on save), with a
  cross-field guard: energy-saving grace may not exceed normal grace.
- **Reset button.** `51 · Reset Presence Timers` pushes the four defaults
  (dwell 15, grace 5, constrained 8, max-hours 3) to the live HVAC attrs and
  persists them in a single writeback.
- **Switch reclustering.** `HVACZoneSweepSwitch` renamed `50 ·`→`46 · Vacancy
  Auto-Off` so the presence-timer controls cluster together on the device card
  (unique_id/entity_id unchanged — cosmetic prefix only).

---

## Tier 2 Review + Fix-up

Two framing-disjoint reviews ran in parallel (Review A: correctness + edge cases
+ Bug Class #32 + cross-field validation; Review B: async correctness + HA
lifecycle + Bug Class #46 + CM reload race + restart resilience). Full report:
`docs/reviews/code-review/hvac_presence_timer_knobs_tier2.md`.

- **A-HIGH-1 (HIGH, fixed).** The config-flow form enforced
  `grace_constrained <= grace`, but the two Number entities are independently
  settable (device card / `number.set_value` / scripts). Driving constrained
  above normal inverts the HVAC `energy_constrained` branch — the house would
  wait *longer* to back off during an energy-shed regime. Fixed with a
  bidirectional clamp: the energy-saving setter clamps to `min(value, normal)`,
  and lowering the normal setter below the persisted energy-saving value clamps
  the latter down in the SAME writeback. Two regression tests added.
- **B-H1 (HIGH, accepted + documented).** Each Number's writeback fires the CM
  update-listener → one untracked `async_reload`. Rapid multi-edit = multiple
  reloads. Both reviewers confirmed the outcome is **convergent** (HA serializes
  reloads per-entry; the rebuilt coordinator re-seeds every attr from
  `entry.options` at setup). A debounce timer was rejected as over-engineering
  (introduces its own untracked-timer hazard for a convergent edge-case UX cost).
  The Reset button already batches into one writeback. Documented at the
  live-attr push sites.
- **A-MED-2 (MEDIUM, fixed).** Type-drift hygiene on the dwell value read.
- **B-M1 (MEDIUM, fixed).** Reload-window doc comment at the live-attr push sites.
- **A-MED-3 (subsumed).** `<=` (equality allowed) consistency — folded into the
  A-HIGH-1 clamp.
- **A-MED-1 (MEDIUM, deferred).** Config-flow `errors["base"]` collision between
  the cover-temp-hysteresis and vacancy cross-field checks (two-trip surfacing).
  This is the established single-base-error convention across all 15 base-error
  sites; surfacing both simultaneously needs field-attached errors inside a
  `section(...)` whose HA rendering is unverified (No-Fabrication). Tracked as a
  form-UX backlog item.
- **A-LOW-2 (LOW, rejected).** Keep `from __future__ import annotations` — it is
  load-bearing for the Python 3.9.6 test harness (pre-existing PEP 604 union
  annotations in number.py/button.py would `TypeError` at import without it; the
  deploy target is 3.10+ but the suite runs 3.9.6).

---

## Tests

- Cycle: 196 passed / 1 skipped (incl. 2 new A-HIGH-1 regression tests:
  `test_constrained_number_clamps_to_normal`,
  `test_lowering_normal_clamps_constrained_down`).
- Full suite baseline-diff: 62 failed both pre- and post-change (all pre-existing
  environmental failures needing real `homeassistant`/DB fixtures); passing count
  5034 → 5074. Zero new failures attributable to this cycle.
- All changed modules `py_compile` clean; no conflict markers.

---

## Live Validation (Review 3)

To be recorded post-restart against the running HVAC Coordinator device:

- **Verify:** All four timer Number entities render on the HVAC Coordinator
  device card — `47 · Zone Entry Dwell (min)`, `48 · Vacancy Grace (min)`,
  `49 · Vacancy Grace — Energy Saving (min)`, `50 · Max Occupancy Hours (h)` —
  each as a BOX-mode input with its persisted value.
- **Verify:** `46 · Vacancy Auto-Off` switch and `51 · Reset Presence Timers`
  button render on the same device, clustered with the timers.
- **Verify (persistence / Bug Class #32):** setting a timer Number persists
  across an HA restart (read back the entity value after restart) — the
  zone-entry-dwell retrofit specifically.
- **Verify (live-attr push):** changing a Number is reflected in the next HVAC
  decision cycle without a restart (the value reaches `hvac._<attr>`).
- **Verify (A-HIGH-1 clamp):** driving `49 · Vacancy Grace — Energy Saving` above
  the normal grace via `number.set_value` clamps it down to the normal value.
- **Verify (Reset):** pressing `51 · Reset Presence Timers` restores all four to
  defaults (15 / 5 / 8 / 3) in one writeback.
- **Verify (no errors):** error-log scan since boot shows zero
  tracebacks attributable to number.py / button.py / the HVAC settings step.

---

## Not in scope

- **Part 2 — EC/HC options-writeback retrofit.** The same options-as-sole-source
  + live-attr-push pattern applies to the Energy Coordinator and HVAC
  Climate-norm Numbers; deferred to a follow-up cycle.
- **A-MED-1 form-UX** (simultaneous base errors) — backlog.

## Review

See `docs/reviews/code-review/hvac_presence_timer_knobs_tier2.md`.
