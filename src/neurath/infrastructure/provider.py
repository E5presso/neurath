"""배정별 지속 실행 기록으로 CLI 실행·상태·중단·재연결을 제공한다."""

import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from threading import Thread
from typing import cast, override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.provider import IProviderService
from neurath.application.provider_records import ProviderCapabilities, ProviderObservation
from neurath.domain.delegation_records import ProviderPlan
from neurath.domain.provider import ProviderKind, ProviderStatus
from neurath.infrastructure.database import user_database_path
from neurath.infrastructure.provider_protocol import discover_models
from neurath.infrastructure.provider_worker import process_identity
from neurath.serialization import encode_uuid


@immutable
class ProviderTranscript:
    """원 출력에서 관찰한 세션·본문·오류와 호스트의 결과 완료 신호다.

    Attributes:
        native_session_id: 실제 출력의 호스트 세션 ID.
        output: 모델 응답 본문이며 도구 출력은 제외한다.
        error: 호스트 오류 원문.
        completed: 호스트가 결과 완료 사건을 출력했는지 여부.
    """

    native_session_id: str | None
    output: str
    error: str | None
    completed: bool


@Pod()
class SubprocessProviderService(IProviderService):
    """각 배정의 단일 실행 디렉터리를 재사용하고 관찰만으로 새 실행을 만들지 않는다."""

    @override
    def discover(self, provider: ProviderKind) -> ProviderCapabilities:
        """실제 모델을 조회하고 명시적으로 구현한 실행 정책을 반환한다.

        Args:
            provider: 조회할 codex 또는 claude.

        Returns:
            ProviderCapabilities: 관찰한 모델과 지원 정책.

        """
        kind = ProviderKind(provider)
        models = discover_models(kind)
        help_text = subprocess.run(
            [kind.value, "--help"], capture_output=True, text=True, check=True, timeout=10
        ).stdout
        policies = self._supported_policies(kind, help_text)
        return ProviderCapabilities(provider=kind, models=models, policies=policies)

    @staticmethod
    def _supported_policies(provider: ProviderKind, help_text: str) -> tuple[str, ...]:
        """설치된 CLI가 명시한 정책 중 어댑터가 구현한 정책을 선택한다.

        Args:
            provider: 지원하는 공급자 종류.
            help_text: 설치된 CLI에서 읽은 도움말 원문.

        Returns:
            tuple[str, ...]: 실제 지원 여부를 확인한 정책 목록.

        Raises:
            ValueError: 지원하지 않는 공급자 값이 전달된 경우.
            RuntimeError: 독립 실행 또는 정책 목록을 확인할 수 없는 경우.
        """
        match provider:
            case ProviderKind.CODEX:
                if "--no-daemon" not in help_text:
                    raise RuntimeError(
                        "Installed Codex does not support isolated process execution"
                    )
                pattern = r"--sandbox[\s\S]*?\[possible values: ([^\]]+)\]"
                supported = ("read-only", "workspace-write", "danger-full-access")
            case ProviderKind.CLAUDE:
                pattern = r"--permission-mode[\s\S]*?\(choices: ([^)]+)\)"
                supported = ("plan", "dontAsk", "acceptEdits")
            case _:
                raise ValueError("Unsupported provider")
        match = re.search(pattern, help_text)
        if match is None:
            raise RuntimeError("Installed provider does not advertise supported execution policies")
        advertised = {
            item.strip().strip('"') for item in match.group(1).replace("\n", "").split(",")
        }
        policies = tuple(policy for policy in supported if policy in advertised)
        if not policies:
            raise RuntimeError("Installed provider has no supported execution policy")
        return policies

    @staticmethod
    def _directory(delegation_id: UUID) -> Path:
        """고유 배정 ID를 사용자 저장 위치 안의 실행 디렉터리로 해석한다.

        Args:
            delegation_id: UUID 형식의 배정 ID.

        Returns:
            Path: 이 배정만의 실행 자료 위치.
        """
        return user_database_path().parent / "provider-runs" / str(delegation_id)

    @override
    def start(self, delegation_id: UUID, plan: ProviderPlan, prompt: str) -> ProviderObservation:
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
            if saved.exists() and json.loads(saved.read_text()) != self._plan_document(plan):
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
        (directory / "plan.json").write_text(
            json.dumps(self._plan_document(plan), default=encode_uuid)
        )
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
    def observe(self, delegation_id: UUID) -> ProviderObservation:
        """기존 출력과 종료 결과만 읽어 불명·실패·중단·완료를 구분한다.

        Args:
            delegation_id: 원 배정 ID.

        Returns:
            ProviderObservation: 실제 호스트 ID와 원 결과를 포함한 관찰.
        """
        directory = self._directory(delegation_id)
        transcript = self._read_transcript(directory)
        result_path = directory / "result.json"
        if not result_path.exists():
            running = transcript.native_session_id is not None and self._is_running(directory)
            return ProviderObservation(
                reference=str(directory),
                status=ProviderStatus.RUNNING if running else ProviderStatus.UNKNOWN,
                native_session_id=transcript.native_session_id,
                output=transcript.output,
                error="Completion has not been observed",
            )
        result = cast(dict[str, object], json.loads(result_path.read_text()))
        status, error = self._completion_result(directory, transcript, result)
        return ProviderObservation(
            reference=str(directory),
            status=status,
            native_session_id=transcript.native_session_id,
            output=transcript.output,
            error=error,
        )

    @staticmethod
    def _read_transcript(directory: Path) -> ProviderTranscript:
        """출력을 공급자 사건별로 해석하며 아직 덜 쓰인 JSON 줄은 다음 조회로 남긴다.

        Args:
            directory: 원 실행 자료 디렉터리.

        Returns:
            ProviderTranscript: 실제 출력에 있는 세션과 모델 결과만 모은 관찰.
        """
        log = directory / "output.jsonl"
        if not log.exists():
            return ProviderTranscript(
                native_session_id=None, output="", error=None, completed=False
            )
        native_id: str | None = None
        output: list[str] = []
        error: str | None = None
        completed = False
        for line in log.read_text(errors="replace").splitlines():
            try:
                message = cast(dict[str, object], json.loads(line))
            except json.JSONDecodeError:
                continue
            if message.get("session_id"):
                native_id = str(message["session_id"])
            match message.get("type"):
                case "thread.started":
                    native_id = str(message["thread_id"])
                case "turn.completed":
                    completed = True
                case "result":
                    completed = True
                    output.append(str(message.get("result", "")))
                    if message.get("is_error"):
                        error = str(message.get("errors", message))
                case "item.completed":
                    item = cast(dict[str, object], message["item"])
                    if item.get("type") == "agent_message":
                        output.append(str(item["text"]))
                case "error" | "turn.failed":
                    error = str(message)
        return ProviderTranscript(
            native_session_id=native_id, output="\n".join(output), error=error, completed=completed
        )

    @staticmethod
    def _is_running(directory: Path) -> bool:
        """저장한 프로세스 신원과 현재 관찰이 일치하는지 확인한다.

        Args:
            directory: 원 프로세스 신원을 보존한 위치.

        Returns:
            bool: 현재 살아 있는 동일 프로세스일 때만 True.
        """
        record = directory / "process.json"
        if not record.exists():
            return False
        process = cast(dict[str, object], json.loads(record.read_text()))
        identity = process_identity(int(str(process["pid"])))
        return bool(identity) and identity == process["identity"]

    @staticmethod
    def _completion_result(
        directory: Path, transcript: ProviderTranscript, result: dict[str, object]
    ) -> tuple[ProviderStatus, str | None]:
        """실제 종료 코드와 호스트 결과를 대조해 중단·실패·완료를 구분한다.

        Args:
            directory: 원 실행의 취소 표시 위치.
            transcript: 호스트 출력 관찰.
            result: worker가 보존한 실제 종료 결과.

        Returns:
            tuple[ProviderStatus, str | None]: 관찰 상태와 실패 진단.
        """
        code = result.get("exit_code")
        if code == -signal.SIGTERM and (directory / "cancel.requested").exists():
            return ProviderStatus.STOPPED, None
        if (
            code == 0
            and transcript.error is None
            and transcript.native_session_id is not None
            and transcript.completed
        ):
            return ProviderStatus.COMPLETED, None
        error = result.get(
            "error",
            transcript.error
            or f"Provider exited with code {code}; native session: {transcript.native_session_id}",
        )
        return ProviderStatus.FAILED, str(error)

    @staticmethod
    def _plan_document(plan: ProviderPlan) -> dict[str, str]:
        """실행 계획을 기존 파일 표현으로 저장하고 같은 형태로 재연결 시 대조한다.

        Args:
            plan: 명시적인 모델·정책·부모 범위.

        Returns:
            dict[str, str]: UUID도 정규 문자열로 표현한 계획 문서.
        """
        return {
            "provider": plan.provider,
            "model": plan.model,
            "policy": plan.policy,
            "directory": plan.directory,
            "parent_session_id": str(plan.parent_session_id),
        }

    @override
    def cancel(self, delegation_id: UUID) -> ProviderObservation:
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
            (directory / "result.json").write_text(
                json.dumps({"exit_code": -signal.SIGTERM}, default=encode_uuid)
            )
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
                reference=str(directory),
                status=ProviderStatus.UNKNOWN,
                error="Process identity no longer matches; stop is unconfirmed",
            )
        (directory / "cancel.requested").touch()
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return self.observe(delegation_id)
