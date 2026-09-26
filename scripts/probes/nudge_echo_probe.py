"""nudge_echo_probe — quantify the Carrier echo mechanism (C23).

Read-only. Runs on the HA host (Samba mount is read-write for humans; this
script only opens URI ...?mode=ro). Feed via:

    ssh ha "python3 -" < scripts/probes/nudge_echo_probe.py

Two questions:

1. For every URA temperature write since 2026-09-19, what is the lag to the
   FIRST recorder climate state change on that entity, and do the observed
   target_temp_high / target_temp_low equal URA's written values under each
   of {round-half-up, round-half-even, floor, ceil} at 1 F granularity?
   Emit p50/p95/max of the lag distribution + a rounding-mode tally.

2. For every `override_detected` row in `ura_activity_log` since 2026-09-19,
   is there a URA write to the same entity within the (measured) echo window
   whose written setpoints equal the row's observed setpoints under the
   winning rounding mode? Those are the ECHOES. The rest are GENUINE. Report
   both counts and, for the top-K genuine rows, dump the surrounding writes
   so a human can eyeball the discriminator (target: 24 echoes must classify
   as URA-echo, and known-genuine rows -- e.g. 2026-09-25 19:17 CDT zone_2
   76 -> 77 (see HVAC state-of-play C22/C23) -- must classify as genuine).

No writes, no dispatch, no HA imports. Pure sqlite3 stdlib.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

REC_DB = "file:/config/home-assistant_v2.db?mode=ro"
URA_DB = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"

# Window: since 2026-09-19 00:00 UTC (all inputs are UTC ISO in URA DB).
SINCE = "2026-09-19T00:00:00"
# W1-A climate_write rows only exist post-restart at 2026-09-26 20:23Z. So we
# use ac_ramp_events (nudge_started / nudge_restored) as the URA-write
# canonical source for the whole window, and cross-check the post-restart
# tail with climate_write rows to confirm the two sources agree.
CLIMATE_WRITE_SINCE = "2026-09-26T20:23:00"

# Echo-window candidates (seconds). Probe reports lag distribution; plan
# picks the operating window from p95.
ECHO_WINDOW_CANDIDATES_S = [8, 12, 15, 20, 30]

# The 3 Carrier zone climate entities.
ENTITIES = [
    "climate.thermostat_bryant_wifi_studyb_zone_1",
    "climate.up_hallway_zone_2",
    "climate.back_hallway_zone_3",
]


def _parse_iso(ts: str) -> datetime:
    """Recorder + URA both write naive UTC ISO. Coerce to aware UTC."""
    if ts.endswith("Z"):
        ts = ts[:-1]
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


ROUNDERS = {
    "half_up": lambda x: math.floor(x + 0.5),
    "half_even": lambda x: int(round(x)),  # Python 3 default: banker's
    "floor": lambda x: math.floor(x),
    "ceil": lambda x: math.ceil(x),
}


def load_ura_writes(uraconn) -> list[dict]:
    """Return URA temperature writes since SINCE, one row per event with the
    fields the probe needs: (ts_utc, entity_id, zone_id, target_high,
    target_low, source)."""
    out: list[dict] = []
    # ac_ramp_events: nudge_started carries target_high (post-nudge value).
    # target_low we look up from the zone's stored target at that time --
    # not in ac_ramp_events schema, so we approximate as "= manual profile
    # low = ha_carrier fills it from manual_activity.heat_set_point". For a
    # cool-side nudge in cool mode the LOW is not part of the write anyway;
    # arrester's echo detection compares WRITTEN values, so we accept
    # `target_low = None` = "URA did not assert this side".
    cur = uraconn.execute(
        """SELECT timestamp, zone_id, event_type, target_high
           FROM ac_ramp_events
           WHERE timestamp >= ?
             AND event_type IN ('nudge_started', 'nudge_restored')
           ORDER BY timestamp""",
        (SINCE,),
    )
    zone_to_entity = {
        "zone_1": ENTITIES[0], "zone_2": ENTITIES[1], "zone_3": ENTITIES[2],
    }
    for ts, zone_id, ev, thigh in cur.fetchall():
        out.append({
            "ts": _parse_iso(ts),
            "entity_id": zone_to_entity.get(zone_id, ""),
            "zone_id": zone_id,
            "target_high": float(thigh) if thigh is not None else None,
            "target_low": None,
            "source": f"ac_ramp:{ev}",
        })

    # climate_write rows (post-W1-A). Read from ura_activity_log.
    # details_json carries values_after with the exact service data.
    try:
        cur = uraconn.execute(
            """SELECT timestamp, entity_id, zone, details_json
               FROM ura_activity_log
               WHERE timestamp >= ?
                 AND action = 'climate_write'
               ORDER BY timestamp""",
            (CLIMATE_WRITE_SINCE,),
        )
        for ts, ent, zone_id, dj in cur.fetchall():
            try:
                d = json.loads(dj or "{}")
            except Exception:
                continue
            if d.get("verb") != "set_temperature":
                continue
            va = d.get("values_after") or {}
            out.append({
                "ts": _parse_iso(ts),
                "entity_id": ent or "",
                "zone_id": zone_id or "",
                "target_high": va.get("target_temp_high"),
                "target_low": va.get("target_temp_low"),
                "source": f"climate_write:{d.get('site', '?')}",
            })
    except sqlite3.OperationalError:
        # Pre-W1-A DB: table exists but no climate_write rows -- fine.
        pass

    out.sort(key=lambda r: r["ts"])
    return out


def load_state_changes(recconn) -> dict[str, list[tuple[datetime, dict]]]:
    """Return {entity_id: [(ts, {target_temp_high, target_temp_low, preset_mode}), ...]}
    from recorder, since SINCE."""
    q_ent = ",".join("?" * len(ENTITIES))
    # HA recorder: states + state_attributes.
    sql = f"""
      SELECT s.last_updated_ts, m.entity_id, sa.shared_attrs
      FROM states s
      JOIN states_meta m ON m.metadata_id = s.metadata_id
      LEFT JOIN state_attributes sa ON sa.attributes_id = s.attributes_id
      WHERE m.entity_id IN ({q_ent})
        AND s.last_updated_ts >= ?
      ORDER BY s.last_updated_ts
    """
    since_ts = _parse_iso(SINCE).timestamp()
    out: dict[str, list[tuple[datetime, dict]]] = defaultdict(list)
    for lu_ts, ent, attrs in recconn.execute(sql, (*ENTITIES, since_ts)):
        if lu_ts is None:
            continue
        try:
            a = json.loads(attrs or "{}")
        except Exception:
            a = {}
        out[ent].append((
            datetime.fromtimestamp(lu_ts, tz=timezone.utc),
            {
                "target_temp_high": a.get("target_temp_high"),
                "target_temp_low": a.get("target_temp_low"),
                "preset_mode": a.get("preset_mode"),
            },
        ))
    return out


def load_override_rows(uraconn) -> list[dict]:
    out: list[dict] = []
    cur = uraconn.execute(
        """SELECT timestamp, entity_id, zone, description, details_json
           FROM ura_activity_log
           WHERE timestamp >= ?
             AND action = 'override_detected'
           ORDER BY timestamp""",
        (SINCE,),
    )
    for ts, ent, zone_id, desc, dj in cur.fetchall():
        d = {}
        try:
            d = json.loads(dj or "{}")
        except Exception:
            pass
        out.append({
            "ts": _parse_iso(ts),
            "entity_id": ent or "",
            "zone_id": zone_id or "",
            "description": desc or "",
            "details": d,
        })
    return out


def observed_setpoints_at(state_series, entity, near_ts, window_s=90):
    """Return the FIRST recorder state row for `entity` in [near_ts, near_ts+window]
    whose setpoints DIFFER from the row just before near_ts."""
    series = state_series.get(entity, [])
    # Find last row strictly before near_ts.
    prev = None
    for ts, a in series:
        if ts >= near_ts:
            break
        prev = a
    prev_hi = prev.get("target_temp_high") if prev else None
    prev_lo = prev.get("target_temp_low") if prev else None
    for ts, a in series:
        if ts < near_ts:
            continue
        if ts > near_ts + timedelta(seconds=window_s):
            break
        hi = a.get("target_temp_high")
        lo = a.get("target_temp_low")
        if hi != prev_hi or lo != prev_lo:
            return (ts, hi, lo)
    return None


def matches_under_rounding(written, observed):
    """Return the set of rounding names under which int(round(written))==observed."""
    if written is None or observed is None:
        return set()
    try:
        w = float(written)
        o = float(observed)
    except Exception:
        return set()
    hits = set()
    for name, fn in ROUNDERS.items():
        if fn(w) == int(o):
            hits.add(name)
    return hits


def main():
    urac = sqlite3.connect(URA_DB, uri=True)
    recc = sqlite3.connect(REC_DB, uri=True)

    writes = load_ura_writes(urac)
    states = load_state_changes(recc)
    overrides = load_override_rows(urac)

    print(f"# URA writes since {SINCE}: {len(writes)}")
    print(f"# override_detected rows since {SINCE}: {len(overrides)}")
    print(f"# state series lengths: " + ", ".join(
        f"{e.split('.')[-1]}={len(states.get(e, []))}" for e in ENTITIES))

    # Q1: lag distribution + rounding mode tally per write.
    lags = []
    rounding_hits = Counter()
    per_entity_lags = defaultdict(list)
    for w in writes:
        if not w["entity_id"]:
            continue
        obs = observed_setpoints_at(states, w["entity_id"], w["ts"])
        if obs is None:
            continue
        obs_ts, obs_hi, obs_lo = obs
        lag_s = (obs_ts - w["ts"]).total_seconds()
        lags.append(lag_s)
        per_entity_lags[w["entity_id"]].append(lag_s)
        # Rounding: only score the high side (cool-side nudges are what we
        # care about); if target_high is None (a restore that wrote only low)
        # skip.
        if w["target_high"] is not None and obs_hi is not None:
            hits = matches_under_rounding(w["target_high"], obs_hi)
            for h in hits:
                rounding_hits[h] += 1
            if not hits:
                rounding_hits["_no_match"] += 1

    def pct(vals, p):
        if not vals:
            return None
        v = sorted(vals)
        k = min(len(v) - 1, int(math.ceil(p / 100.0 * len(v)) - 1))
        return v[max(0, k)]

    print("\n## Q1: URA-write -> first recorder setpoint change lag (s)")
    print(f"  n={len(lags)}  p50={pct(lags,50)}  p95={pct(lags,95)}  max={max(lags) if lags else None}")
    for e, ls in per_entity_lags.items():
        print(f"    {e.split('.')[-1]}: n={len(ls)} p50={pct(ls,50)} p95={pct(ls,95)} max={max(ls)}")
    print("\n## Q1: rounding mode tally (writes where high matched observed high)")
    for k, v in rounding_hits.most_common():
        print(f"    {k}: {v}")

    # Q2: classify each override_detected row.
    # Winner rounding: pick the mode with the highest hit count (excl _no_match).
    winner = None
    best = -1
    for k, v in rounding_hits.items():
        if k == "_no_match":
            continue
        if v > best:
            best, winner = v, k
    print(f"\n# Winning rounding mode: {winner}  (probe uses this for Q2)")

    echo_counts = Counter()
    genuine_rows = []
    for ov in overrides:
        # Recorder state at the override row: read the observed target_high
        # from details, or from the recorder if absent.
        det = ov["details"] or {}
        obs_hi = det.get("new_high") or det.get("target_temp_high")
        obs_lo = det.get("new_low") or det.get("target_temp_low")
        if obs_hi is None:
            # fall back to recorder at ov ts
            obs = observed_setpoints_at(states, ov["entity_id"], ov["ts"] - timedelta(seconds=2))
            if obs:
                _, obs_hi, obs_lo = obs
        # For each candidate echo window, is there a URA write on the same
        # entity in [ov_ts - W, ov_ts] whose target_high rounds to obs_hi?
        matched_any = False
        matched_at = {}
        for W in ECHO_WINDOW_CANDIDATES_S:
            for w in writes:
                if w["entity_id"] != ov["entity_id"]:
                    continue
                dt_s = (ov["ts"] - w["ts"]).total_seconds()
                if not (0 <= dt_s <= W):
                    continue
                if w["target_high"] is None or obs_hi is None:
                    continue
                if winner and ROUNDERS[winner](float(w["target_high"])) == int(float(obs_hi)):
                    matched_at[W] = dt_s
                    matched_any = True
                    break
        if matched_any:
            for W in matched_at:
                echo_counts[f"<= {W}s"] += 1
        else:
            genuine_rows.append(ov)

    total = len(overrides)
    print(f"\n## Q2: override_detected classification (total n={total})")
    for W in ECHO_WINDOW_CANDIDATES_S:
        c = echo_counts.get(f"<= {W}s", 0)
        print(f"    within {W}s of a URA write with matching high (winner rounding): {c}  ({100.0*c/total:.1f}%)")
    print(f"    NOT matched (candidate genuine): {len(genuine_rows)}")

    print("\n## Q2: candidate GENUINE rows (top 10 -- must include known human events)")
    for ov in genuine_rows[:10]:
        print(f"    {ov['ts'].isoformat()}  {ov['zone_id']}  {ov['description']}")

    # Q2b: if we adopt the winning rule at the plan's chosen window (default
    # 15s -- overridable at review), how many known-genuine rows are
    # misclassified?  A known-genuine row is any override_detected row that
    # falls > 60s from ANY URA write on that entity.  If the rule flips one
    # of these to "echo", that's a FALSE POSITIVE and the plan must reject
    # the design.  Target = 0.
    known_genuine_ts = []
    for ov in overrides:
        near = False
        for w in writes:
            if w["entity_id"] != ov["entity_id"]:
                continue
            if abs((ov["ts"] - w["ts"]).total_seconds()) <= 60:
                near = True
                break
        if not near:
            known_genuine_ts.append(ov)
    print(f"\n## Q2b: known-genuine rows (>60s from ANY URA write): {len(known_genuine_ts)}")
    # These should ALL be classified genuine by the rule at every window; check.
    for ov in known_genuine_ts:
        misclass_windows = []
        for W in ECHO_WINDOW_CANDIDATES_S:
            for w in writes:
                if w["entity_id"] != ov["entity_id"]:
                    continue
                dt_s = (ov["ts"] - w["ts"]).total_seconds()
                if 0 <= dt_s <= W:
                    misclass_windows.append(W)
                    break
        if misclass_windows:
            print(f"    !! FALSE POSITIVE at windows {misclass_windows}: {ov['ts'].isoformat()} {ov['zone_id']}")


if __name__ == "__main__":
    main()
