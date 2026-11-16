"""Chuỗi migration Alembic (KN-20): một nhánh duy nhất, nối liền; mọi index trong ``schema.py`` đều
được tạo bởi một migration (quên migration → DB thật thiếu index, test vẫn xanh trên SQLite)."""

import re
from pathlib import Path

from gold_trading.storage.schema import metadata

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _chain():
    revs = {}
    for p in VERSIONS.glob("*.py"):
        s = p.read_text()
        rev = re.search(r'^revision = "([^"]+)"', s, re.M).group(1)
        down = re.search(r'^down_revision = (None|"([^"]+)")', s, re.M).group(2)
        revs[rev] = down
    return revs


def test_single_linear_head():
    revs = _chain()
    downs = [d for d in revs.values() if d is not None]
    assert len(downs) == len(set(downs)), "hai migration cùng nối vào một revision (rẽ nhánh)"
    heads = set(revs) - set(downs)
    assert len(heads) == 1, heads
    assert sum(d is None for d in revs.values()) == 1
    assert heads == {max(revs)}


def test_every_schema_index_has_a_migration():
    text = "\n".join(p.read_text() for p in VERSIONS.glob("*.py"))
    missing = [ix.name for t in metadata.tables.values() for ix in t.indexes
               if ix.name and ix.name not in text]
    assert missing == []


def test_kn20_expires_index_in_schema():
    ix = {i.name: [c.name for c in i.columns] for i in metadata.tables["analyst_outputs"].indexes}
    assert ix["ix_analyst_outputs_expires_at"] == ["expires_at"]
