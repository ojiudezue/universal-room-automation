"""v4.5.7 — Solar banking now fires during away/vacation.

Bug: hvac_predict._check_pre_conditioning had an unconditional
`if house_state in ("away", "vacation"): return` at the top of the
function, blocking ALL pre-conditioning paths (weather pre-cool, solar
banking, pre-arrival, pre-heat) when nobody was home. But solar
banking's documented intent (line 346 comment: "Bank ALL zones
including away — energy has nowhere better to go") only makes sense
during away/vacation: the whole point is to dump surplus PV into the
building's thermal mass when battery is full and grid export is the
only alternative. Storing energy in an empty house has zero comfort
cost.

The early-return was added at some point as a "safety guard" but
silently broke the design intent. Three months of away days with
high SOC + surplus solar have all been exporting to grid for
~$0.04/kWh instead of free-cooling the house.

v4.5.7 fix: per-feature gating instead of one early-return.
- Solar banking → runs regardless of house_state (economics-driven)
- Weather pre-cool → keep away-skip (occupant-comfort driven)
- Pre-arrival → keep away-skip (defensive — pre_arrival_zones
  should be empty during away anyway)
- Pre-heat → keep away-skip (occupant-comfort driven)

Mirror-style tests (mirrors the gating logic since the function is
deeply coupled to the HVAC coordinator and not cleanly importable).
"""

import pytest


# ---------------------------------------------------------------------------
# Mirror of the v4.5.7 _check_pre_conditioning gating logic
# ---------------------------------------------------------------------------

def _gate_decisions(
    house_state: str,
    zone_intelligence_enabled: bool,
    solar_banking_eligible: bool,
    weather_precool_eligible: bool,
    pre_arrival_zones: set,
    preheat_eligible: bool,
):
    """Mirror — returns dict of which features fire under given inputs.

    Match production semantics of `_check_pre_conditioning` post-v4.5.7.
    """
    is_unoccupied = house_state in ("away", "vacation")

    weather_fired = (not is_unoccupied) and weather_precool_eligible

    if not zone_intelligence_enabled:
        return {
            "weather": weather_fired,
            "solar_banking": False,
            "pre_arrival_zones_fired": set(),
            "pre_heat": False,
        }

    # Solar banking — runs regardless of house_state
    solar_banking_fired = solar_banking_eligible

    # Pre-arrival — skipped during away/vacation
    pre_arrival_fired = set() if is_unoccupied else set(pre_arrival_zones)

    # Pre-heat — skipped during away/vacation
    pre_heat_fired = (not is_unoccupied) and preheat_eligible

    return {
        "weather": weather_fired,
        "solar_banking": solar_banking_fired,
        "pre_arrival_zones_fired": pre_arrival_fired,
        "pre_heat": pre_heat_fired,
    }


# ---------------------------------------------------------------------------
# Tests — solar banking gating
# ---------------------------------------------------------------------------

class TestSolarBankingFiresWhenAway:
    """The bug fix: solar banking must fire during away/vacation."""

    def test_away_state_solar_banking_fires(self):
        out = _gate_decisions(
            house_state="away",
            zone_intelligence_enabled=True,
            solar_banking_eligible=True,
            weather_precool_eligible=False,
            pre_arrival_zones=set(),
            preheat_eligible=False,
        )
        assert out["solar_banking"] is True, (
            "Solar banking MUST fire during away — economics drives this "
            "feature, not occupancy. Pre-v4.5.7 the unconditional early-"
            "return at hvac_predict.py:321 silently blocked it."
        )

    def test_vacation_state_solar_banking_fires(self):
        out = _gate_decisions(
            house_state="vacation",
            zone_intelligence_enabled=True,
            solar_banking_eligible=True,
            weather_precool_eligible=False,
            pre_arrival_zones=set(),
            preheat_eligible=False,
        )
        assert out["solar_banking"] is True

    def test_home_state_solar_banking_fires(self):
        """Regression — banking still fires for occupied house states."""
        out = _gate_decisions(
            house_state="home_day",
            zone_intelligence_enabled=True,
            solar_banking_eligible=True,
            weather_precool_eligible=False,
            pre_arrival_zones=set(),
            preheat_eligible=False,
        )
        assert out["solar_banking"] is True

    def test_solar_banking_blocked_by_zone_intelligence_toggle(self):
        """ZI toggle still gates solar banking (pre-existing behavior)."""
        out = _gate_decisions(
            house_state="away",
            zone_intelligence_enabled=False,
            solar_banking_eligible=True,
            weather_precool_eligible=False,
            pre_arrival_zones=set(),
            preheat_eligible=False,
        )
        assert out["solar_banking"] is False, (
            "Solar banking is a ZI feature; ZI=False must still skip it."
        )

    def test_solar_banking_skipped_when_not_eligible(self):
        """If _should_solar_bank returns False, no firing regardless of state."""
        out = _gate_decisions(
            house_state="away",
            zone_intelligence_enabled=True,
            solar_banking_eligible=False,
            weather_precool_eligible=False,
            pre_arrival_zones=set(),
            preheat_eligible=False,
        )
        assert out["solar_banking"] is False


# ---------------------------------------------------------------------------
# Tests — other features keep their away-skip (regression)
# ---------------------------------------------------------------------------

class TestOtherFeaturesKeepAwaySkip:
    """Weather pre-cool, pre-arrival, pre-heat are occupant-driven and
    must stay skipped during away/vacation."""

    def test_weather_precool_skipped_during_away(self):
        out = _gate_decisions(
            house_state="away",
            zone_intelligence_enabled=True,
            solar_banking_eligible=False,
            weather_precool_eligible=True,
            pre_arrival_zones=set(),
            preheat_eligible=False,
        )
        assert out["weather"] is False

    def test_weather_precool_fires_when_home(self):
        out = _gate_decisions(
            house_state="home_day",
            zone_intelligence_enabled=True,
            solar_banking_eligible=False,
            weather_precool_eligible=True,
            pre_arrival_zones=set(),
            preheat_eligible=False,
        )
        assert out["weather"] is True

    def test_pre_arrival_skipped_during_away(self):
        """Pre-arrival is by definition predicting arrival, but the
        defensive away-skip protects against a race where pre_arrival_zones
        wasn't cleared before house_state flipped to away."""
        out = _gate_decisions(
            house_state="away",
            zone_intelligence_enabled=True,
            solar_banking_eligible=False,
            weather_precool_eligible=False,
            pre_arrival_zones={"zone_3"},
            preheat_eligible=False,
        )
        assert out["pre_arrival_zones_fired"] == set()

    def test_pre_arrival_fires_when_home(self):
        out = _gate_decisions(
            house_state="home_day",
            zone_intelligence_enabled=True,
            solar_banking_eligible=False,
            weather_precool_eligible=False,
            pre_arrival_zones={"zone_3", "zone_5"},
            preheat_eligible=False,
        )
        assert out["pre_arrival_zones_fired"] == {"zone_3", "zone_5"}

    def test_pre_heat_skipped_during_vacation(self):
        out = _gate_decisions(
            house_state="vacation",
            zone_intelligence_enabled=True,
            solar_banking_eligible=False,
            weather_precool_eligible=False,
            pre_arrival_zones=set(),
            preheat_eligible=True,
        )
        assert out["pre_heat"] is False

    def test_pre_heat_fires_when_home(self):
        out = _gate_decisions(
            house_state="home_day",
            zone_intelligence_enabled=True,
            solar_banking_eligible=False,
            weather_precool_eligible=False,
            pre_arrival_zones=set(),
            preheat_eligible=True,
        )
        assert out["pre_heat"] is True


# ---------------------------------------------------------------------------
# Source contract — production must match the mirror
# ---------------------------------------------------------------------------

class TestSourceContract:
    @pytest.fixture
    def src(self):
        path = "custom_components/universal_room_automation/domain_coordinators/hvac_predict.py"
        with open(path) as f:
            return f.read()

    def test_no_unconditional_away_early_return(self, src):
        """The pre-v4.5.7 bug was an unconditional `if house_state in
        ('away', 'vacation'): return` at the top of _check_pre_conditioning,
        before the function even computed which features were eligible.
        After v4.5.7 the gating moved per-feature, so this exact pattern
        must not exist as the function's first decision."""
        idx = src.find("async def _check_pre_conditioning")
        assert idx > 0, "_check_pre_conditioning must exist"
        body_end = src.find("\n    async def ", idx + 1)
        if body_end == -1:
            body_end = src.find("\n    def ", idx + 1)
        body = src[idx:body_end] if body_end > 0 else src[idx:idx + 8000]

        # The function previously returned outright when away/vacation.
        # Detect that by finding the early-return pattern that lacks the
        # `is_unoccupied` per-feature gating idiom we replaced it with.
        # Specifically: an `if house_state in ("away", "vacation"):\n    ... return`
        # at module-flow level (not nested in a per-feature branch).
        bad_pattern = 'if house_state in ("away", "vacation"):\n            return'
        assert bad_pattern not in body, (
            "Found the pre-v4.5.7 unconditional away early-return. The "
            "fix is per-feature gating; restore the v4.5.7 structure."
        )

    def test_solar_banking_block_does_not_check_house_state(self, src):
        """Solar banking branch in _check_pre_conditioning must NOT gate
        on house_state (that's the whole point of v4.5.7)."""
        # Find the solar banking section between its anchor comment and
        # the next major section (pre-arrival).
        anchor = "Solar banking (economics-driven"
        idx = src.find(anchor)
        assert idx > 0, "v4.5.7 solar banking anchor comment must exist"
        next_section = src.find("Pre-arrival", idx)
        block = src[idx:next_section] if next_section > 0 else src[idx:idx + 1500]

        # The block should NOT contain any check that returns/skips
        # based on house_state being away/vacation.
        assert 'house_state in ("away"' not in block
        assert "is_unoccupied" not in block, (
            "Solar banking branch must NOT gate on is_unoccupied — that's "
            "the entire point of v4.5.7. Banking runs regardless of "
            "house state."
        )

    def test_weather_precool_still_gated_on_unoccupied(self, src):
        """Weather pre-cool MUST still skip during away/vacation."""
        idx = src.find("Weather pre-cool")
        assert idx > 0
        next_anchor = src.find("Solar banking", idx)
        block = src[idx:next_anchor] if next_anchor > 0 else src[idx:idx + 1500]
        assert "is_unoccupied" in block, (
            "Weather pre-cool block must guard on is_unoccupied — it's "
            "occupant-comfort driven."
        )

    def test_pre_arrival_still_gated_on_unoccupied(self, src):
        idx = src.find("Pre-arrival")
        assert idx > 0
        next_anchor = src.find("Pre-heat", idx)
        block = src[idx:next_anchor] if next_anchor > 0 else src[idx:idx + 1500]
        assert "is_unoccupied" in block

    def test_pre_heat_still_gated_on_unoccupied(self, src):
        idx = src.find("Pre-heat (winter")
        assert idx > 0
        block = src[idx:idx + 1500]
        assert "is_unoccupied" in block
