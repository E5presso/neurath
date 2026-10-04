# intent_audit — 원래 사용자 요구와 비교

같은 Task에 선언된 `review-spec` 하위 스킬을 실행한다. Milestone/parent/issue 또는 승인된 plan의 원문을 실제 구현·검증·병합 결과와 비교한다. 명칭·제품 의미·인수 조건·필요한 결정 문서에서 구체적인 차이가 있는지 확인한다.

`audit_spec_result`에는 원래 요구와 결과의 대응 및 실제 gap을 남긴다. 미충족 요구를 후속 issue에 적었다는 이유로 현재 요청을 완료하지 않는다. 발견한 gap과 correction plan을 기록해 `review-spec.execute`의 조사 자체를 완료하고, `phase_read`에서 상위 `autopilot.intent_audit`으로 돌아왔음을 확인한다. 필수 수정이 있으면 그때 `phase_restart`로 수집부터 다시 진행한다. 사용자가 명시적으로 범위를 바꾼 경우에만 그 지시를 근거로 범위를 갱신한다.
