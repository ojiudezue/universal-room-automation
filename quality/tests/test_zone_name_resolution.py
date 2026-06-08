"""Regression guard for HVAC-zone name resolution (Bug Class #53).

`ZoneManager.zones` is keyed by `zone_id` ("zone_1", …), but zone aggregators
address zones by NAME (`self.zone`). The v4.7.13/v4.7.15 motionless-occupant
fallback did `zones.get(self.zone)` — a name lookup against an id-keyed dict —
so it silently never matched a real HVAC zone (and warned "zone not registered"
on every boot). `_resolve_hvac_zone` resolves by zone_id, exact zone_name, and
merged-name membership ("Entertainment + Master Suite").

The real `_resolve_hvac_zone` is exec-extracted from aggregation.py source so the
test drives production code (Bug Class #44 fixture authority). Fixture mirrors the
LIVE shape confirmed on the instance: 3 HVAC zones keyed zone_1/2/3, zone_1 a
merged Entertainment+Master Suite, plus an aggregator zone ("Outside") with no
thermostat → no HVAC zone.
"""

from __future__ import annotations

import os
import types
import logging

import pytest

_AGG_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "aggregation.py",
)


def _extract_resolver():
    with open(_AGG_PY, "r") as fh:
        src = fh.read()
    start = src.index("def _resolve_hvac_zone(")
    end = src.index("\n\nclass ZoneSensorBase", start)
    g: dict = {"_LOGGER": logging.getLogger("test.zoneresolve")}
    exec(compile(src[start:end], "<_resolve_hvac_zone>", "exec"), g)
    return g["_resolve_hvac_zone"]


_RESOLVE = _extract_resolver()


class _ZS:
    def __init__(self, zone_name):
        self.zone_name = zone_name


class _ZM:
    """Mirrors ZoneManager: .zones keyed by zone_id, values carry zone_name."""
    def __init__(self):
        self.zones = {
            "zone_1": _ZS("Entertainment + Master Suite"),
            "zone_2": _ZS("Upstairs"),
            "zone_3": _ZS("Back Hallway"),
        }


@pytest.fixture
def zm():
    return _ZM()


class TestResolveHvacZone:
    def test_merged_member_first(self, zm):
        assert _RESOLVE(zm, "Entertainment") is zm.zones["zone_1"]

    def test_merged_member_second(self, zm):
        assert _RESOLVE(zm, "Master Suite") is zm.zones["zone_1"]

    def test_exact_merged_name(self, zm):
        assert _RESOLVE(zm, "Entertainment + Master Suite") is zm.zones["zone_1"]

    def test_single_name_upstairs(self, zm):
        assert _RESOLVE(zm, "Upstairs") is zm.zones["zone_2"]

    def test_single_name_back_hallway(self, zm):
        assert _RESOLVE(zm, "Back Hallway") is zm.zones["zone_3"]

    def test_direct_zone_id(self, zm):
        assert _RESOLVE(zm, "zone_1") is zm.zones["zone_1"]

    def test_no_hvac_zone_returns_none(self, zm):
        # Aggregator zone with no thermostat (e.g. "Outside") → None, not a crash.
        assert _RESOLVE(zm, "Outside") is None

    def test_proves_old_lookup_was_broken(self, zm):
        # The pre-fix code did zones.get(name); this would miss every real zone.
        assert zm.zones.get("Entertainment") is None
        assert _RESOLVE(zm, "Entertainment") is not None

    def test_partial_substring_does_not_falsematch(self, zm):
        # "Master" alone must NOT match "Master Suite" (membership is exact part).
        assert _RESOLVE(zm, "Master") is None
        # Substring of a single name must not match either.
        assert _RESOLVE(zm, "Hallway") is None
