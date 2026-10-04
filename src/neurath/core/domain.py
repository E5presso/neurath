"""Immutable work contracts and transitions, independent of hosts and persistence."""

from dataclasses import dataclass, replace
from hashlib import sha256


class CoreError(ValueError):
    def __init__(self, code, **details):
        self.code = code
        self.details = details
        super().__init__(code + (": " + str(details) if details else ""))


def require(predicate, code, **details):
    if not predicate:
        raise CoreError(code, **details)


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    kind: str
    text: str
    event_id: str
    digest: str

    @classmethod
    def create(cls, identifier, kind, text, event_id):
        require(kind in {"native_input", "user", "tool", "report"}, "source-kind")
        require(bool(identifier and event_id), "source-identity")
        return cls(identifier, kind, text, event_id, sha256(text.encode()).hexdigest())


def quote(source, start, end, digest):
    require(source.digest == digest == sha256(source.text.encode()).hexdigest(), "source-changed")
    require(
        type(start) is int and type(end) is int and 0 <= start < end <= len(source.text),
        "quote-range",
    )
    return source.text[start:end]


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    kind: str
    source_id: str
    actor_id: str
    subject: str
    passed: bool
    operation: str | None = None


@dataclass(frozen=True, slots=True)
class Condition:
    id: str
    kinds: frozenset[str] = frozenset({"report"})
    subject_key: str | None = None
    expected_pass: bool = True
    operation: str | None = None
    when: tuple[str, str] | None = None

    def __post_init__(self):
        require(
            isinstance(self.id, str) and bool(self.id.strip()) and bool(self.kinds),
            "condition-definition",
        )
        require(
            self.kinds <= {"report", "check", "review", "publication", "observation", "approval"},
            "condition-definition",
        )
        require(type(self.expected_pass) is bool, "condition-definition")
        require(
            self.operation is None or isinstance(self.operation, str) and bool(self.operation),
            "condition-definition",
        )
        require(
            self.when is None
            or isinstance(self.when, tuple)
            and len(self.when) == 2
            and all(isinstance(value, str) and value for value in self.when),
            "condition-definition",
        )


@dataclass(frozen=True, slots=True)
class Phase:
    id: str
    requires: tuple[Condition, ...] = ()
    # Retained only to decode older candidate snapshots; not an execution policy.
    effects: frozenset[str] = frozenset()
    restart_from: str | None = None
    subskills: frozenset[str] = frozenset()
    choices: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class Skill:
    id: str
    version: str
    phases: tuple[Phase, ...]
    acceptance_restart_from: str | None = None

    def __post_init__(self):
        ids = [p.id for p in self.phases]
        require(
            bool(self.id and self.version and ids) and all(ids) and len(ids) == len(set(ids)),
            "skill-definition",
        )
        for index, phase in enumerate(self.phases):
            require(
                phase.restart_from is None or phase.restart_from in ids[: index + 1],
                "skill-definition",
            )
            conditions = [c.id for c in phase.requires]
            require(all(conditions) and len(conditions) == len(set(conditions)), "skill-definition")
            choices = dict(phase.choices)
            require(
                len(choices) == len(phase.choices) and all(values for values in choices.values()),
                "skill-definition",
            )
            require(
                all(
                    c.when is None or c.when[0] in choices and c.when[1] in choices[c.when[0]]
                    for c in phase.requires
                ),
                "skill-condition-choice",
            )
        require(
            self.acceptance_restart_from is None or self.acceptance_restart_from in ids,
            "skill-definition",
        )


def validate_conditions(conditions, outcomes, inputs):
    require(set(outcomes) <= {c.id for c in conditions}, "unknown-condition")
    for condition in conditions:
        if condition.when is not None and inputs.get(condition.when[0]) != condition.when[1]:
            require(condition.id not in outcomes, "inactive-condition", condition=condition.id)
            continue
        items = outcomes.get(condition.id, ())
        require(
            bool(items) and all(e.passed == condition.expected_pass for e in items),
            "condition-unmet",
            condition=condition.id,
        )
        require(
            all(e.kind in condition.kinds for e in items), "evidence-kind", condition=condition.id
        )
        require(
            condition.operation is None or all(e.operation == condition.operation for e in items),
            "evidence-operation",
            condition=condition.id,
        )
        if condition.subject_key is not None:
            expected = inputs.get(condition.subject_key)
            require(
                expected is not None and all(e.subject == expected for e in items),
                "subject-changed",
                condition=condition.id,
            )


@dataclass(frozen=True, slots=True)
class PhaseCompletion:
    phase_id: str
    outcomes: tuple[tuple[str, tuple[str, ...]], ...]
    inputs: tuple[tuple[str, str], ...]

    @property
    def evidence_ids(self):
        return tuple(identifier for _, identifiers in self.outcomes for identifier in identifiers)


def validate_reuse(previous, outcomes, inputs):
    for condition, items in outcomes.items():
        for evidence in items:
            consumers = [result for result in previous if evidence.id in result.evidence_ids]
            if consumers:
                matching = [
                    result
                    for result in consumers
                    if evidence.id in dict(result.outcomes).get(condition, ())
                ]
                require(bool(matching), "evidence-condition-changed", evidence_id=evidence.id)
                require(
                    any(dict(result.inputs) == inputs for result in matching),
                    "evidence-input-changed",
                    evidence_id=evidence.id,
                )


@dataclass(frozen=True, slots=True)
class Attempt:
    number: int
    completions: tuple[PhaseCompletion, ...]
    failure_source: str
    changed_inputs: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class SkillRun:
    skill: Skill
    completions: tuple[PhaseCompletion, ...] = ()
    attempt: int = 1
    history: tuple[Attempt, ...] = ()
    parent_index: int | None = None

    @property
    def complete(self):
        return len(self.completions) == len(self.skill.phases)

    @property
    def current(self):
        return None if self.complete else self.skill.phases[len(self.completions)]

    def advance(self, phase_id, outcomes, inputs):
        require(
            self.current is not None and self.current.id == phase_id,
            "phase-order",
            current=None if self.current is None else self.current.id,
        )
        for key, choices in self.current.choices:
            require(inputs.get(key) in choices, "phase-choice-required", choice=key)
        validate_conditions(self.current.requires, outcomes, inputs)
        previous = [completion for attempt in self.history for completion in attempt.completions]
        validate_reuse(previous, outcomes, inputs)
        completion = PhaseCompletion(
            phase_id,
            tuple((key, tuple(e.id for e in items)) for key, items in sorted(outcomes.items())),
            tuple(sorted(inputs.items())),
        )
        return replace(self, completions=(*self.completions, completion))

    def restart(self, failure_source, changed_inputs):
        require(bool(failure_source), "failure-source-required")
        target = self.skill.acceptance_restart_from if self.complete else self.current.restart_from
        if target is None:
            target = self.skill.phases[0].id if self.complete else self.current.id
        index = next(i for i, phase in enumerate(self.skill.phases) if phase.id == target)
        if changed_inputs is None:
            index = 0
        else:
            affected = [
                i
                for i, result in enumerate(self.completions)
                if set(changed_inputs) & {key for key, _ in result.inputs}
            ]
            if affected:
                index = min(index, min(affected))
        return replace(
            self,
            completions=self.completions[:index],
            attempt=self.attempt + 1,
            history=(
                *self.history,
                Attempt(
                    self.attempt,
                    self.completions,
                    failure_source,
                    None if changed_inputs is None else tuple(changed_inputs),
                ),
            ),
        )


def select_execution(choice, source_provider, target_provider, reason):
    require(choice in {"subagent", "session", "cross-provider"}, "execution-choice")
    require(
        source_provider in {"codex", "claude-code"} and target_provider in {"codex", "claude-code"},
        "provider",
    )
    if choice != "subagent":
        require(bool(reason.strip()), "execution-reason")
    require((source_provider != target_provider) == (choice == "cross-provider"), "provider-choice")
    return choice


@dataclass(frozen=True, slots=True)
class Assignment:
    id: str
    execution: str
    scope: str
    issuer: str
    recipient: str
    subject: str
    state: str = "issued"
    result_source: str | None = None
    verdict: str | None = None
    acceptance_owner: str | None = None
    role: str = "worker"
    result_subject: str | None = None
    run_index: int | None = None
    phase_id: str | None = None
    attempt: int | None = None

    @property
    def awaiting_result(self):
        return self.state in {"issued", "active", "cancel-requested"}

    def bind(self, recipient):
        require(self.state == "issued", "assignment-state")
        require(not self.recipient or self.recipient == recipient, "recipient-rebinding")
        require(recipient != self.issuer, "assignment-self")
        return replace(self, recipient=recipient)

    def recipient_ended(self, source, *, verdict="failed"):
        if not self.awaiting_result:
            return self
        return self.report(
            self.recipient,
            source,
            "cancelled" if self.state == "cancel-requested" else verdict,
            self.subject,
        )

    def cancel_unstarted(self, source):
        require(
            not self.recipient and self.state in {"issued", "cancel-requested"}, "assignment-state"
        )
        return replace(self, state="rejected", result_source=source, verdict="cancelled")

    def launch_failed(self):
        require(
            not self.recipient and self.state in {"issued", "cancel-requested"}, "assignment-state"
        )
        return replace(self, state="rejected", verdict="failed")

    def start(self, actor):
        require(actor == self.recipient, "actor-mismatch")
        require(self.state == "issued", "assignment-state")
        return replace(self, state="active")

    def report(self, actor, source, verdict, subject):
        require(actor == self.recipient, "actor-mismatch")
        require(self.state in {"issued", "active", "cancel-requested"}, "assignment-state")
        require(
            bool(source) and verdict in {"pass", "failed", "blocked", "cancelled"},
            "assignment-result",
        )
        require(self.role != "reviewer" or subject == self.subject, "subject-changed")
        require(
            self.state != "cancel-requested" or verdict == "cancelled", "assignment-cancel-pending"
        )
        return replace(
            self, state="reported", result_source=source, verdict=verdict, result_subject=subject
        )

    def accept(self, actor, source, subject, *, acceptors=None):
        allowed = {self.acceptance_owner or self.issuer} if acceptors is None else acceptors
        require(actor in allowed, "actor-mismatch")
        require(self.state == "reported" and source == self.result_source, "assignment-result")
        require(self.verdict == "pass", "assignment-unsuccessful")
        require(subject == self.result_subject, "subject-changed")
        return replace(self, state="accepted")

    def reject(self, actor, source, *, acceptors=None):
        allowed = {self.acceptance_owner or self.issuer} if acceptors is None else acceptors
        require(actor in allowed, "actor-mismatch")
        require(self.state == "reported" and source == self.result_source, "assignment-result")
        return replace(self, state="rejected")

    def cancel(self):
        require(self.state in {"issued", "active"}, "assignment-state")
        return replace(self, state="cancel-requested")


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    owner_session: str
    owner_actor: str
    goal: str
    instruction_sources: tuple[str, ...]
    acceptance: tuple[Condition, ...]
    revision: int = 1
    ownership_generation: int = 1
    state: str = "open"
    skill_runs: tuple[SkillRun, ...] = ()
    assignments: tuple[Assignment, ...] = ()
    attempts: tuple[tuple[str, str], ...] = ()
    completion_evidence: tuple[str, ...] = ()
    withdrawal_source: str | None = None
    implementation_actors: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

    def __post_init__(self):
        require(
            bool(self.id and self.owner_session and self.owner_actor and self.goal.strip()),
            "task-definition",
        )
        ids = [c.id for c in self.acceptance]
        require(
            all(
                isinstance(identifier, str) and identifier and identifier != self.id
                for identifier in self.dependencies
            )
            and len(self.dependencies) == len(set(self.dependencies)),
            "task-dependencies",
        )
        require(
            all(condition.when is None for condition in self.acceptance),
            "task-acceptance-unconditional",
        )
        require(
            bool(self.instruction_sources and ids) and all(ids) and len(ids) == len(set(ids)),
            "task-definition",
        )

    def changed(self, **changes):
        return replace(self, revision=self.revision + 1, **changes)

    def require_owner(self, actor, generation):
        require(
            actor == self.owner_actor and generation == self.ownership_generation, "stale-owner"
        )

    def require_revision(self, revision):
        require(
            self.revision == revision, "revision-conflict", expected=revision, actual=self.revision
        )

    @property
    def controllers(self):
        executors = frozenset(
            a.recipient for a in self.assignments if a.role == "executor" and a.state == "active"
        )
        return executors or frozenset({self.owner_actor})

    @property
    def acceptors(self):
        return self.controllers | {self.owner_actor}

    def require_controller(self, actor):
        if self.controllers != {self.owner_actor}:
            require(actor in self.controllers, "executor-controls-phase")
        else:
            self.require_owner(actor, self.ownership_generation)

    def require_participant(self, actor):
        assignment = next(
            (a for a in self.assignments if a.recipient == actor and a.state == "active"), None
        )
        require(actor == self.owner_actor or assignment is not None, "assignment-required")
        return assignment

    def require_writer(self, actor):
        self.require_participant(actor)
        require(
            not any(
                a.recipient == actor and a.role == "reviewer" and a.state == "active"
                for a in self.assignments
            ),
            "reviewer-read-only",
        )

    def require_role(self, recipient, role):
        require(role in {"worker", "reviewer", "executor"}, "assignment-role")
        if recipient:
            require(
                not any(
                    a.recipient == recipient and (a.role == "reviewer") != (role == "reviewer")
                    for a in self.assignments
                ),
                "review-role-conflict",
            )

    def assignment(self, identifier):
        result = next((a for a in self.assignments if a.id == identifier), None)
        require(result is not None, "assignment-missing")
        return result

    def issue_assignment(self, identifier, execution, scope, issuer, recipient, subject, role):
        self.require_controller(issuer)
        self.require_role(recipient, role)
        require(not recipient or recipient != issuer, "assignment-self")
        if role == "executor":
            require(
                not any(a.role == "executor" and a.awaiting_result for a in self.assignments),
                "executor-conflict",
            )
        return self.with_assignment(
            Assignment(
                identifier,
                execution,
                scope,
                issuer,
                recipient,
                subject,
                role=role,
                run_index=self.skill_index,
                phase_id=None if self.current_phase is None else self.current_phase.id,
                attempt=None if self.skill_run is None else self.skill_run.attempt,
            )
        )

    def bind_recipient(self, identifier, recipient):
        assignment = self.assignment(identifier)
        self.require_role(recipient, assignment.role)
        return self.with_assignment(assignment.bind(recipient))

    def start_assignment(self, identifier, actor):
        return self.with_assignment(self.assignment(identifier).start(actor))

    def recipients_ended(self, sources):
        """Apply observed terminal results together, preserving the unfinished user goal."""
        assignments = tuple(
            a.recipient_ended(sources[a.id]) if a.id in sources else a for a in self.assignments
        )
        return self if assignments == self.assignments else self.changed(assignments=assignments)

    def require_assignment_canceller(self, identifier, actor):
        assignment = self.assignment(identifier)
        require(
            actor in {self.owner_actor, assignment.acceptance_owner or assignment.issuer},
            "actor-mismatch",
        )

    def report_assignment(self, identifier, actor, source, verdict, subject):
        assignment = self.assignment(identifier)
        require(assignment.recipient == actor, "actor-mismatch")
        if assignment.role == "executor" and verdict == "pass":
            require(
                self.state == "running" and all(run.complete for run in self.skill_runs),
                "phases-unfinished",
            )
        return self.with_assignment(assignment.report(actor, source, verdict, subject))

    def accept_assignment(self, identifier, actor, source, subject):
        return self.with_assignment(
            self.assignment(identifier).accept(
                actor,
                source,
                subject,
                acceptors=self.acceptors,
            )
        )

    def reject_assignment(self, identifier, actor, source):
        return self.with_assignment(
            self.assignment(identifier).reject(
                actor,
                source,
                acceptors=self.acceptors,
            )
        )

    def record_implementation(self, actor):
        self.require_writer(actor)
        if actor in self.implementation_actors:
            return self
        return self.changed(implementation_actors=(*self.implementation_actors, actor))

    @property
    def skill_run(self):
        index = self.skill_index
        return None if index is None else self.skill_runs[index]

    @property
    def skill_index(self):
        for index in reversed(range(len(self.skill_runs))):
            if not self.skill_runs[index].complete:
                return index
        return next(
            (
                i
                for i in reversed(range(len(self.skill_runs)))
                if self.skill_runs[i].parent_index is None
            ),
            None,
        )

    @property
    def current_phase(self):
        return None if self.skill_run is None else self.skill_run.current

    def observation_scope(self):
        """Bind a native operation to its run and every enclosing attempt."""
        scope = []
        index = self.skill_index
        while index is not None:
            run = self.skill_runs[index]
            scope.append((index, run.attempt))
            index = run.parent_index
        return tuple(scope)

    def validate_observation_scope(self, scope):
        for index, attempt in scope:
            require(0 <= index < len(self.skill_runs), "evidence-run-missing")
            run = self.skill_runs[index]
            require(
                attempt <= run.attempt
                and all(
                    previous.changed_inputs == ()
                    for previous in run.history
                    if previous.number >= attempt
                ),
                "evidence-attempt-changed",
            )

    def start(self):
        require(self.state == "open", "task-state")
        return self.changed(state="running")

    def attach_skill(self, definition):
        require(self.state == "running", "task-state")
        parent = None
        if self.current_phase is not None:
            require(definition.id in self.current_phase.subskills, "subskill-not-declared")
            parent = self.skill_index
        return self.changed(
            skill_runs=(*self.skill_runs, SkillRun(definition, parent_index=parent))
        )

    def _replace_run(self, run, **changes):
        runs = tuple(
            run if index == self.skill_index else value
            for index, value in enumerate(self.skill_runs)
        )
        return self.changed(skill_runs=runs, **changes)

    def complete_phase(self, phase_id, outcomes, inputs):
        require(self.state == "running" and self.skill_run is not None, "task-state")
        require(
            not any(
                a.role != "executor"
                and a.run_index == self.skill_index
                and a.phase_id == phase_id
                and a.attempt == self.skill_run.attempt
                and a.state not in {"accepted", "rejected"}
                for a in self.assignments
            ),
            "assignments-unsettled",
        )
        run = self.skill_run.advance(phase_id, outcomes, inputs)
        previous = [
            completion
            for run in self.skill_runs
            for completion in (
                *run.completions,
                *(c for attempt in run.history for c in attempt.completions),
            )
        ]
        validate_reuse(previous, outcomes, inputs)
        return self._replace_run(run)

    def restart(self, failure_source, changed_inputs=None):
        require(self.state in {"running", "waiting"} and self.skill_run is not None, "task-state")
        # Bounded workers belong to the attempt that issued them. Settle their
        # result or cancellation before changing that attempt; otherwise they
        # retain active access while the next phase stops accounting for them.
        require(
            all(
                a.role == "executor" or a.state in {"accepted", "rejected"}
                for a in self.assignments
            ),
            "assignments-unsettled",
        )
        run = self.skill_run.restart(failure_source, changed_inputs)
        return self._replace_run(run, state="running")

    def wait(self, reason, source):
        require(self.state in {"open", "running", "waiting"}, "task-state")
        require(bool(reason.strip() and source), "waiting-reason")
        return self.changed(state="waiting", attempts=(*self.attempts, (reason, source)))

    def resume(self):
        require(self.state == "waiting", "task-state")
        return self.changed(state="running")

    def with_assignment(self, assignment):
        require(self.state in {"open", "running", "waiting", "withdrawn"}, "task-state")
        existing = any(a.id == assignment.id for a in self.assignments)
        require(self.state != "withdrawn" or existing, "task-withdrawn")
        assignments = tuple(assignment if a.id == assignment.id else a for a in self.assignments)
        return self.changed(assignments=assignments if existing else (*assignments, assignment))

    def complete(self, outcomes):
        require(self.state == "running", "task-state")
        require(all(run.complete for run in self.skill_runs), "phases-unfinished")
        require(
            all(a.state in {"accepted", "rejected"} for a in self.assignments),
            "assignments-unsettled",
        )
        inputs = {
            key: value
            for completion in (() if self.skill_run is None else self.skill_run.completions)
            for key, value in completion.inputs
        }
        previous_ids = {
            identifier
            for run in self.skill_runs
            for attempt in run.history
            for completion in attempt.completions
            for identifier in completion.evidence_ids
        }
        current_ids = {
            identifier
            for run in self.skill_runs
            for completion in run.completions
            if all(inputs.get(key) == value for key, value in completion.inputs)
            for identifier in completion.evidence_ids
        }
        for items in outcomes.values():
            for evidence in items:
                require(
                    evidence.id not in previous_ids or evidence.id in current_ids,
                    "evidence-input-changed",
                    evidence_id=evidence.id,
                )
        validate_conditions(self.acceptance, outcomes, inputs)
        return self.changed(
            state="completed",
            completion_evidence=tuple(e.id for items in outcomes.values() for e in items),
        )

    def withdraw(self, source):
        require(source.kind in {"user", "native_input"}, "user-source-required")
        require(self.state in {"open", "running", "waiting"}, "task-state")
        assignments = tuple(
            a.cancel() if a.state in {"issued", "active"} else a for a in self.assignments
        )
        return self.changed(state="withdrawn", withdrawal_source=source.id, assignments=assignments)

    def adopt(self, session, actor, source, *, previous_owner_stopped):
        require(source.kind in {"user", "native_input"}, "user-source-required")
        require(previous_owner_stopped, "owner-still-active")
        require(self.state in {"open", "running", "waiting"}, "task-state")
        assignments = tuple(replace(a, acceptance_owner=actor) for a in self.assignments)
        return self.changed(
            owner_session=session,
            owner_actor=actor,
            ownership_generation=self.ownership_generation + 1,
            assignments=assignments,
        )


def stop_reasons(session, actor, tasks):
    reasons = []
    for task in tasks:
        if (
            task.owner_session == session
            and task.owner_actor == actor
            and task.state not in {"completed", "withdrawn"}
        ):
            reasons.append(
                {
                    "task_id": task.id,
                    "reason": "task-unfinished",
                    "state": task.state,
                    "phase": None if task.current_phase is None else task.current_phase.id,
                }
            )
        for assignment in task.assignments:
            owed = (
                assignment.recipient == actor
                and assignment.state in {"issued", "active", "cancel-requested"}
                or (assignment.acceptance_owner or assignment.issuer) == actor
                and assignment.state not in {"accepted", "rejected"}
            )
            if owed:
                reasons.append(
                    {
                        "task_id": task.id,
                        "assignment_id": assignment.id,
                        "reason": "assignment-unsettled",
                    }
                )
    return tuple(reasons)
