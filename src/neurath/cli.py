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


def main(arguments=None):
    parser = argparse.ArgumentParser(prog="neurath")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    from neurath.memory.cli import add_commands

    add_commands(commands)
    setup = commands.add_parser("setup", help="프로젝트 설치와 진단을 한 번에 실행")
    setup.add_argument("target", nargs="?", type=Path, help="대상 Git root (기본: 현재 폴더)")
    setup.add_argument("--profile", choices=PROFILES)
    setup.add_argument("--host", action="append", choices=HOSTS, dest="hosts")
    setup.add_argument(
        "--dry-run", action="store_true", help="대상 파일을 쓰지 않고 변경 목록 확인"
    )
    setup.add_argument("--json", action="store_true", help="자동화용 JSON 결과")
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
    for action in ("install", "update", "uninstall"):
        sub = commands.add_parser(action)
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

            result = setup_project(
                root, profile=args.profile, hosts=args.hosts, dry_run=args.dry_run
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
                    make_plan(root, action=args.command, profile=args.profile, hosts=args.hosts),
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
            result = make_plan(root, profile=profile, hosts=hosts)
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
            from neurath.runtime.verification import VerificationError, verify

            config = json.loads((root / ".neurath/project.json").read_text())
            binding = config.get("verification", {}).get(args.name)
            if binding is None:
                raise VerificationError(
                    f"unbound verifier: {args.name}; configure project.json verification"
                )
            result = verify(root, binding)
            if args.name == "check":
                from neurath.memory.cli import native_session
                from neurath.memory.learning import Learning
                from neurath.memory.store import ProjectMemory

                try:
                    host, session = native_session(root)
                except (ValueError, RuntimeError):
                    pass  # A standalone check grants no host-attested learning result.
                else:
                    from neurath.hosts.identity import snapshot
                    from neurath.memory.transcript import synchronize

                    memory = ProjectMemory(root)
                    synchronize(memory, root, host, session, snapshot(root, session))
                    Learning(memory).verified(host, session, result)
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
