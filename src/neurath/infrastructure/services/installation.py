"""로컬 호스트 설정의 Neurath 관리 영역만 원본 보존 후 갱신한다."""

import hashlib
import json
import os
import re
import shlex
import sys
import tomllib
from pathlib import Path
from typing import override
from uuid import uuid4

import aiosqlite
from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.installation import IInstallationService, InstallationResult
from neurath.application.ports.services.skill_catalog import ISkillCatalogService, SkillDescription
from neurath.domain.enums.provider_kind import ProviderKind
from neurath.infrastructure.database import (
    create_database_engine,
    initialize_database,
    sqlite_url,
    user_database_path,
    verify_schema,
)


@Pod()
class PosixInstallationService(IInstallationService):
    """기존 스킬·훅·지침을 덮어쓰지 않는 로컬 설치 어댑터다."""

    def __init__(self, catalog: ISkillCatalogService) -> None:
        """runner와 같은 스킬 선택·단계 계약을 받는다.

        Args:
            catalog: 배포 스킬 지침과 실제 실행 정의.
        """
        self.catalog = catalog

    @override
    async def initialize(self, database: str | None) -> str:
        """기존 SQLite의 일관된 사본을 남기고 현재 스키마로 이전한다.

        Args:
            database: 선택한 파일 또는 사용자 기본 저장소.

        Returns:
            str: 실제 초기화한 저장 파일.
        """
        path = user_database_path() if database is None else Path(database).expanduser().resolve()
        if path.exists():
            await self._backup_database(path)
        await initialize_database(path)
        return str(path)

    @staticmethod
    async def _backup_database(path: Path) -> str:
        """SQLite backup API로 WAL을 포함한 일관된 읽기 사본을 보존한다.

        Args:
            path: 원본 저장소.

        Returns:
            str: 보존한 사본 경로.
        """
        backup = path.with_name(f"{path.name}.before-{uuid4()}")
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        uri = sqlite_url(path, "ro").database
        assert uri is not None
        async with aiosqlite.connect(uri + "?mode=ro", uri=True) as source:
            async with aiosqlite.connect(backup) as target:
                await source.backup(target)
        return str(backup)

    @staticmethod
    def _managed(existing: str, content: str) -> str:
        """Neurath 관리 블록만 바꾸고 나머지 사용자 지침을 그대로 남긴다.

        Args:
            existing: 기존 지침 전체.
            content: 이번 배포의 관리 본문.

        Returns:
            str: 사용자 본문을 보존한 새 지침.

        Raises:
            ValueError: 관리 블록 경계가 손상되어 안전하게 구분할 수 없는 경우.
        """
        begin, end = "<!-- neurath:begin -->", "<!-- neurath:end -->"
        block = f"{begin}\n{content.rstrip()}\n{end}"
        if begin not in existing and end not in existing:
            return existing + ("\n\n" if existing else "") + block + "\n"
        if (
            existing.count(begin) != 1
            or existing.count(end) != 1
            or existing.index(end) < existing.index(begin)
        ):
            raise ValueError(
                "Neurath managed instruction boundaries are damaged; original file was preserved"
            )
        return (
            existing[: existing.index(begin)] + block + existing[existing.index(end) + len(end) :]
        )

    @override
    async def install(
        self,
        provider: ProviderKind,
        directory: str,
        data_home: str | None,
        *,
        preview: bool = False,
    ) -> InstallationResult:
        """검증된 소유 영역을 계획한 뒤 백업·적용하며 실패 시 설정을 복원한다.

        Args:
            provider: 설치할 실제 호스트.
            directory: 사용자 홈 또는 프로젝트 루트.
            data_home: 격리된 데이터 홈 또는 사용자 기본값.
            preview: 파일·DB 변경 없이 계획만 반환할지 여부.

        Returns:
            InstallationResult: 파일 적용 결과와 실제 호스트 활성화 안내.

        Raises:
            ValueError: 실제 디렉터리가 없거나 설정이 올바른 객체가 아닌 경우.
            FileExistsError: Neurath 소유가 아닌 실행 파일·스킬을 덮어써야 하는 경우.
            Exception: 파일 적용 실패 시 원래 설정을 복원한 뒤 원 오류를 전파한다.
        """
        root = Path(directory).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Installation root must be a directory")
        home = (
            user_database_path().parent.parent
            if data_home is None
            else Path(data_home).expanduser().resolve()
        )
        database = home / "neurath" / "core.sqlite3"
        config = root / (".codex" if provider is ProviderKind.CODEX else ".claude")
        managed = config / "neurath"
        executable = managed / "neurath"
        source = Path(__file__).parents[2] / "resources"
        guide = (source / "cli-guide.md").read_text()
        catalog = self.catalog.list(str(root))
        wrapper = f"""#!/bin/sh
# neurath-managed executable
export XDG_DATA_HOME={shlex.quote(str(home))}
export SPAKKY_SQLALCHEMY__CONNECTION_STRING={shlex.quote(sqlite_url(database, "rw").render_as_string(hide_password=False))}
export NEURATH_PROVIDER={shlex.quote(provider.value)}
export NEURATH_COMMAND={shlex.quote(str(executable))}
export NEURATH_INSTALL_ROOT={shlex.quote(str(root))}
exec {shlex.quote(sys.executable)} -I -m neurath.entrypoint "$@"
"""
        if executable.exists() and "# neurath-managed executable" not in executable.read_text():
            raise FileExistsError(f"Unowned executable was preserved: {executable}")
        skills = root / (".agents/skills" if provider is ProviderKind.CODEX else ".claude/skills")
        instructions = guide.replace("@NEURATH_COMMAND@", shlex.quote(str(executable))).replace(
            "@NEURATH_SKILLS@", str(skills)
        )
        rules = root / ("AGENTS.md" if provider is ProviderKind.CODEX else "CLAUDE.md")
        guide_path = managed / "guide.md"
        guide_marker = f"<!-- neurath:provider-guide:{provider.value} -->"
        if guide_path.exists() and not guide_path.read_text().startswith(guide_marker):
            raise FileExistsError(f"Unowned provider guide was preserved: {guide_path}")
        routing = self._guide_routing(root, provider, rules)
        existing_rules = self._legacy_rules(root, rules)
        planned: dict[Path, str] = {
            executable: wrapper,
            guide_path: f"{guide_marker}\n{instructions}",
            rules: self._managed(existing_rules, routing),
        }
        for entry in catalog:
            name = entry.workflow.skill
            path = skills / name / "SKILL.md"
            old = path.read_text() if path.exists() else ""
            if old and "<!-- neurath:begin -->" not in old:
                raise FileExistsError(f"Existing user skill was preserved: {path}")
            initial = self._skill_header(old, name, f"{entry.use_when}. 제외: {entry.exclude}")
            planned[path] = self._managed(initial, self._skill_body(entry, executable))
        hooks_path = config / ("hooks.json" if provider is ProviderKind.CODEX else "settings.json")
        document: dict[str, object] = (
            json.loads(hooks_path.read_text()) if hooks_path.exists() else {}
        )
        if not isinstance(document, dict) or not isinstance(document.get("hooks", {}), dict):
            raise ValueError("Host hook settings must be objects; original settings were preserved")
        hooks = document.setdefault("hooks", {})
        assert isinstance(hooks, dict)
        hook_command = f"{shlex.quote(str(executable))} hook handle --provider {provider.value}"
        events = [
            "SessionStart",
            "UserPromptSubmit",
            "Stop",
            "SubagentStart",
            "SubagentStop",
            "SessionEnd",
            "PreToolUse",
            "PostToolUse",
            "PostToolUseFailure",
        ]
        if provider is ProviderKind.CODEX:
            events.append("Interrupt")
        legacy = self._legacy_launcher(root)
        legacy_verified = (
            legacy is not None
            and self._legacy_digest(root, hooks_path)
            == hashlib.sha256(hooks_path.read_bytes()).hexdigest()
            if hooks_path.exists()
            else False
        )
        for name, groups in tuple(hooks.items()):
            if not isinstance(groups, list):
                raise ValueError("Host hook groups must be arrays")
            hooks[name] = self._retain_hooks(
                groups, hook_command, root / ".neurath/run", provider, legacy_verified
            )
        for name in events:
            retained = hooks.setdefault(name, [])
            assert isinstance(retained, list)
            group: dict[str, object] = {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command,
                        "timeout": 3 if name in ("SessionEnd", "Interrupt") else 30,
                    }
                ]
            }
            if name in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
                group["matcher"] = "Edit|Write|apply_patch"
            hooks[name] = [*retained, group]
        planned[hooks_path] = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        legacy_files, legacy_retained = self._legacy_mcp(root, provider)
        planned.update(legacy_files)
        planned = {
            path.resolve() if path.is_symlink() else path: body for path, body in planned.items()
        }
        originals = {path: path.read_bytes() if path.exists() else None for path in planned}
        changed = [path for path, body in planned.items() if originals[path] != body.encode()]
        if preview:
            return InstallationResult(
                command=str(executable),
                database=str(database),
                changed_files=tuple(str(path) for path in changed),
                backups=(),
                host_action="Preview only; no files, database or native host were changed. "
                + legacy_retained,
                planned_files={str(path): body for path, body in planned.items()},
            )
        backups = []
        if database.exists():
            engine = create_database_engine(database, write=False)
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(verify_schema)
            finally:
                await engine.dispose()
            backups.append(await self._backup_database(database))
        else:
            await initialize_database(database)
        temporary_files: list[Path] = []
        try:
            for path in changed:
                path.parent.mkdir(parents=True, exist_ok=True)
                previous = originals[path]
                if previous is not None:
                    backup = path.with_name(f"{path.name}.before-{uuid4()}")
                    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    os.close(descriptor)
                    backup.write_bytes(previous)
                    backup.chmod(0o600)
                    backups.append(str(backup))
                temporary = path.with_name(f"{path.name}.tmp-{uuid4()}")
                temporary_files.append(temporary)
                temporary.write_text(planned[path])
                temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
                os.replace(temporary, path)
            executable.chmod(0o700)
        except Exception:
            for temporary in temporary_files:
                temporary.unlink(missing_ok=True)
            for path in changed:
                previous = originals[path]
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(previous)
            raise
        return InstallationResult(
            command=str(executable),
            database=str(database),
            changed_files=tuple(str(path) for path in changed),
            backups=tuple(backups),
            host_action="Files applied. Native hook trust and sandbox access remain the host's decisions. Review changed hooks with /hooks if requested, then verify SessionStart and a real CLI request; no trust hashes or permissions were forged. "
            + legacy_retained,
        )

    @staticmethod
    def _guide_routing(root: Path, provider: ProviderKind, rules: Path) -> str:
        """공유 파일에는 호스트별 상대 참조만 두어 설치 순서로 명령이 바뀌지 않게 한다.

        Args:
            root: 명시한 설치 루트.
            provider: 이번에 설치하는 호스트.
            rules: 해당 호스트가 읽는 지침 파일.

        Returns:
            str: 현재 호스트를 명시적으로 선택하는 프로젝트 상대 guide 참조.
        """
        other_rules = root / ("CLAUDE.md" if provider is ProviderKind.CODEX else "AGENTS.md")
        shared = rules.exists() and other_rules.exists() and rules.samefile(other_rules)
        lines = [
            "# Neurath host guides",
            "",
            "Read only the guide for the host running this conversation. Follow existing user/project instructions. Each guide contains that host's installed CLI, skill selection, and recovery instructions; do not use another host's wrapper or infer a new session identity.",
            "",
        ]
        for host in ProviderKind:
            relative = (
                Path(".codex" if host is ProviderKind.CODEX else ".claude") / "neurath/guide.md"
            )
            guide = root / relative
            if (
                host is provider
                or shared
                and guide.is_file()
                and guide.read_text().startswith(f"<!-- neurath:provider-guide:{host.value} -->")
            ):
                lines.append(
                    f"- {host.value}: [Read the {host.value} CLI and skills guide](<{relative.as_posix()}>)."
                )
        return "\n".join(lines)

    @staticmethod
    def _legacy_digest(root: Path, path: Path) -> str | None:
        """구형 manifest가 기록한 해당 경로의 digest만 읽고 활성화 값을 신뢰 근거로 쓰지 않는다.

        Args:
            root: 명시한 프로젝트 루트.
            path: 소유 범위를 대조할 실제 대상.

        Returns:
            str | None: 인식한 파일 기록의 SHA256 또는 미확인.
        """
        manifest = root / ".neurath/install.json"
        if not manifest.is_file():
            return None
        data = json.loads(manifest.read_text())
        if (
            not isinstance(data, dict)
            or data.get("server") != "neurath"
            or not isinstance(data.get("files"), dict)
        ):
            return None
        paths = [path.relative_to(root).as_posix()]
        resolved = path.resolve()
        if resolved.is_relative_to(root):
            paths.append(resolved.relative_to(root).as_posix())
        for key in paths:
            digest = data["files"].get(key)
            if isinstance(digest, str) and re.fullmatch("[0-9a-fA-F]{64}", digest):
                return digest.lower()
        return None

    @classmethod
    def _legacy_launcher(cls, root: Path) -> Path | None:
        """주석 없는 구형 launcher도 현재 바이트·manifest·정확한 실행 대상을 함께 대조한다.

        Args:
            root: 요청한 프로젝트 루트.

        Returns:
            Path | None: 실제 옛 설치로 확인한 launcher 또는 미확인.
        """
        path = root / ".neurath/run"
        if (
            not path.is_file()
            or cls._legacy_digest(root, path) != hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            return None
        data = json.loads((root / ".neurath/install.json").read_text())
        commands = [
            shlex.split(line) for line in path.read_text().splitlines() if line.startswith("exec ")
        ]
        if len(commands) != 1:
            return None
        tokens = commands[0]
        if (
            len(tokens) != 8
            or tokens[:6] != ["exec", data.get("python"), "-I", "-m", "neurath", "--root"]
            or tokens[-1] != "$@"
            or Path(tokens[6]).resolve() != root
        ):
            return None
        return path

    @classmethod
    def _legacy_rules(cls, root: Path, rules: Path) -> str:
        """정확한 구형 관리 영역만 바꾸며 변경된 외부 사용자 정책은 그대로 보존한다.

        Args:
            root: 요청한 프로젝트 루트.
            rules: 물리적으로 공유될 수도 있는 지침 경로.

        Returns:
            str: 구형 블록을 신형 관리 경계로 이어 놓은 원문.

        Raises:
            ValueError: 경계·본문·manifest 소유 항목이 불명확한 경우.
        """
        existing = rules.read_text() if rules.exists() else ""
        begin, end = "<!-- neurath:managed -->", "<!-- /neurath:managed -->"
        if begin not in existing and end not in existing:
            return existing
        if (
            existing.count(begin) != 1
            or existing.count(end) != 1
            or existing.index(end) < existing.index(begin)
        ):
            raise ValueError(
                "Legacy Neurath instruction boundaries are damaged; original file was preserved"
            )
        start, finish = existing.index(begin), existing.index(end) + len(end)
        body = existing[start + len(begin) : existing.index(end)]
        digest = cls._legacy_digest(root, rules)
        known = digest is not None and (
            digest == hashlib.sha256(rules.read_bytes()).hexdigest()
            or "neurath" in body.lower()
            and "mcp" in body.lower()
        )
        if not known or "<!-- neurath:begin -->" in body or "<!-- neurath:end -->" in body:
            raise ValueError(
                "Legacy Neurath instruction ownership is unclear; original block and user policy were preserved"
            )
        if "<!-- neurath:begin -->" in existing or "<!-- neurath:end -->" in existing:
            return existing[:start] + existing[finish:]
        return existing.replace(begin, "<!-- neurath:begin -->").replace(
            end, "<!-- neurath:end -->"
        )

    @staticmethod
    def _old_hook(value: object, launcher: Path, provider: ProviderKind) -> bool:
        """공백·인용 차이와 무관하게 정확한 옛 hook 인자만 대조한다.

        Args:
            value: 기존 handler의 명령 값.
            launcher: 구형 launcher의 실제 위치.
            provider: 설정을 소유한 호스트.

        Returns:
            bool: 추가 명령이나 인자 없는 정확한 옛 호출인지 여부.
        """
        if not isinstance(value, str):
            return False
        try:
            arguments = shlex.split(value)
        except ValueError:
            return False
        return (
            len(arguments) == 4
            and Path(arguments[0]).is_absolute()
            and Path(arguments[0]).resolve() == launcher
            and arguments[1:3] == ["hook", "--provider"]
            and arguments[3]
            in (["codex"] if provider is ProviderKind.CODEX else ["claude", "claude-code"])
        )

    @classmethod
    def _retain_hooks(
        cls,
        groups: list[object],
        command: str,
        launcher: Path,
        provider: ProviderKind,
        legacy_verified: bool,
    ) -> list[object]:
        """확인된 handler만 제거하고 mixed group의 다른 명령과 속성을 보존한다.

        Args:
            groups: 실제 호스트의 기존 사건 그룹.
            command: 현재 설치의 정확한 새 명령.
            launcher: 구형 설치가 사용한 정확한 launcher 위치.
            provider: 해당 설정의 실제 호스트.
            legacy_verified: launcher와 훅 파일의 manifest digest가 모두 일치하는지 여부.

        Returns:
            list[object]: 관계없는 handler와 그룹의 원래 자료.

        Raises:
            ValueError: 옛 명령이 있으나 소유를 확인하지 못해 중복 전환을 피해야 하는 경우.
        """
        retained = []
        for group in groups:
            if cls._managed_hook(group, command):
                continue
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                retained.append(group)
                continue
            handlers = []
            removed = False
            for handler in group["hooks"]:
                value = (
                    handler.get("command", "")
                    if isinstance(handler, dict) and handler.get("type") == "command"
                    else ""
                )
                old = cls._old_hook(value, launcher, provider)
                if old and not legacy_verified:
                    raise ValueError(
                        "Legacy hook ownership is unverified; original configuration was preserved without adding a competing handler"
                    )
                if value != command and not old:
                    handlers.append(handler)
                else:
                    removed = True
            if not removed:
                retained.append(group)
            elif handlers:
                retained.append({**group, "hooks": handlers})
        return retained

    @staticmethod
    def _legacy_mcp(root: Path, provider: ProviderKind) -> tuple[dict[Path, str], str]:
        """정확히 식별한 옛 Neurath 명령 등록만 제거하고 불명확한 항목은 안내한다.

        Args:
            root: 요청한 설정 루트.
            provider: 실제 호스트.

        Returns:
            tuple[dict[Path, str], str]: 소유 등록의 변경 파일과 미인식 항목 안내.
        """
        path = root / (".codex/config.toml" if provider is ProviderKind.CODEX else ".mcp.json")
        if not path.exists():
            return {}, ""
        content = path.read_text()
        data = tomllib.loads(content) if provider is ProviderKind.CODEX else json.loads(content)
        servers = data.get("mcp_servers" if provider is ProviderKind.CODEX else "mcpServers", {})
        entry = servers.get("neurath")
        if entry is None:
            return {}, ""
        executable = entry.get("command", "")
        arguments = entry.get("args", [])
        launcher = Path(executable).expanduser()
        owned_path = any(
            launcher.is_relative_to(root / name)
            for name in (".neurath", ".codex/neurath", ".claude/neurath")
        )
        owned = (
            owned_path
            and launcher.is_file()
            and "# neurath-managed" in launcher.read_text(errors="replace")
            and arguments
            and arguments[0] in {"mcp", "serve"}
        )
        legacy = PosixInstallationService._legacy_launcher(root)
        legacy_arguments = [
            "mcp",
            "--provider",
            "codex" if provider is ProviderKind.CODEX else "claude-code",
        ]
        owned = owned or (
            legacy is not None
            and launcher.is_absolute()
            and launcher.resolve() == legacy
            and arguments == legacy_arguments
            and PosixInstallationService._legacy_digest(root, path)
            == hashlib.sha256(path.read_bytes()).hexdigest()
        )
        retained = "Legacy MCP entry named neurath was retained because ownership is unverified. Read that exact entry and replace only its Neurath invocation with the installed grouped CLI; do not retry cached MCP calls."
        if not owned:
            return {}, retained
        if provider is ProviderKind.CLAUDE:
            del servers["neurath"]
            return {path: json.dumps(data, ensure_ascii=False, indent=2) + "\n"}, ""
        headers = list(re.finditer(r"(?m)^\[[^\n]+\][ \t]*(?:#.*)?$", content))
        spans = [
            (
                match.start(),
                headers[index + 1].start() if index + 1 < len(headers) else len(content),
            )
            for index, match in enumerate(headers)
            if re.fullmatch(r"\[mcp_servers\.neurath(?:\.[^\]]+)?\][ \t]*(?:#.*)?", match.group())
        ]
        if not spans:
            return {}, retained
        for start, end in reversed(spans):
            content = content[:start] + content[end:]
        return {path: content}, ""

    @staticmethod
    def _skill_header(existing: str, name: str, description: str) -> str:
        """첫 줄의 정식 메타데이터를 갱신하고 다른 필드와 사용자 본문을 보존한다.

        Args:
            existing: 관리 스킬의 기존 내용.
            name: 스킬 선택 이름.
            description: 구체적인 선택·제외 조건.

        Returns:
            str: 이름·설명을 갱신하고 다른 내용을 보존한 문서.

        Raises:
            ValueError: 기존 frontmatter의 끝이 없는 경우.
        """
        metadata = ""
        body = existing
        if existing.startswith("---\n"):
            header, separator, body = existing[4:].partition("\n---\n")
            if not separator:
                raise ValueError("Skill frontmatter is incomplete; original file was preserved")
            metadata = re.sub(
                r"(?m)^(?:name|description):[^\n]*(?:\n[ \t]+[^\n]*)*\n?", "", header
            ).strip()
        fields = f"name: {json.dumps(name, ensure_ascii=False)}\ndescription: {json.dumps(description, ensure_ascii=False)}"
        if metadata:
            fields += "\n" + metadata
        return f"---\n{fields}\n---\n{body}"

    @staticmethod
    def _skill_body(entry: SkillDescription, executable: Path) -> str:
        """각 스킬의 실제 선택·입력·단계·결과와 기존 CLI 사용을 연결한다.

        Args:
            entry: runner와 같은 원천에서 읽은 스킬 계약.
            executable: 설치된 CLI 경로.

        Returns:
            str: 해당 요청에 필요한 절차와 결과 조건.
        """
        command = shlex.quote(str(executable))
        workflow = entry.workflow
        distribution = (
            f"""## 정확한 배포본 업데이트

`{command} maintenance version`과 `distribution verify`로 현재 실행을 읽고 `distribution check`로 공식 릴리스 없음·조회 실패·정확한 artifact 일치를 구분한다. 같은 버전도 wheel SHA와 원 소스 commit이 다르면 별도 후보다. 요청한 소스 개정은 해당 checkout에서 `tools/build_release.py`로 빌드한 wheel과 `distribution prepare --source-commit`으로 대조한다. 개발 checkout의 변경분을 clean commit 배포로 표현하지 않는다.
선택 wheel은 `distribution prepare --wheel ... --store ...`로 고정 환경에 준비하고 `distribution plan --candidate ... --provider ... --directory ... --data-home ...`의 실제 변경 전후와 공유 DB 호환성을 확인한다. 이미 요청한 업데이트에 추가 인간 동의·토큰을 요구하지 않는다. 비호환이면 plan의 기존 migration fence/recover/복구 사본 initialize/replay 경로를 같은 범위에서 계속 수행하며 사용자에게 내부 장부 수정을 떠넘기지 않는다.
`distribution apply` 뒤 실제 설치 명령의 `distribution verify`와 `distribution guide`를 호출해 같은 배포의 현재 안내를 읽고 원 작업을 조회한다. 파일 적용·stdout 전달·모델의 사용·네이티브 활성화를 구분한다. CLI 업데이트라는 이유로 호스트 앱 재시작을 강제하지 않는다. 실패 시 해당 receipt의 `distribution recover`를 사용하고 새 DB 기록·전환 큐를 유지한다. 옛 MCP 호출이 캐시돼 있으면 현재 그룹 CLI로 전환하며 같은 실패를 반복하지 않는다.
"""
            if workflow.skill == "update-neurath"
            else ""
        )
        inputs = "\n".join(f"- {item}" for item in entry.required_inputs)
        outcomes = "\n".join(f"- {item}" for item in entry.outcomes)
        branches = "\n".join(f"- {item}" for item in entry.branches)
        steps = "\n".join(
            f"{index}. **{phase.key}**: {phase.purpose}\n   확인할 조건: {', '.join(phase.checks)}"
            for index, phase in enumerate(workflow.phases, 1)
        )
        return f"""# {workflow.skill}

{entry.purpose}

## 선택과 제외

사용: {entry.use_when}
제외: {entry.exclude}

## 필요한 입력

기존 원문·선택 자료에서 다음을 확인한다. 이미 있는 정보를 사용자에게 다시 입력시키지 않는다.

{inputs}

## 수행과 결과 조건

{steps}

## 상황별 분기

{branches}

## 최종 결과

{outcomes}

## 기존 작업에 연결

`{command} context show`와 `context show --section sources`의 모든 관련 페이지를 읽는다. 스킬을 읽은 것만으로 수행·완료를 기록하지 않는다. 단순 대화에는 task나 workflow가 필요 없다.
이미 있는 작업을 선택한다. 실제 수행할 일이 원장에 없을 때만 `task create --title ... --result ...`로 연결한다. 새 절차는 `workflow start --task-id ... --skill {workflow.skill}`로 시작한다. 현재 단계의 작업은 호스트의 추론·파일·명령·네이티브 협업 도구로 수행한다.
호스트에서 실제 확인한 뒤 `workflow report --run-id ... --summary ... --reference ... --check <현재 단계 checks의 항목>`으로 보고한다. 여러 조건이면 --check를 반복하며 확인하지 않은 조건은 통과시키지 않는다.
기존 run은 `workflow show --run-id ...`로 고정 정의·시도·미완료를 읽는다. 다른 스킬이나 finish-session을 이어 수행할 때 새 완료 원장을 만들지 않는다. `workflow revise --run-id ... --reason ... --definition ...`으로 필요한 단계만 추가·정정하고 기존 필수 결과와 동일한 평가 phase를 보존한다. 수행 방법을 바꾸기 위해 새 인간 지시를 요구하지 않는다.
결과 평가 phase가 있으면 실제 원문·전체 TODO·산출물·검증을 관찰된 독립 피어 또는 명시한 provider에게 `collaboration delegate --role reviewer`로 전달한다. 같은 유효 평가를 재사용하고 검토자를 재귀 평가하지 않는다. 실제 보고를 읽고 `workflow report --accepted/--rejected`로 판단하며 미달은 같은 TODO에서 보완한다. 배정·전달·프로세스 종료만으로 원 작업을 성공 처리하지 않는다.
실제 결과는 `task report`, 인계 보고는 `memory checkpoint`, 현재 사실은 `memory update`로 연결한다. 재개는 `session resume`을 사용한다. 커밋·워크트리·PR·이슈는 호스트 도구, 의존성·그래프는 선택한 전문 도구로 수행한다. 스킬은 원 요청의 범위나 기존 호스트 권한을 확대하지 않는다.

{distribution}
"""

    @staticmethod
    def _managed_hook(group: object, command: str) -> bool:
        """정확한 Neurath 실행 경로를 가진 그룹만 소유 설정으로 구분한다.

        Args:
            group: 기존 호스트의 임의 훅 그룹.
            command: 현재 설치 경로의 정확한 실행 명령.

        Returns:
            bool: 다른 훅과 섞이지 않은 동일 Neurath 명령 그룹인지 여부.
        """
        if not isinstance(group, dict):
            return False
        handlers = group.get("hooks")
        if not isinstance(handlers, list) or not handlers:
            return False
        return all(
            isinstance(handler, dict)
            and handler.get("type") == "command"
            and handler.get("command") == command
            for handler in handlers
        )
