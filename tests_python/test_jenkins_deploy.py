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


@pytest.mark.parametrize('failed_step', [0, 1, 2, 3, 4])
def test_health_failure_stops_activation_before_the_next_operation(failed_step):
    source = (Path(__file__).resolve().parents[1] / 'script/jenkins/deploy-remote.sh').read_text(encoding='utf-8')
    activate = re.search(r'^activate\(\) \{.*?^\}', source, flags=re.M | re.S).group()
    script = '''set -euo pipefail
count=0
dc() { count=$((count + 1)); [[ "$count" != "$FAIL_STEP" ]]; }
''' + activate + '''
if activate /release /snapshot; then result=0; else result=$?; fi
printf '%s %s' "$result" "$count"
'''
    result = subprocess.run([git_bash(), '-c', script], env={**os.environ, 'FAIL_STEP': str(failed_step)}, text=True, capture_output=True, timeout=15, check=True)
    assert result.stdout == (f'1 {failed_step}' if failed_step else '0 4')
