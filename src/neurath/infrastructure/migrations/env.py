"""Migrations run only on the transaction owned by Database.initialize()."""

from alembic import context

from neurath.infrastructure.models import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("An explicit database transaction is required")
context.configure(connection=connection, target_metadata=Base.metadata, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
