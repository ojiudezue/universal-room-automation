import sqlite3,json
u=sqlite3.connect("file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",uri=True)
print(u.execute("select action,count(*) from ura_activity_log where coordinator='energy' and timestamp>='2026-10-16' group by 1 order by 2 desc").fetchall())
for r in u.execute("select timestamp,action,substr(description,1,140) from ura_activity_log where coordinator='energy' and timestamp>='2026-10-23T19:00' and timestamp<'2026-10-24T01:00' and action not in ('reserve_write') order by id limit 80"): print(r)
