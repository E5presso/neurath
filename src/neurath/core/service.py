"""Closed work commands under adapter-supplied identity; all progress stays in Task."""

import json
import subprocess
from pathlib import Path

from neurath.core.assignments import AssignmentCommands
from neurath.core.checks import COMMANDS as CHECK_COMMANDS
from neurath.core.checks import call as check_command
from neurath.core.codec import encode
from neurath.core.commands import validated
from neurath.core.communication import COMMANDS as COMMUNICATION_COMMANDS
from neurath.core.communication import call as communicate
from neurath.core.memory_commands import COMMANDS as MEMORY_COMMANDS
from neurath.core.memory_commands import MemoryCommands
from neurath.core.ownership import WorkspaceOwnership
from neurath.core.provenance import Provenance
from neurath.core.provider_commands import COMMANDS as PROVIDER_COMMANDS
from neurath.core.provider_commands import call as provider_command
from neurath.core.sessions import SessionLifecycle
from neurath.core.store import Store
from neurath.core.tasks import TaskCommands
from neurath.project_paths import control_root


class Core:
    def __init__(self, project_root, *, skills=None):
        self.worktree = Path(project_root).resolve()
        try:
            shared = control_root(self.worktree)
        except subprocess.CalledProcessError:
            shared = self.worktree
        self.store = Store(shared)
        self.sessions = SessionLifecycle(self.store)
        self.provenance = Provenance(self.store, self.sessions)
        self.tasks = TaskCommands(self.sessions, self.provenance, skills)
        self.assignments = AssignmentCommands(self.store, self.sessions, self.provenance)
        self.ownership = WorkspaceOwnership(self.store, self.sessions)
        self._memory_commands = None
        self.runtime_info = None
        self._handlers = {
            "worktree_read": self.ownership.worktree_read,
            "worktree_claim": self.ownership.worktree_claim,
            "worktree_release": self.ownership.worktree_release,
            "assignment_prepare": self.assignments.assignment_prepare,
            "assignment_read": self.assignments.assignment_read,
            "assignment_start": self.assignments.assignment_start,
            "assignment_report": self.assignments.assignment_report,
            "assignment_accept": self.assignments.assignment_accept,
            "assignment_reject": self.assignments.assignment_reject,
            "assignment_cancel": self.assignments.assignment_cancel,
            "session_status": self.sessions.session_status,
            "collaboration_discover": self.sessions.collaboration_discover,
            "task_list": self.tasks.task_list,
            "task_read": self.tasks.task_read,
            "task_focus": self.tasks.task_focus,
            "phase_read": self.tasks.phase_read,
            "task_define": self.tasks.task_define,
            "task_withdraw": self.tasks.task_withdraw,
            "task_adopt": self.tasks.task_adopt,
            "task_start": self.tasks.task_start,
            "skill_start": self.tasks.skill_start,
            "task_wait": self.tasks.task_wait,
            "task_resume": self.tasks.task_resume,
            "phase_restart": self.tasks.phase_restart,
            "phase_complete": self.tasks.phase_complete,
            "task_complete": self.tasks.task_complete,
            "source_list": self.provenance.source_list,
            "source_read": self.provenance.source_read,
            "source_quote": self.provenance.source_quote,
            "source_restore": self.provenance.source_restore,
            "evidence_list": self.provenance.evidence_list,
            "approval_record": self.provenance.approval_record,
            "report_record": self.provenance.report_record,
        }

    def call(self, context, name, values, *, guard=None):
        readonly = validated(name, values)
        if name in MEMORY_COMMANDS and self._memory_commands is None:
            self._memory_commands = MemoryCommands(self.worktree, self.store)

        def authenticate(tx):
            self.sessions.actor(tx, context)
            if guard is not None:
                guard(tx)

        observation = None
        installation = None
        if name == "session_status":
            with self.store.transaction() as tx:
                authenticate(tx)
            from neurath.core.diagnostics import installation_status

            installation = installation_status(self.worktree, self.runtime_info)
        if name == "publication_read":
            with self.store.transaction() as tx:
                authenticate(tx)
                tx.task(values["task_id"])
            from neurath.core.publications import observe

            observation = observe(self.store.root, values)

        def execute(tx):
            actor = self.sessions.actor(tx, context)
            if observation is not None:
                return self.provenance.publication(tx, context, values["task_id"], observation)
            result = self._execute(tx, context, actor, name, values)
            if installation is not None:
                result["runtime"] = self.runtime_info
                result["installation"] = installation
            if (
                name == "task_list"
                or not readonly
                and (name.startswith(("task_", "phase_", "skill_", "assignment_")))
            ):
                result["native_todo"] = self.sessions.todo(tx, context, actor)
            return result

        if readonly:
            with self.store.transaction() as tx:
                authenticate(tx)
                return json.loads(encode(execute(tx)))
        return self.store.command(
            context.actor_id,
            values["key"],
            name,
            {key: value for key, value in values.items() if key != "key"},
            execute,
            authenticate=authenticate,
        )

    def _execute(self, tx, context, actor, name, values):
        if name in PROVIDER_COMMANDS:
            return provider_command(tx, self.store, context, name, values)
        if name in CHECK_COMMANDS:
            return check_command(tx, self.store, context, actor, name, values)
        if name in COMMUNICATION_COMMANDS:
            return communicate(tx, context, name, values)
        if name in MEMORY_COMMANDS:
            return self._memory_commands.call(tx, context, actor, name, values)
        return self._handlers[name](tx, context, actor, values)
