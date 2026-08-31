"""EVSE charge-onset gate — Tier-2-DB mutation-anchored tests.

Cycle: evse-charge-onset. Adds a session-anchored HH:MM gate to the OVERNIGHT
`battery_out_of_capacity` leg of `EVChargerController` and `SmartPlugController`
`determine_battery_drain_actions`. The daytime `soc_recovered` leg is UNGATED
(distributive-form reassociation is a defect the review caught).

Sites anchored (each: neuter the named site, this test file's named test goes
RED, restore):

  * energy_pool.py EV release clause (~:2008 pre-patch, reassoc): the
    `(battery_out_of_capacity and (onset_reached or dp_forcing)) or soc_recovered`
    form. Distributive-form regression → daytime test fails.
  * energy_pool.py plug release clause (~:3343 pre-patch, reassoc): mirror.
  * energy_drain_precedence.next_occurrence_of_hhmm — the LOOKBACK shift
    in _charge_onset_reached. Setting LOOKBACK to 0 → 22:00-anchor case fails
    (the naive-impl-killer).
  * Session-anchor stamp on empty→non-empty pause set (`_drain_session_started_at`).
    Removing the stamp → onset-reached returns True (anchor=None), gate does
    not hold, overnight test fails.

The bootstrap piggybacks on test_energy_pool_drain (installs HA stubs).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import test_energy_pool_drain  # noqa: F401  side-effect: stubs
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402
from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
    SmartPlugController,
    ONSET_SESSION_LOOKBACK_H,
    _parse_hhmm,
)
from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E402
    next_occurrence_of_hhmm,
    compute_must_start_by,
)


CDT = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ev(charging=True):
    hass = MockHass()
    hass.set_state("switch.garage_a", "off")  # off so we can observe turn_on
    hass.set_state("sensor.garage_a_power_minute_average", "5000" if charging else "0")
    hass.set_state("sensor.garage_a_energy_today", "0")
    hass.set_state("sensor.garage_a_energy_this_month", "0")
    ev = EVChargerController(hass, evse_config={
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power_minute_average",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_this_month",
        },
    })
    ev._paused_by_battery_drain.add("garage_a")
    return ev, hass


def _make_plug():
    hass = MockHass()
    plug_id = "switch.moes_plug_garage_a"
    hass.set_state(plug_id, "off")
    sp = SmartPlugController(hass, plug_entities=[plug_id])
    sp._paused_by_battery_drain.add(plug_id)
    return sp, hass, plug_id


def _release_fires(actions) -> bool:
    return any(a.get("service") == "switch.turn_on" for a in actions)


# ---------------------------------------------------------------------------
# Extracted helper — byte-identical for compute_must_start_by
# ---------------------------------------------------------------------------


class TestExtractedHelperByteIdentical:
    """`compute_must_start_by` MUST route through `next_occurrence_of_hhmm`
    and produce identical outputs vs the pre-extraction inline form."""

    @pytest.mark.parametrize("now_h,now_m,target_min,expect_add_day", [
        (0, 30, 180, False),   # now=00:30, target=03:00 today
        (5, 0, 180, True),     # now=05:00, target=03:00 tomorrow
        (2, 59, 180, False),   # strict inequality: 02:59 < 03:00 → today
        (3, 0, 180, True),     # 03:00 == today target → tomorrow (strict-after)
        (23, 30, 60, True),    # 23:30, target 01:00 → tomorrow
    ])
    def test_must_start_by_matches_inline_semantics(
        self, now_h, now_m, target_min, expect_add_day,
    ):
        now = datetime(2026, 1, 15, now_h, now_m, tzinfo=CDT)
        got = compute_must_start_by(now, minutes_past_midnight=target_min)
        hh, mm = divmod(target_min, 60)
        expected = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if expect_add_day:
            expected = expected + timedelta(days=1)
        assert got == expected


class TestNextOccurrenceStrictlyAfter:
    def test_strictly_after_at_boundary(self):
        now = datetime(2026, 1, 15, 3, 0, tzinfo=CDT)
        got = next_occurrence_of_hhmm(now, 3, 0)
        # STRICTLY-after: at-or-after the target → tomorrow
        assert got == now + timedelta(days=1)


# ---------------------------------------------------------------------------
# Onset gate — the DISCRIMINATING cases (§5 / §D2)
# ---------------------------------------------------------------------------


class TestDaytimeSolarLegUngated:
    """DAYTIME: soc_recovered=True at 12:00, bat_out_of_cap=False,
    onset="01:00" → release turn_on FIRES at 12:00 (daytime leg ungated).

    KILL: distributing the AND across both legs (the review's regression
    form) makes this test go RED — solar release would be held until
    tomorrow's 01:00, contradicting the daytime-solar semantics.
    """

    def test_ev_daytime_soc_recovered_fires_when_onset_set(self):
        ev, hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        # Simulate a session anchor at 08:00 same day (drain was open earlier)
        ev._drain_session_started_at = datetime(2026, 1, 15, 8, 0, tzinfo=CDT)
        # Battery NOT discharging, solar replenishing, SOC well above threshold+5
        actions = ev.determine_battery_drain_actions(
            battery_power_w=+200.0,        # positive → NOT discharging
            battery_soc=80.0,               # >= 50+5=55 → soc_recovered=True
            soc_threshold=50,
            reserve_soc=20,                 # SOC 80 > 20+2 → NOT bat_out_of_cap
            solar_replenishing=True,
            is_offpeak=False,               # daytime; is_offpeak irrelevant here
            now_local=datetime(2026, 1, 15, 12, 0, tzinfo=CDT),
        )
        assert _release_fires(actions), (
            "daytime soc_recovered leg must be UNGATED; distributive-form "
            "reassociation would incorrectly hold this release"
        )

    def test_plug_daytime_soc_recovered_fires_when_onset_set(self):
        sp, hass, plug_id = _make_plug()
        sp.set_ev_charge_onset_time("01:00")
        sp._drain_session_started_at = datetime(2026, 1, 15, 8, 0, tzinfo=CDT)
        actions = sp.determine_battery_drain_actions(
            battery_power_w=+200.0,
            battery_soc=80.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=True,
            is_offpeak=False,
            now_local=datetime(2026, 1, 15, 12, 0, tzinfo=CDT),
        )
        assert _release_fires(actions)


class TestOvernightHoldUntilOnset:
    """OVERNIGHT: anchor 20:00, onset 01:00 → hold at 20:15, release at 01:00 d2."""

    def test_ev_anchor_2000_holds_at_2015_and_fires_at_0100_d2(self):
        ev, hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        ev._drain_session_started_at = datetime(2026, 1, 15, 20, 0, tzinfo=CDT)
        # Bat_out_of_cap: SOC just above reserve; battery not discharging;
        # solar NOT replenishing (overnight); soc_recovered=False.
        common = dict(
            battery_power_w=+50.0,
            battery_soc=22.0,   # SOC == reserve+2 → bat_out_of_cap=True
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
        )
        # At 20:15 — before onset → HOLD (no turn_on)
        actions_hold = ev.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 15, 20, 15, tzinfo=CDT), **common,
        )
        assert not _release_fires(actions_hold), (
            "overnight bat_out_of_cap must be gated until onset"
        )
        # At 01:00 next day — onset reached → FIRE
        # (need to re-add since discard on release cleared it; re-arm)
        ev._paused_by_battery_drain.add("garage_a")
        actions_fire = ev.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 16, 1, 0, tzinfo=CDT), **common,
        )
        assert _release_fires(actions_fire)

    def test_ev_anchor_2200_operator_example_fires_at_0100_d2(self):
        """OPERATOR EXAMPLE: anchor 22:00, onset 01:00 → fire 01:00 d2.

        KILL TARGET: a naive `now.hour >= onset.hour` at anchor=22:00
        would compute `today_target=01:00` for the anchor date, which is
        ALREADY PAST at 22:00 — a naive impl (no LOOKBACK shift) resolves
        to today's 01:00, so `now=22:15 >= 22:00` short-circuit; OR
        conversely resolves to tomorrow's 01:00 but then `now.hour >=1`
        opens at 22:00 same day. Either naive form gives WRONG answers.

        The correct answer: onset_instant = tomorrow's 01:00 (16:00 shift
        makes today_target=01:00 already-past, so next occurrence rolls
        to tomorrow). Held at 22:15, held at 00:30 d2, fires at 01:00 d2.
        """
        ev, hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        ev._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        common = dict(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
        )
        # 22:15 → hold
        acts = ev.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 15, 22, 15, tzinfo=CDT), **common,
        )
        assert not _release_fires(acts), "held at 22:15 (pre-onset)"
        # 00:30 d2 → still hold (onset is 01:00 d2, not today's 01:00 which is past)
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 16, 0, 30, tzinfo=CDT), **common,
        )
        assert not _release_fires(acts), (
            "held at 00:30 d2 (still before onset 01:00 d2); a naive "
            "hour-compare would have fired here"
        )
        # 01:00 d2 → fires
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 16, 1, 0, tzinfo=CDT), **common,
        )
        assert _release_fires(acts), "must fire at onset 01:00 d2"

    def test_ev_anchor_0215_after_onset_fires_immediately(self):
        """anchor 02:15 (already past 01:00) → fire immediately."""
        ev, hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        ev._drain_session_started_at = datetime(2026, 1, 16, 2, 15, tzinfo=CDT)
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            now_local=datetime(2026, 1, 16, 2, 15, tzinfo=CDT),
        )
        assert _release_fires(acts), (
            "session opened AFTER onset → onset_reached=True immediately; "
            "if LOOKBACK were 0 this would incorrectly resolve to "
            "tomorrow's 01:00 and hold"
        )

    def test_plug_anchor_2200_fires_at_0100_d2(self):
        sp, hass, plug_id = _make_plug()
        sp.set_ev_charge_onset_time("01:00")
        sp._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        common = dict(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
        )
        acts = sp.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 15, 23, 0, tzinfo=CDT), **common,
        )
        assert not _release_fires(acts)
        sp._paused_by_battery_drain.add(plug_id)
        acts = sp.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 16, 1, 0, tzinfo=CDT), **common,
        )
        assert _release_fires(acts)


class TestDPForcingOverridesOnset:
    def test_ev_dp_forcing_overrides_onset_hold(self):
        ev, hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        ev._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            dp_forcing=True,
            now_local=datetime(2026, 1, 15, 22, 30, tzinfo=CDT),
        )
        assert _release_fires(acts), (
            "MUST_START_FORCED must override the onset hold — a plane "
            "already flying beats a scheduled departure"
        )


class TestBlankOnsetByteIdenticalBaseline:
    def test_ev_blank_onset_releases_immediately(self):
        """Blank onset ⇒ gate disabled ⇒ overnight release fires immediately.

        Byte-identical to pre-cycle baseline for the overnight leg.
        """
        ev, hass = _make_ev()
        ev.set_ev_charge_onset_time(None)  # gate off
        ev._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            now_local=datetime(2026, 1, 15, 22, 30, tzinfo=CDT),
        )
        assert _release_fires(acts), "no onset ⇒ baseline behavior"

    def test_ev_empty_string_onset_disables_gate(self):
        ev, hass = _make_ev()
        ev.set_ev_charge_onset_time("")
        ev._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            now_local=datetime(2026, 1, 15, 22, 30, tzinfo=CDT),
        )
        assert _release_fires(acts)


# ---------------------------------------------------------------------------
# Session anchor lifecycle
# ---------------------------------------------------------------------------


class TestSessionAnchorLifecycle:
    def test_anchor_stamped_on_empty_to_nonempty_transition(self):
        """Mutation drill: removing the stamp block → onset gate becomes
        permissive (anchor=None ⇒ _charge_onset_reached returns True) ⇒
        overnight test above regresses to release-immediately (RED).
        """
        ev, hass = _make_ev(charging=True)
        # start with EMPTY pause set (drain not open)
        ev._paused_by_battery_drain.discard("garage_a")
        assert ev._drain_session_started_at is None
        # Present the pause-trigger conditions: charging + discharging + SOC low
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000")
        # Battery discharging, SOC below threshold → PAUSE fires, anchor stamps
        acts = ev.determine_battery_drain_actions(
            battery_power_w=-500.0,
            battery_soc=40.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            now_local=datetime(2026, 1, 15, 22, 0, tzinfo=CDT),
        )
        assert "garage_a" in ev._paused_by_battery_drain
        assert ev._drain_session_started_at is not None, (
            "session anchor must stamp on empty→non-empty transition"
        )

    def test_anchor_cleared_on_session_close(self):
        ev, hass = _make_ev()
        # Session was open; simulate release conditions clearing the set
        ev._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        # SOC recovered, daytime → release, empties the set
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+200.0,
            battery_soc=80.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=True,
            is_offpeak=False,
            now_local=datetime(2026, 1, 16, 12, 0, tzinfo=CDT),
        )
        assert not ev._paused_by_battery_drain
        assert ev._drain_session_started_at is None, (
            "anchor must clear when pause set drains → session closed"
        )

    def test_mark_drain_session_from_restore(self):
        ev, hass = _make_ev()
        anchor = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        ev.mark_drain_session_from_restore(anchor)
        assert ev._drain_session_started_at == anchor


# ---------------------------------------------------------------------------
# Onset helper: unit tests
# ---------------------------------------------------------------------------


class TestChargeOnsetReachedHelper:
    def test_lookback_shift_kills_naive_hour_compare(self):
        """LOOKBACK=6h is what makes the anchor-22:00 case resolve to
        TOMORROW's 01:00. If LOOKBACK were 0, `next_occurrence_of_hhmm(
        22:00, 01, 00)` would return tomorrow's 01:00 too, BUT
        `now=22:15 >= tomorrow's 01:00` = False — held. That happens
        to be correct at 22:15. The failure mode is at now=02:15 with
        anchor=02:15 (after-onset session): LOOKBACK=0 →
        `next_occurrence_of_hhmm(02:15, 01, 00)` = tomorrow 01:00 →
        now(02:15) < tomorrow 01:00 → held. With LOOKBACK=6h, shifted
        anchor = yesterday 20:15 → today 01:00 → now(02:15) >= today
        01:00 → fires. This test asserts the LOOKBACK-critical case.
        """
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        ev._drain_session_started_at = datetime(2026, 1, 16, 2, 15, tzinfo=CDT)
        # LOOKBACK=6 → onset reached
        assert ev._charge_onset_reached(datetime(2026, 1, 16, 2, 15, tzinfo=CDT))

    def test_no_anchor_permissive(self):
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        ev._drain_session_started_at = None
        assert ev._charge_onset_reached(datetime(2026, 1, 16, 2, 15, tzinfo=CDT))

    def test_no_onset_permissive(self):
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_time(None)
        ev._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        assert ev._charge_onset_reached(datetime(2026, 1, 15, 22, 30, tzinfo=CDT))

    def test_malformed_onset_permissive(self):
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_time("not-a-time")
        ev._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        # Malformed value is dropped by setter (stored as None) ⇒ permissive
        assert ev._ev_charge_onset_time is None
        assert ev._charge_onset_reached(datetime(2026, 1, 15, 22, 30, tzinfo=CDT))


class TestParseHHMM:
    @pytest.mark.parametrize("v,expect", [
        ("01:00", (1, 0)),
        ("23:59", (23, 59)),
        ("0:00", (0, 0)),
        ("", None),
        ("bad", None),
        ("25:00", None),
        ("01:60", None),
        (None, None),
    ])
    def test_parse_hhmm(self, v, expect):
        assert _parse_hhmm(v) == expect


class TestLookbackConstant:
    def test_lookback_is_6h(self):
        assert ONSET_SESSION_LOOKBACK_H == 6


# ---------------------------------------------------------------------------
# TASK 1 — Structural-split discriminator (one per site)
# ---------------------------------------------------------------------------


class TestNamedLegSplitDiscriminator:
    """After TASK 1 (structural split), the release condition is:

        daytime_release   = soc_recovered
        overnight_release = battery_out_of_capacity and (onset_reached or dp_forcing)
        if daytime_release or overnight_release: ...

    These per-site discriminators pin the property that WITH onset SET
    but NOT yet reached, the DAYTIME leg alone MUST still fire — because
    `soc_recovered` never appears inside the AND. This is the exact
    scenario that would silently regress if a future edit accidentally
    distributed the AND across both legs, or accidentally collapsed the
    two named booleans back into `if daytime and overnight`.

    Distinct from `TestDaytimeSolarLegUngated`: that class fires with
    onset_reached=True (session anchor stamped BEFORE the wall-clock
    onset instant — the gate would technically be open at test-time).
    Here we deliberately arrange `overnight_release=False AND
    onset_reached=False AND battery_out_of_capacity=False` so the ONLY
    way to fire is via `daytime_release=True`.
    """

    def test_ev_daytime_leg_fires_when_overnight_leg_dark(self):
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        # Session anchor at 22:00 day-1 → onset resolves to 01:00 day-2
        ev._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        # Force overnight_release=False: battery_out_of_capacity=False
        # (SOC well above reserve+2). onset_reached is IRRELEVANT to
        # daytime_release; asserting the split by construction.
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+200.0,     # not discharging
            battery_soc=80.0,            # >>reserve+2 → bat_out_of_cap=False
            soc_threshold=50,            # SOC>=55 → soc_recovered=True
            reserve_soc=20,
            solar_replenishing=True,     # daytime, solar on
            is_offpeak=False,
            now_local=datetime(2026, 1, 15, 22, 30, tzinfo=CDT),
        )
        # Even at 22:30 (well before the 01:00 d2 onset), daytime fires.
        assert _release_fires(acts), (
            "TASK 1 named-leg split: daytime_release must fire alone "
            "when overnight_release is dark, regardless of onset state"
        )

    def test_plug_daytime_leg_fires_when_overnight_leg_dark(self):
        sp, _hass, _plug_id = _make_plug()
        sp.set_ev_charge_onset_time("01:00")
        sp._drain_session_started_at = datetime(2026, 1, 15, 22, 0, tzinfo=CDT)
        acts = sp.determine_battery_drain_actions(
            battery_power_w=+200.0,
            battery_soc=80.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=True,
            is_offpeak=False,
            now_local=datetime(2026, 1, 15, 22, 30, tzinfo=CDT),
        )
        assert _release_fires(acts), (
            "TASK 1 named-leg split (plug mirror): daytime_release fires alone"
        )
