# 하네스 규칙 전수 감사 — 2026-10-20

[English](../en/harness-rule-audit.md)

감사 기준 커밋은 `62f5f3298dddad7195d98799cae1f2940725b51c`입니다. 사용자 원문 지시와 #154/#155의 인라인 리뷰·총평을 대조했습니다. 제가 작성한 AGENTS, 과거 답글, 테스트 기대값 자체를 사용자의 추가 지시로 취급하지 않았습니다. 모든 이름·문법을 허용한다는 새 정책을 만든 것이 아니라, 의미적 지적을 자동 거부 조건으로 확대했던 부분을 제거하거나 실제 계약에 맞게 좁혔습니다.

## 조사 범위와 결과

- 수정 전 AST 진단 분류 **33개 전부**를 아래 표에 대조했습니다. 수정 후 **11개 분류**는 근거와 적용 범위를 확인해 유지·축소했고, **22개 AST 진단**은 제거했습니다. 제거된 진단 중 근거 있는 요구는 기존 도메인·DI·ORM·이전 동작 시험과 현재 계약 시험으로 계속 확인합니다.
- AGENTS와 CLAUDE 진입점, 한영 기여 안내, Ruff/Pyrefly/pydoclint 설정, 문서 언어 검사, 커버리지 게이트, pre-commit/CI, Git hook 설치 코드와 실제 연결, setup, 공개 명세의 제약을 함께 조사했습니다.
- `Any`·`cast`·`Literal` 전체, Core/UoW/DB/transport 이름, repository 메서드·인자 이름, 모든 결과의 특정 접미사/frozen/DTO 강제, 표준 라이브러리 허용 목록, 일반 type-ignore/noqa 주석, Ruff ANN401의 Any 인자 제한, 한국어 글자 비율을 일괄 금지할 근거가 없었습니다.
- 명시적인 Protocol 제외, 추상 port·등록 구성요소의 명시적 타입 관계, 표준 docstring과 한국어 설명, 현재 저장소 기능 재사용, 현재 전용 DTO의 배치, 자료 보존, **라인·분기 100% 및 제외 0**은 유지합니다. 정책·상태는 현재의 실제 Enum 타입 계약으로 확인하며 Literal 전체를 금지하지 않습니다.
- 제품 도메인/애플리케이션 구현과 기존 동작 시험은 바꾸지 않았습니다. 과도한 금지를 전제로 한 하네스 시험을 실제 허용 사례와 구체적인 계약 시험으로 교체했습니다.

## 원래 요구와 개별 정정

표의 PR 번호와 댓글 ID는 [#154 리뷰](https://github.com/E5presso/neurath/pull/154/files)·[#155 리뷰](https://github.com/E5presso/neurath/pull/155/files)의 원문 참조입니다. 현재 대화의 후속 정정이 과거 해석보다 우선합니다.

| 기존 진단 | 결정 | 원래 요구·근거 | 정정한 적용 범위 |
| --- | --- | --- | --- |
| ABSTRACT_METHOD | 유지·적용 대상 한정 | 명시적 port 메서드의 abstractmethod 요구 — [PR154#4280330548](https://github.com/E5presso/neurath/pull/154#discussion_r4280330548) | 실제 port 선언만 검사 |
| AGGREGATE_OWNERSHIP | 이름 검사 제거·동작 시험 유지 | Project가 위치 값을 소유 — [PR154#4281754927](https://github.com/E5presso/neurath/pull/154#discussion_r4281754927) | ProjectLocationRepository라는 이름이 아니라 실제 소유 관계·원자 저장 시험 |
| ALEMBIC_REVISION | 문자열 검사 제거·동작 시험 유지 | Alembic이 revision 관리 — [PR155#4321731311](https://github.com/E5presso/neurath/pull/155#discussion_r4321731311) | 추가 실제 migration을 적용하는 시험; core_0001 같은 진단 문자열 허용 |
| APPLICATION_BOUNDARY | 유지 | 도메인·애플리케이션·저장 책임 구분 — [PR154#4280880042](https://github.com/E5presso/neurath/pull/154#discussion_r4280880042) | 확인된 상위/저장 계층 의존 검사 |
| COLLECTION_CONTRACT | 일괄 tuple 금지 제거·계약 시험으로 한정 | 읽기 전용 목록에는 Sequence — [PR155#4321715119](https://github.com/E5presso/neurath/pull/155#discussion_r4321715119),4321717283 | 현재 두 목록 port의 반환 계약만 검사; 다른 tuple 용도 허용 |
| CORE | 제거 | 의미 없는 Core facade와 모듈 설계 지적 — [PR154#4280341976](https://github.com/E5presso/neurath/pull/154#discussion_r4280341976) | Core/core 이름 자체를 금지하지 않고 실제 책임 검토 |
| DATABASE_WRAPPER | 제거 | 해당 DB wrapper의 필요성 지적 — [PR154#4280970066](https://github.com/E5presso/neurath/pull/154#discussion_r4280970066) | SqliteDatabase라는 클래스 이름을 금지하지 않음 |
| DECLARATIVE_ORM | 등록 모델로 한정 | Spakky 선언형 ORM 사용 — [PR154#4280368400](https://github.com/E5presso/neurath/pull/154#discussion_r4280368400) | 실제 @Table의 기반만 확인; 일반 Table/Column 사용은 허용 |
| DEPENDENCY_COMPOSITION | 이름 기반 생성자 금지 제거 | 외부 DI 프레임워크 사용 — [PR154 review 5530407770](https://github.com/E5presso/neurath/pull/154#pullrequestreview-5530407770); 현재 대화 Spakky 전환 | 실제 컨테이너 주입·요청 자원 수명 시험 유지 |
| DOCSTRING | 중복 AST 검사 제거·표준 검사 유지 | docstring 누락·표준 형식 지적 — [PR154#4280349254](https://github.com/E5presso/neurath/pull/154#discussion_r4280349254); review5530407770 | Ruff와 pydoclint를 공유 runner에서 실행 |
| DOMAIN_BOUNDARY | 허용 라이브러리 목록 제거·방향만 유지 | 도메인의 정책 책임 — [PR154#4280880042](https://github.com/E5presso/neurath/pull/154#discussion_r4280880042),4280894714 | 알려진 상위/저장 계층 import만 검사; 표준 라이브러리 일괄 금지 제거 |
| ENTITY_IDENTITY | id 이름 추론 제거·실제 동일성 시험 유지 | 엔티티와 값 구분 — [PR154#4280930212](https://github.com/E5presso/neurath/pull/154#discussion_r4280930212) | id 필드가 있다는 이유로 엔티티로 단정하지 않음 |
| ENTITY_MUTABILITY | frozen 일괄 추론 제거·실제 변경 시험 유지 | 왜 모든 객체가 frozen인지 지적 — [PR154#4280930212](https://github.com/E5presso/neurath/pull/154#discussion_r4280930212) | id를 가진 frozen 값도 허용; 현재 aggregate 상태 변경 시험 유지 |
| EXPLICIT_IMPORT | 중복 검사 제거 | 일반 코드 품질 검사 — [PR154 review 5529723813](https://github.com/E5presso/neurath/pull/154#pullrequestreview-5529723813) | 프로젝트 표준 Ruff F 검사를 유지; 별도 AST 규칙 중복 없음 |
| EXPLICIT_OBJECT_SELECTION | 제거 | 명시적 상속과 코드의 의도를 드러내라는 지적 — [PR154#4280360643](https://github.com/E5presso/neurath/pull/154#discussion_r4280360643) | 이 지적을 mapping.get(...) or 표현식 전체 금지로 확대하지 않음 |
| FORBIDDEN_TYPE | Protocol만 유지 | Protocol 사용 금지; 도메인 상태에는 Enum — [PR154#4280330548](https://github.com/E5presso/neurath/pull/154#discussion_r4280330548),4280345704 | Any/cast/Literal 전체 금지 제거; 현재 네 상태 타입의 Enum 계약 시험 유지 |
| FRAMEWORK_CRUD | 일괄 override 금지 제거·현재 구현 시험 유지 | 기존 기본 repository 기능 재사용 — 현재 대화: Spakky 기본 기능 재사용 | 현재 네 저장소의 기본 메서드 상속 및 실제 CRUD 동작 검증 |
| FRAMEWORK_REQUEST | 이름 추론 제거·타입/실제 입력 검사 유지 | Spakky 유스케이스 인터페이스 전수 적용 — [PR155#4321719836](https://github.com/E5presso/neurath/pull/155#discussion_r4321719836) | 등록된 처리기의 실제 입력 기반과 제네릭을 확인 |
| FRAMEWORK_USECASE | 실제 등록 처리기로 한정 | 프레임워크 유스케이스 인터페이스 상속 — [PR155#4321719836](https://github.com/E5presso/neurath/pull/155#discussion_r4321719836) | UseCase 접미사 추측 대신 실제 @UseCase와 프레임워크 계약 확인 |
| INFRASTRUCTURE_BOUNDARY | 유지 | 계층별 책임 구분 — 현재 대화 및 PR154 책임 분리 리뷰 | 인프라에서 진입 어댑터로 역의존하는 현재 계층 방향 확인 |
| MAPPED_COLUMN | 모든 필드 금지 제거·실제 매핑 시험 유지 | 타입이 드러나는 선언형 모델 사용 — [PR154#4280360643](https://github.com/E5presso/neurath/pull/154#discussion_r4280360643),4280368400 | 모든 클래스 속성을 영속 필드로 단정하지 않음; 실제 schema/metadata 비교 |
| NOMINAL_IMPLEMENTATION | 실제 repository 등록으로 한정 | 명시적 상속으로 타입 관계 표현 — [PR154#4280360643](https://github.com/E5presso/neurath/pull/154#discussion_r4280360643) | Observer/Repository라는 이름만으로 역할을 추론하지 않음; 실제 DI와 타입 시험 유지 |
| NOMINAL_PORT | port 선언으로 한정 | 명시적 추상 계약 — [PR154#4280330548](https://github.com/E5presso/neurath/pull/154#discussion_r4280330548),4280360643 | port 위치의 명시적 I+대문자 계약 선언에 적용; Input 같은 일반 자료형 제외 |
| OBSERVATION_BOUNDARY | 모든 도메인 타입 참조 금지 제거 | 어댑터가 프로젝트 식별 정책을 소유하지 않게 수정 — [PR154#4280894714](https://github.com/E5presso/neurath/pull/154#discussion_r4280894714) | 실제 DirectoryObservation 반환 계약과 Project의 식별·승격·충돌 시험 유지 |
| PRIMITIVE_REPOSITORY | 메서드·인자 whitelist 제거 | 조회·저장 primitive만 담당 — [PR154#4280880042](https://github.com/E5presso/neurath/pull/154#discussion_r4280880042),4280885303 | 조회 메서드 이름과 expected_revision 인자만으로 도메인 로직이라고 단정하지 않음 |
| REPOSITORY_POLICY | 호출 이름 blacklist 제거 | 도메인 동작의 책임은 도메인 — [PR154#4280880042](https://github.com/E5presso/neurath/pull/154#discussion_r4280880042) | create/move 호출 이름만으로 책임 위반을 판정하지 않음; 실제 의미·동작 검토 |
| REPOSITORY_SAVE | 메서드 이름 blacklist 제거·실제 save 계약 유지 | insert/update를 save로 통합 — [PR154#4281760345](https://github.com/E5presso/neurath/pull/154#discussion_r4281760345) | 현재 저장 계약·수명 시험 유지; 저장과 무관한 create helper까지 금지하지 않음 |
| RESULT_LOCATION | 경로·이름·강제 DTO 검사 제거·현재 DTO 계약 유지 | 유스케이스 전용 결과도 입력처럼 같은 모듈에 정의 — 현재 대화: result dto도 유즈케이스 안에 정의 | 현재 16개 전용 DTO 배치 시험; 고정 접미사·항상 DTO·모든 결과 frozen·고정 개수 요구 제거 |
| SELF_RETURN | 하위 타입 보존 생성으로 한정 | 현재 Python 버전에 맞게 Self 사용 — [PR154#4305379584](https://github.com/E5presso/neurath/pull/154#discussion_r4305379584),4305381892 | cls(...)를 반환하는 생성 경로만 검사; 고정 구체 타입 반환 허용 |
| SUPPRESSION | 커버리지 제외만 유지 | 제외로 숫자를 맞추지 않은 라인·분기 100% — 현재 대화: 라인·분기 100%, 제외 처리로 숫자만 맞추지 말 것 | coverage pragma/실제 excluded_lines 0은 유지; noqa/type-ignore 전면 금지는 제거 |
| TRANSACTION_WRAPPER | 이름·contextmanager 금지 제거·수명 시험 유지 | 중복 UoW 대신 ORM/프레임워크 수명 재사용 — [PR154#4280335140](https://github.com/E5presso/neurath/pull/154#discussion_r4280335140); 현재 대화 Spakky 전환 | commit/rollback 이름·yield+begin 자체를 금지하지 않고 실제 commit/rollback/close 검증 |
| TRANSPORT_PASSTHROUGH | 경로 이름 blacklist 제거 | 불필요한 transport 계층 필요성 지적 — [PR155#4321735899](https://github.com/E5presso/neurath/pull/155#discussion_r4321735899) | 실제 프로토콜/중계 책임을 검토; 특정 경로명을 영구 금지하지 않음 |
| USECASE_INTERFACE | 이름 기반 전면 금지 제거 | 여기서는 정책 변동이 없어 불필요한 인터페이스 — [PR154#4280903353](https://github.com/E5presso/neurath/pull/154#discussion_r4280903353); [PR155#4321719836](https://github.com/E5presso/neurath/pull/155#discussion_r4321719836) | 현재 프레임워크 계약 재사용; IUseCase 이름 자체를 금지하지 않음 |

## 설정·프롬프트·실행 경로 감사

| 대상 | 확인한 근거와 처리 |
| --- | --- |
| Pyrefly·Ruff·pydoclint | 명시 타입 검사·표준 문서 요구를 수행하는 기존 도구 설정을 유지. Any 사용을 따로 금지하던 Ruff ANN401은 해제. 도구가 처리하는 오류에 별도의 의미 금지를 중복 추가하지 않음 |
| 한국어 문서 검사 | 한국어 지시는 유지. 한영 비율·줄별 최소 글자 수를 삭제. 코드/형식 표기를 제외한 문서에서 한국어 설명이 전혀 없는 경우만 표시. 언어의 적절성은 별도 검토 |
| 기본 repository | 현재 네 어댑터·port의 기본 메서드 상속, 실제 save 생성/갱신·배치·삭제·낙관적 충돌 시험 유지. 임의 이름의 모든 override를 금지하지 않음 |
| 실제 ORM·DI | 등록 Table의 선언형 기반, 실제 SchemaRegistry·ConnectionManager·SessionManager·Transaction과 요청 격리/실패 정리를 검증 |
| Alembic | 실제 추가 revision 파일로 호환성 조회·명시적 이전·기존 세션 보존을 시험. 버전처럼 보이는 문자열 자체의 금지 없음 |
| 커버리지 | 사용자 직접 지시인 전체 제품 소스 라인·분기 100%, 누락/제외 0과 실제 보고서 검증을 유지 |
| Git 품질 hook·CI | 동일 quality 경로 유지. 기존 hook 연결과 덮어쓰기 방지, 대상 체크아웃 격리·오류 전달을 검증. 모르는 hook 디렉터리·bare repo 등은 데이터 보존/지원 범위의 기술 조건이며 새 업무 승인 조건이 아님 |
| AGENTS·CLAUDE | CLAUDE.md는 AGENTS.md 심볼릭 링크여서 같은 규칙을 읽음. 의미적 리뷰를 이름·경로·함수/예외 형태의 일괄 금지로 바꾸던 문구를 정정 |
| 공개 명세 | CLI 전용·rules 진입·선택 스킬의 phase·태스크 기반 종료·제3자 평가·수락한 회고·원본 자료 보존을 사용자 대화와 대조. 인간 입력 인증·별도 동의 원장·중복 종료 투표는 추가하지 않음 |
| setup·보존된 호스트 등록 | setup의 실패는 공개 CLI/설치기 미구현인 후보의 기술 상태. 로컬의 과거 호스트 등록은 구형 배포 경로이며 현재 후보 설치/활성화의 증거로 사용하지 않음. 이 감사에서 DB·등록·권한·설치를 변경하지 않음 |

## 해석과 검증의 한계

이 표는 이번 감사의 근거이지 새 승인 원장이나 규칙 생성기가 아닙니다. 이름·타입 표기·예외 사용이 실제 책임을 증명하지 않는 경우는 코드의 의미와 호출 흐름을 검토합니다. 검사의 통과를 사용자의 의도 충족이나 의미적 DDD 정확성의 자동 증명으로 보고하지 않습니다. 이미 바로잡은 도메인 검증의 소유 책임은 유지합니다.
