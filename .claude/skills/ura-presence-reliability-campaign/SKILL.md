---
name: ura-presence-reliability-campaign
description: Executable decision-gated campaign for URA presence-fusion reliability — home_night zone-away flips, camera person-vs-motion per-room policy, residual boot-storm scenarios, unused bed sensor, mmWave fan-noise residuals. Use when a room is "flipping away while occupied", when someone reports "presence broke overnight", when planning a Tier 2-DB presence cycle, when triaging a fan-noise recheck, or when auditing whether a v4.7.13/v4.7.14/v4.7.19/v4.7.21/v4.7.22/v4.7.24 fix is still in effect. Also load before proposing ANY new CONF_*, sensor, or signal in the presence/HVAC substrate — this skill enumerates prior art that would otherwise be duplicated. Not for pure HVAC preset logic (use HVAC coordinator docs) or energy-strategy (use energy-strategy skill).
---

# URA Presence-Reliability Campaign

Runbook for the residual presence-fusion reliability queue on URA v5.7.2+ (2026-07-02).
Assumes you are a single Sonnet-class session with grep, MCP tools (`ha_get_state`,
`ha_get_history`, `ha_get_logs`), Samba mount, and no subagent fleet. Fleet is an
optional accelerator, not a prerequisite.

**Ground rule.** Every claim about file:line, constant, table, or entity in this doc
was verified against the tree at commit tip of `develop` on 2026-07-02. If you are
running later, re-verify per the "Provenance and maintenance" section at the bottom
before quoting anything from here as fact. **No fabrication** (CLAUDE.md).

## When to use / when NOT to use

| Use this skill | Use a different skill |
|---|---|
| Room flips `away` preset while somebody is in it | Preset math itself → `docs/Coordinator/HVAC.md` |
| Camera person-classifier fires ghost occupancy | Actuator did nothing → CLAUDE.md "Troubleshooting — room automation broke" |
| Boot-storm turned lights off at cold-boot | Full deploy pipeline → `deploy` skill |
| Fan-noise re-triggering vacancy | Dashboard card for presence → `ha-dashboard` |
| Auditing v4.7.13 / v4.7.14 / v4.7.19 / v4.7.21 / v4.7.24 fixes still live | Writing a planning doc from scratch → `ura-planner` agent |
| Proposing new CONF/signal in presence surface | Committing changes → `ura-build` agent + deploy skill |

## Load-bearing invariants (state these BEFORE any change)

Any fix in this surface must preserve these. Adversarial reviewer D's job is to
falsify one of these — write the falsification target into the planning doc.

1. **Trust hierarchy.** Phone tracker > BLE > mmWave > PIR > camera-person > camera-motion.
   Higher tier can only *EXTEND* occupancy vs a lower tier disagreeing; higher tier can only
   *VETO* vacancy when it says "occupied".
2. **v4.7.14 all-trackers-away veto is bidirectional.** When every configured
   `person.*` is `away` AND `unidentified_count == 0`, the HouseState AWAY branch runs.
   Do NOT add a per-room trust rule that suppresses this — verify by leaving
   `home_persons` empty falls through to normal `away` path.
3. **Guest detection preserved.** Any veto keyed on tracked persons must gate on
   `unidentified_count == 0`. Fixing v4.7.14 without this shipped ghost-away when
   guests were the only occupants.
4. **Camera can't create presence in a designated opt-out room** (v4.7.16 D4).
   `CONF_DISABLE_CAMERA_PRESENCE=True` rooms MUST NOT re-introduce camera as an
   occupancy source through any new fusion layer.
5. **Boot-actuation storm gate is closed until settle.** `_boot_settle_done` gates
   dispatch of presence-derived actuation. Do not bypass by calling a lower-level
   emit — add your predicate to the release path (`_release_boot_settle`).

## The five open/candidate items

The brief cites five. Verified status against the v5.7.2 tree:

| # | Item | Current state (verified 2026-07-02) | Cycle tier if opened |
|---|---|---|---|
| P1 | home_night zone-away flip | **ALREADY SHIPPED.** `the FAN_TRUST_STATES branch in `hvac.py` (grep `FAN_TRUST_STATES`; currently ~L1245-1290)` gates on `FAN_TRUST_STATES = ("home_night","sleep","waking")` (`hvac_const.py:390`). NOT a build target; treat as regression-watch. | n/a (regression watch) |
| P2 | Camera person-vs-motion per-room policy | **Partial: opt-out shipped**, per-room *nuanced* policy NOT. `CONF_DISABLE_CAMERA_PRESENCE` exists (`const.py:354`, `config_flow.py:108`, `sensor.py:2325`, `strings.json:110`). Discriminator per motion vs person is still investigation-only (`docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md`). | Tier 2-DB (regression-prone: trust hierarchy) |
| P3 | Residual boot-storm scenarios | v4.7.21 shipped Gate 1 (presence dispatch) + Gate 2 (HVAC actuation, 2 cycles). Still latent: cloud-integration slow reload cascading past the timeout (see MEMORY: Envoy boot incident 2026-06-12; RestoreEntity unavailable→OFF poisoning). Gate 3 not designed. | Tier 2-DB |
| P4 | Bed sensor as unused signal | **UNUSED.** No `CONF_BED*` in `const.py`; no consumer in `domain_coordinators/`. Would-be substrate kind. | Tier 2-DB (adds new occupancy kind — substrate change → Bug Class #50 zone) |
| P5 | mmWave fan-noise residuals | v4.7.19 provenance split + v4.7.20 silent hold + v4.7.22 Mode-2 recheck all live. `presence_fan_recheck.py` present. Residual: Master ships Mode-2 OFF by default; sleep-only real observability. | Tier 1 or 2 depending on scope |

Everything else in this doc is per-item runbook.

---

## P1 — home_night zone-away flip (REGRESSION WATCH ONLY)

**Verification, before you "fix" it a second time:**

```bash
# 1. Confirm the trust block is still in place.
grep -n "FAN_TRUST_STATES\|night-trust" \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac.py

# 2. Confirm the state tuple still includes home_night.
grep -n "FAN_TRUST_STATES" \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac_const.py
# EXPECT: FAN_TRUST_STATES: Final = ("home_night", "sleep", "waking")
```

If both greps hit — the fix is IN. Do not "extend it again"; you'll duplicate.

**Live-symptom check (if operator reports "Zone 1 went away in bed"):**

```
# via ha-mcp
ha_get_history entity_id=climate.zone_1_master  duration=8h
ha_get_state entity_id=person.oji_udezue
ha_get_state entity_id=sensor.ura_presence_coordinator_presence_house_state
```

Discriminating experiment (which failure mode is it?):

| Symptom | Interpretation | Fix path |
|---|---|---|
| preset flipped `away` during `home_night`, `person.*` was `home` | v4.7.13 extension regressed | Re-verify `_house_state in FAN_TRUST_STATES` branch executed (add DEBUG log at the FAN_TRUST_STATES branch in `hvac.py` (grep `FAN_TRUST_STATES`; currently ~L1245-1290)) |
| preset flipped `away` during `home_night`, ALL `person.*` were `away` | v4.7.14 veto working as designed — real away | Not a bug; confirm nobody was actually home |
| preset flipped `away` during `home_day` (daytime) | Out of scope of trust block by design | Different cycle — presence degradation daytime |
| Zone regressed to `away` at cold boot | P3 boot-storm — go there | See P3 |

**Do NOT:** re-add a sleep-only trust check. `FAN_TRUST_STATES` already covers.
Do NOT couple bed-sensor into this fix without doing P4 first as its own cycle.

---

## P2 — Camera person-vs-motion per-room policy (Tier 2-DB candidate)

**Current state.** Global camera-motion presence is *already conservative*: presence
Tier-2 fusion only reads person-classified camera signals, not raw motion
(pre-existing behavior, still true — confirm at `presence.py` intake layer before
opening a cycle). The per-room OPT-OUT for chronic camera false positives shipped in
v4.7.16 D4 (`CONF_DISABLE_CAMERA_PRESENCE`). What did NOT ship: **per-room
context-sensitive policy** (e.g. hallway = motion-OK, living-room-with-TV = person-only,
sun-glare rooms = no-camera).

**Prior art you MUST cite in the planning doc (Institutional Context First):**

```bash
grep -n "CONF_DISABLE_CAMERA_PRESENCE\|disable_camera_presence" \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/const.py \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/config_flow.py \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/sensor.py
# EXPECT: const.py:354 (definition), config_flow.py:108 (import), sensor.py:2325 (read + attr)

cat /Users/okosisi/Code/universal-room-automation/docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md
```

**Discriminating experiment (before spending review budget):**

1. Pick 2 rooms with different camera pain — one TV-reflection, one sun-glare.
2. Query `sensor.<room>_unavailable_entities` and per-room provenance attrs
   (`_room_provenance` per v4.7.19).
3. Confirm the false positive is genuinely from `camera.*_person` state
   (not motion). Use `ha_get_history` with `duration=24h`.
4. If both are person-classifier: the fix is CLASSIFIER-side (Protect/Frigate
   thresholds, or a URA person-classifier confidence Number), NOT motion-side.
5. If one is motion: your per-room policy needs motion vs person axes distinct.

**Ranked solution menu (pick before planning):**

| Option | LoC | Tier | Risk | Trust-hierarchy obligation |
|---|---|---|---|---|
| A. Do nothing (operator opts out at CONF_DISABLE_CAMERA_PRESENCE per problem room) | 0 | n/a | 0 | none — respects existing invariant |
| B. Add `CONF_CAMERA_TRUST_MODE` per room {person_only, motion_allowed, disabled} — replaces boolean | ~200 | Tier 2-DB | migration risk on existing boolean | Must degrade to `disabled` under low-lux gate; must preserve v4.7.14 veto |
| C. Add per-room confidence knob (NumberEntity) that thresholds camera contribution | ~400 | Tier 2-DB | fusion math edit | Must NOT allow camera to push higher-tier `person.home` away |
| D. Fusion overhaul — camera as evidence with prior, not as sensor | 1000+ | Tier 3 | huge | Full invariant enumeration required |

**What NOT to do:**
- Do NOT add camera as an occupancy KIND to `OccupancySubstrate` without treating
  it as a Bug Class #50 substrate change (v4.7.24 experience: substrate rebuild
  clobbers subs).
- Do NOT delete `CONF_DISABLE_CAMERA_PRESENCE`; it's the operator's escape hatch.
- Do NOT re-enable camera in rooms where the operator flipped it off.

**Validation gates (post-deploy, in the README write-back):**

```
# Entity attr — per-room state
ha_get_state entity_id=sensor.<room>_room_occupancy
# EXPECT attribute: disable_camera_presence: true/false (verified sensor.py:2392)

# DB — no new false-positive occupancy events from camera during test window
sqlite3 /Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db \
  "SELECT room_id, event_type, trigger_source, count(*) FROM occupancy_events
   WHERE timestamp > strftime('%s','now','-2 hours')
   GROUP BY room_id, event_type, trigger_source ORDER BY count(*) DESC;"
```

Tier 2-DB per standing policy (regression-prone: trust hierarchy ripple).

---

## P3 — Residual boot-storm scenarios (Tier 2-DB candidate)

**Current state.** v4.7.21 shipped two gates on `presence.py`:
- **Gate 1** (dispatch): `_boot_settle_done` — released by predicate A `real_input`
  or predicate B `ha_started` / `timeout` (`BOOT_SETTLE_TIMEOUT_SECONDS`). See
  `_release_boot_settle` at `presence.py:1904`.
- **Gate 2** (HVAC actuation): 2-cycle hold in HVAC coordinator.

**Residual scenarios NOT covered by Gates 1+2:**

| Scenario | Symptom | Why current gates don't catch |
|---|---|---|
| γ-slow-integration | A cloud integration (Envoy, Sonoff) reloads AFTER timeout release, floods dispatchers with `unavailable`→real transitions | Timeout releases blind at `BOOT_SETTLE_TIMEOUT_SECONDS` even if a signal source is still unavailable |
| δ-RestoreEntity poisoning | Sensors restore as `unavailable` then jump to `off`, dispatch reads OFF as "vacant" (Envoy boot incident 2026-06-12) | Gate is on presence side; poisoning is on the sensor side |
| ε-fan_recheck first tick | `presence_fan_recheck` initial DB load races with occupancy inference | Gate covers coordinator, not sub-coordinator restore |

**Verification the two shipped gates are still armed:**

```bash
grep -n "_boot_settle_done\|_release_boot_settle\|BOOT_SETTLE_TIMEOUT_SECONDS" \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence.py \
  | head -30
# EXPECT: :1354 assignment; :1904 def _release_boot_settle; ha_started + timeout paths present
```

**Discriminating experiment (which residual is biting you):**

1. Trigger a cold boot: `ha_restart` or (if MCP unhealthy) SSH → `ha core restart`.
2. Immediately: `ha_get_logs level=warning` — grep `Boot-settle:`
3. Note the release reason: `real_input` vs `ha_started` vs `timeout`.
4. If `timeout` — one of the sensor sources didn't produce a real input in
   `BOOT_SETTLE_TIMEOUT_SECONDS`. That's your γ or δ. Confirm with
   `sensor.<room>_unavailable_entities` snapshot.
5. Cross-reference to `occupancy_events` in the 5min window after boot:

   ```
   sqlite3 <db> "SELECT * FROM occupancy_events WHERE timestamp >
     (SELECT MAX(timestamp)-300 FROM occupancy_events);"
   ```

   If mass `vacant` events from same trigger_source at same second → storm.

**Ranked solution menu:**

| Option | Idea | Tier | Notes |
|---|---|---|---|
| A. Extend Gate 1 predicate to include "N% of substrate kinds have real values" | Tier 2-DB | Touches substrate — Bug Class #50 risk |
| B. Per-integration `after_dependencies` hardening (Envoy pattern) | Tier 2 | Config wiring; still boot ordering |
| C. RestoreEntity guard: don't emit `off` on restored-from-unavailable transition until first real value | Tier 2-DB | Sensor-side; per-platform touch |
| D. Gate 3 in HVAC: hold vacancy actuation until per-zone substrate seen at least one real value | Tier 2-DB | Cleanest — puts the gate closest to the failure |

**What NOT to do:**
- Do NOT extend `BOOT_SETTLE_TIMEOUT_SECONDS` blindly — that stalls the healthy path.
- Do NOT couple presence-gate release to `optimization` coordinator readiness
  (post-rollback rule; see MEMORY: optimizer DB write-flood incident).
- Do NOT add a per-room manual override switch to bypass — masks the bug.

**Validation gates (README write-back):**

```
# Log check — every boot, ONE release line
ha_get_logs pattern="Boot-settle: released"
# EXPECT: exactly 1 per restart, reason=real_input on healthy boot

# DB — no away-storm within 5min of restart
sqlite3 <db> "SELECT count(*) FROM occupancy_events
  WHERE event_type='vacant' AND timestamp > (strftime('%s','now')-300);"
# EXPECT: < number of rooms  (a real storm >> rooms)
```

Tier 2-DB minimum. If touching substrate → still Tier 2-DB, but Reviewer C
framing MUST include Bug Class #50 (substrate sub clobber) mutation.

---

## P4 — Bed sensor as unused signal (Tier 2-DB — substrate change)

**Verified unused (2026-07-02):**

```bash
grep -rn "CONF_BED\|bed_sensor\|bed_occupancy" \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/const.py
# EXPECT: (nothing) — no bed conf exists
```

**Why this matters.** With P1 shipped (home_night trust extends `home_night`),
the bed sensor is a stronger signal than mmWave for the stationary-sleeper case
that first surfaced the gap (memory: `project_zone_away_when_occupied_home_night_gap.md`).
Adding it would:

- Give a POSITIVE occupancy signal in bed (mmWave gives DEGENERATE — misses stillness).
- Enable removing the person-tracker fallback that currently trusts the phone
  location across the whole zone — a signal known to be noisy near sleep.

**But — this is a substrate change.** v4.7.24 taught: `OccupancySubstrate` per-room
per-kind slots; adding a new kind changes seeded state, changes replay on release,
changes `substrate_kinds` attr. See MEMORY: Bug Class #50.

**Prior art to cite (Institutional Context First):**

```bash
grep -n "substrate_kinds\|OccupancySubstrate\|_room_provenance" \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence.py \
  | head -30

cat /Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md
```

**Solution shape (write into planning doc, don't code yet):**

- Add `CONF_BED_SENSORS: list[entity_id]` per room (`const.py`) + config_flow field.
- Register as new substrate kind `bed` alongside existing `motion` / `mmwave` /
  `occupancy` / etc. (verify canonical kinds by grepping `substrate_kinds`).
- In `hvac.py` night-trust block: `bed=True` is STRONGER trust than person tracker
  — cannot be overridden by `away` preset flip regardless of house state.
- Actuator visibility: expose `sensor.<room>_bed_occupied` boolean attr.

**Trust-hierarchy obligation (adversarial Reviewer D falsification target):**
"Under a home_night state where person.oji_udezue = away but bed sensor = occupied,
the zone MUST NOT flip to away." State this falsifiable invariant in the planning doc.

**What NOT to do:**
- Do NOT read a bed sensor from a room's generic `occupancy` list and rely on
  presence to sort it out — that erases provenance and re-creates the v4.7.19
  problem.
- Do NOT skip the Bug Class #50 mutation test (edit substrate rebuild code path,
  confirm the new kind's subscription survives). See CLAUDE.md Tier 3 framing C.
- Do NOT make bed sensor absence a NEGATIVE (would flap empty bedrooms constantly).

**Validation gates:**

```
ha_get_state entity_id=sensor.master_bedroom_room_occupancy
# EXPECT: attribute substrate_kinds now contains "bed"

sqlite3 <db> "SELECT event_type, trigger_source FROM occupancy_events
  WHERE room_id='master_bedroom' AND timestamp > strftime('%s','now','-8 hours')
  ORDER BY timestamp;"
# EXPECT: continuous occupancy through sleep window, trigger_source may include 'bed'
```

Tier 2-DB, framings A=substrate integrity / B=trust-hierarchy invariants / C=
config-flow round-trip + restore. Consider elevating to Tier 3 if the fix
threads through both room-tier AND zone-tier occupancy.

---

## P5 — mmWave fan-noise residuals (Tier 1 or Tier 2)

**Current state (verified 2026-07-02):**
- v4.7.19: provenance split shipped. Per-room `_room_provenance[kind]` in `presence.py`.
- v4.7.20 + v4.7.20.1: silent confidence discount + `async_dispatcher_send` UnboundLocal hotfix.
- v4.7.22: Mode-2 BLE-gated fan pause + recheck. `presence_fan_recheck.py` coordinator.
  Master ships OFF by default; must be flipped ON per room. High-still-risk guard
  present (from Review C1 during that cycle).

**Verification:**

```bash
ls /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py
grep -n "STATE_IDLE\|LAYER_NONE\|CONF_ROOM_FAN_RECHECK_ENABLED" \
  /Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py \
  | head -10
```

**Residual failure modes:**

| Mode | Symptom | Fix path |
|---|---|---|
| a. Room flips `vacant` while fan is on and person is stationary in daytime | Mode-2 not enabled for that room, or BLE ladder not authorized | Enable `CONF_ROOM_FAN_RECHECK_ENABLED` for the room, confirm BLE gate |
| b. Recheck fires nightly for a napper | High-still-risk guard should suppress. If not — regression in the guard | Tier 1 hotfix: re-verify the guard branch runs before dispatch |
| c. Fan pause causes discomfort (user notices the pause) | Mode-2 by design pauses to recheck. Consider Mode-3 (silent confidence) only | Tier 2 alternative pathway |
| d. Fan-trust ON-side restored (reverted fix) | ON-side trust was REMOVED for a reason — don't put it back | REJECT — not a fix, that's a regression |

**Discriminating experiment (which mode):**

```
ha_get_state entity_id=sensor.<room>_room_occupancy
# Attribute: fan_recheck_state (values: idle/pause_pending/rechecking/settled)
# Attribute: fan_recheck_last_outcome (occupied/vacant/skipped_high_still_risk)
# Attribute: fan_recheck_ble_ladder_layer

ha_get_history entity_id=fan.<room>_fan  duration=6h
# Cross-reference with occupancy — did fan pause coincide with vacancy?
```

**What NOT to do (durable operator directives):**
- **Do NOT re-add fan-trust ON-side.** Reverted for cause. See MEMORY.
- **Do NOT skip the `high_still_risk` guard.** It protects nappers.
- Do NOT ship Mode-2 ON-by-default for bedrooms — operator preference.
- Do NOT chain fan-recheck into the boot-settle release path (they solve
  different failures).

**Validation gates:**

Cycle-level: existing acceptance in `PLANNING_fan_noise_mode2_ble_pause_recheck.md`.
Live-level:

```
# 24h of rechecks — outcome distribution should look sensible
sqlite3 <db> "SELECT room_id, fan_recheck_last_outcome, count(*) FROM ...  -- adjust to actual table"
# Confirm: no room stuck in pause_pending; no vacancy-decision when high_still_risk
```

Tier 1 for a targeted guard-branch fix; Tier 2 if adding a new Mode-3 or
changing per-room defaults.

---

## Cross-cutting: change-control routing

**Standing rule (CLAUDE.md).** Regression-prone changes go through Tier 2-DB
(three framing-disjoint reviews). Everything on this campaign except P1 (already
shipped, no fix needed) and a narrow P5 guard hotfix is regression-prone. Default
to elevating.

**Pre-review baseline tag (mandatory before any fix-up applied):**

```bash
git tag pre-review-v<X.Y.Z> -m "Pre-review baseline for v<X.Y.Z>"
git diff pre-review-v<X.Y.Z>..HEAD  # to isolate later
```

**Doing three framing-disjoint reviews as a solo Sonnet-class session (no fleet):**

Run three PASSES, each with a *separately loaded context window*. Don't try to
run all three in one context — the framings will bleed. Save each review to
`docs/reviews/code-review/v<ver>_<name>_review<A|B|C>_<framing>.md`. Then run
a fourth adversarial-completeness pass (Reviewer D) if Tier 3 is warranted.

Suggested framings for THIS surface:

| Reviewer | Framing | Anchors |
|---|---|---|
| A | Trust-hierarchy invariants + per-tier veto correctness | Invariants 1-3 above; falsify: "any lower tier can override a higher one" |
| B | Substrate integrity + Bug Class #50 (sub clobber on rebuild) | `OccupancySubstrate` `_update_signal_subscriptions`, dispatch replay |
| C | Config-flow round-trip + RestoreEntity boot poisoning + CONF_DISABLE_CAMERA_PRESENCE respect | `config_flow.py`, `options_flow.py`, unavailable→OFF path |
| D (if Tier 3) | Falsify: "under X the invariant Y cannot fail in ANY reachable path". Real per-site source mutation test (edit prod source, run suite, restore). Include PRE-EXISTING sites, not just diff. | v5.5.3 D-HIGH-1 recipe |

**Live-validation write-back mandate.** After deploy, replace the prospective
"Live" bullets in `docs/readmes/README_v<ver>.md` with a `Validated <date>` table
of PASS/FAIL rows with entity_id + attribute value + DB row cited. The README's
git history IS the ledger.

---

## Live-access fallback (mount / MCP down)

Fact-home for exact `mount_smbfs` invocation, live URA DB path, and MCP
tool inventory: `ura-diagnostics-and-tooling` § Live-access commands.
Copy verbatim from there — do NOT retype from memory. MCP down → SSH
fallback (`journalctl -u home-assistant` or `ha core logs`). Do NOT
edit `.storage/*` files.

**When to test in-suite instead of live:** if MCP AND mount are both down, run
the presence-scoped isolate:

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v -k "presence or occupancy or boot_settle"
```

Full test-suite invocation + fixture-authority rules live in
`ura-validation-and-qa`. Live validation is still mandatory before
closing the cycle; defer the write-back until access restored, but do
NOT declare the cycle closed.

---

## Provenance and maintenance

Volatile facts in this file, with re-verification one-liners. Dated 2026-07-02.

| Fact | Verify command |
|---|---|
| `FAN_TRUST_STATES = ("home_night","sleep","waking")` | `grep -n FAN_TRUST_STATES custom_components/universal_room_automation/domain_coordinators/hvac_const.py` |
| Night-trust block at hvac.py:~1266 | `grep -n "FAN_TRUST_STATES\|night-trust" custom_components/universal_room_automation/domain_coordinators/hvac.py` |
| `_boot_settle_done` gate + `_release_boot_settle` | `grep -n "_boot_settle_done\|_release_boot_settle" custom_components/universal_room_automation/domain_coordinators/presence.py` |
| `CONF_DISABLE_CAMERA_PRESENCE` shipped | `grep -n CONF_DISABLE_CAMERA_PRESENCE custom_components/universal_room_automation/const.py` |
| Bed sensor UNUSED | `grep -rn "CONF_BED\|bed_sensor" custom_components/universal_room_automation/const.py custom_components/universal_room_automation/domain_coordinators/` |
| `presence_fan_recheck.py` present | `ls custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py` |
| Manifest version | `grep version custom_components/universal_room_automation/manifest.json` |
| DB `occupancy_events` schema | `grep -n "occupancy_events" custom_components/universal_room_automation/database.py` |
| CLAUDE.md tier policy still in effect | `grep -n "Tier 2-DB\|Tier 3" CLAUDE.md` |

If any of these greps returns nothing (or a different location), the codebase has
moved past this document. Update the corresponding section BEFORE using it as
canon, or fall through to the code itself.

**Sibling skills** (do not duplicate their content — cross-reference by name):
- `deploy` — release pipeline for whatever cycle comes out of this campaign.
- `homeassistant_coding` — HA-idiomatic patterns for any new sensor/switch/number.
- `documenter` — post-cycle architecture doc updates.
- `transition-doc` — capture false starts before context clear.
- CLAUDE.md — supreme; when in conflict, CLAUDE.md wins.
