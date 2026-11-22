import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import uuid

import pytest


HELPER = Path(__file__).resolve().parents[1] / 'script/shell/native-fetch-process.py'


@pytest.mark.skipif(
    sys.platform != 'linux' or not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'),
    reason='The native Fetch launcher requires Linux pidfd support',
)
def test_fetch_stderr_stays_open_without_exposing_diagnostics(tmp_path):
    directory = tmp_path / 'users/42/mcp/fetch/installs' / str(uuid.uuid4())
    directory.mkdir(parents=True)
    helper = [sys.executable, '-I', str(HELPER)]
    options = ['--directory', str(directory)]
    pool = json.loads(subprocess.check_output([*helper, 'pool', *options], timeout=10))['poolId']
    nonce = str(uuid.uuid4())
    options += ['--execution', nonce, '--pool', pool]
    subprocess.run([*helper, 'reserve', *options], check=True, stdout=subprocess.PIPE, timeout=10)

    program = r"""
import os
import runpy
import sys

helper, directory, nonce = sys.argv[1:]
records = runpy.run_path(helper)['Records'](directory)

def fetch(module, run_name):
    assert module == 'mcp_server_fetch' and run_name == '__main__'
    os.write(2, b'private Fetch diagnostics')
    print('ready', flush=True)
    assert sys.stdin.readline() == 'continue\n'
    print('tools', flush=True)

runpy.run_module = fetch
records.run(nonce)
"""
    with subprocess.Popen([sys.executable, '-I', '-c', program, str(HELPER), str(directory), nonce],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True) as child:
        try:
            assert select.select([child.stdout], [], [], 5)[0]
            assert child.stdout.readline() == 'ready\n'
            # Readable stderr here would mean either leaked diagnostics or premature EOF.
            assert not select.select([child.stderr], [], [], 0)[0]
            child.stdin.write('continue\n')
            child.stdin.flush()
            assert select.select([child.stdout], [], [], 5)[0]
            assert child.stdout.readline() == 'tools\n'
            assert child.wait(timeout=5) == 0
            assert child.stderr.read() == ''
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    receipt = json.loads(subprocess.check_output([*helper, 'stop', *options], timeout=10))
    assert receipt['executionNonce'] == nonce
    assert receipt['exitVerified'] and receipt['cleanupConfirmed']
