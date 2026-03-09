#!/usr/bin/env python3
"""Generate URA Diagnostics V2 dashboard config (glassmorphism + compact room cards)."""
import json

# --- Styles ---
G = ("ha-card { background: rgba(var(--rgb-card-background-color), 0.4) !important; "
     "backdrop-filter: blur(12px) !important; "
     "border: 1px solid rgba(255,255,255,0.08) !important; "
     "border-radius: 16px !important; "
     "box-shadow: 0 4px 24px rgba(0,0,0,0.1) !important; }")
GM = {"card_mod": {"style": G}}

# --- Data ---
ROOMS = [
    ("Kitchen", "mdi:stove", "kitchen"),
    ("Kitchen Hallway", "mdi:door-sliding", "kitchen_hallway"),
    ("Breakfast Nook", "mdi:coffee-outline", "breakfast_nook"),
    ("Dining Room", "mdi:silverware-fork-knife", "dining_room"),
    ("Living Room", "mdi:sofa-outline", "living_room"),
    ("Receiving Room", "mdi:account-multiple", "receiving_room"),
    ("Master Bedroom", "mdi:bed-king-outline", "master_bedroom"),
    ("Study A", "mdi:desk", "study_a"),
    ("Study B", "mdi:desk-lamp", "study_b"),
    ("Study A Closet", "mdi:hanger", "study_a_closet"),
    ("Game Room", "mdi:gamepad-variant-outline", "game_room"),
    ("Guest Bedroom 1", "mdi:bed-outline", "guest_bedroom_1"),
    ("Guest Bedroom 2", "mdi:bed-double-outline", "guest_bedroom_2"),
    ("Guest Bed 2 Bath", "mdi:shower-head", "guest_bed_2_bath"),
    ("Down Guest Bath", "mdi:toilet", "down_guest_bath"),
    ("Ziri Bedroom", "mdi:bed-single-outline", "ziri_bedroom"),
    ("Patio", "mdi:deck", "patio"),
    ("Garage A", "mdi:garage-variant", "garage_a"),
    ("AV Closet", "mdi:audio-video", "av_closet"),
    ("Stair Closet", "mdi:stairs-box", "stair_closet"),
    ("Media Room Closet", "mdi:projector", "media_room_closet"),
    ("Laundry Closet", "mdi:washing-machine", "laundry_closet"),
    ("Exercise Room Closet", "mdi:dumbbell", "exercise_room_closet"),
]

PEOPLE = [
    ("Ezinne", "person.ezinne", "ezinne"),
    ("Oji", "person.oji_udezue", "oji_udezue"),
    ("Jaya", "person.jaya", "jaya"),
    ("Ziri", "person.ziri", "ziri"),
]

ZONES = [
    ("Back Hallway", "zone_back_hallway", "mdi:door-sliding-open"),
    ("Entertainment", "zone_entertainment", "mdi:television-play"),
    ("Master Suite", "zone_master_suite", "mdi:bed-king-outline"),
    ("Outside", "zone_outside", "mdi:tree"),
    ("Upstairs", "zone_upstairs", "mdi:stairs-up"),
]

PERIMETER_CAMS = [
    "camera.front_door_aerial_low_resolution_channel",
    "camera.front_side_ptz_low_resolution_channel",
    "camera.rear_ptz_low_resolution_channel",
    "camera.back_yard_low_resolution_channel",
    "camera.g5_bullet_low_resolution_channel",
    "camera.utilities_ptz_low_resolution_channel",
    "camera.pool_equipment_low_resolution_channel",
    "camera.hot_tub_low_resolution_channel",
]
ENTRY_CAMS = [
    "camera.madrone_g6_entry_low_resolution_channel",
    "camera.garage_doorbell_lite_low_resolution_channel",
    "camera.garage_a_low_resolution_channel",
    "camera.garage_b_low_resolution_channel",
]
INTERIOR_CAMS = [
    "camera.foyer_fisheye_low_resolution_channel",
    "camera.staircase_low_resolution_channel",
    "camera.stairs_top_low_resolution_channel",
    "camera.master_hallway_low_resolution_channel",
    "camera.playroom_low_resolution_channel",
    "camera.upstairs_hall_low_resolution_channel",
    "camera.family_room_high_resolution_channel",
    "camera.g3_instant_study_a_low_resolution_channel",
]


# --- Helpers ---
def me(entity, name, icon=None, extra=None):
    """Mushroom entity card with glass style."""
    c = {"type": "custom:mushroom-entity-card", "entity": entity, "name": name, **GM}
    if icon:
        c["icon"] = icon
    if extra:
        c.update(extra)
    return c


def cam(entity):
    """Camera picture-glance card."""
    name = entity.split(".")[1].replace("_low_resolution_channel", "").replace("_high_resolution_channel", "").replace("_", " ").title()
    return {
        "type": "picture-glance",
        "camera_image": entity,
        "camera_view": "live",
        "title": name,
        "entities": [],
        "card_mod": {"style": G},
    }


def room_card(name, icon, slug):
    """Compact room button-card with occupancy state."""
    return {
        "type": "custom:button-card",
        "entity": f"binary_sensor.{slug}_occupied",
        "name": name,
        "icon": icon,
        "layout": "icon_name_state2nd",
        "show_state": False,
        "show_label": True,
        "label": "[[[ if (entity.state === 'on') return '\u25cf Occupied'; return '\u25cb Vacant'; ]]]",
        "custom_fields": {
            "people": (
                f"[[[ var p = states['sensor.{slug}_identified_people']; "
                f"if (p && p.state && p.state !== 'unknown' && p.state !== 'unavailable' && p.state !== '') "
                f"return '<ha-icon icon=\"mdi:account\" style=\"--mdc-icon-size:12px;\"></ha-icon> ' + p.state; "
                f"return ''; ]]]"
            ),
            "health": (
                f"[[[ var h = states['sensor.{slug}_automation_health']; "
                f"if (!h) return ''; "
                f"if (h.state === 'normal') return '<span style=\"color:#22c55e\">\u25cf</span>'; "
                f"if (h.state === 'degraded') return '<span style=\"color:#f97316\">\u25cf</span>'; "
                f"if (h.state === 'stale') return '<span style=\"color:#ef4444\">\u25cf</span>'; "
                f"return '<span style=\"color:#6b7280\">\u25cf</span>'; ]]]"
            ),
        },
        "state": [
            {
                "value": "on",
                "styles": {
                    "icon": [{"color": "#22c55e"}],
                    "card": [{"border-left": "3px solid #22c55e"}],
                    "label": [{"color": "#22c55e"}],
                },
            },
            {
                "value": "off",
                "styles": {
                    "icon": [{"color": "var(--disabled-color)"}],
                    "label": [{"color": "var(--secondary-text-color)"}],
                },
            },
        ],
        "styles": {
            "card": [
                {"background": "rgba(var(--rgb-card-background-color), 0.4)"},
                {"backdrop-filter": "blur(12px)"},
                {"border": "1px solid rgba(255,255,255,0.08)"},
                {"border-radius": "16px"},
                {"padding": "12px"},
                {"box-shadow": "0 4px 24px rgba(0,0,0,0.1)"},
                {"overflow": "hidden"},
                {"position": "relative"},
            ],
            "icon": [{"width": "36px"}, {"height": "36px"}],
            "name": [
                {"font-size": "14px"},
                {"font-weight": "600"},
                {"white-space": "nowrap"},
                {"overflow": "hidden"},
                {"text-overflow": "ellipsis"},
            ],
            "label": [{"font-size": "11px"}, {"font-weight": "500"}, {"margin-top": "2px"}],
            "custom_fields": {
                "people": [
                    {"font-size": "10px"},
                    {"opacity": "0.7"},
                    {"position": "absolute"},
                    {"bottom": "8px"},
                    {"right": "12px"},
                ],
                "health": [
                    {"font-size": "8px"},
                    {"position": "absolute"},
                    {"top": "8px"},
                    {"right": "12px"},
                ],
            },
        },
        "grid_options": {"columns": 1, "rows": 2},
    }


def zone_card(label, slug, icon):
    """Compact zone status card."""
    return {
        "type": "custom:button-card",
        "entity": f"sensor.{slug}_presence_status",
        "name": label,
        "icon": icon,
        "layout": "icon_name_state2nd",
        "show_state": True,
        "show_label": True,
        "label": f"[[[ var r = states['sensor.{slug}_rooms_occupied']; if (r) return r.state + ' rooms'; return ''; ]]]",
        "styles": {
            "card": [
                {"background": "rgba(var(--rgb-card-background-color), 0.4)"},
                {"backdrop-filter": "blur(12px)"},
                {"border": "1px solid rgba(255,255,255,0.08)"},
                {"border-radius": "16px"},
                {"padding": "12px"},
                {"box-shadow": "0 4px 24px rgba(0,0,0,0.1)"},
            ],
            "icon": [{"width": "32px"}, {"height": "32px"}],
            "name": [{"font-size": "13px"}, {"font-weight": "600"}],
            "state": [{"font-size": "11px"}, {"opacity": "0.8"}],
            "label": [{"font-size": "10px"}, {"opacity": "0.6"}],
        },
        "state": [
            {"value": "occupied", "styles": {"icon": [{"color": "#22c55e"}]}},
            {"value": "away", "styles": {"icon": [{"color": "var(--disabled-color)"}]}},
        ],
        "grid_options": {"columns": 1, "rows": 2},
    }


# --- Build Views ---

# =========== VIEW 0: HOME ===========
home_view = {
    "title": "Home",
    "icon": "mdi:home",
    "type": "sections",
    "max_columns": 4,
    "sections": [
        # Hero
        {
            "title": "",
            "type": "grid",
            "cards": [
                {
                    "type": "custom:mushroom-template-card",
                    "primary": "{{ states('sensor.universal_room_automation_house_state') | replace('_', ' ') | title }}",
                    "secondary": "{{ states('sensor.universal_room_automation_rooms_occupied') }} rooms occupied \u2022 {{ states('sensor.universal_room_automation_occupant_count') }} people home",
                    "icon": "mdi:home-analytics",
                    "icon_color": "blue",
                    "card_mod": {"style": (
                        "ha-card { background: linear-gradient(135deg, "
                        "rgba(59,130,246,0.25), rgba(147,51,234,0.20)) !important; "
                        "backdrop-filter: blur(16px) !important; "
                        "border: 1px solid rgba(255,255,255,0.12) !important; "
                        "border-radius: 20px !important; "
                        "box-shadow: 0 8px 32px rgba(0,0,0,0.15) !important; }"
                    )},
                    "grid_options": {"columns": 4, "rows": 2},
                },
                {
                    "type": "custom:mushroom-chips-card",
                    "chips": [
                        {"type": "entity", "entity": "sensor.universal_room_automation_person_tracking_status", "icon": "mdi:account-group"},
                        {"type": "entity", "entity": "sensor.universal_room_automation_census_confidence", "icon": "mdi:gauge"},
                        {"type": "entity", "entity": "sensor.ura_coordinator_manager_coordinator_summary", "icon": "mdi:check-circle"},
                        {"type": "entity", "entity": "sensor.universal_room_automation_music_following_health", "icon": "mdi:music-note"},
                    ],
                    "card_mod": {"style": G},
                    "grid_options": {"columns": 4, "rows": 1},
                },
            ],
        },
        # People
        {
            "title": "People",
            "type": "grid",
            "cards": [
                {
                    "type": "custom:mushroom-person-card",
                    "entity": pid,
                    "card_mod": {"style": G},
                    "grid_options": {"columns": 1, "rows": 2},
                }
                for _, pid, _ in PEOPLE
            ] + [
                me(f"sensor.universal_room_automation_{slug}_location", f"{name}", "mdi:map-marker",
                   {"grid_options": {"columns": 1, "rows": 1}})
                for name, _, slug in PEOPLE
            ],
        },
        # Zones
        {
            "title": "Zones",
            "type": "grid",
            "cards": [zone_card(label, slug, icon) for label, slug, icon in ZONES],
        },
        # Camera Peek
        {
            "title": "Cameras",
            "type": "grid",
            "cards": [
                {
                    "type": "grid",
                    "columns": 2,
                    "cards": [
                        cam("camera.front_door_aerial_low_resolution_channel"),
                        cam("camera.madrone_g6_entry_low_resolution_channel"),
                        cam("camera.foyer_fisheye_low_resolution_channel"),
                        cam("camera.staircase_low_resolution_channel"),
                    ],
                    "grid_options": {"columns": 4, "rows": 6},
                },
            ],
        },
    ],
}

# =========== VIEW 1: ROOMS ===========
rooms_view = {
    "title": "Rooms",
    "icon": "mdi:floor-plan",
    "type": "sections",
    "max_columns": 4,
    "sections": [
        {
            "title": "All Rooms",
            "type": "grid",
            "cards": [room_card(n, i, s) for n, i, s in ROOMS],
        },
    ],
}

# =========== VIEW 2: CAMERAS & SECURITY ===========
security_view = {
    "title": "Security",
    "icon": "mdi:cctv",
    "type": "sections",
    "max_columns": 4,
    "sections": [
        {
            "title": "Security Status",
            "type": "grid",
            "cards": [
                me("sensor.ura_security_coordinator_security_armed_state", "Armed State", "mdi:shield-lock",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_security_coordinator_security_last_entry", "Last Entry", "mdi:door-open",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("binary_sensor.ura_security_coordinator_security_alert", "Alert", "mdi:alert-circle",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_security_coordinator_security_compliance", "Compliance", "mdi:check-decagram",
                   {"grid_options": {"columns": 1, "rows": 1}}),
            ],
        },
        {
            "title": "Perimeter",
            "type": "grid",
            "cards": [
                {"type": "grid", "columns": 4, "cards": [cam(c) for c in PERIMETER_CAMS],
                 "grid_options": {"columns": 4, "rows": 6}},
            ],
        },
        {
            "title": "Entry & Doors",
            "type": "grid",
            "cards": [
                {"type": "grid", "columns": 4, "cards": [cam(c) for c in ENTRY_CAMS],
                 "grid_options": {"columns": 4, "rows": 3}},
            ],
        },
        {
            "title": "Interior",
            "type": "grid",
            "cards": [
                {"type": "grid", "columns": 4, "cards": [cam(c) for c in INTERIOR_CAMS],
                 "grid_options": {"columns": 4, "rows": 6}},
            ],
        },
    ],
}

# =========== VIEW 3: SYSTEM ===========
system_view = {
    "title": "System",
    "icon": "mdi:cog",
    "type": "sections",
    "max_columns": 4,
    "sections": [
        # Coordinator Toggles
        {
            "title": "Coordinator Controls",
            "type": "grid",
            "cards": [
                me("switch.universal_room_automation_domain_coordinators_enabled", "Master", "mdi:power",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("switch.ura_presence_coordinator_enabled", "Presence", "mdi:home-account",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("switch.ura_safety_coordinator_enabled", "Safety", "mdi:shield-check",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("switch.ura_security_coordinator_enabled", "Security", "mdi:shield-lock",
                   {"grid_options": {"columns": 1, "rows": 1}}),
            ],
        },
        # Coordinator Status
        {
            "title": "Coordinator Status",
            "type": "grid",
            "cards": [
                me("sensor.ura_coordinator_manager_coordinator_manager", "Manager", "mdi:server",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_coordinator_manager_house_state", "House State", "mdi:home-thermometer",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_coordinator_manager_coordinator_summary", "Summary", "mdi:clipboard-check",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.universal_room_automation_music_following_health", "Music", "mdi:music-note-plus",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                # Presence
                me("sensor.ura_presence_coordinator_presence_house_state", "Presence State", "mdi:home-search",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_presence_coordinator_house_state_confidence", "Confidence", "mdi:gauge",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_presence_coordinator_presence_anomaly", "Anomaly", "mdi:alert-outline",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_presence_coordinator_presence_compliance", "Compliance", "mdi:check-decagram",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                # Safety
                me("sensor.ura_safety_coordinator_safety_status", "Safety Status", "mdi:shield-check",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_safety_coordinator_safety_active_hazards", "Hazards", "mdi:alert",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_safety_coordinator_safety_diagnostics", "Diagnostics", "mdi:stethoscope",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.ura_safety_coordinator_safety_compliance", "Compliance", "mdi:check-decagram",
                   {"grid_options": {"columns": 1, "rows": 1}}),
            ],
        },
        # Automation Health - all rooms
        {
            "title": "Automation Health",
            "type": "grid",
            "cards": [
                {
                    "type": "custom:button-card",
                    "entity": f"sensor.{slug}_automation_health",
                    "name": name,
                    "show_state": True,
                    "show_label": False,
                    "styles": {
                        "card": [
                            {"background": "rgba(var(--rgb-card-background-color), 0.4)"},
                            {"backdrop-filter": "blur(12px)"},
                            {"border": "1px solid rgba(255,255,255,0.08)"},
                            {"border-radius": "12px"},
                            {"padding": "8px"},
                        ],
                        "name": [{"font-size": "11px"}, {"font-weight": "500"}],
                        "state": [{"font-size": "10px"}, {"opacity": "0.7"}],
                        "icon": [{"width": "24px"}, {"height": "24px"}],
                    },
                    "state": [
                        {"value": "normal", "icon": "mdi:heart-pulse", "styles": {"icon": [{"color": "#22c55e"}]}},
                        {"value": "degraded", "icon": "mdi:heart-half-full", "styles": {"icon": [{"color": "#f97316"}]}},
                        {"value": "stale", "icon": "mdi:heart-off", "styles": {"icon": [{"color": "#ef4444"}]}},
                        {"value": "debouncing", "icon": "mdi:timer-sand", "styles": {"icon": [{"color": "#3b82f6"}]}},
                    ],
                    "grid_options": {"columns": 1, "rows": 1},
                }
                for name, _, slug in ROOMS
            ],
        },
        # System Sensors
        {
            "title": "System Sensors",
            "type": "grid",
            "cards": [
                me("sensor.universal_room_automation_climate_delta", "Climate Delta", "mdi:thermometer-lines",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.universal_room_automation_hvac_direction", "HVAC Direction", "mdi:hvac",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.universal_room_automation_rooms_energy_total", "Total Energy", "mdi:lightning-bolt",
                   {"grid_options": {"columns": 1, "rows": 1}}),
                me("sensor.universal_room_automation_humidity_delta", "Humidity Delta", "mdi:water-percent",
                   {"grid_options": {"columns": 1, "rows": 1}}),
            ],
        },
        # Config Status - all rooms
        {
            "title": "Configuration Status",
            "type": "grid",
            "cards": [
                me(f"sensor.{slug}_configuration_status", name, "mdi:cog-outline",
                   {"grid_options": {"columns": 1, "rows": 1}})
                for name, _, slug in ROOMS
            ],
        },
    ],
}

# =========== FULL CONFIG ===========
config = {
    "views": [home_view, rooms_view, security_view, system_view],
}

with open("/tmp/ura_dashboard_v2.json", "w") as f:
    json.dump(config, f)

# Stats
total_cards = 0
for v in config["views"]:
    for s in v.get("sections", []):
        cards = s.get("cards", [])
        total_cards += len(cards)
        for c in cards:
            if c.get("type") == "grid":
                total_cards += len(c.get("cards", []))

print(f"Views: {len(config['views'])}")
print(f"Total cards: ~{total_cards}")
print(f"JSON size: {len(json.dumps(config))} bytes")
print("Written to /tmp/ura_dashboard_v2.json")
