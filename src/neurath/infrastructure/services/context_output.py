"""긴 복원 원문을 사용자 데이터 디렉터리의 독립 파일로 보존한다."""

import os
from hashlib import sha256
from tempfile import NamedTemporaryFile
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.context_output import IContextOutputService
from neurath.infrastructure.database import user_database_path


@Pod()
class PosixContextOutputService(IContextOutputService):
    """같은 내용은 같은 파일에 보존하며 본문을 조용히 잘라내지 않는다."""

    @override
    def preserve(self, content: str) -> str:
        """전체 본문을 저장하고 재현 가능한 절대 경로를 반환한다.

        Args:
            content: 호스트 복원 한도를 넘는 전체 본문.

        Returns:
            str: 다음 호스트 읽기 도구가 사용할 파일 경로.
        """
        directory = user_database_path().parent / "context"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / f"{sha256(content.encode()).hexdigest()}.txt"
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
            temporary = stream.name
            try:
                stream.write(content)
                stream.flush()
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return str(path)
