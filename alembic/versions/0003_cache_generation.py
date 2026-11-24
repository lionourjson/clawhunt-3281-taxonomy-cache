"""Give each dictionary a fresh Redis namespace after an upgrade."""
from alembic import op
import sqlalchemy as sa

revision = "0003_cache_generation"
down_revision = "0002_dictionary_version"


def upgrade():
    op.add_column(
        "dictionary",
        sa.Column("cache_generation", sa.Uuid, nullable=False, server_default=sa.func.gen_random_uuid()),
    )


def downgrade():
    op.drop_column("dictionary", "cache_generation")
