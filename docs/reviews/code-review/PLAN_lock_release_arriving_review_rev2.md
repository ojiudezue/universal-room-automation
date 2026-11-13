# Plan re-review (Tier 3, focused): PLANNING_lock_release_on_arriving.md rev 2

Branch `plan/lock-release-arriving` @ 57d9e216. Scope: §2 invariants, D1 items 2-6, D3, D4, §12 fix table, and the
rejected-M5 reasoning. Code read on this worktree: `security_lock_regime.py` (every `self.reason =`, every
`self._release(`, Store payload/load, `_boot_rebuild`, `_on_boot_recheck`, `_boot_recheck_regime`, `_on_guest_clock`,
`_release`/`_after_release`, `_async_engage`, `_notify_failure`, re-engage, backstop), `house_state.py`
(VALID_TRANSITIONS, `set_override`/`clear_override`), `presence.py` (infer 1255-1440, transition 8180-8340,
dispatch helper 9225-9322, boot-settle override 2660-2700), `manager.py:470-500` (restore before setup),
`security.py:1175-1196`. Presence state-of-play doc was read for rev 1 by the planner; this re-review only checks
code against the plan and asserts no ledger claim.

**Verdict: FIX-PLAN (small).** All eight prior HIGHs are closed against the code. Three plan-text defects remain; one
can produce an untested INV-ARR leak if the builder follows the plan literally. All three are text edits; no
re-review needed after them.

---

## 1. Prior HIGHs: closure check

| Finding | Closed? | Evidence |
|---|---|---|
| F1 (taint cleared on person release) | Closed | D1 item 3 clears only at boundaries. Every `self.reason =` write in the module: 630, 632, 634, 648, 650, 767, 876, 911, 993, 1072, 1099, 1701, 1708. All 13 are in §5 with a clear/no-clear disposition. S1 / approach / proximity / arriving_signal do not write `reason` except via `_after_release` :1708 (VACATION), where the episode genuinely ends |
| F2 / H3a (D4 suppression by `release_gen`) | Closed | `engage_seq` bumped synchronously in `_async_engage` between the `_engage_inflight` stamp (:1913) and `lock.lock` (:1915). No await is added, so INV-2 holds. `release_gen` is no longer used |
| F3 / H3b (timer bound, double page) | Closed | Anchor is the S1 call, which runs after the hold (`_on_hold_confirm` -> `_process_person_edge`). 90 ≥ 20 × 2 + 30 (const.py:3901-3902). The `_failure_nm_at ≥ anchor` dedup is correct for the normal chain (failure at about anchor + 40 s) |
| F4 (raw level read) | Closed | D1, D3 and D4 contain no person-level read. D4b reads `_last_real` / `_arrival_counts`, the existing edge model |
| F5 / H1 (boot channel) | Closed | The saw flag is persisted and also set by `_boot_rebuild` and `_boot_recheck_regime`. The store load (:535) runs before `_boot_rebuild` (:596) |
| H2 (boot-settle-suppressed ARRIVING) | Closed | `old_state == "arriving"` sets the taint. Verified: from AWAY, infer only proposes ARRIVING (presence.py:1366-1368), so the first post-settle edge is `arriving -> home_*`. AWAY -> HOME_* / GUEST are valid in `VALID_TRANSITIONS` (house_state.py:71-79) but reachable only via `set_override` (select/service; `force_state` has no callers). The plan's claim holds |

Rejected M5 holds as stated. Arming at every `arriving_hold` pages on most phantoms. But D4b has the same false-page
shape on a smaller population: see R2-2.

---

## 2. Findings

### R2-1 (MEDIUM, build-trap toward an INV-ARR leak): the structural guard contradicts the no-clear sites
D1 item 3: "a test that greps every `self.reason = ` assignment and asserts each is either inside
`_set_engage_reason` or immediately followed by the helper". Two writes are deliberately neither:
`:634` (`_boot_rebuild` BOOT_UNKNOWN, which must KEEP the restored taint) and `:911` (`_boot_recheck_regime`
guest-night rebuild; §5 says "same episode, no clear"). A builder who makes the guard pass by adding the helper:
- at `:634`: caught by `test_taint_persisted_across_restart_two_rigs`.
- at `:911`: **not caught by any listed test.** Repro: guest toggle ON, sleep window. GUEST_NIGHT episode,
  lockout locked. Phantom GUEST -> AWAY -> ARRIVING (taint) -> HOME_NIGHT (guest_yield_hold). Restart. `_boot_rebuild`
  BOOT_UNKNOWN keeps the taint. The recheck at `:902-911` sets GUEST_NIGHT and wrongly clears. Next morning a live
  HOME_DAY edge is untainted and `house_state:home_day` releases on body evidence only. This breaks INV-ARR, and D3
  stays silent because the saw flag is cleared too.
**Fix:** state the guard as an explicit allowlist `{_set_engage_reason, :634 BOOT_UNKNOWN, :911 guest-night boot}`,
with every other write followed by the helper. Add `test_boot_guest_night_rebuild_keeps_taint` covering the repro
above, and a drill (M19) that adds the helper at `:911`.

### R2-2 (MEDIUM): D4b pages on the same sleeper-phone-flap population that rejected M5, and D0 does not measure it
D4b condition: resident edge `unavailable|unknown -> home` with `_arrival_counts` False, reason engaged, house reads
`away`/`arriving`. A sleeper who never left has `_last_real == home`, so `_really_away` is False (:1365) and the edge
is "uncounted". During a phantom SLEEP -> AWAY -> ARRIVING (the audit's false-AWAY corrections), a phone flap
`unavailable -> home` meets every D4b conjunct, and the lockout is engaged at night. That gives one NM HIGH "X may be
locked out" at 90 s. A real uncounted return and a sleeper flap are indistinguishable on these inputs. D0 (a) counts
both together, and D0 (b) (sleep/home_night) measures the wrong population. Its go/no-go phrase "the (a)-condition
false-page estimate" is undefined.
**Fix:** D0 must split (a) by joining each transition against the audit's phantom/real ARRIVING classification
(false page = (a) during a phantom AWAY/ARRIVING excursion). The D4b go/no-go uses that rate. If it is not < 1 per
week, add a discriminator before shipping D4b (e.g. require no resident `_last_real` change for that pid during the
excursion AND the person's tracker source changed), or ship D4b disabled with its rate recorded.

### R2-3 (MEDIUM): INV-REAL-B misses an uncounted return that lands after the house reached HOME_*
ARRIVING holds about 60 s of hysteresis (house_state.py DEFAULT_HYSTERESIS), then HOME_* follows. A phone that
reconnects (`unavailable -> home`) after the house already reads `home_*` meets the D4b condition with house
`home_*`, so there is no page and no release (ARRIVING no longer covers it). The resident is locked out silently.
This is a reachable shape: phones commonly rejoin Wi-Fi or GPS a minute or more after the body evidence. It is not
listed in §9.3.
**Fix:** either key D4b on `self._arrival_taint` (tainted episode) instead of the live house read, which widens the
false-page population (R2-2), so measure it in D0 too; or name this as a §9.3 residual with D0 counting
`unavailable -> home` edges within N minutes after an ARRIVING -> HOME_* edge.

### R2-4 (LOW): a stale taint survives a boot that finds nothing locked
`reason` is not persisted (:202). If `_boot_rebuild` returns early (no lockout locked, :626), `reason` stays NONE
while a restored `garage_arrival_taint = True` persists. Repro: tainted SLEEP episode, resident person-release
(taint kept by design), restart at 14:00 (nothing locked, so reason NONE and the taint is stale), operator hand-locks
at 15:00, restart at 16:00 with house `home_day`. BOOT_UNKNOWN plus the stale taint gives the boot recheck
`arriving_hold` instead of today's release, so the lock is held until the backstop. **Fix:** in `_boot_rebuild`, call
`_end_episode_arrival_flags()` on the nothing-locked early return. This is safe: with reason NONE there is nothing
to release, and every re-engage goes through `_set_engage_reason`, which clears anyway.

### R2-5 (LOW): stale/failed house-state restore taints at boot
`manager.py:479-480`: when the restore fails or is stale, the machine stays at AWAY. `_boot_rebuild` then sees
`away` + locked and taints (D1 item 2), so a restart after a long outage holds HOME_* until a live SLEEP engage or the
backstop. Bounded and fail-closed. Name it in §9.3 (or taint only when `boot_restore_active` confirmed a restored
`away`/`arriving`).

### R2-6 (LOW): drill M7c is ambiguous against D1 item 3
D1 item 3 adds the helper at `:1708`, inside `_after_release`'s arrival branch (VACATION). M7c says "clear helper
wrongly added to `_after_release` arrival branch". The drill must name the SLEEP/GUEST_NIGHT arm (`:1713`), or the
mutant is the shipped code.

### R2-7 (LOW): D4 page multiplicity and human re-lock
- Two residents arriving together (one car) when S1 cannot unlock without a failure NM (SC not alive, :1593) produce
  two HIGH pages for one lock, because `location` is per pid. Consider keying `location` on the entity.
- A human locking the lockout by hand within 90 s of arrival pages falsely (no `engage_seq` change). Optional: skip if
  the lockout's `last_changed` > anchor and it went unlocked -> locked.
- `_call_later(hass, ...)` in D4 item 3 should read `self._hass`.

---

## 3. Invariant attacks (legal-config)

| Invariant | Result | Notes |
|---|---|---|
| INV-ARR | **LEAK only via R2-1 build path**; otherwise PASS | Tried: restart mid-episode (taint persisted; `ended` excludes `arriving_hold`); boot-settle override (`override_set` is operator-originated: select.py:280, `__init__.py:6224`, presence.py:9398; the boot-settle re-dispatch at presence.py:2690 fires only for a still-active operator override); `override_clear` from ARRIVING taints (fail-closed, fine); WAKING exemption (WAKING reachable only from SLEEP, house_state.py:108-110); guest clock (GUEST_NIGHT is sleep-like, :95, so routing it is byte-identical); SC disable (:767 clears; teardown flushes); AWAY -> HOME_*/GUEST (override only); hold 60 s (person path, outside INV-ARR) |
| INV-REAL | PASS | S1 path is untouched; `_release` does not read house state or taint |
| INV-REAL-B | PASS as stated; coverage gap R2-3, false-page risk R2-2 | |
| INV-PAGE | PASS | Anchor post-hold; `engage_seq` per-call; dedup one-way (a failure NM arriving after D4 fires still double-pages if the blocking unlock call itself hangs > 50 s; accept) |

## 4. Must-fix before build dispatch
R2-1 (allowlist + test + drill), R2-2 (D0 split + go/no-go definition), R2-3 (choose key or name the residual).
R2-4 to R2-7 can be fixed in-plan cheaply (recommended) or by the builder.
