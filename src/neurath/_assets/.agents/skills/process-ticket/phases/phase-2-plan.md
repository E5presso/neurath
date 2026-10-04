# 의도와 구현 계획

사용자 의도를 간결하게 재진술하고 변경할 코드·테스트·문서를 연결한다. 기존 구현과 import/service 경계를 확인하고, 적용되는 failing/characterization test와 focused/project check를 선택한다.

계획은 파일·검증·위험·복구 방법을 판단할 만큼만 구체적으로 작성한다. 단순 구현 선택 때문에 새 승인 절차를 만들지 않는다. 사용자가 `--require-approval`을 명시했다면 해당 계획을 제시하고 그 응답을 기다린다.

`intent_restatement`, `code_inspection` 근거를 기록한다. 구현 범위를 바꾸는 새 결정이 없으면 다음 단계로 진행한다.
