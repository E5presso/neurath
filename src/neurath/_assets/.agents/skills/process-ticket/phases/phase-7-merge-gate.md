# 병합 결정 참고

이 문서는 `monitoring`과 `merge_cleanup`의 병합 판단을 설명한다. 별도 진행 원장이나 추가 phase가 아니다.

실제 PR head와 모든 required checks, 독립 리뷰, ai-review, GitHub approval, unresolved threads를 확인한다. 사용자의 명시적 병합 요청 또는 `--auto-merge` 범위 안이면 승인을 다시 묻지 않는다. PR만 요청받은 경우에는 정의된 `pr-ready` 결과로 반환하고 병합했다고 보고하지 않는다.
