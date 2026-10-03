> **REV 3.2 OPERATOR RULINGS + RESEARCH (2026-09-30) — authoritative over earlier text:**
> - **ecobee heat_cool:** ecobee "Auto" = HA `heat_cool` with target_temp_low/high (requires "Auto Heat/Cool" enabled in the ecobee installation settings; House 2's climate lists heat_cool). The ecobee profile runs zones in heat_cool with URA-written low/high ranges; B1 enforcer applies (confirm in D0b).
> - **ecobee holds use SETPOINTS, not the Current Mode select.** HA's homekit_controller ecobee `current_mode` select is unreliable (stuck reporting "home"; HA core #84399, #85715; workaround = press Clear Hold before a mode change, discussion #1705). Hold = heat_cool range write; release = `button.<x>_clear_hold`. The select is read-only/informational (supersedes REV 3's select-hold direction).
> - **Ranges for thermostats without presets (ecobee, Generic):** when HVAC coordination is enabled for a zone, URA asks for per-zone Home / Sleep / Away ranges (zone HVAC settings; reuse the CPR range field style) and holds with them. Missing ranges → a **Repair** asking for them (not silent no-op).
> - **Repairs** are the surface for both "thermostat type changed" and "comfort ranges missing".
> - **ecobee hold action** (installer setting: until next activity / indefinite / N hours) determines how long ANY URA write lasts before the ecobee schedule resumes. URA re-asserts per tick (S1) and books schedule-driven changes as DEVICE_SCHEDULE. Setup docs recommend "until I change it" / no ecobee schedule (same stance as Bryant schedules).

> **REV 3.1 ERRATA (orchestrator, 2026-09-30 — authoritative over the body where they differ; both Tier-3 plan reviews READY after these):**
> - **R1 (P1):** the suppression stores are `OverrideArrester._suppressed_until` (hvac_override.py:353) and `_suppress_kind` (:368) — NOT `_recent_suppressions` / `_preset_suppressions` (do not exist). The P1 byte-identity harness snapshots THESE two after each site.
> - **R3-1 (P1):** the caller-side suppression list has 22 calls, not 19 — add hvac_override.py:7294 (S8 cancel-nudge preset), :7734 and :7761 (S9 boot ramp audit). The harness covers all 22.
> - **R3-2:** P2 ADDS a new boot seed for the single-setpoint ring; the existing pair seed at hvac.py:6075-6084 is left untouched.
> - **R3-3:** the accessor is `recent_ura_single_setpoints_for(entity_id)`; the ring is `recent_ura_single_setpoints`.
> - **R2 (P2):** DEVICE_SCHEDULE writes ONE `override_detected` row with `gated_reason=device_schedule` and has no other effect (no revert, no borrow end, no latch).
> - **R3 (P2):** an operator override to Generic on a device whose presets exist STOPS S1 and raises a Repair (test asserts it). A detection miss at runtime keeps the thermostat's last resolved profile in memory for the rest of the boot; only a thermostat never resolved since boot falls to blocked-Generic (log line + sensor attribute).
> - **R4 (P2):** the new rings are written inside the existing funnels (exceptions #1 and #3); a write carrying only a single `temperature` skips the pair ring.

> **Operator rulings 2026-09-30 (all 5 open questions, answered as recommended):** (1) P3 ships in the normal release to both houses — profiles are auto-detected, no house-specific flag. (2) The ecobee profile reuses the existing per-zone Home/Sleep/Away setpoint fields; no ecobee-only set. **[REV 3 note: this ruling's PREMISE was wrong — those fields do NOT exist. Only the CPR weather-bucketed DPM ranges exist (`CONF_ZONE_DYNAMIC_PRESET_{bucket}_{HOME,SLEEP}_{LOW,HIGH}` — HOME and SLEEP only, no AWAY, owned by CPR). REV 3 dissolves the need: the ecobee `select.<x>_current_mode` (home/sleep/away) applies the ecobee's OWN comfort settings; the ecobee profile HOLDS BY SELECTING THE MODE and writes NO URA setpoints for holds. Only a "true Generic" thermostat (no presets AND no mode select) would need a URA table — that case falls through to `feature_unavailable("hold")` + a Repair asking for temperatures per Q3. FLAGGED FOR OPERATOR: confirm the ecobee-holds-via-mode-select-only shape is acceptable.]** (3) A Thermostat-type override persists; if detection later sees different hardware (swap), raise a repair/NM and ask — never silently revert. (4) Every notification string is templated by profile name ("your ecobee", "your Carrier"); no hard-coded "Bryant app". (5) P1 byte-identity proof = one parametrized suite (S-site × WriteStatus table), not per-site files.

# HVAC W1-C — Thermostat Profiles (brand-owned semantics; Generic net; ecobee first non-Carrier target) — REV 3

## REV 3 changelog (2026-09-30, after both REV 2 re-reviews returned REVISE — narrow)
- **Banner correction (completeness R2-2):** ecobee no longer needs a URA comfort table. Holds go through `select.<x>_current_mode` (home/sleep/away) which applies the ecobee's own comfort settings; URA writes NO setpoints for a hold on ecobee. Only a "true Generic" thermostat (no presets and no mode select) would need a URA table, and per Q3 that case is `feature_unavailable("hold")` + a Repair — not synthesised.
- **N1 (HIGH) — arrester suppression stays with callers in P1.** The contract table's "funnel registers suppression" line is DELETED. Suppression continues to be registered by the ~20 caller sites: `hvac.py:2588` (B1 heat_cool enforcer, `set_hvac_mode`), `:3564`, `:4115`; `hvac_predict.py:1105, 1128, 1396, 1762, 1869, 1884`; `hvac_override.py:4536, 4546, 4765, 4775, 4797, 5401, 5751, 5919, 6073, 7261`. P1 byte-identity **equality set expanded** to include the suppression store per zone/entity (`_recent_suppressions` / `_preset_suppressions` snapshots at the same points the ledger is asserted). Zero funnel-side suppression change in P1.
- **N2 (HIGH) — Generic in P1 = same funnels as Carrier.** `GenericStrategy.set_setpoints` / `set_hvac_mode` / `release_hold` delegate to the exact same funnel calls in the exact same shape as Carrier for P1. Only `classify_person_change` on non-Carrier may be a stub, and the stub **returns `INCONCLUSIVE`, never raises**. New P1 test: a registry-miss entity driven through every A-site produces byte-identical calls vs the Carrier golden.
- **N3 (MEDIUM) — no `release_hold` caller / record in P1.** Carrier `resume` continues to live inside `emit_set_preset_mode`, so P1 has no `release_hold` caller. `release_hold` records nothing in P1. From P2 it records under its own verb key `release_hold`, never `set_preset_mode`; `_zone_last_write_is_away` (§J) keeps seeing `set_preset_mode` values only.
- **N4 (MEDIUM) + completeness R2-1 (HIGH) — DO NOT widen `recent_ura_setpoints` entries.** Both consumers unpack pairs (`hvac_override.py:205, :4232`, boot seed `hvac.py:6075-6084`) inside a `TypeError/ValueError: continue`, so a 3-tuple silently drops every URA echo → all echoes book HUMAN (the pre-v5.103.17 class). The existing pair-ring stays `(low, high)` untouched. P2 adds a **separate** `recent_ura_single_setpoints` (new producer + new accessor, timestamped entries) plus a URA select-write ring. Carrier consumers are untouched; Carrier's last-4 depth-only rule is unchanged. Boot seed updated in the same P2 commit.
- **R2-1b (MEDIUM) — timestamps live only on the new single-setpoint ring.** `person_change_match_window_s` is a knob for the NEW ring only (Generic setpoint case if it ever activates, and the ecobee-single-setpoint person-change classifier). Carrier keeps its byte-identical depth-4 semantics with no window.
- **R2-2 (HIGH) — ecobee comfort table dropped.** See banner. Ecobee holds via mode select; the plan cites no per-zone URA temperature table. `feature_available("hold")` on ecobee is True (the mode select covers home/sleep/away); on a true-Generic profile it is False → Repair.
- **N5 (MEDIUM) — one canonical verdict × consumer table** in §3d, rows {HUMAN, URA_ECHO, DEVICE_SCHEDULE, INCONCLUSIVE}, columns {`override_detected` row + `gated_reason`, arrester revert, borrow `human_interrupt`, interrupt latch, INFO-1 person restore, INFO cadence}. Removes the changelog / §3c / §3d three-way ambiguity. `INCONCLUSIVE` and `DEVICE_SCHEDULE` both = never revert / never end a borrow / never latch / no INFO-1; one INFO per zone per **boot** (unified — not per-day and per-boot in different places).
- **N6 (MEDIUM) — numbered funnel exceptions; verb shape.** First exception = W1-A `climate_write` ledger (shipped). Second = `profile` / `profile_source` kwarg on `climate_write` (P2). Third = `emit_call_service` (P3, non-climate). Ledger `verb` for climate rows stays the BARE service name unchanged (`set_temperature`, `set_preset_mode`, `set_hvac_mode`) — the P1 goldens, live DISTINCT query and existing readers of `verb` are unaffected. Only non-climate rows written by `emit_call_service` carry `"{domain}.{service}"`. Allowlist for `emit_call_service` = exactly `select.select_option` and `button.press`, siblings resolved via `device_id`. Any other domain/service → FAILED zero calls. Lint clause enforcing this lands with P3 (the exception first exists there).
- **N7 (LOW) — the "60 s select-readable" check is moved from D0a to D0b** (it is a write) and its window is named `ECOBEE_SELECT_READBACK_S` (rung 1, initial 60 s; may adjust from D0b p95).
- **N8 (LOW) — `person_change_match_window_s` sourcing.** For ecobee, set at D0b from p95 echo latency + a fixed margin (`ECOBEE_PC_WINDOW_MARGIN_S`, rung 1); for Generic (setpoint-only), initial 600 s; for Carrier, N/A (depth-only rule).
- **F2 residual — restart/reload scenarios in the P1 harness.** Two scenarios added: (a) boot-audit rehydrate (a persisted borrow row is rehydrated at startup; A14 preset-restore runs; oracle recorded from pre-w1c-p1); (b) room reload mid-borrow (a room coordinator reload while a live borrow is in flight; excursion lease slack expiry).
- **F4 residual — TBD-timing profiles are undispatchable.** A concrete profile whose `echo_ttl_s is None` after detection cannot be applied to a live zone: the Manage Zones dropdown greys it out, live detection to that profile falls to **Generic-blocked** (which is `feature_unavailable("hold")` — no writes) plus a Repair asking to complete D0b. No `None` TTL reaches the suppression math.
- **R2-3 (LOW) — `_last_sent` wording clarified.** Today `_record_sent` replaces the whole per-entity dict; with only one recorded verb this is harmless. REV 3 states: "keep the current single-verb behaviour in P1 unchanged; no new verb is recorded in P1; P2 does not change this semantics either" — a builder should not "fix" it.
- **Completeness C7/C8 line numbers corrected:** `OVERRIDE_RECONNECT_GRACE_S` is `hvac_const.py:677`; `AC_RESET_OUTCOME_*_SETTLE_S` are `:942, :954`.
- **New operator flag** raised in §8: Q0 (banner correction) — confirm ecobee-holds-via-mode-select is acceptable.

## REV 2 changelog (retained for context)
See prior revision history — REV 2 folded both plan-review reports (completeness HIGH 1–5 + MEDIUM 6–11; build-prediction F1–F14) into the plan. REV 3 above supersedes only the specific items called out; every other REV 2 fix stands.

---

## 0. What this plan is
An abstraction layer under HVAC so URA works with a non-Carrier thermostat safely, without carrying Carrier assumptions (named-preset vocabulary, `preset_mode=="manual"` semantics, `heat_cool` dual-leg setpoints, Bryant variable-speed physics, Carrier cloud timings, `ha_carrier` freshness/reload machinery, `next_activity_time`). First non-Carrier target: **ecobee over HomeKit Controller** in the second home ("Home", 192.168.17.243), which goes live weekend of 2026-10-03 with HVAC OFF until P3 validates the ecobee profile there.

Read first, in full: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 corrections ledger); `custom_components/universal_room_automation/domain_coordinators/hvac_strategy.py`; `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md` §14; `docs/planning/AUDIT_house2_ecobee_inspection_2026_09_30.md`; vibememo `169`.

---

## 1. Institutional context verified

### 1a. Prior planning + design docs consulted
`PLANNING_hvac_w1a_thermostat_write_governance.md`, `PLANNING_hvac_w1b_thermostat_definition.md` REV 7, `PLANNING_hvac_w1_w2_finish.md` REV 2, `PLANNING_hvac_enable_custom_preset_ranges.md` §14, `PLANNING_hvac_arc_w1_w2_integration.md`, `AUDIT_house2_ecobee_inspection_2026_09_30.md`, `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md`, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §§1–10 (complete).

### 1b. Memory pulled
vibememo `169`, `feedback_config_first_before_code`, `feedback_no_fabrication`, `feedback_tier2plus_prior_art_scan`, `feedback_tier2db_for_regression_prone`, `feedback_extend_existing_never_rebuild`, `feedback_falsify_before_asserting`, `feedback_wire_in_anchor_mandatory`, `feedback_hollow_test_anchors`, `feedback_suppression_needs_discharge`, `feedback_mutation_verification_pycache_staleness`.

### 1c. Prior-art scan — REUSE vs BUILD per proposed piece
| Piece | Verdict | Where |
|---|---|---|
| Strategy registry + dispatch (`strategy_for`) | **REUSE + extend** to (platform, manufacturer, model) | `hvac_strategy.py:238-286` |
| `WriteResult` / `WriteStatus` / `HoldObservation` | **REUSE** | `hvac_strategy.py:56-90` |
| `_last_sent` (single-verb per-entity, whole-dict replace) | **REUSE, unchanged** (P1 keeps single-verb; P2 does not change it either) | `hvac_strategy.py:142-153` |
| Existing pair-ring `recent_ura_setpoints` `(low, high)` | **REUSE, UNTOUCHED** — pair-shape frozen (consumers unpack pairs) | `hvac_setpoint.py:71-100, 486`; unpack sites `hvac_override.py:205, :4232`; boot seed `hvac.py:6075-6084` |
| **New** single-setpoint ring `recent_ura_single_setpoints` + new accessor | **BUILD** in P2 (only reader = new single-setpoint classifier for ecobee/true-Generic) | new |
| **New** URA select-write ring | **BUILD** in P2 (only reader = ecobee select-classifier) | new |
| Person-change classifier (heat_cool 4-leg) | **REUSE** for Carrier (verbatim delegate) + **extend** to `single_setpoint` and `select_or_setpoint` shapes in P2; verdict enum adds `DEVICE_SCHEDULE` and `INCONCLUSIVE` | `hvac_override.py:167 classify_manual_setpoint_change`, `_transition_is_human` |
| Durable per-write ledger row | **REUSE** for climate verbs (bare service name, unchanged); **extend** in P3 via `emit_call_service` for `select.select_option` + `button.press` (`verb="{domain}.{service}"`) | W1-A funnels in `hvac_setpoint.py` |
| Resume-then-pin (Carrier quirk) | **REUSE, capability-gated** | `hvac_setpoint.py:171-222, 317-410` |
| Manage Zones → Zone HVAC step | **REUSE + add** `Thermostat type` display + override dropdown | `config_flow.py`, `strings.json`, `en.json` |
| Zone `climate_entity` field | **REUSE** as the ID key for profile lookup + `_last_sent` | `config_flow.py` HVAC zone step |
| CPR (Custom Preset Ranges) | **REUSE** — strategy hook exists (§14); merge order §5 | CPR §14 |
| Ecobee hold via `select.<x>_current_mode` | **REUSE** ecobee's own comfort settings behind the select; URA writes NO setpoints for holds on ecobee | audit doc; banner note |
| True-Generic hold (no presets AND no mode select) | **NOT SUPPORTED this cycle** → `feature_unavailable("hold")` + Repair | §3d |
| AI-rule refusal for `climate.*` | **REUSE + extend** in P3 to `select.select_option` / `button.press` allowlisted to the two ecobee-sibling entities | `coordinator.py:1122-1135` |
| `HVAC-WRITE-CONFIRMATION-ORACLE-1` (parked) | **FOLD as capability** `has_write_confirmation_feed`; card stays parked | kanban |

### 1d. Producer / consumer map — value "thermostat profile per zone"
**Producer:** `strategy_for(hass, entity_id)` — dispatches by (registry `platform`, device `manufacturer`, device `model`) → (platform, manufacturer) → (platform) → **Generic** (uncached miss); a per-zone operator override wins (with a Repair when live detection disagrees). Exposed on `sensor.<zone>_status` attrs `thermostat_profile` + `profile_source`, and (P2) on every ledger row.
**Consumers (trust decisions):** every A-site (§2 A1–A15); every §B `"manual"` reader; `classify_person_change`; the S1 gate that today reads `preset_mode == "manual"`; the pre-arrival fan writers; the borrow safety gates; `_check_carrier_freshness` (profile-gated in P2); `_zone_last_write_is_away`; the immune-hold sunset reading `next_activity_time`; the AI-rule refusal set.
**Display consumers:** the Manage Zones panel; `sensor.<zone>_status` (new attrs); NM texts templated by profile.

### 1e. Config-first check
Not solvable by an existing knob. Every new number goes through the knob ladder (§6).

---

## 2. INVENTORY — every Carrier-specific assumption in shared HVAC code

### §A — Write sites that today bake Carrier semantics
| # | Site | Verb | Carrier assumption |
|---|---|---|---|
| A1 | S1 preset writer `hvac.py:3638` | preset (+ hidden `resume`) | `resume` capability, named vocabulary, `preset_mode=="manual"` lockout |
| A2 | B1 heat_cool enforcer `hvac.py:2591` | hvac_mode | `heat_cool` universal |
| A3 | S3 arrester compromise `hvac_override.py:4515` | setpoints | dual-leg |
| A4 | S4 revert `hvac_override.py:4712, 4783` | mode + preset | named-preset pin |
| A5 | AC hard reset off/restore/retry/preset `hvac_override.py:5128, 5250, 5289, 5403` | mode + preset | Bryant variable-speed |
| A6 | S5 soft-nudge start `hvac_override.py:5735` | setpoints | dual-leg + Bryant physics |
| A7 | S6/S7 nudge restore `hvac_override.py:6017, 6040, 6087` | setpoints then preset | dual-leg + named |
| A8 | S8 cancel-nudge button `hvac_override.py:7267, 7296` | setpoints + preset | same |
| A9 | S9 boot ramp audit `hvac_override.py:7739, 7762` | setpoints + preset | same |
| A10 | Excursion lease-expiry auto-return `hvac_excursion.py:708` | preset | named-preset pin |
| A11 | S11/S12/S13 `hvac_predict.py:1106, 1131, 1440, 1784, 1870, 1887` | setpoints + preset | dual-leg + named |
| A12 | Egress `hvac_egress.py:721, 827, 848` | mode + preset | named |
| A13 | S10 DPM CPR `hvac.py:4131` → `emit_set_activity_setpoint` → `ha_carrier.set_activity_setpoint` | activity setpoints | Carrier-only (CPR §14 hook; no change here) |
| A14 | Boot audit NUDGE preset restore `hvac_excursion.py:1177` | preset | named-preset pin |
| A15 | Optimizer L2+ climate actuation (dynamic-domain; `const.py:3692-3694`) | any | SHADOW only until strategy-routed |

### §B — `"manual"` readers (~30 sites; the primary override detector is `hvac_override.py:3568-3619`, whose `:3619` "Ignore" branch silently drops a person's ecobee setpoint change today)
| # | Site |
|---|---|
| B1 | `hvac_override.py:3568-3619` primary override detector (into-manual / within-manual / ignore) |
| B2 | `hvac_override.py:2987-2991` preset-window passthrough |
| B3 | `hvac_override.py:3472` startup-audit stale-override scan |
| B4 | `hvac_override.py:1318, 2571` latch discharge |
| B5 | `hvac_override.py:4748-4749` D2d S4 snapshot guard |
| B6 | `hvac_override.py:6060-6120` nudge-restore paths |
| B7 | `hvac_excursion.py:662-686` `_auto_return` HIGH-1 skip (C26) |
| B8 | `hvac_excursion.py:1168, 1177` boot audit `pre_preset == "manual"` |
| B9 | `hvac.py:3377, 3398, 3409, 3574, 3700, 3793` S1 lockout discharge + write branches |
| B10 | `hvac_preset.py:359` |
| B11 | `hvac_setpoint.py:378, 405, 409, 582` resume-then-pin trigger |
| B12 | `coordinator_diagnostics.py:594` display |
| B13 | `hvac_fans.py:1567+` fan-side `_is_manual_on_hold_live` (name-collision — do NOT confuse; NOT a thermostat manual) |
| B14 | `classify_manual_setpoint_change` `hvac_override.py:167` |

### §C — Timings (Carrier cloud + Bryant physics)
| # | Constant | File |
|---|---|---|
| C1 | `SUPPRESS_TTL_SECONDS = 15` | `hvac_override.py:224` |
| C2 | `SUPPRESS_TTL_SECONDS_PRESET = 120` | `hvac_override.py:264` |
| C3 | `HVAC_DECISION_TICK = 5 min` | `hvac_const.py:13` |
| C4 | Carrier reload set (`_STALE_MAX_AGE_S 900`, `_RELOAD_COOLDOWN_S 1800`, `_RELOAD_MAX_PER_DAY 4`, `_POST_RELOAD_GRACE_TICKS 2`, `_POST_RELOAD_SETTLE_S 1800`) | `hvac_const.py:1415-1462` |
| C5 | Nudge (duration 2 min, size 1.5 °F, eval delay 240 s, `OVERSHOOT_GAP 0`, `RESTORE_SETTLE_DELAY_S 180`) | `hvac_const.py:665, 746, 672` |
| C6 | `HVAC_FAST_PATH_MIN_INTERVAL_S 60`, `_MAX_WRITES_PER_ZONE_PER_HOUR 6`, `_MAX_RUNS_PER_HOUR 30` | `hvac_const.py:1053-1067` |
| C7 | `OVERRIDE_RECONNECT_GRACE_S` **`hvac_const.py:677`** (REV 3 corrected) |
| C8 | `AC_RESET_OUTCOME_*_SETTLE_S 60/150` **`hvac_const.py:942, 954`** (REV 3 corrected) |
| C9 | `EXCURSION_LEASE_SLACK_S 30` | `hvac_excursion.py:74` |
| C10 | `LAST_SENT_TOLERANCE_F 0.5` | `hvac_strategy.py:53` |
| C11 | `ARRESTER_URA_WRITE_RING_DEPTH 4` | `hvac_const.py:530` |
| C12 | Preset resume-then-pin retry (P2 introduces one per profile, rung 1) | `hvac_setpoint.py:317-410` |

### §D–§F, §G–§J (unchanged from REV 2)
§D named-preset hold model; §E ODU/IDU telemetry (`hvac_override.py:2230` blower_rpm CORROBORATE; gate-4 `hvac_const.py:876, 914`; `hvac_override.py:2266+`); §F Carrier config-flow fields; §G `ZoneState` single-setpoint producer (`hvac_zones.py:102-103, 615-616`) + 34 high/low reads in `hvac_predict.py`, 41 in `hvac_override.py`, plus `hvac_fans.py:842`, `hvac_covers.py:638-641`, `sensor.py:12844`; §H `_check_carrier_freshness` (`hvac.py:2166, 7339-7420, 7640-7660`) profile-gated in P2; §I `next_activity_time` immune-hold sunset (`hvac_override.py:694-700, 4052-4064`) capability-gated; §J `_zone_last_write_is_away` (`hvac.py:4772-4786`) reads only `set_preset_mode` records — protected by "no cross-verb clearing" and by "`release_hold` records its own key from P2".

---

## 3. DESIGN

### 3a. Profile interface — contracts frozen in P1

```
class ProfileCapabilities:                # rung 1 on each concrete strategy
    platform: str
    manufacturer: str | None
    has_named_presets: bool
    named_preset_vocabulary: frozenset[str]
    has_heat_cool_mode: bool
    setpoint_shape: Literal["dual_leg", "single_setpoint"]
    supports_resume: bool
    supports_activity_setpoint: bool          # CPR
    has_next_activity_time: bool              # immune-hold sunset
    has_write_confirmation_feed: bool         # HVAC-WRITE-CONFIRMATION-ORACLE-1 fold
    has_mode_select: bool                     # ecobee: True
    mode_select_options: frozenset[str]       # ecobee: {home, sleep, away}
    hold_via: Literal["preset", "mode_select", "setpoint_only", "unsupported"]
    hold_release_mechanism: Literal["preset_named", "resume_service",
                                    "clear_hold_button", "setpoint_write",
                                    "select_write", "unsupported"]
    equipment_telemetry: frozenset[str]
    echo_ttl_s: int | None                    # None = TBD → profile UNDISPATCHABLE
    preset_echo_ttl_s: int | None
    write_rate_min_interval_s: int
    retry_interval_s: int
    person_change_match_window_s: int | None  # only for single_setpoint / select shapes; Carrier None
    person_change_shape: Literal["heat_cool_both_legs", "single_setpoint",
                                 "select_or_setpoint"]

class PersonChangeVerdict(Enum):
    HUMAN                # revert / interrupt latch active
    DEVICE_SCHEDULE      # thermostat-side schedule — never revert / never latch
    URA_ECHO             # our own recent write matched
    INCONCLUSIVE         # e.g. select == unknown; Generic setpoint case; never raises
```

Method contracts (identical across profiles; no site re-implements the shape):

| Method | Kwargs | Returns | `_last_sent` (P1) | Ring effects (P2 only) | Suppression |
|---|---|---|---|---|---|
| `hold_preset` | `entity_id, preset, *, gate, blocking, site, zone_id, reason, excursion_id` | `WriteResult` | records `set_preset_mode` (D2.5 no-op preset-only, unchanged) | none | caller-side, unchanged |
| `set_setpoints` | `entity_id, low, high | temperature, *, gate, blocking, site, zone_id, reason, excursion_id` | `WriteResult` | none | P2: append `(low, high)` to `recent_ura_setpoints` (existing pair-ring, UNCHANGED shape) OR `(temperature, ts)` to the NEW `recent_ura_single_setpoints` when `setpoint_shape=single_setpoint` | caller-side, unchanged |
| `set_hvac_mode` | `entity_id, mode, *, site, zone_id, reason, blocking, excursion_id` | `WriteResult` | none | none | caller-side, unchanged (~20 sites incl. `hvac.py:2588`) |
| `set_mode_select` (P3, ecobee) | `entity_id_of_select, option, *, site, zone_id, reason` | `WriteResult` | none | P2/P3: append `(option, ts)` to the NEW URA select-write ring | none in P1; P3 adds a select-scoped suppression store |
| `release_hold` | `entity_id, *, site, zone_id, reason` | `WriteResult` | **P1: records nothing (no Carrier caller);** P2+: records under its own `release_hold` verb key, never `set_preset_mode` | none | caller-side |
| `classify_person_change` | `entity_id, old_obs, new_obs, ring, single_ring, select_ring, reference_resolver, suppression` | `PersonChangeVerdict + delta_f + changed_legs` | none (pure) | none | reads only |
| `is_human_manual_snapshot`, `feature_available`, `feature_unavailable_reason` | — | — | — | — | — |

**Carrier `classify_person_change` = verbatim delegate to `classify_manual_setpoint_change` / `_transition_is_human`.** Shared contract test table drives every profile over identical event fixtures; Carrier rows PINNED to pre-P1 verdicts. **Generic / ecobee `classify_person_change` in P1 = stub that RETURNS `INCONCLUSIVE`, never raises** (N2).

### 3b. Detection + zone setting
- **Order:** (platform, manufacturer, model) → (platform, manufacturer) → (platform) → **Generic** uncached.
- **Keying:** `climate_entity` (HVAC zones can span house zones).
- **Persistence:** options store ONLY an operator override (`zone_thermostat_profile`, absent = detect). Detection is live per call. On boot, if live detection ≠ persisted override → one Repair + one NM per zone; no silent revert.
- **Undispatchable profiles (F4):** a concrete profile whose `echo_ttl_s is None` cannot apply to a live zone: Manage Zones greys it out; live-detection fall-through when it would land there routes to Generic-blocked + Repair. No `None` TTL reaches suppression math.
- **Miss:** one INFO per entity per boot; `profile_source ∈ {detected, override, detect_miss}`.
- **Profile switch:** flushes ring(s), select-write ring, live suppression, AND `_last_sent` on BOTH old and new strategy instances.
- **NM copy** templated by profile name (ruling 4).

### 3c. Degraded-feature surface
- `feature_available("nudge") == False` → S5 stands down (`ac_ramp_events` reason `nudge_unavailable_profile`).
- `feature_available("borrow.<kind>") == False` → S11/S12/S13/pre_arrival skip (`borrow_disabled_profile`; one INFO per zone per day).
- `feature_available("cpr") == False` → S10 skips quietly (existing behaviour §14).
- `feature_available("hold") == False` → S1 stands down; one Repair asking for the missing capability.

### 3d. Verdict × consumer table (N5 — canonical)
| Verdict | `override_detected` row (`gated_reason`) | Arrester revert | Borrow `human_interrupt` (§9e Q3) | Interrupt latch | INFO-1 person restore | INFO cadence |
|---|---|---|---|---|---|---|
| HUMAN | written | eligible | eligible | eligible | eligible | none |
| URA_ECHO | not written | never | never | never | never | none |
| DEVICE_SCHEDULE | not written (`gated_reason=device_schedule`) | never | never | never | never | 1/zone/boot |
| INCONCLUSIVE | not written (`gated_reason=inconclusive`) | never | never | never | never | 1/zone/boot |

Generic-with-single-setpoint on a mode-less thermostat that has a configured comfort table (out of scope this cycle — see §3d Generic behaviour): `DEVICE_SCHEDULE` cannot be distinguished → always `INCONCLUSIVE`.

**Generic behaviour (this cycle):** `hold_via = "unsupported"`, `feature_available("hold") = False`, `feature_available("borrow.*") = False`, `feature_available("nudge") = False`. Setpoint-only writes are NEVER emitted by Generic on its own (no invented table). A Carrier device forced to Generic via override still routes writes through the funnels identically to Carrier (N2, P1); Generic's degraded surface only bites in P2 when Generic OWNS a hold — which it never does in this cycle. The override-to-Generic dropdown carries the warning "Generic on a detected Carrier device disables URA holds — the ecobee schedule / Bryant schedule takes over. Use only for debug."

### 3e. Ecobee-HomeKit profile (`homekit_controller`, manufacturer contains `ecobee`)
- Observed capabilities (audit doc): `hvac_modes off/heat/cool/heat_cool`; `preset_modes = None`; single setpoint in single-mode; `select.<x>_current_mode` (`home/sleep/away`); `button.<x>_clear_hold`; occupancy + motion binary_sensors; humidity target.
- **Hold model — REV 3 canonical:** hold via `select.<x>_current_mode` = write the option. The ecobee applies its OWN comfort setpoints for that mode. **URA writes NO setpoints for holds on ecobee.** Release via `button.press` on `clear_hold`. Setpoints are ONLY written by user action or non-hold URA paths (e.g. a comfort override the operator opts in later — out of scope this cycle).
- **Capabilities set:** `has_mode_select=True`, `mode_select_options={home,sleep,away}`, `hold_via="mode_select"`, `hold_release_mechanism="clear_hold_button"`, `feature_available("hold")=True`, `feature_available("borrow.*")=False`, `feature_available("nudge")=False`.
- **Person-change (P3):** `select_or_setpoint` — reads the URA select-write ring AND the new single-setpoint ring; a setpoint change unmatched by the single ring within `person_change_match_window_s` = HUMAN; an unmatched select change at a known ecobee comfort-boundary time (D0a schedule-transition catalog) = `DEVICE_SCHEDULE`; `current_mode == unknown` = `INCONCLUSIVE`.
- **B1 heat_cool enforcer:** gated OFF on ecobee (operator Q1 unless overridden).
- **Timings TBD until D0b** (`echo_ttl_s`, `preset_echo_ttl_s`, `write_rate_min_interval_s`, `retry_interval_s`, `person_change_match_window_s`, `ECOBEE_SELECT_READBACK_S`). The profile is UNDISPATCHABLE until D0b fills them (§3b).
- **Non-climate ecobee writes** go through the third named funnel exception `emit_call_service` (P3), allowlisted to exactly `select.select_option` + `button.press` on siblings resolved by `device_id`. Ledger `verb` for these rows = `"select.select_option"` / `"button.press"` (climate-verb rows keep bare service names).

### 3f. CPR (Batch C)
Unchanged from §14. **Merge order: W1-C P1 first** (Carrier byte-identical, no behaviour change at the strategy hook). CPR ships on top of `CarrierStrategy.set_preset_range`. A P1 test pins the variable-domain funnel call shape.

---

## 4. PHASES

### P1 — Route every thermostat write through the profile; Carrier byte-identical
**Deliverables**
1. Every A1–A15 site calls `strategy.*`. Carrier delegates preserve the exact same funnel calls in the same order with the same kwargs. A15 stays SHADOW; must not leave shadow before it is strategy-routed.
2. `_last_sent`: **single-verb behaviour unchanged** (R2-3). No new verb is recorded in P1. `_zone_last_write_is_away` continues to read `set_preset_mode` values only.
3. All ~30 §B `"manual"` readers call `strategy.is_manual_hold(observation)` (Carrier: identical predicate).
4. AST completeness: (a) NO raw `climate` service call outside `hvac_setpoint.py`; (b) NO raw `"manual"` string literal in `hvac*.py` outside `hvac_strategy.py` + an allowlist with per-entry reason. The `select` / `button` lint clause is added in P3, when `emit_call_service` first exists (N6).
5. `PersonChangeVerdict` (incl. `DEVICE_SCHEDULE` and `INCONCLUSIVE`) and method contracts LANDED as public types. Non-Carrier `classify_person_change` = stub returning `INCONCLUSIVE`, never raises (N2).
6. **Generic in P1** — `set_setpoints` / `set_hvac_mode` / `release_hold` delegate to the same funnel calls as Carrier for P1 (N2). A registry-miss test drives every A-site through Generic with calls byte-identical to the Carrier golden.
7. **Suppression stays with callers** (N1). The ~20 caller sites listed in the REV 3 changelog continue to register suppression as today. P1 equality set includes the suppression store snapshot per zone/entity at the same points the ledger is asserted.
8. `release_hold` has NO Carrier caller in P1 and records nothing (N3).

**Byte-identity oracle (F2)**
- Goldens captured against tagged commit `pre-w1c-p1` at `hass.services.async_call` with real `CarrierStrategy` (registry fixture `platform="ha_carrier"`); committed as JSON BEFORE any P1 source edit; regeneration in the P1 branch = review-blocking diff.
- Parametrized over `WriteStatus ∈ {APPLIED, SKIPPED_ALREADY_CORRECT, DEFERRED, FAILED(emit_raised), FAILED(no_presets_supported)}` + unavailable-entity.
- **Equality** = service_data (deep) AND ledger rows (`climate_write`, `ac_ramp_events`, `hvac_excursion_events`, `ura_activity_log`) AND named in-memory state per site (`_last_emitted_range`, `_nudge_restore_timers`, `_zone_last_s1_write`, excursion rows) AND **the suppression store snapshot per zone/entity** (N1) AND each site's old-bool→branch mapping (tabled).
- Per-zone per-site emission order (NOT global).
- **Restart / reload scenarios** (F2 residual): (a) boot-audit rehydrate with a persisted borrow row → A14 preset restore fires; oracle recorded from pre-w1c-p1. (b) room reload mid-borrow → excursion lease slack expiry; oracle recorded pre-P1.
- Per-A-site call-neuter drill; bytecode staleness guard.

**Live (post-deploy, operator-gated)**
- One-shot DB query on `ura_activity_log`: `SELECT DISTINCT verb, site, json_extract(values_after, '$.keys')` before vs after — sets equal for Carrier zones.

**Tier: 3.** Four framing-disjoint reviews (A local; B state-machine + funnel identity + suppression; C per-A-site source mutation; D adversarial completeness).
**Falsifiable invariant:** *for a Carrier zone, every `climate` service call URA makes after P1 is identical in domain, service, service_data (deep), per-zone per-site emission order, and suppression-store side-effect to pre-P1 for every S-site under every `WriteStatus` outcome, ACROSS restart and mid-borrow room reload.*

### P2 — Detection + zone setting + Generic hardening + degraded-feature status + ZoneState + Carrier-freshness gate + rings
**Deliverables**
1. `strategy_for(...)` extended to (platform, manufacturer, model). Manage Zones dropdown + display; keyed by `climate_entity`; persisted OVERRIDE only; live detection; Repair + NM on mismatch; miss loud; `profile_source` sensor attr; profile-switch flush on BOTH instances + rings + suppression + `_last_sent`.
2. `ZoneState.setpoint_shape` + `low=high=temperature` normalisation for `single_setpoint` (§G).
3. `_check_carrier_freshness` and its reload consumers profile-gated (§H).
4. `next_activity_time` immune-hold sunset profile-gated (§I).
5. `feature_available` / `feature_unavailable_reason` piped to switch/button/number entities.
6. Generic hardening: `hold_via="unsupported"`, `feature_available("hold")=False` (§3d). No named pin, no invented setpoints, no borrows, no nudges. Person-change stub upgraded to real `INCONCLUSIVE` classifier (still never raises).
7. **NEW rings:** `recent_ura_single_setpoints` (timestamped `(temperature, ts)` entries, separate producer + separate accessor `recent_ura_single_setpoints_for(entity)`), and the URA select-write ring (`(option, ts)`). Existing pair-ring `recent_ura_setpoints` UNTOUCHED. Boot seeding of the new ring lands in the same commit.
8. Per-profile timings accessed via `strategy.capabilities`; module constants stay as Carrier defaults. **Echo TTLs resolved at suppress time** and stored with the suppression entry (F7).
9. `climate_write` gains `profile` + `profile_source` — **second** named funnel exception, one-line kwarg with a default that keeps funnel-signature byte-identity where the caller omits it.
10. `person_change_match_window_s` for the new single-setpoint ring: Generic 600 s (rung 1). Carrier N/A (depth-only; unchanged). Ecobee TBD.
11. Override dropdown warning per §3d; test the override-to-Generic-on-Carrier case (writes match Carrier goldens; only `feature_available("hold")` flips).

**Acceptance / Verify**
- Test: registry fixture (Carrier / ecobee-HK / made-up brand / no registry entry) → each resolves as expected; miss returns Generic uncached; unavailable Carrier entity with a present registry entry still resolves Carrier.
- Test: profile switch flushes the new ring, select-write ring, suppression, AND `_last_sent` on both instances; a `climate_write` row with `profile_source=override`.
- Test: `_check_carrier_freshness` no-ops on a non-Carrier zone (mutation-verified).
- Test: `ZoneState.setpoint_shape=single_setpoint` ⇒ `low==high==temperature`; downstream readers read a live number.
- Test: the existing pair-ring `recent_ura_setpoints` is byte-identical after P2 (Carrier classifier unchanged).

**Tier: 3.** Four framings.
**Falsifiable invariant:** *no shared HVAC path reads `"manual"` outside the strategy; no path calls a `climate` service outside the funnels; a Generic zone performs ZERO named-preset writes, ZERO `resume` calls, ZERO borrow begins, ZERO nudges, and — because `hold_via="unsupported"` — ZERO setpoint writes on its own initiative; `_check_carrier_freshness` short-circuits on any non-Carrier zone before touching `ha_carrier`; the existing pair-ring's shape and depth semantics are unchanged.*

### P3 — Ecobee-HomeKit profile validated against House 2 (split D0)
**D0a — read-only, 24 h.** Probe against 192.168.17.243:80 (operator token, orchestrator-held; never checked in). Records `climate.<x>` state + attrs, `select.<x>_current_mode` state (incl. every change with timestamp — schedule-transition catalog), `button.<x>_clear_hold` availability, `last_updated` rhythms. Report → `docs/planning/AUDIT_house2_ecobee_probe_2026_10_0x.md`.
**D0b — operator-witnessed scripted write probe** (HVAC coordinator OFF; probe writes are one-shot from a dedicated script; the `ECOBEE_SELECT_READBACK_S` check lives here, N7). Records: hold duration after `select_option` / after `temperature` / after `clear_hold`; echo latency distribution (p50/p95/max) → sets `echo_ttl_s` / `preset_echo_ttl_s`; ecobee "hold action" setting; `person_change_match_window_s = p95 + ECOBEE_PC_WINDOW_MARGIN_S` (rung 1, N8).
**Deliverables**
1. `EcobeeHomeKitStrategy` (platform `homekit_controller`, manufacturer contains `ecobee`, case-insensitive with a fall-back list).
2. Hold via `select_option` on `current_mode` for {home,sleep,away}. **No URA setpoint writes for holds.** Release via `button.press` on `clear_hold`.
3. `classify_person_change` "select_or_setpoint" (uses the new single ring + select ring + D0a schedule catalog).
4. `emit_call_service` (third named funnel exception) + lint clause + AI-rule extension (allowlist exactly `select.select_option` and `button.press`; siblings resolved via `device_id`).
5. Ecobee-safe defaults: nudges + borrows OFF.

**Acceptance / Verify**
- Live (House 2, HVAC coordinator ON with 1 zone bound to the ecobee): a scripted `Home → Sleep → Home` walk shows exactly 3 ledger rows `verb='select.select_option'` filtered by `site=S1`; Clear Hold releases; a person's setpoint bump classifies HUMAN within one state event after the HomeKit echo; a schedule-catalog transition classifies `DEVICE_SCHEDULE`; no borrows / nudges / URA setpoint writes fire.
- Test: fixture states matching the audit + probe drive every method with no exception; mid-write mutation of `current_mode` does not double-emit.

**Tier: 2-DB.** Three framings (A correctness / B cross-coordinator + person-change / C test authority via per-site mutation on House 1 fixture).
**Falsifiable invariant:** *for an ecobee-HK zone, URA never calls `climate.set_preset_mode`, never sends `resume`, never writes `target_temp_high/low` or `temperature` for a hold, never writes to any HA service outside the allowlist `{select.select_option, button.press}` (siblings resolved by `device_id`), and never books a schedule-catalog transition as HUMAN.*

### P4 — Capability-gating of equipment-telemetry features
Unchanged from REV 2. Tier 2-DB (elevated).

---

## 5. Merge order + phase boundaries
- P1 can ship alone once N1–N4 (via R2-1 kept on the SEPARATE new ring) and N6 are honoured.
- P2 depends on P1 for the frozen contracts + suppression discipline; ring shape (existing untouched; new ring separate).
- P3 depends on P2 for detection / Generic hardening / new rings AND on D0b for ecobee timings. Q1 (banner) is answered — P2 must therefore route a House-2 ecobee through Generic before P3 lands, which is safe because Generic in P2 is `feature_unavailable("hold")` (no writes, one Repair).
- **CPR merges AFTER W1-C P1** (§3f).

---

## 6. KNOBS
| Knob | Rung | Home | Why |
|---|---|---|---|
| `zone_thermostat_profile` (Select — override; absent = detect) | 2 (config flow) | Manage Zones → Zone HVAC | Kill switch for the wrong profile |
| Per-profile `echo_ttl_s`, `preset_echo_ttl_s`, `write_rate_min_interval_s`, `retry_interval_s` | 1 (module const on `ProfileCapabilities`) | code | Physics / protocol bounds; ecobee values TBD until D0b |
| `person_change_match_window_s` (Generic 600 s, ecobee TBD; Carrier N/A) | 1 | code | Only for new single/select rings |
| `ECOBEE_SELECT_READBACK_S` (initial 60 s; may adjust from D0b) | 1 | code | D0b readback bound (N7) |
| `ECOBEE_PC_WINDOW_MARGIN_S` | 1 | code | Margin above p95 echo latency (N8) |
| Feature-availability operator overrides | not exposed P1–P4 | — | Add only if a real case appears |

`HVAC_PROFILE_DETECTION_RECHECK_S` DROPPED (detection live per call). Any inline literal in new code = plan violation.

---

## 7. NON-GOALS
- No user-defined-brand UI, no research DB.
- No new sensors / entities for equipment telemetry (P4 gates existing readers).
- No change to CPR scope; no change to `emit_set_activity_setpoint` behaviour in P1.
- No change to the borrow primitive, arrester state machine, AC-ramp math, S1 gate structure, Fan Mode, or the interrupt-latch primitive (v5.103.23).
- **No widening of the existing pair-ring `recent_ura_setpoints`** — new ring separate.
- No cross-verb clearing on `_last_sent`; no no-op skip for new verbs in P1; no new verb recorded in P1.
- No release_hold caller in P1.
- No URA setpoint writes for holds on ecobee.
- Humidity target and `fan_modes` on ecobee are OUT.
- No back-compat migration beyond "absent profile → detect + one-shot Repair on mismatch".
- No leaving optimizer L2+ climate actuation out of shadow before it is strategy-routed.
- No synthesised comfort table for a true-Generic thermostat in this cycle.

---

## 8. OPEN QUESTIONS FOR THE OPERATOR

The five original questions carry the banner rulings (with ruling 2's premise corrected in the banner). Five questions remain live:

- **Q0 (NEW — banner correction).** Confirm the ecobee holds via mode-select shape: `select_option home/sleep/away` applies the ecobee's own comfort settings; URA writes NO setpoints for holds on ecobee. If NOT acceptable, we need either (a) an operator per-zone temperature set — actual new fields, not fabricated REUSE — or (b) the ecobee comfort settings authored on the device itself.
- **Q1 (B1 on ecobee).** Permanently gate B1 heat_cool enforcer OFF on ecobee (plan default; URA runs in the mode a person or the ecobee schedule sets), or force `heat_cool`?
- **Q2 (ecobee "hold action" setting, read at D0b).** If it is not "indefinite", the ecobee auto-releases URA's mode-select hold at its own boundary. Do we (a) require "indefinite" as a pre-condition, (b) tolerate auto-release + re-hold on the next tick, or (c) stricter contract (never write to an ecobee with a non-indefinite hold action)?
- **Q3 (true-Generic — no presets, no mode select).** Plan default: `feature_unavailable("hold")` + Repair asking for the missing capability, no invented URA table. Confirm.
- **Q4 (Repair vs NM on detection mismatch).** Ruling 3 said "raise a repair/NM and ask" — one, both, or escalation (NM first, Repair on next boot)?

---

## 9. SUMMARY
REV 3 folds both re-reviews (build-prediction N1–N8; completeness R2-1, R2-1b, R2-2, R2-3 + line-number fixes). Key shape changes: (i) arrester suppression stays with callers in P1 and enters the byte-identity equality set; (ii) Generic in P1 = same funnel calls as Carrier, classifier stub = `INCONCLUSIVE`, never raises; (iii) `release_hold` has no caller / no record in P1, gets its own verb key from P2; (iv) the existing pair-ring is UNTOUCHED, a SEPARATE timestamped `recent_ura_single_setpoints` + a URA select-write ring land in P2; (v) numbered funnel exceptions with climate-verb ledger rows keeping bare service names, non-climate rows carrying `domain.service`, allowlist exactly `select.select_option` + `button.press`; (vi) restart/reload scenarios added to the P1 harness; (vii) TBD-timing profiles undispatchable; (viii) canonical verdict × consumer table for `DEVICE_SCHEDULE` / `INCONCLUSIVE`; (ix) ecobee comfort table dropped — the ecobee holds via mode-select applying its own comfort settings; (x) C7/C8 line numbers corrected (`:677`, `:942/:954`). Five operator questions live (Q0 confirms the banner-corrected ecobee shape).
