#!/bin/sh
set -eu
fail() { echo "LANGFUSE_PREFLIGHT_REJECTED:$1"; exit 42; }
case "${LANGFUSE_RESOURCE_MODE:-}" in
  production) [ "${LANGFUSE_RESOURCE_APPROVED:-}" = production-reviewed ] || fail approval; min_total_kib=33554432; min_available_kib=25165824; min_disk_kib=31457280 ;;
  isolated-smoke) [ "${LANGFUSE_RESOURCE_APPROVED:-}" = isolated-smoke-reviewed ] || fail approval; min_total_kib=8388608; min_available_kib=6291456; min_disk_kib=12582912 ;;
  *) fail mode ;;
esac
for name in LF_DATABASE_URL LF_POSTGRES_PASSWORD LF_CLICKHOUSE_PASSWORD LF_REDIS_PASSWORD LF_SALT LF_ENCRYPTION_KEY LF_NEXTAUTH_SECRET LF_S3_BUCKET LF_S3_ENDPOINT LF_S3_REGION LF_S3_ACCESS_KEY_ID LF_S3_SECRET_ACCESS_KEY LF_INIT_ORG_ID LF_INIT_PROJECT_ID LF_INIT_PROJECT_PUBLIC_KEY LF_INIT_PROJECT_SECRET_KEY LF_INIT_USER_EMAIL LF_INIT_USER_PASSWORD; do
  value=$(printenv "$name" || true)
  [ -n "$value" ] || fail missing_configuration
done
for name in LF_POSTGRES_PASSWORD LF_CLICKHOUSE_PASSWORD LF_REDIS_PASSWORD LF_SALT LF_NEXTAUTH_SECRET LF_INIT_USER_PASSWORD; do
  value=$(printenv "$name")
  [ "${#value}" -ge 24 ] || fail weak_configuration
done
[ "${#LF_ENCRYPTION_KEY}" -eq 64 ] || fail encryption_key
case "$LF_ENCRYPTION_KEY" in *[!a-fA-F0-9]*) fail encryption_key;; esac
case "$LF_S3_ENDPOINT" in https://*) ;; *) fail storage_tls;; esac
total=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
available=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
disk=$(df -Pk /data | awk 'NR==2 {print $4}')
[ "$total" -ge "$min_total_kib" ] || fail memory_total
[ "$available" -ge "$min_available_kib" ] || fail memory_available
[ "$disk" -ge "$min_disk_kib" ] || fail disk_free
echo LANGFUSE_RESOURCE_GATE_PASSED
