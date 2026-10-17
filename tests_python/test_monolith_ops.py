"""Run snapshot/restore control flow against a Docker protocol fixture, never a production daemon."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import pytest

SOURCE=Path(__file__).resolve().parents[1]/'script/docker/monolith-ops.py'
spec=importlib.util.spec_from_file_location('monolith_ops',SOURCE);ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(ops)
IMAGE='sha256:'+'a'*64
MYSQL_IMAGE='sha256:'+'b'*64


def tar_bytes(name='private.md', content=b'PRIVATE FILE', kind=None, link=None):
    value=io.BytesIO()
    with tarfile.open(fileobj=value,mode='w:gz') as archive:
        item=tarfile.TarInfo(name)
        if kind:item.type=kind;item.linkname=link or '';archive.addfile(item)
        else:item.size=len(content);archive.addfile(item,io.BytesIO(content))
    return value.getvalue()


def fixture(monkeypatch,root):
    (root/'state').mkdir();(root/'releases').mkdir();runtime=root/'runtime';(runtime/'deploy').mkdir(parents=True)
    (runtime/'deploy/cloud.env').write_text('PRIVATE_TOKEN=fixture\nMYSQL_ROOT_PASSWORD=fixture-root\nMYSQL_PASSWORD=fixture-app\nDB_PASSWORD=fixture-app\nJWT_SECRET='+('fixture-jwt-'*4)+'\nMEM0_BRIDGE_TOKEN='+('fixture-bridge-'*4)+'\nREDIS_PASSWORD='+('fixture-redis-'*2)+'\n',encoding='utf8')
    live=[{'id':'db-id','service':'mysql','image':MYSQL_IMAGE,'running':True,'mounts':[]},
          {'id':'backend-id','service':'backend','image':IMAGE,'running':True,'mounts':[{'type':'volume','source':'doorhandle-workspace','target':'/app/workspace'}]},
          {'id':'web-id','service':'nginx','image':IMAGE,'running':True,'mounts':[]}]
    monkeypatch.setattr(ops,'private_config_ok',lambda path:True);monkeypatch.setattr(ops,'inventory',lambda:live)
    monkeypatch.setattr(ops,'healthy',lambda container:True);monkeypatch.setattr(ops,'table_counts',lambda container:{'demo':2})
    monkeypatch.setattr(ops,'table_checksums',lambda container,names:{'demo':123})
    monkeypatch.setattr(ops,'db',lambda container,sql:'0\n' if 'information_schema.events' in sql else 'doorhandledb\n')
    monkeypatch.setattr(ops,'estimate_backup',lambda *args:64*1024**2)
    monkeypatch.setattr(ops.shutil,'disk_usage',lambda path:type('Usage',(),{'free':20*1024**3,'used':20*1024**3,'total':40*1024**3})())
    calls=[];resumed=[]
    monkeypatch.setattr(ops,'resume',lambda rows:resumed.extend(row['id'] for row in rows))
    def docker(*args,**kwargs):
        calls.append((args,kwargs))
        if args[0]=='exec' and 'mysqldump' in str(args):kwargs['output'].write(b'CREATE TABLE demo(id INT);\nINSERT INTO demo VALUES(1),(2);\n')
        elif args[0]=='run' and kwargs.get('output'):kwargs['output'].write(tar_bytes())
        return b''
    monkeypatch.setattr(ops,'docker',docker)
    return runtime,calls,resumed


def test_backup_quiesces_ingress_and_writers_resumes_exact_services_and_checks_all_data(tmp_path,monkeypatch):
    runtime,calls,resumed=fixture(monkeypatch,tmp_path)
    snapshot=ops.backup(tmp_path,runtime)
    result=ops.verify(snapshot)
    assert calls[0][0]==('stop','--time','60','web-id')
    assert calls[1][0]==('stop','--time','60','backend-id')
    assert resumed==['backend-id','web-id'] and 'db-id' not in resumed
    assert result['tableCounts']=={'demo':2} and result['volumes']=={'doorhandle-workspace':'volume-0.tar.gz'}
    assert (snapshot/'COMPLETE').is_file() and not (snapshot/'database.sql').exists()
    assert ops.archive_files(snapshot/'volume-0.tar.gz')['private.md']['sha256']==hashlib.sha256(b'PRIVATE FILE').hexdigest()
    assert all('PRIVATE_TOKEN' not in str(args) for args,kwargs in calls)
    (snapshot/'volume-0.tar.gz').write_bytes(b'damaged')
    with pytest.raises(ops.OpsError,match='checksum'):ops.verify(snapshot)


@pytest.mark.parametrize('failed_phase',['stop','dump','volume','resume'])
def test_backup_failure_never_claims_completion_and_attempts_service_recovery(tmp_path,monkeypatch,failed_phase):
    runtime,calls,resumed=fixture(monkeypatch,tmp_path);original=ops.docker
    def docker(*args,**kwargs):
        if (failed_phase=='stop' and args[0]=='stop') or (failed_phase=='dump' and args[0]=='exec') or (failed_phase=='volume' and args[0]=='run'):raise ops.OpsError('fixture failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(ops,'docker',docker)
    if failed_phase=='resume':
        def resume(rows):resumed.extend(row['id'] for row in rows);raise ops.OpsError('resume failure')
        monkeypatch.setattr(ops,'resume',resume)
    with pytest.raises(ops.OpsError):ops.backup(tmp_path,runtime)
    assert resumed==['backend-id','web-id']
    snapshot=next((tmp_path/'backups').iterdir());assert not (snapshot/'COMPLETE').exists()
    if (snapshot/'manifest.json').exists():
        with pytest.raises(ops.OpsError,match='did not complete'):ops.verify(snapshot)


@pytest.mark.parametrize('name,kind,link',[('../escape',None,None),('/escape',None,None),('link',tarfile.LNKTYPE,'../escape'),('device',tarfile.CHRTYPE,None)])
def test_archive_restore_rejects_traversal_hardlink_escape_and_devices(tmp_path,name,kind,link):
    archive=tmp_path/'archive.tar.gz';archive.write_bytes(tar_bytes(name,kind=kind,link=link))
    with pytest.raises(ops.OpsError,match='Unsafe'):ops.validate_members(archive)


def test_snapshot_manifest_cannot_reference_files_outside_checked_inventory(tmp_path,monkeypatch):
    runtime,_,_=fixture(monkeypatch,tmp_path);snapshot=ops.backup(tmp_path,runtime)
    manifest=json.loads((snapshot/'manifest.json').read_text());manifest['volumes']['doorhandle-workspace']='../../outside.tar.gz'
    ops.write_json(snapshot/'manifest.json',manifest)
    ops.write_json(snapshot/'COMPLETE',{'manifestSha256':ops.digest(snapshot/'manifest.json')})
    with pytest.raises(ops.OpsError,match='volume map'):ops.verify(snapshot)


def test_prune_protects_live_stopped_and_previous_images_and_only_old_app_tags(tmp_path,monkeypatch):
    (tmp_path/'state').mkdir();old='sha256:'+'c'*64;previous='sha256:'+'d'*64
    (tmp_path/'state/previous-images.yml').write_text('image: '+previous)
    rows=[{'Repository':'doorhandlecatch/backend','Tag':f'ci-{n}-'+'e'*12,'ID':('sha256:'+str(n)*64 if n>4 else old if n==2 else previous if n==1 else 'sha256:'+'f'*64)} for n in range(1,7)]
    rows.append({'Repository':'mysql','Tag':'8.4','ID':'sha256:'+'9'*64})
    def docker(*args,**kwargs):
        if args[:2]==('ps','-aq'):return b'live stopped'
        if args[0]=='inspect':return json.dumps([{'Image':old}]).encode()
        if args[:2]==('image','inspect'):return next(row['ID'] for row in rows if row['Repository']+':'+row['Tag']==args[-1]).encode()
        return '\n'.join(json.dumps(row) for row in rows).encode()
    monkeypatch.setattr(ops,'docker',docker)
    result=ops.prune_plan(tmp_path,3)
    assert result['candidates']==['doorhandlecatch/backend:ci-3-'+'e'*12]
    assert old in result['protectedDigests'] and previous in result['protectedDigests']


def test_disk_backup_age_and_private_permissions_are_independent_health_signals(tmp_path,monkeypatch):
    runtime,_,_=fixture(monkeypatch,tmp_path)
    initial=ops.check(tmp_path,runtime);assert not initial['healthy'] and initial['backupAgeHours'] is None
    ops.backup(tmp_path,runtime);assert ops.check(tmp_path,runtime)['healthy']
    monkeypatch.setattr(ops,'private_config_ok',lambda path:False)
    assert not ops.check(tmp_path,runtime)['privateConfigurationPermissions']
    monkeypatch.setattr(ops.shutil,'disk_usage',lambda path:type('Usage',(),{'free':1024,'used':10**9,'total':10**9+1024})())
    assert not ops.check(tmp_path,runtime)['disk']['healthy']


@pytest.mark.parametrize('corrupt',['none','file','database'])
def test_restore_drill_only_writes_new_network_isolated_resources_and_checks_bytes(tmp_path,monkeypatch,corrupt):
    runtime,_,_=fixture(monkeypatch,tmp_path);snapshot=ops.backup(tmp_path,runtime);calls=[];run_suffix=''
    def docker(*args,**kwargs):
        nonlocal run_suffix
        calls.append((args,kwargs))
        if args[:2]==('run','-d'):
            run_suffix=next(value.split('=',1)[1] for value in args if value.startswith('doorhandle.ops.run='))
            assert '--network' in args and args[args.index('--network')+1]=='none';assert '--publish' not in args
            assert kwargs['env']['MYSQL_ROOT_PASSWORD'] not in str(args)
        if 'inspect' in args:return run_suffix.encode()
        if '-c' in args and ops.SCAN_VOLUME in args:return json.dumps({'private.md':{'type':'file','sha256':hashlib.sha256(b'DIFFERENT' if corrupt=='file' else b'PRIVATE FILE').hexdigest()}}).encode()
        return b''
    monkeypatch.setattr(ops,'docker',docker);monkeypatch.setattr(ops,'db',lambda *args:'1\n')
    if corrupt=='database':monkeypatch.setattr(ops,'table_checksums',lambda container,names:{'demo':999})
    if corrupt=='none':
        result=ops.restore_drill(tmp_path,snapshot)
        assert result['passed'] and result['databaseTables']==1 and result['volumes'][0]['verified']
    else:
        with pytest.raises(ops.OpsError,match='differs|differ'):ops.restore_drill(tmp_path,snapshot)
        assert not json.loads(next((tmp_path/'state').glob('restore-drill-*.json')).read_text())['passed']
    deletions=[args for args,kwargs in calls if args[0]=='rm' or args[:2]==('volume','rm')]
    assert deletions and all('doorhandle-restore-drill-' in args[-1] for args in deletions)
    assert all('doorhandle-workspace' not in str(args) for args,kwargs in calls)


def test_command_error_never_logs_database_or_provider_diagnostics(monkeypatch):
    monkeypatch.setattr(ops.subprocess,'run',lambda *args,**kwargs:subprocess.CompletedProcess(args,1,b'',b'PRIVATE PASSWORD=secret'))
    with pytest.raises(ops.OpsError) as error:ops.docker('exec','container','private-operation')
    assert 'secret' not in str(error.value) and 'PASSWORD' not in str(error.value)


def test_interrupted_maintenance_recovers_only_the_exact_original_container_identities(tmp_path,monkeypatch):
    runtime,_,resumed=fixture(monkeypatch,tmp_path);ops.backup(tmp_path,runtime);resumed.clear()
    record=json.loads((tmp_path/'state/maintenance.json').read_text());record['phase']='RECOVERY_REQUIRED';ops.write_json(tmp_path/'state/maintenance.json',record)
    result=ops.recover_maintenance(tmp_path);assert result['recovered'] and resumed==['backend-id','web-id']
    assert not ops.recover_maintenance(tmp_path)['recovered']
    record['containers'][0]['image']='sha256:'+'f'*64;ops.write_json(tmp_path/'state/maintenance.json',record);resumed.clear()
    with pytest.raises(ops.OpsError,match='identity changed'):ops.recover_maintenance(tmp_path)
    assert resumed==[]


def test_systemd_schedule_respects_beijing_midnight_shutdown_and_does_not_catch_up_on_boot():
    units=ops.systemd_units(PurePosixPath('/home/demo/ci'),PurePosixPath('/home/demo/runtime'),PurePosixPath('/home/demo/ci/releases/ci-1/script/docker/monolith-ops.py'),'demo')
    assert len(units)==5
    assert '23:30:00 Asia/Shanghai' in units['doorhandle-backup.timer'] and 'Persistent=false' in units['doorhandle-backup.timer']
    assert 'ExecStopPost=' in units['doorhandle-backup.service'] and ' recover ' in units['doorhandle-backup.service']
    assert 'OnUnitInactiveSec=15min' in units['doorhandle-disk-check.timer']
    assert 'WantedBy=multi-user.target' in units['doorhandle-maintenance-recover.service']
    assert all('User=demo' in value and 'UMask=0077' in value for name,value in units.items() if name.endswith('.service'))
    with pytest.raises(ops.OpsError):ops.systemd_units(Path('/home/demo/ci;touch-anything'),Path('/srv/runtime'),Path('/srv/tool.py'),'demo')


def test_credential_inventory_reports_configuration_without_reading_or_outputting_values(tmp_path,monkeypatch):
    runtime,_,_=fixture(monkeypatch,tmp_path)
    result=ops.credential_status(runtime/'deploy/cloud.env');assert result['healthy'];assert 'fixture' not in json.dumps(result)
    with (runtime/'deploy/cloud.env').open('a') as stream:stream.write('DB_PASSWORD=wrong\n')
    assert not ops.credential_status(runtime/'deploy/cloud.env')['applicationDatabasePasswordMatches']
    monkeypatch.setattr(ops,'private_config_ok',lambda path:False)
    assert ops.credential_status(runtime/'deploy/cloud.env')=={'healthy':False,'reason':'Private configuration permissions are invalid'}


def test_inherited_deployment_lock_cannot_unlock_the_parent_or_use_another_file(tmp_path,monkeypatch):
    import os,sys
    from types import SimpleNamespace
    (tmp_path/'state').mkdir();path=tmp_path/'state/deploy.lock';path.touch();calls=[]
    monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda fd,flag:calls.append(flag)))
    with path.open('a') as parent:
        with ops.maintenance_lock(tmp_path,parent.fileno()):assert not parent.closed
        os.fstat(parent.fileno());assert calls==[6]  # No LOCK_UN against the parent's shared lock.
    with (tmp_path/'different').open('a') as other:
        with pytest.raises(ops.OpsError,match='does not match'):
            with ops.maintenance_lock(tmp_path,other.fileno()):pytest.fail('wrong lock was accepted')


def test_pipeline_backup_gate_precedes_build_and_replacement():
    source=(SOURCE.parents[1]/'jenkins/deploy-remote.sh').read_text()
    backup=source.index('monolith-ops.py" backup');build=source.index(' build backend nginx');replace=source.index('if ! activate "$release"')
    assert backup<build<replace and '--lock-fd 9' in source
    assert '--keep 3 --apply' in source and 'docker volume prune' not in source


def test_checksums_are_queried_for_complete_validated_table_set(monkeypatch):
    calls=[]
    def db(container,sql):calls.append(sql);return 'doorhandledb.a\t123\ndoorhandledb.b\t0\n'
    monkeypatch.setattr(ops,'db',db)
    assert ops.table_checksums('container',{'b':1,'a':2})=={'a':123,'b':0}
    assert calls==['CHECKSUM TABLE `a`,`b` EXTENDED;']
    with pytest.raises(ops.OpsError):ops.table_checksums('container',{'a;injection':1})
    monkeypatch.setattr(ops,'db',lambda *args:'doorhandledb.a\tNULL\n')
    with pytest.raises(ops.OpsError,match='unavailable'):ops.table_checksums('container',{'a':1})


def test_enabled_database_events_are_rejected_before_stopping_services(tmp_path,monkeypatch):
    runtime,calls,resumed=fixture(monkeypatch,tmp_path);monkeypatch.setattr(ops,'db',lambda *args:'1\n')
    with pytest.raises(ops.OpsError,match='database events'):ops.backup(tmp_path,runtime)
    assert calls==[] and resumed==[]


def test_live_oneoff_work_is_not_stopped_and_replayed_by_maintenance(monkeypatch):
    rows=[{'Id':'temporary','Image':IMAGE,'Config':{'Labels':{'com.docker.compose.service':'mcp-runner','com.docker.compose.oneoff':'True'}},'State':{'Running':True},'Mounts':[]}]
    def docker(*args,**kwargs):return b'temporary' if args[0]=='ps' else json.dumps(rows).encode()
    monkeypatch.setattr(ops,'docker',docker)
    with pytest.raises(ops.OpsError,match='one-off'):ops.inventory()


def test_backup_estimate_and_free_space_reserve_prevent_quiescing_when_disk_is_too_small(tmp_path,monkeypatch):
    runtime,calls,resumed=fixture(monkeypatch,tmp_path)
    monkeypatch.setattr(ops,'estimate_backup',lambda *args:19*1024**3)
    with pytest.raises(ops.OpsError,match='estimated backup'):ops.backup(tmp_path,runtime)
    assert calls==[] and resumed==[]
    monkeypatch.setattr(ops.shutil,'disk_usage',lambda path:type('Usage',(),{'free':1024})())
    with pytest.raises(ops.OpsError,match='preserve free disk'):ops.output_budget(tmp_path,2*1024**3)


def test_estimation_only_reads_validated_existing_volumes(monkeypatch):
    calls=[];monkeypatch.setattr(ops,'db',lambda *args:str(20*1024**2))
    def docker(*args,**kwargs):calls.append(args);return b'500'
    monkeypatch.setattr(ops,'docker',docker)
    required=ops.estimate_backup('db',IMAGE,['doorhandle-workspace'])
    assert required>=120*1024**2 and required>120*1024**2
    assert all('readonly' in str(args) and '--network' in args and '--read-only' in args for args in calls)
    with pytest.raises(ops.OpsError):ops.estimate_backup('db',IMAGE,['../anything'])
