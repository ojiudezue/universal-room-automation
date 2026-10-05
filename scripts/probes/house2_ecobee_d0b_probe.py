#!/usr/bin/env python3
"""House 2 ecobee (HomeKit) D0b supervised live probe.

Plan: docs/planning/PLANNING_hvac_w1c_p2_ecobee.md REV 3, section D0b plus the
"D0b go/no-go criteria" appendix of plan review #2 (binding).
Runbook: docs/planning/RUNBOOK_house2_ecobee_d0b.md

Operator-run, operator at the thermostat, House 2 URA HVAC coordinator OFF.
Standalone, stdlib only. Talks to the House 2 HA REST API:

    HA_URL=http://house2.local:8123 HA_TOKEN=... \
        python3 scripts/probes/house2_ecobee_d0b_probe.py [--dry-run] [--entity climate.x]

The token is read from the environment and is never printed or written.

Safety (appendix items 1-4):
  * the full starting state is captured and restored in a finally block, which
    also runs on Ctrl-C (SIGINT) and SIGTERM;
  * a range is never sent unless the live state is heat_cool, and both legs are
    always sent;
  * every commanded leg is clamped to [66, 80] F, and the run aborts if indoor
    temperature leaves that band;
  * preflight lists automations/scripts referencing the entity and the URA HVAC
    coordinator switches, and requires operator confirmation.

Measurement note: HA's REST service endpoint calls services with blocking=True
(homeassistant/components/api/__init__.py, `blocking=True`). The non-blocking
variant of the P1 measurement is not reachable over REST; the probe records the
state at the instant the blocking call returns. State changes are observed by
polling /api/states/<entity> (default every 0.5 s); an intermediate state shorter
than the poll interval can be missed. That limit is written into the results.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Constants (probe-local; this is a one-shot measurement tool, not URA code)
# ---------------------------------------------------------------------------
SAFE_MIN_F = 66.0
SAFE_MAX_F = 80.0
G2_MAX_TOLERANCE_F = 1.0          # G2: T <= 1.0 F
G2_STRICT_TOLERANCE_F = 0.5       # G2: T < 0.5 F, else PR2-4 near-duplicate rule applies
G3_MAX_ECHO_P95_S = 120.0         # G3: echo p95 <= 120 s
URA_PAIR_TOLERANCE_F = 0.5        # LAST_SENT_TOLERANCE_F (review #1 LOW): report rounding against it
DEFAULT_ECHO_TIMEOUT_S = 180.0
DEFAULT_WRITE_GAP_S = 120.0       # P2: writes >= 2 min apart
DEFAULT_POLL_S = 0.5

# P2: five range writes. Includes .5 values (nudge size 1.5 F) and 70 F
# (non-integer Celsius) to measure readback rounding.
P2_WRITES: list[tuple[float, float]] = [
    (70.0, 75.0),
    (70.5, 75.5),
    (71.0, 76.0),
    (69.5, 74.5),
    (70.0, 74.0),
]
# P3: narrow range 72/74, then the winter-home default (2 F gap) 70/72 ("72/70").
P3_WRITES: list[tuple[float, float]] = [(72.0, 74.0), (70.0, 72.0)]
# P4: known range written before the operator's wall-unit change.
P4_BASE: tuple[float, float] = (70.0, 75.0)


class ProbeAbort(Exception):
    """Raised to stop the run; the finally block restores the starting state."""


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested in quality/tests/test_house2_d0b_probe_helpers.py)
# ---------------------------------------------------------------------------
def clamp_leg(value: float, lo: float = SAFE_MIN_F, hi: float = SAFE_MAX_F) -> float:
    """Clamp one commanded leg to the safe band."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise ValueError("leg value is None/NaN")
    return max(lo, min(hi, float(value)))


def build_range_payload(entity_id: str, low: float, high: float) -> dict[str, Any]:
    """Return a set_temperature payload that ALWAYS carries both legs, clamped.

    Raises ValueError if, after clamping, the range is empty (low >= high).
    """
    if low is None or high is None:
        raise ValueError("both legs are required")
    c_low, c_high = clamp_leg(low), clamp_leg(high)
    if c_low >= c_high:
        raise ValueError(f"empty range after clamping: {c_low}/{c_high}")
    return {"entity_id": entity_id, "target_temp_low": c_low, "target_temp_high": c_high}


def assert_heat_cool(state: dict[str, Any]) -> None:
    """Appendix item 2: never send a range unless the live state is heat_cool."""
    live = (state or {}).get("state")
    if live != "heat_cool":
        raise ProbeAbort(f"refusing range write: live hvac state is {live!r}, not 'heat_cool'")


def legs_of(state: dict[str, Any]) -> tuple[float | None, float | None]:
    attrs = (state or {}).get("attributes") or {}
    return _num(attrs.get("target_temp_low")), _num(attrs.get("target_temp_high"))


def indoor_temp(state: dict[str, Any]) -> float | None:
    return _num(((state or {}).get("attributes") or {}).get("current_temperature"))


def indoor_in_band(state: dict[str, Any], lo: float = SAFE_MIN_F, hi: float = SAFE_MAX_F) -> bool:
    """True if indoor temperature is known and inside [lo, hi]. Unknown -> False (fail safe)."""
    t = indoor_temp(state)
    return t is not None and lo <= t <= hi


def is_no_setpoint_state(state: dict[str, Any]) -> bool:
    """The temperature=None hazard: no single setpoint AND no complete leg pair."""
    attrs = (state or {}).get("attributes") or {}
    low, high = legs_of(state)
    return _num(attrs.get("temperature")) is None and (low is None or high is None)


def single_leg_changed(prev: tuple[Any, Any], cur: tuple[Any, Any], target: tuple[float, float],
                       tol: float) -> bool:
    """True if `cur` is an intermediate state where exactly one leg moved to its target."""
    if None in prev or None in cur:
        return False
    moved = [abs(cur[i] - prev[i]) > 1e-9 for i in range(2)]
    at_target = [abs(cur[i] - target[i]) <= tol for i in range(2)]
    return sum(moved) == 1 and not all(at_target)


def legs_match(cur: tuple[Any, Any], target: tuple[float, float], tol: float) -> bool:
    return None not in cur and all(abs(cur[i] - target[i]) <= tol for i in range(2))


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def evaluate_g(results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Evaluate G1-G7 from the results dict. Each -> {"status": GO|NO-GO|UNKNOWN, "evidence": str}.

    Also returns key "OVERALL" applying the appendix NO-GO overrides.
    """
    g: dict[str, dict[str, Any]] = {}
    pre = results.get("preflight", {})
    notes = results.get("p0_notes", {})
    p2 = results.get("p2", {})
    p3 = results.get("p3", {})
    p4 = results.get("p4", {})
    restore = results.get("restore", {})

    def put(key: str, status: str, evidence: str) -> None:
        g[key] = {"status": status, "evidence": evidence}

    # G1 heat_cool exposed + legs appear in heat_cool + Auto enabled
    has_hc = "heat_cool" in (pre.get("hvac_modes") or [])
    legs_seen = bool(results.get("p1", {}).get("legs_present_in_heat_cool"))
    auto = notes.get("auto_heat_cool_enabled")
    if has_hc and legs_seen and auto is True:
        put("G1", "GO", "heat_cool in hvac_modes, legs present, Auto enabled (operator)")
    elif auto is None and has_hc and legs_seen:
        put("G1", "UNKNOWN", "Auto heat/cool enablement not recorded")
    else:
        put("G1", "NO-GO", f"heat_cool={has_hc} legs_present={legs_seen} auto={auto}")

    # G2 measured tolerance T
    t_meas = p2.get("tolerance_t_f")
    landed = p2.get("all_landed")
    if t_meas is None or landed is None:
        put("G2", "UNKNOWN", "P2 not run")
    elif landed and t_meas <= G2_MAX_TOLERANCE_F:
        strict = t_meas < G2_STRICT_TOLERANCE_F
        put("G2", "GO", f"T={t_meas:.2f}F <= {G2_MAX_TOLERANCE_F}; "
            + ("T < 0.5F" if strict else "T >= 0.5F -> PR2-4 near-duplicate rule applies"))
    else:
        put("G2", "NO-GO", f"all_landed={landed} T={t_meas}")

    # G3 echo p95
    p95 = p2.get("echo_p95_s")
    if p95 is None:
        put("G3", "UNKNOWN", "no echo latencies")
    elif p95 <= G3_MAX_ECHO_P95_S:
        put("G3", "GO", f"echo p95={p95:.1f}s <= {G3_MAX_ECHO_P95_S}s (C1 stays conditional)")
    else:
        put("G3", "NO-GO", f"echo p95={p95:.1f}s > {G3_MAX_ECHO_P95_S}s -> C1 mandatory")

    # G4 device min delta measured (any value)
    md = p3.get("device_min_delta_f")
    md_op = notes.get("device_min_delta_f")
    if md is not None or md_op is not None:
        put("G4", "GO", f"measured={md} operator_read={md_op}")
    else:
        put("G4", "NO-GO", "device minimum delta not measured")

    # G5 separability
    sep = p4.get("separable")
    if sep is True:
        put("G5", "GO", p4.get("separability_evidence", "separable"))
    elif sep is False and notes.get("q4_accepted") is True:
        put("G5", "GO", "not separable; operator accepted Q4")
    elif sep is False:
        put("G5", "NO-GO", p4.get("separability_evidence", "not separable") + " (Q4 to operator)")
    else:
        put("G5", "UNKNOWN", "P4 not run / no wall change observed")

    # G6 hold persists with configured hold action
    hold_ok = p2.get("hold_persists_operator")
    drift = p2.get("drift_events", 0)
    if hold_ok is True and not drift:
        put("G6", "GO", "operator confirmed hold shown; no self-move during write gaps")
    elif hold_ok is None:
        put("G6", "UNKNOWN", "hold persistence not recorded")
    else:
        put("G6", "NO-GO", f"operator_hold_ok={hold_ok} drift_events={drift} (answer Q1 before build)")

    # G7 restore confirmed
    if restore.get("verified") is True:
        put("G7", "GO", "starting state restored and read back")
    else:
        put("G7", "NO-GO", f"restore verified={restore.get('verified')} detail={restore.get('detail')}")

    hard = []
    if results.get("hazard_no_setpoint_states"):
        hard.append("a write produced a no-setpoint (temperature=None) state")
    if p2.get("single_leg_intermediates") or p3.get("single_leg_intermediates"):
        hard.append("a single-leg intermediate state was observed")
    for key in ("G1", "G2", "G7"):
        if g[key]["status"] == "NO-GO":
            hard.append(f"{key} NO-GO")
    if hard:
        overall = "NO-GO"
    elif all(g[k]["status"] == "GO" for k in ("G1", "G2", "G3", "G4", "G5", "G6", "G7")):
        overall = "GO"
    else:
        overall = "NO-GO"
    g["OVERALL"] = {"status": overall, "evidence": "; ".join(hard) or "see G1-G7"}
    return g


def _num(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# HA REST client (token never printed)
# ---------------------------------------------------------------------------
class HA:
    def __init__(self, url: str, token: str, dry_run: bool) -> None:
        self.url = url.rstrip("/")
        self._token = token
        self.dry_run = dry_run

    def _req(self, method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self._token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"HTTP {err.code} on {method} {path}") from None
        except urllib.error.URLError as err:
            raise RuntimeError(f"connection error on {method} {path}: {err.reason}") from None
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self._req("GET", path)

    def state(self, entity_id: str) -> dict[str, Any]:
        return self.get(f"/api/states/{entity_id}")

    def call(self, domain: str, service: str, data: dict[str, Any]) -> float:
        """Blocking service call; returns elapsed seconds. Refuses in dry-run."""
        if self.dry_run:
            raise RuntimeError("BUG: service call attempted in dry-run")
        t0 = time.monotonic()
        self._req("POST", f"/api/services/{domain}/{service}", data, timeout=60.0)
        return time.monotonic() - t0


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ask_yes(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def ask_text(prompt: str) -> str:
    try:
        return input(f"{prompt} ").strip()
    except EOFError:
        return ""


def ask_bool(prompt: str) -> bool | None:
    ans = ask_text(f"{prompt} [y/n/?]").lower()
    return True if ans == "y" else False if ans == "n" else None


class Probe:
    def __init__(self, ha: HA, args: argparse.Namespace) -> None:
        self.ha = ha
        self.args = args
        self.entity: str = args.entity or ""
        self.start_state: dict[str, Any] | None = None
        self.restored = False
        self.t0 = time.monotonic()
        self.results: dict[str, Any] = {
            "probe": "house2_ecobee_d0b",
            "plan": "docs/planning/PLANNING_hvac_w1c_p2_ecobee.md REV 3",
            "started_utc": now_iso(),
            "dry_run": args.dry_run,
            "poll_interval_s": args.poll_s,
            "observation_limit": "state changes observed by REST polling; sub-interval intermediates can be missed",
            "rest_service_calls_blocking": True,
            "events": [],
            "hazard_no_setpoint_states": [],
        }

    # -- logging ----------------------------------------------------------
    def log(self, kind: str, **data: Any) -> None:
        ev = {"t_mono": round(time.monotonic() - self.t0, 3), "utc": now_iso(), "kind": kind, **data}
        self.results["events"].append(ev)
        print(f"[{ev['t_mono']:9.3f}] {kind}: {json.dumps(data, default=str)}")

    def gate(self, prompt: str) -> None:
        if not ask_yes(prompt):
            raise ProbeAbort(f"operator declined: {prompt}")

    # -- safety -----------------------------------------------------------
    def check_band(self, state: dict[str, Any]) -> None:
        if not indoor_in_band(state):
            raise ProbeAbort(f"indoor temperature {indoor_temp(state)} outside [{SAFE_MIN_F}, {SAFE_MAX_F}]")

    def read(self) -> dict[str, Any]:
        st = self.ha.state(self.entity)
        if is_no_setpoint_state(st) and st.get("state") not in ("off", "fan_only", "unavailable", "unknown"):
            self.results["hazard_no_setpoint_states"].append(
                {"utc": now_iso(), "state": st.get("state"), "attributes": st.get("attributes")})
        return st

    def write_range(self, low: float, high: float) -> tuple[dict[str, Any], float]:
        st = self.read()
        assert_heat_cool(st)
        self.check_band(st)
        payload = build_range_payload(self.entity, low, high)
        elapsed = self.ha.call("climate", "set_temperature", payload)
        self.log("range_write", low=payload["target_temp_low"], high=payload["target_temp_high"],
                 call_s=round(elapsed, 3))
        return payload, time.monotonic()

    def watch(self, seconds: float, until=None, label: str = "") -> list[dict[str, Any]]:
        """Poll the entity; record every distinct (state, low, high, temperature). Abort on band exit."""
        seen: list[dict[str, Any]] = []
        last = None
        t_start = time.monotonic()
        while time.monotonic() - t_start < seconds:
            st = self.read()
            self.check_band(st)
            attrs = st.get("attributes") or {}
            key = (st.get("state"), *legs_of(st), _num(attrs.get("temperature")))
            if key != last:
                obs = {"t": time.monotonic(), "state": key[0], "low": key[1], "high": key[2],
                       "temperature": key[3], "hvac_action": attrs.get("hvac_action")}
                seen.append(obs)
                self.log(f"state_change{':' + label if label else ''}",
                         **{k: v for k, v in obs.items() if k != "t"})
                last = key
                if until and until(obs):
                    break
            time.sleep(self.args.poll_s)
        return seen

    # -- preflight / P0 ---------------------------------------------------
    def preflight(self) -> None:
        states = self.ha.get("/api/states")
        climates = [s for s in states if s["entity_id"].startswith("climate.")]
        print("\nClimate entities on House 2:")
        for s in climates:
            print(f"  {s['entity_id']:45s} state={s['state']:10s} name={s['attributes'].get('friendly_name')}")
        if not self.entity:
            cands = [s["entity_id"] for s in climates if "ecobee" in json.dumps(s).lower()]
            if len(cands) == 1:
                self.entity = cands[0]
            elif self.args.dry_run and climates:
                self.entity = (cands or [climates[0]["entity_id"]])[0]
            else:
                self.entity = ask_text("Enter the ecobee climate entity_id:")
        if not any(s["entity_id"] == self.entity for s in climates):
            raise ProbeAbort(f"entity {self.entity!r} not found")
        print(f"\nUsing entity: {self.entity}")

        # URA HVAC coordinator switches (must be OFF)
        ura = [s for s in states if s["entity_id"].startswith("switch.")
               and "hvac" in s["entity_id"] and ("coordinator" in s["entity_id"] or "ura" in s["entity_id"])]
        print("\nCandidate URA HVAC coordinator switches (must be OFF):")
        for s in ura:
            print(f"  {s['entity_id']:55s} {s['state']}")
        if not ura:
            print("  (none matched by name - confirm manually in the URA Coordinator Manager)")

        # Automations / scripts referencing the entity (best effort via config API)
        refs = self._find_writers(states)
        print("\nAutomations/scripts referencing the entity (config API, UI-managed only):")
        for r in refs:
            print(f"  {r['entity_id']:55s} state={r['state']}")
        if not refs:
            print("  (none found - YAML-only automations without an id are NOT searchable; confirm manually)")

        st = self.read()
        attrs = st.get("attributes") or {}
        self.results["preflight"] = {
            "entity_id": self.entity,
            "hvac_modes": attrs.get("hvac_modes"),
            "supported_features": attrs.get("supported_features"),
            "min_temp": attrs.get("min_temp"), "max_temp": attrs.get("max_temp"),
            "target_temp_step": attrs.get("target_temp_step"),
            "ura_hvac_switches": [{"entity_id": s["entity_id"], "state": s["state"]} for s in ura],
            "referencing_automations": refs,
        }
        if self.args.dry_run:
            return
        if any(s["state"] == "on" for s in ura):
            print("\n!! A matching URA HVAC switch is ON. Turn the House 2 HVAC coordinator OFF first.")
        self.gate("Confirm: House 2 URA HVAC coordinator is OFF")
        self.gate("Confirm: no automation/script will write this thermostat during the probe "
                  "(listed ones disabled)")

    def _find_writers(self, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for s in states:
            eid = s["entity_id"]
            try:
                if eid.startswith("automation.") and s["attributes"].get("id"):
                    cfg = self.ha.get(f"/api/config/automation/config/{s['attributes']['id']}")
                elif eid.startswith("script."):
                    cfg = self.ha.get(f"/api/config/script/config/{eid.split('.', 1)[1]}")
                else:
                    continue
            except Exception:  # noqa: BLE001 - best effort; YAML-only configs 404
                continue
            if self.entity in json.dumps(cfg):
                out.append({"entity_id": eid, "state": s["state"]})
        return out

    def p0_notes(self) -> None:
        print("\nP0 - read these on the thermostat / ecobee app (y/n/? for unknown):")
        n: dict[str, Any] = {}
        n["hold_action"] = ask_text("Hold action shown (expect 'until I change it'):")
        n["device_min_delta_f"] = _num(ask_text("Auto heat/cool minimum delta (F, blank if unknown):"))
        n["program_running"] = ask_bool("Is an ecobee program/schedule running?")
        n["auto_heat_cool_enabled"] = ask_bool("Is Auto heat/cool enabled?")
        n["smart_home_away"] = ask_bool("Smart Home/Away ON?")
        n["eco_plus"] = ask_bool("Eco+ (incl. schedule/peak relief) ON?")
        n["follow_me"] = ask_bool("Follow Me ON?")
        self.results["p0_notes"] = n
        self.log("p0_notes", **n)
        bad = [k for k in ("program_running", "smart_home_away", "eco_plus", "follow_me") if n[k]]
        if bad:
            print(f"!! These move setpoints by themselves and read as a person: {bad}. Turn them OFF (PR2-13).")
            self.gate("Continue anyway (results will be confounded)?")

    # -- snapshot / restore -----------------------------------------------
    def snapshot(self) -> None:
        st = self.read()
        self.start_state = st
        attrs = st.get("attributes") or {}
        snap = {"state": st.get("state"), "temperature": attrs.get("temperature"),
                "target_temp_low": attrs.get("target_temp_low"),
                "target_temp_high": attrs.get("target_temp_high"),
                "preset_mode": attrs.get("preset_mode"), "fan_mode": attrs.get("fan_mode"),
                "current_temperature": attrs.get("current_temperature")}
        self.results["start_state"] = {"summary": snap, "full": st}
        print("\nSTARTING STATE (will be restored):")
        print(json.dumps(snap, indent=2))

    def restore(self, interactive: bool) -> None:
        if self.args.dry_run or self.start_state is None or self.restored:
            return
        self.restored = True
        info: dict[str, Any] = {"verified": False}
        self.results["restore"] = info
        if interactive and not ask_yes("Restore the starting state now?"):
            info["detail"] = "operator declined restore - RESTORE MANUALLY"
            print("!! Restore declined. Restore the starting state by hand.")
            return
        s = self.start_state
        a = s.get("attributes") or {}
        mode = s.get("state")
        try:
            if mode not in ("unavailable", "unknown"):
                self.ha.call("climate", "set_hvac_mode", {"entity_id": self.entity, "hvac_mode": mode})
            lo, hi = _num(a.get("target_temp_low")), _num(a.get("target_temp_high"))
            temp = _num(a.get("temperature"))
            if mode == "heat_cool" and lo is not None and hi is not None:
                time.sleep(2)
                if self.read().get("state") == "heat_cool":
                    # restore the operator's own values verbatim (no clamping of a restore)
                    self.ha.call("climate", "set_temperature",
                                 {"entity_id": self.entity, "target_temp_low": lo, "target_temp_high": hi})
            elif temp is not None and mode not in ("off", "heat_cool"):
                time.sleep(2)
                self.ha.call("climate", "set_temperature", {"entity_id": self.entity, "temperature": temp})
            deadline = time.monotonic() + self.args.echo_timeout_s
            ok = False
            cur: dict[str, Any] = {}
            while time.monotonic() < deadline:
                cur = self.ha.state(self.entity)
                ca = cur.get("attributes") or {}
                ok = cur.get("state") == mode
                if ok and mode == "heat_cool" and lo is not None:
                    ok = legs_match(legs_of(cur), (lo, hi), G2_MAX_TOLERANCE_F)
                elif ok and temp is not None and mode not in ("off", "heat_cool"):
                    ok = _num(ca.get("temperature")) is not None and abs(_num(ca.get("temperature")) - temp) <= 1.0
                if ok:
                    break
                time.sleep(1.0)
            info["verified"] = ok
            info["final"] = {"state": cur.get("state"), "low": legs_of(cur)[0], "high": legs_of(cur)[1],
                             "temperature": (cur.get("attributes") or {}).get("temperature")}
            info["detail"] = "ok" if ok else "readback did not match the starting state"
            self.log("restore", **info)
        except Exception as err:  # noqa: BLE001 - restore must report, not raise
            info["detail"] = f"restore error: {err}"
            print(f"!! RESTORE FAILED: {err}. Restore the starting state by hand.")

    # -- P1 ----------------------------------------------------------------
    def p1(self) -> None:
        r: dict[str, Any] = {}
        self.results["p1"] = r
        st = self.read()
        if st.get("state") == "heat_cool":
            if ask_yes("Entity is already heat_cool. Switch to 'cool' first so P1 measures the transition?"):
                self.ha.call("climate", "set_hvac_mode", {"entity_id": self.entity, "hvac_mode": "cool"})
                self.watch(30, until=lambda o: o["state"] == "cool", label="p1_to_cool")
            else:
                r["transition_measured"] = False
                r["legs_present_in_heat_cool"] = None not in legs_of(st)
                return
        self.gate("P1: send set_hvac_mode heat_cool (blocking REST call)?")
        t_call = time.monotonic()
        elapsed = self.ha.call("climate", "set_hvac_mode", {"entity_id": self.entity, "hvac_mode": "heat_cool"})
        at_return = self.read()
        r["transition_measured"] = True
        r["call_s"] = round(elapsed, 3)
        r["state_at_return"] = at_return.get("state")
        r["heat_cool_at_return"] = at_return.get("state") == "heat_cool"
        r["legs_at_return"] = legs_of(at_return)
        self.log("p1_return", **{k: v for k, v in r.items()})
        obs = self.watch(60, until=lambda o: o["state"] == "heat_cool" and o["low"] is not None
                         and o["high"] is not None, label="p1")
        hc = [o for o in obs if o["state"] == "heat_cool"]
        r["latency_to_heat_cool_s"] = round(hc[0]["t"] - t_call, 3) if hc else None
        r["legs_present_in_heat_cool"] = any(o["low"] is not None and o["high"] is not None for o in hc) \
            or (r["heat_cool_at_return"] and None not in r["legs_at_return"])
        self.log("p1_result", **{k: v for k, v in r.items()})

    # -- P2 ----------------------------------------------------------------
    def p2(self) -> None:
        r: dict[str, Any] = {"writes": [], "single_leg_intermediates": [], "drift_events": 0}
        self.results["p2"] = r
        latencies: list[float] = []
        errors: list[float] = []
        for i, (lo, hi) in enumerate(P2_WRITES):
            self.gate(f"P2 write {i + 1}/{len(P2_WRITES)}: {clamp_leg(lo)}/{clamp_leg(hi)}?")
            prev = legs_of(self.read())
            payload, t_w = self.write_range(lo, hi)
            target = (payload["target_temp_low"], payload["target_temp_high"])
            obs = self.watch(self.args.echo_timeout_s,
                             until=lambda o: legs_match((o["low"], o["high"]), target, G2_MAX_TOLERANCE_F),
                             label=f"p2_{i + 1}")
            w = self._summarise_write(target, prev, t_w, obs)
            r["writes"].append(w)
            r["single_leg_intermediates"].extend(w["single_leg_intermediates"])
            if w["latency_s"] is not None:
                latencies.append(w["latency_s"])
                errors.extend(w["readback_err_f"])
            # remainder of the >= 2 min gap: anything that moves now is drift (hold / self-move)
            rest = max(0.0, self.args.write_gap_s - (time.monotonic() - t_w))
            if rest:
                gap_obs = self.watch(rest, label=f"p2_{i + 1}_gap")
                moved = [o for o in gap_obs[1:] if (o["low"], o["high"]) != (gap_obs[0]["low"], gap_obs[0]["high"])]
                r["drift_events"] += len(moved)
        r["all_landed"] = all(w["latency_s"] is not None for w in r["writes"])
        r["tolerance_t_f"] = round(max(errors), 3) if errors else None
        r["exceeds_ura_pair_tolerance_0_5"] = bool(errors) and max(errors) > URA_PAIR_TOLERANCE_F
        r["echo_p50_s"] = percentile(latencies, 50)
        r["echo_p95_s"] = percentile(latencies, 95)
        r["echo_max_s"] = max(latencies) if latencies else None
        r["n"] = len(latencies)
        r["hold_shown"] = ask_text("P2: what hold does the thermostat show now?")
        r["hold_persists_operator"] = ask_bool("P2: does that hold persist with the configured hold action?")
        self.log("p2_result", **{k: v for k, v in r.items() if k != "writes"})

    def _summarise_write(self, target, prev, t_w, obs) -> dict[str, Any]:
        landed = [o for o in obs if legs_match((o["low"], o["high"]), target, G2_MAX_TOLERANCE_F)]
        singles = []
        p = prev
        for o in obs:
            cur = (o["low"], o["high"])
            if single_leg_changed(p, cur, target, G2_MAX_TOLERANCE_F):
                singles.append({"low": cur[0], "high": cur[1]})
            p = cur
        w: dict[str, Any] = {"target": list(target), "n_state_changes": len(obs),
                             "single_leg_intermediates": singles, "latency_s": None, "readback": None,
                             "readback_err_f": []}
        if landed:
            o = landed[0]
            w["latency_s"] = round(o["t"] - t_w, 3)
            w["readback"] = [o["low"], o["high"]]
            w["readback_err_f"] = [round(abs(o["low"] - target[0]), 3), round(abs(o["high"] - target[1]), 3)]
        return w

    # -- P3 ----------------------------------------------------------------
    def p3(self) -> None:
        r: dict[str, Any] = {"writes": [], "single_leg_intermediates": []}
        self.results["p3"] = r
        min_delta = None
        for lo, hi in P3_WRITES:
            self.gate(f"P3 write {lo}/{hi} (gap {hi - lo}F)?")
            prev = legs_of(self.read())
            payload, t_w = self.write_range(lo, hi)
            target = (payload["target_temp_low"], payload["target_temp_high"])
            obs = self.watch(self.args.echo_timeout_s, label=f"p3_{lo}_{hi}")
            final = (obs[-1]["low"], obs[-1]["high"]) if obs else legs_of(self.read())
            w = self._summarise_write(target, prev, t_w, obs)
            moved = None
            if None not in final:
                moved = [name for name, i in (("low", 0), ("high", 1)) if abs(final[i] - target[i]) > 0.25]
                if moved:
                    min_delta = final[1] - final[0]
            w.update({"final": list(final), "legs_moved_by_device": moved})
            r["writes"].append(w)
            r["single_leg_intermediates"].extend(w["single_leg_intermediates"])
        smallest = min(hi - lo for lo, hi in P3_WRITES)
        r["device_min_delta_f"] = min_delta if min_delta is not None else (
            f"<= {smallest} (device accepted every gap)" if all(not w["legs_moved_by_device"]
                                                              for w in r["writes"]) else None)
        self.log("p3_result", device_min_delta_f=r["device_min_delta_f"],
                 moved=[w["legs_moved_by_device"] for w in r["writes"]])

    # -- P4 ----------------------------------------------------------------
    def p4(self, tol: float) -> None:
        r: dict[str, Any] = {}
        self.results["p4"] = r
        self.gate(f"P4: write base range {P4_BASE[0]}/{P4_BASE[1]}?")
        payload, t_w = self.write_range(*P4_BASE)
        target = (payload["target_temp_low"], payload["target_temp_high"])
        self.watch(self.args.echo_timeout_s,
                   until=lambda o: legs_match((o["low"], o["high"]), target, G2_MAX_TOLERANCE_F), label="p4_echo")
        before = legs_of(self.read())
        print("\nP4: at the WALL UNIT change ONE setpoint leg (e.g. cool +2F). Press Enter the moment you finish.")
        ask_text("Enter when done:")
        t_done = time.monotonic()
        obs = self.watch(self.args.echo_timeout_s, label="p4_wall")
        changed = [o for o in obs if (o["low"], o["high"]) != before]
        if not changed:
            r["separable"] = None
            r["separability_evidence"] = "no wall change observed"
            return
        first = changed[0]
        final = (changed[-1]["low"], changed[-1]["high"])
        legs_moved = [n for n, i in (("low", 0), ("high", 1))
                      if None not in (final[i], before[i]) and abs(final[i] - before[i]) > 1e-9]
        r.update({"latency_from_operator_s": round(first["t"] - t_done, 3), "before": list(before),
                  "final": list(final), "legs_moved": legs_moved,
                  "other_leg_also_moved": len(legs_moved) > 1, "n_state_changes": len(changed),
                  "seconds_after_ura_write": round(first["t"] - t_w, 3)})
        # Separable if the changed leg(s) land outside T of URA's written value (value test);
        # timing recorded for the operator's Q4 judgement.
        close = [n for n in legs_moved if abs(final[0 if n == "low" else 1] - target[0 if n == "low" else 1]) <= tol]
        r["separable"] = not close
        r["separability_evidence"] = (f"wall change moved {legs_moved}; within T={tol}F of URA write on {close}"
                                      if close else f"wall change moved {legs_moved} beyond T={tol}F")
        self.log("p4_result", **r)

    # -- P5 / P6 (operator-driven, recorded) -------------------------------
    def operator_step(self, key: str, instruction: str) -> None:
        if not ask_yes(f"{key}: {instruction} - run this step?"):
            self.results[key] = {"skipped": True}
            return
        print(f"{key}: do it now; recording for {self.args.echo_timeout_s:.0f}s (Ctrl-C aborts and restores).")
        obs = self.watch(self.args.echo_timeout_s, label=key.lower())
        self.results[key] = {"observations": [{k: v for k, v in o.items() if k != "t"} for o in obs]}

    # -- orchestration -----------------------------------------------------
    def planned_writes(self) -> list[dict[str, Any]]:
        out = [{"step": "P1", "service": "climate.set_hvac_mode", "data": {"hvac_mode": "heat_cool"}}]
        for lo, hi in P2_WRITES:
            out.append({"step": "P2", "service": "climate.set_temperature",
                        "data": build_range_payload(self.entity, lo, hi)})
        for lo, hi in P3_WRITES:
            out.append({"step": "P3", "service": "climate.set_temperature",
                        "data": build_range_payload(self.entity, lo, hi)})
        out.append({"step": "P4", "service": "climate.set_temperature",
                    "data": build_range_payload(self.entity, *P4_BASE)})
        out.append({"step": "RESTORE", "service": "set_hvac_mode + set_temperature", "data": "starting state"})
        return out

    def run(self) -> int:
        self.preflight()
        self.snapshot()
        if self.args.dry_run:
            st = self.start_state or {}
            print(f"\nIndoor in safe band [{SAFE_MIN_F}, {SAFE_MAX_F}]: {indoor_in_band(st)}")
            print("\nDRY RUN - planned writes (nothing sent):")
            for w in self.planned_writes():
                print("  " + json.dumps(w))
            self.results["planned_writes"] = self.planned_writes()
            return 0
        self.check_band(self.start_state or {})
        self.p0_notes()
        self.p1()
        self.p2()
        self.p3()
        tol = self.results["p2"].get("tolerance_t_f") or G2_MAX_TOLERANCE_F
        self.p4(max(tol, 0.5))
        self.results["p0_notes"]["q4_accepted"] = (
            ask_bool("Q4: if P4 was NOT separable, do you accept that?")
            if self.results["p4"].get("separable") is False else None)
        self.operator_step("P5", "change MODE at the wall unit, then change it back")
        self.operator_step("P6", "press 'Resume schedule' in the ecobee app")
        return 0


def write_results(probe: Probe) -> str:
    probe.results["finished_utc"] = now_iso()
    if not probe.args.dry_run:
        probe.results["go_no_go"] = evaluate_g(probe.results)
    path = probe.args.out or f"house2_d0b_results_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(probe.results, fh, indent=2, default=str)
    return path


def print_go_no_go(results: dict[str, Any]) -> None:
    g = results.get("go_no_go")
    if not g:
        return
    print("\n================ D0b GO / NO-GO ================")
    for key in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "OVERALL"):
        print(f"  {key:8s} {g[key]['status']:8s} {g[key]['evidence']}")


# ---------------------------------------------------------------------------
# --discover: read-only multi-thermostat discovery (D0b read-only leg, 2026-10-05)
# Sends NO service calls. Uses GET /api/states, GET /api/history/period and
# POST /api/template (render only) to resolve the device registry.
# ---------------------------------------------------------------------------
CLIMATE_KEYS = ("hvac_modes", "preset_modes", "preset_mode", "fan_modes", "fan_mode", "supported_features",
                "min_temp", "max_temp", "target_temp_step", "temperature", "target_temp_low", "target_temp_high",
                "current_temperature", "current_humidity", "target_humidity", "min_humidity", "max_humidity",
                "hvac_action", "friendly_name")
HIST_KEYS = ("hvac_action", "temperature", "target_temp_low", "target_temp_high", "current_temperature",
             "preset_mode", "fan_mode")


def _template(ha: "HA", tpl: str) -> Any:
    raw = ha._req("POST", "/api/template", {"template": tpl})
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _is_ecobee_like(dev: dict[str, Any]) -> bool:
    blob = " ".join(str(dev.get(k) or "") for k in ("manufacturer", "model", "name")).lower()
    return "ecobee" in blob or (dev.get("model") or "").upper().startswith("ECB")


def _history(ha: "HA", entity_ids: list[str], hours: float) -> dict[str, list[dict[str, Any]]]:
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    path = ("/api/history/period/" + urllib.parse.quote(start) + "?filter_entity_id="
            + ",".join(entity_ids) + "&significant_changes_only=0")
    out: dict[str, list[dict[str, Any]]] = {}
    for series in ha.get(path) or []:
        if not series:
            continue
        eid = series[0]["entity_id"]
        out[eid] = [{"t": s.get("last_changed"), "state": s.get("state"),
                     **{k: (s.get("attributes") or {}).get(k) for k in HIST_KEYS
                        if k in (s.get("attributes") or {})}} for s in series]
    return out


def _summ(series: list[dict[str, Any]], hours: float) -> dict[str, Any]:
    from collections import Counter
    if not series:
        return {"n": 0}
    end = datetime.now(timezone.utc)
    dur: Counter = Counter()
    for i, s in enumerate(series):
        t0 = datetime.fromisoformat(s["t"])
        t1 = datetime.fromisoformat(series[i + 1]["t"]) if i + 1 < len(series) else end
        dur[str(s["state"])] += max(0.0, (t1 - t0).total_seconds())
    return {"n": len(series), "first": series[0]["t"],
            "state_seconds": dict(dur), "state_counts": dict(Counter(str(s["state"]) for s in series))}


def discover(ha: "HA", out_prefix: str, hours: float) -> int:
    states = {s["entity_id"]: s for s in ha.get("/api/states")}
    climates = [e for e in states if e.startswith("climate.")]
    tpl = ("{% set ns = namespace(o=[]) %}{% for e in " + json.dumps(climates) + " %}"
           "{% set d = device_id(e) %}{% set ns.o = ns.o + [{'climate': e, 'device_id': d, "
           "'name': device_attr(d,'name_by_user') or device_attr(d,'name'), "
           "'manufacturer': device_attr(d,'manufacturer'), 'model': device_attr(d,'model'), "
           "'sw_version': device_attr(d,'sw_version'), 'area': area_name(e), "
           "'entities': device_entities(d) if d else []}] %}{% endfor %}{{ ns.o | tojson }}")
    devices = _template(ha, tpl)
    stats: list[dict[str, Any]] = []
    hist_ids: list[str] = []
    for dev in devices:
        dev["ecobee_like"] = _is_ecobee_like(dev)
        st = states.get(dev["climate"], {})
        attrs = st.get("attributes", {})
        dev["climate_state"] = st.get("state")
        dev["climate_attrs"] = {k: attrs.get(k) for k in CLIMATE_KEYS if k in attrs}
        dev["climate_attr_keys"] = sorted(attrs)
        sib = []
        for eid in dev.get("entities") or []:
            if eid == dev["climate"]:
                continue
            s = states.get(eid, {})
            a = s.get("attributes", {})
            sib.append({"entity_id": eid, "state": s.get("state"), "friendly_name": a.get("friendly_name"),
                        "options": a.get("options"), "device_class": a.get("device_class"),
                        "unit": a.get("unit_of_measurement"), "last_changed": s.get("last_changed")})
        dev["siblings"] = sib
        if dev["ecobee_like"]:
            hist_ids.append(dev["climate"])
            hist_ids += [x["entity_id"] for x in sib if x["entity_id"].startswith("select.")]
        stats.append(dev)
    hist = _history(ha, hist_ids, hours) if hist_ids else {}
    summary = {eid: _summ(ser, hours) for eid, ser in hist.items()}
    paths = {}
    for name, payload in (("discovery", {"captured": now_iso(), "hours": hours, "devices": stats}),
                          ("history", hist), ("history_summary", summary)):
        p = f"{out_prefix}_{name}.json"
        with open(p, "w") as fh:
            json.dump(payload, fh, indent=1, default=str)
        paths[name] = p
    for dev in stats:
        print(f"{dev['climate']}: {dev.get('name')} [{dev.get('manufacturer')} {dev.get('model')}] "
              f"ecobee={dev['ecobee_like']} state={dev['climate_state']} siblings={len(dev['siblings'])}")
    for eid, s in summary.items():
        print(f"  hist {eid}: n={s['n']} counts={s.get('state_counts')}")
    print("wrote:", ", ".join(paths.values()))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="read only; print the planned writes")
    ap.add_argument("--entity", help="climate entity_id (else discovered)")
    ap.add_argument("--out", help="results JSON path")
    ap.add_argument("--poll-s", type=float, default=DEFAULT_POLL_S)
    ap.add_argument("--echo-timeout-s", type=float, default=DEFAULT_ECHO_TIMEOUT_S)
    ap.add_argument("--write-gap-s", type=float, default=DEFAULT_WRITE_GAP_S)
    ap.add_argument("--discover", action="store_true",
                    help="read-only: discover ALL thermostats + siblings + history, write JSON, exit (no writes)")
    ap.add_argument("--hours", type=float, default=24.0, help="--discover history window")
    ap.add_argument("--out-prefix", default="house2_d0b", help="--discover output path prefix")
    args = ap.parse_args(argv)

    url, token = os.environ.get("HA_URL"), os.environ.get("HA_TOKEN")
    if not url or not token:
        print("Set HA_URL and HA_TOKEN in the environment.", file=sys.stderr)
        return 2
    if args.discover:
        return discover(HA(url, token, dry_run=True), args.out_prefix, args.hours)
    if args.write_gap_s < DEFAULT_WRITE_GAP_S:
        print(f"note: --write-gap-s below {DEFAULT_WRITE_GAP_S}s deviates from the plan (P2 >= 2 min apart)")

    probe = Probe(HA(url, token, args.dry_run), args)

    def _on_signal(signum, _frame):
        raise ProbeAbort(f"signal {signal.Signals(signum).name}")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    rc = 1
    interrupted = False
    try:
        rc = probe.run()
    except ProbeAbort as err:
        interrupted = True
        probe.log("abort", reason=str(err))
        print(f"\n!! ABORT: {err} - restoring starting state")
    except Exception as err:  # noqa: BLE001 - any failure must still restore
        interrupted = True
        probe.log("error", reason=str(err))
        print(f"\n!! ERROR: {err} - restoring starting state")
    finally:
        # Ignore further signals while restoring.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        probe.restore(interactive=not interrupted)
        path = write_results(probe)
        print_go_no_go(probe.results)
        print(f"\nResults written to {path}")
    return rc if not interrupted else 1


if __name__ == "__main__":
    sys.exit(main())
