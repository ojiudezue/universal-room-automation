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
    "anomalous_wifi_gone_local_home",
    "phone_left_behind_confirmed",
    "phone_left_behind_suspected",
    "no_signal",
    "no_trackers_configured",
    "entity_missing",
})

# Retired per rev-3.5.1: folded into `home_ble_silent`.
_RETIRED_VALUES = ("bermuda_degraded", "home_gps_only")

# Path-α operative threshold (verify at build-review time per AUDIT §6).
_PATH_ALPHA_THRESHOLD = 0.9

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CC = _REPO_ROOT / "custom_components" / "universal_room_automation"
_SCAN_TARGETS = [
    _CC / "domain_coordinators" / "person_coordinator.py",
    _CC / "domain_coordinators" / "aggregation.py",
    _CC / "domain_coordinators" / "presence.py",
    _CC / "sensor.py",
    _CC / "binary_sensor.py",
]


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


def test_attr_names_exported() -> None:
    """I4: canonical attribute names exported from const.py."""
    const = _load_const()
    assert const.ATTR_TRACKING_REASON == "tracking_reason"
    assert const.ATTR_TRACKER_SOURCES == "tracker_sources"
