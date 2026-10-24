# 데이터 이전과 복구

[문서 안내](index.md) · [English](../en/recovery.md)

## 현재 지원 범위

현재 기반 라이브러리는 명시적 `initialize_database`로 해당 패키지의 Alembic head까지 초기화·이전합니다. 기본 DB 경로와 스키마, 호출 예제는 [코어 기반](core-foundation.md)에 있습니다. 일반 요청은 스키마를 변경하지 않고 호환성을 확인합니다.

이 초기화는 과거 하네스 DB를 새 모델로 변환하는 기능이 아닙니다. 인식하지 못한 기존 저장소는 수정하지 않고 거부합니다. 현재 `setup`도 후보 설치를 수행하지 않습니다. 기존 사용자 자료 변환은 #150, 설치 전환은 #151, 운영 진단·우회·장애 기록은 아래 관리 명령으로 제공합니다. 담당 범위는 [구현 계획](implementation-plan.md)을 참고하세요.

## 이전·복구에서 보존할 내용

후속 이전 구현은 원본 DB와 필요한 WAL·설정, 미완료 작업과 원문을 복구 가능한 상태로 보존하고 새 모델과의 대응을 확인해야 합니다. 직접 대응하지 않는 기록도 조회·복원할 수 있게 남깁니다. 과거 완료 표시나 소유권 기록은 당시 이력이며 새로운 성공·승인이 아닙니다.

작성 정지, 새 사건 보존, 전환과 rollback은 [설치·복구 구조](architecture.md#9-설치업그레이드복구finish-session)에 정의합니다. 원본 보관뿐 아니라 미완료 작업의 실제 읽기·재개도 검증합니다. 이미 받은 사용자 지시로 수행 가능한 일에 별도 재입력 절차를 추가하지 않습니다.

저장 장애가 나면 실패 원인과 남은 일을 보존하고 호환 가능한 복구 경로로 제어권을 회복합니다. 우회는 하네스 차단만 멈추며 작업 성공을 만들지 않습니다. 수리 후에는 실제 동작을 검증하고 우회를 해제합니다. 구체적인 관리 명령은 해당 CLI 구현과 함께 문서화합니다.

워크트리 제거는 호스트 도구가 담당합니다. 요청된 정리 대상의 미병합 커밋·로컬 변경·필요한 미추적/무시 파일을 보존하고 복원 가능성을 확인합니다.

## 검증 기준

[요구사항 검증](acceptance.md)의 A34·A50·A51은 이전·rollback, A35는 소유 설정 보존, A36·A61은 장애·복구, A55는 요청된 워크트리 정리를 다룹니다. 임시 자료의 시험과 실제 사용자 설치의 전환·활성화 결과는 구분합니다.

## 운영 진단과 장애 기록 (#147)

`neurath maintenance diagnose --database <파일> --directory <작업 폴더> --provider codex --host-session-id <실제 세션>`은 설정·무결성(외래 키 포함)·Alembic 호환성·프로젝트 연결·재개 경계를 각각 읽습니다. 파일을 생성·이전하거나 프로젝트를 다시 연결하지 않습니다. 없는 자료는 `missing`, 조회 실패는 `failed`, 확인할 수 없는 경계는 `unknown`이며 해당 항목이 있으면 종료 코드는 1입니다. 실행의 실제 liveness는 저장된 상태만으로 확인하지 않습니다.

`maintenance` 그룹은 잘못된 업무 연결 URL에서도 시작할 수 있습니다. 공식 앱을 구성할 동안에만 연결하지 않는 읽기 전용 SQLite URL을 사용하고 진단 전에 원 환경 값을 복원합니다. 사용자 설정 파일이나 DB를 수정하지 않으며 진단은 원래 설정과 명시한 파일을 관찰합니다.

- `incident open --symptom <증상> --reference <출처> [--project-id <ID>]`: 미해결 장애를 등록합니다.
- `incident show --incident-id <ID>`: 원 증상·근거·이관·대체·개정을 조회합니다.
- `incident record --incident-id <ID> --revision <개정> --kind reproduction|fix|regression --detail <실제 수행> --reference <근거>`: 재현·수정·회귀 결과를 순서대로 추가합니다. 회귀에는 `--passed` 또는 `--failed`가 필수입니다.
- `incident refresh --incident-id <ID> --revision <개정> [진단 옵션]`: 실제 진단을 다시 실행해 새 관찰을 추가합니다.
- `incident escalate --incident-id <ID> --revision <개정> --destination <이관 대상·사유>`와 `incident supersede --incident-id <ID> --revision <개정> --replacement-id <ID>`는 미해결 이력과 원 사건 연결을 보존합니다.
- `incident resolve --incident-id <ID> --revision <개정> --explanation <해결 내용>`은 최신 재현 뒤 수정·회귀 성공 근거가 있어야 성공합니다. 사건 해결은 원 작업의 성공이나 완료가 아닙니다.

DB 저장이 불가능하면 `maintenance record-failure --detail <원인·남은 일> --reference <원 호출>`로 `$XDG_STATE_HOME/neurath/recovery.jsonl`(기본 `~/.local/state/neurath/recovery.jsonl`)에 독립 기록을 남깁니다. 훅·장애 명령의 실패도 이 경로와 stderr 출력을 각각 한 번 시도합니다. 두 경로가 실패해도 재시도 루프나 모델 실행을 만들지 않습니다. `host_submitted`는 출력 제출이며 `delivery: unverified`는 실제 사용자 전달을 확인하지 못했다는 뜻입니다. 복구 파일은 코어 원장이나 성공 판정을 대체하지 않습니다.

## 우회와 복원 검증

`neurath hook handle --provider <호스트> --bypass`는 해당 호출의 차단만 중지합니다. 가능한 실제 턴·취소·종료는 계속 기록하며 원문·태스크·호스트 권한을 완료 또는 승인으로 바꾸지 않습니다. 저장 실패 시 우회 응답에도 bookkeeping 미확인을 표시하고 독립 복구 기록을 시도합니다. 우회 옵션을 제거하면 일반 집행 경로로 복원됩니다.

복원 뒤 실제 호스트에서 확보한 Stop 또는 PreToolUse JSON을 `neurath hook verify --provider <호스트>`의 stdin으로 전달합니다. 같은 정상 훅 경로가 실제로 차단하면 `verified: true`와 응답을 반환합니다. 정상 허용·입력 오류·DB 장애는 검증 성공이 아니며 종료 코드 1입니다. 검증은 실제 실행 관찰을 저장하므로 신원이나 사건을 합성해 운영 세션에 넣지 않습니다. 테스트의 실제 CLI·SQLite 검증은 사용자 호스트 설치·활성화 증명이 아닙니다.
