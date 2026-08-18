# AUDIT — Exterior census supersession: is swapping the naive per-camera-bit sum for the track-deduped count SAFE?

**Date:** 2026-08-17 · **Mode:** READ-ONLY adjudication (code inspection only; no code touched, no pytest, DBs untouched)
**Occasion:** Operator ruling — *"the new work should supersede the exterior census. I want to be sure it's not harmful."*
**The swap under audit:** replace the exterior head-count producer in
`PersonCensus._calculate_property_census` (`camera_census.py:1502-1580`, the per-camera OR-sum) with
`ExteriorTrackLinker.census_counts()` (`exterior_track_linker.py:767-777`, adjacency-deduped tracks).
**Read first:** `RESEARCH_census_vs_guest_separation.md` §3, KANBAN `CENSUS-ACCURACY-1`.

**Bottom line up front:** the swap is **SAFE for trust/actuation** (the exterior census is fully
stranded — no coordinator gates any house-state, guest, NM, or safety decision on it) but the
deduped producer can **structurally UNDER-count** in exactly the scenario the operator cares about
(two people collapsing into one track; linker disabled/booting → 0). Because the operator has made
exterior-count accuracy a first-class SECURITY concern, and because the deduped number is **already
published on its own live sensor**, the recommendation is **KEEP BOTH** (do not destroy the naive
sensor). Details and per-question verdicts below.

---

## Q1 — Every consumer of the exterior census output

**Producer surface.** `_calculate_property_census` returns a `CensusZoneResult` with `zone="property"`
(`camera_census.py:1567-1580`). It flows into:
- `total_on_property = house.total_persons + property.total_persons` (`camera_census.py:1137`)
- the `CensusResult` fields `property_exterior`, `total_on_property`, `persons_outside` (`:173-177`, `:1141-1142`)
- the dispatch payload key `property_count = property_result.total_persons` + `total_on_property` (`camera_census.py:1184-1185`), on `SIGNAL_CENSUS_UPDATED`.

**Exhaustive consumer grep** (`property_count`, `total_on_property`, `persons_outside`,
`property_exterior`, `persons_on_property` across the whole integration):

| Consumer | file:line | Trust or Display? | Gates house-state / guest / NM / safety? |
|---|---|---|---|
| `URAPersonsOnPropertyExteriorSensor` (state + `confidence`/`source_agreement`/`peak_held` attrs) | `sensor.py:3593-3621` | **Display** | No |
| `URATotalPersonsOnPropertySensor` (state + `unidentified_total`/`exterior_confidence` attrs) | `sensor.py:3625-3692` | **Display** | No |
| Frontend PWA "On property" card | `frontend-v3/assets/Presence-*.js` | **Display** | No |
| Dispatch key `property_count` | emitted `camera_census.py:1184` | — | **ZERO readers.** `PresenceCoordinator._handle_census_update` reads only `interior_count`, `unidentified_count`, `confidence` (`domain_coordinators/presence.py:4310,4320,4337`). |
| `source_agreement` (exterior) | hardcoded `camera_census.py:1548-1557` | Display attr only | No |

**Independent verification of the "fully stranded" claim (operator asked to VERIFY, not trust):**
- `grep property_count` across the integration → only `camera_census.py` (producer) + the dead payload key. No presence/security/house_state/safety/hvac reader.
- `grep total_on_property | persons_outside | property_exterior | persons_on_property` outside
  `camera_census.py`/`sensor.py`/frontend → **zero hits** in any coordinator.
- The one-way NM coupling the research names is confirmed *in the other direction*: the exterior-person
  NM hazard (`NM_HAZARD_EXTERIOR_PERSON`, `const.py:1547`) is fired by `perimeter_alert.py` off **camera
  rising edges directly** (`perimeter_alert.py:1432,1970`, "Always feeds the linker … Both use rising
  edges" `:796,:2540,:2568`), NOT off the census exterior count. `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY`
  (`const.py:1617,1627,1711-1712`) is guest-state → severity shaping; nothing reads the exterior *count*
  to make an NM decision.

**VERDICT Q1: SAFE.** Every consumer of the exterior census output is a display sensor or a dead
dispatch key. No trust decision anywhere in the system depends on the exterior head count. Swapping the
producer cannot change any actuation, house-state, guest, NM, or safety outcome. The research's
"fully stranded" claim is independently confirmed by grep.

---

## Q2 — Semantics of the two producers, and where they disagree

**Naive** (`camera_census.py:1519-1523`): `exterior_count = Σ over (egress+perimeter) cameras of
is_entity_on(cam)`. One person visible to 3 perimeter cameras = **3**. `identified_count` hard-zero
(`:1569`). No dedup, no identity, no track.

**Linker** (`exterior_track_linker.py:767-777`): `exterior_person_tracks_active = len(open person
tracks)` + `exterior_unidentified_persons = Σ tracks not identified`. One walker across 3 adjacent
cameras within `TRACK_LINK_WINDOW_S=180 s` links into **1** track (`_find_link_target :581-602`:
attaches when `same OR adjacent` and within window). Identity-aware (sub_label promotion → `identified`).

**Where they disagree, and direction:**

**(a) Can the linker UNDER-count in a security-relevant way? YES — two ways, both real:**
1. **Two distinct people collapsing into one track.** `_find_link_target` picks the *nearest-in-time*
   open track that is on the same or an adjacent camera (`:592-602`). Two people walking in together
   across adjacent perimeter cameras within 180 s: the second person's detection attaches to the first
   person's open track → **2 people read as 1**. This is precisely the operator's Q5 worry and it is
   structurally reachable, not hypothetical.
2. **Real person whose camera is absent/mis-mapped in `EXTERIOR_ADJACENCY_GRAPH`** (`const.py:1742-1800`).
   Here the failure is actually the *opposite* (over-count): a non-adjacent hop opens a NEW track
   (`best=None` → new track), so a single walker across two non-adjacent cameras reads 2. The
   adjacency-probe audit's standing policy is "fix detection, don't add false edges"
   (`AUDIT_exterior_camera_adjacency_probe.md`), i.e. missing edges are tolerated as splits =
   over-count, not under-count. So graph gaps are NOT an under-count source; item (1) is the real one.

**(b) Can the linker OVER-count?** Yes, mildly — split tracks from missing adjacency edges (above),
and momentarily during the `TRACK_CLOSE_IDLE_S=300 s` window where a departed person's track stays open.
Both are *less* over-count than the naive Σ-per-camera, which is the whole point of the swap.

**(c) Behavior when disabled via `switch.ura_security_coordinator_exterior_path_tracking`:**
the switch sets `tracking_enabled=False` and calls `drain_open_tracks("operator_off")`
(`switch.py:5764,5771`, `exterior_track_linker.py:616-627`). `observe()` then early-returns
(`:418`), all tracks drain, and `census_counts()` returns **0** for every key. Same for the
`TRACK_LINK_WINDOW_S==0` kill switch. **A swapped exterior census would read 0 whenever exterior path
tracking is off** — where the naive sensor would still report live perimeter camera hits. For a
display that the operator watches as a security surface, a hard 0 while a camera is firing is a
worse failure than an over-count.

**VERDICT Q2: CONDITIONALLY-SAFE-WITH-GUARD.** The linker is more *accurate* (fixes 1-walker-reads-3)
but introduces a genuine security under-count (two-into-one collapse) and goes to 0 when disabled.
Direction of error flips from "fails high" (naive, conservative for perimeter security) to "can fail
low" (linker). Acceptable only if the naive/raw evidence is not destroyed (see recommendation).

---

## Q3 — Availability / lifecycle

The naive census reads `binary_sensor`/camera states synchronously every tick and always yields a
number. The linker is an in-memory object with setup/teardown and a kill switch:
- Instantiated `__init__.py:2729-2746`, torn down `:4605-4608`; `is_active` flips on start
  (`exterior_track_linker.py:302`) / off on stop (`:347`).
- The existing linker sensors gate on it: `available = linker is not None and linker.is_active`
  (`sensor.py:3802-3803`), and `native_value` returns **0** when `linker is None`
  (`sensor.py:3810-3818`).

If `_calculate_property_census` sourced from `census_counts()`:
- **Boot (linker not yet set up):** `hass.data[...]["exterior_track_linker"]` is None → census exterior
  reads 0 (or the census would have to special-case None). The naive path has no such window.
- **Bootstrap allowlist window (`_allowlist_installed=False`, `:439-448`):** linker admits ALL Frigate
  events including interior cameras → exterior track count can transiently **over-count** with interior
  contamination (the SECC-1 incident, `:424-437`). Fail-open by design until `set_allowed_cameras()`
  runs. A swapped census would inherit this boot-window contamination.
- **Teardown / reload:** in-memory tracks are lost; census exterior → 0 until re-populated.

The existing linker *sensors* already model this correctly (they go `unavailable`). But
`_CensusBaseSensor` for the exterior census does **not** — it always renders `result.property_exterior`,
so a swapped value of 0-from-None would show as a real "0 people outside", not "unavailable".

**VERDICT Q3: CONDITIONALLY-SAFE-WITH-GUARD.** No consumer *cares* (Q1), so no actuation breaks — but
the display would silently read 0/wrong during boot, teardown, and the fail-open allowlist window, and
would need an explicit `is_active`/None fallback to the naive path to avoid a misleading "0 outside".

---

## Q4 — The hardcoded `single_source` / confidence question

Exterior census today hardcodes `source_agreement = CENSUS_AGREEMENT_SINGLE` and
`confidence ∈ {NONE, MEDIUM}` (`camera_census.py:1546-1557`), `identified_count=0` (`:1569`), and never
calls `_cross_validate_platforms()`. These fields are **display-only** (Q1: only `sensor.py:3614-3615`,
`:3656`, `:3692` read them; no trust consumer).

Under the swap:
- The linker offers **no confidence or source-agreement notion** — `census_counts()` returns bare ints.
  `source_agreement`/`confidence` would become fully synthetic (whatever the census hardcodes), i.e.
  *as* meaningless as today, just relabeled. No consumer is misled into a trust decision (there is none).
- The linker DOES offer a richer split the naive lacks: `exterior_unidentified_persons` vs
  identified tracks (sub_label-promoted). So `identified_count` could become *non-zero and meaningful*
  (an improvement over the hard 0), and `unidentified_count` could map to `exterior_unidentified_persons`.

**VERDICT Q4: SAFE (display-only), with a labeling caveat.** No consumer reads these fields for trust,
so a stale/synthetic `source_agreement` harms nothing today. But do not advertise the swapped exterior
confidence as a real agreement metric — it isn't one. If exposed, prefer surfacing the linker's own
identified/unidentified split (which is real) and drop or clearly mark `source_agreement`.

---

## Q5 — Security-specific harm check

The operator's framing: exterior-count accuracy is a first-class SECURITY concern. The swap replaces a
*possibly-over-counting* naive sensor with a *possibly-under-counting* deduped one.

- **Is the dedup ever too aggressive for security?** **Yes.** Two intruders arriving together on
  adjacent cameras within `TRACK_LINK_WINDOW_S=180 s` collapse to **one** person track (Q2a-1,
  `_find_link_target :592-602`). A perimeter display reading "1 outside" during a two-person approach is
  a real blind spot. `TRACK_LINK_WINDOW_S=180 s` is a wide window; coordinated arrival is exactly the
  adversarial case.
- **Mitigating fact:** this is a *display* blind spot only. Actual perimeter security actuation
  (`NM_HAZARD_EXTERIOR_PERSON`, recording, alert) fires off **camera rising edges in
  `perimeter_alert.py`**, independent of the census count (Q1). A collapsed track does NOT suppress an
  NM alert — each camera edge still fires. So the swap does not create a *missed-alert* security hole,
  only a *misleading-headcount-on-the-dashboard* one.
- **Countervailing fact:** the naive sensor's over-count is itself a poor security signal (1 walker
  reads 3 — cry-wolf). Neither number alone is a trustworthy intruder count.

**VERDICT Q5: HARMFUL if the swap DESTROYS the naive number; SAFE if both are kept.** The under-count
is real and lands squarely on the operator's stated security priority, but it is confined to display
because no security actuation consumes the count.

---

## Overall recommendation — KEEP BOTH

**The swap is safe to build ONLY as an ADDITIVE / dual-surface change, not as a destructive replacement
of `sensor.persons_on_property_exterior`.** Reasoning:

1. **Trust-safety is a non-issue.** The exterior census is fully stranded (Q1, independently grep-verified).
   Whatever number it shows, nothing actuates on it. This removes the entire regression class the swap
   would otherwise risk.
2. **But accuracy has a genuine two-sided error.** The naive sensor fails *high* (conservative for
   perimeter security); the linker fails *low* in the exact adversarial case the operator cares about
   (coordinated two-person arrival → 1 track) and reads 0 when tracking is disabled or booting (Q2, Q3).
   For a security head-count, silently trading a known over-count for a possible under-count is not a
   strict improvement — it moves the error to the more dangerous side.
3. **The deduped answer is ALREADY published, separately and live.**
   `sensor.exterior_person_tracks_active` and `sensor.exterior_unidentified_persons`
   (`sensor.py:3822-3868`, from `census_counts()`) already carry the correct 1-walker-reads-1 number,
   with proper `unavailable` lifecycle. There is **nothing to build to "get" the deduped count** — it
   exists. Overwriting the naive `persons_on_property_exterior` would *delete* the raw-evidence signal
   while merely relocating a number that already has a home.

**Concrete recommendation:**
- **Do NOT overwrite** `sensor.persons_on_property_exterior` with `census_counts()`. Keep the naive
  per-camera value as the raw-evidence / conservative-floor surface.
- **Compose, don't replace:** if a single "best" exterior head-count is wanted, publish it as a
  *new/derived* value = the linker's deduped count, and optionally expose a `raw_camera_bits` attribute
  = the naive sum so a two-person collapse is visible as "tracks=1, raw_bits=3, investigate". This keeps
  both the accurate count and the conservative security floor on one card.
- **If the operator insists on making `persons_on_property_exterior` the deduped number** (a display
  decision they are entitled to, since nothing actuates on it), it is **conditionally-safe with three
  named guards:** (G1) when `linker is None or not is_active`, fall back to the naive count, never 0;
  (G2) suppress/annotate the value during the fail-open allowlist bootstrap window
  (`_allowlist_installed=False`) to avoid interior-contamination over-count; (G3) drop or clearly mark
  the synthetic `source_agreement`/`confidence` and instead surface the linker's real
  identified/unidentified split. Even then, retain the naive sum as an attribute so the two-into-one
  collapse is not invisible.

**Note vs KANBAN `CENSUS-ACCURACY-1` rescope (2026-08-17):** the card was rescoped to DECAY + suffix
fix, with dedup-repair dropped because the probe measured it buys ~0. This audit concerns only the
*exterior* supersession (research §5 change #7), which is orthogonal to the interior decay work and
should be judged on its own security merits as above.

---

### Per-question verdict summary

| Q | Topic | Verdict |
|---|---|---|
| 1 | Consumers / stranding | **SAFE** — fully stranded, no trust consumer (grep-verified) |
| 2 | Producer semantics / disagreement | **CONDITIONALLY-SAFE-WITH-GUARD** — real two-into-one under-count; 0 when disabled |
| 3 | Availability / lifecycle | **CONDITIONALLY-SAFE-WITH-GUARD** — boot/teardown/allowlist window read 0/contaminated |
| 4 | `single_source` / confidence | **SAFE (display-only)** — synthetic fields harm nothing; linker offers a real id/unid split instead |
| 5 | Security under-count | **HARMFUL if naive destroyed; SAFE if both kept** — collapse is display-only, no missed NM alert |

**Overall: SAFE-WITH-NAMED-GUARDS, and the honest answer is KEEP BOTH** — retain the naive sensor as the
conservative security floor / raw-evidence surface, and let the already-live `exterior_person_tracks_active`
/ `exterior_unidentified_persons` carry the deduped count. Do not overwrite `persons_on_property_exterior`.
