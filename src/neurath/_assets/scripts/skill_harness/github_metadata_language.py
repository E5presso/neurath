"""github metadata language 관련 타입과 실행 흐름을 정의합니다."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_ENGLISH_HEADINGS = (
    "Summary",
    "Acceptance Criteria",
    "Acceptance Handoff",
    "Verification",
    "Gaps",
    "Risk",
    "Risks",
    "Purpose",
)
HANGUL_PATTERN = re.compile(r"[가-힣]")
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
TITLE_ISSUE_PREFIX_PATTERN = re.compile(r"^[^:]+:\s+\[#(?P<issue_number>\d+)\]\s+\S")


@dataclass(frozen=True, slots=True)
class GitHubMetadataLanguageAudit:
    """git hub metadata language audit 관련 설정과 검증 조건을 함께 표현합니다."""

    title_korean: bool
    """title korean 값을 보관합니다."""
    body_korean: bool
    """body korean 값을 보관합니다."""
    forbidden_english_headings: int
    """forbidden english headings 값을 보관합니다."""
    title_issue_prefix: bool
    """title issue prefix 값을 보관합니다."""
    title_issue_number_matches: bool
    """title issue number matches 값을 보관합니다."""
    commit_subject_issue_prefix: bool
    """commit subject issue prefix 값을 보관합니다."""
    commit_subject_issue_number_matches: bool
    """commit subject issue number matches 값을 보관합니다."""

    language_policy: str = "any"
    require_title_prefix: bool = False
    require_commit_prefix: bool = False

    @property
    def korean(self) -> bool:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Returns:
            korean 처리 결과입니다."""
        return self.title_korean and self.body_korean and self.forbidden_english_headings == 0

    def evidence(self) -> str:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Returns:
            evidence 처리 결과입니다."""
        return (
            "github_metadata_language: "
            "validator=scripts.skill_harness.github_metadata_language "
            f"policy_passed={str(self.passes(require_title_issue_prefix=self.require_title_prefix, require_commit_subject_issue_prefix=self.require_commit_prefix)).lower()} "
            f"language_policy={self.language_policy} "
            f"korean={str(self.korean).lower()} "
            f"title_korean={str(self.title_korean).lower()} "
            f"body_korean={str(self.body_korean).lower()} "
            f"forbidden_english_headings={self.forbidden_english_headings} "
            f"title_issue_prefix={str(self.title_issue_prefix).lower()} "
            f"title_issue_number_matches={str(self.title_issue_number_matches).lower()} "
            f"commit_subject_issue_prefix={str(self.commit_subject_issue_prefix).lower()} "
            "commit_subject_issue_number_matches="
            f"{str(self.commit_subject_issue_number_matches).lower()}"
        )

    def passes(
        self,
        *,
        require_title_issue_prefix: bool,
        require_commit_subject_issue_prefix: bool,
    ) -> bool:
        """검증 옵션을 반영해 metadata audit 성공 여부를 반환합니다.

        Args:
            require_title_issue_prefix: PR title issue prefix를 요구할지 여부입니다.
            require_commit_subject_issue_prefix: commit subject issue prefix를 요구할지 여부입니다.

        Returns:
            passes 처리 결과입니다."""
        title_passes = not require_title_issue_prefix or (
            self.title_issue_prefix and self.title_issue_number_matches
        )
        commit_subject_passes = not require_commit_subject_issue_prefix or (
            self.commit_subject_issue_prefix and self.commit_subject_issue_number_matches
        )
        return (self.language_policy == "any" or self.korean) and title_passes and commit_subject_passes


class GitHubMetadataLanguageAuditor:
    """git hub metadata language auditor 관련 설정과 검증 조건을 함께 표현합니다."""

    def audit(
        self,
        title: str,
        body: str,
        *,
        commit_subject: str = "",
        expected_issue_number: int | None = None,
        language_policy: str = "any",
        require_title_prefix: bool = False,
        require_commit_prefix: bool = False,
    ) -> GitHubMetadataLanguageAudit:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            title: 호출자가 넘긴 title 값입니다.
            body: 호출자가 넘긴 body 값입니다.
            commit_subject: publication commit의 subject입니다.
            expected_issue_number: title과 commit subject가 참조해야 하는 issue 번호입니다.

        Returns:
            audit 처리 결과입니다."""
        if language_policy not in {"any", "ko"}:
            raise ValueError("metadata.language must be any or ko")
        title_match = TITLE_ISSUE_PREFIX_PATTERN.search(title)
        commit_subject_match = TITLE_ISSUE_PREFIX_PATTERN.search(commit_subject)
        return GitHubMetadataLanguageAudit(
            language_policy=language_policy,
            require_title_prefix=require_title_prefix,
            require_commit_prefix=require_commit_prefix,
            title_korean=self._has_hangul(title),
            body_korean=self._has_hangul(body),
            forbidden_english_headings=self._forbidden_english_heading_count(body),
            title_issue_prefix=title_match is not None,
            title_issue_number_matches=self._issue_number_matches(
                title_match,
                expected_issue_number,
            ),
            commit_subject_issue_prefix=commit_subject_match is not None,
            commit_subject_issue_number_matches=self._issue_number_matches(
                commit_subject_match,
                expected_issue_number,
            ),
        )

    def _has_hangul(self, text: str) -> bool:
        return HANGUL_PATTERN.search(text) is not None

    def _forbidden_english_heading_count(self, body: str) -> int:
        count = 0
        for match in MARKDOWN_HEADING_PATTERN.finditer(body):
            heading = match.group(1).strip()
            if heading in FORBIDDEN_ENGLISH_HEADINGS:
                count += 1
        return count

    def _issue_number_matches(
        self,
        match: re.Match[str] | None,
        expected_issue_number: int | None,
    ) -> bool:
        if match is None:
            return False
        if expected_issue_number is None:
            return False
        return int(match.group("issue_number")) == expected_issue_number


class GitHubMetadataLanguageCommand:
    """git hub metadata language command 관련 설정과 검증 조건을 함께 표현합니다."""

    def run(self, raw_args: list[str] | None = None) -> int:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Args:
            raw_args: 호출자가 넘긴 raw args 값입니다.

        Returns:
            run 처리 결과입니다."""
        parser = self._parser()
        args = parser.parse_args(raw_args)
        payload = self._payload(args.input_json)
        title = self._field(payload, args.title_field)
        body = self._field(payload, args.body_field)
        commit_subject = self._optional_field(payload, args.commit_subject_field)
        settings_path = Path.cwd() / ".neurath/project.json"
        settings = json.loads(settings_path.read_text()).get("metadata", {}) if settings_path.is_file() else {}
        language = settings.get("language", "any")
        require_title = args.require_title_issue_prefix or settings.get("require_title_issue_prefix", False)
        require_commit = args.require_commit_subject_issue_prefix or settings.get("require_commit_subject_issue_prefix", False)
        if type(require_title) is not bool or type(require_commit) is not bool:
            raise ValueError("metadata issue requirements must be booleans")
        audit = GitHubMetadataLanguageAuditor().audit(
            title=title,
            body=body,
            commit_subject=commit_subject,
            expected_issue_number=args.expected_issue_number,
            language_policy=language,
            require_title_prefix=require_title,
            require_commit_prefix=require_commit,
        )
        print(audit.evidence())
        return (
            0
            if audit.passes(
                require_title_issue_prefix=require_title,
                require_commit_subject_issue_prefix=require_commit,
            )
            else 1
        )

    def _payload(self, path: Path) -> dict[str, object]:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("GitHub metadata input must be a JSON object")
        return parsed

    def _field(self, payload: dict[str, object], field_name: str) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        return value

    def _optional_field(self, payload: dict[str, object], field_name: str) -> str:
        value = payload.get(field_name, "")
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        return value

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Audit GitHub Issue/PR title and body language for Neurath metadata.",
        )
        parser.add_argument("--input-json", required=True, type=Path)
        parser.add_argument("--title-field", default="title")
        parser.add_argument("--body-field", default="body")
        parser.add_argument("--commit-subject-field", default="commit_subject")
        parser.add_argument("--require-title-issue-prefix", action="store_true")
        parser.add_argument("--require-commit-subject-issue-prefix", action="store_true")
        parser.add_argument("--expected-issue-number", type=int)
        return parser


def main() -> int:
    """CLI entrypoint가 인자를 해석하고 process exit code를 반환합니다.

    Returns:
        main 처리 결과입니다."""
    return GitHubMetadataLanguageCommand().run()


if __name__ == "__main__":
    raise SystemExit(main())
