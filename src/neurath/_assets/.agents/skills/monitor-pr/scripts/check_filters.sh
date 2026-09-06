#!/usr/bin/env bash
# Regression checks for monitor-pr comment filtering. This script stubs gh so it
# can run without mutating GitHub state.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/bin"
cat > "$tmp_dir/bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" != "api" ]; then
  echo "unsupported gh invocation: $*" >&2
  exit 1
fi

path="${2:-}"
case "$path" in
  graphql)
    if [ "${FAKE_CASE:-codecov-only}" = "unresolved-thread" ]; then
      cat <<'JSON'
{
  "data": {
    "repository": {
      "pullRequest": {
        "reviewThreads": {
          "nodes": [
            {
              "id": "PRRT_1",
              "isResolved": false,
              "isOutdated": false,
              "comments": {
                "nodes": [
                  {
                    "id": "PRRC_1",
                    "author": {"login": "example-maintainer"},
                    "body": "아직 resolve되지 않은 thread입니다.",
                    "path": "file.py",
                    "line": 7,
                    "originalLine": 7,
                    "url": "https://example.test/thread"
                  }
                ]
              }
            }
          ]
        }
      }
    }
  }
}
JSON
    else
      cat <<'JSON'
{
  "data": {
    "repository": {
      "pullRequest": {
        "reviewThreads": {
          "nodes": []
        }
      }
    }
  }
}
JSON
    fi
    ;;
  repos/*/pulls/*/comments)
    if [ "${FAKE_CASE:-codecov-only}" = "actionable" ] || [ "${FAKE_CASE:-codecov-only}" = "handled-actionable" ]; then
      cat <<'JSON'
[
  {
    "id": 201,
    "user": {"login": "chatgpt-codex-connector[bot]"},
    "body": "**P1** actionable review feedback",
    "path": "file.py",
    "original_line": 7,
    "created_at": "2026-05-03T12:10:00Z",
    "updated_at": "2026-05-03T12:10:00Z"
  }
]
JSON
    else
      printf '[]\n'
    fi
    ;;
  repos/*/issues/*/comments)
    if [ "${FAKE_CASE:-codecov-only}" = "handled-actionable" ]; then
      extra_handled_marker=', {
    "id": 105,
    "user": {"login": "example-maintainer"},
    "body": "인라인 코멘트 처리 완료.\n\n<!-- claude-agent-reply to=201 -->",
    "created_at": "2026-05-03T12:06:00Z",
    "updated_at": "2026-05-03T12:06:00Z"
  }'
    else
      extra_handled_marker=''
    fi
    cat <<'JSON'
[
  {
    "id": 100,
    "user": {"login": "codecov[bot]"},
    "body": "## [Codecov](https://app.codecov.io/example)\n\nAll modified lines are covered.",
    "created_at": "2026-05-03T12:00:00Z",
    "updated_at": "2026-05-03T12:05:00Z"
  },
  {
    "id": 101,
    "user": {"login": "example-maintainer"},
    "body": "Codecov checked.\n\n<!-- claude-agent-reply to=100 -->",
    "created_at": "2026-05-03T12:01:00Z",
    "updated_at": "2026-05-03T12:01:00Z"
  },
  {
    "id": 102,
    "user": {"login": "example-maintainer"},
    "body": "Codecov checked again.\n\n<!-- claude-agent-reply to=100 -->",
    "created_at": "2026-05-03T12:02:00Z",
    "updated_at": "2026-05-03T12:02:00Z"
  },
  {
    "id": 103,
    "user": {"login": "example-maintainer"},
    "body": "## AI 리뷰 결과: 자동 승인 가능\n\n<!-- ai-review verdict=AUTO_APPROVE head=abc123 -->",
    "created_at": "2026-05-03T12:03:00Z",
    "updated_at": "2026-05-03T12:03:00Z"
  },
  {
    "id": 106,
    "user": {"login": "example-maintainer"},
    "body": "## AI Review Verdict: AUTO_APPROVE\n\n새 head `abc123` 기준으로 blocking defect를 찾지 못했습니다.",
    "created_at": "2026-05-03T12:04:30Z",
    "updated_at": "2026-05-03T12:04:30Z"
  },
  {
    "id": 107,
    "user": {"login": "example-maintainer"},
    "body": "AI review 결과: AUTO_APPROVE\n\n한국어 PR review 요약입니다.",
    "created_at": "2026-05-03T12:04:45Z",
    "updated_at": "2026-05-03T12:04:45Z"
  },
  {
    "id": 104,
    "user": {"login": "example-maintainer"},
    "body": "처리 완료 표시입니다.\n\n<!-- claude-agent-reply to=103 -->",
    "created_at": "2026-05-03T12:04:00Z",
    "updated_at": "2026-05-03T12:04:00Z"
  }
JSON
    printf '%s\n' "$extra_handled_marker"
    cat <<'JSON'
]
JSON
    ;;
  repos/*/pulls/*/reviews)
    cat <<'JSON'
[
  {
    "id": 301,
    "user": {"login": "github-actions[bot]"},
    "body": "ai-review status success verified for abc123.\n\n- status creator: @example-maintainer",
    "state": "DISMISSED",
    "submitted_at": "2026-05-03T12:05:00Z"
  }
]
JSON
    ;;
  *)
    echo "unsupported gh api path: $path" >&2
    exit 1
    ;;
esac
SH
chmod +x "$tmp_dir/bin/gh"

run_collect() {
  PATH="$tmp_dir/bin:$PATH" REPO=example/project PR_NUMBER=1 \
    bash "$script_dir/collect_comments.sh"
}

# Verifies informational bot reports and agent signal comments do not become actionable PR work.
codecov_only="$(run_collect)"
grep -q '^TOTAL=0$' <<<"$codecov_only"

# Verifies stale-handled refresh does not make non-actionable bot noise actionable.
stale_codecov="$(PATH="$tmp_dir/bin:$PATH" REPO=example/project PR_NUMBER=1 \
  STALE_HANDLED_IDS=100 bash "$script_dir/collect_comments.sh")"
grep -q '^TOTAL=0$' <<<"$stale_codecov"

# Verifies a real unhandled inline review comment is still collected for triage.
actionable="$(FAKE_CASE=actionable run_collect)"
grep -q '^TOTAL=1$' <<<"$actionable"
grep -q 'chatgpt-codex-connector\[bot\]' <<<"$actionable"

# Verifies a marker reply attached to an inline review comment suppresses only that handled target.
handled_actionable="$(FAKE_CASE=handled-actionable run_collect)"
grep -q '^TOTAL=0$' <<<"$handled_actionable"
grep -q '^UNRESOLVED_THREADS_COUNT=0$' <<<"$handled_actionable"

# Verifies an in-place update can intentionally invalidate the handled marker and resurface the target.
stale_actionable="$(FAKE_CASE=handled-actionable STALE_HANDLED_IDS=201 run_collect)"
grep -q '^TOTAL=1$' <<<"$stale_actionable"
grep -q 'chatgpt-codex-connector\[bot\]' <<<"$stale_actionable"

# Verifies unresolved GitHub review threads remain visible even when comment reply markers exist.
unresolved_thread="$(FAKE_CASE=unresolved-thread run_collect)"
grep -q '^TOTAL=0$' <<<"$unresolved_thread"
grep -q '^UNRESOLVED_THREADS_COUNT=1$' <<<"$unresolved_thread"
grep -q 'UNRESOLVED_THREADS_DATA=' <<<"$unresolved_thread"

echo "monitor-pr filter checks passed"
