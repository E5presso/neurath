"""실행 어댑터가 직접 소유한 프로세스 그룹을 관찰하고 중단한다."""

import os
import signal
import subprocess
from collections.abc import Mapping
from typing import override
from uuid import UUID

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.execution_controller import IExecutionControllerService
from neurath.application.ports.services.writer_observer import IWriterObserverService
from neurath.domain.runtime_records import Liveness


@Pod()
class PosixWriterObserverService(IWriterObserverService, IExecutionControllerService):
    """실행기가 격리된 새 프로세스 그룹으로 직접 시작한 호출만 제어한다.

    Popen(start_new_session=True) 핸들을 실행기에서 받는다. 호스트 앱 PID를 추측하여
    종료하지 않으며 핸들 유실은 UNKNOWN으로 둔다. 루트 프로세스만 종료되고 자식이
    남아 있으면 임대를 회수하지 않는다. 이 상태는 실행 어댑터의 효과 핸들이며 코어의
    지속 상태는 SQLite에서 요청마다 읽는다.
    """

    def __init__(
        self, processes: Mapping[tuple[UUID, str, str], subprocess.Popen[bytes]] | None = None
    ) -> None:
        """실행기가 직접 시작한 프로세스 핸들을 실제 호출 식별자에 연결한다.

        Args:
            processes: 실행·턴·도구 호출별 소유 핸들이며 미등록이면 관찰 결과는 UNKNOWN.
        """
        self.processes = {} if processes is None else processes

    @override
    def observe(self, execution_id: UUID, turn_id: str, tool_use_id: str) -> Liveness:
        """일치하는 호출의 프로세스와 남은 그룹 구성원까지 확인한다.

        Args:
            execution_id: 관찰할 실제 실행.
            turn_id: 해당 실행의 정확한 턴.
            tool_use_id: 관찰할 작성 호출.

        Returns:
            Liveness: 핸들·권한 불명은 UNKNOWN이며 실제 그룹 소멸만 STOPPED.
        """
        process = self.processes.get((execution_id, turn_id, tool_use_id))
        if process is None:
            return Liveness.UNKNOWN
        return self._observe(process)

    @override
    def interrupt(self, execution_id: UUID, turn_id: str) -> Liveness:
        """정확한 실행·턴의 소유 프로세스 그룹만 중단하고 종료를 확인한다.

        Args:
            execution_id: 중단할 실제 실행.
            turn_id: 중단할 정확한 턴.

        Returns:
            Liveness: 대상이 없거나 그룹 소유를 확인할 수 없으면 UNKNOWN.
        """
        processes = tuple(
            process
            for (owner, turn, _), process in self.processes.items()
            if owner == execution_id and turn == turn_id
        )
        if not processes:
            return Liveness.UNKNOWN
        results: list[Liveness] = []
        for process in processes:
            results.append(self._interrupt(process))
        if all(result is Liveness.STOPPED for result in results):
            return Liveness.STOPPED
        return Liveness.UNKNOWN

    def _interrupt(self, process: subprocess.Popen[bytes]) -> Liveness:
        """소유한 루트가 살아 있는 독립 그룹만 종료한다.

        Args:
            process: 직접 생성한 프로세스 핸들.

        Returns:
            Liveness: 중단 후 관찰이며 OS 오류는 미확인으로 처리.
        """
        if process.poll() is not None:
            return self._observe(process)
        try:
            if os.getpgid(process.pid) != process.pid:
                return Liveness.UNKNOWN
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        except OSError, subprocess.TimeoutExpired:
            return Liveness.UNKNOWN
        return self._observe(process)

    @staticmethod
    def _observe(process: subprocess.Popen[bytes]) -> Liveness:
        """루트의 실제 종료와 프로세스 그룹 소멸을 따로 확인한다.

        Args:
            process: 관찰할 소유 프로세스 핸들.

        Returns:
            Liveness: 루트 또는 자식이 살아 있으면 RUNNING, 관찰 권한이 없으면 UNKNOWN.
        """
        if process.poll() is None:
            return Liveness.RUNNING
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return Liveness.STOPPED
        except OSError:
            return Liveness.UNKNOWN
        return Liveness.RUNNING
