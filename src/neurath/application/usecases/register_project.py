"""Orchestrate primitive reads and writes around project identity domain actions."""

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.project_location import IProjectLocationRepository
from neurath.domain.aggregates.project import Project, ProjectLocation
from neurath.domain.observations import DirectoryObservation


class RegisterProjectUseCase:
    """Load candidate locations, apply domain associations, and persist new records."""

    def __init__(self, projects: IProjectRepository, locations: IProjectLocationRepository) -> None:
        """Bind primitive repositories belonging to one request.

        Args:
            projects: Project lookup and insertion port.
            locations: Location lookup, listing, and insertion port.
        """
        self.projects = projects
        self.locations = locations

    def execute(self, observation: DirectoryObservation) -> Project:
        """Register observed identities while retaining existing project references.

        Args:
            observation: Canonical external facts to interpret in the domain.

        Returns:
            Project: Existing or newly registered project entity.
        """
        observed = ProjectLocation.identify(observation)
        candidate_list: list[ProjectLocation] = []
        additions: list[ProjectLocation] = []
        for location in observed:
            found = self.locations.find(location.kind, location.path)
            if found is None:
                candidate_list.append(location)
                additions.append(location)
            else:
                candidate_list.append(found)
        candidates = tuple(candidate_list)
        project_id = ProjectLocation.owner_of(candidates)
        if project_id is None:
            project = Project.create(observation)
        else:
            project = self.projects.get(project_id)
        existing = self.locations.list(project.id)
        project.associate(candidates, existing)
        if project_id is None:
            self.projects.add(project)
        for location in additions:
            self.locations.add(location)
        return project
