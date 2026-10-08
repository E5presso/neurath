"""Composition root. Host and database dependencies meet only here."""

import json
import subprocess
from pathlib import Path

from neurath import __version__
from neurath.transport.recovery import bypass


def project_root(worktree):
    root = Path(worktree).resolve()
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'], text=True, capture_output=True)
    if result.returncode == 0:
        common = Path(result.stdout.strip())
        if common.name == '.git':
            return common.parent
    return root


def database(worktree):
    from neurath.infrastructure import Database
    store = Database(project_root(worktree) / '.neurath/local/neurath.sqlite3')
    store.initialize()
    return store


def application(worktree):
    from neurath.application.service import Application
    return Application(database(worktree).uow)


def status(worktree):
    root = Path(worktree).resolve()
    receipt = root / '.neurath/install.json'
    installed = json.loads(receipt.read_text()) if receipt.is_file() else None
    return {'version': __version__, 'server_name': 'neurath', 'bypass': bypass(root),
            'installation': installed, 'native_activation': 'requires an observed host invocation'}
