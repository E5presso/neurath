"""한국어 설명이 없는 실제 Python 문서 문자열을 찾는다."""

import ast
import re
from pathlib import Path


def check_source(source: str, path: str) -> list[str]:
    """실제 문서 문자열에 한국어 설명이 전혀 없는 경우를 찾는다.

    코드 블록·인라인 코드·Google 섹션명은 설명에서 제외한다. 글자 수나
    영문 대비 비율을 요구하지 않는다. 한국어의 존재만 확인하는 최소 검사이며
    번역의 정확성과 실제 설명 언어·유용성은 별도로 검토한다.

    Args:
        source: 검사할 Python 소스 텍스트.
        path: 진단에 표시할 소스 경로.

    Returns:
        list[str]: 한국어 설명이 전혀 없는 문서 문자열의 진단 목록.
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
        descriptions: list[str] = []
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
            descriptions.append(prose)
        if descriptions and not re.search(r"[가-힣]", " ".join(descriptions)):
            errors.append(
                f"{path}:{node.body[0].lineno} KOREAN_DOCSTRING: 한국어 설명이 없는 문서 문자열을 확인하세요"
            )
    return errors


def check_tree(root: Path) -> list[str]:
    """체크아웃의 모든 Python 소스와 도구·테스트·설정 문서를 검사한다.

    Git 관리 대상 경로는 호출자가 별도로 지정하지 않으며 개발 환경과 빌드
    산출물은 탐색하지 않는다. 루트의 Python 설정 파일도 검사에 포함한다.

    Args:
        root: 검사할 체크아웃의 루트 디렉터리.

    Returns:
        list[str]: 한국어 설명이 없는 문서 문자열의 진단 목록.
    """
    paths = list(root.glob("*.py"))
    for folder in ("src", "tools", "tests"):
        paths.extend((root / folder).rglob("*.py"))
    return [error for path in sorted(paths) for error in check_source(path.read_text(), str(path))]


def main() -> None:
    """문서의 한국어 설명 누락 검사를 실행하고 누락이 있으면 실패한다.

    Raises:
        SystemExit: 한국어 설명이 없는 문서 문자열이 있는 경우.
    """
    errors = check_tree(Path(__file__).resolve().parents[1])
    if errors:
        raise SystemExit("\n".join(errors))
    print("KOREAN_DOCSTRINGS_OK")


if __name__ == "__main__":
    main()
