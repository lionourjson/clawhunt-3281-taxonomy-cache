"""Standalone dictionary and tag tables for the local integration stub."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_standalone_schema"
down_revision = None


def fields():
    return (
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, nullable=False),
        sa.Column("site_id", sa.Uuid, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )


def upgrade():
    op.create_table(
        "dictionary", *fields(), sa.UniqueConstraint("id", "org_id", "site_id", name="uq_dictionary_scope"),
    )
    op.create_table(
        "tag", *fields(),
        sa.Column("dictionary_id", sa.Uuid, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("parent_id", sa.Uuid, sa.ForeignKey("tag.id")),
        sa.Column("merged_into", sa.Uuid, sa.ForeignKey("tag.id")),
        sa.Column("aliases", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(
            ("dictionary_id", "org_id", "site_id"), ("dictionary.id", "dictionary.org_id", "dictionary.site_id"),
            name="fk_tag_dictionary_scope",
        ),
        sa.UniqueConstraint("dictionary_id", "code", name="uq_tag_dictionary_code"),
        sa.CheckConstraint("status IN ('pending', 'active', 'inactive', 'merged')", name="ck_tag_status"),
    )


def downgrade():
    op.drop_table("tag")
    op.drop_table("dictionary")
