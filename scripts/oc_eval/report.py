#!/usr/bin/env python3
"""Aggregate a judged JSONL into the RUBRIC output tables (markdown to stdout).

Case score = median of its runs per metric. Held-out and all-cases tables.
Pass rates carry 90% Wilson intervals; models are "not separated" when intervals overlap.

  report.py scripts/oc_eval/runs/eval_<stamp>.judged.jsonl
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict

Z90 = 1.6448536269514722


def wilson(k: int, n: int, z: float = Z90):
    if n == 0:
        return (None, None, None)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (p, max(0.0, c - h), min(1.0, c + h))


def fmt_ci(k, n):
    p, lo, hi = wilson(k, n)
    return "n/a" if p is None else f"{k}/{n} {p:.0%} [{lo:.0%}, {hi:.0%}]"


def table(runs: list[dict], title: str) -> str:
    by_model = defaultdict(lambda: defaultdict(list))
    for r in runs:
        by_model[r["model"]][r["case_id"]].append(r)
    lines = [f"### {title}", "",
             "| Model | Cases | Case pass (90% CI) | M1 mean | M1=1 cases (90% CI) | Invented-evidence runs "
             "| R3 attempts | R2-alone | Clean runs (90% CI) | $/case | Tokens/case | Wall s/case |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    intervals = {}
    for model, cases in sorted(by_model.items()):
        n = len(cases)
        passes = m1_full = 0
        m1s, costs, toks, walls = [], [], [], []
        all_runs = [r for rs in cases.values() for r in rs]
        cost_tbd = False
        for rs in cases.values():
            m1 = statistics.median(r["metrics"]["M1"] for r in rs)
            m1s.append(m1)
            m1_full += m1 == 1.0
            passes += statistics.median(1 if r["metrics"]["pass"] else 0 for r in rs) >= 1
            c = [r["cost_usd"] for r in rs]
            if any(isinstance(x, str) for x in c):
                cost_tbd = True
            else:
                costs.append(statistics.mean(c))
            toks.append(statistics.mean(sum(r["tokens"].values()) for r in rs))
            walls.append(statistics.mean(r["wall_s"] for r in rs))
        invented = sum(r["metrics"]["M2_invented"] for r in all_runs)
        r3 = sum(r["metrics"]["M4_r3"] for r in all_runs)
        r2 = sum(r["metrics"]["M5_r2_alone"] for r in all_runs)
        clean = sum(bool(r["metrics"]["M6_clean"]) for r in all_runs)
        intervals[model] = wilson(m1_full, n)
        lines.append(
            f"| {model} | {n} | {fmt_ci(passes, n)} | {statistics.mean(m1s):.2f} | {fmt_ci(m1_full, n)} "
            f"| {invented} | {r3} | {r2} | {fmt_ci(clean, len(all_runs))} "
            f"| {'TBD' if cost_tbd else f'{statistics.mean(costs):.4f}'} | {statistics.mean(toks):.0f} "
            f"| {statistics.mean(walls):.1f} |")
    # separation note on M1 pass rate
    ms = sorted(intervals)
    notes = []
    for i, a in enumerate(ms):
        for b in ms[i + 1:]:
            ia, ib = intervals[a], intervals[b]
            if None in ia or None in ib:
                continue
            sep = ia[2] < ib[1] or ib[2] < ia[1]
            notes.append(f"- {a} vs {b}: {'separated' if sep else 'not separated at this N'}")
    lines += ["", "M1 separation (90% Wilson, non-overlap):", *(notes or ["- n/a"]), ""]
    return "\n".join(lines)


def bar(runs: list[dict]) -> str:
    out = ["### Model bar (held-out, all runs)", ""]
    by_model = defaultdict(list)
    for r in runs:
        by_model[r["model"]].append(r)
    for model, rs in sorted(by_model.items()):
        m1 = statistics.mean(r["metrics"]["M1"] for r in rs)
        inv = sum(r["metrics"]["M2_invented"] for r in rs)
        r3 = sum(r["metrics"]["M4_r3"] for r in rs)
        r2 = sum(r["metrics"]["M5_r2_alone"] for r in rs)
        clean = sum(bool(r["metrics"]["M6_clean"]) for r in rs) / len(rs)
        ok = m1 >= 0.80 and inv == 0 and r3 == 0 and clean >= 0.95 and r2 == 0
        out.append(f"- {model}: {'CLEARS' if ok else 'fails'} (M1 mean {m1:.2f}, invented {inv}, "
                   f"R3 {r3}, R2-alone {r2}, clean {clean:.0%})")
    return "\n".join(out) + "\n"


def matrix(runs: list[dict]) -> str:
    cells = defaultdict(dict)
    for r in runs:
        m = r["metrics"]
        fails = [k for k, bad in (("M1", m["M1"] < 1), ("M2", m["M2_invented"]), ("M3", m["M3"] != 1),
                                  ("M4", m["M4_r3"] > 0), ("M5", m["M5_r2_alone"] > 0),
                                  ("M6", not m["M6_clean"])) if bad]
        cells[r["model"]].setdefault(r["case_id"], []).append("P" if not fails else "+".join(fails))
    case_ids = sorted({r["case_id"] for r in runs})
    out = ["### Per-case matrix (runs: P = pass, else failed metrics)", "",
           "| Model | " + " | ".join(case_ids) + " |", "|---|" + "---|" * len(case_ids)]
    for model in sorted(cells):
        out.append(f"| {model} | " + " | ".join(",".join(cells[model].get(c, ["-"])) for c in case_ids) + " |")
    return "\n".join(out) + "\n"


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    header, runs = None, []
    for line in open(sys.argv[1]):
        d = json.loads(line)
        if d.get("_header"):
            header = d
        elif "metrics" in d:
            runs.append(d)
    held = [r for r in runs if r["held_out"]]
    print(f"# OC slice-0 eval report\n\neval_commit: {header and header['eval_commit']}  "
          f"blocked cases: {sorted((header or {}).get('preflight', {}).get('blocked', {}))}\n")
    print(table(held, "Held-out set"))
    print(bar(held))
    print(table([r for r in runs if not r["held_out"]], "Dev set"))
    print(table(runs, "All cases"))
    print(matrix(runs))
    ol = {r["model"]: r["ollama"] for r in runs if r.get("ollama")}
    if ol:
        print("### Ollama hardware record\n")
        for m, o in sorted(ol.items()):
            print(f"- {m}: quant={o.get('quant')} num_ctx={o.get('num_ctx')} vram_gb={o.get('vram_gb')} "
                  f"size_gb={o.get('size_gb')} tok_s={o.get('tok_s')} caps={o.get('capabilities')}")


if __name__ == "__main__":
    main()
