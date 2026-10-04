# 코어 명령 참조

[English](../../en/contributing/capability-map.md)

실행 중인 MCP 연결의 `tools/list`를 사용한다. `core/tool_schema.py`가 schema를, `core/service.py`가 routing을 정의한다. 네이티브 호출마다 새 `_call_id`를 쓰고 동일 mutation 재시도에는 같은 `key`를 쓴다. 네이티브 훅이 실제 실행자와 정확한 요청을 결속한다. 두 값 모두 호스트 권한을 부여하지 않는다. Task 변경에는 반환된 Task revision을 사용한다. 읽기에는 쓰기 소유권이 필요 없다.

| Command | Required fields | Optional fields |
| --- | --- | --- |
| `approval_record` | `action`, `digest`, `end`, `key`, `reason`, `source_id`, `start`, `target`, `task_id` |  |
| `assignment_accept` | `assignment_id`, `key`, `source_id`, `subject`, `task_id` |  |
| `assignment_cancel` | `assignment_id`, `key`, `reason`, `task_id` |  |
| `assignment_prepare` | `execution`, `expected_revision`, `key`, `reason`, `role`, `scope`, `subject`, `task_id` | `checkout`, `provider`, `recipient` |
| `assignment_read` | `assignment_id`, `task_id` |  |
| `assignment_reject` | `assignment_id`, `key`, `source_id`, `task_id` |  |
| `assignment_report` | `assignment_id`, `body`, `key`, `subject`, `task_id`, `verdict` |  |
| `assignment_start` | `assignment_id`, `key`, `task_id` |  |
| `collaboration_ack` | `key`, `message_ids` |  |
| `collaboration_discover` |  |  |
| `collaboration_inbox` |  | `include_read`, `limit` |
| `collaboration_reply` | `body`, `key`, `message_id` |  |
| `collaboration_send` | `body`, `key`, `recipient` | `task_id` |
| `evidence_list` | `task_id` |  |
| `learning_pending` |  |  |
| `learning_status` |  |  |
| `memory_checkpoint` | `key`, `summary` | `decisions`, `lessons`, `next_steps`, `status` |
| `memory_pull` | `source_actor` |  |
| `memory_recall` |  | `limit`, `query` |
| `newsroom_headlines` |  | `limit` |
| `newsroom_publish` | `body`, `key`, `title` |  |
| `newsroom_read` | `article_id` |  |
| `phase_complete` | `expected_revision`, `inputs`, `key`, `outcomes`, `phase_id`, `task_id` |  |
| `phase_read` | `task_id` |  |
| `phase_restart` | `expected_revision`, `key`, `source_id`, `task_id` | `changed_inputs` |
| `provider_prepare` | `assignment_id`, `checkout`, `key`, `task_id` | `model` |
| `provider_read` | `run_id` |  |
| `publication_read` | `checkout`, `publication_kind`, `reference`, `task_id` | `asset_sha256`, `head` |
| `report_record` | `body`, `key`, `passed`, `task_id` | `subject` |
| `session_status` |  |  |
| `skill_start` | `expected_revision`, `key`, `skill`, `task_id` |  |
| `source_list` |  | `kind`, `limit` |
| `source_quote` | `digest`, `end`, `source_id`, `start` |  |
| `source_read` | `source_id` | `limit`, `start` |
| `source_restore` | `body`, `key`, `source_id`, `task_id` |  |
| `task_adopt` | `digest`, `end`, `expected_revision`, `key`, `reason`, `source_id`, `start`, `task_id` |  |
| `task_complete` | `expected_revision`, `key`, `outcomes`, `task_id` |  |
| `task_define` | `acceptance`, `goal`, `key`, `source_ids` | `dependencies` |
| `task_focus` | `key`, `task_id` |  |
| `task_list` |  | `all_project` |
| `task_read` | `task_id` |  |
| `task_resume` | `expected_revision`, `key`, `task_id` |  |
| `task_start` | `expected_revision`, `key`, `task_id` |  |
| `task_wait` | `expected_revision`, `key`, `reason`, `source_id`, `task_id` |  |
| `task_withdraw` | `digest`, `end`, `expected_revision`, `key`, `reason`, `source_id`, `start`, `task_id` |  |
| `verification_prepare` | `check_name`, `checkout`, `key`, `task_id` |  |
| `verification_read` | `execution_id` |  |
| `worktree_claim` | `checkout`, `key`, `task_id` | `create` |
| `worktree_read` | `checkout` |  |
| `worktree_release` | `checkout`, `generation`, `key` |  |

[코어 명세](core-v2-spec.md)
