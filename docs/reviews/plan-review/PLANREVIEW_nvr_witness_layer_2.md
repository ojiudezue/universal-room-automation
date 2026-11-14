# Plan review 2: NVR witness layer (Tier 3, adversarial build-prediction)

Plan: `docs/planning/PLANNING_nvr_witness_layer.md` at develop eddb2c48. Card NVR-WITNESS-CONSOLIDATION-1.
Framing: "what will the builder get wrong reading this?" Disjoint from review 1 (completeness + goal fidelity).
Read-only: plan, review 1, and code at the cited lines on develop. No pytest. HVAC and presence state-of-play docs were
not read: no finding here depends on HVAC or presence-fusion detail. W5c builders must still read them (plan header).

Verdict: **FIX-PLAN** (4 HIGH, 7 MEDIUM, 4 LOW). The design holds up. The problems are instructions a builder cannot
follow as written: two invariants contradict each other, the episode model cannot answer the windowed queries the API
promises, the family value space does not match census's, and W1's new evidence is the same name evidence the guard was
written to distrust.

## Review 1 must-fixes: spot-check that each is closed in the text

| Item | Closed? | Where |
|---|---|---|
| H1 classifier inventory + wider grep | Yes, in the text. But see H1 below: the widened grep now conflicts with INV-W-OPTOUT | §4.1, §6 |
| H2 room fusion / fan veto site | Yes | §2, §4.2, W5c |
| M1 every W1 caller incl. perimeter | Yes; garage_a delta named | §5, W1 tests |
| M2 S2 before W2, absent-getter rule | Yes | §9 step 3-4, INV-W-ONE-HEALTH |
| M3 W3 at HIGH + test | Yes | W3 |
| M4 replay gate | Yes | W5a |
| M5 device-keyed event entity test | Yes | W4 tests |
| G-M1 Q1 blocking | Yes | W4, §12 Q1 |
| L1-L4 | Yes (`_frigate_object_name_for_device` is at `camera_resolver.py:1519` on develop; key unchanged stated; card cited; `:417` listed) | §3, §5, §10, §4.3 |

## Findings

**H1 (HIGH, plan self-contradiction, #62 hollow anchor): INV-W-ONE-CLASSIFIER and INV-W-OPTOUT cannot both hold, and
the builder will break one of them.** INV-W-OPTOUT requires that, with `NVR_WITNESS_USE_TRANSIT=False`, transit is
byte-identical to develop. Develop's transit classifier is the substring test at `transit_validator.py:2705-2708`,
including the `fired_platforms.add(entity_id)` fallback for unknown entities. Keeping the opt-out means keeping that code.
The W2 grep test (`test_one_classifier_grep`) forbids `"_person_occupancy" in` in `transit_validator.py`. The same
conflict applies to perimeter (gated by `_PERIMETER_CLASSIFIER` when W0 finds mismatches) and to census and room fusion,
where W5b and W5c keep the legacy path behind knobs. Timing makes it worse: the grep test lands in W2, but the census
(`camera_census.py:635-649`, etc.) and room fusion sites migrate in W5b/W5c, months later. Predicted build: the builder
either deletes the legacy branch, which breaks OPTOUT, or allowlists the legacy lines "until W5", which makes the
invariant hollow. Fix: state the invariant per phase. (a) In W2 the grep test covers only W2's sites. W5b and W5c each
extend it when they ship. (b) Every legacy opt-out branch is allowlisted by name, with the knob that keeps it alive and
the supersession step that deletes it. (c) Pair the grep with a behavioural test: a registry-only family (an entity whose
suffix says Frigate but whose device is Protect) must classify by device at each migrated site with the knob on.

**H2 (HIGH, under-specified data model): the episode record as specified cannot answer `families_fired(cam, t,
window_s)` / `corroborated` for a window shorter than the episode, and nothing caps episode length.** W2 persists, per
closed episode, "per-family first and last fire time and count". Transit needs "did ≥2 families fire within 10 s of t"
(`transit_validator.py:2689-2712`). Inside a 5-minute episode where Protect fired at the start and the end, first/last
cannot say whether Protect fired within 10 s of t. Because a new fire within the gap extends the episode, a camera with
continuous activity (pool overhead with swimmers, a busy doorbell) chains into one hours-long episode, which becomes one
agreement sample. INV-W-ONE-EPISODE then undercounts samples badly for exactly the busiest cameras. Fix: (a) keep raw
fire timestamps in memory per (cam, family) for at least max(consumer windows), and answer `families_fired` /
`corroborated` from them. Episodes are the persisted history only. (b) Add `NVR_WITNESS_EPISODE_MAX_S` (rung 1, with a
stated default) that force-closes an episode. (c) Test: 20 minutes of fires 30 s apart gives ⌈20·60/MAX⌉ episodes, not 1.

**H3 (HIGH, #22 enum mismatch): W5b "`CameraInfo.platform` assignment via `family_of`" mixes two value spaces.**
`CameraInfo.platform` holds `CAMERA_PLATFORM_UNIFI = "unifiprotect"` (`const.py:2432`) and the Reolink/Dahua constants.
`nvr_family` returns `"protect"` (`perimeter_fp_gates.py:16-29`) and `""` for an empty engine; the plan calls that
"unknown" (§4.1). If the builder assigns `family_of(...)` directly, every Protect camera's platform becomes `"protect"`.
Then every `== CAMERA_PLATFORM_UNIFI` read in census (snapshots `:2026, :2105, :2195, :2827, :3796, :3837, :5984, :6000`)
silently stops matching, and `_cross_validate_platforms` treats Protect counts as some other platform. Develop also has
a deliberate fallback that a straight swap would drop: an unknown integration with a `_person_detected` suffix is treated
as UniFi-like (`camera_census.py:648-650`). Fix: specify a mapping function (`family → CAMERA_PLATFORM_*`), name the
unknown sentinel string, state what happens to the UniFi-like fallback, and require a census golden test over every
snapshot field.

**H4 (HIGH, W1 safety, re-opens the A-MED-2 hazard): the Frigate object name is not independent evidence in the
realistic collision case.** HA names a Frigate camera `camera.X_2` because a Protect `camera.X` already exists, which
means the Frigate object name IS `X`. W1's new rule (candidate stem == input Frigate object name,
`camera_resolver.py:1001-1004` + `:1519`) therefore collapses every Frigate/Protect pair that share a display name,
whether or not they are the same physical camera. That is exactly the case the guard (`:996-1004`,
`test_camera_resolver.py:970`) exists to refuse. The plan's "discriminating" test (Frigate object name `camera_a_2`) is
not that case: an object name `camera_a_2` gives `camera.camera_a_2` with no collision at all. On this house the
collapse is correct (garage_a). On a second install (portability is imperative), two different cameras both called
"driveway" fuse, and that cross-wires transit, census, perimeter and room fusion at once. Fix: either (a) take the risk
explicitly. The plan names the residual, the operator accepts it, and the test pair becomes "same object name, distinct
camera: collapses (documented)" so the behaviour is pinned rather than hidden. Or (b) require a second signal, for
example a unique match: exactly one non-Frigate device on that dstem, and no other Frigate device with that object name.
Add the knob-off golden: `RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE=False` gives byte-identical fusion for every caller.

**M1 (MEDIUM, lifecycle ambiguity): who builds, owns and tears down the layer, and when do readers fetch it?**
"built in `__init__.py`" does not say which entry. Transit (`__init__.py:3464`), perimeter (`:3509`) and census
(`:2938-2950`) are built in the integration entry block. Room fused sensors (`binary_sensor.py`) set up per room entry,
possibly before the integration entry. Predicted errors: building the layer per entry (40 rooms gives 40 subscribers and
40 Stores on one key), or a consumer caching `hass.data[DOMAIN]["nvr_witness"]` at construction and holding a dead
reference after an integration reload. Fix: build once in the integration-entry block, before transit, perimeter and
census; unload with that entry. Consumers fetch it lazily on each call and fall back to legacy when it is absent. Add a
test: a reload of the integration entry leaves no orphan listener, and consumers see the new instance.

**M2 (MEDIUM, restart): episode close needs an owner.** "Only closed episodes persist; an open episode is dropped at
shutdown." If closure is lazy (on the next fire), a quiet camera's last episode stays open until the next activity,
possibly hours. It is invisible to `agreement()` and lost at every restart, a systematic bias against sparse cameras.
Fix: close on a superseding `async_call_later(gap)` per camera, tracked and cancelled at teardown (or close lazily at
read time using `now`). At shutdown, close episodes whose gap has already elapsed before the final save. Test: fire,
wait > gap, restart: one persisted episode.

**M3 (MEDIUM, definition missing): what counts as a "fire".** Transit counts any state that is `on` / `true` / `1` or a
digit > 0 (`transit_validator.py:1355-1359`) and also listens to count sensors (`_on_egress_count_change`, `:1393`).
Perimeter records leg fires in its own path (`:2916`, `:4375`). The plan never says whether a fire is an off→on edge,
any update while on, or a count increment, or whether `last_changed` or callback `now` is the timestamp. `test_transit_optin_matches_legacy_on_door_fixture`
can only pass if the layer's fire definition and clock match transit's, including the ±10 s boundary. Fix: define a fire
(an edge, with count sensors 0→>0), the timestamp source, and whether `families_fired` is symmetric (transit is: it
resolves after the entry window, so later fires count; `:2165` with the delay at `:1387`).

**M4 (MEDIUM, ambiguous API): `agreement(cam, window_s, min_samples)` mixes up three windows.** For perimeter it is
written as `agreement(cam, 60, 20)`, where 60 is the tracker's pair window. In the episode model, though, pairing IS the
episode, so `window_s` has no defined meaning. The tracker also scores the last N outcomes (`perimeter_fp_gates.py:139,
:166`), and the layer API has no last-N argument. Fix: name the parameters (`last_n`, `min_samples`, and `pair_window_s`
if it is still meaningful), and say which perimeter tracker parameter each one replaces.

**M5 (MEDIUM, schema for more than two families): `both / frigate_only / protect_only` is hard-coded for two families.**
Pool overhead has four integrations (memory `reference_pooloverhead_four_integrations`), and the plan says Dahua, Amcrest
and Reolink "keep their own family". What does the record hold when Frigate and Dahua fire? For a camera with only one
family live, every episode is "frigate_only", and W3 or a future scorer reads that as disagreement. Fix: store a
per-family set per episode. Define `both` as frigate ∧ protect. Mark single-family cameras `ineligible` in the sensor and
the scorer, and exclude them from W3.

**M6 (MEDIUM, config extremes): the gap ≥ window rule is prose, not enforced.** Defaults: gap 60 = the perimeter window
60 (equality boundary). Transit 10. If either window is raised above the gap (rung-1 edit), one physical event splits
into two episodes, and a Frigate-then-Protect pair lands as frigate_only + protect_only, so the rate falls. Fix: a test
asserting `NVR_WITNESS_EPISODE_GAP_S >= max(TRANSIT_PLATFORM_WINDOW_S, perimeter window, any W5 window)`, with an
inversion test (gap 5, window 10) that documents the split. Do the same for `PRE_S/POST_S` versus the crossing vision
cap.

**M7 (MEDIUM, persisted-data migration unstated): the existing `universal_room_automation.perimeter_agreement` Store.**
The plan keeps the tracker until W5a but never says the new Store starts empty and does not import the old samples. A
builder may "migrate" the alert-only outcomes (`to_dict` = per-camera bools, no timestamps, no families) into episodes.
That pollutes the record with a different rate semantics (§4.3 caveat) and false timestamps. Fix: one sentence. The
layer starts empty. The old Store is read only by perimeter until the W5a flip, and is deleted in the supersession audit.
Also state the key-orphan rule: when a fusion change moves a `canonical_camera_key`, the old key's episodes age out
(or are pruned on load when the key is not in the current fusion set).

**L1 (LOW, ordering ambiguity):** §9 says "W1 after S1 merges", but §12 Q4 recommends shipping W1 ahead as its own cycle.
S1 had no commits at review 1. Say which wins, and if W1 waits on S1, give the reason (shared resolver callers).

**L2 (LOW, write volume, unmeasured):** a full-dict `async_delay_save` every 30 s, with N cameras × 500 episodes ×
per-family fields. The §10 1 MB revival trigger needs a sizing line from W0 and a test that the serialized store stays
under a stated byte bound at `HISTORY_N` for the W0 camera count.

**L3 (LOW, per-tick cost):** `family_of` does entity- and device-registry lookups. W5b calls it from census ticks over
every camera. Cache it per entity_id and invalidate on the single W2 rescan path.

**L4 (LOW, golden coverage for INV-W-OPTOUT):** opt-out golden tests are named for transit, perimeter and room fusion.
Census has only `test_census_counts_unchanged_with_layer` (counts, not the agreement tag or snapshot). Crossing vision
"mode off" has a Verify line but no named test. `NVR_WITNESS_ENABLED=False` (all consumers legacy, no subscriptions) has
no test. Name one golden per consumer plus the master kill, each driving a fixed fire-sequence corpus.

## Must-fix before build

1. H1: phase INV-W-ONE-CLASSIFIER per deliverable, allowlist each legacy opt-out branch with its knob and deletion step,
   and add the behavioural (device-not-suffix) test per migrated site.
2. H2: in-memory raw-fire ring for windowed queries, plus an episode max-duration knob and test.
3. H3: a family → `CAMERA_PLATFORM_*` mapping, the unknown sentinel, the UniFi-like fallback decision, and a census
   golden test.
4. H4: either accept the same-name residual with the operator and pin it with a test, or add a uniqueness condition.
   Add a knob-off golden.
5. M1-M7: owner entry and lazy fetch; an episode close timer; the fire definition and clock; named `agreement`
   parameters; the multi-family schema with an ineligible state; an enforced gap ≥ window test; a "new Store starts
   empty" sentence plus the key-orphan rule.
