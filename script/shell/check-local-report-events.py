"""Read-only local report queue/receipt checks. Never publishes or changes reports."""
import argparse,json,time,re
from pathlib import Path
from urllib.parse import urlparse
from dotenv import dotenv_values
import pymysql

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--wait-seconds',type=int,default=0,choices=range(0,46))
args=parser.parse_args();root=Path(__file__).resolve().parents[2];env=dotenv_values(root/'.env')
url=urlparse(env['DB_URL'].removeprefix('jdbc:'))
if url.hostname not in ('localhost','127.0.0.1') or url.port not in (None,3306) or url.path!='/doorhandledb':raise SystemExit('Only local doorhandledb allowed')
uuid=r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
with pymysql.connect(host=url.hostname,port=url.port or 3306,user=env['DB_USERNAME'],password=env['DB_PASSWORD'],database='doorhandledb',charset='utf8mb4',autocommit=True) as connection:
    def inspect():
        with connection.cursor() as cursor:
            cursor.execute('SELECT event_id,report_id,event_type,payload_json,delivery_status FROM detection_report_outbox')
            invalid=0;counts={};total=0
            for event_id,report_id,event_type,payload,status in cursor.fetchall():
                total+=1;counts[status]=counts.get(status,0)+1
                try:
                    event=json.loads(payload)
                    assert set(event)=={'eventId','reportId','actorUserId','status','version','schemaVersion'}
                    assert len(payload)<=4096 and re.fullmatch(uuid,event_id) and re.fullmatch('qr-'+uuid,report_id)
                    assert event['eventId']==event_id and event['reportId']==report_id and event_type==f"detection.report.{event['status'].lower()}.v1"
                    assert event['status'] in ('SUBMITTED','WITHDRAWN','APPROVED','REJECTED')
                    assert type(event['actorUserId']) is int and event['actorUserId']>0 and type(event['version']) is int and event['version']>=2 and event['schemaVersion']==1
                except Exception:invalid+=1
            cursor.execute('SELECT COUNT(*) FROM detection_report_event_receipt');receipts=cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM detection_report_event_state');projections=cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM detection_report_outbox e LEFT JOIN detection_report_event_receipt r ON r.event_id=e.event_id WHERE e.delivery_status='DELIVERED' AND r.event_id IS NULL")
            missing=cursor.fetchone()[0]
            return {'totalEvents':total,'statusCounts':counts,'invalidEvents':invalid,'receipts':receipts,'reportStates':projections,'deliveredWithoutReceipt':missing,'allDeliveredAndReceived':total==counts.get('DELIVERED',0) and receipts==total and invalid==0 and missing==0}
    deadline=time.monotonic()+args.wait_seconds
    while True:
        result=inspect()
        if not args.wait_seconds or result['allDeliveredAndReceived'] or time.monotonic()>=deadline:break
        time.sleep(.5)
print(json.dumps(result,ensure_ascii=False))
if args.wait_seconds:
    (root/'work/report-events-managed-delivery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if not result['allDeliveredAndReceived']:raise SystemExit(1)
elif result['invalidEvents']:raise SystemExit(1)
