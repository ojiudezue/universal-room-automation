---
name: deploy
description: Full URA deployment pipeline — tests, README, deploy.sh, HACS update, HA restart, verification
user-invocable: true
---

# URA Deploy Skill

Deploy a new version of Universal Room Automation. Runs the full pipeline:
tests → README → deploy.sh → HACS download → config check → HA restart → verify.

## Usage

`/deploy <version> "<summary>" "<release-notes>"`

Example: `/deploy 3.6.0.12 "Zone camera discovery" "Added camera-to-zone mapping via area registry"`

## Steps

When invoked, execute these steps IN ORDER. Stop on any failure.

### Step 1: Run Tests
```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```
If any tests fail, STOP and report the failures. Do not proceed.

### Step 2: Verify README Exists
Check that `docs/readmes/README_v<version>.md` exists. If not, create it based on the changes in `git diff`.

### Step 3: Pre-stage New Files
Run `git status` to find any new directories or files that deploy.sh might miss (it only globs `*.py` in the component dir, not subdirectories). Stage them with `git add`.

### Step 4: Deploy
```bash
./scripts/deploy.sh <version> "<summary>" "<release-notes>"
```
Report the PR URL and release URL from the output.

### Step 5: HACS Update
Use the `mcp__home-assistant__ha_hacs_download` tool:
- repository_id: "ojiudezue/universal-room-automation"
- version: "v<version>"

### Step 6: Config Check
Use `mcp__home-assistant__ha_check_config` to validate HA configuration.
If invalid, STOP and report errors.

### Step 7: Restart HA
Use `mcp__home-assistant__ha_restart` with confirm=true.

### Step 8: Wait and Verify
Wait 2-3 minutes for HA to restart, then verify the deployment:
- Check that `sensor.ura_presence_coordinator_presence_house_state` is available
- Report the current house state and zone statuses

### Step 9: Report
Print a summary:
- Version deployed
- PR URL
- Release URL
- HA status after restart
