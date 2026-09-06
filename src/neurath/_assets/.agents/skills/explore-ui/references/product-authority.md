# Neurath 제품·UI 정본

## Authority 순서

화면을 만들기 전에 현재 checkout에서 다음을 직접 읽습니다.

1. `.neurath/project.json (documents 슬롯)`: 제품 용어와 대외용어
2. `.neurath/project.json (documents 슬롯)`: Neurath와 세 표면의 제품 의도
3. `.neurath/project.json (documents 슬롯)`: 확정된 기능과 요구사항
4. `.neurath/project.json (documents 슬롯)`: 현재 남아 있는 제품 결정
5. accepted `docs/decisions/*.md`: 현재 architecture와 workflow 경계

현재 checkout과 상태를 다시 확인하며 이전 대화나 memory만으로 authority를 닫지 않습니다.
`Draft`, `사용자 검수 대기`, `임시값`, `미정`, `폐기`를 accepted 결정으로 바꾸지 않습니다.

## Clean slate

Repository에 design token, brand asset, component catalog, screen specification 또는
visual decision이 없으면 그 부재가 현재 정본입니다. 이를 이전 Git history, memory,
runtime record 또는 삭제된 canvas에서 복원하지 않습니다.

Clean slate는 design content가 없다는 뜻이지 collaboration capability가 없다는 뜻이
아닙니다. `.agents/design-collaboration-policy.json`, 네 UI collaboration skill,
`tool:design_canvas` mapping, connector 등록과 regression oracle은 보존합니다.

## 제품 표면

Canonical 용어는 `상주형(resident surface)`, `모바일(mobile surface)`,
`웹(web surface)`입니다. 각 표면의 기능·권한·감지원 차이는 current product spec에서
읽고, 이전 화면 topology나 배치 결정을 복원하지 않습니다.

## 화면과 content provenance

Current product source에 없는 기능, 통계, 추천, shortcut, dashboard module을 후보를 채우기
위해 만들지 않습니다. 화면 안 text와 data는 다음 중 하나에 근거해야 합니다.

- current product requirement의 기능상 label 또는 state
- Domain Dictionary의 대외용어
- 비교를 위해 고정한 현실적인 sample user data
- 실제 interaction에 필요한 짧은 error, recovery 또는 confirmation 정보

Sample data는 data임을 분명히 하고 제품 주장이나 marketing copy로 확대하지 않습니다.
확인 요청은 action, tool, 상태 변경 여부, 가역성과 예약 근거 중 해당하는 내용을
보여 주며 승인과 거부를 받습니다.

## Runtime-owned visual

실제 renderer가 소유하는 visual은 runtime source와 state contract를 읽습니다. Canvas에서는
runtime capture·static export 또는 slot만 사용하고 외형이나 motion을 재구성하지 않습니다.
