# PLANNING — Carrier (cloud-only) stale-detect → bounded reload

Card: `CARRIER-STALE-POLL-REFRESH-1` (consolidated home). Consolidates the Envoy-modeled
resilience framing + subsumes `HVAC-GOVERNED-RESTORE-FAIL-TAIL-1`. Authored by ura-planner
(read-only investigation), 2026-09-09. **Plan-review required before build (Tier 2+ prior-art
scan done inline).**

## Defect
`ha_carrier` (cloud-only) reports `hvac_action=idle` while the compressor draws kW for episodes
up to 108 min; only a config-entry RELOAD clears it (operator-observed). `update_entity` reuses
the stale client/session so it likely won't clear it — reload rebuilds the carrier_api client.
Ground truth = SPAN zone kW. The ramp cycle already routes around this; this fix restores every
OTHER HVAC consumer (preset apply, dwell/vacancy, restore-verify).

## Model: Envoy machinery, minus the complexity
- REUSE the *shape* of `energy.py:2939 _track_envoy_availability` (per-cycle miss → escalating
  counter → NM on Nth → recovery clears) and the named-knob staleness bound + kill-switch of
  `energy_write_verify.py:219 is_reserve_verifiable` / `energy_const.py:1606` (MAX_AGE_S, 0=off).
- DO NOT build local↔cloud reconciliation (Envoy dual-source) — Carrier is cloud-only. This is
  the operator's "much simpler" instruction.

## Falsifiable invariant
Under a Carrier stale-episode, URA issues EXACTLY ONE `homeassistant.reload_config_entry` on the
`ha_carrier` entry within T_RESPOND, iff last reload ≥ T_COOLDOWN ago AND today's count < N_MAX.
In no other condition is any reload issued. NEVER the URA parent entry.

## Deliverables
- **D0 (probe, recommended):** run the `update_entity` remediation leg live once during the next
  stale episode (Probe C confirmed the defect but never ran this leg) — settles cheap-vs-costly.
  If update_entity clears it, D2's action becomes update_entity with reload as second-line.
- **D1 — detection:** `_check_carrier_freshness()` in hvac.py, per decision tick. Signal =
  `last_reported` age (NOT last_changed — durable lesson from HVAC-STALE-ACTUATOR-FRESHNESS-1) >
  CONF_HVAC_CARRIER_STALE_MAX_AGE_S (900s), excluding unavailable/unknown. Optional ANDed
  SPAN-kW blind-corroboration (hvac_action=idle while zone kW>threshold) — the discriminator that
  avoids reloading a legitimately quiet-idle zone.
- **D2 — bounded reload:** `_reload_ha_carrier_entry()`. Resolve the single ha_carrier entry
  (0 or 2+ → NM + no reload); guards in order: cooldown, per-day cap, kill-switch (cooldown=0),
  asyncio.Lock; call reload_config_entry(entry_id); NM info. Restart-safe counters.
- **D3 — discharge/trip-wire:** if still stale 2 ticks after a reload → NM high
  (carrier_reload_ineffective), suppress further reloads for the day, diagnostic row. (No-soak:
  observable failure wired to NM.)
- **D4 — subsume restore-fail tail:** DB join of `ac_ramp_events`(immediate=0 AND delayed=0)
  against reload windows; if the ~4% tail sits in reload-adjacency → resolve
  HVAC-GOVERNED-RESTORE-FAIL-TAIL-1 as subsumed (card residual).

## Knob ladder (Numbers-Get-Knobs)
| Knob | Default | Rung |
|---|---|---|
| CONF_HVAC_CARRIER_STALE_MAX_AGE_S | 900 | module const |
| CONF_HVAC_CARRIER_STALE_REQUIRE_BLIND_CORROBORATION | True | options bool |
| CONF_HVAC_CARRIER_RELOAD_COOLDOWN_S | 1800 (0=kill) | module const |
| CONF_HVAC_CARRIER_RELOAD_MAX_PER_DAY | 6 | module const |
| CONF_HVAC_CARRIER_POST_RELOAD_GRACE_TICKS | 2 | module const |

## Non-goals
Never reload URA parent entry; no update_entity as first-line (pending D0); no local/cloud
reconciliation; ramp detection stays independent; do not ship without D3.

## Review tier
Tier 2-DB (3 framing-disjoint: A correctness/edge, B async/lifecycle/reload-safety,
C cross-coordinator ripple + trip-wire). Operator checkpoint before deploy (cloud reload =
high live blast radius). Pre-review baseline tag mandatory.

## Open questions for operator
1. Run the D0 update_entity probe first (~1 episode, ≤6h), or ship reload-first on the mechanistic
   argument?
2. Blind-corroboration default True requires a SPAN zone kW sensor per zone — confirm all 3 zones
   have one (plan-review grep).
3. Reload lock: per-entry (now) vs coordinator-wide cloud-reload lock (broader, future)?

_Full grounding (file:line REUSE/NEW, prior-art scan) in the ura-planner investigation; key refs:
energy.py:842/2939, energy_write_verify.py:219, energy_const.py:1606, energy_pool.py:1203,
hvac_const.py:560-600, database.py:1720-1756, PLANNING_ac_ramp_pipeline_hardening.md:664,
PLANNING_reconcile_on_return.md:924._

## Operator resolutions (2026-09-09) — plan now READY to build
- **Q1 (D0 probe): SKIP.** Enough probing — Probe C confirmed the defect and the operator has
  empirically established a reload refreshes it. Ship reload-first (mechanistic argument holds).
- **Q2 (SPAN zone kW): VERIFIED present**, not asked — `sensor.span_left_furnace_*`,
  `span_panel_ac_2/ac_3` circuits exist; blind-corroboration viable. Pin the exact zone→circuit
  map at build.
- **Q3 (lock scope): per-entry** — there is no real tradeoff; a per-entry asyncio.Lock preventing
  overlapping reloads is sufficient. (Dropped as a decision.)
- **Reloads/day (operator asked "how many"): default 4.** A healthy day is 0; hitting 4 means the
  reload is NOT holding → that is itself the signal, so the D3 trip-wire escalates (NM high,
  suppress further reloads for the day) rather than reloading a 5th time. Config-flow tunable
  (module const `CONF_HVAC_CARRIER_RELOAD_MAX_PER_DAY=4`, kill-switch via cooldown=0).
- **Observability/control design (operator asked):** automatic + invisible in normal operation.
  CONTROL = config-flow options (max-age, cooldown, max/day, corroboration toggle, kill-switch).
  OBSERVABILITY = (1) diagnostic `sensor.ura_hvac_carrier_freshness` (state = worst-zone age or
  stale-count; attributes = per-zone last_reported age + stale flag), (2) reload events written to
  `ura_activity_log`, (3) NM info on each reload / NM high on reload-ineffective. So: silent when
  healthy, but a sensor + activity trail + alerts when it acts.
