"""Require an explicitly identified ECS host before starting test/runtime processes.

The deployment controller supplies the instance and machine IDs. Do not infer
them from the metadata service: a test job on the wrong ECS must fail closed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
from urllib.request import Request, ProxyHandler, build_opener


def require_ecs_execution():
    if platform.system() != 'Linux':
        raise RuntimeError('Runtime and tests must execute on ECS; this machine is edit/build only')
    instance = os.environ.get('DOORHANDLE_ECS_INSTANCE_ID', '')
    machine = os.environ.get('DOORHANDLE_ECS_MACHINE_ID', '')
    if not re.fullmatch(r'i-[a-z0-9]+', instance) or not re.fullmatch(r'[a-f0-9]{32}', machine):
        raise RuntimeError('Explicit ECS instance and machine IDs are required')
    if Path('/etc/machine-id').read_text().strip() != machine:
        raise RuntimeError('ECS machine identity differs from the admitted execution target')
    # IMDSv2, direct link-local connection; never forward a metadata token to a proxy.
    opener = build_opener(ProxyHandler({}))
    base = 'http://100.100.100.200/latest/'
    with opener.open(Request(base + 'api/token', data=b'', method='PUT', headers={
            'X-aliyun-ecs-metadata-token-ttl-seconds': '60'}), timeout=3) as response:
        token = response.read(4096).decode()
    with opener.open(Request(base + 'meta-data/instance-id', headers={
            'X-aliyun-ecs-metadata-token': token}), timeout=3) as response:
        actual = response.read(256).decode().strip()
    if actual != instance:
        raise RuntimeError('ECS instance identity differs from the admitted execution target')
    return {'instanceId': instance, 'machineId': machine, 'executionLocation': 'ECS'}


if __name__ == '__main__':
    print(json.dumps(require_ecs_execution()))
