"""Native host reporting commands; publishing never runs inside an auto-approved MCP."""

import json
from pathlib import Path

from neurath.reporting import Reporting


def add_commands(commands):
    report = commands.add_parser("report", help="동의 기반 Neurath 공통 하네스 보고")
    sub = report.add_subparsers(dest="report_command", required=True)
    sub.add_parser("status")
    sub.add_parser("list")
    consent = sub.add_parser("consent")
    consent.add_argument("decision", choices=("yes", "no"))
    consent.add_argument("--user-confirmed", action="store_true", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("file", type=Path)
    prepare.add_argument("--privacy-reviewed", action="store_true", required=True)
    for name in ("read", "approve", "submit", "reconcile"):
        command = sub.add_parser(name)
        command.add_argument("id")
        if name == "approve":
            command.add_argument("decision", choices=("yes", "no"))
            command.add_argument("--user-confirmed", action="store_true", required=True)
        if name == "reconcile":
            command.add_argument("url")


def run(root, args):
    if args.report_command not in {"status", "read", "list"}:
        from neurath.cli import _native_or_terminal
        from neurath.runtime.tasks import _verification_owner

        identity = _native_or_terminal(root)
        if identity is not None:
            _verification_owner(root, identity)
    service = Reporting(root)
    match args.report_command:
        case "status":
            return service.status()
        case "list":
            return service.list_reports()
        case "consent":
            return service.consent(args.decision == "yes")
        case "prepare":
            if args.file.stat().st_size > 20000:
                raise ValueError("report input exceeds the bounded template")
            return service.prepare(json.loads(args.file.read_text()),
                                   privacy_reviewed=args.privacy_reviewed)
        case "approve":
            return service.approve(args.id, decision=args.decision == "yes")
        case "read":
            return service.read(args.id)
        case "submit":
            return service.submit(args.id)
        case "reconcile":
            return service.reconcile(args.id, args.url)
