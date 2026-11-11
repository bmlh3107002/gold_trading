"""MT-05: kết quả analyst duy nhất theo (feed_id, output_id), không còn theo output_id.

``output_id`` băm từ nội dung đầu vào. Hai broker có thể có nến GIỐNG HỆT nhau (cùng nhà cung
cấp thanh khoản): trước đây kết quả của nguồn thứ hai bị coi là trùng và không được lưu → tài
khoản đó không bao giờ có kết quả analyst (tìm được khi soát MT-05 phần đọc).

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("analyst_outputs_output_id_key", "analyst_outputs", type_="unique")
    op.create_unique_constraint("uq_analyst_outputs_feed_output", "analyst_outputs",
                                ["feed_id", "output_id"])


def downgrade() -> None:
    conn = op.get_bind()
    dup = conn.execute(sa.text(
        "SELECT count(*) FROM (SELECT output_id FROM analyst_outputs GROUP BY output_id "
        "HAVING count(*) > 1) d")).scalar()
    if dup:
        raise RuntimeError("Có kết quả analyst trùng output_id ở nhiều nguồn: không hạ cấp được")
    op.drop_constraint("uq_analyst_outputs_feed_output", "analyst_outputs", type_="unique")
    op.create_unique_constraint("analyst_outputs_output_id_key", "analyst_outputs", ["output_id"])
