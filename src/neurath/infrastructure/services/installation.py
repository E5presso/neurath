"""로컬 호스트 설정의 Neurath 관리 영역만 원본 보존 후 갱신한다."""

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import override
from uuid import uuid4

import aiosqlite
from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.installation import IInstallationService, InstallationResult
from neurath.application.ports.services.skill_catalog import ISkillCatalogService, SkillDescription
from neurath.domain.enums.provider_kind import ProviderKind
from neurath.infrastructure.database import initialize_database, sqlite_url, user_database_path


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
        self, provider: ProviderKind, directory: str, data_home: str | None
    ) -> InstallationResult:
        """검증된 소유 영역을 계획한 뒤 백업·적용하며 실패 시 설정을 복원한다.

        Args:
            provider: 설치할 실제 호스트.
            directory: 사용자 홈 또는 프로젝트 루트.
            data_home: 격리된 데이터 홈 또는 사용자 기본값.

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
exec {shlex.quote(sys.executable)} -m neurath.entrypoint "$@"
"""
        if executable.exists() and "# neurath-managed executable" not in executable.read_text():
            raise FileExistsError(f"Unowned executable was preserved: {executable}")
        instructions = guide.replace("@NEURATH_COMMAND@", shlex.quote(str(executable)))
        rules = root / ("AGENTS.md" if provider is ProviderKind.CODEX else "CLAUDE.md")
        planned: dict[Path, str] = {
            executable: wrapper,
            rules: self._managed(rules.read_text() if rules.exists() else "", instructions),
        }
        skills = root / (".agents/skills" if provider is ProviderKind.CODEX else ".claude/skills")
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
        for name in events:
            groups = hooks.setdefault(name, [])
            if not isinstance(groups, list):
                raise ValueError("Host hook groups must be arrays")
            retained = [group for group in groups if not self._managed_hook(group, hook_command)]
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
        planned = {
            path.resolve() if path.is_symlink() else path: body for path, body in planned.items()
        }
        originals = {path: path.read_bytes() if path.exists() else None for path in planned}
        changed = [path for path, body in planned.items() if originals[path] != body.encode()]
        backups = []
        if database.exists():
            backups.append(await self._backup_database(database))
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
            host_action="Files applied. Native hook trust and sandbox access remain the host's decisions. Review changed hooks with /hooks if requested, then verify SessionStart and a real CLI request; no trust hashes or permissions were forged.",
        )

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
            isinstance(handler, dict) and handler.get("command") == command for handler in handlers
        )
