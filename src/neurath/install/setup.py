"""A short, human-readable entry point over the existing installation engine."""

from neurath import doctor as diagnostics
from neurath.install.transaction import InstallError, apply_plan, make_plan


def next_steps(hosts, skill_prefix=""):
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
        f"Neurath 스킬은 /{skill_prefix}debug처럼 호출합니다. 기존 프로젝트 스킬의 이름은 유지합니다."
        if skill_prefix else
        "새 세션에서 작업을 요청하세요. 에이전트가 대상 프로젝트의 스킬을 접두어 없이 사용합니다."
    )
    return steps


def setup_project(root, *, profile=None, hosts=None, dry_run=False, skill_prefix=None,
                  auto_report=None):
    from neurath.reporting import Reporting

    if auto_report is not None and type(auto_report) is not bool:
        raise ValueError("auto_report must be an explicit boolean user decision")
    reporting = Reporting(root)
    reporting.status()  # Reject corrupt preferences before installation changes.
    if diagnostics.integrity()["status"] != "passed":
        raise InstallError("distribution integrity failed; obtain an intact Neurath distribution")
    plan = make_plan(root, profile=profile, hosts=hosts, skill_prefix=skill_prefix)
    result = {
        "root": str(root),
        "profile": plan["profile"],
        "hosts": plan["hosts"],
        "skill_prefix": plan["skill_prefix"],
        "reporting": reporting.status(),
        "changes": [
            {"path": item["path"], "action": "remove" if item["after"] is None else "write"}
            for item in plan["changes"]
        ],
    }
    if dry_run:
        return {**result, "status": "planned"}
    result["receipt"] = apply_plan(root, plan)
    if auto_report is not None:
        result["reporting"] = reporting.consent(auto_report)
    result["doctor"] = diagnostics.doctor(root, protocol=True)
    result["status"] = "passed" if diagnostics.passed(result["doctor"]) else "failed"
    result["next_steps"] = next_steps(plan["hosts"], plan["skill_prefix"])
    if result["reporting"]["consent_required"]:
        result["next_steps"].insert(0, "에이전트가 최초 설정에서 사용자에게 동의를 확인합니다: "
                                     + result["reporting"]["question"])
    return result


def show_setup(result):
    print(f"Neurath · {result['root']}")
    print(f"프로필: {result['profile']} | 호스트: {', '.join(result['hosts'])}")
    if result.get("skill_prefix"):
        print(f"Neurath 스킬 접두어: {result['skill_prefix']}")
    if result["status"] == "planned":
        print(
            f"미리보기: {len(result['changes'])}개 경로 변경 예정. 대상 파일을 수정하지 않았습니다."
        )
        for item in result["changes"]:
            print(f"  {item['action']}: {item['path']}")
        return
    print(f"설치 적용: {result['receipt']['changed']}개 경로 변경")
    consent = result["reporting"]["auto_report"]
    print("Neurath 자동 보고: " + ("켜짐" if consent is True else
                                     "꺼짐" if consent is False else "동의 대기 (보고 안 함)"))
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
        print("설치는 적용됐지만 진단에 실패했습니다. diagnostics_project MCP 도구의 protocol=true로 확인하세요.")
    else:
        print("설치 및 로컬 진단 완료. 실제 호스트 활성화는 아직 확인되지 않았습니다.")
    print("다음 단계:")
    for index, step in enumerate(result["next_steps"], 1):
        print(f"  {index}. {step}")
