"""phase runner 관련 타입과 실행 흐름을 정의합니다."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path

from scripts.agent_harness.harness_incident import HarnessIncidentValidationError
from scripts.agent_harness.session_kernel import (
    SessionKernelError,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)


from scripts.skill_harness.phase_models import (
    PhaseRecord,
    PhaseContract,
    PhaseRunState,
    PhaseRunnerError,
    SkillContract,
    VALID_PHASE_STATUSES,
    TERMINAL_PHASE_STATUSES,
)
from scripts.skill_harness.phase_store import (
    PhaseRunStore,
    AdaptiveControlPhaseReadback,
    AdaptiveControlTransitionReadback,
)
from scripts.skill_harness.phase_contracts import SkillContractRepository
from scripts.skill_harness.phase_evidence_validation import (
    PhaseEvidenceValidator,
    RegressionNodeOutcome,
    REVIEW_CODE_ROW_COUNT,
    REVIEW_CODE_ROW_COUNT_TEXT,
)

ROOT = __import__("scripts._neurath_paths", fromlist=["target_root"]).target_root(
    Path(__file__).resolve().parents[2]
)

__all__ = [
    "PhaseRunnerError",
    "PhaseContract",
    "SkillContract",
    "PhaseRecord",
    "PhaseRunState",
    "SkillContractRepository",
    "AdaptiveControlPhaseReadback",
    "AdaptiveControlTransitionReadback",
    "PhaseRunStore",
    "PhaseRunner",
    "PhaseRunnerApplication",
    "RegressionNodeOutcome",
    "REVIEW_CODE_ROW_COUNT",
    "REVIEW_CODE_ROW_COUNT_TEXT",
    "VALID_PHASE_STATUSES",
    "TERMINAL_PHASE_STATUSES",
]


class PhaseRunner:
    """Coordinate contract admission, evidence validation and atomic store transitions."""

    def __init__(self, repository: SkillContractRepository) -> None:
        self._repository = repository
        self._evidence = PhaseEvidenceValidator(repository.root)

    def initialize(
        self,
        skill_name: str,
        run_id: str,
        north_star: str,
        store: PhaseRunStore,
    ) -> dict[str, object]:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            skill_name: 호출자가 넘긴 skill name 값입니다.
            run_id: 호출자가 넘긴 run id 값입니다.
            north_star: 착수 시 고정할 최초 지시·완료 기준·비목표 텍스트입니다.
            store: 호출자가 넘긴 store 값입니다.

        Returns:
            initialize 처리 결과입니다."""
        contract = self._repository.get(skill_name)
        state = PhaseRunState.initialize(contract, run_id, north_star)
        store.write(state)
        first_phase = contract.first_phase()
        return {
            "event": "phase_initialized",
            "skill": state.skill,
            "run_id": state.run_id,
            "north_star": state.north_star,
            "current_phase": self._phase_payload(state, first_phase),
        }

    def current(self, store: PhaseRunStore) -> dict[str, object]:
        state = store.read()
        if state.terminal_state is not None:
            return {
                "event": "phase_run_terminal",
                "skill": state.skill,
                "run_id": state.run_id,
                "terminal_state": state.terminal_state,
            }
        if state.current_phase_id is None:
            return {
                "event": "phase_run_ready_to_finalize",
                "skill": state.skill,
                "run_id": state.run_id,
            }
        contract = self._contract_for_state(state)
        current_phase = contract.phase(state.current_phase_id)
        phase_payload = self._phase_payload(state, current_phase)
        return {
            "event": "current_phase",
            "skill": state.skill,
            "run_id": state.run_id,
            "north_star": state.north_star,
            "phase": phase_payload,
            "phase_id": current_phase.id,
            "phase_name": current_phase.name,
            "min_evidence_count": phase_payload["min_evidence_count"],
            "required_evidence": phase_payload["required_evidence"],
        }

    def complete(
        self,
        store: PhaseRunStore,
        phase_id: int,
        status: str,
        evidence: tuple[str, ...],
        summary: str,
        reason: str | None,
        terminal_state: str | None = None,
    ) -> dict[str, object]:
        """요청을 처리해 호출자가 사용할 값을 반환합니다.

        Args:
            store: 호출자가 넘긴 store 값입니다.
            phase_id: 호출자가 넘긴 phase id 값입니다.
            status: 호출자가 넘긴 status 값입니다.
            evidence: 호출자가 넘긴 evidence 값입니다.
            summary: 호출자가 넘긴 summary 값입니다.
            reason: 호출자가 넘긴 reason 값입니다.
            terminal_state: Operational final phase를 같은 CAS에서 닫을 optional terminal입니다.

        Returns:
            complete 처리 결과입니다.

        Raises:
            PhaseRunnerError: Phase, evidence, adaptive policy 또는 terminal 조건이
                current state와 맞지 않으면 발생합니다."""
        state = store.read()
        contract = self._contract_for_state(state)
        if terminal_state is not None and state.adaptive_control_required:
            raise PhaseRunnerError(
                "ATOMIC_FINALIZE_UNSUPPORTED",
                "adaptive workflow must refresh completion authority after the final phase "
                "and use the separate finalize command",
            )
        self._assert_phase_can_complete(state, phase_id, status, summary, reason)
        self._assert_evaluate_harness_budget(state, status)
        current_phase = contract.phase(phase_id)
        evaluation = self._evidence.evaluate(
            state,
            current_phase,
            status,
            evidence,
            store,
        )
        next_state = state.with_completed_phase(
            contract,
            phase_id,
            status,
            evidence,
            summary,
            reason,
        )
        if terminal_state is not None:
            finalized_state = self._finalize_state(
                store,
                next_state,
                contract,
                terminal_state,
            )
            payload = self._finalized_payload(finalized_state)
            payload.update(
                {
                    "atomic_completion": True,
                    "completed_phase": finalized_state.phase(phase_id).as_payload(),
                    "evaluation": evaluation,
                }
            )
            return payload
        store.write(next_state)
        next_phase = None
        if next_state.current_phase_id is not None:
            next_phase = self._phase_payload(
                next_state,
                contract.phase(next_state.current_phase_id),
            )
        return {
            "event": "phase_completed",
            "skill": state.skill,
            "run_id": state.run_id,
            "north_star": state.north_star,
            "completed_phase": next_state.phase(phase_id).as_payload(),
            "evaluation": evaluation,
            "next_phase": next_phase,
            "terminal_candidate": status if status in TERMINAL_PHASE_STATUSES else None,
        }

    def _assert_evaluate_harness_budget(
        self,
        state: PhaseRunState,
        status: str,
    ) -> None:
        """Bounded evaluate-harness run이 성공을 가장하며 연장되는 것을 거부합니다.

        Args:
            state: Run 시작 시각을 포함한 current phase projection입니다.
            status: Caller가 요청한 phase completion status입니다.

        Raises:
            PhaseRunnerError: 90분 wall-clock 상한 뒤 non-terminal 진행을 요청하면 발생합니다.
        """
        if status in TERMINAL_PHASE_STATUSES or not self._evidence.budget_expired(state):
            return
        raise PhaseRunnerError(
            "EVALUATION_BUDGET_EXHAUSTED",
            "evaluate-harness exceeded its 90 minute wall-clock watchdog; return blocked "
            "control to the user instead of starting or continuing another generation",
        )

    def finalize(
        self,
        store: PhaseRunStore,
        terminal_state: str,
    ) -> dict[str, object]:
        state = store.read()
        contract = self._contract_for_state(state)
        next_state = self._finalize_state(store, state, contract, terminal_state)
        return self._finalized_payload(next_state)

    def _finalize_state(
        self,
        store: PhaseRunStore,
        state: PhaseRunState,
        contract: SkillContract,
        terminal_state: str,
    ) -> PhaseRunState:
        """기존 terminal 조건을 검증하고 한 번의 store transition으로 닫습니다.

        Args:
            store: Exact workflow revision에 결속된 phase store입니다.
            state: Finalize할 completed phase projection입니다.
            contract: State skill의 current executable contract입니다.
            terminal_state: Contract가 허용하는 terminal marker입니다.

        Returns:
            Terminal marker가 기록되고 store에 commit된 state입니다.

        Raises:
            PhaseRunnerError: Terminal 조건 또는 incident read-back이 유효하지 않으면 발생합니다.
        """
        if terminal_state not in contract.terminal_states:
            raise PhaseRunnerError(
                "TERMINAL_STATE_INVALID",
                f"{terminal_state} is not allowed for {state.skill}",
            )
        if terminal_state in TERMINAL_PHASE_STATUSES:
            if not state.has_terminal_phase_status(terminal_state):
                raise PhaseRunnerError(
                    "TERMINAL_PHASE_REQUIRED",
                    f"{terminal_state} finalization requires a {terminal_state} phase",
                )
        elif not state.all_executable_phases_complete():
            raise PhaseRunnerError(
                "INCOMPLETE_PHASES",
                f"{terminal_state} finalization requires every phase to be completed or skipped",
            )
        if (
            state.skill == "autopilot"
            and terminal_state == "merged"
            and any(phase.status != "completed" for phase in state.phases)
        ):
            raise PhaseRunnerError(
                "AUTOPILOT_PHASE_REQUIRED",
                "merged autopilot requires every phase to be completed",
            )
        if state.skill == "process-ticket" and terminal_state == "merged":
            merge_cleanup = next(
                (phase for phase in state.phases if phase.name == "merge_cleanup"),
                None,
            )
            if merge_cleanup is None or merge_cleanup.status != "completed":
                raise PhaseRunnerError(
                    "MERGE_CLEANUP_REQUIRED",
                    "merged finalization requires a completed merge_cleanup phase, "
                    "not a skipped one",
                )
        if state.skill == "process-ticket":
            try:
                store.validate_harness_incidents(self._repository.root)
            except HarnessIncidentValidationError as exc:
                raise PhaseRunnerError(
                    "HARNESS_INCIDENT_UNRESOLVED",
                    str(exc),
                ) from exc

        next_state = state.with_terminal_state(terminal_state)
        store.write(next_state)
        return next_state

    def _finalized_payload(self, state: PhaseRunState) -> dict[str, object]:
        """Terminal state의 canonical JSON receipt를 만듭니다.

        Args:
            state: Store transition까지 완료된 terminal phase state입니다.

        Returns:
            기존 finalize와 atomic complete가 공유하는 terminal receipt입니다.
        """
        finalized_at = time.time()
        return {
            "event": "phase_run_finalized",
            "skill": state.skill,
            "run_id": state.run_id,
            "terminal_state": state.terminal_state,
            "phase_timings": [
                {
                    "id": phase.id,
                    "name": phase.name,
                    "status": phase.status,
                    "duration_seconds": phase.duration_seconds,
                }
                for phase in state.phases
            ],
            "total_duration_seconds": (
                max(0.0, finalized_at - state.started_at_epoch)
                if state.started_at_epoch is not None
                else None
            ),
            "state": state.as_payload(),
        }

    def _assert_phase_can_complete(
        self,
        state: PhaseRunState,
        phase_id: int,
        status: str,
        summary: str,
        reason: str | None,
    ) -> None:
        if state.terminal_state is not None:
            raise PhaseRunnerError("ALREADY_FINALIZED", "phase run is already finalized")
        if state.current_phase_id is None:
            raise PhaseRunnerError("NO_CURRENT_PHASE", "phase run is ready to finalize")
        if phase_id != state.current_phase_id:
            raise PhaseRunnerError(
                "PHASE_ID_MISMATCH",
                f"current phase is {state.current_phase_id}, not {phase_id}",
            )
        if status not in VALID_PHASE_STATUSES:
            raise PhaseRunnerError("STATUS_INVALID", f"{status} is not a valid phase status")
        if state.skill == "autopilot" and status == "skipped":
            raise PhaseRunnerError(
                "AUTOPILOT_SKIP_FORBIDDEN",
                "autopilot phases cannot be skipped; record a verified no-op as completed",
            )
        if not summary:
            raise PhaseRunnerError("SUMMARY_REQUIRED", "phase completion requires a summary")
        if status in TERMINAL_PHASE_STATUSES and not reason:
            raise PhaseRunnerError(
                "REASON_REQUIRED",
                f"{status} phase completion requires a reason",
            )

    def _contract_for_state(self, state: PhaseRunState) -> SkillContract:
        contract = self._repository.get(state.skill)
        if (
            state.skill == "autopilot"
            and len(state.phases) == 7
            and state.phases[5].name == "intent_audit_and_docs"
            and state.phases[6].name == "terminal_report"
        ):
            legacy_phases = (
                *contract.phases[:5],
                PhaseContract(
                    6,
                    "intent_audit_and_docs",
                    2,
                    ("audit_spec_result", "sync_docs_result"),
                    "phases/phase-4-intent-audit.md",
                ),
                PhaseContract(
                    7, "terminal_report", 1, ("terminal_report",), "phases/phase-6-final-report.md"
                ),
            )
            return SkillContract(
                contract.name,
                contract.terminal_states,
                legacy_phases,
                contract.adaptive_control_required,
            )
        return contract

    def _phase_payload(
        self,
        state: PhaseRunState,
        phase: PhaseContract,
    ) -> dict[str, object]:
        """Persisted migration flag를 반영한 current phase requirement를 반환합니다."""
        payload = phase.as_payload()
        required = self._evidence.required_evidence(state, phase, "completed")
        payload["required_evidence"] = list(required)
        payload["min_evidence_count"] = max(phase.min_evidence_count, len(required))
        if state.skill == "finish-session" and phase.name in {"stage_scope", "commit"}:
            payload["skip_evidence"] = ["clean_tree"]
        return payload


class PhaseRunnerApplication:

    def __init__(self, root: Path = ROOT) -> None:
        self._root = root.resolve()

    def run(
        self,
        raw_args: list[str] | None = None,
        *,
        environment: Mapping[str, object] | None = None,
    ) -> int:
        """입력값을 해석해 해당 경계의 처리 결과를 만듭니다.

        Args:
            raw_args: 호출자가 넘긴 raw args 값입니다.
            environment: Session과 actor identity를 제공하는 runtime-owned environment입니다.

        Returns:
            run 처리 결과입니다."""
        parser = self._parser()
        args = parser.parse_args(raw_args)
        runner = PhaseRunner(SkillContractRepository(self._root))
        try:
            store = self._session_store(args, os.environ if environment is None else environment)
            payload = self._dispatch(args, runner, store)
        except PhaseRunnerError as exc:
            self._print_json(
                {
                    "event": "phase_runner_error",
                    "code": exc.code,
                    "message": exc.message,
                }
            )
            return 1
        except (RuntimeIdentityError, SessionKernelError) as exc:
            self._print_json(
                {
                    "event": "phase_runner_error",
                    "code": "STATE_INVALID",
                    "message": str(exc),
                }
            )
            return 1
        self._print_json(payload)
        return 0

    def _session_store(
        self,
        args: argparse.Namespace,
        environment: Mapping[str, object],
    ) -> PhaseRunStore:
        # Session store는 PhaseRunState codec을 이 module에서 가져옵니다.
        from scripts.skill_harness.session_phase_store import (  # noqa: PLC0415  # circular: PhaseRunState codec dependency
            PhaseStateMissingError,
            PhaseWorkflowConflict,
            SessionPhaseRunnerStore,
            SessionPhaseStateStore,
            SessionPhaseStoreError,
        )

        try:
            locator = SessionLocator.from_worktree(self._root)
            binding = RuntimeEnvironmentResolver().resolve(environment)
            handle = StateHandle.attach(locator, binding)
            workflow_id = WorkflowId(args.workflow_id)
            if args.command == "init":
                return SessionPhaseRunnerStore(
                    SessionPhaseStateStore(
                        handle=handle,
                        workflow_id=workflow_id,
                        skill=args.skill,
                        run_id=args.run_id,
                    )
                )
            return SessionPhaseRunnerStore.open_existing(handle, workflow_id)
        except PhaseWorkflowConflict as error:
            raise PhaseRunnerError("STATE_CONFLICT", str(error)) from error
        except PhaseStateMissingError as error:
            raise PhaseRunnerError("STATE_MISSING", str(error)) from error
        except (SessionPhaseStoreError, RuntimeIdentityError, SessionKernelError) as error:
            raise PhaseRunnerError("STATE_INVALID", str(error)) from error

    def _dispatch(
        self,
        args: argparse.Namespace,
        runner: PhaseRunner,
        store: PhaseRunStore,
    ) -> dict[str, object]:
        if args.command == "init":
            return runner.initialize(args.skill, args.run_id, args.north_star, store)
        if args.command == "current":
            return runner.current(store)
        if args.command == "complete":
            return runner.complete(
                store=store,
                phase_id=args.phase_id,
                status=args.status,
                evidence=tuple(args.evidence),
                summary=args.summary,
                reason=args.reason,
                terminal_state=args.terminal_state,
            )
        if args.command == "finalize":
            return runner.finalize(store, args.terminal_state)
        raise PhaseRunnerError("COMMAND_INVALID", f"unsupported command {args.command}")

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Execute Neurath skill phases through a deterministic state machine."
        )
        subparsers = parser.add_subparsers(dest="command", required=True)

        init_parser = subparsers.add_parser("init", help="Start a contracted skill phase run.")
        init_parser.add_argument("--workflow-id", required=True)
        init_parser.add_argument("--skill", required=True)
        init_parser.add_argument("--run-id", required=True)
        init_parser.add_argument(
            "--north-star",
            required=True,
            help="착수 시 고정할 최초 지시·완료 기준·비목표. 매 phase 조회·완료에 다시 노출됩니다.",
        )

        current_parser = subparsers.add_parser(
            "current",
            help="Print the current phase requirements.",
        )
        current_parser.add_argument("--workflow-id", required=True)

        complete_parser = subparsers.add_parser(
            "complete",
            help="Evaluate and complete the current phase.",
        )
        complete_parser.add_argument("--workflow-id", required=True)
        complete_parser.add_argument("--phase-id", type=int, required=True)
        complete_parser.add_argument("--status", choices=VALID_PHASE_STATUSES, required=True)
        complete_parser.add_argument("--summary", required=True)
        complete_parser.add_argument("--reason")
        complete_parser.add_argument("--evidence", action="append", default=[])
        complete_parser.add_argument(
            "--terminal-state",
            help=(
                "Operational final phase를 같은 WorkflowFinalized CAS에서 닫습니다. "
                "Adaptive workflow는 별도 finalize를 사용합니다."
            ),
        )

        finalize_parser = subparsers.add_parser(
            "finalize",
            help="Finalize a phase run after terminal criteria are satisfied.",
        )
        finalize_parser.add_argument("--workflow-id", required=True)
        finalize_parser.add_argument("--terminal-state", required=True)
        return parser

    def _print_json(self, payload: dict[str, object]) -> None:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    """CLI entrypoint가 인자를 해석하고 process exit code를 반환합니다.

    Raises:
        입력 조합이나 외부 응답이 domain invariant와 맞지 않으면 예외를 발생시킵니다."""
    raise SystemExit(PhaseRunnerApplication().run())


if __name__ == "__main__":
    main()
