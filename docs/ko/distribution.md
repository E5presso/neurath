# 배포본 준비·업데이트·복구

Neurath는 wheel SHA-256으로 배포본을 구분합니다. 같은 `0.4.1`이라도 소스 commit이나 실제 artifact가 다르면 다른 후보이며, 버전 문자열만으로 이미 최신이라고 판단하지 않습니다. 후보 준비·파일 적용·새 CLI 실행·모델이 안내를 읽은 것·네이티브 호스트 활성화는 각각 다른 결과입니다.

## 소스와 공식 릴리스

```sh
neurath distribution check --installed /path/to/.codex/neurath/distribution.json
uv run --locked python tools/generate_cli_guide.py --check
uv run --locked python tools/build_release.py --output release-candidate
neurath distribution prepare --wheel release-candidate/neurath-0.4.1-py3-none-any.whl \
  --store /path/to/data/neurath/distributions --source-commit FULL_COMMIT_SHA
```

`check`는 공식 stable 릴리스의 관찰을 `no-release`, `lookup-failed`, `release-observed`, `current-artifact`로 구분합니다. `current-artifact`는 공식 asset digest와 현재 배포 기록이 같은 경우에만 반환하며 소스 브랜치 최신 여부를 대신하지 않습니다. 공식 wheel의 `browser_download_url`도 `prepare --wheel`에 전달할 수 있습니다. 선택한 release asset의 공개 SHA-256과 다운로드 바이트를 대조한 뒤 준비하며, digest 부재·불일치는 성공으로 처리하지 않습니다.

소스 후보는 실제 Typer 정의와 packaged guide가 같은지 먼저 검사합니다. 오래된 가이드나 생성 실패는 빌드를 실패시킵니다. 빌드 staging에 소스 commit·내용 식별을 넣고 CLI·가이드·14개 스킬을 같은 wheel에 묶습니다. 변경 중인 checkout으로 만든 개발 후보는 `source_modified: true`, `source_commit: null`로 표시하며 특정 clean commit의 배포본이라고 주장하지 않습니다. 정확한 commit을 요청했다면 그 checkout에서 빌드한 wheel의 개정을 `--source-commit`과 대조합니다. `.github/workflows/distribution.yml`은 전체 검사와 이 빌드를 실행하여 후보 artifact와 SHA256SUMS를 생성합니다. 후보 생성은 공개 릴리스 발행이 아닙니다.

## 적용과 현재 실행 확인

```sh
neurath distribution plan --candidate /path/to/distributions/WHEEL_SHA \
  --provider codex --directory /path/to/project --data-home /path/to/data
neurath distribution apply --candidate /path/to/distributions/WHEEL_SHA \
  --provider codex --directory /path/to/project --data-home /path/to/data
/path/to/project/.codex/neurath/neurath distribution verify
/path/to/project/.codex/neurath/neurath distribution guide
```

`prepare`는 wheel별 별도 환경을 만들고 현재 실행과 실제 가이드를 대조합니다. 준비된 후보를 임의로 덮어쓰지 않으며 재사용 때도 보관 wheel·가이드·패키지 내용을 확인합니다. 설치 wrapper는 선택한 환경의 Python을 사용하고 작업 폴더를 바꾸지 않습니다. `-I`로 작업 폴더나 `PYTHONPATH`의 같은 이름 모듈이 설치본을 가리지 않게 하면서, 프로젝트·호스트 신원은 원래 환경에서 관찰합니다.

`plan`의 개인 preview 파일에는 실제 변경 전후와 배포본이 함께 들어 있습니다. `apply`가 선택한 후보를 기존 설치기에 전달해 소유 블록·스킬·훅만 갱신하고 실제 새 wrapper를 실행하여 버전과 패키지 내용을 대조합니다. 이미 요청한 업데이트에 추가 동의 토큰이나 새로운 작업을 만들지 않습니다. `./setup --provider ... --directory ...`도 현재 checkout을 고정 wheel로 만든 뒤 이 경로를 사용합니다. `maintenance install`은 현재 호출 환경의 파일 설치를 담당하는 하위 명령이며, 개발 환경을 고정 배포로 준비하는 경로는 `./setup` 또는 `distribution prepare/apply`입니다.

사용자 지침·프로젝트 전문 스킬·다른 확장 설정은 보존합니다. 같은 이름의 비관리 전문 스킬은 원문 그대로 우선하며 해당 기본 파일만 설치에서 제외합니다. 나머지 CLI·guide·hooks·스킬 갱신은 계속하고 `skill_overrides`에 보존 경로를 보고합니다. 설치 guide는 그 원문과 packaged catalog를 구분하며 선택된 전문 절차는 기존 `--definition` 경로를 사용합니다. 공유 가능한 관리 SKILL.md는 현재 호스트 guide의 실제 명령을 참조하므로 `.claude/skills -> ../.agents/skills`에서도 설치 순서에 영향을 받지 않습니다. 과거 MCP 등록은 요청한 루트의 관리 launcher 표지와 정확한 옛 명령이 확인된 항목만 제거합니다. 표지가 없는 구형 `.neurath/run`은 `install.json`의 launcher SHA·Python·실행 대상과 설정 파일 SHA, 정확한 hook/MCP 인자를 함께 대조합니다. 확인된 handler만 바꾸고 혼합 그룹의 다른 handler와 속성은 보존합니다. 정확한 옛 hook 호출이 있지만 소유 대조가 실패하면 계획·적용 모두 새 handler를 추가하기 전에 실패하여 이중 집행을 만들지 않습니다. 구형 `neurath:managed` 블록은 manifest 소유 항목과 명확한 경계·기존 MCP 본문을 확인해 교체합니다. 블록 밖 사용자 수정으로 전체 파일 SHA가 달라져도 그 정책은 보존하며, 경계나 소유가 불명확하면 원문을 보존하고 오류를 반환합니다. 이름만 Neurath인 불명확한 등록은 유지하고 실제 항목을 확인해 현재 그룹 CLI로 바꾸도록 안내합니다. 캐시된 옛 MCP 호출을 계속 재시도하거나 새 MCP 서버를 만들지 않습니다.

0.4.1 후보는 0.4.0의 공개 조회·구독·감시 취소 연결을 보완하는 patch 버전입니다. 새 세션의 rules는 `.codex/neurath/guide.md` 또는 `.claude/neurath/guide.md`의 같은 배포 가이드를 먼저 읽도록 연결합니다. 공유 `AGENTS.md`/`CLAUDE.md`에는 프로젝트 상대 링크만 쓰고 symlink와 사용자 본문을 보존합니다. 호스트별 가이드는 각각의 CLI와 14개 스킬을 가리키므로 설치 순서나 재설치로 다른 호스트의 명령을 사용하지 않습니다. 진행 세션은 `distribution guide`로 실제 현재 안내 본문을 다시 읽습니다. 반환은 stdout 제출 근거이며 모델이 내용을 사용했는지나 호스트가 훅을 활성화했는지는 별도로 확인합니다. CLI 업데이트만으로 호스트 앱 재시작을 선행 조건으로 요구하지 않습니다. 호스트 신뢰 hash·네이티브 identity·권한을 직접 만들지 않습니다.

## 공유 DB와 실패 복구

두 프로젝트나 호스트가 같은 사용자 DB를 사용해도, 각 wrapper·가이드는 선택한 배포본을 명시적으로 가리킵니다. 설치 중 기존 DB를 자동으로 먼저 upgrade하지 않습니다. 후보의 schema·무결성 읽기 검사가 실패하면 파일 전환 전에 중단하고 `plan`에 [보존형 이전](migration.md)의 계속 수행 경로를 반환합니다. 에이전트는 기존 업데이트 범위에서 다음을 수행합니다.

1. 같은 DB를 사용하는 관리 CLI들을 확인하고 현재 호환 runtime들을 보존합니다.
2. 현재 호환 CLI로 `migration fence`하여 원 접속 경로와 사건을 보존합니다. SQLite 경로 차단을 호스트 전체·외부 스케줄의 정지로 주장하지 않습니다.
3. 같은 호환 CLI의 `migration recover`로 새 데이터 홈에 복구 사본을 만듭니다. 후보의 `maintenance initialize`는 그 사본에 실행하고 보존한 작업을 조회합니다.
4. 공유하는 대상 호스트들에 같은 후보와 복구 데이터 홈을 적용하고 기존 전환 폴더의 사건을 재생합니다. 실패하면 원본·새 기록·미처리 큐를 유지하고 호환 runtime으로 계속합니다.

```sh
neurath distribution recover --receipt /path/to/applications/APPLICATION.json
```

적용은 변경 전 파일과 대응하는 후보를 개인 복구 기록에 남깁니다. 중간 실패는 원 실행·안내 조합을 복원하며, 적용 후 복구도 DB나 전환 사건을 과거 사본으로 덮어쓰지 않습니다. 적용 이후 사용자가 수정한 파일은 충돌로 표시하여 보존합니다. 이전 runtime이 현재 DB를 읽을 수 없으면 그 runtime을 재활성화하지 않고 호환 복구를 안내합니다. 인터럽트로 중간 상태가 남아도 기록된 변경 전/후 파일만 복구 대상으로 인정합니다.

전환 큐의 monitor tick은 기존 감시의 현재 세션·태스크·자원 소유·취소·예산을 대조합니다. 정상 관찰과 기술 요약은 기존 트랜잭션에 보존하고, 확인 파일 유실 뒤 재생해도 같은 콜백의 관찰 예산을 다시 소비하지 않습니다. 새로운 사용자 지시로 변환하지 않습니다. 새 감시 사건은 실제 호스트 제출 전 `written`으로 유지합니다. 잘못된 콜백·불명확한 진행 중 관찰은 큐에 남아 정확한 복구를 요구합니다. 실제 네이티브 스케줄 수신과 모델 전달은 별도 활성화 검증입니다.
