"""Read project recall anywhere; write checkpoints only as the actual native actor."""

import uuid

from neurath.memory.learning import Learning
from neurath.memory.store import ProjectMemory
from neurath.runtime.engine import activate


def native_session(root):
    import os

    activate(root)
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle

    binding = RuntimeEnvironmentResolver().resolve(os.environ)
    handle = StateHandle.attach(SessionLocator.from_worktree(root), binding)
    if not binding.is_root:
        raise ValueError("project checkpoints require the root actor")
    handle.inspect()
    return binding.runtime.value, str(binding.session_id)


def add_commands(commands):
    memory = commands.add_parser("memory", help="프로젝트 작업 기록 조회와 인계")
    sub = memory.add_subparsers(dest="memory_command", required=True)
    recall = sub.add_parser("recall")
    recall.add_argument("--query", default="")
    recall.add_argument("--limit", type=int, default=12)
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--summary", required=True)
    checkpoint.add_argument("--decision", action="append", default=[])
    checkpoint.add_argument("--next-step", action="append", default=[])
    checkpoint.add_argument("--lesson", action="append", default=[])
    checkpoint.add_argument(
        "--status", choices=["active", "paused", "completed", "blocked"], default="paused"
    )
    checkpoint.add_argument("--id", default=None)
    learning = commands.add_parser("learning", help="학습한 실행 전략과 검증 이력")
    sub = learning.add_subparsers(dest="learning_command", required=True)
    sub.add_parser("status")
    sub.add_parser("pending")
    defer = sub.add_parser("defer")
    defer.add_argument("--reason", required=True)
    history = sub.add_parser("history")
    history.add_argument("lesson")


def run(root, args):
    memory = ProjectMemory(root)
    if args.command == "learning":
        engine = Learning(memory)
        if args.learning_command in ("pending", "defer"):
            host, session = native_session(root)
            if args.learning_command == "pending":
                return engine.pending(host, session)
            return {
                "status": "deferred",
                "count": engine.defer(host, session, args.reason),
                "authority": "agent-report",
            }
        return engine.status() if args.learning_command == "status" else engine.history(args.lesson)
    if args.memory_command == "recall":
        return memory.recall(args.query, limit=args.limit)
    host, session = native_session(root)
    identity = memory.checkpoint(
        host,
        session,
        "checkpoint:" + (args.id or uuid.uuid4().hex),
        summary=args.summary,
        decisions=args.decision,
        next_steps=args.next_step,
        lessons=args.lesson,
        status=args.status,
    )
    return {
        "status": "saved",
        "id": identity,
        "host": host,
        "session": session,
        "authority": "agent-report",
    }
