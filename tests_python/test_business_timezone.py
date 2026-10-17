"""Verify the actual Unix container launcher under an inherited UTC host setting."""
import os
from pathlib import Path
import subprocess
import tempfile
import yaml
from test_jenkins_deploy import git_bash

ROOT=Path(__file__).resolve().parents[1]

def test_launcher_forces_business_timezone_without_evaluating_java_options():
    entry=ROOT/'deploy/backend/entrypoint.sh'
    # exec bypasses shell functions: put a real fake executable first on PATH.
    (ROOT/'work').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='timezone-test-',dir=ROOT/'work') as folder:
        fake=Path(folder)/'java';fake.write_text('#!/bin/sh\nprintf "%s\\n" "$TZ" "$@"\n',encoding='utf8');fake.chmod(0o755)
        script='cd "$FAKE_BIN"; PATH="$PWD:$PATH"; . "$ENTRYPOINT"'
        env={**os.environ,'TZ':'UTC','JAVA_OPTS':'-Xmx128m -Duser.timezone=UTC','ENTRYPOINT':entry.as_posix(),'FAKE_BIN':Path(folder).as_posix()}
        r=subprocess.run([git_bash(),'-c',script],env=env,text=True,capture_output=True,timeout=15,check=True)
    lines=r.stdout.splitlines()
    assert lines[0]=='Asia/Shanghai'
    assert lines.index('-Duser.timezone=Asia/Shanghai')>lines.index('-Duser.timezone=UTC')
    assert lines[-2:]==['-jar','/app/app.jar']

def test_jdbc_session_and_mysql_defaults_use_same_offset_without_multistatement_sql():
    settings=yaml.safe_load((ROOT/'doorhandle-server/src/main/resources/application.yml').read_text(encoding='utf8'))
    sql=settings['spring']['datasource']['hikari']['connection-init-sql']
    assert "time_zone = '+08:00'" in sql and ';' not in sql
    assert all(charset in sql for charset in ('character_set_client','character_set_connection','character_set_results'))
    cloud=yaml.safe_load((ROOT/'compose.cloud.yml').read_text(encoding='utf8'))
    assert '--default-time-zone=+08:00' in cloud['services']['mysql']['command']
