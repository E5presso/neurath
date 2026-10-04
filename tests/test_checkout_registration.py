"""The tracked clone bootstrap must name the currently shipped core surface."""
from pathlib import Path

from neurath.install.configuration import _matches_checkout_bootstrap


def test_tracked_checkout_registration_is_recognized_before_self_install():
    root = Path(__file__).parents[1]
    for name in (".codex/config.toml", ".codex/hooks.json", ".claude/settings.json", ".mcp.json"):
        assert _matches_checkout_bootstrap(root, name, (root / name).read_text()), name
