"""MT-14: lô nến ghi thật phải mang danh tính MT5 khớp liên kết ACTIVE. Tiện ích cho test."""

from __future__ import annotations

from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.market.feeds import feed_id_for
from gold_trading.storage.repository import Mt5Link

LOGIN = 51234567
SERVER = "Broker-Demo"
BROKER_SYMBOL = "XAUUSD"
IDENT_FIELDS = {"mt5_login": LOGIN, "mt5_server": SERVER, "mt5_account_type": "DEMO",
                "broker_symbol": BROKER_SYMBOL}
# MT-05: nguồn giá của liên kết mặc định trong test
FEED = feed_id_for(SERVER, BROKER_SYMBOL)


def link_active(repo, account_id: str = "default", login: int = LOGIN, server: str = SERVER,
                trade_mode: str = "DEMO") -> Mt5Link:
    """Tạo liên kết ACTIVE thẳng trong kho (bỏ qua bước USER xác nhận — đã test ở
    ``test_mt5_links.py``)."""
    now = utcnow()
    link = Mt5Link(new_id("mtl"), account_id, login, server, None, trade_mode, "win-1", None,
                   "PENDING_CONFIRM", now)
    assert repo.add_pending_link(link)
    return repo.confirm_link(account_id, link.link_id, "test", now)
