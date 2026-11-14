# Plan review 1: NVR witness layer (Tier 3, completeness + framing G)

Plan: `docs/planning/PLANNING_nvr_witness_layer.md` at develop fd5e5be3. Card NVR-WITNESS-CONSOLIDATION-1.
Charter: `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. ura-arc skill loaded. Read-only: code greps on develop,
live registry and config entries read from `/Users/okosisi/ha-config/.storage` (no writes). No pytest.

Verdict: **FIX-PLAN** (2 HIGH, 5 MEDIUM, 4 LOW). The diagnosis, the core design and the REUSE claims hold. What fails is the
completeness of the classifier and agreement-site inventory, which is what INV-W-ONE-CLASSIFIER and the operator's "no
drift" goal depend on.

## Framing 1: completeness

### Verified (holds)

| Claim | Evidence |
|---|---|
| garage_a cause = resolver `_N` collapse, not subscription | Live registry: Frigate device `7c45bd09…` identifiers `[frigate, 01KM239Z…:garage_a]`, no connections; Protect device `f84347c3…` no identifiers, MAC `28:70:4e:18:fc:13`. `camera.garage_a_2` is the configured egress camera (`egress_cameras` in the URA entry). `_shares_evidence_with_inputs` (`camera_resolver.py:1485-1511`) needs MAC, identifier tuple or both-Frigate, and none match. Diagnosis is consistent. |
| W1 live criterion `confidence = 0.9` is reachable once the Protect leg subscribes | `_extract_camera_stem` (`camera_census.py:1009`) strips `_N` before the person suffix, so `garage_a_person_occupancy_2` and `garage_a_person_detected` both stem to `garage_a` (`transit_validator.py:2699`). |
| Unverified claim 1: nothing decides on crossing `confidence` | Bus readers of `ura_person_egress_event`: `sensor.py:4763/4894/5004/5054`, `perimeter_alert.py:1023`, `person_sighting.py:482` (reads `identity_confidence`). DB readers of `person_entry_exit_events` (`database.py:4670, 4704`) do not select or filter on `confidence`. **Holds.** |
| Unverified claim 2: stuck-signal page helper | `domain_coordinators/_stuck_signal_nm.py:165 fire_stuck_signal(hass, kind, key, diagnosis, …, severity=None)`, one per (kind, key) per calendar day. **Exists**, but see M3. |
| REUSE cites | `resolve_detection_legs` `:1117`, `_engine_tag` `:1433` (family from integration; frigate vs frigate2 from the `_N` suffix, which is fine for family), `canonical_camera_key` `:460`, `nvr_family` `perimeter_fp_gates.py:16`, `AgreementTracker` `:129`, Store `perimeter_alert.py:5059`, `PERIMETER_AGREEMENT_SAVE_DELAY_S` `const.py:2635`, `_apply_single_source_gate` `perimeter_alert.py:4924`, `_record_leg_fire` `:2916` (plan says 2919, close enough). All correct. |
| `canonical_camera_key` ripple for garage_a | It is `min(device_ids)` over the fusion. `"7c45…" < "f843…"`, so the garage_a key **does not change** once the Protect device joins. The plan says it "becomes the smaller of the two"; that is true, but the live value stays the same. The plan should say so. |
| Parked-plan trigger | `PLANNING_crossing_vision.md:351` parks "a probe of Protect event clips" with revival at `no_frigate_event` > 25 %. D0 measured 26 % at ±10 s, so **the trigger has fired**. W4 is the correct response; §11 records the edit. |
| Stream-health S1 has no commits | `feature/camera-input-stream-health-s1` tip = develop `1d6ce7a8`. Matches the plan. |

### Findings

**H1 (HIGH, Bug Class #53 one-missed-site, #62 hollow anchor): INV-W-ONE-CLASSIFIER and its grep test miss most of the
suffix family guesses.** The test only greps `"_person_detected" in` / `"_person_occupancy" in`. That pattern exists only at
`transit_validator.py:2705-2707`. The other suffix and platform classifiers use `.endswith(` or `CameraInfo.platform`, so
the grep never sees them:
- perimeter: `_leg_tag` `perimeter_alert.py:578-583`; `base_engine` `:623-657` (this suffix-derived engine feeds
  `nvr_family` at every gate site); `_is_frigate_person_entity` `:4525-4528`; `:671`, `:708`.
- census: `CameraInfo.platform` set by suffix or platform at `camera_census.py:635-649`, `:985-990`, `:1143`, `:1171`,
  `:875-898`. It is consumed as the family by `_cross_validate_platforms` and the snapshot at `:2026`, `:2105`, `:2195`,
  `:2827`, `:5984`, `:6000`, `:3796`, `:3837`.
- `perimeter_alert.py:2179` (`platform == CAMERA_PLATFORM_FRIGATE`).

W2 migrates only transit. W5 leaves census arithmetic "unchanged" and only adds `families_live` reads, so the invariant
is false on the plan's own terms. Repro: once W2 ships, `grep -n 'endswith("_person_detected")' perimeter_alert.py
camera_census.py` still returns hits, and the plan's grep test passes anyway. Fix: enumerate every classifier site in
§4, and for each one assign the deliverable that migrates it or a written KEEP reason (for example, census
`CameraInfo.platform` picks the count sensor and is not a family vote). The grep test also has to cover `endswith(` and
`.platform ==` forms.

**H2 (HIGH, completeness and concept split #63): a fourth Frigate-vs-Protect agreement site is not listed.** Room camera
fusion classifies `agreement` (`no_sources` / `single_source` / `unanimous_on` / `unanimous_off` / `split`) across all
fused sources, Frigate and Protect alike (`binary_sensor.py:1827-1860`). `fan_veto.py:424-441` makes a decision from
it: DENY on `split`, GRANT on `unanimous_on` / `single_source`. The plan says there are "three meanings of agree" (§1.1)
and three rule sites (§11 M13). This is a fourth, and it drives an actuator decision. It is not a consumer, not a
non-goal and not KEEP-with-reason. Fix: add it to §2/§4 with a decision. It can be KEEP (state-level "now", not
windowed) with the reason written down, or a W5-style opt-in reader.

**M1 (MEDIUM, ripple completeness): the W1 blast-radius list misses callers.** The resolver callers that pass through the
`_N` collapse in `resolve_capabilities` (`camera_resolver.py:870`, collapse `:984-1004`) are:
- `__init__.py:647` (room fusion)
- `binary_sensor.py:1596` (room fused sensor, which feeds fan_veto)
- `camera_census.py:857`
- `transit_validator.py:2407` (door-group key)
- `person_sighting.py:334, :503`
- `camera_resolver.py:829/833/863` (pick resolution)
- **`perimeter_alert.py:2341` → `resolve_detection_legs` → `resolve_capabilities` `:1171`**

The plan lists room fusion, fan veto, pick resolution and the key. It omits transit `:2407`, `person_sighting:503` and
perimeter. With W1, perimeter's egress-role wiring of `camera.garage_a_2` gains the Protect leg. That changes garage_a's
`families_live` and AgreementTracker samples in Part A code, so §9's "Perimeter Part A is not reopened" does not hold for
W1. Fix: list every caller, and add perimeter to `test_fusion_callers_golden_except_garage_shape` with garage_a's
expected delta written out.

**M2 (MEDIUM, dependency ordering): W2 depends on a getter that does not exist yet.** INV-W-ONE-HEALTH reads stream
death "only through the stream-health getter", keyed by camera entity. §11 says that getter is an S2 edit to the
stream-health plan. §9 orders W2 after "crossing vision Phase 1 + read-API ship 1" only, with no S2 dependency. Fix: put
S2 (camera-keyed getter) in §9 ahead of W2, or define W2's behaviour when the getter is absent.

**M3 (MEDIUM, hollow trip-wire): W3 must pass `severity="HIGH"`.** `fire_stuck_signal` defaults to MEDIUM, and its own
docstring (`_stuck_signal_nm.py:177-180`) says MEDIUM "reaches no channel under the live NM config … a trip-wire meant to
page passes HIGH". W3 does not name a severity, so a builder following the default ships a silent page. Add the severity
and a test that checks it.

**M4 (MEDIUM, discriminating acceptance): W5 perimeter flip has no rate-semantics guard.** §4 notes that the layer's rate
(all episodes) differs from the tracker's (alerts only). The single-source demote is a security-class de-escalation. W5
tests only "opt-out byte-identical" and "opt-in demotes on layer rate". Add a pre-flip criterion: over the W2 ≥ 14 days,
replay how many past alerts would change demote outcome under the layer rate at the current threshold, and get the
operator's ok if the count is non-zero.

**M5 (MEDIUM, W4 resolver helper): the Protect event entity must be resolved by device, never by name.** Live registry
example: `event.garage_a_garage_doorbell_lite_smart_detection` sits on the Doorbell Lite device (`aba94d43…`), and
`event.garage_a_garage_a_smart_detection` sits on garage_a. A stem or name lookup would cross-wire the two door cameras.
§3 says "per device lookup", but W4's tests should include this exact pair.

**L1 (LOW): missed REUSE.** `_frigate_object_name_for_device` already exists (`camera_resolver.py:1513`, used at `:1020`).
W1 should reuse it and cite it.

**L2 (LOW):** state the live `canonical_camera_key` outcome for garage_a (unchanged, see above).

**L3 (LOW):** the "separate card" for the Protect face-name non-goal is `D1-PROTECT-FACE-BRIDGE-ADDON-1`. Cite it so the
deferral is linked.

**L4 (LOW):** add `transit_validator.py:417` (the registry-update rebuild fires only for `unifiprotect` entries) to §4.
Its interaction with W2's own `entity_registry_updated` rescan should be a single rescan path, not two.

## Framing G: goal fidelity

| Operator said | Plan | Verdict |
|---|---|---|
| "exercise both nvr platforms simultaneously, then cross compare" | W2 records every fire from both families; W4 gives crossing vision a Protect clip | Delivered. The default `disagreement` for dual-witness analysis is narrower than the literal "both". The plan surfaces this as Q1 for the operator (rule 3 ok). **G-M1:** mark Q1 as blocking W4 build, not a default the builder adopts. |
| "How can protect be a separate witness?" | W4 gap-fill + dual witness, plus W1 restoring garage_a's Protect leg | Delivered. |
| "centralize the rules to deconflict to increase confidence" / "no drift … one place" | Evidence, classifier, `corroborated()` and the agreement record are centralised; policy stays per feature (operator ratified this on the card) | **Partially delivered (G-H1 = H1 + H2).** Two "one place" claims are false as scoped: family classification stays scattered in perimeter and census, and the room-fusion `agreement` used by fan veto is not mentioned. Neither is deferred with the operator's yes. That is silent drift against "no drift", and it needs either migration or an explicit operator-approved KEEP. |
| Agreement record: "Critical for learning. Has to be baked into the design" | Episodes persisted in a Store, the `agreement()` API, a diagnostic sensor, consumer-supplied windows, first-class in W2 | Delivered. |
| "not necessary to disturb what's in flight" | Opt-in knobs, ordering after S1 / Phase 1 / Part A | Mostly holds. W1 does reach Part A perimeter wiring (M1), which is a small, defensible change, but the plan should name it. |
| AWAY fast (hard constraint) | No AWAY, house-state or lock path | Holds. Nothing in W0-W5 sits on the AWAY path. |
| Security de-escalate only ≥ 0.9 | The perimeter demote is a severity de-escalation, but not identity-based. W5 changes its rate source | No direct breach. M4 is needed so the flip cannot quietly widen de-escalation. |
| Deferrals | Protect face path (card exists, L3), Reolink/Dahua/Amcrest as witnesses, DB table (trigger stated), ground truth → M10 | All have triggers or cards except the H1/H2 sites, which are neither deferred nor delivered. |

Risk reduction did not change what is delivered: W5's 14-day wait and opt-in flips are sequencing, and the Protect
witness and the agreement record ship in W2/W4.

## Must-fix before build

1. H1: full classifier-site inventory with a migrate-or-KEEP decision per site; widen the grep test.
2. H2: add the room-fusion `agreement` / fan_veto site with a decision.
3. M1-M5: list every W1 caller including perimeter; put S2 ahead of W2; W3 pages at HIGH; W5 replay criterion; W4
   device-keyed event lookup test.
4. G-M1: make Q1 blocking for W4.
