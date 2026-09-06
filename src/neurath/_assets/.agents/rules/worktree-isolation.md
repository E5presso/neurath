---
paths:
  - ".agents/worktrees/**"
  - ".codex/hooks/check-worktree-isolation.sh"
  - "scripts/agent_harness/worktree_*.py"
---

# Worktree Isolation

Worktree는 coding-agent session의 작업 기억이 아니라 여러 session이 함께 경쟁할 수 있는
shared resource입니다. 소유권의 정본은 repository control root 아래의
`WorktreeRegistry`이며, session state 경로나 현재 shell 위치로 owner를 추측하지 않습니다.

## 불변식

- Git common directory와 top-level에서 계산한 `worktree_id`가 resource identity입니다.
- 하나의 worktree에는 한 시점에 하나의 active `(session_id, actor_id)` owner만 존재합니다.
- Claim은 first-writer-wins이며, release와 handoff는 caller가 읽은 owner, lease epoch,
  fencing token 전체를 expected value로 제출하는 optimistic CAS입니다.
- 검증·직렬화·새 token 생성은 mutex 밖에서 수행합니다. Mutex 안에서는 current claim
  재조회, expected 비교, fsync, atomic replace 또는 unlink만 수행합니다.
- Handoff 뒤 이전 fencing token은 즉시 stale이며 과거 owner는 mutation할 수 없습니다.
- Retired actor는 claim, handoff, release authority를 갖지 않습니다.
- 조회는 ownership과 무관하게 항상 허용합니다. Owner가 아니거나 claim이 없어도 inspection을
  차단하지 않습니다.
- 구조화된 파일 수정은 claimed resource의 exact owner actor만 수행합니다.
- Shell·web·provider 등 저장소가 완전히 판정할 수 없는 도구는 호스트에 위임합니다
  (`DEFER_TO_HOST`). 이 결과는 저장소 권한 부여가 아니며 호스트의 승인을 대체하지 않습니다.
- Unclaimed worktree의 구조화된 파일 수정은 거부합니다. Runtime이 증명한 exact active actor가
  path-free `state_cli worktree claim`을 먼저 실행해야 하며, 이 typed transition만 atomic
  first-writer-wins claim을 생성합니다. Missing/foreign/retired actor는 claim할 수 없고,
  동시 claim의 loser는 canonical winner를 다시 읽어 owner mismatch로 거부됩니다.
- Canonical session state와 shared claim 파일은 tool로 직접 편집하지 않고 `StateHandle`과
  typed registry API로만 바꿉니다.

## Tool hook 판정

`.codex/hooks/check-worktree-isolation.sh`는 protocol adapter일 뿐이며 실제 정책은
`scripts.agent_harness.worktree_hook`이 소유합니다.

1. 구조화된 파일 수정은 literal target을 읽고, 나머지 도구는 state를 열지 않고 호스트에 위임합니다.
2. Target을 Git이 증명한 `worktree_id`로 정규화하고 runtime-owned identity로
   `StateHandle.attach`합니다. Workdir는 target 해석의 base입니다.
3. Target이 unclaimed이면 수정을 거부합니다. `state_cli worktree claim`만
   atomic first-writer-wins claim을 생성합니다.
4. `WorktreeRegistry.authorize`가 모든 target의 exact owner임을 확인할 때만
   수정을 허용합니다. 다른 session directory나 active workflow 목록은 scan하지 않습니다.

구조화된 수정의 literal target이 다른 repository나 증명되지 않은 worktree를 가리키면
거부합니다. Shell 문법·명령 효과·승인은 호스트가 판정하며 저장소 allowlist로 복제하지 않습니다.

PR close/merge와 protected default branch push처럼 되돌리기 어려운 external mutation의 사용자
승인 계약은 worktree ownership과 별도로 검사합니다. Worktree owner라는 사실은 publish 승인이
아닙니다.

## Agent DX

Skill과 agent는 path나 state file을 전달하지 않습니다. Runtime identity가 주입된 worktree에서
path-free CLI를 사용합니다.

```bash
python3 -m scripts.agent_harness.state_cli worktree claim
python3 -m scripts.agent_harness.state_cli worktree release
```

Handoff는 current `WorktreeClaim`을 읽은 orchestration service가 explicit next owner와 함께
수행합니다. 충돌은 숨기지 않고 typed lease conflict로 반환하여 상위 workflow가 최신 owner를
읽고 의도를 다시 판단하게 합니다.

## 검증

```bash
bash -n .codex/hooks/check-worktree-isolation.sh
uv run python -m scripts.agent_harness.verification_runner pytest --node scripts/agent_harness/tests/test_worktree_hook.py::WorktreeHookApplicationTest::test_host_managed_tools_require_neither_identity_nor_worktree_claim --node scripts/agent_harness/tests/test_worktree_registry.py::WorktreeRegistryAcceptanceTest::test_non_owner_read_only_access_is_allowed_while_mutation_is_denied
uv run ruff check scripts/agent_harness/worktree_hook.py scripts/agent_harness/worktree_registry.py
```
