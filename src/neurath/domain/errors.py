"""저장 구현의 세부 사항 없이 호출자가 처리할 수 있는 오류를 정의한다."""


class NeurathError(Exception):
    """프로젝트와 세션 요청의 기본 오류다."""


class ContextNotFound(NeurathError):
    """요청한 프로젝트 또는 해당 범위의 세션이 없는 경우다."""


class RevisionConflict(NeurathError):
    """호출자가 버전을 관찰한 뒤 세션이 변경된 경우다."""


class ProjectIdentityConflict(NeurathError):
    """저장된 폴더와 Git 별칭이 호환되지 않는 프로젝트를 가리키는 경우다."""


class StorageNotReady(NeurathError):
    """데이터베이스에 명시적인 초기화 또는 호환 마이그레이션이 필요한 경우다."""
