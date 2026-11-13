#!/bin/bash
# Kiểm thử cả hệ thống bằng Docker (dùng trong CI, chạy tay cũng được):
#   1. dựng toàn bộ compose với bí mật NGẪU NHIÊN (không ghi ra log)
#   2. e2e_auth.py: đăng nhập qua Keycloak thật, phân quyền, CSRF, token Gateway,
#      ADMIN tạo người dùng (MT-20), break-glass, đăng xuất, brute force
#   3. sao lưu một lần → phá dữ liệu → khôi phục cả hai DB → kiểm tra dữ liệu + đăng nhập lại
#   4. quét log mọi container tìm bí mật
# Yêu cầu: các image gold_trading/* đã build sẵn (docker compose build).
set -euo pipefail
cd "$(dirname "$0")/../.."
WORK="$(mktemp -d)"
PROJECT="gt_ci_$$"
rnd() { python3 -c "import secrets; print(secrets.token_urlsafe(24))"; }
KC_DB_PASSWORD="$(rnd)"; KC_ADMIN_PASSWORD="$(rnd)"; GT_OIDC_CLIENT_SECRET="$(rnd)"
INIT_PW="Init-$(rnd)"; NEW_PW="New-$(rnd)"; LEGACY="$(rnd)$(rnd)"; MEMBER_PW="Mem-$(rnd)"
cat > "$WORK/.env" <<EOF
KC_DB_PASSWORD=$KC_DB_PASSWORD
KC_ADMIN_PASSWORD=$KC_ADMIN_PASSWORD
GT_OIDC_CLIENT_SECRET=$GT_OIDC_CLIENT_SECRET
GT_ADMIN_USERNAME=admin
GT_ADMIN_INITIAL_PASSWORD=$INIT_PW
GT_PUBLIC_URL=http://localhost:8080
GT_INGEST_TOKEN=$LEGACY
GT_BACKUP_DIR=$WORK/backups
GT_DATA_SOURCE=SAMPLE
GT_MULTI_USER_ENABLED=1
EOF
DC="docker compose -p $PROJECT --env-file $WORK/.env"
cleanup() { $DC logs --no-color > "$WORK/all.log" 2>&1 || true; $DC down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

wait_healthy() {
  for _ in $(seq 1 60); do
    s="$($DC ps --format '{{.Service}}={{.Health}}' | tr '\n' ' ')"
    if [[ "$s" == *"keycloak=healthy"* && "$s" == *"backend=healthy"* ]]; then return 0; fi
    sleep 5
  done
  echo "Dịch vụ không healthy: $s" >&2
  $DC logs --tail 50 >&2
  return 1
}

echo "== 1. Dựng hệ thống"
$DC up -d --no-build
wait_healthy

echo "== 2. Đăng nhập đầu-cuối"
python3 ops/scripts/e2e_auth.py --base http://localhost:8080 --user admin \
  --initial-password "$INIT_PW" --new-password "$NEW_PW" --legacy-token="$LEGACY" --compose "$DC" \
  --member-password "$MEMBER_PW"

echo "== 3. Sao lưu → phá → khôi phục"
Q() { $DC exec -T db psql -U gold -d gold_trading -Atc "$1"; }
# Nến mẫu (SAMPLE) tự sinh mỗi 15 phút: chỉ đếm nến nạp TRƯỚC lúc sao lưu, nếu không lần chạy
# trùng mốc 15 phút sẽ hỏng ngẫu nhiên (CI run 76, 2026-11-12: 5873 → 5874 qua mốc 16:15).
T0="$(Q 'select now()')"
$DC exec -T backup /usr/local/bin/gt/backup.sh once 2>&1 | grep -v "pg_dump:" || true
CANDLES="select count(*) from candles where ingested_at <= '$T0'"
before="$(Q 'select count(*) from audit_log'):$(Q 'select count(*) from account_members'):$(Q "$CANDLES")"
Q "drop table account_members cascade" >/dev/null
$DC stop backend keycloak
$DC run --rm -T backup restore app latest 2>&1 | grep -v "pg_restore: \(warning\|detail\|hint\)"
$DC run --rm -T backup restore keycloak latest
$DC up -d --no-build
wait_healthy
after="$(Q 'select count(*) from audit_log'):$(Q 'select count(*) from account_members'):$(Q "$CANDLES")"
echo "trước=$before sau=$after (nến nạp trước $T0)"
[ "$before" = "$after" ] || { echo "LỖI: dữ liệu sau khôi phục không khớp" >&2; exit 1; }
if Q "update audit_log set actor='x'" >/dev/null 2>&1; then echo "LỖI: mất trigger append-only" >&2; exit 1; fi
# Bỏ khóa brute force do bước 2 để đăng nhập lại kiểm tra DB Keycloak đã khôi phục
$DC exec -T keycloak bash -c 'K=/opt/keycloak/bin/kcadm.sh; $K config credentials --config /tmp/c --server http://127.0.0.1:8080/auth --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1; $K delete attack-detection/brute-force/users --config /tmp/c -r gold-trading'
python3 ops/scripts/e2e_auth.py --base http://localhost:8080 --user admin \
  --initial-password "$NEW_PW" --new-password "$NEW_PW" --legacy-token="$LEGACY" > "$WORK/e2e2.log"
tail -1 "$WORK/e2e2.log"

echo "== 4. Quét log tìm bí mật"
$DC logs --no-color > "$WORK/all.log" 2>&1
leak=0
for s in "$KC_DB_PASSWORD" "$KC_ADMIN_PASSWORD" "$GT_OIDC_CLIENT_SECRET" "$INIT_PW" "$NEW_PW" "$LEGACY" \
         "$MEMBER_PW" "${MEMBER_PW}N2"; do
  if grep -qF -- "$s" "$WORK/all.log"; then leak=1; echo "LỖI: một bí mật xuất hiện trong log" >&2; fi
done
if grep -qE "gtk_[A-Za-z0-9_-]{20,}" "$WORK/all.log"; then leak=1; echo "LỖI: token Gateway trong log" >&2; fi
[ "$leak" = 0 ] && echo "Không có bí mật trong log"
exit "$leak"
