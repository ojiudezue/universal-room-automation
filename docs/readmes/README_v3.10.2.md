# v3.10.2 — Census v2 Hotfix: WiFi MAC Randomization + Phone Left Behind

**Hotfix release.** Fixes two issues found immediately after v3.10.1 deployment.

## Fixes

### 1. WiFi Guest Detection: Hostname Fallback for Randomized MACs

Modern phones (iOS 14+, Android 10+) use private/randomized MAC addresses on WiFi. This strips the OUI (manufacturer prefix) from the MAC, making the `PHONE_MANUFACTURERS` OUI filter useless — it always sees empty OUI and rejects the device.

**Fix:** Added `PHONE_HOSTNAME_PREFIXES` constant with known phone hostname patterns ("iphone", "galaxy", "pixel", etc.). When OUI is empty, the code falls back to case-insensitive hostname prefix matching. This correctly identifies guest phones like `host_name: "iPhone"` on the Revel SSID even with randomized MACs.

Also: the `guest_vlan_ssid` config field must be set to "Revel" (or your guest SSID) in the Camera Census settings. The `is_guest` auto-detect fallback doesn't work because UniFi doesn't set `is_guest=true` for VLAN-based guest networks.

### 2. Phone Left Behind: Threshold + Census Suppression

**Previous behavior:** Fired when BLE saw a person but cameras hadn't seen them in **4 hours**. After restart, transit_validator cache was empty, so it fired immediately for everyone.

**New behavior:**
- Threshold reduced from 4 hours to **1 hour** — if you haven't been seen by any camera in an hour and BLE says you're home, that's suspicious
- **Census suppression**: If camera census currently sees ANY persons in the house (`total_persons > 0`), the sensor does NOT fire. The census is evidence that people are physically present, so phone-left-behind is moot.
- New attribute: `census_persons_in_house` shows current census count for diagnostics

## Tests

6 new WiFi hostname tests added (68 total census v2 tests, 831 total).
