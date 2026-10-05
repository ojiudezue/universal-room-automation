"""Discover entity ids for P-D1..3. READ-ONLY."""
import sqlite3
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
import datetime as dt
a=dt.datetime(2026,10,3,5,tzinfo=dt.timezone.utc).timestamp();b=a+86400
for pat in ['%person%','device_tracker.%','%bermuda%']:
    for (e,n) in r.execute("select m.entity_id,count(*) from states s join states_meta m using(metadata_id) where m.entity_id like ? and s.last_updated_ts between ? and ? group by 1 order by 1",(pat,a,b)):
        print(n,e)
