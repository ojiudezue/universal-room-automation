"""HVAC W3 G0 — hand-built fixture: zone -> climate -> Carrier system -> SPAN -> ODU/IDU/static/filter.

READ-ONLY. Reads /config/.storage JSON files (open for read) and the recorder DB (mode=ro).
Run: ssh ha "python3 -" < scripts/probes/hvac_w3_g0_fixture.py
"""
import json, re, sqlite3, time

REC = "file:/config/home-assistant_v2.db?mode=ro"
ce = json.load(open("/config/.storage/core.config_entries"))["data"]["entries"]
er = json.load(open("/config/.storage/core.entity_registry"))["data"]["entities"]
dr = json.load(open("/config/.storage/core.device_registry"))["data"]["devices"]
devname = {d["id"]: (d.get("name_by_user") or d.get("name")) for d in dr}
ent_dev = {e["entity_id"]: e.get("device_id") for e in er}
dev_ents = {}
for e in er:
    dev_ents.setdefault(e.get("device_id"), []).append(e["entity_id"])

print("== Zone Manager zones (URA config) ==")
zones = []
for e in ce:
    if e["domain"] != "universal_room_automation":
        continue
    d = {**e.get("data", {}), **e.get("options", {})}
    zdict = d.get("zones")
    if not isinstance(zdict, dict):
        continue
    for zname, zc in zdict.items():
        th = zc.get("zone_thermostat")
        if not th:
            continue
        m = re.search(r"(?:^|[_.\s])zone[_\s]?(\d+)", th)
        zid = f"zone_{m.group(1)}" if m else "?"
        zones.append((zid, zname, th, zc.get("hvac_ac_load_sensor", ""), zc.get("hvac_ac_ramp_zone_enabled")))
for z in sorted(zones):
    print(z)

print("\n== Per climate entity: device + Carrier-system entities ==")
rec = sqlite3.connect(REC, uri=True)
def last_state(eid):
    r = rec.execute(
        "SELECT s.state, s.last_updated_ts FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id "
        "WHERE m.entity_id=? ORDER BY s.last_updated_ts DESC LIMIT 1", (eid,)).fetchone()
    return r
for th in sorted({z[2] for z in zones}):
    dev = ent_dev.get(th)
    print(f"\n{th}  device={devname.get(dev)!r}")
    # The Carrier SYSTEM device is the parent (via_device) of the zone device; list its sensors
    ddev = next((d for d in dr if d["id"] == dev), None)
    sysdev = ddev.get("via_device_id") if ddev else None
    for label, did in (("zone-device", dev), ("system-device(via)", sysdev)):
        if not did:
            continue
        ents = sorted(x for x in dev_ents.get(did, []) if re.search(
            r"(odu|idu|static_pressure|filter|airflow|outdoor_temp|odu_var|updated_(websocket|all_data)_at)", x))
        print(f"  {label}: {devname.get(did)!r}")
        for x in ents:
            print("    ", x, last_state(x))
print("\n== Any *odu_var* in states_meta / entity registry? ==")
print("states_meta:", [r[0] for r in rec.execute("SELECT entity_id FROM states_meta WHERE entity_id LIKE '%odu_var%'")])
print("registry:", [e["entity_id"] for e in er if "odu_var" in e["entity_id"]])
print("\n== SPAN AC power entities (live) ==")
for x in ("sensor.span_panel_ac1_power", "sensor.span_panel_ac_2_power", "sensor.span_panel_ac_3_power"):
    print(x, last_state(x), "device=", devname.get(ent_dev.get(x)))
print("probe ran at", time.strftime("%Y-%m-%d %H:%M:%S %Z"))
