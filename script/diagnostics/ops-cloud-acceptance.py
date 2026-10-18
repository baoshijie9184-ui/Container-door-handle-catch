"""Read/lock verification after a real backup and isolated restore; never restore production or enable timers."""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
from datetime import datetime, timedelta, timezone

parser=argparse.ArgumentParser(description=__doc__)
for option in ['root','runtime','helper','snapshot','restore-report']:parser.add_argument('--'+option,required=True)
args=parser.parse_args()
if sys.platform!='linux':raise RuntimeError('Run against the existing Linux Docker host')
root=Path(args.root).resolve(strict=True);runtime=Path(args.runtime).resolve(strict=True);helper=Path(args.helper).resolve(strict=True)
if not helper.is_relative_to(root):raise RuntimeError('Use a project-owned checked helper')
ops=runpy.run_path(str(helper));ops['checked_root'](str(root))
snapshot=Path(args.snapshot).resolve(strict=True);report=Path(args.restore_report).resolve(strict=True)
if not snapshot.is_relative_to(root/'backups') or not report.is_relative_to(root/'state'):raise RuntimeError('Unexpected evidence directory')
checks=[]
def check(name,condition):
    if not condition:raise RuntimeError('Acceptance failed: '+name)
    checks.append(name)

manifest=ops['verify'](snapshot)
restored=json.loads(report.read_text(encoding='utf8'))
check('Completed backup and full archive hashes verify',True)
check('Snapshot and copied private files retain private permissions',snapshot.stat().st_mode&0o077==0 and all(p.stat().st_mode&0o077==0 for p in snapshot.iterdir() if p.is_file()))
check('Isolated restore verified all database tables and volume inventories',restored.get('passed') is True and restored.get('databaseTables')==len(manifest['tableCounts']) and
      {v['source'] for v in restored.get('volumes',[]) if v.get('verified')}==set(manifest['volumes']) and not restored.get('cleanupWarning'))
check('Restore report belongs to the selected snapshot',restored.get('snapshot')==snapshot.name)
suffix=report.stem.removeprefix('restore-drill-')
if not re.fullmatch('[a-f0-9]{12}',suffix):raise RuntimeError('Unexpected isolated resource identity')
check('Only this restore run has no remaining containers or volumes',not ops['docker']('ps','-aq','--filter','label=doorhandle.ops.run='+suffix).strip() and
      not ops['docker']('volume','ls','-q','--filter','label=doorhandle.ops.run='+suffix).strip())
record=json.loads((root/'state/maintenance.json').read_text(encoding='utf8'))
current=[r for r in ops['inventory']() if r['running']];by_id={r['id']:r for r in current}
check('Backup source services resumed with the same container and image identities',record.get('phase')=='RESUMED' and record.get('snapshot')==snapshot.name and
      all(r['id'] in by_id and by_id[r['id']]['image']==r['image'] and by_id[r['id']]['service']==r['service'] for r in record['containers']))
check('All snapshotted service images remain healthy and unchanged',len(current)==len(manifest['images']) and
      all(manifest['images'].get(r['service'])==r['image'] and ops['healthy'](r['id']) for r in current))

# Test real Linux flock/open-file-description behavior without stopping a service.
probe="""import fcntl,sys
with open(sys.argv[1],'a') as stream:
 try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:sys.exit(75)
sys.exit(0)
"""
def contender():return subprocess.run([sys.executable,'-c',probe,str(root/'state/deploy.lock')],capture_output=True,timeout=5).returncode
with (root/'state/deploy.lock').open('a') as parent:
    import fcntl
    fcntl.flock(parent.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    check('Independent Linux maintenance is rejected while parent owns the lock',contender()==75)
    with ops['maintenance_lock'](root,parent.fileno()):pass
    check('Closing inherited duplicate does not unlock the parent',contender()==75)
check('Linux maintenance lock releases after its true owner closes',contender()==0)

with ops['maintenance_lock'](root):
    health=ops['check'](root,runtime)
    check('Disk configuration and backup receipt operational check is healthy',health.get('healthy') is True)
mysql=next(r for r in current if r['service']=='mysql')
batch=ops['db'](mysql['id'],"SELECT status,total_images,successful_images,failed_images FROM detection_task WHERE task_id='det_20261015_031242_83f36157';").strip().split('\t')
check('Original 100 image result remains completed without new detection',batch==['COMPLETED','100','100','0'])
staging=root/'state/ops-units'
names=['doorhandle-backup.service','doorhandle-backup.timer','doorhandle-disk-check.service','doorhandle-disk-check.timer','doorhandle-maintenance-recover.service']
ops['run'](['systemd-analyze','verify',*[str(staging/name) for name in names]],timeout=30)
check('Real systemd verifies all five staged units',True)
check('Beijing backup time and no boot catch-up remain explicit','23:30:00 Asia/Shanghai' in (staging/'doorhandle-backup.timer').read_text() and
      'Persistent=false' in (staging/'doorhandle-backup.timer').read_text())
print(json.dumps({'at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'snapshot':snapshot.name,'databaseTables':len(manifest['tableCounts']),
                  'volumes':len(manifest['volumes']),'healthyProductionServices':len(current),'checks':checks,'passed':True,'productionRestoreExecuted':False,
                  'timerInstallationExecuted':False,'newApplicationDeploymentExecuted':False},ensure_ascii=False))
