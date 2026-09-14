# PLANNING — Operator-injectable exterior camera seam file

**Status:** PLAN ONLY — build/no-build decision pending operator.
**Date:** 2026-09-13 · **Proposed tier:** 2 (new load path into a safety-adjacent primitive; no new coordinator, no DB)
**Cards:** CAMERA-SEAM-VALIDATION-1, CAMERA-SEAM-RING-CONTRADICTION-1, CAMERA-PTULTRA-NOT-IN-PERIMETER-1, EGRESS-CAMERA-LIST-STALE-5-NOT-3-1

**Operator direction (2026-09-13):**
1. "We need a place to ask the user to upload the file. I think SC config flow is the right spot."
2. "Find how we handle it for TOU file and then critique that and use it or improve it."
3. **"Drop runtime learning. Agree on cost/benefit."** → runtime adjacency learning is KILLED, see §6.

---

## 1. Institutional context verified

**Greps run + results:**

| Proposed piece | Verdict |
|---|---|
| File loader for a JSON config artifact | **REUSE the TOU pattern** — `TOURateEngine.async_from_json_file` (`energy_tou.py:72`) + `_read_json_file` (`:~55`) + `_from_parsed_data` (`:85`). Call site `__init__.py:3449-3453`. |
| Runtime setter to install the graph | **REUSE** `ExteriorTrackLinker.set_adjacency()` (`exterior_track_linker.py:383`) — exists, symmetrizes, currently has **zero production callers**. This plan gives it its first one. |
| Symmetrization | **REUSE** — `set_adjacency` and `__init__` (`:215-219`) already symmetrize; do NOT reimplement. |
| Graph validation | **REUSE** `quality/tests/perimeter/test_seam_graph_invariants.py` (shipped 2026-09-13) — the four invariants become the runtime validator's rules. |
| Config-flow step to host the field | **EXTEND** `async_step_perimeter_alerting` (`config_flow.py:3784`, menu-wired at `:3316`). Do NOT create a new step. |
| Path config key | **REUSE-AND-FIX** `CONF_ENERGY_TOU_RATE_FILE` (`energy_const.py:740`) is **declared and never read** — the TOU path is hardcoded. Our key must not repeat that (see §3 critique C3). |
| File-upload selector | **NEW** — `grep -rn "FileSelector\|upload" custom_components/` returns **nothing**. URA has never used HA's file-upload selector. This is the only genuinely new mechanism. |
| Adjacency learner | **NOT BUILT — killed by operator.** §6. |

**Code surveyed end-to-end:** `energy_tou.py`, `exterior_track_linker.py`, `const.py` (seam/egress block), `config_flow.py` (perimeter step), `__init__.py:3440-3470`.
**Docs read:** `AUDIT_exterior_camera_adjacency_probe.md`, `VALIDATE_exterior_camera_seams.md`.

---

## 2. How TOU does it today (the prior art, traced)

1. **No upload UI.** The operator drops `tou_rates.json` into `/config/universal_room_automation/` over Samba/SSH. Path is `DEFAULT_TOU_RATE_FILE` (`energy_const.py:266`), **hardcoded at the call site**.
2. **Loaded once, at integration setup**, via `hass.async_add_executor_job` — file I/O never touches the event loop.
3. **Parse + normalize:** period-name aliases (`on_peak`→`peak`, `off-peak`→`off_peak`, …); unknown periods logged and **skipped**.
4. **Required-field check:** a season missing `off_peak` → **entire file rejected**, built-in PEC defaults used.
5. **Fail-safe:** file missing / unparseable / OSError → `cls()` built-in defaults, WARNING logged. The system is never left without a rate table.
6. **Provenance surfaced:** `rate_source = "<filename> (<utility>, effective <date>)"`, exposed as a sensor attribute (`sensor.py:8624`).

## 3. Critique of the TOU pattern

**Keep (these are genuinely good and we should copy them):**
- **K1 — Fail-safe to a built-in default.** Never leaves the subsystem without data. Directly applicable: a bad seam file must fall back to `EXTERIOR_ADJACENCY_GRAPH`, never to an empty graph (an empty graph silently disables cross-camera linking).
- **K2 — Executor-job file I/O.** Non-negotiable; HA 2026.x enforces it.
- **K3 — Provenance string surfaced as an entity attribute.** The operator can see *which source won* without reading logs. Copy exactly.
- **K4 — Whole-file rejection on a missing required field**, rather than limping on with a half-applied config.

**Fix (do NOT copy these):**
- **C1 — No upload point.** Requires filesystem access. This is precisely the gap the operator wants closed.
- **C2 — Load-once at setup.** Editing the file needs a full restart; there is no reload service or button. For seams (which the operator will iterate on, as tonight proved) that is too slow a loop.
- **C3 — Dead config key.** `CONF_ENERGY_TOU_RATE_FILE` (`energy_const.py:740`) exists but is never read — a knob that looks configurable and isn't. Verified three ways: the constant name appears only at its definition; the string value `"energy_tou_rate_file"` appears only there too (so nothing reads it via a literal); and the key is absent from every live config entry. **Independently corroborated** — `AUDIT_excess_solar_and_evse_prior_art.md:249` recorded it as finding P16, "DORMANT — grep-verified zero consumers; setting it has no effect". It is an *unfinished wire*, not a bug: the read site exists at `__init__.py:3449-3453`, where the path is passed as the third argument to `async_from_json_file` — one line. Carded as TOU-RATE-FILE-KEY-UNWIRED-1. **Our key must be read at the call site or not exist.**
- **C4 — Inconsistent partial-failure semantics.** Unknown period → warn + skip (partial apply); missing `off_peak` → reject all. Two different philosophies in one loader. **Pick one: reject the whole file.** A partially-applied seam graph is exactly the "wrong-but-plausible seam" failure mode that merges two people into one track.
- **C5 — Errors only reach the log.** A malformed file is invisible in the UI. The operator finds out from a WARNING they may never read.
- **C6 — No schema version.** `utility`/`effective_date` are informational; nothing lets a future loader detect an old format.
- **C7 — No change record.** Nothing notes that the file differs from last boot.

---

## 4. Proposed design

### D1 — File format (`exterior_seams.json`)
Operator-authored, declarative, **ring-first** because that is how the operator actually thinks (proven tonight):

```json
{
  "schema_version": 1,
  "description": "Phalanx Madrone exterior camera seams",
  "ring": ["front_side_ptz", "madrone_g6_entry", "front_door_aerial", "..."],
  "skips": [["armcrest", "g5_bullet"], ["back_yard", "hot_tub"]],
  "fenced": [["pool_equipment", "rear_ptz"], ["back_yard", "front_side_ptz"]],
  "close_pairs": [["g5_bullet", "doorbell_lite"]],
  "egress_cameras": ["madrone_g6_entry", "doorbell_lite", "front_door_aerial",
                     "garage_a", "garage_b"]
}
```
- `ring` generates the 12 cycle edges; `skips` adds operator-validated shortcuts; `fenced` is an explicit deny-list checked *after* generation.
- `egress_cameras` **listed here so the derived egress-adjacent set can be computed rather than hand-maintained** — fixes EGRESS-CAMERA-LIST-STALE-5-NOT-3-1 structurally.
- `close_pairs` is **carried but not consumed** in v1 (parked; see CAMERA-SEAM-CLOSE-PAIR-SEMANTICS-1).

### D2 — Validator (reuses the shipped invariants)
Runs before anything is installed. **Any failure → reject the whole file, keep the const graph** (C4).
1. Every camera named is a known camera key (cross-check against configured `perimeter_cameras` + `egress_cameras`) — *this alone would have caught the `madroneptultra` mismatch.*
2. Ring is a single cycle covering every exterior camera; no duplicates.
3. No node with degree < 2 (no dead ends → can never reach the 3-camera circling threshold).
4. Graph is connected.
5. No `fenced` pair present in the generated edge set.
6. **Ring-vs-skips consistency**: warn when a declared `skip` joins cameras ≥4 ring positions apart (the physical-implausibility smell that tonight's re-read caught).

### D3 — Upload surface (config flow)
Extend **`async_step_perimeter_alerting`** (`config_flow.py:3784`) with an HA file-upload selector. On submit: write to `/config/universal_room_automation/exterior_seams.json`, run D2, and **surface validation errors inline in the form** (fixes C5) — the operator sees "camera `madroneptultra` is not in perimeter_cameras" in the dialog, not in a log.

*Open question for build time:* HA's `FileSelector` is used nowhere in URA (§1). If it proves awkward inside an options flow, the fallback is a **paste-JSON text field** (`TextSelector` multiline) — same validator, same storage, zero new mechanism. Decide by spiking the selector first; do not design around an unverified API (No-Fabrication).

### D4 — Live reload (fixes C2)
A **button entity** — `button.ura_reload_exterior_seams` — re-reads, re-validates, and calls `set_adjacency()`. No restart. Reuses the existing button platform; `set_adjacency` is already safe to call at runtime (it rebuilds `_adjacency` wholesale).

### D5 — Provenance + drift visibility (K3 + C6/C7)
Attributes on the existing perimeter diagnostic sensor: `seam_source` (`"exterior_seams.json (schema 1, 20 seams)"` or `"built-in const"`), `seam_count`, `seam_validation` (`ok` / the first error), `seam_file_sha256`.

### D6 — Const stays the fallback
`EXTERIOR_ADJACENCY_GRAPH` remains the shipped default and the fail-safe target (K1). The file **overrides**; it never merges.

---

## 5. Acceptance criteria

**D1/D2 (format + validator)**
- **Test:** valid file → 20 expected seams; ring-only file → 12; `skips` add exactly the named edges.
- **Test:** each of the 6 validator rules rejects a purpose-built bad file, and rejection leaves the const graph intact (assert the live graph equals the const graph after a failed load).
- **Test:** a file naming `madroneptultra` (not in `perimeter_cameras`) is REJECTED with that camera named in the error.
- **Test:** a file re-adding a `fenced` pair is REJECTED.
- **Mutation:** neutering the validator call in the load path must turn a specific test RED (wire-in anchor, not a helper-only test).

**D3 (upload)**
- **Verify:** submitting a malformed file shows the error in the config-flow form and does not write the file.
- **Live:** operator uploads the ratified seam file and the dialog confirms the seam count.

**D4 (reload)**
- **Verify:** pressing the button after editing the file changes `seam_count` without a restart.
- **Test:** a failed reload leaves the PREVIOUS good graph in place (never an empty graph).

**D5**
- **Live:** `seam_source` names the file when loaded and `"built-in const"` when absent.

---

## 6. Value / cost / risk — and what we are NOT building

**KILLED: runtime adjacency learning.** Operator agreed on cost/benefit. Recorded so it is not re-proposed:
- The 2026-08-06 probe derived seams from co-firing within 180 s. Of the 27 seams that reached `const.py`, the operator struck **10 (37%)** as physically impossible on 2026-09-13 — several with observed counts of 3-4 *after* the simultaneity filter. Co-firing measures **household movement patterns**, not **physical adjacency**, and with a 4-person household those diverge badly.
- The failure is **asymmetric**: a wrong seam merges two people into one track and **suppresses the second alert** (silent security failure); a missing seam only fragments (noisier, never silent). Learning biases toward *adding* edges — toward the silent-failure side.
- The graph is stable physical truth. It changes when a camera moves, not continuously. There is no learning problem here.
- **Retained instead:** the offline probe as a *suggestion report* an operator ratifies. That workflow just worked.

**Value of the file loader:** moderate, and mostly **portability + iteration speed**, not correctness. For this property the const is already ratified. The real wins: (a) the operator can iterate without a code change — tonight needed three corrections and each is currently a const edit + deploy; (b) another operator gets a declarative path; (c) **D2's camera-name validation would have caught the `madroneptultra` mismatch and the 5-vs-3 egress drift automatically.**

**Cost:** one new mechanism (file selector) — everything else is REUSE. Estimate ~1 cycle, Tier 2.

**Risk:** low-to-moderate, concentrated in **the load path, not the data**. A validator bug that admits a bad graph is the only way this loses alerts, which is why D2 rejects whole-file and D6 keeps the const as fallback. Mitigated by reusing the already-shipped, already-mutation-tested invariants.

**Honest recommendation:** the *format + validator* (D1/D2) carry nearly all the value — they are what would have caught tonight's three errors. **D3's upload UI is the expensive, least-certain part** (unproven API in this codebase) and captures the least marginal benefit, since the operator already has Samba access. If we build, consider **D1+D2+D4+D5 first with a drop-a-file path (exactly TOU's ergonomics, plus validation and reload), and treat D3 as a follow-on** — or use the paste-JSON fallback, which gets the "place to upload" the operator asked for at a fraction of the risk.

## 7. Non-goals
- No runtime learning (§6). No merging file+const. No per-room/interior adjacency. No change to `_classify` or circling thresholds (close-pair semantics stay parked). No DB persistence — the file is the record.
