# PLANNING — EC solar power sensor override (EC-SOLAR-ENTITY-OVERRIDE-1)

**Tier:** 2 (one plan review before build; 2 framing-disjoint code reviews + live validation).
Not elevated to 2-DB: no DAO / payload-shape change, no new writer to a shared primitive. The only
behavioral delta is *which entity_id* feeds the existing `solar_production` entity-map key.
**Version:** PATCH (fix-class knob).
**Status:** plan — not built.

## Problem (verified 2026-10-02, operator)

The Envoy's own production aggregate broke at 23:05 Oct 1 (local `/api/v1/production` reports
`wattsNow` 0, lifetime reset to 45,505 Wh; inverters + CT meters healthy; reboot did not fix).
`sensor.envoy_482543015950_current_power_production` = 0.0 while
`sensor.envoy_482543015950_production_ct_power` (kW, same unit) reads real solar.

The EC solar input is *derived*, not configured: `__init__.py:3484-3494` copies every `energy_*`
CM option into `energy_entity_config`, then `derive_envoy_config(serial)` (`energy_const.py:1092-1116`)
is merged with `setdefault` — so an explicit `energy_solar_entity` already wins. No options-flow
field exposes that key, so the operator cannot set it.

## Config-first check (CLAUDE.md step 1b)

- Integration option `solar_production_sensor` (`const.py:1395`, consumed `aggregation.py:2859`)
  already switched by the operator to `production_ct_power`. **Separate key; does not reach EC.**
- No CM options field, Number, or Select writes `energy_solar_entity` (grep of `config_flow.py`
  for `CONF_ENERGY_SOLAR_ENTITY` = zero hits). Hand-editing `.storage` is not an acceptable
  operator action. **Code is required, minimally: one field.**

## Falsifiable invariant

> With the override **blank**, every runtime and validation path resolves `solar_production` to
> `sensor.envoy_{serial}_current_power_production` exactly as today (byte-identical
> `energy_entity_config`). With the override **set** to X, every read of live solar power in URA
> resolves to X — there is no **integration (Python) runtime** path that still reads the derived name.
> (Scope note from plan review: the PWA dashboard reads the derived entity by literal name —
> `dashboard-v3/src/components/tabs/Energy.tsx` "Solar now" card, bundled as
> `frontend-v3/assets/Energy-*.js`. Display-only, out of scope here; carded separately.)

## Institutional context verified

### Greps run + results
| Proposed item | Verdict | Evidence |
|---|---|---|
| Config key `energy_solar_entity` | **REUSED** | `CONF_ENERGY_SOLAR_ENTITY` `energy_const.py:275` |
| Override precedence | **REUSED** | `setdefault` merge `__init__.py:~3491`; `validate_envoy_config` "explicit wins" `energy_const.py:1466-1469`; `repairs.py:64-80` same shape |
| Entity map key `solar_production` | **REUSED** | `energy.py:1000` key_map |
| Options-flow field | **NEW** (field only) | `grep CONF_ENERGY_SOLAR_ENTITY config_flow.py` → 0 hits |
| Clear-on-omit pattern | **REUSED** | `config_flow.py:11608-11624` (`clearable` pop), `:12059-12064` (HVAC vacancy hold) |
| Generic "override any derived Envoy entity" | **NOT BUILT** (parked, see Non-goals) | 13 keys in `derive_envoy_config` |
| New constant / sensor / signal | none | — |

### Prior planning docs consulted
- Skim of `docs/planning/` filenames for envoy/solar/EC: EC Envoy boot-decoupling (validation three-way
  semantics, now in `validate_envoy_config` docstring `energy_const.py:1363-1398`); ENVOY-PRODUCTION-STALE-1
  D3-B (fresh reader, `energy_battery.py:2478-2491`); LKG wave 1 D2 (solar envelope); CM reload
  suppression (v4.7.26/27).
### Memory bodies relevant (index lines)
- `project_session_pickup_2026_09_23` (Envoy flapping arc), `reference_ec_config_surface`
  (enumerate, don't guess), `feedback_parent_entry_reload_watchdog_hazard`,
  `project_cm_reload_suppression_cycle_stack`, `feedback_label_style_guide`,
  `feedback_marginal_benefit_pushback`, `project_single_user_no_backcompat` (2nd home: optional
  fields must degrade gracefully).
### Design docs
- `docs/Coordinator/` EC manual not re-read for this plan-level scope; builder must skim EC manual
  §config surface before editing (reviewer to confirm).
### Code surveyed
- `__init__.py:3470-3520` (derive/merge/validate), `:6860-6995` (`_NO_LIVE_ATTR_KEYS`,
  `OPTIONS_RELOAD_SUPPRESS_KEYS`), `:7800-8128` (`_async_update_listener` CM branch).
- `energy_const.py:1092-1128`, `:1360-1490` (`validate_envoy_config`).
- `config_flow.py:4607-4666`, `:4996-5026` (save path), `:5065-5070` (Envoy field).
- `energy.py:586-592`, `:995-1024`; `energy_battery.py:1583-1585`, `:1729-1760`, `:2436-2531`;
  `energy_billing.py:105,121`; `sensor.py:14071-14096,14283`; `energy_pool.py:1895`; `repairs.py:64-80`.

## PRODUCER check

`solar_production` resolves once at CM setup: `energy_entity_config[CONF_ENERGY_SOLAR_ENTITY]`
→ `EnergyCoordinator._build_entity_map` (`energy.py:1000`) → BatteryStrategy entity map. All live
reads go through `BatteryStrategy._get_entity("solar_production")` / `_read_fresh_power_w("solar_production", ...)`.
Dependency health: derived entity is **broken** (0.0, aggregate dead upstream); CT entity healthy,
**same unit (kW)** — `solar_production_w` (`energy_battery.py:1729+`) normalises by unit, so no
unit-conversion change is needed. Builder must confirm the CT sensor's `unit_of_measurement` attribute
is `kW` live, not assume.

## CONSUMER + call-site map

| # | Consumer | file:line | Reads via | Override flows? |
|---|---|---|---|---|
| 1 | `BatteryStrategy.solar_production` (raw) | `energy_battery.py:1583-1585` | entity map | YES |
| 2 | `BatteryStrategy.solar_production_w` (normalised + LKG stamp) | `energy_battery.py:1729-1760` | entity map, fresh reader | YES |
| 3 | `solar_production_w_envelope` (LKG envelope gate) | `energy_battery.py:2436-2531` | entity map, fresh reader | YES |
| 4 | Battery strategy sensor attr `solar_production` (+ envelope attrs) | `energy_battery.py:4300, 5154, 6016, 6348-6355` | #1 / #3 | YES |
| 5 | EC excess-solar / solar-follow math (`solar_w`) | `energy.py:3442, 3595` | #2 | YES |
| 6 | EC DB snapshot rows `solar_production` kW | `energy.py:3156-3158, 3224, 3267-3277` → `database.py:4936-4945` | #2 | YES |
| 7 | EC envelope passthrough → pool | `energy.py:3858-3890`, `energy_pool.py:1895` | #3 | YES |
| 8 | Envoy freshness sensor `solar_age_s` | `sensor.py:14071-14096, 14283` | entity-map key | YES |
| 9 | `CostTracker(solar_entity=...)` | `energy.py:589` → `energy_billing.py:121` | constructor arg | YES (but **stored, never read** — `self._solar_entity` has no reader; KEEP+DOCUMENT, not a leak) |
| 10 | Setup validation V4 | `__init__.py:~3518` → `energy_const.py:1466-1484` | `resolved` explicit-wins | YES |
| 11 | Options-save validation | `config_flow.py:4996-5020` | merged options + submission | YES |
| 12 | Repair re-validation | `repairs.py:64-80` (setdefault merge) | explicit-wins | YES |
| 13 | Integration aggregation solar | `aggregation.py:2859` | `CONF_SOLAR_PRODUCTION_SENSOR` (separate key) | N/A — operator already set |

**Leaks (paths reading the derived name independently): none found.** The only literal
`current_power_production` occurrences are `derive_envoy_config` (`energy_const.py:1103`) and a
docstring (`:1083`). HVAC does not read solar power (grep of `solar_production|solar_w|solar_kw`
returns no hvac*/presence files).

**Adjacent (NOT a leak of this key, but same upstream break — card it):**
`CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY` (`energy.py:194`) is also derived from the broken aggregate
(lifetime reset to 45,505 Wh). Daily `solar_produced_kwh` (`energy.py:2766-2831`) will compute a
negative delta on the reset day and be nulled by the guard at `:2791-2800`, then be wrong relative
to history afterwards. Solar day-class / forecast paths read Solcast entities (key map
`energy.py:1021-1023`) — reviewer to confirm none read live production. Recommend a separate card
`EC-LIFETIME-PRODUCTION-RESET-1` (measure first: is the post-reset counter monotonic again?).

## Reload behavior (watchdog hazard check)

- A CM options save whose changed keys are **not** all in `OPTIONS_RELOAD_SUPPRESS_KEYS`
  (`__init__.py:6964`) falls through to a **CM entry reload** (`__init__.py:8110-8127`). This is the
  CM entry, not the parent INTEGRATION entry (parent cascade is the 2026-08-07 watchdog incident;
  separate branch `:8141`).
- `energy_entity_config` and the entity map are built only at setup — there is no live push path for
  entity-id keys today. Existing derived-key overrides would behave the same way.
- **Decision: do NOT add the key to `OPTIONS_RELOAD_SUPPRESS_KEYS`.** A reload is *required* to rebuild
  the entity map; suppressing it would persist the value but leave EC reading the old entity until the
  next restart (Bug Class: computed-but-not-consumed). This is a set-once field; one CM reload per
  save is acceptable and matches how the Envoy entity field already behaves.
- Marginal-benefit note: a hot-apply (mutate `_battery` entity map + `_billing._solar_entity` in
  `_apply_in_place`) would avoid the reload but adds a new live writer to the EC entity map and must
  reset the LKG stamp source. Not worth it for a set-once field. **Parked**; revisit trigger: CM
  reload on this save is observed to stall the loop / trip watchdog.
- **Timing:** operator applies the save while the house is awake (CM reload restarts coordinators;
  see `feedback_no_restart_during_sleep`).

## D1: Options-flow field "Solar power sensor (override)"

In `async_step_coordinator_energy` (`config_flow.py:4607`), immediately after the Envoy field
(`:5065-5070`), add:

```python
vol.Optional(
    CONF_ENERGY_SOLAR_ENTITY,
    description={"suggested_value": self._get_current(CONF_ENERGY_SOLAR_ENTITY)},
): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
```

- `suggested_value` (not `default`) so the field renders empty when unset and is clearable — mirror
  the Envoy field.
- **Clear handling (mandatory):** the save does `data={**options, **user_input}` (`:5022-5026`),
  which resurrects a stored value when the cleared field is omitted. Before `async_create_entry`
  (and before the `validate_envoy_config` merge at `:5000` so validation sees the cleared state),
  pop the key from the merge when absent from `user_input` or empty — reuse the
  `config_flow.py:11622-11624` pattern. Empty string must never be persisted. (Plan review
  correction: a `""` does NOT hard-fail V4 — `validate_envoy_config` resolves with `or`
  (`energy_const.py:1469`) so validation passes on the derived name, while the runtime `setdefault`
  (`__init__.py:3491`) keeps `""` → `_get_entity("solar_production")` resolves nothing → solar
  silently None. Silent divergence, worse than a hard-fail; the pop is mandatory.)
- Import `CONF_ENERGY_SOLAR_ENTITY` in the step's local import block (`:4616`).
- **Labels** (`strings.json` + `translations/en.json`, `options.step.coordinator_energy`):
  - name: `Solar power sensor (override)`
  - description: `Leave blank to use the Envoy's solar reading. Pick a sensor here only if that reading is wrong.`
  Plain words, no "derived/aggregate". (Style guide: short phrase + plain helper.)
- No new number → no knob-ladder entry (it is a rung-2 config field: per-deployment structure, set once).
- Validation: `validate_envoy_config` already resolves explicit-wins and checks the resolved solar
  entity for registry/state existence (`energy_const.py:1471-1485`) — a non-existent pick is
  rejected with `derived_entity_missing` on the field key `energy_solar_entity`, which now maps to a
  real form field (good: inline error). No validator change.

### Acceptance Criteria
- **Verify:** With override blank, `energy_entity_config` built at setup is dict-equal to the pre-change build for the same CM options (byte-identical default).
- **Verify:** Setting the override persists `energy_solar_entity` in CM options; clearing it removes the key (not `""`, not the old value).
- **Verify:** Picking a non-existent sensor rejects the save with an error on the field.
- **Test:** `test_ec_solar_override_options_roundtrip_set_and_clear` — drives the real `async_step_coordinator_energy` handler: set → key present; resubmit with field omitted → key absent; resubmit with `""` → key absent.
- **Test:** `test_ec_solar_override_invalid_entity_rejected`.

## D2: Behavioral wiring test on real setup code

No production change expected beyond D1 (precedence already exists); D2 proves it.

### Acceptance Criteria
- **Test:** `test_ec_solar_override_reaches_battery_strategy` — run the real CM setup path (not a fake coordinator — v5.8.0 incident lesson) with CM options containing `energy_envoy_entity=sensor.envoy_<serial>_...` and `energy_solar_entity=sensor.envoy_<serial>_production_ct_power`; set states derived=`0.0`, CT=`4.2` kW. Assert EC battery strategy `solar_production` == 4.2 and `solar_production_w` == 4200.
- **Test:** `test_ec_solar_override_blank_uses_derived` — same, override absent → reads derived (0.0). Discriminating: the two states differ, so a test passing under both configs is impossible.
- **Test:** `test_ec_solar_override_validation_resolves_override` — `validate_envoy_config(...)["resolved"][CONF_ENERGY_SOLAR_ENTITY]` equals the override.
- **Drill (wire-in anchor):** neuter the `setdefault` merge to an overwrite (`energy_entity_config[k] = v`) → the override test must FAIL; restore; clear `__pycache__` (stale-.pyc rule).

## D3: Live

### Acceptance Criteria
- **Live:** After setting the override (house awake), log shows `CM options changed ... falling through to reload (changed_keys=['energy_solar_entity'])`, no watchdog/stall, CM back within normal setup time.
- **Live:** `sensor.ura_energy_coordinator_battery_strategy` attribute `solar_production` equals live `sensor.envoy_482543015950_production_ct_power` (±rounding) while it is >0 in daylight — and is NOT 0.0. Discriminates fix vs no-effect (no-effect = 0.0 = broken aggregate).
- **Live:** Envoy freshness sensor `solar_age_s` attribute is small (seconds), not climbing — proves the freshness reader follows the override.
- **Live:** EC DB snapshot row (`energy` snapshot table, `solar_production` column) written after reload is non-zero in daylight.
- **Live:** No new `envoy` repair issue raised.

## Non-goals / parked

- **Generalising to all 13 derived Envoy entities** — PARKED. Marginal-benefit: only solar is broken
  today; 12 more selectors bloat the form (parsimonious-config rule) and each needs its own consumer
  audit. **Revisit trigger:** a second derived Envoy entity is observed broken while a healthy
  sibling sensor exists, OR the second-home install needs a non-Envoy solar/grid source.
- Lifetime-production reset (adjacent, see above) — separate card.
- Hot-apply without CM reload — parked (see Reload behavior).
- Removing the dead `CostTracker._solar_entity` — KEEP + DOCUMENT, out of scope.

## Files to change
- `custom_components/universal_room_automation/config_flow.py` (field + clear handling)
- `custom_components/universal_room_automation/strings.json`, `translations/en.json` (labels)
- `quality/tests/test_ec_solar_entity_override.py` (new)
- `docs/readmes/README_v<next patch>.md`; EC manual config-surface section (one row).

## Plan review (2026-10-02, one adversarial pass, Tier 2)

**Verdict: BUILD-READY** (after the in-plan fixes below).

Greps re-run independently:
- Literal `current_power_production` repo-wide: integration Python = only `energy_const.py:1083`
  (docstring) + `:1103` (derive). **Non-Python reader found:** PWA `dashboard-v3/src/components/tabs/Energy.tsx`
  (+ bundled `frontend-v3/assets/Energy-*.js`) "Solar now" card hard-codes the derived entity → keeps
  showing 0 kW after the override. Display-only. Invariant narrowed to integration runtime; **card it**
  (e.g. PWA-SOLAR-NOW-ENTITY-1: read the EC battery-strategy `solar_production` attr instead of the raw entity).
  Also `scripts/telemetry_pair_probe.py` (offline probe, not runtime) and `quality/tests/test_envoy_auto_derive.py`.
- `solar_production` / `solar_production_w` consumers: matches the plan's map (#1-#8); no extra readers.
- Solar day-class (`energy_battery.py:2006/2060`): reads forecast entities + `SOLAR_MONTHLY_THRESHOLDS`/custom
  thresholds only — **does not read live production**. Confirmed, no leak.
- `energy_entity_config` consumers: `__init__.py:1213` (deferred re-validation) and `:3791/3830/4246` all take
  the same merged dict → override flows. HVAC only reads net-power (`:3830`).
- Options save (`config_flow.py:4996-5026`): merge `{**options, **user_input}` confirmed; validation runs only
  when the Envoy field is submitted (fine — override without Envoy has nothing to derive against).
  `cm_config = {**data, **options}` (`__init__.py:3302`); `data` never carries this key (no initial-flow field),
  so popping from options is sufficient.
- Precedence: `validate_envoy_config` explicit-wins via `or` (`energy_const.py:1469`) vs runtime `setdefault` —
  equal for non-empty values, **diverge on `""`** (corrected in D1 text).
- CM reload: plan's decision (no suppress-key; reload required) holds.

Findings:
| Sev | Finding | Disposition |
|---|---|---|
| MEDIUM | PWA "Solar now" reads derived entity by name; plan claimed "no leaks" | Fixed in plan (invariant scoped) + card needed |
| LOW | Plan said `""` → V4 hard-fail; actually validation passes and runtime silently reads nothing | Fixed in D1 text |
| LOW | Solar LKG snapshot (`energy.py:1655` restore) after the reload may carry a last-good from the old source; bounded by `DEFAULT_SOLAR_LKG_ENVELOPE_MAX_AGE_S` and superseded by the first live read | Note only; no change |

Acceptance criteria discriminate: D2 states derived=0.0 vs CT=4.2; D3 live "not 0.0" separates fix from no-effect.
Builder: add one D1 test case that the save path with Envoy set + valid override passes validation (resolved key = override).
