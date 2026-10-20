"""기계적으로 검사할 수 있는 리뷰 요구사항마다 정상·실패 fixture를 제공한다."""

import subprocess
import sys
from pathlib import Path

import pytest

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.services.directory_observer import IDirectoryObserver
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.infrastructure.directory_observer import GitDirectoryObserver
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
            "from contextlib import contextmanager as cm\n@cm\ndef scope(session):\n with session.begin(): yield session",
            "TRANSACTION_WRAPPER",
        ),
        ("neurath.application.core", "class Core: pass", "CORE"),
        ("neurath.domain.project", "import sqlalchemy as sa", "DOMAIN_BOUNDARY"),
        (
            "neurath.domain.project",
            "from ..infrastructure.database import create_database_engine",
            "DOMAIN_BOUNDARY",
        ),
        (
            "neurath.domain.project",
            "from neurath.application.usecases import anything",
            "DOMAIN_BOUNDARY",
        ),
        (
            "neurath.application.usecases.change",
            "from neurath.infrastructure.database import create_database_engine",
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
            "class IRegisterSessionUseCase: pass",
            "USECASE_INTERFACE",
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
    errors = ArchitectureChecker(
        {module: '"""구조 계약을 검증하는 테스트 대상이다."""\n' + source}
    ).check()
    assert any(f" {rule}:" in error for error in errors), errors


def test_aliases_and_indirect_nominal_inheritance_are_resolved_across_modules():
    sources = {
        "neurath.application.ports.repositories.project": '''"""구조 계약을 검증하는 테스트 대상이다."""
from abc import ABC as AbstractBase, abstractmethod as abstract
class IProjectRepository(AbstractBase):
    """구조 계약을 검증하는 테스트 대상이다."""
    @abstract
    def get(self, project_id: str) -> str:
        """구조 계약을 검증하는 테스트 대상이다."""
        raise NotImplementedError
''',
        "neurath.infrastructure.base_repository": '''"""구조 계약을 검증하는 테스트 대상이다."""
from neurath.application.ports.repositories.project import IProjectRepository as Contract
class BaseRepository(Contract):
    """구조 계약을 검증하는 테스트 대상이다."""
    def get(self, project_id: str) -> str:
        """구조 계약을 검증하는 테스트 대상이다."""
        return project_id
''',
        "neurath.infrastructure.repositories.project": '''"""구조 계약을 검증하는 테스트 대상이다."""
from neurath.infrastructure.base_repository import BaseRepository as Parent
class ProjectRepository(Parent):
    """구조 계약을 검증하는 테스트 대상이다."""
''',
        "neurath.infrastructure.models.base": '''"""구조 계약을 검증하는 테스트 대상이다."""
from sqlalchemy.orm import DeclarativeBase as D
class Base(D):
    """구조 계약을 검증하는 테스트 대상이다."""
''',
        "neurath.infrastructure.models.project": '''"""구조 계약을 검증하는 테스트 대상이다."""
from sqlalchemy.orm import Mapped as M, mapped_column as column
from neurath.infrastructure.models.base import Base as Parent
class ProjectModel(Parent):
    """구조 계약을 검증하는 테스트 대상이다."""
    __tablename__ = "project"
    id: M[str] = column(primary_key=True)
''',
    }
    assert ArchitectureChecker(sources).check() == []


def test_indirect_protocol_alias_cannot_hide_forbidden_base():
    sources = {
        "neurath.application.alias": '"""구조 계약을 검증하는 테스트 대상이다."""\nimport typing as t\nParent = t.Protocol',
        "neurath.application.ports.repositories.project": '"""구조 계약을 검증하는 테스트 대상이다."""\nfrom neurath.application.alias import Parent as P\nclass IProjectRepository(P):\n """구조 계약을 검증하는 테스트 대상이다."""',
    }
    errors = ArchitectureChecker(sources).check()
    assert any("FORBIDDEN_TYPE" in error for error in errors)
    assert any("NOMINAL_PORT" in error for error in errors)


def test_only_external_ports_are_nominal_and_abstract():
    for interface in (
        IProjectRepository,
        ISessionRepository,
        IDirectoryObserver,
    ):
        with pytest.raises(TypeError):
            interface()
    assert issubclass(ProjectRepository, IProjectRepository)
    assert issubclass(SessionRepository, ISessionRepository)
    assert issubclass(GitDirectoryObserver, IDirectoryObserver)
    assert not hasattr(RegisterSessionUseCase, "__abstractmethods__")


def test_new_source_files_are_discovered_without_whitelisting(tmp_path):
    package = tmp_path / "src" / "neurath" / "domain"
    package.mkdir(parents=True)
    (package / "future.py").write_text(
        '"""구조 계약을 검증하는 테스트 대상이다."""\nimport sqlalchemy'
    )
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
        [
            sys.executable,
            "-m",
            "pyrefly",
            "check",
            "--config",
            str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
            str(fixture),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not assignable" in result.stdout
    assert "abstract" in result.stdout


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
        "neurath.infrastructure.models.bad": '''"""구조 계약을 검증하는 테스트 대상이다."""
from sqlalchemy.sql.schema import Table as Builder
Alias = Builder
record = Alias("project")
'''
    }
    assert any("DECLARATIVE_ORM" in error for error in ArchitectureChecker(sources).check())


def test_inheriting_an_input_dto_is_not_nominal_interface_implementation():
    sources = {
        "neurath.application.ports.usecases.register": '''"""구조 계약을 검증하는 테스트 대상이다."""
class Request:
    """구조 계약을 검증하는 테스트 대상이다."""
''',
        "neurath.infrastructure.repositories.project": '''"""구조 계약을 검증하는 테스트 대상이다."""
from neurath.application.ports.usecases.register import Request
class ProjectRepository(Request):
    """구조 계약을 검증하는 테스트 대상이다."""
''',
    }
    assert any("NOMINAL_IMPLEMENTATION" in error for error in ArchitectureChecker(sources).check())


@pytest.mark.parametrize(
    ("module", "source", "rule"),
    [
        (
            "neurath.application.ports.repositories.project",
            "class IProjectRepository:\n def resolve(self, observation): pass",
            "PRIMITIVE_REPOSITORY",
        ),
        (
            "neurath.application.ports.repositories.session",
            "class ISessionRepository:\n def save(self, entity, expected_revision): pass",
            "PRIMITIVE_REPOSITORY",
        ),
        (
            "neurath.infrastructure.repositories.project",
            "class ProjectRepository:\n def add(self, entity): entity.associate()",
            "REPOSITORY_POLICY",
        ),
        (
            "neurath.application.ports.services.directory_observer",
            "from neurath.domain.aggregates.project import ProjectLocation\nclass IDirectoryObserver:\n def observe(self) -> ProjectLocation: pass",
            "OBSERVATION_BOUNDARY",
        ),
        (
            "neurath.domain.aggregates.project",
            "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass Project:\n id: str",
            "ENTITY_MUTABILITY",
        ),
        (
            "neurath.domain.aggregates.session",
            "from dataclasses import dataclass\n@dataclass\nclass HostSession:\n id: str",
            "ENTITY_IDENTITY",
        ),
        ("neurath.infrastructure.database", "class SqliteDatabase: pass", "DATABASE_WRAPPER"),
        (
            "neurath.transport.session_requests",
            "from neurath.infrastructure.repositories.project import ProjectRepository\nvalue = ProjectRepository(session)",
            "DEPENDENCY_COMPOSITION",
        ),
        ("neurath.domain.project", "value: str = 1 # pyrefly: ignore", "SUPPRESSION"),
    ],
)
def test_round_two_architecture_regressions_are_rejected(module, source, rule):
    errors = ArchitectureChecker(
        {module: '"""구조 계약을 검증하는 테스트 대상이다."""\n' + source}
    ).check()
    assert any(f" {rule}:" in error for error in errors), errors


def test_resource_factories_and_frozen_values_are_not_transaction_or_entity_wrappers():
    sources = {
        "neurath.infrastructure.providers": '''"""구조 계약을 검증하는 테스트 대상이다."""
from collections.abc import Iterator
from contextlib import contextmanager
from sqlalchemy.orm import Session
@contextmanager
def request_scope() -> Iterator[Session]:
    """구조 계약을 검증하는 테스트 대상이다."""
    with Session() as session:
        yield session
''',
        "neurath.domain.observations": '''"""구조 계약을 검증하는 테스트 대상이다."""
from dataclasses import dataclass
@dataclass(frozen=True)
class Observation:
    """구조 계약을 검증하는 테스트 대상이다."""
    working_directory: str
''',
        "neurath.application.usecases.example": '''"""구조 계약을 검증하는 테스트 대상이다."""
class ExampleUseCase:
    """구조 계약을 검증하는 테스트 대상이다."""
''',
    }
    assert ArchitectureChecker(sources).check() == []


def test_pyrefly_rejects_wrong_type_with_the_repository_configuration(tmp_path):
    fixture = tmp_path / "wrong_type.py"
    fixture.write_text('def count() -> int:\n    return "not an integer"\n')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pyrefly",
            "check",
            "--config",
            str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
            str(fixture),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "bad-return" in result.stdout


def test_google_doc_checker_rejects_missing_parameter_and_return_sections(tmp_path):
    fixture = tmp_path / "bad_doc.py"
    fixture.write_text('''"""구조 계약을 검증하는 테스트 대상이다."""
def example(value: str) -> str:
    """구조 계약을 검증하는 테스트 대상이다."""
    return value
''')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pydoclint.main",
            "--config",
            str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
            str(fixture),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "DOC101" in result.stdout + result.stderr
    assert "DOC201" in result.stdout + result.stderr


@pytest.mark.parametrize("method", ["add", "insert", "create", "update"])
@pytest.mark.parametrize("layer", ["application.ports", "infrastructure"])
def test_repository_creation_and_update_aliases_must_use_save(layer, method):
    source = f'''"""저장 계약의 명칭을 검증한다."""
class ExampleRepository:
    """삽입과 갱신을 분리하는 잘못된 저장 계약이다."""
    def {method}(self, entity):
        """잘못된 이름으로 엔티티를 저장한다."""
        pass
'''
    errors = ArchitectureChecker({f"neurath.{layer}.repositories.example": source}).check()
    assert any(" REPOSITORY_SAVE:" in error for error in errors), errors


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("neurath.application.ports.repositories.project_location", "IProjectLocationRepository"),
        ("neurath.infrastructure.repositories.project_location", "ProjectLocationRepository"),
    ],
)
def test_owned_locations_cannot_have_an_independent_repository(module, name):
    source = f'''"""종속 위치의 독립 저장소 회귀를 검증한다."""
class {name}:
    """프로젝트를 통하지 않는 잘못된 위치 저장소다."""
'''
    errors = ArchitectureChecker({module: source}).check()
    assert any(" AGGREGATE_OWNERSHIP:" in error for error in errors), errors


def test_owned_values_relationships_and_domain_creation_are_valid():
    sources = {
        "neurath.domain.aggregates.project": '''"""프로젝트와 소유 위치 값을 정의한다."""
from dataclasses import dataclass
@dataclass(frozen=True)
class ProjectLocation:
    """프로젝트가 소유하는 불변 위치 값이다."""
    kind: str
    path: str
class Project:
    """위치 값을 소유하는 aggregate다."""
    @classmethod
    def create(cls):
        """도메인 규칙으로 새 프로젝트를 생성한다."""
        return cls()
''',
        "neurath.infrastructure.models.project": '''"""프로젝트의 소유 관계를 매핑한다."""
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
class ProjectModel(DeclarativeBase):
    """타입을 명시한 소유 관계 모델이다."""
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(primary_key=True)
    locations: Mapped[list["LocationModel"]] = relationship(cascade="all, delete-orphan")
''',
        "neurath.infrastructure.example": '''"""ORM의 자체 저장 API를 사용할 수 있다."""
def store(session, record):
    """ORM 내부 삽입 API는 저장소 계약 이름과 구별한다."""
    session.add(record)
''',
    }
    assert ArchitectureChecker(sources).check() == []


@pytest.mark.parametrize(
    "statement",
    [
        "record = existing.get(key) or Model()",
        "record: Model = existing.get(key) or Model()",
        "return existing.get(key) or Model()",
        "records = [existing.get(key) or Model() for key in keys]",
    ],
)
def test_repository_object_selection_requires_explicit_none_branch(statement):
    source = f'''"""저장소의 객체 선택 표현을 검사한다."""
def select_record(existing, key, keys):
    """누락된 객체를 암묵적인 진리값으로 대체하는 실패 예다."""
    {statement}
'''
    errors = ArchitectureChecker({"neurath.infrastructure.repositories.example": source}).check()
    assert any(" EXPLICIT_OBJECT_SELECTION:" in error for error in errors), errors


def test_repository_explicit_object_selection_and_boolean_conditions_are_valid():
    source = '''"""명시적인 객체 선택과 일반 조건을 구별한다."""
def select_record(existing, key, valid, ready):
    """누락 여부를 확인하여 객체를 선택한다."""
    record = existing.get(key)
    if record is None:
        record = Model()
    if valid or ready:
        return record
    return None
'''
    assert (
        ArchitectureChecker({"neurath.infrastructure.repositories.example": source}).check() == []
    )


@pytest.mark.parametrize("return_type", ["Factory", "Factory | None", "tuple[Factory, ...]"])
def test_class_factories_use_self_for_subclass_preserving_results(return_type):
    source = f'''"""생성 메서드의 반환 계약을 검증한다."""
class Factory:
    """동적 생성 대상의 타입을 유지한다."""
    @classmethod
    def create(cls) -> {return_type}:
        """생성한 결과를 반환한다."""
        return cls()
'''
    errors = ArchitectureChecker({"neurath.application.factory": source}).check()
    assert any("SELF_RETURN:" in error for error in errors)


def test_self_factory_and_concrete_domain_conversion_have_distinct_return_contracts():
    source = '''"""생성 및 변환 메서드의 서로 다른 반환 계약을 검증한다."""
from typing import Self
class Factory:
    """생성 대상과 구체 변환 결과를 구분한다."""
    @classmethod
    def create(cls) -> Self:
        """호출한 클래스의 새 인스턴스를 반환한다."""
        return cls()
    def to_domain(self) -> Factory:
        """구체 도메인 결과로 변환한다."""
        return Factory()
'''
    assert ArchitectureChecker({"neurath.application.factory": source}).check() == []


def test_python_314_lint_rejects_quoted_and_legacy_typing_annotations(tmp_path):
    source = tmp_path / "annotations.py"
    source.write_text('from typing import List\ndef names() -> "List[str]":\n    return []\n')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
            "--output-format",
            "json",
            str(source),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    import json

    codes = {diagnostic["code"] for diagnostic in json.loads(result.stdout)}
    assert result.returncode == 1
    assert "UP006" in codes
    assert "UP037" in codes
