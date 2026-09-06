# Phase 4: Intent Audit

구현 결과를 승인된 plan 또는 milestone intent와 대조해 audit합니다.

## 절차

1. milestone, parent issue, issue set에 `/audit-spec`를 실행합니다.
2. merged work, skipped work, failed work를 acceptance criteria와 비교합니다.
3. intent drift, glossary drift, missing ADR을 식별합니다.
4. 충분한 metadata가 있는 concrete gap에만 follow-up issue를 만듭니다.

## 통과 조건

product-intent gap을 final report에 숨기지 않습니다. follow-up issue로 보내거나
run을 blocked로 표시합니다.
