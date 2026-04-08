# v4.0.1 — Hotfix: Button Platform Not Forwarded for Coordinator Manager

## Bug Fix

**Problem:** `INTEGRATION_PLATFORMS` did not include `Platform.BUTTON`, so the button platform was never forwarded for the Coordinator Manager config entry. Both `ClearBayesianBeliefsButton` (v4.0.0) and `NMAcknowledgeButton` (v3.6.29) were registered in `button.py` but never loaded by HA because the platform wasn't set up for that entry type.

**Fix:** Added `Platform.BUTTON` to `INTEGRATION_PLATFORMS` list.

**Note:** This means `NMAcknowledgeButton` was also never working (pre-existing since v3.6.29). Both buttons will now appear after this fix.
