"""Xuất OpenAPI ra contracts/openapi.json để frontend sinh type TypeScript."""

import json
from pathlib import Path

from gold_trading.api.app import create_app
from gold_trading.auth.config import AuthConfig
from gold_trading.storage.repository import InMemoryRepository

# Cấu hình giả chỉ để dựng app và đọc schema; không kết nối Keycloak.
AUTH = AuthConfig(
    public_url="http://localhost:8080",
    internal_issuer_url="http://keycloak:8080/auth/realms/gold-trading",
    client_id="gold-trading-dashboard",
    client_secret="schema-export-only-not-a-secret",
)

out = Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"
schema = create_app(InMemoryRepository(), auth=AUTH).openapi()
out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
print(f"wrote {out}")
