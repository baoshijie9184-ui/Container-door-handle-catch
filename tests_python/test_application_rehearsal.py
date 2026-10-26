"""Validate that a rehearsal cannot inherit production identities or unsafe host resources."""
import copy
import importlib.util
import io
from pathlib import Path
import tarfile
import json
import sys
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1]/'script/docker/application-rehearsal.py'
spec = importlib.util.spec_from_file_location('application_rehearsal', SOURCE)
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)
PROJECT = 'doorhandle-rehearsal-0123456789ab'


def sample():
    return {'name': 'doorhandlecatch-monolith',
            'volumes': {'data': {'name': 'doorhandlecatch-monolith_data', 'external': True}},
            'networks': {'main': {'name': 'doorhandlecatch-monolith_main'},
                         'mcp-exec': {'name': 'doorhandlecatch-mcp-exec', 'internal': True}},
            'services': {
                'backend': {'image': 'old', 'environment': {'JWT_SECRET': 'production-jwt', 'DB_PASSWORD': 'production-db',
                    'AGENT_MCP_GATEWAY_SECRET': 'production-mcp', 'AGENT_MCP_GATEWAY_KEY': 'production-gateway',
                    'DEEPSEEK_API_KEY': 'provider-only'}, 'ports': [{'target': 8080, 'published': '8080'}],
                    'networks': {'main': None}, 'volumes': [{'type': 'volume', 'source': 'data', 'target': '/data'}]},
                'mysql': {'image': 'mysql', 'environment': {}, 'command': ['--default-time-zone=+08:00']},
                'mem0': {'image': 'old', 'environment': {'MEM0_BRIDGE_TOKEN': 'production-bridge'}},
                'nginx': {'image': 'old', 'environment': {}},
                'mcp-runner': {'image': 'fixed', 'environment': {'MCP_EXEC_NETWORK': 'doorhandlecatch-mcp-exec', 'MCP_RUNNER_SECRET': 'production-mcp'},
                               'volumes': [{'type': 'bind', 'source': '/var/run/docker.sock', 'target': '/var/run/docker.sock'}]},
                'detection-worker': {'image': 'fixed', 'volumes': [{'type': 'bind', 'source': '/models', 'target': '/models', 'read_only': True}]}}}


def config():
    return rehearsal.isolated_config(sample(), PROJECT, 18089, {'backend': 'sha256:'+'a'*64}, 'doorhandledb')


@pytest.mark.parametrize('foreign', [None,'owner','session','content'])
def test_native_upgrade_fixture_disables_llm_and_rejects_foreign_or_wrong_stored_results(monkeypatch,capsys,foreign):
    payload={'owner':'demo-owner','session':'demo-session','requestId':'fixture-request','content':'synthetic fixture'}
    observed=[]
    memory=SimpleNamespace(llm=SimpleNamespace())
    def add(content,**kwargs):
        observed.append(kwargs)
        assert kwargs['infer'] is False
        return {'results':[{'id':'fixture-memory','event':'ADD'}]}
    memory.add=add
    memory.get=lambda id:{'id':id,'user_id':'foreign' if foreign=='owner' else payload['owner'],
        'agent_id':'doorhandlecatch','run_id':'foreign' if foreign=='session' else payload['session'],
        'memory':'wrong' if foreign=='content' else payload['content']}
    def create(value):
        assert value['llm']['config']['api_key']=='fixture-no-llm-credential'
        return memory
    monkeypatch.setitem(sys.modules,'mem0',SimpleNamespace(Memory=SimpleNamespace(from_config=create)))
    monkeypatch.setitem(sys.modules,'main',SimpleNamespace(get_memory_config=lambda:{'llm':{'config':{'api_key':'private-provider-key'}}},configure_provider_timeouts=lambda value:None))
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(payload)))
    if foreign:
        with pytest.raises(AssertionError):exec(rehearsal.MEMORY_SEED,{})
    else:
        exec(rehearsal.MEMORY_SEED,{})
        receipt=json.loads(capsys.readouterr().out)
        assert receipt['memoryId']=='fixture-memory' and receipt['llmCalls']==0
    assert len(observed)==1
    with pytest.raises(RuntimeError,match='must not call an LLM'):memory.llm.generate_response()


def test_seed_failure_restarts_only_its_owned_memory_service_and_preserves_unknown_identity(tmp_path):
    calls=[]
    class Ops:
        def docker(self,*args,**kwargs):
            calls.append(args)
            return b''
        def healthy(self,id):return id=='owned-memory'
    run=rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.directory,run.project,run.config,run.ops=tmp_path,PROJECT,config(),Ops()
    run.row=lambda service:{'Id':'owned-memory','Image':'sha256:'+'a'*64,'Config':{'Labels':{'io.doorhandle.rehearsal':PROJECT}}}
    def fail(*args,**kwargs):raise RuntimeError('controlled seed failure')
    run.dc=fail
    with pytest.raises(RuntimeError,match='controlled seed failure'):run.seed_memory('owner','session')
    receipt=json.loads((tmp_path/'memory-seed.json').read_text())
    assert receipt['status']=='UNKNOWN' and receipt['requestId'] and receipt['session']=='session'
    assert [c[0] for c in calls]==['stop','ps','start'] and calls[-1]==('start','owned-memory')


def test_bridge_http_failure_has_a_private_classification_and_is_not_replayed(tmp_path):
    calls=[]
    class Ops:
        def docker(self,*args,**kwargs):
            calls.append(args)
            return b'{"bridgeFailure":{"type":"HTTPError","status":503}}'
    run=rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.directory,run.ops=tmp_path,Ops()
    run.row=lambda service:{'Id':'owned-memory'}
    with pytest.raises(RuntimeError,match='do not replay'):
        run.bridge('/memories/add',{'request_id':'original-request','run_id':'session','content':'PRIVATE_TURN_TEXT'})
    assert len(calls)==1
    file=next(tmp_path.glob('bridge-*.json'));receipt=json.loads(file.read_text())
    assert receipt['requestId']=='original-request' and receipt['status']=='FAILED' and receipt['failure']['status']==503
    assert 'PRIVATE_TURN_TEXT' not in file.read_text()


def test_memory_failure_archive_is_owned_read_only_and_redacts_provider_keys(tmp_path,monkeypatch):
    import gzip,hashlib
    calls=[];volume=PROJECT+'_memory'
    row={'Id':'owned-memory','Config':{'Labels':{'io.doorhandle.rehearsal':PROJECT},'Env':['MEM0_BRIDGE_TOKEN=fixture-private-key']},
         'Mounts':[{'Type':'volume','Name':volume}]}
    class Ops:
        def docker(self,*args,**kwargs):
            calls.append(args)
            if args[0]=='ps':return b'owned-memory'
            if args[0]=='inspect':return json.dumps([row]).encode()
            if args[:2]==('volume','inspect'):return json.dumps([{'Labels':{'io.doorhandle.rehearsal':PROJECT}}]).encode()
            if args[0]=='run':kwargs['output'].write(gzip.compress(b'private native receipt'));return b''
            return b''
        def digest(self,path):return hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(rehearsal.subprocess,'run',lambda *args,**kw:SimpleNamespace(stdout=b'failure token fixture-private-key'))
    run=rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.directory,run.project,run.ops=tmp_path,PROJECT,Ops()
    run.baseline=[{'service':'backend','image':'sha256:'+'a'*64}]
    receipt=run.capture_memory_failure()
    assert receipt['captured'] and len(receipt['snapshotSha256'])==64
    assert 'fixture-private-key' not in (tmp_path/'memory-failure.log').read_text()
    archive=next(c for c in calls if c[0]=='run')
    assert 'none' in archive and 'type=volume,src='+volume+',dst=/source,readonly' in archive
    assert not any(c[0] in ('rm','rmi') for c in calls)


def test_config_replaces_credentials_networks_storage_and_listener_without_mutating_source():
    source = sample()
    original = copy.deepcopy(source)
    value = rehearsal.isolated_config(source, PROJECT, 18089, {'backend': 'sha256:'+'a'*64}, 'doorhandledb')
    assert source == original
    assert value['volumes']['data']['name'] == PROJECT+'_data' and not value['volumes']['data'].get('external')
    assert all(resource['name'].startswith(PROJECT+'-') for resource in value['networks'].values())
    assert value['networks']['mcp-exec']['internal']
    backend = value['services']['backend']['environment']
    mysql = value['services']['mysql']['environment']
    assert backend['DB_PASSWORD'] == mysql['MYSQL_PASSWORD'] and backend['DB_PASSWORD'] != mysql['MYSQL_ROOT_PASSWORD']
    assert 'mysql:3306/doorhandledb?' in backend['DB_URL'] and backend['DB_USERNAME'] == mysql['MYSQL_USER']
    assert backend['MEM0_BRIDGE_TOKEN'] == value['services']['mem0']['environment']['MEM0_BRIDGE_TOKEN']
    assert backend['AGENT_MCP_GATEWAY_SECRET'] == value['services']['mcp-runner']['environment']['MCP_RUNNER_SECRET']
    assert value['services']['mcp-runner']['environment']['MCP_EXEC_NETWORK'] == PROJECT+'-mcp-exec'
    assert backend['DEEPSEEK_API_KEY'] == 'provider-only'
    assert all(not environment.startswith('production-') for key, environment in backend.items() if key.endswith(('PASSWORD', 'SECRET', 'TOKEN', 'KEY')))
    assert value['services']['mysql']['command'][-1] == '--event-scheduler=OFF'
    assert 'ports' not in value['services']['backend']
    assert value['services']['nginx']['ports'] == [{'target': 80, 'published': '18089', 'host_ip': '127.0.0.1', 'protocol': 'tcp'}]
    assert config()['services']['backend']['environment']['JWT_SECRET'] != backend['JWT_SECRET']


@pytest.mark.parametrize('damage', ['production-project', 'external-volume', 'shared-network', 'unknown-volume', 'host-root',
    'writable-model', 'public-port', 'privileged', 'host-network', 'host-pid', 'inherited-volumes', 'secrets'])
def test_unowned_or_unsafe_resources_rejected_before_docker(damage):
    value = config()
    if damage == 'production-project': value['name'] = 'doorhandlecatch-monolith'
    elif damage == 'external-volume': value['volumes']['data']['external'] = True
    elif damage == 'shared-network': value['networks']['main']['name'] = 'doorhandlecatch-mcp-exec'
    elif damage == 'unknown-volume': value['services']['backend']['volumes'][0]['source'] = 'production'
    elif damage == 'host-root': value['services']['backend']['volumes'] = [{'type': 'bind', 'source': '/', 'target': '/host'}]
    elif damage == 'writable-model': value['services']['detection-worker']['volumes'][0]['read_only'] = False
    elif damage == 'public-port': value['services']['nginx']['ports'][0]['host_ip'] = '0.0.0.0'
    elif damage == 'privileged': value['services']['backend']['privileged'] = True
    elif damage == 'host-network': value['services']['backend']['network_mode'] = 'host'
    elif damage == 'host-pid': value['services']['backend']['pid'] = 'host'
    elif damage == 'inherited-volumes': value['services']['backend']['volumes_from'] = ['production']
    elif damage == 'secrets': value['secrets'] = {'production-secret': {'external': True}}
    with pytest.raises(RuntimeError): rehearsal.validate_isolation(value, PROJECT)


@pytest.mark.parametrize('project', ['doorhandlecatch-monolith', 'other', 'doorhandle-rehearsal-../bad', PROJECT.upper()])
def test_invalid_project_identity_rejected(project):
    with pytest.raises(RuntimeError): rehearsal.isolated_config(sample(), project, 18089, {}, 'doorhandledb')


@pytest.mark.parametrize('name,kind', [('../outside', tarfile.REGTYPE), ('/outside', tarfile.REGTYPE),
    ('a\\outside', tarfile.REGTYPE), ('link', tarfile.SYMTYPE), ('link', tarfile.LNKTYPE), ('device', tarfile.CHRTYPE)])
def test_source_archive_rejects_traversal_links_and_special_files(tmp_path, name, kind):
    file = tmp_path/'source.tar.gz'
    with tarfile.open(file, 'w:gz') as archive:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE): entry.linkname = '/outside'
        archive.addfile(entry)
    target = tmp_path/'source'
    target.mkdir()
    with pytest.raises(RuntimeError): rehearsal.extract_source(file, target)
    assert list(target.iterdir()) == []


def test_source_archive_accepts_actual_git_layout(tmp_path):
    file = tmp_path/'source.tar.gz'
    with tarfile.open(file, 'w:gz') as archive:
        entry = tarfile.TarInfo('README.md')
        entry.size = 4
        archive.addfile(entry, io.BytesIO(b'test'))
    target = tmp_path/'source'
    target.mkdir()
    rehearsal.extract_source(file, target)
    assert (target/'README.md').read_bytes() == b'test'


def test_cleanup_refuses_foreign_volume_even_if_compose_project_name_matches(tmp_path):
    class Ops:
        class OpsError(RuntimeError): pass
        def docker(self, *args):
            if args[0] == 'ps': return b''
            assert args[:2] == ('volume', 'inspect')
            return b'[{"Labels":{"io.doorhandle.rehearsal":"another-project"}}]'
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.config, run.project, run.ops = config(), PROJECT, Ops()
    run.model_secret_source = None
    run.dc = lambda *args: pytest.fail('Must not call compose down on an unowned resource')
    with pytest.raises(RuntimeError, match='Cleanup ownership'): run.cleanup()


def test_production_identity_change_blocks_acceptance():
    original = {'id': 'original', 'image': 'immutable', 'running': True, 'mounts': []}
    class Ops:
        def inventory(self): return [{**original, 'id': 'unexpected'}]
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.ops, run.baseline = Ops(), [original]
    run.report = {}
    run.persist = lambda: None
    run.check = lambda name, condition: rehearsal.require(condition, name)
    with pytest.raises(RuntimeError, match='Production containers'): run.production_unchanged()
    assert run.report['productionChanged'] is True


def test_foreign_container_rejected_before_compose_down():
    class Ops:
        def docker(self, *args):
            return b'foreign-id' if args[0] == 'ps' else b'[{"Config":{"Labels":{}}}]'
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.config, run.project, run.ops = config(), PROJECT, Ops()
    run.model_secret_source = None
    run.dc = lambda *args: pytest.fail('Foreign container must not be removed')
    with pytest.raises(RuntimeError, match='container ownership'): run.cleanup()


@pytest.mark.parametrize('existing', ['container', 'volume', 'network'])
def test_rehearsal_requires_fresh_resources_before_restore(existing):
    class Ops:
        def docker(self, *args):
            if args[0] == 'ps': return b'existing-id' if existing == 'container' else b''
            if args[0] == existing: return (PROJECT+('_data' if existing == 'volume' else '-main')).encode()
            return b''
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.config, run.project, run.ops = config(), PROJECT, Ops()
    with pytest.raises(RuntimeError, match='already exist'): run.require_fresh_resources()


@pytest.mark.parametrize('data', ['', 'GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG',
    'worker task 0 - 9 -', 'worker task 0 8 9 1', 'worker task 0 9 9 0\nworker other 1 5 8 3'])
def test_missing_unknown_or_pending_worker_offsets_cannot_start_copied_detection(data):
    with pytest.raises(RuntimeError): rehearsal.require_no_detection_backlog(data, 'worker')


def test_every_worker_partition_requires_a_known_committed_end_offset():
    rehearsal.require_no_detection_backlog('GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG\nworker task 0 9 9 0 - - -\nworker task 1 12 12 0 - - -', 'worker')


def ui_resources():
    return {'/': b'<!doctype html><html><div id="app"></div><script type="module" src="/assets/vue.js"></script></html>',
            '/agent-ui/': b'<script type="module" src="/agent-ui/assets/react.js"></script><div id="root"></div>',
            '/assets/vue.js': b'/* real fixture module */ window.vueLoaded=true;',
            '/agent-ui/assets/react.js': b'/* real fixture module */ window.reactLoaded=true;'}


def test_smoke_accepts_legacy_react_fragment_and_requires_its_actual_module():
    class Client:
        def request(self, method, path): return ui_resources()[path]
    rehearsal.verify_ui_entries(Client())


@pytest.mark.parametrize('damage', ['missing-root', 'missing-script', 'external-script', 'traversal-script', 'empty-module', 'spa-fallback'])
def test_entry_smoke_rejects_broken_or_external_module_resources(damage):
    resources = ui_resources()
    if damage == 'missing-root': resources['/agent-ui/'] = resources['/agent-ui/'].replace(b'id="root"', b'id="wrong"')
    elif damage == 'missing-script': resources['/agent-ui/'] = b'<div id="root"></div>'
    elif damage == 'external-script': resources['/agent-ui/'] = resources['/agent-ui/'].replace(b'/agent-ui/assets/react.js', b'https://outside.example/app.js')
    elif damage == 'traversal-script': resources['/agent-ui/'] = resources['/agent-ui/'].replace(b'/agent-ui/assets/react.js', b'/agent-ui/assets/../private.js')
    elif damage == 'empty-module': resources['/agent-ui/assets/react.js'] = b''
    elif damage == 'spa-fallback': resources['/agent-ui/assets/react.js'] = resources['/']
    class Client:
        def request(self, method, path): return resources[path]
    with pytest.raises(RuntimeError): rehearsal.verify_ui_entries(Client())


@pytest.mark.parametrize('existing,signature,creates,passes', [('0','status,user_id,id',True,True),('3','status,user_id,id',False,True),('3','id,user_id,status',False,False)])
def test_fixed_candidate_migration_checks_existing_index_before_creating(tmp_path, existing, signature, creates, passes):
    root = Path(__file__).resolve().parents[1]
    calls = []
    class Ops:
        def db(self, container, sql):
            assert container == 'owned-copy'
            calls.append(sql)
            if 'COLUMN_NAME,LOWER(COLUMN_TYPE)' in sql:
                migrated = any('ADD COLUMN inference_fps' in statement for statement in calls)
                return model_fact_metadata() if migrated else ''
            return existing if 'COUNT(*)' in sql else signature
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.ops = Ops()
    run.report = {}
    run.row = lambda service: {'Id': 'owned-copy'}
    run.check = lambda name, condition: rehearsal.require(condition, name)
    if passes: run.migrate_candidate(root)
    else:
        with pytest.raises(RuntimeError): run.migrate_candidate(root)
    assert any('CREATE INDEX idx_conversation_input_dispatch_owner' in sql for sql in calls) == creates
    if passes:
        assert len(run.report['candidateMigrations']) == 24


def model_fact_metadata():
    return '\n'.join(name+'\t'+kind+'\tYES' for name,kind in (
        ('training_image_count','int'),('training_completed_at','datetime'),('evaluation_image_count','int'),
        ('no_detection_image_count','int'),('inference_fps','decimal(12,4)')))


@pytest.mark.parametrize('metadata', [model_fact_metadata().replace('decimal(12,4)','double'),
                                    model_fact_metadata().replace('int\tYES','int unsigned\tYES'),
                                    model_fact_metadata().replace('\tYES','\tNO')])
def test_candidate_existing_fact_type_mismatch_blocks_ddl(metadata):
    calls=[]
    class Ops:
        def db(self, container, sql): calls.append(sql); return metadata
    run=rehearsal.Rehearsal.__new__(rehearsal.Rehearsal);run.ops=Ops();run.row=lambda service:{'Id':'owned-copy'}
    with pytest.raises(RuntimeError,match='type differs'):
        run.migrate_candidate(Path(__file__).resolve().parents[1])
    assert len(calls)==1 and 'information_schema.COLUMNS' in calls[0]


def test_candidate_incomplete_post_migration_fact_columns_are_not_accepted():
    class Ops:
        def db(self, container, sql): return ''
    run=rehearsal.Rehearsal.__new__(rehearsal.Rehearsal);run.ops=Ops();run.row=lambda service:{'Id':'owned-copy'}
    with pytest.raises(RuntimeError,match='incomplete'):run.verify_model_fact_columns(complete=True)


def test_migration_copy_mismatch_stops_before_any_database_operation(tmp_path):
    file = tmp_path/'sql/mysql/migration-V39-conversation-owner-dispatch.sql'
    mirror = tmp_path/'doorhandle-module-app/src/main/resources/db/migration-V39-conversation-owner-dispatch.sql'
    for path in (file, mirror): path.parent.mkdir(parents=True)
    file.write_text('CREATE INDEX expected;',encoding='utf8')
    mirror.write_text('DIFFERENT;',encoding='utf8')
    run = rehearsal.Rehearsal.__new__(rehearsal.Rehearsal)
    run.row = lambda service: pytest.fail('Must not access a database when migration copies differ')
    with pytest.raises(RuntimeError, match='copies differ'): run.migrate_candidate(tmp_path)
