#!/bin/bash
set -euo pipefail
# 在服务器项目根目录执行，只允许导入空的演示库；不删除或覆盖现有表。
snapshot=${1:?Usage: restore-demo-snapshot.sh database.sql.gz [runtime-files.tar.gz]}
runtime_archive=${2:-}
test -f "$snapshot"
dc=(docker compose --env-file deploy/cloud.env -f compose.monolith.yml -f compose.cloud.yml)
table_count=$("${dc[@]}" exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -N -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()"')
if [ "$table_count" != 0 ]; then
    echo 'Refusing to restore: target database is not empty.' >&2
    exit 2
fi
gzip -dc "$snapshot" | "${dc[@]}" exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql --default-character-set=utf8mb4 -u"$MYSQL_USER" "$MYSQL_DATABASE"'
if [ -n "$runtime_archive" ]; then
    test -f "$runtime_archive"
    "${dc[@]}" run --rm --no-deps -T --user 0 --entrypoint sh backend -ec '
      mkdir -p /tmp/doorhandle-restore
      tar -xzf - -C /tmp/doorhandle-restore
      if [ -d /tmp/doorhandle-restore/uploads ]; then cp -a /tmp/doorhandle-restore/uploads/. /app/uploads/; fi
      if [ -d /tmp/doorhandle-restore/agent-workspace ]; then cp -a /tmp/doorhandle-restore/agent-workspace/. /app/.agentscope/workspace/; fi
      chown -R 10001:10001 /app/uploads /app/.agentscope/workspace
    ' < "$runtime_archive"
fi
"${dc[@]}" exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -N -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT COUNT(*) AS restored_tables FROM information_schema.tables WHERE table_schema=DATABASE()"'
