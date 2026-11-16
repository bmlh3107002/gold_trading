// KN-26: Content-Security-Policy trong nginx.conf phải khớp script nội tuyến của index.html.
import { describe, expect, it } from "vitest";
import html from "../index.html?raw";
import nginx from "../nginx.conf?raw";

async function sha256b64(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

function csp(): Record<string, string[]> {
  const m = nginx.match(/add_header Content-Security-Policy "([^"]+)" always;/);
  expect(m, "thiếu Content-Security-Policy ở nginx.conf").not.toBeNull();
  const out: Record<string, string[]> = {};
  for (const part of m![1].split(";")) {
    const [name, ...vals] = part.trim().split(/\s+/);
    if (name) out[name] = vals;
  }
  return out;
}

describe("KN-26 Content-Security-Policy", () => {
  it("mọi script nội tuyến của index.html có băm sha256 trong script-src", async () => {
    const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
    expect(inline.length).toBeGreaterThan(0);
    const allowed = csp()["script-src"];
    for (const code of inline) {
      const h = `'sha256-${await sha256b64(code)}'`;
      expect(allowed, "sửa script nội tuyến → cập nhật băm trong nginx.conf").toContain(h);
    }
  });

  it("chính sách chặt: không unsafe-inline / unsafe-eval cho script, chỉ cùng nguồn", () => {
    const p = csp();
    expect(p["default-src"]).toEqual(["'self'"]);
    expect(p["script-src"]).not.toContain("'unsafe-inline'");
    expect(p["script-src"]).not.toContain("'unsafe-eval'");
    expect(p["connect-src"]).toEqual(["'self'"]);
    expect(p["object-src"]).toEqual(["'none'"]);
    expect(p["frame-ancestors"]).toEqual(["'none'"]);
    expect(p["base-uri"]).toEqual(["'self'"]);
  });

  it("CSP ở cấp server (áp cho trang + /api/), /auth/ (Keycloak) không bị CSP của trang", () => {
    const server = nginx.slice(0, nginx.indexOf("location /api/"));
    expect(server).toContain("Content-Security-Policy");
    const auth = nginx.slice(nginx.indexOf("location /auth/"), nginx.indexOf("location / {"));
    expect(auth).not.toContain("Content-Security-Policy");
  });
});
