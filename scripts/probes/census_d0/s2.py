import sqlite3,re,json,time
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
ids=[e for (e,) in r.execute("select entity_id from states_meta")]
print([e for e in ids if re.search(r'(oji|ezinne|jaya|ziri).*(room|location|area)',e) and not 'distance' in e][:40])
# Revel attrs: find attribute rows containing Revel
rows=r.execute("select count(*) from state_attributes where shared_attrs like '%\"essid\":\"Revel\"%'").fetchone();print('revel attr rows',rows)
ex=r.execute("select shared_attrs from state_attributes where shared_attrs like '%\"essid\":\"Revel\"%' limit 2").fetchall();print(ex)
