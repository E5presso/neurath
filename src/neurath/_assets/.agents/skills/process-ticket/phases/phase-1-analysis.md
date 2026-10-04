# Work item 확인

현재 사용자 지시, GitHub Issue 또는 승인된 local work item을 읽는다. `AGENTS.md`, `.neurath/project.json`의 문서·검증 설정, 관련 ADR·용어 정의와 실제 코드를 대조한다.

범위와 비목표, 완료 조건, 아직 정해지지 않은 product 의미를 구분한다. 새 용어가 기존 정의와 충돌하면 원문을 확인한다. 해결할 수 있는 구현 선택은 자율적으로 결정하고, 실제 제품 결정이 필요한 부분만 묻는다.

`agents_rules_read`, `work_item_source`, `domain_dictionary_lookup`에는 읽은 정의처와 결론을 담은 attributed report를 연결한다. 원문 인용은 `source_read`/`source_quote`로 확인한다.
