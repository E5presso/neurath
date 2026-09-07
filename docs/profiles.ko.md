# 프로젝트 연결
<!-- date: 2026-09-07; synced_from: source and documentation at 3563609329437641570a5e45d87ceb99064e4c02; English and Korean editions updated together -->

[English](profiles.md) · **한국어**

`generic`이 유일한 프로필입니다. 언어·프레임워크·모노레포 구조를 하네스가 정하지 않습니다.
기존 프로젝트 지침과 `.neurath/project.json`이 문서, 검증 명령, 선택적 보호 대상과
metadata 관례를 결정합니다. 설정 예제와 명령은 [설치 안내](../ONBOARDING.ko.md)에 있습니다.

31개 스킬은 대상 저장소와 현재 사용자 요청에 맞춰 실행합니다. `explain-code`와
`graphify`는 상태를 소유하는 phase 계약이 없는 보조 스킬이며, 나머지 29개는 단계와
증거 계약을 가집니다. 스킬 선택에는 primary intent와 input authority가 모두 맞아야 합니다.

빈 문서 슬롯을 다른 프로젝트 문서로 채우거나, 검증 도구를 임의 설치하거나,
설정하지 않은 검증을 성공으로 처리하지 않습니다. 특정 connector는 기본 보호 대상이
아닙니다. 키트의 상태·규칙·실행 자산과 사용자가 명시한 경로·connector만 보호합니다.

`test-harness`의 키트 회귀 matrix는 키트 개발 소스를 대상으로 실행합니다.
설치 대상 프로젝트의 코드 변경에는 그 프로젝트가 바인딩한 검증을 사용합니다.
기존 제품별 프로필 이름과 제품 상태 namespace는 지원하지 않습니다.
