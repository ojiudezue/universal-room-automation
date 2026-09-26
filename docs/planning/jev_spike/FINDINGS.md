# Jev-class spike — findings (occupancy-trust, code + open bake-off)

## Result table (58-case eval, leave-one-out)
| Arm | works acc | fails acc | overall | ECE |
|---|---|---|---|---|
| CODE (fused room_occupied) | 100% (49/49) | **0% (0/9)** | 84.5% | 0.155 |
| logistic (all features incl. census) | 100% | 100% | 100% | 0.015 |
| logistic (sensors-only, no census) | 100% | 88.9% (8/9) | 98.3% | 0.026 |

## Verdict: INCONCLUSIVE on go/no-go — the classifier wins are LABEL LEAKAGE, not adaptiveness.
The eval labels were **proxy-derived from the same signals the classifier consumes**: the label rules
define occupied⇔persons_in_house≥1 and the split by sensors_on count (0=empty, 1=fails-empty, ≥2=occupied).
Feeding the classifier persons_in_house and sensors_on ⇒ it recovers the rule (100% / 88.9%), which proves
nothing about the real regime a Jev-class is meant to win — ambiguous cases where hand-rules are brittle.
Only ONE case is independently labeled (operator-confirmed Jaya 2026-09-18 empty phantom).

## What IS real and useful
1. CODE is **structurally blind to the phantom** (0% on fails) and **badly calibrated** (ECE 0.155, always
   100%-confident) — genuine, and the phantom signature (all-away + single uncorroborated sensor) is real
   (Jaya-confirmed).
2. On these cases the phantom is separable by SIMPLE signals code already has (census count, sensor count) but
   does not use in fusion → the near-term fix may be a **rule/wire-in** ("distrust a lone sensor when census=0"),
   NOT necessarily a classifier. A classifier earns its place only where signals are genuinely ambiguous.

## The binding prerequisite (the spike's real output)
A valid verdict needs **independent ground-truth labels** — operator-confirmed or from a source disjoint from
the arms' inputs (e.g. door-count, a manual presence log, camera-person ground truth) — for ~20-40 cases,
especially AMBIGUOUS ones (single-sensor, still-body, sibling-disagree). Until then:
- The heavy open candidates (poorjev / jev48 / Luce) are MOOT to install — they'd hit the same leakage; the
  bottleneck is labels, not the model.
- Do NOT read the 100%/88.9% as evidence for a build.

## Recommendation
Park the build. Next step = assemble independent labels (cheapest: operator spot-confirms a batch of
single-sensor/all-away episodes as empty-or-not; or a disjoint truth source), then re-run the SAME harness
(code arm + logistic floor first, heavy candidates only if the floor is beaten on independently-labeled
ambiguous cases). Harness + scorer + eval-builder are committed and one-command-ready.
