"""GUEST-COUNT-DEDUP-MIGRATE-1 — D1/D2/D3 tests.

Migrates two naive ``max(0, camera_total - ble_total)`` guest-count
derivations onto the DEDUPED ``census.last_result.house.unidentified_count``:

- D1: ``ZoneGuestCountSensor._get_guest_count`` in ``aggregation.py``
- D2: ``URAUnexpectedPersonSensor.extra_state_attributes["guest_count"]``
  in ``binary_sensor.py``  (``is_on`` INTENTIONALLY UNCHANGED)

Test authority (Tier 2-DB Review C, per plan D3): the census fixture is
built by driving the REAL ``PersonCensus._apply_enhanced_house_census``
writer (mirroring ``quality/tests/test_guest_census_correctness.py`` shape),
not a hand-built ``CensusZoneResult`` literal. A hand-built literal proves
the reader consumes the field; the real-writer fixture proves the reader
consumes the SAME shape the writer produces.

Discriminating scenario (plan D1/D2): construct a census with
``house.total_persons=6, identified_count=6, unidentified_count=0`` while
``person_coordinator.data`` shows 2 BLE-active. Under the OLD naive
subtraction both sites return ``max(0, 6-2) = 4``; under the migrated
readers both return ``0``. Assertion of ``== 0`` therefore FAILS on the
pre-migration code and PASSES on the migrated code — a genuine
discriminator.

Mutation-anchor tests use a source substring assertion to catch a future
refactor that re-introduces the subtractive form on either site.
"""

from __future__ import annotations

import os
import pathlib
import re
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

# aggregation.py + binary_sensor.py import surfaces not covered by
# _provenance_harness. Install lightweight stubs before importing them.
import sys as _sys
import types as _types
if "homeassistant.helpers.restore_state" not in _sys.modules:
    _rs = _types.ModuleType("homeassistant.helpers.restore_state")
    class _RestoreEntity:  # noqa: D401
        """Stub RestoreEntity."""
    _rs.RestoreEntity = _RestoreEntity
    _sys.modules["homeassistant.helpers.restore_state"] = _rs

# Ensure CoordinatorEntity + DataUpdateCoordinator are on update_coordinator
# (harness installs a bare module but entity.py needs both symbols).
import homeassistant.helpers.update_coordinator as _uc  # type: ignore
if not hasattr(_uc, "CoordinatorEntity"):
    class _CoordinatorEntityMeta(type):
        def __getitem__(cls, item):
            return cls

    class _CoordinatorEntity(metaclass=_CoordinatorEntityMeta):  # noqa: D401
        """Stub CoordinatorEntity (subscriptable-generic-friendly)."""
        def __init__(self, *a, **kw):
            pass
    _uc.CoordinatorEntity = _CoordinatorEntity
if not hasattr(_uc, "DataUpdateCoordinator"):
    _uc.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
if not hasattr(_uc, "UpdateFailed"):
    _uc.UpdateFailed = Exception

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import camera_census as _cc_mod
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    CensusZoneResult,
    PersonCensus,
)
from custom_components.universal_room_automation.aggregation import (
    ZoneGuestCountSensor,
)
from custom_components.universal_room_automation.binary_sensor import (
    URAUnexpectedPersonSensor,
)


DOMAIN = ura_const.DOMAIN


# ---------------------------------------------------------------------------
# tz-aware dt_util (mirrors test_guest_census_correctness.py hygiene).
# ---------------------------------------------------------------------------
class _TzUtil:
    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def as_local(dt: datetime) -> datetime:
        return dt

    UTC = timezone.utc


@pytest.fixture(autouse=True)
def _scoped_dt_util(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_cc_mod, "dt_util", _TzUtil(), raising=True)
    yield


# ---------------------------------------------------------------------------
# Real-writer census fixture (per plan D3 — no hand-built CensusZoneResult).
# ---------------------------------------------------------------------------
class _StubCameraManager:
    def get_cameras_for_entities(self, camera_entity_ids: list[str]) -> list[CameraInfo]:
        return []

    def get_all_frigate_cameras(self) -> list[CameraInfo]:
        return []


def _make_bare_census() -> PersonCensus:
    hass = make_hass()
    hass.states.get = lambda entity_id: None
    integration_entry = MagicMock()
    integration_entry.data = {
        ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION,
    }
    integration_entry.options = {
        ura_const.CONF_CAMERA_PERSON_ENTITIES: [],
        ura_const.CONF_ENHANCED_CENSUS: True,
    }
    hass.config_entries.async_entries.return_value = [integration_entry]
    try:
        hass.data[ura_const.DOMAIN] = {}
    except Exception:  # pragma: no cover
        hass.data = {ura_const.DOMAIN: {}}
    return PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]


def _minimal_raw_result(unid: int = 0) -> CensusZoneResult:
    return CensusZoneResult(
        zone="house",
        identified_count=0,
        identified_persons=[],
        unidentified_count=unid,
        total_persons=unid,
        confidence=ura_const.CENSUS_CONFIDENCE_MEDIUM,
        source_agreement=ura_const.CENSUS_AGREEMENT_SINGLE,
        frigate_count=unid,
        unifi_count=0,
    )


def _stub_camera_producer(census: PersonCensus, *, camera_unrecognized_return: int, pre_cancel: int) -> None:
    def _stub() -> int:
        census._last_camera_total_pre_cancel = pre_cancel
        return camera_unrecognized_return

    census._get_unrecognized_camera_count = _stub  # type: ignore[assignment]


def _stub_hold_decay(census: PersonCensus, held: int) -> None:
    def _stub(raw: int, zone: str, now: datetime):
        return held, False, 0

    census._apply_hold_decay = _stub  # type: ignore[assignment]


def _build_house_result(*, identified: int, held: int, pre_cancel: int, camera_unrecognized: int):
    """Drive the REAL _apply_enhanced_house_census writer (per plan D3)."""
    census = _make_bare_census()
    _stub_camera_producer(census, camera_unrecognized_return=camera_unrecognized, pre_cancel=pre_cancel)
    _stub_hold_decay(census, held=held)
    ble_persons = [f"p{i}" for i in range(identified)]
    return census._apply_enhanced_house_census(
        _minimal_raw_result(unid=held),
        ble_persons=ble_persons,
        now=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Helpers to build a "census wrapper" that mimics PersonCensus.last_result
# ---------------------------------------------------------------------------
class _LastResult:
    def __init__(self, house: CensusZoneResult) -> None:
        self.house = house


class _CensusStub:
    def __init__(self, house: CensusZoneResult) -> None:
        self.last_result = _LastResult(house)


def _make_hass_with(house: CensusZoneResult | None, ble_active: int) -> MagicMock:
    hass = make_hass()
    person_coordinator = MagicMock()
    person_coordinator.data = {
        f"ble{i}": {"tracking_status": "active"} for i in range(ble_active)
    }
    domain_data: dict[str, Any] = {"person_coordinator": person_coordinator}
    if house is not None:
        domain_data["census"] = _CensusStub(house)
    hass.data = {DOMAIN: domain_data}
    return hass


def _make_zone_sensor(hass: MagicMock) -> ZoneGuestCountSensor:
    """Build a ZoneGuestCountSensor without invoking heavy base __init__."""
    sensor = ZoneGuestCountSensor.__new__(ZoneGuestCountSensor)
    sensor.hass = hass
    sensor.zone = "house"
    sensor._guest_count = 0
    return sensor


def _make_unexpected_sensor(hass: MagicMock) -> URAUnexpectedPersonSensor:
    sensor = URAUnexpectedPersonSensor.__new__(URAUnexpectedPersonSensor)
    sensor.hass = hass
    sensor.entry = MagicMock()
    sensor._camera_total = 0
    sensor._ble_total = 0
    return sensor


# ===========================================================================
# D1 — ZoneGuestCountSensor migration
# ===========================================================================


def test_zone_guest_count_reads_deduped_unidentified() -> None:
    """Discriminating scenario: house.total_persons=6, identified=6,
    unidentified=0; BLE active=2. OLD naive returns 4, migrated returns 0."""
    house = _build_house_result(identified=6, held=0, pre_cancel=6, camera_unrecognized=0)
    assert house.total_persons == 6 and house.identified_count == 6 and house.unidentified_count == 0

    hass = _make_hass_with(house, ble_active=2)
    sensor = _make_zone_sensor(hass)

    # DISCRIMINATOR: naive `max(0, 6-2)` = 4; deduped `unidentified_count` = 0.
    assert sensor.native_value == 0
    assert sensor._get_guest_count() == 0


def test_zone_guest_count_none_census_returns_zero() -> None:
    """Graceful-degradation: census absent → 0."""
    hass = _make_hass_with(house=None, ble_active=0)
    sensor = _make_zone_sensor(hass)
    assert sensor.native_value == 0


def test_zone_guest_count_last_result_none_returns_zero() -> None:
    """Graceful-degradation: census present but last_result is None → 0."""
    hass = make_hass()
    census = MagicMock()
    census.last_result = None
    hass.data = {DOMAIN: {"census": census}}
    sensor = _make_zone_sensor(hass)
    assert sensor.native_value == 0


def test_zone_guest_count_attrs_share_house_snapshot() -> None:
    """State-vs-attribute discriminating: attrs surface identified_count +
    unidentified_count from the same house record as native_value."""
    house = _build_house_result(identified=6, held=0, pre_cancel=6, camera_unrecognized=0)
    hass = _make_hass_with(house, ble_active=2)
    sensor = _make_zone_sensor(hass)

    attrs = sensor.extra_state_attributes
    assert attrs["camera_total"] == house.total_persons
    assert attrs["identified_count"] == house.identified_count
    assert attrs["unidentified_count"] == house.unidentified_count
    assert attrs["zone"] == "house"
    # unidentified_count in attrs matches native_value (no divergence)
    assert attrs["unidentified_count"] == sensor.native_value


# ===========================================================================
# D2 — URAUnexpectedPersonSensor.extra_state_attributes["guest_count"] migration
# ===========================================================================


def test_unexpected_person_attr_guest_count_reads_dedup() -> None:
    """Same discriminating scenario: attrs['guest_count'] must be 0, not 4."""
    house = _build_house_result(identified=6, held=0, pre_cancel=6, camera_unrecognized=0)
    hass = _make_hass_with(house, ble_active=2)
    sensor = _make_unexpected_sensor(hass)

    attrs = sensor.extra_state_attributes
    assert attrs["guest_count"] == 0
    # ble_total diagnostic KEPT (scrape compat) — reflects the BLE-active count
    assert attrs["ble_total"] == 2
    assert attrs["camera_total"] == 6


def test_unexpected_person_attr_keys_unchanged() -> None:
    """Scrape-shape contract: attribute key-set is exactly the three keys."""
    house = _build_house_result(identified=6, held=0, pre_cancel=6, camera_unrecognized=0)
    hass = _make_hass_with(house, ble_active=2)
    sensor = _make_unexpected_sensor(hass)
    assert set(sensor.extra_state_attributes.keys()) == {
        "camera_total",
        "ble_total",
        "guest_count",
    }


def test_unexpected_person_attr_none_census_returns_zeros() -> None:
    """Graceful-degradation: census absent → all zeros, keys preserved."""
    hass = _make_hass_with(house=None, ble_active=0)
    sensor = _make_unexpected_sensor(hass)
    attrs = sensor.extra_state_attributes
    assert attrs == {"camera_total": 0, "ble_total": 0, "guest_count": 0}


# ===========================================================================
# is_on UNCHANGED — sibling comparison behavior preserved (plan §5, §9)
# ===========================================================================


def test_unexpected_person_is_on_still_uses_camera_gt_ble() -> None:
    """`is_on` is INTENTIONALLY untouched by this cycle: fires when
    camera_total > ble_active (independent of the deduped attribute).
    This ensures the D2 attribute swap did not leak into is_on semantics.
    """
    # camera_total=6, identified=6 (unidentified=0), BLE active=2 → is_on True
    # because 6 > 2 despite deduped guest_count == 0.
    house = _build_house_result(identified=6, held=0, pre_cancel=6, camera_unrecognized=0)
    hass = _make_hass_with(house, ble_active=2)
    sensor = _make_unexpected_sensor(hass)
    assert sensor.is_on is True
    # attrs disagree with is_on on the deduped view — pre-existing signal
    # separation, documented in plan §9.
    assert sensor.extra_state_attributes["guest_count"] == 0


def test_unexpected_person_is_on_false_when_equal() -> None:
    """is_on comparison is strict `>` (unchanged)."""
    house = _build_house_result(identified=2, held=0, pre_cancel=2, camera_unrecognized=0)
    hass = _make_hass_with(house, ble_active=2)
    sensor = _make_unexpected_sensor(hass)
    assert sensor.is_on is False


def test_unexpected_person_is_on_missing_data_returns_false() -> None:
    """is_on graceful-degrade unchanged: no census or coordinator → False."""
    hass = make_hass()
    hass.data = {DOMAIN: {}}
    sensor = _make_unexpected_sensor(hass)
    assert sensor.is_on is False


# ===========================================================================
# Mutation / grep anchors — I-GC invariant across the two migrated sites
# ===========================================================================

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_AGG_PATH = _REPO_ROOT / "custom_components/universal_room_automation/aggregation.py"
_BIN_PATH = _REPO_ROOT / "custom_components/universal_room_automation/binary_sensor.py"


def _extract_method_source(path: pathlib.Path, method_name: str) -> str:
    src = path.read_text()
    m = re.search(
        rf"    def {re.escape(method_name)}\(self.*?(?=\n    def |\nclass )",
        src,
        re.DOTALL,
    )
    assert m, f"could not locate method {method_name} in {path}"
    return m.group(0)


def test_migrated_body_calls_house_unidentified_count_aggregation() -> None:
    """Mutation anchor D1: _get_guest_count must read house.unidentified_count
    and MUST NOT compute `camera_total - ble_total` (the naive form)."""
    body = _extract_method_source(_AGG_PATH, "_get_guest_count")
    assert "house.unidentified_count" in body, (
        "regression: ZoneGuestCountSensor._get_guest_count no longer reads "
        "the deduped house.unidentified_count field"
    )
    assert "camera_total - ble_total" not in body
    assert "max(0, camera_total" not in body


def test_migrated_attr_reads_house_unidentified_count_binary_sensor() -> None:
    """Mutation anchor D2: URAUnexpectedPersonSensor.extra_state_attributes
    must emit guest_count from house.unidentified_count."""
    body = _extract_method_source(_BIN_PATH, "extra_state_attributes")
    # There are multiple extra_state_attributes in binary_sensor.py; narrow to
    # the URAUnexpectedPersonSensor class by string search.
    src = _BIN_PATH.read_text()
    cls_idx = src.index("class URAUnexpectedPersonSensor(")
    next_cls = src.index("\nclass ", cls_idx + 1)
    cls_body = src[cls_idx:next_cls]
    assert "house.unidentified_count" in cls_body, (
        "regression: URAUnexpectedPersonSensor no longer reads "
        "house.unidentified_count for the guest_count attribute"
    )
    # Ensure the naive expression is gone from THIS class's body.
    assert "max(0, camera_total - ble_total)" not in cls_body
    assert "camera_total - ble_total" not in cls_body


def test_grep_anchor_no_naive_subtraction_on_guest_count_paths() -> None:
    """Repo-wide (targeted): the forbidden expression must not appear as a
    live producer of a guest_count value in either target file."""
    for path in (_AGG_PATH, _BIN_PATH):
        src = path.read_text()
        # Allow the expression only inside comments / docstrings — but the
        # simplest robust check is: any occurrence outside a comment line.
        for lineno, line in enumerate(src.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            # doc-string mentions are acceptable — filter tokens embedded in
            # narrative prose by requiring a bare-expression context (a `(`
            # or `=` on the same line).
            if "camera_total - ble_total" in line and (
                "=" in line or "return" in stripped or "(" in line and ")" in line
                and not (line.count('"') >= 2 or line.count("'") >= 2)
            ):
                # Distinguish narrative text in docstrings by checking whether
                # the line is inside triple-quoted context — best-effort: any
                # line containing `"""` is definitely doc.
                if '"""' in line:
                    continue
                pytest.fail(
                    f"naive subtractive guest-count expression found in "
                    f"{path.name}:{lineno}: {line.strip()}"
                )
