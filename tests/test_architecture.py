"""Positive and negative fixtures for each mechanically enforceable review requirement."""

import subprocess
import sys
from pathlib import Path

import pytest

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.services.project_locator import IProjectLocator
from neurath.application.ports.usecases.register_session import IRegisterSessionUseCase
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.infrastructure.project_locator import GitProjectLocator
from neurath.infrastructure.repositories.project import ProjectRepository
from neurath.infrastructure.repositories.session import SessionRepository
from tools.architecture import ArchitectureChecker, check_tree


@pytest.mark.parametrize(
    ("module", "source", "rule"),
    [
        (
            "neurath.application.bad",
            "from typing import Protocol as P\nclass Contract(P): pass",
            "FORBIDDEN_TYPE",
        ),
        (
            "neurath.application.bad",
            "import typing as t\nAlias = t.Protocol\nclass Contract(Alias): pass",
            "FORBIDDEN_TYPE",
        ),
        (
            "neurath.domain.state",
            'from typing_extensions import Literal as L\nState = L["a", "b"]',
            "FORBIDDEN_TYPE",
        ),
        (
            "neurath.domain.state",
            'import typing\ntype State = typing.Literal["a", "b"]',
            "FORBIDDEN_TYPE",
        ),
        ("neurath.application.bad", "from typing import Any as A\nvalue: A", "FORBIDDEN_TYPE"),
        ("neurath.application.bad", "import typing as t\nvalue = t.cast(str, 1)", "FORBIDDEN_TYPE"),
        ("neurath.application.bad", "class UnitOfWork: pass", "TRANSACTION_WRAPPER"),
        ("neurath.application.bad", "class CustomUow: pass", "TRANSACTION_WRAPPER"),
        (
            "neurath.infrastructure.database",
            "class Storage:\n def commit(self): pass",
            "TRANSACTION_WRAPPER",
        ),
        (
            "neurath.infrastructure.database",
            "from contextlib import contextmanager as cm\n@cm\ndef scope(): yield 1",
            "TRANSACTION_WRAPPER",
        ),
        ("neurath.application.core", "class Core: pass", "CORE"),
        ("neurath.domain.project", "import sqlalchemy as sa", "DOMAIN_BOUNDARY"),
        (
            "neurath.domain.project",
            "from ..infrastructure.database import SqliteDatabase",
            "DOMAIN_BOUNDARY",
        ),
        (
            "neurath.domain.project",
            "from neurath.application.usecases import anything",
            "DOMAIN_BOUNDARY",
        ),
        (
            "neurath.application.usecases.change",
            "from neurath.infrastructure.database import SqliteDatabase",
            "APPLICATION_BOUNDARY",
        ),
        (
            "neurath.infrastructure.repository",
            "from neurath.transport import session_requests",
            "INFRASTRUCTURE_BOUNDARY",
        ),
        (
            "neurath.application.ports.repositories.project",
            "class IProjectRepository: pass",
            "NOMINAL_PORT",
        ),
        (
            "neurath.application.ports.repositories.project",
            "from abc import ABC\nclass IProjectRepository(ABC):\n def get(self): pass",
            "ABSTRACT_METHOD",
        ),
        (
            "neurath.infrastructure.repositories.project",
            "class ProjectRepository:\n def get(self): pass",
            "NOMINAL_IMPLEMENTATION",
        ),
        (
            "neurath.application.usecases.register",
            "class RegisterSessionUseCase: pass",
            "NOMINAL_IMPLEMENTATION",
        ),
        (
            "neurath.infrastructure.models.project",
            'from sqlalchemy import Table as T\nrecord = T("projects")',
            "DECLARATIVE_ORM",
        ),
        (
            "neurath.infrastructure.models.project",
            "import sqlalchemy as sa\nColumnAlias = sa.Column\nvalue = ColumnAlias()",
            "DECLARATIVE_ORM",
        ),
        (
            "neurath.infrastructure.models.project",
            "registry.map_imperatively(Project, table)",
            "DECLARATIVE_ORM",
        ),
        (
            "neurath.infrastructure.models.project",
            'class Project:\n __tablename__ = "project"',
            "DECLARATIVE_ORM",
        ),
        (
            "neurath.infrastructure.models.project",
            'from sqlalchemy.orm import DeclarativeBase\nclass Project(DeclarativeBase):\n __tablename__ = "project"\n id: str = "unmapped"',
            "MAPPED_COLUMN",
        ),
        (
            "neurath.infrastructure.models.project",
            'from sqlalchemy.orm import DeclarativeBase, mapped_column\nclass Project(DeclarativeBase):\n __tablename__ = "project"\n id = mapped_column()',
            "MAPPED_COLUMN",
        ),
        ("neurath.domain.project", "class Project:\n def _private(self): pass", "DOCSTRING"),
        ("neurath.domain.project", "value: str = 1 # type: ignore[assignment]", "SUPPRESSION"),
        ("neurath.domain.project", "from enum import *", "EXPLICIT_IMPORT"),
    ],
)
def test_invalid_architecture_fixture_fails(module, source, rule):
    errors = ArchitectureChecker({module: '"""Fixture module."""\n' + source}).check()
    assert any(f" {rule}:" in error for error in errors), errors


def test_aliases_and_indirect_nominal_inheritance_are_resolved_across_modules():
    sources = {
        "neurath.application.ports.repositories.project": '''"""Project contract."""
from abc import ABC as AbstractBase, abstractmethod as abstract
class IProjectRepository(AbstractBase):
    """Project persistence contract."""
    @abstract
    def get(self, project_id: str) -> str:
        """Read an existing project."""
        raise NotImplementedError
''',
        "neurath.infrastructure.base_repository": '''"""Reusable explicit base."""
from neurath.application.ports.repositories.project import IProjectRepository as Contract
class BaseRepository(Contract):
    """Intermediate nominal implementation."""
    def get(self, project_id: str) -> str:
        """Return the fixture value."""
        return project_id
''',
        "neurath.infrastructure.repositories.project": '''"""Concrete project adapter."""
from neurath.infrastructure.base_repository import BaseRepository as Parent
class ProjectRepository(Parent):
    """Explicitly inherit the contract through the base."""
''',
        "neurath.infrastructure.models.base": '''"""ORM metadata."""
from sqlalchemy.orm import DeclarativeBase as D
class Base(D):
    """Typed metadata base."""
''',
        "neurath.infrastructure.models.project": '''"""Project ORM fixture."""
from sqlalchemy.orm import Mapped as M, mapped_column as column
from neurath.infrastructure.models.base import Base as Parent
class ProjectModel(Parent):
    """Typed declarative persistence record."""
    __tablename__ = "project"
    id: M[str] = column(primary_key=True)
''',
    }
    assert ArchitectureChecker(sources).check() == []


def test_indirect_protocol_alias_cannot_hide_forbidden_base():
    sources = {
        "neurath.application.alias": '"""Alias."""\nimport typing as t\nParent = t.Protocol',
        "neurath.application.ports.repositories.project": '"""Port."""\nfrom neurath.application.alias import Parent as P\nclass IProjectRepository(P):\n """Bad protocol."""',
    }
    errors = ArchitectureChecker(sources).check()
    assert any("FORBIDDEN_TYPE" in error for error in errors)
    assert any("NOMINAL_PORT" in error for error in errors)


def test_repository_and_usecase_contracts_are_nominal_and_abstract():
    for interface in (
        IProjectRepository,
        ISessionRepository,
        IProjectLocator,
        IRegisterSessionUseCase,
    ):
        with pytest.raises(TypeError):
            interface()
    assert issubclass(ProjectRepository, IProjectRepository)
    assert issubclass(SessionRepository, ISessionRepository)
    assert issubclass(GitProjectLocator, IProjectLocator)
    assert issubclass(RegisterSessionUseCase, IRegisterSessionUseCase)


def test_new_source_files_are_discovered_without_whitelisting(tmp_path):
    package = tmp_path / "src" / "neurath" / "domain"
    package.mkdir(parents=True)
    (package / "future.py").write_text('"""Future domain."""\nimport sqlalchemy')
    assert any("DOMAIN_BOUNDARY" in error for error in check_tree(tmp_path))


def test_strict_type_checker_rejects_duck_typed_adapter_and_missing_abstract_method(tmp_path):
    fixture = tmp_path / "nominal.py"
    fixture.write_text("""from neurath.application.ports.repositories.project import IProjectRepository
class DuckRepository:
    pass
repository: IProjectRepository = DuckRepository()
class MissingRepository(IProjectRepository):
    pass
missing = MissingRepository()
""")
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(fixture)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "Incompatible types" in result.stdout
    assert "abstract class" in result.stdout


def test_ruff_rejects_missing_docstrings(tmp_path):
    fixture = tmp_path / "missing_doc.py"
    fixture.write_text("class Example:\n    def execute(self):\n        return 1\n")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "D", str(fixture)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "D100" in result.stdout and "D101" in result.stdout and "D102" in result.stdout


def test_current_source_tree_has_no_architecture_violations():
    assert check_tree(Path(__file__).resolve().parents[1]) == []


def test_importing_low_level_sqlalchemy_alias_does_not_bypass_declarative_rule():
    sources = {
        "neurath.infrastructure.models.bad": '''"""Bad ORM fixture."""
from sqlalchemy.sql.schema import Table as Builder
Alias = Builder
record = Alias("project")
'''
    }
    assert any("DECLARATIVE_ORM" in error for error in ArchitectureChecker(sources).check())


def test_inheriting_an_input_dto_is_not_nominal_interface_implementation():
    sources = {
        "neurath.application.ports.usecases.register": '''"""Input fixture."""
class Request:
    """A value object is not a repository contract."""
''',
        "neurath.infrastructure.repositories.project": '''"""Invalid adapter fixture."""
from neurath.application.ports.usecases.register import Request
class ProjectRepository(Request):
    """Does not implement a repository contract."""
''',
    }
    assert any("NOMINAL_IMPLEMENTATION" in error for error in ArchitectureChecker(sources).check())


def test_command_name_starting_with_i_is_not_an_interface():
    checker = ArchitectureChecker(
        {
            "neurath.application.ports.usecases.invalidate": '"""Invalidation command."""\nclass InvalidateTaskCommand:\n    """Carry a sourced invalidation."""\n    task_id: str'
        }
    )
    assert checker.check() == []
