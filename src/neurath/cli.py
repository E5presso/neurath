"""One installation engine for automation, onboarding agents, and the human wizard."""

import argparse
import json
import sys
from pathlib import Path

from neurath import __version__
from neurath.install.transaction import InstallError, apply_plan, make_plan, recover, repository
from neurath.install.projection import HOSTS, PROFILE_MODULES, PROFILES


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _native_or_terminal(root):
    import os
    from neurath.agents.identity import current_agent

    try:
        return current_agent(root)
    except (ValueError, RuntimeError):
        if any(os.environ.get(key) for key in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "NEURATH_TOOL_BINDING")):
            raise  # Failed native identity never becomes terminal authority.
        return None


def main(arguments=None):
    parser = argparse.ArgumentParser(prog="neurath")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    from neurath.memory.cli import add_commands

    add_commands(commands)
    from neurath.reporting_cli import add_commands as add_report_commands

    add_report_commands(commands)
    from neurath.updates_cli import add_commands as add_release_commands

    add_release_commands(commands)
    setup = commands.add_parser("setup", help="프로젝트 설치와 진단을 한 번에 실행")
    setup.add_argument("target", nargs="?", type=Path, help="대상 Git root (기본: 현재 폴더)")
    setup.add_argument("--profile", choices=PROFILES)
    setup.add_argument("--host", action="append", choices=HOSTS, dest="hosts")
    setup.add_argument(
        "--dry-run", action="store_true", help="대상 파일을 쓰지 않고 변경 목록 확인"
    )
    setup.add_argument("--json", action="store_true", help="자동화용 JSON 결과")
    setup.add_argument("--auto-report", choices=("yes", "no"),
                       help="사용자가 동의한 Neurath 자동 보고 설정; 생략하면 기존 선택 유지")
    plan = commands.add_parser("plan")
    plan.add_argument(
        "--action", choices=["install", "update", "uninstall", "restore"], default="install"
    )
    plan.add_argument("--profile", choices=PROFILES)
    plan.add_argument("--host", action="append", choices=HOSTS, dest="hosts")
    plan.add_argument(
        "--installation-id", "--receipt", dest="receipt", metavar="INSTALLATION_ID",
        help="되돌릴 설치 이력 ID (--receipt는 기존 명령과의 호환용)",
    )
    plan.add_argument("--output", type=Path, required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("plan", type=Path)
    installation_commands = []
    for action in ("install", "update", "uninstall"):
        sub = commands.add_parser(action)
        installation_commands.append(sub)
        sub.add_argument("--profile", choices=PROFILES)
        sub.add_argument("--host", action="append", choices=HOSTS, dest="hosts")
    restore = commands.add_parser("restore")
    restore.add_argument("receipt", metavar="INSTALLATION_ID", help="되돌릴 설치 이력 ID")
    commands.add_parser("recover")
    wizard = commands.add_parser("wizard")
    wizard.add_argument("--output", type=Path, help="새 비공개 계획 파일 (기본: Git 관리 디렉터리)")
    check = commands.add_parser("doctor")
    check.add_argument("--protocol", action="store_true")
    commands.add_parser("integrity")
    engine = commands.add_parser("engine")
    engine.add_argument("module")
    engine.add_argument("args", nargs=argparse.REMAINDER)
    skill = commands.add_parser("skill")
    skill.add_argument("name")
    skill.add_argument("script")
    skill.add_argument("args", nargs=argparse.REMAINDER)
    hook = commands.add_parser("hook")
    hook.add_argument("--host", required=True, choices=HOSTS)
    verify = commands.add_parser("verify")
    verify.add_argument("name")
    commands.add_parser("profile-check")
    commands.add_parser("session-status")
    provider = commands.add_parser("provider").add_subparsers(dest="provider_command", required=True)
    capabilities = provider.add_parser("capabilities")
    capabilities.add_argument("provider", choices=HOSTS)
    route = provider.add_parser("route")
    route.add_argument("provider", choices=HOSTS)
    route.add_argument("operation", choices=("create", "discover", "connect", "status", "message", "resume", "cancel", "peer"))
    for field in ("native-session", "model", "project-id", "message-id", "worktree", "assignment"):
        route.add_argument("--" + field, default="")
    route.add_argument("--requested-json", default="{}")
    provider_run = provider.add_parser("run")
    provider_run.add_argument("--worktree", required=True)
    provider_run.add_argument("--project-id", default="")
    provider_run.add_argument("--assignment", required=True)
    provider_run.add_argument("--provider", choices=("codex", "claude-code"), default="codex")
    provider_run.add_argument("--model", default="")
    provider_run.add_argument("--mode", choices=("inherit", "read-only", "workspace-write", "danger-full-access", "native"), default="inherit")
    provider_run.add_argument("--permission-mode", choices=("plan", "dontAsk", "default", "acceptEdits", "bypassPermissions", "auto"), default="")
    provider_run.add_argument("--plan-id", default="")
    provider_run.add_argument("--plan-revision", type=int, default=1)
    provider_run.add_argument("--assignment-revision", type=int, default=1)
    provider_run.add_argument("--reasoning-effort", default="")
    provider_run.add_argument("--approval-policy", choices=("never", "on-request", "untrusted"), default="")
    provider_run.add_argument("--approvals-reviewer", choices=("user", "auto_review"), default="")
    provider_run.add_argument("--collaboration-mode", choices=("default", "plan"), default="")
    provider_run.add_argument("--key", default="")
    for operation in ("status", "cancel"):
        provider.add_parser(operation).add_argument("run_id")
    delegate = commands.add_parser("delegate")
    delegate_commands = delegate.add_subparsers(dest="delegate_command", required=True)
    prepare = delegate_commands.add_parser("prepare")
    prepare.add_argument("--delegation-id", required=True)
    prepare.add_argument("--assignment", required=True)
    from neurath.agents.cli import add_commands as add_agent_commands

    add_agent_commands(commands, delegate_commands)
    from neurath.agents.newsroom_cli import add_commands as add_newsroom_commands

    add_newsroom_commands(commands)
    source = commands.add_parser("corpus")
    source.add_argument("destination", type=Path)
    for command_parser in (setup, plan, wizard, *installation_commands):
        command_parser.add_argument(
            "--skill-prefix", metavar="PREFIX",
            help="새 설치의 스킬 접두어 (예: neurath-); 생략하면 기존 설치 기록을 유지",
        )
    args = parser.parse_args(arguments)
    try:
        if args.command == "integrity":
            from neurath.doctor import integrity

            result = integrity()
            emit(result)
            return 0 if result["status"] == "passed" else 1
        if args.command == "corpus":
            import shutil

            from neurath.resources import BUNDLE

            if args.destination.exists():
                raise InstallError("corpus destination must not exist")
            shutil.copytree(
                BUNDLE, args.destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            emit(
                {
                    "destination": str(args.destination.resolve()),
                    "kind": "independent-runtime-reference",
                }
            )
            return 0
        root = repository((args.target or args.root) if args.command == "setup" else args.root)
        if args.command == "releases":
            from neurath.updates_cli import run as run_releases

            emit(run_releases(root, args))
            return 0
        if args.command == "report":
            from neurath.reporting_cli import run as run_report

            result = run_report(root, args)
            emit(result)
            return 1 if isinstance(result, dict) and result.get("status") == "uncertain" else 0
        if args.command == "provider":
            if args.provider_command in ("status", "cancel"):
                from neurath.runtime.tasks import execute

                emit(execute(root, "provider_" + args.provider_command, {"run_id": args.run_id},
                             identity=_native_or_terminal(root)))
                return 0
            if args.provider_command == "run":
                from neurath.runtime.provider_execution import run

                fields = {name: getattr(args, name) for name in ("worktree", "assignment", "model",
                    "provider", "mode", "permission_mode", "approval_policy", "approvals_reviewer", "collaboration_mode", "project_id", "key",
                    "plan_id", "plan_revision", "assignment_revision", "reasoning_effort")}
                result = run(root, fields, identity=_native_or_terminal(root))
                emit(result)
                return 0 if result["status"] in {"accepted", "starting", "completed"} else 1
            from neurath.runtime.tasks import provider_task

            fields = {"provider": args.provider}
            if args.provider_command == "route":
                fields.update({name: getattr(args, name) for name in (
                    "operation", "native_session", "model", "project_id", "message_id", "worktree", "assignment")})
                fields["requested"] = json.loads(args.requested_json)
            emit(provider_task("provider_" + args.provider_command, fields))
            return 0
        if args.command == "session-status":
            from neurath.runtime.tasks import session_status

            emit(session_status(root))
            return 0
        if args.command == "newsroom":
            from neurath.agents.newsroom_cli import run as run_newsroom

            emit(run_newsroom(root, args))
            return 0
        if args.command in {"memory", "learning"}:
            from neurath.memory.cli import run

            emit(run(root, args))
            return 0
        if args.command == "agent" or (
            args.command == "delegate" and args.delegate_command != "prepare"
        ):
            from neurath.agents.cli import run as run_agent

            result = run_agent(root, args)
            emit(result)
            if args.command == "delegate" and args.delegate_command in ("run", "resume"):
                return 0 if result["status"] == "completed" else 1
            return 0
        if args.command == "setup":
            from neurath.install.setup import setup_project, show_setup
            from neurath.reporting import Reporting, QUESTION

            decision = None if args.auto_report is None else args.auto_report == "yes"
            if (decision is None and not args.dry_run and not args.json and sys.stdin.isatty()
                    and Reporting(root).status()["consent_required"]):
                answer = input(QUESTION + " [y/N]: ").strip().lower()
                decision = answer in {"y", "yes"}

            result = setup_project(
                root, profile=args.profile, hosts=args.hosts, dry_run=args.dry_run,
                skill_prefix=args.skill_prefix, auto_report=decision,
            )
            emit(result) if args.json else show_setup(result)
            return 1 if result["status"] == "failed" else 0
        elif args.command == "plan":
            from neurath.install.plan import write_plan

            result = make_plan(
                root,
                action=args.action,
                profile=args.profile,
                hosts=args.hosts,
                receipt=args.receipt,
                skill_prefix=args.skill_prefix,
            )
            output = write_plan(root, result, args.output)
            emit(
                {
                    "plan": str(output),
                    "id": result["id"],
                    "changes": [
                        {"path": x["path"], "action": "remove" if x["after"] is None else "write"}
                        for x in result["changes"]
                    ],
                }
            )
        elif args.command == "apply":
            emit(apply_plan(root, json.loads(args.plan.read_text())))
        elif args.command in {"install", "update", "uninstall"}:
            emit(
                apply_plan(
                    root,
                    make_plan(root, action=args.command, profile=args.profile, hosts=args.hosts,
                              skill_prefix=args.skill_prefix),
                )
            )
        elif args.command == "restore":
            emit(apply_plan(root, make_plan(root, action="restore", receipt=args.receipt)))
        elif args.command == "recover":
            emit(recover(root))
        elif args.command == "wizard":
            from neurath.install.plan import write_plan

            profile = input(f"Profile ({', '.join(PROFILES)}) [generic]: ").strip() or "generic"
            hosts = (input("Hosts (codex,claude-code) [both]: ").strip() or ",".join(HOSTS)).split(
                ","
            )
            result = make_plan(root, profile=profile, hosts=hosts, skill_prefix=args.skill_prefix)
            output = write_plan(root, result, args.output)
            print(f"{len(result['changes'])} changes; inspect {output}")
            if input("Apply this plan? [y/N]: ").lower() == "y":
                emit(apply_plan(root, result))
        elif args.command == "doctor":
            from neurath.doctor import doctor, passed

            result = doctor(root, args.protocol)
            emit(result)
            return 0 if passed(result) else 1
        elif args.command == "hook":
            from neurath.hosts.hooks import run_hook

            return run_hook(root, args.host)
        elif args.command == "engine":
            from neurath.runtime.engine import run_engine

            return run_engine(root, args.module, args.args)
        elif args.command == "delegate":
            from neurath.runtime.engine import activate

            activate(root)
            from neurath.hosts.identity import prepare_delegation

            emit(prepare_delegation(root, args.delegation_id, args.assignment))
        elif args.command == "skill":
            from neurath.runtime.engine import run_skill

            return run_skill(root, args.name, args.script, args.args)
        elif args.command == "verify":
            from neurath.runtime.tasks import verification
            identity = _native_or_terminal(root)
            result = verification(root, args.name, identity=identity, require_owner=identity is not None)
            emit(result)
            return 0 if result["status"] == "passed" else 1
        elif args.command == "profile-check":
            import subprocess

            from neurath.install.transaction import read_state

            state = read_state(root)
            if not state:
                raise InstallError("not installed")
            results = []
            for module in PROFILE_MODULES[state["profile"]]:
                process = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-m",
                        "neurath",
                        "--root",
                        str(root),
                        "engine",
                        f"scripts.{module}",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                results.append(
                    {
                        "module": module,
                        "exit_code": process.returncode,
                        "diagnostic": (process.stdout + process.stderr)[-1500:],
                    }
                )
            emit({"profile": state["profile"], "checks": results})
            return 0 if all(x["exit_code"] == 0 for x in results) else 1
        return 0
    except (InstallError, ValueError, OSError, RuntimeError) as error:
        print(f"neurath: {error}", file=sys.stderr)
        return 2
