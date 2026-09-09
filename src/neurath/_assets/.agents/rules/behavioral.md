# 행동 규칙

## 코딩 전에 생각하기

- 요청이 여러 의미로 갈라질 수 있으면 branch를 명시합니다.
- 같은 의도를 더 단순한 경로로 만족할 수 있으면 그 경로를 선택합니다.
- 파일이나 command로 답을 찾을 수 있으면 먼저 확인합니다.
- 새 domain noun, action verb, class name, public method name을 만들기 전에
  `.agents/rules/domain-dictionary.md`의 DD lookup을 수행합니다.

## 단순성

- 실제 필요가 생기기 전에는 configurability, wrapper, extension point를
  추가하지 않습니다.
- 이름 자체가 중요한 의도를 전달하지 않는 one-use helper는 inline으로 둡니다.
- happy path가 더 명확해지면 early return으로 nested branch를 줄입니다.
- 범위가 정해진 작업을 하면서 무관한 cleanup을 끼워 넣지 않습니다.

설계를 논의할 때는 가장 단순한 형태를 먼저 적고, 그 형태가 실제로 무엇을 못 막는지
구체적으로 말합니다. 못 막는 것이 실제 위험일 때만 장치를 더합니다. 고민이 길어질수록
예외 경로와 중간 상태를 늘리는 방향으로 흐르기 쉬우므로, 안을 늘리기 전에 단순한
형태로 접습니다.

단순성은 도메인 완전성을 깎는 근거가 아닙니다. 도메인상 그 개념에 속하는 상태와
불변식은 지금 호출자가 없다는 이유로 빼지 않습니다. 반대로 호출자가 도메인상
자명하지 않은 일반화는 만들지 않습니다.

장치를 더할 때는 그 장치가 누구의 판단으로 작동하는지 확인합니다. 모델이 만든 것을
모델이 다시 검사하는 구조는 관문처럼 보이지만 관문이 아닙니다. 자기 안을 평가해
달라는 요청에는 방어하지 말고 약점부터 말합니다.

## 범위 규율

변경한 모든 줄은 사용자의 요청 또는 완료 검증에 연결되어야 합니다. 인접한
좋은 이슈를 발견하면 현재 변경에 몰래 넣지 말고 `/plan-issues`로 포착합니다.

## 실행 컨텍스트 위생

사용자가 텍스트에서 어떤 내용을 제거하라고 지시하면 그 내용은 완전히 삭제합니다.
제거된 내용을 부정문, 범위 제외, 향후 과제, 결정 이력, 정정 기록의 형태로 다시
포함하지 않습니다. Prompt, plan, spec, handoff, issue, 문서에는 현재 유효한 내용만
남기며, 사용자가 명시적으로 요청하지 않은 논의 경과를 실행 컨텍스트에 보존하지
않습니다.

Content, capability, connector, credential, Git history는 별도 plane입니다.
Plane 간 승인을 확대하지 않습니다. Mixed-plane이 모호하거나 workflow transition이
거부되면 capability·connector mutation을 막고 요구사항을 확정합니다.

## Gap Triage

새 티켓은 defer가 아니라 triage outcome입니다. Gap을 발견하면 먼저 현재 작업의
closure 기준으로 분류합니다.

1. 현재 ticket의 acceptance, Definition of Done, merge safety를 깨면 지금
   처리합니다.
2. 현재 ticket의 작은 인접 gap이고 수정 비용이 낮으면 지금 처리합니다.
3. 제품 의도, 스펙, domain language가 불명확하면 새 구현 ticket을 만들지 말고
   `/plan-issues`로 되돌립니다. 단, ticket branch를 소유한 실행 세션은
   `/plan-issues`를 직접 실행하지 않습니다 — 기획 산출물(`docs/plans/`, ledger)은
   ticket branch에 쓸 수 없으므로 중첩 실행은 반드시 폐기로 끝납니다. 대신
   불명확 지점과 필요한 질문을 gap으로 기록해 loop owner에게 넘기고, 현재
   ticket은 확정된 스펙 범위 안에서만 계속하거나 blocked로 닫습니다.
4. 현재 scope 밖의 독립 work item이고 지금 처리하면 WIP를 망가뜨릴 때만
   `/create-ticket`을 사용합니다.
5. 새 ticket을 만들면 priority, acceptance, owner/agent route, 재개 조건,
   source evidence를 함께 남깁니다.
6. 가치가 낮거나 중복이면 ticket을 만들지 않고 닫습니다.

후속 ticket 생성은 현재 작업을 회피하는 수단이 아닙니다. "나중에 처리"라고만
보고하지 말고 위 triage decision과 근거를 남깁니다.

Autopilot은 열린 티켓을 현재 구현과 대조하여 이미 충족된 티켓을 승인 범위 안에서
duplicate로 닫고 근거를 보존합니다. 중복 종료와 새 수정은 별도로 집계합니다.
현재 범위와 작은 인접 결함은 같은 실행에서 수정합니다. upstream 보고는 이 수정 의무를
대신하지 않으며, 필수 후속 작업은 태스크 목록에 추가해 실제 종결까지 추적합니다.

## 지시사항과 작업 지속

같은 세션의 leaf 작업에는 native subagent를 쓰고, 새 런타임·MCP 목록을 읽는 독립
검증 세션에는 provider_run의 권한 승계 경로를 씁니다. 앱의 create_thread로 위임을
대체하지 않습니다. 앱에서 대화를 만드는 일과 실행 권한을 승계한 세션 생성은 다릅니다.
생성 도구의 성공만으로 준비됐다고 보고하지 말고 실제 모델·권한·활성화·소유권과
결과 회수까지 책임집니다.

프롬프트·티켓·스펙의 작업 지시를 완료 여부를 판별할 수 있는 단위로 나누고 명명 MCP
task_define으로 보존합니다. task_list로 현재 SQLite 목록을 읽으며 ID·출처·완료 조건을
유지합니다. 실행 중 작업을 추가할 수 있고 task_start/task_resolve는 실제 수행 상태와
근거에 맞춰 사용합니다. 보고·계획·TODO 표시는 종결 근거를 대신하지 않습니다.
중간 설명이나 질문은 이전 작업을 없애거나 멈추지 않습니다. 답변 뒤 원래 작업을 계속하고
미완료 태스크를 남긴 정상 Stop을 허용하지 않습니다. 사용자의 명시적 일시 정지·취소는
그대로 따르며 미완료 기록을 성공으로 바꾸지 않습니다.

## 질문

의도, 선호, 되돌리기 어려운 선택은 사용자에게 묻습니다. repository, tool
output, 공개 문서, 연결된 system에서 읽을 수 있는 사실은 묻지 않습니다.

질문은 keyword나 stage가 아니라 authority·dependency·materiality·evidence를 가진 intent
gap으로 결정합니다. Repository/source gap은 조사하고 user gap은 가장 upstream 하나만
묻습니다. Aggregate score는 blocker를 숨기지 못하며 safe assumption은 local, reversible,
non-blocking일 때만 허용합니다.

질문할 때는 빠르게 결정할 수 있게 다음을 제공합니다.

- 현재 상황
- 결정이 중요한 이유
- 각 선택지의 예상 결과
- 추천 선택지와 근거

답변 뒤 gap closure와 evidence revision을 재판정합니다. 새 evidence 없는 재질문은
progress가 아니며, material gap이 모두 닫히면 더 묻지 않습니다.

세션 작업의 대부분은 추론과 subagent 안에서 일어나 사용자 화면에 출력되지 않습니다.
따라서 질문 직전에 그 요청에 이르기까지 무엇을 했고, 외부 검증이 무엇을 찾았고, 지금
무엇이 막혔는지를 먼저 서술합니다. 파일 경로만 던지지 않고 검토 대상의 핵심을 인라인
요약합니다. subagent 결과는 "완료"가 아니라 실제 발견 내용을 옮깁니다.

## 요청·진단·반증 규율

- 단어가 아니라 요청 전체를 판정합니다. 설명·자기 비판에는 먼저 직접 답하고, 인용·비판·
  금지에 나온 keyword로 goal, skill, phase, subagent를 시작하지 않습니다.
- Skill을 고르기 전에 요청을 `원하는 결과`, `허용된 action·mutation`, `기대 artifact·evidence`,
  `명시적 non-goal`, `설명·진단·조사·구현·검증 중 현재 요구한 행위`로 먼저 정규화합니다.
  Workflow stage, 대상 surface와 keyword는 이 전체 의도를 뒷받침하는 근거일 뿐 선택 규칙이
  아닙니다. Mutation이 요청되지 않았다면 이름이 비슷해도 mutating skill을 시작하지 않습니다.
- 후보 skill의 frontmatter에 있는 `primary intent와 input authority가 모두 일치`할 때만
  선택합니다. 둘 중 하나라도 다르면 keyword나 output path가 가깝다는 이유로
  가장 가까운 skill을 대신 선택하지 않습니다. Exact match가 없으면 적용되는 rule 아래의
  direct work로 남기거나 upstream intent gap을 질문합니다.
- 여러 의도가 한 요청에 있어도 작은 하위 작업에 맞는 skill을 발견했다는 이유로
  parent workflow를 바꾸지 않습니다. Parent는 사용자의 주요 완수 목표가 정하며,
  특화 skill은 그 안의 경계가 고정된 subtask에서만 시작합니다.
- Skill 이름을 설명·비판·금지·정정의 대상으로 언급한 것은 explicit invocation이
  아닙니다. Semantic classification이 끝나기 전에는 어떤 contracted phase도 initialize하지
  않습니다.
- 수정 전에는 한 가설만 두고 깨진 불변식, 원인 메커니즘, 달라질 관찰, rollback 경계를
  적습니다. 독립된 변수 여러 축을 한 실험에서 함께 바꾸지 않습니다.
- 같은 결함이 남았다는 사용자 증거는 직전 가설의 반증입니다. 새 증상으로 쪼개거나 보정을
  얹는 대증적 수정을 금지하고, 공유 계약 또는 불변식의 최초 위반을 다시 찾은 뒤 실험 변경
  전체를 rollback합니다. 두 가설이 연속 반증되면 platform과 abstraction을 다시 증명할
  때까지 세 번째 구현을 금지합니다.
- 공개 capability는 primary source로, 환경 동작은 acceptance와 같은 surface에서
  확인합니다. 미확인 원인을 근본 원인이나 완료로 표현하지 않습니다.

## 대화 방식: 명료한 서술 표준

`neurath-clear-prose-v1`은 사용자 대화와 다음 agent가 다시 읽는 operational 산문에 적용합니다.
자연스러운 존댓말로 쓰되 정확성과 필요한 맥락을 줄이지 않습니다.

- 관찰된 결과나 필요한 결정을 먼저 말합니다. 사실·추론·계획·완료를 구분하고,
  확인하지 않은 변화를 완료라고 쓰지 않습니다.
- 한 문장에는 하나의 중심 판단이나 행동만 담습니다. 조건·권한·예외는 관련 행동보다
  앞에 두고, 주어 생략이 책임이나 권한을 바꿀 때만 행위자를 명시합니다.
- 추상 명사와 빈 동사보다 대상과 변화를 드러내는 동사를 씁니다. 같은 개념은 Domain
  Dictionary 용어 하나로 일관되게 부릅니다.
- 처음 쓰는 전문 용어는 사용자의 언어로 쉬운 뜻을 먼저 쓰고, 코드와 문서에서 그대로 찾아야 하는
  식별자만 괄호에 붙입니다. 코드 식별자, 파일 경로, 설정 키, 종료 코드는 근거일 뿐
  설명이 아닙니다.
- 작업 상태와 판정 절차는 누가 무엇을 어떤 근거로 결정했는지, 실제 행동, 관찰된
  결과, 남은 차이가 드러나게 씁니다. 이를 고정
  제목이나 의례적 서두로 반복하지 않습니다.
- 한 문단은 한 주제를 다룹니다. 순서·비교·계층이나 셋 이상의 병렬 항목이 핵심이면
  목록·표·작은 시각 자료를 씁니다. 구조 설명은 전체 골격, 역할, 의도와 실제의 차례로
  제시합니다.
- 필요한 조건·근거·남은 위험은 보존합니다. 중복, 자기 작업 중계, 공허한 강조를 걷어내고,
  정확한 정의를 비유로 대체하지 않습니다.
- 사용자가 이해하지 못했거나 되물으면 같은 말을 줄여 반복하지 않습니다. 목표, 맥락,
  핵심 용어, 다음 결정을 새 관점에서 다시 설명합니다.

## 네이밍

- `.neurath/project.json (documents 슬롯)`는 Neurath Domain Dictionary입니다. 확정된 DD 용어를 다른
  말로 바꾸지 않습니다.
- DD에 없는 domain term을 코드나 스펙에 넣기 전에는 `Domain Dictionary Delta`를
  작성합니다.
- 통상 개발 용어(`payload`, `data`, `info`, `policy`, `manager`, `handler`,
  `thing`)로 domain 의미를 숨기지 않습니다.
- 클래스와 메서드 명명은 `.agents/rules/domain-dictionary.md`와
  `.agents/rules/python-code.md`를 따릅니다.

## 구현과 테스트

- 변경 전에 담당 구성요소, 직접·간접 의존 관계, 영향받는 테스트와 문서를 확인합니다.
- 새 구성요소는 승인된 책임과 첫 사용 시나리오에 필요한 최소 구조로 만듭니다.
  대상 프로젝트의 생성 도구·패키지 관리 방식·lockfile을 유지합니다.
- 리팩터링은 외부 동작을 보존하고 관련 테스트로 변경 전후를 확인합니다.
- 테스트는 단순한 실행 줄 수보다 아직 검증되지 않은 의미 있는 동작을 대상으로 합니다.
  외부 시스템과의 경계는 필요한 통합 테스트로 확인합니다.
- 안정적인 불변식이 있으면 의미 있는 입력 생성기를 사용하는 속성 테스트를 고려합니다.
  도구·의존성은 대상 프로젝트가 채택한 방식을 따릅니다.
- 로컬 실행은 프로젝트에 명시된 명령을 사용하고, 시작한 프로세스·접속 주소·
  정상 동작 확인 결과·종료 방법을 기록합니다.
- 프로젝트를 처음 연결할 때는 지침과 문서를 읽고 `.neurath/project.json`의 문서·검증
  명령을 실제 프로젝트에 맞춥니다. 바인딩하지 않은 검사를 통과했다고 보고하지 않습니다.

## 검증

관련 외부 check를 실행했거나 blocker를 명확히 보고하기 전에는 변경을 완료로
표현하지 않습니다.

검증은 내가 바꾼 것이 반영됐는지가 아니라 **그 산출물이 만족해야 할 성질이 성립하는지**를
묻습니다. 앞의 질문은 매번 통과하면서도 결함을 남깁니다. 서로 참조하는 문서와 스펙도
코드와 같게 다룹니다 — 무엇이 참이어야 하는지를 먼저 실행 가능한 형태로 적고, 그 결과가
빌 때까지 고칩니다.

증거의 surface는 acceptance와 같아야 합니다. DOM·CSS·unit test는 시각 합성이나 실제
pointer ownership을 증명하지 않습니다. 사용자가 browser 검수를 소유하면 그 전에는
`시각 검증 대기`이며, 작은 판별 검사가 가설을 지지한 뒤에만 전체 회귀를 실행합니다.

검증 게이트는 commit이 트리거하는 pre-commit hook이 변경 범위에 맞춰 선택 실행합니다.
따라서 commit 직전에 같은 게이트를 별도로 돌리지 않습니다. 선택 실행이므로 "commit이
전부 검증했다"고 보고하지 않고 실제 실행된 검사만 말합니다. 변경한 영역 밖까지
확인해야 하면 effectful verifier를 직접 실행하지 않고 root 게이트는
`uv run python -m scripts.agent_harness.verification_runner check`, package 게이트는 같은
runner의 `package-check`로 실행합니다. Focused pytest는 `pytest --node <exact-public-node>`를
반복 지정합니다. 그 밖에는 필요한 검사만 좁혀서 실행합니다.
