"""Agent harness violation 출력 모델을 정의합니다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Violation:
    """Agent harness가 발견한 단일 정책 위반입니다."""

    code: str
    """위반 rule을 식별하는 agent harness 코드입니다."""
    path: Path
    """위반이 발생한 repository 파일 경로입니다."""
    message: str
    """domain validation error가 실패 원인을 설명할 때 사용하는 고정 문구입니다."""

    def render(self, root: Path) -> str:
        """위반을 root-relative CLI 출력 문자열로 렌더링합니다.

        Args:
            root: 상대 경로 계산 기준이 되는 Neurath checkout root입니다.

        Returns:
            `<path>: <code>: <message>` 형식의 출력 문자열입니다."""
        display = self.path.relative_to(root) if self.path.is_relative_to(root) else self.path
        return f"{display}: {self.code}: {self.message}"
