---
name: explain-code
description: 현재 checkout의 실제 source, test, config, spec과 ADR을 근거로 code, file, symbol, diff, request flow, data flow 또는 architecture를 사용자 수준에 맞춰 설명합니다. 사용자가 "이 코드 설명해 주세요", "어떻게 동작하나요?", "왜 이렇게 되어 있나요?", "walk me through"처럼 구현을 이해하려 할 때 반드시 사용합니다. 구현, bug fix, code review, refactor, impact analysis 또는 문서 생성이 주목적이면 사용하지 않습니다.
intent-class: source.explain
input-authority: repository-source
not-for: [source.review, change.impact-analyze, defect.investigate]
argument-hint: "<symbol | path[:line] | feature | diff> [brief|standard|deep|interactive] [plain|technical|maintainer]"
user-invocable: true
---

# Explain Code

현재 checkout을 source of truth로 삼아, 코드를 낭독하지 말고 역할, 실행 흐름,
계약과 설계 맥락을 설명합니다. 기본값은 `technical` audience와 `standard` depth입니다.

## 범위

- 설명은 read-only입니다. Source, test, config, docs, Graphify artifact, ticket과 Git
  history를 수정하지 않습니다.
- Read-only는 이 skill의 실행 경계입니다. 사용자가 mutation을 요청한 사실이나 권한을
  read-only 요청으로 재해석하지 말고, 주목적에 맞는 workflow로 정확히 넘깁니다.
- 기본 산출물은 현재 대화의 답변입니다. 사용자가 별도 artifact를 요청하지 않았다면
  tutorial, code comment, `README`, CodeTour 또는 분석 보고서를 만들지 않습니다.
- 요청의 주목적이 구현, bug fix, code review, refactor 또는 impact analysis이면 이
  skill로 설명을 대신하지 말고 해당 작업에 맞는 workflow를 선택합니다.
- 설명 중 결함 후보를 보더라도 review로 확장하지 않습니다. 사용자가 이해해야 하는
  실제 failure path, invariant 또는 gotcha만 근거와 함께 설명합니다.

## 요청 해석

대상은 symbol, `path[:line]`, feature나 concept, diff·commit·branch, request flow,
data flow 또는 architecture일 수 있습니다. 대상과 사용자가 알고 싶은 질문을 먼저
식별합니다. 답이 materially 달라질 때만 한 가지 상위 모호함을 질문하고, source에서
확인할 수 있는 사실은 직접 조사합니다.

사용자가 수준을 지정하지 않으면 표현과 맥락에서 추론합니다.

- `plain`: jargon을 풀어 쓰고 사용자 또는 시스템 효과부터 설명합니다. 비유는 실제로
  이해 부담을 줄일 때만 짧게 사용합니다.
- `technical`: 입력, 분기, dependency, side effect, 반환과 오류를 정확히 설명합니다.
- `maintainer`: boundary, caller·callee, invariant, trade-off와 안전한 변경 지점을 더합니다.

사용자가 깊이를 지정하지 않으면 `standard`를 사용합니다.

- `brief`: 역할과 핵심 흐름만 짧게 답합니다.
- `standard`: 역할, 대표 흐름, 중요한 계약과 근거가 있는 설계 맥락을 답합니다.
- `deep`: 관련 boundary, type, caller·callee, test·config, side effect와 failure path까지
  추적합니다.
- `interactive`: 먼저 유용한 최소 설명을 제공한 뒤, 의미 있는 구간마다 이해 확인이나
  다음 탐색 방향을 묻습니다. 사용자가 코드를 작성하거나 답을 맞히도록 강제하지 않습니다.

## Evidence workflow

1. 대상의 실제 source를 읽습니다. 이름, filename, README 또는 Graphify 결과만으로
   동작을 추정하지 않습니다.
2. 질문에 답하는 데 필요한 범위에서 import, type·interface, caller, callee, test,
   config를 따라갑니다. 단순 함수에 repository 전체 조사를 붙이지 않습니다.
3. Cross-layer feature는 대표 입력 하나를 entry point에서 validation, 핵심 분기,
   dependency, side effect, output 또는 error까지 끝까지 추적합니다.
4. 현재 동작은 source와 config에서 확인합니다. Test는 기대와 regression evidence이며,
   실행 중인 production behavior를 단독으로 증명하지 않습니다.
5. 제품·architecture 의도는 관련 spec과 ADR에서 확인합니다. README, 이름 또는 주석이
   구현과 다르면 `문서화된 의도`와 `관찰된 동작`을 분리합니다.
6. Historical why가 질문의 핵심일 때만 `git blame`과 관련 commit을 조사합니다. History가
   없거나 이유를 말하지 않으면 source 모양을 저자 의도로 바꾸지 않습니다.
7. Graphify는 넓은 codebase의 후보 경로를 찾는 navigation으로만 사용합니다. 답변의
   강한 주장은 원본 source, test, config, spec 또는 ADR을 다시 읽어 확인합니다.
8. 답변 직전에 인용 line이 현재 checkout과 맞는지 다시 확인합니다.

정적 판독으로 답할 수 있는 설명에는 test나 application을 실행하지 않습니다. 사용자가
runtime behavior를 명시적으로 물었고 정적 근거가 부족하면, 필요한 진단 범위와 이유를
먼저 밝히고 현재 repository의 검증 경계를 따릅니다.

## 근거 표현

중요한 non-trivial claim에는 현재 checkout의 정확한 `path:line` 근거를 붙입니다.
Runtime이 local file link를 지원하면 label은 짧은 `path:line`으로, target은 현재
checkout의 absolute path와 시작 line으로 만든 clickable Markdown link를 사용합니다.
경로는 설명을 대신하지 않으므로 먼저 의미를 말하고 바로 뒤에 근거를 붙입니다.

구체적인 validation, 분기, 상수 값, 호출, state change 또는 assertion을 설명할 때는 그
동작이나 값이 실제로 나타나는 행을 인용합니다. 함수·class·test의 선언 시작행이나 인접행은
그 symbol의 위치만 보여 줄 뿐, 내부 동작 claim의 근거를 대신하지 않습니다.
Immutability, optionality, interface method, parameter나 return type 같은 type·contract
속성은 그 속성을 encode한 decorator, annotation 또는 signature 행을 인용합니다.
한 문장이나 문단의 claim을 직접 뒷받침하는 최소한의 line만 인용합니다. 같은 line link를
반복하거나 모든 구현행을 나열해 설명의 흐름을 가리지 않습니다.

특히 구현 이유나 불일치가 있을 때 다음 범주를 섞지 않습니다.

- `관찰된 동작`: 현재 source, config와 직접 확인한 흐름
- `문서화된 의도`: spec, ADR, 명시적 문서 또는 history가 말하는 이유
- `추론`: source 구조에서 도출했지만 명시적으로 기록되지 않은 해석
- `확인 불가`: 현재 checkout의 근거로는 답할 수 없는 내용

추론을 제공하면 어떤 source 사실에서 도출했는지 함께 말합니다. 근거가 없으면 plausible한
설계 이유, trade-off, 취약점 또는 저자 의도를 발명하지 않습니다.

## 답변 구성

질문과 depth에 필요한 section만 사용합니다. `standard`의 기본 골격은 다음과 같습니다.

1. `한눈에 보기`: 이 코드가 맡은 역할과 최종 효과
2. `실제 흐름`: entry부터 핵심 분기, side effect, 반환 또는 오류까지의 순서
3. `중요한 계약`: input·output, state change, invariant와 caller 전제
4. `왜 이렇게 되어 있나`: 문서화된 이유, 명시된 추론 또는 확인 불가
5. `주의할 점`: 이해에 직접 필요한 evidence-backed gotcha가 있을 때만 추가

`brief`에서는 불필요한 heading을 생략합니다. `deep`에서는 관련 boundary와 수정 전에 볼
위치를 더할 수 있지만, 사용자가 요청하지 않은 변경안이나 review finding을 만들지 않습니다.

세 개 이상의 component나 단계 관계가 산문보다 명확해질 때만 작은 Mermaid 또는 ASCII
diagram을 사용합니다. Diagram 하나에는 질문 하나와 abstraction level 하나만 담고,
source에서 확인하지 않은 node나 edge를 추가하지 않습니다.

답변은 사용자의 질문을 직접 해결한 뒤 끝냅니다. 더 깊게 볼 수 있는 선택지는 실제로
유용할 때만 한 문장으로 제안합니다.
