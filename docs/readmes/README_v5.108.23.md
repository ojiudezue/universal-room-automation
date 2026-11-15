# v5.108.23: census deconfliction + crossing ledger (ships dark)

Card: CENSUS-DECONFLICTION-LEDGER-1 (parent VISION-CROSSING-ANALYSIS-1).

Branch `feature/census-deconfliction-p2-ledger`, merged into develop after v5.108.22 (batch 2). Tier 3: four code
reviews (A/B/C/D, `docs/reviews/code-review/v_census_p2_ledger_*.md`), then the merge with batch 2 and the G7 swap
with per-site mutation drills, then a full-suite name-diff (0 failed / 22167 passed vs the batch 2 baseline) and the
D7 gate. Orchestrator check before deploy (2026-11-14): `classify_held` stream branch neutered -> 5 named G7 tests
RED, restored -> green. Operator go: "Sure" (ship the core census), "Ok" (swap + mutation test, no extra review).

Plans: `docs/planning/PLANNING_crossing_vision.md` P2-D1, P2-D2, P2-D3; `docs/planning/PLANNING_census_deconfliction.md`
CD1, CD2, CD3. Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` ("Vision is to assist
census accuracy..."; hard constraint "I need away to be fast acting").

## What ships

- **P2-D1.** The crossing-vision llmvision provider is an option: Integration -> Perimeter Alerting -> Advanced ->
  "Door count AI provider ID" (`crossing_vision_provider_id`). Empty = the install default (the Luna entry
  `01M7B731T26P2HXVW77AQR62PP`) when that llmvision entry exists on this install, else the perimeter provider. A set
  option is used only when it names an llmvision entry on this install.
- **P2-D2 / P2-D3.** A house crossing ledger (RAM) inside the crossing-vision producer: one term per door crossing
  (vision count when `ok`, else max(1, camera count)), an empty-house anchor (cameras see nobody, the fleet is lit, no
  room sensor held on or dead-holding, no rising edge, no entry term, for 15 min -> the ledger resets to the residents
  home), a resident floor that is an arrival credit (lifted only when the resident count rises; the arriving
  resident's own entry term consumes it, so each person counts once), a resident-departure reconcile that consumes one
  person per applied exit, rows `crossing_vision_ledger` (terms, anchors, reconciles, lifts), pages
  `crossing_ledger_stuck` (HIGH) and `crossing_ledger_anchor_zero` (LOW, names the holding inputs, dead ones first;
  silent while enhanced census is off), and the `crossing_ledger` attribute on Outside: Open Tracks. Off with the
  shadow switch. `crossing_vision_disagree` pages HIGH (MEDIUM reaches no channel). The ledger row type is not
  checked by the weekly writer-health trip-wire while the shadow switch is off.
- **CD1.** One dedup function, `census_deconflict.deconflict_house`, called once per census evaluation. The census
  house result gains an awareness view; the trust view (every existing field, the census signal, the DB snapshot, every
  existing entity) is unchanged. F-LEAD is off: the awareness value equals the trust value.
- **CD2.** Two display entities: `sensor.ura_census_people_around`, `sensor.ura_census_guests_around`.
- **CD3.** `switch.ura_crossing_vision_census_authority`, named **Vision Assisted Census** (description attribute:
  "Show people counts that include AI vision of door crossings. Off uses sensors only. Never affects Away, security or
  locks."). Default ON when the install has at least one enabled camera entity in the entity registry, OFF otherwise;
  a stored on / off wins (OFF = every reader uses the trust view); pages
  `crossing_vision_disagree` (door group, 5 disagreements in 24 h) and, only after an F-LEAD flip, "revert F-LEAD".
- Presence: each residency record is also dispatched on `SIGNAL_RESIDENCY_EVENT` (read only by the ledger).
- **Merged with develop v5.108.22 (batch 2), 2026-11-14.** One F2 read: the awareness branch lives in
  `census_view.house_census_view` (vision_status / ledger_state fields on `HouseCensusView`);
  `PresenceCoordinator.get_house_census` delegates to it. RA6 private-census-read guard green with no new allowlist
  row. The cross-validation-off census path keeps both the ledger availability flag and the S2 held / released sets.
- **G7 (contract `CONTRACT_person_awareness_layer.md` §5).** The ledger anchor's held-input check reads the S2 view
  `camera_stream_health.entity_stream_view` per Tier-1 input instead of scanning `hass.data` for room coordinators.
  A Tier-1 input whose stream view is HELD or RELEASED blocks the anchor whatever its last good reading; RELEASED is
  never "off" for the anchor. Inputs dead by state (unavailable / unknown / missing) keep the last-good rule. Behaviour
  change vs the pre-merge branch: a stream-dead input whose last good reading was `off`, and an input that went
  `unavailable` together with its camera (held from t0), now hold.

## What does not change (byte-identical, proven in-suite)

AWAY entry and every `_run_inference` trigger, the census signal payload, `_handle_census_update`, the boot seed,
`CensusMismatchSensor`, the four existing census sensors: pinned against a develop golden generated before any
production change, under five vision variants (ledger absent / 0 / 50 / None / unhealthy, F-LEAD on, classes
{display, notification}, switch ON) — `quality/tests/test_census_trust_golden.py`,
`test_census_awareness_surface.py::test_excluded_consumers_never_read_vision`.

## Operator checkpoint (decisions pending)

- **`CROSSING_VISION_LEDGER_EMPTY_RESET_S` = 900 s (15 min, operator 2026-11-14).** Basis: the actual-Tier-1 sweep
  `docs/planning/AUDIT_ledger_checkpoint_window_sweep_2026_11_14.md`: 15 checkpoints / 7 days from 4 empty episodes,
  all in AWAY; every resurfacing within 60 min was a real arrival's garage precursor (0 unexplained). One rung-1 knob.
- **Anchor rules added in the final fix-up.** An anchor clears the applied-exit store (Q1). No occupancy substrate /
  Tier-1 map = the anchor is BLOCKED (`tier1_map_unavailable` shown as the holder; Q2). A Tier-1 entity that is in no
  entity-registry entry and has no state is ignored for the held set, listed on the ledger diagnostics
  (`tier1_not_in_registry`, `_count`) and logged once.
- **Switch label (review B-L6).** Resolved: "Vision Assisted Census" (operator 2026-11-14).
- **G7 mutation drills (2026-11-14, per-site, restored, `git status` clean).** View read detached ->
  `test_held_set_from_substrate_map_and_lkg` + four `test_g7_*`; RELEASED dropped ->
  `test_g7_released_view_still_blocks_anchor`; input route only -> `test_g7_own_camera_route_for_unresolved_input`;
  `classify_held` stream branch removed / reverted to the last-good rule ->
  `test_stream_dead_input_frozen_reading_is_not_good` + `test_g7_held_view_blocks_even_with_last_good_off`. The
  review C fix-up drills (CC07, CV30, CV59, CV46, CV47, CC03, CV70, CV72, CL40, CL56), the four AWAY drills and five
  merge-site drills (census_view awareness branch, presence delegate, xval-off availability flag) all RED after the
  merge. AW5 (manager boot seed) has no site any more: develop RA7 deleted that branch.

## Operator actions at deploy

1. Optional: set "Door count AI provider ID". Empty uses the Luna entry on this house already.
2. Leave `switch.ura_crossing_vision_census_authority` ON (shipped default).
3. Optional (plan §3.6): repoint headline "people" cards to the awareness entities; keep the trust entities on a
   diagnostics card. No house-visible change until F-LEAD.

## Live acceptance

### Validated 2026-11-14

Restart at about 22:06 UTC (16:06 CST), house state GUEST. Validated 22:07–22:09 UTC, first ~3 minutes after boot.
Clock note: DB timestamps are naive UTC (the `census_snapshots` rows match the UTC clock); the `crossing_ledger`
`last_changed` values are Chicago local. Read-only throughout: no HA state change, no Bermuda diagnostics.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Awareness entities equal the trust entities (F-LEAD off) | PASS (3 reads); hour-long resample PENDING | `sensor.ura_census_people_around` = 3 and `sensor.universal_room_automation_persons_in_house` = 3; `sensor.ura_census_guests_around` = 0 and `sensor.universal_room_automation_unidentified_persons_in_house` = 0. Equal at reads 22:07, 22:08 and 22:08:36 UTC. The awareness sensors last changed 22:07:00 (state unchanged since), so this is a state-equality check, not a per-tick trace. PENDING: the hour-long resample, due about 23:10 UTC. |
| L2 | `switch.ura_crossing_vision_census_authority` present and on | PASS | State `on`, `last_changed` 2026-11-14T22:06:48Z. |
| L3 | Outside: Open Tracks `crossing_ledger.state` is `unknown` after restart | PASS for `unknown`; `known` half PENDING | `sensor.ura_security_coordinator_outside_open_tracks_diagnostic`, attribute `crossing_ledger`: `state` unknown, `unknown_reason` boot, `L` null, `last_anchor` null, `held` lists 5 Tier-1 inputs. `switch.ura_crossing_vision_shadow` on since 22:06:48Z. PENDING `known`: event is the first anchor (cameras see nobody for 15 min, fleet lit, no room input held), which writes the anchor row. |
| L4 | `crossing_vision_ledger` term row with non-null `l_after` | PENDING | `memory_episodes` has zero rows with `episode_type` like `%ledger%`, at any time. Expected while the ledger is unknown. PENDING event: the first door crossing after the ledger becomes known. |
| L5 | `aware_total` non-null after the first census tick | PENDING (no REST read surface) | Neither awareness entity exposes `aware_total`; the attribute list is `count_provenance`, `aware_agreement`, `vision_status`, `ledger_state`. PENDING event: a diagnostics read of `get_house_census("awareness")` on the running instance returning non-null `aware_total`. |
| L6 | Existing census fields and AWAY latency unchanged | PENDING | Trust sensors unchanged since restart: `persons_in_house` = 3 and `unidentified` = 0, with the existing attribute set. AWAY latency cannot be measured yet: no AWAY transition since restart; last `house_state_log` row 2026-11-14T17:34:59 (guest, UTC); last `census_snapshots` row 22:03:48 UTC, pre-restart. PENDING event: post-restart AWAY transitions accumulate, then the median and p90 are compared against the P2-D0 (v) baseline. |
| L7 | `ok` shadow row with model `gpt-6-luna` | PASS (pre-restart rows); post-restart row PENDING | `memory_episodes` `crossing_vision_shadow`: 13 rows `outcome` ok, `model` gpt-6-luna, last 2026-11-14T15:52:52-06:00 (21:52 UTC); also 10 `clustered` and 1 `no_frigate_event`. All predate this restart, so they show the Luna shadow path ran before the restart, not that this build wrote one. PENDING event: an `ok` gpt-6-luna row with `started_at` after 22:06 UTC, from the next door crossing with the shadow switch on. |
| L8 | No `crossing_vision` / `census_deconflict` ERROR; no page on day one | PASS | `system_log` ERROR since boot: 14 entries, none from the crossing-vision or census-deconflict modules. `ha_get_logs` error_log at ERROR, search `crossing_vision` and `census_deconflict`: 0 records. `notification_log` since 22:00 UTC: no `crossing_ledger_stuck`, `crossing_ledger_anchor_zero` or `crossing_vision_disagree` row. The only post-restart page is a normal `perimeter_alert` MEDIUM at 22:07:42 UTC (exterior person, not a ledger page). |
| L9 | No `automations.yaml` reference to the two new entities | PASS | `grep` for `people_around`, `guests_around`, `crossing_vision_census_authority`, `crossing_vision_shadow` in `/Users/okosisi/ha-config/automations.yaml`: no matches (exit 1). File readable. Scope is that file only, as specified. |

**Log scan since restart vs the v5.108.22 boot scan.** Boot 22:06 UTC (v5.108.22 booted 20:38 UTC). URA-origin ERROR: 0 (v5.108.22: 0). URA tracebacks: 0. Non-URA ERRORs (WhatsApp bridge 401, Amcrest connect timeout, lepro_led login, proxmox, thinq, aioamazondevices refresh, esphome `assist_satellite` duplicate-setup at boot, a Kiosk websocket backlog) are the same families as v5.108.22.

New URA-origin WARNINGs versus v5.108.22, all in the boot window (22:06:22–22:07:42 UTC):

- `camera_census`: "Census: all camera platforms unavailable", x2, first 22:06:59. NEW. The v5.108.22 S1 bar was zero camera_census WARNs. Boot transient: no recurrence in the buffer after 22:07:07. Confirm on day one.
- `coordinator`: "All 1 sensors unavailable — holding occupancy state for 60s", x12, first 22:07:03. NEW. Five rooms (Kitchen Hallway, Study A Closet, AV Closet, Dining Room, Guest Bedroom 1 Closet) had their only sensor unavailable at boot. Confirm those sensors come back; this is a sensor-availability question, not a census one.
- `domain_coordinators.hvac`: "boot-settle released via TIMEOUT after 60s", x1. NEW. Boot-settle waited on the `idasen_desk` integration. Boot only.
- `weather_manager`: divergence 5.0°F, x1. NEW. Informational.
- `database`: "DB write queue peak: 28 items", x1. NEW. Single boot burst.
- `homeassistant.components.sensor`: universal_room_automation sensor platform setup over 10 s, x1. NEW. Boot timing.
- `helpers.frame` (URA-origin deprecations): `custom_components/universal_room_automation/__init__.py` line 5211 (`dev_reg2.devices.values()`) and line 5289 (`device_registry.async_get_device`). NEW in this scan. Removal is announced for HA 2027.8.0 and 2027.9.0. Follow-up for the operator, not a census issue.

Not this release, noted for the operator: the Envoy `reserve_soc` CRITICAL pages ("Envoy write reverted", commanded 90, hardware 30) were sent at 22:00 UTC, before the restart. The core was still in bootstrap at 22:07:30 UTC (`/api/config` state `NOT_RUNNING`, `idasen_desk` still pending at 22:07:42); the states read after that were live.

**Verdict:** PASS L1 (partial), L2, L7 (pre-restart), L8, L9; L3 PASS for `unknown` with `known` pending; L4, L5, L6 PENDING. The cycle is not closed until the PENDING rows are written back.

### Prospective criteria (superseded by the validated table above)

| # | Criterion | Evidence to read |
|---|---|---|
| L1 | Both awareness entities have numeric states equal to `sensor.universal_room_automation_persons_in_house` / `..._unidentified_persons_in_house` (F-LEAD off) | entity states, several reads over an hour |
| L2 | `switch.ura_crossing_vision_census_authority` present and `on` | entity state |
| L3 | With the shadow switch on: `crossing_ledger.state` reads `unknown` after the restart, then `known` after the first anchor | Outside: Open Tracks attribute |
| L4 | At least one `crossing_vision_ledger` term row with non-null `l_after` once the ledger is known | `memory_episodes` |
| L5 | The house census result carries non-null `aware_total` after the first census tick | `get_house_census("awareness")` via a diagnostics read, or the awareness entity state |
| L6 | Existing census fields equal their pre-deploy behaviour on a replayed hour; AWAY latency median / p90 unchanged against the P2-D0 (v) baseline | `census_snapshots`, `house_state_log` |
| L7 | At least one `ok` shadow row with `model = gpt-6-luna` after setting the provider option | `crossing_vision_shadow` rows |
| L8 | No `crossing_vision` / `census_deconflict` ERROR in the log; no page on day one | journald, NM log |
| L9 | No `automations.yaml` reference to the two new entities (P2-F1 checkpoint) | grep the HA config |

## Degraded configurations

- Enhanced census off: `census_tick` never runs, the ledger stays `unknown` (awareness = trust); the anchor-zero page
  is suppressed and the diagnostics say `anchor_zero_suppressed: no_census_tick` (review B-L5).
- No interior camera configured: the ledger is handed no body total (missing, never 0) and stays `unknown`.

## Not in this build

CD4 flips (F-LEAD, F-NOTIFY), P2-D8 fast stage, P2-D9 arrival record, P2-D10 metric sensors / grading, the scorer
(P2-D6), CD0 / P2-D0 probes. See the builder report for deviations and open questions.
