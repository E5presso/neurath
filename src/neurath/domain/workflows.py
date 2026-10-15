"""Workflow rules. A procedure result is not an assertion of user-goal success."""

from dataclasses import asdict, dataclass, field

from neurath.domain.core import CoreError


class InvalidWorkflow(CoreError):
    pass


@dataclass(frozen=True)
class Phase:
    id: str
    action: tuple[str, ...]
    target: str
    target_revision: str
    conditions: tuple[str, ...] = ("execution",)
    required: bool = True
    when: str = ""
    depends_on: tuple[str, ...] = ()
    reviewer: str = ""
    mutation: bool = False
    timeout: float = 60.0
    output_limit: int = 16384
    max_attempts: int = 3
    no_progress_limit: int = 2

    def validate(self):
        if not all(
            (self.id.strip(), self.action, self.target.strip(), self.target_revision.strip())
        ):
            raise InvalidWorkflow("Phase needs an action and a versioned target")
        if not self.conditions or any(not c.strip() for c in self.conditions):
            raise InvalidWorkflow("Phase needs explicit result conditions")
        if self.timeout <= 0 or not 1 <= self.output_limit <= 1048576:
            raise InvalidWorkflow("Invalid execution bounds")
        if self.max_attempts < 1 or self.no_progress_limit < 1:
            raise InvalidWorkflow("Review/retry loops must be finite")


@dataclass(frozen=True)
class Definition:
    name: str
    version: str
    purpose: str
    phases: tuple[Phase, ...]
    required_inputs: tuple[str, ...] = ()

    def validate(self, inputs):
        if not all((self.name.strip(), self.version.strip(), self.purpose.strip(), self.phases)):
            raise InvalidWorkflow("A selected definition needs name, version, purpose and phases")
        seen = set()
        for phase in self.phases:
            phase.validate()
            if phase.id in seen or not set(phase.depends_on) <= seen:
                raise InvalidWorkflow("Phase IDs must be unique and dependencies ordered")
            seen.add(phase.id)
            if phase.when and not isinstance(inputs.get(phase.when), bool):
                raise InvalidWorkflow("Conditional branches need a boolean input")
        if any(key not in inputs for key in self.required_inputs):
            raise InvalidWorkflow("Required workflow input is missing")

    @classmethod
    def from_dict(cls, data):
        values = dict(data)
        values["required_inputs"] = tuple(values.get("required_inputs", ()))
        values["phases"] = tuple(
            Phase(**{**p, **{k: tuple(p[k]) for k in ("action", "conditions", "depends_on")}})
            for p in values["phases"]
        )
        return cls(**values)


@dataclass(frozen=True)
class Execution:
    id: str
    run_id: str
    phase: Phase
    inputs: dict
    definition_revision: int
    generation: int


@dataclass(frozen=True)
class Observation:
    key: str
    outcome: str
    summary: str
    target: str
    target_revision: str
    references: tuple[str, ...]
    satisfied: tuple[str, ...] = ()
    reviewer: str = ""
    defects: tuple[str, ...] = ()
    changes: str = ""
    output: str = ""

    def validate(self):
        if self.outcome not in {"succeeded", "failed", "waiting", "timed_out", "interrupted"}:
            raise InvalidWorkflow("Unknown execution outcome")
        if (
            not self.key
            or not self.summary
            or not self.references
            or any(not r for r in self.references)
        ):
            raise InvalidWorkflow("Actual observations require a key, summary and references")


@dataclass
class Run:
    id: str
    project_id: str
    task_id: str
    revision: int
    definition: Definition
    inputs: dict
    task_definition_revision: int
    definition_revision: int = 1
    status: str = "active"
    reason: str = ""
    states: dict = field(default_factory=dict)
    events: list = field(default_factory=list)

    def phase(self, phase_id):
        for phase in self.definition.phases:
            if phase.id == phase_id:
                return phase
        raise InvalidWorkflow("Phase is not in the current definition")

    def initialize(self):
        for phase in self.definition.phases:
            self.states[phase.id] = self.fresh_state()

    @staticmethod
    def fresh_state(generation=1):
        return dict(
            status="pending",
            attempt_id=None,
            generation=generation,
            attempts=0,
            failures=0,
            defects=[],
            reason="",
            result_id=None,
        )

    @property
    def current(self):
        return next(
            (
                p
                for p in self.definition.phases
                if self.states[p.id]["status"] not in {"succeeded", "skipped"}
            ),
            None,
        )

    def skip(self, phase_id, reason):
        phase = self.phase(phase_id)
        state = self.states[phase_id]
        if self.current != phase or state["status"] not in {"pending", "failed"}:
            raise InvalidWorkflow("Only the current unexecuted/failed phase can be skipped")
        if phase.required and not (phase.when and self.inputs[phase.when] is False):
            raise InvalidWorkflow("Required phase cannot be skipped without a scope correction")
        if not reason.strip():
            raise InvalidWorkflow("Skipping requires a reason")
        state.update(status="skipped", reason=reason)
        self.finish()

    def begin(self, phase_id, attempt_id):
        phase = self.phase(phase_id)
        state = self.states[phase_id]
        if self.status != "active" or self.current != phase:
            raise InvalidWorkflow("Run is paused, complete, or phase is out of order")
        if phase.when and not self.inputs[phase.when]:
            raise InvalidWorkflow("Conditional phase is inactive; record a justified skip")
        if state["status"] not in {"pending", "failed"}:
            raise InvalidWorkflow("Reconcile the existing attempt before executing again")
        if state["attempts"] >= phase.max_attempts or state["failures"] >= phase.no_progress_limit:
            raise InvalidWorkflow("Finite review/retry budget exhausted; unresolved work remains")
        if any(self.states[p]["status"] not in {"succeeded", "skipped"} for p in phase.depends_on):
            raise InvalidWorkflow("Phase dependency is unresolved")
        state.update(status="running", attempt_id=attempt_id, attempts=state["attempts"] + 1)
        return Execution(
            attempt_id,
            self.id,
            phase,
            dict(self.inputs),
            self.definition_revision,
            state["generation"],
        )

    def apply(self, execution, observation, result_id):
        state = self.states.get(execution.phase.id)
        if (
            not state
            or state["attempt_id"] != execution.id
            or state["generation"] != execution.generation
        ):
            return False
        # A terminal attempt cannot be resurrected by a late success, even before retry.
        if state["status"] not in {"running", "waiting"}:
            return False
        phase = self.phase(execution.phase.id)
        if (observation.target, observation.target_revision) != (
            phase.target,
            phase.target_revision,
        ):
            return False
        outcome = observation.outcome
        if outcome == "succeeded":
            if not set(phase.conditions) <= set(observation.satisfied) or observation.defects:
                outcome = "failed"
            if phase.reviewer and observation.reviewer != phase.reviewer:
                outcome = "failed"
        state.update(
            status="failed" if outcome in {"timed_out", "interrupted"} else outcome,
            reason=observation.summary,
            result_id=result_id,
        )
        if state["status"] == "failed":
            signature = list(observation.defects) or [observation.summary]
            state["failures"] = state["failures"] + 1 if state["defects"] == signature else 1
            state["defects"] = signature
        self.finish()
        return True

    def finish(self):
        if self.current is None:
            self.status = "completed"
            self.reason = "Procedure complete; user-goal result remains a task decision"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "definition": Definition.from_dict(data["definition"])})
