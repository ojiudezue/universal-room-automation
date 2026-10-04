import sqlite3
u=sqlite3.connect('file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro',uri=True)
for t in ['person_entry_exit_events','census_snapshots']:
    print(t,u.execute(f"select sql from sqlite_master where name='{t}'").fetchone()[0])
    print(u.execute(f"select * from {t} order by rowid desc limit 3").fetchall())
    print(u.execute(f"select min(rowid),count(*) from {t}").fetchone())
r=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
print(r.execute("select min(last_updated_ts),max(last_updated_ts) from states").fetchone())
