"""PR #159의 불변 계약·UUID·지원 공급자 경계를 실제 타입과 저장 동작으로 검증한다."""

import importlib
import inspect
import pkgutil
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4, uuid7

import pytest

import neurath.domain.aggregates
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.usecases.close_conversation import CloseConversationCommand
from neurath.domain.aggregates.project import Project
from neurath.domain.observations import DirectoryObservation
from neurath.domain.provider import ProviderKind
from neurath.infrastructure.provider_worker import _execution_arguments
from neurath.infrastructure.uuid_type import UUIDText
from neurath.serialization import encode_uuid
from tests.conftest import storage_scope
from tools.architecture import ArchitectureChecker


def aggregate_types():
    from spakky.domain.models.aggregate_root import AbstractAggregateRoot

    for entry in pkgutil.iter_modules(
        neurath.domain.aggregates.__path__, neurath.domain.aggregates.__name__ + "."
    ):
        module = importlib.import_module(entry.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, AbstractAggregateRoot):
                yield cls


@pytest.mark.parametrize("aggregate", list(aggregate_types()), ids=lambda cls: cls.__name__)
def test_all_internal_primary_keys_are_ordered_uuid7_values(aggregate):
    first, second = aggregate.next_id(), aggregate.next_id()
    assert isinstance(first, UUID) and first.version == 7
    assert isinstance(second, UUID) and second.version == 7
    assert first.int < second.int
    assert inspect.signature(aggregate.next_id).return_annotation is UUID


@pytest.mark.parametrize(
    "decorator", ["dataclasses.dataclass(frozen=True)", "record(frozen=True, kw_only=True)"]
)
def test_frozen_dataclass_aliases_are_rejected_for_product_contracts(decorator):
    source = f"""import dataclasses
from dataclasses import dataclass as record
@{decorator}
class Request:
    value: str
"""
    violations = ArchitectureChecker({"neurath.application.requests": source}).check()
    assert any("IMMUTABLE_CONTRACT" in item for item in violations)


def test_mutable_dataclass_and_framework_immutable_are_not_blanket_banned():
    source = """from dataclasses import dataclass
from spakky.core.common.mutability import immutable
@dataclass
class MutableBuffer:
    value: str
@immutable
class Request:
    value: str
"""
    assert ArchitectureChecker({"neurath.application.requests": source}).check() == []


def test_commands_use_keyword_only_immutable_fields():
    command = CloseConversationCommand(conversation_id=uuid7(), peer_id=uuid7())
    assert all(
        p.kind is inspect.Parameter.KEYWORD_ONLY
        for p in inspect.signature(CloseConversationCommand).parameters.values()
    )
    with pytest.raises(FrozenInstanceError):
        command.peer_id = uuid7()


async def test_existing_uuid4_values_and_foreign_keys_keep_their_stored_representation(
    database, tmp_path
):
    import sqlite3

    original = uuid4()
    project = Project.create(DirectoryObservation(working_directory=str(tmp_path)))
    project.uid = original
    async with storage_scope(database) as scope:
        await scope.get(IProjectRepository).save(project)
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT id FROM core_projects").fetchall()
    async with storage_scope(database, write=False) as scope:
        restored = await scope.get(IProjectRepository).get(original)
    assert restored.uid == original and restored.uid.version == 4
    assert before == [(str(original),)]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id FROM core_projects").fetchall() == before
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_uuid_boundary_rejects_invalid_stored_identity_without_reissuing_it():
    from sqlalchemy.dialects.sqlite import dialect

    storage = UUIDText()
    with pytest.raises(ValueError):
        storage.process_result_value("legacy-opaque-id", dialect())
    assert storage.process_bind_param(None, dialect()) is None
    assert storage.process_result_value(None, dialect()) is None
    assert encode_uuid(UUID(int=1)) == str(UUID(int=1))
    with pytest.raises(TypeError):
        encode_uuid(object())


def test_worker_requires_an_explicit_supported_provider_enum():
    plan = {"model": "model", "policy": "read-only", "directory": "/fixture"}
    assert _execution_arguments(ProviderKind.CODEX, plan, "session")[0] == "codex"
    assert _execution_arguments(ProviderKind.CLAUDE, plan, "session")[0] == "claude"
    with pytest.raises(ValueError):
        ProviderKind("unsupported-provider")


def test_missing_provider_parent_is_rejected_instead_of_inventing_an_identity():
    from neurath.infrastructure.models.delegation import DelegationModel

    record = DelegationModel(plan_provider="codex", plan_parent_session_id=None)
    with pytest.raises(ValueError, match="parent session"):
        record._provider_plan()


@pytest.mark.parametrize(
    "function,args",
    [
        ("arguments", ()),
        ("initialize", ()),
        ("page", ({},)),
        ("worker", ({}, "session")),
        ("policies", ("",)),
    ],
)
def test_unknown_provider_never_falls_through_to_claude(function, args):
    from neurath.infrastructure import provider_protocol
    from neurath.infrastructure.provider import SubprocessProviderService

    functions = {
        "arguments": provider_protocol._discovery_arguments,
        "initialize": provider_protocol._initial_request,
        "page": provider_protocol._parse_page,
        "worker": _execution_arguments,
        "policies": SubprocessProviderService._supported_policies,
    }
    with pytest.raises(ValueError, match="Unsupported provider"):
        functions[function]("unsupported", *args)


def test_initial_notifications_do_not_claim_a_model_catalog_or_process_start(tmp_path, monkeypatch):
    import json

    from neurath.domain.provider import ProviderStatus
    from neurath.infrastructure.provider import SubprocessProviderService
    from neurath.infrastructure.provider_protocol import _parse_page

    assert _parse_page(ProviderKind.CODEX, {"method": "notification"}) is None
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    service = SubprocessProviderService()
    uid = uuid7()
    directory = service._directory(uid)
    directory.mkdir(parents=True)
    (directory / "output.jsonl").write_text(
        json.dumps({"type": "system", "subtype": "init", "session_id": "observed-native"}) + "\n"
    )
    observed = service.observe(uid)
    assert observed.native_session_id == "observed-native"
    assert observed.status is ProviderStatus.UNKNOWN and observed.output == ""


def test_reusing_root_assignment_does_not_confuse_another_senders_child_assignment():
    from dataclasses import replace

    from neurath.domain.aggregates.delegation import Delegation
    from neurath.domain.delegation_records import DelegationRole, DelegationRoute

    root = Delegation(
        uid=uuid7(),
        task_id=uuid7(),
        definition_number=1,
        source_id=uuid7(),
        sender_id=uuid7(),
        recipient_id=uuid7(),
        role=DelegationRole.EXECUTOR,
        scope="assigned work",
        route=DelegationRoute.PEER,
    )
    child = replace(root, uid=uuid7(), sender_id=uuid7(), parent_id=root.uid)
    assert root.find_reusable([child, root]) is root


def test_all_domain_and_application_immutable_records_use_framework_constructor_contract():
    import dataclasses

    import neurath.application
    import neurath.domain

    checked = []
    for package in (neurath.application, neurath.domain):
        for entry in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            module = importlib.import_module(entry.name)
            for name, cls in inspect.getmembers(module, inspect.isclass):
                if cls.__module__ != module.__name__ or not dataclasses.is_dataclass(cls):
                    continue
                parameters = cls.__dataclass_params__
                if not parameters.frozen:
                    continue
                assert not parameters.eq, name
                assert all(
                    parameter.kind is inspect.Parameter.KEYWORD_ONLY
                    for parameter in inspect.signature(cls).parameters.values()
                ), name
                checked.append(cls)
    assert CloseConversationCommand in checked
