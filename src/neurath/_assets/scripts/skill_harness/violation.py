"""violation 관련 타입과 실행 흐름을 정의합니다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Violation:
    """violation 관련 설정과 검증 조건을 함께 표현합니다."""

    code: str
    """code 값을 보관합니다."""
    path: Path
    """path 값을 보관합니다."""
    message: str
    """domain validation error가 실패 원인을 설명할 때 사용하는 고정 문구입니다."""

    def render(self, root: Path) -> str:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            root: 호출자가 넘긴 root 값입니다.

        Returns:
            render 처리 결과입니다."""
        display = self.path.relative_to(root) if self.path.is_relative_to(root) else self.path
        return f"{display}: {self.code}: {self.message}"
