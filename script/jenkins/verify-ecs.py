"""Run monolith verification on the explicitly admitted original ECS only."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--java-tests', help='Optional explicit Surefire selection; receipt records the reduced scope')
    parser.add_argument('--java-only', action='store_true', help='Do not claim Python/frontend coverage')
    parser.add_argument('--fixture-property', action='append', default=[], metavar='KEY=ABSOLUTE_JSON',
                        help='Explicit isolated MySQL fixture property; requires an explicit Java class selection')
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
    receipt = {'startedAt': datetime.now(timezone.utc).isoformat(), 'identity': identity,
               'javaSelection': args.java_tests, 'javaOnly': args.java_only, 'commands': [],
               'fixtureProperties': [], 'scope': 'ordinary source tests; infrastructure suites remain opt-in unless fixture properties are supplied',
               'cloudStopRequiredAfterControllerCollectsEvidence': True}
    def execute(label, command, cwd):
        entry = {'label': label, 'startedAt': datetime.now(timezone.utc).isoformat()}
        receipt['commands'].append(entry)
        with (output / (label + '.log')).open('xb') as log:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
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
        allowed_files = {'doorhandle.ecs.mysql.config', 'doorhandle.feature.mysql.config', 'workbench.mysql.config', 'agent.model-config.mysql-file',
                         'agent.skill.mysql-file', 'agent.journal.mysql-file', 'detection.command.mysql-file'}
        server_switches = {'EcsMysqlFixtureTest': 'ecs.fixture.mysql', 'AgentCardsLocalMysqlTest': 'agent.cards.local.mysql',
            'AgentConfirmationLocalMysqlTest': 'agent.actions.local.mysql', 'AgentReportLocalMysqlTest': 'agent.report.local.mysql',
            'AgentSessionLocalMysqlTest': 'agent.sessions.local.mysql', 'DetectionScopeLocalMysqlTest': 'detection.scope.local.mysql',
            'LocalMcpMysqlTest': 'agent.local.mcp.mysql', 'MemoryGovernanceLocalMysqlTest': 'agent.memory.local.mysql',
            'ReportEventLocalMysqlTest': 'report.events.local.mysql', 'SkillCommandLocalMysqlTest': 'agent.skills.commands.mysql',
            'SkillEvolutionLocalMysqlTest': 'agent.skills.local.mysql', 'ModelFactsMySqlTest': 'model.facts.mysql'}
        for value in args.fixture_property:
            if not args.java_tests or not re.fullmatch(r'[A-Za-z0-9_.$]+(?:,[A-Za-z0-9_.$]+)*', args.java_tests):
                raise ValueError('Fixture execution requires explicit comma-separated Java class names')
            key, separator, file = value.partition('=')
            if not separator or key not in allowed_files:
                raise ValueError('Unsupported fixture property')
            path = Path(file)
            if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_relative_to(ROOT / 'work'):
                raise ValueError('Fixture must be an explicit existing file in this isolated checkout work directory')
            config = json.loads(path.read_text())
            if config.get('scope') != 'ecs-disposable-mysql' or any(config.get(name) != identity[name] for name in ('instanceId', 'machineId')):
                raise ValueError('Fixture is not bound to this ECS execution host')
            arguments.append('-D' + key + '=' + str(path))
            receipt['fixtureProperties'].append(key)
            if key == 'workbench.mysql.config': arguments.append('-Dworkbench.mysql=true')
            if key == 'agent.journal.mysql-file': arguments.append('-Dagent.journal.mysql=true')
            if key == 'doorhandle.ecs.mysql.config':
                selected = [name.rsplit('.', 1)[-1] for name in args.java_tests.split(',')]
                switches = [server_switches[name] for name in selected if name in server_switches]
                if not switches: raise ValueError('No matching server fixture class was selected')
                arguments += ['-D' + switch + '=true' for switch in switches]
        execute('java', arguments, ROOT)
        counts = {'found': 0, 'passed': 0, 'failed': 0, 'skipped': 0}
        for report in (output / 'java').glob('*/surefire-reports/TEST-*.xml'):
            for case in ET.parse(report).iter('testcase'):
                counts['found'] += 1
                result = 'skipped' if case.find('skipped') is not None else 'failed' if (
                    case.find('failure') is not None or case.find('error') is not None) else 'passed'
                counts[result] += 1
        receipt['javaTests'] = counts
        if counts['passed'] == 0 or counts['failed'] or (args.fixture_property and counts['skipped']):
            raise RuntimeError('The selected Java scope did not execute successfully; inspect original Surefire reports')
        if not args.java_only:
            execute('python', [tools['PYTHON_EXE'], '-B', '-m', 'pytest', 'tests_python', '-q',
                              '--basetemp=' + str(output / 'tmp' / 'pytest'), '--junitxml=' + str(output / 'python.xml')], ROOT)
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
