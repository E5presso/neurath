"""Migrate only the connection explicitly supplied by CoreDatabase.initialize."""

from alembic import context

from neurath.infrastructure.core_schema import metadata

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=metadata,
    version_table="core_schema_revision",
    transactional_ddl=True,
)
with context.begin_transaction():
    context.run_migrations()
