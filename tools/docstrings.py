"""실제 Python 문서 문자열의 한국어 설명이 퇴행하지 않는지 검사한다."""

import ast
import re
from pathlib import Path


def check_source(source: str, path: str) -> list[str]:
    """실제 문서 문자열의 요약과 각 설명 줄에서 한국어 서술을 확인한다.

    식별자·인라인 코드·Google 섹션명은 언어 비율에서 제외한다. 남은 서술은
    한글이 두 글자 이상이고 영문 글자 수 이상이어야 한다. 번역의 정확성과
    문서의 유용성은 이 문법적 회귀 검사와 별도로 사람이 검토한다.

    Args:
        source: 검사할 Python 소스 텍스트.
        path: 진단에 표시할 소스 경로.

    Returns:
        list[str]: 한국어 요약이나 필드 설명이 부족한 문서 문자열의 진단 목록.
    """
    errors: list[str] = []
    headings = {"Args:", "Returns:", "Yields:", "Raises:", "Attributes:", "Examples:", "Notes:"}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node)
        if doc is None:
            continue
        in_code = False
        for offset, line in enumerate(doc.splitlines()):
            prose = line.strip()
            if prose.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not prose or prose in headings or prose.startswith(">>>"):
                continue
            if ": " in prose:
                prose = prose.split(": ", 1)[1]
            prose = re.sub(r"`[^`]+`", "", prose)
            prose = re.sub(r"\b[A-Za-z_]\w*(?:\.\w+)+\b", "", prose)
            prose = re.sub(
                r"(?<![A-Za-z0-9_])(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*|[A-Za-z]+_[A-Za-z_0-9]+)(?![A-Za-z0-9_])",
                "",
                prose,
            )
            korean = len(re.findall(r"[가-힣]", prose))
            english = len(re.findall(r"[a-zA-Z]", prose))
            if korean < 2 or korean < english:
                line_number = node.body[0].lineno + offset
                errors.append(
                    f"{path}:{line_number} KOREAN_DOCSTRING: 한국어로 요약과 설명을 작성하세요"
                )
    return errors


def check_tree(root: Path) -> list[str]:
    """체크아웃의 모든 Python 소스와 도구·테스트·설정 문서를 검사한다.

    Git 관리 대상 경로는 호출자가 별도로 지정하지 않으며 개발 환경과 빌드
    산출물은 탐색하지 않는다. 루트의 Python 설정 파일도 검사에 포함한다.

    Args:
        root: 검사할 체크아웃의 루트 디렉터리.

    Returns:
        list[str]: 현재 소스와 도구·테스트·설정의 문서 언어 위반 목록.
    """
    paths = list(root.glob("*.py"))
    for folder in ("src", "tools", "tests"):
        paths.extend((root / folder).rglob("*.py"))
    return [error for path in sorted(paths) for error in check_source(path.read_text(), str(path))]


def main() -> None:
    """한국어 문서 회귀 검사를 실행하고 위반하면 실패 상태로 종료한다.

    Raises:
        SystemExit: 한국어 문서 작성 규칙을 위반한 경우.
    """
    errors = check_tree(Path(__file__).resolve().parents[1])
    if errors:
        raise SystemExit("\n".join(errors))
    print("KOREAN_DOCSTRINGS_OK")


if __name__ == "__main__":
    main()
