import sqlite3,json
u=sqlite3.connect("file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro",uri=True)
for ts,d,desc in u.execute("select timestamp,details_json,description from ura_activity_log where action='reserve_write' order by id"):
    j=json.loads(d)
    print(ts[5:19],j.get('status'),j.get('path'),j.get('value'),'d',j.get('desire'),'pre',j.get('pre_state'),j.get('hold_owner'),(j.get('reason') or '')[:60])
print("--ANOM")
for r in u.execute("select timestamp,coordinator_id,metric_name,event_class,anomaly_type,severity,substr(context_json,1,160) from anomaly_log where timestamp>='2026-10-16' and (metric_name like '%write%' or metric_name like '%reserve%' or event_class like '%write%' or anomaly_type like '%write%' or anomaly_type like '%reserve%')"): print(r)
print("--NOTIF")
for r in u.execute("select timestamp,severity,substr(title,1,100) from notification_log where timestamp>='2026-10-16' and (title like '%not applied%' or title like '%reserve%' or message like '%reserve_soc%') order by timestamp"): print(r)
