"""Add the version counter and backfill existing dictionaries to version 1."""
from alembic import op
import sqlalchemy as sa

revision = "0002_dictionary_version"
down_revision = "0001_standalone_schema"


def upgrade():
    op.add_column("dictionary", sa.Column("version", sa.BigInteger, nullable=False, server_default=sa.text("1")))
    op.create_check_constraint("ck_dictionary_version", "dictionary", "version >= 1")


def downgrade():
    op.drop_constraint("ck_dictionary_version", "dictionary", type_="check")
    op.drop_column("dictionary", "version")
