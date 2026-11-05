"""Xuất OpenAPI ra contracts/openapi.json để frontend sinh type TypeScript."""

import json
from pathlib import Path

from gold_trading.api.app import create_app

out = Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n")
print(f"wrote {out}")
