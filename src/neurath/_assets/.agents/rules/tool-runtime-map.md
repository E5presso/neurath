# 실행 도구 선택

Neurath의 named MCP는 Task·phase·출처·위임·소유권 상태를 다룬다. 파일 수정·검사·
실제 subagent/provider 실행은 현재 호스트의 native 도구를 사용한다. 반환된 계획이나
marker는 실제 실행·승인·완료가 아니다. 현재 스키마와 반환 ID를 따른다.

| 작업 | Neurath 명령 또는 native 표면 |
| --- | --- |
| 현재 작업 | session_status, task_list, task_read, task_focus |
| 요구와 진행 | task_define/start/wait/resume/complete, skill_start, phase_read/complete/restart |
| 실제 원문 | source_list/read/quote, evidence_list |
| 보고와 승인 해석 | report_record, approval_record |
| writer 자원 | worktree_read/claim/release |
| 작업 위임 | assignment_prepare/start/read/report/accept/reject/cancel |
| 다른 세션/provider | provider_prepare/read 및 반환된 native 실행 |
| 동료 메시지 | collaboration_discover/send/inbox/reply/ack |
| 공유 지식 | newsroom_publish/headlines/read, memory_recall/checkpoint/pull |
| 공개 결과 확인 | publication_read |
| 결함 복구 | 상태·원문 오류를 보존하고 승인된 native 도구로 수리 |

재사용 가능한 `tool:<key>` 참조는 아래 의미를 가진다. 정확한 native 이름은 현재
호스트의 inventory와 schema에서 확인하며 도구 부재를 성공으로 기록하지 않는다.

| key | 실제 동작 |
| --- | --- |
| read_file, search_files, read_many | Read/Glob/Grep 또는 native shell의 cat/rg 읽기 |
| edit_file | Edit/Write 또는 apply_patch, 실제 절대 대상 경로 |
| run_shell | 호스트의 Bash/exec_command와 실제 workdir |
| ask_user | 현재 host의 사용자 질문 도구 |
| spawn_agent, team_create | 현재 native subagent 도구 |
| create_worktree | 예약된 실제 경로에 native Git worktree 생성 |
| send_progress | 사용자에게 현재 결과·남은 불확실성 설명 |
| send_message | 승인된 native agent 메시지 또는 프로젝트 mailbox |
| github | 현재 GitHub connector 또는 native gh |
| source_research | 현재 문서 검색 도구와 원문 조회 |
| design_canvas, browser, native_mobile | 실제 해당 native 기능; 없으면 정확한 미지원 보고 |
| phase_runner | 같은 Task의 skill_start 및 phase_read/complete/restart |
| verify_repository | project.json의 등록된 실제 native 검사 명령 |
| local_pr_monitor | 현재 지원되는 PR 이벤트 감시와 그 실제 결과 |

서로 독립된 읽기 조사 둘 이상은 병렬 위임하고 결과를 대조한다. 필요 없이 슬롯을
채우지 않는다. 독립 리뷰는 새 컨텍스트의 reviewer 한 명이 전체 검토 기준을 확인하며
구현자의 자체 검토로 대체하지 않는다. 리뷰어의 읽기·실패 보고에 writer lease나 관측할
수 없는 부모 계보를 선행 조건으로 요구하지 않는다.

같은 계정·프로세스의 모든 프로그램 효과를 정적으로 증명한다고 주장하지 않는다.
알려진 편집·게시·정리 효과를 현재 phase에서 검사하고, 분류되지 않은 실행은 execute로
처리한다. 혼합 호출의 알려진 효과를 지우지 않는다. Host sandbox와 승인 체계는 그대로
유지한다. 출력의 PASS 문자열·도구 시작 handle·write_stdin 접수는 실제 완료 근거가 아니다.
