# v5.100.0 — Device arrangement: Rooms grouping node + sweep re-arm + CM menu

**Type:** Feature cycle (operator-facing device-tree arrangement).
**Tier:** 2-DB (device-registry surgery — the v5.92.3→v5.94.1 arc had 8 mistakes). Two
framing-disjoint reviews + orchestrator mutation-verify. Cards: `URA-INTEGRATION-ARRANGEMENT-1`,
`DEVICE-TREE-SWEEP-COUNTER-LIFETIME-LATCH-1`, `DEVICE-TREE-TUPLE-UNPACK-CONSISTENCY-1`,
`CM-CONFIG-FLOW-UX-1` (blank-rows half; selector polish → `CM-CONFIG-FLOW-UX-SELECTORS-1`).

**First release on the 5.100 line** — deliberately: HACS sorts releases with `awesomeversion`
(integer-segment semver, the same lib HA core uses for its own `2024.10 > 2024.9` CalVer), so
5.100.0 sorts correctly after 5.99.x. No jump to 6.x needed; 6.0.0 stays reserved for the
IDENTITY-DRIVEN AUTONOMY milestone. (See `feedback_versioning_convention`.)

## What shipped
- **D3 — Rooms grouping node.** The device tree now nests **House → Rooms → Room** (rooms
  previously hung flat off House, asymmetric with Zones/Coordinators). New `Rooms` device is
  INTEGRATION-owned; rooms re-nest under it via the imperative D-NEST sweep. **Pure `via_device`
  display-nesting change** — NOT an ownership migration (rooms keep their own entries), and NO
  integration-entry reload (avoids the ~5-min watchdog path).
- **D1 — sweep-counter re-arm.** The parent-link sweep no longer latches after 3 tries for the
  session; it resets on a clean (residual==0) sweep, so a late-appearing room gets nested.
- **D2 — tuple-unpack safety.** Two `device.identifiers` loops (`__init__.py:1717`, `:4250`) now
  `len>=2`-guard + index, so a 3-tuple identifier (bond/homekit) no longer aborts zone-orphan
  cleanup (the v5.94.3 bug pattern).
- **D4 — CM menu.** The two previously-BLANK Coordinator-Manager options rows (notification
  volume + per-person routing) now have labels + step titles/descriptions (translation-only —
  option round-trip + RestoreEntity byte-identical). Per-field selector polish carded separately.

## Review outcome (the battery earned its keep)
Both reviewers independently caught 2 CRITICALs pre-ship: the new entity-less, integration-owned
Rooms node collided with (A1/B1) the empty-shell-removal predicate — it would be **deleted on every
CM setup/reload, orphaning all ~40 rooms** — and (A2) the stamper's empty-shell exclusion, which
**refused it as a parent** (inert + a permanent sweep trip-wire). Fixed via a shared
`_GROUPING_NODE_IDS` exemption in both predicates (a parent-owned entity-less node that is NOT a
shell), with real-registry tests (RED-on-neuter) and DEVICE_TREE.md updated. Orchestrator
re-ran the room-orphaning drill independently.

## Live validation — acceptance criteria (discriminating)
- **L1 (restart resilience):** URA loads, config valid, zero new URA ERRORs.
- **L2 (the Rooms node SURVIVES — the CRITICAL that was fixed):** after restart AND after CM
  setup/reload, a device `(universal_room_automation, "rooms")` named "URA: Rooms" **exists** in
  the device registry (it must NOT be deleted by shell-cleanup). Discriminator: the pre-fix build
  would show it gone with a log line `removed empty parent-entry shell device … (rooms)`.
- **L3 (nesting):** rooms' `via_device_id` points at the Rooms device, and the Rooms device's
  `via_device_id` points at the integration device (House → Rooms → Room). No orphaned rooms
  (`via_device_id == None`). No permanent INV-4 sweep WARN trip-wire.
- **L4 (menu):** the CM "Configure Settings" menu shows the two rows labeled (not blank).
- **L5 (5.100 line):** HACS installed v5.100.0 correctly (proves the version-sort is fine).

_Validated <date> — filled in post-restart._
