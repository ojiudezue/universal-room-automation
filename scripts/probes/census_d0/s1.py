import sqlite3,re
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
ids=[e for (e,) in r.execute("select entity_id from states_meta")]
for pat in [r'person_count',r'^person\.',r'guest_bedroom.*occup|guest.*bedroom.*occupied',r'census|guest_mode|house_state|wifi_guest',r'apollo.*target_count|upzone2']:
    print(pat,[e for e in ids if re.search(pat,e)][:80])
n=sum(1 for e in ids if e.startswith('device_tracker.'));print('trackers',n)
