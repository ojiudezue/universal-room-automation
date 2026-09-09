# v5.100.5 — Stop registering the dead React dashboards to the sidebar (reversible)

**Type:** Maintenance (removal of dead-panel registration). **Tier:** 1.
Cards: `DELETE-REACT-DASHBOARDS-1` (phase 1). Phase 2 (code deletion) parked as
`DELETE-REACT-DASHBOARDS-CODE-2` (warm/maintenance).

## Why
The base build still registered two dead React/WebSocket dashboards as sidebar panels
("URA" → `ura-dashboard` from `frontend/`, "URA Dashboard" → `ura-dashboard-v3` from `frontend-v3/`).
They never worked and are superseded by the URA v8 Lovelace dashboard (the commercialization PWA
is a separate off-repo project). **Operator's call: do the smaller, reversible change first** —
stop auto-deploying them to the sidebar — before deleting the code.

## What shipped
- **`__init__.py` (integration setup):** removed the panel + static-path registration block for
  BOTH `frontend/` and `frontend-v3/` (`panel_custom.async_register_panel` +
  `hass.http.async_register_static_paths` + their `async_on_unload` panel teardowns). Replaced with
  a comment marking the reversible phase-1 removal. **No code deleted** — the `frontend/` and
  `frontend-v3/` directories remain on disk (retained for phase 2).
- **Tests:** flipped the 5 setup/unload-symmetry assertions from "panel registered + paired remove"
  to "React panels/static-paths are NOT registered" — reintroducing the registration is now the
  guarded regression.

## Non-goals (phase 2, parked)
Deleting `dashboard/`, `dashboard-v3/`, `frontend/`, `frontend-v3/` and dropping the `frontend/`
line from `deploy.sh:198`. Irreversible — waits behind this reversible step
(`DELETE-REACT-DASHBOARDS-CODE-2`, revisit trigger: phase 1 lived with no need to restore the panels).

## Live validation — acceptance criteria
- **L1:** restart clean, config valid, no new URA errors.
- **L2 (the change):** the two URA React panels ("URA" / "URA Dashboard") are **gone from the HA
  sidebar**. The URA v8 Lovelace dashboard is unaffected.
- **L3 (reversible/no-harm):** no `Failed to register URA Dashboard panel` warnings (the code path
  is gone), and integration setup completes.

_Validated <date> — filled in post-restart._
