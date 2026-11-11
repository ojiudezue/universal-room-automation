"""NM-BUTTON-READY-PATTERN-1: NM-backed buttons refresh on SIGNAL_NM_READY.

Buttons are never polled. The NM mute-person button and the test perimeter
alert button read ``hass.data[DOMAIN]["notification_manager"]`` in
``available``; NM is registered after the button platform adds them, so
without a SIGNAL_NM_READY subscription they stay unavailable after boot
(same defect as GuestLeftButton, fixed v5.108.2).
"""
from __future__ import annotations

import importlib

import pytest

import guest_split_harness as H


def _build(cls_name):
    BT = importlib.import_module(f"{H._PKG}.button")
    hass = H.MagicMock()
    hass.data = {H.DOMAIN: {}}
    cls = getattr(BT, cls_name)
    if cls_name == "NMMutePersonChannelPrimaryButton":
        b = cls(hass, H.MagicMock(), "person.oji", "imessage")
    else:
        b = cls(hass, H.MagicMock())
    return hass, b


@pytest.mark.parametrize("cls_name", [
    "NMMutePersonChannelPrimaryButton",
    "SendTestPerimeterAlertButton",
])
def test_button_refreshes_when_nm_becomes_ready(monkeypatch, cls_name):
    from homeassistant.helpers import dispatcher
    SIG = importlib.import_module(
        f"{H._PKG}.domain_coordinators.signals").SIGNAL_NM_READY
    assert SIG == "ura_notification_manager_ready"
    connected = {}
    unsub = object()

    def _connect(hass, sig, fn):
        connected[sig] = fn
        return unsub

    monkeypatch.setattr(dispatcher, "async_dispatcher_connect", _connect)
    hass, b = _build(cls_name)
    removers = []
    b.async_on_remove = removers.append
    writes = []
    b.async_write_ha_state = lambda: writes.append(b.available)

    H.run(b.async_added_to_hass())
    assert b.available is False
    assert list(connected) == [SIG]
    assert removers == [unsub]
    assert writes == []

    hass.data[H.DOMAIN]["notification_manager"] = object()
    connected[SIG]()
    assert writes == [True]


def test_entity_ids_unchanged():
    _, mute = _build("NMMutePersonChannelPrimaryButton")
    _, perim = _build("SendTestPerimeterAlertButton")
    assert mute.unique_id == "universal_room_automation_nm_mute_person_oji_imessage"
    assert perim.unique_id == "universal_room_automation_send_test_perimeter_alert"
