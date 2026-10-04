# 검증 경계

[English](../../en/contributing/validation.md) · [코어 계약](core-v2-spec.md)

필수 소스 검사는 `uv run --locked python tools/check.py`다. 버전 일치·매니페스트 무결성·Python 진단·유지한 패키지/설치 테스트·격리된 코어 계약 테스트를 검사한다. 선택 실행은 부분 근거다. 격리된 일부 계약 검사는 `tools/run_core_regressions.py --workers 0 tests/test_domain.py`로 실행한다.

정확한 wheel을 빌드하고 `tools/validate_distribution.py`로 외부 환경 실행을, `tools/validate_setup.py`로 설치 보존을 확인한다. 네이티브 훅 프로토콜 fixture는 payload 처리를 검사하며 실제 호스트 로딩을 증명하지 않는다. 실제 호스트에서는 phase 건너뛰기 거부와 미완료 Stop 거부 뒤 같은 Task의 계속 실행을 관측한다. 비공개 로그는 공개 문서·배포본에서 제외한다. 일부 검사 통과·에이전트 보고·설치만으로 릴리스 준비 완료를 주장하지 않는다.
