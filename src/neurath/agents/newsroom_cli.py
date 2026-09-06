"""The same explicit article operations for native shells and the scoped MCP tool."""

from neurath.agents.identity import current_agent
from neurath.agents.newsroom import Newsroom
from neurath.agents.store import MessageStore


def add_commands(commands):
    parser = commands.add_parser("newsroom", help="Active 동료의 제목 알림과 선택적 기사 조회")
    sub = parser.add_subparsers(dest="newsroom_command", required=True)
    for name in ("publish", "revise", "comment"):
        action = sub.add_parser(name)
        if name != "publish":
            action.add_argument("article_id")
            action.add_argument("--revision", type=int, required=True)
        if name != "comment":
            action.add_argument("--title", required=True, help="본문을 대표하는 30자 이내 제목")
        action.add_argument("--body", required=True)
        action.add_argument("--key", required=True)
    read = sub.add_parser("read")
    read.add_argument("article_id")
    read.add_argument("--history", action="store_true", help="정정 이력과 댓글도 명시적으로 조회")
    read.add_argument("--after", type=int, default=0)
    read.add_argument("--limit", type=int, default=10)
    for name in ("headlines", "peers"):
        sub.add_parser(name).add_argument("--limit", type=int, default=20)
    sub.add_parser("seen").add_argument("event_id")


def run(root, args, *, identity=None):
    identity = identity or current_agent(root)
    room = Newsroom(MessageStore(root))
    fields = vars(args).copy()
    action = fields.pop("newsroom_command")
    for name in ("command", "root"):
        fields.pop(name, None)
    result = getattr(room, action)(identity.address, **fields)
    return {action: result} if isinstance(result, list) else result
