"""Skill over a trivial baseline for stored predictions.

PREDICT-SCORER-BASELINE-SKILL-1. The accuracy sensors used to report a raw
hit rate only, so a no-skill model read as "94%" (the empty-room base rate)
or as "19%" next-room top-1 (exactly what always guessing the usual room
scores). Every scorer here reports the hit rate NEXT TO the trivial
baseline measured on the SAME rows, and the difference (skill).

- Next room: baseline = always guess the person's most common actual room
  in the scored rows (per person; pooled rows sum the per-person hits).
  Measured on the same rows it scores, so the baseline is slightly
  optimistic: skill here is conservative.
- Occupancy probability: baseline = always predict the base rate of the
  same rows (Brier) / always predict the majority outcome (hit rate).

Pure: no HA imports. One definition, shared by the accuracy sensors, the
Bayesian accuracy stats and the Optimization next-room clause (plan D7), so
there is never a second baseline.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable, Sequence

# (person_id, predicted_top, actual_room, prediction_timestamp_iso)
NextRoomRow = tuple


def _parse_ts(raw) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def dedupe_flaps(rows: Sequence[NextRoomRow], window_s: float) -> list:
    """Drop a row when the SAME person's next row (in the given order, which
    is write order) is less than ``window_s`` seconds later by its
    ``prediction_timestamp``. Rows with an unparseable timestamp are kept.
    ``window_s <= 0`` returns the rows unchanged."""
    rows = list(rows)
    if not window_s or window_s <= 0:
        return rows
    keep = [True] * len(rows)
    last_idx: dict = {}
    for i, row in enumerate(rows):
        person = row[0]
        j = last_idx.get(person)
        if j is not None:
            a, b = _parse_ts(rows[j][3]), _parse_ts(row[3])
            if a is not None and b is not None:
                try:
                    gap = (b - a).total_seconds()
                except TypeError:  # mixed naive / aware
                    gap = None
                if gap is not None and gap < window_s:
                    keep[j] = False
        last_idx[person] = i
    return [r for r, k in zip(rows, keep) if k]


def next_room_skill(rows: Iterable[NextRoomRow]) -> dict:
    """Top-1 hit rate, the usual-room baseline on the same rows, and skill.

    Returns ``{"n", "top1_pct", "baseline_top1_pct", "skill_pct"}``; the
    three percentages are ``None`` when there are no rows.
    """
    rows = list(rows)
    n = len(rows)
    if n == 0:
        return {"n": 0, "top1_pct": None, "baseline_top1_pct": None,
                "skill_pct": None}
    hits = sum(1 for r in rows if r[1] is not None and r[1] == r[2])
    per_person: dict = {}
    for r in rows:
        per_person.setdefault(r[0], Counter())[r[2]] += 1
    base_hits = sum(c.most_common(1)[0][1] for c in per_person.values())
    top1 = hits / n * 100.0
    base = base_hits / n * 100.0
    return {
        "n": n,
        "top1_pct": round(top1, 1),
        "baseline_top1_pct": round(base, 1),
        "skill_pct": round(top1 - base, 1),
    }


def occupancy_skill(pairs: Iterable[tuple[float, int]]) -> dict:
    """Brier and hit rate of probability predictions vs the base rate.

    ``pairs``: ``(predicted_probability, actual 0/1)``. Returns
    ``{"n", "base_rate", "base_rate_brier", "brier_skill",
    "baseline_hit_rate", "hit_rate_skill_pct"}``. ``brier_skill`` is
    ``1 - brier / base_rate_brier`` (> 0 = better than the constant);
    ``None`` when the base-rate Brier is 0 (all outcomes equal).
    """
    pairs = [(float(p), int(a)) for p, a in pairs]
    n = len(pairs)
    if n == 0:
        return {"n": 0, "base_rate": None, "base_rate_brier": None,
                "brier_skill": None, "baseline_hit_rate": None,
                "hit_rate_skill_pct": None}
    base = sum(a for _, a in pairs) / n
    brier = sum((p - a) ** 2 for p, a in pairs) / n
    base_brier = sum((base - a) ** 2 for _, a in pairs) / n
    hits = sum(1 for p, a in pairs if (p > 0.5) == (a == 1))
    majority = 1 if base > 0.5 else 0
    base_hits = sum(1 for _, a in pairs if a == majority)
    return {
        "n": n,
        "base_rate": round(base, 4),
        "base_rate_brier": round(base_brier, 4),
        "brier_skill": (
            round(1.0 - brier / base_brier, 4) if base_brier > 0 else None
        ),
        "baseline_hit_rate": round(base_hits / n * 100.0, 1),
        "hit_rate_skill_pct": round((hits - base_hits) / n * 100.0, 1),
    }
