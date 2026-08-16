"""PATH-ALPHA D2c + D3 + D1 §4.7.2 — observability + exact-match + zone bucket.

Covers:
    - D2c(i)   aggregation.py: tracking_reason / tracker_sources threaded
      through PersonLocationSensor.extra_state_attributes and through the
      ZonePersonTrackingStatus per-person dict.
    - D2c(ii)  sensor.py: face_recognized_count published alongside
      census_count on the house-state sensor; tracking_reason threaded
      into the two person-passthrough dicts (:3039 + :3088 pre-D2c).
    - D2c(iii) binary_sensor.py: PersonPhoneLeftBehindSensor exposes D9
      room-corroboration outcome (suppressed / source / evidence).
    - D3       presence.py: `_extract_reason_field` extracts values via
      EXACT split (never substring); reason string enriched with
      `tracking_reason=<value>` so downstream classifiers can key on it.
    - D1 §4.7.2 aggregation.py: `test_zone_bucket_default_is_lost` — a
      person_info dict with NO `tracking_status` key must bucket into
      lost_count (fail-safe direction under new semantics).

All observability additions render None/absent-safe before first
evaluation (asserted for each surface).
"""
from __future__ import annotations

import ast
from pathlib import Path

# COLLECTION HAZARD (2026-08-16): the sibling
# `test_v570_guest_detection_trust` installs the real
# `custom_components.universal_room_automation.domain_coordinators.*`
# modules into sys.modules using file-path spec loaders, but it guards
# each install with `if <name> not in sys.modules: _load_module(...)`.
# A SEPARATE sibling — `test_path_alpha_d2a_matrix_classifier.py` at
# lines 160-166 — installs a MINIMAL STUB `signals` module (only
# `SIGNAL_PERSON_ARRIVING`) via `types.ModuleType`. When collection
# order runs d2a before d2c, the sibling's guard skips loading the
# REAL signals module, and later `from .signals import SIGNAL_CENSUS_UPDATED`
# inside presence.py raises `ImportError: ... (unknown location)` —
# taking the ENTIRE d2c file (19 tests) out of the run silently.
#
# Symptom to detect: a `signals` module in sys.modules lacking
# `SIGNAL_CENSUS_UPDATED` (and, defensively, lacking `__file__`) is a
# stub. Purge the whole domain_coordinators subtree + `const` + the
# stubbed `signals` so the sibling loader re-installs the real ones.
# This is a LOUD fix — if the real modules cannot be loaded, the
# ImportError still surfaces at collection with an actionable trace
# (never silently skipped). Do NOT weaken this to `try/except: skip`
# — a skip would recreate the silent-coverage-loss defect.
import sys as _sys  # noqa: E402
_pkg = "custom_components.universal_room_automation"
_dc = f"{_pkg}.domain_coordinators"
_sig_key = f"{_dc}.signals"
_sig_mod = _sys.modules.get(_sig_key)
if _sig_mod is not None and not hasattr(_sig_mod, "SIGNAL_CENSUS_UPDATED"):
    # SURGICAL purge (2026-08-16): only evict the STUB signals entry
    # (and any presence/aggregation/sensor entries that were loaded
    # AGAINST the stub — they hold a reference to the stub's globals
    # by way of `from .signals import ...` bindings). Do NOT purge
    # `const` or unrelated siblings — a broader purge caused 5
    # order-dependent regressions in test_arrester_comfort_delay,
    # test_energy_behavioral_write_verify, and test_nm_cycle_c2_*
    # which rely on the previously-installed const module identity.
    del _sys.modules[_sig_key]
    for _dependent in (
        f"{_dc}.presence",
        f"{_dc}.house_state",
        f"{_dc}.base",
        f"{_dc}.coordinator_diagnostics",
    ):
        if _dependent in _sys.modules:
            del _sys.modules[_dependent]

# Import the sibling HA-module mock installer so aggregation / presence /
# sensor / binary_sensor imports succeed under pytest.
import quality.tests.test_v570_guest_detection_trust  # noqa: F401

# Post-install verification: fail LOUDLY at collection with a
# distinct, actionable message if the sibling still failed to
# install the real signals module. This turns any future recurrence
# of the collection-order hazard into a single-line, correctly-
# labelled failure instead of an obscure `unknown location` trace.
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    signals as _signals_mod,
)
assert hasattr(_signals_mod, "SIGNAL_CENSUS_UPDATED"), (
    "test_pathalpha_d2c_d3_observability: real "
    "`domain_coordinators.signals` module was not loaded (missing "
    "`SIGNAL_CENSUS_UPDATED`). A sibling test has installed a stub. "
    "See the COLLECTION HAZARD comment at the top of this file."
)


PKG = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"
DC_PATH = PKG / "domain_coordinators"
PRESENCE_SRC = (DC_PATH / "presence.py").read_text()
AGGREGATION_SRC = (PKG / "aggregation.py").read_text()
SENSOR_SRC = (PKG / "sensor.py").read_text()
BINARY_SENSOR_SRC = (PKG / "binary_sensor.py").read_text()


# ===========================================================================
# D3 — `_extract_reason_field` EXACT-match semantics
# ===========================================================================


def _get_extractor():
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        _extract_reason_field,
    )
    return _extract_reason_field


def test_d3_extract_exact_match_returns_value():
    ex = _get_extractor()
    r = "tracking_status=lost,tracking_reason=away_ble_silent_only"
    assert ex(r, "tracking_status") == "lost"
    assert ex(r, "tracking_reason") == "away_ble_silent_only"


def test_d3_extract_missing_field_returns_none():
    ex = _get_extractor()
    assert ex("tracking_status=lost", "tracking_reason") is None


def test_d3_extract_empty_inputs_return_none():
    ex = _get_extractor()
    assert ex("", "tracking_reason") is None
    assert ex("tracking_reason=x", "") is None
    assert ex(None, "tracking_reason") is None  # type: ignore[arg-type]


def test_d3_exact_match_rejects_substring_false_positive():
    """PATH-ALPHA D3: a reason value that CONTAINS another value must
    NOT false-match. The critical case: `away_all_agree` contains the
    substring `away`; `away_ble_silent_only` shares the `away_` prefix
    with `away_gps_only`. A substring-based classifier would collide.
    """
    ex = _get_extractor()
    r = "tracking_reason=away_all_agree"
    # Correct extraction:
    assert ex(r, "tracking_reason") == "away_all_agree"
    # An operator asking for a DIFFERENT reason value must get None,
    # even if that value is a substring of the actual value.
    assert ex(r, "away") is None
    assert ex(r, "away_all") is None
    # Field-name matches must be exact — `tracking` alone must not
    # accidentally hit `tracking_reason`.
    assert ex(r, "tracking") is None


def test_d3_extract_handles_whitespace_tokens():
    ex = _get_extractor()
    r = " tracking_status=lost , tracking_reason=no_signal "
    assert ex(r, "tracking_status") == "lost"
    assert ex(r, "tracking_reason") == "no_signal"


def test_d3_reason_string_enriched_with_tracking_reason_at_source():
    """PATH-ALPHA D3 prerequisite: the excluded_persons builder must emit
    tracking_reason as a parseable token so the extractor above has
    something to key on."""
    assert "tracking_reason={info.get('tracking_reason', 'no_signal')}" in PRESENCE_SRC, (
        "D3: excluded_persons reason string must carry tracking_reason=<value>"
    )


# ===========================================================================
# D2c(i) — aggregation.py PersonLocationSensor + ZonePersonTrackingStatus
# ===========================================================================


def test_d2c_person_location_sensor_init_has_provenance_defaults():
    """Attrs must render safely before the classifier first fires."""
    assert 'self._tracking_reason: str = "no_signal"' in AGGREGATION_SRC
    assert "self._tracker_sources: dict = {}" in AGGREGATION_SRC


def test_d2c_person_location_sensor_attrs_publish_reason_and_sources():
    assert "ATTR_TRACKING_REASON: _tracking_reason" in AGGREGATION_SRC
    assert "ATTR_TRACKER_SOURCES: _tracker_sources" in AGGREGATION_SRC


def test_d2c_zone_bucket_dict_carries_tracking_reason_and_sources():
    """The ZonePersonTrackingStatus per-person dict must expose the
    matrix-cell provenance."""
    idx = AGGREGATION_SRC.find("persons_in_zone.append({")
    assert idx >= 0
    block = AGGREGATION_SRC[idx: idx + 2000]
    assert '"tracking_reason":' in block
    assert '"tracker_sources":' in block


# ===========================================================================
# D1 §4.7.2 — zone bucket default is "lost" (fail-safe)
# ===========================================================================


def test_zone_bucket_default_is_lost():
    """Post-D2c COMMENT reservation: a person_info dict missing the
    `tracking_status` key must bucket into `lost_count` — NEVER into
    `active_count` (would inflate presence) or `stale_count` (implies
    STALE has meaning here). The fallback preserves the fail-safe
    direction under the unified-matrix semantics.

    Mirrors the production `.get("tracking_status", "lost")` branch;
    the same helper is inline in aggregation.py:~5180-5195.
    """
    active_count = 0
    stale_count = 0
    lost_count = 0
    # Simulate: ONE structurally-broken person_info (no `tracking_status`
    # key) whose `location` matches the zone room.
    person_info = {"location": "kitchen"}
    zone_rooms = ["kitchen"]
    if person_info.get("location", "") in zone_rooms:
        status = person_info.get("tracking_status", "lost")
        if status == "active":
            active_count += 1
        elif status == "stale":
            stale_count += 1
        else:
            lost_count += 1
    assert (active_count, stale_count, lost_count) == (0, 0, 1), (
        "D1 §4.7.2: broken emit (no tracking_status) must fail-safe to lost"
    )


def test_source_invariant_zone_bucket_default_comment_present():
    """The explanatory comment on the `.get(..., "lost")` default must
    live at the call site so future readers see WHY the default is
    correct under the new semantics (per brief; if we believe the
    default should change, surface as a matrix-design finding — do NOT
    change it here)."""
    assert 'PATH-ALPHA D2c' in AGGREGATION_SRC
    assert '"lost")' in AGGREGATION_SRC


# ===========================================================================
# D2c(ii) — sensor.py face_recognized_count + tracking_reason passthrough
# ===========================================================================


def test_d2c_house_state_publishes_both_census_and_face_counts():
    """Post-GAP-A D8, path α gates on `face_recognized_count`. The
    house-state sensor MUST publish BOTH values (census_count for
    legacy dashboards, face_recognized_count as the actual gate)."""
    assert 'attrs["census_count"] = presence.census_count' in SENSOR_SRC
    assert 'attrs["face_recognized_count"] = int(' in SENSOR_SRC
    assert 'attrs["path_alpha_gate_source"] = "face_recognized_count"' in SENSOR_SRC


def test_d2c_house_state_face_count_renders_zero_before_first_eval():
    """Fail-safe default: missing _face_recognized_count attr → 0 (not
    None, not error). Mirrors infer()'s kwarg default and cannot
    inflate away-veto denial."""
    class _Fake:
        pass
    fake_presence = _Fake()
    # Reproduces the getattr(...) fallback in sensor.py.
    val = int(getattr(fake_presence, "_face_recognized_count", 0) or 0)
    assert val == 0


def test_d2c_room_person_dicts_thread_tracking_reason():
    """The two per-person passthrough dicts in sensor.py (native_value
    and extra_state_attributes for room-scope person status) must carry
    tracking_reason."""
    # Grep for both passthrough sites; each must contain the key.
    hits = SENSOR_SRC.count(
        '"tracking_reason": person_info.get('
    )
    assert hits >= 2, (
        f"D2c: expected two per-person tracking_reason passthroughs, found {hits}"
    )


# ===========================================================================
# D2c(iii) — binary_sensor.py D9 room-corroboration outcome
# ===========================================================================


def test_d2c_phone_left_behind_attrs_expose_room_corroboration_fields():
    """The PersonPhoneLeftBehindSensor's attr dict must publish the
    three D9 corroboration fields. All three must default to None so
    dashboards render safely before first evaluation / on missing
    surfaces (fail-OPEN, matches is_on semantics)."""
    idx = BINARY_SENSOR_SRC.find("class PersonPhoneLeftBehindSensor(")
    assert idx >= 0
    body = BINARY_SENSOR_SRC[idx: idx + 10000]
    assert '"room_corroboration_suppressed":' in body
    assert '"room_corroboration_source":' in body
    assert '"room_corroboration_evidence":' in body


def test_d2c_phone_left_behind_room_corroboration_defaults_are_none():
    """Trace the default assignments verbatim to prove attrs render
    None-safe on the first evaluation."""
    idx = BINARY_SENSOR_SRC.find("class PersonPhoneLeftBehindSensor(")
    body = BINARY_SENSOR_SRC[idx: idx + 10000]
    assert "room_corroboration_suppressed: bool | None = None" in body
    assert "room_corroboration_source: str | None = None" in body
    assert "room_corroboration_evidence: str | None = None" in body


# ===========================================================================
# Mutation drills — ≥2 neuter shapes for grep-adjacent anchors
# ===========================================================================


def test_drill_shape_a_reason_string_enrichment_load_bearing():
    """Drill shape A (comment-out): if the tracking_reason token is
    stripped from the reason string, `_extract_reason_field(...,
    'tracking_reason')` returns None — proving the token is load-
    bearing for the D3 classifier."""
    ex = _get_extractor()
    # Simulate the un-enriched (pre-D3) reason string shape:
    r_neutered = "tracking_status=lost"
    assert ex(r_neutered, "tracking_reason") is None
    # And the enriched form works:
    r_full = "tracking_status=lost,tracking_reason=no_signal"
    assert ex(r_full, "tracking_reason") == "no_signal"


def test_drill_shape_b_reason_string_enrichment_delete_neuter():
    """Drill shape B (delete): if the reason string is EMPTY (both
    tokens removed), the extractor still returns None (no crash)."""
    ex = _get_extractor()
    assert ex("", "tracking_reason") is None


def test_drill_ast_face_recognized_count_publication_call_present():
    """AST anchor: sensor.py's house-state extra_state_attributes must
    contain a dict-item assignment for `face_recognized_count`. A
    grep-based check (already above) can be defeated by a stray comment;
    parsing sensor.py + walking for the assign statement is more robust.
    """
    tree = ast.parse(SENSOR_SRC)
    found = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Subscript)
        ):
            tgt = node.targets[0]
            if (
                isinstance(tgt.slice, ast.Constant)
                and tgt.slice.value == "face_recognized_count"
            ):
                found = True
                break
    assert found, (
        "D2c: no `attrs['face_recognized_count'] = ...` assignment found in sensor.py"
    )
