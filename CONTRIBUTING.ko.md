# Neurath 개발 참여

[English](CONTRIBUTING.md) · **한국어**

<!-- date: 2026-09-07; synced_from: source and documentation at 3563609329437641570a5e45d87ceb99064e4c02; English and Korean editions updated together -->

Neurath는 독립된 호스트 실행 환경과 자체 실행 자산을 갖춘 Python 3.14 패키지입니다.
저장소에 커밋된 잠금 파일을 사용해 개발 환경을 재현합니다.

```sh
uv sync --locked
uv run --locked python tools/check.py
```

`tools/check.py`는 배포본 무결성, Python 진단, 설치 테스트, 런타임 계약을 검사합니다.
런타임 테스트는 임시 Git 저장소에서 실행하며, 종료 후 해당 저장소를 삭제합니다.
오류 분석을 위해 테스트 저장소를 남기려면
`tools/run_core_regressions.py --target /private/path/to/fixture`를 사용하세요.

## 개발 저장소에 하네스 설치하기

```sh
./setup --self
```

빌드한 패키지를 영구적인 도구 환경에 설치한 뒤, 이 저장소에 하네스를 적용합니다.
하네스는 개발용 `.venv`에서 실행하지 않습니다. 설치 후 각 호스트에서 훅을 확인하고
새 세션을 시작하세요. 프로젝트 연결 설정은 `.neurath/project.json`에 있습니다.
다른 프로젝트에 설치한 하네스의 실행 환경은 그대로 유지됩니다. 같은 소스로 다시
설치하면 기존 실행 환경을 검증한 뒤 재사용합니다. 복구에 사용할 이전 실행 환경도 보관합니다.

설치된 `.agents/skills/<name>`, `.neurath/rules`, 호스트 훅은 생성된 파일입니다.
`src/neurath/_assets`의 원본을 수정한 뒤 설치를 갱신하세요.

## 변경·검증·설치 갱신

```sh
# 실행 코드나 설치 자산을 변경한 뒤 실행
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv run --locked python -m build
./setup --self
.neurath/run doctor --protocol
```

새 설치 동작은 먼저 실패하는 테스트로 정의합니다. 기존 지침, 훅, 권한, 의존성과
사용자가 편집한 프로젝트 연결 설정을 보존하세요. 런타임 검사를 통과시키기 위해 상태 JSON을 직접 편집하거나
호스트 신원을 위조해서는 안 됩니다.

## 패키지 구성

```text
src/neurath/
├── cli.py              # 공개 명령줄 인터페이스
├── doctor.py           # 무결성·파일 배치·프로토콜 검사
├── resources.py        # 배포 자산 조회
├── install/            # 호스트별 파일 배치·병합·충돌 검사·설치 트랜잭션·복구
├── hosts/              # Codex·Claude 훅, 신원 확인, 실행 수명주기
├── runtime/            # 엔진 진입점과 검증 명령
├── memory/             # 공유 기억·회고·관측된 실행 방법의 학습
├── _assets/            # 런타임 엔진·스킬·규칙·계약
└── manifest.json       # 전체 실행 코드와 자산의 무결성 검사 목록

tests/
├── test_*.py           # 패키지·설치·어댑터 회귀 테스트
└── runtime/            # 상태·소유권·평가 권한·단계별 계약 테스트

tools/                  # 빌드·검증 도구
docs/                   # 구조·호스트·프로젝트 연결·검증 문서
```

## 검증 근거 관리

실제 호스트의 실행 기록, 설치 계획, 설치 이력, 실행 결과, 검증 기록, 검토 결과,
오류 재현용 파일은 Git에서 제외한 로컬 저장소에 보관합니다.
공개 문서에는 검증한 동작과 범위를 기록하고, 개인 컴퓨터의 경로나 실행 중인 세션의
신원 토큰은 넣지 않습니다. 실제 호스트 활성화를 확인하려면 해당 호스트의 신뢰 설정과
신원 근거가 필요합니다. `doctor --protocol`만으로는 이를 증명할 수 없습니다.

공개 배포는 별도로 명시해야 하는 작업입니다. wheel을 빌드하거나 로컬에 설치하는 것만으로
GitHub나 패키지 저장소에 게시되지는 않습니다.

생성된 스킬, 호스트 설정, 로컬 실행기는 Git에서 제외합니다. 프로젝트 연결 설정과 공개
지침 파일은 버전 관리에 포함하세요. 새로 복제한 저장소에서는 `./setup --self`로 설치 파일을
다시 만들 수 있습니다. 설치기는 기존 Neurath 지침 블록이 원문과 정확히 일치하면 보존하며,
충돌하는 편집이 있으면 거부합니다. 처음 실행하기 전에 각 호스트의 실제 훅을 확인하세요.

## 영어판과 한국어판 함께 관리하기

공개 독자용 문서는 영어 기본판(`*.md`)과 한국어 번역판(`*.ko.md`)을 개별 파일로 유지합니다.
동작, 명령, 제한과 검증 범위가 같도록 두 언어를 함께 갱신하세요.
각 문서에 언어 전환 링크를 두고, 나머지 링크는 선택한 언어를 유지합니다.
소스 배포본에도 두 언어를 모두 포함합니다. `tests/test_publication.py`가 이 규칙을 검사합니다.
`AGENTS.md`와 설치된 스킬 자산 같은 실행 지침은 각자의 계약을 따릅니다.
