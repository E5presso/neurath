"""POSIX 프로세스 그룹을 실행하며 출력은 메모리의 지정 한도만 보존한다."""

import os
import signal
import subprocess
from threading import Event, Thread
from time import monotonic
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.phase_executor import IPhaseExecutorService
from neurath.domain.values.phase_attempt import PhaseResult, PhaseStatus
from neurath.domain.values.workflow_definition import PhaseDefinition


@Pod()
class SubprocessPhaseExecutorService(IPhaseExecutorService):
    """POSIX 프로세스 그룹을 실행하며 출력은 메모리의 지정 한도만 보존한다.

    프로세스 수명 안의 중단 신호만 메모리에 보유한다. 프로세스가 사라진 뒤의
    결과 조회·중복 제거는 보장하지 않으므로 재시작 후 결과 불명을 재실행하지 않는다.
    """

    def __init__(self) -> None:
        """현재 요청 실행의 중단 신호를 초기화한다."""
        self.interrupted = Event()

    @property
    @override
    def supports_deduplication(self) -> bool:
        """로컬 프로세스 실행에는 영속적인 중복 제거가 없음을 반환한다.

        Returns:
            bool: 항상 False.
        """
        return False

    def interrupt(self) -> None:
        """현재 요청의 실행 중인 프로세스를 종료하도록 신호를 설정한다."""
        self.interrupted.set()

    @override
    def lookup(self, request_id: str, phase: PhaseDefinition) -> PhaseResult | None:
        """이전 프로세스의 결과를 복원할 수 없으므로 미확인을 반환한다.

        Args:
            request_id: 조회하려는 시도의 ID.
            phase: 시도 당시의 단계 정의.

        Returns:
            PhaseResult | None: 영속 실행 영수증이 없으므로 None.
        """
        return None

    @override
    def execute(self, request_id: str, phase: PhaseDefinition) -> PhaseResult:
        """명령을 실행하고 제한 시간·중단 시 자식 그룹까지 종료한다.

        exit:0만 자동 판정한다. 그 밖의 검사는 별도 결과 보고에서 충족해야 하며
        프로세스 성공만으로 임의의 의미적 검증 조건을 통과시키지 않는다.

        Args:
            request_id: 결과 근거에 연결할 run·시도 ID.
            phase: 실행 인자·디렉터리·대상과 출력·시간 한도.

        Returns:
            PhaseResult: 종료 코드·제한된 출력과 실제 실패 또는 성공 결과.
        """
        output = bytearray()
        truncated = Event()
        try:
            process = subprocess.Popen(
                list(phase.arguments),
                cwd=phase.directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as error:
            return PhaseResult(
                status=PhaseStatus.FAILED,
                target_revision=phase.target_revision,
                summary=str(error),
                evidence=(request_id,),
            )
        assert process.stdout is not None
        stream = process.stdout

        def read_output() -> None:
            """파이프를 계속 비우되 보존 한도를 넘긴 출력은 메모리에 쌓지 않는다."""
            while chunk := stream.read(65536):
                remaining = phase.output_limit - len(output)
                output.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated.set()

        reader = Thread(target=read_output, daemon=True)
        reader.start()
        deadline = monotonic() + phase.timeout
        reason = ""
        try:
            while process.poll() is None:
                if self.interrupted.is_set():
                    reason = "interrupted"
                    break
                if monotonic() >= deadline:
                    reason = "timeout"
                    break
                try:
                    process.wait(timeout=0.02)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            reader.join()
            stream.close()
            self.interrupted.clear()
        succeeded = not reason and process.returncode == 0
        status = PhaseStatus.SUCCEEDED if succeeded else PhaseStatus.FAILED
        if succeeded and not set(phase.checks).issubset({"exit:0"}):
            status = PhaseStatus.WAITING
            reason = "execution succeeded; required checks remain"
        return PhaseResult(
            status=status,
            target_revision=phase.target_revision,
            summary=(reason or f"exit:{process.returncode}")
            + ("; output truncated" if truncated.is_set() else ""),
            evidence=(request_id,),
            checks=("exit:0",) if succeeded else (),
            output=bytes(output).decode(errors="ignore"),
            exit_code=process.returncode,
        )
