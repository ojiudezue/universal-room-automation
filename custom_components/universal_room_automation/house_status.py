"""Read-only house status answers (NM-INBOUND-HOUSE-QUERIES-1, D1).

Pure read functions over ``hass`` + coordinators. Each returns a
``StatusResult`` (structured fields with a ``source`` per field so a tool
caller can cite) and ``render`` turns one into a short text reply.

Consumers: NM diag text menu (``notification_manager._process_inbound_reply``).
Named future consumer: the OC agent (as tools). No trust decision reads this
module.

Invariant I2 (plan §5): nothing here actuates or persists. Getters it calls
may write RAM caches (e.g. ``solar_production_w`` LKG stamps), which is
allowed. Every read is guarded: a missing coordinator or a raising getter
yields the value ``unknown`` with note ``source unavailable``; a function
never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import logging
from typing import Any

from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_ROOM

_LOGGER = logging.getLogger(__name__)

# Rung 1 knobs (plan §8). Display-only thresholds.
# AC "running" when the zone's ac_load_sensor reads above this (kW).
HOUSE_STATUS_AC_RUNNING_KW = 0.3
# A field whose source entity is older than this renders "(N min old)".
HOUSE_STATUS_STALE_S = 300
# Garage remote-lockout locks, read directly (plan §12 Q2 default: NOT in the
# security coordinator lock list, so the SC lock check never acts on them).
# Empty tuple -> garage omits lockouts.
HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES: tuple[str, ...] = (
    "lock.konnected_f0f5bd523b00_lock",
    "lock.ratgdov25i_dbfe2a_lock_remotes",
)

UNKNOWN = "unknown"
SOURCE_UNAVAILABLE = "source unavailable"


@dataclass(frozen=True)
class Field:
    """One labelled value in an answer."""

    label: str
    value: str
    unit: str = ""
    source: str = ""
    age_s: float | None = None
    note: str = ""
    problem: bool = False


@dataclass(frozen=True)
class StatusResult:
    """One answer: item key, time, fields, problem count."""

    item: str
    as_of: datetime
    fields: list[Field] = field(default_factory=list)
    problems: int = 0


def _result(item: str, fields: list[Field]) -> StatusResult:
    return StatusResult(
        item=item,
        as_of=dt_util.utcnow(),
        fields=list(fields),
        problems=sum(1 for f in fields if f.problem),
    )


def _manager(hass) -> Any:
    try:
        return hass.data.get(DOMAIN, {}).get("coordinator_manager")
    except Exception:  # noqa: BLE001
        return None


def _coord(hass, key: str) -> Any:
    mgr = _manager(hass)
    if mgr is None:
        return None
    try:
        return mgr.coordinators.get(key)
    except Exception:  # noqa: BLE001
        return None


def _age_s(state) -> float | None:
    try:
        return (dt_util.utcnow() - state.last_updated).total_seconds()
    except Exception:  # noqa: BLE001
        return None


def _state_field(hass, entity_id: str, label: str, bad: tuple[str, ...]) -> Field:
    """Field for one HA entity, verbatim state; ``bad`` states are problems."""
    try:
        st = hass.states.get(entity_id)
    except Exception:  # noqa: BLE001
        st = None
    if st is None:
        return Field(label, "not found", source=entity_id, note=SOURCE_UNAVAILABLE, problem=True)
    value = str(st.state)
    return Field(
        label, value, source=entity_id, age_s=_age_s(st),
        problem=value in bad or value in ("unavailable", "unknown"),
    )


def _label(hass, entity_id: str) -> str:
    try:
        st = hass.states.get(entity_id)
        name = st.attributes.get("friendly_name") if st is not None else None
        if name:
            return str(name)
    except Exception:  # noqa: BLE001
        pass
    return entity_id.split(".", 1)[-1].replace("_", " ")


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def doors(hass) -> StatusResult:
    """Lock states for the security coordinator's configured lock list."""
    sc = _coord(hass, "security")
    if sc is None:
        return _result("doors", [Field("locks", UNKNOWN, source="security coordinator", note=SOURCE_UNAVAILABLE, problem=True)])
    try:
        ids = list(getattr(sc, "_lock_entities", None) or [])
    except Exception:  # noqa: BLE001
        ids = []
    if not ids:
        return _result("doors", [Field("locks", "none configured", source="security_lock_entities")])
    # SC-LOCK-SWEEP-EXCLUDE-1: a never-auto-lock (interior) lock is listed
    # with a note; reading unlocked is not a problem, jammed / offline is.
    try:
        excluded = set(sc._sweep_excluded())
    except Exception:  # noqa: BLE001
        excluded = set()
    fields = []
    for eid in ids:
        if eid in excluded:
            f = _state_field(hass, eid, _label(hass, eid), bad=("jammed",))
            fields.append(replace(f, note=f.note or "not auto-locked"))
        else:
            fields.append(_state_field(
                hass, eid, _label(hass, eid), bad=("unlocked", "open", "jammed", "unlocking")
            ))
    return _result("doors", fields)


def garage(hass) -> StatusResult:
    """Garage covers (SC list) plus remote-lockout locks (read directly)."""
    fields: list[Field] = []
    sc = _coord(hass, "security")
    if sc is None:
        fields.append(Field("doors", UNKNOWN, source="security coordinator", note=SOURCE_UNAVAILABLE, problem=True))
    else:
        try:
            ids = list(getattr(sc, "_garage_entities", None) or [])
        except Exception:  # noqa: BLE001
            ids = []
        if not ids:
            fields.append(Field("doors", "none configured", source="security_garage_entities"))
        for eid in ids:
            fields.append(_state_field(hass, eid, _label(hass, eid), bad=("open", "opening")))
    for eid in HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES:
        f = _state_field(hass, eid, "remotes locked out: " + _label(hass, eid), bad=())
        if f.value == "not found":
            f = Field("lockout", "not found", source=eid, note=SOURCE_UNAVAILABLE)
        else:
            # Entity state only; never claims the keypad is blocked.
            f = Field(f.label, "on" if f.value == "locked" else ("off" if f.value == "unlocked" else f.value),
                      source=eid, age_s=f.age_s, problem=f.value in ("unavailable", "unknown"))
        fields.append(f)
    return _result("garage", fields)


def who(hass) -> StatusResult:
    """House state, census estimate, per-person location."""
    fields: list[Field] = []
    mgr = _manager(hass)
    hs = UNKNOWN
    if mgr is not None:
        try:
            raw = mgr.house_state
            hs = str(getattr(raw, "value", raw)) if raw is not None else UNKNOWN
        except Exception:  # noqa: BLE001
            hs = UNKNOWN
    fields.append(Field("house", hs, source="CoordinatorManager.house_state",
                        note="" if hs != UNKNOWN else SOURCE_UNAVAILABLE))
    pres = _coord(hass, "presence")
    census = UNKNOWN
    if pres is not None:
        try:
            c = pres.census_count
            census = f"~{int(c)} (estimate)" if c is not None else UNKNOWN
        except Exception:  # noqa: BLE001
            census = UNKNOWN
    fields.append(Field("people", census, source="PresenceCoordinator.census_count"))
    pc = None
    try:
        pc = hass.data.get(DOMAIN, {}).get("person_coordinator")
    except Exception:  # noqa: BLE001
        pc = None
    if pc is None:
        fields.append(Field("persons", UNKNOWN, source="person_coordinator", note=SOURCE_UNAVAILABLE))
        return _result("who", fields)
    try:
        from .person_coordinator import person_state_for_trust
    except Exception:  # noqa: BLE001

        def person_state_for_trust(hass, eid):  # raw-state fallback
            st = hass.states.get(eid)
            return st.state if st is not None else None
    try:
        names = list((pc.data or {}).keys())
    except Exception:  # noqa: BLE001
        names = []
    for name in names:
        try:
            loc = pc.get_person_location(name)
        except Exception:  # noqa: BLE001
            loc = UNKNOWN
        state = None
        try:
            eid = pc._find_person_entity(name)
            state = person_state_for_trust(hass, eid) if eid else None
        except Exception:  # noqa: BLE001
            state = None
        value = str(state) if state else UNKNOWN
        if state == "home" and loc and loc != UNKNOWN:
            value = f"home ({loc})"
        fields.append(Field(str(name), value, source="person_state_for_trust+get_person_location"))
    return _result("who", fields)


def _load_kw(hvac, zone) -> float | None:
    """kW from the zone's ac_load_sensor via the HVAC arrester reader
    (W->kW, kWh rejection, staleness; warn=False so no rate-limit stamp)."""
    arrester = getattr(hvac, "_override_arrester", None)
    if arrester is None or not getattr(zone, "ac_load_sensor", ""):
        return None
    try:
        return arrester._read_kwh_rate(zone, dt_util.now(), warn=False)
    except Exception:  # noqa: BLE001
        return None


def hvac(hass) -> StatusResult:
    """Per HVAC zone: temperature, set range, reported preset, running."""
    hv = _coord(hass, "hvac")
    if hv is None:
        return _result("hvac", [Field("zones", UNKNOWN, source="hvac coordinator", note=SOURCE_UNAVAILABLE, problem=True)])
    try:
        zones = dict(hv.zone_manager.zones)
    except Exception:  # noqa: BLE001
        return _result("hvac", [Field("zones", UNKNOWN, source="ZoneManager.zones", note=SOURCE_UNAVAILABLE, problem=True)])
    fields: list[Field] = []
    for zid, z in zones.items():
        name = getattr(z, "zone_name", None) or str(zid)
        temp = getattr(z, "current_temperature", None)
        lo = getattr(z, "target_temp_low", None)
        hi = getattr(z, "target_temp_high", None)
        preset = getattr(z, "preset_mode", None)
        parts = [f"{temp:.0f}°" if isinstance(temp, (int, float)) else "temp ?"]
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            parts.append(f"set {lo:.0f}-{hi:.0f}")
        parts.append(f"thermostat reports {preset}" if preset else "preset ?")
        if not getattr(z, "ac_load_sensor", ""):
            parts.append("running: not measured")
        else:
            kw = _load_kw(hv, z)
            if kw is None:
                parts.append("running: unknown")
            else:
                parts.append("running" if kw > HOUSE_STATUS_AC_RUNNING_KW else "idle")
        fields.append(Field(str(name), ", ".join(parts), source=f"ZoneState[{zid}]"))
    if not fields:
        fields.append(Field("zones", "none", source="ZoneManager.zones"))
    return _result("hvac", fields)


def energy(hass) -> StatusResult:
    """Battery SOC, solar now, grid now (W-normalized)."""
    ec = _coord(hass, "energy")
    bs = None
    if ec is not None:
        try:
            bs = ec.battery_strategy
        except Exception:  # noqa: BLE001
            bs = None
    if bs is None:
        return _result("energy", [Field("energy", UNKNOWN, source="energy coordinator", note=SOURCE_UNAVAILABLE, problem=True)])

    def _get(attr):
        try:
            return getattr(bs, attr)
        except Exception:  # noqa: BLE001
            return None

    fields: list[Field] = []
    soc = _get("battery_soc")
    fields.append(Field("battery", f"{soc:.0f}" if isinstance(soc, (int, float)) else UNKNOWN,
                        unit="%" if isinstance(soc, (int, float)) else "", source="BatteryStrategy.battery_soc"))
    solar = _get("solar_production_w")
    fields.append(Field("solar", f"{solar / 1000.0:.1f}" if isinstance(solar, (int, float)) else UNKNOWN,
                        unit="kW" if isinstance(solar, (int, float)) else "", source="BatteryStrategy.solar_production_w"))
    net = _get("net_power_w")
    age = None
    try:
        eid = bs._get_entity("net_power")
        st = hass.states.get(eid) if eid else None
        age = _age_s(st) if st is not None else None
    except Exception:  # noqa: BLE001
        age = None
    if isinstance(net, (int, float)):
        val = f"{'importing' if net >= 0 else 'exporting'} {abs(net) / 1000.0:.1f}"
        fields.append(Field("grid", val, unit="kW", source="BatteryStrategy.net_power_w", age_s=age))
    else:
        fields.append(Field("grid", UNKNOWN, source="BatteryStrategy.net_power_w"))
    return _result("energy", fields)


async def alerts(hass, nm) -> StatusResult:
    """NM alert state, unacked CRITICALs (age-capped), non-nominal anomalies."""
    fields: list[Field] = []
    try:
        state = nm.alert_state.value
    except Exception:  # noqa: BLE001
        state = UNKNOWN
    fields.append(Field("alert state", str(state), source="NotificationManager.alert_state",
                        problem=state not in ("idle", UNKNOWN)))
    database = None
    try:
        database = hass.data.get(DOMAIN, {}).get("database")
    except Exception:  # noqa: BLE001
        database = None
    if database is None:
        fields.append(Field("unacked criticals", UNKNOWN, source="database", note=SOURCE_UNAVAILABLE))
    else:
        try:
            rows = await database.get_active_criticals(limit=50)
            fresh = [r for r in rows if not nm._recovery_row_is_stale(r)]
            fields.append(Field("unacked criticals", str(len(fresh)), source="get_active_criticals",
                                problem=bool(fresh)))
            for r in fresh[:3]:
                fields.append(Field(f"  {r.get('hazard_type') or r.get('title') or 'alert'}",
                                    str(r.get("timestamp", ""))[:16], source="notification_log", problem=True))
        except Exception:  # noqa: BLE001
            fields.append(Field("unacked criticals", UNKNOWN, source="get_active_criticals", note=SOURCE_UNAVAILABLE))
    mgr = _manager(hass)
    coords: dict = {}
    if mgr is not None:
        try:
            coords = dict(mgr.coordinators)
        except Exception:  # noqa: BLE001
            coords = {}
    bad = []
    for cid, c in coords.items():
        det = getattr(c, "anomaly_detector", None)
        if det is None:
            continue
        try:
            s = det.get_sensor_state()
        except Exception:  # noqa: BLE001
            continue
        if s and s != "nominal":
            bad.append(Field(f"anomaly {cid}", str(s), source=f"{cid}.anomaly_detector", problem=s not in ("learning", "partial", "insufficient_data")))
    try:
        nm_anom = nm.anomaly_status
        if nm_anom and nm_anom != "nominal":
            bad.append(Field("anomaly notifications", str(nm_anom), source="NotificationManager.anomaly_status"))
    except Exception:  # noqa: BLE001
        pass
    fields.extend(bad)
    if not bad:
        fields.append(Field("anomalies", "all nominal", source="anomaly_detector.get_sensor_state"))
    return _result("alerts", fields)


def health(hass) -> StatusResult:
    """Unavailable entities per room (by unique_id) + URA repairs."""
    fields: list[Field] = []
    try:
        from homeassistant.helpers import entity_registry as er
        reg = er.async_get(hass)
        entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if (e.data or {}).get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
        ]
    except Exception:  # noqa: BLE001
        reg, entries = None, []
        fields.append(Field("rooms", UNKNOWN, source="entity registry", note=SOURCE_UNAVAILABLE, problem=True))
    reporting = 0
    for entry in entries:
        try:
            eid = reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_unavailable_entities")
        except Exception:  # noqa: BLE001
            eid = None
        st = hass.states.get(eid) if eid else None
        if st is None:
            continue
        reporting += 1
        try:
            n = int(float(st.state))
        except (TypeError, ValueError):
            continue
        if n > 0:
            act = st.attributes.get("actuator_count", 0) or 0
            fields.append(Field(str(entry.title), f"{n} unavailable ({act} actuators)", source=eid, problem=True))
    if entries:
        fields.append(Field("rooms reporting", f"{reporting}/{len(entries)}", source="*_unavailable_entities"))
    try:
        from homeassistant.helpers import issue_registry as ir
        issues = [k for k in ir.async_get(hass).issues if k[0] == DOMAIN]
        fields.append(Field("repairs", str(len(issues)), source="issue_registry", problem=bool(issues)))
    except Exception:  # noqa: BLE001
        fields.append(Field("repairs", UNKNOWN, source="issue_registry", note=SOURCE_UNAVAILABLE))
    return _result("health", fields)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _line(f: Field) -> str:
    val = f"{f.value}{(' ' + f.unit) if f.unit else ''}"
    if f.age_s is not None and f.age_s > HOUSE_STATUS_STALE_S:
        val += f" ({int(f.age_s // 60)} min old)"
    if f.note:
        val += f" [{f.note}]"
    return f"{'! ' if f.problem else ''}{f.label}: {val}"


def render(result: StatusResult, max_chars: int) -> str:
    """Short text: header + one line per field, problems first.

    Always multi-line (I3: an echoed reply can never equal a one-token
    command). Never exceeds ``max_chars``; truncation drops the tail and
    ends with ``…(more: <item>)``.
    """
    header = f"{result.item.capitalize()}" + (f" ({result.problems} need attention)" if result.problems else "")
    ordered = [f for f in result.fields if f.problem] + [f for f in result.fields if not f.problem]
    lines = [_line(f) for f in ordered] or ["no data"]
    suffix = f"…(more: {result.item})"
    out = header
    for i, ln in enumerate(lines):
        candidate = out + "\n" + ln
        remaining = len(lines) - i - 1
        budget = max_chars - (len(suffix) + 1 if remaining else 0)
        if len(candidate) > budget:
            room = max_chars - len(suffix) - 1
            if room < len(out):
                out = out[: max(0, room)]
            return out + "\n" + suffix
        out = candidate
    return out
