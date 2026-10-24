"""Git HEAD와 로컬 산출물 내용을 읽어 오래된 평가의 재사용을 막는다."""

import asyncio
import hashlib
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.evaluation_artifact import IEvaluationArtifactService


@Pod()
class GitEvaluationArtifactService(IEvaluationArtifactService):
    """실제 파일 내용과 Git HEAD를 관찰하며 사용자 파일을 수정하지 않는다."""

    @override
    async def observe(self, directory: str, references: Sequence[str]) -> Sequence[str]:
        """읽기 전용 관찰을 이벤트 루프 밖에서 수행한다.

        Args:
            directory: 실제 작업 폴더.
            references: 로컬 경로 또는 외부 불변 참조.

        Returns:
            Sequence[str]: 실제 파일 지문과 현재 HEAD 및 외부 참조.
        """
        return await asyncio.to_thread(self._observe, directory, references)

    def _observe(self, directory: str, references: Sequence[str]) -> Sequence[str]:
        """일반 폴더·Git 저장소·파일 부재를 서로 다른 관찰로 보존한다.

        Args:
            directory: 실제 작업 폴더.
            references: 호출자가 선택한 산출물·검증 참조.

        Returns:
            Sequence[str]: 내용 지문과 현재 Git 개정의 순서 있는 관찰.

        Raises:
            ValueError: 폴더가 없거나 Git 관찰 자체가 실패한 경우.
        """
        folder = Path(directory)
        if not folder.is_dir():
            raise ValueError("Evaluation directory does not exist")
        observations = []
        for reference in references:
            if reference == "git:HEAD":
                result = subprocess.run(
                    ["git", "-C", str(folder), "rev-parse", "--verify", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode == 0:
                    head = f"git-head:{result.stdout.strip()}"
                elif (
                    "not a git repository" in result.stderr
                    or "Needed a single revision" in result.stderr
                ):
                    head = "git-head:unavailable"
                else:
                    raise ValueError(f"Cannot observe current Git HEAD: {result.stderr}")
                observations.append(head)
                continue
            if ":" in reference and not reference.startswith("file:"):
                observations.append(f"external-reference:{reference}")
                continue
            path = Path(reference.removeprefix("file:"))
            if not path.is_absolute():
                path = folder / path
            if not path.is_file():
                observations.append(f"missing-file:{path}")
                continue
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            observations.append(f"file:{path}:{digest}")
        return tuple(observations)
