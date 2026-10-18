# Tier-1 review (framing A): 47593224e websocket_api + 9523dcd0d dual-push.sh — 2026-10-18

Reviewer: ura-reviewer, framing A (correctness / edge cases / blast radius). Not HVAC- or presence-scoped, so the state-of-play docs were not required.
Targeted tests: `quality/tests/test_websocket_api.py` + `quality/tests/test_deploy_scripts.py`. Result: 31 passed.

## 47593224e — websocket_api.py

| # | SEV | Site | Finding |
|---|---|---|---|
| W1 | holds | websocket_api.py:88,102,114 | The installed HA is **2026.2.3**. `decorators.py:141-151` reads `schema["type"]` for a dict, then sets `_ws_schema = messages.BASE_COMMAND_MESSAGE_SCHEMA.extend(schema)`. The old code built that same object by hand. The validator is identical, `type` stays `vol.Required(<cmd>)`, and `id` comes from BASE. The old form was a `vol.Schema` and not a `vol.All`, so line 144 `schema.validators[0]` raised AttributeError at import. The fix is correct. |
| W2 | holds | websocket_api.py:234 | `@callback` makes `hass.add_job` dispatch through `loop.call_soon_threadsafe` and run on the loop. Without it, the job would run in the executor. The function only calls `connection.send_message` and logs, so it never blocks. |
| W3 | LOW (unverified) | n/a | I could not verify the live **HA 2026.9** source, because only 2026.2.3 is installed in .venv-ha. Dict schemas are the decorator's documented primary form, and I know of no change in this area, but that comes from memory and not from the 2026.9 source. Close it at deploy by checking that the three commands register (no import error in the log) and that one `subscribe` round-trip works. |

## 9523dcd0d — scripts/dual-push.sh

| # | SEV | Site | Finding |
|---|---|---|---|
| D1 | holds | deploy.sh:281-295 | **Exit-code contract.** `_on_signal` exits 130 or 143, and deploy.sh step 4 (inside `set +e`) halts on both. When the operator presses ^C, deploy.sh is also in the foreground process group. dual-push exits normally with 130 rather than dying by signal, so deploy.sh carries on to the `rc=130 → exit 130` branch. No change from before. |
| D2 | LOW | deploy.sh:409-413 | The reconcile-mirror caller (inside the `set +e` at 361-419) treats 130/143 as a warning and does not halt. This is pre-existing and not a regression. In practice deploy.sh gets SIGINT itself. Optional fix: mirror the step-4 halt branches. |
| D3 | LOW | dual-push.sh:146 | **Background job inside `$(...)`.** In the command-substitution subshell the INT/TERM traps reset to default, and `_ACTIVE_PUSH_PID` is set only in that subshell. On ^C during `ls-remote`, the subshell dies and the parent trap restores the URL and exits 130 straight away. That part is correct. But the parent's `_ACTIVE_PUSH_PID` is empty, so it never kills the `timeout`+`ls-remote` pair. They sit in their own process group, outside the reach of the terminal SIGINT, and live on as orphans for up to GITEA_PUSH_TIMEOUT_SECS. The impact is a read-only ls-remote that finishes or times out. The token stays in that process's memory and does not land on disk or in argv. Before this commit the same orphan existed, plus a delay. Not a regression. |
| D4 | holds | dual-push.sh:125-127 | **set -e.** `wait ... \|\| rc=$?` is inside an `\|\|` list, so a non-zero exit does not trip errexit, and `_ACTIVE_PUSH_PID` is cleared before `return`. At the callers, line 146 sits in an `if !`, line 157 has `\|\| return 0`, and lines 233/243 propagate a non-zero rc through errexit as before (124 for a timeout still reaches deploy's catch-all warning). |
| D5 | holds | dual-push.sh:128-130 | **Path without a timeout binary.** It is unchanged and still runs in the foreground, so the old deferred-trap behaviour remains on hosts with neither `gtimeout` nor `timeout` (^C reaches git directly because both share the process group, so git dies and the trap runs). Acceptable. |
| D6 | LOW | dual-push.sh:125 | **stdin.** With job control off, bash gives an `&` job stdin from /dev/null. Git asks for credentials on /dev/tty, not stdin. However `timeout` already called setpgid before this commit, so a prompt on /dev/tty from a background process group would get SIGTTIN and stop until the timeout fired. Credentials are embedded in the URL, so in practice no prompt appears. Not a regression. |
| D7 | holds | dual-push.sh:70 (`_on_signal`) | **TERM to the timeout PID.** `$!` is coreutils `timeout`. When `timeout` receives TERM, its handler forwards the signal to the monitored child and, without `--foreground`, to its own process group as well, so git and its remote-helper children get it too. The trap's `restore_gitea_url` then runs a second time via EXIT, which is idempotent. |
| D8 | holds | dual-push.sh:125 | With job control off, bash sets SIGINT to ignored for background jobs. `timeout` installs its own handlers, so that has no effect. ^C reaches bash's `wait`, which returns at once (>128), and the trap runs. |

## Summary

| SEV | Found | Fix-required |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 0 | 0 |
| LOW | 4 (W3, D2, D3, D6) | 0 |

Bug classes: Untracked background tasks (D3, an orphaned subprocess in the subshell path, pre-existing). Off-loop callback (W2, fixed).

**Verdict: SHIP.** Optional follow-ups: kill the orphan in the `$(...)` path (for example, avoid the substitution by writing ls-remote to a temp file), and halt on 130/143 at deploy.sh:409.
