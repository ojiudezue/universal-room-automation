# URA v5.72.0 — FanPolicyOracle complete (FAN-LAYER-2) + deterministic test suite (SUITE-HYGIENE-1)

Two cycles, one deploy.

## FAN-LAYER-2 — every fan write now has one brain, and every wrap has a test

Completes the FanPolicyOracle migration begun in v5.70.0. **Tier 2-DB**: three plan revisions
(two adversarial plan reviews caught a ledger-orphaning key scheme, a constructor break of 10
test files, and a would-be deadlock), staged D1/D2 build with an honest mid-build checkpoint,
three framing-disjoint code reviews, one consolidated fix-up.

- **RoomFanState (HVAC tier) delegates to the oracle**: plain-class conversion with a
  backward-compatible 13-field constructor; ISO↔datetime descriptor with hydrate-on-read;
  both tiers now key by `room:{NFC(name)}` with a **wired entry→room key migration**
  (field-wise freshest-wins on collision — Review B caught the helper built-but-unwired, and
  the fix-up corrected the empty-mapping variant that would have dropped live holds).
- **All 9 writers route through `oracle.actuate()`** (per-room lock, TOCTOU-safe): W1 temp
  revert, W2 sleep-off, W3 temp/onset ON, W4 chokepoint (W10 pause/restore route through it),
  W8 vacancy sweep, W9 pre-arrival deactivate, W11 safety (always-allows OFF), W12
  pre-arrival ON. Deadlock audit clean (no actuate encloses a locked setter; non-reentrancy
  discipline verified at the R-M-W site).
- **Zero hollow anchors**: Review C corroborated that all 7 new wraps shipped scan-verified
  only, then authored behavioral anchors for W8/W9/W4; the fix-up built a RoomAutomation
  harness and anchored the remaining four. All nine wraps red under semantic neuter
  (orchestrator re-drilled W1). Sleep-axis veto made reachable on HVAC onset paths
  (canonical trigger constants replace dynamic strings).
- Deferred (carded): orphaned oracle rows on room rename (comment-marked), one end-to-end
  onset-emit drill (oracle-side locked).

## SUITE-HYGIENE-1 — the suite stops lying

Census found **155 test files writing 1292 times into `sys.modules` (98 keys)** — the root of
the order-dependent flake families taxing every cycle's verification. Ships: a conftest
snapshot/restore fixture (test-synth namespaces; wider prefixes measured and rejected — 7
fixed / 7 broken, those pollution-DEPENDENT files carded as SUITE-HYGIENE-2), an env-gated
attribution canary (`URA_SYSMODULES_CANARY[_STRICT]`), and a probe-trio regression anchor
that reds if the fixture is ever weakened. **Determinism proven: three full-suite runs with
byte-identical failure lists (sha-matched), zero regressions.** Zero production code.

## Acceptance criteria

- **Live:** loads, zero URA errors; fan behavior byte-equivalent (delegation transparent).
- **Live (holds)**: manual fan holds/cooldowns survive as v5.68.0 spec across BOTH tiers now.
- **Live (migration)**: no `entry:*`-keyed oracle rows carrying live holds after first
  discover_fans (one-time re-key, idempotent).
- **Live (no flap)**: currently-ON fans steady post-restart.

## Live Validation

### Validated 2026-08-11 (v5.72.0 boot, night)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | `system_log` ERROR search for `universal_room` empty post-restart; house_state `home_night` |
| L2 | Delegation transparent — fans steady | **PASS (live signal)** | `fan.air_circulator` + Jaya bedroom sleep fan ON and holding through the HVAC-tier delegation cutover; Living Room off (correct — vacant); no flap |
| L3 | Key migration one-time re-key | **PASS (by construction this boot)** | RAM ledger fresh at boot → discover_fans constructs room:-keyed rows directly; migration path exercised in-suite (survive/collision/idempotent tests); the migration matters for RELOAD-without-restart, mutation-anchored |
| L4 | Manual holds across both tiers | **ORGANIC (shared with v5.68.0 L2)** | The one operator test still owed: manual Living Room fan-ON must hold ~1h — now proven through BOTH tiers by construction; all 9 wraps mutation-anchored in-suite, orchestrator re-drilled W1 |
| L5 | Suite determinism | **PASS** | SUITE-HYGIENE-1 probe trio green in merged suite; failure list = the stable 23 (identical name-set through both merges) |

PR #501: +4299/−233 (non-empty verified). HACS install verified at v5.72.0 (first download call
timed out; state checked before retry).
