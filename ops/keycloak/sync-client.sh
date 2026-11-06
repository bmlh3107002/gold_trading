#!/bin/bash
# Đồng bộ client "gold-trading-dashboard" với .env SAU KHI realm đã được nhập:
# - redirect URI / post-logout theo GT_PUBLIC_URL (khi đổi địa chỉ truy cập)
# - client secret theo GT_OIDC_CLIENT_SECRET (khi xoay secret)
# - theme trang đăng nhập "cutlotdesk" (realm cài trước khi có theme)
# - service account của client: chỉ manage-users + view-users, để ADMIN tạo người dùng
#   trên Dashboard (MT-20). Không cấp realm-admin hay realm role nào.
# Keycloak chỉ nhập realm một lần, nên đổi .env về sau phải chạy script này:
#   docker compose exec keycloak /opt/keycloak/bin/sync-client.sh
# Không in bí mật ra màn hình.
set -euo pipefail
: "${GT_PUBLIC_URL:?thiếu GT_PUBLIC_URL}"
: "${GT_OIDC_CLIENT_SECRET:?thiếu GT_OIDC_CLIENT_SECRET}"
KCADM=/opt/keycloak/bin/kcadm.sh
CFG=$(mktemp)
trap 'rm -f "$CFG"' EXIT
$KCADM config credentials --config "$CFG" --server http://127.0.0.1:8080/auth --realm master \
  --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null
ID=$($KCADM get clients --config "$CFG" -r gold-trading -q clientId=gold-trading-dashboard --fields id --format csv --noquotes)
[ -n "$ID" ] || { echo "Không tìm thấy client gold-trading-dashboard" >&2; exit 1; }
URL="${GT_PUBLIC_URL%/}"
$KCADM update "clients/$ID" --config "$CFG" -r gold-trading \
  -s "rootUrl=$URL" \
  -s "redirectUris=[\"$URL/api/auth/callback\"]" \
  -s "attributes.\"post.logout.redirect.uris\"=$URL/" \
  -s "secret=$GT_OIDC_CLIENT_SECRET" \
  -s serviceAccountsEnabled=true
$KCADM add-roles --config "$CFG" -r gold-trading \
  --uusername service-account-gold-trading-dashboard \
  --cclientid realm-management --rolename manage-users --rolename view-users
# Keycloak ≥ 26.8: token Admin API cần scope kc-admin-api (TÙY CHỌN: backend tự xin khi cần)
SID=$($KCADM get client-scopes --config "$CFG" -r gold-trading --fields id,name --format csv \
  --noquotes | grep ",kc-admin-api$" | cut -d, -f1)
[ -n "$SID" ] || { echo "Không tìm thấy client scope kc-admin-api" >&2; exit 1; }
$KCADM update "clients/$ID/optional-client-scopes/$SID" --config "$CFG" -r gold-trading
$KCADM update realms/gold-trading --config "$CFG" -s loginTheme=cutlotdesk
echo "Đã đồng bộ client: địa chỉ $URL, client secret theo .env (không in ra), theme đăng nhập cutlotdesk, quyền tạo người dùng cho backend."
