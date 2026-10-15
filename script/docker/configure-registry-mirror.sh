#!/bin/bash
set -euo pipefail
# https://github.com/DaoCloud/public-image-mirror (Apache-2.0)
# 合并配置，不覆盖已有日志、存储、代理或其他镜像源设置。
if [ "$(id -u)" -ne 0 ]; then echo 'Run with sudo.' >&2; exit 1; fi
install -d -m 0755 /etc/docker
mirror_config=$(mktemp /etc/docker/daemon-mirror.XXXXXX.json)
trap 'rm -f "$mirror_config"' EXIT
python3 - "$mirror_config" <<'PY'
import json, pathlib, sys
source=pathlib.Path('/etc/docker/daemon.json')
config=json.loads(source.read_text()) if source.exists() else {}
mirrors=config.get('registry-mirrors', [])
if not isinstance(mirrors,list): raise SystemExit('Invalid existing registry-mirrors')
config['registry-mirrors']=list(dict.fromkeys(['https://docker.m.daocloud.io', *mirrors]))
pathlib.Path(sys.argv[1]).write_text(json.dumps(config,indent=2)+'\n')
PY
dockerd --validate --config-file "$mirror_config"
if [ -f /etc/docker/daemon.json ]; then
    cp -p /etc/docker/daemon.json "/etc/docker/daemon.json.backup.$(date -u +%Y%m%dT%H%M%SZ)"
fi
install -m 0600 "$mirror_config" /etc/docker/daemon.json
systemctl restart docker
systemctl is-active docker
docker pull hello-world:latest
docker run --rm --network none hello-world:latest
