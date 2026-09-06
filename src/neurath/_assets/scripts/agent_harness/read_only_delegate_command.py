"""Read-only shell command를 계약 profile별 fail-closed allowlist로 검증합니다.

`delegate` profile은 foreign worktree를 읽는 review/evaluation delegate의 초격리
계약이고, `owner-root` profile은 자기 worktree를 소유한 세션이 repository root
context에서 수행하는 일상 조회(진단용 git 조회, 존재 검사 분기, 단순 reader
pipeline, 격리 assert script)를 mutation 없이 허용하는 계약입니다."""

from __future__ import annotations

import argparse
import re
import shlex
from typing import ClassVar


class ReadOnlyDelegateCommandValidator:
    """Shell control과 mutation surface를 fail-closed allowlist로 제한합니다.

    기본 `delegate` profile은 단일 명령만 허용하고 git에 격리 환경을 요구합니다.
    `owner-root` profile은 `&&`/`;`/pipe로 이어진 조회 체인과 평범한 git 조회를
    허용하되, redirection·substitution·mutation verb는 동일하게 거부합니다."""

    _QUOTE_SUPPRESSED_TOKENS: ClassVar[tuple[str, ...]] = (
        "\n",
        "\r",
        ";",
        "|",
        "&",
        ">",
        "<",
    )
    """따옴표 안에서는 리터럴이 되는 pipe·redirection·separator 연산자입니다. 따옴표를
    마스킹한 잔여 텍스트에서만 shell control로 판정해, 검색 패턴('->' 등) 속 문자는
    데이터로 통과시킵니다."""
    _SUBSTITUTION_TOKENS: ClassVar[tuple[str, ...]] = (
        "`",
        "$(",
    )
    """이중따옴표 안에서도 활성인 command substitution 시작 표식입니다. 따옴표 완화가
    치환 우회를 열지 않도록 원문 그대로 fail-closed로 검사합니다."""
    _SIMPLE_READERS: ClassVar[set[str]] = {
        "basename",
        "cat",
        "column",
        "comm",
        "cut",
        "diff",
        "dirname",
        "file",
        "grep",
        "head",
        "jq",
        "ls",
        "nl",
        "pwd",
        "readlink",
        "realpath",
        "rg",
        "shasum",
        "sort",
        "stat",
        "tail",
        "test",
        "tr",
        "uniq",
        "wc",
    }
    _GIT_READ_SUBCOMMANDS: ClassVar[set[str]] = {
        "describe",
        "diff",
        "diff-tree",
        "log",
        "ls-files",
        "ls-tree",
        "merge-base",
        "name-rev",
        "rev-parse",
        "show",
        "status",
    }
    _GIT_DIFF_SUBCOMMANDS: ClassVar[set[str]] = {"diff", "diff-tree", "log", "show"}
    _GIT_REQUIRED_CONFIG: ClassVar[set[str]] = {
        "core.fsmonitor=false",
        "core.hooksPath=/dev/null",
        "log.showSignature=false",
    }
    _GIT_REQUIRED_ENVIRONMENT: ClassVar[set[str]] = {
        "GIT_CONFIG_GLOBAL=/dev/null",
        "GIT_CONFIG_NOSYSTEM=1",
        "GIT_OPTIONAL_LOCKS=0",
        "GIT_PAGER=cat",
        "HOME=/dev/null",
        "PAGER=cat",
        "PATH=/usr/bin:/bin",
    }

    _OWNER_CONDITIONAL_KEYWORDS: ClassVar[set[str]] = {"if", "elif", "then", "else", "fi"}
    """존재 검사 분기 체인에서 조회 의미만 남기고 벗겨낼 shell keyword입니다."""
    _OWNER_HARMLESS_EXECUTABLES: ClassVar[set[str]] = {"[", "echo", "false", "printf", "true"}
    """분기 결과 표기에만 쓰이는, filesystem을 바꾸지 못하는 executable입니다."""
    _OWNER_ASSERT_SCRIPT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:/[^ ]+/)?\.agents/skills/[a-z0-9-]+/scripts/assert_worktree_isolation\.sh$"
    )
    """소유자가 root context에서 실행할 수 있는 read-only 격리 assert script 경로입니다."""
    _SKILL_SCRIPT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:/[^ ]+/)?\.agents/skills/[a-z0-9-]+/scripts/[a-z0-9_]+\.py$"
    )
    """도움말 조회를 허용하는 in-repo skill helper script 경로입니다."""
    _PYTHON_LAUNCH_PREFIXES: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("uv", "run", "python"),
        ("uv", "run", "python3"),
        ("python3",),
        ("python",),
    )
    """Skill helper 도움말 조회에서 벗겨낼 interpreter launcher 형태입니다."""

    def __init__(self, profile: str = "delegate") -> None:
        """검증에 적용할 계약 profile을 고정합니다.

        Args:
            profile: `delegate`는 foreign worktree 초격리 계약, `owner-root`는
                소유 세션의 root-context 조회 계약을 선택합니다.

        Raises:
            ValueError: 정의되지 않은 profile 이름이 들어오면 발생합니다.
        """
        if profile not in {"delegate", "owner-root"}:
            raise ValueError(f"unknown read-only profile: {profile}")
        self._profile = profile

    def validate(self, command: str) -> None:
        """Command가 side effect 없는 inspection/test allowlist인지 검증합니다.

        Args:
            command: Hook tool input의 원문 shell command입니다.

        Raises:
            ValueError: Shell control 또는 mutation-capable command가 포함됐을 때 발생합니다.
        """
        if not command.strip():
            raise ValueError("delegate command must be non-empty")
        if any(token in command for token in self._SUBSTITUTION_TOKENS):
            raise ValueError("command substitution is not read-only")
        if self._profile == "owner-root":
            self._validate_owner_root_chain(command)
            return
        if any(token in self._quote_masked(command) for token in self._QUOTE_SUPPRESSED_TOKENS):
            raise ValueError("shell control and redirection are not read-only")
        self._validate_single_stage(command, relaxed_git=False)

    def _validate_owner_root_chain(self, command: str) -> None:
        """`&&`/`;`/newline/pipe로 이어진 조회 체인을 stage 단위로 검증합니다.

        Args:
            command: 소유 세션이 root context에서 실행하려는 원문 command입니다.

        Raises:
            ValueError: Redirection, background 실행, mutation stage가 섞이면 발생합니다.
        """
        masked = self._quote_masked(command)
        for harmless in ("2>&1", "2>/dev/null", ">/dev/null"):
            masked = masked.replace(harmless, " " * len(harmless))
        if any(token in masked for token in ("<", ">")):
            raise ValueError("shell redirection is not read-only")
        if re.search(r"(?<!&)&(?!&)", masked):
            raise ValueError("background execution is not read-only")
        boundary = re.compile(r"&&|;|\n|\r|\|")
        cursor = 0
        segments: list[str] = []
        for match in boundary.finditer(masked):
            segments.append(command[cursor : match.start()])
            cursor = match.end()
        segments.append(command[cursor:])
        for segment in segments:
            stripped = segment.strip()
            if not stripped:
                continue
            self._validate_owner_root_stage(stripped)

    def _validate_owner_root_stage(self, stage: str) -> None:
        """조회 체인의 단일 stage가 mutation 능력 없는 allowlist인지 검증합니다.

        Args:
            stage: 구분자 사이에서 잘라낸 하나의 command stage입니다.

        Raises:
            ValueError: Reader/조회 git/assert script/무해 executable 밖이면 발생합니다.
        """
        try:
            tokens = shlex.split(stage, posix=True)
        except ValueError as exc:
            raise ValueError("owner inspection stage must have valid shell quoting") from exc
        while tokens and tokens[0] in self._OWNER_CONDITIONAL_KEYWORDS:
            tokens = tokens[1:]
        if not tokens:
            return
        executable = tokens[0]
        if executable in self._OWNER_HARMLESS_EXECUTABLES:
            return
        if self._OWNER_ASSERT_SCRIPT_PATTERN.match(executable):
            if any(not argument.isdigit() for argument in tokens[1:]):
                raise ValueError("isolation assert script accepts only issue numbers")
            return
        if self._is_skill_script_help(tokens):
            return
        self._validate_single_stage(stage_tokens=tokens, relaxed_git=True)

    def _is_skill_script_help(self, tokens: list[str]) -> bool:
        """Stage가 in-repo skill helper의 도움말 조회인지 판정합니다.

        Args:
            tokens: Tokenize된 stage입니다.

        Returns:
            Launcher + skill script + 도움말 flag(부속 subcommand 하나 허용)면 True입니다.
        """
        for prefix in self._PYTHON_LAUNCH_PREFIXES:
            if tuple(tokens[: len(prefix)]) == prefix:
                tokens = tokens[len(prefix) :]
                break
        else:
            return False
        if not tokens or not self._SKILL_SCRIPT_PATTERN.match(tokens[0]):
            return False
        arguments = tokens[1:]
        help_flags = {"-h", "--help"}
        subcommands = [argument for argument in arguments if argument not in help_flags]
        has_help = any(argument in help_flags for argument in arguments)
        harmless_subcommand = len(subcommands) <= 1 and all(
            not argument.startswith("-") for argument in subcommands
        )
        return has_help and harmless_subcommand

    def _validate_single_stage(
        self,
        command: str | None = None,
        *,
        stage_tokens: list[str] | None = None,
        relaxed_git: bool,
    ) -> None:
        """단일 command를 profile별 git 격리 요구 수준에 맞춰 검증합니다.

        Args:
            command: 아직 tokenize하지 않은 원문 command입니다.
            stage_tokens: 이미 tokenize를 마친 stage token 목록입니다.
            relaxed_git: 소유자 조회 계약에서 git 격리 환경 요구를 생략할지 여부입니다.

        Raises:
            ValueError: Allowlist 밖 executable 또는 mutation-capable 옵션이면 발생합니다.
        """
        if stage_tokens is None:
            try:
                stage_tokens = shlex.split(command or "", posix=True)
            except ValueError as exc:
                raise ValueError("delegate command must have valid shell quoting") from exc
        tokens = stage_tokens
        if not tokens:
            raise ValueError("delegate command must be non-empty")
        tokens, environment, isolated_environment = self._strip_read_only_environment(tokens)
        if not tokens:
            raise ValueError("delegate command is missing an executable")
        executable = tokens[0]
        if executable in self._SIMPLE_READERS:
            self._validate_simple_reader(tokens)
            return
        if executable == "find":
            self._validate_find(tokens)
            return
        if executable == "sed":
            self._validate_sed(tokens)
            return
        if executable == "git":
            if not relaxed_git and (
                not isolated_environment or not self._GIT_REQUIRED_ENVIRONMENT.issubset(environment)
            ):
                raise ValueError(
                    "delegate git requires the complete isolated read-only environment"
                )
            self._validate_git(tokens, relaxed=relaxed_git)
            return
        raise ValueError(f"delegate executable is not read-only allowlisted: {executable}")

    def _quote_masked(self, command: str) -> str:
        """따옴표와 backslash escape로 감싼 구간을 공백으로 지운 잔여 텍스트를 만듭니다.

        pipe·redirection·separator 연산자는 single/double 따옴표 안에서 모두 리터럴이므로,
        마스킹한 잔여 텍스트에서만 이들을 shell control로 판정하면 검색 패턴 속 문자를
        데이터로 통과시키면서 실제 연산자는 그대로 차단합니다.

        Args:
            command: hook tool input의 원문 shell command입니다.

        Returns:
            따옴표·escape 구간을 공백으로 대체한 같은 길이의 문자열입니다."""
        masked: list[str] = []
        quote = ""
        escaped = False
        for character in command:
            if escaped:
                masked.append(" ")
                escaped = False
                continue
            if quote:
                if character == quote:
                    quote = ""
                masked.append(" ")
                continue
            if character == "\\":
                escaped = True
                masked.append(" ")
                continue
            if character in ("'", '"'):
                quote = character
                masked.append(" ")
                continue
            masked.append(character)
        return "".join(masked)

    def _strip_read_only_environment(
        self,
        tokens: list[str],
    ) -> tuple[list[str], set[str], bool]:
        if tokens[0] != "env":
            return tokens, set(), False
        index = 1
        isolated_environment = index < len(tokens) and tokens[index] == "-i"
        if isolated_environment:
            index += 1
        allowed = self._GIT_REQUIRED_ENVIRONMENT
        environment: set[str] = set()
        while index < len(tokens) and "=" in tokens[index]:
            if tokens[index] not in allowed:
                raise ValueError(
                    f"delegate environment override is not allowlisted: {tokens[index]}"
                )
            environment.add(tokens[index])
            index += 1
        return tokens[index:], environment, isolated_environment

    def _validate_simple_reader(self, tokens: list[str]) -> None:
        if tokens[0] == "rg" and any(
            token.startswith(("--hostname-bin", "--pre")) for token in tokens[1:]
        ):
            raise ValueError("ripgrep helper execution is not read-only")
        if tokens[0] == "jq" and any(token in {"-f", "--from-file"} for token in tokens[1:]):
            raise ValueError("jq program files are not needed for delegate inspection")

    def _validate_find(self, tokens: list[str]) -> None:
        forbidden = ("-delete", "-exec", "-fls", "-fprint", "-ok")
        if any(token.startswith(forbidden) for token in tokens[1:]):
            raise ValueError("find mutation or command execution is not read-only")

    def _validate_sed(self, tokens: list[str]) -> None:
        if any(token == "-i" or token.startswith("-i") for token in tokens[1:]):
            raise ValueError("sed in-place editing is not read-only")
        arguments = [token for token in tokens[1:] if token not in {"-E", "-n", "-nE"}]
        if not arguments:
            raise ValueError("sed inspection expression is required")
        expression = arguments[0]
        numeric = expression.replace(" ", "")
        is_numeric_print = numeric.endswith("p") and all(
            character in "0123456789,$+-p" for character in numeric
        )
        is_regex_print = re.fullmatch(r"/(?:\\.|[^/\\])+/p", expression) is not None
        if not (is_numeric_print or is_regex_print):
            raise ValueError(
                "sed delegate usage is limited to numeric print ranges or /pattern/ prints"
            )

    def _validate_git(self, tokens: list[str], relaxed: bool = False) -> None:
        """git 호출이 조회 subcommand allowlist 안에 있는지 검증합니다.

        Args:
            tokens: `git`으로 시작하는 tokenize된 command입니다.
            relaxed: 소유자 조회 계약에서 격리 config/flag 요구를 생략할지 여부입니다.

        Raises:
            ValueError: 조회 allowlist 밖 subcommand 또는 실행 유발 옵션이면 발생합니다.
        """
        index = 1
        safe_config: set[str] = set()
        while index < len(tokens) and tokens[index].startswith("-"):
            if tokens[index] == "-C" and index + 1 < len(tokens):
                index += 2
                continue
            if tokens[index] == "-c" and index + 1 < len(tokens):
                config = tokens[index + 1]
                if config not in self._GIT_REQUIRED_CONFIG:
                    raise ValueError(f"git config override is not read-only allowlisted: {config}")
                safe_config.add(config)
                index += 2
                continue
            raise ValueError(f"git global option is not read-only allowlisted: {tokens[index]}")
        if not relaxed and not self._GIT_REQUIRED_CONFIG.issubset(safe_config):
            raise ValueError("delegate git requires all execution-disabling config overrides")
        if index >= len(tokens):
            raise ValueError("git subcommand is required")
        subcommand = tokens[index]
        arguments = tokens[index + 1 :]
        mutation_options = ("--ext-diff", "--output", "--show-signature", "--textconv")
        if any(argument.startswith(mutation_options) or "%G" in argument for argument in arguments):
            raise ValueError("git output/external execution options are not read-only")
        if (
            not relaxed
            and subcommand in self._GIT_DIFF_SUBCOMMANDS
            and not {
                "--ignore-submodules=all",
                "--no-ext-diff",
                "--no-textconv",
            }.issubset(arguments)
        ):
            raise ValueError(
                "git diff-producing commands require helper- and submodule-disabling flags"
            )
        if not relaxed and subcommand == "status" and "--ignore-submodules=all" not in arguments:
            raise ValueError("git status requires --ignore-submodules=all")
        if subcommand == "ls-files" and "--recurse-submodules" in arguments:
            raise ValueError("git ls-files cannot recurse into submodule processes")
        if subcommand in self._GIT_READ_SUBCOMMANDS:
            return
        if (
            subcommand == "branch"
            and arguments
            and all(
                argument
                in {"--all", "--list", "--remotes", "--show-current", "-a", "-r", "-v", "-vv"}
                for argument in arguments
            )
        ):
            return
        if (
            subcommand == "worktree"
            and arguments
            and arguments[0] == "list"
            and all(
                argument in {"--porcelain", "-v", "--verbose", "-z"} for argument in arguments[1:]
            )
        ):
            return
        if subcommand == "remote" and arguments == ["-v"]:
            return
        if (
            subcommand == "remote"
            and len(arguments) >= 2
            and arguments[0] == "get-url"
            and all(argument in {"--all", "--push"} for argument in arguments[1:-1])
            and not arguments[-1].startswith("-")
        ):
            return
        if (
            subcommand == "config"
            and len(arguments) == 2
            and arguments[0] in {"--get", "--get-all"}
            and not arguments[1].startswith("-")
        ):
            return
        if (
            subcommand == "config"
            and arguments
            and arguments[0] == "--list"
            and all(
                argument in {"--includes", "--no-includes", "--show-names", "--show-origin", "-z"}
                for argument in arguments[1:]
            )
        ):
            return
        raise ValueError(f"git subcommand is not read-only allowlisted: {subcommand}")


def main() -> int:
    """CLI command를 검증하고 rejection reason을 stderr에 출력합니다.

    Returns:
        허용된 command이면 0입니다.
    """
    parser = argparse.ArgumentParser(description="Validate a read-only delegate command.")
    parser.add_argument("--command", required=True)
    parser.add_argument("--profile", default="delegate", choices=("delegate", "owner-root"))
    args = parser.parse_args()
    try:
        ReadOnlyDelegateCommandValidator(profile=args.profile).validate(args.command)
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
