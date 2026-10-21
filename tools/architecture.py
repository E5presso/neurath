"""구체적인 구조 문법을 검사하며 의미적 응집성은 사람 검토에 남긴다."""

import ast
import re
from pathlib import Path


class ArchitectureChecker:
    """로컬 import·상속 관계를 해석해 계층 의존과 등록된 프레임워크 계약을 검사한다."""

    def __init__(self, sources: dict[str, str]) -> None:
        """점으로 구분한 모듈 이름을 키로 갖는 전체 소스 트리를 구문 분석한다.

        Args:
            sources: 점으로 구분한 모듈 이름을 키로 갖는 Python 소스 텍스트.
        """
        self.trees = {module: ast.parse(source) for module, source in sources.items()}
        self.sources = sources
        self.aliases: dict[str, str] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        for module, tree in self.trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for item in node.names:
                        self.aliases[f"{module}.{item.asname or item.name.split('.')[0]}"] = (
                            item.name if item.asname else item.name.split(".")[0]
                        )
                    continue
                if isinstance(node, ast.ImportFrom):
                    imported = self._import_module(module, node)
                    for item in node.names:
                        self.aliases[f"{module}.{item.asname or item.name}"] = (
                            f"{imported}.{item.name}"
                        )
                    continue
                if isinstance(node, ast.ClassDef):
                    self.classes[f"{module}.{node.name}"] = node
            for node in tree.body:
                if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
                    self.aliases[f"{module}.{node.name.id}"] = self._name(module, node.value)
                    continue
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                target = node.targets[0]
                if not isinstance(target, ast.Name) or not isinstance(
                    node.value, (ast.Name, ast.Attribute)
                ):
                    continue
                self.aliases[f"{module}.{target.id}"] = self._name(module, node.value)

    def _import_module(self, module: str, node: ast.ImportFrom) -> str:
        """임포트하는 모듈의 패키지를 기준으로 상대 임포트를 해석한다.

        Args:
            module: 구문 노드를 포함하는 점으로 구분한 모듈 이름.
            node: 임포트 심벌을 해석할 구문 노드.

        Returns:
            str: 임포트 문에서 해석한 절대 모듈 이름.
        """
        if node.level == 0:
            return node.module or ""
        parts = module.split(".")[: -node.level]
        if node.module:
            parts.extend(node.module.split("."))
        return ".".join(parts)

    def _name(self, module: str, node: ast.AST) -> str:
        """타입 표기·기반 클래스·호출 대상의 정규 심벌 이름을 반환한다.

        Args:
            module: 구문 노드를 포함하는 점으로 구분한 모듈 이름.
            node: 임포트 심벌을 해석할 구문 노드.

        Returns:
            str: 정규 심벌 이름이며 지원하지 않는 문법이면 빈 문자열.
        """
        if isinstance(node, ast.Subscript):
            return self._name(module, node.value)
        if isinstance(node, ast.Name):
            name = f"{module}.{node.id}"
        elif isinstance(node, ast.Attribute):
            name = self._name(module, node.value) + "." + node.attr
        else:
            return ""
        seen: set[str] = set()
        while name in self.aliases and name not in seen:
            seen.add(name)
            name = self.aliases[name]
        return name

    def _ancestors(self, symbol: str, seen: set[str] | None = None) -> set[str]:
        """임포트한 기반 클래스와 간접 로컬 상속을 포함하여 명시적 상속을 추적한다.

        Args:
            symbol: 조사할 클래스의 완전한 이름.
            seen: 상속 순환을 끊기 위해 기록한 이미 방문한 클래스 이름들.

        Returns:
            set[str]: 외부 기반 클래스를 포함하는 클래스와 모든 상위 클래스 이름들.
        """
        visited = set() if seen is None else set(seen)
        if symbol in visited or symbol not in self.classes:
            return {symbol}
        visited.add(symbol)
        module = symbol.rsplit(".", 1)[0]
        result = {symbol}
        for base in self.classes[symbol].bases:
            result.update(self._ancestors(self._name(module, base), visited))
        return result

    def _is_query_module(self, module: str) -> bool:
        """조회 계약을 구현한 유스케이스가 있는 모듈인지 확인한다.

        Args:
            module: 검사할 모듈의 정규 이름.

        Returns:
            bool: 실제 QueryUseCase 계약을 구현한 클래스가 있으면 True.
        """
        contracts = {
            f"{package}.{name}"
            for package in ("spakky.domain", "spakky.domain.application.query")
            for name in ("IQueryUseCase", "IAsyncQueryUseCase")
        }
        return any(
            symbol.rsplit(".", 1)[0] == module and bool(self._ancestors(symbol) & contracts)
            for symbol in self.classes
        )

    def _is_orm_symbol(self, symbol: str) -> bool:
        """SQLAlchemy API 또는 영속성 모델을 직접 참조하는 심벌인지 확인한다.

        Args:
            symbol: 별칭을 해석한 심벌 이름.

        Returns:
            bool: SQLAlchemy 또는 ORM 매핑 심벌이면 True.
        """
        return any(
            symbol == prefix or symbol.startswith(prefix + ".")
            for prefix in (
                "sqlalchemy",
                "spakky.plugins.sqlalchemy",
                "neurath.infrastructure.models",
            )
        )

    def _check_execution_boundary(
        self, module: str, node: ast.ClassDef, ancestors: set[str], decorators: set[str]
    ) -> list[str]:
        """명령의 영속성 직접 접근과 이벤트 어댑터의 작업 의존성 주입을 검사한다.

        Args:
            module: 클래스가 정의된 모듈.
            node: 검사할 클래스 구문.
            ancestors: 별칭과 간접 상속을 해석한 기반 계약.
            decorators: 별칭을 해석한 클래스 데코레이터.

        Returns:
            list[str]: 확인된 Command/Query·이벤트 어댑터 경계 위반.
        """
        commands = {
            f"{package}.{name}"
            for package in ("spakky.domain", "spakky.domain.application.command")
            for name in ("ICommandUseCase", "IAsyncCommandUseCase")
        }
        errors = []
        if ancestors & commands:
            for item in ast.walk(node):
                if isinstance(item, (ast.Name, ast.Attribute)) and self._is_orm_symbol(
                    self._name(module, item)
                ):
                    errors.append(
                        f"{module}:{item.lineno} COMMAND_PERSISTENCE: commands depend on aggregate repository contracts"
                    )
        handler = "spakky.event.stereotype.event_handler.EventHandler"
        inherited_decorators = {
            self._name(
                parent.rsplit(".", 1)[0],
                decorator.func if isinstance(decorator, ast.Call) else decorator,
            )
            for parent in ancestors
            if parent in self.classes
            for decorator in self.classes[parent].decorator_list
        }
        if handler not in decorators | inherited_decorators:
            return errors
        for method in node.body:
            if not isinstance(method, ast.FunctionDef) or method.name != "__init__":
                continue
            for argument in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs):
                if argument.arg == "self" or argument.annotation is None:
                    continue
                dependencies = {
                    ancestor
                    for item in ast.walk(argument.annotation)
                    if isinstance(item, (ast.Name, ast.Attribute))
                    for ancestor in self._ancestors(self._name(module, item))
                }
                if any(
                    self._is_orm_symbol(dependency)
                    or dependency.startswith(
                        (
                            "neurath.application.ports.services.",
                            "neurath.application.ports.repositories.",
                            "spakky.event.event_publisher.",
                        )
                    )
                    for dependency in dependencies
                ):
                    errors.append(
                        f"{module}:{argument.lineno} EVENT_HANDLER_DEPENDENCY: delegate service and repository operations to use cases"
                    )
        return errors

    def _check_import(self, module: str, node: ast.Import | ast.ImportFrom) -> list[str]:
        """단일 import의 계층 의존 방향과 명시적인 Protocol 반입을 검사한다.

        Args:
            module: import가 포함된 소스 모듈 이름.
            node: 검사할 import 구문.

        Returns:
            list[str]: 이 import에서 발견한 의존 방향·타입 계약 위반.
        """
        errors: list[str] = []
        location = f"{module}:{node.lineno}"
        imported_modules = (
            [item.name for item in node.names]
            if isinstance(node, ast.Import)
            else [self._import_module(module, node)]
        )
        for imported in imported_modules:
            if module.startswith("neurath.domain.") and imported.startswith(
                (
                    "neurath.application",
                    "neurath.infrastructure",
                    "neurath.transport",
                    "neurath.bootstrap",
                    "sqlalchemy",
                    "alembic",
                    "typer",
                    "spakky.plugins.typer",
                    "spakky.data",
                    "spakky.plugins.sqlalchemy",
                )
            ):
                errors.append(f"{location} DOMAIN_BOUNDARY: {imported}")
            if module.startswith("neurath.application."):
                query_read = self._is_query_module(module) and self._is_orm_symbol(imported)
                forbidden = imported.startswith(
                    (
                        "neurath.infrastructure",
                        "neurath.transport",
                        "neurath.bootstrap",
                        "sqlalchemy",
                        "alembic",
                        "typer",
                        "spakky.plugins.typer",
                        "spakky.plugins.sqlalchemy",
                    )
                )
                if forbidden and not query_read:
                    errors.append(f"{location} APPLICATION_BOUNDARY: {imported}")
            if module.startswith("neurath.infrastructure.") and imported.startswith(
                ("neurath.transport", "neurath.bootstrap")
            ):
                errors.append(f"{location} INFRASTRUCTURE_BOUNDARY: {imported}")
            if (
                module.startswith("neurath.transport.")
                and imported.startswith(
                    (
                        "neurath.infrastructure",
                        "neurath.bootstrap",
                        "sqlalchemy",
                        "alembic",
                        "spakky.plugins.sqlalchemy",
                    )
                )
                and imported != "spakky.plugins.sqlalchemy.persistency.connection_manager"
            ):
                errors.append(f"{location} TRANSPORT_BOUNDARY: {imported}")
        if (
            isinstance(node, ast.ImportFrom)
            and node.module in {"typing", "typing_extensions"}
            and any(item.name == "Protocol" for item in node.names)
        ):
            errors.append(
                f"{location} FORBIDDEN_TYPE: Protocol was explicitly excluded from this project"
            )
        return errors

    def _check_port(self, module: str, node: ast.ClassDef, ancestors: set[str]) -> list[str]:
        """명시적 port 선언에만 추상 기반과 메서드 계약 검사를 적용한다.

        Args:
            module: 클래스가 선언된 모듈 이름.
            node: 검사할 클래스 선언.
            ancestors: 별칭·간접 상속을 해석한 기반 타입 이름들.

        Returns:
            list[str]: 추상 계약이 빠진 port와 메서드의 진단.
        """
        if not (
            module.startswith("neurath.application.ports.")
            and node.name.startswith("I")
            and node.name[1:2].isupper()
        ):
            return []
        errors: list[str] = []
        if "abc.ABC" not in ancestors:
            errors.append(f"{module}:{node.lineno} NOMINAL_PORT: declare an abstract nominal port")
        for method in node.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                self._name(module, item) == "abc.abstractmethod" for item in method.decorator_list
            ):
                continue
            errors.append(f"{module}:{method.lineno} ABSTRACT_METHOD: {node.name}.{method.name}")
        return errors

    def _check_role_name(
        self, module: str, node: ast.ClassDef, ancestors: set[str], decorators: set[str]
    ) -> list[str]:
        """서비스·저장소 계약과 구현체의 역할 접미사·기술 접두어를 검사한다.

        전체 소스의 포트 선언과 별칭·간접 상속을 따라 구현체를 찾는다. 실제 기술을
        표현하는 접두어는 현재 구현에 사용하는 Git·Subprocess·Stderr·Posix·SQLAlchemy다.
        새로운 기술 구현을 추가할 때 해당 기술 접두어와 정상·실패 fixture를 함께 추가한다.

        Args:
            module: 선언이 포함된 모듈 이름.
            node: 검사할 클래스 선언.
            ancestors: 별칭과 간접 상속을 해석한 타입들.
            decorators: 실제 등록 데코레이터의 정규 이름들.

        Returns:
            list[str]: 인터페이스 형식 또는 구현체 명명 규칙 위반.
        """
        roles = {
            "Service": "neurath.application.ports.services.",
            "Repository": "neurath.application.ports.repositories.",
        }
        technologies = {
            "Service": ("Git", "Subprocess", "Stderr", "Posix"),
            "Repository": ("SQLAlchemy",),
        }
        errors: list[str] = []
        location = f"{module}:{node.lineno}"
        for suffix, namespace in roles.items():
            if module.startswith(namespace):
                if not (
                    node.name.startswith("I")
                    and node.name[1:2].isupper()
                    and node.name.endswith(suffix)
                    and len(node.name) > len(suffix) + 1
                ):
                    errors.append(f"{location} INTERFACE_NAME: use I<role>{suffix}")
                continue
            contracts = {
                parent.rsplit(".", 1)[1][1:]
                for parent in ancestors
                if parent.startswith(namespace) and parent in self.classes
            }
            stereotype = (
                "spakky.data.stereotype.repository.Repository"
                if suffix == "Repository"
                else "spakky.core.stereotype.service.Service"
            )
            if not contracts and stereotype not in decorators:
                continue
            expected = {
                technology + contract
                for technology in technologies[suffix]
                for contract in contracts
            }
            if node.name not in expected or not node.name.endswith(suffix):
                errors.append(
                    f"{location} IMPLEMENTATION_NAME: replace interface I with a concrete technology; end with {suffix}"
                )
        return errors

    def _check_class(self, module: str, node: ast.ClassDef) -> list[str]:
        """등록된 구성요소의 기반과 하위 타입을 보존하는 생성 메서드를 검사한다.

        Args:
            module: 클래스가 선언된 모듈 이름.
            node: 실제 데코레이터·상속·메서드를 확인할 선언.

        Returns:
            list[str]: 이 클래스와 메서드의 명시적 계약 위반.
        """
        errors: list[str] = []
        location = f"{module}:{node.lineno}"
        usecase_contracts = {
            f"{package}.{name}"
            for package in (
                "spakky.domain",
                "spakky.domain.application.command",
                "spakky.domain.application.query",
            )
            for name in (
                "ICommandUseCase",
                "IQueryUseCase",
                "IAsyncCommandUseCase",
                "IAsyncQueryUseCase",
            )
        }
        table_bases = {
            "sqlalchemy.orm.DeclarativeBase",
            "spakky.plugins.sqlalchemy.orm.table.AbstractTable",
            "spakky.plugins.sqlalchemy.orm.table.AbstractMappableTable",
        }
        repository_bases = {
            "spakky.data.persistency.repository.IGenericRepository",
            "spakky.data.persistency.repository.IAsyncGenericRepository",
            "spakky.plugins.sqlalchemy.persistency.repository.AbstractGenericRepository",
            "spakky.plugins.sqlalchemy.persistency.repository.AbstractAsyncGenericRepository",
        }
        symbol = f"{module}.{node.name}"
        ancestors = self._ancestors(symbol)
        decorators = {
            self._name(module, item.func if isinstance(item, ast.Call) else item)
            for item in node.decorator_list
        }
        if (
            "spakky.plugins.typer.stereotypes.cli_controller.CliController" in decorators
            and not module.startswith("neurath.transport.")
        ):
            errors.append(f"{location} CLI_BOUNDARY: CLI controllers belong to transport")
        errors.extend(self._check_execution_boundary(module, node, ancestors, decorators))
        errors.extend(self._check_port(module, node, ancestors))
        errors.extend(self._check_role_name(module, node, ancestors, decorators))
        has_port = any(
            parent in self.classes
            and parent.startswith("neurath.application.ports.")
            and "abc.ABC" in self._ancestors(parent)
            for parent in ancestors
        )
        if (
            "spakky.data.stereotype.repository.Repository" in decorators
            and not has_port
            and not ancestors.intersection(repository_bases)
        ):
            errors.append(
                f"{location} NOMINAL_IMPLEMENTATION: declare the repository contract being implemented"
            )
        is_usecase = "spakky.core.stereotype.usecase.UseCase" in decorators or bool(
            ancestors.intersection(usecase_contracts)
        )
        if is_usecase and not node.name.endswith("UseCase"):
            errors.append(f"{location} USECASE_NAME: use-case names must end with UseCase")
        if "spakky.core.stereotype.usecase.UseCase" in decorators and not ancestors.intersection(
            usecase_contracts
        ):
            errors.append(f"{location} FRAMEWORK_USECASE: implement a Spakky use-case contract")
        if "spakky.plugins.sqlalchemy.orm.table.Table" in decorators and not ancestors.intersection(
            table_bases
        ):
            errors.append(
                f"{location} DECLARATIVE_ORM: registered Table models require their declarative base"
            )
        for method in node.body:
            if (
                not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                or not method.args.args
            ):
                continue
            if not any(
                self._name(module, item).rsplit(".", 1)[-1] == "classmethod"
                for item in method.decorator_list
            ):
                continue
            constructed_type = method.args.args[0].arg
            returned = [
                item.value
                for item in ast.walk(method)
                if isinstance(item, ast.Return)
                and item.value is not None
                and not (isinstance(item.value, ast.Constant) and item.value.value is None)
            ]
            preserves_subclass = bool(returned) and all(
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == constructed_type
                for value in returned
            )
            if (
                preserves_subclass
                and method.returns is not None
                and any(
                    isinstance(annotation, (ast.Name, ast.Attribute))
                    and self._name(module, annotation) == symbol
                    for annotation in ast.walk(method.returns)
                )
            ):
                errors.append(
                    f"{module}:{method.lineno} SELF_RETURN: a cls constructor preserves the caller's subtype"
                )
        return errors

    def check(self) -> list[str]:
        """소스·import·클래스별 검사를 모아 위치와 규칙 코드로 반환한다.

        각 구문에 적용되지 않는 검사는 건너뛰되, 한 구문에서 발견한 여러 진단을
        모두 보존한다. 구문 검사로 도메인 책임이나 추상화의 필요성을 판정하지 않는다.

        Returns:
            list[str]: 중복을 제거하고 정렬한 현재 소스의 계약 위반 목록.
        """
        errors: list[str] = []
        protocols = {"typing.Protocol", "typing_extensions.Protocol"}
        for module, tree in self.trees.items():
            for line, source_line in enumerate(self.sources[module].splitlines(), 1):
                if not re.search(r"#\s*pragma:\s*no\s*(cover|branch)", source_line):
                    continue
                errors.append(
                    f"{module}:{line} SUPPRESSION: coverage exclusions violate the requested zero-exclusion check"
                )
            for node in ast.walk(tree):
                location = f"{module}:{getattr(node, 'lineno', 1)}"
                if (
                    isinstance(node, (ast.Name, ast.Attribute, ast.Subscript))
                    and self._name(module, node) in protocols
                ):
                    errors.append(
                        f"{location} FORBIDDEN_TYPE: Protocol was explicitly excluded from this project"
                    )
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    errors.extend(self._check_import(module, node))
                    continue
                if not isinstance(node, ast.ClassDef):
                    continue
                errors.extend(self._check_class(module, node))
        return sorted(set(errors))


def check_tree(root: Path) -> list[str]:
    """새 파일이 검사를 우회하지 못하도록 현재 소스 모듈 전체를 탐색한다.

    Args:
        root: 조사할 체크아웃의 루트 디렉터리.

    Returns:
        list[str]: 탐색한 현재 패키지 모듈 전체의 위반 목록.
    """
    sources: dict[str, str] = {}
    for path in sorted((root / "src").rglob("*.py")):
        module = ".".join(path.relative_to(root / "src").with_suffix("").parts)
        sources[module] = path.read_text()
    return ArchitectureChecker(sources).check()


def main() -> None:
    """전체 소스 구조 검사를 실행하고 위반 시 실패 상태로 종료한다.

    Raises:
        SystemExit: 구조 검사에서 하나 이상의 위반을 발견한 경우.
    """
    errors = check_tree(Path(__file__).resolve().parents[1])
    for error in errors:
        print(error)
    if errors:
        raise SystemExit(1)
    print("ARCHITECTURE_CHECK_OK")


if __name__ == "__main__":
    main()
