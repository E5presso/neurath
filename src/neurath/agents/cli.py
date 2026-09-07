"""Tools shared by both hosts; the sender is always resolved from native identity."""

import sys
import uuid
from pathlib import Path

from neurath.agents.identity import current_agent
from neurath.agents.store import MessageStore


def add_commands(commands, delegate_commands):
    agent = commands.add_parser("agent", help="독립 작업 간 메시지와 대화")
    sub = agent.add_subparsers(dest="agent_command", required=True)
    register = sub.add_parser("register")
    register.add_argument("--name", required=True)
    register.add_argument("--summary", default="")
    discover = sub.add_parser("discover")
    discover.add_argument("--query", default="")
    discover.add_argument("--limit", type=int, default=50)
    for name in ("inbox", "wait"):
        inbox = sub.add_parser(name)
        inbox.add_argument("--limit", type=int, default=20)
        inbox.add_argument("--conversation")
        if name == "inbox":
            inbox.add_argument("--include-read", action="store_true")
        else:
            inbox.add_argument("--timeout", type=float, default=30)
    send = sub.add_parser("send")
    send.add_argument("--to", required=True)
    send.add_argument("--message", required=True)
    send.add_argument("--key", required=True)
    send.add_argument(
        "--kind", choices=("question", "proposal", "update", "result"), default="question"
    )
    send.add_argument("--max-messages", type=int, default=32)
    send.add_argument("--ttl", type=int, default=86400)
    reply = sub.add_parser("reply")
    reply.add_argument("message_id")
    reply.add_argument("--message", required=True)
    reply.add_argument("--key", required=True)
    for name in ("message", "ack", "forward", "submitted"):
        parser = sub.add_parser(name)
        parser.add_argument("message_id")
        if name == "submitted":
            parser.add_argument("--transport", required=True)
    for name in ("conversation", "close"):
        sub.add_parser(name).add_argument("conversation")
    for name in ("subscribe", "unsubscribe"):
        sub.add_parser(name).add_argument("--to", required=True)
    publish = sub.add_parser("publish")
    publish.add_argument("--message", required=True)
    publish.add_argument("--key", required=True)
    start = delegate_commands.add_parser("run", help="선택한 provider와 model로 작업 실행")
    start.add_argument("--provider", choices=("codex", "claude-code"), required=True)
    start.add_argument("--model", required=True)
    start.add_argument("--assignment", required=True)
    start.add_argument("--id")
    start.add_argument("--context-file", type=Path)
    start.add_argument("--timeout", type=float, default=300)
    start.add_argument("--mode", choices=("read-only", "workspace-write"), default="read-only")
    start.add_argument("--worktree", type=Path)
    for name in ("status", "cancel", "resume"):
        parser = delegate_commands.add_parser(name)
        parser.add_argument("run_id")
        if name == "resume":
            parser.add_argument("--assignment", required=True)
            parser.add_argument("--timeout", type=float, default=300)
            parser.add_argument("--id")


def run(root, args, *, identity=None):
    if args.command == "delegate":
        identity = identity or current_agent(root)
        store = MessageStore(root)
        store.register(identity)
        return delegate(store, identity, args)
    from neurath.runtime.tasks import peer

    fields = vars(args).copy()
    action = fields.pop("agent_command")
    for name in ("command", "root"):
        fields.pop(name, None)
    if action != "discover":
        identity = identity or current_agent(root)
    return peer(root, action, fields, identity=identity)


def delegate(store, identity, args):
    from neurath.agents import runner

    action = args.delegate_command
    if action in ("run", "resume") and not identity.is_root:
        raise ValueError(
            "external worker creation requires the root actor; peers can still message directly"
        )
    if action in ("status", "cancel"):
        return getattr(runner, action)(store, identity.address, args.run_id)
    run_id = args.id or uuid.uuid4().hex
    print(f"Neurath provider run: {run_id}", file=sys.stderr, flush=True)
    if action == "resume":
        return runner.resume(
            store,
            identity.address,
            args.run_id,
            args.assignment,
            timeout=args.timeout,
            new_run_id=run_id,
        )
    context = ""
    if args.context_file:
        with args.context_file.open("rb") as stream:
            data = stream.read(262145)
        if len(data) > 262144:
            raise ValueError("context file exceeds 256 KiB")
        context = data.decode("utf-8")
    return runner.run(
        store,
        identity.address,
        provider=args.provider,
        model=args.model,
        assignment=args.assignment,
        context=context,
        timeout=args.timeout,
        mode=args.mode,
        worktree=args.worktree,
        run_id=run_id,
    )
