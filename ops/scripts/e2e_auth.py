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
    p.add_argument("--compose", default="", help="tiền tố lệnh docker compose (để chạy break-glass)")
    a = p.parse_args()

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
    s, accs = b.api("GET", "/api/accounts")
    check("ADMIN đầu tiên là OWNER tài khoản default",
          s == 200 and any(x["account_id"] == "default" and x["role"] == "OWNER" for x in accs))

    s, _ = b.api("POST", "/api/accounts/default/safety",
                 {"action": "halt", "reason_code": "E2E"}, origin="https://evil.example")
    check("Request ghi từ origin lạ → 403", s == 403)
    s, _ = b.api("POST", "/api/accounts/default/safety", {"action": "halt", "reason_code": "E2E"},
                 origin=None)
    check("Request ghi thiếu Origin → 403", s == 403)
    s, st = b.api("POST", "/api/accounts/default/safety",
                  {"action": "resume", "reason_code": "E2E", "operator_approved": True})
    check("OWNER mở lại (có xác nhận), cùng origin → ACTIVE",
          s == 200 and st["safety_state"] == "ACTIVE")
    s, aud = b.api("GET", "/api/accounts/default/audit")
    check("Audit ghi actor theo phiên", s == 200 and any(
        e["action"] == "safety.resume" and e["actor"] == a.user for e in aud))

    # Token Gateway: token cũ chạy tới khi xoay
    hb = {"gateway_id": "e2e", "gateway_version": "e2e", "read_only": True,
          "terminal_connected": True, "account_type": "DEMO", "server_tz": "Europe/Athens"}
    _, info = b.api("GET", "/api/accounts/default/gateway/token")
    s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=a.legacy_token)
    if info["legacy_token_active"]:
        check("Token cũ GT_INGEST_TOKEN còn chạy trước lần xoay đầu tiên", s == 200)
    else:
        check("Token cũ đã bị vô hiệu (đã xoay ở lần trước) → 401", s == 401)
    s, issued = b.api("POST", "/api/accounts/default/gateway/token")
    tok = issued["token"] if s == 200 else ""
    check("Xoay token Gateway", s == 200 and tok.startswith("gtk_"))
    s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=a.legacy_token)
    check("Token cũ hết hiệu lực ngay sau khi xoay", s == 401)
    s, _ = b.api("POST", "/api/ingest/mt5/heartbeat", hb, origin=None, token=tok)
    check("Token mới dùng được", s == 200)

    # Break-glass: HALT bằng CLI, backend đang chạy nhận trạng thái
    if a.compose:
        cmd = a.compose.split() + ["exec", "-T", "backend", "gt-break-glass", "halt", "--all",
                                   "--reason", "E2E"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        check("gt-break-glass halt --all chạy được", r.returncode == 0)
        time.sleep(3)
        s, st = b.api("GET", "/api/accounts/default/status")
        check("Backend đang chạy thấy HALTED từ CLI", s == 200 and st["safety_state"] == "HALTED")

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
