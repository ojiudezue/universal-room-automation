# Worklog — October 2026 session (reconstructed 2026-10-14)

Reconstructed read-only from `git log` (URA repo + sibling `ha-health-monitor` repo),
`docs/readmes/README_v5.103.*.md`, `docs/planning/kanban.data.yaml`, and the session
transcript JSONL. Git commit hashes and version numbers are directly verified against
the live repo. Anything sourced only from commit-message narrative (not independently
confirmed against code/README/live state) is marked **(inferred)**.

Session window covered: roughly 2026-10-03 through 2026-10-14 (the URA `git log --since
2026-10-01` actually surfaces commits back to late September because several overnight
batches were dated late and corrected; the effective work described below runs through
commit `643a0f4fa`, 2026-10-14).

Two threads named in the task brief were initially searched for in `git log` / kanban only
and reported NOT FOUND — both are **HA-config-side actions** (Lovelace/automation/entity-
registry edits via `mcp__home-assistant__*` tools and a cross-session hand-off), not URA
code changes, so they never appear in `git log` or the kanban YAML. A second pass of the
session transcript JSONL (`c1688a6c-7043-4c5f-9bd2-ce6ec5c84bf8.jsonl`, grep `landscape`/`ELK`)
recovered both threads in full; see their write-ups below. Neither has a kanban card
(confirmed: `grep -ni "landscape\|elk" docs/planning/kanban.data.yaml docs/planning/KANBAN.md`
returns no thread-relevant hit — the lone `ElkM1` match in the YAML is an unrelated boot-loop-
stall incident note, not a card for this thread). **NO CARD** for either.

---

## 1. Chronological work log grouped by effort

### HVAC arc (W1-C P1/P2, Custom Preset Ranges, A1 high-draw stall)
- **W1-C P1** (thermostat definition / write-borrow-return, ecobee groundwork) — shipped v5.103.35/.36 era; `e521bd0bb` fix: W1-C P1 review fix-ups (order-robust release_hold test, exact allowlist counts). Kanban card `HVAC-W1-THERMOSTAT-DEFINITION` = **done**.
- **W1-C P2 (ecobee / HomeKit thin adapter)** — shipped **v5.103.40** (`d62fdb9a4`, "HVAC W1-C P2: ecobee (HomeKit) thin adapter") and **v5.103.41** (`8aa0f8c34`, "P2 option C: ecobee comfort select by default"), both merged as Tier 2-DB/Tier 3 with multiple review passes (`48839180b` Tier 2-DB+D fix pass; `8c7f9f7e6` Tier 3: 4 reviews + D re-pass). Kanban card `HVAC-W1C-GENERIC-THERMOSTAT-1` reconciled done at both versions.
- **HVAC Batch C — Custom Preset Ranges (CPR)** — shipped **v5.103.39** (`f87d9e8b9` feat, `baba5a7f2` merge: Tier 2-DB + D; default OFF, empty rollout). Fix-up `423477247` addressed Review D HIGH (would-write snapshot gate). Card `HVAC-CUSTOM-PRESET-RANGES-1` is in **waiting_me** lane as of the live board snapshot (i.e., a follow-on decision/verify step was still pending at session end, not a fresh build).
- **HVAC-A1 high-draw diagnostic off the event loop** — shipped **v5.103.56** (`b9ea92432`). HA Health Monitor flagged a ~2s event-loop stall on 11/12 HVAC ticks inside `OverrideArrester._refresh_a1_cache` → `_high_draw_time_s_7d` (re-walking 7 days of recorder history per zone on the event loop). Fix: moved to an executor worker (`_compute_high_draw_time_s_7d`), cached hourly (`HVAC_A1_HIGH_DRAW_REFRESH_S = 3600`). Tier 1-with-Tier-2-protocol (2 reviews, fix-ups drilled); full suite name-diff vs `7ef7551e0` clean (0 new/0 gone). Card `HVAC-A1-HIGHDRAW-PER-TICK-SCAN-1` closed in `a4f8c90cc`.
  - **README_v5.103.56.md has NO "Validated" results table** — only prospective "Live acceptance" bullets (HM no longer shows the stall post-restart; A1 attributes still populated; 0 URA errors). **This is a straggler: live validation was never written back.**
- Other HVAC items touched: `75b371795` fix (EC night release latch, cross-listed energy); `550d4de95` "EC daylight-gated rung horizon + poor-night WAIT drain floor (Tier 3)" — energy-adjacent, not pure HVAC.

### EC house-entity defaults (v5.103.55)
- Shipped **v5.103.55** (`570117210`, "Energy settings name roles, not brands; no house-specific entity defaults in code"). Card `EC-HOUSE-ENTITY-DEFAULTS-1`, 4 reviews + fix-ups drilled (`af57f3b49` merge). Multiple fix-up passes: `8c0ae2d96` (parent reload on mapping-change, value-normalized diff), `99b6f4327` (G1 completion: EVSE/DP-mains/cloud-stamp/pool roles, reload-safe pin), `4663b1f3a` (wire-in anchors + role-word scrub), `2df2d0572` (order-independent test fix).
- **README_v5.103.55.md HAS a filled-in "Validated 2026-10-13 (restart 11:31 CDT)" table** (confirmed by grep) — this one closed the loop properly.

### Review-lane ship (v5.103.49)
- **v5.103.49** (`415605360`, "Review-lane batch") bundled four independently-reviewed branches into one release: `fix/stuck-sensor-warn-once`, `fix/shutdown-db-write-fastfail`, `feature/ec-ev-toggle-tripwire-rebased`, `fix/test-bathroom-exhaust-collection`. Cards closed: `STUCK-SENSOR-WARNING-PER-TICK-1`, `SHUTDOWN-CENSUS-DB-WRITES-BLOCK-1`, `EC-EV-TOGGLE-TRIPWIRE-1`, `TEST-STRATEGY-REARCH-1`.
- `914309fce` README note: "shutdown fix judged at next restart" — i.e. the shutdown DB-write fast-fail could only be validated live on a subsequent restart, not at deploy time. **(partially deferred validation — see stragglers)**

### Presence / fan-noise / occupancy arc
- **v5.103.51** running-fan mmWave noise rejection (C1a-C5), Tier 2-DB: plan review + 3 reviews, `7b650279c` merge, suite name-diff 0 new.
- **v5.103.52** radar settings Phase A (ZK/ZX per-room block, send-on-save, reapply service) + night-light red-parity + plain-English sensor form — `d0bd5090e`.
- **v5.103.53** "Fan trust follows sensor capability; per-room radar settings; memory writers live again" (`3f821892c`) — bundles `OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1`, `URA-SENSOR-TUNING-1`, `MEMORY-WRITERS-SILENT-DROP-1`.
- **v5.103.54** "Running-fan release ignores radar motion bits; house state unknown (not away) at boot" (`51d2a7ec4`) — cards `D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1`, `HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1`.
  - **README_v5.103.54.md HAS a filled "Validated 2026-10-12 (restart 09:03 CDT)" table**: PASS rows for "Installed + restarted" (manifest v5.103.54), "Boot: 0 URA errors", "House state never away across restart" (cited entity history for `sensor.ura_presence_coordinator_presence_house_state`).
- Reference docs shipped alongside: `60de0aaae` PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md (canonical ground truth + corrections ledger), `16c5dc056` SENSOR_FLEET_CLASSES.md (Hobeian ZV=motion / ZK/ZX=presence), both wired into CLAUDE.md.

### Census / identity arc
- `07e9e3857` fix(census): canonicalize space/hyphen name forms (card `CENSUS-NAME-SPACE-DEDUP-1`, shipped v5.103.47).
- `da014347d` feat(census-inputs-first): D1 door-event quality + `peak_person_count` (shipped v5.103.39 bundle).
- Multiple census planning revisions (Rev 2 through Rev 5+) tracked through October, several NO-GO verdicts on hybrid-estimator and D0-replay approaches (`77d93379e` "census hybrid D0-REPLAY — NO-GO (door ledger quality)"). Several threads remain in **waiting_operator** (`CENSUS-GROUND-TRUTH-CSV-FIX-1`, `CENSUS-PATIO-THROUGH-GLASS-1`) and **pre_planning** (`CENSUS-ACCURACY-1`).

### Energy coordinator (EC) resilience / degraded-data / billing
- **EC degraded-data policy** phase 1, Tier 3 — `651c72cfc` feat, `b6ec1fdf4` merge (4 reviews + D re-pass; stream tier dormant), shipped v5.103.39. Follow-up fix-ups `ad6aaad44`, `9b8978fff` (Review-D M1/L2).
- **EC billing from meter counters** — shipped v5.103.45/.46 (`00d94b014`, `4136b7a93`), Tier 2-DB: plan + 2 plan re-reviews, 3 build reviews, orchestrator re-drill 29/29. A clock-leak in tests was caught and fixed (`4630fd008`: "review C-5 was claimed fixed but was not").
- **EC-EV-TOGGLE-TRIPWIRE-1** — shipped v5.103.49 (alert when strategy flip-flops an EVSE), and its own soak-exit surfaced the **EV-FILL-PRIORITY-SOC-CHATTER-1** finding (80% SOC boundary chatter, measured via `ura_activity_log` charger rows + Envoy SOC sensor, 2 of 7 logged days). That card is **waiting_operator** with an explicit A/B pick requested ("build the re-pause buffer" vs "accept") — unresolved as of session end.
- **EV-TRIPWIRE-TESTS-ORDER-DEPENDENT-1** (three EV flip-flop tripwire tests fail only in full-suite order) — still **in_progress** per the live board.
- `ROOM-ENERGY-SENSOR-MISPICKS-1` (several rooms read "energy today" from the wrong sensor) — **in_progress**, not shipped.
- `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1`, `ENERGY-CONSUMPTION-FORECAST-POISONED-1`, `DB-SIZE-GROWTH-1`, `COVERAGE-EVENING-ATTRIBUTION-DRIFT-1` — all **waiting_operator**, unresolved.

### Night-light arc
- Rev 3 action-rule shipped v5.103.42 (`af13bd33e`), Tier 2-DB (plan review + 3 reviews + fix pass). Off-path + house-Sleep colour fix shipped v5.103.43 (`445158e07`). Sleep-protection gate interaction fixed v5.103.44 (`a8e1a1b53`). `NIGHTLIGHT-SLEEP-ONSET-RECOLOUR-1` remains **waiting_operator**.

### Board / kanban dispositions and hygiene
- Large recurring pattern of `board: operator dispositions queued (N)` commits throughout the period — operator-side disposition buttons (done/deferred/declined) queued and applied each session start per the `ura-kanban` capture-first protocol. Final commit of the period, `643a0f4fa`, applies **73 operator dispositions** in one batch (acks + instructions) — the largest single disposition-apply commit in the log.
- `BOARD-CURRENCY-1` reconcile commits run after nearly every version ship (`5ecadb523`, `a4f8c90cc`, `3e4437eb1`, `8be341d86`, etc.) — the forcing-function ladder keeping the board in sync with shipped code.

### Study A Wi-Fi CSI (ESPectre) audit
- `a6ef49f88` "audit: Study A Wi-Fi CSI (ESPectre) sensor review — motion-class today" — a read-only audit, not a build. No corresponding kanban card title matched "CSI"/"ESPectre" directly in the live board scan; classified under the general Study A sensor thread (several `Study A`-tagged cards exist: `SAFETY-HAZARD-NEVER-CLEARS-1` waiting_operator, `SAFETY-HUMIDITY-JUNK-READING-1` done, `CENSUS-ACCURACY-1` pre_planning, `SCALE-LEAN-ROOM-PROFILE-1` done, `HVAC-HOLD-SIZING-ALL-ROOMS-1` done, `STUCK-SENSOR-1` parked). The audit's disposition (parked/carded/dropped) was not independently confirmed in this read-only pass — **(inferred: likely folded into the general sensor-fleet-classes doctrine, not independently verified)**.

### Health Monitor v2 / v2.1 (sibling repo `~/Code/ha-health-monitor`, branch `v2.1-wave1`)
This is a **separate repo with its own versioning (1.x → 2.x)**, not part of URA's version numbers. Working tree is clean; branch `v2.1-wave1` up to date with origin.
- v2.0.0: Phase 0 API verification (HA 2026.10.1), Phase 1 build (`b056e04`: loop-lag marker, setup-retry marker, repairs + fix flows, self-timing guardrails, v1 migration) through `1e2e44e` README_v2.0.0 + CHANGELOG.
- v2.1.0 (R7 as-built across W1-W20): 8 layers built sequentially — layer 2 (device state model: reachable/unreachable/off/disabled/long-gone), layer 3 (daily book + step detector), layer 4 (radio PHY sampler: UniFi/Matter/Z2M/OTBR), layer 5 (system health: disk/clock/CPU/DB-size/backup-age), layer 6 (Matter node availability), layer 7 (automation/script failures), layer 8 (export action + external long-term statistics), plus labels (configurable "off" label), power-link co-drop detection, baselines ("accept as normal") per integration/fleet/house, GC-pause timing wired into loop-lag attribution.
- Final commit of the visible window: `1b7f773` "docs: review fix-up recorded in README_v2.1.0 (finding table, final perf x3 + full-suite runs, 117-drill table), CHANGELOG, PLAN_v2 R7 W19-W20" — this reads as the cycle's closing documentation commit. Review findings 1-11 were applied across `424456b` through `3afb87a` (repair-flood cap, relay-detach repair, power-link co-drop scoring, fleet-index/baseline-tracking perf, perf gate with 20 fleets/21 baselines/300 off-labelled devices).
- This is the producer of the HVAC-A1 event-loop-stall finding consumed by the URA HVAC arc above — i.e. Health Monitor v2.1 is live and actively flagging real URA stalls (cross-repo evidence the tool works).
- **Not independently re-verified here**: whether v2.1.0 has itself been deployed/restarted live on the Wigton or Madrone HA instance, or is still sitting on `v2.1-wave1` awaiting merge/release. The README_v2.1.0 commit exists but no `ha-health-monitor` deploy/release-tag commit was seen in this scan. **(straggler — flagged below)**

### Sonoff R4M fleet
- Kanban card `SONOFF-R4M-MULTICAST-AB-1` ("Sonoff MINI R4M fleet drops to cloud/unavailable since 10-06, AP fw 8.8.11 — multicast A/B [test]") is in **waiting_me** lane — an A/B test was proposed/in motion but not resolved by session end. No corresponding git commit found (this is a diagnostics/config thread, not a code change) — **(inferred from kanban card only, not cross-verified against a live AP/network change)**.
- Related but distinct: `WIFI-SWITCH-DROPOUTS-BATHROOMS-1`, `MASTER-TOILET-SONOFF-DROPOUTS-1`, `WIFI-ACTUATOR-FLEET-FLAP-1` — all separate Wi-Fi-actuator-fleet cards, all **waiting_operator**, unresolved.

### Landscape lighting / 82-entity-disable batch (2026-10-13 night, found in transcript)
Pure HA-config work (no URA code, no kanban card — NO CARD) done live via `mcp__home-assistant__*`
tools against the Samba-mounted HA instance, during the same overnight window as the HVAC-A1
fix and Health Monitor v2.1 build.
- **Root problem:** two duplicate landscape-lighting automations existed — `automation.landscape_lighting_control`
  (native LIFX, alias "Landscape Lighting Control") and `automation.landscape_lighting_lifx_matter_version`
  (LIFX-via-Matter, originally titled "New automation") — both created by earlier Wi-Fi-flakiness
  workarounds, both still firing sunset-to-1AM.
- **Measurement before deciding (Config-First / Measure-Before-Build discipline):** compared the two
  paths' live dropout history via a direct read of `home-assistant_v2.db` (`scratchpad/lifx_cmp.py`) —
  the Matter path showed **62 dropouts vs 398 for native LIFX over the same 10 days** (measured
  2026-10-13), so Matter was kept as the one true automation.
- **Fix shipped:** disabled `automation.landscape_lighting_control` (native LIFX, kept-not-deleted,
  reversible). Added a retry loop to `automation.landscape_lighting_lifx_matter_version` (renamed
  "Landscape Lighting") via `ha_config_set_automation` + `python_transform`: after the on/off command,
  re-send to any light that didn't respond, up to 5 tries, to absorb Wi-Fi flakiness. Also dropped
  4 dead light targets from its action list (LIFX-over-Matter spots 4/5/8/9, Hampton spots 5/6,
  GK perimeter 2/6) that hadn't responded in 10 days — likely fixtures physically replaced with
  non-smart units whose old entities will never reconnect.
- **The 82-entity disable batch** was a separate, broader cleanup the operator approved ("I took
  your 'A' as a go-ahead") after a read-only inventory agent (dispatched as "Relay-to-bulb detach
  inventory") **disproved the standing relay theory** — no Shelly/Sonoff relay could be shown to
  cut power to any smart bulb; the dropouts were independent device failures, not switched circuits.
  All 82 were set `disabled_by: user` in the entity registry (reversible per-entity), zero failures,
  full list saved to `scratchpad/disabled_stragglers_2026-10-13.json`:
  | Group | Count |
  |---|---|
  | Landscape lights that never reconnected (Matter, Hampton, GK, native LIFX, local Tuya) | 14 |
  | SmartThings copies of LIFX spotlights (duplicate integration paths) | 9 |
  | Cloud Tuya lights that never reach HA, plus their night-light channels | 27 |
  | Govee Study table-lamp segments (lamp itself stayed enabled) | 15 |
  | Status LEDs, kiosk LEDs, Meross do-not-disturb lights, unused Inovelli light channels | 17 |
  | **Total** | **82** |
  Explicitly left alone: local Tuya lights on circuits that are switched off (dining, patio,
  kitchen-dining, balcony) and 5 one-off devices, per prior agreement with the operator.
- **Live validation:** none beyond the zero-failure disable-call confirmation and the measured
  62-vs-398 dropout comparison that justified the automation choice — this was a same-night
  config action, not a code cycle, so there's no README write-back and no further "did it hold"
  check was run in this transcript. **Straggler: no multi-night confirmation that the retry-loop
  automation actually eliminated recurring landscape dropouts** — only the pre-fix 10-day baseline
  was measured, not a post-fix window.

### ELK M1 handoff (2026-10-14 ~01:00, found in transcript)
A cross-session hand-off (from another live Claude session, "Homelab 925", via the cross-session
socket `uds:/tmp/cc-socks/92524.sock`) at 2026-10-14T01:04. Operator-approved decision stated in
the hand-off: **keep the ELK M1 alarm panel, fix the HA-side `elkm1` integration, do NOT switch to
Konnected.** Pure HA-config / diagnostics work — no URA code touched, no kanban card (NO CARD).
- **Request:** make the ELK M1 controls usable in HA; the `elkm1` config entry ("ElkM1") was loaded
  but under-configured.
- **This session (URA/Claude Code side) stopped and flagged a live safety condition before touching
  anything:** `alarm_control_panel.elkm1_area_1` was not merely "triggered" — it reported
  `alarm_state: fire_alarm`, disarmed, "not ready to arm," since 11:36 that morning (5 minutes after
  an HA restart), which pointed at HA having picked up a pre-existing alarm condition from the panel
  rather than a live intrusion.
- **Root-caused via direct zone read (no fabrication — verified against the live `elkm1` entities,
  not inferred):** the fire alarm traced to **zone 7, the Kitchen Heat Detector** — `sensor.elkm1_kitchen_heat_det`
  reporting `physical_status: short`, `logical: violated`, `triggered_alarm: true`. The sibling heat
  zone (zone 8, Garage A/B) was normal, ruling out a panel-wide fault. This refuted the operator's
  working theory (relayed via the cross-session hand-off) that the trigger was a keypad the
  integration didn't understand.
- **Action taken:** none to the ELK panel itself. The finding was sent back over the cross-session
  socket ("ELK triggered = heat zone 7 short") and all ELK changes were explicitly held pending
  operator review of the heat-detector short.
- **Still open / straggler:** the actual HA-side integration fix requested in the hand-off (making
  ELK M1 controls usable in HA) was **not started** — the session's entire ELK engagement was
  diagnostic triage of the live fire-alarm condition that surfaced on first contact. The zone-7
  short needs physical inspection/repair before any further ELK/HA config work is safe to resume.
  Per the 2026-10-14 resume memo (`project_session_pickup_2026_10_14.md`), this is carried forward
  as "waiting on operator: ELK heat detector" — still no kanban card exists for it.

### Memory roadmap / writers
- `MEMORY-WRITERS-SILENT-DROP-1` shipped in v5.103.53 (`862a6f8c7`, `951ea523f`): fixed `async_create_background_task` missing `name=`, added `fan_recheck_outcome` + weekly writer-health trip-wire.
- `9667cece1` "v5.103.53 live validation; memory roadmap card closed" — a broader "memory roadmap" card was closed at this point, consistent with the large back-catalog of `done` memory-thread cards visible on the live board (`MEMORY-PROGRAM-EPIC`, `MEMORY-COMPACTOR-1`, `MEMORY-FIRST-DIAGNOSTICS-1`, `MEMORY-RETRO-VALUE-1`, `MEMORY-WRITERS-1`, all status=**done**). `MEMORY-ZONE-PHANTOM-WRITER-1` remains **parked**.

---

## 2. STRAGGLERS table

| Item | Thread | Owner | Kanban card | Notes/evidence |
|---|---|---|---|---|
| README_v5.103.56 has no "Validated" results table, only prospective "Live acceptance" bullets | HVAC-A1 high-draw stall fix | me | HVAC-A1-HIGHDRAW-PER-TICK-SCAN-1 (card closed, but README write-back incomplete per CLAUDE.md mandatory rule) | Confirmed via `grep -n "Validated\|Live" docs/readmes/README_v5.103.56.md` — only "## Live acceptance" with bullet list, no PASS/FAIL table |
| EV fill-priority 80% SOC chatter — operator PICK requested (A: build re-pause buffer, Tier 2-DB / B: accept) | Energy / EV | operator | EV-FILL-PRIORITY-SOC-CHATTER-1 | status=waiting_operator; `next:` field explicitly asks operator to pick A or B |
| Landscape lighting retry-loop fix (Matter automation, 5x retries) has no post-fix multi-night dropout check — only the pre-fix 10-day baseline (62 vs 398) was measured | HA config (landscape automations + 82-entity disable) | me | NO CARD | Found via transcript second pass (`c1688a6c-...jsonl`, `landscape` grep, lines ~59173-59542); pure HA-config action, never carded; no README/validation surface exists for this kind of change |
| ELK M1 handoff: HA-side `elkm1` integration fix (the actual request) never started — session triaged a live `fire_alarm` state instead and found zone 7 (Kitchen Heat Detector) reporting `physical_status: short`; all ELK changes held pending operator review of the short | Security / ELK M1 | operator | NO CARD | Found via transcript second pass (`landscape`/`ELK` grep, lines ~59670-59758); cross-session hand-off at 2026-10-14T01:04 from "Homelab 925"; carried forward in `project_session_pickup_2026_10_14.md` as "waiting on operator: ELK heat detector" |
| Three EV tripwire tests fail only in full-suite order (pass isolated) | Energy / test infra | me | EV-TRIPWIRE-TESTS-ORDER-DEPENDENT-1 | status=in_progress on live board |
| Several rooms read "energy today" from wrong sensor (radar field / export co-mingled) | Energy sensors | me | ROOM-ENERGY-SENSOR-MISPICKS-1 | status=in_progress on live board |
| Shutdown DB fast-fail "judged at next restart" — not validated at deploy time | Unload/shutdown hygiene | me | UNLOAD-SYMMETRY-TASK-HYGIENE-1 (in_progress) | commit `914309fce`: "README v5.103.49: deploy-restart note (shutdown fix judged at next restart)" |
| Optimization Coordinator stuck-sensor generalization (all device kinds, not room-scoped) | OC / diagnostics | me | OC-STUCK-SENSOR-GENERALIZE-1 | status=review on live board — built, awaiting review disposition |
| HVAC Batch C Custom Preset Ranges — follow-on decision pending | HVAC | me/operator | HVAC-CUSTOM-PRESET-RANGES-1 | status=waiting_me on live board (shipped v5.103.39 but a next-step is still parked on me) |
| Sonoff R4M multicast A/B test | Network/fleet diagnostics | me | SONOFF-R4M-MULTICAST-AB-1 | status=waiting_me; no git commit found — diagnostics-only thread |
| ha-health-monitor v2.1.0 — README/CHANGELOG committed, but no confirmed live deploy/restart on either HA instance | Health Monitor | me/operator | NO CARD (lives in sibling repo, outside URA kanban) | git status clean on branch `v2.1-wave1`; no release-tag or deploy commit observed in this scan |
| Landscape lighting / 82-entity-disable batch | Unknown | unknown | NO CARD | Not found in URA git log, kanban.data.yaml, or docs/planning/ for this period — possible capture-first miss or wrong-repo work |
| ELK M1 handoff | Unknown | unknown | NO CARD | Not found anywhere in the searched surfaces for this period |
| Study A Wi-Fi CSI (ESPectre) audit disposition | Sensor fleet | operator | NO CARD matched directly ("CSI"/"ESPectre" not in kanban text) | Audit commit `a6ef49f88` exists; its disposition (park/drop/build) not independently confirmed against a specific card in this pass |
| 46 (historically) `shipped_organic` cards and soak-exit backlog — general organic-lane hygiene | Cross-cutting | me | multiple (see `waiting_operator` list) | Per CLAUDE.md "Soak Exit" policy, organic cards need bounded-window disposal; this pass did not re-audit the full organic lane count |
| Large `waiting_operator` backlog (41 cards observed live, e.g. BOND-BRIDGE-UNRESPONSIVE-1, FRONT-DOOR-LOCK-OFFLINE-1, RECORDER-BLOAT-LOGFLOOD-1, DB-SIZE-GROWTH-1, HA-2027-DEPRECATIONS-URA-1, WIGTON-HA-UNRESPONSIVE-1, PERIMETER-ALERT-VOLUME-FATIGUE-1, and others) | Cross-cutting | operator | see list in §1 "waiting_operator" scan | Live board scan via `yaml.safe_load`; each card is an open cross-session handoff awaiting operator input/decision |
| Uncommitted/untracked files at present | Repo hygiene | me/operator | NO CARD | `git status`: modified `.vibememo/counseling.jsonl`, modified `docs/planning/KANBAN.md`; untracked `.claude/mcp.json.bak-20261001`, `.claude/tmp/` |
| CENSUS-GROUND-TRUTH-CSV-FIX-1 — ground-truth fixture carries truth operator has since corrected | Census | operator | CENSUS-GROUND-TRUTH-CSV-FIX-1 | status=waiting_operator |
| CENSUS-ACCURACY-1 — interior census accuracy (decay vs guest hysteresis) | Census | operator/me | CENSUS-ACCURACY-1 | status=pre_planning (not yet scoped) |

---

**Verification note:** all commit hashes and version strings above were read directly
from `git log --since=2026-10-01 --oneline` in `/Users/okosisi/Code/universal-room-automation`
and from `ha-health-monitor`'s `git log`. README validation-table presence/absence was
grep-verified directly against the files named. Kanban card statuses were read directly
from `docs/planning/kanban.data.yaml` via a Python/yaml parse at the time of this
reconstruction (2026-10-14) — lane assignments may have moved since if further work
happened after this read.

---

## 3. Continuation 2026-10-14 → 2026-10-21 (written 2026-10-21; the log had lapsed for a week)

Sources: `git log --since=2026-10-14` commit subjects (verified), README headings (grep-verified), and
this session's own work. Per-release detail lives in each `README_v5.103.N.md`; this is the index.

### Releases (verified commit subjects)
- **v5.103.57** never-fires sensor detector, EC field clearing, shutdown DB hygiene · **.58/.59** boot stalls removed (deprecated `config_entries`, room-area lookup, camera scan) · **.60** bathroom exhaust smell rule
- **.61** safety hazards clear on recovery · **.62** CPR settle gate · **.63** EV fill-priority re-pause buffer · **.64** exit naming / late names · **.65** safety re-page after ack (README title mislabelled "v5.103.63")
- **EC storm/reserve arc:** .66 reserve write governor · .67 outage ledger · .68 storm Stage A · .69 Stage B+C · .70 Stage E · .74 reserve check reads live Envoy sensor
- **.71** five Tier-1 fixes · **.72** house state sleep mask/BLE memory · **.73** fan recheck in bedrooms/media by day · **.75** paused rooms stop lights/fans
- **Billing:** .76 SmartHub bill check + 365-day room history · .77 cycle-day setting reaches engine · .79 bill prediction from SmartHub cost
- **.78** diagnostic sensors stop rewriting unchanged info · **.80** four NM calls that never delivered · **.81** EC shutdown save (validated 15:45 restart)
- **.82** daily solar from the production-CT counter (card EC-SOLAR-LIFETIME-COUNTER-FLAP-1; daily rows pending 10-22/10-23)
- **.83** occupancy anomaly on a room dwell model (BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1; 7-day replay due 10-28)

### Non-URA-code work (2026-10-21) — no git trail in URA
- **Halo** (`~/Code/halo-panels`) 0.1.1 live, 7 panels incl. Study A; HomeLab bridge 1.7.0 on all panels (colour/effect reporting).
- **HA config:** 3 MQTT "-kiosk" devices removed; `wallpanel_fleet_force_off_secure` retargeted to the 7 ESPHome screen lights (backup in `ura-v8-backups/`).
- **Bermuda offsets** (calibration2): Foyer proxy +3→0, Entry panel 0→-3, BP1_A +3→+6, Study A panel 0→+3. Re-measure due 10-22 19:13.
- **Ollama workstation** back (192.168.13.62, ~16 GB GPU); pulled `glm4:9b`, `deepseek-r1:14b`.

### Docs / decisions
- Audits: predictions (no prediction both useful and correct; arrival-not-dwell), room memory + coordinator request APIs.
- **OC vision rev 5 approved** (agent-first, R0-R3 tiers, P1-P5 promotable types, tool exclusions, $25/mo cap, 1-week R0, slice 0 model eval next).

### Stragglers found by this pass
| Item | Owner | Note |
|---|---|---|
| README_v5.103.62, .63 (EV buffer), .65, .67, .68 lack a `Validated` table | me | prospective-only; write back from DB/log one-shot |
| README_v5.103.65 title says v5.103.63 | me | one-line fix |
| Timed checks 10-22 07:17, 10-22 19:13, 10-23 07:19, 10-28 10:23 | me | session crons + on cards |
| Worklog lapsed 10-14→10-21 | me | keep appending at each ship batch |

### 2026-10-24 evening (after v5.103.89)
**Shipped live, no code:** Enphase Realtime integration enabled (MQTT add-on stays off); HM `gc_refreeze_h` 0→4 (early: stalls 50→1/h; re-read due ~10-25 08:00).
**Merged to develop, ships next deploy:** EV toggle tripwire diagnostic-only, no page (`EV_TOGGLE_TRIPWIRE_NOTIFY_ENABLED=False`, d8d98548d). Operator: "I don't want to be paged at all about EV".
**In review → deploy gate:** PERSON-BLE-WINS-OVER-STALE-GPS-1 on `fix/presence-gps-assistive` (749162ec4). GPS assistive, BLE leads (switch `BLE Leads Home/Away`, default on; arm 360 s at ≥30 Bermuda proxies). Plan rev 3 + plan review (2 rounds), consequence replay, build, reviews A SHIP / B decision / C 56/62 RED → fix-up 17/17 RED, orchestrator gate mutation 26 RED. Full-suite name-diff running. Pending operator: B-H1/H2 (home without phone → away/false guest) A=accept (default) / B=garage guard.
**Found:** Oji's companion app sends no new location (re-sends the 14:03 fix); old duplicate mobile_app registration deleted by operator. Frigate labels Jaya as Oji (FRIGATE-FACE-MISLABEL-OJI-1, operator retrain). `sensor.persons`=4 is Spook's configured-person count, not occupancy. In-house unidentified flicker 0-2 at 19:50-20:09 (interior only; exterior 0).
**Cards:** PERSON-BLE-WINS-OVER-STALE-GPS-1, FRIGATE-FACE-MISLABEL-OJI-1, CENSUS-UNIDENTIFIED-SNAPSHOT-1 (inbox).

## Release index (auto-appended at deploy)

- 2026-10-24 07:04 **v5.103.87** — v5.103.87: daily solar forecast restored, regime next-room check made real, work log at ship (cards: EC-PREDICTOR-SOLCAST-UNWIRED-1,REGIME-NEXT-ROOM-ACCURACY-JSON-COMPARE-1,WORKLOG-APPEND-AT-SHIP-1)
- 2026-10-24 07:44 **v5.103.88** — v5.103.88: a life-safety alert keeps the notification slot (cards: NM-MULTI-ALERT-TRACKING-1)
- 2026-10-24 14:01 **v5.103.89** — v5.103.89: Envoy reserve oracle phase 2 + Halo panel channel (off by default) (cards: EC-ENPHASE-CONNECTIVITY-RESILIENCE-1,WALLPANEL-URA-NOTIFY-1,NM-MULTI-ALERT-TRACKING-1)
