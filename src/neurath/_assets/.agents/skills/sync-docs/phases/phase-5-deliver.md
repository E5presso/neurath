# Phase 5: 검증된 변경 전달

필요할 때 documentation change를 검증하고 publish합니다.

## 절차

1. 관련 docs 또는 harness verification을 실행합니다.
2. docs change가 넓으면 `uv run python -m scripts.agent_harness.verification_runner pre-commit`을 실행합니다.
3. workflow가 요청한 경우에만 commit 또는 PR을 만듭니다.
4. final terminal state를 보고합니다.

## 통과 조건

검증하지 않은 docs edit를 sync 완료로 주장하지 않습니다.
