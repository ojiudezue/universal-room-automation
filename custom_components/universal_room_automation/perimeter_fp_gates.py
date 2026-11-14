"""PERIMETER-FP-STREET-NOISE-1 (v5.107.0): pure helpers for the perimeter
false-positive gates (PLANNING_perimeter_fp_build_2026_11.md D1/D3/D5/D6).

No HA imports: everything here is unit-testable on its own. The manager in
perimeter_alert.py owns timing, I/O and the severity block.
"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from typing import Any


def nvr_family(engine: str | None) -> str:
    """Map a leg engine tag to its NVR family (plan §0.6.4).

    frigate / frigate2 -> "frigate"; protect / protect2 -> "protect";
    anything else is its own family (the tag itself), so the legacy
    kill-switch tags keep today's string semantics.
    """
    e = str(engine or "")
    if e.startswith("frigate"):
        return "frigate"
    if e.startswith("protect"):
        return "protect"
    return e


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def zone_slug(name: Any) -> str:
    """Case/punctuation-insensitive zone key (plan D3 rev 2, M3)."""
    s = _SLUG_RE.sub("_", str(name or "").strip().lower())
    return s.strip("_")


# D6: first non-empty line `PERSON: YES|NO|UNSURE` (case-insensitive).
_VERDICT_LINE_RE = re.compile(r"^\s*\**\s*person\s*\**\s*:\s*\**\s*([a-z]+)", re.I)
VERDICT_YES = "YES"
VERDICT_NO = "NO"
VERDICT_UNSURE = "UNSURE"


def parse_vlm_verdict(text: str | None) -> tuple[str | None, str]:
    """Return (description_without_verdict_line, verdict).

    Strict: only a first non-empty line starting `PERSON:` carries a
    verdict; its first word must be yes/no/unsure, anything else is UNSURE.
    A line that does not start with `PERSON:` means no verdict (UNSURE) and
    the text is returned untouched. Never raises.
    """
    try:
        if not text:
            return None, VERDICT_UNSURE
        lines = str(text).splitlines()
        idx = next((i for i, ln in enumerate(lines) if ln.strip()), None)
        if idx is None:
            return None, VERDICT_UNSURE
        m = _VERDICT_LINE_RE.match(lines[idx])
        if not m:
            return str(text).strip() or None, VERDICT_UNSURE
        word = m.group(1).upper()
        verdict = word if word in (VERDICT_YES, VERDICT_NO, VERDICT_UNSURE) else VERDICT_UNSURE
        rest = "\n".join(lines[idx + 1:]).strip()
        return (rest or None), verdict
    except Exception:  # noqa: BLE001
        return None, VERDICT_UNSURE


# PERIMETER-GATE-EVIDENCE D3: second line `LOCATION: PROPERTY|STREET|UNSURE`.
_LOCATION_LINE_RE = re.compile(
    r"^\s*\**\s*location\s*\**\s*:\s*\**\s*([a-z]+)", re.I,
)
LOCATION_PROPERTY = "PROPERTY"
LOCATION_STREET = "STREET"
LOCATION_UNSURE = "UNSURE"


def parse_vlm_verdicts(text: str | None) -> tuple[str | None, str, str]:
    """Return (description, person_verdict, location_verdict).

    PERSON is parsed exactly as ``parse_vlm_verdict`` does (it is called).
    LOCATION is read ONLY from the next non-empty line after the PERSON line
    when that line starts ``LOCATION:``; that line is then removed from the
    description. Any other shape gives location UNSURE and leaves the text
    exactly as ``parse_vlm_verdict`` returns it. Never raises.
    """
    desc, person = parse_vlm_verdict(text)
    try:
        if not desc:
            return desc, person, LOCATION_UNSURE
        lines = str(text).splitlines()
        first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
        if first is None or not _VERDICT_LINE_RE.match(lines[first]):
            return desc, person, LOCATION_UNSURE
        nxt = next(
            (i for i in range(first + 1, len(lines)) if lines[i].strip()), None,
        )
        if nxt is None:
            return desc, person, LOCATION_UNSURE
        m = _LOCATION_LINE_RE.match(lines[nxt])
        if not m:
            return desc, person, LOCATION_UNSURE
        word = m.group(1).upper()
        loc = word if word in (
            LOCATION_PROPERTY, LOCATION_STREET, LOCATION_UNSURE,
        ) else LOCATION_UNSURE
        rest = "\n".join(lines[nxt + 1:]).strip()
        return (rest or None), person, loc
    except Exception:  # noqa: BLE001
        return desc, person, LOCATION_UNSURE


def is_daylight(elevation: Any, min_deg: Any) -> bool:
    """PERIMETER-GATE-EVIDENCE D1: True only for a numeric sun elevation at
    or above ``min_deg``. None / non-numeric / any error -> False (NIGHT):
    a missing sun reading must never permit a demote. Never raises."""
    try:
        if elevation is None or isinstance(elevation, bool):
            return False
        return float(elevation) >= float(min_deg)
    except Exception:  # noqa: BLE001
        return False


class AgreementTracker:
    """D5: per-camera last-N "was the alert corroborated by the other NVR
    family within ±window" outcomes.

    A sample is opened at alert time with the lookback result; any other-
    family fire inside the forward window marks it corroborated; once the
    forward window has elapsed the sample is finalised into the per-camera
    deque. Pure state: the caller supplies `now` and does persistence.
    """

    def __init__(self, window_n: int, pair_window_s: float) -> None:
        self.window_n = max(1, int(window_n))
        self.pair_window_s = float(pair_window_s)
        self._outcomes: dict[str, deque] = {}
        # [cam, alert_ts, alert_family, corroborated]
        self._pending: list[list[Any]] = []

    # -- recording -------------------------------------------------------
    def open_sample(
        self, cam: str, alert_ts: datetime, alert_family: str,
        seen_in_lookback: bool,
    ) -> None:
        self._pending.append([cam, alert_ts, alert_family, bool(seen_in_lookback)])

    def note_fire(self, cam: str, family: str, ts: datetime) -> None:
        for p in self._pending:
            if p[0] != cam or p[3] or family == p[2]:
                continue
            dt = (ts - p[1]).total_seconds()
            if 0 <= dt <= self.pair_window_s:
                p[3] = True

    def finalize_due(self, now: datetime) -> bool:
        """Finalise samples whose forward window elapsed. True if any."""
        changed = False
        keep: list[list[Any]] = []
        for p in self._pending:
            if (now - p[1]).total_seconds() > self.pair_window_s:
                self._outcomes.setdefault(
                    p[0], deque(maxlen=self.window_n)
                ).append(bool(p[3]))
                changed = True
            else:
                keep.append(p)
        self._pending = keep
        return changed

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    # -- reading ---------------------------------------------------------
    def samples(self, cam: str) -> int:
        return len(self._outcomes.get(cam, ()))

    def rate(self, cam: str) -> float | None:
        d = self._outcomes.get(cam)
        if not d:
            return None
        return sum(1 for x in d if x) / len(d)

    def stats(self) -> dict[str, dict[str, Any]]:
        return {
            cam: {"samples": len(d), "agreement_rate": round(self.rate(cam) or 0.0, 3)}
            for cam, d in self._outcomes.items()
        }

    # -- persistence -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"outcomes": {c: [bool(x) for x in d] for c, d in self._outcomes.items()}}

    def load_dict(self, data: Any) -> bool:
        """Load persisted outcomes. Malformed data -> empty tracker, False.

        Outcomes already finalised in memory (between subscription and the
        awaited load) are APPENDED after the loaded ones, never dropped
        (review B-LOW-3)."""
        existing = {c: list(d) for c, d in self._outcomes.items()}
        try:
            raw = (data or {}).get("outcomes", {})
            if not isinstance(raw, dict):
                raise ValueError("outcomes not a dict")
            loaded: dict[str, deque] = {}
            for cam, vals in raw.items():
                if not isinstance(vals, list):
                    raise ValueError("outcome list malformed")
                loaded[str(cam)] = deque(
                    (bool(v) for v in vals if isinstance(v, bool)),
                    maxlen=self.window_n,
                )
            for cam, vals in existing.items():
                loaded.setdefault(cam, deque(maxlen=self.window_n)).extend(vals)
            self._outcomes = loaded
            return True
        except Exception:  # noqa: BLE001
            self._outcomes = {
                c: deque(v, maxlen=self.window_n) for c, v in existing.items()
            }
            return False
