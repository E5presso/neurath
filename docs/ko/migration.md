# 기존 자료 보존과 선택 재개

`migration` CLI는 과거 SQLite를 읽기 전용으로 조사하고 일관된 사본을 만든 뒤, 선택한 자료를 현재 사용자 단위 코어에 연결합니다. 원본을 읽거나 스냅샷을 등록하는 것만으로 과거 미완료 작업이 현재 세션의 작업이나 Stop 차단 조건이 되지 않습니다. 과거 소유자·세션·임대·수행 결과는 이력이며 현재 네이티브 신원이나 권한을 증명하지 않습니다.

## 관찰과 보존

```sh
neurath migration inspect --source /path/to/old.sqlite3
neurath migration prepare --source /path/to/old.sqlite3 \
  --directory /path/to/project --archive-directory /path/to/private-backups \
  --config /path/to/old-config.json
neurath migration read --archive-id UUID --section tasks --limit 20
```

`inspect`는 실제 테이블과 행 수, WAL 존재를 반환합니다. 지원 형식은 `records/tasks/source_archives`와 Alembic `0001/0002`를 가진 저장소, `runtime_records/runtime_schema/events` 저장소입니다. 그 밖의 형식은 `unknown`으로 명시합니다. `prepare`는 SQLite backup으로 일관된 커밋 상태를 만들고, 관찰 시점의 원 DB·WAL·SHM 및 지정한 설정 파일도 별도로 보존합니다. 원 파일의 단순 복사본과 일관된 조회 사본은 `files.json`에서 구분합니다. 같은 원본 경로·내용·설정은 같은 등록으로 연결합니다.

조회 영역은 `tasks`, `sources`, `workflows`, `enclave`, `messages`, `learning`, `memory`, `unknown`입니다. 원문과 원 상태·참조는 그대로 반환하며, `unknown`은 보존된 테이블 및 행 수를 표시합니다. 이 목록이 모든 자료의 의미를 해석했다는 뜻은 아닙니다. 내장 `zlib-json-v1` archive는 스트림으로 풀어 임시 파일에서 필요한 행을 읽으며 전체 JSON을 메모리에 펼치지 않습니다. 페이지의 `total: null`은 전체 수를 아직 세지 않았다는 뜻입니다. `next_offset`이 있으면 같은 영역과 `--offset`으로 다음 페이지를 읽습니다. 마지막 페이지에서만 확인한 전체 수를 반환합니다.

## 현재 작업과 연결

```sh
neurath migration resume --archive-id UUID --key ORIGINAL_TASK_KEY \
  --workflow-key ORIGINAL_WORKFLOW_KEY
neurath migration recall --archive-id UUID --section messages --key ORIGINAL_MESSAGE_KEY \
  --task-id CURRENT_TASK_UUID
```

에이전트는 기존 사용자 요청 범위에서 원문과 상태를 읽고 대상을 선택합니다. 별도 인간 승인이나 원문 재입력은 요구하지 않습니다. `resume`은 실제 관찰된 현재 프로젝트·세션에서 미완료 작업을 시작합니다. 원래 태스크 정의와 상태·소유권은 handoff 기억으로 남기며, 이미 현대형 저장소에 대응된 runtime 태스크는 계보로 대조하여 중복 생성하지 않습니다. 반복 재개는 같은 현재 작업을 반환합니다. 과거 미완료 phase는 기존 runner의 호스트 단계로 이어지며, 이전 성공 결과를 현재 시도의 성공으로 만들지 않습니다. 과거 성공한 선행 작업은 원 자료와 증거를 보존하고 runner의 필수 첫 단계에서 현재 유효성을 확인합니다. 현재 성공 태스크를 꾸며 만들지 않습니다. 미완료 선행 작업은 먼저 선택 재개한 같은 현재 태스크에 의존으로 연결하며, 그 작업이 아직 성공하지 않았으면 종속 작업은 pending으로 유지합니다. 찾을 수 없는 선행 작업이나 인식할 수 없는 의존 형식은 명시적으로 거절하고 원본을 유지합니다.

`recall`은 선택한 원문·절차·enclave·메시지·학습·기억을 기존 Memory와 enclave의 가정 참조로 연결합니다. 과거 사실을 검증된 현재 사실로, 메시지를 읽음/ACK로, 제안 교훈을 적용된 개선으로 승격하지 않습니다. 기억의 원 상태와 참조를 읽고 기존 업무·협업·회고 흐름에서 필요한 행동을 이어갑니다. 알 수 없는 원문이나 비구조화 자료를 추측으로 새 사용자 지시로 만들지 않습니다.

## 작성 경로 전환과 사건

```sh
neurath migration fence --source /path/to/old.sqlite3 \
  --archive-directory /path/to/private-backups
```

이 명령은 선택한 실제 경로를 변경하므로 운영 전환을 수행하는 때에만 사용합니다. POSIX `lsof` 관찰로 외부 SQLite 연결이 없음을 확인하고, 사본 생성 이후 데이터 변경 여부와 SQLite exclusive 잠금을 검사합니다. 관찰 불가·열린 연결·늦은 변경이면 경로를 전환하지 않습니다. 일관된 사본과 원 inode를 남긴 뒤 원 경로를 전환 폴더로 원자 교체하여 표준 SQLite의 옛 경로 재접속 쓰기를 거절합니다. 늦게 열린 연결의 쓰기도 SQLite의 이동된 DB 검사로 실패합니다. 이는 선택한 SQLite 접속 경로의 기술적 전환이며 호스트 프로세스 종료, 외부 예약 취소 또는 임의 경로를 쓰는 프로그램의 정지를 증명하지 않습니다.

현재 훅 CLI가 전환 경로를 만나면 원 payload와 정규화된 사건을 잠금·fsync를 거쳐 순서대로 보존합니다. 일반 도구를 막는 새 승인 절차는 만들지 않습니다. 종료 사건은 아직 코어 처리가 안 되었으므로 계속 종료할 수 없다고 응답합니다. 복구 후 `migration replay --directory TRANSITION_DIRECTORY`는 기존 `ReceiveHook` 트랜잭션으로 적용하고 성공 뒤 큐를 확인 처리합니다. 확인 파일 쓰기 전 중단되어도 같은 사건은 중복 반영되지 않습니다. 실제 호스트 전달 여부는 `unverified`입니다. 감시 tick은 새 사용자 지시로 바꾸지 않고 명시적 미처리 오류와 큐에 남깁니다. 기존 감시 경로에서 현재 예약·취소·소유권을 대조할 때까지 적용 완료를 주장하지 않습니다.

## 새 기록 이후 복구

```sh
neurath migration recover --source /path/to/current-core.sqlite3 \
  --destination /path/to/recovered-core.sqlite3
```

`recover`는 현행 Alembic 호환성을 확인하고 새 목적지에 현재 코어 전체를 복제합니다. 기존 목적지를 덮어쓰지 않으며 `activated: false`를 반환합니다. 새 태스크·기억·사건 반영 기록을 버리는 구버전 역변환은 제공하지 않습니다. 전환 큐와 사본·원 파일을 함께 유지하고 호환 코어를 선택한 후 미처리 사건을 재생합니다. 데이터 사본 생성과 실제 설정 전환·호스트 활성화는 구분합니다.

회귀 시험은 합성 자료의 원문·순서·계보·선택 재개, 실제 SQLite writer 재접속과 늦은 연결, WAL·관찰 실패, 실제 훅 CLI 큐·중복 반영 방지, 새 기록 후 복구를 검증합니다. 실제 과거 자료의 복제본에서도 조회·재개·복구와 대용량 제한 조회를 확인했습니다. 운영 원본 전환, 호스트 스케줄 취소, 실제 모델 전달은 이 검증으로 완료된 것으로 취급하지 않습니다.
