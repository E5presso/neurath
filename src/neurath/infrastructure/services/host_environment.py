"""현재 프로세스의 호스트 주소와 cwd를 변경 없이 읽는다."""

import os
from pathlib import Path
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.host_environment import (
    HostEnvironment,
    IHostEnvironmentService,
)


@Pod()
class PosixHostEnvironmentService(IHostEnvironmentService):
    """호스트 환경과 관찰된 세션을 연결하며 없는 신원을 생성하지 않는다."""

    @override
    def read(self) -> HostEnvironment:
        """명령마다 환경을 새로 읽어 이전 호출의 맥락을 재사용하지 않는다.

        Returns:
            HostEnvironment: 호스트 세션 주소와 실제 현재 폴더.
        """
        native = (
            os.environ.get("NEURATH_SESSION_ID")
            or os.environ.get("CODEX_THREAD_ID")
            or os.environ.get("CLAUDE_SESSION_ID", "")
        )
        provider = os.environ.get("NEURATH_PROVIDER", "")
        if not provider and os.environ.get("CODEX_THREAD_ID"):
            provider = "codex"
        return HostEnvironment(directory=str(Path.cwd()), session=native, provider=provider)

    @override
    def publish(self, provider: str, session: str) -> None:
        """Claude의 공식 환경 파일에 Neurath 소유 변수만 안전하게 추가한다.

        Args:
            provider: 실제 시작한 호스트 공급자.
            session: 실제 시작 사건의 세션 주소.
        """
        from shlex import quote

        target = os.environ.get("CLAUDE_ENV_FILE")
        if provider != "claude" or not target:
            return
        path = Path(target)
        content = path.read_text() if path.exists() else ""
        values = {"NEURATH_SESSION_ID": session, "NEURATH_PROVIDER": provider}
        for key in ("SPAKKY_SQLALCHEMY__CONNECTION_STRING", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            if key in os.environ:
                values[key] = os.environ[key]
        lines = [f"export {key}={quote(value)}" for key, value in values.items()]
        missing = [line for line in lines if line not in content.splitlines()]
        if not missing:
            return
        with path.open("a") as stream:
            stream.write("\n" + "\n".join(missing) + "\n")
