from os import environ

from alembic import context
from sqlalchemy import create_engine

from app.taxonomy.models import metadata


def run():
    url = environ["DATABASE_URL"]
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            context.configure(connection=conn, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run()
