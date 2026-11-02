"""Tomorrow forecast + per-period pricing (EC-COST-AND-FORECAST-MATH-1 Build 2).

Pure helpers, no HA state. The EnergyCoordinator owns the I/O (weather
service, recorder statistics, URA DB) and calls these.

  D8  select_forecast_for_date / temp_feature  (date-keyed, no fallback)
  D9  hvac_zone_consumption                    (per-HVAC-zone AC + base)
  D3  net_bias / predict_net                   (Option A)
  D4  period_shares / representative_instants / price_net_kwh
                                               (per-period kWh shares x live
                                               TOU rates; INV-FC-2, INV-RATE-1)

Every rate is read from the TOU engine at call time; nothing here stores a
rate (INV-RATE-1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.util import dt as dt_util


# ---------------------------------------------------------------------------
# D8 — forecast entry for a LOCAL date
# ---------------------------------------------------------------------------

def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def select_forecast_for_date(
    forecasts: Iterable[Mapping[str, Any]] | None, target: date,
) -> tuple[float, float] | None:
    """(high, low) of the daily entry whose ``datetime`` falls on ``target``
    in LOCAL time, else None.

    Never index-based, never ``forecast[0]``, never the current temperature:
    a missing entry or a missing high/low returns None (the caller exposes
    ``missing_input``).
    """
    if not forecasts:
        return None
    for entry in forecasts:
        if not isinstance(entry, Mapping):
            continue
        raw = entry.get("datetime")
        parsed = dt_util.parse_datetime(raw) if isinstance(raw, str) else (
            raw if isinstance(raw, datetime) else None
        )
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        if dt_util.as_local(parsed).date() != target:
            continue
        high, low = _num(entry.get("temperature")), _num(entry.get("templow"))
        if high is None or low is None:
            return None
        return high, low
    return None


def temp_feature(high_low: tuple[float, float] | None) -> float | None:
    """(high + low) / 2: the proxy the v1/v2/hvac_zone fits were trained on
    (OWM daily entries carry no mean)."""
    if high_low is None:
        return None
    return (high_low[0] + high_low[1]) / 2.0


# ---------------------------------------------------------------------------
# D9 — per-HVAC-zone arm
# ---------------------------------------------------------------------------

def trailing_mean(
    series: Mapping[date, float], target: date, days: int,
) -> float | None:
    """Mean of ``series`` over the ``days`` local dates BEFORE ``target``."""
    vals = [series[target - timedelta(days=k)] for k in range(1, days + 1)
            if series.get(target - timedelta(days=k)) is not None]
    return sum(vals) / len(vals) if vals else None


def hvac_zone_consumption(
    consts: Mapping[str, Any],
    temp: float | None,
    indoor_means: list[float | None],
    base_nonhvac: float | None,
) -> float | None:
    """Σ_z [a_z + b_z·max(out − in_z, 0) + c_z·max(in_z − out, 0)] + base.

    ``indoor_means[z]`` = zone thermostat trailing mean (HVAC zones, never
    house-zone averages). Any missing input → None (no fallback).
    """
    zones = consts["zones"]
    if temp is None or base_nonhvac is None or len(indoor_means) != len(zones):
        return None
    total = 0.0
    for z, tin in zip(zones, indoor_means):
        if tin is None:
            return None
        total += (z["a"] + z["b_cool"] * max(temp - tin, 0.0)
                  + z["c_heat"] * max(tin - temp, 0.0))
    return total + base_nonhvac


# ---------------------------------------------------------------------------
# D3 — Option A net
# ---------------------------------------------------------------------------

def net_bias(rows: Iterable[Mapping[str, Any]], days: int) -> float:
    """Mean of (import − export) − (consumption − solar) over the newest
    ``days`` rows that carry all four values. 0 when ``days`` is 0 (kill
    switch) or no row qualifies."""
    if days <= 0:
        return 0.0
    gaps = []
    for r in rows:
        vals = [_num(r.get(k)) for k in
                ("import_kwh", "export_kwh", "consumption_kwh",
                 "solar_production_kwh")]
        if any(v is None for v in vals):
            continue
        imp, exp, cons, sol = vals
        gaps.append((r.get("date"), (imp - exp) - (cons - sol)))
    gaps.sort(key=lambda g: g[0] or "")
    use = [g for _, g in gaps[-days:]]
    return sum(use) / len(use) if use else 0.0


def predict_net(
    consumption: float | None, solar: float | None, bias: float,
) -> float | None:
    """Net grid kWh (import − export) = consumption − solar + bias."""
    if consumption is None or solar is None:
        return None
    return consumption - solar + bias


# ---------------------------------------------------------------------------
# D4 — per-period pricing
# ---------------------------------------------------------------------------

def period_shares(mix: Mapping[str, Mapping[str, float]], key: str) -> dict[str, float]:
    """{period: share} of ``key`` ('import_kwh' / 'export_kwh'); {} when the
    total is not positive."""
    total = sum(max(float(v.get(key, 0.0) or 0.0), 0.0) for v in mix.values())
    if total <= 0:
        return {}
    return {p: max(float(v.get(key, 0.0) or 0.0), 0.0) / total
            for p, v in mix.items()}


def _local_hours(day: date) -> list[datetime]:
    """The local wall-clock half-hour points of ``day`` (DST-aware: a day
    with 23 or 25 hours yields 23 or 25 points)."""
    tz = dt_util.get_default_time_zone()
    start = datetime.combine(day, time(0), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    out = []
    t = dt_util.as_utc(start) + timedelta(minutes=30)
    while t < dt_util.as_utc(end):
        out.append(dt_util.as_local(t))
        t += timedelta(hours=1)
    return out


def representative_instants(tou: Any, day: date) -> dict[str, datetime]:
    """First local hour-midpoint of ``day`` in each TOU period (engine's own
    schedule via ``_period_at``)."""
    out: dict[str, datetime] = {}
    for t in _local_hours(day):
        out.setdefault(tou._period_at(t), t)
    return out


def hour_weighted_rates(tou: Any, day: date) -> tuple[float, float]:
    """(import, export) $/kWh averaged over every local hour of ``day``.
    The fallback when history is too thin for a period mix — never an
    instant rate (INV-FC-2)."""
    hours = _local_hours(day)
    imp = sum(float(tou.get_effective_import_rate(t)) for t in hours) / len(hours)
    exp = sum(float(tou.get_export_rate(t)) for t in hours) / len(hours)
    return imp, exp


def price_net_kwh(
    net_kwh: float,
    mix: Mapping[str, Mapping[str, float]] | None,
    tou: Any,
    day: date,
    min_days: int,
    mix_days: int,
) -> tuple[float, dict[str, Any]]:
    """Cost of ``net_kwh`` (import − export) on local ``day``.

    Import (net > 0): Σ_p imp_share_p · net · eff_import_rate(t_p).
    Export (net < 0): Σ_p exp_share_p · net · export_rate(t_p) (a credit).
    t_p = the representative instant of period p on ``day``; a period with
    history but absent from ``day``'s schedule is priced at the day's
    hour-weighted rate. With fewer than ``min_days`` of mix, or no share on
    the needed side, the hour-weighted day rate is used. Rates are read
    live from the engine every call (INV-RATE-1).
    """
    imp_w, exp_w = hour_weighted_rates(tou, day)
    key = "import_kwh" if net_kwh >= 0 else "export_kwh"
    shares = (period_shares(mix, key) if mix and mix_days >= min_days else {})
    meta: dict[str, Any] = {
        "import_shares": period_shares(mix, "import_kwh") if mix else {},
        "export_shares": period_shares(mix, "export_kwh") if mix else {},
    }
    if not shares:
        rate = imp_w if net_kwh >= 0 else exp_w
        meta["rate_source"] = "hour_weighted_day"
        return net_kwh * rate, meta
    instants = representative_instants(tou, day)
    cost = 0.0
    for p, share in shares.items():
        t = instants.get(p)
        if t is None:
            rate = imp_w if net_kwh >= 0 else exp_w
        elif net_kwh >= 0:
            rate = float(tou.get_effective_import_rate(t))
        else:
            rate = float(tou.get_export_rate(t))
        cost += share * net_kwh * rate
    meta["rate_source"] = f"period_mix_{mix_days}d"
    return cost, meta


def bucket_period_mix(
    rows: Iterable[tuple[str, float | None, float | None, float]],
    tou: Any,
) -> tuple[dict[str, dict[str, float]], int]:
    """Bucket energy_history rows (naive-UTC ts, import kW, export kW, dt_h)
    into ``{period: {import_kwh, export_kwh}}`` by each row's LOCAL time and
    the engine's ``_period_at``. Returns (mix, distinct local days)."""
    mix: dict[str, dict[str, float]] = {}
    days: set[date] = set()
    for ts, imp_kw, exp_kw, dt_h in rows:
        parsed = dt_util.parse_datetime(ts) if isinstance(ts, str) else None
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        local = dt_util.as_local(parsed)
        days.add(local.date())
        b = mix.setdefault(tou._period_at(local),
                           {"import_kwh": 0.0, "export_kwh": 0.0})
        b["import_kwh"] += float(imp_kw or 0.0) * float(dt_h or 0.0)
        b["export_kwh"] += float(exp_kw or 0.0) * float(dt_h or 0.0)
    return mix, len(days)


def forecast_accuracy(
    rows: Iterable[Mapping[str, Any]], today: date, d3_arm: str,
) -> dict[str, dict[str, Any]]:
    """D5 per arm: ``mae_7d_kwh``, ``mae_30d_kwh``, ``bias_30d_kwh`` (mean
    of predicted − actual consumption, NMBE in kWh) over completed local
    target dates (< ``today``) with an actual. The D3 arm also carries
    ``net_mae_30d_kwh``, ``cost_mae_30d`` (vs energy_daily.net_cost) and
    ``log_rows``. A window with no scored day reports None."""
    out: dict[str, dict[str, Any]] = {}
    by_arm: dict[str, list] = {}
    for r in rows:
        by_arm.setdefault(r.get("arm"), []).append(r)

    def errs(rs, days, pred_key, actual_fn):
        lo = (today - timedelta(days=days)).isoformat()
        hi = today.isoformat()
        vals = []
        for r in rs:
            td = r.get("target_date") or ""
            if not (lo <= td < hi):
                continue
            p, a = _num(r.get(pred_key)), actual_fn(r)
            if p is not None and a is not None:
                vals.append(p - a)
        return vals

    def _mae(v):
        return round(sum(map(abs, v)) / len(v), 2) if v else None

    def cons(r):
        return _num(r.get("consumption_kwh"))

    def net(r):
        i, e = _num(r.get("import_kwh")), _num(r.get("export_kwh"))
        return None if i is None or e is None else i - e

    for arm, rs in by_arm.items():
        e7 = errs(rs, 7, "pred_consumption_kwh", cons)
        e30 = errs(rs, 30, "pred_consumption_kwh", cons)
        entry: dict[str, Any] = {
            "mae_7d_kwh": _mae(e7),
            "mae_30d_kwh": _mae(e30),
            "bias_30d_kwh": round(sum(e30) / len(e30), 2) if e30 else None,
        }
        if arm == d3_arm:
            entry["net_mae_30d_kwh"] = _mae(errs(rs, 30, "pred_net_kwh", net))
            entry["cost_mae_30d"] = _mae(errs(
                rs, 30, "pred_cost", lambda r: _num(r.get("net_cost"))))
            entry["log_rows"] = len(rs)
        out[arm] = entry
    return out


def local_day_bounds_utc_naive(day: date) -> tuple[str, str]:
    """[local midnight of ``day``, local midnight of next day) as naive-UTC
    ISO strings (the energy_history timestamp format)."""
    tz = dt_util.get_default_time_zone()
    s = dt_util.as_utc(datetime.combine(day, time(0), tzinfo=tz))
    e = dt_util.as_utc(datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz))
    return s.replace(tzinfo=None).isoformat(), e.replace(tzinfo=None).isoformat()
