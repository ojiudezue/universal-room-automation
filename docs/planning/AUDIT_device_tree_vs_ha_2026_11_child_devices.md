# AUDIT: URA device tree vs HA 2026.11 child devices / DeviceInfo dataclass

Read-only, 2026-11-04. House is on 2026.10.4. Read in full: `docs/architecture/DEVICE_TREE.md`, `docs/reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md`. Surveyed: `_devices.py`, `entity.py`, `aggregation.py:4217`, `time.py:120`, `__init__.py` registry sites, and kanban device-tree cards.

## 1. What HA actually changed, and when

- **Child devices.** A child is a lightweight sub-device for one part of one physical product, such as a power-strip outlet. It points at its parent through `parent_device_id` (the parent's `DeviceEntry.id`). Nesting is **one level only**. A child carries no `via_device`, manufacturer, model or firmware of its own. It **must share the parent's config entry and subentry**. Deleting or disabling the parent cascades to its children, and targeting the parent also targets the children's entities. Removing a child removes its entity-registry entries. Converting a child back to a main device needs a remove and a recreate. Available from **Core 2026.9**. HA describes `via_device` as *connectivity* and child devices as *composition*, and says hub relationships "keep using `via_device_id`". Source: https://contributors.home-assistant.io/blog/2026/10/22/child-devices/
- **`DeviceInfo` / `ChildDeviceInfo` become dataclasses in 2026.11.** Dict access survives only as a compatibility layer that will be deprecated. Passing a mapping to `DeviceInfo({...})` raises `TypeError`. Unset fields read as `UNDEFINED`. The deprecated `via_device` *field* is **removed in 2027.8**; the replacement is `via_device_id`. New helpers: `async_get_or_create_from_info` and `async_get_or_create_child_from_info`. Source: https://contributors.home-assistant.io/blog/2026/10/13/device-info-class/
- **Single-owner devices.** Reading `DeviceEntry.config_entries` or `primary_config_entry` warns for custom integrations until **2027.10**. The replacements are `config_entry_id` and `config_subentry_id`. Source: https://contributors.home-assistant.io/blog/2026/09/15/device-entry-config-entries-deprecation/
- **The user release note** covers only the user-facing side: child devices, naming, and Tuya adopting them first. https://www.home-assistant.io/blog/2026/11/04/release-202611/

**Contradiction to report.** `DEVICE_TREE.md:94-97` says 2026.9 made declarative `via_device` a hard `RuntimeError`. The contributor post lists `via_device` as "still work but log a deprecation warning", with removal in 2027.8. The live 2026.9 traceback (kanban `HA-2026-9-VIA-DEVICE-COMPAT-1`, line 6582) is ground truth for the `async_get_or_create` path, so the doc is not wrong in practice. The doc should still cite the 2027.8 removal date and stop implying `via_device_id` is going away. It is not.

## 2. Known gaps and what the new mechanism does for each

| Gap | Source | Does HA 2026.11 close it? |
|---|---|---|
| Rooms → Rooms node → House nesting is only display, stamped after setup | DEVICE_TREE §2, `_devices.py:195-221` | **No.** Each room is its own config entry and a child must share its parent's entry. Not reachable. |
| CM/ZM/Rooms → Whole House nesting | `_devices.py:134` `PARENT_MAP` | **No.** These devices span different entries (INTEGRATION, CM, ZM). |
| Coordinators → CM device (same CM entry) | DEVICE_TREE §1 | **Mechanically possible, semantically wrong, and risky.** HA scopes children to parts of one product. Children cannot keep their own `model`/`sw_version` (`aggregation.py:4217-4222` sets both). Parent targeting would fan a CM-targeted action out to every coordinator entity. Conversion wipes entity settings. **Partial at best. Do not adopt.** |
| Sweep latch / late stamp (ARRANGEMENT, SWEEP-COUNTER-LATCH) | kanban 7289, 7369 (done) | Not affected. `via_device_id` remains the supported hub/grouping link. |
| ~146 inline `DeviceInfo(` literals across 11 files; identity drift risk | `DEVICE-INFO-HELPER-CONSOLIDATION-1` (parked) | **No.** The dataclass change raises the cost of drift: a dict-style read or mutation of a `DeviceInfo` breaks once the compatibility layer goes. Grep found no dict-style `device_info[...]` or `.get` on DeviceInfo today. Revival trigger for the parked card. |
| Deprecated `async_get_device(identifiers=)` at `__init__.py:1405, 1411, 1442, 5218` | `HA-2027-DEPRECATIONS-URA-1` (planned, kanban 31993) | **No.** Still four live sites, breaking 2027.8. They are unrelated to child devices. |
| `config_entries` reads | `_devices.py:175-192` | **Already closed.** `_device_config_entries` prefers `config_entry_id`. The fallback getattr is for HA versions before 2026.10 only. |
| Zone-slug orphan removal has no 0-entity guard | postmortem §Open; `__init__.py:4911-4928` | **No.** Still unguarded: `async_remove_device` is called on identifier match with no entity-count check. No card found. |

## 3. Nesting code: keep, replace or delete

| Item | Verdict | Why |
|---|---|---|
| `async_stamp_via_device_tree` (`_devices.py:441`) | **KEEP** | `via_device_id` is the documented supported field. Nothing in 2026.11 deprecates it. |
| `PARENT_MAP` / `_resolve_parent_identifier` (`_devices.py:134, 195`) | **KEEP** | Cross-entry nesting has no other mechanism. |
| `_GROUPING_NODE_IDS` (`_devices.py:172`) | **KEEP** | The Rooms node is still load-bearing. |
| Sweep scheduler + retry (`_devices.py:579-700`) | **KEEP** | Unchanged. |
| `_device_config_entries` legacy fallback (`_devices.py:192`) | **KEEP + DOCUMENT** | Dead on 2026.10 or later, but a multi-home install could still run an older HA (`project_single_user_no_backcompat` is changing). Delete only once the minimum supported HA version is ≥2026.10. |
| Zero-declarative-`via_device` test | **KEEP** | 2027.8 removes the field, so the guard stays valuable. |
| Child-device adoption | **PARK** | Revival trigger: URA models a real multi-part *physical* device (none today), or HA deprecates `via_device_id` (no signal of that). |

Nothing lands in DELETE.

## 4. Recommended minimal path

The operator's sense that there are gaps is right, but **child devices close none of them**. The real gaps are pre-existing deprecations plus one unguarded delete.

1. **Doc fix (now, Tier 1, no HA dependency).** Correct `DEVICE_TREE.md` §3: give the 2027.8 removal date for the `via_device` *field*, state that `via_device_id` stays supported, and add a child-devices note: not applicable, same-entry rule, link above.
2. **Run `HA-2027-DEPRECATIONS-URA-1` (Tier 2, works on 2026.10).** Replace the four `async_get_device` sites by iterating `devices.values()` and selecting by `device.id`. This follows DEVICE_TREE §3 and postmortem lesson 4, and it also removes the last-writer-wins hazard.
3. **New card: zone-orphan guard (Tier 1).** Apply the v5.94.1 guarded-removal pattern at `__init__.py:4928`.
4. **After the house is on ≥2026.11 (Tier 1).** Boot once and read `system_log` for `DeviceInfo` dict-compatibility or `via_device` warnings. It is a probe, not a build: measure first, then decide whether to revive `DEVICE-INFO-HELPER-CONSOLIDATION-1`. That card is the only work the dataclass change could force, and only if the probe shows dict usage.

The test harness is pinned to HA 2026.2.3 (`TEST-HARNESS-REAL-HA-DEFAULT-1`), so it cannot exercise `ChildDeviceInfo` or the dataclass. Any step 4 work needs that pin lifted first.
