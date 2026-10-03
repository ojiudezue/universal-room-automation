"""HVAC W1-C P1 — Carrier byte-identity oracle (ONE parametrized suite).

Plan: ``docs/planning/PLANNING_hvac_w1c_thermostat_profiles.md`` REV 3 + REV 3.1
errata, P1 "Byte-identity oracle (F2)"; operator ruling 5 (one parametrized
suite, S-site x WriteStatus table, not per-site files).

HOW THE ORACLE IS AUTHORED (Bug Class #62 guard — never regenerate):
  * The goldens in ``golden/w1c_p1_goldens.json`` were CAPTURED by running this
    exact file with ``URA_W1C_RECORD_GOLDENS=1`` on the tagged baseline
    ``pre-w1c-p1`` (develop @52781d54f), BEFORE any P1 production edit, and
    committed in their own commit. A regeneration on the P1 branch is a
    review-blocking diff.
  * Capture point = ``hass.services.async_call`` (the REAL funnels run,
    including resume-then-pin, the comfort-delay gate and the freeze/deadband
    guards). The strategy under test is whatever ``strategy_for`` resolves
    from a REAL entity-registry lookup: the fixture registry reports
    ``platform="ha_carrier"`` (Carrier) or has no entry (registry miss ->
    Generic). ``strategy_for`` is never monkeypatched.

EQUALITY (per scenario): the ordered climate service calls
(domain / service / data / blocking) AND the ``climate_write`` ledger rows AND
the other ledger rows (``ura_activity_log`` via the activity logger,
``ac_ramp_events``, ``hvac_excursion_events`` / excursion-row persistence) AND
the arrester suppression store ``{entity: (_suppress_kind, ttl)}`` (errata R1:
``OverrideArrester._suppressed_until`` / ``_suppress_kind``) AND the named
in-memory state per site AND the exception (if any) that escaped the enclosing
method (the site's old bool->branch mapping is observable through these).
Order is per zone (every scenario drives one zone).

Variants (WriteStatus axis):
  applied            wire call succeeds
  deferred           comfort-delay gate says DEFER (sites that pass a gate)
  failed_raise       every climate service call raises RuntimeError
  failed_no_presets  the entity advertises NO preset_modes
  unavailable        the entity reads ``unavailable`` with no attributes
  skipped            the Carrier strategy's last_sent already equals the
                     preset the site writes AND the live entity shows it
                     (only S1 may no-op; for every other site this variant
                     proves it does NOT)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402

GOLDEN_PATH = Path(_HERE) / "golden" / "w1c_p1_goldens.json"
RECORD = os.environ.get("URA_W1C_RECORD_GOLDENS") == "1"

ZONE = "zone_1"
ENT = "climate.test_zone_1"
VARIANTS = (
    "applied", "deferred", "failed_raise", "failed_no_presets",
    "unavailable", "skipped",
)


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    return H.load_real()


@pytest.fixture
def expected_lingering_timers():
    return True


# --------------------------------------------------------------------------
# Recording fakes
# --------------------------------------------------------------------------


class RecDB(H.FakeDB):
    """FakeDB that records every DAO call the write sites make (the
    ``ac_ramp_events`` / excursion persistence / ``ura_activity_log`` rows)."""

    def __init__(self, *, in_flight=None, excursion_rows=None):
        super().__init__()
        self.dao: list[list] = []
        self._in_flight = dict(in_flight or {})
        self._ex_rows = list(excursion_rows or [])
        self._event_id = 0

    def _rec(self, name, kw):
        self.dao.append([name, dict(kw)])

    # excursion primitive
    async def save_excursion_row(self, row):
        self._rec("save_excursion_row", row)

    async def clear_excursion_row(self, zone_id):
        self._rec("clear_excursion_row", {"zone_id": zone_id})

    async def get_all_excursion_rows(self):
        return list(self._ex_rows)

    async def log_excursion_event(self, **kw):
        self._rec("log_excursion_event", kw)

    # AC ramp surface
    async def get_ac_reset_state(self, zone_id, date=None):
        return {
            "zone_id": zone_id,
            "in_flight_nudge_original_target": self._in_flight.get(zone_id),
            "soft_nudge_count": 0, "day_reset_count": 0, "night_reset_count": 0,
        }

    async def set_ac_in_flight_nudge(self, **kw):
        self._rec("set_ac_in_flight_nudge", kw)
        self._in_flight[kw.get("zone_id")] = kw.get("original_target")

    async def clear_ac_in_flight_nudge(self, zone_id):
        self._rec("clear_ac_in_flight_nudge", {"zone_id": zone_id})
        self._in_flight.pop(zone_id, None)

    async def save_ac_reset_state(self, state):
        self._rec("save_ac_reset_state", state)

    async def log_ac_ramp_event(self, **kw):
        self._rec("log_ac_ramp_event", kw)
        self._event_id += 1
        return self._event_id

    async def update_ac_ramp_restore_settled(self, **kw):
        self._rec("update_ac_ramp_restore_settled", kw)

    async def update_ac_ramp_event_fields(self, *a, **kw):
        self._rec("update_ac_ramp_event_fields", {"args": list(a), **kw})

    async def get_zones_with_in_flight_nudge(self):
        return [
            {"zone_id": z, "original_target": t, "nudged_target": t + 1.5,
             "started_ts": "2000-01-01T00:00:00+00:00", "duration_s": 120}
            for z, t in self._in_flight.items() if t is not None
        ]


_ISO_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?"
)
_EPOCH_MS_RE = re.compile(r":\d{12,14}\b")
# S9 notes carry wall-clock elapsed seconds since the fixture's fixed
# 2000-01-01 start — masked (non-deterministic across runs).
_ELAPSED_RE = re.compile(r"elapsed_s=\d+")


def _norm(obj):
    """Deterministic JSON form: ISO datetimes and epoch-ms ids masked."""
    s = json.dumps(obj, default=str, sort_keys=True)
    s = _ISO_RE.sub("<ts>", s)
    s = _EPOCH_MS_RE.sub(":<ms>", s)
    s = _ELAPSED_RE.sub("elapsed_s=<s>", s)
    return json.loads(s)


class _Ctx:
    def __init__(self, mods, hass, coord, variant, registry):
        self.mods = mods
        self.hass = hass
        self.coord = coord
        self.arr = coord._override_arrester
        self.pred = coord._predictor
        self.egress = coord._egress_manager
        self.ex = mods["hvac_excursion"]
        self.S = mods["hvac_strategy"]
        self.variant = variant
        self.registry = registry
        self.calls: list[dict] = []
        self.timers: list[list] = []
        self.apply_modes = False
        self.db: RecDB | None = None
        self.exc: str | None = None

    @property
    def zone(self):
        return self.coord.zone_manager.zones[ZONE]

    def set_entity(self, **kw):
        """Place the live climate entity, honouring the variant."""
        if self.variant == "unavailable":
            self.hass.states.async_set(ENT, "unavailable", {})
            return
        if self.variant == "failed_no_presets":
            kw["preset_modes"] = ()
        H.set_climate(self.hass, ENT, **kw)

    def seed_last_sent(self, preset):
        """`skipped` variant: the CARRIER strategy already sent `preset` and
        the live entity (placed by the scenario) shows it."""
        if self.variant != "skipped":
            return
        self.S.strategy_for_platform("ha_carrier")._record_sent(
            ENT, "set_preset_mode", preset,
        )

    def defer_gate(self):
        if self.variant == "deferred":
            self.arr.comfort_delay_active = lambda zone_id=None: True


def _install(mods, monkeypatch, *, variant, registry, db_kwargs=None):
    coord, hass = H.make_coord(mods)
    ctx = _Ctx(mods, hass, coord, variant, registry)
    DOMAIN = mods["const"].DOMAIN
    db = RecDB(**(db_kwargs or {}))
    hass.data[DOMAIN]["database"] = db
    ctx.db = db
    ctx.arr._db = db
    ctx.ex._test_clear_leases()
    ctx.ex._test_bind(hass=hass, db=db)
    ctx.S._test_reset_cache()
    # Order-robustness: the per-day NM latch (e.g. "Governed borrow
    # restore failed") is module state; a prior test that latched it would
    # suppress this scenario's NM. Reset so every scenario starts clean.
    import importlib as _il
    _il.import_module(
        "custom_components.universal_room_automation.domain_coordinators._stuck_signal_nm"
    ).reset_latches_for_tests()

    # REAL registry lookup through a fixture registry (strategy_for is NOT
    # patched): Carrier platform, or a miss (-> Generic, uncached).
    from homeassistant.helpers import entity_registry as er

    class _Reg:
        def async_get(self, entity_id):
            if registry == "carrier" and str(entity_id).startswith("climate."):
                return types.SimpleNamespace(platform="ha_carrier", entity_id=entity_id)
            return None

    _reg = _Reg()
    monkeypatch.setattr(er, "async_get", lambda _h: _reg)

    async def _svc(domain, service, service_data=None, blocking=False, **_kw):
        data = dict(service_data or {})
        ctx.calls.append({
            "domain": domain, "service": service, "data": data,
            "blocking": bool(blocking),
        })
        if variant == "failed_raise" and domain == "climate":
            raise RuntimeError("w1c_golden_wire_failure")
        if ctx.apply_modes and domain == "climate" and service == "set_hvac_mode":
            st = hass.states.get(data.get("entity_id"))
            if st is not None:
                hass.states.async_set(
                    data["entity_id"], data["hvac_mode"], dict(st.attributes),
                )
        return None

    hass.services.async_call = _svc

    def _fake_call_later(module_name):
        def _cl(_hass, delay, _cb):
            try:
                d = float(delay.total_seconds()) if hasattr(delay, "total_seconds") else float(delay)
            except Exception:  # noqa: BLE001
                d = -1.0
            ctx.timers.append([module_name, int(round(d))])
            return lambda: None
        return _cl

    for m in ("hvac", "hvac_override", "hvac_predict"):
        if hasattr(mods[m], "async_call_later"):
            monkeypatch.setattr(mods[m], "async_call_later", _fake_call_later(m))

    real_asyncio = mods["hvac_override"].asyncio

    async def _instant_sleep(*_a, **_k):
        await real_asyncio.sleep(0)

    class _AsyncioProxy:
        def __getattr__(self, name):
            if name == "sleep":
                return _instant_sleep
            return getattr(real_asyncio, name)

    monkeypatch.setattr(mods["hvac_override"], "asyncio", _AsyncioProxy())

    # Fixed local clock for the predictor (pre-heat duration is measured to
    # OFF_PEAK_END_HOUR from now()).
    real_dt = mods["hvac_predict"].dt_util
    fixed_local = real_dt.now().replace(hour=3, minute=0, second=0, microsecond=0)

    class _DtProxy:
        def __getattr__(self, name):
            if name == "now":
                return lambda *a, **k: fixed_local
            return getattr(real_dt, name)

    monkeypatch.setattr(mods["hvac_predict"], "dt_util", _DtProxy())
    return ctx


async def _drain(hass, rounds: int = 40):
    for _ in range(rounds):
        tasks = [t for t in getattr(hass, "_stub_tasks", []) if not t.done()]
        if not tasks:
            await asyncio.sleep(0)
            continue
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)


def _observe(ctx) -> dict:
    mods, hass, arr = ctx.mods, ctx.hass, ctx.arr
    DOMAIN = mods["const"].DOMAIN
    now = mods["hvac_override"].dt_util.now()
    supp = {}
    for eid, until in arr._suppressed_until.items():
        try:
            ttl = int(round((until - now).total_seconds()))
        except Exception:  # noqa: BLE001
            ttl = None
        supp[eid] = [arr._suppress_kind.get(eid), ttl]
    cw = []
    other_rows = []
    for r in ctx.db.rows:
        if r.get("action") == "climate_write":
            d = json.loads(r["details_json"])
            d.pop("ts_issued", None)
            d.pop("ts_returned", None)
            cw.append({"entity_id": r.get("entity_id"), "zone": r.get("zone"), **d})
        else:
            other_rows.append(r)
    act = [
        {k: v for k, v in r.items() if k != "description"}
        for r in hass.data[DOMAIN]["activity_logger"].rows
    ]
    nm = [
        {"title": n.get("title"), "severity": n.get("severity")}
        for n in hass.data[DOMAIN]["notification_manager"].notes
    ]
    zone = ctx.zone
    pred = ctx.pred
    ex = ctx.ex
    carrier = ctx.S._STRATEGY_BY_PLATFORM.get("ha_carrier")
    state = {
        "last_emitted_range": {
            k: list(v) if v is not None else None
            for k, v in sorted(ctx.coord._last_emitted_range.items())
        },
        "zone_last_s1_write": {
            k: [v[0], v[1]] for k, v in sorted(ctx.coord._zone_last_s1_write.items())
        },
        "nudge_restore_timers": sorted(arr._nudge_restore_timers),
        "nudge_in_flight": sorted(arr._nudge_in_flight),
        "nudge_pre_preset": dict(sorted(arr._nudge_pre_preset.items())),
        "nudge_tokens": sorted(getattr(arr, "_nudge_excursion_tokens", {})),
        "compromise_tokens": sorted(getattr(arr, "_compromise_excursion_tokens", {})),
        "compromise_timers": sorted(arr._compromise_timers),
        "compromise_active": {k: v for k, v in sorted(arr._compromise_active.items())},
        "override_active": {k: v for k, v in sorted(arr._override_active.items())},
        "grace_timers": sorted(arr._grace_timers),
        "reset_timers": sorted(arr._reset_timers),
        "verify_tasks": sorted(arr._verify_tasks),
        "excursion_rows": {z: t.kind.value for z, t in sorted(ex._rows.items())},
        "banking_tokens": sorted(getattr(pred, "_banking_excursion_tokens", {}) or {}),
        "preheat_tokens": sorted(getattr(pred, "_preheat_excursion_tokens", {}) or {}),
        "pre_conditioning_zones": sorted(getattr(pred, "_pre_conditioning_zones", set()) or set()),
        "egress_paused": sorted(getattr(ctx.egress, "_paused_by_egress", {}) or {}),
        "egress_tokens": sorted(getattr(ctx.egress, "_egress_excursion_tokens", {}) or {}),
        "ramp_state": getattr(zone, "ramp_state", None),
        "carrier_last_sent": (
            {k: {vk: vv[0] for vk, vv in v.items()} for k, v in carrier._last_sent.items()}
            if carrier is not None else None
        ),
    }
    return _norm({
        "exc": ctx.exc,
        "calls": ctx.calls,
        "climate_write": cw,
        "db_rows_other": other_rows,
        "dao": ctx.db.dao,
        "activity": act,
        "nm": nm,
        "suppression": supp,
        "timers": ctx.timers,
        "state": state,
    })


async def _run(ctx, coro_fn):
    try:
        await coro_fn()
    except Exception as exc:  # noqa: BLE001 — RECORDED (part of the oracle), never hidden
        ctx.exc = type(exc).__name__
    await _drain(ctx.hass)


# --------------------------------------------------------------------------
# Scenarios — one per write site (enclosing production method driven)
# --------------------------------------------------------------------------


async def sc_S1(ctx):
    """A1 — S1 preset writer `hvac.py` `_apply_house_state_presets`
    (`hold_preset` -> resume-then-pin on a manual zone)."""
    c = ctx.coord
    c._house_state = "home_day"
    c._zone_intelligence_enabled = False
    z = ctx.zone
    z.preset_mode = "manual"
    for other in ("zone_2", "zone_3"):
        c.zone_manager.zones[other].preset_mode = "home"
    if ctx.variant == "skipped":
        ctx.set_entity(preset_mode="home", hold_activity="home")
        ctx.seed_last_sent("home")
    else:
        ctx.set_entity(preset_mode="manual", hold_activity="manual")
    if ctx.variant == "deferred":
        # S1 only consults the gate for its defer-reason set.
        c._house_state = "home_day"
        c._last_house_state_change = None
    ctx.defer_gate()
    await _run(ctx, c._apply_house_state_presets)


async def sc_B1(ctx):
    """A2 — B1 heat_cool enforcer `hvac.py` `_apply_house_state_presets`."""
    c = ctx.coord
    c._house_state = "home_day"
    c._zone_intelligence_enabled = False
    for zid in ("zone_1", "zone_2", "zone_3"):
        c.zone_manager.zones[zid].preset_mode = "home"
    z = ctx.zone
    z.hvac_mode = "cool"
    ctx.set_entity(preset_mode="home", hold_activity="home", state="cool")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, c._apply_house_state_presets)


async def sc_S10(ctx):
    """A13 — S10 DPM apply `hvac.py` `_async_apply_preset_overrides`."""
    c = ctx.coord
    c._guest_mode_actuation_enabled = True
    c._house_state = "home_day"
    DOMAIN = ctx.mods["const"].DOMAIN
    ec = types.SimpleNamespace(_dynamic_preset_overrides={})
    ctx.hass.data[DOMAIN]["coordinator_manager"] = types.SimpleNamespace(
        coordinators={"energy": ec},
    )
    for zid in ("zone_2", "zone_3"):
        c._last_emitted_range[zid] = (0.0, 0.0)
    ctx.set_entity(preset_mode="home", hold_activity="home")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, c._async_apply_preset_overrides)


def _episode(ctx):
    arr = ctx.arr
    arr._arrest_gen = {}
    return None


async def sc_S3(ctx):
    """A3 — S3 arrester compromise `_apply_compromise`."""
    arr = ctx.arr
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=72.0, low=68.0)
    ctx.seed_last_sent("manual")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._apply_compromise(
        ctx.zone, "home", 74.0, 68.0, 76.0, 68.0,
    ))


async def sc_S4(ctx):
    """A4 — B4 mode + S4 preset `_revert_override` (named original preset,
    drifted mode so B4 fires too)."""
    arr = ctx.arr
    z = ctx.zone
    z.hvac_mode = "cool"
    ctx.set_entity(preset_mode="manual", hold_activity="manual", state="cool")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._revert_override(z, "home"))


async def sc_S4_token(ctx):
    """A4 — S4 with a live compromise token whose snapshot is NAMED."""
    arr = ctx.arr
    z = ctx.zone
    z.hvac_mode = "heat_cool"
    ctx.set_entity(preset_mode="sleep", hold_activity="sleep")
    tok = await ctx.ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT,
        kind=ctx.ex.EXCURSION_KIND.COMPROMISE, excursion_low=68.0,
        excursion_high=74.0, duration_s=900, site="S3_compromise",
    )
    arr._compromise_excursion_tokens[ZONE] = tok
    ctx.set_entity(preset_mode="manual", hold_activity="manual")
    ctx.seed_last_sent("sleep")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._revert_override(z, "home"))


async def sc_B5(ctx):
    """A5 — B5 AC reset OFF `_perform_ac_reset`."""
    arr = ctx.arr
    z = ctx.zone
    z.hvac_mode = "heat_cool"
    ctx.set_entity(preset_mode="home", hold_activity="home")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._perform_ac_reset(z))


async def sc_B6_B7_reset_preset(ctx):
    """A5 — B6 restore, B7 retries, and the verify-success preset restore
    (`_restore_after_reset` + its `_verify_restore` closure). The device model
    applies mode writes so the SUCCESS branch (preset restore) is reached;
    under `failed_raise` / `unavailable` the retry path runs instead."""
    arr = ctx.arr
    z = ctx.zone
    z.hvac_mode = "off"
    ctx.apply_modes = True
    ctx.set_entity(preset_mode="manual", hold_activity="manual", state="off")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._restore_after_reset(z, "cool", original_preset="home"))


async def sc_B7_retry(ctx):
    """A5 — B7 retry path: the device does NOT apply the mode write, so the
    verify loop retries twice and then fails."""
    arr = ctx.arr
    z = ctx.zone
    z.hvac_mode = "off"
    ctx.set_entity(preset_mode="home", hold_activity="home", state="off")
    ctx.seed_last_sent("home")
    await _run(ctx, lambda: arr._restore_after_reset(z, "cool", original_preset="home"))


async def sc_S5(ctx):
    """A6 — S5 soft-nudge start `_perform_soft_nudge`."""
    arr = ctx.arr
    z = ctx.zone
    ctx.set_entity(preset_mode="sleep", hold_activity="sleep")
    ctx.seed_last_sent("sleep")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._perform_soft_nudge(z, 2.5))


async def sc_S6S7_named(ctx):
    """A7 — S7 preset restore (named snapshot, S6 dropped)."""
    arr = ctx.arr
    z = ctx.zone
    ctx.set_entity(preset_mode="sleep", hold_activity="sleep")
    tok = await ctx.ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ctx.ex.EXCURSION_KIND.NUDGE,
        excursion_low=68.0, excursion_high=77.5, duration_s=120, site="S5_nudge_start",
    )
    arr._nudge_excursion_tokens[ZONE] = tok
    arr._nudge_pre_preset[ZONE] = "sleep"
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=77.5)
    ctx.seed_last_sent("sleep")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._restore_after_nudge(z, 76.0))


async def sc_S6S7_manual(ctx):
    """A7 — S6 raw setpoint restore + S7 pin (HUMAN_MANUAL `manual` snapshot)."""
    arr = ctx.arr
    z = ctx.zone
    ctx.set_entity(preset_mode="manual", hold_activity="manual")
    tok = await ctx.ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ctx.ex.EXCURSION_KIND.NUDGE,
        excursion_low=68.0, excursion_high=77.5, duration_s=120, site="S5_nudge_start",
    )
    arr._nudge_excursion_tokens[ZONE] = tok
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=77.5)
    ctx.seed_last_sent("manual")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._restore_after_nudge(z, 76.0))


async def sc_S6_person(ctx):
    """A7 — the INFO-1 person restore (`hvac_override.py` S6 person path):
    a person-protected zone with a recorded reference -> their own setpoints."""
    arr = ctx.arr
    z = ctx.zone
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=75.0, low=69.0)
    arr._nudge_ref_map()[ZONE] = {"arrival": False, "high": 75.0, "low": 69.0}
    arr._corrective_writes_suppressed = lambda zone_id=None: True
    ctx.seed_last_sent("manual")
    ctx.defer_gate()
    await _run(ctx, lambda: arr._restore_after_nudge(z, 76.0))


async def sc_S8(ctx):
    """A8 — S8 cancel-nudge setpoint + preset `cancel_nudge` (manual snapshot
    -> both halves)."""
    arr = ctx.arr
    ctx.db._in_flight[ZONE] = 76.0
    ctx.set_entity(preset_mode="manual", hold_activity="manual")
    tok = await ctx.ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ctx.ex.EXCURSION_KIND.NUDGE,
        excursion_low=68.0, excursion_high=77.5, duration_s=120, site="S5_nudge_start",
    )
    tok.pre_preset = "manual"
    arr._nudge_excursion_tokens[ZONE] = tok
    ctx.seed_last_sent("manual")
    ctx.defer_gate()
    await _run(ctx, lambda: arr.cancel_nudge(ZONE))


async def sc_S8_named(ctx):
    """A8 — S8 cancel-nudge with a NAMED snapshot (preset half only)."""
    arr = ctx.arr
    ctx.db._in_flight[ZONE] = 76.0
    ctx.set_entity(preset_mode="home", hold_activity="home")
    tok = await ctx.ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ctx.ex.EXCURSION_KIND.NUDGE,
        excursion_low=68.0, excursion_high=77.5, duration_s=120, site="S5_nudge_start",
    )
    arr._nudge_excursion_tokens[ZONE] = tok
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=77.5)
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: arr.cancel_nudge(ZONE))


async def sc_S9(ctx):
    """A9 — S9 boot ramp audit restore (manual snapshot -> setpoint + preset)."""
    arr = ctx.arr
    ctx.db._in_flight[ZONE] = 76.0
    ctx.db._ex_rows = [{"zone_id": ZONE, "kind": "nudge", "pre_preset": "manual"}]
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=77.5)
    ctx.seed_last_sent("manual")
    ctx.defer_gate()
    await _run(ctx, arr.async_startup_ramp_audit)


async def sc_S9_named(ctx):
    """A9 — S9 boot ramp audit restore, NAMED snapshot (preset only)."""
    arr = ctx.arr
    ctx.db._in_flight[ZONE] = 76.0
    ctx.db._ex_rows = [{"zone_id": ZONE, "kind": "nudge", "pre_preset": "sleep"}]
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=77.5)
    ctx.seed_last_sent("sleep")
    ctx.defer_gate()
    await _run(ctx, arr.async_startup_ramp_audit)


async def sc_A10_auto_return(ctx):
    """A10 — lease-expiry auto-return `hvac_excursion._auto_return` via the
    real sweep: a PREHEAT row with a NAMED snapshot outlives its lease."""
    ex = ctx.ex
    ctx.set_entity(preset_mode="sleep", hold_activity="sleep")
    tok = await ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ex.EXCURSION_KIND.PREHEAT,
        excursion_low=70.0, excursion_high=76.0, duration_s=60, site="S13_pre_heat",
    )
    tok.started_ts -= 3600  # well past duration + EXCURSION_LEASE_SLACK_S
    ctx.set_entity(preset_mode="manual", hold_activity="manual")
    ctx.seed_last_sent("sleep")
    ctx.defer_gate()
    await _run(ctx, lambda: ex._auto_release_sweep(ctx.coord))


async def sc_A14_boot_audit(ctx):
    """A14 + A10 — restart scenario (a): boot-audit rehydrate. A persisted
    NUDGE row (named snapshot) fires the A14 preset restore; a persisted
    BANKING row (named snapshot) runs `_auto_return` (A10); a PREHEAT row is
    rehydrated into the registry."""
    ex = ctx.ex
    now_iso = datetime.now(timezone.utc).isoformat()
    ctx.db._ex_rows = [
        {"zone_id": ZONE, "kind": "nudge", "pre_preset": "sleep",
         "excursion_id": "nudge:zone_1:1", "started_ts": now_iso},
        {"zone_id": "zone_2", "kind": "banking", "pre_preset": "home",
         "excursion_id": "banking:zone_2:1", "started_ts": now_iso},
        {"zone_id": "zone_3", "kind": "preheat", "pre_preset": "home",
         "excursion_id": "preheat:zone_3:1", "started_ts": now_iso,
         "duration_s": 600},
    ]
    ctx.set_entity(preset_mode="manual", hold_activity="manual")
    H.set_climate(ctx.hass, "climate.test_zone_2", preset_mode="manual", hold_activity="manual")
    ctx.seed_last_sent("sleep")
    ctx.defer_gate()
    await _run(ctx, lambda: ex.async_startup_excursion_audit(ctx.hass, ctx.coord))


async def sc_reload_mid_borrow(ctx):
    """Restart/reload scenario (b): a room reload mid-borrow. A BANKING borrow
    is live, the zone's only room is transient (loading) for longer than the
    borrow's lease, and the lease-slack sweep closes the row through
    `_auto_return` (A10) with its named snapshot."""
    ex = ctx.ex
    ctx.set_entity(preset_mode="home", hold_activity="home")
    tok = await ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ex.EXCURSION_KIND.BANKING,
        excursion_low=68.0, excursion_high=73.0, duration_s=None, site="S12_pre_cool",
    )
    ctx.pred._banking_excursion_tokens = {ZONE: tok}
    # The room coordinator is reloading: the zone manager sees a transient room.
    zm = ctx.coord.zone_manager
    tb = getattr(zm, "_transient_since", None)
    if isinstance(tb, dict):
        tb["room_reloading"] = datetime.now(timezone.utc)
    tok.started_ts -= 3 * 86400  # past EXCURSION_LEASE_MAX_S
    ctx.set_entity(preset_mode="manual", hold_activity="manual")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: ex._auto_release_sweep(ctx.coord))


async def _bank(ctx, snap):
    ex = ctx.ex
    ctx.set_entity(preset_mode=snap, hold_activity=snap)
    tok = await ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ex.EXCURSION_KIND.BANKING,
        duration_s=None, site="S12_pre_cool",
    )
    ctx.pred._banking_excursion_tokens = {ZONE: tok}
    ctx.coord._last_emitted_range[ZONE] = (68.0, 76.0)
    return tok


async def sc_S11_named(ctx):
    """A11 — S11 banking release, NAMED snapshot (preset half)."""
    await _bank(ctx, "home")
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=73.0)
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: ctx.pred._release_banked_zones({ZONE}))


async def sc_S11_manual(ctx):
    """A11 — S11 banking release, HUMAN_MANUAL snapshot (setpoint half)."""
    await _bank(ctx, "manual")
    ctx.set_entity(preset_mode="manual", hold_activity="manual", high=73.0)
    ctx.seed_last_sent("manual")
    ctx.defer_gate()
    await _run(ctx, lambda: ctx.pred._release_banked_zones({ZONE}))


async def sc_S12(ctx):
    """A11 — S12 pre-cool `_execute_zone_pre_cool`."""
    ctx.set_entity(preset_mode="home", hold_activity="home")
    ctx.coord._last_emitted_range[ZONE] = (68.0, 76.0)
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: ctx.pred._execute_zone_pre_cool(ctx.zone, -3.0, "solar_banking"))


async def sc_S13_start(ctx):
    """A11 — S13 pre-heat start `_execute_pre_heat`."""
    for zid in ("zone_2", "zone_3"):
        zz = ctx.coord.zone_manager.zones[zid]
        zz.room_conditions = []
    ctx.zone.room_conditions = [
        types.SimpleNamespace(occupied=True, hvac_occupied=True, room_name="Living Room"),
    ]
    ctx.set_entity(preset_mode="home", hold_activity="home")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, ctx.pred._execute_pre_heat)


async def _preheat_tok(ctx, snap):
    ex = ctx.ex
    ctx.set_entity(preset_mode=snap, hold_activity=snap, high=76.0, low=68.0)
    tok = await ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ex.EXCURSION_KIND.PREHEAT,
        excursion_low=70.0, excursion_high=76.0, duration_s=600, site="S13_pre_heat",
    )
    ctx.pred._preheat_excursion_tokens = {ZONE: tok}
    ctx.pred._preheat_return_timers = {ZONE: (lambda: None)}
    ctx.pred._pre_conditioning_zones.add(ZONE)
    ctx.coord._last_emitted_range[ZONE] = (60.0, 90.0)
    return tok


async def sc_S13_return_named(ctx):
    """A11 — S13 pre-heat return, NAMED snapshot (preset half)."""
    await _preheat_tok(ctx, "home")
    ctx.set_entity(preset_mode="manual", hold_activity="manual", low=70.0)
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: ctx.pred._return_preheat(ZONE))


async def sc_S13_return_manual(ctx):
    """A11 — S13 pre-heat return, HUMAN_MANUAL snapshot (setpoint half)."""
    await _preheat_tok(ctx, "manual")
    ctx.set_entity(preset_mode="manual", hold_activity="manual", low=70.0)
    ctx.seed_last_sent("manual")
    ctx.defer_gate()
    await _run(ctx, lambda: ctx.pred._return_preheat(ZONE))


async def sc_B2(ctx):
    """A12 — B2 egress pause `_engage_pause`."""
    ctx.set_entity(preset_mode="home", hold_activity="home")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    em = ctx.egress
    await _run(ctx, lambda: em._engage_pause(
        zone_id=ZONE, zone_state=ctx.zone, triggered_room="Living Room",
        now=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
    ))


async def sc_B3_resume(ctx):
    """A12 — B3 mode + egress preset resume `_engage_resume`."""
    em = ctx.egress
    ctx.set_entity(preset_mode="home", hold_activity="home")
    tok = await ctx.ex.begin_excursion(
        ctx.hass, zone_id=ZONE, entity_id=ENT, kind=ctx.ex.EXCURSION_KIND.EGRESS_PAUSE,
        duration_s=None, site="S15_egress_pause",
    )
    em._egress_excursion_tokens = {ZONE: tok}
    em._paused_by_egress[ZONE] = {
        "mode": "heat_cool", "preset": "home",
        "paused_at": datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
        "triggered_by_room": "Living Room", "thermostat": ENT,
    }
    ctx.set_entity(preset_mode="manual", hold_activity="manual", state="off")
    ctx.seed_last_sent("home")
    ctx.defer_gate()
    await _run(ctx, lambda: em._engage_resume(
        zone_id=ZONE, zone_state=ctx.zone,
        now=datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc),
    ))


SCENARIOS = {
    "A1_S1": sc_S1,
    "A2_B1": sc_B1,
    "A3_S3": sc_S3,
    "A4_B4_S4": sc_S4,
    "A4_S4_token": sc_S4_token,
    "A5_B5": sc_B5,
    "A5_B6_B7_preset": sc_B6_B7_reset_preset,
    "A5_B7_retry": sc_B7_retry,
    "A6_S5": sc_S5,
    "A7_S7_named": sc_S6S7_named,
    "A7_S6_S7_manual": sc_S6S7_manual,
    "A7_S6_person": sc_S6_person,
    "A8_S8_manual": sc_S8,
    "A8_S8_named": sc_S8_named,
    "A9_S9_manual": sc_S9,
    "A9_S9_named": sc_S9_named,
    "A10_auto_return": sc_A10_auto_return,
    "A11_S11_named": sc_S11_named,
    "A11_S11_manual": sc_S11_manual,
    "A11_S12": sc_S12,
    "A11_S13_start": sc_S13_start,
    "A11_S13_return_named": sc_S13_return_named,
    "A11_S13_return_manual": sc_S13_return_manual,
    "A12_B2": sc_B2,
    "A12_B3_resume": sc_B3_resume,
    "A13_S10": sc_S10,
    "RESTART_a_A14_boot_audit": sc_A14_boot_audit,
    "RELOAD_b_mid_borrow": sc_reload_mid_borrow,
}

CASES = [(s, v) for s in SCENARIOS for v in VARIANTS]


async def _capture(mods, monkeypatch, scenario, variant, registry):
    ctx = _install(mods, monkeypatch, variant=variant, registry=registry)
    await SCENARIOS[scenario](ctx)
    obs = _observe(ctx)
    ctx.ex._test_clear_leases()
    return obs


async def drive_site(monkeypatch, scenario: str, variant: str = "applied",
                     registry: str = "carrier") -> dict:
    """Shared BEHAVIOURAL driver for other test files (W1-C P1 converted
    several source-grep anchors to drive the enclosing production method
    through these scenarios). Shim state is snapshotted and RESTORED."""
    baseline = H.snapshot_shims()
    try:
        mods = H.load_real()
        return await _capture(mods, monkeypatch, scenario, variant, registry)
    finally:
        H.restore_shims(baseline)


class site_ctx:
    """Async context manager: a fully installed scenario context (real
    modules, recording services, fixture registry) for a converted test
    that needs a custom drive. Shims are restored on exit."""

    def __init__(self, monkeypatch, variant: str = "applied", registry: str = "carrier"):
        self._mp = monkeypatch
        self._variant = variant
        self._registry = registry

    async def __aenter__(self):
        self._baseline = H.snapshot_shims()
        mods = H.load_real()
        self.ctx = _install(mods, self._mp, variant=self._variant, registry=self._registry)
        return self.ctx

    async def __aexit__(self, *exc):
        try:
            await _drain(self.ctx.hass)
            self.ctx.ex._test_clear_leases()
        finally:
            H.restore_shims(self._baseline)
        return False


def climate_calls(obs: dict, service: str) -> list:
    return [c["data"] for c in obs["calls"] if c["domain"] == "climate" and c["service"] == service]


def _load_goldens() -> dict:
    if not GOLDEN_PATH.exists():
        return {}
    return json.loads(GOLDEN_PATH.read_text())


_GOLDENS = _load_goldens()
_RECORDED: dict = {}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,variant", CASES, ids=[f"{s}-{v}" for s, v in CASES])
async def test_carrier_byte_identity(mods, monkeypatch, scenario, variant):
    """Carrier (registry platform `ha_carrier`): observation == pre-w1c-p1 golden."""
    key = f"{scenario}|{variant}"
    obs = await _capture(mods, monkeypatch, scenario, variant, "carrier")
    if RECORD:
        _RECORDED[key] = obs
        data = _load_goldens()
        data[key] = obs
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        return
    assert key in _GOLDENS, f"no golden for {key} (goldens are never regenerated on the P1 branch)"
    assert _cmp_form(obs) == _cmp_form(_GOLDENS[key])


def _cmp_form(obs: dict) -> dict:
    """Comparator normalisation (the golden FILE is never edited): an
    uncached Carrier strategy instance (`None`) and a cached one with an
    empty `last_sent` (`{}`) are the same state — "URA has recorded no
    preset for any entity". P1 routes every site through `strategy_for`,
    which caches the instance on first use; pre-P1 only S1 did."""
    o = json.loads(json.dumps(obs))
    if o["state"].get("carrier_last_sent") is None:
        o["state"]["carrier_last_sent"] = {}
    return o


def _without_carrier_record(obs: dict) -> dict:
    """A registry miss resolves an UNCACHED GenericStrategy per call
    (`hvac_strategy.strategy_for`, by design) — its `_last_sent` is never the
    cached Carrier instance's. Everything else must be identical."""
    o = json.loads(json.dumps(obs))
    o["state"].pop("carrier_last_sent", None)
    return o


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,variant", CASES, ids=[f"{s}-{v}" for s, v in CASES])
async def test_registry_miss_generic_identical_to_carrier_golden(mods, monkeypatch, scenario, variant):
    """N2: a registry-miss entity (-> Generic) driven through every A-site
    makes calls / rows / suppression / state identical to the Carrier golden."""
    if variant == "skipped":
        pytest.skip("the skipped variant seeds the CARRIER instance's last_sent; "
                    "a registry miss has no cached instance to seed")
    key = f"{scenario}|{variant}"
    obs = await _capture(mods, monkeypatch, scenario, variant, "miss")
    golden = _RECORDED.get(key) if RECORD else _GOLDENS.get(key)
    assert golden is not None, f"no golden for {key}"
    assert _without_carrier_record(obs) == _without_carrier_record(golden)
