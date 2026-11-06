#!/bin/bash
# Dùng chung cho backup.sh và restore.sh. Không in mật khẩu.
set -euo pipefail
# Bản sao lưu chứa dữ liệu nhạy cảm (DB Keycloak có hash mật khẩu, client secret):
# chỉ chủ sở hữu đọc được.
umask 077
BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP="${GT_BACKUP_KEEP:-14}"

# db_env <app|keycloak>: đặt PGHOST/PGUSER/PGDATABASE/PGPASSWORD cho DB tương ứng
db_env() {
  case "$1" in
    app)
      export PGHOST="${APP_DB_HOST:-db}" PGUSER="${APP_DB_USER:-gold}" \
             PGDATABASE="${APP_DB_NAME:-gold_trading}" PGPASSWORD="${APP_DB_PASSWORD:?thiếu APP_DB_PASSWORD}" ;;
    keycloak)
      export PGHOST="${KC_DB_HOST:-keycloak-db}" PGUSER="${KC_DB_USER:-keycloak}" \
             PGDATABASE="${KC_DB_NAME:-keycloak}" PGPASSWORD="${KC_DB_PASSWORD:?thiếu KC_DB_PASSWORD}" ;;
    *) echo "DB phải là app hoặc keycloak" >&2; return 2 ;;
  esac
}

log() { printf '{"ts":"%s","logger":"backup","msg":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

disk_pct() { df -P "$BACKUP_DIR" | awk 'NR==2 {gsub("%","",$5); print $5}'; }
