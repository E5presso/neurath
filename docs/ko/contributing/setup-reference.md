# 설치 실행 참조

[English](../../en/contributing/setup-reference.md) · [코어 계약](core-v2-spec.md)

에이전트는 승인된 대상 설치에 `./setup TARGET`, 현재 checkout 자기 설치에 `./setup --self`를 사용한다. 설치는 개발 가상환경과 분리된 불변 도구 환경을 준비하고 소스 식별을 검증한 뒤 설정 투영본과 프로토콜 진단을 수행한다. 같은 설치를 반복하면 변경하지 않는다.

패키지 CLI는 `setup`, `plan`, `apply`, `install`, `update`, `uninstall`, `restore`, `recover`, `doctor`, `integrity`를 유지한다. 정확한 인자는 현재 parser에서 확인한다. 프로젝트 작업에는 명명된 core MCP 도구와 네이티브 편집·검사 도구를 사용한다. 이전 generic engine·skill-script gateway는 제거했다. 로컬 프로토콜 검사가 성공해도 호스트 신뢰나 실제 활성화를 증명하지 않는다.
