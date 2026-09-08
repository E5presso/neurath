"""Native agent interface; user decisions are never exposed as auto-approved MCP calls."""

from neurath.updates import Updates


def add_commands(commands):
    sub = commands.add_parser("releases").add_subparsers(dest="release_command", required=True)
    for name in ("status", "notice", "recover"):
        sub.add_parser(name)
    sub.add_parser("check").add_argument("--force", action="store_true")
    for name in ("prepare", "apply", "choose"):
        parser = sub.add_parser(name)
        parser.add_argument("id")
        if name == "choose":
            parser.add_argument("decision", choices=("yes", "no", "later"))
            parser.add_argument("--user-confirmed", action="store_true", required=True)


def run(root, args):
    if args.release_command != "status":
        from neurath.cli import _native_or_terminal
        from neurath.runtime.tasks import _verification_owner
        identity = _native_or_terminal(root)
        if identity is not None:
            _verification_owner(root, identity)
    service = Updates(root)
    match args.release_command:
        case "check":
            return service.check(force=args.force)
        case "choose":
            return service.choose(args.id, args.decision, user_confirmed=args.user_confirmed)
        case "prepare" | "apply":
            return getattr(service, args.release_command)(args.id)
        case _:
            return getattr(service, args.release_command)()
