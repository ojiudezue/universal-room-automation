#!/usr/bin/env python3
"""DP drain-target source candidate simulation (v6 — Rev-17 honest emitted-value).

Rev-17 delta vs v5 (Rev-16): `emitted_drain_target` is now an INDEPENDENT hand-
set fixture field. In v5 it was derived from `emitter_drain_floor(s)` — the same
function ORACLE-A uses — making C6 (Rev-16 value-stamp) equivalent to ORACLE-A on
the value axis by construction (a tautology). v6 breaks the derivation: each
fixture states the emitted value the emitter is EXPECTED to emit for that
scenario, independently of any oracle formula. C6's value-axis score is now real
evidence, not construction.

Rev-16 correctness (preserved at Rev-17):
  D-HIGH-1 (partial_hold clamp gap): partial_hold reaches the drain-fallback
    branch (branch entry at :5269; :4900 comment "partial_hold/allow_discharge
    fall through"; only full_hold short-circuits at :4903) and the emitter
    clamps `drain_target` up to `effective_reserve` at :5322. Rev-15's DP-side
    re-derivation via `max(reserve_soc, current_offpeak_drain_target())` omits
    this clamp — emits max(10,10)=10 where the emitter emits max(10,50)=50.

  D-HIGH-2 (in-tick, pre-await, two-caller race across the awaits at
    :5587-5588). Sim can't model concurrency but can model the mechanism-level
    distinction (pre-await lexical capture vs post-await attribute read); C6
    models the safe path.

  D2-HIGH-1 (Rev-16 cross-tick mailbox leak): the OTHER determine_mode caller
    (_evaluate_battery at :6185) can refill the attribute between two
    _decision_cycle_body ticks. Sim can't model cross-tick sequencing either
    but its C6 modelling reads only `emitted_drain_target` — a per-tick
    property that the production code guarantees via the Rev-17 PRODUCER
    ENTRY-RESET at determine_mode:4590. The cross-tick anchor is in the test
    suite (T-cross-tick-reset drives REAL determine_mode); the sim covers the
    value-axis dimension.

RULING (operator 2026-08-25, VALUE STAMP + THREADED LOCAL + PRODUCER ENTRY-RESET):
DP consumes the value the emitter actually emitted this tick, VERBATIM. Written
by the drain-fallback branch AFTER the partial_hold clamp at :5322-5323; cleared
at the top of every determine_mode call by the entry-reset at :4590; captured by
the coordinator into a stack-local BEFORE any await, threaded as a keyword
parameter into `_dp_decision_tick` and `_run_dp_shadow_eval`. No DP-side re-
derivation, no attribute re-read.

Two oracles preserved (with the partial_hold clamp applied):

  ORACLE-A (STRICT EMITTER MIRROR): what the emitter will actually drain to,
    including the partial_hold clamp at energy_battery.py:5322.
  ORACLE-B (RULED FORMULA): max(reserve_soc, emitter_drain_floor). Under the
    live config (reserve <= drain) A and B agree; they diverge only on the
    inverted config (D4 fixture).

No HA imports — pure arithmetic + boolean model of documented semantics.
"""

# ---- ORACLES ---------------------------------------------------------------

def emitter_drain_floor(s):
    """Emitter's post-clamp drain floor inside the drain-fallback branch.

    Reflects the actual arithmetic at energy_battery.py:5306-5322:
      1. base = max(drain_target(d1_class), drain_target(d2_class))   -- :5306-5313
      2. if hold_depth == "partial_hold": base = max(base, effective_reserve)  -- :5321-5322
    """
    base = max(s["drain_target_d1"], s["drain_target_d2"])
    if s["hold_depth"] == "partial_hold":
        base = max(base, s["effective_reserve"])
    return base


def oracle_a_strict_emitter(s):
    if s["in_drain_branch"]:
        return ("act", emitter_drain_floor(s))
    return ("decline", None)


def oracle_b_ruled_formula(s):
    if s["in_drain_branch"]:
        return ("act", max(s["reserve_soc"], emitter_drain_floor(s)))
    return ("decline", None)


# ---- CANDIDATES ------------------------------------------------------------

def c0_static(s):
    return ("act", s["static_knob"])


def c1_compose_park(s):
    # BUILT candidate does NOT know about the partial_hold clamp.
    park = max(s["drain_target_d1"], s["drain_target_d2"])
    if s["charging"]:
        park = max(park, s["evse_hold_soc"])
    park = max(park, s["dp_prev_stamp"])
    return ("act", max(s["reserve_soc"], park))


def c2_accessor(s):
    # `current_offpeak_drain_target()` — does NOT apply partial_hold clamp.
    return ("act", max(s["drain_target_d1"], s["drain_target_d2"]))


def c3_reserve_max_accessor(s):
    # Rev-13 formula — does NOT apply partial_hold clamp.
    return ("act", max(s["reserve_soc"],
                       max(s["drain_target_d1"], s["drain_target_d2"])))


def c4_rev14_negative_inference_gate(s):
    """Rev-14: negative conjunction over three predicates + accessor re-derive.

    The negative predicates cannot distinguish "drain branch ran" from four
    non-drain branches (N5-N8). ALSO does not apply partial_hold clamp: on N3
    with hold_depth != "allow_discharge", the negative gate INCORRECTLY DECLINES
    (partial_hold reaches the drain branch — should ACT with the clamped value).
    """
    negative_gate_open = (
        (not s["arbitrage_active"])
        and (not s["attain_active"])
        and (s["hold_depth"] == "allow_discharge")
    )
    if not negative_gate_open:
        return ("decline", None)
    return ("act", max(s["reserve_soc"],
                       max(s["drain_target_d1"], s["drain_target_d2"])))


def c5_rev15_bool_stamp_plus_rederive(s):
    """Rev-15: positive BOOL stamp gate + DP-side re-derivation via
    max(reserve_soc, current_offpeak_drain_target()).

    Gate is exhaustive by construction (correctly declines on all non-drain).
    But the re-derivation on the DP side omits the partial_hold clamp at :5322,
    so on N3 (partial_hold, drain branch DOES run) it emits the un-clamped
    value. THIS is D-HIGH-1 exposed.
    """
    if not s["in_drain_branch"]:
        return ("decline", None)
    return ("act", max(s["reserve_soc"],
                       max(s["drain_target_d1"], s["drain_target_d2"])))


def c6_rev17_value_stamp(s):
    """Rev-16 mechanism, Rev-17 sim honesty: DP consumes the emitter's actual
    emitted floor VERBATIM. In production this is `_offpeak_drain_branch_target`
    written by the drain-fallback branch after the partial_hold clamp at
    :5322-5323 (and cleared at determine_mode:4590 entry-reset), captured into a
    stack-local by the coordinator before any await, threaded into
    `_dp_decision_tick` as a keyword parameter. No re-derivation, no re-read.

    Modelled here by reading the INDEPENDENT hand-set fixture field
    `emitted_drain_target`. Rev-17 fix (D-pass finding on Rev-16 sim v5):
    `emitted_drain_target` is now hand-set per fixture, NOT derived from
    `emitter_drain_floor(s)`. This breaks the value-axis tautology C6≡ORACLE-A
    and makes C6's ORACLE-A score real evidence rather than construction.
    """
    emitted = s["emitted_drain_target"]
    if emitted is None:
        return ("decline", None)
    return ("act", int(emitted))


CANDIDATES = [
    ("C0 static_knob (pre-fix bug)", c0_static),
    ("C1 compose/park (BUILT, no gate)", c1_compose_park),
    ("C2 accessor alone (no gate)", c2_accessor),
    ("C3 max(reserve, accessor) (Rev-13, no gate)", c3_reserve_max_accessor),
    ("C4 negative-inference gate (Rev-14)", c4_rev14_negative_inference_gate),
    ("C5 bool-stamp + re-derive (Rev-15)", c5_rev15_bool_stamp_plus_rederive),
    ("C6 value-stamp (Rev-17 proposal)", c6_rev17_value_stamp),
]


# ---- SCENARIOS -------------------------------------------------------------
# INDEPENDENT hand-set fixture fields:
#   in_drain_branch       — True iff the drain-fallback branch actually ran.
#                            Set BY HAND per scenario (Rev-15 C-HIGH-3 closure).
#   effective_reserve     — inclement-elevated floor (:5322 clamp input).
#                            Equals reserve_soc under allow_discharge/full_hold;
#                            elevated under partial_hold.
#   emitted_drain_target  — the emitter's ACTUAL post-clamp emitted floor for
#                            this scenario. Hand-set (Rev-17 fix; Rev-16 derived
#                            this from emitter_drain_floor(s), a tautology on the
#                            value axis for C6). None on non-drain fixtures.

def mk(name, *, reserve, d1, d2, hold_depth, arb, attain, evse_hold, prev,
       soc, charging, in_drain_branch, emitted_drain_target,
       effective_reserve=None, static=80):
    """All three independent fixture fields (in_drain_branch,
    effective_reserve, emitted_drain_target) MUST be passed explicitly per
    scenario. `emitted_drain_target` has no default and must be stated
    (Rev-17 anti-tautology discipline).
    """
    if effective_reserve is None:
        effective_reserve = reserve
    return dict(
        name=name, reserve_soc=reserve, drain_target_d1=d1, drain_target_d2=d2,
        hold_depth=hold_depth, arbitrage_active=arb, attain_active=attain,
        evse_hold_soc=evse_hold, dp_prev_stamp=prev, soc=soc, charging=charging,
        static_knob=static, in_drain_branch=in_drain_branch,
        effective_reserve=effective_reserve,
        emitted_drain_target=emitted_drain_target,
    )


SCENARIOS = [
    # ---- DRAIN-FALLBACK (branch ran — DP should ACT with the emitter's floor) ----
    # emitted_drain_target = the value the emitter is EXPECTED to emit for this
    # scenario, hand-set independently of any oracle/candidate formula.
    mk("D1 allow_discharge, not charging",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=40, charging=False,
       in_drain_branch=True, emitted_drain_target=10),
    mk("D2 EVSE charging hold@65 (mirror discriminator)",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=65, prev=0, soc=40, charging=True,
       in_drain_branch=True, emitted_drain_target=10),
    mk("D3 multi-day D+1=15 D+2=25 (allow_discharge)",
       reserve=10, d1=15, d2=25, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=40, prev=0, soc=55, charging=True,
       in_drain_branch=True, emitted_drain_target=25),
    mk("D4 inverted config reserve15 drain10 (A vs B diverge — safety floor)",
       reserve=15, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=40, prev=0, soc=40, charging=True,
       in_drain_branch=True, emitted_drain_target=10),

    # ---- NON-DRAIN, Rev-14 negative gate CORRECTLY closes (N1, N2, N4) ----
    mk("N1 arbitrage HOLD/CHARGE",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=True, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False, emitted_drain_target=None),
    mk("N2 attain latched",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=True, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False, emitted_drain_target=None),

    # ---- DRAIN-FALLBACK, partial_hold path (Rev-16 CORRECTION of Rev-15 N3) ----
    # partial_hold FALLS THROUGH (:4900 comment) so the drain branch DOES run.
    # The clamp at :5322 raises drain_target up to effective_reserve (=50 for a
    # watch-uncorroborated overnight). Rev-15 bool-stamp opens the gate correctly
    # but Rev-15 DP-side re-derivation omits the clamp → wrong value. Rev-16
    # value-stamp carries the post-clamp 50 verbatim. THIS is D-HIGH-1.
    mk("N3 inclement partial_hold (drain branch DOES run, clamp to 50)",
       reserve=10, d1=10, d2=10, hold_depth="partial_hold",
       arb=False, attain=False, evse_hold=40, prev=0, soc=55, charging=True,
       in_drain_branch=True, effective_reserve=50, emitted_drain_target=50),

    mk("N4 inclement full_hold (short-circuit at :4903 — drain branch skipped)",
       reserve=10, d1=10, d2=10, hold_depth="full_hold",
       arb=False, attain=False, evse_hold=40, prev=0, soc=55, charging=True,
       in_drain_branch=False, emitted_drain_target=None),

    # ---- NON-DRAIN, Rev-14 negative gate INCORRECTLY OPENS (N5-N8) ----
    mk("N5 arbitrage WAIT — arb cleared to False at energy_battery.py:3157",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False, emitted_drain_target=None),
    mk("N6 envoy-blind hold — arb cleared to False at :4705, early return",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False, emitted_drain_target=None),
    mk("N7 attain-reboot-release — return at :4118/:4131, arb untouched=False",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False, emitted_drain_target=None),
    mk("N8 peak-period — determine_mode returns before off-peak branch",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False, emitted_drain_target=None),
]


def score(oracle_out, cand_out):
    o_dec, o_tgt = oracle_out
    c_dec, c_tgt = cand_out
    if o_dec != c_dec:
        return False
    if o_dec == "act" and int(c_tgt) != int(o_tgt):
        return False
    return True


def main():
    print("=" * 116)
    print("DP DRAIN-TARGET CANDIDATE SIMULATION v6 — Rev-17 hand-set emitted_drain_target")
    print("Two oracles: A = strict emitter mirror (with :5322 partial_hold clamp);")
    print("             B = RULED formula max(reserve, emitter_drain_floor).")
    print("`in_drain_branch`, `effective_reserve`, `emitted_drain_target` are INDEPENDENT hand-set fixture fields.")
    print("=" * 116)
    totals_a = {n: 0 for n, _ in CANDIDATES}
    totals_b = {n: 0 for n, _ in CANDIDATES}
    for s in SCENARIOS:
        oa = oracle_a_strict_emitter(s)
        ob = oracle_b_ruled_formula(s)
        def tag(o):
            return f"ACT target={o[1]}" if o[0] == "act" else "DECLINE"
        print(f"\n{s['name']}   (in_drain_branch={s['in_drain_branch']}, "
              f"hold_depth={s['hold_depth']!r}, effective_reserve={s['effective_reserve']}, "
              f"emitted_drain_target={s['emitted_drain_target']})")
        print(f"  ORACLE-A {tag(oa)}    ORACLE-B {tag(ob)}    soc={s['soc']}")
        for n, fn in CANDIDATES:
            c = fn(s)
            a_ok = score(oa, c)
            b_ok = score(ob, c)
            if a_ok:
                totals_a[n] += 1
            if b_ok:
                totals_b[n] += 1
            c_dec, c_tgt = c
            tag_c = f"ACT target={c_tgt}" if c_dec == "act" else "DECLINE"
            mark = f"A={'OK' if a_ok else 'XX'} B={'OK' if b_ok else 'XX'}"
            print(f"    {mark}  {n:<48} -> {tag_c}")
    n_sc = len(SCENARIOS)
    print("\n" + "=" * 116)
    print(f"SCORECARD (out of {n_sc}): ORACLE-A strict emitter mirror  |  ORACLE-B RULED formula")
    for n, _ in CANDIDATES:
        print(f"  A={totals_a[n]}/{n_sc}   B={totals_b[n]}/{n_sc}   {n}")
    print("=" * 116)
    print("Reading the scorecard (Rev-17):")
    print("  * C0 (pre-fix bug) and C1 (BUILT) fail catastrophically.")
    print("  * C2 (accessor, no gate): A=4/12, B=3/12 — acts everywhere; misses N3 clamp;")
    print("    ties ORACLE-A on D4 (=10 mirrors emitter) but diverges from ORACLE-B (10 vs 15).")
    print("  * C3 (max(reserve, accessor), no gate): A=3/12, B=4/12 — mirror of C2 on D4.")
    print("  * C4 (Rev-14 negative-inference): correctly declines N1/N2/N4;")
    print("    INCORRECTLY DECLINES N3 (partial_hold clamp closes the gate wrongly);")
    print("    INCORRECTLY ACTS on N5-N8.")
    print("  * C5 (Rev-15 bool-stamp + re-derive): A=10/12, B=11/12. Declines all 7 non-drain")
    print("    correctly; exact on D1/D2/D3; INCORRECTLY EMITS un-clamped value on N3")
    print("    (emitter emits 50, C5 emits max(reserve=10, max(d1=10,d2=10))=10). This is")
    print("    D-HIGH-1 exposed.")
    print("  * C6 (Rev-17 value-stamp) reads `emitted_drain_target` — HAND-SET per fixture")
    print("    independent of any oracle formula (Rev-17 anti-tautology). Mirrors the")
    print("    production stamp at :5322-5323, cleared at determine_mode:4590 entry-reset.")
    print("    A=12/12 (strict emitter mirror, real evidence — not tautology).")
    print("    B=11/12 — D4 divergence under RULED formula (operator-ruled safety floor,")
    print("    live NO-OP under reserve<=drain).")


if __name__ == "__main__":
    main()
