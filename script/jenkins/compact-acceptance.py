"""Pure validation of fixed-source compact acceptance coverage and original reports.

This module runs no tests, models, processes or database operations. Its caller
first validates the private Jenkins envelope and every included artifact hash.
"""
from pathlib import Path
import hashlib
import json
import re
import xml.etree.ElementTree as ET


FIELDS = ('found', 'passed', 'failed', 'skipped')


def require(value, message):
    if not value:
        raise ValueError(message)


def profile(source):
    file = Path(source) / 'script/jenkins/compact-acceptance.json'
    require(file.is_file() and not file.is_symlink() and file.stat().st_size <= 1024 * 1024,
            'A bounded fixed-source compact acceptance profile is required')
    raw = file.read_bytes(); value = json.loads(raw)
    require(value.get('schemaVersion') == 1 and value.get('kind') == 'doorhandle-compact-acceptance-profile'
            and value.get('sourceTableCount') == 131 and value.get('targetTableCount') == 29,
            'Unexpected fixed-source compact acceptance profile')
    return value, hashlib.sha256(raw).hexdigest()


def tally(cases):
    result = dict.fromkeys(FIELDS, 0)
    for case in cases:
        state = 'skipped' if case.find('skipped') is not None else 'failed' if (
            case.find('failure') is not None or case.find('error') is not None) else 'passed'
        result['found'] += 1; result[state] += 1
    return result


def counts_match(reported, actual):
    return isinstance(reported, dict) and all(type(reported.get(name)) is int
            and reported[name] == actual[name] for name in FIELDS)


def passed(counts, minimum=1, allow_skips=False):
    return counts['passed'] >= minimum and counts['failed'] == 0 and (allow_skips or counts['skipped'] == 0)


def class_counts(cases, name):
    return tally(case for case in cases if (case.get('classname', '') == name
                 or case.get('classname', '').startswith(name + '$')))


def module_cases(cases, name):
    short = name.removeprefix('tests_python.')
    return [case for case in cases if any(case.get('classname', '') == prefix
            or case.get('classname', '').startswith(prefix + '.') for prefix in (name, short))]


def reports(output, descriptors, catalog, prefix):
    require(isinstance(descriptors, list) and descriptors and len(descriptors) < 2000,
            'A suite must reference its original report files')
    cases, seen = [], set()
    for descriptor in descriptors:
        require(isinstance(descriptor, dict) and set(descriptor) == {'path', 'bytes', 'sha256'},
                'Invalid suite report reference')
        name = descriptor['path']
        require(isinstance(name, str) and name.startswith(prefix) and name not in seen
                and name.endswith('.xml') and catalog.get('reports/' + name) == descriptor,
                'A suite report is not bound to the admitted artifact catalog')
        seen.add(name)
        file = Path(output) / name
        root = ET.parse(file).getroot()
        for case in root.iter('testcase'):
            if not case.get('classname'):
                case.set('classname', root.get('name', ''))
            cases.append(case)
    return cases, seen


def validate_mysql_suites(result, value, output, catalog):
    """Require all audited classes once, independently of invocation batching."""
    expected = {item['className']: item for item in value['javaSuites']}
    require(len(expected) == len(value['javaSuites']) and expected, 'Repeated or empty required Java coverage')
    suites = result.get('javaSuites')
    require(isinstance(suites, list) and 1 <= len(suites) <= len(expected),
            'The complete required MySQL suite matrix did not execute')
    seen_classes, seen_reports, selected_actual = set(), set(), {}
    total = dict.fromkeys(FIELDS, 0)
    for suite in suites:
        selection = suite.get('javaSelection')
        require(isinstance(selection, list) and selection
                and all(isinstance(name, str) and name in expected for name in selection)
                and len(selection) == len(set(selection)) and not set(selection) & seen_classes
                and suite.get('status') == 'PASS',
                'Each audited MySQL class must execute once in an admitted invocation')
        properties = [key for name in selection for key in expected[name]['fixtureProperties']]
        require(isinstance(suite.get('fixtureProperties'), list)
                and len(properties) == len(set(properties))
                and sorted(suite['fixtureProperties']) == sorted(properties),
                'A MySQL suite did not use its exact audited fixture properties')
        cases, names = reports(output, suite.get('reportFiles'), catalog, 'java/')
        require(not names.intersection(seen_reports), 'A MySQL report was reused for another suite')
        seen_reports.update(names)
        aggregate = tally(cases)
        observed = suite.get('selectedJavaClasses')
        require(isinstance(observed, dict) and set(observed) == set(selection)
                and passed(aggregate) and counts_match(suite.get('javaTests'), aggregate),
                'A required MySQL class was omitted, failed, skipped or misreported')
        covered = 0
        for name in selection:
            actual = class_counts(cases, name); covered += actual['found']
            require(passed(actual, expected[name]['minimumTests']) and counts_match(observed[name], actual),
                    'A required MySQL class was omitted, failed, skipped or misreported')
            selected_actual[name] = actual
        require(covered == aggregate['found'], 'A MySQL invocation contains unselected Java test evidence')
        seen_classes.update(selection)
        for field in FIELDS:
            total[field] += aggregate[field]
    require(seen_classes == set(expected), 'The complete required MySQL suite matrix did not execute')
    require(counts_match(result.get('javaTests'), total), 'Required MySQL aggregate counts differ')
    selected = result.get('selectedJavaClasses')
    require(isinstance(selected, dict) and set(selected) == set(selected_actual)
            and all(counts_match(selected[name], actual) for name, actual in selected_actual.items()),
            'The top-level MySQL class counts differ from original XML')
    top_reports = result.get('javaReportFiles')
    require(isinstance(top_reports, list) and len(top_reports) == len(seen_reports)
            and {item['path'] for item in top_reports} == seen_reports
            and all(catalog.get('reports/' + item['path']) == item for item in top_reports),
            'The top-level MySQL report catalog differs from executed suite evidence')
    return len(expected)


def validate_run(result, value, profile_sha, output, catalog):
    """Require each selected class and cross-language test gate, never only totals."""
    require(result.get('status') == 'PASS' and result.get('acceptanceProfileSha256') == profile_sha
            and result.get('javaOnly') is False, 'Acceptance receipt does not bind the complete fixed-source profile')
    java_classes = validate_mysql_suites(result, value, output, catalog)

    source = result.get('sourceRegression', {})
    require(source.get('status') == 'PASS' and value['sourceRegression']['required'] is True,
            'The ordinary source regression did not execute in this build')
    cases, _ = reports(output, source.get('reportFiles'), catalog, 'source-regression/java/')
    actual = tally(cases)
    require(passed(actual, allow_skips=True) and counts_match(source.get('javaTests'), actual),
            'Ordinary Java regression contains failures or changed counts')
    for requirement in value['sourceRegression']['requiredClasses']:
        name = requirement['className']; actual = class_counts(cases, name)
        require(passed(actual, requirement['minimumTests'])
                and counts_match(source.get('selectedJavaClasses', {}).get(name), actual),
                'A required ordinary Java regression class was omitted, failed or skipped')

    require('reports/python.xml' in catalog, 'Actual Python JUnit evidence is missing')
    python_cases = list(ET.parse(Path(output) / 'python.xml').getroot().iter('testcase'))
    actual = tally(python_cases)
    require(passed(actual, allow_skips=True) and counts_match(result.get('pythonTests'), actual)
            and result.get('workerMysqlRequested') is True
            and re.fullmatch(r'[a-f0-9]{64}', result.get('workerMysqlConfigSha256', '')),
            'Python regression and real worker receipt persistence were not fully executed')
    known = set()
    for requirement in value['python']['requiredSuites']:
        name = requirement['module']; cases = module_cases(python_cases, name); known.update(map(id, cases))
        actual = tally(cases)
        allowed = set(requirement.get('allowedSkippedTests', []))
        skipped = {case.get('name') for case in cases if case.find('skipped') is not None}
        require(passed(actual, requirement['minimumTests'], allow_skips=True) and skipped <= allowed
                and actual['skipped'] == len(skipped)
                and counts_match(result.get('selectedPythonSuites', {}).get(name), actual),
                'A required Python suite was omitted, failed, unexpectedly skipped or misreported')
    require(len(known) == len(python_cases), 'Python executed an unprofiled test module')
    whole = value['wholeMigration']; migration_cases = module_cases(python_cases, whole['pythonSuite'])
    migration = tally(migration_cases)
    require(result.get('wholeMigrationRequested') is True and passed(migration)
            and all(type(result.get('wholeMigrationTests', {}).get(key)) is int
                    and result['wholeMigrationTests'][key] == migration[key] for key in ('passed', 'failed', 'skipped')),
            'Complete copy and source/target recovery acceptance did not actually pass')

    commands = result.get('commands', [])
    for frontend in value['frontends']:
        name = frontend['directory']; observed = result.get('frontendResults', {}).get(name, {})
        require(observed.get('selectedTestFiles') == frontend['testFiles']
                and all(type(observed.get(key)) is int and observed[key] == 0
                        for key in ('installExitCode', 'testExitCode', 'buildExitCode')),
                'A frontend did not execute its fixed test files and build')
        for label in frontend['requiredCommands']:
            matches = [command for command in commands if command.get('label') == label]
            require(len(matches) == 1 and type(matches[0].get('exitCode')) is int and matches[0]['exitCode'] == 0,
                    'A required frontend command is missing or failed')
        log = name + '-test.log'
        require('reports/' + log in catalog, 'Frontend test output is not bound to this run')
        tap = (Path(output) / log).read_text(encoding='utf8')
        summaries = {}
        for key in ('tests', 'pass', 'fail', 'skipped', 'cancelled', 'todo'):
            matches = re.findall(r'^# ' + key + r' ([0-9]+)\s*$', tap, re.M)
            require(matches, 'Frontend test output lacks an actual TAP result summary')
            summaries[key] = int(matches[-1])
        actual = {'found': summaries['tests'], 'passed': summaries['pass'],
                  'failed': summaries['fail'], 'skipped': summaries['skipped']}
        require(passed(actual, frontend['minimumTests']) and summaries['cancelled'] == summaries['todo'] == 0
                and counts_match(observed.get('tests'), actual),
                'Frontend test cases were absent, failed, skipped or misreported')
    return {'acceptanceProfileSha256': profile_sha, 'javaClasses': java_classes,
            'sourceClasses': len(value['sourceRegression']['requiredClasses']),
            'pythonSuites': len(value['python']['requiredSuites']), 'frontends': len(value['frontends'])}
