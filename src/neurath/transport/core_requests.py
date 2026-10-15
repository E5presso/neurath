"""Composition boundary for future CLI and native hook adapters.

This is an internal Python API, not a generic operation dispatcher or another
public command. It does not register hooks, trust identities, or initialize DBs.
"""

from pathlib import Path

from neurath.application.core import Core
from neurath.infrastructure.core_database import CoreDatabase
from neurath.infrastructure.project_location import LocalProjects


def build_core(database_path: Path | None = None) -> Core:
    return Core(CoreDatabase(database_path), LocalProjects())
