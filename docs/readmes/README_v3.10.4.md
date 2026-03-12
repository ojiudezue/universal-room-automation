# v3.10.4 — Census WiFi Guest Detection: Exclusion-Based Shared Network Filtering

**Hotfix release.** Fixes WiFi guest detection on shared entertainment networks.

## Problem

v3.10.2 used an include-list of phone hostname prefixes (iPhone, Galaxy, Pixel). This failed in two ways:
1. **Over-counted**: Family iPhones on Revel were counted as guests (13 "guests")
2. **Under-counted**: Guest phones with custom hostnames (e.g., "Uche-s-S22") were missed entirely

The Revel SSID is a shared entertainment network with Samsung TVs, HomePods, WiiMs, URC remotes, cameras, IoT devices, family phones, and guest phones.

## Fix: Exclusion-Based Five-Layer Filtering

Flipped the approach from "include known phone hostnames" to "exclude known non-guest devices." This catches guest phones with ANY hostname (standard or custom).

### 1. Empty Hostname Filter
Devices with no hostname can't be identified — excluded.

### 2. Infrastructure Exclusion (NON_GUEST_HOSTNAME_PREFIXES)
Excludes known non-personal device types by hostname prefix:
- Entertainment: Samsung (TVs), HomePod, WiiM, Sonos
- Remotes: TRC-*, URC
- IoT: espressif, ESP-*, Shelly, Tasmota, Tuya
- Cameras: ArmCrest/Amcrest, Reolink, Dahua, G3/G4/G5 (Ubiquiti)
- Network/Energy: Ubiquiti, UniFi, Envoy, Enphase

### 3. Tablet Exclusion (TABLET_HOSTNAME_PREFIXES)
iPads excluded — count phones only (1 per guest) for accurate headcount.

### 4. Person Exclusion
Device trackers in tracked persons' `device_trackers` attribute are excluded (family phones).

### 5. Recency Filter (24h)
Only devices with `last_changed` within 24 hours are counted. Resident devices that have been on the network for days are excluded. Long-staying guests are still caught by `camera_unrecognized`.

## Example: Real Revel Network

27 devices on Revel → only 2 guest phones counted:
- 5 Samsung TVs → excluded (infrastructure "Samsung")
- 2 HomePods → excluded (infrastructure "HomePod-*")
- 1 WiiM → excluded (infrastructure "WiiM*")
- 3 URC remotes → excluded (infrastructure "TRC-*")
- 1 camera, 1 envoy, 2 espressif, 1 G3 cam → excluded (infrastructure)
- 3 iPads → excluded (tablet)
- 3 family iPhones → excluded (recency: been home >24h)
- **"Uche-s-S22"** → COUNTED (custom hostname, recent, not family)
- **"OnePlus-Nord-N30-5G"** → COUNTED (recent, not family)

## New Constants

- `WIFI_GUEST_RECENCY_HOURS = 24`
- `NON_GUEST_HOSTNAME_PREFIXES` — 20 infrastructure hostname patterns
- `TABLET_HOSTNAME_PREFIXES` — ("ipad",)

## Tests

21 new WiFi guest tests (89 census v2 tests, 852 total).
- Custom-named guest phone detection ("Uche-s-S22", "OnePlus-Nord-N30-5G")
- Infrastructure exclusion (URC, envoy, camera, G3)
- Full real-world Revel scenario (27 devices → 2 guests)
- Person exclusion, recency, boundary conditions, case insensitivity
