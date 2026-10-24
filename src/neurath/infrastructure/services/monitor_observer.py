"""PR 상태 조회는 30초로 제한하고 출력은 마지막 완결 JSON 상태만 사용한다."""

import json
import subprocess
from pathlib import Path
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.monitor_observer import (
    IMonitorObserverService,
    MonitorObservation,
)
from neurath.domain.values.task_monitor import MonitorKind


@Pod()
class SubprocessMonitorObserverService(IMonitorObserverService):
    """PR 상태 조회는 30초로 제한하고 출력은 마지막 완결 JSON 상태만 사용한다."""

    @override
    def observe(self, kind: MonitorKind, target: str) -> MonitorObservation:
        """모델을 깨우거나 임의 명령을 실행하지 않고 명시한 대상만 읽는다.

        Args:
            kind: PR 또는 완결 상태 출력 파일.
            target: 등록 시 검증한 정확한 대상.

        Returns:
            MonitorObservation: 완결 상태·조각 또는 실제 실패.

        Raises:
            ValueError: 미지원 종류·너무 큰 상태이며 관찰 실패 값으로 변환함.
        """
        try:
            match kind:
                case MonitorKind.PULL_REQUEST:
                    return self._pull_request(target)
                case MonitorKind.OUTPUT:
                    return self._output(target)
                case _:
                    raise ValueError("Unsupported monitor kind")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            return MonitorObservation(
                state=None,
                reference=target,
                error=f"{type(error).__name__}: {error}. Check the target and observer access.",
            )

    def _pull_request(self, target: str) -> MonitorObservation:
        """시각·로그 조각을 제외한 PR·검사 상태를 안정된 JSON으로 정규화한다.

        Args:
            target: 저장한 정확한 GitHub PR 주소.

        Returns:
            MonitorObservation: 대상 요구와 체크 상태의 완결 관찰.

        Raises:
            ValueError: 완결 상태가 보존 한도를 초과한 경우.
        """
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                target,
                "--json",
                "state,headRefOid,reviewDecision,mergeStateStatus,statusCheckRollup",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(result.stdout)
        checks = sorted(
            json.dumps(
                {
                    key: row.get(key)
                    for key in ("name", "context", "state", "status", "conclusion", "workflowName")
                },
                sort_keys=True,
            )
            for row in data["statusCheckRollup"] or ()
        )
        state = json.dumps(
            {
                "state": data["state"],
                "head": data["headRefOid"],
                "review": data["reviewDecision"],
                "merge": data["mergeStateStatus"],
                "checks": checks,
            },
            sort_keys=True,
        )
        if len(state) > 16384:
            raise ValueError("PR state exceeds the bounded observation contract")
        return MonitorObservation(state=state, reference=target)

    def _output(self, target: str) -> MonitorObservation:
        """최대 64KiB 꼬리에서 마지막 완결 행의 state만 읽고 조각은 무시한다.

        Args:
            target: 요청한 절대 출력 파일 경로.

        Returns:
            MonitorObservation: 마지막 완결 상태 또는 조각뿐인 관찰.

        Raises:
            ValueError: 완결된 상태 레코드가 지원하는 형식이 아닌 경우.
        """
        with Path(target).open("rb") as stream:
            size = stream.seek(0, 2)
            offset = max(0, size - 65536)
            stream.seek(offset)
            output = stream.read(65536)
        lines = output.split(b"\n")[:-1]
        if offset:
            lines = lines[1:]
        if not lines:
            return MonitorObservation(state=None, reference=target)
        data = json.loads(lines[-1])
        if not isinstance(data, dict) or not isinstance(data.get("state"), str):
            raise ValueError("Complete output line requires a string state field")
        if not data["state"].strip() or len(data["state"]) > 16384:
            raise ValueError("Output state must be nonempty and at most 16384 characters")
        return MonitorObservation(state=data["state"], reference=f"{target}#bytes={size}")
