"""MT-05: nguồn giá theo (server broker, symbol broker) — không trộn giá giữa các broker (DEC-14).

1. Bảng ``price_feeds`` (chỉ thêm dòng).
2. ``candles``, ``candle_quarantine``, ``analyst_outputs`` thêm cột ``feed_id`` (mặc định ""
   = nguồn không gắn broker: SAMPLE/CSV). Khóa chính ``candles`` thêm ``feed_id``.
3. Nến / cách ly / kết quả analyst MT5 có từ trước (không biết thuộc broker nào) →
   ``feed_id = 'legacy-unknown-broker'``: giữ lại để tra cứu, KHÔNG tài khoản nào đọc. Gateway
   nạp bù lại lịch sử vào đúng nguồn sau khi liên kết (mặc định an toàn: không đoán broker).
4. ``mt5_links.broker_symbol``: symbol broker khóa ở lô nến đầu tiên được ghi.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

LEGACY = "legacy-unknown-broker"


def upgrade() -> None:
    op.create_table(
        "price_feeds",
        sa.Column("feed_id", sa.String(64), primary_key=True),
        sa.Column("mt5_server", sa.String(256), nullable=False),
        sa.Column("broker_symbol", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        "CREATE TRIGGER price_feeds_append_only BEFORE UPDATE OR DELETE ON price_feeds "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    )
    op.add_column("mt5_links", sa.Column("broker_symbol", sa.String(64)))
    for table in ("candles", "candle_quarantine", "analyst_outputs"):
        op.add_column(table, sa.Column("feed_id", sa.String(64), nullable=False,
                                       server_default=""))
    # Gắn nhãn dữ liệu MT5 cũ. Bảng append-only: tắt trigger đúng trong lúc gắn nhãn.
    for table in ("candles", "candle_quarantine", "analyst_outputs"):
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_append_only")
        op.execute(f"UPDATE {table} SET feed_id = '{LEGACY}' WHERE source = 'MT5'")
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_append_only")
    op.drop_constraint("candles_pkey", "candles", type_="primary")
    op.create_primary_key("candles_pkey", "candles",
                          ["symbol", "timeframe", "source", "feed_id", "open_time", "revision"])
    op.drop_index("ix_analyst_outputs_lookup", "analyst_outputs")
    op.create_index("ix_analyst_outputs_lookup", "analyst_outputs",
                    ["analyst_id", "symbol", "timeframe", "source", "feed_id", "as_of"])


def downgrade() -> None:
    # Không gộp được nến của nhiều nguồn về một khóa cũ mà không mất dữ liệu: chỉ hạ cấp khi
    # mọi nến MT5 đều cùng một feed (hoặc không có nến MT5).
    conn = op.get_bind()
    n = conn.execute(sa.text(
        "SELECT count(DISTINCT feed_id) FROM candles WHERE source = 'MT5'")).scalar()
    if n and n > 1:
        raise RuntimeError("Có nến của nhiều nguồn giá: không hạ cấp được 0009 an toàn")
    op.drop_index("ix_analyst_outputs_lookup", "analyst_outputs")
    op.create_index("ix_analyst_outputs_lookup", "analyst_outputs",
                    ["analyst_id", "symbol", "timeframe", "source", "as_of"])
    op.drop_constraint("candles_pkey", "candles", type_="primary")
    op.create_primary_key("candles_pkey", "candles",
                          ["symbol", "timeframe", "source", "open_time", "revision"])
    for table in ("candles", "candle_quarantine", "analyst_outputs"):
        op.drop_column(table, "feed_id")
    op.drop_column("mt5_links", "broker_symbol")
    op.execute("DROP TRIGGER IF EXISTS price_feeds_append_only ON price_feeds;")
    op.drop_table("price_feeds")
