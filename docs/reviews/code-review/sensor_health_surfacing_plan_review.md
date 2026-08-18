# Plan Review — Sensor Health Surfacing (chatter detector + NM replace hook + unavailable-sensor surfacing)

- **Plan under review:** `docs/planning/PLANNING_sensor_health_surfacing.md`
- **Tier:** 2 (feature cycle) — one adversarial plan review before build
- **Framing:** completeness of the load-bearing REUSED claims + falsifiability of §2 invariant + consumer-enumeration integrity + non-goals
- **Verdict:** **PLAN-READY** (three LOW clarifications to fold into the plan or the builder brief; none blocking)

---

## Independent verification of the two load-bearing REUSED claims

The plan's Tier-2 justification (additive, no new sensor, no new table, no cross-coordinator ripple) COLLAPSES if either of the two REUSE anchors is wrong. I re-verified both from source rather than trusting the ledger.

### Load-bearing REUSE 1 — `UnavailableEntitiesSensor` can carry a `reason="chattering"` branch for INPUT sensors

**VERIFIED — reuse is clean.**

- `sensor.py:1677` `UnavailableEntitiesSensor` is the correct entity.
- `_iter_configured()` (`sensor.py:1774-1794`) yields BOTH input-sensor and actuator entities, with `category` in {`"sensor"`, `"actuator"`}. Input categories iterated include `_SENSOR_LIST_KEYS = ("motion_sensors", "presence_sensors", "occupancy_sensors", "power_sensors")` and single keys `("temperature_sensor", "humidity_sensor", "illuminance_sensor")`.
- **Naming disambiguation (informational, folded into LOW-1 below):** the config key for mmWave is literally `"presence_sensors"` — `const.py:433` defines `CONF_MMWAVE_SENSORS: Final = "presence_sensors"` with the comment "blueprint calls them presence_sensors". So `_iter_configured` already covers the plan's `motion ∪ mmwave ∪ occupancy` candidate set. The reuse WORKS, but the plan writes "mmwave_sensors" as a config key in several places and the builder must remember to read `config["presence_sensors"]`.
- `_unavailable_details()` (`sensor.py:1821-1868`) already carries an OVERRIDE branch for flapping actuators (`is_flapping = eid in flapping_ids`) with `reason="flapping"`, `transition_count`, `since`. The plan's proposed chatter branch (`is_chattering = eid in chattering_ids` → `reason="chattering"`, `transition_count`, `since`) is a **byte-for-byte symmetric extension** of the existing flapping branch. The key additive change vs. the flapping branch is that `is_chattering` must OR into the "do not `continue`" guard: `if not is_unavail and not is_flapping and not is_chattering: continue`. That is exactly what the plan D3 body specifies.
- Chattering INPUT sensors will correctly land in `unavailable_sensors` (not `unavailable_actuators`) because `category` from `_iter_configured` is `"sensor"` for the motion/presence/occupancy lists.

**Not a broken reuse.** `UnavailableEntitiesSensor` iterates configured INPUT sensors on every attribute read — a chattering PIR / mmWave / occupancy binary sensor WILL be seen.

### Load-bearing REUSE 2 — `fire_stuck_signal(kind="chatter", ..., remedy=...)` + per-day latch + `_write_stuck_anomaly` + `fire_stuck_signal_recovered` discharge

**VERIFIED — reuse is clean.**

- `fire_stuck_signal` (`_stuck_signal_nm.py:167-262`) signature accepts `kind: str` — **free-form**, no enum registration. `kind="chatter"` needs no code change beyond the plan's D2 call site.
- `remedy: str = ""` is present in the signature (line 173) and is appended to the NM message body as `f"{message}\n\nSuggested remedy: {remedy}"` only when non-empty (`:225-226`). The plan's remedy string (`"Replace sensor {entity_id} — chatter pattern indicates hardware fault..."`) will render correctly.
- Per-day latch (`_LATCHES` at `:47`; key `(kind, tuple(key))`; keyed by ISO day at `:190`) coalesces to exactly one dispatch per `(kind, key)` per calendar day. `_prune_stale_latches` (`:100`) is the backstop. All operate independently of `kind` string.
- `_write_stuck_anomaly` (`:162` in the plan's citation; observed persist call at `:246-252`) is invoked from `fire_stuck_signal` under a swallowing `try/except` so a DB write failure does not block the NM path. `anomaly_type='stuck_signal'` with `json_extract(payload,'$.kind')='chatter'` (the plan's D2 live-validation SELECT) is a legitimate query shape.
- `fire_stuck_signal_recovered` (`:267`) confirmed to clear the latch — `_LATCHES.pop(latch_key, None)` at `:288` AND `:293`. The plan's "next-day flap re-notifies immediately" claim is correct.
- `STUCK_SIGNAL_NM_HAZARD_TYPE = "stuck_signal"` (`const.py:3778`) — the plan's "sub-classification by `kind`" claim is verified. The kind list is a **comment** at `const.py:3773-3776`; appending `chatter` is a doc-only change.

**Not a broken reuse.** The NM path accepts `kind="chatter"` with no plumbing changes.

---

## Complement-not-duplicate verification (against `_detect_duty_cycle_stuck`)

Verified from `coordinator.py:1584-1770`:

- D2's candidate set is `(mmwave_sensors + occupancy_sensors)` — **PIRs (motion_sensors) are explicitly excluded as candidates.** The docstring at `:1602-1606` says so directly ("Motion sensors themselves are NOT candidates — PIR is our corroboration source"). The plan's claim (§1.1 row 8 and §3 D1 step 1) is verified.
- D2's stuck rule requires the on-ratio to exceed `CONF_STUCK_SENSOR_DUTYCYCLE_PCT` (default 0.85). A 50/50 oscillator (Garage B: 3,769 off / 3,765 on in 24h) has on-ratio ≈ 0.5 → never trips D2. Chatter's transition-rate rule (transitions_per_min > 2.0) trips at rate ≈ 5.2/min. **Genuine complement — not a duplicate.**
- The 2026-08-09 incident replay premise (`_detect_duty_cycle_stuck` returns ∅ on the ratgdo shape) is therefore structurally guaranteed: on-ratio ≈ 0.5 cannot exceed 0.85, and it is not clear from the plan which CONF bucket ratgdo actually lives in (see LOW-2). **Regardless** of which bucket, the complement holds — if in `motion_sensors`, D2 excludes it as a candidate; if in `presence_sensors`/`occupancy_sensors`, the on-ratio math excludes it.

---

## Self-corroboration hole — closed by design

§3 D1 step 6: "no *other* (different `entity_id`) candidate produced ≥1 transition in the same window → mark chattering. (Own-transitions do not corroborate.)" This directly addresses the `INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md` §3.2 warning ("the anchor is the broken thing"). A chattering PIR cannot self-clear because its own transitions are excluded from the corroboration count. **Sound.**

The plan's §1.1 row 8 ("must not count the candidate's own transitions toward corroboration") and the falsifiable invariant in §2 (independent = "different-entity-id") are consistent.

---

## Falsifiability check on §2 invariant

The invariant names the exact observable: `sensor.<room>_unavailable_entities.attributes.details` with `reason == "chattering"` AND exactly one `stuck_signal` NM per calendar day with `kind == "chatter"` and non-empty `remedy` naming the entity. Both surfaces are queryable at runtime (HA state read; `anomaly_log` SELECT). The converse clause ("corroborated MUST NOT appear") gives the discriminator. **Falsifiable.**

Reviewer D territory: the invariant's "any legal room configuration" clause covers the incident shape (single-member motion/presence/occupancy list with no siblings). No obvious escape hatch.

---

## Consumer enumeration — verified exhaustive

- `_chattering_entities`: read only by `UnavailableEntitiesSensor._unavailable_details` (D3). Display-only. No trust-decision code path. `grep -r _chattering_entities custom_components/` currently returns 0 hits (as expected — the field does not exist yet); after build, the only reader must remain `sensor.py`.
- `sensor.<room>_unavailable_entities`: I confirmed via a quick grep of `custom_components/` that no automation-logic code reads `.details[*].reason` for a trust decision; the attribute is diagnostic-category, disabled-by-default. Adding `reason="chattering"` rows is purely additive to Lovelace / PWA consumers.
- `fire_stuck_signal(kind="chatter", ...)` fans out via NotificationManager per NM Cycle A routing — no new pipeline. `anomaly_log` gets a per-day-latched row via `_write_stuck_anomaly`; no write-flood risk.

Plan §5 accurately maps producer to consumers.

---

## Knob ladder audit (§4)

All rung 1 (module constants) justified:

- `CHATTER_WINDOW_MIN=60`, `CHATTER_MIN_TICKS=20` — sibling to `DEFAULT_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN` and `DEFAULT_STUCK_SENSOR_DUTYCYCLE_MIN_TICKS` (`const.py`, defaults 60 and 20). Consistent with the "detection-quality knob = rung 1" heuristic.
- `CHATTER_MIN_TRANSITIONS_PER_MIN=2.0` — headroom vs. incident (~5.2/min) is 2.6×. Justification for the specific value is present; a busier hallway PIR that legitimately exceeds 2/min will be corroborated by a sibling and therefore returns ∅.
- `CHATTER_RECOVERY_QUIET_WINDOW_MIN=60` — symmetric with detection window.
- `CHATTER_DETECTOR_ENABLED=True` — rung-1 kill switch with byte-identical semantics documented ("`False` → `_detect_chatter` returns `set()` immediately, `_chattering_entities` stays empty, D3 surfaces nothing, D2 emits nothing"). Sibling of `STUCK_EXCLUSION_ENABLED`.
- `CONF_STUCK_SIGNAL_NM_ENABLED` reuse silences ALL stuck_signal NM including the new `kind="chatter"` — verified at `_stuck_signal_nm.py:190` (`_kill_switch_on(hass)` gate covers all kinds).

**Kill-switch is properly documented; no drift risk.**

---

## Test-discrimination audit (§3 acceptance criteria)

- D1: `test_chatter_detector_flags_oscillator` vs. `test_chatter_detector_ignores_corroborated` — the OSCILLATOR-alone-vs-oscillator-with-corroborator pair genuinely discriminates (identical oscillator, different sibling activity, opposite verdicts).
- D1: `test_chatter_detector_own_transitions_do_not_corroborate` — directly kills the anchor-is-broken failure mode.
- D1: `test_chatter_detector_replay_garage_b_incident_2026_08_09` — pairs with an assertion that `_detect_duty_cycle_stuck` returns ∅ on the SAME fixture. That is the correct complement proof.
- D2: `test_chatter_nm_kill_switch_silences_only_nm` correctly separates detection from notification (i.e. `_chattering_entities` still populated with kill switch off).
- D3: `test_unavailable_entities_sensor_no_chatter_when_set_empty` is the required discriminator against always-emit false positives.
- D4: wire-in drill uses source mutation for the surfacing branch and monkey-patch for the tick-site — matches `feedback_hollow_test_anchors.md` and `feedback_mutation_verification_pycache_staleness.md`.

**Tests discriminate. No always-pass sentinels.**

---

## Non-goals (§6) — verified explicit and correct

1. No occupancy exclusion — correct. Chatter without corroboration might still be a hyper-sensitive real sensor; the plan draws the right blast-radius line (notify-only).
2. No new DB table — `anomaly_log` via `_write_stuck_anomaly` handles it. Trigger to revisit stated.
3. No house-level aggregator sensor — correct, room-level is the natural surface.
4. Not the signal_trust_ledger migration — respects "Extraction, not invention".
5. Not actuator chatter — D2.11 handles actuator flap quarantine with different semantics.
6. No config-flow field — rung-1 discipline preserved.

---

## Findings

### LOW-1 — Naming disambiguation: mmwave list lives under key `"presence_sensors"`

The plan repeatedly references "mmwave_sensors" as if it were a config key (e.g. §2 invariant "any legal `CONF_MOTION_SENSORS / _MMWAVE_SENSORS / _OCCUPANCY_SENSORS` combination", §3 D1 signature `_detect_chatter(self, now, motion, mmwave, occupancy, room_name)`, §7 files-changed context). The constant `CONF_MMWAVE_SENSORS` is defined at `const.py:433` as the string `"presence_sensors"` (blueprint historical naming). This is not wrong — D2 uses the same convention — but the builder brief should call out that `config["presence_sensors"]` is the read to use, and any candidate-set diagnostic log lines should render both the internal name and the config key to avoid confusion in operator debugging.

**Fold-in:** add a one-line note in §3 D1 or §7 explicitly stating "candidate set is `motion_sensors ∪ presence_sensors ∪ occupancy_sensors` (config keys — `CONF_MMWAVE_SENSORS = 'presence_sensors'`)".

### LOW-2 — Ratgdo bucket unspecified in incident replay premise

The plan's D1 incident-replay acceptance criterion feeds "the Garage B 24 h recorder shape (3,769 off / 3,765 on, no other room sensors)" and asserts the detector returns `{ratgdo_entity_id}`. `grep ratgdo custom_components/` returns nothing (the ratgdo integration is external to URA). The incident memo does not state WHICH CONF list ratgdo lives in for Garage B.

The complement claim holds under EITHER hypothesis (if ratgdo is in `motion_sensors`, D2 excludes it as a candidate; if in `presence_sensors`/`occupancy_sensors`, its ~50% duty cannot exceed 0.85). But the chatter detector only sees ratgdo if it is in one of `motion_sensors ∪ presence_sensors ∪ occupancy_sensors` — if the operator wired it into `power_sensors` or into a bespoke door-sensor list, the incident replay will falsely PASS (`_detect_chatter` returns ∅ because the entity is not in the candidate set) and D3 will falsely SURFACE (because `_iter_configured` yields `power_sensors` under `category="sensor"`). Neither behavior would represent a real chatter flag.

**Fold-in:** before build dispatch, verify the Garage B room config against the live `.storage/core.config_entries` and pin the CONF bucket in the incident-replay fixture docstring. If ratgdo is not in the candidate set, add a follow-up card: "chatter candidate set may need to include other binary-sensor buckets" — separate marginal-benefit decision.

### LOW-3 — Recovery latch clearance verified; make the discharge test explicit

`fire_stuck_signal_recovered` (`_stuck_signal_nm.py:267`) does clear the latch (`_LATCHES.pop(latch_key, None)` at `:288` and `:293`) — verified. The plan's `test_chatter_nm_recovery_clears_latch` covers this in principle, but the plan body under D2 ("on recovery... call `fire_stuck_signal_recovered`... so the per-day latch clears and next flap re-notifies immediately") should specify the acceptance test observes the second dispatch **within the same calendar day** — otherwise the day-rollover latch prune would give a green light without proving recovery worked.

**Fold-in:** in D2 acceptance criteria, tighten `test_chatter_nm_recovery_clears_latch` wording to: "same-day: dispatch → recovery → dispatch = two dispatches (proves recovery cleared latch, not day-rollover)".

---

## Institutional-context ledger — spot-checked and accurate

- `_detect_duty_cycle_stuck` at `coordinator.py:1576` — confirmed (line 1584 in current tree; close enough).
- `_stuck_sensor_hours` continuous-on at `sensor.py:2296,2353` — not re-verified, but not load-bearing for this review.
- `UnavailableEntitiesSensor` at `sensor.py:1677` — confirmed exact line.
- `fire_stuck_signal` at `_stuck_signal_nm.py:165` — confirmed at `:167`.
- `_LATCHES` at `_stuck_signal_nm.py:47` — confirmed.
- `STUCK_SIGNAL_NM_HAZARD_TYPE` at `const.py:3778` — confirmed exact line.
- `CONF_FLAP_SENSITIVITY` at `config_flow.py:10005-10063`, `const.py:2988-3018` — not re-verified but consistent with plan's disambiguation of ACTUATOR-flap-quarantine as unrelated.
- `_KIND_TO_CONF` at `occupancy_substrate.py:81` — not re-verified (not load-bearing for this cycle; plan reuses via D2's existing candidate-set construction).

No fabricated citations detected.

---

## Verdict

**PLAN-READY.** Both load-bearing reuses (surfacing sensor + NM hook) verified from source. Complement-vs-duplicate proven. Self-corroboration hole closed by "different-entity-id" clause. Consumer enumeration exhaustive and free of trust-decision leaks. Knobs on the correct rung with a documented kill switch. Tests discriminate. Non-goals sharp.

The three LOW findings are clarifications for the builder brief; none blocks build dispatch. Recommend the builder resolve LOW-2 (ratgdo CONF-bucket verification against live config) before starting D1 so the incident-replay fixture is grounded in the actual Garage B configuration.

Tier 2 review protocol (§8) — two framing-disjoint code reviews + live validation — remains appropriate. No elevation to Tier 2-DB indicated.
