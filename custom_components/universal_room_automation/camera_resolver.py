"""Shared CameraResolver primitive (2026-08-01 room-camera fusion cycle).

Extract-and-abstract of ``CameraIntegrationManager.resolve_cross_platform_sensors``
semantics into a standalone module consumed by:
  - camera_census (via gated cutover — legacy path preserved behind flag)
  - binary_sensor.CameraPersonDetectedSensor (D3 fused per-room sensor)
  - fan_veto (D5, via the fused sensor)

Correlation ladder (ordered — first-match wins per correlation basis, but the
resolver collects ALL siblings across all rungs and attributes each with its
basis):
  1. same-device       — entity_id -> device_id, collect matching entities on
                         that device. F1 FIX: WITHIN a UniFi Protect device
                         (NVR-style; can host multiple physical cameras),
                         filter by entity-name-stem so garage_hallway_* on
                         the staircase device does not fuse into staircase.
  2. device-MAC        — `device.connections` MAC join across integrations
                         (Frigate has none; UniFi/Reolink typically populate).
                         Built + fixture-tested; ZERO live cross-integration
                         matches on the D0 registry (AUDIT §4 F5) so this rung
                         adds nothing on this deployment today.
  3. identifiers       — cross-integration identifier-tuple overlap.
                         Same status as MAC: infrastructure, no live consumers.
  4. network-inventory — IP/hostname -> MAC via UniFi Network client table.
                         Stub interface only this cycle (TODO); the resolver
                         accepts an optional ``network_inventory`` provider
                         and does NOT wire the live lookup.
  5. name-stem         — the workhorse. F2 FIX: collapse same-object-name
                         Frigate devices across the two hosts (frigate 1/2
                         are NOT independent corroborators until the F1<->F2
                         stability gate opens — see FRIGATE_CROSS_HOST_
                         CORROBORATION_ENABLED). F3 FIX: exclude
                         ``_package_*`` detectors from the person capability.
  6. operator-declared — CONF_ROOM_CAMERAS multi-select is ground truth: two
                         entities listed together are asserted to be the same
                         physical camera regardless of MAC/stem parity.

Face semantics (per plan amendment):
  - enabled  = usable corroborator
  - disabled = AMBIGUOUS (unknown, NOT negative evidence, never auto-enable)
  - absent   = absent

Face is NEVER auto-enabled (invariant).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

_LOGGER = logging.getLogger(__name__)


def _norm_mac(value: Any) -> str:
    """Normalize a MAC connection value. A-L1: prefer HA's format_mac (canonical
    lowercase colon-separated form), else fall back to a lowercased string so
    index + lookup both agree on the same key.
    """
    if value is None:
        return ""
    try:
        from homeassistant.helpers.device_registry import format_mac  # noqa: PLC0415
        return format_mac(str(value))
    except Exception:  # noqa: BLE001 — resolver runs from tests w/o HA import
        return str(value).lower()

# ---------------------------------------------------------------------------
# Module-level rung-1 knobs (per plan: "flip via later reviewed change").
# These are code-review-gated (Numbers-Get-Knobs rung 1 — module constant),
# NOT operator-tunable at runtime. Their state is exposed for observability
# but changing them requires a reviewed edit.
# ---------------------------------------------------------------------------

# F2 gate: Frigate-1 <-> Frigate-2 corroboration. Off until the 72h stability
# gate (a) zero MQTT session evictions, (b) zero unavailable<->value flapping,
# (c) no retained-message ghosts — is measured PASS post prefix-split.
FRIGATE_CROSS_HOST_CORROBORATION_ENABLED: bool = True  # gate PASSED 2026-08-04: 72h post prefix-split, 0 organic evictions/flaps/ghosts (all 15 unavailability events map to deploy restarts + homelab config work)

# D4 dry-run: first release LOGS what it would enable, does NOT call
# switch.turn_on. Flip to False in a later reviewed change once the log
# inventory looks right.
CAMERA_AUTOENABLE_DRY_RUN: bool = True

# Census cutover flag. Route
# `CameraIntegrationManager.resolve_cross_platform_sensors` (the whole-house
# census path) through the new CameraResolver when True; fall back to the
# legacy name-stem-only path preserved in camera_census.py when False.
#
# B-MED-2 (2026-08-06): fire-axe scope note. Flipping this flag to False
# reverts ONLY the census `resolve_cross_platform_sensors` code path. It
# does NOT disable:
#   - D3 CameraPersonDetectedSensor per-room fused sensor (always uses
#     CameraResolver directly via `resolve_operator_declaration`)
#   - D5 fan_veto camera-person leg (via the D3 sensor)
#   - D4 auto-enable dry-run scan
# The new resolver stays live in those consumers; only the census merges
# fall back to legacy. Cutover requires a golden-master diff artifact
# (legacy vs new outputs across the live registry) per the plan amendment
# — do NOT flip without that artifact.
CENSUS_USE_NEW_RESOLVER: bool = True


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

# Correlation-basis vocabulary. Exported as string constants for grep-ability.
BASIS_SAME_DEVICE = "same_device"
BASIS_MAC = "mac"
BASIS_IDENTIFIERS = "identifiers"
BASIS_NETWORK_INVENTORY = "network_inventory"
BASIS_NAME_STEM = "name_stem"
BASIS_OPERATOR_DECLARED = "operator_declared"

# Face capability tri-state.
FACE_ABSENT = "absent"
FACE_USABLE = "usable"
FACE_AMBIGUOUS = "ambiguous"

# Frigate/UniFi/Reolink/Amcrest/Dahua platform identifiers.
PLATFORM_FRIGATE = "frigate"
PLATFORM_UNIFI = "unifiprotect"
PLATFORM_REOLINK = "reolink"
PLATFORM_AMCREST = "amcrest"
PLATFORM_DAHUA = "dahua"

# Canonical area precedence across grouped legs of the same physical
# camera (RESACC-1 A-2/A-3 fix, 2026-08-09). When the primary entity's
# OWN area is unset, the resolver falls back to sibling legs. This order
# arbitrates the fallback deterministically so the same physical camera
# resolves to the same area regardless of which platform was enumerated.
#
# Rationale (per AUDIT_resolver_ground_truth_manual.md 2026-08-07):
#   - unifiprotect: carries the real area on all 7 exterior perimeter
#     cameras (A-3 ground truth column).
#   - frigate:      Frigate legs carry the correct area on armcrest
#     (`pool`) while the dahua device-area is mis-set to `balcony` (A-2).
#   - reolink/amcrest/dahua: native device-area frequently mis-set on
#     this deployment; used only as last-resort fallback.
CANONICAL_AREA_PRECEDENCE: tuple[str, ...] = (
    PLATFORM_UNIFI,
    PLATFORM_FRIGATE,
    PLATFORM_REOLINK,
    PLATFORM_AMCREST,
    PLATFORM_DAHUA,
)


@dataclass
class FusionSource:
    """One per-integration view of a physical camera."""
    integration: str
    device_id: str
    person_binary_sensor: str | None = None
    face_binary_sensor: str | None = None
    face_capability: str = FACE_ABSENT   # FACE_ABSENT | FACE_USABLE | FACE_AMBIGUOUS
    person_count_sensor: str | None = None
    person_detect_switch: str | None = None
    face_detect_switch: str | None = None    # INVENTORY ONLY — never auto-enabled
    correlation_basis: str = BASIS_SAME_DEVICE


@dataclass(frozen=True)
class EnumeratedCamera:
    """One physical camera enumerated by ``enumerate_platform_cameras``.

    TRANSIT-1 (2026-08-07). Pairs a physical camera (one ``device_id``) with
    every detection leg the resolver's ladder pulls in for a given family,
    plus the area attribution (Protect-leg-first with cross-leg fallback per
    AUDIT_resolver_ground_truth_manual.md §A-3).

    ``legs`` is a list of ``binary_sensor`` entity_ids covering the family
    across every integration attached to this physical camera (Frigate F1+F2
    twins + Protect base+``_2`` + native-AI etc. — same behavior as
    ``resolve_detection_legs``).
    """
    device_id: str
    area_id: str | None
    legs: tuple[str, ...]
    primary_entity: str


@dataclass(frozen=True)
class DetectionLeg:
    """One (entity_id, engine) pair for a physical camera + detection family.

    Cycle-3 resolver-legs (2026-08-07). Consumed by PerimeterAlertManager
    (replaces the retired ``_fused_sibling`` / ``_protect_person_legs`` /
    ``_derive_sibling_sensor`` helper triplet — three generations of
    hand-rolled slug logic) and by observability surfaces that need to
    attribute a firing to a specific engine.

    ``engine`` is the observability tag emitted in coverage logs + the
    disagreement telemetry. Value space:
        frigate, frigate2, protect, protect2, reolink, amcrest, dahua

    ``integration`` is the raw HA platform (frigate, unifiprotect,
    reolink, amcrest, dahua) — kept separately from ``engine`` because
    F1 vs F2 both share the frigate platform but need distinct engines.
    """
    entity_id: str
    engine: str
    integration: str
    device_id: str


@dataclass
class RoomCameraFusion:
    """All per-integration sources for one physical camera."""
    physical_camera_id: str
    sources: list[FusionSource] = field(default_factory=list)
    discovered_at: datetime = field(default_factory=datetime.now)
    # D'-MED-1: person sensors of F2-collapse LOSERS, retained so consumers
    # can watch for their recovery and re-resolve (a winner picked while
    # both hosts were down must not stick forever once the loser recovers).
    dropped_person_sensors: list[str] = field(default_factory=list)

    def person_binary_sensor_entity_ids(self) -> list[str]:
        return [s.person_binary_sensor for s in self.sources if s.person_binary_sensor]

    def person_detect_switch_entity_ids(self) -> list[str]:
        return [s.person_detect_switch for s in self.sources if s.person_detect_switch]

    def face_detect_switch_entity_ids(self) -> list[str]:
        """INVENTORY only — this list is never fed to any auto-enable path."""
        return [s.face_detect_switch for s in self.sources if s.face_detect_switch]


# ---------------------------------------------------------------------------
# Suffix / pattern sets (widened per D0 F-findings)
# ---------------------------------------------------------------------------

_PERSON_SUFFIXES = (
    "_person_occupancy",     # Frigate
    "_person_detected",      # UniFi Protect / generic
    "_person",               # Reolink native AI (bare)
    "_smart_motion_human",   # Dahua / Amcrest native AI (verified live 2026-08-07)
)

# Cycle-3 resolver-legs (2026-08-07): family suffix vocabulary widened from
# the perimeter_alert.py-local sets. Native-AI shapes verified via live
# entity registry (ssh ha probe 2026-08-07):
#   Reolink porch PTZ  -> binary_sensor.<slug>_person / _vehicle / _animal
#   Dahua pool overhead-> binary_sensor.<slug>_smart_motion_human / _vehicle
#   UniFi Protect       -> binary_sensor.<slug>_person_detected / _vehicle_detected / _animal_detected
#   Frigate             -> binary_sensor.<slug>_person_occupancy (+ HA `_2` on second host)
_VEHICLE_SUFFIXES = (
    "_vehicle_detected",     # UniFi Protect smart-detect
    "_smart_motion_vehicle", # Dahua / Amcrest native
    "_vehicle",              # Reolink native (bare)
)

_ANIMAL_SUFFIXES = (
    "_animal_detected",      # UniFi Protect smart-detect
    "_smart_motion_animal",  # Dahua / Amcrest native (defensive; not seen live)
    "_animal",               # Reolink native (bare)
)

_FAMILY_SUFFIXES: dict[str, tuple[str, ...]] = {
    "person": _PERSON_SUFFIXES,
    "vehicle": _VEHICLE_SUFFIXES,
    "animal": _ANIMAL_SUFFIXES,
}

_FACE_SUFFIXES = (
    "_face_recognized",
    "_face_detected",
    "_smart_detect_face",
    "_ai_face",
    "_last_recognized_face",
)

_PERSON_SWITCH_SUFFIXES = (
    "_detections_person",       # UniFi Protect
    "_person_detection",        # Reolink
    "_smart_detect_person",     # possible Reolink/Amcrest
    "_ai_person",               # possible Reolink/Amcrest
)

# Face switches — INVENTORY ONLY. This set exists so the resolver can PROVE
# (via test) that none of these entity_ids ever reach the auto-enable
# code path. Widened per D0 §5 face-protection scope.
_FACE_SWITCH_SUFFIXES = (
    "_detections_face",
    "_detections_smart_face",
    "_face_detection",
    "_smart_detect_face",
    "_ai_face",
)

_PERSON_COUNT_SUFFIX = "_person_count"

# Camera-entity resolution suffixes stripped when computing per-device stems.
# Kept module-level so both `_compute_device_stems` and `_stem_match` agree.
_CAMERA_RESOLUTION_SUFFIXES = (
    "_high_resolution_channel",
    "_medium_resolution_channel",
    "_low_resolution_channel",
    "_fisheye",
)


def _strip_camera_resolution_suffix(name: str) -> str:
    for suf in _CAMERA_RESOLUTION_SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def _strip_disambiguation_suffix(name: str) -> str:
    """Strip HA's _N entity-id disambiguation suffix (bench finding
    2026-08-01: operator-picked camera.armcrestash41b_2 failed the
    name-stem match against Frigate object 'armcrestash41b')."""
    if not isinstance(name, str) or not name:
        return name
    import re as _re
    return _re.sub(r"_\d+$", "", name)


def _entity_name(entity_id: str) -> str:
    return entity_id.split(".", 1)[1] if "." in entity_id else entity_id


def _strip_suffix(name: str, suffixes: Iterable[str]) -> str | None:
    for suf in suffixes:
        if name.endswith(suf):
            return name[: -len(suf)]
    return None


def _has_any_suffix(entity_id: str, suffixes: Iterable[str]) -> bool:
    name = _entity_name(entity_id)
    return any(name.endswith(s) for s in suffixes)


def resolve_area_id_for_entity(entity_registry: Any, device_registry: Any, entity_id: str) -> str | None:
    """B-MED-1: resolve an entity's area_id with legacy semantics.

    Precedence (matches legacy `camera_census.resolve_camera_entity` and
    the pre-cutover path, which used
    `bs_entity.area_id or camera_entry.area_id`):
      1. entity.area_id (registry override on the entity itself)
      2. device.area_id via entity.device_id -> device registry
      3. None (degrades on any registry error — legacy behavior)

    Pure helper so it can be unit-tested against synthetic registries.
    """
    try:
        ent = entity_registry.async_get(entity_id)
    except Exception:  # noqa: BLE001
        return None
    if ent is None:
        return None
    area = getattr(ent, "area_id", None)
    if area:
        return area
    did = getattr(ent, "device_id", None)
    if not did:
        return None
    try:
        dev = device_registry.async_get(did)
    except Exception:  # noqa: BLE001
        return None
    if dev is None:
        return None
    return getattr(dev, "area_id", None)


def _is_package_detector(entity_id: str) -> bool:
    """F3: exclude Frigate ``_package_*`` object detectors from person fusion.

    Package-person is a distinct Frigate object class; the AUDIT (§F3)
    documented `_package_person_occupancy` and `_package_person_count` sitting
    on the same device as the real person detector. Conflation raises the
    egress false-positive rate.
    """
    return "_package_" in _entity_name(entity_id) or _entity_name(entity_id).startswith("package_")


# ---------------------------------------------------------------------------
# Minimal duck-typed views of the HA registries.
#
# The resolver operates on any object exposing the attributes it reads. This
# allows synthetic-fixture tests to drive the REAL resolver code without
# importing homeassistant (Bug Class #62 discipline: tests exercise the same
# module production uses).
#
# EntityEntry-like: .entity_id, .device_id, .domain, .platform, .name,
#                   .disabled_by (or None)
# DeviceEntry-like: .id, .identifiers (set of (integration, key) tuples),
#                   .connections (set of (type, value) tuples)
# EntityRegistry-like: .entities: Mapping[str, EntityEntry]  and
#                      .async_get(entity_id) -> EntityEntry | None
# DeviceRegistry-like: .devices: Mapping[str, DeviceEntry]  and
#                      .async_get(device_id) -> DeviceEntry | None
# ---------------------------------------------------------------------------


class CameraResolver:
    """Resolve any camera-related entity to a fused per-integration capability map."""

    def __init__(
        self,
        entity_registry: Any,
        device_registry: Any,
        *,
        network_inventory: Callable[[str], str | None] | None = None,
        state_getter: Callable[[str], Any | None] | None = None,
    ) -> None:
        """Initialize.

        Args:
            entity_registry: object exposing ``.entities`` mapping + ``.async_get``.
            device_registry: object exposing ``.devices`` mapping + ``.async_get``.
            network_inventory: OPTIONAL callable(ip_or_hostname) -> mac. Stub
                interface only this cycle — no live UniFi Network integration
                yet. Provide in tests to exercise the network-inventory rung.
                TODO: wire live UniFi Network client-table lookup in a later
                cycle (D0 F5 measured zero live cross-platform MAC matches on
                this deployment; the rung is infra without a live consumer).
        """
        self._er = entity_registry
        self._dr = device_registry
        self._network_inventory = network_inventory
        # Optional state accessor used by the deterministic F2 collapse
        # winner-selection (A-M3). Signature matches hass.states.get.
        self._state_getter = state_getter
        # Build the MAC index once per resolver instance.
        self._mac_to_device_ids: dict[str, set[str]] = {}
        # Build a stem -> list[device_id] index for the same-Frigate-object collapse.
        self._frigate_stem_to_device_ids: dict[str, list[str]] = {}
        # Census-cutover fix (2026-08-06): bidirectional camera-stem index.
        # Maps camera-entity-name stem -> device_ids for ANY device that owns
        # a `camera.*` entity or a person `binary_sensor.*` entity. This lets
        # rung-5 traverse Frigate -> Protect (the direction the Frigate-object
        # -keyed `_frigate_stem_to_device_ids` cannot serve because Protect
        # devices have empty identifiers on this deployment). Chosen over
        # options (b) integration-inference-based extended index and
        # (c) operator-declared amendment per the GOLDEN_MASTER doc's fix
        # options list: minimal surgery, no new inference machinery, no
        # per-camera operator burden.
        self._stem_to_device_ids: dict[str, set[str]] = {}
        # A-MED-2 / C-MED-2 guard: keep a SEPARATE disambiguation-stripped
        # index so a lookup only collapses `_N` when the two devices share
        # evidence (MAC, identifier tuple, OR both are frigate — the
        # explicit cross-host case). Prevents unrelated same-first-token
        # cameras (e.g. `camera_a` vs `camera_a_2` that are physically
        # distinct) from being fused. Consulted post-check in rung-5.
        self._dstem_to_device_ids: dict[str, set[str]] = {}
        # Cache of device_id -> integration-hint derived from any entity's
        # `.platform`, used as a fallback when the device has no identifiers
        # (Protect NVR devices on this deployment). Populated during index
        # build in one pass so `_infer_integration` does not re-walk.
        self._device_platform_hint: dict[str, str] = {}
        self._build_indices()

    # ---- Index construction ------------------------------------------------

    def _build_indices(self) -> None:
        """Walk the device registry once and build MAC + Frigate-stem indices."""
        try:
            devices = list(getattr(self._dr, "devices", {}).values())
        except Exception as exc:  # noqa: BLE001 — defensive; registry can be mocked oddly
            _LOGGER.warning("CameraResolver: device registry walk failed: %s", exc)
            devices = []
        for dev in devices:
            connections = getattr(dev, "connections", None) or ()
            for conn in connections:
                try:
                    ctype, cval = conn
                except Exception:
                    continue
                if ctype != "mac" or not cval:
                    continue
                mac = _norm_mac(cval)
                if not mac:
                    continue
                self._mac_to_device_ids.setdefault(mac, set()).add(dev.id)
            # Frigate-stem index: identifiers look like ("frigate", "<host>:<name>")
            identifiers = getattr(dev, "identifiers", None) or ()
            for ident in identifiers:
                try:
                    integ, key = ident
                except Exception:
                    continue
                if integ != PLATFORM_FRIGATE or not isinstance(key, str):
                    continue
                # Extract object name (portion after the last ':')
                obj = key.rsplit(":", 1)[-1] if ":" in key else key
                self._frigate_stem_to_device_ids.setdefault(obj, []).append(dev.id)

        # Bidirectional stem index + platform-hint cache: walk the entity
        # registry ONCE, extract a stem from every camera.* or person
        # binary_sensor.* entity, key device_ids under that stem so a lookup
        # of "doorbell_lite" returns BOTH the Frigate device AND the Protect
        # device that own the same physical camera.
        try:
            entities = list(getattr(self._er, "entities", {}).values())
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("CameraResolver: entity registry walk failed: %s", exc)
            entities = []
        for ent in entities:
            did = getattr(ent, "device_id", None)
            if not did:
                continue
            # A-MED-1: skip disabled entities — they never fire state changes
            # and must not silently pull a device into a fusion. Matches the
            # `disabled_by is None` gate already used in `_scan_device_entities`
            # for the same reason (Bug Class #21: disabled-entity leakage).
            if getattr(ent, "disabled_by", None) is not None:
                continue
            eid = getattr(ent, "entity_id", "") or ""
            domain = getattr(ent, "domain", None) or (eid.split(".", 1)[0] if "." in eid else "")
            name = _entity_name(eid)
            stem: str | None = None
            if domain == "camera":
                stem = _strip_camera_resolution_suffix(name)
            elif domain == "binary_sensor":
                # B-HIGH-2: normalize in BOTH orders. HA's `_N` disambiguation
                # can attach AFTER the person-suffix (live observation:
                # `binary_sensor.back_yard_person_occupancy_2` carries `_2`
                # after `_person_occupancy`, not before). Try person-suffix
                # first; on miss, strip `_N` and retry. This lets F1's base
                # and F2's `_2` variant both collapse to the same stem key.
                stripped = _strip_suffix(name, _PERSON_SUFFIXES)
                if stripped is None:
                    _pre = _strip_disambiguation_suffix(name)
                    if _pre != name:
                        stripped = _strip_suffix(_pre, _PERSON_SUFFIXES)
                if stripped:
                    stem = stripped
            if stem:
                self._stem_to_device_ids.setdefault(stem, set()).add(did)
                # Populate the SEPARATE dstem index (A-MED-2/C-MED-2 guard):
                # lookups against this index in rung-5 gate on shared evidence
                # before collapsing.
                dstem = _strip_disambiguation_suffix(stem)
                if dstem != stem:
                    self._dstem_to_device_ids.setdefault(dstem, set()).add(did)
            # Platform-hint cache: prefer known camera-integration platforms
            # (unifiprotect, frigate, reolink, amcrest, dahua). Otherwise
            # accept the first non-empty value as a weak fallback. This
            # avoids co-resident non-camera integrations (e.g. the `unifi`
            # Network integration sharing devices with `unifiprotect`)
            # winning the hint and mislabeling the platform.
            plat = getattr(ent, "platform", None)
            if plat:
                _KNOWN = (PLATFORM_UNIFI, PLATFORM_FRIGATE, PLATFORM_REOLINK, PLATFORM_AMCREST, PLATFORM_DAHUA)
                cur = self._device_platform_hint.get(did)
                if plat in _KNOWN:
                    self._device_platform_hint[did] = plat
                elif cur is None:
                    self._device_platform_hint[did] = plat

    # ---- Public API --------------------------------------------------------

    def resolve_entity_to_device_id(self, entity_id: str) -> str | None:
        """Any-domain entity -> its HA device_id, or None."""
        try:
            entry = self._er.async_get(entity_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("CameraResolver: registry lookup failed for %s: %s", entity_id, exc)
            return None
        if entry is None:
            _LOGGER.warning("CameraResolver: entity %s not in registry", entity_id)
            return None
        did = getattr(entry, "device_id", None)
        if not did:
            _LOGGER.warning("CameraResolver: entity %s has no device_id", entity_id)
        return did

    def resolve_operator_declaration(
        self,
        entity_ids: list[str],
    ) -> list[RoomCameraFusion]:
        """CONF_ROOM_CAMERAS multi-select -> LIST of RoomCameraFusion (D-MED-2).

        Fix #7 (2026-08-01 fix-up): the multi-select now models one entry per
        physical camera. Each input entity_id is resolved via the ladder; any
        entities the ladder pulls in (MAC / identifier / name-stem siblings)
        merge into the SAME physical camera's fusion. Two unrelated input
        entities (no ladder link) resolve to TWO fusions.

        Consumers (D3 fused sensor, D5 fan_veto, D4 dry-run scan) OR across
        the returned list and attribute per-camera.
        """
        input_devices: list[str] = []
        seen: set[str] = set()
        for eid in entity_ids:
            did = self.resolve_entity_to_device_id(eid)
            if did and did not in seen:
                seen.add(did)
                input_devices.append(did)
        fusions: list[RoomCameraFusion] = []
        consumed: set[str] = set()
        for did in input_devices:
            if did in consumed:
                continue
            fusion = self.resolve_capabilities([did])
            for s in fusion.sources:
                consumed.add(s.device_id)
            if fusion.sources:
                fusions.append(fusion)
        return fusions

    def resolve_capabilities(
        self,
        device_ids: list[str],
        *,
        operator_declared: bool = False,
    ) -> RoomCameraFusion:
        """Walk the ladder for a set of device_ids -> RoomCameraFusion.

        `operator_declared=True` tags any sources whose only link to the group
        is the operator's multi-select (i.e. they matched no MAC/identifier/
        stem rung to the input set).
        """
        if not device_ids:
            return RoomCameraFusion(physical_camera_id="")

        # Rung 1 (same-device): resolve the input device_ids themselves + any
        # extra device_ids their MAC connections pull in.
        # For operator-declared multi-select: the FIRST input device is the
        # primary (SAME_DEVICE); any additional input devices that no other
        # rung links back get OPERATOR_DECLARED (their only correlation is
        # the operator's multi-select).
        expanded: dict[str, str] = {}   # device_id -> correlation_basis
        for i, did in enumerate(device_ids):
            if i == 0 or not operator_declared:
                expanded[did] = BASIS_SAME_DEVICE
            else:
                # D'-LOW-2: vestigial from the pre-Fix#7 single-fusion path — the
                # operator-facing caller now resolves each entity separately, so this
                # branch has no live emitter. Retained for a future batch-group path.
                expanded[did] = BASIS_OPERATOR_DECLARED

        # Rung 2 (MAC join).
        for did in list(expanded.keys()):
            dev = self._device(did)
            if not dev:
                continue
            for conn in getattr(dev, "connections", None) or ():
                try:
                    ctype, cval = conn
                except Exception:
                    continue
                if ctype != "mac" or not cval:
                    continue
                for peer_did in self._mac_to_device_ids.get(_norm_mac(cval), set()):
                    if peer_did not in expanded:
                        expanded[peer_did] = BASIS_MAC

        # Rung 3 (identifiers): overlap of full (integration, key) TUPLES —
        # D-LOW-1 fix. Matching bare key strings across different integrations
        # produced spurious pulls when two unrelated integrations happened to
        # reuse an opaque key.
        input_identifier_tuples: set[tuple[str, str]] = set()
        for did in device_ids:
            dev = self._device(did)
            if not dev:
                continue
            for ident in getattr(dev, "identifiers", None) or ():
                try:
                    integ, key = ident
                except Exception:
                    continue
                if isinstance(key, str) and integ:
                    input_identifier_tuples.add((integ, key))
        for dev in getattr(self._dr, "devices", {}).values():
            if dev.id in expanded:
                continue
            for ident in getattr(dev, "identifiers", None) or ():
                try:
                    integ, key = ident
                except Exception:
                    continue
                if isinstance(key, str) and (integ, key) in input_identifier_tuples:
                    expanded[dev.id] = BASIS_IDENTIFIERS
                    break

        # Rung 4 (network-inventory): join via IP/hostname -> MAC.
        if self._network_inventory is not None:
            for did in list(expanded.keys()):
                dev = self._device(did)
                if not dev:
                    continue
                for conn in getattr(dev, "connections", None) or ():
                    try:
                        ctype, cval = conn
                    except Exception:
                        continue
                    if ctype not in ("ip", "hostname") or not cval:
                        continue
                    try:
                        mac = self._network_inventory(str(cval))
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.debug("network_inventory lookup failed for %s: %s", cval, exc)
                        continue
                    if not mac:
                        continue
                    for peer_did in self._mac_to_device_ids.get(_norm_mac(mac), set()):
                        if peer_did not in expanded:
                            expanded[peer_did] = BASIS_NETWORK_INVENTORY

        # Determine per-device stems (from the input `camera.*` entities that
        # sit on each device) — used for the F1 filter within multi-camera
        # Protect devices.
        device_stems = self._compute_device_stems(device_ids)

        # Rung 5 (name-stem): find sibling DEVICES via shared Frigate object
        # name (F2 collapse handled below), plus entity-level sibling entities
        # on OTHER devices sharing a stem.
        for stem in list(device_stems.values()):
            # D-HIGH-1: try both raw stem and resolution-suffix-stripped stem
            # (the compute already strips, but be defensive against callers
            # passing raw values).
            for lookup in ([stem] if stem in self._frigate_stem_to_device_ids else [stem, _strip_camera_resolution_suffix(stem), _strip_disambiguation_suffix(_strip_camera_resolution_suffix(stem))]):  # D'-LOW-1: stripped fallback only on raw miss
                for sibling_did in self._frigate_stem_to_device_ids.get(lookup, []):
                    if sibling_did not in expanded:
                        expanded[sibling_did] = BASIS_NAME_STEM
            # Bidirectional stem lookup — reaches any device (Protect,
            # Frigate, Reolink…) that owns a camera/person entity sharing
            # this stem. Required for Frigate -> Protect direction (egress
            # cameras: doorbell_lite, front_door_aerial, madrone_g6_entry —
            # GOLDEN_MASTER BLOCK-1). EXACT-stem lookups are always safe
            # (same-stem == same physical camera by construction).
            for lookup in (stem, _strip_camera_resolution_suffix(stem)):
                for sibling_did in self._stem_to_device_ids.get(lookup, ()):
                    if sibling_did not in expanded:
                        expanded[sibling_did] = BASIS_NAME_STEM
            # A-MED-2/C-MED-2 GUARDED disambiguation collapse: only accept
            # a `_N`-stripped sibling when it shares evidence with the input
            # (MAC connection, identifier tuple, OR both devices are frigate
            # — the explicit cross-host case). Unrelated cameras that happen
            # to share a first token (e.g. `camera_a` vs a physically
            # distinct `camera_a_2`) are NOT collapsed.
            dstem = _strip_disambiguation_suffix(_strip_camera_resolution_suffix(stem))
            if dstem and dstem in self._dstem_to_device_ids:
                for sibling_did in self._dstem_to_device_ids.get(dstem, ()):
                    if sibling_did in expanded:
                        continue
                    if self._shares_evidence_with_inputs(sibling_did, device_ids):
                        expanded[sibling_did] = BASIS_NAME_STEM

        # ---- F2 collapse: pre-select the winning Frigate device per object-name
        # A-M3 fix — deterministic winner:
        #   (1) person_bs state == "on"
        #   (2) person_bs state not in (unavailable, unknown, None)
        #   (3) lowest sorted device_id
        # D-MED-1 observability: INFO log every collapse fire.
        # -------------------------------------------------------------------
        frigate_dropped: set[str] = set()
        if not FRIGATE_CROSS_HOST_CORROBORATION_ENABLED:
            frigate_by_obj: dict[str, list[str]] = {}
            for did in expanded:
                dev = self._device(did)
                if self._infer_integration(dev) != PLATFORM_FRIGATE:
                    continue
                obj = self._frigate_object_name_for_device(dev)
                if obj:
                    frigate_by_obj.setdefault(obj, []).append(did)
            for obj, dids in frigate_by_obj.items():
                if len(dids) <= 1:
                    continue

                def _read_state(did: str) -> str | None:
                    p_bs, *_ = self._scan_device_entities(
                        did, PLATFORM_FRIGATE, stem_filter=device_stems.get(did)
                    )
                    if not p_bs or self._state_getter is None:
                        return None
                    try:
                        st = self._state_getter(p_bs)
                    except Exception:  # noqa: BLE001
                        return None
                    if st is None:
                        return None
                    return getattr(st, "state", None) if not isinstance(st, str) else st

                def _rank(did: str):
                    s = _read_state(did)
                    if s == "on":
                        return (0, did)
                    if s and s not in ("unavailable", "unknown"):
                        return (1, did)
                    return (2, did)

                ordered = sorted(dids, key=_rank)
                winner = ordered[0]
                losers = ordered[1:]
                for l in losers:
                    frigate_dropped.add(l)
                _LOGGER.info(
                    "CameraResolver: F2 collapse fired — object=%s winner=%s "
                    "losers=%s (gate FRIGATE_CROSS_HOST_CORROBORATION_ENABLED=False)",
                    obj, winner, losers,
                )

        # ---- Build FusionSources per resolved device --------------------
        # Iterate in deterministic device_id order so the primary source and
        # attribution ordering are byte-stable across restarts.
        sources: list[FusionSource] = []
        for did in sorted(expanded.keys()):
            basis = expanded[did]
            if did in frigate_dropped:
                continue
            dev = self._device(did)
            integration = self._infer_integration(dev)
            # Gather entities on this device.
            person_bs, face_bs, face_cap, count_s, person_sw, face_sw = self._scan_device_entities(
                did, integration, stem_filter=device_stems.get(did)
            )

            if not (person_bs or face_bs or count_s or person_sw):
                # Device contributes nothing to the fusion — skip.
                continue

            src_basis = basis
            sources.append(FusionSource(
                integration=integration,
                device_id=did,
                person_binary_sensor=person_bs,
                face_binary_sensor=face_bs,
                face_capability=face_cap,
                person_count_sensor=count_s,
                person_detect_switch=person_sw,
                face_detect_switch=face_sw,
                correlation_basis=src_basis,
            ))

        # Post-fusion dedup by (integration, device_id) — belt-and-suspenders.
        deduped: dict[tuple[str, str], FusionSource] = {}
        for s in sources:
            deduped.setdefault((s.integration, s.device_id), s)
        sources = list(deduped.values())

        physical_camera_id = sorted(device_ids)[0] if device_ids else ""
        # D'-MED-1: collect the dropped losers' person sensors so consumers
        # can subscribe to their recovery and re-resolve.
        dropped_sensors: list[str] = []
        for did in sorted(frigate_dropped):
            d_bs, *_rest = self._scan_device_entities(
                did, self._infer_integration(self._device(did)),
                stem_filter=device_stems.get(did),
            )
            if d_bs:
                dropped_sensors.append(d_bs)
        return RoomCameraFusion(
            physical_camera_id=physical_camera_id,
            sources=sources,
            dropped_person_sensors=dropped_sensors,
        )

    # ---- Cycle-3 resolver-legs: multi-integration family sensor lookup ----

    def resolve_detection_legs(
        self,
        camera_entity_id: str,
        family: str,
        *,
        stem_aliases: dict[str, str] | None = None,
        stem_hint: str | None = None,
    ) -> list[DetectionLeg]:
        """Return every integration's detection sensors for ``family``.

        Cycle-3 resolver-legs (2026-08-07). Consumed by PerimeterAlertManager
        setup + rescan; replaces the retired ``_fused_sibling`` /
        ``_protect_person_legs`` / ``_derive_sibling_sensor`` triplet.

        Uses the existing correlation ladder (rungs 1-5) to expand the
        camera device into its correlated device set, then scans every
        device's entities for binary_sensors matching ``family``'s suffix
        set. HA disambiguation (``_2``, ``_3``, ...) is treated as a
        second engine leg for the same integration (frigate ``_2`` =
        frigate2 host, protect ``_2`` = protect2 leg).

        ``stem_aliases`` bridges native-AI stems whose slug diverges from
        the Frigate object name (verified live 2026-08-07:
        ``ptzcamreolinktmixpstudybporch`` vs Frigate ``reolinkstudybporchptz``;
        ``armcrestpooloverhead`` vs Frigate ``armcrest``). Applied both
        directions: a resolved Frigate stem alias-maps to the native slug
        for entity lookup; an operator-configured native camera alias-
        maps to the Frigate stem for cross-engine discovery. Frigate
        devices carry no MAC connections on this deployment (verified
        via device_registry probe 2026-08-07), so MAC-rung joins cannot
        bridge them.

        Returns DetectionLegs in deterministic (entity_id) order — so
        the setup coverage log + telemetry key order are byte-stable.
        Never raises on registry errors; degrades to empty list.
        """
        family = (family or "").lower()
        suffixes = _FAMILY_SUFFIXES.get(family)
        if suffixes is None:
            _LOGGER.debug(
                "CameraResolver.resolve_detection_legs: unknown family %r "
                "(known: %s)",
                family, sorted(_FAMILY_SUFFIXES.keys()),
            )
            return []

        try:
            did = self.resolve_entity_to_device_id(camera_entity_id)
        except Exception:  # noqa: BLE001
            return []
        if not did:
            return []

        # Correlated device set via the existing ladder.
        try:
            fusion = self.resolve_capabilities([did])
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "CameraResolver.resolve_detection_legs: capabilities "
                "resolve failed for %s", camera_entity_id, exc_info=True,
            )
            return []
        device_ids: set[str] = {s.device_id for s in fusion.sources}
        device_ids.add(did)

        # Stem-alias bridge for native-AI cameras whose slug diverges
        # from the Frigate object name (MAC rung cannot bridge because
        # Frigate devices carry no MAC connections on this deployment).
        # Consult the bidirectional stem index built at construction.
        try:
            stems = self._compute_device_stems([did])
        except Exception:  # noqa: BLE001
            stems = {}
        base_stem = stems.get(did) or _strip_camera_resolution_suffix(
            _entity_name(camera_entity_id)
        )
        candidate_stems: set[str] = set()
        if base_stem:
            candidate_stems.add(base_stem)
            candidate_stems.add(_strip_disambiguation_suffix(base_stem))
        # RESACC-1 A-2 fix: caller-provided stem hint bridges cases where
        # `_compute_device_stems` picks up a camera name with a device-
        # specific suffix (e.g. `armcrestpooloverhead_main`) that is not
        # in `_CAMERA_RESOLUTION_SUFFIXES` and so misses the alias entry.
        # enumerate_platform_cameras passes the enumeration stem here.
        if stem_hint:
            candidate_stems.add(stem_hint)
            candidate_stems.add(_strip_disambiguation_suffix(stem_hint))
        if stem_aliases:
            for stem in list(candidate_stems):
                aliased = stem_aliases.get(stem)
                if aliased:
                    candidate_stems.add(aliased)
                # Reverse-alias: if base_stem is the alias TARGET, pull
                # in every native slug that maps to it (armcrest ->
                # armcrestpooloverhead).
                for native, canonical in stem_aliases.items():
                    if canonical == stem and native:
                        candidate_stems.add(native)
        for stem in candidate_stems:
            for extra_did in self._stem_to_device_ids.get(stem, ()):
                device_ids.add(extra_did)

        # Scan each device for family-suffixed binary sensors.
        legs: list[DetectionLeg] = []
        seen_eids: set[str] = set()
        try:
            entities = list(self._er.entities.values())
        except Exception:  # noqa: BLE001
            entities = []
        for ent in entities:
            ent_did = getattr(ent, "device_id", None)
            if ent_did not in device_ids:
                continue
            if getattr(ent, "disabled_by", None) is not None:
                continue
            eid = getattr(ent, "entity_id", "") or ""
            if not eid.startswith("binary_sensor."):
                continue
            name = _entity_name(eid)
            integration = self._infer_integration(self._device(ent_did))
            # F13 (cycle-3 fix-up 2026-08-07): defense-in-depth — exclude
            # ANY `_package_*` family entity regardless of inferred
            # integration, so a device with empty identifiers can't sneak
            # a package-person leg into the fusion.
            if _is_package_detector(eid):
                continue
            # F13: log once per device when integration inference fails
            # instead of silently tagging engine "unknown".
            if not integration and ent_did:
                if not hasattr(self, "_unknown_integration_logged"):
                    self._unknown_integration_logged = set()
                if ent_did not in self._unknown_integration_logged:
                    self._unknown_integration_logged.add(ent_did)
                    _LOGGER.debug(
                        "CameraResolver.resolve_detection_legs: device %s "
                        "has no inferable integration; engine will be "
                        "tagged 'unknown' for its legs.", ent_did,
                    )
            # Suffix match — with `_2`/`_N` disambiguation stripped.
            stripped_name = _strip_disambiguation_suffix(name)
            matched = False
            for suf in suffixes:
                if name.endswith(suf) or stripped_name.endswith(suf):
                    matched = True
                    break
            if not matched:
                continue
            if eid in seen_eids:
                continue
            seen_eids.add(eid)
            engine = self._engine_tag(integration, name, ent_did)
            legs.append(DetectionLeg(
                entity_id=eid,
                engine=engine,
                integration=integration,
                device_id=ent_did or "",
            ))
        legs.sort(key=lambda l: l.entity_id)
        return legs

    # ---- TRANSIT-1 (2026-08-07): platform-first enumeration --------------

    def enumerate_platform_cameras(
        self,
        platform: str,
        family: str = "person",
    ) -> list[EnumeratedCamera]:
        """Enumerate physical cameras of ``platform`` that expose a ``family`` detector.

        Walks the entity registry, keeps enabled ``binary_sensor.*`` entities
        whose ``.platform`` matches AND whose entity name carries a suffix in
        ``_FAMILY_SUFFIXES[family]`` (with the ``_N`` disambiguation strip),
        excluding ``_package_*`` detectors. Groups by ``device_id`` (one
        ``EnumeratedCamera`` per physical camera).

        For each grouped device the returned ``legs`` set is the union of
        every detection leg ``resolve_detection_legs`` pulls in for the
        primary entity — so Frigate F1/F2 twins and native-AI siblings of
        the same physical camera collapse into ONE row with all their
        entity_ids in ``.legs``.

        Area attribution: prefer the platform's own leg (Protect is
        authoritative per AUDIT_resolver_ground_truth_manual.md §A-3);
        on ``None``, fall back across the sibling legs until a non-None
        area is found. Pure — no HA API calls, drives off the duck-typed
        registries the resolver was built with.

        Never raises; degrades to ``[]`` on any registry error.
        """
        family = (family or "").lower()
        suffixes = _FAMILY_SUFFIXES.get(family)
        if suffixes is None:
            _LOGGER.debug(
                "CameraResolver.enumerate_platform_cameras: unknown family %r "
                "(known: %s)", family, sorted(_FAMILY_SUFFIXES.keys()),
            )
            return []

        try:
            entities = list(getattr(self._er, "entities", {}).values())
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "CameraResolver.enumerate_platform_cameras: entity registry "
                "walk failed", exc_info=True,
            )
            return []

        # F3 fix (TRANSIT-1 fix-up): a Protect NVR device can host MULTIPLE
        # physical cameras (e.g. `staircase_person_detected` +
        # `garagehallway_person_detected` on the same NVR). Group by
        # (device_id, stem) — the stem is the entity name with the family
        # suffix and any `_N` disambiguation stripped — so each physical
        # camera surfaces as its OWN EnumeratedCamera row with its OWN
        # area attribution. Grouping by device_id alone silently collapses
        # them into one row and drops coverage.
        def _stem_of(name: str) -> str | None:
            for suf in suffixes:
                if name.endswith(suf):
                    return name[: -len(suf)]
                stripped = _strip_disambiguation_suffix(name)
                if stripped.endswith(suf):
                    return stripped[: -len(suf)]
            return None

        # (device_id, stem) -> primary entity_id (prefer shortest / base entity
        # for stable ordering and to avoid picking a `_2` disambiguated variant
        # as the representative).
        groups: dict[tuple[str, str], str] = {}
        for ent in entities:
            if getattr(ent, "platform", None) != platform:
                continue
            if getattr(ent, "disabled_by", None) is not None:
                continue
            did = getattr(ent, "device_id", None)
            if not did:
                continue
            eid = getattr(ent, "entity_id", "") or ""
            if not eid.startswith("binary_sensor."):
                continue
            if _is_package_detector(eid):
                continue
            name = _entity_name(eid)
            stem = _stem_of(name)
            if not stem:
                continue
            key = (did, stem)
            prev = groups.get(key)
            if prev is None or len(eid) < len(prev) or (len(eid) == len(prev) and eid < prev):
                groups[key] = eid

        results: list[EnumeratedCamera] = []
        for (did, stem), primary_eid in groups.items():
            # Wire EXTERIOR_CAMERA_KEY_ALIASES into enumeration so
            # native-AI stems whose slug diverges from the canonical
            # (e.g. `armcrestpooloverhead` → `armcrest`) fuse their
            # sibling legs. Without this, enumerating `dahua` sees the
            # dahua leg only and misses the frigate `armcrest` sibling
            # (A-2 area-attribution regression).
            _CAM_ALIASES = None
            try:
                from .const import EXTERIOR_CAMERA_KEY_ALIASES as _CAM_ALIASES  # type: ignore[no-redef]
            except Exception:  # noqa: BLE001
                # Fallback for direct-source test imports where relative
                # package import isn't available.
                try:
                    import importlib.util as _ilu
                    from pathlib import Path as _P
                    _const_path = _P(__file__).with_name("const.py")
                    _cs = _ilu.spec_from_file_location("_ura_const_for_resolver", _const_path)
                    _cm = _ilu.module_from_spec(_cs)
                    _cs.loader.exec_module(_cm)
                    _CAM_ALIASES = getattr(_cm, "EXTERIOR_CAMERA_KEY_ALIASES", None)
                except Exception:  # noqa: BLE001
                    _CAM_ALIASES = None
            try:
                all_legs = self.resolve_detection_legs(
                    primary_eid, family,
                    stem_aliases=_CAM_ALIASES,
                    stem_hint=stem,
                )
            except Exception:  # noqa: BLE001
                all_legs = []

            # F3 fix continued: filter legs to this stem so an NVR device's
            # other physical cameras don't bleed into this row. A leg's
            # entity-name (with family suffix + `_N` stripped) must equal or
            # start with `<stem>` (word-boundary — same semantics as the
            # `_scan_device_entities` stem filter).
            def _leg_matches_stem(leg_eid: str) -> bool:
                nm = _entity_name(leg_eid)
                # Strip family suffix (any) then `_N`
                inner: str | None = None
                for suf in suffixes:
                    if nm.endswith(suf):
                        inner = nm[: -len(suf)]
                        break
                if inner is None:
                    stripped = _strip_disambiguation_suffix(nm)
                    for suf in suffixes:
                        if stripped.endswith(suf):
                            inner = stripped[: -len(suf)]
                            break
                if inner is None:
                    return False
                inner_stripped = _strip_disambiguation_suffix(inner)
                base = _strip_disambiguation_suffix(stem)
                # Alias-aware: a leg whose inner equals the canonical
                # alias of stem (or vice-versa) is the same physical
                # camera — e.g. dahua leg stem `armcrestpooloverhead`
                # ↔ frigate leg inner `armcrest`.
                alias_map = _CAM_ALIASES or {}
                stem_alias = alias_map.get(stem)
                inner_alias = alias_map.get(inner)
                return (
                    inner == stem or inner_stripped == base
                    or inner.startswith(stem + "_")
                    or inner_stripped.startswith(base + "_")
                    or (stem_alias is not None and (inner == stem_alias or inner.startswith(stem_alias + "_")))
                    or (inner_alias is not None and (inner_alias == stem or inner_alias.startswith(stem + "_")))
                )

            filtered_legs = [l for l in all_legs if _leg_matches_stem(l.entity_id)]
            leg_eids = tuple(l.entity_id for l in filtered_legs) if filtered_legs else (primary_eid,)

            # RESACC-1 A-2/A-3 fix (2026-08-09): arbitrate across ALL
            # grouped legs by CANONICAL_AREA_PRECEDENCE so the same
            # physical camera resolves to the same area regardless of
            # which platform was enumerated (determinism). This supersedes
            # the F4 same-integration guard — F3 grouping (RESACC-1
            # measured 39/39 recall, 0 precision violations, adversarial
            # near-miss clean) is the evidence that made the guard
            # unnecessary. The primary's OWN area wins when its
            # integration is at the top of the precedence (natural
            # tie-break — Protect primaries stay authoritative on the
            # exterior perimeter); a lower-precedence primary (e.g. a
            # dahua leg whose device-area is mis-set to `balcony`) is
            # correctly overridden by a higher-precedence sibling
            # (Frigate `pool`, A-2).
            #
            # Fail-open: any exception in area resolution leaves the
            # value None; never raises into the caller.
            leg_areas: list[tuple[str, str]] = []
            all_lookup_legs: list[tuple[str, str]] = [(primary_eid, platform)]
            for leg in filtered_legs:
                if leg.entity_id == primary_eid:
                    continue
                all_lookup_legs.append((leg.entity_id, leg.integration or ""))
            for eid, integ in all_lookup_legs:
                try:
                    a = resolve_area_id_for_entity(self._er, self._dr, eid)
                except Exception:  # noqa: BLE001
                    a = None
                if a:
                    leg_areas.append((integ, a))

            area: str | None = None
            for pref in CANONICAL_AREA_PRECEDENCE:
                for integ, a in leg_areas:
                    if integ == pref:
                        area = a
                        break
                if area:
                    break
            # Fallback: any leg area at all, if precedence didn't match
            # (e.g. integration name outside the known set).
            if not area and leg_areas:
                area = leg_areas[0][1]

            results.append(EnumeratedCamera(
                device_id=did,
                area_id=area,
                legs=leg_eids,
                primary_entity=primary_eid,
            ))

        results.sort(key=lambda c: c.primary_entity)
        return results

    def _engine_tag(self, integration: str, entity_name: str, device_id: str | None) -> str:
        """Map (integration, entity_name, device_id) -> engine label.

        Engines: frigate, frigate2, protect, protect2, reolink, amcrest,
        dahua. F1 vs F2 (both platform=frigate) split by HA `_N`
        disambiguation on the entity name — F2 sensors were registered
        second so HA minted `_2` at registration time (verified in
        AUDIT_frigate1_sunset.md §4). Native-AI + Protect follow the
        same suffix convention on their `_2` siblings.
        """
        import re as _re
        m = _re.search(r"_(\d+)$", entity_name)
        suffix_n: int | None = int(m.group(1)) if m else None
        if integration == PLATFORM_FRIGATE:
            return "frigate2" if suffix_n and suffix_n >= 2 else "frigate"
        if integration == PLATFORM_UNIFI:
            return "protect2" if suffix_n and suffix_n >= 2 else "protect"
        if integration == PLATFORM_REOLINK:
            return "reolink"
        if integration == PLATFORM_AMCREST:
            return "amcrest"
        if integration == PLATFORM_DAHUA:
            return "dahua"
        return integration or "unknown"

    # ---- Internals ---------------------------------------------------------

    def _device(self, device_id: str) -> Any | None:
        try:
            return self._dr.async_get(device_id)
        except Exception:
            return getattr(self._dr, "devices", {}).get(device_id)

    def _infer_integration(self, dev: Any | None) -> str:
        if dev is None:
            return ""
        for ident in getattr(dev, "identifiers", None) or ():
            try:
                integ, _ = ident
            except Exception:
                continue
            if integ:
                return integ
        # GOLDEN_MASTER bonus finding: live UniFi Protect devices carry
        # empty identifiers on this deployment, which made the F1 stem
        # filter inert. Fall back to any owned entity's `.platform`
        # (populated for both Protect and Frigate) so F1 becomes live.
        did = getattr(dev, "id", None)
        if did:
            return self._device_platform_hint.get(did, "")
        return ""

    def _shares_evidence_with_inputs(
        self, candidate_did: str, input_device_ids: list[str]
    ) -> bool:
        """A-MED-2/C-MED-2 shared-evidence gate for disambiguation collapse.

        Return True iff candidate device shares a MAC connection, an
        identifier tuple with any input device, OR both candidate and any
        input device are `frigate` (the explicit cross-host case: same
        physical camera surfaced via two Frigate hosts).
        """
        cand = self._device(candidate_did)
        if cand is None:
            return False
        cand_macs = {_norm_mac(c[1]) for c in (getattr(cand, "connections", None) or ())
                     if isinstance(c, tuple) and len(c) == 2 and c[0] == "mac" and c[1]}
        cand_idents = {tuple(i) for i in (getattr(cand, "identifiers", None) or ())
                       if isinstance(i, tuple) and len(i) == 2}
        cand_frigate = self._infer_integration(cand) == PLATFORM_FRIGATE
        for did in input_device_ids:
            dev = self._device(did)
            if dev is None:
                continue
            in_macs = {_norm_mac(c[1]) for c in (getattr(dev, "connections", None) or ())
                       if isinstance(c, tuple) and len(c) == 2 and c[0] == "mac" and c[1]}
            if cand_macs & in_macs:
                return True
            in_idents = {tuple(i) for i in (getattr(dev, "identifiers", None) or ())
                         if isinstance(i, tuple) and len(i) == 2}
            if cand_idents & in_idents:
                return True
            if cand_frigate and self._infer_integration(dev) == PLATFORM_FRIGATE:
                return True
        return False

    def _frigate_object_name_for_device(self, dev: Any | None) -> str | None:
        if dev is None:
            return None
        for ident in getattr(dev, "identifiers", None) or ():
            try:
                integ, key = ident
            except Exception:
                continue
            if integ == PLATFORM_FRIGATE and isinstance(key, str):
                return key.rsplit(":", 1)[-1] if ":" in key else key
        return None

    def _compute_device_stems(self, device_ids: list[str]) -> dict[str, str]:
        """For each input device, extract a canonical stem from any camera.*
        or person/face binary_sensor entity it owns. Used for F1 filtering
        and for the name-stem rung.
        """
        out: dict[str, str] = {}
        try:
            entities = list(self._er.entities.values())
        except Exception:
            entities = []
        by_dev: dict[str, list[Any]] = {}
        for ent in entities:
            did = getattr(ent, "device_id", None)
            if did in device_ids:
                by_dev.setdefault(did, []).append(ent)
        for did, ents in by_dev.items():
            stem: str | None = None
            # Prefer camera.* entity as the canonical stem source.
            for ent in ents:
                if getattr(ent, "domain", None) == "camera":
                    stem = _entity_name(ent.entity_id)
                    break
            if stem is None:
                for ent in ents:
                    s = _strip_suffix(_entity_name(ent.entity_id), _PERSON_SUFFIXES)
                    if s:
                        stem = s
                        break
            if stem:
                # D-HIGH-1 (D's stem keyspace fix): the Frigate identifier index
                # keys off the object-name (e.g. "staircase"); a UniFi camera
                # entity name typically carries a resolution suffix (e.g.
                # "staircase_high_resolution_channel"). Strip the suffix so
                # rung-5 lookup can match Frigate<->Protect on the same base.
                out[did] = _strip_camera_resolution_suffix(stem)
        return out

    def _scan_device_entities(
        self,
        device_id: str,
        integration: str,
        *,
        stem_filter: str | None,
    ) -> tuple[str | None, str | None, str, str | None, str | None, str | None]:
        """Return (person_bs, face_bs, face_capability, count_sensor,
        person_switch, face_switch) for a device.

        F1 fix: when integration is UniFi Protect AND a stem_filter is provided,
        only entities whose name-stem starts with the same prefix as the input
        camera participate. This prevents the NVR-style Protect device (which
        can host multiple physical cameras, e.g. the staircase+garagehallway
        record documented in AUDIT §F1) from fusing sensors from a DIFFERENT
        physical camera into the wrong room.
        """
        person_bs: str | None = None
        face_bs: str | None = None
        face_cap: str = FACE_ABSENT
        count_s: str | None = None
        person_sw: str | None = None
        face_sw: str | None = None

        try:
            entities = [e for e in self._er.entities.values()
                        if getattr(e, "device_id", None) == device_id]
        except Exception:
            entities = []

        def _stem_match(entity_id: str) -> bool:
            # F1: within a Protect device that hosts multiple cameras, only
            # accept entities whose name-stem equals the camera's FULL stripped
            # base OR starts with `<base>_` (word-boundary semantics). No
            # first-token / bare-substring fallback — that was A-M5 / E-HIGH-3
            # / D-HIGH-1: three independent findings that the permissive
            # prefix-compare would silently pull in unrelated cameras that
            # happen to share a first token (e.g. "garage_*" siblings on a
            # "garagehallway_*" device).
            if integration != PLATFORM_UNIFI or not stem_filter:
                return True
            name = _entity_name(entity_id)
            base = _strip_camera_resolution_suffix(stem_filter)
            if not base:
                return True
            return name == base or name.startswith(base + "_")

        for ent in entities:
            eid = getattr(ent, "entity_id", "")
            domain = getattr(ent, "domain", "") or (eid.split(".", 1)[0] if "." in eid else "")
            disabled_by = getattr(ent, "disabled_by", None)
            # A-L2 fix: package-person detector filter is a Frigate-only concept
            # (Frigate's package-object detector shares a stem with its person
            # detector). Do NOT apply to other integrations.
            if integration == PLATFORM_FRIGATE and _is_package_detector(eid):
                continue
            if not _stem_match(eid):
                continue

            if domain == "binary_sensor":
                if _has_any_suffix(eid, _PERSON_SUFFIXES) and disabled_by is None:
                    if person_bs is None:
                        person_bs = eid
                elif _has_any_suffix(eid, _FACE_SUFFIXES):
                    if face_bs is None:
                        face_bs = eid
                    # A-M4 (sticky escalation): USABLE never demotes to AMBIGUOUS.
                    # Once ANY enabled face entity is seen, capability stays USABLE
                    # even if a later disabled face entity is scanned.
                    if disabled_by is None:
                        face_cap = FACE_USABLE
                    elif face_cap == FACE_ABSENT:
                        face_cap = FACE_AMBIGUOUS
            elif domain == "sensor":
                if _entity_name(eid).endswith(_PERSON_COUNT_SUFFIX) and disabled_by is None:
                    if count_s is None:
                        count_s = eid
                elif _has_any_suffix(eid, _FACE_SUFFIXES):
                    # sensor.<stem>_last_recognized_face — presence indicates face capability.
                    # A-M4: sticky USABLE.
                    if disabled_by is None:
                        face_cap = FACE_USABLE
                    elif face_cap == FACE_ABSENT:
                        face_cap = FACE_AMBIGUOUS
            elif domain == "switch":
                if _has_any_suffix(eid, _PERSON_SWITCH_SUFFIXES) and disabled_by is None:
                    if person_sw is None:
                        person_sw = eid
                elif _has_any_suffix(eid, _FACE_SWITCH_SUFFIXES):
                    if face_sw is None:
                        face_sw = eid

        return person_bs, face_bs, face_cap, count_s, person_sw, face_sw


# ---------------------------------------------------------------------------
# D4 auto-enable helper (dry-run gated).
# ---------------------------------------------------------------------------


def collect_person_switches_to_enable(
    fusions: Iterable[RoomCameraFusion],
    state_getter: Callable[[str], Any | None],
) -> list[str]:
    """Return the person-detect switch entity_ids that would be turned on.

    Face switches are NEVER included (invariant). The caller decides whether
    to actually call switch.turn_on (production) or just log the list
    (dry-run per CAMERA_AUTOENABLE_DRY_RUN).
    """
    out: list[str] = []
    for fusion in fusions:
        for sw in fusion.person_detect_switch_entity_ids():
            try:
                st = state_getter(sw)
            except Exception:
                st = None
            if st is None:
                # A-L4 contract: a None state read means the entity is NOT
                # in the state machine yet (registry-only / restart transient).
                # We INCLUDE it in the dry-run inventory so the operator sees
                # every candidate; the production call site (once wired) MUST
                # re-check state at call time and skip if still None. This is
                # the dry-run-first invariant — visibility beats silence.
                out.append(sw)
                continue
            state_val = getattr(st, "state", None) if not isinstance(st, str) else st
            if state_val == "off":
                out.append(sw)
    return out
