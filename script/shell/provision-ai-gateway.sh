#!/usr/bin/env bash
# Run on the existing Linux ECS, from a reviewed checkout. Does not restart the business app.
set -euo pipefail
umask 077
runtime=${1:?existing private runtime directory required}
current=${2:?current application release directory required}
source_dir=$(cd "$(dirname "$0")/../.." && pwd)
for path in "$runtime" "$current"; do
  [[ "$path" =~ ^/(home|srv|opt)/[a-zA-Z0-9_./-]+$ && "/$path/" != *"/../"* ]] || exit 2
done
envfile="$runtime/deploy/cloud.env"
test -r "$envfile"
test -r "$current/compose.monolith.yml"
cd "$source_dir"
# Docker/containerd may remove a bare image ID from lookup after its last tag moves.
# Retain prior referenced images under a private immutable tag before rebuilding.
python3 - "$envfile" <<'PY'
import pathlib,re,subprocess,sys
values=dict(line.split('=',1) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if re.match(r'^[A-Z_][A-Z_0-9]*=',line))
for key,repo in [('MCP_FETCH_IMAGE','mcp-runtime'),('MCP_EGRESS_IMAGE','mcp-egress')]:
    image=values.get(key,'')
    if re.fullmatch('sha256:[a-f0-9]{64}',image):
        subprocess.run(['docker','tag',image,'doorhandlecatch/'+repo+':pin-'+image[7:]],check=True)
PY
docker build --provenance=false --progress=plain -t doorhandlecatch/mcp-runtime:20261015 -f deploy/mcp/Dockerfile .
docker build --provenance=false --progress=plain -t doorhandlecatch/mcp-egress:20261015 -f deploy/mcp/Dockerfile.egress .
image=$(docker image inspect doorhandlecatch/mcp-runtime:20261015 --format '{{.Id}}')
egress=$(docker image inspect doorhandlecatch/mcp-egress:20261015 --format '{{.Id}}')
gid=$(stat -c %g /var/run/docker.sock)
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ && "$egress" =~ ^sha256:[a-f0-9]{64}$ && "$gid" =~ ^[0-9]+$ ]] || exit 2
docker tag "$image" "doorhandlecatch/mcp-runtime:pin-${image#sha256:}"
docker tag "$egress" "doorhandlecatch/mcp-egress:pin-${egress#sha256:}"
# Private values stay in the server env file. Keep a mode-0600 pre-change backup.
python3 - "$envfile" "$image" "$egress" "$gid" <<'PY'
import datetime, os, pathlib, re, secrets, shutil, sys
path=pathlib.Path(sys.argv[1])
original=path.read_text()
values=dict(line.split('=',1) for line in original.splitlines() if re.match(r'^[A-Z_][A-Z_0-9]*=',line))
if not values.get('MCP_SERVER_PUBLIC_IPS'):
    raise SystemExit('Set MCP_SERVER_PUBLIC_IPS to the verified ECS public IP(s) first')
updates={'MCP_FETCH_IMAGE':sys.argv[2], 'MCP_EGRESS_IMAGE':sys.argv[3], 'MCP_DOCKER_GID':sys.argv[4],
    'AGENT_LOCAL_MCP_ENABLED':'true', 'AGENT_MCP_GATEWAY_SECRET': values.get('AGENT_MCP_GATEWAY_SECRET') or secrets.token_hex(32),
    'AGENT_MCP_GATEWAY_KEY': values.get('AGENT_MCP_GATEWAY_KEY') or secrets.token_hex(32)}
backup=path.with_name('cloud.env.before-ai-gateway-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
shutil.copy2(path,backup);os.chmod(backup,0o600)
lines=[line for line in original.splitlines() if line.split('=',1)[0] not in updates]
content='\n'.join(lines+[key+'='+value for key,value in updates.items()])+'\n'
temp=path.with_suffix('.env.tmp');temp.write_text(content);os.chmod(temp,0o600);temp.replace(path)
PY
export DOORHANDLE_ENV_FILE="$envfile"
export DETECTION_BUILD_CONTEXT="$runtime/work/cloud/pth-worker-build"
dc=(docker compose --project-name doorhandlecatch-monolith --env-file "$envfile"
  -f "$current/compose.monolith.yml" -f "$current/compose.cloud.yml" -f "$current/compose.detection.yml"
  -f "$source_dir/compose.ai-gateway.yml")
"${dc[@]}" config --quiet
"${dc[@]}" up -d --no-build --pull never --wait --wait-timeout 300 higress mcp-egress mcp-runner
# The rollout marker is only written once authentication through Higress is verified.
"${dc[@]}" exec -T mcp-runner /opt/fetch/.venv/bin/python - <<'PY'
import base64, hashlib, hmac, json, os, time, urllib.error, urllib.request, uuid
now=int(time.time())
body=base64.urlsafe_b64encode(json.dumps(dict(aud='doorhandle-mcp-runner',owner=1,installation=str(uuid.uuid4()),
    nonce=str(uuid.uuid4()),scope='install',iat=now,exp=now+60)).encode()).decode().rstrip('=')
signature=base64.urlsafe_b64encode(hmac.new(os.environ['MCP_RUNNER_SECRET'].encode(),body.encode(),hashlib.sha256).digest()).decode().rstrip('=')
# Read gateway service key through stdin in the next separate check, not from the runner environment.
request=urllib.request.Request('http://higress:8080/mcp/fetch/artifact',headers={'Authorization':'Bearer '+body+'.'+signature})
try:
    urllib.request.urlopen(request,timeout=15)
    raise SystemExit('Gateway unexpectedly accepted a missing service key')
except urllib.error.HTTPError as error:
    assert error.code==401,error.code
print('Gateway rejects MCP requests without the service credential')
PY
echo 'Gateway infrastructure is ready; run the authenticated acceptance test before enabling deployment overlay.'
echo 'After acceptance: touch the private runtime deploy/ai-gateway.enabled marker, then publish with Jenkins.'
