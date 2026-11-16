// KN-26: Content-Security-Policy trong nginx.conf phải khớp script nội tuyến của index.html.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(__dirname, "..");
const nginx = readFileSync(resolve(root, "nginx.conf"), "utf8");
const html = readFileSync(resolve(root, "index.html"), "utf8");

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
  it("mọi script nội tuyến của index.html có băm sha256 trong script-src", () => {
    const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
    expect(inline.length).toBeGreaterThan(0);
    const allowed = csp()["script-src"];
    for (const code of inline) {
      const h = `'sha256-${createHash("sha256").update(code, "utf8").digest("base64")}'`;
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
