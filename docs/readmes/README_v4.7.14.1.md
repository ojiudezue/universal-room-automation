# v4.7.14.1 — Forgotten-Phone Hotfix

## Summary

Hotfix closing three forgotten-phone gaps in v4.7.14's person-tracker AWAY veto.

## Why this ships

v4.7.14 introduced a high-confidence (0.95) "all phones say away" veto on the
camera-driven ARRIVING/HOME paths. The veto correctly defends against Frigate
ghost-presence on empty rooms, but it does not check whether each phone is
**independently trustworthy** before trusting the household-level all-away
signal. Three failure modes slipped past v4.7.14:

- **Gap A — Forgotten phone at home, person walks past camera (false-positive AWAY):**
  Phone sits in the bedroom; resident walks through the kitchen; Frigate
  face-recognizes them. `census_count >= 1`, `unidentified_count == 0`,
  `all_tracked_persons_away == True` (phone says away). v4.7.14 veto fires
  and flips the house to AWAY despite a face-IDed resident being right there.

- **Gap B — Phone on the counter, person actually at work (false-negative AWAY):**
  Phone is at home (BLE), person is at the office. `person.X = home` because
  the phone is home. URA refuses to veto despite the other three phones being
  away. v4.7.14 sticks in HOME variants when no one is here.

- **Gap C — Stale Bermuda data fires a high-confidence veto (stale-positive):**
  Tracking decays to STALE (60-300 s) or LOST (>300 s). `location` field is
  preserved from stale fallback. v4.7.14 reads the stale value as authoritative
  and fires the 0.95 veto on data that may be an hour old.

Single rule: the veto must trust phones ONLY when each phone is independently
trustworthy.

## Changes

Three surgical fixes in `custom_components/universal_room_automation/domain_coordinators/presence.py`.

### H1 — Veto requires `census_count == 0`

Tighten `StateInferenceEngine.infer()` veto predicate (presence.py:415-419)
to require `census_count == 0` in addition to `unidentified_count == 0`.
Closes Gap A.

```python
# Before (v4.7.14)
if all_tracked_persons_away and unidentified_count == 0:

# After (v4.7.14.1 H1)
if (
    all_tracked_persons_away
    and unidentified_count == 0
    and census_count == 0
):
```

### H2 — Exclude phone-left-behind persons from veto denominator

In `_run_inference` (presence.py:1925-1937 helper + :1956-1961 filter),
exclude any person whose `binary_sensor.<slug>_phone_left_behind` is `on`
before the all-away reduction. REUSES the existing
`PersonPhoneLeftBehindSensor` from binary_sensor.py:973-1084 — not
rebuilding detection. Closes Gap B.

Fail-OPEN: if the binary_sensor doesn't exist
(`_attr_entity_registry_enabled_default = False` at binary_sensor.py:988) or
the state is `unknown` / `unavailable`, the person is counted in the
denominator (preserves v4.7.14 baseline behavior for operators who haven't
explicitly enabled the diagnostic).

### H3 — Exclude STALE/LOST persons from veto denominator

In the same filter (presence.py:1939-1950 helper + :1960 filter chain), exclude
any person whose `tracking_status` is not `TRACKING_STATUS_ACTIVE`. REUSES the
existing `tracking_status` field set by person_coordinator.py at :213 (ACTIVE),
:288 (STALE), :153/:333/:345/:377 (LOST). Closes Gap C.

Defensive default: missing `tracking_status` field defaults to ACTIVE
(fail forward toward v4.7.14 baseline).

## What's NOT changing

- v4.7.14 D1 / D2 / D3 surfaces preserved:
  - `StateInferenceEngine.infer()` signature unchanged
  - `_run_inference` computation block structure preserved (`tracked_count > 0`
    fail-safe guard intact)
  - `PresenceHouseStateSensor` attributes `tracked_persons_count` /
    `all_tracked_persons_away` continue to expose the post-filter counts
- No new `CONF_*` knobs
- No new entities, sensors, or buttons
- No DB schema change
- `PersonPhoneLeftBehindSensor` detection logic unchanged (consumed as-is)
- `person_coordinator.py` `tracking_status` transitions unchanged (consumed as-is)
- `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS` (300 s) unchanged
- Frigate / camera configs unchanged

## Operator runbook (post-deploy, within 10 minutes of restart)

1. **HACS installed-version check:**
   - `update.universal_room_automation_update.installed_version` should be
     `v4.7.14.1`. If not, HACS download or HA restart didn't complete.

2. **Coordinator entities present:**
   - `sensor.ura_presence_coordinator_presence_house_state` must exist and
     have a valid state.
   - `sensor.ura_presence_coordinator_house_state_confidence` must exist and
     be a numeric 0.0 - 1.0.

3. **Veto signature check (run when household is actually away):**
   - Verify all 4 persons reach `not_home` on the HA side.
   - `census_count` attribute should be `0` (no one face-IDed in front of cameras).
   - `house_state` should be `away`.
   - `house_state_confidence` should be `0.95` (the veto signature).
   - This is the v4.7.14 regression-guard check.

4. **H1 forgotten-phone check (when phone is left at home):**
   - Leave one phone in the bedroom; walk past the kitchen camera.
   - During the walk, `census_count` should rise to `>= 1`.
   - `house_state` must NOT become `away`.
   - `house_state_confidence` must NOT be `0.95`.
   - If `away` fires during this scenario, H1 is wrong — roll back.

5. **H2 phone-left-behind check (requires diagnostic enabled):**
   - In Settings -> Devices & Services -> Entities, find
     `binary_sensor.<person>_phone_left_behind` (disabled by default).
   - Enable it for one person; restart HA.
   - When that person's sensor is `on` and the other persons reach `not_home`:
     - `tracked_persons_count` attribute should reflect the post-filter count
       (one less than the configured person count).
     - `all_tracked_persons_away` attribute should be `true` (assuming the
       remaining persons are all away).

6. **H3 STALE/LOST check (passive — happens when a phone drifts):**
   - When `person_coordinator.data["<person>"]["tracking_status"]` is `stale`
     or `lost`, that person should not appear in
     `away_person_ids` log enumeration.
   - `tracked_persons_count` should reflect the post-filter count.

## Pre-deploy snapshot procedure

Capture the following BEFORE running `./scripts/deploy.sh`:

| Snapshot | Source | What to record |
|---|---|---|
| HACS installed version | `update.universal_room_automation_update.installed_version` | Current value (should be `v4.7.14`) |
| House-state confidence baseline | `sensor.ura_presence_coordinator_house_state_confidence` | Last 1h average + any 0.95 transitions |
| Phone trackers | `person.*` state | Each person's current state |
| Census count | `sensor.ura_presence_coordinator_presence_house_state` `census_count` attr | Current value |
| Veto-fired log lines | HA logs (journald, source=core) | `grep "Person-tracker veto fired"` over last 24h — count and timestamps |
| `tracked_persons_count` attr | `sensor.ura_presence_coordinator_presence_house_state` | Current count |
| `all_tracked_persons_away` attr | Same sensor | Current value |
| Tracking-status snapshot | `person_coordinator.data["<person>"]["tracking_status"]` per person | Record for each person |
| `phone_left_behind` enabled? | Per-person `binary_sensor.<slug>_phone_left_behind` | Yes/No per person |

Without these, the post-deploy diff is impossible.

## Post-deploy validation procedure

Within 10 minutes of HA restart:

1. Verify HACS installed version: `v4.7.14.1`.
2. Run operator runbook steps 2-3 above.
3. Watch HA logs for at least one of:
   - A `"Person-tracker veto fired"` log line WITH the post-filter
     `away_person_ids` enumeration (proves H2/H3 took effect).
   - OR `house_state` flipping to `away` at confidence `0.95` (proves
     veto path is still alive).
4. Spot-check that NO `house_state == away` transition fires when
   `census_count >= 1` (H1 regression check).

## Rollback procedure

If any post-deploy check fails:

1. In HACS, downgrade `universal_room_automation` to `v4.7.14`.
2. Restart Home Assistant.
3. Confirm `update.universal_room_automation_update.installed_version == "v4.7.14"`.
4. Confirm `sensor.ura_presence_coordinator_house_state_confidence` returns to
   `0.95` during all-away windows (v4.7.14 baseline).
5. File an issue with the symptom + the pre/post observation table below
   so the next cycle can diagnose.

## Live-validation checklist

### Veto-still-fires regression (carries v4.7.14 baseline)

When all 4 persons reach `not_home` AND `census_count == 0` AND `unidentified_count == 0`:

| Attribute / sensor | Expected value |
|---|---|
| `sensor.ura_presence_coordinator_presence_house_state` state | `away` |
| `tracked_persons_count` attr | `4` (4 configured persons, no H2/H3 filters tripped) |
| `all_tracked_persons_away` attr | `true` |
| `sensor.ura_presence_coordinator_house_state_confidence` | `0.95` |
| `binary_sensor.ura_presence_coordinator_house_occupied` | `off` |
| Logs (last 1h) | At least one `"Person-tracker veto fired"` line enumerating all 4 persons |

### H1 forgotten-phone-at-home

When phone is left at home AND resident walks past a camera that face-IDs them:

| Attribute / sensor | Expected value |
|---|---|
| `census_count` attr | `>= 1` |
| `house_state` | NOT `away` (should be `arriving` or `home_*`) |
| `house_state_confidence` | NOT `0.95` |
| Logs (10 min around event) | ZERO `"Person-tracker veto fired"` lines |

**Pass criteria:** confidence stays 0.95 only when veto fires; if a
forgotten-phone person walks past Frigate, veto must NOT fire and the
house must not flip to `away`.

### H2 phone-left-behind exclusion

When `binary_sensor.<person>_phone_left_behind` for one person is `on` AND
the other 3 are away:

| Attribute / sensor | Expected value |
|---|---|
| `binary_sensor.<flagged_person>_phone_left_behind` | `on` |
| `tracked_persons_count` attr | `3` (post-filter) |
| `all_tracked_persons_away` attr | `true` |
| `house_state` | `away` (assuming `census_count == 0`) |
| Logs (10 min) | `"Person-tracker veto fired"` listing the 3 non-flagged persons |

### H3 STALE/LOST exclusion

When one person's `tracking_status == "stale"` AND the other 3 are
ACTIVE+away:

| Attribute / sensor | Expected value |
|---|---|
| `tracked_persons_count` attr | `3` (post-filter — STALE excluded) |
| `all_tracked_persons_away` attr | `true` |
| Veto-fired log | Lists the 3 ACTIVE persons, not the STALE one |

### All-filtered fail-safe

When ALL 4 persons are `phone_left_behind=on` OR `tracking_status != ACTIVE`:

| Attribute / sensor | Expected value |
|---|---|
| `tracked_persons_count` attr | `0` |
| `all_tracked_persons_away` attr | `false` (fail-safe — empty denominator does NOT veto) |
| House state | Falls through to the v4.7.14 baseline AND-gate (confidence 0.9) or camera path |

## Pre/post observation table

Fill in at deploy time:

| Window | Time (UTC) | All persons `not_home`? | `census_count` | `unidentified_count` | `phone_left_behind` (any on?) | `tracking_status` (any STALE/LOST?) | `house_state` | `confidence` | `tracked_persons_count` attr | `all_tracked_persons_away` attr | Veto fired? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Pre-deploy | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ |
| T+10min | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ |
| T+1h | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ |
| Morning workday | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ |

## Known limitations

- **`PersonPhoneLeftBehindSensor` is disabled by default** (binary_sensor.py:988).
  Operators who have not opted in will see H2 take NO behavioral effect
  (fail-OPEN: missing entity → person counted). This is the intentional
  conservative posture.
- **`PersonPhoneLeftBehindSensor` is force-False during 22-07 local**
  (binary_sensor.py:991-1017). During those hours, H2 carve-out is
  inactive — phones that BLE-decay during sleep continue to count in the
  veto denominator. The veto is for AWAY (not SLEEP), so this is the
  desired behavior; sleep-state ripple is v4.7.15's scope.
- **STALE/LOST detection lags by up to 60 s** (`STALE_THRESHOLD_SECONDS`
  in const.py:166). H3 is a guard against trusting OLD data, not a real-time
  reactivity boost.
- **Hard-coded thresholds.** Confidence value 0.95 and the census/unidentified
  comparisons remain hardcoded. Operator-tunable knobs are explicit non-goal
  of this hotfix.
- **No new entities surfaced.** All diagnostic visibility comes from the
  v4.7.14 D3 attributes (`tracked_persons_count`, `all_tracked_persons_away`)
  plus three new keys added by fix-up A-M2 (`tracked_persons_count_trusted`,
  `excluded_persons`) — see fix-up section below.

## v4.7.14.1 Tier 2-DB review fix-up findings

The build was reviewed by three parallel staff-engineer reviewers per the
Tier 2-DB protocol. Four findings (1 HIGH + 3 MEDIUMs) were applied as
fix-up commits on this branch before merge. The fix-ups did not change the
H1/H2/H3 user-facing behavior contract — they tightened correctness, log
quality, and operator-visibility regressions surfaced by the reviews.

### A-H1 (HIGH) — H2 entity_id resolution via entity registry

Reviewer A surfaced that the pre-fix H2 helper constructed entity_id as
`binary_sensor.{slug}_phone_left_behind`, which does NOT match HA's actual
entity composition under `_attr_has_entity_name=True` + DeviceInfo
name="Universal Room Automation". The operator-verified live entity_id is
`binary_sensor.universal_room_automation_<slug>_phone_left_behind` —
device-prefixed. Pre-fix: H2 silently fail-OPEN for every person, shipping
the cycle with H2 effectively disabled.

Fix: H2 now resolves entity_id via
`entity_registry.async_get_entity_id("binary_sensor", DOMAIN, unique_id)`
where `unique_id` mirrors `binary_sensor.py:1000`'s formula. Robust to
device renames and operator entity_id renames. The
`test_h2_entity_id_slug_matches_binary_sensor_format` (Bug Class #44
self-confirming mirror) was replaced with a registry-driven behavioral
test.

Live-validation impact: operators verifying H2 should see one of the four
live entity_ids resolve to a real state, not None.

### A-M1 + A-M3 (MEDIUM, converged with B1.a) — Veto-fired log enrichment

Pre-fix the veto-fired INFO log gate was outcome-driven (`new_state ==
AWAY`) so it ALSO fired on the line-398 AND-gate path (confidence 0.9),
misattributing it to the v4.7.14.1 veto (confidence 0.95). Message text
omitted `census_count == 0` (H1 condition) and the excluded-persons set
(H2/H3 filter targets).

Fix:
- Gate now requires `self._census_count == 0` AND `any_zone_occupied` so
  the log fires ONLY on the actual 0.95 veto path.
- Message now includes: trustworthy-persons count + ids, excluded-persons
  count + per-person "name(reason)" enumeration, `census_count=0`,
  `confidence=0.95`.

Operator runbook impact: when verifying H2/H3 post-deploy, journald
should show `excluded` count > 0 with a per-person reason like
`oji(phone_left_behind=on)` or `jaya(tracking_status=stale)`.

### A-M2 (MEDIUM, converged with B1.c) — Dual `tracked_persons_count` exposure

Pre-fix the `tracked_persons_count` attribute silently flipped from raw
configured count (pre-v4.7.14.1) to the post-filter count, causing
operators with 4 configured persons + 1 phone_left_behind to see `3` and
misdiagnose person_coordinator dropout.

Fix: expose THREE attributes on
`sensor.ura_presence_coordinator_presence_house_state`:
- `tracked_persons_count` — raw configured count (pre-v4.7.14.1 semantic
  preserved; no silent shrinkage).
- `tracked_persons_count_trusted` — post-H2/H3 filter count used by the
  veto reduction (new).
- `excluded_persons` — dict mapping each filtered-out person to their
  exclusion reason (`"phone_left_behind=on"` or
  `"tracking_status=<value>"`).

Operator runbook impact: dashboards that read `tracked_persons_count`
keep working unchanged; new dashboards that need the trust-aware count
read `tracked_persons_count_trusted`.

### Deferred (per plan §8 + reviewer guidance)

- **C1 MEDIUM (test fixture authority).** Mirror helpers in
  `test_v4714_1_forgotten_phone_hotfix.py:_phone_trustworthy` /
  `_tracking_active` remain hybrid mirrors with source-level invariants.
  Cleanup folded into v4.7.15 D1 helper extraction — when the shared
  helper lands, the in-test mirrors are replaced with direct calls.
- **A-L1, A-L2, A-L3 LOWs** — sibling sites missing filters,
  `_tracking_active` default-direction documentation,
  `all_tracked_persons_away` kwarg default. Deferred per plan §8.
- **B2.c, B4.b NITs** — docstring updates. Deferred.

### CRITICAL: Cross-cycle handoff requirement for v4.7.15

The v4.7.15 builder, when it rebases the in-flight feature branch
`feature/v4.7.15-universalize-bug-class-48` onto this hotfix tip, MUST:

1. Resolve the merge conflict at `presence.py` veto-computation block by
   KEEPING the v4.7.14.1 versions (H1 in `infer()`, H2/H3 + filter loop in
   `_run_inference`, A-H1 entity-registry resolution, A-M1/M3 excluded
   persons capture, A-M2 dual-count attributes).
2. Update v4.7.15 D1's Pattern A helper
   (`should_veto_due_to_reliable_signals`) to **consume** the H1/H2/H3
   surfaces v4.7.14.1 added — NOT reimplement them inline. Pattern A
   accepts:
   - `transient_signals[kind=="census_count"]` (H1 input)
   - `reliable_signals[kind=="person_phone_trustworthy"]` (H2 input)
   - `reliable_signals[kind=="person_tracking_active"]` (H3 input)
3. Delete v4.7.14.1's local helpers `_phone_trustworthy` and
   `_tracking_active` from `_run_inference` once the shared helper exposes
   them as utilities; the per-name filter loop becomes an INPUT BUILDER
   for the helper, not duplicate filter logic.
4. Update the source-invariant tests at
   `quality/tests/test_v4714_1_forgotten_phone_hotfix.py` (lines that
   assert `def _phone_trustworthy` / `_tracking_active` literal presence)
   to point at the shared helper names, OR replace them with direct calls
   against the v4.7.15 D1 helper test fixture. The current invariants
   DELIBERATELY trip after extraction — that is the trip-wire by design.
5. Apply Reviewer C's C1 MEDIUM cleanup of v4.7.14.1's hybrid mirror
   tests as part of D1 work (the mirrors are replaced by direct
   production-path tests once the helper is extractable).

The v4.7.15 helper's `VetoDecision` SHOULD expose the excluded-persons
map + dual counts so the universal sensor surface mirrors the
three-attribute exposure across all veto consumers (e.g., v4.7.16's
per-room weighted veto).

## Cross-cycle reference

- **Predecessor:** v4.7.14 (`docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md`,
  `docs/readmes/README_v4.7.14.md`) — introduced the veto.
- **Sibling sprint:** v4.7.15 (sleep-state trust universalization, `docs/planning/PLANNING_v4.7.15_*`) —
  separate scope. Merge order to be coordinated via
  `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md`.
- **Bug Class #48** entry in `docs/QUALITY_CONTEXT.md` — this hotfix is the
  "follow-up tightening" reference for the v4.7.14 trust-hierarchy ripple.
- **Source-of-truth planning doc:** `docs/planning/PLANNING_v4.7.14.1_forgotten_phone_hotfix.md`.
