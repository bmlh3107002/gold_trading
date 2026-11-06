#!/bin/bash
# Khôi phục một DB từ bản sao lưu.
#   docker compose stop backend keycloak
#   docker compose run --rm backup restore app latest          # hoặc tên file cụ thể
#   docker compose run --rm backup restore keycloak latest
#   docker compose up -d
# An toàn: kiểm tra SHA-256; TỪ CHỐI nếu còn kết nối khác tới DB (backend/keycloak chưa dừng).
# Sau khi khôi phục, backend khởi động theo quy tắc ACTIVE→PAUSED: Safety không bao giờ tự ACTIVE.
source /usr/local/bin/gt/common.sh
db="${1:-}"; which="${2:-latest}"
[ "$db" = "app" ] || [ "$db" = "keycloak" ] || { echo "Dùng: restore app|keycloak latest|<tên file>" >&2; exit 2; }
dir="$BACKUP_DIR/$db"
if [ "$which" = "latest" ]; then
  file="$(ls -1t "$dir"/"$db"-*.dump 2>/dev/null | head -n 1 || true)"
else
  file="$dir/$(basename "$which")"
fi
[ -n "$file" ] && [ -f "$file" ] || { echo "Không tìm thấy bản sao lưu ($which) trong $dir" >&2; exit 1; }
[ -f "$file.sha256" ] || { echo "Thiếu file kiểm tra $file.sha256: không khôi phục" >&2; exit 1; }
expected="$(awk '{print $1}' "$file.sha256")"
actual="$(sha256sum "$file" | awk '{print $1}')"
[ -n "$expected" ] && [ "$expected" = "$actual" ] || { echo "SHA-256 KHÔNG KHỚP: file hỏng, không khôi phục" >&2; exit 1; }
pg_restore --list "$file" > /dev/null || { echo "File không đọc được bằng pg_restore" >&2; exit 1; }

db_env "$db"
target="$PGDATABASE"
# Chỉ đếm kết nối của ứng dụng (bỏ worker nền của TimescaleDB).
others="$(psql -d postgres -Atc "SELECT count(*) FROM pg_stat_activity WHERE datname = '$target' AND pid <> pg_backend_pid() AND backend_type = 'client backend'")"
if [ "$others" != "0" ]; then
  echo "Còn $others kết nối tới DB $target. Chạy trước: docker compose stop backend keycloak" >&2
  exit 1
fi
log "Khôi phục $db từ $(basename "$file")"
psql -d postgres -v ON_ERROR_STOP=1 -qc "DROP DATABASE IF EXISTS \"$target\" WITH (FORCE)" -c "CREATE DATABASE \"$target\" OWNER \"$PGUSER\""
if [ "$db" = "app" ]; then
  psql -d "$target" -v ON_ERROR_STOP=1 -qc "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()" > /dev/null
  pg_restore --no-owner -d "$target" "$file"
  psql -d "$target" -v ON_ERROR_STOP=1 -qc "SELECT timescaledb_post_restore()" > /dev/null
else
  pg_restore --no-owner -d "$target" "$file"
fi
log "Khôi phục $db xong. Chạy: docker compose up -d"
