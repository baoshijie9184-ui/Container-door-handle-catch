"""Run monolith verification on the explicitly admitted original ECS only."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
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
sys.path.insert(0, str(ROOT / 'scripts'))
from ecs_execution import require_ecs_execution


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
        'ModelBudgetMySqlTest', 'PersonalModelQuotaMySqlTest', 'QuotaAccountStoreMySqlTest')),
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
        'BusinessMutationAuditTest', 'OperationsAuditServiceTest')),
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


def fixture_arguments(args, identity):
    """Validate the entire fixture plan before a test subprocess is started."""
    manifest_receipt = None
    args.compact_migration_config = None
    if args.fixture_manifest:
        if args.java_tests or args.fixture_property or args.java_only:
            raise ValueError('Fixture manifest cannot be combined with Java scope or fixture CLI overrides')
        _, manifest, digest = private_json(args.fixture_manifest)
        if set(manifest) - {'version', 'javaTests', 'fixtureProperties', 'javaOnly', 'migrationConfig'} \
                or type(manifest.get('version')) is not int or manifest['version'] != 1 \
                or type(manifest.get('javaOnly', False)) is not bool \
                or not isinstance(manifest.get('javaTests'), list):
            raise ValueError('Fixture manifest requires version=1 and only documented fields')
        selected = java_classes(manifest.get('javaTests'))
        properties = manifest.get('fixtureProperties')
        if not isinstance(properties, dict) or not properties:
            raise ValueError('Fixture manifest requires explicit fixtureProperties')
        args.java_tests = ','.join(selected)
        args.java_only = manifest.get('javaOnly', False)
        if 'migrationConfig' in manifest:
            if args.java_only:
                raise ValueError('Whole migration acceptance requires Python execution, not javaOnly')
            private_json(manifest['migrationConfig'])
            args.compact_migration_config = manifest['migrationConfig']
        manifest_receipt = {'version': 1, 'sha256': digest}
    else:
        selected = java_classes(args.java_tests) if args.java_tests else []
        properties = {}
        for value in args.fixture_property:
            key, separator, file = value.partition('=')
            if not separator or key in properties:
                raise ValueError('Fixture properties must have unique KEY=ABSOLUTE_JSON entries')
            properties[key] = file
    if not properties:
        return [], selected, manifest_receipt
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
    configs, arguments = {}, []
    for key, file in properties.items():
        if not isinstance(file, str) or not file:
            raise ValueError('Fixture properties must contain absolute private JSON paths')
        path, config, _ = private_json(file)
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
        arguments.append('-D' + key + '=' + str(path))
    for source, target, strict in MIGRATION_PAIRS:
        if source in configs or (strict and target in configs):
            if source not in configs or target not in configs:
                raise ValueError('Migration source and target configurations must be supplied together')
            left, right = configs[source], configs[target]
            if left['database'] == right['database'] or any(left[name] != right[name]
                    for name in ('serverUuid', 'port', 'dataDirectory')):
                raise ValueError('Migration requires distinct schemas on the same disposable ECS MySQL server')
    if args.compact_migration_config:
        sys.path.insert(0, str(ROOT / 'script/schema'))
        from compact_migration_runtime import load_config
        migration, actual_identity, _ = load_config(Path(args.compact_migration_config))
        connection = migration['connection']
        if migration['scope'] != 'ecs-disposable-migration' or actual_identity != identity \
                or not any(config['serverUuid'] == migration['serverUuid'] and config['port'] == connection['port']
                           for config in configs.values()):
            raise ValueError('Whole migration acceptance must use the same explicitly admitted disposable MySQL server')
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
    return arguments, selected, manifest_receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--java-tests', help='Optional explicit Surefire selection; receipt records the reduced scope')
    parser.add_argument('--java-only', action='store_true', help='Do not claim Python/frontend coverage')
    parser.add_argument('--fixture-property', action='append', default=[], metavar='KEY=ABSOLUTE_JSON',
                        help='Explicit isolated MySQL fixture property; requires an explicit Java class selection')
    parser.add_argument('--fixture-manifest', type=Path,
                        help='Private version=1 JSON under this checkout work; defines classes and fixture properties')
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
    output = args.output or ROOT / 'work' / ('ecs-ci-' + uuid.uuid4().hex)
    if not output.is_absolute() or output.resolve() != output or not output.is_relative_to(ROOT / 'work'):
        raise ValueError('A fresh absolute output under this checkout work directory is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    (output / 'tmp').mkdir()
    (output / 'profile').mkdir()
    tools = {}
    requested_tools = [('MAVEN_CMD', 'mvn')]
    if not args.java_only:
        requested_tools += [('PYTHON_EXE', 'python3'), ('NODE_EXE', 'node'), ('NPM_CMD', 'npm')]
    for key, binary in requested_tools:
        value = os.environ.get(key) or shutil.which(binary)
        if not value or not Path(value).is_absolute() or not Path(value).is_file():
            raise ValueError('Configure an existing absolute ECS executable: ' + key)
        tools[key] = value
    # No production database/model environment or implicit user profile enters verification.
    env = {name: value for name, value in os.environ.items()
           if name in ('PATH', 'JAVA_HOME', 'LANG', 'LC_ALL', 'DOORHANDLE_ECS_INSTANCE_ID', 'DOORHANDLE_ECS_MACHINE_ID')}
    env.update(HOME=str(output / 'profile'), TMPDIR=str(output / 'tmp'),
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHON_DOTENV_DISABLED='1',
               npm_config_cache=str(output / 'npm-cache'))
    python_env = env.copy()
    if args.compact_migration_config:
        python_env.update(DOORHANDLE_COMPACT_MIGRATION_TESTS='1',
                          DOORHANDLE_COMPACT_MIGRATION_CONFIG=args.compact_migration_config,
                          DOORHANDLE_CI_EVIDENCE_DIR=str(output))
    receipt = {'schemaVersion': 1, 'startedAt': datetime.now(timezone.utc).isoformat(), 'identity': identity,
               'javaSelection': args.java_tests, 'javaOnly': args.java_only, 'commands': [],
               'fixtureProperties': [value[2:].split('=', 1)[0] for value in fixture_options if not value.endswith('=true')],
               'fixtureManifest': manifest_receipt,
               'wholeMigrationRequested': bool(args.compact_migration_config),
               'scopeKind': 'mysql' if fixture_options else 'source',
               'scope': 'explicit disposable MySQL Java scope' if fixture_options else
                        'ordinary source tests; infrastructure suites remain opt-in and skipped suites are not migration acceptance',
               'ecsLifecycle': {'managedBy': 'external-to-jenkins', 'cloudOperationsPerformed': False,
                                'note': 'Start ECS before the test window and stop it outside CI/CD after evidence collection'}}
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
            raise RuntimeError(label + ' failed; original log preserved')
    try:
        arguments = [tools['MAVEN_CMD'], '-B', '-ntp', '-Ddoorhandle.isolated-verification=true',
                     '-Ddoorhandle.verification-root=' + str(output / 'java'),
                     '-Dmaven.repo.local=' + str(ROOT / 'work' / 'ecs-maven-repository'), 'clean', 'verify']
        if args.java_tests:
            arguments += ['-Dtest=' + args.java_tests, '-Dsurefire.failIfNoSpecifiedTests=false']
        arguments += fixture_options
        execute('java', arguments, ROOT)
        counts = {'found': 0, 'passed': 0, 'failed': 0, 'skipped': 0}
        selected_counts = {name: {'found': 0, 'passed': 0, 'failed': 0, 'skipped': 0} for name in selected_classes}
        for report in (output / 'java').glob('*/surefire-reports/TEST-*.xml'):
            suite = ET.parse(report).getroot()
            for case in suite.iter('testcase'):
                counts['found'] += 1
                result = 'skipped' if case.find('skipped') is not None else 'failed' if (
                    case.find('failure') is not None or case.find('error') is not None) else 'passed'
                counts[result] += 1
                actual_class = case.get('classname') or suite.get('name', '')
                for requested, tally in selected_counts.items():
                    compared = actual_class if '.' in requested else actual_class.rsplit('.', 1)[-1]
                    if compared == requested or compared.startswith(requested + '$'):
                        tally['found'] += 1
                        tally[result] += 1
        receipt['javaTests'] = counts
        receipt['selectedJavaClasses'] = selected_counts
        if counts['passed'] == 0 or counts['failed'] or (fixture_options and counts['skipped']) \
                or any(not tally['passed'] or tally['failed'] or (fixture_options and tally['skipped'])
                       for tally in selected_counts.values()):
            raise RuntimeError('The selected Java scope did not execute successfully; inspect original Surefire reports')
        if not args.java_only:
            execute('python', [tools['PYTHON_EXE'], '-B', '-m', 'pytest', 'tests_python', '-q',
                              '--basetemp=' + str(output / 'tmp' / 'pytest'), '--junitxml=' + str(output / 'python.xml')], ROOT, environment=python_env)
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
                execute(frontend + '-install', [tools['NPM_CMD'], 'ci', '--include=dev', '--ignore-scripts', '--no-audit', '--no-fund'], ROOT / frontend)
                execute(frontend + '-test', [tools['NODE_EXE'], '--test'], ROOT / frontend)
                arguments = [tools['NPM_CMD'], 'run', 'build']
                if frontend == 'frontend-agent':
                    arguments += ['--', '--base=/agent-ui/']
                execute(frontend + '-build', arguments, ROOT / frontend)
        receipt['status'] = 'PASS'
    except BaseException as error:
        receipt['status'] = 'FAILED'
        receipt['errorType'] = type(error).__name__
        raise
    finally:
        receipt['finishedAt'] = datetime.now(timezone.utc).isoformat()
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
