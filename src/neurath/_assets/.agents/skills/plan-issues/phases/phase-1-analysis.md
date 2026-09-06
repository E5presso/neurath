# Phase 1: 문서와 코드 분석

질문을 시작하기 전에 repository context를 분석합니다.

## 필수 읽기

- `.neurath/project.json (documents 슬롯)`
- `.neurath/project.json (documents 슬롯)`
- `.neurath/project.json (documents 슬롯)`
- `.neurath/project.json (documents 슬롯)`
- `.neurath/project.json (documents 슬롯)`
- 기존 `docs/plans/`
- 사용자 요청이 지목한 code, test, harness 파일

## 절차

1. `rg --files`로 관련 파일을 확인합니다.
2. 사용자 용어를 `docs`, `apps`, `packages`, `e2e`, `deploy`,
   `.agents`에서 검색합니다.
3. `.agents/rules/domain-dictionary.md`에 따라 `.neurath/project.json (documents 슬롯)` Domain
   Dictionary lookup을 수행합니다.
4. 기존 용어, package boundary, 이전 결정을 식별합니다.
5. 문서와 코드가 사용자 표현과 충돌하는 지점을 기록합니다.

## 완료 evidence

- `grill_with_docs_source`
- `repo_evidence`
- `docs_evidence`
- `domain_dictionary_lookup`
- `language_conflicts`
