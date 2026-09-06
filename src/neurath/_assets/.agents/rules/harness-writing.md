---
paths:
  - ".agents/**"
  - ".codex/**"
  - "scripts/**"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# Harness 작성

Harness file은 project diary가 아니라 behavior rule입니다.

## 일반 규칙만 추가

미래 case에서 agent behavior를 바꿀 때만 rule을 추가합니다. 한 incident 때문에
기억에 남는 예시는 피합니다.

## Clean-slate 문서성

Harness와 ticket template은 새 agent가 chat history 없이 읽어도 실행 방향을
오해하지 않게 써야 합니다. 필요한 context, source of truth, non-goal,
acceptance criteria, verification command는 명시하되, 오래된 세부사항이나
중복된 narrative를 쌓아 context rot을 만들지 않습니다.

## 다섯 가지 test

rule을 추가하거나 확장하기 전에 확인합니다.

1. 삭제: 이 줄이 없으면 agent가 실제로 실패할 가능성이 큰가?
2. 비추론: code나 docs가 이미 답할 수 있는가?
3. 중복: 이미 다른 곳에서 강제되는가?
4. 행동: 문구가 tone이 아니라 action을 바꾸는가?
5. 일반성: one-off case가 아니라 재사용 가능한 원칙인가?

하나라도 실패하면 줄이거나 넣지 않습니다.

## 검증 gate의 자리

Static harness enforcement는 skill이 아니라 commit 시점에 수행합니다.
`.pre-commit-config.yaml`이 executable verification SSOT이며, 새 검사는 여기에
추가합니다. 같은 검사를 실행하는 `/check` 류의 skill을 다시 만들지 않습니다.
Hook entrypoint는 `mise.toml`에 선언된 task를 실행합니다. 검사 단계와 tool 버전의
SSOT는 `mise.toml` 하나이며, CI도 `mise`를 설치해 같은 task를 부릅니다. 같은 task를
다른 곳에 다시 적으면 두 실행 경로가 갈라지므로, `mise`가 없는 환경에서는 대체
명령을 돌리지 않고 실패합니다. Root hook은 영향받은 uv package의 package-local
pre-commit config를 orchestration합니다.

## 산문과 게이트의 분업

Harness의 산문은 절대 규칙을 세우는 장치가 아니라 agent의 사고를 유도하는
장치입니다. 절대 규칙은 코드 게이트가 집행합니다.

이 분업에서 따라오는 판정 기준은 하나입니다. **코드 게이트는 기계가 확인할 수 있는
사실만 강제합니다.** 파일이 있는지, 형식이 맞는지, 명령이 통과했는지, 상한을
넘겼는지는 강제해도 됩니다. 반대로 agent가 붙인 분류나 해석에만 의존하는 판단은
강제 대상이 아닙니다. 그런 판단은 경고로 남기고, 무엇을 어떻게 정했는지는 agent가
근거와 함께 기록합니다.

해석 위에 강제를 얹으면 두 방향으로 오작동합니다. agent가 이름을 다르게 붙이면
조용히 지나가고, 넓게 붙이면 정상 경로가 막힙니다. 그런 게이트는 관문처럼 보이지만
관문이 아닙니다.

명료한 서술 표준의 의미 준수도 산문 하네스가 유도합니다. Gate는 canonical 표준의
위치와 version marker, always-on 예산, 중복 reminder 미배선처럼 기계가 확인할 수 있는
사실만 검사합니다. 문장의 자연스러움, 한 문장 한 판단, 사실과 추론의 의미상 분리는
점수화하거나 tool call을 차단하지 않습니다.

## Gate 변경 규율

enforcement gate(hook, checker, contract)는 자연어 규칙과 달리 코드로 차단·요구를
집행합니다. gate가 선언된 목적보다 넓게 집행되어 무관한 정상 동작까지 막는 표류가
반복적으로 관찰됐습니다(근거: `.neurath/project.json (documents 슬롯)`).
gate를 추가·수정할 때는 다음을 지킵니다.

- 목적과 비목표를 명시합니다. gate가 해결하는 문제(목적)와, 절대 차단·요구하면 안
  되는 것(비목표)을 함께 적습니다. 비목표는 디테일 수준으로 적습니다(예: "읽기,
  무관 세션, read-only 호출, incremental 커밋은 차단하지 않는다").
- 차단을 추가하거나 넓히는 변경에는 그 차단이 비목표를 침범하지 않음을 증명하는
  allow-test를 함께 추가하거나 갱신합니다. block-test만 쌓으면 과잉집행이 "의도된
  동작"으로 굳습니다.
- commit/PR 본문에 이 변경이 대상 gate의 어느 목적에 복무하는지, 집행 범위를
  넓히는지 좁히는지 진술합니다.
- Canonical process state guard는 임의 interpreter와 직접 mutation을 계속 차단하되,
  exact in-worktree path로 고정된 공식 실행 결과 검증기 또는 publisher가 state를
  read-back하는 정상 경로는 허용합니다. Allowlist 변경은 실제 공식 command를 실행하는
  회귀 테스트로 보호합니다.

Capability와 content는 다릅니다. Checker가 capability·connector·regression을
고정합니다. Mutation은 PreToolUse guard·allow-test로 막습니다.

## Runtime 대칭

Neurath harness는 Claude Code와 Codex 양쪽에서 같게 동작해야 합니다. Rule, skill,
hook script는 symlink로 한 소스를 공유하므로 자동으로 대칭이지만, hook을 event에
배선하는 파일은 runtime별로 갈라집니다. 한쪽에만 배선하면 다른 runtime에서 그
harness가 조용히 사라집니다.

Hook을 추가·제거·이동하면 두 배선 파일을 함께 고칩니다. 같은 script가 같은 event에
걸려 있어야 하며, 확인은 눈이 아니라 다음 검사가 합니다.

```bash
uv run python -m scripts.agent_harness.verification_runner harness-lint
```

이 검사는 공유 디렉터리가 symlink인지와 배선의 (event, script) 쌍이 양쪽에서 같은지를
비교합니다. Runtime별로 문법이 달라 명령 문자열은 다를 수 있고, 그 차이는 위반이
아닙니다.

## Edit discipline

이슈 처리 세션에서 harness file을 수정할 때는 대상 issue worktree에서 수행합니다.
격리 worktree에서 patch를 적용하기 전후로 root/worktree guard를 통과시켜야 합니다.
세션 CWD가 대상 worktree root임을 확신할 수 없으면
`.agents/skills/process-ticket/scripts/safe_worktree_apply_patch.sh <issue-number>`
wrapper를 사용합니다.

문서가 가리키는 repository 경로는 산문 규율이 아니라 lint가 실재를 검사합니다.
경로를 바꾸거나 파일을 옮기면 참조를 함께 고치고, glob·placeholder·아직 만들지 않은
승인된 자리는 그 검사의 비목표입니다.

Harness edit 후에는 다음을 실행합니다.

```bash
uv run python -m scripts.agent_harness.verification_runner harness-lint
git diff --check
```

script나 Python file을 건드렸으면 더 넓은 check를 실행합니다.

Package-local pre-commit entry는 workspace runner가 이미 해당 package directory를
working directory로 사용한다는 계약에서 실행 가능해야 합니다. Root에서 직접 실행하는
경로도 지원해야 하면 package path 존재 여부를 먼저 확인해 선택하고, package directory를
다시 root-relative path로 무조건 이동하지 않습니다. 회귀 테스트는 실제 entry를 package
working directory에서 실행해 이 계약을 검증합니다.

Type checker hook은 검사 대상 파일/디렉터리를 hook entrypoint에 중복 지정하지
않고 각 package의 `pyproject.toml` 설정을 SSOT로 둡니다. Hook은 runner option과
출력 형식만 지정합니다.

## Deterministic contract

skill에 ordered phase, terminal state, required report shape가 있으면
`.agents/skills/contracts.json`에 contract를 encode하고
`scripts/skill_harness` test로 보호합니다. phase order나 report format을 prose에만
의존하지 않습니다.

Composite skill은 추가로 다음을 지킵니다.

- contract에 `phase_files_required`를 설정합니다.
- 각 executable phase에 `phase_file`을 추가합니다.
- 모든 phase 또는 supporting Markdown file이 `SKILL.md`에서 도달 가능하게 합니다.
- tool call이 나타나면 `.agents/rules/tool-runtime-map.md`를 참조합니다.
- runtime-neutral tool action에는 `tool:<key>`를 사용합니다.
