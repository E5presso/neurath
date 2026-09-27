"""violation 관련 타입과 실행 흐름을 정의합니다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Violation:

    code: str
    """code 값을 보관합니다."""
    path: Path
    """path 값을 보관합니다."""
    message: str
    """domain validation error가 실패 원인을 설명할 때 사용하는 고정 문구입니다."""

    def render(self, root: Path) -> str:
        display = self.path.relative_to(root) if self.path.is_relative_to(root) else self.path
        return f"{display}: {self.code}: {self.message}"
