# 동의 기반 upstream 보고

[English](../../en/contributing/reporting-reference.md) · [코어 계약](core-v2-spec.md)

`report status`로 저장된 선택을 읽는다. 답변이 없으면 자동 보고를 끈 상태로 둔다. 네이티브 `report prepare`는 개인정보 검토 뒤 범위가 한정된 공통 하네스 보고를 준비한다. `report submit`은 정확한 초안을 게시하고 결과를 다시 읽는다. 전달 여부가 불확실하면 재전송 대신 대조한다. 프로젝트 전용 contribution 초안에는 별도의 명시적 승인이 필요하다.

훅은 로컬 안내만 제공하며 보고를 게시하지 않는다. 의사결정 명령에는 실제 입력 인용과 정확한 네이티브 명령 대상에 연결된 승인 해석이 필요하다. `--user-confirmed` 인자만으로 입력 출처를 증명할 수 없다. 설치 업데이트는 기존 동의와 보고 이력을 보존한다.
