# PLANNING — NM Cycle C-2: Routing UI + Life-Safety Union Knob + Device Consolidation

**Sequenced after:** v5.27.0 (NM Cycle C) ships from `build/nm-cycle-c` and completes live validation + README write-back.
**Target version:** v5.28.0 (nominal; confirm at cycle start).
**Operator directives (2026-07-21):** "File it and plan it" for the routing UI; for overheat / high_co2 life-safety classification, "Tunable?" — this doc answers yes, ADDITIVE-ONLY, rung 2.

---

## Institutional context verified

### Prior planning docs consulted
- `docs/planning/PLANNING_nm_overhaul_2026_07.md` — full read of Cycle C section (lines 235-273) + revision log entries #3 (hazard_type axis), #7 (NM-1 mute shortcut), #10 (Tier-3 elevation), and the deferred-work register entry (2026-07-20, A-MED-2) on overheat/high_co2 cadence — the exact operator "tunable?" question this cycle answers.
- `docs/planning/PLANNING_nm_cycle_a2_knob_surface.md` — options-flow knob-surface reference (matches the A-2 step this cycle mirrors).
- `docs/reviews/code-review/v5.26.0_nm_cycle_b.md` — A-CRIT-1 (enum/string token mismatch, Bug Class #22) is the exemplar for how the life-safety frozenset went wrong once; the union helper (D2) inherits the vocabulary-authority guardrails.

### Memory bodies pulled
- `project_v4_7_25_hvac_presence_timer_knobs_live.md` — options-flow bidirectional-clamp pattern (A-HIGH-1) for cross-field validation similar to what routing-matrix completeness will need.
- `project_incident_v5_8_0_setup_recursion.md` — reminder that fake-coordinator tests don't exercise real construction; D1/D2 tests MUST wire options through real `async_step_*` handlers, not synthetic dicts.

### Design docs
- No dedicated Coordinator design doc for NM; the planning doc above is the authoritative NM architecture reference. This cycle updates it in-place with a `## Cycle C-2` section rather than a new file.

### Code locations surveyed (end-to-end)
- `custom_components/universal_room_automation/config_flow.py:6290-6560` — `async_step_coordinator_notifications_volume` (the A-2 step). Reused as the structural template for D1 and D2 sub-steps: `_get_current` accessor, `NumberSelector`, `BooleanSelector`, per-key `_DEFAULTS` map, `_equals_default` numeric+list coercion, save-side default-drop, form re-render on `errors["base"]`, direct `async_create_entry(title="", data=new_opts)` write with a merged options dict.
- `custom_components/universal_room_automation/const.py:1339-1347` — `NM_LIFE_SAFETY_HAZARDS` frozenset (rung 1, the invariant-critical vocabulary).
- `custom_components/universal_room_automation/const.py:1330-1368` — NM CONF/DEFAULT constants pattern (rung, unit, docstring style).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:997, 1657, 2384, 2417, 2491` — **the 5 read-sites of `NM_LIFE_SAFETY_HAZARDS`** (see D2 consumer-site enumeration below; this is the load-bearing set for the union helper).
- `custom_components/universal_room_automation/__init__.py:4609-4662` — `_NO_LIVE_ATTR_KEYS` + `OPTIONS_RELOAD_SUPPRESS_KEYS` frozensets (membership tests — every new CONF key from this cycle MUST land in both to preserve the reload-suppression contract A-2 fix-up ratified).
- `custom_components/universal_room_automation/switch.py:3421-3510` — NM dry-run switch (device_info identifier `(DOMAIN, "notification_manager")`) — the device page D3 consolidates around.
- `custom_components/universal_room_automation/number.py:3190-3300` — `_nm_device_info()` mixin, `NMBucketCapacityNumber`, `NMBucketRefillPerMinNumber` — the two NM Numbers that already exist on develop.

### Institutional grep results — REUSED vs NEW

| Proposed | Status | Anchor |
|---|---|---|
| `async_step_coordinator_notifications_routing` (per-person routing sub-step) | **NEW** — no per-person matrix step exists on develop; mirrors A-2 shape (`config_flow.py:6290`) | — |
| Save-side default-drop for matrix keys | **REUSED** — `_equals_default` at `config_flow.py:6360-6374` handles list/tuple order-independent compare; extend to nested dict via canonical-serialization helper | `config_flow.py:6337-6374` |
| Cross-field validation (matrix completeness / DND-bypass severity legality) | **REUSED PATTERN** — monotonicity check at `config_flow.py:6388-6401` (`errors["base"]` + re-render); D1 does the same for matrix completeness | `config_flow.py:6388-6401` |
| Enum-vs-str L4 coercion (severity/channel lowercase) | **REUSED** — allowlist coercion at `config_flow.py:6378-6384` (str-lowercase before equality check) — Bug Class #22 mitigation | `config_flow.py:6378-6384` |
| Membership in `_NO_LIVE_ATTR_KEYS` + `OPTIONS_RELOAD_SUPPRESS_KEYS` | **REUSED** — must add the 4 Cycle-C CONF keys + `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` to both frozensets (`__init__.py:4609-4662`) | `__init__.py:4609-4662` |
| `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` | **NEW** — no life-safety-classification knob today (frozenset is source-only); rung 2 per Numbers-Get-Knobs; ADDITIVE-only by construction (union, never difference) | — |
| Life-safety union helper (`is_life_safety_hazard(hz)`) | **NEW** — the 5 read-sites currently inline `str(hazard_type or "").lower() in NM_LIFE_SAFETY_HAZARDS` (Bug Class #53: computed-but-not-consumed risk if any site is missed) | replaces 5 inline reads |
| NM device page consolidation | **REUSED** — `_nm_device_info()` mixin at `number.py:3190`; add `_attr_entity_category` where appropriate | `number.py:3190-3218` |

**Falsifiable invariant (Tier-2-DB / Tier-3 elevation hinge):**
> **I-C2-LS:** For any `hazard_type H` and any reachable NM code path, `H` is treated as life-safety (30 s cadence, bucket-bypass, boot-settle exemption, DND floor, mute exception) **if and only if** `H ∈ (NM_LIFE_SAFETY_HAZARDS ∪ options[CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS])`. Demotion of any member of `NM_LIFE_SAFETY_HAZARDS` is impossible by construction (union, never difference).

---

## D1 — Per-person routing UI (severity × channel matrix + hazard overrides + DND-bypass)

Adds one new options-flow sub-step (or per-person nested sub-steps) under the CM menu that authors the persisted CONF keys the Cycle C router already honors:
- `CONF_NM_PERSON_ROUTING_MATRIX` — `{person_id: {severity: {channel: bool}}}`
- `CONF_NM_PERSON_HAZARD_OVERRIDES` — `{person_id: {hazard_type: {severity: {channel: bool}}}}` (optional 3rd axis; empty = 2D-default per doc line 240)
- `CONF_NM_PERSON_DND_BYPASS_SEVERITIES` — `{person_id: [severity, ...]}` (default `{CRITICAL}` per doc line 254)
- `CONF_NM_MUTE_DEFAULT_DURATION_MINUTES` — Number-backed knob for the `nm.mute_person_channel` service default (rung 3, per Numbers-Get-Knobs)

### Sub-step topology
1. Landing sub-step lists configured persons (drawn from existing `CONF_NM_PERSON_*` keys already on develop — Institutional Context: `CONF_NM_PERSON_DELIVERY_PREF` at const.py ~line 748 per the audit doc) with an "edit routing for <person>" selector.
2. Per-person sub-step: a grid of `BooleanSelector` per (severity × channel) cell. Channel columns are `NM_CHANNELS_KNOWN` (source of truth); severity rows are the `Severity` enum values lowercased.
3. Optional hazard-override sub-step (revealed by an "Add hazard override" toggle): (hazard_type multi-select × severity × channel) collapsed grid.
4. DND-bypass sub-step: `SelectSelector(multiple=True)` over severity values; default `["critical"]`.

### Save-side contract (mirrors A-2 fix-up mechanisms verbatim)
- **Lowercase coercion (Bug Class #22 mitigation).** Every submitted severity, channel, and hazard_type token is `str(x).lower()`'d **before** equality/default-drop compares. Mirrors `config_flow.py:6378-6384`.
- **Default-drop.** For each `(person, severity, channel)` cell, if the submitted value equals the migration-derived default (the legacy `CONF_NM_*_SEVERITY`-implied bool), drop it from the persisted dict. Nested-dict equivalent of `_equals_default` at `config_flow.py:6360-6374` — implement `_canonical_matrix(d)` (sorted keys, tuple values) then compare. **This is load-bearing:** without it, "open form + save" freezes the current routing defaults into the entry and future migration retunes stop reaching this deployment (the C-MED-1 trap from A-2).
- **Matrix completeness validation.** Every configured `(person, severity)` row MUST resolve to ≥1 truthy channel OR be explicitly all-false (interpreted as "silent for this person at this severity"). Rows with mixed missing keys re-render the form with `errors["base"] = "nm_c2_matrix_row_incomplete"`. Mirrors `config_flow.py:6388-6401`.
- **v3.2.3.1 options-clobber trap.** The step MUST start from `dict(self._config_entry.options)`, mutate only the CONF keys it owns, and write the merged dict — never a fresh dict of just the step's fields. Mirrors `config_flow.py:6410-6418`.
- **"Number Fields = Form Fields" trap.** `CONF_NM_MUTE_DEFAULT_DURATION_MINUTES` has BOTH a Number entity (live-tunable dashboard surface) AND a form field on the routing step; both must round-trip through the same option key and neither may clobber the other. Reuse the Number-persistence pattern from `_nm_device_info()` writeback (`number.py:3190-3300`) and add the key to `OPTIONS_RELOAD_SUPPRESS_KEYS` so a form save does not reload CM.
- **Membership.** All D1 CONF keys added to `_NO_LIVE_ATTR_KEYS` (no live-attr push) AND `OPTIONS_RELOAD_SUPPRESS_KEYS` (in-place apply). See `__init__.py:4609, 4662`.

### Acceptance criteria
- **Verify:** With no options set, the routing sub-step renders defaults derived from the legacy `CONF_NM_*_SEVERITY` migration and saves nothing (empty persisted matrix ≡ legacy behavior; matches Cycle C acceptance line 267).
- **Verify:** Submitting the form untouched leaves `entry.options` byte-identical (default-drop proven).
- **Verify:** Matrix-row incompleteness re-renders with `errors["base"]`.
- **Verify:** Editing a single (person, severity, channel) cell writes only that cell into the persisted matrix.
- **Test:** `test_cycle_c2_options_flow_routing_matrix_default_drop`, `test_cycle_c2_matrix_lowercase_coercion`, `test_cycle_c2_matrix_row_incompleteness_reraises_form`, `test_cycle_c2_dnd_bypass_round_trip`, `test_cycle_c2_mute_duration_number_and_form_no_clobber` — all wire real `async_step_*` (not synthetic dicts; per v5.8.0 incident lesson).
- **Live:** Author a routing change via the options-flow UI for one person; MCP-verify `entry.options[CONF_NM_PERSON_ROUTING_MATRIX]` contains ONLY the changed cells; MCP-fire a synthetic CRITICAL through the dry-run gate; audit log shows the intended channel-set.
- **Live:** Round-trip: reload the config entry (in-place, no CM reload — verify sibling `last_changed` invariant per v4.7.26/27 pattern) and re-open the form; every field renders the persisted value.

---

## D2 — `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` (operator "Tunable?" answer)

**Directive.** Operator asked whether the overheat / high_co2 life-safety classification should be tunable. Answer: **yes, ADDITIVE-ONLY, rung 2.** The base frozenset stays a rung-1 code-reviewed safety contract; the knob can only PROMOTE non-base hazards into life-safety treatment. Demotion is impossible by construction.

### CONF definition (const.py)
```python
# NM Cycle C-2 (2026-07-21): additive-only life-safety promotion.
# The base NM_LIFE_SAFETY_HAZARDS frozenset stays rung-1 code-reviewed
# (demotion requires code review + Tier-3). This options knob PROMOTES
# additional HazardType tokens into life-safety treatment: 30s cadence,
# bucket bypass, boot-settle exemption, DND floor, mute exception.
# Kill-switch: empty list = base set only (byte-identical to Cycle C).
CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS: Final = "nm_extra_life_safety_hazards"
DEFAULT_NM_EXTRA_LIFE_SAFETY_HAZARDS: Final = []
```

Selector: `SelectSelector(multiple=True)` whose options are `[t for t in HazardType if t.value not in NM_LIFE_SAFETY_HAZARDS]` (e.g. `overheat`, `high_co2`, plus any future HazardType additions not already promoted). Options page copy explicitly states the promotion is one-way and kill-switch semantics (empty = base set only).

### Single-source-of-truth helper (the load-bearing site)
Add to `notification_manager.py` (or a small `_nm_life_safety.py`):
```python
def is_life_safety_hazard(hass, hazard_type: str | None) -> bool:
    """Union of NM_LIFE_SAFETY_HAZARDS and the operator-promoted extras.
    ADDITIVE-ONLY: base frozenset members are always life-safety."""
    token = str(hazard_type or "").lower()
    if token in NM_LIFE_SAFETY_HAZARDS:
        return True
    extras = _cached_extras(hass)  # cached like nm_cycle_a_knob(), flushed on options update
    return token in extras
```

### Consumer-site enumeration (Bug Class #53, computed-but-not-consumed)
All **5** current read-sites of `NM_LIFE_SAFETY_HAZARDS` must be migrated to `is_life_safety_hazard(...)`. This is the invariant proof surface Reviewer D re-enumerates; Reviewer C mutation-tests each site:

| # | File | Line | Site | Semantics if missed |
|---|---|---|---|---|
| 1 | `domain_coordinators/notification_manager.py` | 997 | `_boot_settle_should_suppress` gate (`life_safety_hazard` local var) | Promoted hazard would be collapsed during 60s boot-settle window |
| 2 | `domain_coordinators/notification_manager.py` | 1657 | `_repeat_interval_for(hazard)` → 30s vs 300s cadence selector | Promoted hazard would keep 300s paging cadence |
| 3 | `domain_coordinators/notification_manager.py` | 2384 | Bucket-bypass path (life-safety escapes token-bucket rate limit) | Promoted hazard would be rate-limited and droppable |
| 4 | `domain_coordinators/notification_manager.py` | 2417 | Quiet-hours / DND floor bypass | Promoted hazard would be suppressed during quiet hours |
| 5 | `domain_coordinators/notification_manager.py` | 2491 | Mute exception (per-person mute cannot silence life-safety) | Promoted hazard would be silenceable by a 2 AM mute |

**Test authority (Tier-2-DB Review C mandate).** Each of the 5 sites gets a mutation-anchored test: neuter the site's `is_life_safety_hazard(...)` call to `False`, run the suite, confirm a specific test fails, restore. A site whose bypass leaves the suite green is untested = unacceptable. Orchestrator personally re-greps `NM_LIFE_SAFETY_HAZARDS` post-migration to confirm **zero remaining inline reads** outside the helper + the helper itself + tests + const.py definition.

### Membership + reload contract
- `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` added to `_NO_LIVE_ATTR_KEYS` + `OPTIONS_RELOAD_SUPPRESS_KEYS`.
- Cache flush on options-update-listener (mirrors A-2 `nm_cycle_a_knob` cache flush) so the next tick sees the new union.

### Acceptance criteria
- **Verify:** With empty extras (default), every one of the 5 sites treats `overheat` and `high_co2` identically to v5.27.0 (byte-identical CRITICAL cadence 300s, bucket-eligible, etc.).
- **Verify:** With `extras=[overheat]`, all 5 sites treat `overheat` as life-safety in a single dry-run sweep.
- **Verify:** Removing `smoke` from `NM_LIFE_SAFETY_HAZARDS` at test time (mutation) must fail the vocabulary-authority test — demotion is impossible.
- **Test:** `test_cycle_c2_life_safety_union_helper_default_empty`, `test_cycle_c2_life_safety_union_helper_promotion`, `test_cycle_c2_life_safety_union_all_5_sites_route_through_helper` (grep-based: assert no `NM_LIFE_SAFETY_HAZARDS` read outside the helper module + const), plus one `test_cycle_c2_mutation_<siteN>_fails` per consumer site (5 tests).
- **Live:** Set `extras=[overheat]`; fire a synthetic overheat CRITICAL under dry-run; audit log shows 30s cadence + bucket-bypass + DND-bypass + mute-exception paths taken.
- **Live:** README write-back records the extras value in effect + the 24h count of promoted-path emissions.

---

## D3 — Control-surface consolidation for the NM device page

**Not a build for its own sake — a recommendation pass.** Inventory today (post-Cycle-C) and propose naming/category/visibility discipline.

### Current NM device-page inventory (post-v5.27.0)
| Kind | Entity | Source | Notes |
|---|---|---|---|
| Switch | `switch.ura_nm_dry_run` | `switch.py:3421` | B0 gate |
| Switch | `switch.ura_nm_messaging_suppress` | (Cycle B, branch) | Belt-and-suspenders |
| Number | `number.ura_nm_bucket_capacity` | `number.py:3202` | B3 |
| Number | `number.ura_nm_bucket_refill_per_min` | `number.py:3259` | B3 |
| Number | `number.ura_nm_mute_default_duration_minutes` (NEW D1) | this cycle | Rung 3 |
| Button | `button.ura_nm_mute_<person>_<channel>` × N | Cycle C C4 (branch) | NM-1 shortcut |
| Sensor | `sensor.ura_notification_manager` + ~10 attribute-carriers | notification_manager entity setup | Diagnostic |

### Recommendations (not to be over-built)
1. **Naming.** All NM-device entity object_ids prefixed `ura_nm_*`. `switch.ura_nm_dry_run` already conforms; audit that all bucket Numbers and mute Buttons follow suit. Rename any that don't at cycle boundary (breaking rename requires migration; if any Number is already published on develop, defer rename to a dedicated hygiene cycle rather than clobber unique_ids).
2. **Entity categories.**
   - `EntityCategory.CONFIG`: `nm_dry_run`, `nm_messaging_suppress`, `nm_bucket_capacity`, `nm_bucket_refill_per_min`, `nm_mute_default_duration_minutes` — operator dials, not runtime state.
   - `EntityCategory.DIAGNOSTIC`: mute-status sensors, overflow-drop counters, per-channel bucket-level attributes.
   - Default (control): per-person mute Buttons — these are user-invoked actions.
3. **Device-page vs hidden.** All CONFIG + DIAGNOSTIC entities visible on device page. Hide nothing by default; the operator has repeatedly said they want the surface visible.
4. **Per-channel enable toggle surface — RECOMMEND NO.** Global per-channel enable is already reachable via the options-flow "notifications" step (`CONF_NM_*_SEVERITY`) and per-person granularity now lives in D1's matrix. Adding a Switch entity per channel would create a third source of truth for the same policy (precedence-ordering trap; Bug Class #22 territory). Recommendation: **do not build**; document the options-flow location in the NM device-page suggested-cards docstring. If organic complaints surface in the 30-day window post-D1, revisit as a small follow-up.

### Acceptance criteria
- **Verify:** Inventory table matches live entities via MCP `ha_get_entities` filtered by device `notification_manager`.
- **Verify:** Every CONFIG entity carries `entity_category=EntityCategory.CONFIG`; every DIAGNOSTIC entity carries `entity_category=EntityCategory.DIAGNOSTIC`.
- **Test:** `test_cycle_c2_nm_device_entity_categories` — asserts categories on the entity classes at import time.
- **Live:** Screenshot / MCP dump of NM device page post-restart shows CONFIG cluster, DIAGNOSTIC cluster, mute Buttons, sensor summary — one coherent surface.

---

## Numbers-Get-Knobs table

| Number | Rung | Home | Why this rung |
|---|---|---|---|
| `CONF_NM_PERSON_ROUTING_MATRIX` | 2 | Options flow (D1) | Per-deployment routing structure, changed rarely, needs form for grid UX |
| `CONF_NM_PERSON_HAZARD_OVERRIDES` | 2 | Options flow (D1) | Per-deployment structure; same rung as parent matrix |
| `CONF_NM_PERSON_DND_BYPASS_SEVERITIES` | 2 | Options flow (D1) | Per-deployment policy; kill-switch: empty = respect quiet hours for all severities |
| `CONF_NM_MUTE_DEFAULT_DURATION_MINUTES` | 3 | Number entity + options-flow field (D1) | Operator legitimately tunes by observation ("60 min was too short at 2 AM"); dashboard-exposed |
| `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` | 2 | Options flow (D2) | Safety-classification policy; per-deployment; kill-switch: empty = base set only |
| `NM_LIFE_SAFETY_HAZARDS` (base frozenset) | 1 | `const.py` module constant | Rung-1 by design — demotion or membership churn is a safety contract that requires code review + Tier-3 |

---

## Tier classification — argued honestly

**Recommendation: Tier 2-DB (three framing-disjoint reviews) with the life-safety-union helper as the load-bearing site.**

Argument:
- D1 alone (options-flow authoring) is a Tier-2 feature cycle — mirrors A-2's shape exactly, and A-2 shipped safely at Tier 2.
- D2 pushes the cycle up to Tier 2-DB because it introduces a shared primitive (`is_life_safety_hazard`) consumed by **5 sites**, all of which govern safety-critical routing behavior (cadence, rate-limit bypass, DND, mute exception). This is textbook Bug Class #53 territory: computed-but-not-consumed. The three disjoint framings are:
  - **A** — local correctness (helper logic, cache flush, union algebra, kill-switch semantics on empty).
  - **B** — integration / cross-site (every one of the 5 sites reads via the helper; no inline `NM_LIFE_SAFETY_HAZARDS` remains outside helper+const+tests; options-update cache flush actually flushes; membership in the two reload-suppression frozensets is complete).
  - **C** — test authority via real per-site source mutation (neuter each of the 5 sites in turn; confirm a specific test fails; restore).

**Why not Tier 3?** D2's invariant is ADDITIVE by construction — the frozenset cannot be demoted through this knob, so the worst-case blast radius is "an operator-added hazard gets non-life-safety treatment on a missed site" (loss of a promotion), not "a base life-safety hazard gets silently demoted" (safety regression). That said, if the operator flags the cycle delicate at planning-review time, elevate to Tier 3 and add Reviewer D adversarial-completeness against invariant **I-C2-LS** — the framing is ready.

**Operator checkpoint:** After planning-doc review, before build kickoff, confirm Tier 2-DB vs Tier 3 elevation.

---

## Plan-completion stub

Track at cycle close under a "## Plan completion" section:
- [ ] D1 delivered / deferred (justification)
- [ ] D2 delivered / deferred (justification)
- [ ] D3 recommendations enacted (which) / deferred (which + where tracked)
- [ ] Per-channel enable Switch surface — decided NOT to build (D3.4); document location for revisit trigger
- [ ] README write-back with observed live results (per mandatory post-Live-Validation policy)

---

## Sequencing

1. **Precondition:** v5.27.0 (Cycle C) shipped, live-validated, README write-back complete, per-person channel targets populated per pipeline precondition #1 (planning doc line 282).
2. **Precondition:** Operator ratification of Cycle-B A-MED-2 open question (overheat/high_co2 cadence) — this cycle answers it via the D2 knob, so ratification is "yes, expose the knob; leave defaults empty (kill-switch position)".
3. This cycle: planning-doc review → operator Tier checkpoint → build → 3 (or 4) framing-disjoint reviews → fix-up → deploy → live validation → README write-back → close.
4. **Deferred to future cycles:** overflow drain (still deferred per Cycle B deferred-work register); per-channel enable Switch surface (D3.4 recommendation to not build now); any UI for the routing-decision audit-log query surface if C2 shipped a service+attribute but the operator wants a Lovelace card.

---

## Operator rulings — 2026-07-22 pre-build checkpoint

1. **Tier: ELEVATED TO TIER 3** (operator overrode the 2-DB call). Four
   framing-disjoint reviews incl. adversarial-completeness D-pass over the
   life-safety-union consumer surface; operator checkpoint before deploy.
2. **CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS closes the Cycle-B overheat/high_co2
   policy question.** Defaults stay empty; operator promotes from UI.
   Policy tracker entry retired.
3. **NM entity rename to uniform `ura_nm_*`: IN SCOPE for C-2** (operator
   chose rename-now while surface is small). MANDATORY: full
   safe-refactoring impact analysis first (dashboards incl. ura-v7 NM
   references, recorder history break documented, unique_id migration via
   entity registry where possible); rename is its own deliverable +
   review framing, not a drive-by.
4. **Audit surface: small markdown card** on a v7 tab showing last ~10
   routing decisions (who/what/why) — ships with C-2 for matrix-authoring
   feedback.
