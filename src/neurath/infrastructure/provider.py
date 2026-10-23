"""배정별 지속 실행 기록으로 CLI 실행·상태·중단·재연결을 제공한다."""

import json
import os
import re
import signal
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from threading import Thread
from typing import cast, override
from uuid import UUID

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.provider import IProviderService
from neurath.application.provider_records import ProviderCapabilities, ProviderObservation
from neurath.domain.delegation_records import ProviderPlan
from neurath.infrastructure.database import user_database_path
from neurath.infrastructure.provider_protocol import discover_models
from neurath.infrastructure.provider_worker import process_identity


@Pod()
class SubprocessProviderService(IProviderService):
    """각 배정의 단일 실행 디렉터리를 재사용하고 관찰만으로 새 실행을 만들지 않는다."""

    @override
    def discover(self, provider: str) -> ProviderCapabilities:
        """실제 모델을 조회하고 명시적으로 구현한 실행 정책을 반환한다.

        Args:
            provider: 조회할 codex 또는 claude.

        Returns:
            ProviderCapabilities: 관찰한 모델과 지원 정책.

        Raises:
            RuntimeError: 설치된 CLI에서 지원 정책을 확인할 수 없는 경우.
        """
        models = discover_models(provider)
        help_text = subprocess.run(
            [provider, "--help"], capture_output=True, text=True, check=True, timeout=10
        ).stdout
        if provider == "codex" and "--no-daemon" not in help_text:
            raise RuntimeError("Installed Codex does not support isolated process execution")
        pattern = (
            r"--sandbox[\s\S]*?\[possible values: ([^\]]+)\]"
            if provider == "codex"
            else r"--permission-mode[\s\S]*?\(choices: ([^)]+)\)"
        )
        match = re.search(pattern, help_text)
        if match is None:
            raise RuntimeError("Installed provider does not advertise supported execution policies")
        advertised = {
            item.strip().strip('"') for item in match.group(1).replace("\n", "").split(",")
        }
        supported = (
            ("read-only", "workspace-write", "danger-full-access")
            if provider == "codex"
            else ("plan", "dontAsk", "acceptEdits")
        )
        policies = tuple(policy for policy in supported if policy in advertised)
        if not policies:
            raise RuntimeError("Installed provider has no supported execution policy")
        return ProviderCapabilities(provider, models, policies)

    @staticmethod
    def _directory(delegation_id: str) -> Path:
        """고유 배정 ID를 사용자 저장 위치 안의 실행 디렉터리로 해석한다.

        Args:
            delegation_id: UUID 형식의 배정 ID.

        Returns:
            Path: 이 배정만의 실행 자료 위치.
        """
        return user_database_path().parent / "provider-runs" / str(UUID(delegation_id))

    @override
    def start(self, delegation_id: str, plan: ProviderPlan, prompt: str) -> ProviderObservation:
        """배정 디렉터리를 배타적으로 만들고 같은 배정은 기존 실행에 연결한다.

        Args:
            delegation_id: 원 배정 ID.
            plan: 검증하고 저장한 실행 계획.
            prompt: 원 지시와 맡긴 범위.

        Returns:
            ProviderObservation: 실제 제출 또는 기존 실행의 관찰.

        Raises:
            ValueError: 지원 모델·정책 또는 실행 위치가 아닌 경우.
        """
        directory = self._directory(delegation_id)
        if directory.exists():
            saved = directory / "plan.json"
            if saved.exists() and json.loads(saved.read_text()) != asdict(plan):
                raise ValueError("Recovery cannot replace the original execution plan")
            return self.observe(delegation_id)
        capabilities = self.discover(plan.provider)
        if (
            plan.model not in capabilities.models
            or plan.policy not in capabilities.policies
            or not Path(plan.directory).is_dir()
            or not prompt.strip()
        ):
            raise ValueError("Unsupported provider plan or empty assignment")
        directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            return self.observe(delegation_id)
        (directory / "plan.json").write_text(json.dumps(asdict(plan)))
        (directory / "prompt.txt").write_text(prompt)
        with (directory / "worker.log").open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "neurath.infrastructure.provider_worker", str(directory)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        # 자식의 수명은 원 실행 디렉터리로 관찰한다. 요청 프로세스가 종료돼도 이어진다.
        Thread(target=process.wait, daemon=True).start()
        (directory / "worker.pid").write_text(str(process.pid))
        return self.observe(delegation_id)

    @override
    def observe(self, delegation_id: str) -> ProviderObservation:
        """기존 출력과 종료 결과만 읽어 불명·실패·중단·완료를 구분한다.

        Args:
            delegation_id: 원 배정 ID.

        Returns:
            ProviderObservation: 실제 호스트 ID와 원 결과를 포함한 관찰.
        """
        directory = self._directory(delegation_id)
        native_id: str | None = None
        output: list[str] = []
        provider_error: str | None = None
        completed = False
        log = directory / "output.jsonl"
        if log.exists():
            for line in log.read_text(errors="replace").splitlines():
                try:
                    item = cast(dict[str, object], json.loads(line))
                except json.JSONDecodeError:
                    continue
                if item.get("type") == "thread.started":
                    native_id = str(item["thread_id"])
                if item.get("session_id"):
                    native_id = str(item["session_id"])
                if item.get("type") == "turn.completed":
                    completed = True
                if item.get("type") == "result":
                    completed = True
                    output.append(str(item.get("result", "")))
                    if item.get("is_error"):
                        provider_error = str(item.get("errors", item))
                if item.get("type") == "item.completed":
                    detail = cast(dict[str, object], item["item"])
                    if detail.get("type") == "agent_message":
                        output.append(str(detail["text"]))
                if item.get("type") in ("error", "turn.failed"):
                    provider_error = str(item)
        result_path = directory / "result.json"
        if not result_path.exists():
            process_file = directory / "process.json"
            running = False
            if native_id is not None and process_file.exists():
                process = cast(dict[str, object], json.loads(process_file.read_text()))
                identity = process_identity(int(str(process["pid"])))
                running = bool(identity) and identity == process["identity"]
            return ProviderObservation(
                str(directory),
                "running" if running else "unknown",
                native_id,
                "\n".join(output),
                "Completion has not been observed",
            )
        result = cast(dict[str, object], json.loads(result_path.read_text()))
        code = result.get("exit_code")
        if code == -signal.SIGTERM and (directory / "cancel.requested").exists():
            return ProviderObservation(str(directory), "stopped", native_id, "\n".join(output))
        if code != 0 or provider_error is not None or native_id is None or not completed:
            return ProviderObservation(
                str(directory),
                "failed",
                native_id,
                "\n".join(output),
                str(
                    result.get(
                        "error",
                        provider_error
                        or f"Provider exited with code {code}; native session: {native_id}",
                    )
                ),
            )
        return ProviderObservation(str(directory), "completed", native_id, "\n".join(output))

    @override
    def cancel(self, delegation_id: str) -> ProviderObservation:
        """등록한 프로세스의 실제 시작 신원을 대조한 뒤 해당 그룹에만 중단을 보낸다.

        Args:
            delegation_id: 이 어댑터로 시작한 배정 ID.

        Returns:
            ProviderObservation: 즉시 관찰한 상태이며 종료 전에는 중단 완료가 아니다.
        """
        directory = self._directory(delegation_id)
        directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            (directory / "cancel.requested").touch()
            (directory / "result.json").write_text(json.dumps({"exit_code": -signal.SIGTERM}))
            return self.observe(delegation_id)
        (directory / "cancel.requested").touch()
        record = directory / "process.json"
        if not record.exists() or (directory / "result.json").exists():
            return self.observe(delegation_id)
        process = cast(dict[str, object], json.loads(record.read_text()))
        pid = int(str(process["pid"]))
        identity = process_identity(pid)
        if not identity or identity != process["identity"]:
            return ProviderObservation(
                str(directory),
                "unknown",
                error="Process identity no longer matches; stop is unconfirmed",
            )
        (directory / "cancel.requested").touch()
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return self.observe(delegation_id)
