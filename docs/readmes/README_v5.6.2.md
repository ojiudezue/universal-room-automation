# URA v5.6.2 — Climate & Fans menu-label hotfix

v5.6.1 fixed the step *title* and field labels, but the options-flow **menu item** you click to enter the step still read **"🌡️ Climate & HVAC"**. The v5.6.0 rename was incomplete in the *source itself* — both `strings.json` and `translations/en.json` carried the stale `options.init.menu_options.climate` label (the build renamed the step title only). Because both files agreed on the wrong value, the v5.6.1 strings↔en parity test couldn't catch it.

## What ships (Tier 1)
- **Menu label fixed** in both `strings.json` and `translations/en.json`: `options.init.menu_options.climate` → **"🌡️ Climate & Fans"**.
- **Two stale code comments** updated (`const.py`, `config_flow.py`: "Climate & HVAC" → "Climate & Fans"). No functional change.
- **Parity test extended** to compare `menu_options` keys + values between `strings.json` and `en.json`, so a future menu-label en-drift is caught.
- **No logic change.** Strings + comments + test.

## Note on the test gap
The parity test guards en↔strings *drift*, but this miss was an *incomplete rename* (both files stale-but-matching), which structural parity can't detect. Mitigation is process: a rename must grep the whole tree for the old label. This hotfix's sweep confirmed **zero** remaining "Climate & HVAC" anywhere in the component.

## Live Validation — Validated 2026-06-23 (post-restart)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Hotfix healthy | **PASS** | installed_version = `v5.6.2`; zero URA ERROR entries at boot. |
| L2 | Menu label fixed | **PASS (file+test)** | `options.init.menu_options.climate` = "🌡️ Climate & Fans" in `translations/en.json` (served post-restart); parity test 77/77 incl. menu_options; zero "Climate & HVAC" remaining in the component. |
| L3 | Visual render | **operator-confirm** | Reopen room config → the options menu item reads **"🌡️ Climate & Fans"** and the step within shows friendly labels. |
