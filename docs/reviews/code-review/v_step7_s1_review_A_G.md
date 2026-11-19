# Step 7 S1 review, framings A + G (6b0401670, base ac36af1ba = merge-base, verified)

Verdict: **SHIP**, plus one LOW fix in the same cycle.
Tests: test_egress_edge_anchor.py + test_person_awareness_layer_guard.py, 189 passed.

## Findings
1. **LOW (fails open, docstring wrong). transit_validator.py `_parse_confusable_pairs` `_resolve`.** A name that is not tracked, or a first name that `canonical_person_slug` finds ambiguous (it returns ""), is kept as the typed slug. `tracked_person_entity_id` then gives `person.<typed>`, which has no residency edges, so the pair never blocks anything. The docstring says "fail closed: that person's edges still block", which is false. Fix: correct the docstring, or skip the pair and log it (it already logs once). Live pairs jaya / ezinne / oji resolve, so this is only latent.
2. **LOW (cleared, declared).** On an `exit` crossing the anchor sends "<name> arrived". The plan declares this at :46 ("went back to the car") and the operator approved Q3.
3. **Cleared, name mapping.** Typed names go through `slug_of`, then the existing face mapper `canonical_person_slug` (camera_census.py:4240), checked against `tracked_person_slugs()` from config. That is the established path for operator-typed text, not entity-id guessing.
4. **Cleared, anchor rule.** Matches the plan: face or ble+face provenance, live face legs, tier >= MEDIUM, own counted / non-stale / non-boot arrival edge in [t_E-300, t_E+45], truncation returns None, a partner edge blocks. The confidence is compared by name to `CONSUMER_CLASS_MIN_CONFIDENCE[NOTIFICATION]`. An import-time check keeps it below the security bar. `egress_timestamp.timestamp()` is tz-correct epoch, matching edge_ts epoch (presence.py:6136).
5. **Cleared, LEAD 0.** `_compute_edge_anchor` returns None first, so notify/record/D8a get the same values as before, with `edge_anchor: None` added to D8a.
6. **Layer guard +2 rows.** These are sanctioned reads through the public layer (the `CONSUMER_CLASS` constant and the DB delegate), not a leak. The plan text should record it.
7. **D2 trip-wire.** Rows come back `ORDER BY started_at ASC` (database.py:11102), so `outcomes[0]` is the oldest and the pre-S1 check works. It stays quiet for up to 7 days after deploy, then pages. It persists across restarts, so it satisfies the zero-fire rule.

## G (goal fidelity)
- Phone first, face second: met.
- 0.6 / 0.75: met.
- jaya|oji pair: met.
- Minimal change on the notify path: met. One branch is added ahead of the existing one, and bus, DB and census are untouched.
- No added latency: met. The anchor is synchronous, before notify.
