# Review D (re-fix) — Egress-Face Identity D1

**Reviewer:** Adversarial completeness pass (Tier 2-DB 4th framing)
**Branch:** `feature/egress-face-identity-d1` @ `2eedd6096`
**Base:** `develop`
**Scope:** verify Review A/B/C fix-ups are complete and the fix-up
introduced no new defect; probe the kill-switch, namespace canonicalizer,
and test authority adversarially.

**Verdict:** **SHIP-WITH-FIX** — two MEDIUM findings that must be
resolved before deploy. No CRITICAL/HIGH. The B-CRIT-1 relocation fix
IS complete (single gated caller, symmetric evict). The kill switch is
functionally inert on the *egress-face contribution* path, but the
"byte-identical" invariant the plan/const.py claims is **falsified** by
the always-on name normalization at the fuse sites. Also a silent
first-token collision in the canonicalizer.

---

## Findings

### D-MED-1 — Kill switch is NOT byte-identical to pre-cycle behaviour
**Files:** `custom_components/universal_room_automation/const.py:2170-2172`,
`camera_census.py:1869-1880` (raw fuse) and `:3603-3617` (enhanced
recompute), `sensor.py` docstring, tests
`test_kill_switch_disabled_house_fuse_byte_identical` at
`quality/tests/test_egress_face_identity_d1.py:668-679`.

The const.py docstring for `CONF_EGRESS_IDENTITY_ENABLED` explicitly
promises: *"both fuse sites are byte-identical to pre-cycle behaviour"*
when False. The config_flow help text repeats the claim. This is
**false** in general.

Pre-cycle fuse (`:1855` before this branch): `known_persons = face_ids | ble_ids`
— raw string union.
Post-cycle with kill-switch OFF:
```python
known_persons = (self._normalize_name_set(face_ids)
                 | self._normalize_name_set(ble_ids)
                 | egress_face_ids)   # empty when disabled
```
`_normalize_name_set` unconditionally canonicalizes every name to the
URA person-slug namespace regardless of the kill switch. Same in the
enhanced-house recompute at `:3612-3616`.

**Reachable repro (legal config, no cycle involvement):**
- `tracked_persons=["person.oji_udezue"]`
- `face_ids={"Oji"}` (Frigate first-name)
- `ble_ids={"oji_udezue"}` (URA slug)
- Pre-cycle: `len(face_ids | ble_ids) == 2`, `identified_count == 2`.
- Post-cycle, kill-switch OFF: `_normalize_name_set({"Oji"})={"oji_udezue"}`,
  `_normalize_name_set({"oji_udezue"})={"oji_udezue"}`, union size 1,
  `identified_count == 1`. `unidentified_count` and every downstream
  guest-math consumer therefore shift by +1.

This may in fact be a defensible *improvement* (deduping the same
identity across sensor sources), but shipping it behind a switch that
advertises byte-identity means the operator cannot actually revert to
pre-cycle behaviour by flipping the switch. The kill switch buys back
only the `_egress_face_ids` contribution, not the normalization
side-effect.

**Test authority (hollow-oracle, Bug Class #62):**
`test_kill_switch_disabled_house_fuse_byte_identical` asserts only
`census._get_egress_face_ids_fresh(now) == set()`. It does NOT drive
the actual fuse and compare its output against the raw-union oracle.
The test's name promises what the test does not measure. A test that
mutates the production union expression (e.g. removes the
`_normalize_name_set` calls) would still pass, so the "byte-identical"
invariant is unanchored.

**Fix — pick one, before deploy:**
1. **(preferred)** Gate the normalization on the switch:
   ```python
   if self._is_egress_identity_enabled():
       known_persons = (self._normalize_name_set(face_ids)
                        | self._normalize_name_set(ble_ids)
                        | egress_face_ids)
   else:
       known_persons = face_ids | ble_ids
   ```
   at both fuse sites, and add a test that seeds `{"Oji"}, {"oji_udezue"}`
   under kill-switch OFF and asserts `identified_count == 2`.
2. Revise the const.py + config_flow help text to say *"no egress-face
   contribution to the census union"* and drop the "byte-identical"
   claim; add a note that name normalization is unconditional and IS a
   behaviour change from pre-cycle. Rename the test to
   `test_kill_switch_disabled_egress_contribution_is_empty` so its
   oracle matches its name.

Option 1 delivers the promised kill-switch semantics; option 2 admits
the reality of the change. Do not ship the current mismatch.

---

### D-MED-2 — First-token canonicalization silently merges two residents sharing a first name
**File:** `camera_census.py:2790-2802` (`_canonical_person_slug`).

```python
head = s.split("_", 1)[0]
for slug in tracked:
    if slug.split("_", 1)[0] == head:
        return slug
```

If `tracked_persons` contains two slugs with the same first token
(`oji_udezue`, `oji_smith`), a face sensor reporting `"Oji"` is
canonicalized to whichever slug appears first in the operator's
tracked_persons list — deterministic on list order, but **silent**.
The stamped `person_id` on the egress DB row and the census union
member both become the wrong resident. Neither the docstring nor the
config-flow field for `tracked_persons` documents a
"first-name uniqueness required" constraint.

**Reachable repro (legal config):**
- `tracked_persons=["person.oji_udezue", "person.oji_smith"]` (two
  residents whose Frigate face-library first names collide is a normal
  house scenario — spouses, siblings, roommates).
- Frigate publishes `"Oji"` for Oji Smith on the front-door egress
  camera.
- `_canonical_person_slug("Oji")` returns `"oji_udezue"` (first-list
  entry wins). Census `identified_persons` shows `oji_udezue` present;
  `person.oji_udezue.state` says `not_home` (correct — he's out); the
  in-resolver fail-open veto at `transit_validator.py:1150-1160` then
  drops the recognition — so the failure mode there is that Oji
  Smith's real recognition is *lost*, not misattributed. However on
  the CENSUS union path (`camera_census._get_face_recognized_person_names`
  and the enhanced recompute at `:3603`), that veto lives elsewhere,
  and the misattribution IS realized when Oji Udezue's tracker is
  `home` — Oji Smith's face flips through the union under Udezue's
  slug and `identified_count` still counts one, but the DB row for
  the egress event records the wrong person.

Today this house does not appear to have a first-name collision (only
one `oji_*`), so the finding is latent. But this is the census
identity namespace bridge — a class of house that CAN have collisions
must not silently mis-stamp.

**Fix — pick one:**
1. If exactly one first-token match is found, return it; if more than
   one match, log `_LOGGER.warning` once and return `""` (empty ⇒ no
   census register, no DB stamp — falls back to today's None). This is
   the fail-closed choice.
2. Document explicitly in the `tracked_persons` config-flow field help
   AND in `_canonical_person_slug`'s docstring: *"tracked_persons
   first-token uniqueness required; on collision, the first entry
   wins."* Add a startup check that warns on collision.

Option 1 is safer; the false-negative (no stamp) is recoverable — the
false-attribution (wrong person_id) is not.

---

## Non-findings (verified clean)

- **B-CRIT-1 fix completeness — CLEAN.** `register_egress_face` has
  exactly ONE production caller (`transit_validator.py:1257`), inside
  the `direction in ("entry", "exit")` gate, and the branch selects
  register vs evict. The DB-write gate (`direction != "ambiguous"`) is
  the same three-way gate, so bus event / DB row / census union all
  agree per crossing. Ambiguous crossings do not mutate census.
- **evict namespace parity — CLEAN.** `evict_egress_face` uses the
  identical `_canonical_person_slug` path as `register_egress_face`
  and is called with the same `person_id` string that was previously
  registered (both come from the same resolver call within
  `_resolve_direction`). No namespace mismatch — an entry followed by
  an exit within the TTL will evict the exact same key it registered.
- **Kill-switch — the *egress-face contribution* path IS inert.** With
  the switch False: resolver early-returns None ⇒ event `person_id`
  is None ⇒ `if person_id and direction in ...` never fires ⇒ dict
  never mutated ⇒ `_get_egress_face_ids_fresh` returns empty even if
  the dict were forced non-empty. Observability counter
  `_egress_identities_stamped` in `sensor.py:4204-4213` gates on
  `if person_id:`, so it stays 0 while disabled. (The normalization
  side-effect is a separate finding — D-MED-1.)
- **Options-flow scope — CLEAN.** `CONF_EGRESS_IDENTITY_ENABLED` is
  in `async_step_camera_census` inside `UniversalRoomAutomationOptionsFlow`
  alongside `CONF_ENHANCED_CENSUS` and `CONF_GUEST_VLAN_SSID`. Both
  the writer (options save) and the reader (`_is_egress_identity_enabled`
  filtering by `ENTRY_TYPE_INTEGRATION`) target the same integration-
  level entry. A saved True round-trips to the reader.
- **Sign symmetry — CLEAN.** Both the resolver
  (`transit_validator.py:1116-1121`) and `_get_egress_face_ids_fresh`
  (`camera_census.py:2911-2919`) drop `age < 0` (future-dated) entries
  as stale, per A-LOW-1 / C-LOW-3.
- **tz-naive coercion — CLEAN.** `register_egress_face` coerces naive
  `ts` to UTC before storing, so the later `(now - ts)` in the fresh-set
  reader cannot raise TypeError.
- **Test-suite hygiene** — the 15 D1 tests DRIVE production paths
  (call `_resolve_egress_face_identity`, `register_egress_face`,
  `_get_egress_face_ids_fresh`, and the fuse expressions via
  `_calculate_confidence_and_persons` style helpers). No wall-clock
  coupling — timestamps are injected. `test_resolver_vetoes_when_person_not_home_oracle_independent`
  and `test_resolver_returns_fresh_name_as_canonical_slug` have
  independent oracles. Note the hollow-oracle exception called out in
  D-MED-1.

---

## Recommendation

- Fix D-MED-1 (kill-switch normalization gate OR docstring reversal +
  test rename) — 1 file, ≤10 LOC, and one test.
- Fix D-MED-2 (fail-closed on canonicalizer ambiguity + warning) —
  ~8 LOC in `_canonical_person_slug` + one test.
- Re-run the D1 test file. No new review pass needed for these two
  contained fixes; they do not cross a new coordinator boundary.

Once both fixed: **SHIP**. Feature ships dormant per plan (kill switch
default False), so live risk is minimal even before the operator flips
it on.
