"""구체적인 구조 문법을 검사하며 의미적 응집성은 사람 검토에 남긴다."""

import ast
import re
from pathlib import Path


class ArchitectureChecker:
    """명시적 계약을 검사하기 전에 로컬 임포트 별칭과 상속을 해석한다."""

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
                elif isinstance(node, ast.ImportFrom):
                    imported = self._import_module(module, node)
                    for item in node.names:
                        self.aliases[f"{module}.{item.asname or item.name}"] = (
                            f"{imported}.{item.name}"
                        )
                elif isinstance(node, ast.ClassDef):
                    self.classes[f"{module}.{node.name}"] = node
            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    target = node.targets[0]
                    if isinstance(target, ast.Name) and isinstance(
                        node.value, (ast.Name, ast.Attribute)
                    ):
                        self.aliases[f"{module}.{target.id}"] = self._name(module, node.value)
                elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
                    self.aliases[f"{module}.{node.name.id}"] = self._name(module, node.value)

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

    def check(self) -> list[str]:
        """각 위반에 대해 모듈과 줄 번호 및 수정 가능한 규칙 코드를 반환한다.

        Returns:
            list[str]: 모듈·줄 번호·규칙 코드로 구성한 중복 없는 정렬된 위반 목록.
        """
        errors: list[str] = []
        forbidden = {
            f"{package}.{name}"
            for package in ("typing", "typing_extensions")
            for name in ("Protocol", "Literal", "Any", "cast")
        }
        for module, tree in self.trees.items():
            migration = ".infrastructure.migrations." in module
            if module.rsplit(".", 1)[-1] == "core" or (
                module.rsplit(".", 1)[-1].startswith("core_") and not migration
            ):
                errors.append(f"{module}:1 CORE: organize modules by responsibility")
            for line, text in enumerate(self.sources[module].splitlines(), start=1):
                if re.search(
                    r"#\s*(type:\s*ignore|noqa|pyrefly:|pragma:\s*no\s*(cover|branch))", text
                ):
                    errors.append(f"{module}:{line} SUPPRESSION: correct the type or lint error")
            if not ast.get_docstring(tree):
                errors.append(f"{module}:1 DOCSTRING: document the module responsibility")
            for node in ast.walk(tree):
                line = getattr(node, "lineno", 1)
                location = f"{module}:{line}"
                if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
                    name = self._name(module, node)
                    if name in forbidden:
                        errors.append(f"{location} FORBIDDEN_TYPE: {name}")
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports = (
                        [item.name for item in node.names]
                        if isinstance(node, ast.Import)
                        else [self._import_module(module, node)]
                    )
                    for imported in imports:
                        if ".domain." in module and not (
                            imported.startswith(("neurath.domain", "spakky.domain"))
                            or imported == "spakky.core.common.mutability"
                            or imported.split(".")[0]
                            in {
                                "abc",
                                "dataclasses",
                                "enum",
                                "typing",
                                "uuid",
                                "datetime",
                                "decimal",
                                "collections",
                                "__future__",
                            }
                        ):
                            errors.append(f"{location} DOMAIN_BOUNDARY: {imported}")
                        if ".application." in module and imported.startswith(
                            ("neurath.infrastructure", "neurath.transport", "sqlalchemy", "alembic")
                        ):
                            errors.append(f"{location} APPLICATION_BOUNDARY: {imported}")
                        if ".infrastructure." in module and imported.startswith(
                            "neurath.transport"
                        ):
                            errors.append(f"{location} INFRASTRUCTURE_BOUNDARY: {imported}")
                    for item in node.names:
                        if (
                            item.name in {"Protocol", "Literal", "Any", "cast"}
                            and isinstance(node, ast.ImportFrom)
                            and node.module in {"typing", "typing_extensions"}
                        ):
                            errors.append(f"{location} FORBIDDEN_TYPE: {item.name}")
                        if item.name == "*":
                            errors.append(
                                f"{location} EXPLICIT_IMPORT: wildcard imports obscure contracts"
                            )
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if not ast.get_docstring(node):
                        errors.append(f"{location} DOCSTRING: document {node.name}")
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if ".infrastructure.repositories." in module and node.name in {
                        "get",
                        "get_or_none",
                        "contains",
                        "range",
                        "save",
                        "save_all",
                        "delete",
                        "delete_all",
                    }:
                        errors.append(
                            f"{location} FRAMEWORK_CRUD: inherit the Spakky repository implementation"
                        )
                    if ".repositories." in module and node.name in {
                        "add",
                        "insert",
                        "create",
                        "update",
                    }:
                        errors.append(
                            f"{location} REPOSITORY_SAVE: use save for insertion and update"
                        )
                    if node.name in {"transaction", "commit", "rollback", "uow", "unit_of_work"}:
                        errors.append(f"{location} TRANSACTION_WRAPPER: use ORM Session lifecycle")
                    if any(
                        isinstance(child, (ast.Yield, ast.YieldFrom)) for child in ast.walk(node)
                    ):
                        if any(
                            isinstance(child, ast.Call)
                            and isinstance(child.func, ast.Attribute)
                            and child.func.attr in {"begin", "commit", "rollback"}
                            for child in ast.walk(node)
                        ):
                            errors.append(
                                f"{location} TRANSACTION_WRAPPER: resource providers must not wrap transactions"
                            )
                    if ".ports.repositories." in module:
                        if node.name not in {
                            "get",
                            "find",
                            "list",
                            "find_by_location",
                            "save",
                            "delete",
                            "exists",
                        }:
                            errors.append(
                                f"{location} PRIMITIVE_REPOSITORY: expose lookup and storage only"
                            )
                        if any(
                            argument.arg == "expected_revision"
                            for argument in node.args.args + node.args.kwonlyargs
                        ):
                            errors.append(
                                f"{location} PRIMITIVE_REPOSITORY: revision decisions belong to the entity"
                            )
                if ".infrastructure.repositories." in module:
                    selected = None
                    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Return)):
                        selected = node.value
                    elif isinstance(node, ast.ListComp):
                        selected = node.elt
                    if isinstance(selected, ast.BoolOp) and isinstance(selected.op, ast.Or):
                        if any(
                            isinstance(value, ast.Call)
                            and isinstance(value.func, ast.Attribute)
                            and value.func.attr == "get"
                            for value in selected.values
                        ):
                            errors.append(
                                f"{location} EXPLICIT_OBJECT_SELECTION: use a named value and is None branch"
                            )
                if isinstance(node, ast.Call):
                    called = self._name(module, node.func)
                    if ".transport." in module and called.endswith(
                        ("Repository", "UseCase", "Observer")
                    ):
                        errors.append(
                            f"{location} DEPENDENCY_COMPOSITION: resolve dependencies through Spakky"
                        )
                    if (
                        ".infrastructure.repositories." in module
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr
                        in {"move", "associate", "identify", "owner_of", "root_for", "create"}
                    ):
                        errors.append(
                            f"{location} REPOSITORY_POLICY: call domain actions in the application layer"
                        )
                    if not migration and (
                        (
                            called.startswith("sqlalchemy.")
                            and called.rsplit(".", 1)[-1] in {"Table", "Column"}
                        )
                        or called.endswith(".map_imperatively")
                    ):
                        errors.append(f"{location} DECLARATIVE_ORM: use Mapped and mapped_column")
                if not isinstance(node, ast.ClassDef):
                    continue
                for method in node.body:
                    if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if not any(
                        isinstance(decorator, ast.Name) and decorator.id == "classmethod"
                        for decorator in method.decorator_list
                    ):
                        continue
                    if method.returns is not None and any(
                        isinstance(annotation, ast.Name) and annotation.id == node.name
                        for annotation in ast.walk(method.returns)
                    ):
                        errors.append(
                            f"{module}:{method.lineno} SELF_RETURN: use Self in class factories"
                        )
                if ".repositories." in module and node.name in {
                    "IProjectLocationRepository",
                    "ProjectLocationRepository",
                }:
                    errors.append(
                        f"{location} AGGREGATE_OWNERSHIP: persist locations through Project"
                    )
                if "unitofwork" in node.name.lower().replace("_", "") or node.name.lower().endswith(
                    "uow"
                ):
                    errors.append(f"{location} TRANSACTION_WRAPPER: remove custom unit of work")
                if node.name == "Core":
                    errors.append(f"{location} CORE: name a specific use-case responsibility")
                if ".ports.usecases." in module or (
                    ".application.usecases." in module
                    and node.name.startswith("I")
                    and node.name.endswith("UseCase")
                ):
                    errors.append(
                        f"{location} USECASE_INTERFACE: keep concrete application use cases"
                    )
                if node.name == "SqliteDatabase":
                    errors.append(
                        f"{location} DATABASE_WRAPPER: use engine and initialization functions"
                    )
                if ".domain." in module:
                    fields = {
                        child.target.id
                        for child in node.body
                        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
                    }
                    is_entity = "id" in fields
                    if is_entity:
                        for decorator in node.decorator_list:
                            if (
                                self._name(
                                    module,
                                    decorator.func
                                    if isinstance(decorator, ast.Call)
                                    else decorator,
                                )
                                == "dataclasses.dataclass"
                            ):
                                if any(
                                    keyword.arg == "frozen"
                                    and isinstance(keyword.value, ast.Constant)
                                    and keyword.value.value is True
                                    for keyword in (
                                        decorator.keywords
                                        if isinstance(decorator, ast.Call)
                                        else []
                                    )
                                ):
                                    errors.append(
                                        f"{location} ENTITY_MUTABILITY: entities own state transitions; use frozen only for values"
                                    )
                                if not any(
                                    keyword.arg == "eq"
                                    and isinstance(keyword.value, ast.Constant)
                                    and keyword.value.value is False
                                    for keyword in (
                                        decorator.keywords
                                        if isinstance(decorator, ast.Call)
                                        else []
                                    )
                                ):
                                    errors.append(
                                        f"{location} ENTITY_IDENTITY: declare entity equality explicitly"
                                    )
                symbol = f"{module}.{node.name}"
                ancestors = self._ancestors(symbol)
                service_adapter = any(".ports.services." in parent for parent in ancestors)
                if service_adapter:
                    for child in ast.walk(node):
                        if isinstance(
                            child, (ast.Name, ast.Attribute, ast.Subscript)
                        ) and ".domain.aggregates." in self._name(module, child):
                            errors.append(
                                f"{location} OBSERVATION_BOUNDARY: service adapters return primitive facts, not entities"
                            )
                if ".ports.services." in module:
                    for child in ast.walk(node):
                        if isinstance(
                            child, (ast.Name, ast.Attribute, ast.Subscript)
                        ) and ".domain.aggregates." in self._name(module, child):
                            errors.append(
                                f"{location} OBSERVATION_BOUNDARY: observation contracts must not expose entities"
                            )
                is_port = ".application.ports." in module and node.name.startswith("I")
                if is_port:
                    if "abc.ABC" not in ancestors:
                        errors.append(f"{location} NOMINAL_PORT: inherit ABC explicitly")
                    for method in node.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and not any(
                            self._name(module, decorator) == "abc.abstractmethod"
                            for decorator in method.decorator_list
                        ):
                            errors.append(f"{location} ABSTRACT_METHOD: {node.name}.{method.name}")
                is_adapter = (
                    ".infrastructure.repositories." in module or node.name.endswith("Observer")
                ) and not is_port
                if is_adapter and not any(
                    ".application.ports." in parent
                    and parent in self.classes
                    and self.classes[parent].name.startswith("I")
                    and "abc.ABC" in self._ancestors(parent)
                    for parent in ancestors
                ):
                    errors.append(
                        f"{location} NOMINAL_IMPLEMENTATION: explicitly inherit its application port"
                    )
                has_table = any(
                    isinstance(item, (ast.Assign, ast.AnnAssign))
                    and any(
                        isinstance(target, ast.Name) and target.id == "__tablename__"
                        for target in (
                            item.targets if isinstance(item, ast.Assign) else [item.target]
                        )
                    )
                    for item in node.body
                )
                if has_table:
                    if not ancestors.intersection(
                        {
                            "sqlalchemy.orm.DeclarativeBase",
                            "spakky.plugins.sqlalchemy.orm.table.AbstractTable",
                            "spakky.plugins.sqlalchemy.orm.table.AbstractMappableTable",
                        }
                    ):
                        errors.append(
                            f"{location} DECLARATIVE_ORM: table class must inherit DeclarativeBase"
                        )
                    for field in node.body:
                        if isinstance(field, ast.Assign) and not all(
                            isinstance(target, ast.Name) and target.id.startswith("__")
                            for target in field.targets
                        ):
                            errors.append(
                                f"{location} MAPPED_COLUMN: persistent fields need Mapped annotations"
                            )
                        if (
                            isinstance(field, ast.AnnAssign)
                            and isinstance(field.target, ast.Name)
                            and not field.target.id.startswith("__")
                        ):
                            if (
                                self._name(module, field.annotation) != "sqlalchemy.orm.Mapped"
                                or not isinstance(field.value, ast.Call)
                                or self._name(module, field.value.func)
                                not in {
                                    "sqlalchemy.orm.mapped_column",
                                    "sqlalchemy.orm.relationship",
                                }
                            ):
                                errors.append(f"{location} MAPPED_COLUMN: {field.target.id}")
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
