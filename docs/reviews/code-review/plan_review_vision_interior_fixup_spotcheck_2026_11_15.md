# Plan review: interior vision sightings, fix-up spot-check (last Tier 3 plan gate), 2026-11-15

Diff: `git diff adee0d3a 8e1f0e27 -- docs/planning/PLANNING_vision_interior_sightings.md` (develop; ship 3b merged as
v5.108.25). Driver: `plan_review_vision_interior_closure_2026_11_15.md`. Read only. Presence/identity docs not re-read in
full; no finding rests on a sensor-class or ledger claim. HVAC not touched.

**Verdict: PLAN-FIX-REQUIRED.** 0 CRITICAL, 0 HIGH, 1 MEDIUM, 3 LOW. All 19 closure findings (N1-N9, E1, L-1..L-8) are
addressed in the text. One MEDIUM: §9.D4 still says the interior term travels as `extra_guest_terms={"interior": term}`,
which in the real function goes into `vis`. That contradicts the new lower-bound rule and brings N2 back at admission
alone. The fix is a few sentences.

## 1. Closure check

| Finding | Verdict | Evidence |
|---|---|---|
| N1 | CLOSED | `frigate_member` `domain_coordinators/camera_stream_health.py:880`, `own_camera_entity_for_device` `:744`, `entity_stream_view` `:1201`, `physical_camera_dead` `camera_twin_health.py:1165` all exist on develop. LIVE is defined by §7 per member. The rule, INV-IV-MISSING extension, D2/D3 tests and a mutation are present |
| N2 | RULE CLOSED, TRANSPORT OPEN | see M-1 |
| N3 | CLOSED | `_stream_last_reading` exists (`camera_census.py:1516`, written `:2815-2817`, read `:2836`; the plan's `:2804/:2825` cites are off by about 11 lines, harmless). Platform from the registry; one group per area asserted in D0(a) |
| N4 | CLOSED | one definition in §8b (ANY group, debounced, knob, LIVE→None is a change); D0(i); D2 Verify aligned |
| N5 | CLOSED | one placement per slug before the union, BLE ACTIVE else newest fresh face; well defined, because a BLE person is in one room. A BLE room with no camera means the slug is subtracted nowhere, which is correct. `persons_in_room` is NEW (only `get_persons_in_room`, `person_coordinator.py:2498`, exists); §14 pins the return type `tuple[str, ...]` and `active_only` = `TRACKING_STATUS_ACTIVE`; the union goes through `person_ids.slug_of` |
| N6 | CLOSED | cumulative chain windows, missed-camera continuation, `INTERIOR_TIMELAPSE_MAX_HOPS`, live-chain test |
| N7 | CLOSED (L-a) | `_layer_guard_engine.py` walks every module (`rglob("*.py")` `:1259`) as AST with `rel` per file, so an `ast.Attribute`/`Subscript` load check with a module exemption is the same shape as R7 (`:914-935`). 0 existing `.affect` / `["affect"]` hits, so no false positives. Reply excludes affect except `operator_affect` |
| N8 / Q2 | CLOSED (L-b) | `_is_authorized_to_ack` `domain_coordinators/notification_manager.py:3447`: `CONF_NM_SECURITY_ACK_PERSONS`, else first `CONF_NM_PERSONS[].CONF_NM_PERSON_ENTITY` — matches the plan's description |
| N9 | CLOSED | reserve knob, skip reason, test |
| E1 | CLOSED | §13 non-goal with revival trigger, carded, sighting §15.8 edit |
| L-1..L-8 | CLOSED | each present at the cited section |

## 2. Q1 + N2 truth table against `deconflict_house` (`census_deconflict.py:90-131`)

Develop: `guest_cam = unidentified_count`; `vis = guest_terms_max({"ledger": guest_vis, **extra_guest_terms})` (`:105`);
`aware = vis if vision_leads else guest_cam` (`:117`); trust returned unchanged.

With the rule as stated (base = develop's value, interior outside `vis`, `aware = max(base, interior)` only when admitted
AND `interior_leads` AND interior not None), every row holds:

| Row | Can it lower aware_guests? | Trust view |
|---|---|---|
| 1 not admitted | no (no pull) | unchanged |
| 2 admitted, interior leads False | no, if interior is outside `vis` | unchanged |
| 3 L False, IL True | no: max(guest_cam, interior) ≥ guest_cam | unchanged |
| 4 L True, ledger present | no: max(ledger, interior) ≥ ledger = develop | unchanged |
| 5 L True, ledger None | no: max(guest_cam, interior); N2 repro 2 → 2 | unchanged |
| 6 interior None | no | unchanged |

Double counting: a guest seen at a door (ledger) and by an interior camera is combined by max, never a sum, so the guest
counts once. The worst case is an undercount, which is accepted for a lower bound. `aware_total = identified +
aware` rises with `aware_guests`; `unidentified_count` and the trust fields are untouched.

### M-1 (MEDIUM, must fix): the transport sentence contradicts the rule and brings N2 back at admission

§9.D4 Formula (plan :526) and §3 (:48), §5 (:134) and the H1 row (:766) say the term is "passed as
`extra_guest_terms={"interior": term}`". In the real function every `extra_guest_terms` entry enters `vis`
(`census_deconflict.py:105`). A builder who follows that sentence gets the following repro, with only
`INTERIOR_VISION_TERM_ADMITTED` True: it is a reviewed const edit, NOT the Tier-3 flip. Set L True, ledger None (unhealthy), `guest_cam` 2, all
interior groups LIVE and empty (interior 0), `interior_leads` False. Then `vis` = 0 and `aware_guests` = 0. Row 2 says "as
develop" (2). This is the N2 defect, now reachable before the flip checkpoint.

A related gap: row 2 says admission gives "case, agreement, provenance (display)", and the Live bullet says "`aware_agreement`
reflects interior". Develop computes all three from `vis` vs `guest_cam`. If interior is outside `vis`, the plan does not say how
interior affects them, or what `case` and `count_provenance` are when interior raises the count (row 5: is case
`CASE_ONE_MISSING`? is provenance vision?).

Fix: give interior its own keyword, for example `deconflict_house(..., interior_term=None, interior_leads=False)`, never
inside `extra_guest_terms` (or state that `deconflict_house` drops the `"interior"` key before `vis`). Then rewrite :48, :134, :526
and :766 to match. Define the display fields: either keep `case`/`aware_agreement`/`count_provenance` byte-identical to develop
and put interior's agreement in diagnostics only, or give the formula for them. Add a `test_truth_table` row-2 case with ledger
None and interior 0, and the mutation "route interior through `extra_guest_terms`" → red.

## 3. Other checks

- **New knobs (§12):** `INTERIOR_VISION_TERM_LEADS`, `INTERIOR_VISION_STATIC_DEBOUNCE_S`, `INTERIOR_DESCRIBE_RESERVED_CALLS`,
  `select.ura_interior_describe_access`, `INTERIOR_DESCRIBE_NM_COOLDOWN_S`, `INTERIOR_TIMELAPSE_MAX_HOPS`,
  `INTERIOR_FRAMES_LEFT_CHECK_ENABLED`: each has a name, a rung, a default, a reason and an off value. 0 code hits for each new
  name (NEW is correct). PASS.
- **One clean document:** apart from M-1 (old transport text left beside the new rule), there are no layered overrides.
  "draft 3" appears only as the labelled Q1/Q2 alternatives. The closure ledger is appended as a resolution table, not as
  spec text. PASS after M-1.

## 4. LOW (fix in the same edit)

- **L-a.** The `FORBIDDEN_ATTR_READS` check can be evaded through `getattr(desc, "affect")`, `dataclasses.asdict(desc)` or
  `vars(desc)`. Either state that the rule also matches `getattr(_, "affect")` constant-string calls, or accept and record
  the residual.
- **L-b.** If `_is_authorized_to_ack` is called directly it returns `(True, "any")` for any non-security hazard
  (`notification_manager.py:3458-3459`). A builder who "reuses" it for describe would allow everyone. State: factor out the
  operator resolution (`:3460-3466`) into a helper and do not call `_is_authorized_to_ack`. Also say the requester is compared as a
  `CONF_NM_PERSON_ENTITY` value. `test_describe_access_default_operator_only` catches the mistake, so this stays LOW.
- **L-c.** The Select option `residents` is not defined (NM persons? residents in the census roster?). Give it one line.

## 5. Must fix before approval

M-1. Fold in L-a..L-c. Once M-1 is fixed, the plan is PLAN-APPROVE-READY without another full review. A one-line
orchestrator re-grep of the transport sentences is enough.

| Severity | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 (M-1) |
| LOW | 3 |

Bug classes: concept split / incomplete edit (#63/#53: rule changed, transport text not) for M-1; hollow-guard residual (#62)
for L-a; reuse-the-wrong-primitive for L-b.
