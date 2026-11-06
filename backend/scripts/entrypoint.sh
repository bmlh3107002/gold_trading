#!/bin/sh
# Khởi động backend trong container: chạy migration rồi mới phục vụ API.
set -e

if [ -n "$DATABASE_URL" ]; then
  echo "Chạy migration database..."
  i=0
  until alembic upgrade head; do
    i=$((i + 1))
    if [ "$i" -ge 10 ]; then
      echo "Không migrate được database sau $i lần thử" >&2
      exit 1
    fi
    echo "Database chưa sẵn sàng, thử lại sau 3 giây ($i/10)..."
    sleep 3
  done
else
  echo "DATABASE_URL chưa đặt: chạy với bộ nhớ (restart sẽ mất trạng thái)"
fi

# --no-access-log: access log do backend tự ghi (JSON, không có query string, che bí mật).
exec uvicorn --factory gold_trading.api.app:create_app --host 0.0.0.0 --port 8000 \
  --no-access-log
