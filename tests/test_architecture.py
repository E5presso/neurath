"""기계적으로 검사할 수 있는 리뷰 요구사항마다 정상·실패 fixture를 제공한다."""

import subprocess
import sys
from pathlib import Path

import pytest

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.directory_observer import IDirectoryObserverService
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.infrastructure.directory_observer import GitDirectoryObserverService
from neurath.infrastructure.repositories.project import SQLAlchemyProjectRepository
from neurath.infrastructure.repositories.session import SQLAlchemySessionRepository
from tools.architecture import ArchitectureChecker, check_tree


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
class SQLAlchemyProjectRepository(Contract):
    """구조 계약을 검증하는 테스트 대상이다."""
    def get(self, project_id: str) -> str:
        """구조 계약을 검증하는 테스트 대상이다."""
        return project_id
''',
        "neurath.infrastructure.repositories.project": '''"""구조 계약을 검증하는 테스트 대상이다."""
from neurath.infrastructure.base_repository import SQLAlchemyProjectRepository as Parent
class SQLAlchemyProjectRepository(Parent):
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
        IRequestSourceRepository,
        ITaskRepository,
        IProjectRepository,
        ISessionRepository,
        IDirectoryObserverService,
    ):
        with pytest.raises(TypeError):
            interface()
    assert issubclass(SQLAlchemyProjectRepository, IProjectRepository)
    assert issubclass(SQLAlchemySessionRepository, ISessionRepository)
    assert issubclass(GitDirectoryObserverService, IDirectoryObserverService)
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


@pytest.mark.parametrize("alias", ["ContextNotFound", "MissingScope"])
def test_usecase_can_propagate_or_raise_domain_errors_without_a_syntax_ban(alias):
    source = f'''"""유스케이스의 예외 사용을 문법만으로 금지하지 않는다."""
from dataclasses import dataclass
from spakky.domain import AbstractQuery, IQueryUseCase
from neurath.domain.errors import ContextNotFound as {alias}
@dataclass(frozen=True)
class GetTaskQuery(AbstractQuery):
    """조회할 작업을 지정한다."""
    task_id: str
@dataclass(frozen=True)
class GetTaskResult:
    """조회 결과를 전달한다."""
    task_id: str
class GetTaskUseCase(IQueryUseCase[GetTaskQuery, GetTaskResult]):
    """오류의 발생·전파·변환을 사용할 수 있는 유스케이스다."""
    def run(self, query: GetTaskQuery) -> GetTaskResult:
        """예외 타입만 보고 업무 책임을 판정하지 않는다."""
        try:
            raise {alias}("unavailable")
        except {alias} as error:
            raise {alias}("requested task unavailable") from error
'''
    assert ArchitectureChecker({"neurath.application.usecases.get_task": source}).check() == []


@pytest.mark.parametrize("package", ["domain", "application"])
def test_function_shape_alone_does_not_establish_business_responsibility(package):
    source = '''"""함수나 정적 메서드의 형태만으로 책임 위반을 단정하지 않는다."""
def normalize_label(value: str) -> str:
    """표시 문자열의 앞뒤 공백을 정리한다."""
    return value.strip()
class Labels:
    """출력 형식을 다루는 예시다."""
    @staticmethod
    def normalize(value: str) -> str:
        """표시용 문자열을 반환한다."""
        return value.strip()
'''
    assert ArchitectureChecker({f"neurath.{package}.labels": source}).check() == []


@pytest.mark.parametrize(
    ("module", "source", "rule"),
    [
        (
            "neurath.application.ports.test",
            "from typing import Protocol as P\nclass Port(P): pass",
            "FORBIDDEN_TYPE",
        ),
        ("neurath.domain.test", "import sqlalchemy", "DOMAIN_BOUNDARY"),
        ("neurath.domain.test", "from neurath.application import usecases", "DOMAIN_BOUNDARY"),
        (
            "neurath.application.test",
            "from neurath.infrastructure import database",
            "APPLICATION_BOUNDARY",
        ),
        (
            "neurath.infrastructure.test",
            "from neurath.transport import cli",
            "INFRASTRUCTURE_BOUNDARY",
        ),
        ("neurath.application.ports.test", "class IPort: pass", "NOMINAL_PORT"),
        (
            "neurath.application.ports.test",
            "from abc import ABC\nclass IPort(ABC):\n def fetch(self): pass",
            "ABSTRACT_METHOD",
        ),
        (
            "neurath.infrastructure.test",
            "from spakky.data.stereotype.repository import Repository\n@Repository()\nclass Store: pass",
            "NOMINAL_IMPLEMENTATION",
        ),
        (
            "neurath.application.test",
            "from spakky.core.stereotype.usecase import UseCase\n@UseCase()\nclass Handler: pass",
            "FRAMEWORK_USECASE",
        ),
        (
            "neurath.infrastructure.test",
            "from spakky.plugins.sqlalchemy.orm.table import Table\n@Table()\nclass Row: pass",
            "DECLARATIVE_ORM",
        ),
    ],
)
def test_confirmed_contracts_fail_at_their_actual_boundary(module, source, rule):
    assert any(f" {rule}:" in error for error in ArchitectureChecker({module: source}).check())


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("neurath.application.core", "class Core: pass"),
        ("neurath.infrastructure.core_schema", "class SqliteDatabase: pass"),
        ("neurath.domain.records", "class UnitOfWork: pass\nclass CommitObserver: pass"),
        (
            "neurath.application.ports.usecases.policy",
            "from abc import ABC\nclass IPolicyUseCase(ABC): pass",
        ),
        ("neurath.transport.task_requests", "def process(request): return request"),
        ("neurath.application.dto.values", "class SharedValue: pass"),
        ("neurath.infrastructure.database", 'diagnostic_revision = "core_0001"'),
        (
            "neurath.domain.values",
            "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass Reference:\n id: str",
        ),
        (
            "neurath.domain.values",
            "from typing import Any, Literal, cast\ntype Option = Literal['yes', 'no']\nvalue: Any = None\nlabel = cast(str, 'ok')",
        ),
        ("neurath.domain.values", "from pathlib import PurePath\nimport hashlib, json"),
        ("neurath.application.values", "def records() -> tuple[str, ...]: return ()"),
        ("neurath.application.values", "class ExampleUseCase: pass\nclass ExampleCommand: pass"),
        (
            "neurath.infrastructure.queries",
            "from sqlalchemy import Table, Column, MetaData, Integer\nrows = Table('rows', MetaData(), Column('id', Integer))",
        ),
        (
            "neurath.infrastructure.repositories.values",
            "class QueryBuilder:\n def get(self): pass\n def create(self): pass\n def select_range(self, expected_revision): pass",
        ),
        ("neurath.infrastructure.repositories.values", "value = mapping.get(key) or fallback"),
        (
            "neurath.application.values",
            "value: str = 'ok' # type: ignore[assignment]\nunused = 1 # noqa",
        ),
        (
            "neurath.infrastructure.providers",
            "from contextlib import contextmanager\n@contextmanager\ndef connection(engine):\n with engine.begin() as conn: yield conn",
        ),
        (
            "neurath.application.factories",
            "class Factory:\n @classmethod\n def fixed(cls) -> Factory: return Factory()",
        ),
    ],
)
def test_names_and_unrelated_syntax_do_not_prove_a_responsibility_violation(module, source):
    assert ArchitectureChecker({module: source}).check() == []


def test_repository_query_contract_is_not_a_fixed_method_or_parameter_whitelist():
    source = '''"""조회 계약은 필요한 질의와 저장 관찰을 표현한다."""
from abc import ABC, abstractmethod
class IHistoryRepository(ABC):
    """저장된 개정으로 기간 조회를 제공한다."""
    @abstractmethod
    def select_by_period(self, expected_revision: int):
        """지정한 저장 개정의 자료를 조회한다."""
        raise NotImplementedError
'''
    assert (
        ArchitectureChecker({"neurath.application.ports.repositories.history": source}).check()
        == []
    )


def test_registered_usecases_use_framework_contracts():
    import importlib
    import inspect
    import pkgutil
    from typing import get_type_hints

    from spakky.core.stereotype.usecase import UseCase
    from spakky.domain.application.command import (
        AbstractCommand,
        IAsyncCommandUseCase,
    )
    from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

    import neurath.application.usecases as package

    checked = []
    for info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        module = importlib.import_module(info.name)
        for _, handler in inspect.getmembers(module, inspect.isclass):
            if handler.__module__ != module.__name__ or not UseCase.exists(handler):
                continue
            if inspect.isabstract(handler):
                continue
            assert issubclass(handler, (IAsyncCommandUseCase, IAsyncQueryUseCase))
            assert inspect.iscoroutinefunction(handler.run)
            hints = get_type_hints(handler.run)
            if issubclass(handler, IAsyncCommandUseCase):
                assert issubclass(hints["command"], AbstractCommand)
            else:
                assert issubclass(hints["query"], AbstractQuery)
            checked.append(handler)
    assert checked


def test_current_collection_ports_and_domain_state_types_match_the_reviewed_contracts():
    from collections.abc import Sequence
    from enum import Enum
    from typing import get_origin, get_type_hints

    from neurath.domain.aggregates.project import ProjectKind
    from neurath.domain.aggregates.request_source import SourceKind
    from neurath.domain.task_records import Outcome, TaskStatus

    for port in (IRequestSourceRepository, ITaskRepository):
        assert get_origin(get_type_hints(port.range)["return"]) is Sequence
    for state in (ProjectKind, SourceKind, Outcome, TaskStatus):
        assert issubclass(state, Enum)


@pytest.mark.parametrize(
    "module_name,handler_name,result_name",
    [
        ("correct_task", "CorrectTaskUseCase", "CorrectTaskResult"),
        ("create_task", "CreateTaskUseCase", "CreateTaskResult"),
        ("get_session_context", "GetSessionContextUseCase", "GetSessionContextResult"),
        ("get_sources", "GetSourcesUseCase", "GetSourcesResult"),
        ("get_task", "GetTaskUseCase", "GetTaskResult"),
        ("get_tasks", "GetTasksUseCase", "GetTasksResult"),
        ("invalidate_task", "InvalidateTaskUseCase", "InvalidateTaskResult"),
        ("move_session", "MoveSessionUseCase", "MoveSessionResult"),
        ("record_source", "RecordSourceUseCase", "RecordSourceResult"),
        ("register_project", "RegisterProjectUseCase", "RegisterProjectResult"),
        ("register_session", "RegisterSessionUseCase", "RegisterSessionResult"),
        ("report_result", "ReportResultUseCase", "ReportResult"),
        ("resume_task", "ResumeTaskUseCase", "ResumeTaskResult"),
        ("start_task", "StartTaskUseCase", "StartTaskResult"),
        ("submit_result", "SubmitResultUseCase", "SubmitResult"),
        ("wait_task", "WaitTaskUseCase", "WaitTaskResult"),
        ("start_workflow", "StartWorkflowUseCase", "StartWorkflowResult"),
        ("get_workflow", "GetWorkflowUseCase", "GetWorkflowResult"),
        ("prepare_phase", "PreparePhaseUseCase", "PreparePhaseResult"),
        ("report_phase", "ReportPhaseUseCase", "ReportPhaseResult"),
        ("revise_workflow", "ReviseWorkflowUseCase", "ReviseWorkflowResult"),
        ("skip_phase", "SkipPhaseUseCase", "SkipPhaseResult"),
        ("execute_phase", "ExecutePhaseUseCase", "ExecutePhaseResult"),
        ("receive_hook", "ReceiveHookUseCase", "ReceiveHookResult"),
    ],
)
def test_reviewed_case_specific_result_contract_is_colocated(
    module_name, handler_name, result_name
):
    import importlib
    from typing import get_type_hints

    module = importlib.import_module("neurath.application.usecases." + module_name)
    handler = getattr(module, handler_name)
    result = getattr(module, result_name)
    assert get_type_hints(handler.run)["return"] is result
    assert result.__module__ == handler.__module__


@pytest.mark.parametrize(("annotation", "valid"), [("Any", False), ("object", True)])
def test_standard_linter_checks_dynamic_annotations_without_a_global_ignore(
    tmp_path, annotation, valid
):
    fixture = tmp_path / "boundary.py"
    fixture.write_text(
        '"""입력의 구체 타입을 요구하지 않고 그대로 반환하는 사례다."""\n'
        + ("from typing import Any\n" if annotation == "Any" else "")
        + f'''


def echo(value: {annotation}) -> {annotation}:
    """외부 값을 전달한다.

    Args:
        value: 전달할 동적 값.

    Returns:
        {annotation}: 전달된 값.
    """
    return value
'''
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
            str(fixture),
        ],
        capture_output=True,
        text=True,
    )
    if valid:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert "ANN401" in result.stdout


@pytest.mark.parametrize(
    ("rule", "nested", "guarded"),
    [
        (
            "RET505",
            "    if values:\n        return values[0]\n    else:\n        return 0\n",
            "    if not values:\n        return 0\n    return values[0]\n",
        ),
        (
            "RET506",
            '    if not values:\n        raise ValueError("empty")\n    else:\n        return values[0]\n',
            '    if not values:\n        raise ValueError("empty")\n    return values[0]\n',
        ),
        (
            "RET507",
            "    total = 0\n    for value in values:\n        if value < 0:\n            continue\n        else:\n            total += value\n    return total\n",
            "    total = 0\n    for value in values:\n        if value < 0:\n            continue\n        total += value\n    return total\n",
        ),
        (
            "RET508",
            "    total = 0\n    for value in values:\n        if value == 0:\n            break\n        else:\n            total += value\n    return total\n",
            "    total = 0\n    for value in values:\n        if value == 0:\n            break\n        total += value\n    return total\n",
        ),
    ],
)
def test_shared_ruff_rules_reject_terminal_else_and_accept_guard_clauses(
    tmp_path, rule, nested, guarded
):
    import json

    prefix = '''"""종료한 분기 뒤의 불필요한 else를 검사하는 입력이다."""


def score(values: list[int]) -> int:
    """입력에 대응하는 점수를 계산한다.

    Args:
        values: 검사할 정수 목록.

    Returns:
        int: 선택하거나 누적한 점수.
    """
'''
    fixture = tmp_path / "control_flow.py"
    config = Path(__file__).resolve().parents[1] / "pyproject.toml"
    for body, expected in ((nested, {rule}), (guarded, set())):
        fixture.write_text(prefix + body)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--config",
                str(config),
                "--output-format",
                "json",
                str(fixture),
            ],
            capture_output=True,
            text=True,
        )
        assert {item["code"] for item in json.loads(result.stdout)} == expected
        assert result.returncode == bool(expected)


def test_control_flow_rules_allow_nonterminal_alternatives(tmp_path):
    fixture = tmp_path / "alternatives.py"
    fixture.write_text('''"""양쪽 분기가 값을 만드는 정당한 조건 분기의 입력이다."""


def magnitude(value: int) -> int:
    """입력의 부호에 맞춰 크기를 선택한다.

    Args:
        value: 부호를 판정할 정수.

    Returns:
        int: 선택한 절댓값.
    """
    if value >= 0:
        result = value
    else:
        result = -value
    return result
''')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
            str(fixture),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_checker_retains_all_independent_findings_after_guard_refactor():
    source = """
import neurath.infrastructure.database
from typing import Protocol
from spakky.core.stereotype.usecase import UseCase
from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.orm.table import Table
@UseCase()
@Repository()
@Table()
class IInvalid:
    def run(self):
        pass
"""
    errors = ArchitectureChecker({"neurath.application.ports.invalid": source}).check()
    codes = {error.split()[1].rstrip(":") for error in errors}
    assert codes == {
        "APPLICATION_BOUNDARY",
        "FORBIDDEN_TYPE",
        "NOMINAL_PORT",
        "ABSTRACT_METHOD",
        "NOMINAL_IMPLEMENTATION",
        "IMPLEMENTATION_NAME",
        "USECASE_NAME",
        "FRAMEWORK_USECASE",
        "DECLARATIVE_ORM",
    }


def role_sources(suffix, interface, implementation, *, aliased=False):
    role = "services" if suffix == "Service" else "repositories"
    contract = f"neurath.application.ports.{role}.probe"
    interface_source = f"from abc import ABC, abstractmethod\nclass {interface}(ABC):\n @abstractmethod\n def probe(self): raise NotImplementedError\n"
    if aliased:
        base = f"from {contract} import {interface} as Contract\nclass GitProbeService(Contract):\n def probe(self): return 'observed'\n"
        concrete = f"from neurath.infrastructure.base import GitProbeService as Parent\nclass {implementation}(Parent): pass\n"
        return {
            contract: interface_source,
            "neurath.infrastructure.base": base,
            "neurath.infrastructure.probe": concrete,
        }
    concrete = f"from {contract} import {interface} as Contract\nclass {implementation}(Contract):\n def probe(self): return 'observed'\n"
    return {contract: interface_source, "neurath.infrastructure.probe": concrete}


@pytest.mark.parametrize(
    "suffix,interface,implementation,code",
    [
        ("Service", "IProbe", "GitProbe", "INTERFACE_NAME"),
        ("Service", "ProbeService", "GitProbeService", "INTERFACE_NAME"),
        ("Service", "IService", "GitService", "INTERFACE_NAME"),
        ("Repository", "IProbe", "SQLAlchemyProbe", "INTERFACE_NAME"),
        ("Repository", "ProbeRepository", "SQLAlchemyProbeRepository", "INTERFACE_NAME"),
        ("Service", "IProbeService", "GitProbe", "IMPLEMENTATION_NAME"),
        ("Service", "IProbeService", "ProbeService", "IMPLEMENTATION_NAME"),
        ("Service", "IProbeService", "IProbeService", "IMPLEMENTATION_NAME"),
        ("Service", "IProbeService", "DefaultProbeService", "IMPLEMENTATION_NAME"),
        ("Service", "IProbeService", "GitOtherService", "IMPLEMENTATION_NAME"),
        ("Repository", "IProbeRepository", "SQLAlchemyProbe", "IMPLEMENTATION_NAME"),
        ("Repository", "IProbeRepository", "ProbeRepository", "IMPLEMENTATION_NAME"),
        ("Repository", "IProbeRepository", "DefaultProbeRepository", "IMPLEMENTATION_NAME"),
        ("Repository", "IProbeRepository", "SQLAlchemyOtherRepository", "IMPLEMENTATION_NAME"),
    ],
)
def test_role_naming_rejects_missing_suffix_interface_prefix_and_technology(
    suffix, interface, implementation, code
):
    errors = ArchitectureChecker(role_sources(suffix, interface, implementation)).check()
    assert any(code in error for error in errors), errors


@pytest.mark.parametrize(
    "suffix,interface,implementation",
    [
        ("Service", "IProbeService", "GitProbeService"),
        ("Service", "IProbeService", "SubprocessProbeService"),
        ("Service", "IProbeService", "StderrProbeService"),
        ("Service", "IProbeService", "PosixProbeService"),
        ("Repository", "IProbeRepository", "SQLAlchemyProbeRepository"),
    ],
)
def test_role_naming_accepts_new_contracts_without_class_allowlist(
    suffix, interface, implementation
):
    assert ArchitectureChecker(role_sources(suffix, interface, implementation)).check() == []


def test_role_naming_follows_aliases_and_indirect_inheritance_even_after_module_move():
    good = role_sources("Service", "IProbeService", "GitProbeService", aliased=True)
    assert ArchitectureChecker(good).check() == []
    bad = role_sources("Service", "IProbeService", "ProbeService", aliased=True)
    bad["neurath.other.probe"] = bad.pop("neurath.infrastructure.probe")
    assert any("IMPLEMENTATION_NAME" in error for error in ArchitectureChecker(bad).check())


def test_naming_gate_returns_failure_for_new_source_file(tmp_path):
    import shutil

    root = Path(__file__).resolve().parents[1]
    tools = tmp_path / "tools"
    tools.mkdir()
    shutil.copyfile(root / "tools/architecture.py", tools / "architecture.py")
    sources = role_sources("Service", "IProbeService", "GitProbeService")
    for module, source in sources.items():
        target = tmp_path / "src" / Path(*module.split(".")).with_suffix(".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    passed = subprocess.run(
        [sys.executable, str(tools / "architecture.py")], capture_output=True, text=True
    )
    assert passed.returncode == 0, passed.stdout + passed.stderr
    target = tmp_path / "src/neurath/infrastructure/new_service.py"
    target.write_text(
        "from neurath.application.ports.services.probe import IProbeService\nclass ProbeService(IProbeService):\n def probe(self): return None\n"
    )
    failed = subprocess.run(
        [sys.executable, str(tools / "architecture.py")], capture_output=True, text=True
    )
    assert failed.returncode == 1
    assert "new_service" in failed.stdout and "IMPLEMENTATION_NAME" in failed.stdout
    assert "ARCHITECTURE_CHECK_OK" not in failed.stdout


@pytest.mark.parametrize(
    "base", ["ICommandUseCase", "IQueryUseCase", "IAsyncCommandUseCase", "IAsyncQueryUseCase"]
)
def test_usecase_suffix_is_required_without_technology_prefix(base):
    package = "command" if "Command" in base else "query"
    source = f"from spakky.domain.application.{package} import {base} as Contract\nclass CreateTask(Contract): pass\n"
    errors = ArchitectureChecker({"neurath.application.usecases.create_task": source}).check()
    assert any("USECASE_NAME" in error for error in errors)
    fixed = source.replace("class CreateTask(", "class CreateTaskUseCase(")
    assert ArchitectureChecker({"neurath.application.usecases.create_task": fixed}).check() == []


def test_usecase_suffix_follows_decorator_alias_and_indirect_framework_contract():
    source = "from spakky.core.stereotype.usecase import UseCase as Registered\n@Registered()\nclass CreateTask: pass\n"
    errors = ArchitectureChecker({"neurath.application.usecases.create_task": source}).check()
    assert any("USECASE_NAME" in error for error in errors)
    sources = {
        "neurath.application.base": "from spakky.domain.application.command import ICommandUseCase as Contract\nclass BaseUseCase(Contract): pass\n",
        "neurath.application.usecases.create_task": "from neurath.application.base import BaseUseCase as Parent\nclass CreateTask(Parent): pass\n",
    }
    assert any("USECASE_NAME" in error for error in ArchitectureChecker(sources).check())
    sources["neurath.application.usecases.create_task"] = sources[
        "neurath.application.usecases.create_task"
    ].replace("class CreateTask(", "class CreateTaskUseCase(")
    assert ArchitectureChecker(sources).check() == []


@pytest.mark.parametrize(
    "module,source,code",
    [
        (
            "neurath.infrastructure.hooks",
            'from spakky.plugins.typer.stereotypes.cli_controller import CliController as CLI\n@CLI("hook")\nclass HookCliController: pass',
            "CLI_BOUNDARY",
        ),
        (
            "neurath.transport.cli.hooks",
            "from neurath.infrastructure.providers import request_container",
            "TRANSPORT_BOUNDARY",
        ),
        (
            "neurath.transport.cli.hooks",
            "import spakky.plugins.sqlalchemy.persistency.transaction",
            "TRANSPORT_BOUNDARY",
        ),
        ("neurath.application.usecases.hook", "import typer", "APPLICATION_BOUNDARY"),
        ("neurath.domain.hook", "import spakky.plugins.typer", "DOMAIN_BOUNDARY"),
    ],
)
def test_cli_boundary_keeps_protocol_in_transport_and_composition_outside(module, source, code):
    assert any(code in error for error in ArchitectureChecker({module: source}).check())


def test_spakky_cli_controller_and_bootstrap_composition_are_allowed():
    sources = {
        "neurath.transport.cli.hooks": 'from spakky.plugins.typer.stereotypes.cli_controller import CliController\n@CliController("hook")\nclass HookCliController: pass',
        "neurath.bootstrap": "from neurath.transport.cli.hooks import HookCliController\nfrom neurath.infrastructure.providers import request_container",
    }
    assert ArchitectureChecker(sources).check() == []


def test_command_sqlalchemy_dependency_is_rejected_even_with_query_in_same_module():
    sources = {
        "neurath.application.usecases.mixed": """
from spakky.domain.application.command import IAsyncCommandUseCase as Write
from spakky.domain.application.query import IAsyncQueryUseCase as Read
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager as Database
from sqlalchemy import select as lookup
class ReadUseCase(Read):
    async def run(self, query):
        return lookup(1)
class BaseWriteUseCase(Write):
    pass
class WriteUseCase(BaseWriteUseCase):
    def __init__(self, database: Database):
        self.database = database
    async def run(self, command):
        return await self.database.session.scalar(lookup(1))
"""
    }
    errors = ArchitectureChecker(sources).check()
    assert any("COMMAND_PERSISTENCE" in error for error in errors)
    assert not any("APPLICATION_BOUNDARY" in error for error in errors)


def test_query_sqlalchemy_read_is_allowed_but_command_module_import_is_rejected():
    query = """
from spakky.domain.application.query import IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import select
from neurath.infrastructure.models.task import TaskModel
class ReadUseCase(IAsyncQueryUseCase):
    def __init__(self, session: AsyncSessionManager):
        self.session = session
    async def run(self, query):
        return await self.session.session.scalar(select(TaskModel))
"""
    assert ArchitectureChecker({"neurath.application.usecases.read": query}).check() == []
    errors = ArchitectureChecker(
        {"neurath.application.usecases.write": "import sqlalchemy"}
    ).check()
    assert any("APPLICATION_BOUNDARY" in error for error in errors)


def test_event_adapter_rejects_work_service_dependency_through_alias_and_inheritance():
    sources = {
        "neurath.transport.events.base": """
from spakky.event.stereotype.event_handler import EventHandler as Event
@Event()
class BaseHandler:
    pass
""",
        "neurath.transport.events.runtime": """
from neurath.transport.events.base import BaseHandler
from neurath.application.ports.services.writer_observer import IWriterObserverService as Observer
class RuntimeHandler(BaseHandler):
    def __init__(self, observer: Observer | None):
        self.observer = observer
""",
    }
    errors = ArchitectureChecker(sources).check()
    assert any("EVENT_HANDLER_DEPENDENCY" in error for error in errors)


def test_event_adapter_accepts_a_usecase_dependency_without_service_naming_rules():
    sources = {
        "neurath.application.usecases.run": """
from spakky.domain.application.command import IAsyncCommandUseCase as Command
class RunUseCase(Command):
    async def run(self, command):
        pass
""",
        "neurath.transport.events.run": """
from spakky.event.stereotype.event_handler import EventHandler as Event
from neurath.application.usecases.run import RunUseCase as Run
@Event()
class RunHandler:
    def __init__(self, operation: Run):
        self.operation = operation
    async def receive(self, event):
        await self.operation.run(event)
""",
    }
    assert ArchitectureChecker(sources).check() == []


def test_event_adapter_settings_are_not_misclassified_as_work_services():
    source = """
from spakky.event.stereotype.event_handler import EventHandler
@EventHandler()
class Handler:
    def __init__(self, label: str):
        self.label = label
"""
    assert ArchitectureChecker({"neurath.transport.events.settings": source}).check() == []
