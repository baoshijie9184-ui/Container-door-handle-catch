#!/usr/bin/env python3
"""Prepare and verify the fixed MCP runner transition. Invoke only under the deployment lock."""
import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


guard = module('mcp_runtime_guard', 'mcp-compat.py')
common = guard.common
require = common.require
PRIVATE = 'mcp-runtime-private.json'
OVERRIDE = 'mcp-runtime-activation.json'
PUBLIC = 'mcp-runtime-transition.json'
RECEIPTS = Path('/var/lib/doorhandle-mcp/executions.sqlite3')

# Never launch an SDK/server or open the original stopped database writable. Read a bounded copy,
# including WAL, without immutable=1 (which could hide committed WAL records).
PROBE = r'''import json,os,sqlite3,stat,tempfile,shutil
from pathlib import Path
from contextlib import closing
source=Path('/source/executions.sqlite3')
try:
 if any(path.is_symlink() for path in (source,*source.parents)):raise ValueError()
 if not source.exists():
  if any(source.parent.glob('executions.sqlite3*')):raise ValueError()
  print(json.dumps({'pool':None,'required':0,'pending':0,'imageOperations':0}));raise SystemExit(0)
 with tempfile.TemporaryDirectory(prefix='mcp-protocol-') as temporary:
  remaining=192*1024*1024
  for original in (source,source.with_name(source.name+'-wal')):
   if original.is_symlink():raise ValueError()
   if not original.exists():continue
   with os.fdopen(os.open(original,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
    before=os.fstat(stream.fileno())
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>remaining:raise ValueError()
    remaining-=before.st_size
    with (Path(temporary)/original.name).open('xb') as target:shutil.copyfileobj(stream,target,1024*1024)
    after=os.fstat(stream.fileno());current=original.stat()
    identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns)
    if identity(before)!=identity(after) or identity(before)!=identity(current):raise ValueError()
  with closing(sqlite3.connect((Path(temporary)/source.name).as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
   db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
   tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   if not {'metadata','execution','revocation','execution_event'}<=tables:raise ValueError()
   rows=db.execute("SELECT value FROM metadata WHERE key='pool_id'").fetchall()
   if len(rows)!=1:raise ValueError()
   pool=rows[0][0]
   pending=db.execute("SELECT COUNT(*) FROM execution WHERE status<>'REMOVED'").fetchone()[0]
   operations=db.execute('SELECT COUNT(*) FROM image_retirement').fetchone()[0] if 'image_retirement' in tables else 0
   if operations and 'image_retirement_event' not in tables:raise ValueError()
   policy=db.execute("SELECT value FROM metadata WHERE key='required_image_policy'").fetchall()
   if policy and (len(policy)!=1 or policy[0][0]!='4'):raise ValueError()
   print(json.dumps({'pool':pool,'required':2 if policy else 1 if operations else 0,'pending':pending,'imageOperations':operations}))
except Exception:
 raise SystemExit('MCP protocol storage cannot be verified')
'''


def image(reference):
    require(isinstance(reference, str) and common.DIGEST.fullmatch(reference), 'Runner images must already exist as immutable local IDs')
    values = json.loads(common.docker('image', 'inspect', reference))
    require(len(values) == 1 and values[0].get('Id') == reference, 'Runner image identity unavailable')
    labels = values[0].get('Config', {}).get('Labels') or {}
    require(labels.get('doorhandle.mcp.fetch') == 'true' and labels.get('doorhandle.mcp.version') == '2026.10.10'
            and labels.get('doorhandle.mcp.package-sha256') == 'd722c48bdc1de3e2a81727853bc490cf55c6c935e2038cdcad3c111b1d85db77', 'Runner is outside the reviewed fixed release')
    capability = labels.get('io.doorhandle.mcp-image-lifecycle', '0')
    require(capability in ('0', '1', '2'), 'Unknown runner journal protocol')
    return int(capability)


def volume(project, row):
    mounts = [value for value in row.get('Mounts', []) if value.get('Destination') == str(RECEIPTS.parent)]
    require(len(mounts) == 1 and mounts[0].get('Type') == 'volume' and mounts[0].get('RW') is True, 'Existing runner receipt volume is required')
    name = mounts[0].get('Name', '')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name), 'Runner volume identity invalid')
    values = json.loads(common.docker('volume', 'inspect', name)); require(len(values) == 1, 'Runner volume unavailable')
    labels = values[0].get('Labels') or {}
    require(labels.get('com.docker.compose.project') == project or labels.get('io.doorhandle.rehearsal') == project, 'Runner volume belongs to another deployment')
    binding = hashlib.sha256(json.dumps([project,name,values[0].get('CreatedAt'),values[0].get('Driver')], separators=(',', ':')).encode()).hexdigest()
    return name, binding


def inspect_id(cid, project, service):
    require(common.CID.fullmatch(cid or ''), 'Container identity invalid')
    values = json.loads(common.docker('inspect', cid)); require(len(values) == 1, 'Container disappeared during transition')
    value = values[0]; labels = value.get('Config', {}).get('Labels') or {}
    require(value.get('Id') == cid and labels.get('com.docker.compose.project') == project and labels.get('com.docker.compose.service') == service, 'Container no longer belongs to this transition')
    return value


def private_read(state, name):
    path = state/name; require(not path.is_symlink(), 'Runner transition file cannot be a link')
    value = path.stat(); require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and value.st_uid in (0,os.geteuid()) and not value.st_mode & 0o077 and value.st_size <= 8*1024*1024, 'Runner transition file is not private')
    return json.loads(path.read_text())


def write_record(state, record):
    record.setdefault('attempt',uuid.uuid4().hex)
    require(isinstance(record['attempt'],str) and re.fullmatch('[a-f0-9]{32}',record['attempt']) and type(record.get('revision',0)) is int and 0<=record.get('revision',0)<1000000,'Runner attempt metadata is invalid')
    record['revision']=record.get('revision',0)+1
    history=state/'mcp-runtime-history'
    require(not history.is_symlink(),'Runner history cannot be redirected');history.mkdir(mode=0o700,exist_ok=True)
    metadata=history.stat();require(metadata.st_uid in (0,os.geteuid()) and not metadata.st_mode & 0o077,'Runner history is not private')
    while (history/(record['attempt']+'-'+str(record['revision']).zfill(6)+'.json')).exists():record['revision']+=1
    require(len(list(history.iterdir()))<10000,'Runner transition history requires explicit archival')
    common.write_json(history/(record['attempt']+'-'+str(record['revision']).zfill(6)+'.json'),record)
    common.write_json(state/PRIVATE, record)
    public = {key: record.get(key) for key in ('schema','project','phase','action','requiredProtocol','selectedImage','previousImage','poolVerified','volumeBinding','pendingExecutions','imageOperations','checkedAt')}
    public.update(attempt=record['attempt'],revision=record['revision'],declarationOnly=record.get('phase') not in ('VERIFIED','FINALIZED'),retentionVerified=bool(record.get('retentionVerified')))
    common.write_json(state/PUBLIC, public)


def probe(row, name, probe_image):
    require(row.get('State', {}).get('Running') is False, 'Runner must be stopped before reading receipt storage')
    consumers=common.docker('ps','-aq','--filter','volume='+name,'--filter','status=running').decode().split()
    for cid in consumers:
        require(common.CID.fullmatch(cid),'Unexpected volume consumer')
        values=json.loads(common.docker('inspect',cid));require(len(values)==1,'Volume consumer disappeared')
        require(not any(value.get('Type')=='volume' and value.get('Name')==name and value.get('RW') for value in values[0].get('Mounts',[])),'Another live writer still mounts the runner journal')
    result = json.loads(common.docker('run','--rm','--pull','never','--network','none','--read-only','--memory','320m','--pids-limit','32','--cpus','0.5','--user','10001:10001','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--mount','type=volume,src='+name+',dst=/source,readonly','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=224m,uid=10001,gid=10001',
        '--entrypoint','/opt/fetch/.venv/bin/python',probe_image,'-I','-c',PROBE,timeout=60))
    require(type(result.get('required')) is int and result['required'] in (0,1,2) and type(result.get('pending')) is int and result['pending'] >= 0
            and type(result.get('imageOperations')) is int and 0 <= result['imageOperations'] <= 128
            and (result.get('pool') is None or isinstance(result['pool'],str) and re.fullmatch('[a-f0-9]{32}',result['pool'])), 'Runner receipt probe was inconclusive')
    return result


def validate_spec(config, current, project, name):
    service = config.get('services', {}).get('mcp-runner', {}); env = service.get('environment', {})
    backend = config.get('services', {}).get('backend', {}).get('environment', {})
    require(isinstance(env,dict) and env.get('MCP_EXECUTION_DB') == str(RECEIPTS), 'Fixed persistent runner journal required')
    require(env.get('MCP_EGRESS_PROXY') == 'http://mcp-egress:3128' and env.get('MCP_EXEC_NETWORK') == ('doorhandlecatch-mcp-exec' if project==common.PROJECT else project+'-mcp-exec'), 'Runner execution network changed')
    current_env = common.environment(current)
    require(current_env.get('MCP_RUNNER_SECRET') == env.get('MCP_RUNNER_SECRET') == backend.get('AGENT_MCP_GATEWAY_SECRET') and len(env.get('MCP_RUNNER_SECRET',''))>=32, 'Runner credential rotation requires a separate coordinated operation')
    mounts = service.get('volumes', [])
    for mount in mounts:
        target=mount.get('target')
        if target == str(RECEIPTS.parent):
            logical=mount.get('source'); definition=config.get('volumes',{}).get(logical,{})
            require(mount.get('type')=='volume' and definition.get('name',project+'_'+logical)==name, 'Transition would replace the runner receipt volume')
        else:
            require(mount.get('type')=='bind' and (mount.get('source'),target) in (('/var/run/docker.sock','/var/run/docker.sock'),('/usr/bin/docker','/usr/local/bin/docker')), 'Unexpected runner host mount')
    require(sum(value.get('target')==str(RECEIPTS.parent) for value in mounts)==1 and service.get('read_only') is True and not service.get('privileged') and not service.get('network_mode') and not service.get('pid') and not service.get('devices'), 'Runner isolation differs from the fixed deployment')
    require(env.get('MCP_FETCH_IMAGE')==service.get('image')==backend.get('AGENT_MCP_GATEWAY_IMAGE'), 'Runner and backend target bundle differ')
    require(not service.get('command') and not service.get('entrypoint') and 'ALL' in service.get('cap_drop',[]) and any(value.startswith('no-new-privileges') for value in service.get('security_opt',[])), 'Only the fixed runner program and isolation policy may be transitioned')
    for mount in current.get('Mounts',[]):
        if mount.get('Destination')==str(RECEIPTS.parent):continue
        require(mount.get('Type')=='bind' and (mount.get('Source'),mount.get('Destination')) in (('/var/run/docker.sock','/var/run/docker.sock'),('/run/docker.sock','/var/run/docker.sock'),('/usr/bin/docker','/usr/local/bin/docker')), 'Existing runner has an unexpected host mount')
    require(not current.get('HostConfig',{}).get('Privileged') and current.get('HostConfig',{}).get('ReadonlyRootfs') is True,'Existing runner isolation is not the fixed baseline')
    return service, env


def snapshot_definition(desired,current):
    value=copy.deepcopy(desired);actual=current.get('Config',{});host=current.get('HostConfig',{})
    value.pop('build',None);value.pop('pull_policy',None)
    value.update(image=current['Image'],environment=common.environment(current),user=actual.get('User','10001:10001'),read_only=True)
    for key,source in (('command','Cmd'),('entrypoint','Entrypoint')):
        if actual.get(source) is not None:value[key]=actual[source]
        else:value.pop(key,None)
    for key,source in (('cap_drop','CapDrop'),('security_opt','SecurityOpt'),('group_add','GroupAdd'),('pids_limit','PidsLimit'),('mem_limit','Memory')):
        if host.get(source) is not None:value[key]=host[source]
    if host.get('NanoCpus'):value['cpus']=str(host['NanoCpus']/1000000000)
    if host.get('Tmpfs') is not None:value['tmpfs']=[path+':'+options for path,options in host['Tmpfs'].items()]
    return value


def selected_config(config, selected):
    value=copy.deepcopy(config); env=value['services']['mcp-runner']['environment']; old_target=env['MCP_FETCH_IMAGE']
    approved={entry.strip() for entry in env.get('MCP_FETCH_APPROVED_IMAGES','').split(',') if entry.strip()}
    if selected!=old_target:approved.add(old_target)
    approved.discard(selected)
    require(len(approved)+1<=8 and all(common.DIGEST.fullmatch(entry) for entry in approved), 'Reviewed runner fallback list exceeds its fixed bound')
    for entry in approved:image(entry)
    env['MCP_FETCH_IMAGE']=selected;env['MCP_FETCH_APPROVED_IMAGES']=','.join(sorted(approved))
    value['services']['mcp-runner']['image']=selected
    value['services']['backend']['environment'].update(AGENT_MCP_GATEWAY_IMAGE=selected,MCP_FETCH_APPROVED_IMAGES=env['MCP_FETCH_APPROVED_IMAGES'])
    return value


def retention_available(project, config):
    mysql=common.container(project,'mysql');columns=guard.columns(mysql,'agent_fetch_image_retention')
    if not columns:
        require(not guard.flag(config['services']['backend']['environment'],'AGENT_MCP_SHARED_IMAGE_CLEANUP_ENABLED'),'V60 is required before shared cleanup can be activated')
        return False
    require({'reference_id','image_id','reference_kind','state'}<=columns and {'control_id','state','revision'}<=guard.columns(mysql,'agent_fetch_image_retention_control') and {'request_id','action_name','image_id'}<=guard.columns(mysql,'agent_fetch_image_retention_event'),'Recovery image retention migration is incomplete')
    return True


def retain(project, record, images):
    if not record.get('retentionAvailable'):return
    require(re.fullmatch('[a-f0-9]{32}',record['attempt']) and all(common.DIGEST.fullmatch(value) for value in images),'Retention request identity invalid')
    mysql=common.container(project,'mysql');values=sorted(set(images));quoted=','.join("'"+value+"'" for value in values);reference='transition:'+record['attempt']
    sql="START TRANSACTION; INSERT IGNORE INTO agent_fetch_image(image_id,state) VALUES "+','.join("('"+value+"','ACTIVE')" for value in values)+"; SELECT state FROM agent_fetch_image WHERE image_id IN ("+quoted+") ORDER BY image_id FOR UPDATE; "
    sql+="INSERT IGNORE INTO agent_fetch_image_retention(reference_id,image_id,reference_kind,state) SELECT '"+reference+"',image_id,'TRANSITION','HELD' FROM agent_fetch_image WHERE image_id IN ("+quoted+") AND state='ACTIVE'; "
    sql+="INSERT IGNORE INTO agent_fetch_image_retention_event(request_id,action_name,image_id) SELECT '"+record['attempt']+"','PREPARE_HOLD',r.image_id FROM agent_fetch_image_retention r JOIN agent_fetch_image f ON f.image_id=r.image_id AND f.state='ACTIVE' WHERE r.reference_id='"+reference+"' AND r.image_id IN ("+quoted+") AND r.state='HELD'; SELECT CONCAT('held:',COUNT(*)) FROM agent_fetch_image_retention r JOIN agent_fetch_image f ON f.image_id=r.image_id AND f.state='ACTIVE' WHERE r.reference_id='"+reference+"' AND r.image_id IN ("+quoted+") AND r.state='HELD'; COMMIT;"
    result=common.db(mysql,sql).splitlines();require(result and result[-1]=='held:'+str(len(values)),'A retired image cannot be retained as a new recovery baseline')


def snapshot(state, output, mode, allow_unhealthy, *, project=common.PROJECT):
    state=common.private_state(state);path=Path(output).absolute()
    allowed=path in (state/'rollback-current.yml',state/'previous-images.yml') or path.parent.parent==state.parent/'releases' and re.fullmatch('ci-[0-9]+-[a-f0-9]{12}',path.parent.name) and path.name in ('previous-images.yml','runtime-images.yml')
    require(allowed and not any(value.is_symlink() for value in (path,*path.parents)), 'Image snapshot must remain inside this deployment')
    services={};backend=None
    for service in ('backend','nginx','mysql','redis','kafka','mem0','chroma','detection-worker','mcp-runner'):
        row=common.container(project,service,optional=service=='mcp-runner')
        if row is None:continue
        healthy=row.get('State',{}).get('Running') is True and row.get('State',{}).get('Health',{}).get('Status')=='healthy'
        require(healthy or allow_unhealthy and service in ('backend','nginx','mem0','mcp-runner'), 'Existing services must be healthy before an image snapshot')
        if service=='backend':backend=row
        if mode!='all' and service not in ('chroma','detection-worker'):continue
        require(common.DIGEST.fullmatch(row.get('Image','')),'Snapshot image is not immutable');services[service]={'image':row['Image']}
        if service=='backend':
            env=common.environment(row);_,capability=guard.capability(row['Image']);_,formats=common.image(row['Image'])
            services[service]['environment']={'DETECTION_ASSIGNMENT_WRITES_ENABLED':str(common.boolean(env,common.GATE,True) if formats['json']==2 else True).lower(),'AGENT_MCP_WRITES_ENABLED':str(guard.flag(env,guard.GATE,True) if capability>=2 else True).lower()}
        if service=='mcp-runner':
            env=common.environment(row);backend_env=common.environment(backend)
            require(env.get('MCP_FETCH_IMAGE')==row['Image']==backend_env.get('AGENT_MCP_GATEWAY_IMAGE'),'Snapshot runner and backend target differ')
            approved=env.get('MCP_FETCH_APPROVED_IMAGES','');require(approved==backend_env.get('MCP_FETCH_APPROVED_IMAGES',''),'Snapshot reviewed lists differ')
            values=[value.strip() for value in approved.split(',') if value.strip()]
            require(len(set(values)|{row['Image']})<=8 and all(common.DIGEST.fullmatch(value) for value in values),'Snapshot release list is not fixed')
            services[service]['environment']={'MCP_FETCH_IMAGE':row['Image'],'MCP_FETCH_APPROVED_IMAGES':approved}
            services['backend']['environment'].update(AGENT_MCP_GATEWAY_IMAGE=row['Image'],MCP_FETCH_APPROVED_IMAGES=approved)
    common.write_json(path,{'services':services})


def prepare(state, config, *, project=common.PROJECT, restore_unpublished=False):
    state=common.private_state(state)
    restoration_of=None
    if (state/PRIVATE).exists():
        prior=private_read(state,PRIVATE)
        require(prior.get('phase') in ('VERIFIED','FINALIZED','RESTORED','DISABLED') and prior.get('project')==project, 'An unfinished runner transition must be reconciled before a new one')
        if prior.get('phase')=='VERIFIED':
            published=private_read(state,'release-publication.json') if (state/'release-publication.json').exists() else {}
            if published.get('runtimeAttempt')!=prior['attempt']:
                expected=next((value['image'] for value in prior.get('originals',[]) if value['service']=='backend'),None)
                require(restore_unpublished and expected==guard.capability(config['services']['backend']['image'])[0],'A verified but unpublished application transition must be reconciled before another release')
                restoration_of=prior['attempt']
            elif restore_unpublished:
                require(common.container(project,'backend')['Image']==guard.capability(config['services']['backend']['image'])[0],'Automatic restoration must preserve the published application')
                restoration_of=prior['attempt']
        elif restore_unpublished:
            require(common.container(project,'backend')['Image']==guard.capability(config['services']['backend']['image'])[0],'An automatic restoration must target the recorded original application')
            restoration_of=prior['attempt']
    runner=common.container(project,'mcp-runner',optional=True)
    if runner is None:
        require('mcp-runner' not in config.get('services',{}), 'Initial runner provisioning must complete before an in-place transition')
        guard.guard(state,config,project=project,pin=True)
        original=common.container(project,'backend')
        record={'schema':1,'project':project,'phase':'VERIFIED','action':'disabled','requiredProtocol':0,'poolVerified':False,'selectedBackendImage':guard.capability(config['services']['backend']['image'])[0],'restorationOf':restoration_of,'originals':[{'service':'backend','image':original['Image']}],'checkedAt':dt.datetime.now(common.ZONE).isoformat()}
        common.write_json(state/OVERRIDE,{'services':{}});write_record(state,record);return record
    name,binding=volume(project,runner); desired,env=validate_spec(config,runner,project,name)
    target=env['MCP_FETCH_IMAGE'];target_cap=image(target);old_cap=image(runner['Image'])
    current_env=common.environment(runner)
    require(guard.potential(config['services']['backend']['environment'])<4 or old_cap>=2,'Prepare a deployment-aware runner baseline before first image-retirement activation')
    # Validate application readers before quiescing. Actual storage is checked again once stopped.
    preview=selected_config(config,runner['Image'] if old_cap>target_cap else target)
    preview_receipt=guard.guard(state,preview,project=project,pin=True,runner_transition=True)
    record={'schema':1,'project':project,'phase':'PREPARING','action':'replace','requiredProtocol':0,'selectedImage':preview['services']['mcp-runner']['image'],'previousImage':runner['Image'],
            'volumeBinding':binding,'volumeName':name,'poolVerified':False,'previousEnvironment':current_env,'previousRunnerDefinition':snapshot_definition(desired,runner),'configuration':copy.deepcopy(config),
            'originals':[],'restorationOf':restoration_of,'quiescenceStarted':False,'retentionAvailable':retention_available(project,config),'selectedBackendImage':guard.capability(config['services']['backend']['image'])[0],'checkedAt':dt.datetime.now(common.ZONE).isoformat()}
    for service in ('nginx','backend','higress','mcp-runner'):
        row=common.container(project,service,optional=service=='higress')
        if row:record['originals'].append({'service':service,'id':row['Id'],'image':row['Image'],'started':row.get('State',{}).get('StartedAt'),'running':bool(row.get('State',{}).get('Running'))})
    write_record(state,record)
    try:
        retain(project,record,{runner['Image'],record['selectedImage']})
        record['quiescenceStarted']=True;write_record(state,record)
        for item in record['originals']:
            if not item['running']:continue
            row=inspect_id(item['id'],project,item['service'])
            require(row.get('Image')==item['image'] and row.get('State',{}).get('StartedAt')==item['started'],'Container generation changed before runner quiescence')
            common.docker('stop','--time','60',item['id'],timeout=180)
        stopped=inspect_id(runner['Id'],project,'mcp-runner');storage=probe(stopped,name,runner['Image'])
        required=max(storage['required'],2 if preview_receipt['required']>=4 else 1 if preview_receipt['required']>=3 else 0)
        selected=target if target_cap>=required else runner['Image']
        require(image(selected)>=required,'No existing runner can read the durable journal')
        effective=selected_config(config,selected)
        retain(project,record,{runner['Image'],selected})
        guard.guard(state,effective,project=project,pin=True,runner_transition=True,minimum_protocol=4 if storage['required']>=2 else 3 if storage['required'] else 0)
        if storage['pool'] is None:
            mysql=common.container(project,'mysql')
            execution_columns=guard.columns(mysql,'agent_mcp_execution')
            if execution_columns:
                require('state' in execution_columns and not common.exists(mysql,"SELECT EXISTS(SELECT 1 FROM agent_mcp_execution WHERE state<>'REMOVED' LIMIT 1);"),'A new journal pool cannot replace pending gateway executions')
            require(not common.docker('ps','-aq','--filter','label=doorhandle.mcp.managed=true').strip() and not common.docker('ps','-aq','--filter','label=doorhandle.mcp.legal=true').strip(),'Untracked MCP resources prevent journal initialization')
        record.update(phase='PREPARED',action='preserve' if selected!=target else 'replace',requiredProtocol=required,selectedImage=selected,previousPool=storage['pool'],pendingExecutions=storage['pending'],imageOperations=storage['imageOperations'])
        override={'services':{'mcp-runner':effective['services']['mcp-runner'],'backend':{'environment':{key:effective['services']['backend']['environment'][key] for key in ('AGENT_MCP_GATEWAY_IMAGE','MCP_FETCH_APPROVED_IMAGES')}}}}
        common.write_json(state/OVERRIDE,override);write_record(state,record);return record
    except Exception:
        record['phase']='NEEDS_REVIEW';write_record(state,record)
        raise


def verify(state, *, project=common.PROJECT):
    state=common.private_state(state);record=private_read(state,PRIVATE)
    require(record.get('project')==project and record.get('phase') in ('PREPARED','APPLYING','VERIFIED'), 'No matching prepared runner transition')
    if record.get('action')=='disabled':return record
    runner=common.container(project,'mcp-runner');name,binding=volume(project,runner)
    require(name==record['volumeName'] and binding==record['volumeBinding'] and runner['Image']==record['selectedImage'] and runner.get('State',{}).get('Running') is True and runner.get('State',{}).get('Health',{}).get('Status')=='healthy','Selected runner identity or health was not verified')
    # Fixed read-only SQL in the selected runner, without invoking an SDK or tool.
    durable=record.get('previousPool') is not None or image(runner['Image'])>=1 or guard.flag(record['configuration']['services']['backend']['environment'],'AGENT_MCP_EXECUTION_RECEIPTS_ENABLED')
    if durable:
        value=running_pool(runner['Id'])
        require(record.get('previousPool') is None or value==record['previousPool'], 'Runner pool changed; no execution exit may be inferred')
    for item in record.get('originals',[]):
        if item['service']=='higress' and item['running']:
            row=inspect_id(item['id'],project,'higress');require(row['Image']==item['image'] and row.get('State',{}).get('StartedAt')==item['started'],'Gateway generation changed during runner transition')
            if not row.get('State',{}).get('Running'):common.docker('start',item['id'])
    record.update(phase='VERIFIED',poolVerified=durable,selectedPool=value if durable else None,selectedContainer=runner['Id'],selectedStarted=runner.get('State',{}).get('StartedAt'),checkedAt=dt.datetime.now(common.ZONE).isoformat());write_record(state,record);return record


def running_pool(cid):
    value=json.loads(common.docker('exec',cid,'/opt/fetch/.venv/bin/python','-I','-c',"import json,sqlite3;from contextlib import closing\nwith closing(sqlite3.connect('file:/var/lib/doorhandle-mcp/executions.sqlite3?mode=ro',uri=True,timeout=2)) as db:\n db.execute('PRAGMA query_only=ON');print(json.dumps({'pool':db.execute(\"SELECT value FROM metadata WHERE key='pool_id'\").fetchone()[0]}))"))
    require(isinstance(value.get('pool'),str) and re.fullmatch('[a-f0-9]{32}',value['pool']),'Runner pool was not verified')
    return value['pool']


def applying(state, *, project=common.PROJECT):
    record=private_read(state,PRIVATE);require(record.get('project')==project and record.get('phase')=='PREPARED','Runner is not prepared for replacement')
    record['phase']='APPLYING';write_record(state,record);return record


def recover(state, *, project=common.PROJECT):
    state=common.private_state(state);record=private_read(state,PRIVATE)
    require(record.get('project')==project and record.get('phase') in ('PREPARING','PREPARED','APPLYING','NEEDS_REVIEW'),'No recoverable runner transition')
    try:
        if not record.get('quiescenceStarted'):
            for item in record['originals']:
                row=inspect_id(item['id'],project,item['service'])
                require(row['Image']==item['image'] and row.get('State',{}).get('StartedAt')==item['started'] and bool(row.get('State',{}).get('Running'))==item['running'],'Original state changed outside this transition')
            record.update(phase='RESTORED',checkedAt=dt.datetime.now(common.ZONE).isoformat());write_record(state,record);return record
        current=common.container(project,'mcp-runner');name,binding=volume(project,current)
        require(name==record['volumeName'] and binding==record['volumeBinding'] and current['Image'] in (record['previousImage'],record['selectedImage']),'Runner changed outside the recorded transition')
        if current.get('State',{}).get('Running'):common.docker('stop','--time','60',current['Id'],timeout=180)
        stopped=inspect_id(current['Id'],project,'mcp-runner');storage=probe(stopped,name,record['previousImage'])
        require(image(record['previousImage'])>=storage['required'],'Previous runner cannot read durable image fences; keep the compatible runner and reconcile manually')
        require(record.get('previousPool') is None or storage['pool']==record['previousPool'],'Runner pool changed during transition; automatic restoration is not approved')
        config=copy.deepcopy(record['configuration']);config['services']['mcp-runner']=record['previousRunnerDefinition']
        old_env=record['previousEnvironment']
        config['services']['backend']['environment'].update(AGENT_MCP_GATEWAY_IMAGE=record['previousImage'],MCP_FETCH_APPROVED_IMAGES=old_env.get('MCP_FETCH_APPROVED_IMAGES',''))
        backend_floor=4 if storage['required']>=2 else 3 if storage['required'] else 0
        require(guard.capability(next(value['image'] for value in record['originals'] if value['service']=='backend'))[1]>=backend_floor,'Original backend cannot read persisted image fences')
        recovery=state/'mcp-runtime-recovery-compose.json';common.write_json(recovery,config)
        common.docker('compose','--project-name',project,'-f',str(recovery),'up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120','mcp-runner',timeout=150)
        restored=common.container(project,'mcp-runner');require(restored['Image']==record['previousImage'] and volume(project,restored)[1]==binding and restored.get('State',{}).get('Health',{}).get('Status')=='healthy','Previous runner was not restored healthy')
        if storage['pool'] is not None:require(running_pool(restored['Id'])==storage['pool'],'Restored runner changed the receipt pool')
        for service in ('higress','backend','nginx'):
            for item in record['originals']:
                if item['service']!=service or not item['running']:continue
                row=inspect_id(item['id'],project,service)
                require(row['Image']==item['image'] and row.get('State',{}).get('StartedAt')==item['started'],'Original application changed; do not start another generation')
                if not row.get('State',{}).get('Running'):common.docker('start',item['id'])
        record.update(phase='RESTORED',poolVerified=storage['pool'] is not None,requiredProtocol=storage['required'],checkedAt=dt.datetime.now(common.ZONE).isoformat());write_record(state,record);return record
    except Exception:
        record['phase']='NEEDS_REVIEW';write_record(state,record);raise


def finalize(state, *, project=common.PROJECT):
    state=common.private_state(state);record=private_read(state,PRIVATE)
    require(record.get('project')==project and record.get('phase') in ('VERIFIED','FINALIZED'),'Only a verified runner transition can be finalized')
    if project==common.PROJECT:
        publication=private_read(state,'release-publication.json')
        require(publication.get('runtimeAttempt')==record['attempt'],'Publication pointers were not committed for this runner attempt')
    if record.get('action')=='disabled':
        backend=common.container(project,'backend');require(backend['Image']==record['selectedBackendImage'] and backend.get('State',{}).get('Health',{}).get('Status')=='healthy','Published application identity is not healthy')
        record['phase']='FINALIZED';write_record(state,record);return record
    backend=common.container(project,'backend');runner=common.container(project,'mcp-runner')
    require(backend['Image']==record['selectedBackendImage'] and backend.get('State',{}).get('Health',{}).get('Status')=='healthy' and runner['Image']==record['selectedImage'] and runner.get('State',{}).get('Health',{}).get('Status')=='healthy','Published application and runner identities are not healthy')
    require(runner['Id']==record.get('selectedContainer') and runner.get('State',{}).get('StartedAt')==record.get('selectedStarted'),'Runner generation changed after verification; reconcile before publishing recovery references')
    require(volume(project,runner)[1]==record['volumeBinding'],'Published runner no longer uses the recorded volume')
    if record.get('poolVerified'):require(running_pool(runner['Id'])==record.get('selectedPool'),'Runner receipt pool changed after verification')
    if record.get('retentionAvailable'):
        mysql=common.container(project,'mysql');current,previous=record['selectedImage'],record['previousImage'];request=record['attempt']
        require(common.DIGEST.fullmatch(current) and common.DIGEST.fullmatch(previous) and re.fullmatch('[a-f0-9]{32}',request),'Publication retention identities are invalid')
        # Publication pointers are updated by the caller first; commit all recovery references together.
        exists=common.exists(mysql,"SELECT EXISTS(SELECT 1 FROM agent_fetch_image_retention_event WHERE request_id='"+request+"' AND action_name='PUBLISH_REFERENCES' LIMIT 1);")
        sql="START TRANSACTION; SELECT image_id FROM agent_fetch_image ORDER BY image_id FOR UPDATE; "
        # Gate every mutation in the same locked transaction. A failed precondition must not release
        # the old recovery references or mark a partial baseline ACTIVE before the caller sees it.
        ids=','.join("'"+value+"'" for value in sorted({current,previous}))
        sql+="SET @fetch_retention_ready=(SELECT COUNT(*)="+str(len({current,previous}))+" FROM agent_fetch_image WHERE image_id IN ("+ids+") AND state='ACTIVE') AND (SELECT COUNT(*)=1 FROM agent_fetch_image_retention_control WHERE control_id=1 AND state IN ('COLLECTING','ACTIVE')); "
        for reference,image_id in (('deployment-current',current),('deployment-previous',previous)):
            sql+="INSERT INTO agent_fetch_image_retention(reference_id,image_id,reference_kind,state) SELECT '"+reference+"','"+image_id+"','PUBLISHED','HELD' WHERE @fetch_retention_ready ON DUPLICATE KEY UPDATE state='HELD',updated_at=CURRENT_TIMESTAMP; "
            sql+="UPDATE agent_fetch_image_retention SET state='RELEASED',updated_at=CURRENT_TIMESTAMP WHERE @fetch_retention_ready AND reference_id='"+reference+"' AND image_id<>'"+image_id+"' AND state='HELD'; "
        sql+="UPDATE agent_fetch_image_retention SET state='RELEASED',updated_at=CURRENT_TIMESTAMP WHERE @fetch_retention_ready AND reference_kind='TRANSITION' AND state='HELD'; UPDATE agent_fetch_image_retention_control SET state='ACTIVE',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE @fetch_retention_ready AND control_id=1; "
        sql+="INSERT IGNORE INTO agent_fetch_image_retention_event(request_id,action_name,image_id) SELECT '"+request+"','PUBLISH_REFERENCES','"+current+"' WHERE @fetch_retention_ready; SELECT IF(@fetch_retention_ready,'ACTIVE','PRESERVED'); COMMIT;"
        if not exists:require(common.db(mysql,sql).splitlines()[-1]=='ACTIVE','Published recovery references were not committed; previous references remain protected')
        else:
            require(common.exists(mysql,"SELECT (SELECT COUNT(*) FROM agent_fetch_image_retention WHERE reference_id='deployment-current' AND image_id='"+current+"' AND state='HELD')=1 AND (SELECT COUNT(*) FROM agent_fetch_image_retention WHERE reference_id='deployment-previous' AND image_id='"+previous+"' AND state='HELD')=1 AND (SELECT COUNT(*) FROM agent_fetch_image_retention_control WHERE control_id=1 AND state='ACTIVE')=1 AND (SELECT COUNT(*) FROM agent_fetch_image WHERE image_id IN ('"+current+"','"+previous+"') AND state<>'ACTIVE')=0;"),'Existing publication receipt does not match its protected images and active retention baseline')
    record.update(phase='FINALIZED',retentionVerified=bool(record.get('retentionAvailable')),checkedAt=dt.datetime.now(common.ZONE).isoformat());write_record(state,record);return record


def atomic_text(path, value):
    require(not path.is_symlink(),'Publication pointer cannot be a link')
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with os.fdopen(os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
        stream.write(value+'\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def aborted(state, *, project=common.PROJECT):
    record=private_read(state,PRIVATE)
    require(record.get('project')==project and record.get('phase')=='VERIFIED' and record.get('restorationOf'),'Only the explicitly restored original application can close an aborted release')
    backend=common.container(project,'backend');require(backend['Image']==record['selectedBackendImage'] and backend.get('State',{}).get('Health',{}).get('Status')=='healthy','Original application restoration remains unverified')
    record.update(phase='RESTORED',applicationRestored=True,checkedAt=dt.datetime.now(common.ZONE).isoformat());write_record(state,record);return record


def sync_publication(state, *, project=common.PROJECT):
    if not (state/'release-publication.json').exists():return
    value=private_read(state,'release-publication.json')
    require(value.get('schema')==1 and value.get('project')==project and isinstance(value.get('previousImages'),dict),'Publication record is invalid')
    for key in ('current','previous'):
        require(isinstance(value.get(key),str) and re.fullmatch(r'/(home|srv|opt)/[A-Za-z0-9_./-]+',value[key]) and '..' not in Path(value[key]).parts,'Publication directory invalid')
    common.write_json(state/'previous-images.yml',value['previousImages'])
    atomic_text(state/'previous-directory',value['previous']);atomic_text(state/'current-directory',value['current'])


def publish(state,current,previous,images, *, project=common.PROJECT):
    require(current is not None and previous is not None and images is not None,'Explicit publication pointers are required')
    record=private_read(state,PRIVATE);require(record.get('project')==project and record.get('phase')=='VERIFIED','Publication requires a verified runner transition')
    for directory in (current,previous):
        path=Path(directory);require(path.is_absolute() and path.is_dir() and re.fullmatch(r'/(home|srv|opt)/[A-Za-z0-9_./-]+',directory) and '..' not in path.parts and not any(value.is_symlink() for value in (path,*path.parents)),'Publication directory redirects are forbidden')
    path=Path(images).absolute();allowed=path==state/'rollback-current.yml' or path.parent.parent==state.parent/'releases' and path.name=='previous-images.yml'
    require(allowed and not path.is_symlink() and path.is_file() and path.stat().st_size<=1024*1024,'Publication snapshot is not an approved image snapshot')
    value=json.loads(path.read_text());require(isinstance(value,dict) and isinstance(value.get('services'),dict),'Publication image snapshot is invalid')
    # This single fsynced record is authoritative if a later compatibility-file update is interrupted.
    common.write_json(state/'release-publication.json',{'schema':1,'project':project,'current':current,'previous':previous,'previousImages':value,'runtimeAttempt':record['attempt'],'checkedAt':dt.datetime.now(common.ZONE).isoformat()})
    sync_publication(state,project=project);return record


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('status','snapshot','prepare','applying','verify','recover','aborted','publish','sync-publication','finalize'));parser.add_argument('--state',required=True);parser.add_argument('--lock-fd',required=True,type=int);parser.add_argument('--project',default=common.PROJECT)
    parser.add_argument('--output');parser.add_argument('--mode',choices=('all','runtime'),default='all');parser.add_argument('--allow-unhealthy',action='store_true')
    parser.add_argument('--current');parser.add_argument('--previous');parser.add_argument('--images')
    parser.add_argument('--restore-unpublished',action='store_true')
    args=parser.parse_args();state=common.private_state(args.state);lock=state/'deploy.lock';require(args.lock_fd>2 and not lock.is_symlink(),'Inherited deployment lock required')
    descriptor,expected=os.fstat(args.lock_fd),lock.stat();require(stat.S_ISREG(descriptor.st_mode) and descriptor.st_nlink==1 and (descriptor.st_dev,descriptor.st_ino)==(expected.st_dev,expected.st_ino),'Wrong runner deployment lock')
    import fcntl
    fcntl.flock(args.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if args.action=='status':
        value=private_read(state,PRIVATE) if (state/PRIVATE).exists() else None
        print(value['attempt']+':'+value['phase'] if value else 'NONE');return
    if args.action=='sync-publication':sync_publication(state,project=args.project);return
    if args.action=='publish':publish(state,args.current,args.previous,args.images,project=args.project);return
    if args.action=='snapshot':require(args.output is not None,'Snapshot output is required');snapshot(state,args.output,args.mode,args.allow_unhealthy,project=args.project);return
    if args.action=='prepare':
        payload=sys.stdin.buffer.read(8*1024*1024+1);require(len(payload)<=8*1024*1024,'Runner Compose metadata too large');record=prepare(state,json.loads(payload),project=args.project,restore_unpublished=args.restore_unpublished)
    else:record={'applying':applying,'verify':verify,'recover':recover,'aborted':aborted,'finalize':finalize}[args.action](state,project=args.project)
    print(record['action'])


if __name__=='__main__':
    try:main()
    except Exception:
        print('MCP runner transition remains unverified; retain private evidence and do not replay executions.',file=sys.stderr);raise SystemExit(2)
