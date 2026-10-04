"""Shared core service fixture."""

import subprocess

import pytest

from neurath.core.domain import Condition, Phase, Skill
from neurath.core.service import Context, Core


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
    service.observe_actor("root", "session", "codex")
    service.observe_actor("child", "session", "codex", parent="root")
    context = Context("root", "session", "call-1")
    source = service.observe_user(context, "Fix and check the result", "user-event")
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
