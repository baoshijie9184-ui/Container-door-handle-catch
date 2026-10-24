#!/usr/bin/env bash
# Update application containers within the existing Compose project; retain all data volumes.
set -euo pipefail
umask 077
action=${1:?action required}
root=${2:?release root required}
runtime=${3:?existing runtime directory required}
tag=${4:?release tag required}
digest=${5:-}
[[ "$action" == deploy || "$action" == rollback ]] || exit 2
[[ "$tag" =~ ^ci-[0-9]+-[a-f0-9]{12}$ ]] || exit 2
for path in "$root" "$runtime"; do
    [[ "$path" =~ ^/(home|srv|opt)/[a-zA-Z0-9_./-]+$ && "$path" != */ && "/$path/" != *"/../"* ]] || exit 2
done
[[ -d "$runtime" && -r "$runtime/deploy/cloud.env" ]] || { echo 'Existing private runtime config is required.' >&2; exit 2; }
mkdir -p "$root/releases" "$root/state" "$root/inbox"
root=$(realpath "$root")
runtime=$(realpath "$runtime")
envfile="$runtime/deploy/cloud.env"
export DOORHANDLE_ENV_FILE="$envfile"
export DETECTION_BUILD_CONTEXT="$runtime/work/cloud/pth-worker-build"
project=doorhandlecatch-monolith
compat_helper="$(dirname "${BASH_SOURCE[0]}")/memory-compat.py"
[[ -r "$compat_helper" ]] || { echo 'Memory compatibility helper is required.' >&2; exit 2; }
memory_override=()
mcp_override=()
mcp_recovery_done=false
mcp_manual_recovery=false
assignment_helper="$(dirname "${BASH_SOURCE[0]}")/assignment-compat.py"
[[ -r "$assignment_helper" ]] || { echo 'Assignment compatibility helper is required.' >&2; exit 2; }
mcp_helper="$(dirname "${BASH_SOURCE[0]}")/mcp-compat.py"
[[ -r "$mcp_helper" ]] || { echo 'Native MCP compatibility helper is required.' >&2; exit 2; }
runtime_helper="$(dirname "${BASH_SOURCE[0]}")/mcp-runtime.py"
[[ -r "$runtime_helper" ]] || { echo 'MCP runtime transition helper is required.' >&2; exit 2; }
exec 9>"$root/state/deploy.lock"
flock -n 9 || { echo 'Another deployment is in progress.' >&2; exit 3; }
python3 "$runtime_helper" sync-publication --state "$root/state" --lock-fd 9
secret_helper="$(dirname "${BASH_SOURCE[0]}")/model-secrets.py"
[[ -r "$secret_helper" ]] || { echo 'Model Secret guard helper is required.' >&2; exit 2; }
model_key_source=$(python3 "$secret_helper" source --root "$root" --runtime "$runtime")
if [[ "$model_key_source" != disabled ]]; then
    export MODEL_CONFIG_MASTER_KEY_SOURCE="$model_key_source"
fi

dc() {
    local dir=$1 override=$2
    shift 2
    local overlays=()
    if [[ -f "$runtime/deploy/ai-gateway.enabled" && -f "$dir/compose.ai-gateway.yml" ]]; then
        overlays=(-f "$dir/compose.ai-gateway.yml")
    fi
    if [[ "$model_key_source" != disabled ]]; then
        [[ -r "$dir/compose.model-config.yml" ]] || { echo 'Release has no model Secret overlay; select a compatible version.' >&2; return 1; }
        overlays+=(-f "$dir/compose.model-config.yml")
    fi
    docker compose --project-name "$project" --env-file "$envfile" \
        -f "$dir/compose.monolith.yml" -f "$dir/compose.cloud.yml" -f "$dir/compose.detection.yml" \
        "${overlays[@]}" -f "$override" "${memory_override[@]}" "${mcp_override[@]}" "$@"
}

# Snapshot actual running image IDs, independent of a mutable tag or private env APP_IMAGE_TAG.
snapshot() {
    local file=$1 mode=$2 allow_unhealthy=${3:-no}
    local options=()
    if [[ "$allow_unhealthy" == yes ]]; then options=(--allow-unhealthy); fi
    python3 "$runtime_helper" snapshot --state "$root/state" --lock-fd 9 --output "$file" --mode "$mode" "${options[@]}"
}

prepare_mcp_runtime() {
    local dir=$1 images=$2 restoring=${3:-no} before after
    local options=()
    if [[ "$restoring" == yes ]]; then options=(--restore-unpublished); fi
    mcp_override=()
    before=$(python3 "$runtime_helper" status --state "$root/state" --lock-fd 9) || return 1
    if ! mcp_action=$(dc "$dir" "$images" config --format json | python3 "$runtime_helper" prepare --state "$root/state" --lock-fd 9 "${options[@]}"); then
        after=$(python3 "$runtime_helper" status --state "$root/state" --lock-fd 9) || { mcp_manual_recovery=true; return 1; }
        if [[ "$before" != "$after" && "$after" == *:NEEDS_REVIEW ]]; then
            if python3 "$runtime_helper" recover --state "$root/state" --lock-fd 9; then mcp_recovery_done=true; else mcp_manual_recovery=true; fi
        elif [[ "$after" != NONE && "$after" != *:VERIFIED && "$after" != *:FINALIZED && "$after" != *:RESTORED ]]; then
            mcp_manual_recovery=true
        fi
        return 1
    fi
    [[ "$mcp_action" == replace || "$mcp_action" == preserve || "$mcp_action" == disabled ]] || return 1
    mcp_override=(-f "$root/state/mcp-runtime-activation.json")
    if [[ "$mcp_action" != disabled ]]; then
        if ! python3 "$runtime_helper" applying --state "$root/state" --lock-fd 9 \
            || ! dc "$dir" "$images" up -d --no-deps --no-build --pull never --wait --wait-timeout 120 mcp-runner \
            || ! python3 "$runtime_helper" verify --state "$root/state" --lock-fd 9; then
            if python3 "$runtime_helper" recover --state "$root/state" --lock-fd 9; then mcp_recovery_done=true; else mcp_manual_recovery=true; fi
            return 1
        fi
    fi
    dc "$dir" "$images" config --format json | python3 "$mcp_helper" guard --state "$root/state" --lock-fd 9 --pin > "$root/state/mcp-transition.pending.json" || return 1
    mv "$root/state/mcp-transition.pending.json" "$root/state/mcp-transition.json"
}

prepare_memory() {
    local dir=$1 images=$2
    memory_override=()
    memory_action=$(dc "$dir" "$images" config --format json | python3 "$compat_helper" prepare --state "$root/state" --lock-fd 9) || return 1
    [[ "$memory_action" == replace || "$memory_action" == preserve ]] || return 1
    if [[ "$memory_action" == preserve ]]; then echo 'Retained the compatible memory bridge while rolling back application images.' >&2; fi
    memory_override=(-f "$root/state/memory-activation-images.yml")
}

verify_memory() {
    python3 "$compat_helper" verify --state "$root/state" --lock-fd 9
}

activate() {
    local dir=$1 images=$2 restoring=${3:-no}
    mcp_override=()
    memory_override=()
    mcp_recovery_done=false
    mcp_manual_recovery=false
    # No application is stopped until metadata, reader declarations and the recovery baseline agree.
    dc "$dir" "$images" config --format json | python3 "$assignment_helper" guard --state "$root/state" --lock-fd 9 --pin > "$root/state/assignment-transition.pending.json" || return 1
    mv "$root/state/assignment-transition.pending.json" "$root/state/assignment-transition.json"
    # Validate encrypted escrow + an offline signed restore proof and image format before stopping either writer.
    dc "$dir" "$images" config --format json | python3 "$secret_helper" guard --root "$root" --runtime "$runtime" --pin > "$root/state/model-secret-transition.pending.json" || return 1
    mv "$root/state/model-secret-transition.pending.json" "$root/state/model-secret-transition.json"
    prepare_mcp_runtime "$dir" "$images" "$restoring" || return 1
    # Quiesce reads/writes, inspect the durable protocol floor, and pin an immutable compatible bridge.
    prepare_memory "$dir" "$images" || return 1
    if [[ "$memory_action" == replace ]]; then
        dc "$dir" "$images" up -d --no-deps --no-build --pull never --wait --wait-timeout 240 mem0 || return 1
    fi
    verify_memory || return 1
    dc "$dir" "$images" up -d --no-deps --no-build --pull never --wait --wait-timeout 240 backend || return 1
    dc "$dir" "$images" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 nginx || return 1
    dc "$dir" "$images" exec -T backend curl -fsS http://127.0.0.1:8080/actuator/health >/dev/null || return 1
    dc "$dir" "$images" exec -T nginx wget -q -O /dev/null http://127.0.0.1/nginx-health || return 1
    if [[ -f "${runtime:-}/deploy/ai-gateway.enabled" && -f "$dir/compose.ai-gateway.yml" ]]; then
        dc "$dir" "$images" exec -T backend curl -fsS http://higress:15021/healthz/ready >/dev/null || return 1
    fi
}

if [[ "$action" == rollback ]]; then
    [[ -s "$root/state/previous-directory" && -s "$root/state/previous-images.yml" ]] || { echo 'No previous successful release recorded.' >&2; exit 4; }
    previous=$(cat "$root/state/previous-directory")
    [[ "$previous" == "$runtime" || "$previous" == "$root/releases/"* ]] || exit 2
    current=$(cat "$root/state/current-directory")
    snapshot "$root/state/rollback-current.yml" all yes
    if ! activate "$previous" "$root/state/previous-images.yml"; then
        if [[ "$mcp_manual_recovery" == true ]]; then echo 'Runner recovery remains unverified; preserve volumes and transition evidence.' >&2; exit 6; fi
        if [[ "$mcp_recovery_done" == true ]]; then echo 'Runner transition was restored; rollback was not published.' >&2; exit 5; fi
        echo 'Rollback health check failed; restoring current images.' >&2
        activate "$current" "$root/state/rollback-current.yml" yes || { echo 'Current release restoration also failed; manual recovery required.' >&2; exit 6; }
        python3 "$runtime_helper" aborted --state "$root/state" --lock-fd 9
        exit 5
    fi
    python3 "$runtime_helper" publish --state "$root/state" --lock-fd 9 --current "$previous" --previous "$current" --images "$root/state/rollback-current.yml"
    python3 "$runtime_helper" finalize --state "$root/state" --lock-fd 9
    echo 'Rollback passed application health checks.'
    exit 0
fi

[[ "$digest" =~ ^[a-f0-9]{64}$ ]] || exit 2
archive="$root/inbox/$tag/source.tar.gz"
[[ -f "$archive" ]] || exit 2
printf '%s  %s\n' "$digest" "$archive" | sha256sum --check --status
release="$root/releases/$tag"
[[ ! -e "$release" ]] || { echo 'Release ID already exists; use a new build.' >&2; exit 2; }
mkdir "$release"
# Archives originate from git archive; reject traversal, symbolic links and special entries too.
python3 - "$archive" "$release" <<'PY'
import pathlib, sys, tarfile
destination = pathlib.Path(sys.argv[2]).resolve()
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    for item in archive.getmembers():
        path = pathlib.PurePosixPath(item.name)
        if path.is_absolute() or '..' in path.parts or not (item.isfile() or item.isdir()):
            raise SystemExit('Unsafe source archive entry')
    archive.extractall(destination, filter='data')
PY
for file in compose.monolith.yml compose.cloud.yml compose.detection.yml; do test -r "$release/$file"; done
previous=$runtime
if [[ -s "$root/state/current-directory" ]]; then previous=$(cat "$root/state/current-directory"); fi
[[ "$previous" == "$runtime" || "$previous" == "$root/releases/"* ]] || exit 2
snapshot "$release/previous-images.yml" all
snapshot "$release/runtime-images.yml" runtime
export APP_IMAGE_TAG=$tag
dc "$release" "$release/runtime-images.yml" config --quiet
# The backup helper inherits this deployment's lock; failed backup prevents any app replacement.
python3 "$release/script/docker/monolith-ops.py" backup --root "$root" --runtime "$runtime" --lock-fd 9
# The memory protocol and backend are released together. Runtime PTH/Chroma remain pinned.
dc "$release" "$release/runtime-images.yml" build backend nginx mem0
if ! activate "$release" "$release/runtime-images.yml"; then
    if [[ "$mcp_manual_recovery" == true ]]; then echo 'Runner recovery remains unverified; preserve volumes and transition evidence.' >&2; exit 6; fi
    if [[ "$mcp_recovery_done" == true ]]; then echo 'Runner transition was restored; release was not published.' >&2; exit 5; fi
    # Keep startup evidence before replacing the failed container during rollback.
    dc "$release" "$release/runtime-images.yml" logs --no-color --tail 200 backend > "$root/state/failed-$tag-backend.log" 2>&1 || true
    echo 'Deployment health check failed; restoring previous application images.' >&2
    activate "$previous" "$release/previous-images.yml" yes || { echo 'Restoration failed; manual recovery required.' >&2; exit 6; }
    python3 "$runtime_helper" aborted --state "$root/state" --lock-fd 9
    exit 5
fi
python3 "$runtime_helper" publish --state "$root/state" --lock-fd 9 --current "$release" --previous "$previous" --images "$release/previous-images.yml"
python3 "$runtime_helper" finalize --state "$root/state" --lock-fd 9
echo "Release $tag passed application health checks."
python3 "$release/script/docker/monolith-ops.py" prune --root "$root" --runtime "$runtime" --lock-fd 9 --keep 3 --apply \
    || echo 'Application is healthy; old image cleanup needs review.' >&2
