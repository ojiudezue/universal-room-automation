#!/usr/bin/env python3
"""DP drain-target source candidate simulation (v4 — Rev-15 positive-stamp honest).

Rebuilt after Rev-14 re-review flagged the negative-inference gate as ambiguous
(C-CRIT-1) and the v3 sim as tautological (C-HIGH-3):

  C-CRIT-1: Rev-14 gated DP on the negative conjunction
    `not _arbitrage_active AND not _attain_active AND
     _last_inclement_decision.hold_depth == "allow_discharge"`.
    But `_arbitrage_active = False` is written at THREE distinct sites in
    energy_battery.py (verified this session):
      * :3157 — arbitrage WAIT branch (drain branch did NOT run)
      * :4705 — envoy-blind hold early return (drain branch did NOT run)
      * :5274 — drain-fallback branch entry (drain branch DID run)
    Attain-reboot-release (:4118/:4131) and grid-disconnect (:4890) never touch
    `_arbitrage_active` either. Any of these non-drain branches leaves the
    negative conjunction True, so Rev-14's gate would falsely open on WAIT,
    envoy-blind hold, attain-reboot-release, and (via the shadow path before
    the off-peak gate at energy.py:4416) peak-period. The negative conjunction
    cannot distinguish "drain branch ran" from four other cases.

  C-HIGH-3: v3 computed `in_drain_branch` in `mk()` FROM the same predicates
    the Rev-14 candidate consumed:
        in_drain = (not arb) and (not attain) and hold_depth == "allow_discharge"
    So the sim's oracle and the sim's candidate agreed BY CONSTRUCTION on every
    fixture — the scorecard trivially favored C4 (Rev-14). v4 makes
    `in_drain_branch` an INDEPENDENT fixture field set BY HAND per scenario,
    mirroring the production positive stamp at energy_battery.py:5274. The
    Rev-14 candidate then reveals its actual disagreement with the oracle on
    the load-bearing non-drain fixtures.

RULING (operator 2026-08-25, POSITIVE STAMP): DP transitions ONLY when the
positive stamp written by the drain-fallback branch itself is True on the
current tick. Otherwise DP declines with DP_REASON_EMITTER_NOT_DRAINING.

Two oracles preserved from v3 (unchanged):

  ORACLE-A (STRICT EMITTER MIRROR): what the emitter will actually drain to.
  ORACLE-B (RULED FORMULA): max(reserve_soc, current_offpeak_drain_target()).

Under the LIVE config (reserve<=drain) A and B agree; they diverge only on the
inverted config (D4 fixture).

No HA imports — pure arithmetic + boolean model of documented semantics.
"""

# ---- ORACLES ---------------------------------------------------------------

def emitter_drain_floor(s):
    """Emitter's drain floor inside the drain-fallback branch."""
    return max(s["drain_target_d1"], s["drain_target_d2"])


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
    park = emitter_drain_floor(s)
    if s["charging"]:
        park = max(park, s["evse_hold_soc"])
    park = max(park, s["dp_prev_stamp"])
    return ("act", max(s["reserve_soc"], park))


def c2_accessor(s):
    return ("act", emitter_drain_floor(s))


def c3_reserve_max_accessor(s):
    return ("act", max(s["reserve_soc"], emitter_drain_floor(s)))


def c4_rev14_negative_inference_gate(s):
    """Rev-14: negative conjunction over three predicates.

    THIS is the load-bearing bug the sim now exposes honestly. The predicates
    are all satisfied on WAIT / envoy-blind / attain-reboot-release / peak,
    but the drain branch did NOT run in those cases.
    """
    negative_gate_open = (
        (not s["arbitrage_active"])
        and (not s["attain_active"])
        and (s["hold_depth"] == "allow_discharge")
    )
    if not negative_gate_open:
        return ("decline", None)
    return ("act", max(s["reserve_soc"], emitter_drain_floor(s)))


def c5_rev15_positive_stamp_gate(s):
    """Rev-15: positive stamp read directly from the fixture (mirrors the
    production stamp at energy_battery.py:5274, set by the drain-fallback
    branch itself and reset each tick by the coordinator)."""
    if not s["in_drain_branch"]:
        return ("decline", None)
    return ("act", max(s["reserve_soc"], emitter_drain_floor(s)))


CANDIDATES = [
    ("C0 static_knob (pre-fix bug)", c0_static),
    ("C1 compose/park (BUILT, no gate)", c1_compose_park),
    ("C2 accessor alone (no gate)", c2_accessor),
    ("C3 max(reserve, accessor) (Rev-13, no gate)", c3_reserve_max_accessor),
    ("C4 negative-inference gate (Rev-14)", c4_rev14_negative_inference_gate),
    ("C5 positive-stamp gate (Rev-15 proposal)", c5_rev15_positive_stamp_gate),
]


# ---- SCENARIOS -------------------------------------------------------------
# `in_drain_branch` is an INDEPENDENT fixture field (Rev-15 C-HIGH-3 fix).
# It mirrors the production positive stamp at energy_battery.py:5274 — True
# iff the drain-fallback branch actually ran on THIS tick.

def mk(name, *, reserve, d1, d2, hold_depth, arb, attain, evse_hold, prev,
       soc, charging, in_drain_branch, static=80):
    return dict(
        name=name, reserve_soc=reserve, drain_target_d1=d1, drain_target_d2=d2,
        hold_depth=hold_depth, arbitrage_active=arb, attain_active=attain,
        evse_hold_soc=evse_hold, dp_prev_stamp=prev, soc=soc, charging=charging,
        static_knob=static, in_drain_branch=in_drain_branch,
    )


SCENARIOS = [
    # ---- DRAIN-FALLBACK (stamp True — DP should ACT) ----
    mk("D1 excellent, not charging",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=40, charging=False,
       in_drain_branch=True),
    mk("D2 EVSE charging hold@65 (mirror discriminator)",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=65, prev=0, soc=40, charging=True,
       in_drain_branch=True),
    mk("D3 multi-day D+1=15 D+2=25",
       reserve=10, d1=15, d2=25, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=40, prev=0, soc=55, charging=True,
       in_drain_branch=True),
    mk("D4 inverted config reserve15 drain10 (A vs B diverge — safety floor)",
       reserve=15, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=40, prev=0, soc=40, charging=True,
       in_drain_branch=True),

    # ---- NON-DRAIN, Rev-14 negative gate CORRECTLY closes (N1-N4) ----
    mk("N1 arbitrage HOLD/CHARGE",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=True, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False),
    mk("N2 attain latched",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=True, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False),
    mk("N3 inclement partial_hold",
       reserve=10, d1=10, d2=10, hold_depth="partial_hold",
       arb=False, attain=False, evse_hold=40, prev=0, soc=55, charging=True,
       in_drain_branch=False),
    mk("N4 inclement full_hold",
       reserve=10, d1=10, d2=10, hold_depth="full_hold",
       arb=False, attain=False, evse_hold=40, prev=0, soc=55, charging=True,
       in_drain_branch=False),

    # ---- NON-DRAIN, Rev-14 negative gate INCORRECTLY OPENS (N5-N8) ----
    # These are the load-bearing Rev-15 additions. All Rev-14 negative
    # predicates pass (arb=False, attain=False, hold_depth=allow_discharge),
    # but the drain-fallback branch did NOT run — so `in_drain_branch=False`.
    mk("N5 arbitrage WAIT — arb cleared to False at energy_battery.py:3157",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False),
    mk("N6 envoy-blind hold — arb cleared to False at :4705, early return",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False),
    mk("N7 attain-reboot-release — return at :4118/:4131, arb untouched=False",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False),
    mk("N8 peak-period — _get_off_peak_decision not invoked, stamp reset only",
       reserve=10, d1=10, d2=10, hold_depth="allow_discharge",
       arb=False, attain=False, evse_hold=0, prev=0, soc=55, charging=True,
       in_drain_branch=False),
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
    print("DP DRAIN-TARGET CANDIDATE SIMULATION v4 — Rev-15 positive-stamp honest")
    print("Two oracles: A = strict emitter mirror; B = RULED formula max(reserve, accessor).")
    print("`in_drain_branch` is an INDEPENDENT fixture field (Rev-15 C-HIGH-3 fix — no tautology).")
    print("=" * 116)
    totals_a = {n: 0 for n, _ in CANDIDATES}
    totals_b = {n: 0 for n, _ in CANDIDATES}
    for s in SCENARIOS:
        oa = oracle_a_strict_emitter(s)
        ob = oracle_b_ruled_formula(s)
        def tag(o):
            return f"ACT target={o[1]}" if o[0] == "act" else "DECLINE"
        print(f"\n{s['name']}   (in_drain_branch={s['in_drain_branch']}, "
              f"arb={s['arbitrage_active']}, attain={s['attain_active']}, "
              f"hold_depth={s['hold_depth']!r})")
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
    print("Reading the scorecard:")
    print("  * C0 (pre-fix bug) and C1 (BUILT) fail catastrophically.")
    print("  * C2 / C3 fail on all 8 non-drain fixtures (no gate).")
    print("  * C4 (Rev-14 negative-inference) correctly declines N1-N4 but INCORRECTLY")
    print("    ACTS on N5 (arbitrage WAIT), N6 (envoy-blind hold), N7 (attain-reboot-")
    print("    release), and N8 (peak-period) — the four load-bearing Rev-15 fixtures")
    print("    where the negative predicates all pass but the drain branch did NOT run.")
    print("    THIS is C-CRIT-1: the negative conjunction cannot distinguish 'drain")
    print("    branch ran' from these non-drain branches.")
    print("  * C5 (Rev-15 positive-stamp) reads the fixture's independent stamp field")
    print("    directly — mirrors the production stamp at energy_battery.py:5274.")
    print("    Perfect under ORACLE-B (12/12); one D4 divergence under ORACLE-A (the")
    print("    operator-ruled safety floor, no-op under live config where reserve<=drain).")


if __name__ == "__main__":
    main()
