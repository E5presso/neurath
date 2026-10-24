"""패키지 스킬 또는 선택한 전문 절차를 기존 runner 정의로 읽는다."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast, override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.skill_catalog import ISkillCatalogService, SkillDescription
from neurath.domain.values.evaluation_target import EvaluationKind, EvaluationTarget
from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition


@Pod()
class PosixSkillCatalogService(ISkillCatalogService):
    """설치 지침과 단계 정의를 같은 원천에서 읽으며 실행이나 저장을 하지 않는다."""

    @override
    def list(self, directory: str) -> Sequence[SkillDescription]:
        """배포 스킬의 적용·제외·입력·분기와 runner 정의를 함께 읽는다.

        Args:
            directory: 실제 호스트 작업 폴더.

        Returns:
            Sequence[SkillDescription]: 선택 지침과 고정된 단계 정의.
        """
        catalog = cast(
            dict[str, dict[str, Any]],
            json.loads((Path(__file__).parents[2] / "resources" / "skills.json").read_text()),
        )
        return tuple(
            SkillDescription(
                purpose=item["purpose"],
                use_when=item["use_when"],
                exclude=item["exclude"],
                required_inputs=item["required_inputs"],
                outcomes=item["outcomes"],
                branches=item["branches"],
                workflow=self._definition(name, directory, item),
            )
            for name, item in catalog.items()
        )

    @override
    def load(self, skill: str, directory: str, definition: str | None = None) -> WorkflowDefinition:
        """선택한 기본 또는 전문 스킬의 버전·원문·입력·단계를 고정한다.

        Args:
            skill: 실제로 선택한 스킬 이름.
            directory: 호스트의 실제 작업 폴더.
            definition: 호스트가 선택한 전문 절차 JSON 또는 None.

        Returns:
            WorkflowDefinition: 읽기만 한 단계 정의이며 아직 수행되지 않았다.

        Raises:
            ValueError: 없는 스킬 또는 형식이 잘못된 정의를 전달한 경우.
        """
        if definition is not None:
            raw = json.loads(definition)
            if not isinstance(raw, dict):
                raise ValueError("Skill definition must be a JSON object")
            return self._definition(skill, directory, raw)
        entries = self.list(directory)
        for entry in entries:
            if entry.workflow.skill == skill:
                return entry.workflow
        raise ValueError(
            f"Unknown skill {skill}; available: {', '.join(item.workflow.skill for item in entries)}. "
            "Use --definition for a selected project/user skill, workflow show for an existing run, "
            "or workflow revise to change its method. plan belongs in define-spec; implement-ui in implement-spec; "
            "dependency work uses specialist tools; recovery uses session resume."
        )

    @staticmethod
    def _definition(skill: str, directory: str, raw: dict[str, Any]) -> WorkflowDefinition:
        """JSON의 명시적 단계와 선택 원문을 실행 없이 기존 값 객체로 변환한다.

        Args:
            skill: 선택한 절차의 이름.
            directory: 실제 호스트 작업 폴더.
            raw: 버전·입력·단계와 선택적 원문 경로.

        Returns:
            WorkflowDefinition: 저장될 정의·입력·원문 스냅샷.

        Raises:
            ValueError: 단계 배열이나 문자열 입력 형식이 잘못된 경우.
        """
        if raw.get("skill", skill) != skill:
            raise ValueError("Definition must match the selected skill name")
        phases = raw.get("phases")
        inputs = raw.get("inputs", {})
        if not isinstance(phases, list) or any(not isinstance(item, dict) for item in phases):
            raise ValueError("Skill phases must be an array of phase objects")
        if not isinstance(inputs, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in inputs.items()
        ):
            raise ValueError("Skill inputs must map names to string values")
        inputs = dict(inputs)
        source = raw.get("source")
        if source is not None:
            path = (Path(directory) / Path(source).expanduser()).resolve()
            inputs["skill_source"] = str(path)
            inputs["skill_source_body"] = path.read_text()
        definitions = []
        for item in phases:
            for field in ("checks", "arguments"):
                values = item.get(field, [])
                if not isinstance(values, list) or any(
                    not isinstance(value, str) for value in values
                ):
                    raise ValueError(f"Phase {field} must be an array of strings")
            evaluation = item.get("evaluation")
            definitions.append(
                PhaseDefinition(
                    key=item["key"],
                    purpose=item["purpose"]
                    + (f"\n결과 조건: {item['result']}" if "result" in item else ""),
                    arguments=tuple(item.get("arguments", ())),
                    directory=directory,
                    target_revision=item.get("target_revision", "current"),
                    checks=tuple(item["checks"]),
                    skip_condition=item.get("skip_condition"),
                    evaluation=None
                    if evaluation is None
                    else EvaluationTarget(
                        kind=EvaluationKind(evaluation["kind"]),
                        artifacts=tuple(evaluation.get("artifacts", ())),
                        verification=tuple(evaluation.get("verification", ())),
                    ),
                )
            )
        return WorkflowDefinition(
            skill=skill,
            version=raw["version"],
            phases=tuple(definitions),
            inputs=tuple(inputs.items()),
        )
