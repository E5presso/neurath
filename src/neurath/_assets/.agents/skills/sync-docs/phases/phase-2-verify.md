# Phase 2: 문서 검증

draft documentation을 Writer와 다른 context 또는 sub-agent에서 fact-check합니다.
같은 context가 자기 산출물을 검증하지 않습니다.

## Verifier Posture

Verifier는 Writer report를 신뢰하지 않습니다. 변경된 문서를 직접 읽고, code, test,
plan, ADR, package metadata, deployment manifest, harness file에서 사실을 확인합니다.
확인하지 못한 주장은 `미확인`으로 보고합니다.

## 입력

- 변경된 문서 file path 목록
- source evidence 목록: commit SHA, changed files, plan/ADR/context path
- code root와 package/app/service root
- `.neurath/project.json (documents 슬롯)`
- 관련 `.agents/rules/*.md`

## 10항목 Fact-Check

1. 파일 경로: 문서에 언급된 path가 실제 존재하는가
2. class/function/type/DTO 이름: 실제 정의와 일치하는가
3. import 또는 dependency 관계: 코드와 package metadata에 맞는가
4. API endpoint, event, schema, database object: 실제 contract와 일치하는가
5. type/signature: parameter, return type, serialized shape가 맞는가
6. dependency/runtime version: `pyproject.toml`, `mise.toml`, lockfile과 맞는가
7. 누락: 코드나 plan에 존재하는 중요한 aggregate, port, endpoint, glossary term이 빠졌는가
8. 유령 항목: 삭제됐거나 아직 구현되지 않은 feature를 실제처럼 설명하는가
9. diagram/format: Mermaid, table, heading, frontmatter 또는 metadata가 깨지지 않았는가
10. Domain Dictionary: public/internal term, Korean/English term, UI/code naming이 DD와 맞는가

## 필수 판정

각 문서마다 `통과`, `실패`, `미확인` 중 하나를 기록합니다.

- Critical: 문서가 거짓 behavior, 존재하지 않는 API/code, 승인되지 않은 product
  behavior, 깨진 command를 사실처럼 말함
- Warning: 표현 불명확, DD drift, 포맷/가독성 문제, source metadata 누락 또는 약함

Critical이 하나라도 있으면 Phase 3 reconcile 전에 수정해야 합니다. Warning은
reconcile에서 수용/반론/보류를 결정합니다.

## 보고 형식

```markdown
## Verify Report

### 검증 결과
| 문서 | 통과 | 실패 | 미확인 |
|------|------|------|--------|

### Critical
- `{file}:{line}` — {문제} / evidence: {확인한 source}

### Warning
- `{file}:{line}` — {문제} / evidence: {확인한 source}

### Pass
- {문서 목록}
```

## 완료 evidence

- `verifier_report`
- `source_fact_check`
- `frontmatter_or_metadata_check`
- `critical_warning_findings`
- `writer_independence_check`
- `ten_point_fact_check`
- `critical_warning_report`
