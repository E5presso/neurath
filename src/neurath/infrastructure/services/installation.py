"""로컬 호스트 설정의 Neurath 관리 영역만 원본 보존 후 갱신한다."""

import json
import os
import shlex
import sys
from pathlib import Path
from typing import cast, override
from uuid import uuid4

import aiosqlite
from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.installation import IInstallationService, InstallationResult
from neurath.domain.enums.provider_kind import ProviderKind
from neurath.infrastructure.database import initialize_database, sqlite_url, user_database_path


@Pod()
class PosixInstallationService(IInstallationService):
    """기존 스킬·훅·지침을 덮어쓰지 않는 로컬 설치 어댑터다."""

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
        catalog = cast(dict[str, list[str]], json.loads((source / "skills.json").read_text()))
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
        for name, phases in catalog.items():
            path = skills / name / "SKILL.md"
            old = path.read_text() if path.exists() else ""
            if old and "<!-- neurath:begin -->" not in old:
                raise FileExistsError(f"Existing user skill was preserved: {path}")
            description = phases[0]
            initial = old or f"---\nname: {name}\ndescription: {description}\n---\n"
            body = self._skill_body(name, phases, executable)
            planned[path] = self._managed(initial, body)
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
    def _skill_body(name: str, phases: list[str], executable: Path) -> str:
        """공유 CLI 가이드와 실제 단계 정의를 스킬의 수행 지침에 연결한다.

        Args:
            name: 선택할 스킬 이름.
            phases: 실제 배포 절차의 목적 목록.
            executable: 설치된 CLI 경로.

        Returns:
            str: 사용자 범위와 호스트 실행을 유지하는 스킬 본문.
        """
        command = shlex.quote(str(executable))
        steps = "\n".join(f"{index}. {purpose}" for index, purpose in enumerate(phases, 1))
        return f"""# {name}
Use this skill only when it matches the user's request. Read the original instruction and current project rules. Simple answers and status questions do not require a task or workflow.
Read current state with `{command} context show`; original sources with `context show --section sources`. Hooks preserve observed input; do not ask the user to re-enter it or fabricate provenance.
For a work item, use `task create --title ... --result ...`, then `workflow start --task-id ... --skill {name}`. The host agent performs reasoning, file edits, commands and native delegation with its own tools. Neurath records the state; it does not replace the host's tool permissions.

{steps}

After actual work, report the current stage with `workflow report --run-id ... --summary ... --reference ... --check done`. Revise methods when necessary while retaining the original result and its evaluation. Do not manufacture a user correction to change the implementation method.
For a result-review phase, use an observed native peer or explicitly selected provider through `collaboration delegate --role reviewer` with actual artifact and verification references. Native children are created with the host's existing tool, not a second Neurath session. Reviewers read original sources and the full TODO, report unmet items and evidence, and do not spawn recursive reviewers.
Read the stored report, accept or reject its findings with evidence using `workflow report --accepted/--rejected`, fix confirmed unmet work in the same TODO, then `task report` the actual result. Delivery or a process exit is not success of the original goal.
Save useful current facts with `memory update --changes ...`; keep details in memory references. Hooks restore the current context after compaction. Do not make the user manage internal IDs or repair bookkeeping.
Offer reflection once only when problems occurred. Requested reflection may be withdrawn; refusal or silence must not block the original work. Apply only requested improvements using the host's file tools, verify the original failure and normal controls, and preserve source-linked lessons. Prior lessons never override current user instructions.
Only watch external work when requested. Use the host's existing scheduler on the same conversation and the monitor callback returned by Neurath; unchanged polls must not launch model work. Stop or update the watcher when the original task changes or finishes.
Do not merge, publish, install into unrelated projects, or expand authority merely because this skill is running. Use already-given user authorization and report actual evidence, failures and remaining work.
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
