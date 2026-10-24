"""검증된 빈 스키마를 시험별 독립 SQLite 파일로 복제한다."""

import sqlite3
from contextlib import closing
from pathlib import Path


def copy_empty_database(template: Path, destination: Path) -> Path:
    """읽기 전용 원본에서 SQLite backup으로 새 시험 파일을 만든다."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(template.as_uri() + "?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(destination)) as target,
    ):
        source.backup(target)
    return destination
