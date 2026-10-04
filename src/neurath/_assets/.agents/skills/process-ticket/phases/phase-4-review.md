# Test-first와 구현

`test_first`와 `implementation`은 순서가 다른 두 단계다.

먼저 검증 정책을 판단한다. 동작 변경·버그·설치 변경에는 요구를 판별할 실패 또는 characterization test를 만들고 기대한 실패인지 확인한다. 문서·기계적 변경처럼 새 테스트가 요구를 판별하지 않는 경우에는 정의된 `not-required` 경로에 이유와 대체 검증을 기록한다. 임의로 phase를 생략하지 않는다.

`test_policy`는 실제 변경 성격을 설명한다. 테스트가 필요한 경로의 `failing_test`는 관측된 실패 결과이고 `expected_failure`는 그 실패가 요구와 관련 있다는 판단이다. 산문의 FAIL 문구는 검사 결과를 대신하지 못한다.

그 뒤 승인된 범위의 최소 production change를 구현한다. 관련 없는 리팩터링과 새로운 제품 요구를 추가하지 않는다. `approved_scope`, `changed_files`를 실제 diff와 연결한다. 효과가 다른 단계의 작업은 phase를 건너뛰어 실행하지 않는다.

필요한 독립 조사에는 bounded subagent를 쓴다. 구현자를 최종 리뷰어로 재사용하지 않는다. 최종 독립 리뷰는 commit된 정확한 head를 대상으로 publication 단계에서 수행한다.
