"""Agent-operated local installation and transport entrypoints."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog='neurath')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('mcp', 'hook'):
        command = sub.add_parser(name)
        command.add_argument('--provider', choices=('codex', 'claude-code'), required=True)
    recovery = sub.add_parser('bypass')
    recovery.add_argument('--enabled', choices=('true', 'false'))
    check = sub.add_parser('check-run')
    check.add_argument('execution_id')
    sub.add_parser('status')
    install = sub.add_parser('install')
    install.add_argument('--source', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'mcp':
        from neurath.transport.mcp import serve
        serve(args.root, args.provider)
    elif args.command == 'hook':
        from neurath.transport.hooks import run
        run(args.root, args.provider)
    elif args.command == 'bypass':
        from neurath.transport.recovery import bypass
        print(json.dumps(bypass(args.root, None if args.enabled is None else args.enabled == 'true')))
    elif args.command == 'check-run':
        from neurath.transport.check_runner import run
        result = run(args.root, args.execution_id)
        print(json.dumps(result, ensure_ascii=False))
        code = result['exit_code']
        raise SystemExit(1 if code is None else code if code >= 0 else 128 - code)
    elif args.command == 'install':
        from neurath.install import install
        print(json.dumps(install(args.root, args.source), indent=2))
    else:
        from neurath.transport.runtime import status
        print(json.dumps(status(args.root), indent=2))
