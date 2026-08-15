# RESEARCH: Getting UniFi Protect FACE IDENTITY into Home Assistant

Date: 2026-08-15. Research task for URA presence-fusion: this install's Protect API
demonstrably carries per-event recognized face identity (name/id/confidence — verified
against the live Protect REST/websocket; Family Room AI Theta emits face events with
names), but the HA integration surface exposes no identity attributes. Goal: get face
identity into HA so URA can consume it as a local face-identity producer.

All claims below are web-verified against the cited source on 2026-08-15 unless marked
UNVERIFIED.

---

## 1. Official HA core `unifiprotect` integration — DOES NOT expose face identity

Verified against the official docs page and current core source
(`homeassistant/components/unifiprotect/event.py` on `dev`).

Event entities the core integration defines (from `event.py`):

| Event entity key | Identity carried |
|---|---|
| `doorbell` (ring) | none (`event_id` only) |
| `nfc` (NFC card scanned) | YES — `full_name`, `ulp_id`, user status via `_add_ulp_user_infos()` |
| `fingerprint` (identified / not_identified) | YES — `full_name`, `ulp_id` |
| `vehicle` | `license_plate`, `confidence`, attributes |
| `package`, `motion_detection` | none |
| `smart_detection` / `sound_detection` | `event_id` + `smart_detect_types` only |

So core DOES ship the identity plumbing for NFC/fingerprint (ULP keyring lookup,
`unifiprotect.get_user_keyring_info` action) and for license plates — but **face**
events surface only as a `smart_detection` event with `event_type: face`. No
recognized-person name, ulp_id, or confidence attribute exists on any entity,
including registry-disabled-by-default ones. The docs page states this explicitly:
"The Smart detection event reports *which* type was detected, not the richer
recognized metadata behind it."

- Open feature request (active, unresolved as of March 2026):
  https://community.home-assistant.io/t/expose-face-recognition-from-unifi-protect-integration/753747
- No open/merged core PR found adding face `matched_name` surfacing (searched
  GitHub issues/PRs; found only thumbnail/event_id bugs).

**Conclusion: no configuration or hidden entity gets face names out of core today.**

## 2. The data IS in the library core uses (`uiprotect`)

Verified in `uilibs/uiprotect` source (`src/uiprotect/data/nvr.py`):

- `EventMetadata.detected_thumbnails: list[EventDetectedThumbnail]` (Protect 2.11.13+)
- `EventDetectedThumbnail.group: EventThumbnailGroup`
- `EventThumbnailGroup.matched_name: str | None` + `confidence: int`

i.e. the exact recognized-person name + confidence we saw on the wire is parsed and
typed by the library the core integration already bundles — core just never maps it
to an entity/attribute. (This also means a small core PR is feasible; the
fingerprint/NFC entities are the template.)

## 3. HACS / custom integrations

- **unifi-protect-bridge** (https://github.com/Hovborg/unifi-protect-bridge, MIT,
  custom-repository HACS install, min HA 2026.3.0) — the only custom integration
  found that surfaces face identity. It provisions Protect Alarm-Manager webhook
  automations itself, receives local push, and exposes:
  - `sensor.<nvr>_bridge_last_known_face` and per-camera
    `sensor.<camera>_last_recognized_face_<name>` (lazy-created when Protect sends names)
  - HA events `unifi_protect_bridge_face`, `..._face_known`, `..._face_unknown`,
    `..._face_of_interest` with `recognized_face_names` / `primary_recognized_face`
    payload fields.
  - Maintenance: active CI, min-HA pinned to a current 2026 release; but it is a
    small single-maintainer repo (~48 commits). UNVERIFIED: exact last-commit date
    (GitHub page didn't render it in fetch). Treat as young, not abandonware —
    re-check commit recency before adopting.
- Legacy `briis/unifiprotect` HACS integration: archived/superseded by core years
  ago — not a candidate.
- Nothing in HACS default index found that exposes face names via the uiprotect
  websocket path.

## 4. Fallback shapes (no third-party dependency)

### 4a. URA consumes uiprotect directly
`uiprotect` is already installed in this HA (core dep). URA could open its own
`ProtectApiClient` websocket subscription and read
`event.metadata.detected_thumbnails[*].group.matched_name/.confidence` on
`smart_detect_types` containing `face`. Fully local, richest data (name +
confidence + camera + event timing), no polling.
Cost: URA takes on Protect auth/session lifecycle, a second websocket to the NVR,
and version coupling to uiprotect's model churn (the detected_thumbnails shape is
"2.11.13+" gated — it has already changed once). Medium-high maintenance.

### 4b. Protect Alarm Manager webhook → HA webhook trigger
VERIFIED: Alarm Manager can trigger on Face ID (alongside license plate / NFC /
fingerprint) and can filter on a specific face name; HTTP POST delivers a fixed
JSON body (`alarm.triggers[*].key/value`, timestamp) to any URL — point it at an HA
webhook trigger (`/api/webhook/<id>`), template out the face name, fire a
`ura_face_identified` event or set an input_text/sensor. Sources: UI Help Center
"Send UniFi Protect Alerts to Web Services using Webhooks" + Alarm Manager article;
community-confirmed `trigger.json.alarm.triggers` parsing.
Caveats: payload structure is fixed and NOT operator-customizable; confidence is
likely absent (UNVERIFIED — capture one real POST via webhook.site/HA trace before
relying on it); one alarm rule per trigger set; webhook fires at/after event
finalization (community reports ~sub-second to a few seconds delay).
Maintenance: near-zero code (one Alarm Manager rule + one HA automation), survives
HA/core upgrades untouched. AppDaemon adds nothing over a native webhook trigger —
skip it.

## Ranking / recommendation

1. **Alarm Manager webhook → HA webhook automation (4b) — RECOMMENDED first step.**
   Lowest maintenance, zero dependencies, uses only supported Ubiquiti + HA
   primitives, gets the NAME today. Probe-first (per Measure Before You Build):
   capture one live face-match POST to confirm the name field and whether
   confidence appears, before wiring URA to the resulting HA event.
2. **unifi-protect-bridge (HACS)** — same webhook mechanism, nicer entities/events,
   but adds a young single-maintainer dependency for something 4b does in ~20 lines
   of automation. Adopt only if we want its per-camera named-face sensors and its
   commit history checks out.
3. **URA → uiprotect direct (4a)** — best data (confidence included), worst
   maintenance. Park unless 4b's payload proves to lack something URA needs
   (e.g. confidence gating).
4. **Upstream core PR** — the plumbing (uiprotect `matched_name`, the
   fingerprint-entity pattern) already exists; a face event entity with
   `full_name`/`confidence` attrs is a plausible small contribution, but timeline
   is not under our control. Do 4b now regardless.

## Could not verify
- Exact Alarm Manager face-webhook payload field names on THIS firmware (capture live).
- Whether webhook payload includes confidence (suspected no).
- unifi-protect-bridge last-commit date / real-world reliability.

## Sources
- https://www.home-assistant.io/integrations/unifiprotect/
- https://github.com/home-assistant/core — homeassistant/components/unifiprotect/event.py (dev)
- https://github.com/uilibs/uiprotect — src/uiprotect/data/nvr.py
- https://community.home-assistant.io/t/expose-face-recognition-from-unifi-protect-integration/753747
- https://github.com/Hovborg/unifi-protect-bridge
- https://help.ui.com/hc/en-us/articles/25478744592023-Send-UniFi-Protect-Alerts-to-Web-Services-using-Webhooks
- https://help.ui.com/hc/en-us/articles/27721287753239-UniFi-Alarm-Manager-Customize-Alerts-Integrations-and-Automations-Across-UniFi
- https://community.home-assistant.io/t/unifi-protect-custom-webhook-vs-home-assistant-trigger/847025
