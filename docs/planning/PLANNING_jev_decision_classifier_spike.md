# PLANNING — Jev-class decision-classifier: measure-first spike

**Type:** read-only measure-first spike (no URA behavior change). **Card:** `JEV-DECISION-CLASSIFIER-SPIKE-1`.
**Operator goals:** (a) **correctness** — a decision layer "almost as reliable as code" on cases code already handles; (b) **adaptiveness** — makes a sensible *calibrated* call where hand-authored code fails / has no rule. Decision under test chosen by operator: **occupancy-trust**. Candidate approach chosen: **bake-off 2–3 open Jev reproductions + an official-Jev control + the code baseline.**

## The decision under test
**Occupancy-trust:** given room R's sensor states + provenance + memory/baseline context at time T → a typed decision `{occupied: bool}` **+ a calibrated confidence**. This is the decision that cost a full plan→build→3-review→mutation-verify cycle this session (freshness gate / stuck-sensor / Jaya fan-phantom) and whose hand-tuned corroboration is brittle + non-stationary — the ideal adaptiveness test.

## Three arms (identical inputs, identical labels, identical splits)
1. **CODE** — URA's current fusion + corroboration heuristic (`coordinator._fusion_filter_active` / the corroboration gates). The baseline being defended.
2. **OPEN bake-off (local):** `poorjev` (zero-shot-NLI, offline, MIT, reports ECE 0.170→0.071), `jev48` (2B weights reproduction), `Luce`/`OpenJev` (open recipe reporting accuracy+ECE vs Jev). Run **behind `jev-local`'s Jev-compatible `POST /v1/systemone` endpoint** so the harness is endpoint-agnostic.
3. **OFFICIAL JEV (cloud control)** — same request shape via the swap of one endpoint/key. **Needs operator signup + API key** (only blocker for this arm).

## Eval set + the load-bearing split
Assemble a labeled set of (features @ T → ground-truth occupied/empty), each tagged to a split:
- **code-works split** — unambiguous cases (multi-sensor corroborated presence; long clearly-empty stretches). Ground truth is easy. **Correctness bar:** the classifier must ~match code here (don't regress the easy stuff).
- **code-fails split** — the hard cases where the heuristic mis-fired or is known-fragile: **Jaya fan-still phantom (empty room held occupied), single-sensor frozen-on, mmWave still-body sleeper, lone-corroborator, camera-motion-not-occupancy, freshness gaps.** Ground truth from **operator confirmations** (e.g. Jaya was empty 2026-09-18 17:44–19:26) + recorder + physical reasoning. **Adaptiveness bar:** classifier beats code here AND its confidence correctly drops where genuinely ambiguous.

**Feature vector per case** ("program state in"): the room's motion/mmwave/occupancy/camera/BLE states + `source_type`/provenance + `regime_detector`/`memory_baseline` stats (on-ratio, deviation) + memory context (recent occupancy pattern). Reuse existing extractors; do NOT hand-craft new ones.

**Label schema:** `{ts, room, features{…}, label: occupied|empty, split: works|fails, label_provenance}` → committed as the acceptance fixture (hand-built first, per measure-before-build).

## Metrics (per arm, per split)
- **Correctness:** accuracy vs label + **ECE** (calibration) on the code-works split.
- **Adaptiveness:** accuracy + **calibrated-abstention quality** on the code-fails split (does confidence drop where it should?).
- **Cost / latency / dependency:** $/call + ms + local-vs-cloud (URA hot-path constraint).

## Go / no-go
An arm earns a build only if it **matches CODE on code-works AND beats CODE on code-fails**, at acceptable latency/cost/dependency. Open-local arm preferred over cloud on ties (no hot-path cloud dependency). If no arm beats code on adaptiveness → we keep code and have *proven* it, for ~a spike's cost.

## Assets that de-risk this (already in URA)
- **`anomaly_log`** (~28k rows) = a label source for the *sibling* anomaly decision (spike #2 later); for occupancy it's operator-confirmed + recorder ground truth.
- **`regime_detector` / `memory_baseline`** = half the feature extraction already computed.
- **room/house memory (`memory_facade`)** = the feature store (context in) + a future outcome ledger for self-calibration + per-room personalization.

## Work split
- **Needs operator:** official-Jev signup + API key (unlocks arm 3).
- **Needs env setup:** clone/run poorjev + jev48 + Luce behind jev-local (model downloads ~a few hundred MB each) — on the Mac-mini sidecar, not HAOS.
- **Do-now (read-only, no key):** assemble the labeled occupancy-trust eval set (both splits) from the recorder + this session's operator-confirmed episodes; build the endpoint-agnostic harness + the CODE arm; wire the scoring/ECE report. The moment the key + candidate envs land, the bake-off is one command.

## Non-goals
- No URA behavior change (pure measurement). No deploy. If a build is later justified, it goes through the reusable-`decide()`-primitive design (advisory, kill-switched, code-owns-threshold, deterministic fallback) — a separate cycle.
