"""Exercise deployment failure handling without a Docker daemon or an ECS."""
from pathlib import Path
import os
import re
import shutil
import subprocess
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


@pytest.mark.parametrize('failed_step', [0, 1, 2, 3, 4, 5])
def test_health_failure_stops_activation_before_the_next_operation(failed_step):
    source = (Path(__file__).resolve().parents[1] / 'script/jenkins/deploy-remote.sh').read_text(encoding='utf-8')
    activate = re.search(r'^activate\(\) \{.*?^\}', source, flags=re.M | re.S).group()
    script = '''set -euo pipefail
count=0
prepare_memory() { memory_action=replace; }
verify_memory() { :; }
dc() { count=$((count + 1)); [[ "$count" != "$FAIL_STEP" ]]; }
''' + activate + '''
if activate /release /snapshot; then result=0; else result=$?; fi
printf '%s %s' "$result" "$count"
'''
    result = subprocess.run([git_bash(), '-c', script], env={**os.environ, 'FAIL_STEP': str(failed_step)}, text=True, capture_output=True, timeout=15, check=True)
    assert result.stdout == (f'1 {failed_step}' if failed_step else '0 5')


def test_memory_bridge_is_healthy_before_backend_activation_and_uses_the_same_rollback_path():
    source=(Path(__file__).resolve().parents[1]/'script/jenkins/deploy-remote.sh').read_text(encoding='utf8')
    activate=re.search(r'^activate\(\) \{.*?^\}',source,flags=re.M|re.S).group()
    script='set -euo pipefail\nprepare_memory() { memory_action=replace; }\nverify_memory() { :; }\ndc() { printf "%s\\n" "$*" >&2; }\n'+activate+'\nactivate /release /snapshot'
    result=subprocess.run([git_bash(),'-c',script],text=True,capture_output=True,timeout=15,check=True)
    calls=result.stderr.splitlines()
    assert len(calls)==5 and calls[0].endswith('240 mem0') and calls[1].endswith('240 backend')
    assert all('--no-deps --no-build --pull never' in call for call in calls[:3])
    assert 'activate "$previous" "$root/state/previous-images.yml"' in source
    assert 'activate "$previous" "$release/previous-images.yml"' in source


@pytest.mark.parametrize('failure',['prepare','verify','none'])
def test_preserved_bridge_is_not_recreated_and_unverified_memory_cannot_start_backend(failure):
    source=(Path(__file__).resolve().parents[1]/'script/jenkins/deploy-remote.sh').read_text(encoding='utf8')
    activate=re.search(r'^activate\(\) \{.*?^\}',source,flags=re.M|re.S).group()
    script='''set -euo pipefail
prepare_memory() { memory_action=preserve; [[ "$FAILURE" != prepare ]]; }
verify_memory() { [[ "$FAILURE" != verify ]]; }
dc() { printf '%s\\n' "$*" >&2; }
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


@pytest.mark.parametrize('failed_service,allow,succeeds',[('backend','yes',True),('mem0','yes',True),('backend','no',False),('mysql','yes',False)])
def test_snapshot_allows_unhealthy_app_rollback_but_keeps_database_health_gate(tmp_path,failed_service,allow,succeeds):
    source=(Path(__file__).resolve().parents[1]/'script/jenkins/deploy-remote.sh').read_text(encoding='utf8')
    snapshot=re.search(r'^snapshot\(\) \{.*?^\}',source,flags=re.M|re.S).group()
    script='''set -euo pipefail
project=doorhandlecatch-monolith
docker() {
 if [[ "$1" == ps ]]; then printf '%s' "${@: -1}"; return; fi
 if [[ "$3" == '{{.Image}}' ]]; then printf 'sha256:%064d' 1; return; fi
 if [[ "${@: -1}" == *"=$FAILED_SERVICE" ]]; then printf exited/unhealthy; else printf running/healthy; fi
}
'''+snapshot+'''\nif snapshot "$SNAPSHOT" all "$ALLOW"; then printf ok; else printf rejected; fi'''
    result=subprocess.run([git_bash(),'-c',script],env={**os.environ,'SNAPSHOT':str(tmp_path/'images.yml'),'FAILED_SERVICE':failed_service,'ALLOW':allow},text=True,capture_output=True,timeout=15,check=True)
    assert result.stdout==('ok' if succeeds else 'rejected')
