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
    assert RegisterSessionUseCase.__abstractmethods__ == frozenset()


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
from spakky.domain import ICommandUseCase
class ExampleUseCase(ICommandUseCase):
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


@pytest.mark.parametrize(
    "method",
    ["get", "get_or_none", "contains", "range", "save", "save_all", "delete", "delete_all"],
)
def test_framework_crud_reimplementation_is_rejected(method):
    source = f'''"""기본 저장 계약의 재구현을 검증하는 실패 사례다."""
class ExampleRepository:
    """프레임워크 기본 메서드를 다시 구현한 잘못된 저장소다."""
    def {method}(self, value):
        """프레임워크에서 상속해야 하는 메서드다."""
        return value
'''
    errors = ArchitectureChecker({"neurath.infrastructure.repositories.example": source}).check()
    assert any("FRAMEWORK_CRUD:" in error for error in errors)


def test_framework_domain_bases_and_tables_are_allowed_without_layer_escape():
    sources = {
        "neurath.domain.aggregates.example": '''"""프레임워크 도메인 기반을 사용하는 정상 사례다."""
from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot
@mutable
class Example(AbstractAggregateRoot[str]):
    """식별자와 변경 추적을 상속하는 도메인이다."""
''',
        "neurath.infrastructure.models.example": '''"""프레임워크 선언형 테이블을 사용하는 정상 사례다."""
from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy.orm import Mapped, mapped_column
from neurath.domain.aggregates.example import Example
@Table(Example)
class ExampleModel(AbstractMappableTable[Example]):
    """도메인과 연결된 선언형 테이블이다."""
    __tablename__ = "example"
    id: Mapped[str] = mapped_column(primary_key=True)
''',
    }
    assert ArchitectureChecker(sources).check() == []
    sources["neurath.domain.aggregates.example"] += (
        "\nfrom spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository\n"
    )
    assert any("DOMAIN_BOUNDARY:" in error for error in ArchitectureChecker(sources).check())


@pytest.mark.parametrize("pragma", ["no cover", "no branch"])
def test_coverage_suppression_is_rejected(pragma):
    source = f'''"""커버리지 누락을 주석으로 숨기는 실패 사례다."""
def delivery_fee(express):
    """조건에 따라 배달 요금을 결정한다."""
    if express:  # pragma: {pragma}
        return 10
    return 0
'''
    errors = ArchitectureChecker({"neurath.application.delivery": source}).check()
    assert any("SUPPRESSION:" in error for error in errors)


def test_invalidate_usecase_is_concrete_while_named_usecase_interface_still_rejected():
    concrete = '''"""무효화 동작을 구체 클래스로 선언하는 정상 사례다."""
from spakky.domain import ICommandUseCase
class InvalidateTaskUseCase(ICommandUseCase):
    """실제 정정을 반영하는 구체 유스케이스다."""
'''
    assert (
        ArchitectureChecker({"neurath.application.usecases.invalidate_task": concrete}).check()
        == []
    )
    abstract = concrete.replace("InvalidateTaskUseCase", "IInvalidationUseCase")
    assert any(
        "USECASE_INTERFACE:" in error
        for error in ArchitectureChecker(
            {"neurath.application.usecases.invalidate_task": abstract}
        ).check()
    )


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("class CreateTaskUseCase: pass", "FRAMEWORK_USECASE"),
        ("class CreateTaskCommand: pass", "FRAMEWORK_REQUEST"),
        ("class GetTasksQuery: pass", "FRAMEWORK_REQUEST"),
        ("def records() -> tuple[str, ...]: pass", "COLLECTION_CONTRACT"),
        (
            "from builtins import tuple as T\ndef records() -> T[str, ...]: pass",
            "COLLECTION_CONTRACT",
        ),
    ],
)
def test_reviewed_framework_and_sequence_contract_regressions_fail(source, rule):
    errors = ArchitectureChecker({"neurath.application.usecases.example": source}).check()
    assert any(f" {rule}:" in error for error in errors)


def test_framework_contract_aliases_and_sequence_and_fixed_pairs_are_allowed():
    source = '''"""프레임워크 계약의 별칭과 컬렉션을 검증한다."""
from collections.abc import Sequence
from spakky.domain.application.command import AbstractCommand as Command, ICommandUseCase as UseCase
from spakky.domain.application.query import AbstractQuery as Query, IQueryUseCase as QueryUseCase
class CreateTaskCommand(Command):
    """작업 생성 명령이다."""
class CreateTaskUseCase(UseCase):
    """작업 생성 유스케이스다."""
class GetTasksQuery(Query):
    """작업 목록 조회다."""
class GetTasksUseCase(QueryUseCase):
    """작업 목록 유스케이스다."""
class Values:
    """조회 시퀀스와 고정 이종 쌍의 계약을 구분한다."""
    records: Sequence[str]
    pair: tuple[str, int]
'''
    assert ArchitectureChecker({"neurath.application.usecases.example": source}).check() == []


def test_every_real_usecase_and_request_implements_the_framework_contract():
    import importlib
    import inspect
    import pkgutil

    from spakky.domain.application.command import AbstractCommand, ICommandUseCase
    from spakky.domain.application.query import AbstractQuery, IQueryUseCase

    import neurath.application.usecases as package

    usecases = []
    requests = []
    results = []
    for info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        module = importlib.import_module(info.name)
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__:
                continue
            if name.endswith("UseCase"):
                assert issubclass(cls, (ICommandUseCase, IQueryUseCase)), cls
                assert not inspect.isabstract(cls), cls
                assert "run" in cls.__dict__, cls
                assert "execute" not in cls.__dict__, cls
                from dataclasses import is_dataclass
                from typing import get_type_hints

                result_type = get_type_hints(cls.run)["return"]
                assert result_type.__module__ == module.__name__, cls
                assert (
                    result_type.__name__
                    == name.removesuffix("UseCase").removesuffix("Result") + "Result"
                ), cls
                assert is_dataclass(result_type) and result_type.__dataclass_params__.frozen, cls
                results.append(result_type)
                usecases.append(cls)
            elif name.endswith(("Command", "Query")):
                assert issubclass(cls, (AbstractCommand, AbstractQuery)), cls
                requests.append(cls)
    assert len(usecases) == len(requests) == len(results) == 16


@pytest.mark.parametrize(
    ("module", "source", "rule"),
    [
        ("neurath.application.dto.task", "class TaskDTO: pass", "RESULT_LOCATION"),
        ("neurath.transport.task_requests", "def get_task(request): pass", "TRANSPORT_PASSTHROUGH"),
        (
            "neurath.transport.session_requests",
            "def register_session(request): pass",
            "TRANSPORT_PASSTHROUGH",
        ),
        ("neurath.infrastructure.database", 'SCHEMA_REVISION = "core_0003"', "ALEMBIC_REVISION"),
        ("neurath.infrastructure.database", 'CURRENT_HEAD: str = "core_0004"', "ALEMBIC_REVISION"),
        (
            "neurath.application.usecases.get_task",
            "class GetTaskUseCase:\n def run(self, query) -> str: pass",
            "RESULT_LOCATION",
        ),
        (
            "neurath.application.usecases.get_task",
            "from neurath.application.results import GetTaskResult\nclass GetTaskUseCase:\n def run(self, query) -> GetTaskResult: pass",
            "RESULT_LOCATION",
        ),
    ],
)
def test_reviewed_result_placement_revision_and_relay_regressions_fail(module, source, rule):
    errors = ArchitectureChecker({module: source}).check()
    assert any(f" {rule}:" in error for error in errors), errors


def test_local_input_result_and_handler_are_valid_together():
    source = '''"""같은 모듈에 입출력 계약을 정의한다."""
from collections.abc import Sequence
from dataclasses import dataclass
from spakky.domain import AbstractQuery, IQueryUseCase
@dataclass(frozen=True)
class GetNamesQuery(AbstractQuery):
    """조회할 프로젝트를 지정한다."""
    project_id: str
@dataclass(frozen=True)
class GetNamesResult:
    """조회한 이름을 전달한다."""
    names: Sequence[str]
class GetNamesUseCase(IQueryUseCase[GetNamesQuery, GetNamesResult]):
    """동일한 모듈의 입출력 계약을 구현한다."""
    def run(self, query: GetNamesQuery) -> GetNamesResult:
        """명시한 범위의 결과를 반환한다."""
        return GetNamesResult(names=())
'''
    assert ArchitectureChecker({"neurath.application.usecases.get_names": source}).check() == []


@pytest.mark.parametrize("package", ["domain", "application"])
@pytest.mark.parametrize(
    "source",
    [
        "def validate_dependencies(tasks, uid, dependencies): pass",
        "def arbitrary_rule(value): pass",
        "async def apply_policy(value): pass",
        "if True:\n def enforce(value): pass",
        "def outer():\n def hidden_rule(value): pass",
        "class UnnamedRules:\n @staticmethod\n def arbitrary_rule(value): pass",
        "class UnnamedRules:\n @classmethod\n def check_value(cls, value): pass",
        "from builtins import staticmethod as static\nclass Rules:\n @static\n def arbitrary(value): pass",
    ],
)
def test_standalone_business_functions_and_utility_class_relabels_are_rejected(package, source):
    module = f"neurath.{package}.rules"
    errors = ArchitectureChecker({module: source}).check()
    assert any("BEHAVIOR_OWNERSHIP:" in error for error in errors), errors


def test_owned_validation_and_infrastructure_entrypoints_are_allowed():
    sources = {
        "neurath.domain.aggregates.task": '''"""데이터를 소유하는 도메인 객체 안에서 규칙을 검사한다."""
from spakky.domain import AbstractAggregateRoot
class Task(AbstractAggregateRoot[str]):
    """의존을 소유하고 검증하는 태스크다."""
    dependencies: Sequence[str]
    def validate_dependencies(self, tasks):
        """자기 의존의 규칙을 검사한다."""
        return None
''',
        "neurath.infrastructure.database": '''"""인프라 초기화 진입점은 업무 정책과 구분한다."""
def initialize_database(path):
    """명시한 저장소를 초기화한다."""
    return None
''',
        "neurath.infrastructure.migrations.versions.example": '''"""Alembic이 호출하는 진입점은 프레임워크 계약이다."""
def upgrade():
    """새 스키마를 적용한다."""
    return None
''',
    }
    assert ArchitectureChecker(sources).check() == []


def test_current_business_modules_have_no_standalone_rule_functions():
    import ast

    package = Path(__file__).resolve().parents[1] / "src" / "neurath"
    for layer in ("domain", "application"):
        for path in (package / layer).rglob("*.py"):
            tree = ast.parse(path.read_text())
            assert not any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in tree.body
            ), path


@pytest.mark.parametrize("alias", ["ContextNotFound", "MissingScope"])
def test_usecase_must_delegate_domain_rejection_to_its_owner(alias):
    source = f'''"""외부 계층이 범위 규칙을 직접 판정하는 회귀다."""
from neurath.domain.errors import ContextNotFound as {alias}
class CreateTaskUseCase:
    """소유 객체 대신 프로젝트 범위를 판정하는 잘못된 처리다."""
    def run(self, command):
        """직접 필드를 비교하고 도메인 오류를 던진다."""
        if self.task.project_id != command.project_id:
            raise {alias}("wrong project")
'''
    errors = ArchitectureChecker({"neurath.application.usecases.create_task": source}).check()
    assert any("DOMAIN_RULE_OWNER:" in error for error in errors), errors
