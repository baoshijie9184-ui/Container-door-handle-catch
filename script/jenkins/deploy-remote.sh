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
exec 9>"$root/state/deploy.lock"
flock -n 9 || { echo 'Another deployment is in progress.' >&2; exit 3; }

dc() {
    local dir=$1 override=$2
    shift 2
    docker compose --project-name "$project" --env-file "$envfile" \
        -f "$dir/compose.monolith.yml" -f "$dir/compose.cloud.yml" -f "$dir/compose.detection.yml" \
        -f "$override" "$@"
}

# Snapshot actual running image IDs, independent of a mutable tag or private env APP_IMAGE_TAG.
snapshot() {
    local file=$1 mode=$2 service cid image health
    printf 'services:\n' > "$file"
    for service in backend nginx mysql redis kafka mem0 chroma detection-worker; do
        cid=$(docker ps -aq --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=$service")
        [[ -n "$cid" && "$cid" != *$'\n'* ]] || { echo "Expected one existing $service container." >&2; return 1; }
        health=$(docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$cid")
        [[ "$health" == running/healthy ]] || { echo "$service is not healthy: $health" >&2; return 1; }
        image=$(docker inspect --format '{{.Image}}' "$cid")
        [[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]] || return 1
        if [[ "$mode" == all || "$service" == mem0 || "$service" == chroma || "$service" == detection-worker ]]; then
            printf '  %s:\n    image: %s\n' "$service" "$image" >> "$file"
        fi
    done
}

activate() {
    local dir=$1 images=$2
    # No dependencies or initializer jobs are recreated; databases and worker remain untouched.
    dc "$dir" "$images" up -d --no-deps --no-build --pull never --wait --wait-timeout 240 backend || return 1
    dc "$dir" "$images" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 90 nginx || return 1
    dc "$dir" "$images" exec -T backend curl -fsS http://127.0.0.1:8080/actuator/health >/dev/null || return 1
    dc "$dir" "$images" exec -T nginx wget -q -O /dev/null http://127.0.0.1/nginx-health || return 1
}

if [[ "$action" == rollback ]]; then
    [[ -s "$root/state/previous-directory" && -s "$root/state/previous-images.yml" ]] || { echo 'No previous successful release recorded.' >&2; exit 4; }
    previous=$(cat "$root/state/previous-directory")
    [[ "$previous" == "$runtime" || "$previous" == "$root/releases/"* ]] || exit 2
    current=$(cat "$root/state/current-directory")
    snapshot "$root/state/rollback-current.yml" all
    if ! activate "$previous" "$root/state/previous-images.yml"; then
        echo 'Rollback health check failed; restoring current images.' >&2
        activate "$current" "$root/state/rollback-current.yml" || { echo 'Current release restoration also failed; manual recovery required.' >&2; exit 6; }
        exit 5
    fi
    cp "$root/state/rollback-current.yml" "$root/state/previous-images.yml"
    printf '%s\n' "$current" > "$root/state/previous-directory"
    printf '%s\n' "$previous" > "$root/state/current-directory"
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
# Only backend and web are rebuilt. Runtime PTH/Mem0 images are explicitly pinned above.
dc "$release" "$release/runtime-images.yml" build backend nginx
if ! activate "$release" "$release/runtime-images.yml"; then
    echo 'Deployment health check failed; restoring previous application images.' >&2
    activate "$previous" "$release/previous-images.yml" || { echo 'Restoration failed; manual recovery required.' >&2; exit 6; }
    exit 5
fi
cp "$release/previous-images.yml" "$root/state/previous-images.yml"
printf '%s\n' "$previous" > "$root/state/previous-directory"
printf '%s\n' "$release" > "$root/state/current-directory"
echo "Release $tag passed application health checks."
