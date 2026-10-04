# 코어 용어

[English](../en/terminology.md)

| Term | 의미 |
| --- | --- |
| Task | 사용자 목표·인수 조건·순서가 있는 스킬 실행·시도·배정을 하나로 관리하는 진행 단위. |
| Phase | 스킬이 정의한 순서상의 현재 단계. 필수 결과와 허용 효과가 있다. |
| Attempt | 실행 또는 재작업 시도. 실패해도 목표가 완료되거나 취소되지 않는다. |
| Actor | 작업 디렉터리와 별개로 네이티브에서 관측한 세션 또는 에이전트. |
| Assignment | 서브에이전트·독립 세션·교차 provider 방식으로 위임한 한정된 작업. |
| Worker / reviewer / executor | 역할. 세션이나 호스트를 결정하는 실행 방식이 아니다. |
| Writer lease | checkout의 배타적 쓰기 조정. 세대로 오래된 반환 요청을 거부한다. |
| Source | 원본 네이티브 입력·도구 관측·출처가 표시된 보고. |
| Evidence | 특정 조건과 대상에 사용하는 보존된 출처·결과. |
| Approval interpretation | 정확한 원문 인용을 행동·대상에 연결한 에이전트의 해석. 호스트 권한을 변경하지 않는다. |
| Review target | 독립 리뷰를 위해 보존한 명시적 checkout과 실제 소스 스냅샷. |
| Stop | 네이티브 정상 종료 경계. 소유한 미완료 작업은 계속 수행해야 한다. |
| TODO | Task 상태를 투영한 네이티브 표시. 별도의 진행 기준이 아니다. |
| Installation / activation | 파일·런타임 배치 / 연결된 네이티브 호스트의 실제 사용. |

[코어 명세](contributing/core-v2-spec.md)
