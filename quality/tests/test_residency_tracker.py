"""HOUSE-STATE step 1a D2: the pure residency tracker (INV-PRODUCER).

Plan PLANNING_house_state_axes_step1.md rev 3 §A3.1 / D2. Oracles are written
by hand with literal times (setup at 0 s, boot window 600 s, really-away
900 s); nothing below reads a production constant.
"""

from __future__ import annotations

from custom_components.universal_room_automation.domain_coordinators.residency import (
    KIND_ARRIVAL,
    KIND_DEPARTURE,
    ResidencyTracker,
)

OJI = "person.oji_udezue"
EZ = "person.ezinne_udezue"
KIOSK = "person.wall_kiosk"
RESIDENTS = frozenset({OJI, EZ})

SETUP = 0.0
AFTER_BOOT = 10_000.0  # well past the 600 s boot window


def _tracker(residents=RESIDENTS):
    return ResidencyTracker(
        lambda: residents, setup_ts=SETUP, boot_window_s=600.0,
        min_away_s=900.0, recent_events=32,
    )


def test_counted_arrival_record():
    t = _tracker()
    t.on_event(OJI, "home", "not_home", AFTER_BOOT)
    ev = t.on_event(OJI, "not_home", "home", AFTER_BOOT + 60)
    assert ev is not None
    assert ev.kind == KIND_ARRIVAL
    assert ev.person == OJI
    assert (ev.old_state, ev.new_state) == ("not_home", "home")
    assert ev.counted is True
    assert ev.source_stale is False
    assert ev.in_boot_window is False
    assert ev.resident_set_resolved is True
    assert t.arrived_at[OJI] == AFTER_BOOT + 60


def test_uncounted_unavailable_return():
    """home (real, 10 min ago) -> unavailable -> home: not counted; with the
    ledger not_home 20 min ago: counted (discriminates "counted is just
    old_val")."""
    t = _tracker()
    t.on_event(OJI, "not_home", "home", AFTER_BOOT)          # real home
    t.on_event(OJI, "home", "unavailable", AFTER_BOOT + 300)
    ev = t.on_event(OJI, "unavailable", "home", AFTER_BOOT + 600)
    assert ev.kind == KIND_ARRIVAL and ev.counted is False
    t2 = _tracker()
    t2.on_event(OJI, "home", "not_home", AFTER_BOOT)          # real not_home
    t2.on_event(OJI, "not_home", "unavailable", AFTER_BOOT + 1100)
    ev2 = t2.on_event(OJI, "unavailable", "home", AFTER_BOOT + 1200)
    assert ev2.counted is True


def test_attribute_event_keeps_since():
    """not_home at t0, attribute-only not_home -> not_home at t0+18 min,
    unavailable at t0+19, home at t0+20 -> counted (a restamp at +18 would
    make it 2 min away -> not counted)."""
    t0 = AFTER_BOOT
    t = _tracker()
    t.on_event(OJI, "home", "not_home", t0)
    assert t.on_event(OJI, "not_home", "not_home", t0 + 18 * 60) is None
    t.on_event(OJI, "not_home", "unavailable", t0 + 19 * 60)
    ev = t.on_event(OJI, "unavailable", "home", t0 + 20 * 60)
    assert ev.counted is True
    assert t.ledger[OJI] == ("home", t0 + 20 * 60, False)


def test_departure_record():
    t = _tracker()
    ev = t.on_event(EZ, "home", "not_home", AFTER_BOOT)
    assert ev.kind == KIND_DEPARTURE
    assert ev.counted is None
    assert ev.source_stale is False
    assert t.left_at[EZ] == AFTER_BOOT
    ev2 = t.on_event(EZ, "home", "work", AFTER_BOOT + 5)  # named zone
    assert ev2.kind == KIND_DEPARTURE


def test_home_to_unavailable_no_record():
    t = _tracker()
    assert t.on_event(EZ, "home", "unavailable", AFTER_BOOT) is None
    assert t.on_event(EZ, "home", "unknown", AFTER_BOOT + 1) is None
    assert list(t.recent) == []


def test_same_state_no_record():
    t = _tracker()
    assert t.on_event(EZ, "home", "home", AFTER_BOOT) is None
    assert t.on_event(EZ, "not_home", "not_home", AFTER_BOOT) is None
    assert list(t.recent) == []


def test_non_resident_ignored():
    t = _tracker()
    assert t.on_event(KIOSK, "not_home", "home", AFTER_BOOT) is None
    assert list(t.recent) == []
    # Its ledger is still kept (one ledger rule for every person.*).
    assert t.ledger[KIOSK] == ("home", AFTER_BOOT, False)


def test_empty_tracked_persons_falls_back_to_all_persons():
    """The resident set passed in is the caller's fallback (every person.*);
    with KIOSK in it, KIOSK edges are recorded."""
    t = _tracker(residents=frozenset({OJI, EZ, KIOSK}))
    ev = t.on_event(KIOSK, "not_home", "home", AFTER_BOOT)
    assert ev is not None and ev.person == KIOSK


def test_restore_edge_stamps_restored_no_record():
    t = _tracker()
    t.on_restore(OJI, "home", 5.0)
    assert t.ledger[OJI] == ("home", 5.0, True)
    assert list(t.recent) == []
    t.on_restore(EZ, "unavailable", 5.0)
    assert EZ not in t.ledger


def test_boot_window_flag():
    """Restore, then the next unknown -> home inside 600 s -> counted (boot
    exception) and in_boot_window True; at 600 s it is outside."""
    t = _tracker()
    t.on_restore(OJI, "home", 1.0)
    t.on_event(OJI, "home", "unknown", 100.0)
    ev = t.on_event(OJI, "unknown", "home", 599.0)
    assert ev.counted is True
    assert ev.in_boot_window is True
    t2 = _tracker()
    t2.on_event(OJI, "not_home", "home", 300.0)          # real home in boot
    t2.on_event(OJI, "home", "unknown", 590.0)
    ev2 = t2.on_event(OJI, "unknown", "home", 600.0)
    assert ev2.in_boot_window is False
    assert ev2.counted is False                          # blip while home


def test_source_stale_flag():
    t = _tracker()
    ev = t.on_event(OJI, "not_home", "home", AFTER_BOOT, source_stale=True)
    assert ev.source_stale is True
    dep = t.on_event(OJI, "home", "not_home", AFTER_BOOT + 5, source_stale=True)
    assert dep.source_stale is False  # departures never carry it


def test_recent_arrival_filters():
    t = _tracker()
    t.on_event(OJI, "not_home", "home", 100.0)                       # boot window
    assert t.recent_arrival(300, 200.0) is None
    assert t.recent_arrival(300, 200.0, include_boot=True).person == OJI
    t.on_event(EZ, "not_home", "home", AFTER_BOOT, source_stale=True)
    assert t.recent_arrival(300, AFTER_BOOT + 40) is None             # stale
    assert t.recent_arrival(300, AFTER_BOOT + 40, include_stale=True).person == EZ
    t.on_event(EZ, "home", "not_home", AFTER_BOOT + 50)
    t.on_event(EZ, "not_home", "home", AFTER_BOOT + 100)              # counted
    assert t.recent_arrival(300, AFTER_BOOT + 140).person == EZ
    assert t.recent_arrival(300, AFTER_BOOT + 400).person == EZ       # age 300
    assert t.recent_arrival(300, AFTER_BOOT + 401) is None            # age 301
    assert t.recent_arrival(0, AFTER_BOOT + 140) is None              # 0 = off
    # An uncounted arrival never qualifies with counted=True.
    t.on_event(OJI, "home", "unavailable", AFTER_BOOT + 200)
    t.on_event(OJI, "unavailable", "home", AFTER_BOOT + 210)          # blip
    assert t.recent_arrival(5, AFTER_BOOT + 212) is None
    assert t.recent_arrival(5, AFTER_BOOT + 212, counted=False).person == OJI


def test_unresolved_resident_set_records_flagged_and_skipped():
    t = ResidencyTracker(lambda: None, setup_ts=SETUP, boot_window_s=600.0,
                         min_away_s=900.0, recent_events=32)
    ev = t.on_event(KIOSK, "not_home", "home", AFTER_BOOT)
    assert ev is not None and ev.resident_set_resolved is False
    assert t.recent_arrival(300, AFTER_BOOT + 1) is None
    assert t.on_event("sensor.x", "off", "home", AFTER_BOOT) is None


def test_ring_is_bounded():
    t = ResidencyTracker(lambda: RESIDENTS, setup_ts=SETUP, boot_window_s=600.0,
                         min_away_s=900.0, recent_events=3)
    for i in range(5):
        t.on_event(OJI, "home", "not_home", AFTER_BOOT + 2 * i)
        t.on_event(OJI, "not_home", "home", AFTER_BOOT + 2 * i + 1)
    assert len(t.recent) == 3
