# Backlog — candidate small cycles (filed 2026-07-26)

Each item: **why** (the problem), **benefit** (what fixing buys), **threshold** (the
marginal-benefit trigger that justifies doing it — per CLAUDE.md "Marginal-Benefit
Decomposition"), and a **tier** estimate. Filed, not scheduled. Ordered by likely value.

---

### 1. mmWave phantom occupancy → HVAC waste (Master Bedroom + Kitchen)
- **Why:** mmWave presence alone holds a room "occupied" even with PIR motion dead for hours while a comfort fan runs (fan airflow / mmWave over-sensitivity). Verified 2026-07-26: Master Bedroom mmWave flapping + PIR off 6 h held zone_1 occupied → Study B/Bryant thermostat **cooled an empty Master Suite**. Kitchen shows the same via `binary_sensor.mmwave_lux_wifi_esphome_kitchen_presence`. URA has fan-interference machinery (v4.7.20/22) but it isn't engaging here.
- **Benefit:** stops cooling/heating genuinely-empty zones (real $), and makes census/room-tiles accurate. This is the highest-$ item on the list.
- **Threshold:** do it once we've confirmed it recurs whenever fans run (it will) OR measure the wasted AC-runtime on empty zones over a few days and it's non-trivial. Operator deferred the root fix 2026-07-26 — revisit when the empty-zone cooling recurs or before peak-cost season.
- **Tier:** 2 (presence↔HVAC seam). Fix shape: mmWave-alone must not hold occupancy when PIR is dead N min AND a comfort fan is running (require PIR/BLE corroboration, or fan-interference discount).

### 2. Person-tracker hygiene + user_id auto-association
- **Why:** a stale/duplicate or stationary tracker can hold a person "home" indefinitely (HA person = "any tracker home ⇒ home"). Ezinne's `zinny_s_iphone_15` did this for 3+ days; also her user_id auto-associates devices (`iphone`, `zinnysmac`) beyond the explicit list.
- **Benefit:** one dead/stationary device can't hold the house occupied (which cascades to HVAC via person_zone_map).
- **Threshold:** do it if it recurs for another person, or bundle when the Ezinne tracker is re-added. Low effort.
- **Tier:** 1. (Ezinne mitigated live 2026-07-26 via `person/update` prune — reversible.)

### 3. Census durable face-freshness fix
- **Why:** the census trusts a Frigate `last_camera` sensor's `last_changed` as a freshness clock, but that sensor flaps `unavailable⇄value` (re-stamping last_changed), so a departed person's face never ages out. v5.31.0 shipped a person-trust cross-check (drops face when `person.<slug>=not_home`) as the robust symptom-killer; this is the deeper root fix.
- **Benefit:** correct even for a guest/unenrolled face, and independent of the person-state gate.
- **Threshold:** only if the cross-check proves insufficient (e.g. a guest face latches), or the Frigate flapping is fixed at source making this moot.
- **Tier:** 1–2.

### 4. Override "fewer firings" (AC nudge)
- **Why:** the AC nudge fires ~21×/night even at setpoint on an empty house (intentional per hotfix v4.7.16.2 — catches variable-speed modulation waste). v5.31.0 B1/B2 stopped the false override-count + preset churn.
- **Benefit:** less thermostat actuation/wear if the nudge itself is judged unnecessary when unoccupied.
- **Threshold:** **only if H6 post-v5.31.0 shows the loop persists** on an empty overnight. If B1 broke the loop (expected), skip. Reversing the overshoot gap is a policy change, not a bug fix.
- **Tier:** 2-DB (energy semantics + EC ripple). Options: promote `AC_NUDGE_OVERSHOOT_GAP` to a per-zone live knob, or an occupancy gate.

### 5. Fan actuation shared-layer extraction (DOC 2 — already filed)
- **Why:** manual-off cooldown / hysteresis / min-runtime / arbitration are implemented independently in the room-tier and HVAC-tier fan paths → behavior drifts (the whole 2026-07-26 fan saga).
- **Benefit:** one shared `FanActuator` both tiers call → consistency by construction.
- **Threshold:** when next touching fan logic, or if another tier-inconsistency bug appears. Not worth the blast radius on its own yet.
- **Tier:** 3 (shared primitive, presence↔HVAC). Plan: `docs/planning/PLANNING_fan_actuation_shared_layer.md`.

### 6. D3 outdoor-temp envelope fix-forward
- **Why:** LKG D3 ships as a no-op (CRIT-1: producer orphaned) → freeze protection has no robustness to a stale/dead outdoor sensor. Quarantined (`stash@{0}` / `build/lkg-d3`).
- **Benefit:** freeze floor survives a weather-feed outage (pipe safety in an Austin/Uri climate).
- **Threshold:** before the next cold snap / winter. Decision already ratified: persist ≤12 h → notify+release, secondary-provider precedence.
- **Tier:** 3.

### 7. Energy-savings sensor unification (audit in flight)
- **Why:** multiple inconsistent savings/avoided/cost sensors; "cost saved" is arbitrage-only and misses **time-shifted-joules** (what energy would've cost at peak with no solar/battery); no billing-cycle scope. (Planner filing `PLANNING_energy_savings_unification.md`.)
- **Benefit:** one accurate savings family — day / billing-cycle / lifetime — with correct peak-avoidance value.
- **Threshold:** do when the audit doc lands + operator prioritizes; it's a clarity/accuracy win, not a safety issue.
- **Tier:** 2-DB.

### 8. QUALITY_CONTEXT.md bug-class additions
- **Why:** two classes recurred this session — **cross-coordinator re-assertion** (one coordinator's guard defeated by another writer, e.g. reconciler vs fan cooldown) and **grep-only-test overstates coverage**.
- **Benefit:** institutional memory so future builds anticipate them.
- **Threshold:** trivial — do anytime (doc-only).
- **Tier:** 0 (docs).

### 9. Baseline test hygiene
- **Why:** ~44/14 pre-existing full-suite failures are `test_freeze_floor` cross-test ordering pollution (25/25 in isolation) — "red" is currently noise, obscuring real signal.
- **Benefit:** a clean suite gate so deploy.sh's test step is meaningful.
- **Threshold:** before a deploy where we want a hard green gate; or when a real failure hides in the noise.
- **Tier:** 1 (xfail-quarantine the pollution set).

### 10. Small / display
- **`wifi_guest_floor` attribute** reads 2 on an empty house (display-only, does NOT feed the count) — tune the guest-VLAN hostname/recency filter if the *attribute* should read 0. **Threshold:** only if it confuses on the dashboard. Tier 1.
- **Dashboard ura-v8:** weather animation assets (needs operator to drop `weather-bg.min.js`+`cloud.png` in `config/www/`); `data.zones` vs `options.zones` reconcile (Zone Manager); PWA `automation_mode` inert-knob (wire or hide — flagged G4).
- **`ac_kwh_avoided` naming** — folded into #7 (energy unification).
</content>
