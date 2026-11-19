# Plan review: step 7 egress arrival identity rev 3.2 (completeness/build-prediction + G)

Plan: `docs/planning/PLANNING_egress_direction_aware_identity.md` @ 335bf1284. Manual §5.5 read in full (lines 1024-1076).

**Verdict: PLAN-FIX-REQUIRED** (small; fix in plan, no redesign).

## Verified holds
- One notify site: `_arrival_departure_notify` `transit_validator.py:2956`, sole call `:2559`; manual §5.5 says "the ONE arrival/departure notification site". Lock-regime "after X arrived" texts (`security_lock_regime.py:1615,1643`) are a separate class, not moved.
- Record built at `:2526` before notify `:2559`; `get_person_edges_since` `presence.py:6135` (`edge_ts >= t`, never raises, `()` on error).
- 0.75 bar read from `CONSUMER_CLASS_MIN_CONFIDENCE` at `:2979`; anchor 0.75 < security 0.9; consistent with §5.5(b). No security/access reader changed (§5.5(a) holds).
- "Alert now": synchronous read at resolution, no added delay. AWAY inputs untouched.

## Findings
1. **MEDIUM, upper bound.** `get_person_edges_since` has no upper bound; `_resolve_direction` can run later than t_E+45. Plan must say: filter `edge_ts <= t_E + EGRESS_ENTRY_WINDOW_SECONDS`, convert `egress_timestamp` (datetime) to epoch; add test edge at t_E+46 → no anchor.
2. **MEDIUM, eligibility ambiguity.** INV (i) "FACE leg" vs "attached_ble* never anchor" leaves `IDENTITY_PROVENANCE_BLE_FACE` (`:2180`) undecided. List the eligible provenance values explicitly. Also §4 says provenance `face+residency` on the record; D2 says record keeps resolver provenance. Pick one (D2 is right).
3. **LOW.** `person_edges_truncated_since` (`presence.py:6149`) unused; truncation yields no anchor (safe). State it.
4. **LOW.** G-WRONG on graded set has few anchors to grade; say the expected count.

## G (goal fidelity)
- **Tradeoff for the operator:** "It should do both" was about naming people NOT home at the crossing. S1 does not do that; it is parked (P-1, Q2) on D0 (d). Stated honestly, but it is the literal ask.
- Departure naming is not improved (true exits still need 0.75) and is absent from §11. Add a parked row or say "no change by design".
- Operator rule 2026-11-17: the D1 move relocates hardened code for contract hygiene, not user value. A kwarg on the existing function delivers S1 with less risk. Ask the operator, or justify the move beyond "contract says so".
