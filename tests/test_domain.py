"""Git·SQL·어댑터 없이 동일성과 상태 전이 정책을 검증한다."""

from dataclasses import FrozenInstanceError

import pytest

from neurath.application.context import SessionContext
from neurath.domain.aggregates.project import Project, ProjectKind, ProjectLocation
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import ProjectIdentityConflict, RevisionConflict
from neurath.domain.observations import DirectoryObservation


def test_identity_and_root_policy_distinguishes_clones_and_unifies_worktrees():
    primary = DirectoryObservation("/repo", "/repo/.git", "/repo")
    linked = DirectoryObservation("/linked/child", "/repo/.git", "/repo")
    clone = DirectoryObservation("/clone", "/clone/.git", "/clone")
    assert Project.identify(primary) == Project.identify(linked)
    assert Project.identify(primary) != Project.identify(clone)
    assert Project.create(linked).root_path == "/repo"
    assert Project.identify(DirectoryObservation("/folder")) == (
        ProjectLocation(ProjectKind.FOLDER, "/folder"),
    )


@pytest.mark.parametrize(
    "observation",
    [
        DirectoryObservation("/path", "/git", None),
        DirectoryObservation("/path", None, "/root"),
    ],
)
def test_incomplete_git_facts_are_rejected_in_domain(observation):
    with pytest.raises(ValueError):
        Project.identify(observation)


def test_folder_promotion_from_first_linked_observation_retains_entity_identity():
    project = Project.create(DirectoryObservation("/repo"))
    retained_id = project.id
    candidates = Project.identify(DirectoryObservation("/linked", "/repo/.git", "/repo"))
    assert Project.owner_of((project,)) is project
    project.associate(candidates)
    assert set(project.locations) == set(candidates)
    assert project.id == retained_id and project.root_path == "/repo"


def test_conflicting_owners_and_replacement_git_identity_never_partially_associate():
    first = Project.create(DirectoryObservation("/one", "/one/.git", "/one"))
    second = Project.create(DirectoryObservation("/two"))
    before = first.locations
    with pytest.raises(ProjectIdentityConflict):
        Project.owner_of((first, second))
    with pytest.raises(ProjectIdentityConflict):
        first.associate((ProjectLocation(ProjectKind.GIT, "/different/.git"),))
    assert first.locations == before
    assert Project.owner_of((first, first)) is first
    assert Project.owner_of(()) is None


def test_owned_location_is_an_immutable_value_without_owner_identity():
    location = ProjectLocation(ProjectKind.FOLDER, "/root")
    assert location == ProjectLocation(ProjectKind.FOLDER, "/root")
    assert location != ProjectLocation(ProjectKind.GIT, "/root")
    with pytest.raises(FrozenInstanceError):
        location.path = "/changed"


def test_entity_identity_is_stable_while_snapshot_equality_compares_state():
    project = Project("project", "/root")
    session = HostSession("session", project.id, "codex", "native", "/root", 1)
    before = SessionContext.from_entities(project, session)
    same_identity = HostSession("session", project.id, "codex", "native", "/different", 8)
    assert session == same_identity
    assert project == Project(project.id, "/another-root")
    session.move("/next", 1)
    assert session.id == "session" and session.working_directory == "/next"
    assert session.revision == 1  # Persistence owns the optimistic version counter.
    assert SessionContext.from_entities(project, session) != before
    assert before.session.working_directory == "/root"
    with pytest.raises(FrozenInstanceError):
        before.session.revision = 2


def test_domain_rejects_stale_movement_without_mutating_state():
    session = HostSession("session", "project", "codex", "native", "/root", 3)
    with pytest.raises(RevisionConflict):
        session.move("/next", 2)
    assert session.working_directory == "/root" and session.revision == 3


@pytest.mark.parametrize(("provider", "native"), [(" ", "native"), ("codex", "")])
def test_domain_rejects_empty_native_identity(provider, native):
    with pytest.raises(ValueError):
        HostSession.create("project", provider, native, "/root")
