# 기여 안내

[처음으로](README.ko.md) · [English](CONTRIBUTING.md)

새 0.3.0 후보는 도메인 규칙, 애플리케이션 연산, 영속화, 호스트 연동을 분리합니다. 생명주기 규칙을 변경하기 전에 [수용 명세](docs/ko/specification.md)를 읽으세요. 요구사항은 목표이며 실제 결과가 있을 때만 검증을 통과했다고 표현합니다.

## 구조

도메인은 영속화 어댑터에 의존하지 않고 엔티티와 불변조건을 소유합니다. 애플리케이션 연산은 작업 단위를 통해 저장소를 조정합니다. SQLAlchemy가 영속화를 구현하고 Alembic이 스키마 변경을 관리합니다. MCP는 `neurath`라는 하나의 서버 이름으로 지원하는 애플리케이션 기능을 노출합니다. 호스트 어댑터는 네이티브 맥락을 담당하며 호출자가 제공한 프로토콜 인자만으로 독립적인 호스트 증명을 확정할 수 없습니다.

## 동작 변경

변경 범위를 좁게 유지하고 관계없는 로컬 작업을 보존하세요. 소유권 검사, 단계 순서, 근거 범위, 위임 수락, 트랜잭션 동작, 멱등성, 임대 세대 차단, 마이그레이션 동작을 바꿀 때는 의미 있는 테스트를 추가하세요. 버전 문자열을 반복하는 테스트는 정확성을 입증하지 않습니다.

새 연산에는 행위자, 소유 자원, 허용 시작 상태, 예상 리비전, 입력, 출력, 영속적인 효과, 실패 조건을 문서화하세요. 재시도 동작을 명시하세요. 같은 키의 재호출이 원래 결과를 반환하는지, 충돌하는 입력을 거절하는지 정의하세요. 트랜잭션 실패 후 부분적인 생명주기 변경이 남으면 안 됩니다.

## 검증

다음 항목을 별도로 검사하세요.

1. 도메인 규칙: 권한 없는 변경, 순서를 어긴 단계, 관련 없는 근거, 성급한 완료를 거절합니다.
2. 저장: 원자적 롤백, 경합하는 리비전, 반복 요청, 해제한 임대, 오래된 세대를 검증합니다.
3. 마이그레이션: 원본 전체를 보존하고 미완료 작업을 집계하며 미래 스키마를 쓰기 없이 거절하고 반복 실행을 검증합니다.
4. 복구: 사용할 수 없는 운영 데이터베이스에서 우회를 실행하고 복원 자료를 검증합니다.
5. 프로토콜: 실제 노출한 도구를 조회하고 호출하며 잘못된 입력과 기록된 실패도 확인합니다.
6. 네이티브 호스트: 의도한 설치 배포본을 사용하는 실제 연동에서 관찰을 얻습니다.

실제 수행한 검사와 그 결과를 보고하세요. 패키지 테스트로 프로토콜 호출이나 네이티브 활성화를 대신하면 안 됩니다. 실행할 수 없는 호스트 검사는 명시적으로 미검증 상태로 남겨야 합니다.

## 개발 명령과 기능 목록

저장소 루트에서 잠금 파일에 맞춰 환경을 동기화하고 필수 검증 진입점을 실행하세요.

```sh
uv sync --locked
uv run --locked python tools/check.py
```

검증 진입점은 Ruff, pytest, 휠 빌드를 순서대로 실행합니다. 해당 명령이 모두 성공한 뒤에만 `NEURATH_CHECK_OK`를 출력합니다. 이 표시는 네이티브 호스트 활성화를 입증하지 않습니다.

현재 체크아웃이나 명시적으로 선택한 프로젝트에 로컬 설치를 준비할 수 있습니다.

```sh
./setup --self
./setup /target/project
```

설치는 `.neurath/run` 래퍼를 제공합니다. 모듈 진입점에서도 루트와 제공자를 명시할 수 있습니다.

```sh
uv run --locked python -m neurath --root . status
uv run --locked python -m neurath --root . mcp --provider codex
uv run --locked python -m neurath --root . hook --provider claude-code
```

`mcp`는 표준 입력에서 줄 단위 JSON-RPC를 받습니다. `hook`은 호스트 훅 입력을 받으며 실제 네이티브 사건 없이 호출했다고 호스트 활성화가 입증되지는 않습니다. 두 전송 명령 모두 두 제공자를 지원합니다.

운영 데이터베이스를 열지 않고 복구 우회의 상태를 확인하거나 변경할 수 있습니다.

```sh
uv run --locked python -m neurath --root . bypass
uv run --locked python -m neurath --root . bypass --enabled true
uv run --locked python -m neurath --root . bypass --enabled false
```

MCP 도구 `harness_bypass`는 선택적인 불리언 `enabled`로 같은 워크트리 범위의 복구 기능을 제공합니다. Neurath 훅을 일시 중지하며 호스트 권한을 부여하거나 작업을 완료하지 않습니다.

### 프로토콜 기능 목록

MCP 전송 이름에는 밑줄을 사용하고 애플리케이션 명령에는 점을 사용합니다. 예를 들어 개념상 명령 `session.get`, `task.create`, `task.activate`, `verification.prepare`는 MCP에서 `session_get`, `task_create`, `task_activate`, `verification_prepare`로 호출합니다. 아래 표는 개념상 명령 이름이며 MCP를 호출할 때는 각 점을 밑줄로 바꾸세요. `harness_bypass`는 이미 전송 이름입니다. 서버 이름은 `neurath`로 유지됩니다.

현재의 닫힌 입력 스키마는 MCP `tools/list`로 확인하세요. 각 애플리케이션 도구와 `verification.prepare`에는 해당 네이티브 호출을 연결하기 위한 새로운 `_call_id`가 필요합니다. 애플리케이션 변경 연산에는 멱등성을 위한 `request_id`도 필요합니다. 검증 준비는 대신 같은 행위자의 같은 명령이 이미 준비·실행 중이면 두 번째 준비를 거절합니다. 버전이 있는 기록을 갱신하는 연산에는 문서화된 `expected_revision`이 필요하며 새 변경을 구성하기 전에 기록을 읽어야 합니다. 알 수 없는 필드는 거절합니다.

| 영역 | 연산 |
| --- | --- |
| 세션 | `session.get` |
| 작업 | `task.create`, `task.get`, `task.list`, `task.adopt`, `task.activate`, `task.resume`, `task.wait`, `task.withdraw`, `task.revise`, `task.complete` |
| 순서가 있는 단계 | `phase.start`, `phase.complete` |
| 조건과 근거 | `criterion.satisfy`, `evidence.record`, `evidence.list` |
| 위임 | `delegation.prepare`, `delegation.start`, `delegation.report`, `delegation.accept`, `delegation.reject`, `delegation.cancel`, `delegation.list` |
| 통신 | `message.send`, `message.list`, `message.ack` |
| 체크포인트 | `checkpoint.save`, `checkpoint.list` |
| 작성 임대 | `lease.acquire`, `lease.release`, `lease.check` |
| 네이티브 검사 | `verification.prepare` |
| 복구 | `harness_bypass` |

`evidence.record`는 에이전트 보고를 기록합니다. 네이티브 도구 결과나 사람의 승인을 만들어 낼 수 없습니다. `message.ack`는 위임 작업을 수락하지 않고 전달을 확인합니다. `task.revise`에는 새 사용자 출처가 필요하며 이전 검증을 무효화합니다. `task.withdraw`에는 해당 작업에 연결된 네이티브 승인이 필요합니다. 임대는 원장 작성자를 조정하며 호스트 파일시스템에 대한 권한을 부여하지 않습니다.

`task.adopt`는 새 네이티브 사용자 지시가 있을 때만 종료된 세션의 미완료 작업 소유권을 이어받습니다. 보관된 원래 출처는 보존합니다. 이는 작업을 가져오거나 읽었을 때 암묵적으로 일어나는 변화가 아니라 명시적인 소유권 변경입니다.

### 네이티브 검증

`.neurath/project.json`의 `verification` 아래에 이름을 가진 검사를 설정하세요. 검사는 `argv` 목록과 선택적인 체크아웃 내부의 `cwd`, 선택적인 `success_codes` 목록을 갖습니다. 성공 코드는 기본값이 `[0]`입니다. 예시는 다음과 같습니다.

```json
{
  "verification": {
    "project": {
      "argv": ["uv", "run", "--locked", "python", "tools/check.py"],
      "cwd": ".",
      "success_codes": [0]
    }
  }
}
```

활성 상태로 소유한 작업에 대해 `task_id`, `check_name`, 선택적인 `criterion_id` 또는 `phase_id`, 네이티브 `_call_id`로 MCP 도구 `verification_prepare`를 호출하세요. 응답에는 `execution_id`, `state: prepared`, `cmd`와 `workdir`를 인자로 갖는 `exec_command`라는 `native_action`이 포함됩니다. 반환된 명령은 해당 실행 식별자로 `.neurath/run check-run`을 실행합니다. 반환된 동작을 네이티브 호스트를 통해 한 번 실행하세요.

네이티브 실행 전 관찰이 실행기 시작 전에 준비한 실행을 연결합니다. 실행기는 저장된 인자 목록을 하위 프로세스로 실행하고 실제 반환 코드를 직접 기록합니다. JSON처럼 보이는 표준 출력이나 출력된 성공 표시로 이 결과를 만들어 낼 수 없습니다. 실행기는 호스트의 도구 출력 표시 방식과 독립적으로 근거를 저장합니다. 이후 MCP 도구 `evidence_list`를 호출하고 해당 근거를 단계나 조건 전이에 사용하세요.

실행기를 시작했다는 사실만으로 성공이 입증되지는 않습니다. 조건을 충족하거나 단계를 완료하기 전에 저장된 완료 근거를 기다리세요. 실행이 중단되면 계속할 방법을 결정하기 전에 저장된 상태와 근거를 확인하세요. 이 설계가 모든 취소나 프로세스 종료에서 자동 복구를 보장하지는 않습니다.

이 프로토콜은 임의의 셸 실행이나 외부 에이전트 실행을 제공하지 않습니다. 실제 작업은 네이티브 호스트 도구가 수행하며 호출이나 보고로 관찰한 결과를 대신할 수 없습니다. 관찰한 테스트와 네이티브 생명주기 결과는 [후보 검증 기록](docs/ko/candidate-status.md)을 참고하세요.

### 중단과 계속하기

미완료 작업이 남아 있으면 첫 Stop 훅은 계속 진행하도록 요청합니다. 이후 중단에서 호스트가 `stop_hook_active: true`를 알리면 훅은 미완료 작업을 보존하면서 제어를 넘깁니다. 이를 통해 장애 보고가 끝없이 반복되는 것을 방지합니다. 제어를 넘기는 행위는 작업을 완료·철회·취소하지 않습니다. 계속할 수 있게 되면 기존 소유자, 단계, 근거를 유지하면서 작업을 재개하세요.

### 변경된 Codex 훅 신뢰

설치하거나 훅 정의를 변경한 뒤에는 Codex CLI에서 `/hooks`를 열고 현재 Neurath 훅 정의를 검토한 후 의도한 정의를 명시적으로 신뢰하세요. Codex는 정확한 정의 해시에 신뢰를 연결하며, 사용자가 검토하기 전에는 새로 추가되거나 변경된 비관리형 훅을 건너뜁니다. [공식 훅 신뢰 안내](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)를 참고하세요.

사용자가 이 절차를 마친 뒤 실제 네이티브 사건과 연결된 MCP 호출을 관찰하고 설정한 검사를 실행하여 저장된 근거를 읽으세요. 도구 발견만으로 이 절차가 완료되지는 않습니다. 해당 관찰이 생길 때까지 네이티브 활성화를 대기 상태로 유지하고, 조건을 충족하기 위해 신뢰 기록을 수정하거나 수신증을 만들어 내지 마세요.

## 문서

`docs/en/`과 `docs/ko/`에 대응되는 영문·국문 페이지를 유지하세요. 언어 내부 탐색은 같은 언어로 유지하고 번역 링크를 명시하세요. 범위가 바뀌면 루트 README와 기여 안내의 두 언어 버전도 갱신하세요. 사용자 페이지에는 자연어 흐름을 사용하고 에이전트 대상 명령은 이 문서에 두세요.

공개 문서에 개인 로컬 경로나 관계없는 저장소 이름을 넣지 마세요. 요구사항, 구현한 기능, 관찰한 검증을 구분하세요. 문서 작성 권한이 공개, 푸시, 배포, 설치, 호스트 재시작을 허용한다고 추정하면 안 됩니다.
