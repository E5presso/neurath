"""Declarative metadata shared by this package's persistent records."""

from sqlalchemy.orm import DeclarativeBase


class DatabaseModel(DeclarativeBase):
    """Base for typed ORM mappings; schema creation is managed only by Alembic."""
