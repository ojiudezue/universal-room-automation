# ROLLBACK CARD — v5.88.0 (governed thermostat borrows)

**Written BEFORE deploy, 2026-08-22.** Operator: *"Deploy but be rollback ready. Or at
minimum toggle off ready. Very sensitive URA code."*

## Known-good state to return to

| | value |
|---|---|
| Last good version | **v5.87.0** |
| develop HEAD before merge | `143be070b` |
| Feature branch | `worktree-agent-afcd187979582d742` @ `bfbc18ae5` |

## LEVEL 1 — toggle off (fastest, no restart, partial)

**Settings → Devices & Services → URA → HVAC Coordinator → Configure →
"Governed thermostat borrows" → OFF**

Stops NEW borrows being recorded. In-flight borrows still complete and still restore.
Thermostats are still written and still restored via the legacy path.

**PARTIAL — this does NOT revert three behaviour changes:**
1. unfiltered pre-change snapshot (a `manual` preset is now stored and written back)
2. unconditional preset restore in `_restore_after_nudge`
3. `blocking=True` on the restore write

**So if the symptom is in the RESTORE path itself, Level 1 will not fix it — go to Level 2.**

## LEVEL 2 — full rollback to v5.87.0 (operator can do this without the assistant)

HACS → Integrations → Universal Room Automation → three-dot menu → **Redownload** →
select **v5.87.0** → Restart Home Assistant.

Reverts everything including the three behaviour changes above.

## LEVEL 3 — git revert + redeploy (if HACS is unavailable)

```
git checkout develop
git revert --no-commit <merge-commit>
./scripts/deploy.sh 5.88.1 "revert v5.88.0" "..."
```

## Symptoms that should trigger a rollback

- A zone stuck on `preset_mode: manual` after a nudge completes (the founding defect — the
  thing this cycle exists to prevent; if it REAPPEARS the cycle made it worse)
- `[GOVERNED BORROW RESTORE FAILED]` log lines appearing repeatedly
- Thermostats not returning to their pre-borrow setpoints after an egress pause or a nudge
- Any zone left on `hvac_mode: off` after a door closes
- URA ERROR flood at boot referencing `hvac_excursion`

## Deliberately NOT a rollback trigger

- `restore_ok: null` in the sensor or events table — that means *policy chose not to restore*
  (immunity / comfort-delay). It is expected and is NOT a failure.
- A single `stale_excursion_row` NM at low severity.

## Fast health check after restart

```
sensor.ura_hvac_coordinator_governed_thermostat_borrows   -> exists, state 0 at idle
                                                 -> last_return.restore_ok == true
                                                 -> started_today.nudge == ac_nudges_today
grep '[GOVERNED BORROW RESTORE FAILED]' in the log -> expect NONE
climate.* preset_mode after a nudge               -> NOT 'manual'
```
