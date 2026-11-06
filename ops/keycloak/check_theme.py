"""Kiểm tra theme đăng nhập AurumDesk của Keycloak.

- theme.properties kế thừa keycloak.v2 và nạp đủ file CSS/JS khai báo;
- realm dùng loginTheme "aurumdesk"; sync-client.sh đặt lại theme cho realm đã cài;
- màu trong aurumdesk.css khớp frontend/src/styles/tokens.css (cùng tên biến, cả sáng và tối);
- JS chỉ đọc đúng khóa localStorage của Dashboard, không gọi mạng.

Chạy từ gốc repo: python3 ops/keycloak/check_theme.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "ops/keycloak/themes/aurumdesk/login"
TOKENS = ROOT / "frontend/src/styles/tokens.css"
REALM = ROOT / "ops/keycloak/realm/gold-trading-realm.json"
SYNC = ROOT / "ops/keycloak/sync-client.sh"
DOCKERFILE = ROOT / "ops/keycloak/Dockerfile"

VAR = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;]+);")


def blocks(css: str, selector_re: str) -> dict[str, str]:
    """Gộp biến CSS của mọi khối có selector khớp ``selector_re`` (khối sau đè khối trước)."""
    out: dict[str, str] = {}
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        sel = " ".join(m.group(1).split())
        if re.fullmatch(selector_re, sel):
            out.update({k: v.strip().lower() for k, v in VAR.findall(m.group(2))})
    return out


def props(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def check() -> list[str]:
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    p = props(THEME / "theme.properties")
    need(p.get("parent") == "keycloak.v2", "theme phải kế thừa keycloak.v2")
    need(p.get("darkMode") == "false", "darkMode phải tắt (sáng/tối theo data-theme)")
    styles = p.get("styles", "").split()
    need(styles[:1] == ["css/styles.css"], "styles phải giữ css/styles.css của theme cha ở đầu")
    for res in styles[1:] + p.get("scripts", "").split():
        need((THEME / "resources" / res).is_file(), f"thiếu file {res}")

    for lang in ("vi", "en"):
        msgs = props(THEME / f"messages/messages_{lang}.properties")
        need("AURUM" in msgs.get("loginTitleHtml", ""), f"messages_{lang}: thiếu logo loginTitleHtml")

    realm = json.loads(REALM.read_text(encoding="utf-8"))
    need(realm.get("loginTheme") == "aurumdesk", "realm phải đặt loginTheme=aurumdesk")
    need("loginTheme=aurumdesk" in SYNC.read_text(encoding="utf-8"), "sync-client.sh phải đặt loginTheme")
    need("themes/aurumdesk" in DOCKERFILE.read_text(encoding="utf-8"), "Dockerfile phải chép theme")

    js = (THEME / "resources/js/aurumdesk-theme.js").read_text(encoding="utf-8")
    need('"aurumdesk.theme"' in js, "JS phải đọc khóa localStorage aurumdesk.theme")
    need(
        not re.search(r"fetch|XMLHttpRequest|sendBeacon|WebSocket|import\(", js),
        "JS không được gọi mạng",
    )

    tokens = TOKENS.read_text(encoding="utf-8")
    theme_css = (THEME / "resources/css/aurumdesk.css").read_text(encoding="utf-8")
    for mode, fe_sel, kc_sel in (
        ("tối", r':root, :root\[data-theme="dark"\]', r'html\.login-pf, html\.login-pf\[data-theme="dark"\]'),
        ("sáng", r':root\[data-theme="light"\]', r'html\.login-pf\[data-theme="light"\]'),
    ):
        fe = blocks(tokens, fe_sel)
        kc = blocks(theme_css, kc_sel)
        need(bool(fe) and bool(kc), f"không tìm thấy khối token {mode}")
        for name, value in kc.items():
            if name in fe and fe[name] != value:
                errors.append(f"màu {mode} --{name}: theme {value} ≠ frontend {fe[name]}")
        shared = set(kc) & set(fe)
        need(len(shared) >= 10, f"quá ít token {mode} dùng chung với frontend ({len(shared)})")
    return errors


if __name__ == "__main__":
    errs = check()
    for e in errs:
        print("LỖI:", e)
    print("Theme AurumDesk: OK" if not errs else f"{len(errs)} lỗi")
    sys.exit(1 if errs else 0)
