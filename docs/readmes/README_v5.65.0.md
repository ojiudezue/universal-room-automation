# URA v5.65.0 — Sensor capability vs analytic role (SENSOR-CAPABILITY-1)

**Tier 3** — four framing-disjoint reviews (A local correctness / B invariants+integration /
C test authority via per-site mutation / D adversarial completeness), CRIT-HIGH-MED fix-up,
operator-ruled LOW-stink pass, orchestrator independent mutation verification, operator
checkpoint before deploy. Also aboard: KHOST-1 kanban generator (`scripts/kanban_render.py`,
docs-side) and the BOARD-CURRENCY-1 deploy gate's **first live run** (this release).

## The problem

`occupancy_substrate.py` mapped sensor *kind* 1:1 onto the three CONF lists
(`_KIND_TO_CONF`; `TIER1_KINDS = ("motion","mmwave","occupancy")`): the hardware wiring
declaration and the analytic role were the same field. Consequences, measured in
`AUDIT_mmwave_only_rooms_2026-07-31.md`:

- A bed sensor could not declare itself a bed — it inherited `"occupancy"` and was therefore
  a **stuck-detector candidate** (judged) instead of the ideal corroborator (consulted).
  Master Bedroom's bed sensor got flagged duty-cycle-stuck every night someone slept on it.
- "Corroborator" was hardcoded to mean *the motion bucket*, so six rooms with no PIR
  (5 mmWave-only + Master) had **no corroborator by vocabulary**, not by lack of evidence.

Operator ruling (2026-08-09): *"Sensor reality should not pin use and analysis reality in
software. It should just tell us what the hardware layer is."*

## What ships

- **`domain_coordinators/sensor_capability.py`** — frozen `SensorCapability`,
  `derive_capability` (per-entity: operator override wins, else CONF-list-derived — byte-
  identical defaults), `validate_capabilities_payload` (rejects: missing/unknown `kind`,
  unknown `trust_class`/`failure_mode`, unwired entities, and overrides that would evict an
  entity from both the corroborator and candidate sets — the D-MEDIUM-1 narrowing hole).
- **`domain_coordinators/sensor_role.py`** — pure `resolve_role(room_config, entity, RoleQuery)`;
  `CANDIDATE_FOR_STUCK` / `CORROBORATOR_FOR_ROOM` live, `CREATOR_VS_EXTENDER` reserved.
  Roles are computed per query, never persisted (I2). `strong_evidence` trust demotes an
  mmwave/occupancy-wired entity out of the stuck-candidate set and elevates it to corroborator.
- **`CONF_SENSOR_CAPABILITIES`** — per-room options JSON (multiline textarea; HA has no dict
  selector — per-sensor dropdowns ride the next cycle per operator). Empty ⇒ key not persisted.
- **One consumer migrated:** `coordinator._detect_duty_cycle_stuck` builds its corroborator
  and candidate sets via `resolve_role`. Fan-recheck / provenance / entity attrs are explicit
  non-goals (plan §8).
- **I3 ward:** capability kinds cannot reach the legacy provenance channel;
  `_audit_provenance_invariants` still raises, docstring states the vocabulary is closed by
  design. C proved the runtime ward has teeth (widening `TIER1_KINDS` reddens 5 tests).

## Invariants

- **I1** — with no capabilities declared anywhere, substrate dispatch, provenance, D2's return
  set and all entity attributes are byte-identical to v5.64.0. **Documented carve-out** (§10.1,
  Reviewer B adjudication): an entity listed in ≥2 CONF lists was previously double-scored in
  D2 (same ring appended twice/tick, reaching MIN_TICKS in half the time); it is now scored
  exactly once under P15 precedence, matching the substrate's own normalisation. Defensive
  WARN'd path, not intended config; the fix is locked by `test_d2_p15_both_buckets_scored_exactly_once`
  plus motion×mmwave / motion×occupancy analogues.
- **I2** — pure role resolution; no persistence across ticks.
- **I3** — no capability leak into `TIER1_KINDS` consumers; full §1.5 enumeration verified
  untouched by Reviewer B (no half-migrated reader).

## Review provenance

`sensor-cap-rebase` branch: build `c82290f68` (rebased — original build was 214 commits stale,
caught and re-validated), fix-up `bed359d5d` (HIGH-A1 missing-kind validator, MED-A2
failure_mode enum, D-MEDIUM-1 narrowing rejection, C-MED-1 byte-identity + behavioural anchor
for corroborator elevation, dead `_seen_corr` branch + false comment deleted, misfiled-hybrid
collision WARN, D-LOW-2 fallthrough WARN), LOW pass `ce6158aa6` (narrowed excepts, ring-purge
invariant test — builder correctly refused my inverted purge-floor instruction — preserved-
corroborator state test, collision-WARN caplog test).

Reviewer disagreement worth recording: B/C/D read one line three ways; D's HIGH was real but
mis-attributed (both its proposed fixes would have been no-ops — the kind check already
excluded the entity). Adjudicated from source; C's drill 13 proved the branch inert.

Suite at merge: **21 failed / 8541 passed / 45 skipped / 2 xfailed** — failing names are the
pre-existing set; +16 over the v5.64.0-era baseline are this cycle's and KHOST-1's tests.

## Acceptance criteria

- **Live:** integration loads; zero URA ERROR lines attributable to `sensor_capability` /
  `sensor_role` / `_detect_duty_cycle_stuck` post-restart.
- **Live (I1):** with no capabilities declared, `binary_sensor.<room>_occupied` attributes and
  D2 stuck notifications behave identically to v5.64.0 (no new stuck flags, no vanished ones,
  within the observation window).
- **Live (declaration path — the point of the cycle):** operator declares
  `{"binary_sensor.bed_presence_...": {"kind": "bed"}}` on Master Bedroom → options save
  round-trips → subsequent nights produce **no duty-cycle-stuck NM for the bed sensor** while
  it remains available as a corroborator.
- **Live (validator):** a capability with a missing `kind` or a motion-wired entity retagged
  `mmwave` is rejected at save with a human-readable error.

## Live Validation

### Validated 2026-08-10 (v5.65.0 boot ~09:5x CDT)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Integration loads; zero URA errors | **PASS** | All 41 config entries `loaded`; `system_log` ERROR search for `universal_room` empty post-restart AND post-declaration-reload; 190 URA sensors up; house_state `home_day`; zones z1/z2/z3 reporting |
| L2 | I1 — behaviour identical with no declarations | **PASS (window)** | No new stuck-signal NMs, no vanished entities, zone/room occupancy normal between boot and declaration. Longer-horizon proof is organic by construction (I1 is mutation-anchored in-suite) |
| L3 | Declaration path round-trips | **PASS** (organic half open) | `sensor_capabilities = {'binary_sensor.bed_presence_2bd7b4_bed_occupied_either_fast': {'kind': 'bed'}}` persisted via the options flow (entry reloaded cleanly, all 62 sibling option keys byte-intact); form re-entry renders the stored JSON pretty-printed. **Organic:** no duty-cycle-stuck NM for the bed sensor over the coming nights — the founding use case |
| L4 | Validator rejects bad payloads live | **PASS** | Live submit of `{"trust_class": "strong_evidence"}` (no `kind` — the HIGH-A1 shape) → `sensor_capabilities_invalid`, save aborted, stored declaration untouched |

Boot-only transients: none observed (websocket took ~2 min to accept connections post-boot; normal).

Notes: the deploy was also the **first live execution of the BOARD-CURRENCY-1 `--cards` gate** —
step 4b marked the card `shipped_organic v5.65.0`, bumped `meta.last_reconciled`, and wrote
vibememo entry 034 inside the release flow, exactly as rehearsed in dry-run. PR #494:
47 files, +8635/−178 (non-empty verified).
