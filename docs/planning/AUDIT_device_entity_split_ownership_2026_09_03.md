# AUDIT — Device/Entity Split-Ownership (D0 measure-before-build probe)

**Date:** 2026-09-03
**Cycle:** device/entity de-fragmentation (D1 build gate)
**Method:** read-only enumeration of the LIVE Home Assistant registries from the Samba mount.
**Mount freshness:** `/Users/okosisi/ha-config/.HA_VERSION` = `2026.9.0`;
`core.device_registry` + `core.entity_registry` both dated 2026-09-03 15:06;
`core.restore_state` dated 15:15. Mount is FRESH — not a stale cache.

This is a **measure-before-build** probe (CLAUDE.md). No code was changed. Its verdict
gates the D1 build.

---

## Config entries of interest

| Role | Entry title | entry_id |
|---|---|---|
| Source / migration source (`ENTRY_TYPE_INTEGRATION`) | Universal Room Automation | `01KAYV8P69B381KCK3516YVM76` (**PARENT**) |
| Target (`ENTRY_TYPE_COORDINATOR_MANAGER`) | URA: Coordinator Manager | `01KJEC3FYPYAGBQKZWC94CR8GR` (**CM**) |

Note: the Zone Manager entry is `01KJEC3ARCN49EVC80VZZPHCZQ` (not a party to this migration).

---

## Coordinator device inventory

61 URA devices total (rooms + zones + coordinators). The singleton **coordinator** device
identities and their home entry:

| identifier | device_id | entry | device name |
|---|---|---|---|
| integration | `61e84be21633cbbba38b78e03ad65fde` | PARENT | Universal Room Automation |
| coordinator_manager | `0a839889cb5ac3f42d2edc47ce2ab92a` | CM | URA: Coordinator Manager |
| coordinator_manager | `df3b6a7404c9b6ee8a92bba243f2b604` | **PARENT** | URA: Coordinator Manager (dup) |
| energy_coordinator | `2565046ab3c5293fa23f2cc39f76d112` | CM | URA: Energy Coordinator |
| hvac_coordinator | `29986e4bb6c72a84522d92de85ec8461` | CM | URA: HVAC Coordinator |
| presence_coordinator | `804e7d6b7ba48f71767edb861dc559e0` | CM | URA: Presence Coordinator |
| safety_coordinator | `40601226966f4a65222b437c5a3638be` | CM | URA: Safety Coordinator |
| security_coordinator | `29afdbe7ac64886d2d147469c11e9e00` | CM | URA: Security Coordinator |
| security_coordinator | `29c94840ffbe5a09f83d754c114e04cf` | **PARENT** | URA: Security Coordinator (dup) |
| optimization_coordinator | `2854e4c98c9b8951c5a860d4262039a5` | CM | URA: Optimization Coordinator |
| notification_manager | `2998e0985f0cc062310ae97553ade4bb` | CM | URA: Notification Manager |
| music_following_coordinator | `8609260bd007237100783b24a7a6110e` | CM | URA: Music Following Coordinator |
| music_following_coordinator | `3e9ba2930f5a0661e5ea2846243dbb6f` | **PARENT** | URA: Music Following Coordinator (dup) |
| coordinator_music_following | `236dd4f6702a64cca1d7fc40481c695b` | CM | **URA: Music Following (DEAD, 0 entities)** |
| coordinator_music_following | `1cdb9ac4ee5e330f939ed3530c24a50f` | PARENT | **URA: Music Following (DEAD, 0 entities)** |

Three coordinator identities have a **duplicate device record straddling both entries**
(coordinator_manager, security_coordinator, music_following_coordinator) — this is the
fragmentation. The others are cleanly CM-homed.

---

## Split-ownership table (entity counts by config_entry_id)

456 entities live on coordinator devices. Grouped by identifier × owning entry:

| identifier | PARENT | CM | matches operator screenshot? |
|---|---:|---:|---|
| coordinator_manager | **10** | 50 | ✅ CM-10 / CM-50 |
| security_coordinator | **6** | 15 | ✅ Security-6 / Security-15 |
| music_following_coordinator | **1** | 9 | ✅ MusicFollowing-1 / MusicFollowing-9 |
| integration | 80 | — | (house-level, stays on PARENT) |
| energy_coordinator | — | 84 | clean |
| hvac_coordinator | — | 131 | clean |
| presence_coordinator | — | 24 | clean |
| safety_coordinator | — | 14 | clean |
| optimization_coordinator | — | 10 | clean |
| notification_manager | — | 22 | clean |
| coordinator_music_following (dead) | 0 | 0 | dead identity |

**The operator's observed counts reproduce exactly.**

### MIGRATION SET = 17 entities

Coordinator entities currently owned by the **PARENT** entry that should move to the **CM**
entry: **10 (coordinator_manager) + 6 (security_coordinator) + 1 (music_following_coordinator) = 17.**
Full list in the companion CSV (`AUDIT_device_entity_split_ownership_2026_09_03.csv`), which
is the D1 test fixture.

The `integration` device's 80 PARENT-owned entities are house/whole-house scoped and are NOT
part of the migration set — they legitimately belong to the integration parent device.

---

## unique_id-stability audit — THE critical output

For each of the 17 migration-set entities, checked whether `unique_id` embeds the PARENT
entry_id or any per-entry ULID token.

**VERDICT: 17 SAFE / 0 BLOCKED. No `_migrate_entity_unique_id` hook is required.**

Every migration-set unique_id is entry-independent — built from `universal_room_automation_`
+ a semantic key (e.g. `universal_room_automation_house_next_room_accuracy`,
`universal_room_automation_exterior_person_tracks_active`). None contain
`01KAYV8P69B381KCK3516YVM76` or any 26-char ULID. A naive entry-swap (re-homing the entity to
the CM `config_entry_id`) re-registers **in place** — the unique_id is unchanged, so HA will
NOT mint a `_2` duplicate. This is a simple relocation, not a rename.

Sample (full 17 in CSV):

| entity_id | unique_id | stability |
|---|---|---|
| sensor.ura_coordinator_manager_house_next_room_accuracy | universal_room_automation_house_next_room_accuracy | SAFE |
| sensor.ura_coordinator_manager_household_routine_status | universal_room_automation_household_routine_status | SAFE |
| sensor.ura_security_coordinator_outside_people_being_tracked | universal_room_automation_exterior_person_tracks_active | SAFE |
| sensor.universal_room_automation_music_following_health | universal_room_automation_music_following_health | SAFE |

**Minor note (not a blocker):** one unique_id contains a literal space —
`universal_room_automation_person_oji udezue_next_room_accuracy`. It is entry-independent and
therefore SAFE for this migration; flagged only so D1 does not "clean it up" mid-relocation
(changing the unique_id string WOULD mint a `_2`). Leave it byte-identical.

---

## Baseline (for D1 post-deploy acceptance)

| metric | value |
|---|---|
| Total URA entities (platform = universal_room_automation) | **4626** (matches expected ~4626) |
| Total entities on URA devices | 4626 (consistent) |
| URA entities `unavailable`/`unknown` in restore_state (exclude from acceptance) | **71** |
| URA entities with `disabled_by` set | 1953 |
| Migration-set (17) currently unavailable/unknown | **0** — all 17 live |

The 71 unavailable/unknown URA entities are the pre-existing dead set; D1 post-deploy
acceptance should assert the migration-set 17 remain available and no NEW `_2` duplicates
appear, and should exclude the 71 from any "all URA entities available" check.

### Dead device for deletion

`coordinator_music_following` identity has **two** 0-entity device records (the retired
identifier, superseded by `music_following_coordinator`):

- `236dd4f6702a64cca1d7fc40481c695b` (CM entry) — 0 entities
- `1cdb9ac4ee5e330f939ed3530c24a50f` (PARENT entry) — 0 entities

Both are safe to delete (no entities reference them). Operator's "the dead URA: Music
Following (0-entity) device" = these two records.

---

## D1 gate verdict

- ✅ Split-ownership reproduced exactly (17-entity migration set).
- ✅ **No unique_id migration hook needed** — all 17 SAFE, simple `config_entry_id` relocation.
- ✅ Baseline captured (4626 total; 71 dead to exclude; 17 migration-set all live).
- ✅ Dead-device deletion targets identified (2 records, `coordinator_music_following`).
- ⚠️ D1 must NOT alter any migration-set unique_id string (esp. the `oji udezue` space one).

**GO for D1 build** as a plain re-home + dead-device cleanup. No `_migrate_entity_unique_id`
machinery required.
