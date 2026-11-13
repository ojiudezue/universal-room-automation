"""FACE-ARRIVAL-REBUILD-1 (plan rev 11 §1.2a): the provenance vocabulary
constants keep the literal values the census and transit validator used."""

from __future__ import annotations

from custom_components.universal_room_automation import const as ura_const


def test_values_unchanged():
    """The provenance constants name the literals the census and the transit
    validator used before the rename (hand-written oracle)."""
    assert ura_const.IDENTITY_PROVENANCE_FACE == "face"
    assert ura_const.IDENTITY_PROVENANCE_BLE == "ble"
    assert ura_const.IDENTITY_PROVENANCE_BLE_FACE == "ble+face"
    assert ura_const.IDENTITY_PROVENANCE_VISION == "vision"
    assert ura_const.IDENTITY_PROVENANCE_VALUES == frozenset(
        {"face", "ble", "ble+face", "vision"},
    )
