# Upstream 보고 실행 참조

[English](../../en/contributing/reporting-reference.md) · **한국어**

[사용자 동작](../usage/reporting.md)을 제품 계약으로 사용합니다. 보고 명령은 네이티브 셸에서
현재 호스트의 소유권·실행·네트워크 정책을 따릅니다. 자동 승인되는 MCP 변경 도구에 전송을
넣지 않습니다. 기존에 인증한 GitHub CLI를 사용하며 보고를 위해 권한을 바꾸거나 자격 증명을
수집하지 않습니다.

설치 에이전트는 status가 반환한 질문 전체로 동의를 받습니다. 첫 대화형 setup은 직접 묻고,
비대화형 setup은 동의 질문을 반환하되 자동 보고가 꺼진 상태로 설치합니다.
기존 설치에도 온보딩 안내를 제공합니다. 미응답은 동의가 아니며 다른 작업을 막지 않습니다.
같은 온보딩 대화에서 질문을 반복하지 않고, 거절한 뒤에는 사용자 의도 없이 다시 묻지 않습니다.

```sh
neurath setup /path/to/project --auto-report yes
.neurath/run report status
.neurath/run report consent no --user-confirmed
```

명시적인 사용자 답변을 받은 뒤에만 yes/no를 전달합니다. 업데이트 시 옵션을 생략하면 기존
선택을 유지하며 dry-run은 저장하지 않습니다. 동의와 초안은 Git 공통 관리 디렉터리의
`neurath-reporting/state.json`에 보관합니다. 체크아웃에 포함하지 않으며 업데이트·제거·복원으로
동의를 되돌리거나 다른 clone에 복사하지 않습니다. 비공개 파일, 원자적 교체와 프로세스 간
잠금으로 저장하며 설정이 손상되면 보고를 차단합니다.

보고용 JSON은 다음 필드만 허용합니다.

```json
{
  "kind": "defect",
  "scope": "common",
  "component": "cli.py",
  "summary": "설치가 명시적 선택을 잃음",
  "expected": "선택한 호스트를 유지한다.",
  "observed": "반복 설치가 호스트 선택을 초기화한다.",
  "reproduction": "비어 있는 임시 Git 저장소에서 설치를 반복한다.",
  "proposal": "업데이트 시 설치된 호스트 선택을 유지한다."
}
```

위 내용은 설명용 예시이며 현재 결함을 주장하지 않습니다. kind는 `defect`, `improvement`,
`contribution`, scope는 `common`, `project-specific`입니다. project-specific은
contribution에서만 허용하지만 내용은 항상 Neurath만 설명해야 합니다.
component는 manifest에 있는 패키지 상대 경로입니다. 공통 보고는 수정된 패키지 구성 요소와
전용화된 설치 자산을 거부합니다. 이 검사로 의미상의 원인을 증명할 수는 없으므로,
에이전트가 일반적인 임시 환경에서 재현하고 Neurath의 공통 동작인지 확인해야 합니다.

```sh
.neurath/run report prepare /private/local/report.json --privacy-reviewed
.neurath/run report read REPORT_ID
.neurath/run report submit REPORT_ID
```

privacy-reviewed 플래그는 실제 의미 검토를 수행했다는 표명이며 자동 정제 기능이 아닙니다.
로그·소스·환경·대화·첨부를 자동 수집하지 않습니다. 허용 필드, 길이 제한, 알려진 프로젝트·
원격 식별자, 경로·URL·자격 증명 패턴도 검사합니다. 정규식으로 임의의 업무 정보를 모두
식별할 수는 없습니다. 정보 제외나 공통 범위가 불확실하면 준비·전송하지 않습니다.

배포 템플릿은 `src/neurath/templates/`, 사용자가 GitHub에서 선택하는 대응 템플릿은
`.github/ISSUE_TEMPLATE/`에 있습니다. 제목과 렌더링된 본문 전체를 해시하여 초안 ID를
만듭니다. 기여 동의는 정확한 ID에 결속합니다.

```sh
.neurath/run report approve REPORT_ID yes --user-confirmed
.neurath/run report submit REPORT_ID
```

반환된 제목·본문·고정 대상 저장소를 보여 준 뒤 동의를 받습니다. 거절은 같은 명령의 no로
기록합니다. 자동 보고 설정으로 기여를 승인할 수 없으며 아이디어에 대한 동의를 사용자가
보지 못한 프로젝트 정보의 공개 동의로 해석하지 않습니다.

목적지는 `github.com/E5presso/neurath`로 고정합니다. 인자 배열, 비공개 본문 파일,
프로젝트 밖 임시 작업 디렉터리, 대화형 질문 비활성화와 기존 GitHub 인증을 사용합니다.
원격 URL·제목·본문을 확인합니다. 로컬 잠금으로 동시 중복 전송을 막고 네트워크 호출 전에
uncertain을 저장합니다. 중단·시간 초과·인증 실패·원격 확인 실패는 자동 재시도하지 않습니다.
중복 방지는 로컬 Git 프로젝트 안의 동일한 렌더링 초안 단위이며 여러 프로젝트 사이의
의미상 중복 탐지 기능은 아닙니다.

```sh
.neurath/run report list
.neurath/run report read REPORT_ID
.neurath/run report reconcile REPORT_ID https://github.com/E5presso/neurath/issues/123
```

reconcile은 내용이 정확히 일치하는 기존 이슈만 확인하며 새 이슈를 만들지 않습니다.
이슈가 없으면 불확실한 기록을 보존하고 실패를 설명합니다. 새 전송에는 운영자의 명시적인
검토가 필요합니다. 보고 문제로 Stop을 막거나 workflow 성공을 만들지 않습니다.
훅은 안내만 추가하며 네트워크·백그라운드 작업·동료나 세션 생성을 수행하지 않습니다.

[설치 설계](installation-design.md) · [검증](validation.md)
