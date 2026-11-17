import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


import pytest


def pytest_addoption(parser):
    parser.addoption('--doorhandle-control-gate', action='store_true', default=False,
                     help='Run and admit all fixed control modules before other full-acceptance tests')


def fixed_control_minimum():
    import importlib.util
    file = ROOT_DIR / 'script/jenkins/verify-ecs.py'
    spec = importlib.util.spec_from_file_location('full_acceptance_control_order', file)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    return helper.control_gate_minimum()


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    if not config.getoption('--doorhandle-control-gate'):
        return
    minimum = fixed_control_minimum()
    selected = {}
    totals = dict.fromkeys(minimum, 0)
    for item in items:
        path = Path(item.path)
        name = 'tests_python.' + path.stem
        if path.parent == ROOT_DIR / 'tests_python' and name in minimum:
            if item.nodeid in selected:
                raise pytest.UsageError('Same-attempt control collection contains a repeated testcase')
            selected[item.nodeid] = name
            totals[name] += 1
    if not minimum or any(totals[name] < count for name, count in minimum.items()):
        raise pytest.UsageError('Same-attempt control collection omitted required modules or cases')
    config._doorhandle_control_gate = {'nodes': selected, 'reports': {}, 'admitted': False}
    items[:] = [item for item in items if item.nodeid in selected] + [item for item in items if item.nodeid not in selected]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    gate = getattr(item.config, '_doorhandle_control_gate', None)
    if gate is not None and item.nodeid in gate['nodes']:
        report = outcome.get_result()
        gate['reports'].setdefault(item.nodeid, {})[report.when] = report.outcome


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    gate = getattr(item.config, '_doorhandle_control_gate', None)
    if gate is None or gate['admitted'] or item.nodeid in gate['nodes']:
        return
    # Finish the entire control group, including teardown errors, before deciding.
    # Never enter whole-copy/native preparation after a failed or skipped control.
    if not gate['nodes'] or any(gate['reports'].get(node) !=
            {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'} for node in gate['nodes']):
        pytest.exit('Same-attempt controls failed, skipped or did not complete; remaining Python was not executed', returncode=1)
    gate['admitted'] = True


@pytest.fixture(autouse=True)
def isolate_memory_receipts(request, monkeypatch, tmp_path):
    if not request.node.path.name.startswith("test_memory_"):
        yield
        return
    import threading
    from memory_service import main
    from memory_service.write_receipts import MemoryWriter
    lock = threading.Lock()
    writer = MemoryWriter(tmp_path / "receipt-store", lambda: main.memory_instance, lock)
    monkeypatch.setattr(main, "memory_write_lock", lock)
    monkeypatch.setattr(main, "memory_writer", writer)
    try:
        yield writer
    finally:
        writer.close()
