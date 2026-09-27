# Codex 폴링 훅 호환성

[English](../../en/contributing/codex-poll-hook.md)

Neurath의 wave 가드는 차단형 대기 전에 호스트 이벤트를 받아야 합니다. Codex 코드
모드는 일반적으로 중첩 도구에도 훅을 적용하지만, `write_stdin`의 `PreToolUse`를
생략하는 릴리스에서는 폴링이 그 경계 밖에 있습니다. JavaScript wrapper를 전부
거부하면 정상적인 비대기 작업까지 막으며 전송 경로의 결함도 해결하지 못합니다.

`tools/compat/codex-write-stdin-pretooluse.patch`의 개발자용 패치는 해당 예외를
제거합니다. 공통 디스패처가 프로세스에 접근하기 전에 실제 `write_stdin` 이름과
JSON 인자로 이벤트를 보냅니다. 기존 stdin 승인과 프로세스 신원 검사는 유지됩니다.
원래 명령이 종료되면 대응하는 Bash `PostToolUse`도 기존대로 한 번 전달됩니다.

인접 JSON에는 정확한 upstream 태그·커밋·패치 지문·테스트가 기록되어 있습니다.
그 소스 리비전에만 적용하고 다른 버전으로 옮길 때는 독립적으로 다시 검토합니다.
이는 별도 호스트 빌드입니다. Neurath wheel은 Codex를 포함하지 않으며 다른
저장소를 패키지 빌드 입력으로 사용하지 않습니다.

## 에이전트 실행 참조

Upstream 저장소의 개발 지침과 고정 도구 체인을 따릅니다. 격리된 Codex checkout에
패치를 적용하고 다음을 실행합니다.

```sh
just fmt
just test --cargo-profile dev-small -p codex-core --test all -E 'test(suite::hooks::pre_tool_use_blocks_nested_write_stdin_before_input) | test(suite::hooks::post_tool_use_blocks_when_exec_session_completes_via_write_stdin)'
cargo build --profile dev-small -p codex-cli --bin codex
```

일치하는 `codex-code-mode-host`를 실행 파일 옆에 두고 기존 격리 설정을 유지합니다.
회귀 테스트는 실제로 반환된 실행 중 프로세스 ID로 빈 입력 폴링과 입력 전송을
검사하며, 정상 중첩 작업과 원래 명령의 종료 이벤트도 확인합니다.

`tools/native_stop_probe.py`와 `tools/native_wave_probe.py`에는 명시적인
`--codex-bin`, `--model`, 이미 신뢰된 `--project`, 로컬 `--output`을 전달합니다.
Stop probe는 같은 네이티브 턴에서 종료 시도·Stop 차단·태스크 해결·정상 Stop이
순서대로 발생했는지 검사합니다. Wave probe는 기존 프로젝트 claim을 먼저 반환한
뒤 자체 읽기 전용 진단 claim을 획득하며, 두 자식의 보고를 소비한 후 반환합니다.
검사를 통과시키기 위해 다른 세션의 claim을 강제 회수하거나 신뢰를 바꾸지 않습니다.

SDK의 `codex_bin` 설정으로 독립 app-server 실행 파일을 선택할 수 있습니다.
데스크톱 활성화는 별도 관찰입니다. 재연결 뒤 실제 실행 파일과 네이티브 이벤트를
확인합니다. 로컬 호환 실행 파일이나 독립 probe 성공만으로 실행 중인 데스크톱
프로세스가 교체되지는 않습니다.

[호스트 경계](hosts.md)와 [협업 계약](collaboration-contract.md)을 참고하세요.
