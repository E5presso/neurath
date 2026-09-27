"""Codec 추출이 공개 import와 기존 snapshot byte 계약을 보존하는지 검증합니다."""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness import (
    session_events,
    session_kernel,
    session_model,
    session_store,
)
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle


class SessionStateCodecBoundaryTest(TestCase):
    """직렬화와 상태 검증의 별도 소유자가 기존 kernel API와 동일하게 동작합니다."""

    def test_public_classes_and_snapshot_bytes_are_preserved(self) -> None:
        """기존 import는 같은 클래스이며 실제 snapshot round-trip byte가 바뀌지 않습니다."""
        module = importlib.import_module("scripts.agent_harness.session_state_codec")
        self.assertIs(module.SessionStateCodec, session_kernel.SessionStateCodec)
        self.assertIs(module.SessionStateValidator, session_kernel.SessionStateValidator)
        self.assertIs(session_model.ProcessState, session_kernel.ProcessState)
        self.assertIs(session_model.RevisionConflict, session_kernel.RevisionConflict)
        self.assertIs(session_events.SessionStarted, session_kernel.SessionStarted)
        self.assertIs(session_store.SessionStateStore, session_kernel.SessionStateStore)
        with TemporaryDirectory() as directory:
            handle = StateHandle.initialize(
                session_kernel.SessionLocator(Path(directory)),
                RuntimeEnvironmentResolver().resolve({"CODEX_THREAD_ID": "codec-extraction"}),
            )
            state = handle.inspect()
            encoded = session_kernel.SessionStateCodec().encode(state)
            decoded = module.SessionStateCodec().decode(json.loads(encoded), state.session.id)
            self.assertEqual(encoded, module.SessionStateCodec().encode(decoded))

    def test_import_order_does_not_create_a_cycle(self) -> None:
        """새 소유자와 공개 kernel을 어느 순서로 import해도 같은 객체를 반환합니다."""
        for first, second in (
            ("session_kernel", "session_state_codec"),
            ("session_state_codec", "session_kernel"),
            ("session_model", "session_kernel, session_state_codec"),
            ("session_store", "session_kernel, session_state_codec"),
        ):
            with self.subTest(first=first):
                result = subprocess.run(
                    (
                        sys.executable,
                        "-c",
                        f"from scripts.agent_harness import {first}, {second}; "
                        "assert session_kernel.SessionStateCodec is session_state_codec.SessionStateCodec; "
                        "assert session_kernel.SessionStateValidator is session_state_codec.SessionStateValidator",
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_model_import_does_not_initialize_storage_or_kernel(self) -> None:
        """Consumers of decoded values can load the model without loading persistence."""
        result = subprocess.run(
            (
                sys.executable,
                "-c",
                "import sys; from scripts.agent_harness.session_model import SessionId; "
                "assert SessionId('domain-only') == 'domain-only'; "
                "assert 'scripts.agent_harness.session_kernel' not in sys.modules; "
                "assert 'scripts.agent_harness.session_store' not in sys.modules; "
                "assert 'scripts.agent_harness.runtime_database' not in sys.modules",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_pre_refactor_snapshot_reencodes_without_data_loss(self) -> None:
        """Persisted actor/workflow/prompt/delegation/incident/outbox data remains readable."""
        encoded = (
            Path(__file__).with_name("fixtures").joinpath("session_snapshot_v1.json").read_bytes()
        )
        state = session_kernel.SessionStateCodec().decode(
            json.loads(encoded), session_kernel.SessionId("snapshot-compat")
        )
        self.assertEqual(encoded, session_kernel.SessionStateCodec().encode(state))
        # An unrelated actor transition must retain every already persisted aggregate.
        advanced = session_kernel.SessionStateReducer().reduce(
            state,
            session_kernel.ActorStarted(
                session_kernel.SessionId("snapshot-compat"),
                session_kernel.ActorId("codex:another-child"),
                session_kernel.ActorId("codex:root"),
                session_kernel.ActorKind.SUBAGENT,
                "another-child-start",
            ),
        )
        expected = json.loads(encoded)
        actual = advanced.to_payload()
        del actual["actors"]["codex:another-child"]
        self.assertEqual(expected, actual)
