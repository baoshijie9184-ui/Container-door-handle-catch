#!/bin/sh
set -eu
# JAVA_OPTS 按 JVM 参数分词，不经过 eval；禁用通配符展开。
set -f
export TZ=Asia/Shanghai
exec java ${JAVA_OPTS:-} -Duser.timezone=Asia/Shanghai -jar /app/app.jar "$@"
