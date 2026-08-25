import sqlite3
c=sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro",uri=True)
def series(e):
    q="""SELECT s.last_updated_ts, s.state FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id
         WHERE m.entity_id=? AND s.state IN ('on','off') ORDER BY s.last_updated_ts"""
    return list(c.execute(q,(e,)))
P=series("binary_sensor.occupancy_lux_temp_humidity_hobeian_exercise_presence_2")
F=series("fan.fan_switch_3")
def transitions(S):
    out=[];prev=None
    for t,s in S:
        if s!=prev: out.append((t,s)); prev=s
    return out
PT,FT=transitions(P),transitions(F)
def nearest_after(t,TR,want):
    for tt,ss in TR:
        if tt>=t-1 and ss==want: return tt-t
    return None
def nearest_before(t,TR,want):
    best=None
    for tt,ss in TR:
        if tt<=t and ss==want: best=t-tt
        if tt>t: break
    return best
print("fan OFF->ON events: lag until presence turns ON")
for t,s in FT:
    if s=='on':
        d=nearest_after(t,PT,'on')
        print(f"   fan_on lag_to_presence_on = {d if d is None else round(d,1)}s")
print("\nfan ON->OFF events: lag until presence turns OFF (NEGATIVE-ish = presence already off)")
for t,s in FT:
    if s=='off':
        d=nearest_after(t,PT,'off'); b=nearest_before(t,PT,'off')
        print(f"   fan_off -> presence_off after {None if d is None else round(d,1)}s | presence had been off {None if b is None else round(b,1)}s before")
