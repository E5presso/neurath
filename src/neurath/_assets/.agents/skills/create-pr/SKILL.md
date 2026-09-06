---
name: create-pr
description: remote가 있으면 현재 branch를 push하고 PR을 생성합니다.
intent-class: pull-request.create
input-authority: repository-git-state
not-for: [pull-request.review, session.finish]
argument-hint: "<PR intent or issue number> [--acceptance-file PATH | --acceptance-missing]"
user-invocable: true
---

# Create PR

## 결정적 phase 실행

Operational phase는 `uv run python -m scripts.skill_harness.phase_runner` 실행 결과를 잇습니다.
`current`는 recovery 전용이고 마지막 `complete --terminal-state`가 terminal CAS를 닫습니다.

## Tool runtime 호환성

`.agents/rules/tool-runtime-map.md`를 사용합니다. 모든 tool action은 Claude Code와
Codex에서 이 map을 통해 변환합니다.

## GitHub Metadata 언어

GitHub metadata는 대상 프로젝트가 정한 언어와 형식으로 작성합니다.
제목·본문·commit subject·issue 연결 규칙은 대상 저장소의 템플릿을 따릅니다.
게시 전후 실제 metadata read-back에 `scripts.skill_harness.github_metadata_language`를
실행하고 `policy_passed=true`를 확인합니다. 언어와 prefix는 `.neurath/project.json`의
metadata 설정에서 명시한 경우에만 요구합니다. `commit_subject`에는
`git log -1 --format=%s`의 실제 결과를 전달합니다.

1. `git status --short --branch` 확인.
2. branch remote 확인. 필요하면 의도적으로 설정합니다.
3. push 후 local `HEAD`가 remote에 도달했는지 확인.
4. acceptance handoff를 준비합니다.
   - `--acceptance-file PATH`가 있으면 해당 파일 내용을 PR body의
     인수 기준 section에 그대로 포함합니다.
   - `--acceptance-missing`이면 `acceptance_check: missing`과 reason을 PR body에
     포함합니다.
   - Phase 4.5에서 `PASS` 또는 `partial`을 보고했는데 acceptance file도 missing
     marker도 없으면 PR을 생성하지 않습니다.
5. 즉시 PR을 생성합니다. draft 여부는 사용자 요청과 대상 저장소의 관례를 따릅니다. PR title은
   `<대상 프로젝트의 commit 또는 PR 제목 형식>` 형식으로, body는 대상 프로젝트의 언어로
   작성하고, 본문에는 다음을 포함합니다.
   - 목적
   - 구현 요약
   - 가능한 경우 연결된 GitHub Issue
   - 인수 기준 또는 acceptance handoff
   - 검증
   - 위험
   - linked plan artifact
6. PR metadata를 설정합니다.
   - assignee: 기본은 `@me` 또는 source issue assignee입니다.
   - labels: issue/template/source plan에서 도출한 label을 적용합니다.
   - reviewer: repository convention이 있으면 요청합니다.
7. PR 다시 읽기. URL, branch, base branch, body, linked issue, assignee, labels,
   reviewer request, acceptance handoff를 검증합니다. assignee 또는 required label
   read-back이 비어 있으면 monitor phase로 넘어가지 않습니다.

remote가 없으면 PR 생성이 blocked됐다고 보고하고 local state를 유지합니다.
