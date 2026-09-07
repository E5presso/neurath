# 설치 진입점 개선
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[사용 안내](../usage/index.md) · [기여자 안내](index.md)


[English](../../en/contributing/installation-design.md) · **한국어**

2026-09-06에 확인한 공개 설치 안내를 참고해 사용자 흐름을 단순화했다.
참고 저장소의 설치 스크립트나 지침을 복사하지 않고 Neurath의 기존 설치 엔진을 사용한다.

| 참고 | 확인한 설치 흐름 | Neurath에 반영한 점 |
| --- | --- | --- |
| [Q00/ouroboros](https://github.com/Q00/ouroboros#quick-start) | 단일 설치 스크립트, 도구 준비, 에이전트 초기 설정으로 연결 | 도구 환경 준비부터 대상 설치·진단까지 한 진입점으로 연결 |
| [garrytan/gstack](https://github.com/garrytan/gstack#install--30-seconds) | 에이전트에 붙여 넣는 설치 요청, 소스의 `setup`, 호스트 선택 | 복사 가능한 설치 요청, `./setup TARGET`, 명시적 호스트 선택 |
| [mattpocock/skills](https://github.com/mattpocock/skills#installation-30-second-setup) | 플러그인 또는 skills 설치 후 프로젝트 초기 설정 | 설치와 프로젝트별 문서·검증 바인딩을 구분하고 다음 단계 안내 |

Neurath는 스킬 파일뿐 아니라 영구 Python 런타임, 훅, 트랜잭션 기록이 필요하다.
따라서 스킬 복사만으로 설치 완료라고 표시하지 않는다. 런처는 설치된 Python 경로를
사용하므로 임시 캐시의 `uvx` 대신 [uv tool install](https://docs.astral.sh/uv/concepts/tools/)로
영구 환경을 만든다. [uv 공식 설치기 옵션](https://docs.astral.sh/uv/reference/installer/)으로
uv 준비 시 셸 설정 수정을 끈다. Python 3.14는 uv가 준비한다.

공개 저장소에서 받은 소스를 기준으로 설치 경로를 안내한다.
소스를 받은 사용자는 `./setup /target`, 도구 설치 후에는 `neurath setup`을 사용한다.
`setup`은 무결성 확인 → 기존 계획 생성 → 기존 적용 → 로컬 진단 순서로 실행한다.
설치 승인 요청을 반복하지 않으며 host trust는 호스트에서 사용자가 검토한다.

기존 `install`, `plan`, `apply`, `wizard`는 유지한다. 기본 프로필은 generic이며,
기존 설치를 다시 설정할 때 호스트·프로필·사용자가 편집한 바인딩을 보존한다.
미리보기는 대상에 파일을 쓰지 않고 원문 없는 경로 목록만 출력한다.
