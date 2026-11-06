#!/bin/bash
# Sao lưu định kỳ hai DB ra thư mục BACKUP_DIR (bind mount ra máy người dùng).
#   backup.sh loop     chạy nền: sau GT_BACKUP_START_DELAY_S giây (mặc định 300), sao lưu nếu bản
#                      gần nhất đã cũ, rồi mỗi GT_BACKUP_INTERVAL_HOURS giờ
#   backup.sh once     sao lưu một lần rồi thoát
#   backup.sh restore  chuyển sang restore.sh (xem restore.sh)
# Mỗi bản: file .dump (pg_dump -Fc) + .sha256. Ghi ra file tạm, kiểm tra bằng pg_restore --list,
# rồi mới đổi tên: bản dở dang không bao giờ mang tên hợp lệ. Giữ GT_BACKUP_KEEP bản mỗi DB.
source /usr/local/bin/gt/common.sh
INTERVAL_H="${GT_BACKUP_INTERVAL_HOURS:-24}"

dump_one() {
  local db="$1" dir="$BACKUP_DIR/$1" ts tmp final
  mkdir -p "$dir"
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  final="$dir/$db-$ts.dump"
  tmp="$dir/.tmp-$db-$ts.dump"
  ( db_env "$db"
    pg_dump -Fc --no-password -f "$tmp" )
  pg_restore --list "$tmp" > /dev/null
  ( cd "$dir" && sha256sum "$(basename "$tmp")" | sed "s/$(basename "$tmp")/$(basename "$final")/" > "$final.sha256" )
  mv "$tmp" "$final"
  # Xoay vòng: giữ KEEP bản mới nhất
  ls -1t "$dir"/"$db"-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
    rm -f "$old" "$old.sha256"
  done
  echo "$final"
}

write_status() {
  local result="$1" detail="$2" app_file="$3" kc_file="$4"
  local tmp="$BACKUP_DIR/.status.json.tmp"
  printf '{"result":"%s","detail":"%s","finished_at":"%s","app_file":"%s","keycloak_file":"%s","app_count":%s,"keycloak_count":%s,"disk_used_pct":%s,"interval_hours":%s,"keep":%s}\n' \
    "$result" "$detail" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$app_file")" "$(basename "$kc_file")" \
    "$(ls -1 "$BACKUP_DIR"/app/app-*.dump 2>/dev/null | wc -l)" \
    "$(ls -1 "$BACKUP_DIR"/keycloak/keycloak-*.dump 2>/dev/null | wc -l)" \
    "$(disk_pct)" "$INTERVAL_H" "$KEEP" > "$tmp"
  chmod 644 "$tmp"  # backend (chỉ đọc, user khác) cần đọc file trạng thái
  mv "$tmp" "$BACKUP_DIR/status.json"
}

run_once() {
  mkdir -p "$BACKUP_DIR"
  rm -f "$BACKUP_DIR"/app/.tmp-* "$BACKUP_DIR"/keycloak/.tmp-* 2>/dev/null || true
  local app kc
  if ! app="$(dump_one app)"; then
    log "Sao lưu DB ứng dụng THẤT BẠI"; write_status FAILED "app dump failed" "" ""; return 1
  fi
  if ! kc="$(dump_one keycloak)"; then
    log "Sao lưu DB Keycloak THẤT BẠI"; write_status FAILED "keycloak dump failed" "$app" ""; return 1
  fi
  write_status OK "" "$app" "$kc"
  log "Sao lưu xong: $(basename "$app"), $(basename "$kc"); ổ đĩa $(disk_pct)%"
  if [ "$(disk_pct)" -gt 85 ]; then log "CẢNH BÁO: ổ chứa bản sao lưu đã dùng $(disk_pct)%"; fi
}

is_due() {
  local latest
  latest="$(ls -1t "$BACKUP_DIR"/app/app-*.dump 2>/dev/null | head -n 1 || true)"
  [ -z "$latest" ] && return 0
  [ "$(( $(date +%s) - $(stat -c %Y "$latest") ))" -ge "$(( INTERVAL_H * 3600 ))" ]
}

case "${1:-loop}" in
  once) run_once ;;
  restore) shift; exec /usr/local/bin/gt/restore.sh "$@" ;;
  loop)
    log "Bắt đầu: mỗi ${INTERVAL_H} giờ, giữ ${KEEP} bản mỗi DB, thư mục $BACKUP_DIR"
    # Đợi các dịch vụ khởi tạo xong (Keycloak tạo bảng, backend chạy migration) rồi mới sao lưu.
    sleep "${GT_BACKUP_START_DELAY_S:-300}"
    while true; do
      if is_due; then run_once || log "Sẽ thử lại sau 15 phút"; fi
      sleep 900
    done ;;
  *) echo "Dùng: backup.sh loop|once|restore ..." >&2; exit 2 ;;
esac
