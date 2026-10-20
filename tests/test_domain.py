"""Git·SQL·어댑터 없이 동일성과 상태 전이 정책을 검증한다."""

from dataclasses import FrozenInstanceError, asdict

import pytest

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
        ProjectLocation(kind=ProjectKind.FOLDER, path="/folder"),
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
        first.associate((ProjectLocation(kind=ProjectKind.GIT, path="/different/.git"),))
    assert first.locations == before
    assert Project.owner_of((first, first)) is first
    assert Project.owner_of(()) is None


def test_owned_location_is_an_immutable_value_without_owner_identity():
    location = ProjectLocation(kind=ProjectKind.FOLDER, path="/root")
    assert location == ProjectLocation(kind=ProjectKind.FOLDER, path="/root")
    assert location != ProjectLocation(kind=ProjectKind.GIT, path="/root")
    with pytest.raises(FrozenInstanceError):
        location.path = "/changed"


def test_entity_identity_is_stable_while_its_state_changes():
    project = Project(uid="project", root_path="/root")
    session = HostSession(
        uid="session",
        project_id=project.id,
        provider="codex",
        host_session_id="native",
        working_directory="/root",
        revision=1,
    )
    before = asdict(session)
    same_identity = HostSession(
        uid="session",
        project_id=project.id,
        provider="codex",
        host_session_id="native",
        working_directory="/different",
        revision=8,
    )
    assert session == same_identity
    assert project == Project(uid=project.id, root_path="/another-root")
    session.move("/next", 1)
    assert session.id == "session" and session.working_directory == "/next"
    assert session.revision == 1  # 정수 잠금 카운터는 ORM이 저장할 때 갱신한다.
    assert asdict(session) != before
    assert before["working_directory"] == "/root"


def test_domain_rejects_stale_movement_without_mutating_state():
    session = HostSession(
        uid="session",
        project_id="project",
        provider="codex",
        host_session_id="native",
        working_directory="/root",
        revision=3,
    )
    with pytest.raises(RevisionConflict):
        session.move("/next", 2)
    assert session.working_directory == "/root" and session.revision == 3


@pytest.mark.parametrize(("provider", "native"), [(" ", "native"), ("codex", "")])
def test_domain_rejects_empty_native_identity(provider, native):
    with pytest.raises(ValueError):
        HostSession.create("project", provider, native, "/root")
