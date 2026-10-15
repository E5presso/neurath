"""Check concrete architectural syntax; semantic cohesion still requires human review."""

import ast
import re
from pathlib import Path


class ArchitectureChecker:
    """Resolve local import aliases and inheritance before enforcing explicit contracts."""

    def __init__(self, sources: dict[str, str]) -> None:
        """Parse a complete source tree whose keys are dotted module names."""
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
        """Resolve relative imports against the importing module's package."""
        if node.level == 0:
            return node.module or ""
        parts = module.split(".")[: -node.level]
        if node.module:
            parts.extend(node.module.split("."))
        return ".".join(parts)

    def _name(self, module: str, node: ast.AST) -> str:
        """Return a canonical symbol name for an annotation, base, or call target."""
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
        """Follow explicit base classes, including imported and indirect local bases."""
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
        """Return actionable rule codes with module and line for every violation."""
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
                if re.search(r"#\s*(type:\s*ignore|noqa|mypy:)", text):
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
                            imported.startswith("neurath.domain")
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
                    if node.name in {"transaction", "commit", "rollback", "uow", "unit_of_work"}:
                        errors.append(f"{location} TRANSACTION_WRAPPER: use ORM Session lifecycle")
                    for decorator in node.decorator_list:
                        if self._name(module, decorator) in {
                            "contextlib.contextmanager",
                            "contextlib.asynccontextmanager",
                        }:
                            errors.append(
                                f"{location} TRANSACTION_WRAPPER: no custom context manager lifecycle"
                            )
                if isinstance(node, ast.Call):
                    called = self._name(module, node.func)
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
                if "unitofwork" in node.name.lower().replace("_", "") or node.name.lower().endswith(
                    "uow"
                ):
                    errors.append(f"{location} TRANSACTION_WRAPPER: remove custom unit of work")
                if node.name == "Core":
                    errors.append(f"{location} CORE: name a specific use-case responsibility")
                symbol = f"{module}.{node.name}"
                ancestors = self._ancestors(symbol)
                is_port = (
                    ".application.ports." in module
                    and node.name.startswith("I")
                    and len(node.name) > 1
                    and node.name[1].isupper()
                )
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
                    ".application.usecases." in module
                    or ".infrastructure.repositories." in module
                    or node.name.endswith("Locator")
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
                    if "sqlalchemy.orm.DeclarativeBase" not in ancestors:
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
                                != "sqlalchemy.orm.mapped_column"
                            ):
                                errors.append(f"{location} MAPPED_COLUMN: {field.target.id}")
        return sorted(set(errors))


def check_tree(root: Path) -> list[str]:
    """Discover every current source module, so future files cannot evade the gate."""
    sources: dict[str, str] = {}
    for path in sorted((root / "src").rglob("*.py")):
        module = ".".join(path.relative_to(root / "src").with_suffix("").parts)
        sources[module] = path.read_text()
    return ArchitectureChecker(sources).check()


def main() -> None:
    """Run the complete source architecture gate and fail the process on violations."""
    errors = check_tree(Path(__file__).resolve().parents[1])
    for error in errors:
        print(error)
    if errors:
        raise SystemExit(1)
    print("ARCHITECTURE_CHECK_OK")


if __name__ == "__main__":
    main()
