# Layer L4 (bf985dab1) - Review C (per-site source mutation)

Run set: l4 test + guard test + census_ble_over_face, egress_identity_producer_d2b, census_trust_golden, guest_census_correctness, egress_direction_aware (baseline 274 pass). 18 drills, each restored, tree clean.

| Site | Result | RED test |
|---|---|---|
| 5 veto call sites reverted (4 census, 1 transit) | RED x5 | l4 display_name / ambiguous [per-method] + guard allowlist |
| exact short-circuit | RED | exact_entity_byte_identical |
| friendly_name match | RED | display_name_person_not_fail_open |
| entity-id slug match | RED | matches_entity_id_slug |
| ambiguity (>1) | RED | ambiguous_keeps_fail_open |
| zero-match returns exact | RED | no_match_returns_exact |
| hit/miss counters (swap, drop) | RED | display_name tests |
| diagnostics counter surface | RED | layer_diagnostics_expose_fallback_counters |
| guard taint `_person_entity_for_slug` | RED | guard allowlist |
| guard taint bare `person_entity_for_slug` | GREEN | none |
| empty-target guard `if target:` | GREEN | none |
| `person.` prefix filter | GREEN | none (equivalent while async_all is domain-scoped) |
| `async_all("person")` domain arg | GREEN | none (fake ignores domain) |
| exact id built from slug_of(slug) | GREEN | none |

GREEN findings (all LOW): empty slug with nameless persons, domain-scope/prefix-filter, bare taint name (transit uses it), "slug used exactly as passed" claim are untested.

Verdict: SHIP (add the 5 LOW tests as follow-up).
