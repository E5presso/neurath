"""프로젝트와 소유 위치의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.project import Project


class IProjectRepository(IAsyncGenericRepository[Project, str], ABC):
    """프로젝트의 위치 값들을 포함한 aggregate의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""
