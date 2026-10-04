# 실제 검증

work item의 인수 조건을 현재 결과와 대조한다. 명시된 executable acceptance와 focused test, 프로젝트 필수 검사를 실제 올바른 작업 경로에서 실행한다. 없는 검사 명령이나 성공 결과를 만들지 않는다.

프로젝트에 정의된 검사는 실제 command/cwd와 종료 결과로 관측한다. 실행 중인 handle, 출력에 적힌 PASS, agent report는 native check evidence가 아니다. 코드를 바꾸면 이전 검사 결과가 새 코드를 증명하지 않는다.

`acceptance_result`는 각 인수 조건의 결과를 설명한다. 필요한 `focused_test_result`, `pre_commit_result`는 실제 check evidence를 참조한다. 실행 가능한 검사가 없는 합당한 경우에는 정의된 검증 경로와 부족한 보증을 명시한다. 사용자에게 요구한 결과 자체가 미완료이면 다음 단계로 진행하지 않는다.
