"""Room rules: the one compiler, validator, preview renderer and record adapter.

AI-ROOM-RULES-TRUST-REPAIR-1 (``docs/planning/PLANNING_unified_room_rules.md``
D1-D4, D8). A room rule is ONE record however it was authored ("describe a
rule" in words, or "run an automation when X"):

    {rule_id, source: "described" | "automation", trigger_type, person,
     conditions, enabled, actions, ...}

* ``compile_rule`` turns a description into validated actions + conditions
  through ``ai_task.generate_data`` with TEXT-only structure fields
  (``ROOM_RULE_STRUCTURE``). Two failure kinds stay apart:
  ``model_unavailable`` (the AI Task call itself failed: entity missing or
  unavailable, service error, timeout) and ``parse_failed`` (a response came
  back but did not validate). Saved rules never call the model.
* ``render_rule_preview`` is a pure function of the stored trigger, person,
  conditions and actions (INV-R4): LLM text never describes what a rule does.
* ``adapt_rules`` is the read-time adapter (stored config is not rewritten):
  ``CONF_AI_RULES`` entries plus legacy ``CONF_AUTOMATION_CHAINS`` bindings.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Any, Callable, Iterable, Mapping

from .const import (
    AI_RULE_ALLOWED_DOMAINS,
    AI_RULE_PARSING_PROMPT,
    CONF_AI_RULES,
    CONF_AREA_ID,
    CONF_AUTO_DEVICES,
    CONF_AUTO_SWITCHES,
    CONF_AUTOMATION_CHAINS,
    CONF_COVERS,
    CONF_FANS,
    CONF_LIGHTS,
    CONF_MANUAL_DEVICES,
    CONF_MANUAL_SWITCHES,
    CONF_NIGHT_LIGHTS,
    ROOM_RULE_CONDITION_TYPES,
    ROOM_RULE_DATA_KEYS,
    ROOM_RULE_STRUCTURE,
    RULE_PARSE_TIMEOUT_S,
    HOUSE_STATE_TRIGGER_VALUES,
    TRIGGER_ENERGY_CONSTRAINT,
    TRIGGER_ENTER,
    TRIGGER_EXIT,
    TRIGGER_HOUSE_STATE_PREFIX,
    TRIGGER_LUX_BRIGHT,
    TRIGGER_LUX_DARK,
    TRIGGER_SAFETY_HAZARD,
    TRIGGER_SECURITY_EVENT,
)
from .person_ids import display_of, slug_of

_LOGGER = logging.getLogger(__name__)

# The compiler never emits climate (the runtime gate blocks it too).
ROOM_RULE_ALLOWED_DOMAINS: frozenset = AI_RULE_ALLOWED_DOMAINS - {"climate"}
# Domains where `toggle` is rejected: the light manual-hold oracle only
# covers turn_on / turn_off (plan INV-R1, review MEDIUM-2).
_TOGGLE_REJECTED_DOMAINS: frozenset = frozenset({"light", "switch"})
# Targets in these domains may be any existing entity of that domain
# (an automation or scene is rarely in the room's area).
_ANY_ENTITY_DOMAINS: frozenset = frozenset({"automation", "scene"})

SOURCE_DESCRIBED = "described"
SOURCE_AUTOMATION = "automation"

KIND_OK = "ok"
KIND_MODEL_UNAVAILABLE = "model_unavailable"
KIND_PARSE_FAILED = "parse_failed"
KIND_UNSUPPORTED = "unsupported"

TASK_NAME = "ura_parse_room_rule"

_HOUSE_STATE_LABELS = {
    "away": "Away", "arriving": "Arriving", "home_day": "Home Day",
    "home_evening": "Home Evening", "home_night": "Home Night",
    "sleep": "Sleep", "waking": "Waking", "guest": "Guest",
    "vacation": "Vacation",
}


# ---------------------------------------------------------------------------
# Record adapter (D4, D8)
# ---------------------------------------------------------------------------


def stored_rules(entry: Any) -> tuple[list, bool]:
    """``(rules, data_only)``: the rule list read options first, then data
    (the existing fallback). ``data_only`` is True when the list came from
    ``entry.data`` (written by the retired room-creation flow)."""
    options = getattr(entry, "options", None) or {}
    data = getattr(entry, "data", None) or {}
    if CONF_AI_RULES in options:
        return list(options.get(CONF_AI_RULES) or []), False
    raw = list(data.get(CONF_AI_RULES) or [])
    return raw, bool(raw)


def stored_chains(entry: Any) -> dict:
    options = getattr(entry, "options", None) or {}
    data = getattr(entry, "data", None) or {}
    chains = options.get(CONF_AUTOMATION_CHAINS, data.get(CONF_AUTOMATION_CHAINS, {}))
    return dict(chains) if isinstance(chains, dict) else {}


def _actions_well_formed(actions: Any) -> bool:
    if not isinstance(actions, list) or not actions:
        return False
    for a in actions:
        if not isinstance(a, dict):
            return False
        if not isinstance(a.get("domain"), str) or not isinstance(a.get("service"), str):
            return False
    return True


def automation_action(automation_entity: str, skip_condition: bool) -> dict:
    """The one action an "automation" rule carries (routes through the gate)."""
    return {
        "domain": "automation",
        "service": "trigger",
        "target": {"entity_id": automation_entity},
        "data": {"skip_condition": bool(skip_condition)},
    }


def adapt_rules(rules: Iterable[Any], chains: Mapping[str, Any] | None = None,
                *, data_only: bool = False) -> list[dict]:
    """Normalise stored rules + legacy chains into one record list.

    Automation rules come first (the old chain order). A legacy chain entry
    becomes source ``automation`` with ``skip_condition`` False (the
    automation's own conditions apply; HA's default is True: a deliberate
    behaviour change, README). ``needs_parse`` is True for a rule with no
    well-formed action, a rule flagged ``needs_parsing``, or a rule that
    lives only in ``entry.data`` (D8): such a rule never runs.
    """
    out_auto: list[dict] = []
    out_desc: list[dict] = []
    for trig, auto_id in (chains or {}).items():
        if not isinstance(auto_id, str) or not auto_id:
            continue
        out_auto.append({
            "rule_id": f"chain_{trig}",
            "source": SOURCE_AUTOMATION,
            "trigger_type": str(trig),
            "person": "",
            "conditions": [],
            "enabled": True,
            "actions": [automation_action(auto_id, False)],
            "automation_entity": auto_id,
            "skip_condition": False,
            "description": "",
            "summary": "",
            "created_at": None,
            "needs_parse": False,
            "legacy_chain": True,
        })
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        source = r.get("source") or SOURCE_DESCRIBED
        actions = r.get("actions")
        conds = r.get("conditions") or []
        rec = {
            "rule_id": str(r.get("rule_id") or ""),
            "source": source,
            "trigger_type": str(r.get("trigger_type") or ""),
            "person": str(r.get("person") or "").strip(),
            "conditions": list(conds) if isinstance(conds, list) else [],
            "enabled": bool(r.get("enabled", True)),
            "actions": list(actions) if isinstance(actions, list) else [],
            "automation_entity": r.get("automation_entity"),
            "skip_condition": bool(r.get("skip_condition", False)),
            "description": str(r.get("description") or ""),
            "summary": str(r.get("summary") or ""),
            "created_at": r.get("created_at"),
            "needs_parse": bool(
                data_only
                or r.get("needs_parsing")
                or not _actions_well_formed(actions)
                or not isinstance(conds, list)
            ),
            "legacy_chain": False,
        }
        (out_auto if source == SOURCE_AUTOMATION else out_desc).append(rec)
    return out_auto + out_desc


def rules_for_entry(entry: Any) -> list[dict]:
    """The adapted record list for one room entry (the executor's read)."""
    rules, data_only = stored_rules(entry)
    return adapt_rules(rules, stored_chains(entry), data_only=data_only)


def rule_status(rec: Mapping[str, Any]) -> str:
    """Per-rule status: ``needs_parse`` > ``disabled`` > ``active``."""
    if rec.get("needs_parse"):
        return "needs_parse"
    if not rec.get("enabled", True):
        return "disabled"
    return "active"


# ---------------------------------------------------------------------------
# Room entity set (D1): one definition feeds the prompt AND validation
# ---------------------------------------------------------------------------


def room_entity_set(hass: Any, cfg: Mapping[str, Any]) -> list[dict]:
    """The room's configured devices + every enabled entity in its HA area
    (entity registry ``area_id``). Each item: ``{entity_id, name, domain}``;
    only entities HA has a state for. Climate entities are left out: every
    climate action is rejected (climate block), so offering one to the model
    only invites parse failures."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(eid: Any) -> None:
        if not isinstance(eid, str) or eid in seen or eid.startswith("climate."):
            return
        st = hass.states.get(eid)
        if st is None:
            return
        seen.add(eid)
        out.append({
            "entity_id": eid,
            "name": (getattr(st, "attributes", {}) or {}).get("friendly_name", eid),
            "domain": eid.split(".")[0],
        })

    for key in (CONF_LIGHTS, CONF_NIGHT_LIGHTS, CONF_FANS, CONF_AUTO_DEVICES,
                CONF_MANUAL_DEVICES, CONF_COVERS, CONF_AUTO_SWITCHES,
                CONF_MANUAL_SWITCHES):
        for eid in cfg.get(key, []) or []:
            add(eid)
    area_id = cfg.get(CONF_AREA_ID)
    if area_id:
        try:
            from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
            reg = er.async_get(hass)
            for ent in list(reg.entities.values()):
                if getattr(ent, "area_id", None) == area_id and not getattr(ent, "disabled", False):
                    add(ent.entity_id)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("room_entity_set: registry read failed", exc_info=True)
    return out


# ---------------------------------------------------------------------------
# Validation (D1, D2)
# ---------------------------------------------------------------------------


def _entity_ids(target: Any) -> list:
    if not isinstance(target, dict):
        return []
    eid = target.get("entity_id")
    if isinstance(eid, str):
        return [eid]
    if isinstance(eid, list):
        return list(eid)
    return []


def validate_actions(hass: Any, actions: Any, room_entity_ids: Iterable[str]) -> list[str]:
    """Strict per-action checks; returns error strings (empty = valid).

    Rejects: an empty list, a non-object action, a domain outside the
    allowlist (climate included), ``toggle`` on light/switch, a target
    missing or outside the room entity set (automation.* / scene.* may be
    any existing entity of that domain), an entity of another domain, a
    non-object ``data`` and any data key not listed for the domain in
    ``ROOM_RULE_DATA_KEYS`` (named, never silently dropped)."""
    errors: list[str] = []
    if not isinstance(actions, list) or not actions:
        return ["no actions"]
    allowed = set(room_entity_ids)
    for i, a in enumerate(actions, 1):
        label = f"Action {i}"
        if not isinstance(a, dict):
            errors.append(f"{label}: not an object")
            continue
        domain, service = a.get("domain"), a.get("service")
        if not isinstance(domain, str) or not domain or not isinstance(service, str) or not service:
            errors.append(f"{label}: missing domain or service")
            continue
        if domain not in ROOM_RULE_ALLOWED_DOMAINS:
            errors.append(f"{label}: domain '{domain}' is not allowed")
            continue
        if service == "toggle" and domain in _TOGGLE_REJECTED_DOMAINS:
            errors.append(f"{label}: {domain}.toggle is not allowed (use turn_on or turn_off)")
            continue
        ids = _entity_ids(a.get("target"))
        if not ids:
            errors.append(f"{label}: no target entity")
        for eid in ids:
            if not isinstance(eid, str) or "." not in eid:
                errors.append(f"{label}: bad entity '{eid}'")
                continue
            if eid.split(".")[0] != domain:
                errors.append(f"{label}: entity '{eid}' is not a {domain}")
                continue
            if domain in _ANY_ENTITY_DOMAINS:
                if hass.states.get(eid) is None:
                    errors.append(f"{label}: entity '{eid}' not found")
            elif eid not in allowed:
                errors.append(f"{label}: entity '{eid}' is not in this room")
        data = a.get("data", {})
        if data is None:
            data = {}
        if not isinstance(data, dict):
            errors.append(f"{label}: data must be an object")
            continue
        keys = ROOM_RULE_DATA_KEYS.get(domain, frozenset())
        for k in data:
            if k not in keys:
                errors.append(f"{label}: data key '{k}' is not allowed for {domain}")
    return errors


def _parse_hhmm(value: Any) -> dtime | None:
    if not isinstance(value, str):
        return None
    try:
        hh, mm = value.strip().split(":")[:2]
        return dtime(int(hh), int(mm))
    except Exception:  # noqa: BLE001
        return None


def validate_conditions(conditions: Any) -> list[str]:
    errors: list[str] = []
    if conditions is None:
        return errors
    if not isinstance(conditions, list):
        return ["conditions must be a list"]
    for i, c in enumerate(conditions, 1):
        label = f"Condition {i}"
        if not isinstance(c, dict):
            errors.append(f"{label}: not an object")
            continue
        kind = c.get("type")
        if kind not in ROOM_RULE_CONDITION_TYPES:
            errors.append(f"{label}: unknown condition '{kind}'")
            continue
        if kind == "time_window":
            s, e = _parse_hhmm(c.get("start")), _parse_hhmm(c.get("end"))
            if s is None or e is None:
                errors.append(f"{label}: time_window needs start and end as HH:MM")
            elif s == e:
                errors.append(f"{label}: time_window start equals end")
        elif kind == "house_state_in":
            states = c.get("states")
            if not isinstance(states, list) or not states:
                errors.append(f"{label}: house_state_in needs a states list")
            else:
                bad = [s for s in states if s not in HOUSE_STATE_TRIGGER_VALUES]
                if bad:
                    errors.append(f"{label}: unknown house state {bad}")
    return errors


# ---------------------------------------------------------------------------
# Conditions at run time (D2)
# ---------------------------------------------------------------------------


def in_time_window(start: dtime, end: dtime, now: dtime) -> bool:
    """Local window; crosses midnight when ``start > end``."""
    if start < end:
        return start <= now < end
    return now >= start or now < end


def evaluate_conditions(
    conditions: Iterable[Mapping[str, Any]],
    *,
    dark_fn: Callable[[], bool],
    now_local: datetime,
    house_state: str | None,
) -> tuple[bool, dict, str | None]:
    """``(all_true, values, first_failed_kind)``. ``values`` holds what each
    condition read (for the decision log)."""
    values: dict = {}
    failed: str | None = None
    for c in conditions or []:
        kind = c.get("type")
        ok = False
        if kind == "after_dark":
            try:
                ok = bool(dark_fn())
            except Exception:  # noqa: BLE001
                ok = False
            values["after_dark"] = ok
        elif kind == "time_window":
            s, e = _parse_hhmm(c.get("start")), _parse_hhmm(c.get("end"))
            ok = bool(s and e and s != e and in_time_window(s, e, now_local.time()))
            values["time_window"] = f"{c.get('start')}-{c.get('end')}@{now_local.strftime('%H:%M')}={ok}"
        elif kind == "house_state_in":
            states = c.get("states") or []
            ok = house_state in states
            values["house_state"] = house_state
        else:
            values[str(kind)] = "unknown"
        if not ok and failed is None:
            failed = str(kind)
    return failed is None, values, failed


# ---------------------------------------------------------------------------
# Compile (D1, D3)
# ---------------------------------------------------------------------------


@dataclass
class CompileResult:
    kind: str
    actions: list = field(default_factory=list)
    conditions: list = field(default_factory=list)
    unsupported: str = ""
    summary: str = ""
    errors: list = field(default_factory=list)
    model_entity: str = ""

    @property
    def ok(self) -> bool:
        return self.kind == KIND_OK


def trigger_phrase_for_prompt(trigger_type: str, person: str) -> str:
    who = person_display(None, person) if person else "someone"
    if trigger_type == TRIGGER_ENTER:
        return f"{who} enters the room"
    if trigger_type == TRIGGER_EXIT:
        return f"{who} leaves the room"
    if trigger_type == TRIGGER_LUX_DARK:
        return "the room gets dark"
    if trigger_type == TRIGGER_LUX_BRIGHT:
        return "the room gets bright"
    if trigger_type.startswith(TRIGGER_HOUSE_STATE_PREFIX):
        st = trigger_type[len(TRIGGER_HOUSE_STATE_PREFIX):]
        return f"the house switches to {_HOUSE_STATE_LABELS.get(st, st)}"
    if trigger_type == TRIGGER_ENERGY_CONSTRAINT:
        return "the energy mode changes (peak, shed, coast)"
    if trigger_type == TRIGGER_SAFETY_HAZARD:
        return "a safety hazard is detected (smoke, CO, water leak)"
    if trigger_type == TRIGGER_SECURITY_EVENT:
        return "a security event happens"
    return trigger_type


def extract_fields(raw: Any) -> dict | None:
    """The structure container with the ``_extract_findings_list`` precedence:
    ``raw['data']`` when it is a dict (strict: no fallback to flat keys),
    else ``raw``."""
    if not isinstance(raw, dict):
        return None
    container = raw["data"] if isinstance(raw.get("data"), dict) else raw
    return container if isinstance(container, dict) else None


def _json_list(value: Any) -> list | None:
    """A JSON array given as a string (the TEXT structure) or already a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, list) else None
    if value is None:
        return []
    return None


def parse_and_validate(hass: Any, raw: Any, room_entity_ids: Iterable[str]) -> CompileResult:
    """Validate an AI Task response (no model call). ``parse_failed`` on any
    structural or validation error; ``unsupported`` when the model named
    something it could not express."""
    container = extract_fields(raw)
    if container is None:
        return CompileResult(KIND_PARSE_FAILED, errors=["empty response"])
    actions = _json_list(container.get("actions_json"))
    if actions is None:
        return CompileResult(KIND_PARSE_FAILED, errors=["actions_json is not a JSON array"])
    conditions = _json_list(container.get("conditions_json"))
    if conditions is None:
        return CompileResult(KIND_PARSE_FAILED, errors=["conditions_json is not a JSON array"])
    unsupported = str(container.get("unsupported") or "").strip()
    summary = str(container.get("summary") or "").strip()
    errors = validate_actions(hass, actions, room_entity_ids) + validate_conditions(conditions)
    if unsupported:
        return CompileResult(KIND_UNSUPPORTED, actions=actions, conditions=conditions,
                             unsupported=unsupported, summary=summary, errors=errors)
    if errors:
        return CompileResult(KIND_PARSE_FAILED, actions=actions, conditions=conditions,
                             summary=summary, errors=errors)
    return CompileResult(KIND_OK, actions=actions, conditions=conditions, summary=summary)


async def compile_rule(
    hass: Any,
    *,
    description: str,
    trigger_type: str,
    person: str,
    room_name: str,
    entities: list[dict],
    ai_task_entity: str,
    timeout_s: float | None = None,
) -> CompileResult:
    """One AI Task call (``ai_task.generate_data``) then strict validation.

    ``model_unavailable``: the configured entity is missing or unavailable,
    the ``ai_task`` service is not registered, the call raised (HA error,
    service not found, account locked) or timed out. ``parse_failed``: a
    response came back and did not validate. The call is wrapped in
    ``asyncio.timeout(RULE_PARSE_TIMEOUT_S)``."""
    entity = (ai_task_entity or "").strip()
    label = entity or "HA default AI Task"
    if entity:
        st = hass.states.get(entity)
        if st is None or getattr(st, "state", None) in ("unavailable",):
            return CompileResult(KIND_MODEL_UNAVAILABLE, model_entity=label,
                                 errors=[f"{label} is not available"])
    try:
        if not hass.services.has_service("ai_task", "generate_data"):
            return CompileResult(KIND_MODEL_UNAVAILABLE, model_entity=label,
                                 errors=["ai_task.generate_data is not registered"])
    except Exception:  # noqa: BLE001
        pass
    prompt = AI_RULE_PARSING_PROMPT.format(
        room_name=room_name,
        trigger_label=trigger_phrase_for_prompt(trigger_type, person),
        description=description,
        entities_json=json.dumps(entities, indent=2),
    )
    payload: dict = {
        "task_name": TASK_NAME,
        "instructions": prompt,
        "structure": ROOM_RULE_STRUCTURE,
    }
    if entity:
        payload["entity_id"] = entity
    limit = RULE_PARSE_TIMEOUT_S if timeout_s is None else timeout_s
    try:
        async with asyncio.timeout(limit):
            raw = await hass.services.async_call(
                "ai_task", "generate_data", payload,
                blocking=True, return_response=True,
            )
    except (asyncio.TimeoutError, TimeoutError):
        _LOGGER.warning("Room rule: %s timed out after %ss", label, limit)
        return CompileResult(KIND_MODEL_UNAVAILABLE, model_entity=label,
                             errors=[f"{label} timed out"])
    except Exception as err:  # noqa: BLE001 - HomeAssistantError, ServiceNotFound, ...
        _LOGGER.warning("Room rule: %s failed: %s", label, err)
        return CompileResult(KIND_MODEL_UNAVAILABLE, model_entity=label,
                             errors=[f"{label}: {err}"])
    ids = [e.get("entity_id") for e in entities if isinstance(e, dict)]
    result = parse_and_validate(hass, raw, ids)
    result.model_entity = label
    if not result.ok:
        _LOGGER.info("Room rule compile %s: %s", result.kind, result.errors or result.unsupported)
    return result


# ---------------------------------------------------------------------------
# Preview (D3, INV-R4): written by code from the stored record only
# ---------------------------------------------------------------------------


def person_display(hass: Any, person: Any) -> str:
    """Friendly name of a ``person.*`` entity, else the display form of its slug."""
    p = str(person or "").strip()
    if not p:
        return ""
    if hass is not None and p.startswith("person."):
        try:
            st = hass.states.get(p)
            if st is not None:
                name = (getattr(st, "attributes", {}) or {}).get("friendly_name")
                if name:
                    return str(name)
        except Exception:  # noqa: BLE001
            pass
    return display_of(slug_of(p)) if "." in p or "_" in p else p


def _name(hass: Any, eid: str) -> str:
    try:
        st = hass.states.get(eid) if hass is not None else None
        if st is not None:
            name = (getattr(st, "attributes", {}) or {}).get("friendly_name")
            if name:
                return str(name)
    except Exception:  # noqa: BLE001
        pass
    return eid


def _pct(v: Any) -> str:
    try:
        f = float(v)
        return f"{int(f) if f.is_integer() else f} percent"
    except (TypeError, ValueError):
        return f"{v} percent"


def _data_words(domain: str, data: Mapping[str, Any]) -> list[str]:
    words: list[str] = []
    for k, v in (data or {}).items():
        if k == "brightness_pct":
            words.append(f"at {_pct(v)}")
        elif k == "color_temp_kelvin":
            words.append(f"at {v} K")
        elif k == "rgb_color":
            words.append(f"in colour {v}")
        elif k == "color_name":
            words.append(f"in {v}")
        elif k == "transition":
            words.append(f"over {v} s")
        elif k == "percentage":
            words.append(f"at {_pct(v)}")
        elif k == "preset_mode":
            words.append(f"on preset {v}")
        elif k == "oscillating":
            words.append("oscillating" if v else "not oscillating")
        elif k == "direction":
            words.append(f"turning {v}")
        elif k == "volume_level":
            try:
                words.append(f"at volume {_pct(round(float(v) * 100))}")
            except (TypeError, ValueError):
                words.append(f"at volume {v}")
        elif k == "media_content_id":
            words.append(f"playing {v}")
        elif k == "media_content_type":
            continue
        elif k == "source":
            words.append(f"from {v}")
        elif k in ("position", "tilt_position"):
            words.append(("tilted to " if k == "tilt_position" else "to ") + _pct(v))
        elif k in ("value", "option"):
            words.append(f"to {v}")
        elif k == "skip_condition":
            words.append("ignoring its own conditions" if v else "if its own conditions pass")
        else:
            words.append(f"{k} {v}")
    return words


_VERBS = {
    "turn_on": "turn on", "turn_off": "turn off", "open_cover": "open",
    "close_cover": "close", "stop_cover": "stop", "set_cover_position": "move",
    "lock": "lock", "unlock": "unlock", "media_play": "play",
    "media_pause": "pause", "media_stop": "stop", "volume_set": "set",
    "play_media": "play on", "select_source": "switch", "set_percentage": "set",
    "set_preset_mode": "set", "press": "press", "set_value": "set",
    "select_option": "set", "trigger": "run",
}


def _action_words(hass: Any, action: Mapping[str, Any]) -> str:
    domain = str(action.get("domain") or "")
    service = str(action.get("service") or "")
    names = [_name(hass, e) for e in _entity_ids(action.get("target"))]
    who = " and ".join(names) if names else "nothing"
    if domain == "automation" and service == "trigger":
        head = f"run automation {who}"
    elif domain == "scene" and service == "turn_on":
        head = f"turn on scene {who}"
    else:
        verb = _VERBS.get(service, f"{domain}.{service}")
        head = f"{verb} {who}"
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    words = _data_words(domain, data)
    return " ".join([head] + words)


def _condition_words(c: Mapping[str, Any]) -> str:
    kind = c.get("type")
    if kind == "after_dark":
        return "after dark"
    if kind == "time_window":
        return f"between {c.get('start')} and {c.get('end')}"
    if kind == "house_state_in":
        labels = [_HOUSE_STATE_LABELS.get(s, str(s)) for s in c.get("states") or []]
        return "while the house is " + " or ".join(labels)
    return str(kind)


def _trigger_words(trigger: str, who: str, room: str) -> str:
    if trigger == TRIGGER_ENTER:
        return f"When {who or 'someone'} enters {room}"
    if trigger == TRIGGER_EXIT:
        return f"When {who or 'someone'} leaves {room}"
    if trigger == TRIGGER_LUX_DARK:
        return f"When {room} gets dark"
    if trigger == TRIGGER_LUX_BRIGHT:
        return f"When {room} gets bright"
    if trigger.startswith(TRIGGER_HOUSE_STATE_PREFIX):
        st = trigger[len(TRIGGER_HOUSE_STATE_PREFIX):]
        return f"When the house switches to {_HOUSE_STATE_LABELS.get(st, st)}"
    if trigger == TRIGGER_ENERGY_CONSTRAINT:
        return "When the energy mode changes"
    if trigger == TRIGGER_SAFETY_HAZARD:
        return "When a safety hazard is detected"
    if trigger == TRIGGER_SECURITY_EVENT:
        return "When a security event happens"
    return f"When {trigger}"


def render_rule_preview(rule: Mapping[str, Any], hass: Any, room_name: str = "this room") -> str:
    """Plain-words preview from the stored trigger, person, conditions and
    actions (INV-R4). The LLM ``summary`` / ``description`` are never read.

    e.g. "When Oji enters Exercise Room, after dark: turn on Exercise Lamp
    at 40 percent."
    """
    trigger = str(rule.get("trigger_type") or "")
    who = person_display(hass, rule.get("person"))
    head = _trigger_words(trigger, who, room_name)
    if who and trigger not in (TRIGGER_ENTER, TRIGGER_EXIT):
        head += f", while {who} is in {room_name}"
    conds = [_condition_words(c) for c in rule.get("conditions") or [] if isinstance(c, dict)]
    if conds:
        head += ", " + ", ".join(conds)
    acts = [_action_words(hass, a) for a in rule.get("actions") or [] if isinstance(a, dict)]
    body = "; ".join(acts) if acts else "nothing (needs a re-check)"
    return f"{head}: {body}."
