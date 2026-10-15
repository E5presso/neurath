"""Identity and transition policies tested without Git, SQL, or adapters."""

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
    assert ProjectLocation.identify(primary) == ProjectLocation.identify(linked)
    assert ProjectLocation.identify(primary) != ProjectLocation.identify(clone)
    assert Project.create(linked).root_path == "/repo"
    assert ProjectLocation.identify(DirectoryObservation("/folder")) == (
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
        ProjectLocation.identify(observation)


def test_folder_promotion_from_first_linked_observation_retains_entity_identity():
    project = Project("retained", "/repo")
    folder = ProjectLocation(ProjectKind.FOLDER, "/repo", project.id)
    git, observed_folder = ProjectLocation.identify(
        DirectoryObservation("/linked", "/repo/.git", "/repo")
    )
    assert folder == observed_folder  # Identity is independent of association state.
    assert ProjectLocation.owner_of((git, folder)) == project.id
    project.associate((git, folder), (folder,))
    assert git.project_id == folder.project_id == "retained"
    assert project.id == "retained" and project.root_path == "/repo"


def test_conflicting_owners_and_replacement_git_identity_never_partially_associate():
    project = Project("first", "/root")
    folder = ProjectLocation(ProjectKind.FOLDER, "/root", "second")
    git = ProjectLocation(ProjectKind.GIT, "/root/.git")
    with pytest.raises(ProjectIdentityConflict):
        project.associate((git, folder), ())
    assert git.project_id is None and folder.project_id == "second"
    folder.associate("second")
    with pytest.raises(ProjectIdentityConflict):
        folder.associate("first")
    previous = ProjectLocation(ProjectKind.GIT, "/old/.git", "first")
    with pytest.raises(ProjectIdentityConflict):
        project.associate((git,), (previous,))
    assert git.project_id is None
    with pytest.raises(ProjectIdentityConflict):
        ProjectLocation.owner_of((folder, previous))


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
