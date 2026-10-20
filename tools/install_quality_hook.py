"""기존 사용자 훅을 보존하면서 작업 트리 전용 품질 훅을 설치한다."""

import os
import shlex
import subprocess
from pathlib import Path

MARKER = "# neurath-quality-hook-v1"


def git_environment() -> dict[str, str]:
    """호출할 Git의 대상 저장소가 상속 환경으로 바뀌지 않게 GIT_*를 제외한다.

    Returns:
        dict[str, str]: 상속된 Git 저장소 환경 설정을 제거한 프로세스 환경.
    """
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def git(root: Path, *arguments: str) -> str:
    """명시적으로 선택한 체크아웃의 Git 설정을 읽거나 변경한다.

    Args:
        root: 조사할 체크아웃의 루트 디렉터리.
        *arguments: 셸 보간 없이 전달하는 Git 인자들.

    Returns:
        str: 앞뒤 공백을 제거한 Git 표준 출력.
    """
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, env=git_environment()
    ).strip()


def optional_config(root: Path, scope: str, key: str) -> str | None:
    """설정값의 부재와 실행 실패를 구분하여 설정을 읽는다.

    Args:
        root: 조사할 체크아웃의 루트 디렉터리.
        scope: Git 설정 범위 플래그이며 빈 문자열이면 유효 설정 전체.
        key: 읽을 Git 설정 키.

    Returns:
        str | None: 유효 설정값이며 Git이 키 부재를 보고하면 None.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "config", *([scope] if scope else []), "--get", key],
        text=True,
        capture_output=True,
        env=git_environment(),
        check=False,
    )
    if result.returncode == 1:
        return None
    result.check_returncode()
    return result.stdout.strip()


def install(root: Path) -> Path:
    """현재 작업 트리의 pre-commit 앞에 기존 훅을 연결하고 품질 검사를 설치한다.

    관리 표지가 있는 동일 설치는 재사용한다. 다른 worktree의 hooksPath를 바꾸지
    않도록 worktree별 설정을 활성화하고 현재 작업 트리의 경로만 지정한다.

    Args:
        root: 품질 훅을 설치할 체크아웃의 경로.

    Returns:
        Path: 이전 훅을 보존하여 설치한 작업 트리 전용 훅 경로.

    Raises:
        RuntimeError: 관리 표지 없는 설치·기존 대상 디렉터리·명시적 core.worktree·bare 설정을 만난 경우.
    """
    root = Path(git(root, "rev-parse", "--show-toplevel"))
    git_directory = Path(git(root, "rev-parse", "--absolute-git-dir"))
    destination = git_directory / "neurath-quality-hooks"
    hook = destination / "pre-commit"
    current_hooks = optional_config(root, "", "core.hooksPath")
    managed = current_hooks is not None and Path(current_hooks) == destination
    if managed and (not hook.is_file() or MARKER not in hook.read_text()):
        raise RuntimeError("Managed hook path exists without the expected hook; inspect manually")
    if managed:
        return hook
    if destination.exists():
        raise RuntimeError("Refusing to overwrite an existing hook directory")
    if optional_config(root, "--local", "core.worktree") is not None:
        raise RuntimeError("Explicit core.worktree requires manual worktreeConfig migration")
    if optional_config(root, "--local", "core.bare") == "true":
        raise RuntimeError("Bare repositories do not support this checkout hook")
    if current_hooks is None:
        previous = Path(git(root, "rev-parse", "--git-path", "hooks/pre-commit"))
    else:
        previous = Path(current_hooks) / "pre-commit"
    if not previous.is_absolute():
        previous = root / previous
    script = "#!/bin/sh\nset -eu\n" + MARKER + "\n"
    script += f"previous={shlex.quote(str(previous))}\n"
    script += 'if [ -x "$previous" ]; then "$previous" "$@"; fi\n'
    script += "exec uv run --locked pre-commit run --hook-stage pre-commit\n"
    destination.mkdir()
    hook.write_text(script)
    hook.chmod(0o755)
    # hooksPath를 이 작업 트리에만 설정할 수 있도록 worktree별 설정을 활성화한다.
    git(root, "config", "--local", "extensions.worktreeConfig", "true")
    git(root, "config", "--worktree", "core.hooksPath", str(destination))
    return hook


def main() -> None:
    """이 도구가 속한 체크아웃에 훅을 설치한다."""
    print(install(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    main()
