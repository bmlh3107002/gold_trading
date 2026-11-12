"""Kiểm thử đầu-cuối với Keycloak THẬT (OPS-07/14/15/17, MT-04): chạy sau `docker compose up`.

    python3 ops/scripts/e2e_auth.py --base http://localhost:8080 \
        --user admin --initial-password ... --new-password ... --legacy-token ...

Chỉ dùng thư viện chuẩn. Tự quản cookie (cookiejar chuẩn không gửi cookie Secure qua
http://localhost, còn trình duyệt thì có). Không in mật khẩu/token/cookie.
Bước brute force chạy CUỐI vì nó khóa tạm tài khoản.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class Browser:
    """Trình duyệt tối giản: theo redirect, giữ cookie theo host (bỏ qua cờ Secure ở localhost)."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cookies: dict[str, dict[str, str]] = {}

    def _host(self, url: str) -> str:
        return urllib.parse.urlsplit(url).netloc

    def request(self, method: str, url: str, body: bytes | None = None,
                headers: dict[str, str] | None = None, follow: bool = True):
        url = urllib.parse.urljoin(self.base + "/", url)
        for _ in range(15):
            h = dict(headers or {})
            jar = self.cookies.get(self._host(url), {})
            if jar:
                h["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
            req = urllib.request.Request(url, data=body, method=method, headers=h)
            try:
                resp = OPENER.open(req, timeout=20)
                status, rh, data = resp.status, resp.headers, resp.read()
            except urllib.error.HTTPError as e:
                status, rh, data = e.code, e.headers, e.read()
            for sc in rh.get_all("Set-Cookie") or []:
                c = SimpleCookie()
                c.load(sc)
                for k, m in c.items():
                    host_jar = self.cookies.setdefault(self._host(url), {})
                    if m["max-age"] == "0" or m.value == "":
                        host_jar.pop(k, None)
                    else:
                        host_jar[k] = m.value
            if follow and status in (301, 302, 303, 307) and rh.get("Location"):
                url = urllib.parse.urljoin(url, rh["Location"])
                method, body = "GET", None
                headers = {}
                continue
            return status, data.decode("utf-8", "replace"), url
        raise RuntimeError("quá nhiều redirect")

    def api(self, method: str, path: str, payload=None, origin: str | None = "default",
            token: str | None = None):
        headers = {"Content-Type": "application/json"}
        if origin == "default":
            headers["Origin"] = self.base
        elif origin:
            headers["Origin"] = origin
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(payload).encode() if payload is not None else None
        status, text, _ = self.request(method, path, body, headers, follow=False)
        try:
            return status, json.loads(text) if text else None
        except json.JSONDecodeError:
            return status, text


def form_action(page: str) -> str:
    m = re.search(r'<form[^>]+action="([^"]+)"', page)
    if not m:
        raise AssertionError("Không thấy form trên trang Keycloak")
    return html.unescape(m.group(1))


def post_form(b: Browser, action: str, fields: dict[str, str]):
    return b.request("POST", action, urllib.parse.urlencode(fields).encode(),
                     {"Content-Type": "application/x-www-form-urlencoded"})


def login(b: Browser, user: str, password: str, new_password: str | None = None):
    status, page, url = b.request("GET", "/api/auth/login?next=/")
    assert status == 200 and "/auth/realms/gold-trading/" in url, (status, url)
    status, page, url = post_form(b, form_action(page), {"username": user, "password": password})
    if "password-new" in page:
        assert new_password, "Keycloak yêu cầu đổi mật khẩu"
        status, page, url = post_form(b, form_action(page), {
            "password-new": new_password, "password-confirm": new_password,
        })
    if "VERIFY_PROFILE" in url or ('name="firstName"' in page and 'name="email"' in page):
        # Lần đăng nhập đầu: Keycloak yêu cầu bổ sung email + họ tên
        status, page, url = post_form(b, form_action(page), {
            "email": f"{user}@example.invalid", "firstName": "E2E", "lastName": user,
        })
    return status, page, url


CHECKS: list[tuple[str, bool]] = []


def frame_options(base: str, path: str) -> list[str]:
    """Các header X-Frame-Options thật sự trả về (không theo redirect)."""
    req = urllib.request.Request(base.rstrip("/") + path, method="GET")
    try:
        resp = OPENER.open(req, timeout=20)
        rh = resp.headers
    except urllib.error.HTTPError as e:
        rh = e.headers
    return [v.strip().upper() for v in (rh.get_all("X-Frame-Options") or [])]


def check(name: str, ok: bool) -> None:
    CHECKS.append((name, ok))
    print(("  OK  " if ok else "  LỖI ") + name)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8080")
    p.add_argument("--user", default="admin")
    p.add_argument("--initial-password", required=True)
    p.add_argument("--new-password", required=True)
    p.add_argument("--legacy-token", required=True)
    p.add_argument("--member-password", default="",
                   help="mật khẩu tạm cho người dùng tạo trên Dashboard (MT-20); trống = bỏ qua")
    p.add_argument("--compose", default="", help="tiền tố lệnh docker compose (để chạy break-glass)")
    a = p.parse_args()

    # Trang quản trị Keycloak cần tự nhúng (SAMEORIGIN); Dashboard vẫn cấm nhúng (DENY).
    check("Dashboard cấm nhúng iframe (X-Frame-Options DENY)",
          frame_options(a.base, "/") == ["DENY"])
    check("Trang quản trị Keycloak cho nhúng cùng origin (SAMEORIGIN, một header)",
          frame_options(a.base, "/auth/admin/master/console/") == ["SAMEORIGIN"])

    b = Browser(a.base)
    s, _ = b.api("GET", "/api/auth/me")
    check("Chưa đăng nhập → /api/auth/me 401", s == 401)
    s, _ = b.api("GET", "/api/accounts/default/status")
    check("Chưa đăng nhập → API tài khoản 401", s == 401)

    status, page, url = login(b, a.user, a.initial_password, a.new_password)
    check("Đăng nhập qua Keycloak thật (đổi mật khẩu lần đầu) → về Dashboard",
          urllib.parse.urlsplit(url).path == "/" and "auth_error" not in url)
    jar = b.cookies.get(urllib.parse.urlsplit(a.base).netloc, {})
    check("Có cookie phiên __Host-gt_session", "__Host-gt_session" in jar)

    s, me = b.api("GET", "/api/auth/me")
    check("/api/auth/me trả đúng người, có ADMIN", s == 200 and me["username"] == a.user
          and me["is_admin"] is True)
    # DEC-16: ADMIN chỉ quản lý tài khoản, không có / không vào tài khoản giao dịch nào
    s, accs = b.api("GET", "/api/accounts")
    check("ADMIN không có tài khoản giao dịch nào", s == 200 and accs == [])
    s, _ = b.api("GET", "/api/accounts/default/status")
    check("ADMIN không xem được tài khoản giao dịch → 404", s == 404)
    s, _ = b.api("POST", "/api/admin/kill-switch", {"reason_code": "E2E"})
    check("Kill switch trên Dashboard đã bỏ (chỉ còn break-glass CLI)", s in (404, 405))
    s, users = b.api("GET", "/api/admin/users")
    check("ADMIN xem danh sách USER", s == 200 and isinstance(users, list))
    # DEC-17: một USER một dòng; price_feed = MT5 của người đó cấp giá (tài khoản "default")
    default_owned = s == 200 and any(u["price_feed"] for u in users)

    hb = {"gateway_id": "e2e", "gateway_version": "e2e", "read_only": True,
          "terminal_connected": True, "account_type": "DEMO", "server_tz": "Europe/Athens"}
    s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=a.legacy_token)
    if default_owned:
        check("Token cũ đã bị thay (đã có USER nhận Tài khoản chính) → 401", s == 401)
    else:
        check("Token cũ GT_INGEST_TOKEN còn chạy trước khi có USER đầu tiên", s == 200)

    temp_passwords: list[str] = []
    if a.member_password:
        uname = f"e2e{int(time.time()) % 1000000}"
        new_user = {"username": uname, "email": f"{uname}@example.invalid", "first_name": "E2E",
                    "last_name": "Member", "password": a.member_password}
        s, cu = b.api("POST", "/api/admin/users", new_user)
        check("ADMIN tạo USER: KHÔNG tự sinh token (DEC-17: USER xin, ADMIN cấp)",
              s == 201 and "gateway" not in cu)
        sub = cu["sub"] if s == 201 else ""
        s, cred = b.api("POST", f"/api/admin/users/{sub}/gateway-token")
        acc = cred.get("account_id") if s == 200 else ""
        expected = f"u-{uname}" if default_owned else "default"
        tok = cred.get("token", "") if s == 200 else ""
        check("ADMIN cấp token cho tài khoản giao dịch riêng của USER",
              s == 200 and acc == expected and tok.startswith("gtk_"))
        s, _ = b.api("POST", "/api/admin/users", new_user)
        check("Tạo trùng tên đăng nhập → 409", s == 409)
        s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=tok)
        check("Token Gateway của USER dùng được ngay", s == 200)
        if acc == "default":
            s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None,
                         token=a.legacy_token)
            check("Token cũ hết hiệu lực khi USER nhận Tài khoản chính", s == 401)
        s, users = b.api("GET", "/api/admin/users")
        row = next((u for u in users if u["username"] == uname), None) if s == 200 else None
        check("Danh sách: USER ACTIVE, Gateway CONNECTED, không lộ token",
              row is not None and row["status"] == "ACTIVE"
              and row["gateway_status"] == "CONNECTED" and tok not in str(users))

        m = Browser(a.base)
        status, page, url = login(m, uname, a.member_password, a.member_password + "N2")
        check("USER đăng nhập (bắt đổi mật khẩu tạm) → về Dashboard",
              urllib.parse.urlsplit(url).path == "/" and "auth_error" not in url)
        s, me2 = m.api("GET", "/api/auth/me")
        check("USER không phải ADMIN", s == 200 and me2["is_admin"] is False)
        s, accs2 = m.api("GET", "/api/accounts")
        check("USER chỉ thấy tài khoản của mình",
              s == 200 and [x["account_id"] for x in accs2] == [acc])
        s, _ = m.api("POST", f"/api/accounts/{acc}/safety",
                     {"action": "halt", "reason_code": "E2E"}, origin="https://evil.example")
        check("Request ghi từ origin lạ → 403", s == 403)
        s, _ = m.api("POST", f"/api/accounts/{acc}/safety",
                     {"action": "halt", "reason_code": "E2E"}, origin=None)
        check("Request ghi thiếu Origin → 403", s == 403)
        s, st = m.api("POST", f"/api/accounts/{acc}/safety",
                      {"action": "resume", "reason_code": "E2E", "operator_approved": True})
        check("USER mở lại (có xác nhận), cùng origin → ACTIVE",
              s == 200 and st["safety_state"] == "ACTIVE")
        s, aud = m.api("GET", f"/api/accounts/{acc}/audit")
        check("Audit ghi actor theo phiên", s == 200 and any(
            e["action"] == "safety.resume" and e["actor"] == uname for e in aud))
        s, _ = m.api("GET", "/api/admin/users")
        check("USER không vào được trang quản trị → 403", s == 403)

        # DEC-17: USER xin cấp lại token → ADMIN thấy → từ chối (token đang dùng giữ nguyên)
        s, ti = m.api("POST", f"/api/accounts/{acc}/gateway/token-request")
        check("USER xin cấp lại token → PENDING", s == 200 and ti["request_status"] == "PENDING")
        s, users = b.api("GET", "/api/admin/users")
        row = next((u for u in users if u["sub"] == sub), None) if s == 200 else None
        check("ADMIN thấy yêu cầu xin token", row is not None and row["token_requested_at"])
        s, _ = b.api("POST", f"/api/admin/users/{sub}/gateway-token/reject")
        s2, ti = m.api("GET", f"/api/accounts/{acc}/gateway/token")
        check("ADMIN từ chối → USER thấy REJECTED, token cũ vẫn chạy",
              s == 204 and s2 == 200 and ti["request_status"] == "REJECTED"
              and b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=tok)[0] == 200)
        # DEC-17: ADMIN sửa email/họ/tên trên Keycloak thật (gửi lại bản đầy đủ)
        new_email = f"{uname}.moi@example.invalid"
        s, ed = b.api("PUT", f"/api/admin/users/{sub}",
                      {"email": new_email, "first_name": "E2E", "last_name": "Sua"})
        check("ADMIN sửa thông tin USER",
              s == 200 and ed["email"] == new_email and ed["display_name"] == "E2E Sua")

        # Khóa: Keycloak + backend + Gateway
        s, lk = b.api("POST", f"/api/admin/users/{sub}/lock")
        check("ADMIN khóa USER (Keycloak đã cập nhật)",
              s == 200 and lk["status"] == "LOCKED" and lk["keycloak_synced"] is True)
        s, _ = m.api("GET", "/api/auth/me")
        check("USER bị khóa: phiên cũ bị thu hồi → 401", s == 401)
        s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=tok)
        check("USER bị khóa: Gateway bị từ chối → 403", s == 403)
        m2 = Browser(a.base)
        status, page, url = login(m2, uname, a.member_password + "N2")
        check("USER bị khóa không đăng nhập được",
              urllib.parse.urlsplit(url).path != "/" or "auth_error" in url)
        s, ul = b.api("POST", f"/api/admin/users/{sub}/unlock")
        check("ADMIN mở khóa USER", s == 200 and ul["status"] == "ACTIVE")
        s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=tok)
        check("Mở khóa: token cũ dùng lại được", s == 200)
        # Đặt lại mật khẩu: mật khẩu tạm mới, bắt đổi, token giữ nguyên
        s, rp = b.api("POST", f"/api/admin/users/{sub}/reset-password")
        pw = rp.get("temporary_password", "") if s == 200 else ""
        temp_passwords.append(pw)
        check("ADMIN đặt lại mật khẩu (mật khẩu tạm ≥ 12 ký tự)", s == 200 and len(pw) >= 12)
        m3 = Browser(a.base)
        status, page, url = login(m3, uname, pw, a.member_password + "N2")
        check("USER đăng nhập bằng mật khẩu tạm (bắt đổi) → về Dashboard",
              urllib.parse.urlsplit(url).path == "/" and "auth_error" not in url)
        s, st = m3.api("GET", f"/api/accounts/{acc}/status")
        check("Sau mở khóa + đặt lại mật khẩu: bot không tự chạy (Mode vẫn PAPER)",
              s == 200 and st["mode"] == "PAPER")
        s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=tok)
        check("Đặt lại mật khẩu không đổi token Gateway", s == 200)

        # Break-glass: HALT bằng CLI, backend đang chạy nhận trạng thái
        if a.compose:
            cmd = a.compose.split() + ["exec", "-T", "backend", "gt-break-glass", "halt",
                                       "--all", "--reason", "E2E"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            check("gt-break-glass halt --all chạy được", r.returncode == 0)
            time.sleep(3)
            s, st = m3.api("GET", f"/api/accounts/{acc}/status")
            check("Backend đang chạy thấy HALTED từ CLI",
                  s == 200 and st["safety_state"] == "HALTED")
            logs = subprocess.run(a.compose.split() + ["logs", "--no-color"],
                                  capture_output=True, text=True, timeout=120).stdout
            check("Mật khẩu tạm không xuất hiện trong log",
                  all(p and p not in logs for p in temp_passwords))

        # DEC-17: xóa USER. USER này đang cấp giá hoặc Gateway đang kết nối → từ chối
        s, _ = b.api("DELETE", f"/api/admin/users/{sub}")
        check("Xóa USER đang cấp giá / Gateway đang kết nối → 409", s == 409)
        s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=tok)
        check("Xóa bị từ chối: token Gateway vẫn chạy", s == 200)
        # USER thứ hai (tài khoản riêng, chưa có Gateway kết nối) → xóa được
        u2 = {**new_user, "username": uname + "x", "email": f"{uname}x@example.invalid"}
        s, c2 = b.api("POST", "/api/admin/users", u2)
        sub2 = c2["sub"] if s == 201 else ""
        s, cred2 = b.api("POST", f"/api/admin/users/{sub2}/gateway-token")
        tok2 = cred2.get("token", "") if s == 200 else ""
        check("Tạo USER thứ hai + cấp token", bool(sub2) and tok2.startswith("gtk_"))
        s, dr = b.api("DELETE", f"/api/admin/users/{sub2}")
        check("Xóa USER (Keycloak đã xóa)", s == 200 and dr["keycloak_synced"] is True
              and dr["tokens_revoked"] == 1)
        s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=tok2)
        check("USER đã xóa: token Gateway bị thu hồi → 401", s == 401)
        s, users = b.api("GET", "/api/admin/users")
        check("USER đã xóa không còn trong danh sách",
              s == 200 and all(u["sub"] != sub2 for u in users))
        m4 = Browser(a.base)
        status, page, url = login(m4, u2["username"], a.member_password)
        check("USER đã xóa không đăng nhập được",
              urllib.parse.urlsplit(url).path != "/" or "auth_error" in url)

    # Đăng xuất cả phía Keycloak
    s, lo = b.api("POST", "/api/auth/logout")
    check("Đăng xuất trả URL Keycloak", s == 200 and "/protocol/openid-connect/logout" in
          lo["logout_url"])
    status, _, url = b.request("GET", lo["logout_url"])
    s, _ = b.api("GET", "/api/auth/me")
    check("Sau đăng xuất → 401", s == 401)
    status, page, url = b.request("GET", "/api/auth/login?next=/")
    check("Phiên SSO Keycloak cũng đã kết thúc (phải nhập lại mật khẩu)",
          "/auth/realms/gold-trading/" in url and 'name="password"' in page)

    # Brute force (0-C08): sai 5 lần → mật khẩu ĐÚNG cũng bị từ chối tạm thời
    bf = Browser(a.base)
    for _ in range(6):
        login(bf, a.user, "wrong-password-xyz")
    status, page, url = login(bf, a.user, a.new_password)
    check("Brute force: sau nhiều lần sai, đăng nhập đúng cũng bị khóa tạm",
          "/api/auth/callback" not in url and urllib.parse.urlsplit(url).path != "/")

    failed = [n for n, ok in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} kiểm tra đạt")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
