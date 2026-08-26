# PLANNING: HVAC Excursion-Restore Unified Cycle

**Status:** plan-reviewed (both framing-disjoint plan reviews applied
2026-08-26; ready for build dispatch).
**Tier assessment:** **Tier 3** — see §Tier Justification. Requires 4
framing-disjoint reviews (A local correctness, B integration/state-machine,
C per-site source-mutation test authority, D adversarial completeness /
diff-blind), the last including PRE-EXISTING code.
**Consolidates cards (kanban.data.yaml):**

- `BORROW-BANKING-LEASE-NOT-RELEASED-1` (line 2901) — banking excursions
  begin, never end.
- `HVAC-MANUAL-PRESET-CONTRACT-1` (line 9677) — sanctioned raw-setpoint
  writers do not return the zone to a preset; `should_change_preset`
  self-lockout on `manual`.
- `S14-CEILING-NEEDS-AN-ENDING-1` (line 9559) — off-phase ceiling hold has
  no exit; operator (2026-08-21) chose "give it an ending" migrated as a
  BORROW KIND with computed `duration_s`.

The three cards are one family: **every raw-setpoint excursion in this
codebase must end at a bounded time AND return the zone to a preset, AND
the preset manager must be able to recover a `manual` zone that no
excursion currently owns.** The three symptoms are three failure modes of
one missing invariant.

---

## Falsifiable Invariant

> **For every zone at every time t:**
> **either** the zone is `preset != manual` (governed by the preset
> manager);
> **or** there exists a live `ExcursionToken` (row in
> `hvac_excursion_state`) whose `zone_id == zone` and whose age <
> `duration_s + EXCURSION_LEASE_SLACK_S` (bounded by
> `EXCURSION_LEASE_MAX_S`);
> **or** the zone is under a documented manual-immunity condition
> (freshly-observed operator adjustment within `_suppress_kind` TTL — the
> arrester's grace period).

Equivalently: a zone in `preset == manual` with **no** live excursion row
AND **no** in-flight arrester grace is a violation. If any legal
config-and-state produces that condition, this cycle has failed and D
must falsify.

The invariant has TWO producer duties (both must hold):

1. **BOUNDED-END:** every sanctioned raw-setpoint writer opens an
   `ExcursionToken` at begin and closes it via `return_excursion` at end;
   the token has a `duration_s` or falls under `EXCURSION_LEASE_MAX_S`.
2. **PRESET-RESTORE:** every `return_excursion` on a kind that induced
   `manual` writes a preset (via `emit_set_preset_mode`) as part of its
   restore sequence.

AND one consumer duty:

3. **RECOVERY:** the house-state preset-apply tick recovers a `manual`
   zone when NO excursion row is live for that zone AND the arrester
   `_suppress_kind` grace is not in effect. The gate lives at the tick
   call-site (`hvac.py` `_apply_house_state_presets`), NOT inside
   `should_change_preset` — see D3 CRIT-1 resolution.

---

## Institutional Context Verified

### Cards & prior planning read (full)

- `docs/planning/kanban.data.yaml` — the three subject cards read
  end-to-end (line 2901 banking; line 9559 S14; line 9677 manual-preset)
  plus the sibling `HVAC-PRESET-FLAP-1` context they reference.
- `docs/planning/PLANNING_hvac_governed_excursion.md` — the shipped
  primitive; this cycle CONSUMES it. Notes §12 parked-plan trigger for
  S14: "if the operator wants the ceiling to self-release, that is a
  separate card that re-litigates PRESET-FLAP-1" — this cycle is that
  separate card, operator-approved 2026-08-21.
- `docs/planning/PLANNING_preset_flap_offphase_honesty.md` — encodes the
  S14 no-release behaviour BY DESIGN at :184-195, live acceptance
  criterion :280 asserting no follow-on restore write fires, and shipped
  test `test_ceiling_held_until_next_preset_transition`. **All three
  artifacts must be overturned deliberately and visibly** (see D4).

### Code read (line numbers verified via git-grep 2026-08-26)

- `custom_components/universal_room_automation/domain_coordinators/hvac_excursion.py`
  end-to-end (module docstring §1-56; `EXCURSION_LEASE_SLACK_S=30` at
  :71; `EXCURSION_LEASE_MAX_S=7200` at :76; `EXCURSION_KIND` enum at
  :87; `begin_excursion` def :589; `return_excursion` def :694;
  `async_startup_excursion_audit` around :884-993 including the
  NUDGE-only preset restore at :941-985 with `emit_set_preset_mode`
  call at :954).
- `hvac_setpoint.py`: `emit_set_temperature` def :121;
  `emit_set_preset_mode` def :180.
- `hvac.py`: `_apply_house_state_presets` def :1550 (called bare at
  :1463 inside the main sweep); S1 house-state preset writer
  `emit_set_preset_mode` at :2152; vacancy bypass at :2031 (RH3);
  `should_change_preset` sole call at :2035; S10 (DPM) apply
  `emit_set_temperature` at :2445; S14 ceiling emit
  `emit_set_temperature` at :3149.
- `hvac_override.py`: `SUPPRESS_TTL_SECONDS=5` at :128;
  `_suppress_kind` dict at :218; suppress helper set at :2624 with
  `_suppress_kind[entity_id]=kind` at :2626; the mid-window
  manual-passthrough consumer around :2321; `emit_set_temperature`
  sites: :3125 (S3 pre-nudge), :4155 (S5 soft-nudge perform),
  :4327 (S6-family soft-nudge restore), :5539 (cancel_nudge restore,
  `kind="temp"`), :5914 (**startup ramp audit restore**,
  `site="S9_startup_ramp_audit_restore"`, `kind="temp"` suppression at
  :5906 — MISSED by the prior draft; sanctioned writer, no preset
  restore today). `emit_set_preset_mode` sites: :3279, :3845, :4364,
  :5565.
- `hvac_preset.py`: `should_change_preset(current_preset, target_preset)`
  def at :202; the `if current_preset == "manual": return False`
  self-lockout at :215. Pure two-string function that CANNOT consult
  provenance even in principle.
- `hvac_predict.py`: `emit_set_temperature` at :958 (S11 solar
  banking), :1109 (S12 pre-cool), :1393 (S13 pre-heat), :1456
  (predictive follow-up write). `begin_excursion` calls at :1074
  (BANKING) and :1360 (PREHEAT). Grep confirms ZERO
  `emit_set_preset_mode` calls in the module.
- `hvac_egress.py`: `emit_set_preset_mode` at :795 (egress restore).
  `begin_excursion(EGRESS_PAUSE)` at :654.

### Design docs

- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md`,
  `docs/Coordinator/HVAC_COORDINATOR_MANUAL.md` — reviewed for the
  preset-vs-manual contract and the arrester's role.

### Grep results (per Producer / Consumer rule) — VERIFIED 2026-08-26

- **`emit_set_temperature` call sites — 11 sites total** (NOT 13; prior
  draft inherited a stale count from `AUDIT_RESULT_2026_08_20`; the
  discrepancy is the two shipped-since migrations plus prior
  double-counting): `hvac_predict.py:958, 1109, 1393, 1456`;
  `hvac.py:2445, 3149`; `hvac_override.py:3125, 4155, 4327, 5539, 5914`.
  Full classification in §D2 Site Table. Reviewer D re-runs `git grep`
  independently before ship.
- **`emit_set_preset_mode` call sites — 7 emit sites total**
  (NOT 4; prior draft cited wrong lines): `hvac.py:2152` (S1
  house-state preset writer); `hvac_excursion.py:954` (primitive's OWN
  NUDGE preset restore during startup audit — see D3 coordination
  note); `hvac_egress.py:795` (egress restore);
  `hvac_override.py:3279, 3845, 4364, 5565` (nudge/cancel_nudge
  restore family: :3279 FIX-B2 nudge restore; :3845 post-manual
  re-preset; :4364 nudge follow-up restore; :5565 cancel_nudge restore
  FIX-B1).
- **`should_change_preset` call sites** — sole call at `hvac.py:2035`
  with the vacancy bypass immediately above at `hvac.py:2031` (RH3).
  Consumer count = 1; D3 has exactly one call-site to modify (and it
  is NOT the def in `hvac_preset.py`).
- **`hvac_excursion_state` DB DAOs** — `save_excursion_row`,
  `clear_excursion_row`, `get_all_excursion_rows` (module docstring
  :23-28); `log_excursion_event` writes the ENDED table.

### Reuse vs New — per proposed knob / signal / sensor

- **`EXCURSION_LEASE_SLACK_S=30`, `EXCURSION_LEASE_MAX_S=7200`,
  `EXCURSION_RETURN_BLOCKING`** — REUSED (`hvac_excursion.py:71-76`+).
  D1 (banking auto-release) and D4 (S14) use these; no new timers.
- **`EXCURSION_KIND.BANKING`, `.PREHEAT`, `.EGRESS_PAUSE`,
  `.COMPROMISE`, `.NUDGE`** — REUSED (`hvac_excursion.py:87`+). D4
  adds ONE new kind (see D4 CRIT resolution).
- **`_suppress_kind` provenance / `SUPPRESS_TTL_SECONDS=5`** — REUSED
  (`hvac_override.py:128`, `:218`, `:2624`). D3 consults this + the
  excursion registry, not the raw preset string. No new tag.
- **`switch.ura_hvac_coordinator_governed_excursion_enabled`** (kill
  switch) — REUSED (declared in `switch.py`). New D4 kind inherits it
  automatically.
- **`hvac_excursion_state`, `hvac_excursion_events`** — REUSED DAOs.
  D1's banking auto-release writes the same ended-event row shape the
  primitive already emits (`hvac_excursion.py` return_excursion path).
- **NEW: `EXCURSION_KIND.OFF_PHASE_CEILING = "off_phase_ceiling"`** — D4
  (see CRIT-MED resolution: single choice, not "OR reuse COMPROMISE").
- **NEW: `EXCURSION_AUTORELEASE_SWEEP_S = 60`** — module constant, Rung 1,
  implementation detail.
- **NEW: `switch.ura_hvac_d3_recovery_enabled`** — kill switch for D3
  recovery, default OFF at ship (see D3 CRIT-2 interlock).

---

## Producer / Consumer Discrimination

**Producer question (all four deliverables):** who WRITES the excursion
row / ended event / preset restore? Failure to write one of them = the
observation looks correct via the OTHER but the invariant is broken.
Discriminating oracles:

- **BANKING (D1) producer PASS:** at least one `banking` row appears in
  `hvac_excursion_events` (ENDED table) within `duration_s +
  EXCURSION_LEASE_SLACK_S` of a banking `begin_excursion`. Today
  (2026-08-25, live): 0. Under the fix, > 0.
- **Discriminator vs "banking never ran":** join
  `hvac_excursion_state` count of banking begins × `hvac_excursion_events`
  count of banking ends. Ratio == 1 = producer works. Ratio << 1 =
  auto-release fails. Ratio == 0/0 = feature dormant, DO NOT SCORE.

**Consumer question (D3):** who READS the excursion registry to decide
whether to recover a `manual` zone? Answer: the CALL SITE at
`hvac.py:2035` gains this consumer via an inline check in
`_apply_house_state_presets`; `should_change_preset` stays a pure
predicate (see D3 CRIT-1). Discriminator: a zone in `manual` with no
live excursion row transitions OUT of manual on the next
`_apply_house_state_presets` tick (bounded by tick cadence).

---

## Tier Justification

Tier 3 (four framing-disjoint reviews) is required, not merely elevated:

1. **Threads a value (preset restore) through a state machine consumed
   by many emission sites** — 11 setpoint-write sites; failure mode is
   ONE MISSED SITE (Bug Class #53). This is the exact D-HIGH-1 shape
   from v5.5.3.
2. **Cost-AND-safety-impacting** — solar banking mid-flight cancellation
   (energy regression), compressor short-cycling under a bad recovery,
   comfort during S14 ceiling.
3. **Re-litigates a shipped deliberate trade** — three artifacts encode
   the S14 no-release behaviour by design; overturning them is
   irreversible in effect.
4. **Cross-coordinator coupling** — preset manager × arrester ×
   excursion primitive × energy off-phase state.
5. **Prior evidence** — HVAC preset/setpoint area has a history of
   multi-fix-up cycles (governed-excursion cycle itself was 1 build + 4
   fix-ups + 7 reviews).

Reviewer D MUST re-enumerate the setpoint-write surface independently
INCLUDING pre-existing code (not just this cycle's diff) and produce a
concrete legal-config repro for any leak.

---

## D2 Site Table (verified 2026-08-26; reviewer D re-runs independently)

Source: verified `git grep` 2026-08-26 across
`custom_components/universal_room_automation/domain_coordinators/`.
Every row's line number was refreshed for this plan; reviewer D
re-enumerates and any drift becomes a finding.

| Site | File:line | Kind (today) | Sanctioned excursion? | Restores preset today? | Migration in this cycle |
|---|---|---|---|---|---|
| S1 | `hvac.py:2152` (`emit_set_preset_mode` inside `_apply_house_state_presets`) | house-state preset writer | n/a — decides, does not excurse | writes `preset` (the healthy path) | untouched; the reference the invariant restores TO. D3 recovery gate lives at the caller `hvac.py:2035` |
| S3 | `hvac_override.py:3125` (`emit_set_temperature`) | AC pre-nudge / setup | YES (COMPROMISE at `:3098`) | NO | audit in D2; migrate return-path to write `emit_set_preset_mode` OR document immunity |
| S5 | `hvac_override.py:4155` | AC soft nudge (perform) | YES (NUDGE at `:4132`) | via FIX-B2 restore at `hvac_override.py:3279` (racy — 509 ms clobber measured) | leave migration alone (nudge shipped); D3 fixes the stranding by giving the tick site the recovery path |
| S6 | `hvac_override.py:4327` | soft-nudge restore (S6 family) | audit — sits inside nudge lifecycle | preset restore is the intent (paired with `:4364`) | audit for race; leave code alone if D3 recovery covers it |
| S? | `hvac_override.py:5539` (cancel_nudge restore, `kind="temp"` at `:5527`-ish) | cancel_nudge restore | audit | via FIX-B1 preset write at `hvac_override.py:5565` | audit in D2 |
| **S9 (NEW ROW — was missed)** | `hvac_override.py:5914` (startup ramp audit restore, `site="S9_startup_ramp_audit_restore"`, arrester suppression `kind="temp"` at `:5906`) | boot-time nudge restoration | YES by intent (restores operator's pre-outage target) | NO — writes setpoint only, no `emit_set_preset_mode` follows | audit in D2; classify. Recommend: migrate to a `NUDGE` (or dedicated `STARTUP_RESTORE`) begin/return pair so the boot-restored zone still enters D3's recovery orbit if the write leaves it in `manual` |
| S10 | `hvac.py:2445` | Dynamic Preset Manager apply | yes — but DPM currently OFF | NO (writes low/high, no preset) | AUDIT — see NON-GOAL. If in scope, wrap in `PREHEAT` or new kind and add preset restore. Recommend: OUT OF SCOPE for this cycle (DPM off + separate design; card it) |
| S11 | `hvac_predict.py:958` | solar banking | YES (BANKING at `hvac_predict.py:1074`) | NO — grep confirms 0 `emit_set_preset_mode` in the module | ALREADY MIGRATED as `BANKING` at begin; **D1 adds return-path preset restore** |
| S12 | `hvac_predict.py:1109` | pre-cool | yes (BANKING branch) | NO | already `BANKING`; D1 covers |
| S13 | `hvac_predict.py:1393` | pre-heat | YES (PREHEAT at `hvac_predict.py:1360`) | NO | add return-path preset restore (D2 + D1's `_auto_return` pattern) |
| S? | `hvac_predict.py:1456` | predictive follow-up write | audit — likely inside one of the banking branches | audit | D2 classification: confirm covered by the enclosing begin/return, or migrate independently |

**Site count reconciliation:** 11 rows = 11 `emit_set_temperature`
sites in production. The prior draft's "13" was inherited from
`AUDIT_RESULT_2026_08_20` which pre-dated the nudge / banking /
preheat / egress migrations that collapsed several sites into governed
pairs. The two missing sites from the older count are the migrated-and-
subsumed writes now covered by their governed callers.

Sanctioned writers per this table = 11 (all listed above). No egress
setpoint site remains outside the primitive (the setpoint arm of egress
is already inside `EGRESS_PAUSE`).

D2's acceptance is the completed table with EVERY row proven by a
per-site source mutation drill (framing C).

---

## Deliverables

### D1 — Banking auto-release / lease-expiry (writes ended event + restores preset)

**Problem (live-measured 2026-08-25):** `hvac_excursion_state` holds 2
OPEN banking rows; `hvac_excursion_events` has 0 banking rows. Banking
begins, never ends. Banking (S11/S12/S13 in `hvac_predict.py`) performs
the temp write only.

**Scope:**

1. Add a periodic auto-release sweep to the excursion primitive: on a
   coordinator tick (or `async_track_time_interval` at
   `EXCURSION_AUTORELEASE_SWEEP_S = 60` s), scan `_rows` (in-memory
   registry). For each row with `age > duration_s +
   EXCURSION_LEASE_SLACK_S` (or `age > EXCURSION_LEASE_MAX_S`
   unconditionally), invoke `_auto_return(zone_id,
   reason="lease_expiry")` which:
   - Reads `pre_preset` from the token.
   - **If `pre_preset in {"manual", None}` or empty string:** SKIP the
     preset write, log an ended-event with `preset_after=<observed>`,
     `restore_ok=None` (the ReturnOutcome 3-way distinction — neither
     PASS nor FAIL, "no legitimate preset to restore to"), and let D3
     recover the zone on the next `_apply_house_state_presets` tick.
     (HIGH-1 resolution.)
   - Otherwise, writes preset back via `emit_set_preset_mode` at
     `blocking=EXCURSION_RETURN_BLOCKING` (True).
   - Calls `return_excursion(..., trigger="lease_expiry",
     preset_after=<observed>, restore_ok=<verify or None per above>)`
     — that already writes the ENDED row via `log_excursion_event`.
2. **Natural-end explicit close per banking kind — SITES NAMED:**
   - S11 (`hvac_predict.py:958`, BANKING begin at `:1074`) — natural
     end at the completion of the solar-banking window inside the S11
     branch (the same branch that opens the token). Add an explicit
     `return_excursion(trigger="natural_end", preset_after=...)` at
     the branch-exit path.
   - S12 (`hvac_predict.py:1109`, BANKING branch) — same pattern at
     the pre-cool completion path in the enclosing branch.
   - S13 (`hvac_predict.py:1393`, PREHEAT begin at `:1360`) — same
     pattern at the pre-heat completion path.
   Explicit close snapshots the intended natural preset (not
   `pre_preset`, which may have been `"manual"` at begin per §13.5
   UNFILTERED); auto-release is the backstop. If the reviewer finds
   the natural-end site is non-trivial for any of S11/S12/S13, that
   site's explicit-close is CARDED as follow-on
   (`BANKING-EXPLICIT-CLOSE-<Sxx>-1`) and the acceptance test for D1
   is written so it CANNOT pass vacuously via lease-expiry — see
   Acceptance Criteria below. (HIGH-2 resolution.)
3. Suppression-needs-a-discharge check: if the coordinator restarts
   mid-lease, `async_startup_excursion_audit` already drops rows older
   than `EXCURSION_LEASE_MAX_S` and fires `stale_excursion_row`
   (severity=low). This deliverable adds: for a stale-drop of a banking
   row, ALSO run the auto-release restore path (write preset, log
   ended event with `trigger="stale_boot_release"`) — subject to the
   same `pre_preset in {"manual", None}` skip as (1). (HIGH-1 also.)

**Knobs (numbers-get-knobs ladder):**

- `EXCURSION_LEASE_SLACK_S=30` — module constant (REUSED,
  `hvac_excursion.py:71`); no promotion.
- `EXCURSION_LEASE_MAX_S=7200` — module constant (REUSED,
  `hvac_excursion.py:76`); no promotion.
- `EXCURSION_AUTORELEASE_SWEEP_S=60` — module constant (NEW,
  `hvac_excursion.py`); Rung 1 (module) — implementation detail.

**Acceptance Criteria:**

- **Verify (test):** `test_banking_auto_release_writes_ended_event` —
  begin a banking excursion with `duration_s=5`, sleep 5+slack, assert
  a row appears in `hvac_excursion_events` with `kind='banking'`,
  `trigger='lease_expiry'`.
- **Verify (test):** `test_banking_auto_release_writes_preset_after` —
  same fixture, `pre_preset="home_day"`, assert `emit_set_preset_mode`
  was called with `"home_day"`.
- **Verify (test HIGH-1):**
  `test_banking_auto_release_skips_preset_when_pre_preset_manual` —
  same fixture, `pre_preset="manual"`, assert `emit_set_preset_mode`
  was NOT called, ended-event row appears with `restore_ok=None`.
- **Verify (test):** `test_banking_stale_boot_release_writes_preset` —
  simulate a persisted row older than `EXCURSION_LEASE_MAX_S`, boot
  audit, assert preset write occurred (when `pre_preset` legitimate)
  AND ended-event row appeared with `trigger='stale_boot_release'`.
- **Discriminating test (per producer/consumer rule):**
  `test_banking_natural_close_does_not_double_return` — explicit
  `return_excursion` followed by an auto-release sweep must be a no-op
  second call (§4.6 `_returned` guard already handles this; assert only
  ONE ended-event row appears).
- **Discriminating test (HIGH-2 non-vacuous natural-end):**
  `test_banking_explicit_close_fires_before_lease_expiry` — for each
  named natural-end site (S11/S12/S13), simulate the branch's
  natural-completion condition WITHIN `duration_s`, assert the ended
  event carries `trigger="natural_end"` (NOT `lease_expiry`). If a
  site was carded as follow-on, the test asserts the carded stub
  raises `pytest.xfail(reason="carded: BANKING-EXPLICIT-CLOSE-<Sxx>-1")`
  and the D1 acceptance is met by lease-expiry PLUS the card being
  filed.
- **Sensor:** `sensor.ura_hvac_coordinator_governed_thermostat_borrows`
  `returned_today.banking >= 1` and `restore_failed_today.banking` in
  `{empty, 0}` after a full solar-banking day.
- **Live:** `SELECT count(*) FROM hvac_excursion_events WHERE
  kind='banking'` > 0 within 24 h of a sunny day post-deploy; `SELECT
  count(*) FROM hvac_excursion_state WHERE kind='banking'` returns
  to 0 after each banking cycle.
- **Live (discriminating):** the two currently-OPEN banking rows
  (started 2026-08-22) are cleared by boot audit as `stale_boot_release`
  in the first restart post-deploy.

---

### D2 — Audit + close every non-restoring sanctioned excursion site

**Problem:** the site table above is verified but Bug Class #53 says one
missed site defeats the invariant. Reviewer D re-enumerates.

**Scope:**

1. Reviewer D independently re-enumerates every `emit_set_temperature`
   call site via `git grep -n emit_set_temperature
   custom_components/universal_room_automation/domain_coordinators/`.
2. Fill the site table completely (base is the 11-row table above;
   any drift is a finding).
3. For every sanctioned-and-non-restoring row, EITHER:
   - Migrate it to a `begin_excursion` / `return_excursion` pair with a
     `duration_s` that reflects the writer's intent AND a preset restore
     in the return path (D1's `_auto_return` is the reference); OR
   - Document immunity with a source comment + a per-site test asserting
     the immunity condition still holds (framing C mutation drill).
4. Verify the site-family classifier tuple at `hvac_setpoint.py`
   matches the `site=` args of every migrated caller.
5. **D3 interlock (CRIT-2):** the D3 recovery kill switch
   `switch.ura_hvac_d3_recovery_enabled` remains OFF at ship. It is
   flipped ON in a follow-up commit ONLY after D2's live-validation
   shows every migrated kind writing an ended-event row for its
   observed begins. The aggregate whitelist test at build time gates
   the code merge (see acceptance).

**Non-scope for D2 (state explicitly):**

- S10 (DPM `hvac.py:2445`) — DPM is currently OFF; requires a
  redesign of what a "preset" for a DPM override means (operator
  ruling "DPM should emit presets, not setpoints" per
  `DPM_RECON_2026_08_20`). RESOLVED IN PLAN: **S10 is CARDED as
  follow-on** (`DPM-EMIT-PRESET-1`). Keep Auto-Adjust OFF until it
  lands. (MED resolution.)
- The **decider/writer split** for the preset path — its own cycle per
  operator ruling; folding doubles the blast radius.
- **The `set_hvac_mode` axis** — excluded on evidence per
  `HVAC-GOVERNED-EXCURSION-1 SCOPE_DECISION_MODE_EXCLUDED_2026_08_21`.

**Knobs:** none new. This is an audit-and-migrate deliverable.

**Acceptance Criteria:**

- **Test:** for every migrated site, one framing-C mutation test:
  neuter the added `begin_excursion` call at that site (return None
  instead of a token), run the suite, assert a SPECIFIC test fails
  naming that site.
- **Test (MED resolution — AST-based, not text-grep):**
  `test_every_setpoint_writer_is_governed` — parse
  `custom_components/universal_room_automation/domain_coordinators/*.py`
  with `ast`, walk for `Call` nodes whose resolved name is
  `emit_set_temperature`, then for each such call locate the enclosing
  function definition and assert it either (a) is preceded within the
  same function body by an `await begin_excursion(...)` call whose
  return is bound and referenced in a `return_excursion` on every
  exit path, or (b) the enclosing function name is in a documented
  IMMUNE_WRITERS whitelist constant (source-of-truth in the test file,
  paired with a per-entry comment). Whitelist changes require a paired
  test change — a review smell surface. AST-based to avoid text-grep
  false positives (comments, string literals, docstrings referencing
  the name).
- **Sensor:** `sensor.ura_hvac_coordinator_governed_thermostat_borrows`
  `started_today` shows non-zero counts for `banking`, `preheat`, plus
  any newly-migrated kinds within a normal-behaviour day.
- **Live:** for each migrated kind, ≥ 1 ended-event row appears within
  24 h of deploy WITH `preset_after` non-NULL and different from
  `"manual"` (unless zone was in manual at begin and the operator hadn't
  touched it — the UNFILTERED snapshot case).
- **Discriminator vs "the feature never fired":** cross-check
  `started_today.<kind> > 0` in the same day the ended-event count is
  measured. If both zero, live-validation is INDETERMINATE, not PASS.

---

### D3 — Fix `should_change_preset` self-lockout WITHOUT stomping owned excursions

**Problem:** `hvac_preset.py:215` returns False whenever
`current_preset == "manual"`. Pure two-string function — cannot consult
provenance. A `manual` zone stays `manual` forever unless an external
event moves it. This is the CONSUMER duty of the invariant.

**CRIT-1 resolution — SINGLE IMPLEMENTATION CHOSEN (no alternatives):**

The recovery gate is **INLINE at the sole call site
`hvac.py:2035` inside `_apply_house_state_presets`**, and
`should_change_preset` is **NOT WIDENED** — it remains a pure
two-string predicate. Widening the predicate to accept `hass` /
`zone_id` is explicitly REJECTED (it would leak coordinator state
into a policy helper that other callers may adopt later; the
decider/writer reframe direction is served by keeping policy at the
tick site).

**Scope:**

1. Add a read-only helper `has_live_row(zone_id: str) -> bool` on
   `hvac_excursion.py` — reads the in-memory `_rows` registry, returns
   True iff any row exists for `zone_id`. Docstring pins that this is
   a **recovery consumer only, MUST NOT be reused as a runtime gate**
   (per the 2026-08-21 gate-strip decision the primitive is
   BOOKKEEPING ONLY). No writes, no dispatch, no I/O.
2. **CRIT-3 resolution — KIND handling + stranded-row rule.**
   `has_live_row(zone_id)` intentionally does NOT filter by kind — a
   live row of ANY kind counts as "owned" for recovery purposes,
   including a NUDGE row that is technically stale-but-not-yet-swept.
   **To prevent a stranded row of one kind masking a stranded
   manual indefinitely**, the recovery gate additionally consults
   `age`: a row whose `age > duration_s + EXCURSION_LEASE_SLACK_S` is
   treated as EXPIRED-IN-FLIGHT and does NOT block recovery
   (equivalently: `has_live_row` returns False for rows past their
   expiry even if `_auto_return` has not yet run). This makes D1's
   `_auto_return` sweep the fast-path and the gate's `age` check the
   correctness-path — max stranding a live-elsewhere row can impose
   on a stranded manual is `EXCURSION_LEASE_SLACK_S = 30 s`. Absolute
   backstop is `EXCURSION_LEASE_MAX_S = 7200 s` (D1 lease-expiry).
3. The recovery gate at `hvac.py:2035` becomes:
   ```
   # existing vacancy bypass at :2031 preserved AS-IS
   elif zone.preset_mode == "manual":
       if not self._d3_recovery_enabled:  # kill switch, default OFF
           if not self._preset_manager.should_change_preset(
               zone.preset_mode, effective_preset,
           ):
               continue  # legacy behaviour
       else:
           # CRIT-2 gated: excursion registry + arrester grace
           if _ex_mod.has_live_row(zone.id):
               continue  # legitimately owned; do not fight
           if self._override_arrester.suppress_active(zone.climate_entity):
               continue  # operator's recent manual touch, within TTL
           # RECOVER: fall through to preset write
   elif not self._preset_manager.should_change_preset(
       zone.preset_mode, effective_preset,
   ):
       continue
   ```
4. `suppress_active(entity_id)` is a NEW **thin read-only helper** on
   `hvac_override.py` returning True iff `_suppress_kind` is set AND
   the paired expiry timestamp has not passed. Wraps the existing
   `_suppress_kind` state at `:218` / expiry-set at `:2624`. No new
   TTL — REUSES `SUPPRESS_TTL_SECONDS = 5` at `:128`.
5. The vacancy-bypass at `hvac.py:2031` is preserved AS-IS.

**CRIT-2 — code-level interlock enforcing D2-before-D3:**

- New switch `switch.ura_hvac_d3_recovery_enabled`, persisted via the
  existing switch machinery, **default OFF at ship**.
- The build MUST include the AST-based
  `test_every_setpoint_writer_is_governed` from D2 as a hard gate
  (failing test = build fails). This proves at BUILD time that every
  setpoint-writer is inside a begin/return pair.
- D3 recovery goes LIVE only after: (a) that test is green in CI, AND
  (b) D2's live-validation shows every migrated kind writing
  ended-event rows post-deploy (24 h observation window). At that
  point the operator flips the switch ON in a follow-up commit or via
  the UI.
- With the switch OFF, the branch at `hvac.py:2035` falls through to
  the legacy `should_change_preset` call — pre-cycle behaviour
  preserved bit-for-bit.

**Discriminating design (critical):** the gate must NEVER interrupt an
IN-FLIGHT nudge / banking / preheat. The invariant proof rests on the
D2 audit: every sanctioned raw-setpoint writer has a live row for the
duration of its excursion. If D2 misses a site, D3 will recover a zone
that a legitimate writer owns → cancelled solar banking mid-flight.
**This is D3's load-bearing dependency on D2**; framing D falsifies
it by picking a sanctioned-writer site, mutating it to NOT call
`begin_excursion`, and asserting D3's recovery does not stomp a live
banking session in a test.

**Knobs:**

- `SUPPRESS_TTL_SECONDS=5` — REUSED (`hvac_override.py:128`). No
  promotion; safety-adjacent, review-gated tuning.
- `switch.ura_hvac_d3_recovery_enabled` — NEW switch, default OFF.
  Rung 3 (Number/Select/Switch entity) — operator-flipped after D2
  validation confirms the invariant surface is closed.

**Acceptance Criteria:**

- **Test:** `test_manual_with_no_live_excursion_recovers_on_next_tick` —
  switch ON, set zone to `manual`, no excursion row, no arrester grace,
  run one tick of `_apply_house_state_presets`, assert
  `emit_set_preset_mode` was called with the house-state's intended
  preset.
- **Test (discriminating):**
  `test_manual_with_live_banking_excursion_is_not_stomped` — switch ON,
  begin a banking excursion (fresh, `age < duration_s`), set zone to
  `manual`, run the tick, assert `emit_set_preset_mode` was NOT called
  for that zone; then `return_excursion`, run tick, assert preset
  write.
- **Test (CRIT-3 stranded-row):**
  `test_manual_with_expired_live_row_recovers` — switch ON, insert a
  live row with `age = duration_s + EXCURSION_LEASE_SLACK_S + 1`
  (D1's auto-release intentionally not yet run), set zone to `manual`,
  run the tick, assert `emit_set_preset_mode` WAS called (expired row
  does not block recovery).
- **Test (discriminating):**
  `test_manual_within_arrester_grace_is_not_stomped` — switch ON,
  simulate `_suppress_kind` active within TTL, assert no recovery;
  step time past TTL, assert recovery on next tick.
- **Test (framing C mutation):** neuter `has_live_row` to return False
  unconditionally; assert
  `test_manual_with_live_banking_excursion_is_not_stomped` FAILS with
  a specific error.
- **Test (kill-switch OFF preserves legacy):**
  `test_d3_recovery_disabled_matches_pre_cycle_behavior` — switch OFF,
  set zone to `manual`, run tick, assert `emit_set_preset_mode` NOT
  called (byte-identical to pre-cycle `should_change_preset` return
  False).
- **Sensor:** invert `sensor.ura_hvac_zone_<n>_preset_manual_duration`
  (REUSE any existing manual-duration counter; if none, add via
  existing sensor.py machinery) — under D3 the 95th percentile of
  continuous `manual` time drops from 10.5-14.5 h / day to O(minutes).
- **Live:** SELECT the longest continuous `manual` run per zone per day
  from `states` — target < 30 min after switch flipped ON. Baseline
  measured 2026-08-20: zone_1 14 h 35 min, zone_2 ~11 h.
- **Live (discriminating vs D2 miss):** count `banking` and `preheat`
  ended-event rows for the same day the switch flips; if D3 is
  recovering a live excursion, the row count drops.

---

### D4 — S14 migrated as a borrow kind, one-shot-per-off-phase

**Problem:** S14 `hvac.py:3149` writes a raw setpoint to hold the
cooling ceiling during an energy-coast/shed off-phase. The write flips
the Bryant to `manual`, and S14 has no explicit exit. Operator ruling
2026-08-21: "give it an ending", migrate as a borrow kind,
one-shot-per-off-phase (anti-flap).

**MED resolution — KIND: `EXCURSION_KIND.OFF_PHASE_CEILING =
"off_phase_ceiling"` — SINGLE CHOICE, not "OR reuse COMPROMISE".**
Reusing COMPROMISE would collide with the existing compromise ledger
(already 100% of the ENDED table's non-nudge rows) and confuse
post-hoc analytics. Add the enum member to `hvac_excursion.py:87`+.

**Scope:**

1. S14 wraps its `emit_set_temperature(site="S14", ...)` at
   `hvac.py:3149` with `begin_excursion(kind=EXCURSION_KIND.OFF_PHASE_CEILING,
   duration_s=<computed off-phase remaining>, site="S14")` and a
   matching `return_excursion` on the paired path. `duration_s` is the
   computed off-phase remaining, passed once at begin, clamped by
   `EXCURSION_LEASE_MAX_S`.
2. **D3-coordination note (COMPLETENESS finding — explicit
   precedence + no-double-write at return time):**
   `hvac_excursion.py:954` performs a preset restore ONLY inside
   `async_startup_excursion_audit` and ONLY when
   `kind == EXCURSION_KIND.NUDGE` (guarded at `:941`). It is INERT
   for `OFF_PHASE_CEILING` and cannot double-write with D4's own
   return-path preset restore. **Precedence at return time:**
   D4's `return_excursion` performs the sole preset write for its
   own excursion; the primitive's :954 branch does not fire for
   OFF_PHASE_CEILING. If the operator later chooses to widen :954
   beyond NUDGE, that is a separate card
   (`STARTUP-AUDIT-PRESET-RESTORE-KIND-BROADEN-1`) and D4's return
   path must be teach the primitive-side branch to be skipped for
   OFF_PHASE_CEILING to preserve exactly-one-write.
3. **HIGH-3 resolution — off-phase-ID source (D0 probe RAN 2026-08-26, orchestrator).** The off-phase is NOT an Energy-Coordinator concept — `git grep off_phase` in `domain_coordinators/energy*` returns NOTHING. The off-phase is an **HVAC duty-cycle concept** (HVAC-PRESET-FLAP-1 D4), and its episode identity **already exists**: `(zone_id, house_state)`, tracked by `self._offphase_logged: set[tuple[str, str]]` (`hvac.py:344`, the mirror of `_night_trust_logged`), "single per-(zone, house_state) episode … discharged on house_state transition; a new house_state is a new episode" (`hvac.py:345-349`). So the S14 one-shot key is a **REUSE of `(zone_id, house_state)`**, NOT a new EC field — corrected from the prior "EC start-timestamp" assumption. Stability is by CONSTRUCTION: `house_state` changes only on a real house transition, not a tick refresh, so the key is invariant across EC/coordinator refreshes within one off-phase. Keep `test_off_phase_id_stable_across_ec_ticks` (sample the `(zone_id, house_state)` key N=10 across simulated refreshes → all equal) as the guard; the discharge is the SAME house_state-transition edge that already clears `_offphase_logged`.
4. **One-shot-per-off-phase guard (MANDATORY):** after
   `return_excursion` for an off-phase, S14 records
   `_off_phase_ceiling_released[(zone_id, house_state)] = True`. While that
   flag holds, S14 falls back to SUPPRESSION-ONLY for the remainder of
   that off-phase (do NOT flip to away, do NOT re-write the ceiling).
   Re-arm on the NEXT off-phase (new (zone_id, house_state) episode, i.e. a house_state transition).
5. **Restart behaviour (declared):** PERSIST-VIA-EXCURSION-STATE. The
   excursion row persists via existing `save_excursion_row`; on boot,
   `async_startup_excursion_audit` rehydrates if fresh, or drops as
   stale + auto-release (D1's `stale_boot_release`). The one-shot flag
   is EPHEMERAL — if HA restarts mid off-phase, the flag is lost, S14
   MAY re-arm once after boot. Documented and accepted (a single
   post-restart flap is bounded by `EXCURSION_LEASE_MAX_S`, ≤ 2 h).
6. **Overturn the three artifacts:**
   - `PLANNING_preset_flap_offphase_honesty.md:184-195` — annotate:
     "SUPERSEDED 2026-08-21 by operator decision; see
     PLANNING_hvac_excursion_restore_unified.md D4."
   - Same file :280 acceptance criterion — annotate.
   - `test_ceiling_held_until_next_preset_transition` — INVERT: rename
     to `test_ceiling_releases_at_off_phase_end_or_lease_expiry`,
     assert preset restore fires exactly ONCE per off-phase. Do NOT
     delete the original silently.
7. **HIGH-4 resolution — relinquish check on divergence.** The
   `ExcursionToken` schema at `hvac_excursion.py:106` already
   persists the WRITTEN setpoint via the `pre_setpoint` /
   `wrote_setpoint` field family. **VERIFY at build time** that the
   field storing the S14-written high-side setpoint exists and is
   populated by `begin_excursion` (name to be confirmed by the
   builder against `hvac_excursion.py:106`+ during the first hour of
   build; if absent, add it — this becomes a small D4 sub-task, not a
   plan reopen). The relinquish comparison is
   `abs(current_setpoint_high - token.wrote_setpoint_high) >
   SETPOINT_ECHO_TOLERANCE` where `SETPOINT_ECHO_TOLERANCE` is the
   **v5.51.1 echo-guard constant** reused verbatim (locate at build
   time via `git grep -n ECHO_TOLERANCE`; the plan pins REUSE, not
   value). If diverged, disarm SILENTLY (return_excursion with
   `restore_ok=None` per the ReturnOutcome 3-way distinction)
   instead of writing the preset.

**Scope decision on D4 splitting (resolved in-plan):** D4 ships in
the SAME cycle as D1/D2/D3 (single deploy, per the invariant's
coherence: D3 without D4 still leaves S14 semantically wrong even
though it gets a row). The alternative "split D4 to follow-on" is
REJECTED — D4 is small once D1's `_auto_return` exists, and
splitting risks operator-visible S14 flap for the intervening period.
(MED resolution.)

**Knobs (numbers-get-knobs ladder):**

- `duration_s` for S14 — **COMPUTED, no knob.**
- Cap: `EXCURSION_LEASE_MAX_S=7200` — REUSED.
- Kill switch:
  `switch.ura_hvac_coordinator_governed_excursion_enabled` — REUSED
  (new kind inherits automatically).
- `SETPOINT_ECHO_TOLERANCE` — REUSED (v5.51.1 echo-guard). No new
  constant.

**Acceptance Criteria:**

- **Test (INVERTED):**
  `test_ceiling_releases_at_off_phase_end_or_lease_expiry` — begin
  S14 with `duration_s=5`, wait 5+slack, assert
  `emit_set_preset_mode` was called AND ended-event row appears in
  `hvac_excursion_events` with `kind='off_phase_ceiling'`.
- **Test (discriminating anti-flap):**
  `test_s14_one_shot_per_off_phase_no_reflap` — inside one off-phase,
  after release, tick S14 3× more; assert `emit_set_temperature` was
  NOT called (suppression-only fallback). Then advance to a NEW
  off-phase (new ID), assert S14 CAN re-arm.
- **Test (off-phase-ID stability):**
  `test_off_phase_id_stable_across_ec_ticks` (see Scope 3).
- **Test (framing C):** neuter the `begin_excursion` call at S14,
  run suite, assert the migration test fails with a specific error.
- **Test (relinquish):**
  `test_s14_silent_disarm_on_setpoint_divergence` — after S14 begin,
  simulate an external setpoint change beyond `SETPOINT_ECHO_TOLERANCE`;
  assert `return_excursion` fires with `restore_ok=None` and NO
  preset write.
- **Sensor:** `sensor.ura_hvac_coordinator_governed_thermostat_borrows`
  `started_today.off_phase_ceiling` and
  `returned_today.off_phase_ceiling` are non-zero during a duty-cycle
  day; `restore_failed_today.off_phase_ceiling` is empty or 0.
- **Live:** in a house_night → home_day transition that spans an
  off-phase, zone in S14-managed manual returns to a preset within
  `off_phase_remaining_s + EXCURSION_LEASE_SLACK_S`.
- **Live (discriminating vs flap regression):** in a full off-phase
  window, count ENDED events for `kind='off_phase_ceiling'` per
  off-phase per zone — must be exactly 1, never 2+.

---

## Non-Goals (explicit)

- **`set_hvac_mode` axis** — excluded on evidence per
  `HVAC-GOVERNED-EXCURSION-1 SCOPE_DECISION_MODE_EXCLUDED_2026_08_21`.
- **Decider / writer architectural split** — separate cycle.
- **DPM (S10) redesign** — CARDED as `DPM-EMIT-PRESET-1` (follow-on).
  Keep Auto-Adjust OFF until it lands.
- **Write rate limit / Carrier 504 loop-breaker** — retracted for lack
  of evidence.
- **AC-nudge race repair** — separate card.
- **Freeze-floor / deadband** — already correctly at the chokepoint.
- **Broadening `hvac_excursion.py:954` startup preset restore beyond
  NUDGE** — CARDED as `STARTUP-AUDIT-PRESET-RESTORE-KIND-BROADEN-1`
  (follow-on; D4 does not depend on it).

---

## Sequencing & Dependencies

1. **D2 audit runs FIRST** — the site table is D3's load-bearing
   dependency.
2. **D1 second** — banking auto-release is an isolated backstop.
3. **D3 third — SHIPS DISABLED (kill switch OFF).** The AST test from
   D2 gates the build. Switch flipped ON only after D2 live-validation
   confirms every migrated kind writes ended-event rows (see D3
   CRIT-2).
4. **D4 fourth** — S14 migrates as `OFF_PHASE_CEILING` kind
   CONSUMING D1's auto-release machinery.

All four in one deploy per the invariant's coherence; D3 goes LIVE via
kill-switch flip in a follow-up commit after D2 observation window.

---

## Follow-On Cards Filed by This Plan Review

Stubs to be filed into `docs/planning/kanban.data.yaml` by the
orchestrator BEFORE build dispatch:

1. **`DPM-EMIT-PRESET-1`** — Migrate S10 (`hvac.py:2445`, DPM apply)
   from raw setpoint writes to preset emission per operator ruling in
   `DPM_RECON_2026_08_20`. Prerequisite: Auto-Adjust remains OFF.
   Deferred from this cycle's D2 non-scope.
2. **`STARTUP-AUDIT-PRESET-RESTORE-KIND-BROADEN-1`** — Consider
   broadening `hvac_excursion.py:954` preset restore beyond
   `EXCURSION_KIND.NUDGE`. Currently guarded at :941 to NUDGE only.
   Deferred; D4 explicitly designs around the guard.
3. **`BANKING-EXPLICIT-CLOSE-S11-1`** / `-S12-1` / `-S13-1` —
   filed only IF during build the natural-end site for any of
   S11/S12/S13 proves non-trivial (see D1 Scope 2). Placeholder
   entries; the build agent files/withdraws each based on the actual
   branch shape.

---

## Live-Validation Ledger (README write-back)

Per the mandatory README write-back rule, the post-deploy README must
carry a `Validated <date>` table replacing the prospective Live bullets
above, with observed evidence per criterion (entity_id + attribute
values, DB row counts, longest-manual-run per-zone-per-day). Key
observations to capture:

- D1: OPEN banking rows in `hvac_excursion_state` before/after (baseline
  2, expected 0).
- D2: full site table with each row's live-validation state.
- D3: 95th percentile continuous `manual` per zone per day
  before/after (baseline 10.5-14.5 h, target < 30 min) — measured
  AFTER the kill-switch is flipped ON.
- D4: `off_phase_ceiling` ended events per off-phase per zone
  (target exactly 1).

The README also carries the switch-flip commit hash + date the D3
kill switch was flipped ON, and the 24 h observation window that
preceded it.

---

## Plan-Review Checklist (Tier 3 requires TWO plan reviews — APPLIED)

Both framing-disjoint plan reviews returned FIX-THE-PLAN. Their
findings have been applied in place above. Summary of resolutions:

| Finding | Severity | Resolution |
|---|---|---|
| Stale citations (`:1411`, `:1892`, `:1896`, wrong emit_set_preset_mode sites) | COMPLETENESS | All line numbers re-grepped 2026-08-26 and updated. Real sites: def `_apply_house_state_presets`:1550, S1 writer :2152, vacancy bypass :2031, `should_change_preset` call :2035; emit_set_preset_mode 7 sites enumerated. |
| Missed sanctioned writer `hvac_override.py:5914` (startup nudge restore, `kind="temp"`) | COMPLETENESS | Added as S9 row in D2 site table with classification. |
| "13 sites" mis-count | COMPLETENESS | Reconciled to 11 with rationale. |
| Missing D3 coordination with `hvac_excursion.py:954` | COMPLETENESS | Added D4 Scope 2 precedence + no-double-write note; STARTUP-AUDIT-PRESET-RESTORE-KIND-BROADEN-1 carded. |
| CRIT-1 D3 implementation ambiguity | BUILD-PRED | Single choice: inline gate at hvac.py:2035 calling `has_live_row`; `should_change_preset` NOT widened. Alternative clause deleted. |
| CRIT-2 D3-before-D2 ordering not code-fenced | BUILD-PRED | New kill switch `switch.ura_hvac_d3_recovery_enabled` default OFF + AST whitelist test as build-time hard gate + explicit switch-flip protocol post-D2-validation. |
| CRIT-3 `has_live_row` kind + stranded row | BUILD-PRED | `has_live_row` treats age > duration_s+SLACK as not-live; max stranding 30 s; D1 lease-expiry MAX_S is the backstop. Documented. |
| HIGH-1 D1 pre_preset in {manual, None} | BUILD-PRED | Explicit skip + `restore_ok=None` on both auto-release and stale-boot paths; specific test added. |
| HIGH-2 natural-end site naming | BUILD-PRED | Named per S11/S12/S13 with follow-on-card fallback; non-vacuous acceptance test added. |
| HIGH-3 off-phase-ID source verification | BUILD-PRED | D0 probe required at plan-review completion + cross-refresh stability test spec added. |
| HIGH-4 excursion token setpoint schema + tolerance | BUILD-PRED | Named field family + REUSE of v5.51.1 SETPOINT_ECHO_TOLERANCE + exact comparison specified. |
| MED: OFF_PHASE_CEILING vs COMPROMISE | BUILD-PRED | Committed to NEW kind OFF_PHASE_CEILING. |
| MED: S10 / DPM | BUILD-PRED | Carded as DPM-EMIT-PRESET-1, out of D2 scope. |
| MED: D4 split | BUILD-PRED | Resolved: D4 ships in-cycle with D1/D2/D3. |
| MED: whitelist test AST vs text-grep | BUILD-PRED | Specified as AST-based; text-grep rejected. |

---

**End of plan.**
