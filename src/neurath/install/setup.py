"""A short, human-readable entry point over the existing installation engine."""

from neurath import doctor as diagnostics
from neurath.install.transaction import InstallError, apply_plan, make_plan


def next_steps(hosts):
    steps = [
        "대상 프로젝트의 에이전트에서 .neurath/project.json에 실제 문서 경로와 검증 명령을 연결하세요.",
    ]
    if "codex" in hosts:
        steps.append(
            "Codex에서 대상 프로젝트를 열고 프로젝트 신뢰 및 /hooks의 Neurath 훅을 검토하세요."
        )
    if "claude-code" in hosts:
        steps.append(
            "Claude Code에서 대상 프로젝트를 열고 /hooks에서 Neurath 훅 로딩을 확인하세요."
        )
    steps.append(
        "새 세션에서 작업을 요청하세요. 에이전트가 대상 프로젝트의 스킬을 접두어 없이 사용합니다."
    )
    return steps


def setup_project(root, *, profile=None, hosts=None, dry_run=False):
    if diagnostics.integrity()["status"] != "passed":
        raise InstallError("distribution integrity failed; obtain an intact Neurath distribution")
    plan = make_plan(root, profile=profile, hosts=hosts)
    result = {
        "root": str(root),
        "profile": plan["profile"],
        "hosts": plan["hosts"],
        "changes": [
            {"path": item["path"], "action": "remove" if item["after"] is None else "write"}
            for item in plan["changes"]
        ],
    }
    if dry_run:
        return {**result, "status": "planned"}
    result["receipt"] = apply_plan(root, plan)
    result["doctor"] = diagnostics.doctor(root, protocol=True)
    result["status"] = "passed" if diagnostics.passed(result["doctor"]) else "failed"
    result["next_steps"] = next_steps(plan["hosts"])
    return result


def show_setup(result):
    print(f"Neurath · {result['root']}")
    print(f"프로필: {result['profile']} | 호스트: {', '.join(result['hosts'])}")
    if result["status"] == "planned":
        print(
            f"미리보기: {len(result['changes'])}개 경로 변경 예정. 대상 파일을 수정하지 않았습니다."
        )
        for item in result["changes"]:
            print(f"  {item['action']}: {item['path']}")
        return
    print(f"설치 적용: {result['receipt']['changed']}개 경로 변경")
    report = result["doctor"]
    for label, key in (("배포본 무결성", "distribution"), ("파일 배치", "placement")):
        print(f"{label}: {report[key]['status']}")
        for error in report[key].get("errors", []):
            print(f"  {error}")
    for host, check in report["protocol"].items():
        if isinstance(check, dict):
            print(f"훅 프로토콜 ({host}): {check['status']}")
            if check["status"] == "failed" and check.get("diagnostic"):
                print(f"  {check['diagnostic']}")
    if result["status"] == "failed":
        print("설치는 적용됐지만 진단에 실패했습니다. .neurath/run doctor --protocol로 확인하세요.")
    else:
        print("설치 및 로컬 진단 완료. 실제 호스트 활성화는 아직 확인되지 않았습니다.")
    print("다음 단계:")
    for index, step in enumerate(result["next_steps"], 1):
        print(f"  {index}. {step}")
