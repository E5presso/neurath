"""Shared core service fixture."""

import subprocess

import pytest

from neurath.core.commands import Context
from neurath.core.domain import Condition, Phase, Skill
from neurath.core.service import Core


@pytest.fixture
def core(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    service = Core(
        tmp_path,
        skills={
            "test": Skill(
                "test",
                "1",
                (
                    Phase("analysis", (Condition("scope"),), frozenset({"read"})),
                    Phase(
                        "check",
                        (Condition("tested", frozenset({"check"})),),
                        frozenset({"read", "check"}),
                    ),
                ),
            )
        },
    )
    service.sessions.observe_actor("root", "session", "codex")
    service.sessions.observe_actor("child", "session", "codex", parent="root")
    context = Context("root", "session", "call-1")
    source = service.provenance.observe_user(context, "Fix and check the result", "user-event")
    result = service.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Result works",
            "source_ids": [source.id],
            "acceptance": [{"id": "works", "kinds": ["check"]}],
        },
    )
    return service, result["task"]["id"]
