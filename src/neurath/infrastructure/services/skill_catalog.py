"""패키지에 포함된 스킬의 고정 절차를 읽어 현재 작업에 연결한다."""

import json
from pathlib import Path
from typing import cast, override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.skill_catalog import ISkillCatalogService
from neurath.domain.values.evaluation_target import EvaluationKind, EvaluationTarget
from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition


@Pod()
class PosixSkillCatalogService(ISkillCatalogService):
    """설치한 절차 정의를 읽으며 모델 호출이나 상태 변경을 만들지 않는다."""

    @override
    def load(self, skill: str, directory: str) -> WorkflowDefinition:
        """알려진 배포 스킬의 단계 목적과 결과 조건을 현재 폴더에 연결한다.

        Args:
            skill: 실제 패키지에 있는 스킬 이름.
            directory: 호스트의 실제 작업 폴더.

        Returns:
            WorkflowDefinition: 고정한 스킬 버전과 실제 절차.

        Raises:
            ValueError: 배포본에 없는 스킬을 선택한 경우.
        """
        catalog = cast(
            dict[str, list[str]],
            json.loads((Path(__file__).parents[2] / "resources" / "skills.json").read_text()),
        )
        if skill not in catalog:
            raise ValueError(f"Unknown skill {skill}; available: {', '.join(catalog)}")
        phases = [
            PhaseDefinition(
                key=f"step-{number}",
                purpose=purpose,
                arguments=(),
                directory=directory,
                target_revision="current",
                checks=("done",),
            )
            for number, purpose in enumerate(catalog[skill], 1)
        ]
        if skill in ("implement-spec", "autopilot", "debug", "finish-session"):
            phases.append(
                PhaseDefinition(
                    key="result-review",
                    purpose="원문·전체 TODO·실제 결과를 독립 평가하고 확인된 미달을 보완한다",
                    arguments=(),
                    directory=directory,
                    target_revision="current",
                    checks=("intent",),
                    evaluation=EvaluationTarget(
                        kind=EvaluationKind.RESULT, artifacts=(), verification=()
                    ),
                )
            )
        return WorkflowDefinition(skill=skill, version="1", phases=tuple(phases), inputs=())
