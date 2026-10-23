"""한 배정의 CLI 프로세스를 감시하고 원 출력과 종료 코드를 파일에 보존한다."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import cast


def process_identity(pid: int) -> str:
    """PID 재사용을 구분할 실제 프로세스 시작 시각과 프로세스 그룹을 읽는다.

    Args:
        pid: 관찰할 로컬 프로세스 ID.

    Returns:
        str: 프로세스 관찰 원문이며 대상이 없으면 빈 문자열.
    """
    return subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=", "-o", "pgid="],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def execute(directory: Path) -> None:
    """이미 보존한 계획을 한 번 실행하고 종료 결과를 원자적으로 교체한다.

    Args:
        directory: 고유 배정에 연결된 관리 실행 디렉터리.
    """
    if (directory / "cancel.requested").exists():
        (directory / "result.json").write_text(json.dumps({"exit_code": -signal.SIGTERM}))
        return
    plan = cast(dict[str, str], json.loads((directory / "plan.json").read_text()))
    provider = plan["provider"]
    if provider == "codex":
        args = [
            "codex",
            "--no-daemon",
            "exec",
            "--json",
            "--model",
            plan["model"],
            "--sandbox",
            plan["policy"],
            "-c",
            'approval_policy="never"',
            "--cd",
            plan["directory"],
            "-",
        ]
    else:
        args = [
            "claude",
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--model",
            plan["model"],
            "--permission-mode",
            plan["policy"],
            "--permission-prompts",
            "none",
            "--session-id",
            directory.name,
        ]
    environment = dict(os.environ, NEURATH_DELEGATION_ID=directory.name)
    with (
        (directory / "prompt.txt").open("rb") as prompt,
        (directory / "output.jsonl").open("wb") as output,
        (directory / "stderr.txt").open("wb") as stderr,
    ):
        try:
            with subprocess.Popen(
                args,
                cwd=plan["directory"],
                env=environment,
                stdin=prompt,
                stdout=output,
                stderr=stderr,
                start_new_session=True,
            ) as process:
                identity = process_identity(process.pid)
                (directory / "process.json").write_text(
                    json.dumps({"pid": process.pid, "identity": identity})
                )
                if (directory / "cancel.requested").exists():
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                code = process.wait()
            result: dict[str, object] = {"exit_code": code}
        except OSError as error:
            result = {"error": str(error)}
    temporary = directory / "result.tmp"
    temporary.write_text(json.dumps(result))
    temporary.replace(directory / "result.json")


if __name__ == "__main__":
    execute(Path(sys.argv[1]))
