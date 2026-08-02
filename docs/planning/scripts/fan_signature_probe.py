#!/usr/bin/env python3
"""Fan-signature separability probe (read-only).

Run on the HA host:  ssh ha "python3 -" < fan_signature_probe.py

Reads the HA recorder DB and the URA DB (both mode=ro) and prints per-class
feature tables for:
  - binary mmWave edge cadence (Study A Zigbee unit — the phantom incident unit)
  - numeric LD2410 energy channels (Kitchen / Jaya / Ziri / Study B ESPHome
    units — the only units that expose energy channels)
  - fan on/off cross-checks and URA occupancy_events ground truth.

No writes anywhere. See AUDIT_fan_signature_separability_probe.md for the report.
"""
import sqlite3, json, math, statistics as st
from datetime import datetime, timezone

REC = "file:/config/home-assistant_v2.db?mode=ro"
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"

def T(s):  # "2026-08-01 13:05" UTC -> epoch
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%m-%d %H:%M:%S")

rec = sqlite3.connect(REC, uri=True); rc = rec.cursor()
ura = sqlite3.connect(URA, uri=True); uc = ura.cursor()

def hist(eid, t0, t1, seed=True):
    """[(ts,state)] within window, optionally seeded with last state before t0."""
    out = []
    if seed:
        rc.execute("""select s.last_updated_ts,s.state from states s
            join states_meta m on s.metadata_id=m.metadata_id
            where m.entity_id=? and s.last_updated_ts<? order by s.last_updated_ts desc limit 1""",(eid,t0))
        r = rc.fetchone()
        if r: out.append((t0, r[1]))
    rc.execute("""select s.last_updated_ts,s.state from states s
        join states_meta m on s.metadata_id=m.metadata_id
        where m.entity_id=? and s.last_updated_ts>=? and s.last_updated_ts<=?
        order by s.last_updated_ts""",(eid,t0,t1))
    out.extend(rc.fetchall())
    return out

# ---------- labeled windows (UTC) ----------
WIN = {
  "FANON_VACANT_A": (T("2026-08-01 13:06"), T("2026-08-01 17:07")),   # fan 100%, room empty
  "FANON_VACANT_B": (T("2026-07-31 00:32"), T("2026-07-31 20:41")),   # fan 100%, pre-phantom
  "FANOFF_VACANT_A":(T("2026-08-01 17:15"), T("2026-08-01 22:00")),
  "FANOFF_VACANT_B":(T("2026-07-30 01:00"), T("2026-07-30 23:59")),   # fan off all day, house away
  "OCCUPIED_0725":  (T("2026-07-25 16:00"), T("2026-07-26 04:00")),   # pre-departure; verify w/ ura events
}

ROOMS = {"studya":"01KAAHJG9BHAP2VDTEYWDWZTA7","studyb":"01KDRGWK4FCFEGSY3WG6N6DH5Q",
         "kitchen":"01KE9XFFQYHFGNB9F3GX3G6CGX","jaya":"01KJXMA4VRMZZ337N8YNKV7KJQ",
         "ziri":"01KJJN92CZ4KEM6WXB3168N8YW"}

print("="*78); print("GROUND TRUTH: ura occupancy_events per room per window")
for wn,(t0,t1) in WIN.items():
    for rn,rid in ROOMS.items():
        uc.execute("""select event_type,trigger_source,timestamp from occupancy_events
            where room_id=? and timestamp>=? and timestamp<=? order by timestamp""",(rid,t0,t1))
        rows = uc.fetchall()
        if rows:
            srcs = {}
            for e,s,_ in rows: srcs[f"{e}/{s}"] = srcs.get(f"{e}/{s}",0)+1
            print(f"  {wn:16s} {rn:8s} n={len(rows)} {srcs}")

# genuine-occupancy windows: motion-triggered entry/exit pairs anywhere in recorder span
print("\nMotion-triggered entry/exit pairs (candidate OCCUPIED windows), whole span:")
for rn,rid in ROOMS.items():
    uc.execute("""select event_type,trigger_source,timestamp,duration from occupancy_events
        where room_id=? and timestamp>=? order by timestamp""",(rid, T("2026-07-25 16:00")))
    ev = uc.fetchall()
    pairs=[]; cur=None
    for e,s,ts,dur in ev:
        if e=="occupancy_entry" and s=="motion": cur=ts
        elif e=="occupancy_exit" and cur: pairs.append((cur,ts)); cur=None
    long_pairs=[(a,b) for a,b in pairs if b-a>600]
    print(f"  {rn:8s} entries={len(pairs)} >10min={len(long_pairs)} " +
          " ".join(f"[{iso(a)}->{iso(b)}]" for a,b in long_pairs[:6]))

# ---------- binary edge cadence: Study A zigbee presence ----------
def edge_stats(eid, t0, t1):
    h = hist(eid,t0,t1)
    edges=[(ts,s) for ts,s in h if s in ("on","off")]
    if not edges: return None
    # collapse repeats
    seq=[edges[0]]
    for ts,s in edges[1:]:
        if s!=seq[-1][1]: seq.append((ts,s))
    on_t=0.0; ons=[]; offs=[]; onsets=[]
    for i,(ts,s) in enumerate(seq):
        nxt = seq[i+1][0] if i+1<len(seq) else t1
        if s=="on":
            on_t += nxt-ts
            ons.append(nxt-ts)
            if ts>t0: onsets.append(ts)
        else:
            offs.append(nxt-ts)
    ioi=[b-a for a,b in zip(onsets,onsets[1:])]
    def q(x):
        if not x: return "-"
        x=sorted(x); n=len(x)
        med=x[n//2]
        return f"med={med:.0f}s IQR=[{x[n//4]:.0f},{x[3*n//4]:.0f}] n={n}"
    cv = (st.pstdev(ioi)/st.mean(ioi)) if len(ioi)>1 and st.mean(ioi)>0 else None
    return dict(n_edges=len(seq)-1, duty=on_t/(t1-t0), on_dwell=q(ons), off_dwell=q(offs),
                inter_onset=q(ioi), ioi_cv=(f"{cv:.2f}" if cv is not None else "-"))

print("\n"+"="*78); print("BINARY EDGE CADENCE: binary_sensor.mmwave_zigbee_studya_presence")
for wn,(t0,t1) in WIN.items():
    s = edge_stats("binary_sensor.mmwave_zigbee_studya_presence",t0,t1)
    print(f"  {wn:16s} {s}")

# also check the room's PIR/motion sensor edges for the same windows (corroborating vacancy)
rc.execute("select entity_id from states_meta where entity_id like 'binary_sensor.%studya%'")
studya_bins=[r[0] for r in rc.fetchall()]
print("\n  studya binary sensors in recorder:", studya_bins)
for eid in studya_bins:
    if eid=="binary_sensor.mmwave_zigbee_studya_presence": continue
    line=[]
    for wn,(t0,t1) in WIN.items():
        h=[x for x in hist(eid,t0,t1,seed=False) if x[1] in ("on","off")]
        line.append(f"{wn}:{len(h)}")
    print(f"  edges {eid}: "+" ".join(line))

# ---------- numeric energy channels ----------
def num_stats(eid, t0, t1, label):
    h=[(ts,float(s)) for ts,s in hist(eid,t0,t1,seed=False)
       if s not in ("unavailable","unknown","")]
    if len(h)<10: return f"  {label:34s} {eid.split('.')[-1]:22s} n={len(h)} (insufficient)"
    ts=[a for a,_ in h]; v=[b for _,b in h]
    dts=sorted(b-a for a,b in zip(ts,ts[1:]))
    mdt=dts[len(dts)//2]
    mean=st.mean(v); sd=st.pstdev(v); cv=sd/mean if mean else float("inf")
    # resample to grid at max(mdt,1s) for autocorr
    grid=max(1.0,mdt); n=int((ts[-1]-ts[0])/grid)
    g=[]; j=0
    for i in range(min(n,20000)):
        t=ts[0]+i*grid
        while j+1<len(ts) and ts[j+1]<=t: j+=1
        g.append(v[j])
    def ac(lag):
        if lag>=len(g)-2: return None
        m=st.mean(g); var=sum((x-m)**2 for x in g)
        if var==0: return 0.0
        return sum((g[i]-m)*(g[i+lag]-m) for i in range(len(g)-lag))/var
    lags={f"lag{k}s": ac(max(1,int(k/grid))) for k in (int(grid),30,60,300)}
    lagstr=" ".join(f"{k}={x:.2f}" for k,x in lags.items() if x is not None)
    # coarse periodogram (DFT on irregular samples) up to Nyquist
    nyq=min(0.5, 1/(2*mdt)) if mdt>0 else 0.5
    peak=""
    if nyq>=0.05 and len(h)>100:
        m=st.mean(v); best=(0,0)
        f=0.05
        while f<=nyq:
            re=sum((x-m)*math.cos(2*math.pi*f*t) for t,x in h)
            im=sum((x-m)*math.sin(2*math.pi*f*t) for t,x in h)
            p=(re*re+im*im)/len(h)
            if p>best[1]: best=(f,p)
            f+=0.01
        peak=f" pgram_peak={best[0]:.2f}Hz(p={best[1]:.1f})"
    else:
        peak=f" pgram=N/A(Nyquist={nyq:.3f}Hz<0.05)"
    return (f"  {label:34s} {eid.split('.')[-1]:22s} n={len(h)} mdt={mdt:.1f}s "
            f"mean={mean:.1f} sd={sd:.1f} CV={cv:.2f} {lagstr}{peak}")

print("\n"+"="*78); print("NUMERIC ENERGY CHANNELS (units that have them; Study A has NONE)")
ENERGY_UNITS = {
 "studyb": ["sensor.mmwave_lux_wifi_esphome_studyb_move_energy","sensor.mmwave_lux_wifi_esphome_studyb_still_energy"],
 "kitchen":["sensor.mmwave_lux_wifi_esphome_kitchen_move_energy","sensor.mmwave_lux_wifi_esphome_kitchen_still_energy"],
 "jaya":   ["sensor.jaya_3_move_energy","sensor.jaya_3_still_energy"],
 "ziri":   ["sensor.ziri_3_move_energy","sensor.ziri_3_still_energy"],
}
# recorder cadence over last 24h
now=T("2026-08-01 23:00")
print("\nObserved recorder cadence (last 24h):")
for rn,eids in ENERGY_UNITS.items():
    for eid in eids:
        h=hist(eid,now-86400,now,seed=False)
        if len(h)>2:
            ts=[a for a,_ in h]; dts=sorted(b-a for a,b in zip(ts,ts[1:]))
            print(f"  {eid:52s} n24h={len(h)} med_dt={dts[len(dts)//2]:.1f}s p90_dt={dts[int(.9*len(dts))]:.1f}s")
        else:
            print(f"  {eid:52s} n24h={len(h)} (no data)")

# fan pairings for energy rooms: which fans ran during the away week?
print("\nFan activity 07-26..08-01 for energy-instrumented rooms:")
for feid in ["fan.fanswitch_treat_wifi_jayabedroom","fan.fan_temp_wifi_jayabedroom",
             "fan.fanswitch_treat_wifi_ziribedroom","fan.ceiling_fan_fan"]:
    h=hist(feid,T("2026-07-26 00:00"),T("2026-08-01 23:00"),seed=True)
    seq=[];
    for ts,s in h:
        if not seq or s!=seq[-1][1]: seq.append((ts,s))
    ons=[(ts,s) for ts,s in seq]
    print(f"  {feid}: {len(seq)-1} transitions; "+" ".join(f"{iso(t)}:{s}" for t,s in seq[:12]))

print("\nPer-class numeric stats:")
CLASSES = [
 ("VACANT_fanoff (07-30 full day)", T("2026-07-30 01:00"), T("2026-07-30 23:59")),
 ("VACANT_fanoff (08-01 17:15-22)", T("2026-08-01 17:15"), T("2026-08-01 22:00")),
 ("OCCUPIED (07-25 16-04Z)",        T("2026-07-25 16:00"), T("2026-07-26 04:00")),
]
for label,t0,t1 in CLASSES:
    for rn,eids in ENERGY_UNITS.items():
        for eid in eids:
            print(num_stats(eid,t0,t1,f"{label} [{rn}]"))

rec.close(); ura.close()
print("\nDONE")
