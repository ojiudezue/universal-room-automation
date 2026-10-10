## HA restarts no longer stall ~3 minutes on URA database writes (SHUTDOWN-CENSUS-DB-WRITES-BLOCK-1)

When Home Assistant shuts down it stops URA's database writer early. Writes that arrived
after that used to wait up to 5 minutes for a writer that never came back, so HA's
shutdown sat out two of its own timeouts (100 s + 60 s) on every restart. Now those late
writes are skipped at once (they could not be saved anyway), census snapshots stop
trying once the writer is gone, and a write that was in progress when the writer stopped
returns instead of hanging. Deliberate pauses (database cleanup) still queue writes as before.

Live acceptance (at the deploy restart):
- Verify: the restart's shutdown completes without "timed out waiting for ... log_census"
  / "_evaluate_nudge_outcome" lines and without "DB write failed: shutdown timeout" from
  coordinator diagnostics (read the core log within the hour of the restart).
- Verify: HA is back (homeassistant_start) noticeably faster than the 10-05 19:00 restart
  (~12 min end to end).
