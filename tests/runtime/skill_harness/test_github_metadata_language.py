"""test github metadata language 관련 타입과 실행 흐름을 정의합니다."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.skill_harness.github_metadata_language import GitHubMetadataLanguageCommand


class GitHubMetadataLanguageCommandTest(TestCase):
    """skill contract와 phase runner enforcement 회귀 시나리오를 unittest fixture로 고정합니다."""

    def test_accepts_korean_title_and_body(self) -> None:
        """skill contract와 phase runner enforcement의 accepts korean title and body 회귀 조건을 검증합니다."""
        with TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "pr.json"
            input_path.write_text(
                json.dumps(
                    {
                        "title": "PF-02B AgentActionRecord 계약 구현",
                        "body": "## 목적\nNeurath 행동 기록 계약을 구현합니다.\n\n## 검증\n테스트 통과.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = GitHubMetadataLanguageCommand().run([
                    "--input-json",
                    str(input_path),
                ])

        self.assertEqual(0, exit_code)
        self.assertIn("korean=true", output.getvalue())
        self.assertIn("forbidden_english_headings=0", output.getvalue())

    def test_requires_pr_title_issue_prefix_when_requested(self) -> None:
        """skill contract와 phase runner enforcement의 requires pr title issue prefix when requested 회귀 조건을 검증합니다."""
        with TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "pr.json"
            input_path.write_text(
                json.dumps(
                    {
                        "title": "feat(neurath): [#32] 행동 기록 계약 구현",
                        "body": "## 목적\nNeurath 행동 기록 계약을 구현합니다.\n\n## 검증\n테스트 통과.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = GitHubMetadataLanguageCommand().run([
                    "--input-json",
                    str(input_path),
                    "--require-title-issue-prefix",
                    "--expected-issue-number",
                    "32",
                ])

        self.assertEqual(0, exit_code)
        self.assertIn("title_issue_prefix=true", output.getvalue())
        self.assertIn("title_issue_number_matches=true", output.getvalue())

    def test_rejects_pr_title_with_different_issue_number(self) -> None:
        """요청한 issue 번호와 다른 PR title prefix를 거부합니다."""
        with TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "pr.json"
            input_path.write_text(
                json.dumps(
                    {
                        "title": "feat(neurath): [#999] 행동 기록 계약 구현",
                        "body": "## 목적\nNeurath 행동 기록 계약을 구현합니다.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = GitHubMetadataLanguageCommand().run([
                    "--input-json",
                    str(input_path),
                    "--require-title-issue-prefix",
                    "--expected-issue-number",
                    "32",
                ])

        self.assertEqual(1, exit_code)
        self.assertIn("title_issue_prefix=true", output.getvalue())
        self.assertIn("title_issue_number_matches=false", output.getvalue())

    def test_requires_matching_commit_subject_issue_prefix(self) -> None:
        """commit subject도 요청한 issue 번호 prefix를 가져야 합니다."""
        with TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "publication.json"
            input_path.write_text(
                json.dumps(
                    {
                        "title": "feat(neurath): [#32] 행동 기록 계약 구현",
                        "body": "## 목적\nNeurath 행동 기록 계약을 구현합니다.",
                        "commit_subject": "feat(neurath): [#32] 행동 기록 계약 구현",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = GitHubMetadataLanguageCommand().run([
                    "--input-json",
                    str(input_path),
                    "--require-title-issue-prefix",
                    "--require-commit-subject-issue-prefix",
                    "--expected-issue-number",
                    "32",
                ])

        self.assertEqual(0, exit_code)
        self.assertIn("commit_subject_issue_prefix=true", output.getvalue())
        self.assertIn("commit_subject_issue_number_matches=true", output.getvalue())

    def test_rejects_commit_subject_with_different_issue_number(self) -> None:
        """다른 issue 번호를 가리키는 commit subject를 거부합니다."""
        with TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "publication.json"
            input_path.write_text(
                json.dumps(
                    {
                        "title": "feat(neurath): [#32] 행동 기록 계약 구현",
                        "body": "## 목적\nNeurath 행동 기록 계약을 구현합니다.",
                        "commit_subject": "feat(neurath): [#999] 행동 기록 계약 구현",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = GitHubMetadataLanguageCommand().run([
                    "--input-json",
                    str(input_path),
                    "--require-title-issue-prefix",
                    "--require-commit-subject-issue-prefix",
                    "--expected-issue-number",
                    "32",
                ])

        self.assertEqual(1, exit_code)
        self.assertIn("commit_subject_issue_prefix=true", output.getvalue())
        self.assertIn("commit_subject_issue_number_matches=false", output.getvalue())

    def test_rejects_prefix_requirements_without_expected_issue_number(self) -> None:
        """issue 번호 일치 검증은 expected issue number 없이는 성공하지 않습니다."""
        with TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "publication.json"
            input_path.write_text(
                json.dumps(
                    {
                        "title": "feat(neurath): [#999] 행동 기록 계약 구현",
                        "body": "## 목적\nNeurath 행동 기록 계약을 구현합니다.",
                        "commit_subject": "feat(neurath): [#999] 행동 기록 계약 구현",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = GitHubMetadataLanguageCommand().run([
                    "--input-json",
                    str(input_path),
                    "--require-title-issue-prefix",
                    "--require-commit-subject-issue-prefix",
                ])

        self.assertEqual(1, exit_code)
        self.assertIn("title_issue_number_matches=false", output.getvalue())
        self.assertIn("commit_subject_issue_number_matches=false", output.getvalue())

    def test_rejects_pr_title_without_issue_prefix_when_requested(self) -> None:
        """skill contract와 phase runner enforcement의 rejects pr title without issue prefix when requested 회귀 조건을 검증합니다."""
        with TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "pr.json"
            input_path.write_text(
                json.dumps(
                    {
                        "title": "feat(neurath): 행동 기록 계약 구현",
                        "body": "## 목적\nNeurath 행동 기록 계약을 구현합니다.\n\n## 검증\n테스트 통과.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = GitHubMetadataLanguageCommand().run([
                    "--input-json",
                    str(input_path),
                    "--require-title-issue-prefix",
                ])

        self.assertEqual(1, exit_code)
        self.assertIn("korean=true", output.getvalue())
        self.assertIn("title_issue_prefix=false", output.getvalue())

    def test_accepts_english_without_project_language_policy(self) -> None:
        """skill contract와 phase runner enforcement의 rejects english title and body headings 회귀 조건을 검증합니다."""
        with TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "pr.json"
            input_path.write_text(
                json.dumps(
                    {
                        "title": "Add agent action record contract",
                        "body": (
                            "## Summary\nAdd action record support.\n\n## Verification\nTests pass."
                        ),
                    },
                ),
                encoding="utf-8",
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = GitHubMetadataLanguageCommand().run([
                    "--input-json",
                    str(input_path),
                ])

        self.assertEqual(0, exit_code)
        self.assertIn("korean=false", output.getvalue())
        self.assertIn("title_korean=false", output.getvalue())
        self.assertIn("body_korean=false", output.getvalue())
        self.assertIn("forbidden_english_headings=2", output.getvalue())
