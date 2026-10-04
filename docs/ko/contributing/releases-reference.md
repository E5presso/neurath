# 릴리스 조회와 적용

[English](../../en/contributing/releases-reference.md) · [코어 계약](core-v2-spec.md)

에이전트는 네이티브 `releases check`를 실행하고 `releases notice`를 확인한 뒤 정확한 후보를 준비한다. 사용자의 yes/no/later 선택을 받아 같은 후보에 기록하고 승인된 후보를 적용한다. 인자는 `updates_cli.py`의 현재 parser에서 확인한다. 미응답은 동의가 아니다. 불변 후보가 바뀌면 이전 선택을 재사용할 수 없다.

후보 설치는 버전·배포 식별자·wheel 해시를 확인하면서 사용자 파일과 보고 동의를 보존한다. 적용이 중단되면 무작정 재적용하지 않고 복구한다. 소스 변경·설치·실제 활성화·공개 릴리스는 각각 관측한다. 게시에는 검증된 wheel과 리뷰한 commit을 가리키는 tag가 필요하며 `publication_read`로 GitHub 릴리스 상태를 확인한다.
