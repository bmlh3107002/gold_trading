"""Kiểm tra file realm: JSON hợp lệ, các thiết lập an toàn bắt buộc, KHÔNG chứa bí mật thật.

Mọi giá trị bí mật (client secret, mật khẩu) phải là placeholder ${BIẾN_MÔI_TRƯỜNG}.
Chạy: python3 ops/keycloak/check_realm.py ops/keycloak/realm/gold-trading-realm.json
"""

from __future__ import annotations

import json
import re
import sys

PLACEHOLDER = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def check(realm: dict) -> list[str]:
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(realm.get("bruteForceProtected") is True, "bruteForceProtected phải bật")
    need(realm.get("registrationAllowed") is False, "registrationAllowed phải tắt")
    need(realm.get("sslRequired") in ("external", "all"), "sslRequired phải là external/all")
    need(realm.get("ssoSessionMaxLifespan") == 28800, "ssoSessionMaxLifespan phải là 8 giờ")
    need(realm.get("ssoSessionIdleTimeout") == 1800, "ssoSessionIdleTimeout phải là 30 phút")
    roles = [r["name"] for r in realm.get("roles", {}).get("realm", [])]
    need("ADMIN" in roles, "thiếu realm role ADMIN")

    clients = {c["clientId"]: c for c in realm.get("clients", [])}
    c = clients.get("gold-trading-dashboard")
    need(c is not None, "thiếu client gold-trading-dashboard")
    if c:
        need(c.get("publicClient") is False, "client phải là confidential")
        need(c.get("implicitFlowEnabled") is False, "implicit flow phải tắt")
        need(c.get("directAccessGrantsEnabled") is False, "password grant phải tắt")
        need(
            c.get("attributes", {}).get("pkce.code.challenge.method") == "S256",
            "PKCE S256 bắt buộc",
        )
        need(PLACEHOLDER.match(str(c.get("secret", ""))) is not None, "client secret phải là ${VAR}")
        need(c.get("serviceAccountsEnabled") is True, "service account (MT-20) phải bật")
        need("kc-admin-api" in c.get("optionalClientScopes", [])
             and "kc-admin-api" not in c.get("defaultClientScopes", []),
             "kc-admin-api phải là scope TÙY CHỌN (token người dùng không mang quyền Admin API)")
        for uri in c.get("redirectUris", []):
            need("*" not in uri, f"redirect URI không được có ký tự đại diện: {uri}")

    sa = [u for u in realm.get("users", []) if u.get("serviceAccountClientId")]
    need(len(sa) == 1 and sa[0].get("serviceAccountClientId") == "gold-trading-dashboard",
         "cần đúng một service account cho gold-trading-dashboard")
    for u in sa:
        need(not u.get("realmRoles"), "service account không được có realm role")
        roles = u.get("clientRoles", {})
        need(set(roles) <= {"realm-management"}
             and set(roles.get("realm-management", [])) == {"manage-users", "view-users"},
             "service account chỉ được manage-users + view-users")
    for u in realm.get("users", []):
        for cred in u.get("credentials", []):
            need(
                PLACEHOLDER.match(str(cred.get("value", ""))) is not None,
                f"mật khẩu của {u.get('username')} phải là ${{VAR}}",
            )
            need(cred.get("temporary") is True, "mật khẩu khởi tạo phải là tạm thời")
    return errors


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        errs = check(json.load(f))
    for e in errs:
        print("LỖI:", e)
    if errs:
        sys.exit(1)
    print("Realm OK")
