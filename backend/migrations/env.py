import os

from alembic import context
from sqlalchemy import create_engine

from gold_trading.storage.schema import metadata

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL chưa được đặt")


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
