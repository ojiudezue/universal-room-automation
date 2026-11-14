# DRAFT: census deconfliction + crossing ledger (ships dark)

Branch `feature/census-deconfliction-p2-ledger` (from develop 3ec3f4d2). Version assigned at deploy. Tier 3: four
code reviews, orchestrator re-grep and mutation, operator checkpoint before deploy.

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
  room sensor held on or dead-holding, no rising edge, no entry term, for 30 min -> the ledger resets to the residents
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
- **Switch label (review B-L6).** `switch.ura_crossing_vision_census_authority` friendly name is pending the operator;
  proposed "Vision Leads Counts".

## Operator actions at deploy

1. Optional: set "Door count AI provider ID". Empty uses the Luna entry on this house already.
2. Leave `switch.ura_crossing_vision_census_authority` ON (shipped default).
3. Optional (plan §3.6): repoint headline "people" cards to the awareness entities; keep the trust entities on a
   diagnostics card. No house-visible change until F-LEAD.

## Live acceptance (prospective; write the observed results back after the restart)

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
