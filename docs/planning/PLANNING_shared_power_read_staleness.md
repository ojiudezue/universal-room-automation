# PLANNING — Shared Power-Read Staleness Helper (ENVOY-PRODUCTION-STALE-1)

**Card:** `ENVOY-PRODUCTION-STALE-1` (consolidated per operator 2026-08-31).
**Tier:** **2-DB** (regression-prone, cross-coordinator ripple: energy_battery → energy_pool → EVSE + DP + NM; touches a shared primitive consumed by many decision sites; also folds together four hand-rolled gates whose thresholds MUST be preserved byte-for-byte on the fresh path).
**Mode:** planning only (read-only). Awaits plan review before build dispatch.
**Falsifiable invariant (state up front):**
> For every trust-decision-consuming power/SOC read in the Energy family, a numeric HA state whose `last_updated` is older than the site's configured `MAX_AGE_S` MUST be treated as **absent** (helper returns `None`), routing the consumer to its already-built fallback (LKG envelope, cloud fallback, `STALE_POWER` set, `blind_hold_active`). On the fresh path (age ≤ MAX_AGE_S, valid unit, in-range) the returned value MUST be **byte-identical** to today's read.

---

## Institutional context verified

### Design/rules read
- `CLAUDE.md` — Tier 2-DB triggers; Producer/Consumer rule; "Numbers get knobs" ladder; "Coincidental equality masks a concept split"; "Extend existing, never rebuild"; "Do the robust fix, not band-aid+card".
- `docs/QUALITY_CONTEXT.md` — Bug class **#7 stale data source** (frozen-valid numeric reads defeat consumers that only check unknown/unavailable) — this cycle is a systematic sweep of that class across the Energy read surface.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.5a — reserve verifiable backout knob (MAX_AGE_S=0 fire-axe); establishes the *"missing = go to fallback, never trust a stale value"* doctrine this cycle extends to the READ layer.

### Prior planning / memory pulled
- Memo `reference_ec_reserve_verifiable_backout_knob` — fire-axe precedent; the reserve gate ALREADY uses last_updated-age → None; the SOC/power reads never gained the equivalent.
- Memo `feedback_coincidental_equality_masks_concept_split` — informs why the four hand-rolled gates converged on 180s / 300s / 600s **by domain** and MUST NOT be silently unified into one number.
- Memo `feedback_do_robust_fix_not_bandaid_and_card` — supports operator's consolidate ruling over "extract helper first, migrate later".
- Memo `feedback_read_consumers_before_asserting_function` — direct authority for the Consumer check on every migrated site.
- v5.17.5 A1 review record — introduced `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600` (`energy_battery.py:882-910`); the extra-comment there IS the template for this cycle's per-site guard.
- v4.5.0 unit-consistency sweep — established `_read_power_w` as the single power reader; this cycle mirrors that pattern at the staleness layer.

### Producer AND Consumer surveyed (audit lines re-verified by grep in this session)

| # | Site (producer) | file:line | Current reject | Fresh-path consumers (trust) | Fallback that engages when helper returns `None` |
|---|---|---|---|---|---|
| 1 | `_read_power_w("solar_production")` via `solar_production_w` | `energy_battery.py:1572-1596`, called at `:1614` | unknown/unavailable only | LKG stamp at `:1618-1620`; excess-solar admit `energy_pool.py:1483`; strategy math | `solar_production_w_envelope()` at `:2287` — but its "envelope needed?" check is `live is None` (`:2300-2307`); today a frozen-valid solar poisons LKG AND defeats the envelope entry |
| 2 | `_read_power_w("net_power")` via `net_power_w` | `energy_battery.py:1628-1636` | unknown/unavailable only | grid-import cap, peak-import accounting, billing accumulator (docstring `:1631-1634`) | none — a frozen net_power silently mis-bills / mis-caps |
| 3 | `battery_power_w` inline | `energy_battery.py:1546-1570` | unknown/unavailable only | strategy math; NOT the same as `battery_power` display prop (`:1530`, kept for display) | none — a frozen battery power hides drain |
| 4 | PRIMARY `battery_soc` via `_get_state_float` | `energy_battery.py:785-795`, called at `:828` | unknown/unavailable only | LKG stamp at `:830-832`; divergence check `:834`; every downstream battery strategy consumer. **Highest-value site** — A1 (`:895-910`) only guards the cloud fallback. | three-tier resolver: LKG (`:838-842`) → cloud fallback (`:843-921`). Both **already exist** and today are dark on frozen primary. |

Existing hand-rolled gates (to be folded to route through the shared helper, thresholds preserved):

| Gate | file:line | Threshold | Behavior on stale |
|---|---|---|---|
| Cloud-SOC A1 | `energy_battery.py:891-906` | `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600` (`energy_const.py:326`) | return None |
| EVSE per-bay solar power | `energy_pool.py:4695-4708` | `SOLAR_POWER_FRESH_S=180` (`energy_const.py:974`) | add to `stale_power` set |
| Grid source (solar-follow) | `energy_pool.py:4406-4413` | `SOLAR_FOLLOW_GRID_FRESH_S=180` (`energy_const.py:975`) | return `(None, "stale")` |
| AC-kWh sensor | `sensor.py:12491-12507` | `AC_KWH_SENSOR_STALENESS_S` (hvac_const) | **display-only** `stale` attribute — `native_value` NOT gated |

**Consumer-check finding (design-binding):** `sensor.ura_energy_envoy_status.stale` is DISPLAY-ONLY — no decision reads it. The trust flag `envoy_available` IS trusted (`energy.py:3753` blind_hold DP; `energy_pool.py:571` EVSE guard; `:2934` NM alert) but is computed from SOC+storage_mode, **not solar production or net_power**. ∴ The fix MUST gate the READ (helper returns `None` → LKG envelope / fallback / stale_power engages). Adding another unconsumed staleness sensor would repeat the display-only failure mode.

### Grep prior-art results for proposed additions
- `_state_age_s` / `state_age_s` / `read_fresh` / `_read_state_fresh` — **NEW** (grepped `custom_components/`, no equivalent public helper; `energy_battery.py:891` and `energy_pool.py:4406` and `:4695` and `sensor.py:12494` are all site-local re-implementations of the same 5-line arithmetic).
- `DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S`, `DEFAULT_NET_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` — **NEW** (no existing constants for these reads; `DEFAULT_SOC_LKG_MAX_AGE_S`/`DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S` are LKG-tier / cloud-tier, NOT primary-read staleness). Rung 1 (module constants — safety knobs, review-gated) per "Numbers get knobs".

### Code locations surveyed end-to-end
- `energy_battery.py:770-925` (SOC resolver + A1 gate); `:1530-1636` (power readers + LKG stamp); `:2270-2320` (envelope + `stamped` gate).
- `energy_pool.py:565-580` (blind-guard predicate); `:1470-1500` (arb resume); `:4240-4413` (grid-follow freshness); `:4685-4710` (per-bay solar power freshness).
- `energy_const.py:300-340`, `:960-985` — MAX_AGE / FRESH_S constant family.
- `sensor.py:12395-12510` — AC-kWh display gate.
- `energy.py:3745-3765` — `envoy_available` consumer contract.

---

## Deliverables

### D1 — Add the shared helper (single source of truth)

Add two module-private helpers on `EnergyBatteryCoordinator` (co-located with `_get_state_float` at `energy_battery.py:785`, same coordinator that owns every downstream fallback — no new module, no cross-coordinator import surface):

- `_state_age_s(state) -> float | None` — returns `(now_utc − state.last_updated).total_seconds()`, or `None` if the state is missing, has no `last_updated`, or the stamp is naive (fail-closed per CF-8 precedent at `energy_pool.py:4402-4409`).
- `_read_fresh_power_w(entity_key, max_age_s) -> float | None` — supersedes `_read_power_w`: same unit-normalization, plus rejects when `_state_age_s(state)` is `None` OR `> max_age_s`. Preserves the exact fresh-path byte-identity (same float, same kW→W scaling).
- `_read_fresh_float(entity_id, max_age_s) -> float | None` — same for the non-unit-scaled SOC read (used by the primary-SOC site).

**Producer check:** the helper's only inputs are `hass.states.get(...)` and a constant; no new dependencies; no runtime writer. **Consumer check:** in D1 the helpers have zero consumers (added but not yet wired) — a builder mutation of the fresh-path branch MUST leave the suite green (D1 is neutral); a mutation of the stale-branch MUST fail a D2/D3/D4/D5 test (added below).

#### Acceptance
- **Verify:** helper module imports; no site calls it yet.
- **Test:** `test_state_age_s_missing_naive_fresh_stale` covers the four cases (None state, naive stamp, fresh, stale); `test_read_fresh_power_w_unit_scaling_preserved` proves fresh path byte-identical to `_read_power_w` at a range of stamps.
- **Live:** N/A (no wire-in yet).

### D2 — Migrate PRIMARY `battery_soc` (highest-value site)

Change `energy_battery.py:828` from `self._get_state_float(self._get_entity("battery_soc"))` to `self._read_fresh_float(self._get_entity("battery_soc"), DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S)`. **New const** `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S: Final = 300` in `energy_const.py` next to `DEFAULT_SOC_LKG_MAX_AGE_S:318` — matches LKG horizon (a stale primary should immediately hand off to LKG at the same age boundary, which is why they must be equal by design; document with a `# NOTE:` referencing the equality as intentional, not coincidental — Bug Class #63 counterweight).

When helper returns `None`, existing three-tier resolver at `:838-921` already runs (LKG → cloud); no other change needed.

#### Acceptance
- **Verify:** on stale primary + fresh LKG, `battery_soc` returns the LKG value (not the frozen primary); `_soc_source_last == "lkg"`.
- **Verify:** on stale primary + no LKG + fresh cloud fallback, `battery_soc` returns the cloud value; `_soc_source_last == "cloud_fallback"`.
- **Discriminating:** inject a frozen numeric primary with `last_updated` = now − 400s while a sibling entity shows `last_updated` = now − 5s → primary read returns `None`; the observed `_soc_source_last` MUST be `lkg` under fresh LKG (NOT `envoy`) and MUST be `cloud_fallback` when LKG is also expired (NOT `envoy`). A fix that failed to gate would still show `envoy`, which is a distinct observable.
- **Test:** `test_primary_soc_stale_falls_to_lkg`, `test_primary_soc_stale_no_lkg_falls_to_cloud`, `test_primary_soc_fresh_byte_identical`.
- **Neuter→RED:** deleting the `max_age_s` arg (routing back through `_get_state_float`) MUST fail `test_primary_soc_stale_falls_to_lkg`.
- **Live:** post-deploy, DB spot-check on `soc_source_last` transitions — expect zero `envoy` reads with source-entity `last_updated` age > 300s in the sensor's `attributes`.

### D3 — Migrate `solar_production_w`

Change the call at `energy_battery.py:1614` from `self._read_power_w("solar_production")` to `self._read_fresh_power_w("solar_production", DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S)`. **New const** `DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S: Final = 180` in `energy_const.py` adjacent to `SOLAR_POWER_FRESH_S:974` (same horizon by intent — Envoy production sensor and per-bay Emporia both settle at ~2× p90; document the equality with a `# NOTE:` and keep the constants separate so a future producer-side tuning cannot silently shift EVSE bay accounting).

When helper returns `None`, the existing envelope path at `:2287` MUST engage. Fix the envelope's entry check at `:2300-2307` — today it reads *"return None when live solar is currently available"* by testing `_read_power_w(...) is not None`; this cycle changes the same call to the fresh reader, so the check remains coherent (stale-live ⇒ helper `None` ⇒ envelope proceeds). Verify by construction; no logic change to the envelope itself.

#### Acceptance
- **Verify:** with the Envoy solar sensor frozen at 0 W for > 180s and Envoy otherwise responsive, the LKG stamp at `:1618` does NOT tick (last_updated of `_solar_prod_lkg_at` unchanged); the envelope is queried and (if LKG-fresh) returns a tier.
- **Discriminating:** inject a frozen-0 solar sensor (age = 200s) while `sensor.envoy_..._battery` shows age = 5s → `solar_production_w` returns `None` AND `_solar_prod_lkg_w` is unchanged. A fix that failed to gate would re-stamp `_solar_prod_lkg_w = 0.0` and `_solar_prod_lkg_at = now` — a distinct observable (LKG polluted to 0).
- **Test:** `test_solar_stale_does_not_poison_lkg`, `test_solar_stale_engages_envelope`, `test_solar_fresh_byte_identical`, `test_excess_solar_admit_uses_stamped_not_frozen` (against `energy_pool.py:1483`).
- **Neuter→RED:** delete the fresh-reader migration at `:1614` and re-run — `test_solar_stale_does_not_poison_lkg` MUST fail.
- **Live:** post-deploy, verify `_solar_prod_lkg_w` monotonicity (no drop-to-0 stamp in the persisted blob) across a sample Envoy blind window; NM `blind_hold` alert path unchanged (bytes-identical `envoy_available`).

### D4 — Migrate `net_power_w` and inline `battery_power_w`

- Change `energy_battery.py:1636` to `self._read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S)`. **New const** `DEFAULT_NET_POWER_MAX_AGE_S: Final = 180` (same reason as solar: Envoy CT).
- Refactor `battery_power_w` at `:1546-1570` to call `_read_fresh_power_w("battery_power", DEFAULT_BATTERY_POWER_MAX_AGE_S)` with sign-flip applied after (keeping the sign-flip contract explicit at the call site, not in the helper). **New const** `DEFAULT_BATTERY_POWER_MAX_AGE_S: Final = 180`.
- **Do NOT** change the display-only `battery_power` prop at `:1530` (keeps backward-compat display behavior; docstring already declares it raw-for-display).

#### Acceptance
- **Test:** `test_net_power_stale_returns_none`, `test_battery_power_w_stale_returns_none_sign_preserved`, `test_battery_power_display_unchanged` (prop `battery_power` at `:1530` still returns frozen value for backward compat).
- **Discriminating:** for battery_power_w, inject frozen positive value at age 200s while battery display shows age 5s (via `battery_power` prop) → `battery_power_w` returns `None`, `battery_power` returns the frozen value. Confirms the sign-flip contract preserved AND the display/decision paths diverged as designed.
- **Neuter→RED:** per site.
- **Live:** peak-import accounting counter unaffected on a fresh 24h window; on the next observed Envoy CT stall > 180s, the counter freezes (does not integrate the stale value) — verified against a recorder query on the CT entity's `last_updated` vs the sensor tick.

### D5 — Fold the 4 hand-rolled gates through the helper (de-dup, thresholds preserved)

For each existing gate, replace the site-local age arithmetic with a call to `_state_age_s(state)`. Site behavior on stale is **unchanged** — the same branch fires with the same threshold.

- `energy_battery.py:891-910` (cloud-SOC A1) — call `_state_age_s(st)` in place of the manual `(now - lu).total_seconds()` at `:895`; keep the `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600` comparison and the `fallback_stale_reject` branch identical.
- `energy_pool.py:4695-4708` (EVSE per-bay) — call `_state_age_s` (imported from `energy_battery` as a staticmethod, OR lifted to a module-level util in `energy_battery.py` and re-imported — builder chooses the smaller diff). Preserve `SOLAR_POWER_FRESH_S=180` and the `stale_power` set add; preserve CF-8 fail-closed on naive/missing.
- `energy_pool.py:4406-4413` (grid-follow) — same, preserving `SOLAR_FOLLOW_GRID_FRESH_S=180` and `(None, "stale")` return; preserve CF-8 fail-closed.
- `sensor.py:12491-12507` (AC-kWh **display-only**) — call `_state_age_s(state)` to compute `age_s`; **DO NOT** gate `native_value` on staleness in this cycle (that would change behavior of a display sensor; carded separately if desired). This is a pure de-dup of arithmetic — behavior byte-identical, including the `stale = True` default when age unknown.

#### Acceptance (D5)
- **Test:** for each site, `test_<site>_helper_call_preserves_threshold` — inject state at age = threshold − 1, threshold + 1, missing `last_updated`, naive `last_updated`; assert current-behavior branch fires in all 4 cases.
- **Neuter→RED:** in each site, replace the helper call with a hard-coded `age = 0.0` — the corresponding threshold test MUST fail.
- **Live:** `SOLAR_FOLLOW`/EVSE debug counters (existing `stale_power` set, `(None, "stale")` grid returns) show the same event rates in the 24h post-deploy window as the 24h pre-deploy window (±10%). NM alert path unchanged (bytes-identical `envoy_available`, bytes-identical `blind_hold_active`).

### D6 — Pre/post row-rate snapshot (Tier 2-DB requirement)

Before deploy, capture pre-deploy rates for:
- `_soc_source_last` distribution over the last 24h (from any coordinator-published attribute / log grep).
- Envoy anomaly rows by `(coordinator, severity, type)` (Tier 2-DB standing snapshot).
- Any `stale_power` / `(None, "stale")` counter exposed by EVSE / solar-follow.

Post-deploy comparison ±25% at 24h post-restart (per Tier 2-DB policy).

---

## Non-goals (explicit)

- **No new unconsumed staleness sensor.** Consumer-check ruling: gate the READ, do not publish another display-only `stale` flag.
- **No threshold changes to any existing gate.** `SOLAR_POWER_FRESH_S=180`, `SOLAR_FOLLOW_GRID_FRESH_S=180`, `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600`, `AC_KWH_SENSOR_STALENESS_S` — untouched. The four new consts (solar / net / batt-power / primary-SOC) are additions.
- **No change to `envoy_available` composition** (still SOC + storage_mode based); this cycle only makes the underlying reads stale-safe.
- **No periodic reload / probe / watchdog** to force freshness. Passive read-time gate only.
- **No change to display props** (`battery_power` at `:1530`; AC-kWh `native_value`).
- **No unification of the four hand-rolled thresholds into one number.** Bug Class #63 counterweight: equal-in-common-config ≠ same concept.
- **No migration of non-Energy staleness sites** (BLE room-mapping, presence LKG, tracker-stale) — out of scope; carded separately if the pattern proves worth generalizing.

---

## Tier 2-DB review plan (3 framings + Live)

- **Review A — data integrity / read-layer correctness.** Byte-identity of the fresh path across all 4 migrated reads (D2/D3/D4) via mutation-anchored source drills. Verify `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S == DEFAULT_SOC_LKG_MAX_AGE_S` equality is intentional and documented. Check LKG stamp semantics preserved (no accidental stamp on `None`).
- **Review B — signal-chain / cross-coordinator integration.** For each consumer (`energy_pool.py:1483` excess-solar admit; battery strategy; billing accumulator; `energy.py:3753` blind_hold; NM alert `:2934`) trace end-to-end that a stale read at the producer routes to the correct fallback with no double-emit, no signal drop, and no restart divergence. Enumerate the four folded gates and prove each site's on-stale branch is byte-identical post-refactor.
- **Review C — new surface / test authority.** Every new const round-trips via `energy_const.py` (rung 1); every acceptance test drives production code (no INSERT/monkeypatch shortcuts); the discriminating tests actually discriminate (fix-vs-nothing AND fix-vs-plausible-wrong-fix, per `feedback_verification_needs_disjoint_framings`).
- **Review D — Live Validation, post-restart.** Recorder query: for each migrated read, sample a 6h window and confirm zero decision-path consumers observed `source_last == envoy` with source `last_updated` age > MAX_AGE_S. Row-rate snapshot compared vs pre-deploy ±25%. README `Validated <date>` table written back before cycle close.

---

## Files to change

- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — add helpers (D1); migrate 4 reads (D2/D3/D4); fold A1 gate (D5).
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` — fold 2 gates (D5).
- `custom_components/universal_room_automation/sensor.py` — fold 1 display gate (D5, arithmetic only).
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — 4 new `DEFAULT_*_MAX_AGE_S` constants with rationale comments.
- `quality/tests/` — new test module `test_shared_power_read_staleness.py` covering D1-D5 acceptance.
- `docs/readmes/README_v<next>.md` — pre-deploy prospective, post-restart validation table.

## Risks & mitigations
- **Test-file collision** — coordinate with any concurrent Energy cycle via worktree isolation (memo `feedback_worktree_isolation_all_agents`); serialise suite runs (memo `feedback_serialise_suite_runs_across_agents`).
- **`.pyc` staleness during mutation drills** — enforce `PYTHONDONTWRITEBYTECODE=1` + `find … -name __pycache__ -delete` before each drill (memo `feedback_mutation_verification_pycache_staleness`).
- **Silent threshold drift** — Review A explicit checklist to diff all four preserved constants pre/post.

## Open questions for operator (not blocking planning)
- AC-kWh `native_value` staleness gate: card a follow-up to actually gate the read (today only the attribute is set), or leave the display sensor alone? (Non-goal in this cycle either way.)
