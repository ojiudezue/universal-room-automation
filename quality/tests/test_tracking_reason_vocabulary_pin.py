"""PATH-ALPHA rev-3.5.1 D2d — vocabulary pin for `tracking_reason`.

Pins the canonical `TRACKING_REASON_VALUES` frozenset shape and, critically,
asserts that the two retired values (`bermuda_degraded`, `home_gps_only`)
are NOT reachable — they are folded into `home_ble_silent` per rev-3.5.1
semantic unification. Also asserts these retired values do NOT appear as
string literals anywhere in the production classifier or writer surfaces
(grep-asserted at test collection time so vocabulary drift is caught
before it can be emitted at runtime).

Load-bearing invariants:
  I1: `TRACKING_REASON_VALUES` is a frozenset of the exact 15 canonical
      values listed in AUDIT §"Institutional context verified".
  I2: retired values (`bermuda_degraded`, `home_gps_only`) are NEITHER
      members of the frozenset NOR reachable as string literals in
      person_coordinator.py / aggregation.py / presence.py / sensor.py.
  I3: `BLE_SILENT_ONLY_AWAY_CONFIDENCE` is strictly below the operative
      path-α confidence threshold (0.9 per AUDIT §6). Default 0.82.
  I4: `ATTR_TRACKING_REASON` and `ATTR_TRACKER_SOURCES` are exported as
      the canonical attribute names.

Drill-friendliness:
  - Removing any canonical value from the frozenset reddens
    `test_frozenset_membership_pinned`.
  - Re-introducing a retired value string in any production surface reddens
    `test_retired_values_not_reachable_as_literals`.
  - Setting the knob to ≥ 0.9 reddens `test_row14_knob_below_path_alpha`.
"""

from __future__ import annotations

import re
from pathlib import Path

import importlib.util
import sys
import types


def _load_const() -> types.ModuleType:
    """Load const.py directly by file path, bypassing package __init__.

    The universal_room_automation package __init__.py imports homeassistant,
    which the test environment does not provide unless a sibling bootstrap
    has run first. const.py itself only imports {datetime.timedelta,
    typing.Final}, so a file-path spec load is sufficient AND avoids
    coupling this pin test to any sibling's stub graph.
    """
    cached = sys.modules.get("_ura_const_for_vocab_pin")
    if cached is not None:
        return cached
    src = _REPO_ROOT / "custom_components" / "universal_room_automation" / "const.py"
    spec = importlib.util.spec_from_file_location(
        "_ura_const_for_vocab_pin", str(src)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ura_const_for_vocab_pin"] = mod
    spec.loader.exec_module(mod)
    return mod

# rev-3.5.1 canonical vocabulary (AUDIT §"Institutional context verified")
_CANONICAL_VALUES = frozenset({
    "bermuda",
    "home_ble_silent",
    "away_all_agree",
    "away_wifi_silent_local",
    "away_wifi_only",
    "away_gps_only",
    "away_ble_silent_only",
    "anomalous_gps_stale_local_gone",
    "anomalous_gps_lag_arrival",
    # `anomalous_wifi_gone_local_home` removed per C-HIGH-2 adjudication —
    # row 5 collapses into row 1's Bermuda-authoritative interception
    # (same outcome, no separate emission site). See const.py comment.
    "phone_left_behind_confirmed",
    "phone_left_behind_suspected",
    "no_signal",
    "no_trackers_configured",
    "entity_missing",
})

# Retired per rev-3.5.1: folded into `home_ble_silent`.
# Retired per C-HIGH-2 (2026-08-16): `anomalous_wifi_gone_local_home`
# — row 5 collapses into row 1's Bermuda-authoritative interception;
# no emission site ever existed. Removed from TRACKING_REASON_VALUES.
_RETIRED_VALUES = (
    "bermuda_degraded",
    "home_gps_only",
    "anomalous_wifi_gone_local_home",
)

# Path-α operative threshold (verify at build-review time per AUDIT §6).
_PATH_ALPHA_THRESHOLD = 0.9

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CC = _REPO_ROOT / "custom_components" / "universal_room_automation"
# C-HIGH-1 fix (2026-08-16): person_coordinator.py and aggregation.py
# live at the PACKAGE root, NOT under domain_coordinators/. The prior
# paths silently no-op'd (the loop guard at line ~140 skipped missing
# targets), leaving the classifier surface (where D2a introduced the
# reason vocabulary) uncovered — a hollow-anchor variant 6 defect.
_SCAN_TARGETS = [
    _CC / "person_coordinator.py",
    _CC / "aggregation.py",
    _CC / "domain_coordinators" / "presence.py",
    _CC / "sensor.py",
    _CC / "binary_sensor.py",
]


def test_scan_targets_exist() -> None:
    """C-HIGH-1 self-alarm: every _SCAN_TARGETS entry MUST exist.

    A missing path is a test failure, not a silent skip. Prevents the
    exact drift class that produced the C-HIGH-1 defect: two paths
    pointed at `domain_coordinators/person_coordinator.py` and
    `domain_coordinators/aggregation.py`, neither of which exists —
    so the retired-literal scan silently skipped the classifier
    surface and the aggregation surface entirely.
    """
    missing = [str(p) for p in _SCAN_TARGETS if not p.exists()]
    assert not missing, (
        "test_tracking_reason_vocabulary_pin._SCAN_TARGETS references "
        f"paths that do not exist: {missing}. Rename detected — update "
        "the constant, do NOT rely on the silent-skip guard."
    )


def test_frozenset_membership_pinned() -> None:
    """I1: TRACKING_REASON_VALUES must be exactly the 15 canonical values."""
    const = _load_const()
    TRACKING_REASON_VALUES = const.TRACKING_REASON_VALUES
    assert isinstance(TRACKING_REASON_VALUES, frozenset), (
        "TRACKING_REASON_VALUES must be a frozenset (immutable vocabulary)"
    )
    assert TRACKING_REASON_VALUES == _CANONICAL_VALUES, (
        "Vocabulary drift: "
        f"missing={_CANONICAL_VALUES - TRACKING_REASON_VALUES}, "
        f"extra={TRACKING_REASON_VALUES - _CANONICAL_VALUES}"
    )


def test_retired_values_not_in_frozenset() -> None:
    """I2 (half): retired rev-3.5 values are not frozenset members."""
    const = _load_const()
    TRACKING_REASON_VALUES = const.TRACKING_REASON_VALUES
    for retired in _RETIRED_VALUES:
        assert retired not in TRACKING_REASON_VALUES, (
            f"rev-3.5.1 retired `{retired}` reappeared in TRACKING_REASON_VALUES; "
            "folded into `home_ble_silent`"
        )


def test_retired_values_not_reachable_as_literals() -> None:
    """I2 (grep half): retired values must not appear in production surfaces.

    Emitting a retired value would silently escape the frozenset gate at
    stamp sites that use string literals rather than the constant. Repo
    grep prevents this class of drift.
    """
    offenders: list[str] = []
    for retired in _RETIRED_VALUES:
        needle = re.compile(rf'["\']{re.escape(retired)}["\']')
        for target in _SCAN_TARGETS:
            if not target.exists():
                continue
            text = target.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if needle.search(line):
                    offenders.append(f"{target.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Retired tracking_reason string literal(s) found in production surface(s); "
        "fold into `home_ble_silent` per rev-3.5.1:\n  " + "\n  ".join(offenders)
    )


def test_row14_knob_below_path_alpha() -> None:
    """I3: row-14 BLE-only away knob must be strictly below path-α threshold.

    Load-bearing safety: a solo BLE-only person (Ziri) must NOT be able to
    flip the house to away without corroboration. If the knob ever ≥ the
    path-α threshold, this invariant collapses.
    """
    BLE_SILENT_ONLY_AWAY_CONFIDENCE = _load_const().BLE_SILENT_ONLY_AWAY_CONFIDENCE
    assert 0.0 <= BLE_SILENT_ONLY_AWAY_CONFIDENCE < _PATH_ALPHA_THRESHOLD, (
        f"BLE_SILENT_ONLY_AWAY_CONFIDENCE={BLE_SILENT_ONLY_AWAY_CONFIDENCE} "
        f"must be in [0.0, {_PATH_ALPHA_THRESHOLD}); >= threshold lets a "
        "solo BLE-only person flip the house away — Ziri worked-example "
        "AUDIT §6 forbids this."
    )


def test_row5_collapses_into_bermuda_authoritative() -> None:
    """C-HIGH-2 pin: row 5 (`GPS=home, WiFi=not_home, BLE=visible@home_room`)
    has NO dedicated emission site in `_classify_matrix_row`. It is
    intercepted UPSTREAM by the Bermuda-authoritative branch which
    stamps `tracking_reason="bermuda"` + `TRACKING_STATUS_ACTIVE` +
    location=<resolved_room> — the same "blocks away, home-affirmed"
    outcome row 5 specified. Adjudicated 2026-08-16 as case (a):
    documentation artifact, not a real gap.

    This test pins that adjudication three ways:
      1. `anomalous_wifi_gone_local_home` is NOT in TRACKING_REASON_VALUES
         (already covered by test_retired_values_not_in_frozenset).
      2. The classifier `_classify_matrix_row` has NO branch producing
         that reason (grep-asserted below).
      3. The Bermuda-authoritative branch at person_coordinator.py exists
         and stamps `"bermuda"` as tracking_reason (source anchor).

    Removing the interception (or re-introducing the dead vocabulary)
    reddens a distinctly-named assertion.
    """
    pc = _CC / "person_coordinator.py"
    assert pc.exists(), pc
    src = pc.read_text(encoding="utf-8")

    # (2) No branch emits the retired reason. Grep for a QUOTED
    # literal only — code comments referencing the retired name (for
    # documentation) are fine and expected.
    quoted = re.compile(r'["\']anomalous_wifi_gone_local_home["\']')
    hits = [
        f"{lineno}: {line.strip()}"
        for lineno, line in enumerate(src.splitlines(), 1)
        if quoted.search(line)
    ]
    assert not hits, (
        "person_coordinator.py contains a quoted literal reference to "
        "the retired reason `anomalous_wifi_gone_local_home` — row 5 "
        "was adjudicated as collapsed into the Bermuda-authoritative "
        "interception; the reason must not resurface as an emit or "
        f"whitelist value.\n  " + "\n  ".join(hits)
    )

    # (3) Bermuda-authoritative stamp exists and uses reason="bermuda".
    # The stamp site sets ATTR_TRACKING_REASON: "bermuda" inline; if
    # that literal disappears the interception is broken.
    assert 'ATTR_TRACKING_REASON: "bermuda"' in src, (
        "person_coordinator.py: Bermuda-authoritative interception no "
        "longer stamps tracking_reason=`bermuda`. If this branch is "
        "removed row 5's outcome (blocks away, home-affirmed) is lost — "
        "either restore the stamp or add a dedicated row-5 emission "
        "site and re-introduce the vocabulary value."
    )


def test_attr_names_exported() -> None:
    """I4: canonical attribute names exported from const.py."""
    const = _load_const()
    assert const.ATTR_TRACKING_REASON == "tracking_reason"
    assert const.ATTR_TRACKER_SOURCES == "tracker_sources"
