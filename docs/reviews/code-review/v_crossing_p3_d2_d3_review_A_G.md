# Review A + G: crossing vision P3-D2 + P3-D3 (00cd94cef, base 056c69993)

Verdict: **SHIP after M1** (FIX-REQUIRED if the operator wants no regression for resolved crossings).

Tests: 4 cycle files, 350 passed. The tree guard flagged `test_person_awareness_layer_guard.py`, which mutates `crossing_vision.py` in place. That behaviour predates this diff (L2).

| Sev | Where | Finding |
|---|---|---|
| MEDIUM M1 | crossing_vision.py:962-454 (cap/busy gates) | Deviation 3 confirmed. Ambiguous requests hold slots (MAX_CONCURRENT=2, each waits about E+25 s and then calls for about 13 s) and count against the cap. During a yard-walker burst (26 ambiguous crossings on 11-16, clustered at 60 s) a resolved crossing can fall to skipped_busy and get the camera term instead of the vision term. That is worse than the pre-P3 behaviour. Volume: about 54 calls/day against a cap of 93, so cap pressure is low and only bursts bite. Fix in this cycle with a cheap rule: an ambiguous request needs `_pending_primaries() < MAX-1` and `calls+waiting < cap - reserve`. Correct the plan :807. Bug class: risk reduction changed what is delivered. |
| LOW L1 | crossing_vision.py:520-525 | The late-joiner rule now keys on `term_direction`. When the primary built no term (n=None), a same-direction joiner now gets its own term. I judge this more correct, but it is a behaviour change, so record it. |
| LOW L2 | test_person_awareness_layer_guard.py:527 | Pre-existing in-place source drills. Move them to `_mutation_sandbox`. |
| LOW L3 | :489 residual 5 | On the event_clip route the second request overwrites `_waiting_by_event`, so the first request fires late at its 120 s timeout. It still fires. Accepted residual. |

Cleared:
- **Deviation 1:** CONTRACT §2.3, §4.2 and G3 sanctioned vision attributes. The two AMENDED readers filter on `role=="exit_backfilled"` (sensor.py:5171, :5312).
- **Deviation 2:** confirmed in the installed llmvision `providers.py:730` (`strict: True`). The anyOf-null fields are valid strict schema. The parser maps missing, null or out-of-enum values to unclear/None and never changes outcome (:330-335).
- **Deviation 4:** clean.
- **INV-DIR-GATE:** `cluster_terms` drops non-entry/exit members (crossing_ledger.py:187). No production reader of `vision_direction` exists outside the module.
- **Window arithmetic:** floor(E-5) to ceil(E+15), fired at E+25. When that time cannot be reached within 120 s, the request falls back to the event clip. A long event uses the window only once it is complete.
- **`_yield_to_repeat`:** no await between the check and `inflight += 1`, so the in-flight bound holds.
- **Short-clip path:** preserved (`video_file` is generic for both routes).
- **Knobs:** all on rung 1, each with a stated off value.

G: the change delivers reps toward census and arrivals accuracy (it watches and records, with direction held behind the gate), in line with "build, hold, measure". The ledger and away logic are untouched, so away stays fast-acting. The window route starts the call sooner than the event end does. Camera selection uses the event payload, not a name guess. No hard constraint is broken. The one place where a risk reduction changes what is delivered is M1.
