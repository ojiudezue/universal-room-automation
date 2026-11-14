# Review A (local correctness): census deconfliction P2 + crossing ledger

Branch `feature/census-deconfliction-p2-ledger` @ ed9229c5, base develop 3ec3f4d2 (verified `git merge-base develop HEAD`).
Framing A only: arithmetic, clamps, helpers, per-site. Repros below were run against the pure module
(`crossing_ledger.py` loaded standalone) with the shipped knob defaults where they matter.

Docs read: PLANNING_crossing_vision.md (§4 invariants, P2-D1..D3), PLANNING_census_deconfliction.md (§3.3, §4, CD1),
IDENTITY_FUSION_CAMERAS_MANUAL.md §5.5, the presence state of play and SENSOR_FLEET_CLASSES (presence-adjacent:
census inputs). No contradiction with the corrections ledgers found in the reviewed code.

Identity model: the ledger is an F3 consumer producing an F2-A count term; `deconflict_house` is the F2 deconfliction
function. Neither writes an F1/F2-T value (INV-P2-IDENTITY holds by inspection: `census_deconflict.py:118` copies the
trust union; `crossing_ledger.py` never names a person except the residency record id).

## Findings

### A-HIGH-1: the floor double-counts every resident arrival (Bug class #63, coincidental equality / concept split; plan-level)
`crossing_ledger.py:266-268` (floor `L = max(L, R)`) + `:303-305` (entry `L += n`).
Presence's resident arrival (geofence / BLE, F5) normally lands BEFORE the door crossing's ledger term (the term waits
for the vision outcome: TIMEOUT + EVENT_END_WAIT). The floor then raises L for the arriving resident and the entry term
adds them a second time.
Repro (defaults): anchored L = R = 1; census_tick R = 2 (resident B's arrival edge) -> floor L = 2; entry term n = 1
(B's door crossing, E after the anchor) -> L = 3; next tick `guest_vis = 1`. Ran: `(1, True)`.
Nothing discharges it except the next empty-house anchor, which needs 1 h of zero bodies with no rising edge, i.e.
usually never while anyone is awake at home. The anchor then records residue +1, so bar a (drift) fails on ordinary
traffic and F-LEAD can never qualify. After F-LEAD it is a false guest on every resident arrival.

### A-HIGH-2: the floor defeats the departure reconcile (same class; plan-level)
`crossing_ledger.py:266-268` + `:401-406`.
The reconcile window LEAD 900 s exists because the door exit term precedes the residency departure edge. Between the
two, every 30 s census tick re-floors L to the old R; when R then drops, the reconcile sees the exit term and cancels,
so nothing takes the floor's +1 back.
Repro (defaults): anchored L = R = 2; exit term E = 200 -> L = 1; tick at 290 with R still 2 -> L = 2; departure t_e =
500, R = 1; judge: `reason = exit_term`, `l_after = 2`; `guest_vis = 1`. Ran exactly that (`L_raw = 1` is right; `L` is wrong).
Any resident departure whose exit crossing lands more than one census interval before the presence departure edge,
which is the normal ordering, leaves a phantom guest.

Recommended fix (both HIGHs, needs a planner decision since §P2-D2 step 4 specifies the floor): do not mutate L with
the floor. `guest_vis = max(0, L - R)` already clamps the guest side, so the floor only matters for missed resident
entries; handle those with a floor credit instead. Track `floor_credit` (how much the floor raised L); an entry term
first consumes credit (no double add); an exit term in the departure window releases it. Or apply the floor only on a
rise of R and treat the matching entry term inside an arrival window (mirror of the departure reconcile) as already
counted. Required tests: `test_resident_arrival_before_entry_term_counted_once`,
`test_exit_term_before_departure_edge_no_phantom` (the two repros above, as tests).

### A-HIGH-3: P2-D1 deploy hazard: the empty option sends the Luna model to the perimeter provider
`crossing_vision.py:776-800` (`_provider_id`), `const.py` (rung-1 `CROSSING_VISION_PROVIDER_ID = "01M7B731T26P2HXVW77AQR62PP"`
deleted), `const.py:3549` `CROSSING_VISION_MODEL = "gpt-6-luna"`, call site `crossing_vision.py:864-871`.
On deploy the new option `crossing_vision_provider_id` is empty on this install (nobody has opened the options form),
so `_provider_id()` returns None and the call goes to the perimeter provider, while `model = gpt-6-luna` is still sent
and still stamped on every row (`:951`). Result: either every call errors on a model the perimeter entry does not serve
(error trip-wire, no `ok` rows, P2-D1 Live criterion fails) or rows claim `gpt-6-luna` that another model produced,
which poisons the one-model bar data P2-D1 exists to guarantee.
Fix: keep the Phase 1 install-presence fallback. When the option is empty, try the rung-1 Luna entry id and use it only
if it is an llmvision config entry on THIS install (the existing portability check); else None. Portability still holds
(another house never has that id). Add `test_empty_option_uses_install_present_default` next to
`test_empty_override_falls_back` (which should then cover "default absent on this install").

### A-MED-1: `camera_peak_count = 0` yields a 0-person term (builder question 2)
`crossing_ledger.py:111-112`. `_count(0)` is 0, so the fallback term is n = 0. `_sample_peak_person_count`
(`transit_validator.py:1307-1350`) can legally return 0 (a seeded or in-window 0 on the step-and-hold count sensor).
A direction-resolved crossing is at least one person, so: entry n = 0 loses the person and still sets
`_entry_since_sample` (blocks the anchor for no count); exit n = 0 is a missed exit.
Answer: term 1. Use `peak if peak else 1` (0 and None both mean "camera did not count it").

### A-MED-2: an entry term while unknown does not restart the anchor window (builder question 1)
`crossing_ledger.py:297-298` returns before `_entry_since_sample` is set. Repro: unknown, reset window 600 s, bodies 0,
entry crossing at 290 -> anchor fires at 600 with L = R = 0 (a guest standing outside camera coverage is lost; the
term was recorded with reason `unknown`). The window predicate is evidence of "nobody extra is inside"; an entry
crossing is direct evidence against it whatever the ledger state. Answer: yes, restart. Set `_entry_since_sample`
for every entry term (unknown or late included); it only delays the first anchor by one window after an entry.

### A-MED-3: no interior cameras gives a body total of 0, not missing (builder question 3)
`camera_census.py:2193-2195` (`not configured_interior` -> `camera_total = 0`) feeds `_last_house_camera_bodies = 0`
(`:2251-2253`). With no cameras the anchor's body leg is vacuously true and the ledger anchors on rising-edge silence
alone (a still guest is anchored away in an hour). Rule 5 says an absent source is missing, never zero.
Answer: None when `configured_interior` is empty (ledger stays unknown, case D). Same gap on the cross-validation-off
path: every entity unavailable gives `single_source_total = 0` and `all_platforms_unavailable` stays False
(`:2207-2240`); the dark latch mitigates only after its hysteresis. Set the flag there too when no entity was available.

### A-MED-4: one exit term cancels any number of departure reconciles
`crossing_ledger.py:402`. `any(lo <= e <= hi ...)` does not consume. Two residents leave, one exit term n = 1 (camera
counted one): both reconciles cancel, L stays one high. Also a guest's exit within 15 min before a resident departure
cancels that resident's reconcile. Fix: store `(e_ts, n)` and consume n across judged departures.

### A-LOW-1: enhanced census off -> ledger permanently unknown, anchor-zero LOW pages after 48 h
`camera_census.py:1808` gates `_apply_enhanced_house_census`, the only `census_tick` caller, so `_bodies` stays None.
The LOW page text ("Normal while someone is always home") misleads. Suppress the anchor-zero page when no
`census_tick` has ever arrived, or name the cause.

### A-LOW-2: builder question 4 (settle unused)
The only settle the ledger needs is the reconcile delay (TIMEOUT + EVENT_END_WAIT), consumed at
`crossing_vision.py` ledger construction -> `crossing_ledger.py:389`. The P2-D9 arrival-record settle is out of this
build's scope. I could not identify a different unused "settle" symbol in the diff; I would be guessing beyond this.
If it is a knob with no reader, label it "no runtime reader in this build" like the NOTIFY constants.

## Cleared (holds because)

- `deconflict_house` arithmetic: case thresholds match plan §3.3 for flag_min 1 (diff 0 -> A; 1 -> close; >1 ->
  disagree) and degrade sanely at 0 / negative. `aware_guests == guest_cam` whenever `vision_leads` False
  (`census_deconflict.py:117`), so INV-P2-AWARE-DECONFLICT holds for every input.
- Guest side max, not sum: `guest_terms_max` (`:83-87`); malformed / negative / bool terms drop out; all missing -> None
  -> case D.
- `aware_total == total_persons` at the dark default: `total = clamped_total = identified + clamped_unidentified`
  (`camera_census.py:6560-6562`) because `clamped_total >= identified_count`.
- R = max(residents_home, identified_count) (`camera_census.py:6612-6625`): one person on BLE and face is one slug in
  `recognized_set` (normalized union, `:6497-6502`) and max with presence counts them once. Error or missing presence
  -> identified_count. Pre-existing: the egress-identity-off fork unions un-normalized names (`:6504`), unchanged here.
- Unhealthy -> missing: `vis = guest_vis if healthy else None` (`camera_census.py:6676`); dark, None bodies, torn
  down, switch off, exception all reach case D. `census_tick` freshness: census 30 s (`const.py SCAN_INTERVAL_CENSUS`)
  < 2 x eval 120 s.
- Exit clamp at 0 with `L_raw` unclamped (`crossing_ledger.py:308-310`); late terms not applied and not blocking;
  reset `set_unknown` clears L, window and pending; anchor sets `t_start = now`, voids pending departures at or before
  it; `independent` flag correct (True at boot / after unknown / after an applied term or reconcile, False on
  back-to-back empty anchors).
- Latches: stuck pages once, re-arms at guest_vis 0 or None; anchor-zero pages once, re-armed by an anchor and by
  `rebase` on the enable edge.
- Clusters: same direction -> one term with the primary's count; mixed -> per-member camera terms, vision count
  never split; non entry/exit members dropped.
- `_last_house_camera_bodies` entry-reset at the top of `_calculate_house_census` (`camera_census.py:2013`).

## Verdict: FIX-REQUIRED

Must fix: A-HIGH-1 and A-HIGH-2 (plan step 4 floor, needs a planner ruling plus the two repro tests), A-HIGH-3
(install-presence fallback before deploy). Should fix in the same pass: A-MED-1..4.

| Severity | Found | Class |
|---|---|---|
| HIGH | 3 | #63 concept split (floor vs terms) x2; config default regression (deploy) |
| MEDIUM | 4 | fabricated zero (missing-as-0) x2; evidence not consumed; window gate gap |
| LOW | 2 | trip-wire false context; doc |
