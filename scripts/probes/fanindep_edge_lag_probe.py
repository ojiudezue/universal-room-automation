import sqlite3
c=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
def series(e):
    return list(c.execute("""SELECT s.last_updated_ts,s.state FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id
        WHERE m.entity_id=? AND s.state IN ('on','off') ORDER BY s.last_updated_ts""",(e,)))
def trans(S):
    out=[];prev=None
    for t,s in S:
        if s!=prev: out.append((t,s)); prev=s
    return out
PAIRS=[("Upstairs Guestroom","binary_sensor.occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2","fan.fan_switch_4"),
       ("Guest Bedroom 1","binary_sensor.occupancy_lux_temp_humidity_hobeian_downguestroom_presence_2","fan.guest_room_down_ceiling_fan"),
       ("Breakfast Nook","binary_sensor.occupancy_lux_temp_humidity_hobeian_breakfast_presence_2","fan.151732606487193_fan")]
for name,pres,fan in PAIRS:
    PT,FT=trans(series(pres)),trans(series(fan))
    print(f"\n### {name}  ({len(PT)} pres trans, {len(FT)} fan trans)")
    if not FT: print("   fan never toggled in window — untestable"); continue
    rise=[];fall=[]
    for t,s in FT:
        if s=='on':
            d=[tt-t for tt,ss in PT if ss=='on' and tt>=t-1]
            if d: rise.append(round(d[0],1))
        else:
            d=[tt-t for tt,ss in PT if ss=='off' and tt>=t-1]
            if d: fall.append(round(d[0],1))
    print(f"   fan_on  -> presence_on  lags: {sorted(rise)[:12]}")
    print(f"   fan_off -> presence_off lags: {sorted(fall)[:12]}")
    tight=[x for x in rise if x<10]
    print(f"   >>> rising lags under 10s: {len(tight)}/{len(rise)}  {'LATCH SIGNATURE' if len(tight)>=3 else 'no clear signature'}")
