"""Run monolith verification on the explicitly admitted original ECS only."""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
WORKER_FIXTURE_HELPER = ROOT / 'script/schema/worker_mysql_fixture.py'
sys.path.insert(0, str(ROOT / 'scripts'))
from ecs_execution import require_ecs_execution


@contextmanager
def private_process_umask():
    """Keep verifier-owned host logs and intermediate directories private."""
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


# These names describe existing ECS-only Java fixtures. Never accept arbitrary -D
# properties: some unrelated switches enable paid models or production services.
FIXTURE_SCHEMAS = {
    'doorhandle.ecs.mysql.config': ('doorhandle_ecsit_', 'ecsit_'),
    'doorhandle.feature.mysql.config': ('doorhandle_feature_', 'ecsit_'),
    'workbench.mysql.config': ('doorhandle_wb_verify_', 'wb_verify_'),
    'workbench.migration.source': ('doorhandle_agent_verify_', 'ecsit_'),
    'workbench.migration.target': ('doorhandle_wb_verify_', 'wb_verify_'),
    'agent.model-config.mysql-file': ('doorhandle_model_verify_', 'ecsit_'),
    'agent.skill.mysql-file': ('doorhandle_skill_verify_', 'ecsit_'),
    'agent.journal.mysql-file': ('doorhandle_agent_verify_', 'ecsit_'),
    'detection.command.mysql-file': ('doorhandle_detection_verify_', 'ecsit_'),
    'detection.outbox.mysql-file': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.action.mysql.config': ('doorhandle_agent_verify_', 'ecsit_'),
    'doorhandle.action.source.config': ('doorhandle_agent_verify_', 'ecsit_'),
    'doorhandle.context.mysql.config': ('doorhandle_agent_verify_', 'ecsit_'),
    'doorhandle.context.source.config': ('doorhandle_agent_verify_', 'ecsit_'),
    'doorhandle.mcp.mysql.config': ('doorhandle_agent_verify_', 'ecsit_'),
    'doorhandle.mcp.source.config': ('doorhandle_agent_verify_', 'ecsit_'),
    'doorhandle.model-budget.source.config': ('doorhandle_feature_', 'ecsit_'),
    'doorhandle.workspace.source.config': ('doorhandle_feature_', 'ecsit_'),
    'doorhandle.chat-evidence.source.config': ('doorhandle_feature_', 'ecsit_'),
    'legacy.chat.mysql.config': ('doorhandle_agent_verify_', 'ecsit_'),
    'doorhandle.core.mysql.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.fingerprint.mysql.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'detection.identity.mysql.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'detection.identity.source.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.support.mysql.config': ('doorhandle_feature_', 'ecsit_'),
    'doorhandle.support.source.config': ('doorhandle_feature_', 'ecsit_'),
    'doorhandle.report.mysql.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.digest.mysql.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.digest.copy.source.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.digest.copy.mysql.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.core.copy.source.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.core.copy.target.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.detection.runtime.copy.source.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.detection.runtime.copy.target.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.operations.mysql.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.operations.source.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.binding.mysql.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'doorhandle.binding.source.config': ('doorhandle_detection_verify_', 'ecsit_'),
    'report.copy.source-config': ('doorhandle_detection_verify_', 'ecsit_'),
    'report.copy.target-config': ('doorhandle_detection_verify_', 'ecsit_'),
    'agent.research.copy.source-config': ('doorhandle_agent_verify_', 'ecsit_'),
    'agent.research.copy.target-config': ('doorhandle_agent_verify_', 'ecsit_'),
    'agent.memory.copy.source-config': ('doorhandle_wb_verify_', 'ecsit_'),
    'agent.memory.copy.target-config': ('doorhandle_wb_verify_', 'ecsit_'),
    'model.file.copy.source-config': ('doorhandle_model_verify_', 'ecsit_'),
    'model.file.copy.target-config': ('doorhandle_model_verify_', 'ecsit_'),
    'model.log.copy.source-config': ('doorhandle_model_verify_', 'ecsit_'),
    'model.log.copy.target-config': ('doorhandle_model_verify_', 'ecsit_'),
    'infra.log.copy.source-config': ('doorhandle_feature_', 'ecsit_'),
    'infra.log.copy.target-config': ('doorhandle_feature_', 'ecsit_'),
}

SERVER_SWITCHES = {
    'EcsMysqlFixtureTest': 'ecs.fixture.mysql', 'AgentCardsLocalMysqlTest': 'agent.cards.local.mysql',
    'AgentConfirmationLocalMysqlTest': 'agent.actions.local.mysql', 'AgentReportLocalMysqlTest': 'agent.report.local.mysql',
    'AgentSessionLocalMysqlTest': 'agent.sessions.local.mysql', 'DetectionScopeLocalMysqlTest': 'detection.scope.local.mysql',
    'LocalMcpMysqlTest': 'agent.local.mcp.mysql', 'MemoryGovernanceLocalMysqlTest': 'agent.memory.local.mysql',
    'ReportEventLocalMysqlTest': 'report.events.local.mysql', 'SkillCommandLocalMysqlTest': 'agent.skills.commands.mysql',
    'SkillEvolutionLocalMysqlTest': 'agent.skills.local.mysql', 'ModelFactsMySqlTest': 'model.facts.mysql',
}

# The third member means the explicitly named target is only valid with a source.
# Reusable targets such as context.mysql.config remain usable without migrations.
MIGRATION_PAIRS = (
    ('doorhandle.action.source.config', 'doorhandle.action.mysql.config', False),
    ('doorhandle.context.source.config', 'doorhandle.context.mysql.config', False),
    ('doorhandle.mcp.source.config', 'doorhandle.mcp.mysql.config', False),
    ('doorhandle.model-budget.source.config', 'doorhandle.feature.mysql.config', False),
    ('doorhandle.workspace.source.config', 'doorhandle.feature.mysql.config', False),
    ('doorhandle.chat-evidence.source.config', 'doorhandle.feature.mysql.config', False),
    ('doorhandle.operations.source.config', 'doorhandle.operations.mysql.config', False),
    ('doorhandle.binding.source.config', 'doorhandle.binding.mysql.config', False),
    ('workbench.migration.source', 'workbench.migration.target', True),
    ('doorhandle.core.copy.source.config', 'doorhandle.core.copy.target.config', True),
    ('doorhandle.detection.runtime.copy.source.config', 'doorhandle.detection.runtime.copy.target.config', True),
    ('detection.identity.source.config', 'detection.identity.mysql.config', False),
    ('doorhandle.support.source.config', 'doorhandle.support.mysql.config', True),
    ('doorhandle.digest.copy.source.config', 'doorhandle.digest.copy.mysql.config', True),
    ('report.copy.source-config', 'report.copy.target-config', True),
    ('agent.research.copy.source-config', 'agent.research.copy.target-config', True),
    ('agent.memory.copy.source-config', 'agent.memory.copy.target-config', True),
    ('model.file.copy.source-config', 'model.file.copy.target-config', True),
    ('model.log.copy.source-config', 'model.log.copy.target-config', True),
    ('infra.log.copy.source-config', 'infra.log.copy.target-config', True),
)

FIXTURE_CLASSES = {name: ('doorhandle.ecs.mysql.config',) for name in SERVER_SWITCHES}
for property_name, classes in (
    ('doorhandle.feature.mysql.config', ('HistoricalDetectionSummaryMySqlTest', 'QualityKnowledgeMySqlTest',
        'MessageExecutionLinksTest', 'AgentWorkspaceServiceTest', 'ConversationInboxMySqlTest',
        'ModelBudgetMySqlTest', 'PersonalModelQuotaMySqlTest', 'QuotaAccountStoreMySqlTest', 'AiCollaborationMySqlTest')),
    ('workbench.mysql.config', ('AgentWorkbenchServiceTest',)),
    ('agent.model-config.mysql-file', ('ModelConfigurationServiceTest', 'ModelConfigurationMigrationMySqlTest')),
    ('agent.skill.mysql-file', ('SkillDownloadLeasesTest', 'SkillMigrationMySqlTest')),
    ('agent.journal.mysql-file', ('MysqlAgentJournalTest', 'JdbcOwnerLockMySqlTest')),
    ('detection.command.mysql-file', ('DetectionExecutionApiImplTest',)),
    ('detection.outbox.mysql-file', ('DetectionDispatchOutboxTest',)),
    ('doorhandle.action.mysql.config', ('AgentActionServiceTest', 'AgentContractEvalTest')),
    ('doorhandle.context.mysql.config', ('ContextStoreMySqlTest',)),
    ('doorhandle.mcp.mysql.config', ('LocalMcpServiceTest', 'PersistentMcpInstallQueueTest',
        'CrossInstanceMcpInstallCancellationTest')),
    ('legacy.chat.mysql.config', ('LegacyChatActionStoreMySqlTest',)),
    ('doorhandle.core.mysql.config', ('Core12PersistenceMySqlTest',)),
    ('doorhandle.fingerprint.mysql.config', ('DetectionFingerprintProjectionMySqlTest',)),
    ('detection.identity.mysql.config', ('DetectionIdentityServiceTest', 'IdentityEvidenceMySqlTest')),
    ('doorhandle.report.mysql.config', ('QualityReportServiceTest', 'ReportEventDeliveryTest',
        'IdentityPersistenceMySqlTest')),
    ('doorhandle.digest.mysql.config', ('QualityDigestMySqlTest',)),
    ('doorhandle.operations.mysql.config', ('AccountIdentityServiceTest', 'FileDeliveryAuditMySqlTest',
        'BusinessMutationAuditTest', 'OperationsAuditServiceTest', 'LoginSessionMySqlTest',
        'BusinessMutationCollaborationTest', 'OperationsChangeHistoryTest', 'CollaborationHttpMySqlTest')),
    ('doorhandle.report.mysql.config', ('DetectionCollaborationMySqlTest', 'SystemDetectionHistoryMySqlTest')),
):
    for class_name in classes:
        FIXTURE_CLASSES[class_name] = (property_name,)
for class_name, source, target in (
    ('ConfirmationMigrationMySqlTest', 'doorhandle.action.source.config', 'doorhandle.action.mysql.config'),
    ('ContextMigrationMySqlTest', 'doorhandle.context.source.config', 'doorhandle.context.mysql.config'),
    ('McpMigrationMySqlTest', 'doorhandle.mcp.source.config', 'doorhandle.mcp.mysql.config'),
    ('ModelBudgetMigrationMySqlTest', 'doorhandle.model-budget.source.config', 'doorhandle.feature.mysql.config'),
    ('WorkspaceMigrationMySqlTest', 'doorhandle.workspace.source.config', 'doorhandle.feature.mysql.config'),
    ('CompactChatMigrationMySqlTest', 'doorhandle.chat-evidence.source.config', 'doorhandle.feature.mysql.config'),
    ('OperationsCopyMySqlTest', 'doorhandle.operations.source.config', 'doorhandle.operations.mysql.config'),
    ('OrganizationBindingAuditMigrationMySqlTest', 'doorhandle.binding.source.config', 'doorhandle.binding.mysql.config'),
    ('WorkbenchMigrationMySqlTest', 'workbench.migration.source', 'workbench.migration.target'),
    ('CoreCopyMigrationMySqlTest', 'doorhandle.core.copy.source.config', 'doorhandle.core.copy.target.config'),
    ('DetectionRuntimeCopyMySqlTest', 'doorhandle.detection.runtime.copy.source.config', 'doorhandle.detection.runtime.copy.target.config'),
    ('IdentityMigrationMySqlTest', 'detection.identity.source.config', 'detection.identity.mysql.config'),
    ('SupportCopyMigrationMySqlTest', 'doorhandle.support.source.config', 'doorhandle.support.mysql.config'),
    ('DigestCopyMigrationMySqlTest', 'doorhandle.digest.copy.source.config', 'doorhandle.digest.copy.mysql.config'),
    ('ReportWorkflowMigrationMySqlTest', 'report.copy.source-config', 'report.copy.target-config'),
    ('ResearchExportMigrationMySqlTest', 'agent.research.copy.source-config', 'agent.research.copy.target-config'),
    ('MemoryGovernanceMigrationMySqlTest', 'agent.memory.copy.source-config', 'agent.memory.copy.target-config'),
    ('ModelFileGovernanceMySqlTest', 'model.file.copy.source-config', 'model.file.copy.target-config'),
    ('ModelUploadIdempotencyMySqlTest', 'model.file.copy.source-config', 'model.file.copy.target-config'),
    ('ModelOperationAuditMySqlTest', 'model.log.copy.source-config', 'model.log.copy.target-config'),
    ('InfraOperationAuditMySqlTest', 'infra.log.copy.source-config', 'infra.log.copy.target-config'),
):
    FIXTURE_CLASSES[class_name] = (source, target)


def private_json(path):
    """Read only canonical, bounded private files inside this checkout's work."""
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_relative_to(ROOT / 'work') \
            or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Private fixture files must be existing canonical files under this checkout work')
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate private configuration key')
            result[key] = value
        return result
    content = path.read_bytes()
    try:
        value = json.loads(content, object_pairs_hook=unique_keys)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError('Private fixture JSON is invalid') from None
    if not isinstance(value, dict):
        raise ValueError('Private fixture JSON must contain an object')
    return path, value, hashlib.sha256(content).hexdigest()


def java_classes(value):
    values = value.split(',') if isinstance(value, str) else value
    if not isinstance(values, list) or not values or len(values) > 100 \
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*', name)
                   for name in values) or len(set(values)) != len(values):
        raise ValueError('Select unique, explicit comma-separated Java class names without patterns')
    return values


def admit_fixture_suite(selected, properties, identity):
    """Admit one independently provisioned suite; never construct global -D overrides."""
    if not selected or set(properties) - FIXTURE_SCHEMAS.keys():
        raise ValueError('Fixture execution requires explicit classes and allowlisted properties')
    expected = set()
    for name in selected:
        required = FIXTURE_CLASSES.get(name.rsplit('.', 1)[-1])
        if required is None or not set(required).issubset(properties):
            raise ValueError('Selected fixture class has no audited matching configuration: ' + name)
        expected.update(required)
    if set(properties) != expected:
        raise ValueError('Fixture properties must exactly match the selected audited Java scope')
    configs, arguments, inputs = {}, [], {}
    for key, file in properties.items():
        if not isinstance(file, str) or not file:
            raise ValueError('Fixture properties must contain absolute private JSON paths')
        path, config, digest = private_json(file)
        prefix, account_prefix = FIXTURE_SCHEMAS[key]
        digits = 12 if prefix == 'doorhandle_feature_' else 10
        database = config.get('database')
        port = config.get('port')
        if config.get('scope') != 'ecs-disposable-mysql' \
                or any(config.get(name) != identity[name] for name in ('instanceId', 'machineId')) \
                or not isinstance(database, str) or not re.fullmatch(prefix + r'[a-f0-9]{' + str(digits) + '}', database) \
                or config.get('username') != account_prefix + database[len(prefix):] \
                or type(port) is not int or not 1024 < port <= 65535 or port == 3306 \
                or not isinstance(config.get('password'), str) or not config['password'].strip() \
                or not isinstance(config.get('serverUuid'), str) \
                or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', config['serverUuid']):
            raise ValueError('Fixture metadata differs from the admitted disposable ECS schema: ' + key)
        expected_url = (f'jdbc:mysql://127.0.0.1:{port}/{database}'
                        '?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai')
        if config.get('url') != expected_url or not isinstance(config.get('dataDirectory'), str):
            raise ValueError('Fixture JDBC identity or data directory is invalid: ' + key)
        data = Path(config['dataDirectory'])
        if not data.is_absolute() or data.resolve(strict=True) != data or not data.is_dir() \
                or not data.is_relative_to(path.parent):
            raise ValueError('Fixture data directory must belong to its private attempt: ' + key)
        configs[key] = config
        inputs[str(path)] = digest
        arguments.append('-D' + key + '=' + str(path))
    for source, target, strict in MIGRATION_PAIRS:
        if source in configs or (strict and target in configs):
            if source not in configs or target not in configs:
                raise ValueError('Migration source and target configurations must be supplied together')
            left, right = configs[source], configs[target]
            if left['database'] == right['database'] or any(left[name] != right[name]
                    for name in ('serverUuid', 'port', 'dataDirectory')):
                raise ValueError('Migration requires distinct schemas on the same disposable ECS MySQL server')
    switches = set()
    for name in selected:
        switch = SERVER_SWITCHES.get(name.rsplit('.', 1)[-1])
        if switch:
            switches.add(switch)
    if 'workbench.mysql.config' in configs:
        switches.add('workbench.mysql')
    if 'agent.journal.mysql-file' in configs:
        switches.add('agent.journal.mysql')
    arguments += ['-D' + name + '=true' for name in sorted(switches)]
    return arguments, configs, inputs


def fixture_arguments(args, identity):
    """Admit every v1/v2 suite and its storage boundary before starting any test."""
    manifest_receipt = None
    args.compact_migration_config = None
    args.compact_migration_config_sha256 = None
    args.worker_mysql_config = None
    args.worker_mysql_config_sha256 = None
    args.source_regression = False
    args.java_suites = []
    if args.fixture_manifest:
        if args.java_tests or args.fixture_property or args.java_only:
            raise ValueError('Fixture manifest cannot be combined with Java scope or fixture CLI overrides')
        _, manifest, digest = private_json(args.fixture_manifest)
        version = manifest.get('version')
        if type(version) is not int or version not in (1, 2) or type(manifest.get('javaOnly', False)) is not bool:
            raise ValueError('Fixture manifest requires version=1 or version=2 and documented fields')
        if version == 1:
            if set(manifest) - {'version', 'javaTests', 'fixtureProperties', 'javaOnly', 'migrationConfig'}:
                raise ValueError('Fixture manifest version=1 contains undocumented fields')
            suites = [{'javaTests': manifest.get('javaTests'), 'fixtureProperties': manifest.get('fixtureProperties')}]
            migration = manifest.get('migrationConfig')
        else:
            if set(manifest) - {'version', 'javaSuites', 'javaOnly', 'wholeMigrationConfig', 'workerMysqlConfig', 'sourceRegression'}:
                raise ValueError('Fixture manifest version=2 contains undocumented fields')
            if type(manifest.get('sourceRegression', False)) is not bool:
                raise ValueError('sourceRegression must be an explicit boolean')
            args.source_regression = manifest.get('sourceRegression', False)
            suites = manifest.get('javaSuites')
            if not isinstance(suites, list) or not 1 <= len(suites) <= 100:
                raise ValueError('Fixture manifest version=2 requires one to 100 explicit javaSuites')
            migration = manifest.get('wholeMigrationConfig')
            worker = manifest.get('workerMysqlConfig')
            if worker is not None:
                if manifest.get('javaOnly', False):
                    raise ValueError('Worker MySQL acceptance requires Python execution, not javaOnly')
                path, config, worker_digest = private_json(worker)
                specification = importlib.util.spec_from_file_location('admitted_worker_fixture', WORKER_FIXTURE_HELPER)
                helper = importlib.util.module_from_spec(specification)
                specification.loader.exec_module(helper)
                if helper.read_mysql_fixture(str(path), ROOT, identity) != config:
                    raise ValueError('Worker fixture configuration changed during admission')
                args.worker_mysql_config, args.worker_mysql_config_sha256 = str(path), worker_digest
        args.java_only = manifest.get('javaOnly', False)
        if migration is not None:
            if args.java_only:
                raise ValueError('Whole migration acceptance requires Python execution, not javaOnly')
            _, _, args.compact_migration_config_sha256 = private_json(migration)
            args.compact_migration_config = migration
        manifest_receipt = {'version': version, 'sha256': digest}
    else:
        properties = {}
        for value in args.fixture_property:
            key, separator, file = value.partition('=')
            if not separator or key in properties:
                raise ValueError('Fixture properties must have unique KEY=ABSOLUTE_JSON entries')
            properties[key] = file
        suites = [{'javaTests': java_classes(args.java_tests) if args.java_tests else [], 'fixtureProperties': properties}]
    selected, arguments, all_configs = [], [], []
    seen_classes, seen_inputs, seen_schemas = set(), set(), set()
    for index, suite in enumerate(suites, 1):
        if not isinstance(suite, dict) or set(suite) != {'javaTests', 'fixtureProperties'}:
            raise ValueError('Each javaSuite requires only javaTests and fixtureProperties')
        if args.fixture_manifest and not isinstance(suite['javaTests'], list):
            raise ValueError('Manifest javaTests must be an explicit class list')
        classes = java_classes(suite['javaTests']) if suite['javaTests'] else []
        properties = suite['fixtureProperties']
        if not isinstance(properties, dict) or (args.fixture_manifest and not properties):
            raise ValueError('Fixture manifest requires explicit fixtureProperties for every suite')
        if args.fixture_manifest and not classes:
            raise ValueError('Fixture manifest requires explicit classes for every suite')
        aliases = {name.rsplit('.', 1)[-1] for name in classes}
        if len(aliases) != len(classes) or aliases & seen_classes:
            raise ValueError('Java classes must be globally unique across suites, including simple/FQN aliases')
        if properties:
            options, configs, inputs = admit_fixture_suite(classes, properties, identity)
        else:
            options, configs, inputs = [], {}, {}
        schemas = {(config['serverUuid'], config['database']) for config in configs.values()}
        if len(inputs) != len(configs) or len(schemas) != len(configs) \
                or set(inputs) & seen_inputs or schemas & seen_schemas:
            raise ValueError('Different Java suites must use distinct private inputs and disposable schemas')
        seen_classes.update(aliases); seen_inputs.update(inputs); seen_schemas.update(schemas)
        all_configs.extend(configs.values()); arguments.extend(options); selected.extend(classes)
        if len(selected) > 100:
            raise ValueError('The complete verification plan exceeds 100 selected Java classes')
        args.java_suites.append({'id': 'suite-' + str(index).zfill(3), 'javaSelection': classes,
                                'fixtureProperties': sorted(properties), 'fixtureOptions': options, 'privateInputs': inputs})
    args.java_tests = ','.join(selected) if selected else None
    if args.compact_migration_config:
        sys.path.insert(0, str(ROOT / 'script/schema'))
        from compact_migration_runtime import load_config
        migration, actual_identity, _ = load_config(Path(args.compact_migration_config))
        connection = migration['connection']
        if migration['scope'] != 'ecs-disposable-migration' or actual_identity != identity \
                or not any(config['serverUuid'] == migration['serverUuid'] and config['port'] == connection['port']
                           and config['dataDirectory'] == migration.get('dataDirectory') for config in all_configs):
            raise ValueError('Whole migration acceptance must use the same explicitly admitted disposable MySQL server and storage')
        occupied = {config['database'] for config in all_configs if config['serverUuid'] == migration['serverUuid']}
        if occupied & {migration['sourceSchema'], migration['targetSchema'], *migration['recoverySchemas'].values()}:
            raise ValueError('Whole migration schemas must be distinct from every Java fixture schema')
    if args.worker_mysql_config:
        _, worker, _ = private_json(args.worker_mysql_config)
        if (worker['serverUuid'], worker['database']) in seen_schemas or args.worker_mysql_config in seen_inputs:
            raise ValueError('Worker MySQL acceptance must use its own independent schema and private input')
    return arguments, selected, manifest_receipt


def empty_counts():
    return {'found': 0, 'passed': 0, 'failed': 0, 'skipped': 0}


def require_unchanged_inputs(inputs):
    for file, expected in inputs.items():
        if private_json(file)[2] != expected:
            raise ValueError('A private fixture input changed after whole-plan admission')


def archive_java_reports(build_root, destination_root, output):
    """Keep original Surefire XML bytes; a collision is never overwritten or renamed."""
    catalog = []
    for report in sorted(build_root.glob('*/surefire-reports/TEST-*.xml')):
        if not report.is_file() or report.is_symlink() or report.resolve(strict=True) != report \
                or not report.is_relative_to(build_root) or report.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Original Java report is not a bounded regular owned file')
        relative = report.relative_to(build_root)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/surefire-reports/TEST-[A-Za-z0-9_.$-]+\.xml', relative.as_posix()):
            raise ValueError('Original Java report has an unexpected path')
        destination = destination_root / relative
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with report.open('rb') as source, destination.open('xb') as target:
            os.chmod(destination, 0o600)
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block); target.write(block)
        catalog.append({'path': destination.relative_to(output).as_posix(), 'bytes': destination.stat().st_size,
                        'sha256': digest.hexdigest()})
    return catalog


def java_report_counts(output, catalog, selected):
    counts = empty_counts()
    requested_counts = {name: empty_counts() for name in selected}
    for descriptor in catalog:
        report = output / descriptor['path']
        root = ET.parse(report).getroot()
        for case in root.iter('testcase'):
            result = 'skipped' if case.find('skipped') is not None else 'failed' if (
                case.find('failure') is not None or case.find('error') is not None) else 'passed'
            counts['found'] += 1; counts[result] += 1
            actual = case.get('classname') or root.get('name', '')
            for requested, tally in requested_counts.items():
                compared = actual if '.' in requested else actual.rsplit('.', 1)[-1]
                if compared == requested or compared.startswith(requested + '$'):
                    tally['found'] += 1; tally[result] += 1
    return counts, requested_counts


def require_java_pass(counts, selected, *, fixture):
    if counts['passed'] == 0 or counts['failed'] or (fixture and counts['skipped']) \
            or any(not tally['passed'] or tally['failed'] or (fixture and tally['skipped']) for tally in selected.values()) \
            or (fixture and sum(tally['found'] for tally in selected.values()) != counts['found']):
        raise RuntimeError('The selected Java suite did not execute successfully; inspect its original Surefire reports')


class VerificationCommandFailure(RuntimeError):
    """A real child exit, distinct from interruption or executor admission errors."""
    def __init__(self, label, exit_code):
        super().__init__(label + ' failed; original log preserved')
        self.label, self.exit_code = label, exit_code


def require_complete_assertion_reports(output, entry, profile, *, require_failure=True):
    """Complete native XML; the failure path additionally requires assertions."""
    selected = entry['javaSelection']; catalog = entry['reportFiles']
    if not selected or len(set(selected)) != len(selected) or not catalog:
        raise ValueError('Assertion continuation requires every selected original Java report')
    counts, classes = empty_counts(), {name: empty_counts() for name in selected}
    seen = set()
    assertion_types = {'java.lang.AssertionError', 'org.opentest4j.AssertionFailedError',
                       'org.opentest4j.MultipleFailuresError'}
    for binding in catalog:
        path = output / binding['path']
        if binding['path'] in seen or not path.is_file() or path.is_symlink() or path.resolve(strict=True) != path \
                or not path.is_relative_to(output) or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Assertion continuation original Java report is missing or redirected')
        seen.add(binding['path']); raw = path.read_bytes()
        if len(raw) != binding['bytes'] or hashlib.sha256(raw).hexdigest() != binding['sha256'] \
                or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('Assertion continuation original Java report bytes differ')
        root = ET.fromstring(raw)
        if next(root.iter('error'), None) is not None or next(root.iter('skipped'), None) is not None \
                or any(node.get(key, '0') != '0' for node in root.iter('testsuite') for key in ('errors', 'skipped')):
            raise ValueError('Lifecycle, skipped or global Java errors prevent assertion continuation')
        for case in root.iter('testcase'):
            name = case.get('classname') or root.get('name', '')
            matches = [requested for requested in selected if name == requested or name.startswith(requested + '$')]
            failure = case.findall('failure')
            if len(matches) != 1 or not case.get('name', '').strip() or case.find('error') is not None \
                    or case.find('skipped') is not None or len(failure) > 1 \
                    or (failure and failure[0].get('type') not in assertion_types):
                raise ValueError('Only complete assertion failures may continue native Java groups')
            result = 'failed' if failure else 'passed'
            for target in (counts, classes[matches[0]]):
                target['found'] += 1; target[result] += 1
    if (not counts['failed'] if require_failure else bool(counts['failed'])) \
            or counts != entry['javaTests'] or classes != entry['selectedJavaClasses']:
        raise ValueError('Assertion continuation original Java counts differ')
    for name, tally in classes.items():
        required = [row for row in profile['javaSuites'] if row['className'] == name]
        if len(required) != 1 or type(required[0]['minimumTests']) is not int or required[0]['minimumTests'] <= 0 \
                or tally['found'] < required[0]['minimumTests']:
            raise ValueError('Assertion continuation omitted a selected native Java class or testcase')


def assertion_tool_cleanup(runtime, value, expected_sha, command):
    """Bind exit=1 to the original OCI command, including successful safety cleanup."""
    if not command or command[0] != str(Path(value['directory']) / 'mvn'):
        raise ValueError('Only this admitted Maven command may continue after assertions')
    stopped = runtime.cleanup(value)
    proof = runtime.evidence(value, stopped)
    arguments_sha = hashlib.sha256(json.dumps(command[1:], ensure_ascii=True).encode()).hexdigest()
    matches = [row for row in proof['commands'] if row['tool'] == 'mvn' and row['argumentsSha256'] == arguments_sha]
    if stopped.get('status') != 'STOPPED' or stopped.get('remaining') != [] \
            or stopped.get('manifestSha256') != expected_sha or proof.get('manifestSha256') != expected_sha or len(matches) != 1:
        raise ValueError('Assertion continuation lacks unchanged tool admission and owned cleanup')
    record = matches[0]; cleaned = record.get('cleanup') or {}; monitoring = record.get('resourceMonitoring') or {}
    if record.get('status') != 'EXITED' or type(record.get('exitCode')) is not int or record['exitCode'] != 1 \
            or record.get('resourceLimitTriggered') is not False or cleaned.get('removed') is not True \
            or type(cleaned.get('pid')) is not int or cleaned['pid'] != 0 \
            or type(cleaned.get('exitCode')) is not int or cleaned['exitCode'] != 1 \
            or (record.get('mavenDependencyCache') or {}).get('status') != 'READY' \
            or monitoring.get('capacityVerdict') != 'CONTROLLED_MEASUREMENT' \
            or monitoring.get('diskFloorBytes') != runtime.DISK_FLOOR \
            or monitoring.get('memoryFloorBytes') != runtime.MEMORY_FLOOR \
            or type(monitoring.get('samples')) is not int or monitoring['samples'] < 1 \
            or any(type(monitoring.get(key)) is not int or monitoring[key] < minimum for key, minimum in (
                ('minimumDiskAvailableBytes', runtime.DISK_FLOOR), ('minimumMemoryAvailableBytes', runtime.MEMORY_FLOOR))):
        raise ValueError('Assertion continuation cannot hide an executor, resource, OOM or cache failure')
    return {'cleanup': stopped, 'command': record}


def assertion_command_log(output, label):
    path = output / (label + '.log')
    if not path.is_file() or path.is_symlink() or path.resolve(strict=True) != path \
            or not path.is_relative_to(output) or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError('Assertion continuation requires its bounded original command log')
    raw = path.read_bytes()
    # A servlet can turn a JVM heap/resource error into a plain HTTP assertion;
    # Docker OOMKilled and the host memory floor cannot alone exclude that path.
    if re.search(rb'OutOfMemoryError|Java heap space|Could not reserve enough space|unable to create native thread|'
                 rb'There was an error in the forked process|Process Exit Code:\s*137|forked VM terminated|'
                 rb'VM crash|Crashed tests:|hs_err_pid|FATAL ERROR in native method|SIGSEGV|SIGABRT|'
                 rb'A fatal error has been detected', raw, re.I):
        raise ValueError('JVM or forked-process resource failure prevents assertion continuation')
    return {'file': path.relative_to(output).as_posix(), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def continue_native_assertions(suite, entry, profile, output, build_root, source_inputs, compiled_outputs,
                               command, error, cleanup_command):
    if type(error) is not VerificationCommandFailure or type(error.exit_code) is not int or error.exit_code != 1 \
            or error.label != suite.get('commandLabel', 'java-' + suite['id']) or not suite['fixtureProperties'] \
            or compiled_outputs is None or source_inputs is None or not callable(cleanup_command):
        raise error
    require_complete_assertion_reports(output, entry, profile)
    original_log = assertion_command_log(output, error.label)
    def unchanged():
        require_unchanged_inputs(suite.get('privateInputs', {}))
        if java_source_inventory(ROOT) != source_inputs or java_compiled_inventory(build_root, output) != compiled_outputs:
            raise ValueError('Assertion continuation source, private inputs or compiled Java bytes changed')
    unchanged()
    proof = cleanup_command(command)
    if type(proof) is not dict or (proof.get('cleanup') or {}).get('status') != 'STOPPED' \
            or (proof.get('cleanup') or {}).get('remaining') != []:
        raise ValueError('Assertion continuation requires confirmed owned-tool cleanup')
    unchanged()
    require_complete_assertion_reports(output, entry, profile)
    if assertion_command_log(output, error.label) != original_log:
        raise ValueError('Original Maven command log changed during assertion admission')
    entry.update(status='FAILED', assertionContinuation=proof, failureKind='COMPLETE_ASSERTION_FAILURES',
        assertionCommandLog=original_log,
        compiledBytesSha256=hashlib.sha256(json.dumps(compiled_outputs, sort_keys=True).encode()).hexdigest(),
        sourceInputsSha256=hashlib.sha256(json.dumps(source_inputs, sort_keys=True).encode()).hexdigest())
    entry['reportOutputCleanup'] = clear_java_reports(build_root, output)
    require_java_reuse(build_root, output, source_inputs, compiled_outputs)
    return False


def run_native_java_groups(suites, run_java, receipt):
    failed = []
    for suite in suites:
        outcome = run_java(suite)
        if type(outcome) is not bool:
            raise ValueError('A native Java group has no explicit verified outcome')
        if outcome is False:
            failed.append(suite['id'])
            receipt['nativeAssertionFailures'] = list(failed)
    if failed:
        raise RuntimeError('Native Java assertion failures were collected; all later verification remains blocked')


def aggregate_java_suites(suites):
    counts, selected, reports = empty_counts(), {}, []
    for suite in suites:
        for key in counts:
            counts[key] += suite.get('javaTests', {}).get(key, 0)
        for name, tally in suite.get('selectedJavaClasses', {}).items():
            if name in selected:
                raise ValueError('A Java class was reported by more than its admitted suite')
            selected[name] = tally
        reports.extend(suite.get('reportFiles', []))
    return counts, selected, reports


def acceptance_profile():
    path = ROOT / 'script/jenkins/compact-acceptance.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError('The fixed-source compact acceptance profile is missing or unbounded')
    raw = path.read_bytes()
    profile = json.loads(raw)
    if profile.get('schemaVersion') != 1 or profile.get('kind') != 'doorhandle-compact-acceptance-profile':
        raise ValueError('The fixed-source compact acceptance profile is unsupported')
    return profile, hashlib.sha256(raw).hexdigest()


def python_report_counts(path):
    counts, modules = empty_counts(), {}
    for case in ET.parse(path).getroot().iter('testcase'):
        name = case.get('classname', '')
        # pytest JUnit emits the module followed by any containing test class.
        match = re.match(r'(?:tests_python\.)?(test_[A-Za-z0-9_]+)(?:\.|$)', name)
        if not match:
            raise ValueError('A Python testcase has no explicit source test module')
        tally = modules.setdefault('tests_python.' + match.group(1), empty_counts())
        result = 'skipped' if case.find('skipped') is not None else 'failed' if (
            case.find('failure') is not None or case.find('error') is not None) else 'passed'
        for destination in (counts, tally):
            destination['found'] += 1; destination[result] += 1
    if counts['passed'] == 0 or counts['failed']:
        raise RuntimeError('Python verification did not record actual passing testcases')
    return counts, modules


def frontend_test_files(profile, directory):
    matches = [item for item in profile.get('frontends', []) if item.get('directory') == directory]
    if len(matches) != 1:
        raise ValueError('A frontend has no unique fixed-source acceptance profile')
    files = matches[0].get('testFiles')
    if not isinstance(files, list) or not files or len(set(files)) != len(files):
        raise ValueError('Frontend acceptance requires explicit unique test files')
    root = ROOT / directory
    for name in files:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+\.(?:cjs|mjs|js)', name) \
                or name.startswith('/') or '..' in Path(name).parts or 'node_modules' in Path(name).parts:
            raise ValueError('A frontend test path is not a source file')
        path = root / name
        if path.resolve(strict=True) != path or not path.is_file():
            raise ValueError('A selected frontend test file is missing or redirected')
    return files


def node_tap_counts(path):
    text = path.read_text(encoding='utf8')
    values = {}
    for key in ('tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'):
        rows = re.findall(r'^# ' + key + r' ([0-9]+)\s*$', text, re.M)
        if len(rows) != 1:
            raise ValueError('Node TAP did not produce one complete final testcase tally')
        values[key] = int(rows[0])
    if values['tests'] == 0 or values['pass'] == 0 or values['tests'] != sum(values[key] for key in ('pass', 'fail', 'cancelled', 'skipped', 'todo')):
        raise ValueError('Node TAP testcase totals are empty or inconsistent')
    return {'found': values['tests'], 'passed': values['pass'], 'failed': values['fail'] + values['cancelled'],
            'skipped': values['skipped'] + values['todo']}


def admitted_tool_executables(manifest, expected_sha, identity):
    """Bind tool paths to the outer verifier's admitted manifest and this checkout."""
    if not expected_sha or not re.fullmatch(r'[a-f0-9]{64}', expected_sha):
        raise ValueError('Tool registration requires its admitted manifest digest')
    spec = importlib.util.spec_from_file_location('ecs_verifier_tool_runtime', ROOT / 'script/jenkins/ecs-tool-runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    value = runtime.private_json(manifest)
    if runtime.digest(manifest) != expected_sha or ROOT.name != 'checkout' or ROOT.parent.parent.name != 'verification':
        raise ValueError('Tool registration differs from the outer fixed-source admission')
    value, actual_sha = runtime.admit(manifest, root=ROOT.parents[2], tag=ROOT.parent.name,
        commit=value['commit'], source_sha=value['sourceSha256'], identity=identity, source=ROOT)
    tools = {key: str(Path(value['directory']) / binary) for key, binary in (
        ('MAVEN_CMD', 'mvn'), ('PYTHON_EXE', 'python'), ('NODE_EXE', 'node'), ('NPM_CMD', 'npm'))}
    cache = runtime.registered_maven_cache(value)
    tools['MAVEN_REPOSITORY'] = cache['repository']
    tools['_cleanup_owned_tools'] = lambda: runtime.cleanup(value)
    tools['_assertion_failure_cleanup'] = lambda command: assertion_tool_cleanup(runtime, value, actual_sha, command)
    # This is the immutable executor identity checked exactly by verify-remote.
    # Shared dependency usage belongs to each command's tool evidence instead.
    return tools, {'manifestSha256': actual_sha, 'images': value['images']}


def owned_directory(path, parent):
    path, parent = Path(path), Path(parent)
    if not path.is_absolute() or path == parent or not path.is_relative_to(parent) \
            or path.resolve(strict=True) != path or parent.resolve(strict=True) != parent \
            or not path.is_dir() or path.stat().st_uid != os.getuid() or parent.stat().st_uid != os.getuid():
        raise ValueError('Build cleanup requires this attempt owned directory without redirected parents')
    return path


def tree_inventory(path, *, allow_links=False, hash_files=False):
    """Never follow package-manager symlinks while measuring an owned output."""
    files, size, links = 0, 0, 0
    binding = hashlib.sha256()
    for current, directories, names in os.walk(path, followlinks=False):
        for name in sorted(directories + names):
            entry = Path(current) / name
            if entry.is_symlink():
                if not allow_links:
                    raise ValueError('Java/output inventory cannot contain symbolic links')
                links += 1
                continue
            if entry.is_file():
                length = entry.stat().st_size
                files += 1; size += length
                if hash_files:
                    checksum = hashlib.sha256()
                    with entry.open('rb') as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            checksum.update(block)
                    binding.update(json.dumps([entry.relative_to(path).as_posix(), length, checksum.hexdigest()],
                                              ensure_ascii=True, separators=(',', ':')).encode() + b'\n')
        directories.sort()
    result = {'files': files, 'bytes': size, 'links': links}
    if hash_files:
        result['sha256'] = binding.hexdigest()
    return result


def remove_owned_build(path, parent, *, allow_links=False):
    path = owned_directory(path, parent)
    result = tree_inventory(path, allow_links=allow_links)
    # rmtree unlinks nested node_modules/.bin links without following their targets.
    # The admitted top-level directory and every parent remain real owned paths.
    shutil.rmtree(path)
    if path.exists() or path.is_symlink():
        raise RuntimeError('Owned build output remains after cleanup')
    return {'status': 'REMOVED', 'relativePath': path.relative_to(ROOT).as_posix(), **result}


def java_source_inventory(root):
    """Bind reusable compilation to the same reactor POMs, sources and resources."""
    root = Path(root)
    pom = root / 'pom.xml'
    if pom.resolve(strict=True) != pom or pom.is_symlink():
        raise ValueError('Java reactor source must be canonical')
    modules = [node.text for node in ET.parse(pom).findall('./{*}modules/{*}module')]
    if not modules or len(modules) != len(set(modules)) or any(
            not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..') for name in modules):
        raise ValueError('Java reuse requires the fixed explicit reactor modules')
    result = {'poms': {}, 'trees': {}}
    for name in ('', *modules):
        path = root / name / 'pom.xml'
        if path.resolve(strict=True) != path or path.is_symlink() or not path.is_file():
            raise ValueError('Java reactor POM changed or was redirected')
        result['poms'][path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in [root / name / 'src' for name in modules] + [root / '.mvn']:
        if path.exists() or path.is_symlink():
            owned_directory(path, root)
            result['trees'][path.relative_to(root).as_posix()] = tree_inventory(path, hash_files=True)
    return result


def java_compiled_inventory(build_root, output):
    """Classes and copied resources only; reports and JVM scratch are never reused."""
    build_root = owned_directory(build_root, output); result = {}
    for module in sorted(build_root.iterdir()):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', module.name):
            raise ValueError('Unexpected shared Java module output')
        owned_directory(module, build_root)
        for name in ('classes', 'test-classes'):
            path = module / name
            if path.exists() or path.is_symlink():
                owned_directory(path, build_root)
                result[path.relative_to(build_root).as_posix()] = tree_inventory(path, hash_files=True)
    if not result or not any(row['files'] for row in result.values()):
        raise ValueError('A reusable Java compilation must contain actual compiled files')
    return result


def require_java_reuse(build_root, output, expected_source, expected_compiled):
    if java_source_inventory(ROOT) != expected_source:
        raise ValueError('Fixed Java source changed before compilation reuse')
    if java_compiled_inventory(build_root, output) != expected_compiled:
        raise ValueError('Compiled Java classes or resources changed before reuse')
    if any(build_root.glob('*/surefire-reports')):
        raise ValueError('Previous Java reports must be archived and removed before another suite')


def clear_java_reports(build_root, output):
    build_root = owned_directory(build_root, output)
    return [remove_owned_build(path, build_root) for path in sorted(build_root.glob('*/surefire-reports'))]


def java_maven_arguments(suite, tools, build_root, *, initial, source_regression=False):
    arguments = [tools['MAVEN_CMD'], '-B', '-ntp', '-Ddoorhandle.isolated-verification=true',
                 '-Ddoorhandle.verification-root=' + str(build_root),
                 '-Dmaven.repo.local=' + tools.get('MAVEN_REPOSITORY', str(ROOT / 'work' / 'ecs-maven-repository'))]
    if initial:
        arguments.append('clean')
    arguments.append('test' if suite['fixtureProperties'] else 'verify')
    if suite['javaSelection'] and not source_regression:
        arguments += ['-Dtest=' + ','.join(suite['javaSelection']), '-Dsurefire.failIfNoSpecifiedTests=false']
        if suite['fixtureProperties'] and len(suite['javaSelection']) > 1:
            arguments += ['-DforkCount=1', '-DreuseForks=false', '-Djunit.jupiter.execution.parallel.enabled=false']
    arguments += suite['fixtureOptions']
    module = suite.get('mavenModule')
    if module is not None:
        if initial or source_regression or not suite['fixtureProperties'] or not isinstance(module, str) \
                or not re.fullmatch(r'[A-Za-z0-9_.-]+', module) or module in ('.', '..'):
            raise ValueError('Only a warm native command may select one explicit reactor module')
        arguments += ['-pl', module, '-am']
    return arguments


def middleware_protocol_reports(output):
    """Require the actual remote SDK/server cases, not adjacent mock tests."""
    java_name = 'com.ruanzhu.doorhandle.framework.semantic.QdrantSemanticIntegrationTest'
    java_cases = [case for file in sorted(Path(output).glob('**/surefire-reports/TEST-*.xml'))
                  for case in ET.parse(file).getroot().iter('testcase')
                  if case.get('classname') == java_name]
    python_cases = [case for case in ET.parse(Path(output) / 'python.xml').getroot().iter('testcase')
                    if case.get('classname') == 'tests_python.test_memory_qdrant'
                    and case.get('name') == 'test_real_native_qdrant_keeps_public_id_vector_direction_and_account_filters']
    for cases in (java_cases, python_cases):
        if not cases or any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped')):
            raise RuntimeError('Actual Qdrant Java/Python SDK protocol acceptance is missing, failed or skipped')
    return {'status': 'PASS', 'javaNativeCases': len(java_cases), 'pythonNativeCases': len(python_cases),
            'embeddingProfile': 'EXPLICIT_TEST_ONLY', 'providerCalls': 0, 'productionActivationVerified': False}


def observability_protocol_reports(output):
    java_name = 'com.ruanzhu.doorhandle.module.app.config.PrometheusScrapeIntegrationTest'
    java_cases = [case for file in sorted(Path(output).glob('**/surefire-reports/TEST-*.xml'))
                  for case in ET.parse(file).getroot().iter('testcase')
                  if case.get('classname') == java_name]
    python_cases = [case for case in ET.parse(Path(output) / 'python.xml').getroot().iter('testcase')
                    if case.get('classname') == 'tests_python.test_observability_scrape']
    for cases in (java_cases, python_cases):
        if not cases or any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped')):
            raise RuntimeError('Actual Prometheus Java/Python scrape cases are missing, failed or skipped')
    return {'status': 'PASS', 'javaNativeCases': len(java_cases), 'pythonNativeCases': len(python_cases),
            'langfuseRuntime': 'DEFERRED_BY_USER', 'providerCalls': 0}


def semantic_mysql_protocol_reports(output):
    name = 'com.ruanzhu.doorhandle.module.app.service.knowledge.QualityKnowledgeMySqlTest'
    # Native reports only: the ordinary source regression intentionally has no
    # SQL flags and cannot replace this explicit disposable-database suite.
    cases = [case for file in sorted((Path(output) / 'java').glob('*/surefire-reports/TEST-*.xml'))
             for case in ET.parse(file).getroot().iter('testcase') if case.get('classname') == name]
    if len(cases) < 14 or any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped')):
        raise RuntimeError('Semantic source fencing requires all 14 actual isolated MySQL cases')
    return {'status': 'PASS', 'nativeCases': len(cases), 'sourceData': 'SYNTHETIC_ONLY',
            'wholeDatabaseMigrationVerified': False}


def semantic_mysql_source_suite(args, identity):
    """Reuse native-suite + ordinary regression orchestration, without cloning old data."""
    if os.environ.get('DOORHANDLE_REQUIRE_SEMANTIC_MYSQL_TESTS') != 'true':
        return None
    if args.fixture_manifest or args.java_tests or args.java_only or args.fixture_property:
        raise ValueError('The source semantic MySQL component cannot override another explicit fixture scope')
    name = 'com.ruanzhu.doorhandle.module.app.service.knowledge.QualityKnowledgeMySqlTest'
    properties = {'doorhandle.feature.mysql.config': os.environ.get('DOORHANDLE_TEST_SEMANTIC_MYSQL_CONFIG', '')}
    options, _configs, inputs = admit_fixture_suite([name], properties, identity)
    args.java_suites = [{'id': 'suite-001', 'javaSelection': [name], 'fixtureProperties': sorted(properties),
                        'fixtureOptions': options, 'privateInputs': inputs}]
    args.source_regression = True
    return name


def native_module_parts(suite, profile, build_root, output):
    """Map each reviewed FQCN to one fixed source and its existing compiled file."""
    pom = ROOT / 'pom.xml'
    if pom.is_symlink() or pom.resolve(strict=True) != pom or not pom.is_file():
        raise ValueError('Native module commands require the unchanged canonical reactor POM')
    modules = [node.text for node in ET.parse(pom).findall('./{*}modules/{*}module')]
    if not modules or len(set(modules)) != len(modules) or any(not isinstance(name, str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..') for name in modules):
        raise ValueError('Native module commands require the explicit fixed reactor')
    artifacts = {}
    for name in modules:
        directory = owned_directory(ROOT / name, ROOT)
        pom = directory / 'pom.xml'
        if pom.is_symlink() or pom.resolve(strict=True) != pom or not pom.is_file():
            raise ValueError('Native module command POM is redirected')
        artifact = ET.parse(pom).findtext('./{*}artifactId')
        if not artifact or not re.fullmatch(r'[A-Za-z0-9_.-]+', artifact) or artifact in ('.', '..') \
                or artifact in artifacts.values():
            raise ValueError('Native module command has an ambiguous compiled artifact directory')
        artifacts[name] = artifact
    grouped = {name: [] for name in modules}
    names = java_classes(suite['javaSelection'])
    for name in names:
        if '.' not in name:
            raise ValueError('Native module commands require reviewed fully qualified class names')
        relative = Path(*name.split('.'))
        sources = [ROOT / module / 'src/test/java' / relative.with_suffix('.java') for module in modules]
        found = [path for path in sources if path.exists() or path.is_symlink()]
        requirements = [row for row in profile['javaSuites'] if row['className'] == name]
        if len(found) != 1 or len(requirements) != 1:
            raise ValueError('Native class does not map uniquely to the fixed test source')
        source = found[0]; module = source.relative_to(ROOT).parts[0]
        compiled = build_root / artifacts[module] / 'test-classes' / relative.with_suffix('.class')
        if requirements[0].get('source') != source.relative_to(ROOT).as_posix():
            raise ValueError('Native module source differs from the reviewed class profile')
        bindings = {'className': name}
        for role, file, parent, maximum in (('source', source, ROOT, 2 * 1024 * 1024),
                                          ('compiled', compiled, output, 32 * 1024 * 1024)):
            owned_directory(file.parent, parent)
            if not file.is_file() or file.is_symlink() or file.resolve(strict=True) != file \
                    or file.stat().st_uid != os.getuid() or file.stat().st_nlink != 1 \
                    or file.stat().st_mode & 0o022 or not 0 < file.stat().st_size <= maximum:
                raise ValueError('Native module source or original compiled class is missing or redirected')
            raw = file.read_bytes()
            if role == 'compiled' and (len(raw) < 10 or raw[:4] != b'\xca\xfe\xba\xbe'):
                raise ValueError('Native module selection requires an actual existing compiled Java class')
            bindings[role] = {'path': file.relative_to(parent).as_posix(), 'bytes': len(raw),
                              'sha256': hashlib.sha256(raw).hexdigest()}
        grouped[module].append(bindings)
    return [{'module': name, 'javaSelection': [row['className'] for row in grouped[name]],
             'classBindings': grouped[name]} for name in modules if grouped[name]]


def run_native_module_parts(suite, entry, parts, output, run_part, refresh_receipt):
    """Keep original outer-suite coverage while every module gets its own exit."""
    entry['moduleCommands'] = []; failed = False
    selected = [name for part in parts for name in part['javaSelection']]
    if len(selected) != len(set(selected)) or set(selected) != set(suite['javaSelection']) \
            or len({part['module'] for part in parts}) != len(parts):
        raise ValueError('Native module commands must preserve every original selected class exactly once')
    for part in parts:
        child = {**suite, 'javaSelection': part['javaSelection'], 'mavenModule': part['module']}
        observed = {key: child[key] for key in ('id', 'javaSelection', 'fixtureProperties', 'mavenModule')}
        observed.update(status='FAILED', javaTests=empty_counts(), selectedJavaClasses={}, reportFiles=[],
                        classBindings=part['classBindings'], compilationMode='SAME_ATTEMPT_COMPILED_BYTES')
        entry['moduleCommands'].append(observed)
        try:
            outcome = run_part(child, observed)
        finally:
            entry['reportFiles'].extend(observed['reportFiles'])
            entry['javaTests'], entry['selectedJavaClasses'] = java_report_counts(output, entry['reportFiles'], suite['javaSelection'])
            refresh_receipt()
        if type(outcome) is not bool:
            raise ValueError('A native module command has no explicit verified outcome')
        failed = failed or not outcome
    entry['status'] = 'FAILED' if failed else 'PASS'
    return not failed


def cleanup_source_pytest_temporary(output, receipt, *, ordinary_source, python_succeeded, stop_tools=None):
    """Release only passed source-test scratch; native migration evidence stays."""
    record = receipt['pythonTemporaryCleanup'] = {'status': 'RETAINED_NATIVE_EVIDENCE'}
    if ordinary_source is not True:
        return record
    counts = receipt.get('pythonTests', {})
    # python_report_counts folds both JUnit failure and error nodes into failed.
    if python_succeeded is not True or type(counts.get('failed')) is not int or counts['failed'] != 0 \
            or type(counts.get('passed')) is not int or counts['passed'] <= 0:
        record['status'] = 'RETAINED_PYTHON_NOT_PASSED'
        return record
    output = owned_directory(Path(output), ROOT)
    parent = owned_directory(output / 'tmp', output)
    temporary = parent / 'pytest'
    if not temporary.exists() and not temporary.is_symlink():
        record['status'] = 'ABSENT'
        return record
    record['status'] = 'RETAINED_UNCONFIRMED_TOOLS'
    if stop_tools is None:
        return record
    try:
        stopped = stop_tools()
        if stopped.get('status') != 'STOPPED' or stopped.get('remaining') != []:
            raise RuntimeError('Owned Python tools were not stopped; temporary evidence is retained')
    except BaseException as error:
        record['errorType'] = type(error).__name__
        raise
    record['toolsStoppedBeforeCleanup'] = True
    record['status'] = 'RETAINED_CLEANUP_FAILED'
    record.update(remove_owned_build(temporary, parent, allow_links=True))
    return record


@contextmanager
def frontend_dependencies(frontend, result, *, stop_tools=None):
    if frontend not in ('frontend', 'frontend-agent'):
        raise ValueError('Only the fixed frontend dependency trees may be cleaned')
    parent = owned_directory(ROOT / frontend, ROOT)
    dependencies = parent / 'node_modules'
    if dependencies.exists() or dependencies.is_symlink():
        raise ValueError('Frontend verification requires absent dependencies in this fresh checkout')
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        if dependencies.exists() or dependencies.is_symlink():
            confirmed = stop_tools is not None
            if confirmed:
                stopped = stop_tools()
                if stopped.get('status') != 'STOPPED' or stopped.get('remaining') != []:
                    raise RuntimeError('Owned frontend tools were not stopped; dependency files are retained')
                result['toolsStoppedBeforeDependencyCleanup'] = True
            if succeeded or confirmed:
                result['dependenciesCleanup'] = remove_owned_build(dependencies, parent, allow_links=True)
            else:
                # An unregistered host command has no Docker ownership proof.
                result['dependenciesCleanup'] = {'status': 'RETAINED_UNCONFIRMED_TOOLS'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--java-tests', help='Optional explicit Surefire selection; receipt records the reduced scope')
    parser.add_argument('--java-only', action='store_true', help='Do not claim Python/frontend coverage')
    parser.add_argument('--fixture-property', action='append', default=[], metavar='KEY=ABSOLUTE_JSON',
                        help='Explicit isolated MySQL fixture property; requires an explicit Java class selection')
    parser.add_argument('--fixture-manifest', type=Path,
                        help='Private version=1 or version=2 JSON under this checkout work; defines isolated Java suites')
    parser.add_argument('--tool-manifest', type=Path, help='Fixed-build temporary ECS tool registration')
    parser.add_argument('--tool-manifest-sha256', help='Manifest digest admitted by the outer fixed-source verifier')
    args = parser.parse_args()
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt('ECS verification interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    identity = require_ecs_execution()
    if identity['instanceId'] != 'i-2zeieuov2aum486jm1ek':
        raise RuntimeError('Monolith verification is restricted to the ECS identified as 172.29.146.74')
    if (ROOT / 'deploy/cloud.env').exists() or ROOT == Path('/home/ecs-user/doorhandle-release-20261014') \
            or ROOT.is_relative_to(Path('/home/ecs-user/doorhandle-ci/releases')):
        raise RuntimeError('Verification requires a separate checkout, never the existing deployment runtime')
    fixture_options, selected_classes, manifest_receipt = fixture_arguments(args, identity)
    semantic_mysql_class = semantic_mysql_source_suite(args, identity)
    if semantic_mysql_class is not None:
        selected_classes = [semantic_mysql_class]
    profile, profile_sha = acceptance_profile()
    output = args.output or ROOT / 'work' / ('ecs-ci-' + uuid.uuid4().hex)
    if not output.is_absolute() or output.resolve() != output or not output.is_relative_to(ROOT / 'work'):
        raise ValueError('A fresh absolute output under this checkout work directory is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    (output / 'tmp').mkdir()
    (output / 'profile').mkdir()
    tools, tool_receipt = {}, None
    if args.tool_manifest:
        tools, tool_receipt = admitted_tool_executables(args.tool_manifest, args.tool_manifest_sha256, identity)
    elif args.tool_manifest_sha256:
        raise ValueError('A tool manifest digest requires its explicit registered path')
    requested_tools = [('MAVEN_CMD', 'mvn')]
    if not args.java_only:
        requested_tools += [('PYTHON_EXE', 'python3'), ('NODE_EXE', 'node'), ('NPM_CMD', 'npm')]
    for key, binary in requested_tools:
        if key in tools:
            continue
        value = os.environ.get(key) or shutil.which(binary)
        if not value or not Path(value).is_absolute() or not Path(value).is_file():
            raise ValueError('Configure an existing absolute ECS executable: ' + key)
        tools[key] = value
    # No production database/model environment or implicit user profile enters verification.
    env = {name: value for name, value in os.environ.items()
           if name in ('PATH', 'JAVA_HOME', 'LANG', 'LC_ALL', 'DOORHANDLE_ECS_INSTANCE_ID', 'DOORHANDLE_ECS_MACHINE_ID',
               'DOORHANDLE_TEST_QDRANT_HOST', 'DOORHANDLE_TEST_QDRANT_PORT', 'DOORHANDLE_TEST_QDRANT_GRPC_PORT',
               'DOORHANDLE_TEST_QDRANT_KEY_FILE', 'DOORHANDLE_TEST_QDRANT_TLS', 'DOORHANDLE_REQUIRE_QDRANT_TESTS',
               'DOORHANDLE_TEST_PROMETHEUS_URL', 'DOORHANDLE_TEST_ALERTMANAGER_URL',
               'DOORHANDLE_TEST_OBSERVABILITY_TARGETS', 'DOORHANDLE_TEST_OBSERVABILITY_TOKEN_FILE',
               'DOORHANDLE_REQUIRE_OBSERVABILITY_TESTS', 'DOORHANDLE_TEST_SEMANTIC_MYSQL_CONFIG',
               'DOORHANDLE_REQUIRE_SEMANTIC_MYSQL_TESTS')}
    env.update(HOME=str(output / 'profile'), TMPDIR=str(output / 'tmp'),
               JAVA_TOOL_OPTIONS='-Xmx1536m -XX:MaxMetaspaceSize=512m -XX:+ExitOnOutOfMemoryError',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHON_DOTENV_DISABLED='1',
               npm_config_cache=str(output / 'npm-cache'))
    python_env = env.copy()
    if tool_receipt is not None:
        python_env['DOORHANDLE_MIGRATION_JAVA'] = str(args.tool_manifest.parent / 'java')
    if args.compact_migration_config:
        python_env.update(DOORHANDLE_COMPACT_MIGRATION_TESTS='1',
                          DOORHANDLE_COMPACT_MIGRATION_CONFIG=args.compact_migration_config,
                          DOORHANDLE_CI_EVIDENCE_DIR=str(output))
    if args.worker_mysql_config:
        python_env.update(DOORHANDLE_WORKER_MYSQL_TESTS='1', DOORHANDLE_WORKER_MYSQL_CONFIG=args.worker_mysql_config)
    receipt = {'schemaVersion': 1, 'startedAt': datetime.now(timezone.utc).isoformat(), 'identity': identity,
               'javaSelection': args.java_tests, 'javaOnly': args.java_only, 'commands': [],
               'fixtureProperties': sorted({key for suite in args.java_suites for key in suite['fixtureProperties']}),
               'fixtureManifest': manifest_receipt,
               'acceptanceProfileSha256': profile_sha, 'javaSuites': [], 'javaReportFiles': [],
               'wholeMigrationRequested': bool(args.compact_migration_config),
               'workerMysqlRequested': bool(args.worker_mysql_config), 'workerMysqlConfigSha256': args.worker_mysql_config_sha256,
               'scopeKind': 'mysql' if fixture_options else 'source',
               'semanticMysqlComponentRequested': semantic_mysql_class is not None,
               'scope': 'explicit disposable MySQL Java scope' if fixture_options else
                        'ordinary source tests; infrastructure suites remain opt-in and skipped suites are not migration acceptance',
               'ecsLifecycle': {'managedBy': 'external-to-jenkins', 'cloudOperationsPerformed': False,
                                'note': 'Start ECS before the test window and stop it outside CI/CD after evidence collection'}}
    if tool_receipt is not None:
        receipt['toolRuntime'] = tool_receipt
    def execute(label, command, cwd, *, environment=None):
        entry = {'label': label, 'startedAt': datetime.now(timezone.utc).isoformat()}
        receipt['commands'].append(entry)
        with (output / (label + '.log')).open('xb') as log:
            process = subprocess.Popen(command, cwd=cwd, env=env if environment is None else environment, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            entry['pid'] = process.pid
            try:
                process.wait(timeout=3600)
            except BaseException as error:
                entry['interruptionType'] = type(error).__name__
                # Only the new session created above is signalled, never unrelated services.
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(timeout=10)
                raise
            finally:
                entry['exitCode'] = process.returncode
                entry['finishedAt'] = datetime.now(timezone.utc).isoformat()
        if process.returncode:
            raise VerificationCommandFailure(label, process.returncode)
    try:
        shared_build_root = None; compiled_outputs = None; source_inputs = None; java_command_number = 0
        def refresh_java_receipt():
            receipt['javaTests'], receipt['selectedJavaClasses'], receipt['javaReportFiles'] = aggregate_java_suites(receipt['javaSuites'])
        def run_java_command(suite, entry, *, initial=False, source_regression=False):
            nonlocal compiled_outputs, java_command_number
            build_root = shared_build_root
            if not initial:
                require_java_reuse(build_root, output, source_inputs, compiled_outputs)
            if source_regression:
                label = 'java-source-regression'
            else:
                java_command_number += 1
                if java_command_number > 999:
                    raise ValueError('Native Java command logs exceeded their bounded numeric namespace')
                label = 'java-suite-' + str(java_command_number).zfill(3)
            suite = {**suite, 'commandLabel': label}; entry['commandLabel'] = label
            entry['compiledBuildRoot'] = build_root.relative_to(output).as_posix()
            destination = output / ('source-regression/java' if source_regression else 'java')
            arguments = java_maven_arguments(suite, tools, build_root, initial=initial, source_regression=source_regression)
            command_failure = None
            try:
                require_unchanged_inputs(suite.get('privateInputs', {}))
                try:
                    execute(label, arguments, ROOT)
                except VerificationCommandFailure as error:
                    command_failure = error
            finally:
                entry['reportFiles'] = archive_java_reports(build_root, destination, output)
                entry['javaTests'], entry['selectedJavaClasses'] = java_report_counts(output, entry['reportFiles'], suite['javaSelection'])
                refresh_java_receipt()
            if command_failure is not None:
                if initial or source_regression:
                    raise command_failure
                return continue_native_assertions(suite, entry, profile, output, build_root, source_inputs, compiled_outputs,
                    arguments, command_failure, tools.get('_assertion_failure_cleanup'))
            require_java_pass(entry['javaTests'], entry['selectedJavaClasses'], fixture=bool(suite['fixtureProperties']))
            if suite.get('mavenModule') is not None:
                require_complete_assertion_reports(output, entry, profile, require_failure=False)
            if java_source_inventory(ROOT) != source_inputs:
                raise ValueError('Fixed Java source changed during verification')
            observed_compiled = java_compiled_inventory(build_root, output)
            if compiled_outputs is not None and observed_compiled != compiled_outputs:
                raise ValueError('Compiled Java classes or resources changed during reuse')
            compiled_outputs = observed_compiled
            entry['compiledBytesSha256'] = hashlib.sha256(json.dumps(compiled_outputs, sort_keys=True).encode()).hexdigest()
            entry['sourceInputsSha256'] = hashlib.sha256(json.dumps(source_inputs, sort_keys=True).encode()).hexdigest()
            if source_regression:
                # Opt-in infrastructure suites may skip in the ordinary reactor;
                # each explicitly audited pure-logic class must execute in full.
                for required in profile['sourceRegression']['requiredClasses']:
                    tally = entry['selectedJavaClasses'][required['className']]
                    if tally['passed'] < required['minimumTests'] or tally['skipped']:
                        raise RuntimeError('Ordinary Java regression omitted a required pure-logic class')
            entry['status'] = 'PASS'
            entry['reportOutputCleanup'] = clear_java_reports(build_root, output)
            return True
        def run_java(suite, *, source_regression=False):
            nonlocal shared_build_root, source_inputs
            initial = shared_build_root is None
            if initial:
                build_root = output / ('java-suites/' + suite['id'])
                if build_root.exists() or build_root.is_symlink():
                    raise ValueError('The shared Java compilation requires a fresh owned build output')
                build_root.mkdir(mode=0o700, parents=True); shared_build_root = build_root
                source_inputs = java_source_inventory(ROOT)
            else:
                build_root = shared_build_root
                require_java_reuse(build_root, output, source_inputs, compiled_outputs)
            entry = {key: suite[key] for key in ('id', 'javaSelection', 'fixtureProperties')}
            entry.update(status='FAILED', javaTests=empty_counts(), selectedJavaClasses={}, reportFiles=[],
                         compilationMode='FRESH_REACTOR' if initial else 'SAME_ATTEMPT_COMPILED_BYTES',
                         compiledBuildRoot=build_root.relative_to(output).as_posix())
            if source_regression:
                receipt['sourceRegression'] = entry
            else:
                receipt['javaSuites'].append(entry)
            if not initial and not source_regression and suite['fixtureProperties']:
                parts = native_module_parts(suite, profile, build_root, output)
                outcome = run_native_module_parts(suite, entry, parts, output, run_java_command, refresh_java_receipt)
                entry['compiledBytesSha256'] = hashlib.sha256(json.dumps(compiled_outputs, sort_keys=True).encode()).hexdigest()
                entry['sourceInputsSha256'] = hashlib.sha256(json.dumps(source_inputs, sort_keys=True).encode()).hexdigest()
                return outcome
            return run_java_command(suite, entry, initial=initial, source_regression=source_regression)
        run_native_java_groups(args.java_suites, run_java, receipt)
        if args.source_regression:
            required = java_classes([item['className'] for item in profile['sourceRegression']['requiredClasses']])
            run_java({'id': 'source-regression', 'javaSelection': required, 'fixtureProperties': [], 'fixtureOptions': []}, source_regression=True)
        receipt['sharedJavaBuildCleanup'] = remove_owned_build(shared_build_root, output)
        if not args.java_only:
            require_unchanged_inputs({file: digest for file, digest in (
                (args.compact_migration_config, args.compact_migration_config_sha256),
                (args.worker_mysql_config, args.worker_mysql_config_sha256)) if file})
            ordinary_source = not fixture_options and not args.fixture_manifest \
                and not args.compact_migration_config and not args.worker_mysql_config
            receipt['pythonTemporaryCleanup'] = {'status': 'RETAINED_PYTHON_NOT_PASSED' if ordinary_source else 'RETAINED_NATIVE_EVIDENCE'}
            execute('python', [tools['PYTHON_EXE'], '-B', '-m', 'pytest', 'tests_python', '-q',
                              '--basetemp=' + str(output / 'tmp' / 'pytest'), '--junitxml=' + str(output / 'python.xml')], ROOT, environment=python_env)
            receipt['pythonTests'], receipt['selectedPythonSuites'] = python_report_counts(output / 'python.xml')
            if env.get('DOORHANDLE_REQUIRE_QDRANT_TESTS') == 'true':
                receipt['middlewareProtocol'] = middleware_protocol_reports(output)
            if env.get('DOORHANDLE_REQUIRE_OBSERVABILITY_TESTS') == 'true':
                receipt['observabilityProtocol'] = observability_protocol_reports(output)
            if semantic_mysql_class is not None:
                receipt['semanticMysqlProtocol'] = semantic_mysql_protocol_reports(output)
            cleanup_source_pytest_temporary(output, receipt, ordinary_source=ordinary_source, python_succeeded=True,
                                            stop_tools=tools.get('_cleanup_owned_tools'))
            if args.worker_mysql_config:
                worker_tally = receipt['selectedPythonSuites'].get('tests_python.test_detection_worker_receipts', empty_counts())
                if not worker_tally['passed'] or worker_tally['failed'] or worker_tally['skipped']:
                    raise RuntimeError('Worker MySQL acceptance was missing, failed or skipped')
            if args.compact_migration_config:
                cases = [case for case in ET.parse(output / 'python.xml').getroot().iter('testcase')
                         if 'test_compact_migration_orchestration_ecs' in case.get('classname', '').split('.')]
                if not cases or any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped')):
                    raise RuntimeError('Whole migration acceptance was missing, failed or skipped')
                proof_file = output / 'migration.json'
                if not proof_file.is_file() or proof_file.is_symlink() or proof_file.stat().st_size > 16384:
                    raise RuntimeError('Whole migration acceptance requires its bounded public proof summary')
                proof = json.loads(proof_file.read_text(encoding='utf8'))
                expected = {'schemaVersion': 1, 'kind': 'doorhandle-compact-migration-acceptance',
                            'status': 'VERIFIED', 'sourceTableCount': 131, 'targetTableCount': 29}
                hashes = {'migrationReceiptSha256', 'sourceSnapshotSha256', 'targetSnapshotSha256',
                          'sourceRecoveryReceiptSha256', 'targetRecoveryReceiptSha256'}
                if not isinstance(proof, dict) or set(proof) != set(expected) | hashes \
                        or any(type(proof.get(key)) is not type(value) or proof[key] != value for key, value in expected.items()) \
                        or any(not isinstance(proof[key], str) or not re.fullmatch(r'[a-f0-9]{64}', proof[key]) for key in hashes):
                    raise RuntimeError('Whole migration proof summary is incomplete or contains unapproved fields')
                receipt['wholeMigrationTests'] = {'passed': len(cases), 'failed': 0, 'skipped': 0}
                receipt['wholeMigrationSummarySha256'] = hashlib.sha256(proof_file.read_bytes()).hexdigest()
            for frontend in ('frontend', 'frontend-agent'):
                frontend_result = {'selectedTestFiles': frontend_test_files(profile, frontend)}
                receipt.setdefault('frontendResults', {})[frontend] = frontend_result
                with frontend_dependencies(frontend, frontend_result, stop_tools=tools.get('_cleanup_owned_tools')):
                    execute(frontend + '-install', [tools['NPM_CMD'], 'ci', '--include=dev', '--ignore-scripts', '--no-audit', '--no-fund'], ROOT / frontend)
                    frontend_result['installExitCode'] = 0
                    execute(frontend + '-test', [tools['NODE_EXE'], '--test', '--test-reporter=tap', *frontend_result['selectedTestFiles']], ROOT / frontend)
                    frontend_result['tests'] = node_tap_counts(output / (frontend + '-test.log'))
                    frontend_result['testExitCode'] = 0
                    if frontend_result['tests']['failed'] or frontend_result['tests']['skipped']:
                        raise RuntimeError('Frontend tests failed or skipped required testcases')
                    minimum = next(item['minimumTests'] for item in profile['frontends'] if item['directory'] == frontend)
                    if frontend_result['tests']['passed'] < minimum:
                        raise RuntimeError('Frontend execution omitted required testcases from the fixed-source profile')
                    arguments = [tools['NPM_CMD'], 'run', 'build']
                    if frontend == 'frontend-agent':
                        arguments += ['--', '--base=/agent-ui/']
                    execute(frontend + '-build', arguments, ROOT / frontend)
                    frontend_result['buildExitCode'] = 0
                    distribution = owned_directory(ROOT / frontend / 'dist', ROOT / frontend)
                    frontend_result['artifact'] = tree_inventory(distribution, hash_files=True)
        receipt['status'] = 'PASS'
    except BaseException as error:
        receipt['status'] = 'FAILED'
        receipt['errorType'] = type(error).__name__
        raise
    finally:
        receipt['finishedAt'] = datetime.now(timezone.utc).isoformat()
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf8')


if __name__ == '__main__':
    with private_process_umask():
        main()
