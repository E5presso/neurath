"""Session snapshot의 JSON codec과 cross-record 상태 검증을 소유합니다."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.agent_harness.session_kernel import (
        ActorId,
        ActorRecord,
        DelegationId,
        DelegationRecord,
        DelegationResult,
        EffectId,
        ForegroundPromptAuthorityContext,
        ForegroundTurnReceipt,
        ForegroundTurnRecord,
        ForegroundUserPromptReceipt,
        HarnessIncidentEvidenceArchive,
        HarnessIncidentRecord,
        HarnessRegressionReceipt,
        IncidentId,
        MaterialActionBatch,
        OutboxEffect,
        ProcessState,
        ResumeId,
        SessionId,
        SessionRecord,
        WorkflowId,
        WorkflowRecord,
    )


class SessionStateCodec:
    """Raw JSON과 typed immutable ProcessState 사이의 유일한 변환 경계입니다."""

    def decode(self, payload: object, expected_session_id: SessionId | None = None) -> ProcessState:
        """JSON object를 identity invariant가 검증된 ProcessState로 변환합니다.

        Args:
            payload: Snapshot file에서 역직렬화한 untrusted JSON-compatible 값입니다.
            expected_session_id: 다른 session snapshot을 읽지 못하게 확인할 identity입니다.

        Returns:
            Schema, identity, topology, reference invariant를 통과한 immutable snapshot입니다.

        Raises:
            InvalidSessionState: Payload shape, schema, identity, record invariant가 틀리면
                발생합니다.
        """
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            PROCESS_STATE_SCHEMA,
            InvalidSessionState,
            ProcessState,
        )

        if not isinstance(payload, dict):
            raise InvalidSessionState("process state root must be an object")
        if payload.get("schema") != PROCESS_STATE_SCHEMA:
            raise InvalidSessionState("unsupported process state schema")
        revision = payload.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise InvalidSessionState("revision must be a non-negative integer")
        session_payload = payload.get("session")
        if not isinstance(session_payload, dict):
            raise InvalidSessionState("session must be an object")
        session = self._decode_session(session_payload)
        if expected_session_id is not None and session.id != expected_session_id:
            raise InvalidSessionState(
                f"session id mismatch: expected {expected_session_id}, got {session.id}"
            )
        actors = self._decode_actors(payload.get("actors"))
        workflows = self._decode_workflows(payload.get("workflows"))
        delegations = self._decode_delegations(payload.get("delegations"))
        state = ProcessState(
            revision=revision,
            session=session,
            actors=actors,
            workflows=workflows,
            delegations=delegations,
            resources=self._object_mapping(payload, "resources"),
            mailboxes=self._object_mapping(payload, "mailboxes"),
            incidents=self._decode_incidents(payload.get("incidents")),
            outbox=self._decode_outbox(payload.get("outbox")),
            foreground_turns=self._decode_foreground_turns(payload.get("foreground_turns", {})),
            material_actions=self._decode_material_actions(payload.get("material_actions", {})),
        )
        SessionStateValidator().validate(state)
        return state

    def encode(self, state: ProcessState) -> bytes:
        """Validated ProcessState를 deterministic UTF-8 JSON bytes로 변환합니다.

        Args:
            state: Canonical snapshot file에 기록할 immutable operational state입니다.

        Returns:
            Key가 정렬되고 마지막 newline을 포함하는 UTF-8 JSON bytes입니다.

        Raises:
            InvalidSessionState: Commit 대상 state의 cross-record invariant가 틀리면
                발생합니다.
        """
        SessionStateValidator().validate(state)
        return (
            json.dumps(
                state.to_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def _decode_session(self, payload: dict[object, object]) -> SessionRecord:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ActorId,
            InvalidSessionState,
            ResumeId,
            SessionId,
            SessionRecord,
            SessionRuntime,
            SessionStatus,
        )

        session_id = SessionId(self._string(payload.get("id"), "id"))
        resume_value = payload.get("resume_id")
        resume_id: ResumeId | None = None
        if resume_value is not None:
            if not isinstance(resume_value, str):
                raise InvalidSessionState("session.resume_id must be a string or null")
            resume_id = ResumeId(resume_value)
        runtime_value = payload.get("runtime")
        status_value = payload.get("status")
        root_actor_id = ActorId(self._string(payload.get("root_actor_id"), "root_actor_id"))
        try:
            runtime = SessionRuntime(runtime_value)
            status = SessionStatus(status_value)
        except (TypeError, ValueError) as error:
            raise InvalidSessionState("session runtime or status is invalid") from error
        parent_value = payload.get("parent_session_id")
        parent_session_id: SessionId | None = None
        if parent_value is not None:
            parent_session_id = SessionId(self._string(parent_value, "parent_session_id"))
        provenance_value = payload.get("lifecycle_provenance_id")
        lifecycle_provenance_id: str | None = None
        if provenance_value is not None:
            lifecycle_provenance_id = self._string(
                provenance_value,
                "lifecycle_provenance_id",
            )
        last_lifecycle_value = payload.get("last_lifecycle_idempotency_key")
        last_lifecycle_idempotency_key = self._optional_string(
            last_lifecycle_value,
            "last_lifecycle_idempotency_key",
        )
        return SessionRecord(
            session_id,
            resume_id,
            runtime,
            root_actor_id,
            status,
            parent_session_id,
            lifecycle_provenance_id,
            last_lifecycle_idempotency_key,
        )

    def _decode_actors(self, payload: object) -> dict[ActorId, ActorRecord]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ActorId,
            ActorKind,
            ActorLineageAssurance,
            ActorRecord,
            ActorStatus,
            InvalidSessionState,
        )

        if not isinstance(payload, dict):
            raise InvalidSessionState("actors must be an object")
        actors: dict[ActorId, ActorRecord] = {}
        for raw_id, raw_record in payload.items():
            if not isinstance(raw_id, str) or not isinstance(raw_record, dict):
                raise InvalidSessionState("actor entries must be keyed objects")
            actor_id = ActorId(raw_id)
            record_id = ActorId(self._string(raw_record.get("id"), "id"))
            if actor_id != record_id:
                raise InvalidSessionState(f"actor key/id mismatch: {raw_id}")
            raw_parent = raw_record.get("parent_actor_id")
            parent_id = (
                None if raw_parent is None else ActorId(self._string(raw_parent, "parent_actor_id"))
            )
            try:
                kind = ActorKind(raw_record.get("kind"))
                status = ActorStatus(raw_record.get("status"))
                raw_lineage_assurance = raw_record.get("lineage_assurance")
                lineage_assurance = (
                    ActorLineageAssurance.UNATTESTED
                    if raw_lineage_assurance is None
                    else ActorLineageAssurance(raw_lineage_assurance)
                )
            except (TypeError, ValueError) as error:
                raise InvalidSessionState(
                    f"invalid actor kind, status, or lineage assurance: {raw_id}"
                ) from error
            actors[actor_id] = ActorRecord(
                actor_id,
                parent_id,
                kind,
                status,
                lineage_assurance,
            )
        return actors

    def _decode_workflows(self, payload: object) -> dict[WorkflowId, WorkflowRecord]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ActorId,
            InvalidSessionState,
            WorkflowId,
            WorkflowRecord,
            WorkflowStatus,
        )

        if not isinstance(payload, dict):
            raise InvalidSessionState("workflows must be an object")
        workflows: dict[WorkflowId, WorkflowRecord] = {}
        for raw_id, raw_record in payload.items():
            if not isinstance(raw_id, str) or not isinstance(raw_record, dict):
                raise InvalidSessionState("workflow entries must be keyed objects")
            workflow_id = WorkflowId(raw_id)
            record_id = WorkflowId(self._string(raw_record.get("id"), "id"))
            if workflow_id != record_id:
                raise InvalidSessionState(f"workflow key/id mismatch: {raw_id}")
            owner_id = ActorId(self._string(raw_record.get("owner_actor_id"), "owner_actor_id"))
            kind = self._string(raw_record.get("kind"), "kind")
            raw_goal = raw_record.get("goal")
            goal = None if raw_goal is None else self._string(raw_goal, "goal")
            raw_payload = raw_record.get("payload")
            if not isinstance(raw_payload, dict) or any(
                not isinstance(key, str) for key in raw_payload
            ):
                raise InvalidSessionState(f"workflow payload must be an object: {raw_id}")
            revision = raw_record.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
                raise InvalidSessionState(f"workflow revision is invalid: {raw_id}")
            try:
                status = WorkflowStatus(raw_record.get("status"))
            except (TypeError, ValueError) as error:
                raise InvalidSessionState(f"invalid workflow status: {raw_id}") from error
            raw_idempotency_key = raw_record.get("last_transition_idempotency_key")
            last_transition_idempotency_key: str | None = None
            if raw_idempotency_key is not None:
                last_transition_idempotency_key = self._string(
                    raw_idempotency_key,
                    "last_transition_idempotency_key",
                )
            workflows[workflow_id] = WorkflowRecord(
                workflow_id,
                owner_id,
                kind,
                goal,
                {str(key): value for key, value in raw_payload.items()},
                revision,
                status,
                last_transition_idempotency_key,
            )
        return workflows

    def _decode_foreground_turns(
        self,
        payload: object,
    ) -> dict[ActorId, ForegroundTurnRecord]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ActorId,
            ForegroundTurnOutcome,
            ForegroundTurnReceipt,
            ForegroundTurnRecord,
            ForegroundTurnStatus,
            InvalidSessionState,
            TransitionRejected,
        )

        if not isinstance(payload, dict):
            raise InvalidSessionState("foreground_turns must be an object")
        turns: dict[ActorId, ForegroundTurnRecord] = {}
        for raw_actor_id, raw_record in payload.items():
            if not isinstance(raw_actor_id, str) or not isinstance(raw_record, dict):
                raise InvalidSessionState("foreground turn entries must be actor-keyed objects")
            actor_id = ActorId(raw_actor_id)
            owner_actor_id = ActorId(
                self._string(raw_record.get("owner_actor_id"), "owner_actor_id")
            )
            generation = raw_record.get("generation")
            revision = raw_record.get("revision")
            if not isinstance(generation, int) or isinstance(generation, bool):
                raise InvalidSessionState("foreground turn generation must be an integer")
            if not isinstance(revision, int) or isinstance(revision, bool):
                raise InvalidSessionState("foreground turn revision must be an integer")
            try:
                status = ForegroundTurnStatus(raw_record.get("status"))
            except (TypeError, ValueError) as error:
                raise InvalidSessionState("foreground turn status is invalid") from error
            raw_receipt = raw_record.get("receipt")
            receipt: ForegroundTurnReceipt | None = None
            if raw_receipt is not None:
                if not isinstance(raw_receipt, dict):
                    raise InvalidSessionState("foreground turn receipt must be an object or null")
                try:
                    outcome = ForegroundTurnOutcome(raw_receipt.get("outcome"))
                except (TypeError, ValueError) as error:
                    raise InvalidSessionState("foreground turn outcome is invalid") from error
                try:
                    receipt = ForegroundTurnReceipt(
                        outcome,
                        summary=self._optional_string(raw_receipt.get("summary"), "summary"),
                        question=self._optional_string(raw_receipt.get("question"), "question"),
                        reason=self._optional_string(raw_receipt.get("reason"), "reason"),
                    )
                except TransitionRejected as error:
                    raise InvalidSessionState(str(error)) from error
            turns[actor_id] = ForegroundTurnRecord(
                owner_actor_id,
                generation,
                revision,
                status,
                receipt,
                self._optional_string(raw_record.get("vendor_turn_id"), "vendor_turn_id"),
                self._decode_user_prompt_receipt(raw_record.get("user_prompt_receipt")),
            )
        return turns

    def _decode_user_prompt_receipt(
        self,
        payload: object,
    ) -> ForegroundUserPromptReceipt | None:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ForegroundUserPromptReceipt,
            InvalidSessionState,
        )

        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise InvalidSessionState("foreground user prompt receipt must be an object or null")
        generation = payload.get("generation")
        turn_revision = payload.get("turn_revision")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise InvalidSessionState("foreground user prompt generation must be an integer")
        if not isinstance(turn_revision, int) or isinstance(turn_revision, bool):
            raise InvalidSessionState("foreground user prompt revision must be an integer")
        return ForegroundUserPromptReceipt(
            prompt_digest=self._string(payload.get("prompt_digest"), "prompt_digest"),
            generation=generation,
            turn_revision=turn_revision,
            vendor_turn_id=self._optional_string(
                payload.get("vendor_turn_id"),
                "user_prompt_vendor_turn_id",
            ),
            authority_context=self._decode_prompt_authority_context(
                payload.get("authority_context")
            ),
        )

    def _decode_material_actions(
        self,
        payload: object,
    ) -> dict[ActorId, MaterialActionBatch]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ActorId,
            InvalidSessionState,
            MaterialActionBatch,
        )

        if not isinstance(payload, dict):
            raise InvalidSessionState("material_actions must be an object")
        batches: dict[ActorId, MaterialActionBatch] = {}
        for raw_actor_id, raw_batch in payload.items():
            if not isinstance(raw_actor_id, str):
                raise InvalidSessionState("material action entries must be actor-keyed objects")
            actor_id = ActorId(raw_actor_id)
            try:
                batches[actor_id] = MaterialActionBatch.from_payload(raw_batch)
            except (TypeError, ValueError) as error:
                raise InvalidSessionState(str(error)) from error
        return batches

    def _decode_prompt_authority_context(
        self,
        payload: object,
    ) -> ForegroundPromptAuthorityContext | None:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ForegroundPromptAuthorityContext,
            InvalidSessionState,
            WorkflowId,
        )

        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise InvalidSessionState("prompt authority context must be an object or null")
        workflow_revision = payload.get("workflow_revision")
        intent_revision = payload.get("intent_revision")
        question_generation = payload.get("question_generation")
        question_turn_revision = payload.get("question_turn_revision")
        for label, value in (
            ("workflow_revision", workflow_revision),
            ("intent_revision", intent_revision),
            ("question_generation", question_generation),
            ("question_turn_revision", question_turn_revision),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise InvalidSessionState(f"prompt authority {label} must be an integer")
        assert isinstance(workflow_revision, int)
        assert isinstance(intent_revision, int)
        assert isinstance(question_generation, int)
        assert isinstance(question_turn_revision, int)
        return ForegroundPromptAuthorityContext(
            workflow_id=WorkflowId(self._string(payload.get("workflow_id"), "workflow_id")),
            workflow_revision=workflow_revision,
            goal_fingerprint=self._string(
                payload.get("goal_fingerprint"),
                "goal_fingerprint",
            ),
            intent_revision=intent_revision,
            source_revision=self._string(
                payload.get("source_revision"),
                "source_revision",
            ),
            criterion_ids=self._string_tuple(payload.get("criterion_ids"), "criterion_ids"),
            claim_ids=self._string_tuple(payload.get("claim_ids"), "claim_ids"),
            control_action=self._string(payload.get("control_action"), "control_action"),
            question_digest=self._string(
                payload.get("question_digest"),
                "question_digest",
            ),
            question_generation=question_generation,
            question_turn_revision=question_turn_revision,
        )

    def _decode_delegations(self, payload: object) -> dict[DelegationId, DelegationRecord]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ActorId,
            DelegationId,
            DelegationRecord,
            DelegationStatus,
            DelegationTopologyPolicy,
            InvalidSessionState,
        )

        if not isinstance(payload, dict):
            raise InvalidSessionState("delegations must be an object")
        delegations: dict[DelegationId, DelegationRecord] = {}
        for raw_id, raw_record in payload.items():
            if not isinstance(raw_id, str) or not isinstance(raw_record, dict):
                raise InvalidSessionState("delegation entries must be keyed objects")
            delegation_id = DelegationId(raw_id)
            record_id = DelegationId(self._string(raw_record.get("id"), "id"))
            if delegation_id != record_id:
                raise InvalidSessionState(f"delegation key/id mismatch: {raw_id}")
            owner_id = ActorId(self._string(raw_record.get("owner_actor_id"), "owner_actor_id"))
            target_id = ActorId(self._string(raw_record.get("target_actor_id"), "target_actor_id"))
            assignment = self._string(raw_record.get("assignment"), "assignment")
            try:
                status = DelegationStatus(raw_record.get("status"))
                raw_topology_policy = raw_record.get("topology_policy")
                topology_policy = (
                    DelegationTopologyPolicy.UNSPECIFIED
                    if raw_topology_policy is None
                    else DelegationTopologyPolicy(raw_topology_policy)
                )
            except (TypeError, ValueError) as error:
                raise InvalidSessionState(
                    f"invalid delegation status or topology policy: {raw_id}"
                ) from error
            result = self._decode_delegation_result(raw_record.get("result"), raw_id)
            delegations[delegation_id] = DelegationRecord(
                delegation_id,
                owner_id,
                target_id,
                assignment,
                status,
                result,
                topology_policy,
            )
        return delegations

    def _decode_delegation_result(
        self,
        payload: object,
        delegation_id: str,
    ) -> DelegationResult | None:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            DelegationResult,
            InvalidSessionState,
        )

        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise InvalidSessionState(f"delegation result must be an object: {delegation_id}")
        verdict = self._string(payload.get("verdict"), "verdict")
        summary = self._string(payload.get("summary"), "summary")
        outcome_ref = self._string(payload.get("outcome_ref"), "outcome_ref")
        raw_findings = payload.get("blocking_findings")
        if not isinstance(raw_findings, list) or any(
            not isinstance(finding, str) or not finding.strip() for finding in raw_findings
        ):
            raise InvalidSessionState(
                f"delegation blocking findings must be strings: {delegation_id}"
            )
        return DelegationResult(
            verdict,
            summary,
            outcome_ref,
            tuple(raw_findings),
        )

    def _decode_incidents(self, payload: object) -> dict[IncidentId, HarnessIncidentRecord]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ActorId,
            HarnessIncidentRecord,
            HarnessIncidentStatus,
            IncidentId,
            InvalidSessionState,
        )

        if not isinstance(payload, dict):
            raise InvalidSessionState("incidents must be an object")
        incidents: dict[IncidentId, HarnessIncidentRecord] = {}
        for raw_id, raw_record in payload.items():
            if not isinstance(raw_id, str) or not isinstance(raw_record, dict):
                raise InvalidSessionState("incident entries must be keyed objects")
            occurrence_id = IncidentId(raw_id)
            record_id = IncidentId(self._string(raw_record.get("occurrence_id"), "occurrence_id"))
            legacy_id = IncidentId(self._string(raw_record.get("id"), "id"))
            if occurrence_id != record_id or occurrence_id != legacy_id:
                raise InvalidSessionState(f"incident key/id mismatch: {raw_id}")
            try:
                status = HarnessIncidentStatus(raw_record.get("status"))
            except (TypeError, ValueError) as error:
                raise InvalidSessionState(f"invalid incident status: {raw_id}") from error
            escalation = raw_record.get("escalation")
            escalation_summary: str | None = None
            reproduction_commands: tuple[str, ...] = ()
            if escalation is not None:
                if (
                    not isinstance(escalation, dict)
                    or escalation.get("handoff_route") != "loop-owner"
                ):
                    raise InvalidSessionState(f"invalid incident escalation: {raw_id}")
                escalation_summary = self._string(escalation.get("summary"), "summary")
                reproduction_commands = self._string_tuple(
                    escalation.get("reproduction_commands"),
                    "reproduction_commands",
                )
            incidents[occurrence_id] = HarnessIncidentRecord(
                occurrence_id=occurrence_id,
                rule_id=self._string(raw_record.get("rule_id"), "rule_id"),
                actor_id=ActorId(self._string(raw_record.get("actor_id"), "actor_id")),
                status=status,
                symptom=self._string(raw_record.get("symptom"), "symptom"),
                recorded_at=self._string(raw_record.get("recorded_at"), "recorded_at"),
                root_cause=self._optional_string(raw_record.get("root_cause"), "root_cause"),
                harness_fix=self._optional_string_tuple(
                    raw_record.get("harness_fix"), "harness_fix"
                ),
                regression_evidence=self._decode_regression_receipts(
                    raw_record.get("regression_evidence")
                ),
                resolved_at=self._optional_string(raw_record.get("resolved_at"), "resolved_at"),
                escalation_summary=escalation_summary,
                reproduction_commands=reproduction_commands,
                escalated_at=self._optional_string(raw_record.get("escalated_at"), "escalated_at"),
                evidence_refreshed_at=self._optional_string(
                    raw_record.get("evidence_refreshed_at"),
                    "evidence_refreshed_at",
                ),
                evidence_superseded_at=self._optional_string(
                    raw_record.get("evidence_superseded_at"),
                    "evidence_superseded_at",
                ),
                superseded_resolution_evidence=self._decode_incident_archives(
                    raw_record.get("superseded_resolution_evidence")
                ),
            )
        return incidents

    def _decode_outbox(self, payload: object) -> dict[EffectId, OutboxEffect]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            ActorId,
            EffectId,
            EffectKind,
            InvalidSessionState,
            OutboxEffect,
        )

        if not isinstance(payload, dict):
            raise InvalidSessionState("outbox must be an object")
        effects: dict[EffectId, OutboxEffect] = {}
        for raw_id, raw_effect in payload.items():
            if not isinstance(raw_id, str) or not isinstance(raw_effect, dict):
                raise InvalidSessionState("outbox entries must be keyed objects")
            effect_id = EffectId(raw_id)
            persisted_id = EffectId(self._string(raw_effect.get("id"), "id"))
            if effect_id != persisted_id:
                raise InvalidSessionState(f"outbox key/id mismatch: {raw_id}")
            try:
                kind = EffectKind(raw_effect.get("kind"))
            except (TypeError, ValueError) as error:
                raise InvalidSessionState(f"invalid outbox effect kind: {raw_id}") from error
            raw_payload = raw_effect.get("payload")
            if not isinstance(raw_payload, dict) or any(
                not isinstance(key, str) for key in raw_payload
            ):
                raise InvalidSessionState(f"outbox effect payload is invalid: {raw_id}")
            effects[effect_id] = OutboxEffect(
                effect_id=effect_id,
                actor_id=ActorId(self._string(raw_effect.get("actor_id"), "actor_id")),
                kind=kind,
                delivery_key=self._string(raw_effect.get("delivery_key"), "delivery_key"),
                payload={str(key): value for key, value in raw_payload.items()},
            )
        return effects

    def _decode_regression_receipts(
        self,
        payload: object,
    ) -> tuple[HarnessRegressionReceipt, ...]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            HarnessRegressionReceipt,
            InvalidSessionState,
        )

        if payload is None:
            return ()
        if not isinstance(payload, list):
            raise InvalidSessionState("regression_evidence must be an array")
        receipts: list[HarnessRegressionReceipt] = []
        for raw_receipt in payload:
            if not isinstance(raw_receipt, dict):
                raise InvalidSessionState("regression_evidence entries must be objects")
            exit_code = raw_receipt.get("exit_code")
            if not isinstance(exit_code, int) or isinstance(exit_code, bool):
                raise InvalidSessionState("regression receipt exit_code must be an integer")
            receipts.append(
                HarnessRegressionReceipt(
                    command=self._string(raw_receipt.get("command"), "command"),
                    exit_code=exit_code,
                    head_sha=self._string(raw_receipt.get("head_sha"), "head_sha"),
                    verified_at=self._string(raw_receipt.get("verified_at"), "verified_at"),
                    output_sha256=self._string(
                        raw_receipt.get("output_sha256"),
                        "output_sha256",
                    ),
                )
            )
        return tuple(receipts)

    def _decode_incident_archives(
        self,
        payload: object,
    ) -> tuple[HarnessIncidentEvidenceArchive, ...]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            HarnessIncidentEvidenceArchive,
            InvalidSessionState,
        )

        if payload is None:
            return ()
        if not isinstance(payload, list):
            raise InvalidSessionState("superseded_resolution_evidence must be an array")
        archives: list[HarnessIncidentEvidenceArchive] = []
        for raw_archive in payload:
            if not isinstance(raw_archive, dict):
                raise InvalidSessionState("superseded resolution entries must be objects")
            archives.append(
                HarnessIncidentEvidenceArchive(
                    harness_fix=self._string_tuple(raw_archive.get("harness_fix"), "harness_fix"),
                    regression_evidence=self._decode_regression_receipts(
                        raw_archive.get("regression_evidence")
                    ),
                    superseded_at=self._string(
                        raw_archive.get("superseded_at"),
                        "superseded_at",
                    ),
                )
            )
        return tuple(archives)

    def _optional_string(self, value: object, key: str) -> str | None:
        if value is None:
            return None
        return self._string(value, key)

    def _string_tuple(self, value: object, key: str) -> tuple[str, ...]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            InvalidSessionState,
        )

        if not isinstance(value, list) or not value:
            raise InvalidSessionState(f"{key} must be a non-empty string array")
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise InvalidSessionState(f"{key} must contain non-empty strings")
        return tuple(item.strip() for item in value if isinstance(item, str))

    def _optional_string_tuple(self, value: object, key: str) -> tuple[str, ...]:
        if value is None:
            return ()
        return self._string_tuple(value, key)

    def _object_mapping(self, payload: dict[object, object], key: str) -> dict[str, object]:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            InvalidSessionState,
        )

        value = payload.get(key)
        if not isinstance(value, dict) or any(not isinstance(item, str) for item in value):
            raise InvalidSessionState(f"{key} must be a string-keyed object")
        return {str(item): entry for item, entry in value.items()}

    def _string(self, value: object, key: str) -> str:
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            InvalidSessionState,
        )

        if not isinstance(value, str) or not value.strip():
            raise InvalidSessionState(f"{key} must be a non-empty string")
        return value


class SessionStateValidator:
    """Cross-record state invariant를 read와 commit 양쪽에서 검증합니다."""

    def validate(self, state: ProcessState) -> None:
        """Session, actor lineage, delegation reference의 정합성을 검증합니다.

        Args:
            state: Read 또는 commit boundary에서 신뢰하기 전에 검사할 snapshot입니다.

        Raises:
            InvalidSessionState: Root topology, subagent parent, delegation reference가
                서로 일치하지 않으면 발생합니다.
        """
        from scripts.agent_harness.session_kernel import (  # noqa: PLC0415 - codec/model cycle
            MAX_PENDING_OUTBOX_EFFECTS,
            ActorKind,
            ActorLineageAssurance,
            ActorStatus,
            DelegationStatus,
            DelegationTopologyPolicy,
            ForegroundTurnStatus,
            InvalidSessionState,
            MaterialActionStatus,
            SessionStatus,
            WorkflowId,
        )

        root = state.actors.get(state.session.root_actor_id)
        if root is None:
            raise InvalidSessionState("root actor is missing")
        if root.kind is not ActorKind.ROOT or root.parent_actor_id is not None:
            raise InvalidSessionState("root actor topology is invalid")
        if root.lineage_assurance is not ActorLineageAssurance.UNATTESTED:
            raise InvalidSessionState("root actor cannot claim parent lineage assurance")
        roots = tuple(actor for actor in state.actors.values() if actor.kind is ActorKind.ROOT)
        if len(roots) != 1:
            raise InvalidSessionState("exactly one root actor is required")
        if state.session.status is SessionStatus.ACTIVE and root.status not in {
            ActorStatus.ACTIVE,
            ActorStatus.IDLE,
        }:
            raise InvalidSessionState("active session requires an available root actor")
        for actor_id, actor in state.actors.items():
            if actor.id != actor_id:
                raise InvalidSessionState(f"actor key/id mismatch: {actor_id}")
            if actor.kind is ActorKind.SUBAGENT and (
                actor.parent_actor_id is None or actor.parent_actor_id not in state.actors
            ):
                raise InvalidSessionState(f"subagent parent is missing: {actor.id}")
        for workflow_id, workflow in state.workflows.items():
            if workflow.id != workflow_id:
                raise InvalidSessionState(f"workflow key/id mismatch: {workflow_id}")
            if workflow.owner_actor_id not in state.actors:
                raise InvalidSessionState(f"workflow owner is missing: {workflow.id}")
            if workflow.revision < 0:
                raise InvalidSessionState(f"workflow revision is invalid: {workflow.id}")
        for actor_id, turn in state.foreground_turns.items():
            if turn.owner_actor_id != actor_id:
                raise InvalidSessionState(f"foreground turn key/owner mismatch: {actor_id}")
            if actor_id not in state.actors:
                raise InvalidSessionState(f"foreground turn owner is missing: {actor_id}")
            user_receipt = turn.user_prompt_receipt
            if user_receipt is None or user_receipt.authority_context is None:
                continue
            context = user_receipt.authority_context
            workflow = state.workflows.get(context.workflow_id)
            if workflow is None or workflow.owner_actor_id != actor_id:
                raise InvalidSessionState(
                    f"foreground user prompt workflow is missing or foreign: {context.workflow_id}"
                )
        for actor_id, batch in state.material_actions.items():
            if actor_id not in state.actors or batch.actor_id != str(actor_id):
                raise InvalidSessionState(
                    f"material action owner is missing or foreign: {actor_id}"
                )
            if batch.session_id != str(state.session.id):
                raise InvalidSessionState(f"material action session is foreign: {batch.batch_id}")
            turn = state.foreground_turns.get(actor_id)
            if turn is None or batch.turn_generation > turn.generation:
                raise InvalidSessionState(f"material action foreground turn is missing: {actor_id}")
            if batch.status is MaterialActionStatus.OPEN and (
                turn.status is not ForegroundTurnStatus.ACTIVE
                or batch.turn_generation != turn.generation
                or batch.turn_revision != turn.revision
            ):
                raise InvalidSessionState(
                    f"open material action is stale for foreground turn: {batch.batch_id}"
                )
            binding = batch.adaptive_binding
            if binding is not None:
                workflow = state.workflows.get(WorkflowId(binding.workflow_id))
                if (
                    workflow is None
                    or workflow.owner_actor_id != actor_id
                    or workflow.revision < binding.workflow_revision
                ):
                    raise InvalidSessionState(
                        f"material action adaptive workflow is missing or foreign: {binding.workflow_id}"
                    )
        for delegation_id, delegation in state.delegations.items():
            if delegation.id != delegation_id:
                raise InvalidSessionState(f"delegation key/id mismatch: {delegation_id}")
            if delegation.owner_actor_id not in state.actors:
                raise InvalidSessionState(f"delegation owner is missing: {delegation.id}")
            if delegation.target_actor_id not in state.actors:
                raise InvalidSessionState(f"delegation target is missing: {delegation.id}")
            target = state.actors[delegation.target_actor_id]
            if delegation.topology_policy is DelegationTopologyPolicy.DIRECT_CHILD and (
                target.kind is not ActorKind.SUBAGENT
                or target.parent_actor_id != delegation.owner_actor_id
                or target.lineage_assurance is not ActorLineageAssurance.HOST_ATTESTED
            ):
                raise InvalidSessionState(
                    f"direct-child delegation topology or assurance is invalid: {delegation.id}"
                )
            if delegation.status is DelegationStatus.PENDING and delegation._result is not None:
                raise InvalidSessionState(f"pending delegation has a result: {delegation.id}")
            if delegation.status is not DelegationStatus.PENDING and delegation._result is None:
                raise InvalidSessionState(f"reported delegation result is missing: {delegation.id}")
        for incident_id, incident in state.incidents.items():
            if incident.id != incident_id:
                raise InvalidSessionState(f"incident key/id mismatch: {incident_id}")
            if incident.actor_id not in state.actors:
                raise InvalidSessionState(f"incident actor is missing: {incident.id}")
        if len(state.outbox) > MAX_PENDING_OUTBOX_EFFECTS:
            raise InvalidSessionState("pending outbox exceeds its bounded capacity")
        delivery_keys: set[str] = set()
        for effect_id, effect in state.outbox.items():
            if effect.id != effect_id:
                raise InvalidSessionState(f"outbox key/id mismatch: {effect_id}")
            if effect.actor_id not in state.actors:
                raise InvalidSessionState(f"outbox effect actor is missing: {effect_id}")
            if effect.delivery_key in delivery_keys:
                raise InvalidSessionState(
                    f"outbox delivery key is duplicated: {effect.delivery_key}"
                )
            delivery_keys.add(effect.delivery_key)
