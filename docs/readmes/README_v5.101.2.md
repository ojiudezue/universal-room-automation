# URA v5.101.2 — Exterior seam ratification, TOU rate-file hardening

**Shipped:** 2026-09-14
**Tier:** 2 (operator-ratified data change to a safety-adjacent primitive + a new validation path on a cost-relevant loader)
**Cards:** CAMERA-SEAM-VALIDATION-1 · TOU-RATE-FILE-KEY-UNWIRED-1 · TOU-FILE-NO-RATE-VALIDATION-1 ·
TOU-FILE-TOGGLE-AND-LOUD-FAILURE-1 · OVERRIDE-COUNT-STARTUP-AUDIT-UNTESTED-1 (rode v5.101.1)

Five branches, integrated and merge-tested together before ship.

---

## D1 — Exterior camera seams re-ratified: 27 → 21, and one camera was missing

The operator validated every declared camera adjacency against the physical property and supplied
a single ring covering all **thirteen** exterior cameras. Ten seams were struck as physically
impossible (an intervening camera was named for most; two were "opposite sides of the house").

**The missing camera.** An earlier pass read the ring as twelve cameras and mapped the operator's
label "Madrone PT Ultra/Reolink hub" onto `reolinkstudybporchptz`. **There are two Reolinks.**
`madroneptultra` and `reolinkstudybporchptz` are distinct devices, each with its own Frigate person
detector. An earlier hypothesis — that `pool_equipment` and the Reolink slot were *swapped* — was
**wrong**; the ring was never mis-ordered, it was missing a node.

Result: **21 seams** = 13 ring edges + 8 operator-validated skips. Zero dead ends, zero fenced
pairs live.

**The derived constant moved with it.** `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS` is *computed*
from the graph, so striking `front_door_aerial↔hot_tub` drops `hot_tub` out of it, and
`front_door_aerial` drops out because it *is* an egress camera. **Behaviour change:** a track seen
only on `hot_tub` no longer auto-classifies `approach`.

**Egress cameras are not all exterior** (operator ruling): the garage cameras watch a way *into*
the house but sit inside the garage and do not see external people. The seam spec now splits
`egress_cameras` into `exterior` / `interior`, derives egress-adjacency from **exterior only**, and
makes an interior camera appearing in the exterior ring an error.

### Acceptance criteria
- **Verify:** graph has 13 nodes / 21 undirected edges, no node of degree < 2, connected.
- **Verify:** no fenced pair present (12 struck pairs listed in-source).
- **Test:** `test_seam_graph_invariants.py` — egress-adjacent equals the graph-derived set; no
  egress camera appears in the egress-*adjacent* list; fenced seams stay struck; no dead ends.
- **Live:** perimeter alerting continues to fire; no new ERROR from `exterior_track_linker`.

---

## D2 — Seam file format + validator (`exterior_seams.py`)

New declarative, ring-first file so the graph can be corrected without a code change. Six
validation rules, **whole-file rejection only** — there is no partial-apply path, because a
half-applied seam graph *is* the wrong-seam failure mode.

**Why strict:** a WRONG seam merges two different people into one track and **suppresses the
second alert** (silent). A MISSING seam only fragments one person into noisier alerts (loud,
never silent). Rejection is the safe direction.

Rules: unknown camera (catches naming a camera the integration doesn't watch) · ring coverage
(warn) · no dead ends · connectivity · fenced pair present (**error**, never a silent drop) ·
implausible skip span (warn) · interior-egress-in-ring (error).

The ratified file ships at `docs/examples/exterior_seams.example.json` and is placed live at
`/config/universal_room_automation/exterior_seams.json` — the path `DEFAULT_EXTERIOR_SEAM_FILE`
points to, so the drop-a-file route and a future config-flow picker converge on **one** location.

**NOT wired as a loader in this release.** The file is the record and the validator is tested;
consuming it at runtime is a follow-on (D4 reload button, D5 provenance, D3 upload picker).

### Acceptance criteria
- **Test:** 18 tests; ring-only yields 13 edges, +skips yields 21.
- **Test:** each rule rejects a purpose-built bad file; a fenced pair re-added is an error.
- **Verify:** the live file round-trips clean — 21 edges, zero errors, zero warnings,
  egress-adjacent derives to exactly 5 cameras.

---

## D3 — TOU rate-file: the config key now actually works

`CONF_ENERGY_TOU_RATE_FILE` was defined and **never read** — the path was hardcoded, so setting it
did nothing. (Independently corroborated: `AUDIT_excess_solar_and_evse_prior_art.md:249` recorded
it as dormant.) It is now read at the load site with `DEFAULT_TOU_RATE_FILE` as fallback, plus a
path-safety guard: absolute paths and `..` traversal are rejected and warned, so a config key
cannot become an arbitrary-file-read primitive.

### Acceptance criteria
- **Test:** unset key → default path; traversal/absolute → rejected; wire-in anchor asserts the
  call site passes the resolver's output.
- **Verify:** behaviour byte-identical when the key is unset.

---

## D4 — TOU rate file: validation (the silent-zero-rates hole)

The loader performed **no validation at all** — `grep -cE "raise |ValueError"` returned **0**. A
misspelled rate field fell through `period_data.get("rate", 0.0)` and silently priced electricity
at **zero**, while `rate_source` reported the file as authoritative. That corrupts every arbitrage
and load-shifting decision.

Now: an explicit numeric rate is **required** per period; import rate ≥ 0 (export **may** be
negative — some tariffs charge for over-export); magnitude ceiling 10.0 $/kWh (a two-decimal typo
guard — real peak is ~0.16); hours must be integer `0<=start<end<=24` and non-overlapping; months
covered exactly once. Errors are collected as a **list** so the operator sees every fault at once.

**Deliberate semantic change:** an unknown period name now rejects the whole file (was warn+skip).
This unifies the loader's previously inconsistent partial-failure behaviour.

**Measured blast radius = zero.** The live `/config/universal_room_automation/tou_rates.json` is
**identical** to the built-in `PEC_TOU_RATES` fallback — every rate, hour range, month mapping and
fixed charge. A rejection today would serve the same numbers now running.

### Acceptance criteria
- **Test:** a misspelled rate field is REJECTED, not loaded at 0.0 (the discriminating test).
- **Test:** overlapping hours / out-of-range hours / uncovered month / double-claimed month rejected.
- **Verify:** the operator's real file still loads — `file_status: ok`, summer peak `0.161843`.
- **Verify:** missing or unparseable file falls back exactly as before.

---

## D5 — TOU rate file: loud failure + kill switch

Validation without visibility would mean a future edit silently demoting the file to built-in
rates. So:

- **Loud:** a present-but-rejected file raises an operator-visible alert naming the specific
  errors, via the existing shared `fire_stuck_signal` NM path (per-day latched, fail-open) — an
  established mechanism, not a new one.
- **Visible:** `tou_file_status` on `sensor.ura_tou_period` reads `ok` / `rejected` / `absent` /
  `disabled`, alongside the already-computed `rate_source` provenance.
- **Kill switch:** `CONF_ENERGY_TOU_RATE_FILE_ENABLED`, **default TRUE** so behaviour is
  byte-identical until flipped. False skips all filesystem access and uses built-in rates.

Both TOU settings render adjacent in the **Energy** options step (they had landed 253 lines apart
on separate branches; paired during integration).

### Acceptance criteria
- **Test:** rejected → alert fires, status `rejected`, rates still built-in.
- **Test:** absent → status `absent`, no alert (absence is normal).
- **Test:** toggle False with a valid file → built-in rates, status `disabled`, no alert.
- **Live:** `sensor.ura_tou_period` exposes `tou_file_status` = `ok`.

---

## Verification performed pre-deploy

| Check | Result |
|---|---|
| Conflict markers | none |
| `compileall` | rc=0 |
| perimeter + linker + optimizer (default env) | **241 passed**, 1 pre-existing failure |
| energy/TOU + arrester + recorder + evse + cflow (`.venv-ha`) | **167 passed**, 0 failed |
| Live `tou_rates.json` under the new validator | **loads clean**, `file_status: ok`, peak `0.161843` |
| Live `exterior_seams.json` through the validator | 21 edges, 0 errors, 0 warnings |
| Seam invariants mutation | re-adding a fenced seam → RED; restored, residue 0 |
| Seam validator mutations (×2) | fenced-check and egress-exclusion each → RED; restored |
| TOU validation mutation | neutering `_validate_parsed_data` → **9 tests RED**; restored |
| Merge-conflict resolution mutation (×1 run) | dropping the path resolver → RED; restored |

**Pre-existing failure, unchanged:** `test_exterior_cycle2.py::test_snapshot_resolver_strips_underscore_2_before_person_suffix`
— confirmed failing on clean `develop` before any of this work. Not caused by this release.

**Integration note:** three TOU branches independently edited the same engine-construction site.
The conflict was resolved keeping **both** changes (path resolver *and* enabled toggle) — each
would otherwise have silently un-wired the other's card — and the resolution was mutation-verified.

---

## Known limitations carried into this release

- The wire-in anchor for D3 is **source-level, not behavioural**: it parses the call site's
  argument list. The resolver's six tests are behavioural. A future edit could wire a *different*
  wrong resolver and both stay green. Do not cite it as proof the runtime receives the path.
- Full-suite baseline diff could not be captured — `pytest quality/tests/` exceeds the 2-minute
  tool timeout (tracked: TEST-STRATEGY-REARCH-1). "No regressions" is scoped to the affected files.
- `madroneptultra` has a ring position but is **not yet in `perimeter_cameras`**, so URA receives
  no events from it and that ring edge is inert. Operator config action, tracked by
  CAMERA-PTULTRA-NOT-IN-PERIMETER-1.

---

## Live Validation — to be completed post-restart

Per CLAUDE.md this README is not done until observed results are written back here as a
`Validated <date>` table with concrete evidence.

- [ ] D1 — perimeter alerting still fires; no linker ERRORs; graph loads with 13 nodes
- [ ] D2 — in-suite only (the file is not consumed at runtime this release)
- [ ] D3 — TOU path resolves; unset key behaves as before
- [ ] D4 — `tou_rates.json` accepted; rates unchanged from pre-deploy
- [ ] D5 — `sensor.ura_tou_period` exposes `tou_file_status: ok`
