"""v4.5.5 — person_coordinator self.data None-guard regression.

Pre-fix bug: `_calculate_confidence` at person_coordinator.py:865 had:
    if person_name in self.data and closest_area_distance is not None:
without the `if not self.data or` guard that every other access site
in the file uses (lines 937, 943, 949, 984, 1000, etc).

When `DataUpdateCoordinator.data` is `None` (state during first
refresh after startup), `person_name in None` raises:
    TypeError: argument of type 'NoneType' is not a container or iterable

Caught by the function's broad `except Exception`, logged as
"Error calculating confidence for X in Y: …" — single ERROR per
restart, returns 0.5 fallback so person tracking keeps working.

v4.5.5 fix is one line:
    if self.data and person_name in self.data and closest_area_distance is not None:

Mirror-style test asserts the guard pattern is present in source.
The full function isn't cleanly importable without HA core (same
reason as v4.5.3's mirror test for the EC switch factory).
"""


class TestSelfDataNoneGuard:
    """Source-grep contract: every `person_name in self.data` site must
    be preceded by a `not self.data` / `self.data and` guard. The bug
    was a single line missing this pattern."""

    def _source(self):
        with open("custom_components/universal_room_automation/person_coordinator.py") as f:
            return f.read()

    def test_calculate_confidence_guards_self_data(self):
        src = self._source()
        # Locate _calculate_confidence and slice out its body.
        idx = src.find("async def _calculate_confidence")
        assert idx > 0, "_calculate_confidence must exist"
        end = src.find("\n    async def ", idx + 1)
        if end == -1:
            end = src.find("\n    def ", idx + 1)
        body = src[idx:end] if end > 0 else src[idx:]

        # Every `person_name in self.data` reference inside this function
        # must be guarded with `self.data` truthiness check on the same line.
        offset = 0
        while True:
            pos = body.find("person_name in self.data", offset)
            if pos == -1:
                break
            line_start = body.rfind("\n", 0, pos) + 1
            line_end = body.find("\n", pos)
            line = body[line_start:line_end if line_end > 0 else len(body)]
            assert (
                "self.data and" in line
                or "not self.data" in line
            ), (
                f"`person_name in self.data` access in _calculate_confidence "
                f"is unguarded — DataUpdateCoordinator.data can be None "
                f"during first refresh, causing `argument of type 'NoneType' "
                f"is not a container or iterable`. Line:\n  {line.strip()}"
            )
            offset = pos + 1

    def test_other_access_sites_already_guarded(self):
        """Sanity: confirm the guard pattern URA uses elsewhere is
        still intact — the 6+ sites at 937/943/949/984/1000 etc."""
        src = self._source()
        # Each of these sites uses the established guard verbatim.
        # If any disappear or stop matching, this test won't detect it
        # directly — but it's a smoke check that the established pattern
        # exists at all in the file.
        assert "if not self.data or person_name not in self.data:" in src, (
            "Established guard pattern missing — production code may "
            "have drifted away from the v4.5.5 fix's reference pattern."
        )
