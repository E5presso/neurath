"""한국어 설명 누락 검사와 과도한 비율 제한 방지의 회귀를 검증한다."""

from pathlib import Path

import pytest

from tools.docstrings import check_source, check_tree


@pytest.mark.parametrize("doc", ["Return the current project.", "Read SQLAlchemy Session state."])
def test_wholly_english_documentation_is_reported(doc):
    assert check_source(f'"""{doc}"""', "fixture.py")


def test_language_check_does_not_invent_a_ratio_or_per_line_quota():
    doc = "SQLAlchemy Session Transaction ConnectionManager SchemaRegistry를 설명한다.\n\nExamples:\n    Transaction(context)"
    assert check_source(f'"""{doc}"""', "fixture.py") == []


def test_korean_prose_preserves_google_headings_types_and_code_identifiers():
    source = '''"""프로젝트를 조회하고 저장하는 계약이다.

Args:
    project_id: 조회할 프로젝트의 식별자.
Returns:
    tuple[ProjectLocation, ...]: Project가 소유한 위치 값들.
Raises:
    ValueError: 식별자가 비어 있는 경우.
Attributes:
    session: SQLAlchemy의 `Session` 자원.
"""
'''
    assert check_source(source, "fixture.py") == []


def test_embedded_negative_test_data_is_not_an_actual_docstring():
    source = "'''한국어 문서 회귀 검사의 음성 데이터를 보관한다.'''\nfixture = '\"\"\"English fixture.\"\"\"'"
    assert check_source(source, "fixture.py") == []


def test_language_guard_discovers_new_tools_tests_and_root_configuration(tmp_path):
    for relative in ("src/new.py", "tools/new.py", "tests/new.py", "config.py"):
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text('"""English documentation."""')
    errors = check_tree(tmp_path)
    assert len(errors) == 4
    assert all("KOREAN_DOCSTRING" in error for error in errors)


def test_current_docstrings_have_korean_descriptions_for_language_review():
    assert check_tree(Path(__file__).resolve().parents[1]) == []
