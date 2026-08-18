# PROBE — Protect face contribution at egress (the missing half of D0)

> ⚠️ **SUPERSEDED / CORRECTED 2026-08-18 (operator).** This probe (and the Frigate-only ~7%
> figure it complements) measured the **front door** (`madrone_g6_entry`) — the WRONG camera. Most
> family entries are via the **garage**, and Protect names people in the **family room** — i.e. on
> the *real* entry path. So the "~7% / NO-GO / build face-independent" conclusion here is **NOT
> valid** as stated. Frigate is on all cameras and Protect named face is reachable via the live
> Alarm Manager webhook; the identity path is **viable**. Any re-measurement MUST target **garage
> entries + family-room arrival** and **include Protect named face** — not Frigate-at-the-front-door.
> See `reference_egress_face_coverage_7pct_not_a_ceiling` (memory) + the corrected
> `AUDIT_census_identity_supersession_and_consumers.md`. Do not cite the 7% as a ceiling.

**Card:** `EXTERIOR-GUEST-EGRESS-1` · **Thread:** presence
**Complements:** `docs/planning/PROBE_exterior_guest_egress.md` (Frigate-only D0 probe, ~7% at egress)
**Author:** oji@outlook.com · **Date:** 2026-08-18
**Kind:** READ-ONLY measurement probe. No design. All DB reads `mode=ro`.

**Why this probe.** The first D0 probe measured **Frigate** face coverage only (~7% in-window at door/exterior cams) and explicitly parked D1 behind "face recognition coverage at door/exterior cameras ≥30%." It did **not** measure **UniFi Protect** face recognition, which the operator believes is concentrated on the G6 entry cam + family room — exactly the egress-relevant location. This probe measures the Protect contribution so cycle 3 can replan the "build BOTH face + face-independent" scope on real numbers.

**Data surfaces used**
- HA recorder (`purge_keep_days` ~7): `/config/home-assistant_v2.db` via `ssh ha` + `sqlite3 ?mode=ro`. True window: **2026-08-10 09:12 → 2026-08-18 05:33 UTC (~7.7 d)**.
- HA entity registry: `/config/.storage/core.entity_registry`.
- **UniFi Protect NVR REST/websocket** via `unifi-protect` MCP (`protect_list_known_faces`, `protect_list_smart_detections`, `protect_list_cameras`) — this reads the controller directly, NOT HA.
- `person_entry_exit_events` rate (186 entry/wk) carried forward from the prior probe (unchanged).

---

## Q1 — Where does UniFi Protect expose face recognition, and what shape?

**METHOD.** (a) Enumerated all `platform=unifiprotect` entities in the registry, greped for face/smart/recognition. (b) Sampled `event.*_smart_detection` attribute JSON from the recorder. (c) Queried the NVR directly via the Protect MCP.

**RESULT — in Home Assistant (what URA can consume).**
- The `unifiprotect` integration exposes **NO face-recognition entity of any kind.** No `last_recognized_face`, no name sensor, no `select`/`text` identity entity. The only face surface is the per-camera **`event.<area>_<cam>_smart_detection`** entity, whose payload is:
  ```
  {"event_type":"face","friendly_name":"Family Room Smart detection"}
  ```
  `event_type` takes values `person / vehicle / face / animal / package` — **`face` means "a face was detected", never WHO.** There is no name, no person id, no confidence in the HA attribute. (License-plate is a separate `sensor.*_license_plate_detected`; there is no analogous face-name sensor.)
- **The only face entities carrying a recognized NAME in HA are Frigate's** `sensor.<cam>_last_recognized_face_2` (23 of them). Protect contributes **zero named-identity entities to HA.**

**RESULT — at the NVR controller (not in HA).** The Protect controller *does* run Known-Face recognition, exposed via the REST API (Protect MCP) but **not surfaced to HA**:
- `protect_list_known_faces`: **4 named residents** — `Ade`, `Oji`, `Shola`, `Ziri` — plus 2 unlabeled groups. Cumulative `detections_count` is tiny: Oji 23, Ziri 50, Shola 2, Ade 1 (lifetime, since account creation months ago).
- `protect_list_smart_detections(type=face)` events carry `recognized_person_id`, `recognized_person_name`, `recognized_person_confidence` **when Protect matches a known face** — but most events carry only an auto-clustered `face_###` id (unlabeled) or `face_degraded_*` (low-conf), i.e. no resident name.

**CONFIDENCE: HIGH.** Registry-confirmed absence of any Protect face entity in HA; NVR shape confirmed by direct MCP reads.

**Load-bearing consequence:** even where Protect *knows* who someone is, **URA cannot read it** — the identity lives only on the NVR REST API, not as an HA entity. Consuming it for D1 would require building a new NVR-events integration (out of the current cycle-3 scope, which is "Frigate-2 AND Protect *entities*").

---

## Q2 — Protect face coverage AT EGRESS (the entry camera)

**METHOD.** Camera-id map from `protect_list_cameras`: `6962dd38001ab203e419ef26` = **Madrone G6 Entry** (the egress cam); `67a2881f0149da03e40004f4` = **Family Room** (interior AI-Theta). Counted `face`-type smart-detection events per camera over the 7.7 d recorder window; cross-read the NVR event buffer (~49 recent face events, ~2 d) for `recognized_person_name` presence per camera.

**RESULT.**
| camera | face-detection events (7.7 d, recorder) | named-recognition (NVR sample) |
|---|---|---|
| **Family Room** (interior) | **276** | Oji×2, Ziri×2 — the ONLY named events |
| **Madrone G6 Entry** (egress) | **10** | **0 named** — only unlabeled `face_254/255/210` clusters |
| any other camera | **0** | 0 |

- Protect face DETECTION over the whole house fires on exactly **two** cameras, and is **27× more frequent at the interior Family Room than at the actual entry camera** (276 vs 10).
- At the **entry camera**, Protect produced ~10 face *detections* in 7.7 d and, in the observed buffer, **zero carried a resident name** (all were unlabeled auto-clusters).
- Named recognitions land at the **interior** Family Room camera — people are recognized once they are already inside the living room, not as they cross the door.

Against the ~186 weekly `entry` events: entry-camera Protect face detections ≈ 10/186 = **5.4% detection**, and **named identity ≈ 0%**. Even if URA could read NVR names (it can't today), the entry-camera named-recognition contribution is ~0.

**CONFIDENCE: HIGH** on the per-camera detection split (full-window recorder counts); **MEDIUM** on the exact named-rate at the entry cam (NVR buffer sample ~2 d, but 0/entry-cam named is consistent with the recognition clustering on the interior camera).

---

## Q3 — Combined Frigate + Protect face coverage at egress (the real number)

**METHOD.** Add the Protect entry-camera identity contribution (Q2) to the Frigate egress coverage from the prior probe (~7% in-window at door/exterior cams, on the now-shipped `_2`-suffix entities).

**RESULT.**
| source | consumable by URA today? | egress *identity* coverage |
|---|---|---|
| Frigate `_2` face sensors | **yes** (HA entities) | ~**7%** (code's ±45 s window, door/exterior cams) |
| Protect face **in HA** | no name in payload | **0%** (detection only, no identity) |
| Protect face **at NVR** (names) | **no** — not an HA entity | entry-cam named ≈ **0%** (names cluster on interior Family Room) |
| **Combined (consumable)** | | **≈ 7%** |
| **Combined (even counting un-consumable NVR names)** | | **still ≈ 7%** at the entry camera |

Protect adds **nothing** to egress identity: in HA it has no name to add, and at the NVR its named recognitions happen at the interior Family Room, not at the door. The combined number stays at the Frigate ~7%.

**CONFIDENCE: HIGH.** Both legs measured; the Protect leg contributes ~0 at egress by two independent facts (no HA name; NVR names are interior-only).

---

## Q4 — Cross-NVR agreement / conflict

**METHOD.** Looked for cases where Frigate and Protect both recognize a face at the same camera/time and compared the WHO.

**RESULT.** Effectively **unmeasurable / near-zero overlap.**
- Protect surfaces a name only at Family Room (interior). Frigate's face coverage at egress door/exterior cams was ~7% and was structurally dead until the `_2`-suffix fix (per the prior probe), so there is no meaningful historical window where both NVRs named a person at the same door/exterior camera at the same time.
- No conflict cases (different names) could be constructed from the available data because the two producers barely co-fire on the same camera. The residents Protect knows (Ade/Oji/Shola/Ziri) are a subset consistent with the household; no evidence of disagreement, but also no positive agreement sample.

**CONFIDENCE: LOW** on fusion behavior (insufficient co-fire sample). If cycle 3 ever wires Protect NVR names, agreement must be re-measured after both producers are live at the same cameras.

---

## Go / no-go update for cycle-3 D1

**D1 (populate `person_id` / identity on the egress event) — remains NO-GO.**

- Combined **consumable** face-identity coverage at egress = **~7%** (Frigate only). The 30% gate is **not** cleared.
- **Protect does not rescue D1.** Two independent blockers: (1) the HA `unifiprotect` integration exposes face as *detection only* — `event_type:"face"` with no name, so URA has nothing to read; (2) even at the NVR, where names exist, recognition clusters on the **interior Family Room** camera (276 events) and produces **~0 named recognitions at the actual entry camera** (10 detections, 0 named in sample). People are named once they're in the living room, not as they cross the door.
- The operator's premise ("Protect face concentrated on G6 entry + family room") is **half-true and non-load-bearing**: Protect face *detection* is concentrated on those two cameras, but *recognition with a name* is a Family-Room-interior phenomenon, and the entry camera sees ~10 detections/week with no names. Concentration ≠ identity-at-the-door.

**Implication for the "build BOTH face + face-independent" scope:**
- **Face arm (D1) stays parked.** Neither NVR delivers ≥30% named identity at the door. Frigate ~7%, Protect ~0% consumable.
- If the face arm is ever revived, the cheapest unlock is **not** more fusion — it is either (a) improving Frigate/Protect recognition *at the entry camera*, or (b) building an NVR-events bridge so URA can read Protect's `recognized_person_name` (a new integration, its own cycle). Both are gated on a re-run of this probe showing ≥30% named identity at door/exterior cams.
- **The face-independent arm is where the egress value lives** — consistent with the prior probe's D3 GO (approach-track → egress-adjacent termination, 94%, face-independent). Cycle 3 should lead with the face-independent path and treat identity as a parked enhancement with the explicit revisit trigger: *"named face recognition at door/exterior cameras ≥30% in a re-run of Q2/Q3."*

**Honest bottom line:** combined Frigate+Protect face coverage at egress is **~7%**, unchanged by adding Protect. The identity path is still **well below the 30% threshold**. NO-GO for D1.
