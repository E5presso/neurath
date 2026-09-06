# New Ticket Intake

worker가 spawned issue를 보고할 때 이 reference를 사용합니다.

## 필수 check

1. worker가 follow-up issue를 보고하면 먼저 `.agents/rules/behavioral.md` Gap
   Triage decision이 있는지 확인합니다. 없으면 spawned work로 세지 않습니다.
2. follow-up issue는 `/create-ticket`으로 생성한 것을 선호합니다. worker가
   lower-level GitHub call을 사용했으면 같은 metadata contract로 검증합니다.
3. spawned GitHub Issue를 다시 읽습니다.
4. parent, milestone, label, assignee, blocked-by metadata를 확인합니다.
5. 현재 autopilot scope에 속하는지 확인합니다.
6. metadata 검증 후에만 DAG에 추가합니다.
7. 검증 실패 시 한 번 repair하고 다시 읽습니다.

검증되지 않은 issue ID는 spawned work로 세지 않습니다.
