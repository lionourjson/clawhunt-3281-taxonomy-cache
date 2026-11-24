from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey,
    ForeignKeyConstraint, MetaData, String, Table, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()


def standard_columns():
    return (
        Column("id", Uuid, primary_key=True),
        Column("org_id", Uuid, nullable=False),
        Column("site_id", Uuid, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("created_by", Uuid, nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("deleted_at", DateTime(timezone=True)),
    )


dictionary = Table(
    "dictionary", metadata, *standard_columns(),
    Column("version", BigInteger, nullable=False, server_default=text("1")),
    Column("cache_generation", Uuid, nullable=False, server_default=func.gen_random_uuid()),
    CheckConstraint("version >= 1", name="ck_dictionary_version"),
    UniqueConstraint("id", "org_id", "site_id", name="uq_dictionary_scope"),
)

tag = Table(
    "tag", metadata, *standard_columns(),
    Column("dictionary_id", Uuid, nullable=False),
    Column("code", String(64), nullable=False),
    Column("label", String(128), nullable=False),
    Column("status", String(16), nullable=False),
    Column("parent_id", Uuid, ForeignKey("tag.id")),
    Column("merged_into", Uuid, ForeignKey("tag.id")),
    Column("aliases", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    ForeignKeyConstraint(
        ("dictionary_id", "org_id", "site_id"), ("dictionary.id", "dictionary.org_id", "dictionary.site_id"),
        name="fk_tag_dictionary_scope",
    ),
    UniqueConstraint("dictionary_id", "code", name="uq_tag_dictionary_code"),
    CheckConstraint("status IN ('pending', 'active', 'inactive', 'merged')", name="ck_tag_status"),
)
