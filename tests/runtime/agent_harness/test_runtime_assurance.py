"""Repository wiring과 host attestation의 runtime assurance 경계를 검증합니다."""

import hashlib
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest import TestCase

from scripts.agent_harness.runtime_assurance import (
    AssuranceAvailability,
    AssuranceEvidenceSource,
    RuntimeAssurance,
    RuntimeAssuranceError,
    RuntimeAssuranceInventory,
    RuntimeAssuranceProfile,
    RuntimeConfigDigest,
)
from scripts.agent_harness.session_kernel import SessionRuntime


class RuntimeAssuranceInventoryTest(TestCase):
    """Runtime별 repository sensor와 host-only assurance를 과장 없이 분리합니다."""

    def setUp(self) -> None:
        """Current repository root에 결속된 assurance inventory를 준비합니다."""
        self.root = Path(__file__).resolve().parents[3]
        self.inventory = RuntimeAssuranceInventory(self.root)

    def test_profile_is_typed_immutable_and_binds_exact_config_digest(self) -> None:
        """Profile은 runtime config bytes와 immutable typed identity를 함께 고정합니다."""
        profile = self.inventory.profile(SessionRuntime.CODEX)
        config_path = self.root / ".codex/hooks.json"
        expected_digest = RuntimeConfigDigest(
            f"sha256:{hashlib.sha256(config_path.read_bytes()).hexdigest()}"
        )

        self.assertIsInstance(profile, RuntimeAssuranceProfile)
        self.assertEqual(SessionRuntime.CODEX, profile.runtime)
        self.assertEqual(Path(".codex/hooks.json"), profile.config_path)
        self.assertEqual(expected_digest, profile.config_digest)
        self.assertIsInstance(profile.config_digest, RuntimeConfigDigest)
        self.assertIsInstance(profile.wired_events, frozenset)
        self.assertIsInstance(profile.assurances, tuple)
        with self.assertRaises(FrozenInstanceError):
            RuntimeAssuranceProfile.__setattr__(
                profile,
                "runtime",
                SessionRuntime.CLAUDE_CODE,
            )

    def test_claude_repository_wiring_declares_child_terminal_and_failure_sensors(self) -> None:
        """Claude config의 wiring은 sensor를 DECLARED로만 projection합니다."""
        profile = self.inventory.profile(SessionRuntime.CLAUDE_CODE)
        assurances = {item.assurance: item for item in profile.assurances}

        self.assertEqual(Path(".claude/settings.json"), profile.config_path)
        self.assertTrue(
            {
                "SubagentStart",
                "SubagentStop",
                "SessionEnd",
                "PostToolUseFailure",
                "PermissionDenied",
            }.issubset(profile.wired_events)
        )
        session_end = assurances[RuntimeAssurance.SESSION_END_SENSOR]
        self.assertEqual(AssuranceAvailability.DECLARED, session_end.availability)
        self.assertEqual(
            AssuranceEvidenceSource.REPOSITORY_WIRING,
            session_end.evidence_source,
        )
        for assurance in (
            RuntimeAssurance.CHILD_START_SENSOR,
            RuntimeAssurance.CHILD_STOP_SENSOR,
            RuntimeAssurance.MATERIAL_ACTION_FAILURE_SENSOR,
            RuntimeAssurance.PERMISSION_DENIED_SENSOR,
        ):
            with self.subTest(assurance=assurance):
                self.assertEqual(
                    AssuranceAvailability.DECLARED,
                    assurances[assurance].availability,
                )
                self.assertEqual(
                    AssuranceEvidenceSource.REPOSITORY_WIRING,
                    assurances[assurance].evidence_source,
                )

    def test_codex_repository_wiring_declares_common_child_and_session_end_sensors(self) -> None:
        """Codex common lifecycle wiring은 선언만 증명하고 live delivery는 증명하지 않습니다."""
        profile = self.inventory.profile(SessionRuntime.CODEX)
        assurances = {item.assurance: item for item in profile.assurances}

        self.assertTrue(
            {"SubagentStart", "SubagentStop", "SessionEnd"}.issubset(profile.wired_events)
        )
        self.assertTrue({"PostToolUseFailure", "PermissionDenied"}.isdisjoint(profile.wired_events))
        session_end = assurances[RuntimeAssurance.SESSION_END_SENSOR]
        self.assertEqual(AssuranceAvailability.DECLARED, session_end.availability)
        self.assertEqual(
            AssuranceEvidenceSource.REPOSITORY_WIRING,
            session_end.evidence_source,
        )
        for assurance in (
            RuntimeAssurance.CHILD_START_SENSOR,
            RuntimeAssurance.CHILD_STOP_SENSOR,
        ):
            with self.subTest(assurance=assurance):
                self.assertEqual(
                    AssuranceAvailability.DECLARED,
                    assurances[assurance].availability,
                )
                self.assertEqual(
                    AssuranceEvidenceSource.REPOSITORY_WIRING,
                    assurances[assurance].evidence_source,
                )
        for assurance in (
            RuntimeAssurance.MATERIAL_ACTION_FAILURE_SENSOR,
            RuntimeAssurance.PERMISSION_DENIED_SENSOR,
        ):
            with self.subTest(assurance=assurance):
                self.assertEqual(
                    AssuranceAvailability.UNAVAILABLE,
                    assurances[assurance].availability,
                )
                self.assertEqual(
                    AssuranceEvidenceSource.REPOSITORY_WIRING,
                    assurances[assurance].evidence_source,
                )

    def test_repository_config_does_not_self_attest_host_only_assurances(self) -> None:
        """Repository hook 선언은 lineage, mutation 권한, delivery 의미의 증명이 아닙니다."""
        host_only = (
            RuntimeAssurance.IMMEDIATE_PARENT_LINEAGE,
            RuntimeAssurance.HOST_MANAGED_MUTATION_AUTHORITY,
            RuntimeAssurance.EVENT_DELIVERY_SEMANTICS,
        )

        for runtime in SessionRuntime:
            assurances = {
                item.assurance: item for item in self.inventory.profile(runtime).assurances
            }
            for assurance in host_only:
                with self.subTest(runtime=runtime, assurance=assurance):
                    self.assertEqual(
                        AssuranceAvailability.UNAVAILABLE,
                        assurances[assurance].availability,
                    )
                    self.assertEqual(
                        AssuranceEvidenceSource.HOST_ATTESTATION,
                        assurances[assurance].evidence_source,
                    )

    def test_profile_separates_declared_wiring_from_host_admission(self) -> None:
        """Config declaration은 typed query로 보존되지만 host admission이 되지 않습니다."""
        profile = self.inventory.profile(SessionRuntime.CLAUDE_CODE)

        self.assertTrue(profile.is_declared(RuntimeAssurance.CHILD_START_SENSOR))
        self.assertFalse(profile.is_admissible(RuntimeAssurance.CHILD_START_SENSOR))
        self.assertFalse(profile.is_declared(RuntimeAssurance.IMMEDIATE_PARENT_LINEAGE))
        self.assertFalse(profile.is_admissible(RuntimeAssurance.IMMEDIATE_PARENT_LINEAGE))

        missing = replace(
            profile,
            assurances=tuple(
                item
                for item in profile.assurances
                if item.assurance is not RuntimeAssurance.IMMEDIATE_PARENT_LINEAGE
            ),
        )
        duplicate = replace(
            profile,
            assurances=profile.assurances + (profile.assurances[0],),
        )
        with self.assertRaises(RuntimeAssuranceError):
            missing.is_admissible(RuntimeAssurance.IMMEDIATE_PARENT_LINEAGE)
        with self.assertRaises(RuntimeAssuranceError):
            duplicate.is_declared(profile.assurances[0].assurance)
