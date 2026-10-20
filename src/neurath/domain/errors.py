"""저장 구현의 세부 사항 없이 호출자가 처리할 수 있는 오류를 정의한다."""


class NeurathError(Exception):
    """프로젝트·세션·원문·태스크 요청에서 호출자가 처리할 오류의 공통 기반이다."""


class ContextNotFound(NeurathError):
    """요청한 기록·시도가 없거나 지정한 프로젝트·소유 세션 범위와 다른 경우다."""


class RevisionConflict(NeurathError):
    """읽은 revision 또는 도메인 version이 현재 저장 상태와 달라 수정을 거부한 경우다."""


class ProjectIdentityConflict(NeurathError):
    """저장된 폴더와 Git 별칭이 호환되지 않는 프로젝트를 가리키는 경우다."""


class StorageNotReady(NeurathError):
    """일반 요청에 필요한 DB가 없거나 스키마를 현재 패키지로 해석할 수 없는 경우다."""


class InvalidTaskState(NeurathError):
    """원문·현재 개정·시도 또는 상태 전이의 조건이 맞지 않는 경우다."""
