# D7 — Synthesis and leverage ranking

Derived entirely from D1, D2, D3, D4, D6. D5 was not run (see `D5_NOT_RUN.md`). Every number below
traces to one of those artifacts.

---

## The answer: which single fix removes the most noise

**Add four symbols to the AST-slice loader keep-set. It removes 65 of the 158 — 41% — and it is one
change.**

Three files build a namespace for AST-sliced production code and hand it to
`quality/tests/_ast_slice_guard.py`, which refuses to proceed if the sliced code loads a name the
namespace does not carry. All three currently raise the **identical** error:

```
RuntimeError: AST-slice namespace missing symbols the sliced code loads
  — add stubs to the loader (or extend the keep-set):
  ['_CONF_CHATTER_BURST_K', '_CONF_CHATTER_MODE', '_CONF_CHATTER_T_FLOOR_S', '_hvac_tunable_apply']
```

| file | baseline failures | reported as |
|---|---|---|
| `quality/tests/test_part2_ec_hc_writeback.py` | 38 | FAILED |
| `quality/tests/test_cm_reload_suppression.py` | 17 | ERROR (all 17 of the suite's errors) |
| `quality/tests/test_reload_watchdog_hazard.py` | 10 | FAILED |
| **total** | **65** | **41% of the 158** |

The cause is ordinary drift, not a design flaw: the v5.85.0 chatter cycle added `CONF_CHATTER_*`
constants and a `_hvac_tunable_apply` helper to code these three loaders slice, and nobody extended
their keep-sets. The guard did exactly its job — it refused to run against an incomplete namespace and
said precisely what to add. Nobody read the message.

**The falsifier, stated in advance:** if adding those four stubs does not turn all 65 green, this
recommendation is wrong and the leverage moves to order-pollution (60 ids, second place). The cost of
testing it is three files and roughly a dozen lines.

**Second place, and worth doing next:** order pollution, 60 ids, of which 15 are already traced to a
single donor file (below). **Third:** the Python-version mismatch, 10 ids, which is a `pyenv` line
rather than a code change. **Distant fourth:** source-text tests, ~13 ids.

---

## Where the plan's predictions were overruled by the data

The plan wrote its predictions in advance so the numbers could contradict them. Four did.

**1. "The 158 is IDENTICAL on develop and on feature branches."** Half true, and the false half
matters. Across the eight full-suite captures the totals were 141/141/141/141/143/143/143/**154**
failed. The 158 is the *intersection* — a stable core that every run's failing set contains as a
subset — but 15 further ids appear in one run or another. Set-diffing a branch against "158" will
show 13 spurious regressions on some runs. The real invariant to diff against is the intersection,
and it must be recomputed, not assumed.

**2. "If D1 shows one bucket dominates, the leverage answer is D2."** One bucket does nearly
dominate — B3 order-pollution at 60 — but it is not the biggest lever, because 65 of the remaining 98
share a *single* root cause that is cheaper to fix than any pollution work. The plan's decision rule
selected the wrong deliverable. Bucket size was the wrong metric; **failures-per-fix** was the right
one.

**3. The seeded donor mechanism is right; the seeded donor file is not.** The brief seeds
`test_ac_ramp_pipeline_hardening.py` at "71/71 alone, 11 failed in suite". Measured: **71/71 alone,
confirmed** — and **zero** in-suite failures. That file appears in the failing set of none of the eight
captured runs. But the *mechanism* the brief describes — a leaked `async_call_later` replacement — was
confirmed in a neighbouring file (below). The hypothesis was sound and the exhibit was wrong.

**4. Source-text tests are not the noise problem.** D3 found **341** tests whose assertions bind to
production source text, in 82 files — about **3.6%** of the suite. Only ~13 of them are in the 158.
**96% of source-text tests are currently green.** Worse for the theory: all three founding exhibits
already carry in-tree fixes dated 2026-08-22 and 2026-08-23. Bug Class #62 is real, and its individual
failures are expensive to debug, but as a noise source it is the smallest of the four candidates by an
order of magnitude.

---

## The order-pollution mechanism, named and reproduced

The plan asked for a donor two-file drill and specified both outcomes as reportable. The first ten
donor candidates — every file that empties a process-global `homeassistant*` `__path__` — produced
**zero** victim failures across 50 pairs. That looked like the "diffuse" outcome.

It was not diffuse. An alphabetical-prefix bisect on the largest victim isolated a single file:

```
VICTIM  quality/tests/test_chatter_detector.py            (15 baseline failures)
PREFIX  43 files up to and including the victim           -> 15 victim failures
bisect  21 -> 10 -> 5 -> 2 -> 1
CULPRIT quality/tests/test_ac_ramp_master_option_persistence.py
```

Confirmed as a two-file selection — donor first, victim second — reproducing **all 15**:

```
ModuleNotFoundError: No module named 'homeassistant.helpers.entity_registry';
                     'homeassistant.helpers' is not a package
TypeError: 'NoneType' object is not callable
```

The guilty line is `test_ac_ramp_master_option_persistence.py:75`:

```python
_mods = {
    "homeassistant.helpers": {},                                   # <- no __path__ at all
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),  # <- the seeded leak, exactly
        ...
    },
    ...
}
for _n, _a in _mods.items():
    sys.modules.setdefault(_n, _mock_module(_n, **_a))             # line 75 — process-global
```

Two distinct leaks from one block. `homeassistant.helpers` is installed as a plain module with no
`__path__`, so every later `import homeassistant.helpers.entity_registry` fails with "is not a
package". And `async_call_later` is replaced with a `MagicMock` — the brief's seeded mechanism,
verbatim, one file over from where it was expected.

Two properties make this class hard to find and explain why the naive drill missed it:

- **It fires at COLLECTION, not at test time.** `sys.modules.setdefault(...)` runs at module import.
  Pytest imports every selected file before running any test, so contamination is decided by
  *collection order*, which is alphabetical, and is independent of execution order.
- **`setdefault` means first writer wins.** Whether a file is donor or victim depends only on its
  alphabetical position relative to the others in the selection. That is why an arbitrary two-file
  pairing reproduces nothing and the correct pairing reproduces everything.

D6 quantifies the surface this mechanism runs on: **95** `__path__ = []` sites in 49 files, **18** of
them on process-global `homeassistant*` names; **85** `<mod>.__path__[idx]` reads in 67 files; **33** of
those reads in 18 files repair the stub on *presence* rather than *content* and will raise `IndexError`
on an emptied stub. The repo already documents the mechanism against itself — the comment at
`test_hvac_vacancy_sweep_manual_on_guard.py:186` reads *"otherwise sibling test files that do
`_ura.__path__[0]` will trip."*

A per-file bisect of the remaining victims was started and is the obvious follow-up; each victim costs
roughly 14 subset runs.

---

## Two classes the plan's model does not contain

**Reverse pollution — 49 failures that exist ONLY when a file runs alone.** Twenty-one files fail alone
and pass in the suite (`test_v4513_gap_fixes.py` −9, `test_perimeter_burst_demotion.py` −8,
`test_data_pipeline.py` −7, `test_v4514_anomaly_visibility.py` −5, …). These tests are green only because
a sibling ran first and left a stub behind. They are exactly as fragile as the 60 B3 ids, in the opposite
direction, and they are **invisible to the 158 baseline entirely** — which means the baseline understates
the coupling. Several files are simultaneously donor and victim.

**The test host is on the wrong Python.** `custom_components/.../switch.py:512` uses PEP-604
`fire_signal: str | None` in a class-body signature with no `from __future__ import annotations`. The
annotation is evaluated at class-definition time, and the host runs **Python 3.9.6** (macOS
CommandLineTools), so importing the module raises
`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`. Home Assistant runs 3.12/3.13,
so **this is not a production defect** — it is 7 baseline failures caused purely by the local toolchain
(10 counting the other B4 rows). It also reframes the whole test architecture: the elaborate
`sys.modules` stubbing and AST-slicing machinery exists in part because real production modules
*cannot be imported* on this interpreter. Running the suite on the HA-matched Python is a one-line
change with an unusually large blast radius, and should be evaluated before any structural work.

---

## Filled leverage table

| candidate | noise removed | as % of 158 | cost | risk ingredients |
|---|---|---|---|---|
| **Extend the AST-slice keep-set with 4 symbols** | **65** | **41%** | 3 files, ~12 lines | none — the guard names the exact symbols |
| Fix order-pollution donors (D2/D6) | up to 60 | 38% | 1 donor found; ~14 subset runs per remaining victim to isolate the rest | shared-fixture / collection-order design |
| Run the suite on the HA-matched Python | 10 | 6% | one interpreter change | may surface *new* failures previously masked by 3.9 import errors |
| Triage the 16 genuine B1 defects | 16 | 10% | one cycle each | real product work, not noise removal |
| Convert source-text tests (D3) | ~13 | 8% | per-test rewrite ×13 | 341-test population, 96% currently green |
| Anti-hollow anchor discipline (D4) | 0 existing | 0% | ongoing policy | prevents future defects; removes no current noise |

Note the last row. D4's hollow rate is **8 of 13 evaluable sites (62%)** — the worst single number in
this cycle, and the fifth consecutive cycle to show it — but it removes **zero** of the 158. It is a
defect-prevention problem, not a noise problem, and conflating the two is how it keeps getting
deprioritised. It needs its own card on its own merits.

---

## Recommended follow-up cards

1. **`TEST-ASTSLICE-KEEPSET-1`** (do first) — add `_CONF_CHATTER_BURST_K`, `_CONF_CHATTER_MODE`,
   `_CONF_CHATTER_T_FLOOR_S`, `_hvac_tunable_apply` to the loader namespaces in
   `test_part2_ec_hc_writeback.py`, `test_cm_reload_suppression.py`, `test_reload_watchdog_hazard.py`.
   Acceptance: those three files go green alone; the recomputed baseline drops from 158 to 93.
   *Discriminating:* if fewer than 65 clear, the shared-root-cause reading is wrong.
2. **`TEST-COLLECTION-STUB-ISOLATION-1`** — the `sys.modules` contamination surface. First deliverable is
   finishing the per-victim bisect (the harness is written); second is deciding between fixing the 33
   presence-based repairs in place and moving package stubbing into a session fixture that restores
   `sys.modules` per file. Includes the 49 reverse-pollution failures.
3. **`TEST-PYTHON-VERSION-1`** — pin the test interpreter to the HA-matched version. Cheap, but expect it
   to reveal failures that 3.9 import errors were hiding; measure before and after.
4. **`TEST-WIRE-IN-ANCHOR-MANDATE-1`** — the 62% hollow rate. Prevention, not cleanup. Owns the D4 table.
5. **`TEST-WEDGE-1`** (gated, D5) — starts at `test_memory_compactor.py`, which wedges alone in 1.15 s of
   test time. No full-suite run needed to begin.

No card proposes deleting or skipping a test.
