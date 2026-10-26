"""Exercise deployment failure handling without a Docker daemon or an ECS."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import shlex
import importlib.util
import pytest


def git_bash():
    if os.name == 'nt':
        git = shutil.which('git')
        if git:
            candidate = Path(git).resolve().parents[1] / 'bin/bash.exe'
            if candidate.is_file():
                return str(candidate)
        pytest.skip('Git Bash required for the Linux deployment helper test')
    return shutil.which('bash') or pytest.skip('Bash not installed')


def activation_support(tmp_path):
    # Memory/health tests stub only the independent assignment, Secret and MCP guards.
    # Their config reads do not count as application activation operations.
    return '''
root=ROOT_PATH
runtime="$root/runtime"
mkdir -p "$root/state" "$runtime"
assignment_helper=assignment-fixture
secret_helper=secret-fixture
prepare_mcp_runtime() { :; }
python3() { cat >/dev/null; [[ "${GUARD_FAIL:-}" != "$1" ]] || return 1; printf '{}'; }
'''.replace('ROOT_PATH', shlex.quote(tmp_path.as_posix()))


@pytest.mark.parametrize('failed_step', [0, 1, 2, 3, 4, 5])
def test_health_failure_stops_activation_before_the_next_operation(tmp_path, failed_step):
    source = (Path(__file__).resolve().parents[1] / 'script/jenkins/deploy-remote.sh').read_text(encoding='utf-8')
    activate = re.search(r'^activate\(\) \{.*?^\}', source, flags=re.M | re.S).group()
    script = 'set -euo pipefail\n' + activation_support(tmp_path) + '''
count=0
prepare_memory() { memory_action=replace; }
verify_memory() { :; }
dc() { if [[ "$3" == config ]]; then printf '{}'; return; fi; count=$((count + 1)); [[ "$count" != "$FAIL_STEP" ]]; }
''' + activate + '''
if activate /release /snapshot; then result=0; else result=$?; fi
printf '%s %s' "$result" "$count"
'''
    result = subprocess.run([git_bash(), '-c', script], env={**os.environ, 'FAIL_STEP': str(failed_step)}, text=True, capture_output=True, timeout=15, check=True)
    assert result.stdout == (f'1 {failed_step}' if failed_step else '0 5')


def test_memory_bridge_is_healthy_before_backend_activation_and_uses_the_same_rollback_path(tmp_path):
    source=(Path(__file__).resolve().parents[1]/'script/jenkins/deploy-remote.sh').read_text(encoding='utf8')
    activate=re.search(r'^activate\(\) \{.*?^\}',source,flags=re.M|re.S).group()
    script='set -euo pipefail\n'+activation_support(tmp_path)+'\nprepare_memory() { memory_action=replace; }\nverify_memory() { :; }\ndc() { if [[ "$3" == config ]]; then printf "{}"; return; fi; printf "%s\\n" "$*" >&2; }\n'+activate+'\nactivate /release /snapshot'
    result=subprocess.run([git_bash(),'-c',script],text=True,capture_output=True,timeout=15,check=True)
    calls=result.stderr.splitlines()
    assert len(calls)==5 and calls[0].endswith('240 mem0') and calls[1].endswith('240 backend')
    assert all('--no-deps --no-build --pull never' in call for call in calls[:3])
    assert 'activate "$previous" "$root/state/previous-images.yml"' in source
    assert 'activate "$previous" "$release/previous-images.yml"' in source


@pytest.mark.parametrize('failure',['prepare','verify','none'])
def test_preserved_bridge_is_not_recreated_and_unverified_memory_cannot_start_backend(tmp_path, failure):
    source=(Path(__file__).resolve().parents[1]/'script/jenkins/deploy-remote.sh').read_text(encoding='utf8')
    activate=re.search(r'^activate\(\) \{.*?^\}',source,flags=re.M|re.S).group()
    script='set -euo pipefail\n'+activation_support(tmp_path)+'''
prepare_memory() { memory_action=preserve; [[ "$FAILURE" != prepare ]]; }
verify_memory() { [[ "$FAILURE" != verify ]]; }
dc() { if [[ "$3" == config ]]; then printf '{}'; return; fi; printf '%s\\n' "$*" >&2; }
'''+activate+'''\nif activate /release /snapshot; then printf ok; else printf failed; fi'''
    result=subprocess.run([git_bash(),'-c',script],env={**os.environ,'FAILURE':failure},text=True,capture_output=True,timeout=15,check=True)
    calls=result.stderr.splitlines()
    if failure!='none':assert result.stdout=='failed' and not calls
    else:
        assert result.stdout=='ok' and len(calls)==4
        assert calls[0].endswith('240 backend') and all(not call.endswith(' mem0') for call in calls)


def test_pipeline_uploads_guard_for_legacy_rollback_and_allows_recovering_unhealthy_apps():
    root=Path(__file__).resolve().parents[1]
    pipeline=(root/'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    assert pipeline.index("'script/docker/memory-compat.py'")<pipeline.index("if ($env:ACTION -eq 'rollback')")
    source=(root/'script/jenkins/deploy-remote.sh').read_text(encoding='utf8')
    assert 'snapshot "$root/state/rollback-current.yml" all yes' in source


@pytest.mark.parametrize('allow', ['yes', 'no'])
def test_snapshot_delegates_unhealthy_app_policy_to_runtime_guard(tmp_path,allow):
    source=(Path(__file__).resolve().parents[1]/'script/jenkins/deploy-remote.sh').read_text(encoding='utf8')
    snapshot=re.search(r'^snapshot\(\) \{.*?^\}',source,flags=re.M|re.S).group()
    script='''set -euo pipefail
root=/isolated
runtime_helper=runtime-fixture
python3() { printf '%s\\n' "$*"; }
'''+snapshot+'''\nif snapshot "$SNAPSHOT" all "$ALLOW"; then printf ok; else printf rejected; fi'''
    result=subprocess.run([git_bash(),'-c',script],env={**os.environ,'SNAPSHOT':str(tmp_path/'images.yml'),'ALLOW':allow},text=True,capture_output=True,timeout=15,check=True)
    assert 'runtime-fixture snapshot --state /isolated/state --lock-fd 9 --output' in result.stdout
    assert ('--allow-unhealthy' in result.stdout) == (allow == 'yes')
    assert result.stdout.endswith('ok')


@pytest.mark.parametrize('failed_service,allow,succeeds', [('backend',True,True),('mem0',True,True),('backend',False,False),('mysql',True,False)])
def test_runtime_snapshot_keeps_the_database_health_gate(tmp_path, monkeypatch, failed_service, allow, succeeds):
    file=Path(__file__).resolve().parents[1]/'script/docker/mcp-runtime.py'
    spec=importlib.util.spec_from_file_location('runtime_snapshot_fixture',file)
    runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
    state=tmp_path/'state';state.mkdir()
    monkeypatch.setattr(runtime.common,'private_state',lambda value:state)
    def container(project, service, **kwargs):
        if service=='mcp-runner': return None
        return {'Image':'sha256:'+'a'*64,'State':{'Running':service!=failed_service,'Health':{'Status':'healthy'}}}
    monkeypatch.setattr(runtime.common,'container',container)
    monkeypatch.setattr(runtime.common,'environment',lambda row:{})
    monkeypatch.setattr(runtime.guard,'capability',lambda image:(None,1))
    monkeypatch.setattr(runtime.common,'image',lambda image:(None,{'json':1}))
    outputs=[];monkeypatch.setattr(runtime.common,'write_json',lambda path,value:outputs.append(value))
    if succeeds:
        runtime.snapshot(state,state/'previous-images.yml','all',allow)
        assert outputs[0]['services']['mysql']['image']=='sha256:'+'a'*64
    else:
        with pytest.raises(runtime.common.GuardError,match='healthy'):
            runtime.snapshot(state,state/'previous-images.yml','all',allow)
        assert not outputs


@pytest.mark.parametrize('guard', ['assignment-fixture', 'secret-fixture'])
def test_prerequisite_guard_failure_stops_before_any_application_activation(tmp_path, guard):
    source=(Path(__file__).resolve().parents[1]/'script/jenkins/deploy-remote.sh').read_text(encoding='utf8')
    activate=re.search(r'^activate\(\) \{.*?^\}',source,flags=re.M|re.S).group()
    script='set -euo pipefail\n'+activation_support(tmp_path)+'''
prepare_mcp_runtime() { printf unexpected >&2; return 1; }
dc() { if [[ "$3" == config ]]; then printf '{}'; return; fi; printf unexpected >&2; return 1; }
'''+activate+'\nif activate /release /snapshot; then printf ok; else printf rejected; fi'
    result=subprocess.run([git_bash(),'-c',script],env={**os.environ,'GUARD_FAIL':guard},text=True,capture_output=True,timeout=15,check=True)
    assert result.stdout=='rejected' and not result.stderr
