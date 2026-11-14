"""GĐ3 bước 6 (NEWS-02..04, DEC-08): sổ gọi Claude cho News analyst — chỉ thêm.

Mỗi dòng = một lần gọi (kể cả lỗi / từ chối): chi phí theo tháng (ngân sách 20 USD) tính từ bảng
này; kết quả trích xuất kèm phiên bản prompt + mô hình. Trigger chặn UPDATE + DELETE.
Thiết kế: docs/thiet-ke/32-news-analyst.md

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_llm_calls",
        sa.Column("call_id", sa.String(64), primary_key=True),
        sa.Column("story_key", sa.String(256), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("served_model", sa.String(64)),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("request_id", sa.String(128)),
        sa.Column("result", JSONB()),
        sa.CheckConstraint("status IN ('OK', 'REFUSED', 'ERROR', 'INVALID_OUTPUT', 'TRUNCATED')",
                           name="ck_news_llm_calls_status"),
        sa.CheckConstraint("attempt >= 1", name="ck_news_llm_calls_attempt"),
        sa.UniqueConstraint("story_key", "prompt_version", "model", "attempt",
                            name="uq_news_llm_calls_attempt"),
    )
    op.create_index("ix_news_llm_calls_created", "news_llm_calls", ["created_at"])
    op.create_index("ix_news_llm_calls_story", "news_llm_calls", ["story_key"])
    op.execute("CREATE TRIGGER news_llm_calls_append_only BEFORE UPDATE OR DELETE "
               "ON news_llm_calls FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS news_llm_calls_append_only ON news_llm_calls;")
    op.drop_index("ix_news_llm_calls_story", table_name="news_llm_calls")
    op.drop_index("ix_news_llm_calls_created", table_name="news_llm_calls")
    op.drop_table("news_llm_calls")
