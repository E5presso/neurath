"""정확한 wheel 배포본의 조회·준비·계획·적용·복구를 제공한다."""

import hashlib
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.apply_distribution import (
    ApplyDistributionCommand,
    ApplyDistributionUseCase,
)
from neurath.application.usecases.check_distribution import (
    CheckDistributionQuery,
    CheckDistributionUseCase,
)
from neurath.application.usecases.plan_distribution import (
    PlanDistributionCommand,
    PlanDistributionUseCase,
)
from neurath.application.usecases.prepare_distribution import (
    PrepareDistributionCommand,
    PrepareDistributionUseCase,
)
from neurath.application.usecases.recover_distribution import (
    RecoverDistributionCommand,
    RecoverDistributionUseCase,
)
from neurath.cli_guide import render
from neurath.domain.enums.provider_kind import ProviderKind


@CliController("distribution")
class DistributionCliController:
    """사용자가 요청한 업데이트를 별도 승인 토큰 없이 정확한 후보에 연결한다."""

    def __init__(
        self,
        check: CheckDistributionUseCase,
        prepare: PrepareDistributionUseCase,
        plan: PlanDistributionUseCase,
        apply: ApplyDistributionUseCase,
        recover: RecoverDistributionUseCase,
    ) -> None:
        """배포 단계별 작업 단위를 받는다.

        Args:
            check: 공식 릴리스 관찰.
            prepare: wheel 실행 환경 준비.
            plan: 현재 파일과 후보의 변경 계획.
            apply: 명시한 후보 적용.
            recover: 해당 적용의 보존형 복구.
        """
        self.check = check
        self.prepare = prepare
        self.plan = plan
        self.apply = apply
        self.recover = recover

    @command("verify")
    async def verify_runtime(self) -> None:
        """현재 실행의 실제 명령과 패키지 가이드를 대조하고 내용 식별을 반환한다."""
        root = Path(__file__).parents[2]
        guide = (root / "resources/cli-guide.md").read_text()
        provenance = root / "resources/distribution.json"
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json", ".md"}:
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
        echo(
            json.dumps(
                {
                    "guide_matches": guide == render(),
                    "guide_sha256": hashlib.sha256(guide.encode()).hexdigest(),
                    "package_sha256": digest.hexdigest(),
                    "package": str(root),
                    "provenance": json.loads(provenance.read_text())
                    if provenance.exists()
                    else None,
                }
            )
        )

    @command("guide")
    async def read_guide(self) -> None:
        """진행 중 세션이 현재 호출 배포본의 실제 안내 본문을 다시 읽도록 반환한다."""
        root = Path(__file__).parents[2]
        guide = (root / "resources/cli-guide.md").read_text()
        installed_root = Path(os.environ.get("NEURATH_INSTALL_ROOT", os.getcwd()))
        skills = installed_root / (
            ".claude/skills" if os.environ.get("NEURATH_PROVIDER") == "claude" else ".agents/skills"
        )
        rendered = guide.replace(
            "@NEURATH_COMMAND@",
            os.environ.get("NEURATH_COMMAND", str(Path(sys.executable).with_name("neurath"))),
        ).replace("@NEURATH_SKILLS@", str(skills))
        echo(
            json.dumps(
                {
                    "version": version("neurath"),
                    "guide_sha256": hashlib.sha256(guide.encode()).hexdigest(),
                    "guide": rendered,
                    "delivery": "stdout; actual model uptake remains unverified",
                }
            )
        )

    @command("check")
    async def check_release(self, installed: str | None = None) -> None:
        """공식 릴리스 없음·조회 실패·관찰과 현재 artifact 일치를 구분한다.

        Args:
            installed: 현재 설치의 distribution.json 또는 None.
        """
        echo(json.dumps(await self.check.run(CheckDistributionQuery(installed=installed))))

    @command("prepare")
    async def prepare_candidate(
        self,
        wheel: Annotated[str, Option("--wheel")],
        store: Annotated[str, Option("--store")],
        source_commit: str | None = None,
    ) -> None:
        """정확한 wheel을 별도 환경에 준비하며 현재 호스트 설정은 바꾸지 않는다.

        Args:
            wheel: 명시한 실제 wheel 파일.
            store: 후보 환경 보관 폴더.
            source_commit: 요청한 정확한 소스 commit 또는 None.
        """
        echo(
            json.dumps(
                await self.prepare.run(
                    PrepareDistributionCommand(
                        wheel=wheel, store=store, source_commit=source_commit
                    )
                )
            )
        )

    @command("plan")
    async def plan_candidate(
        self,
        candidate: Annotated[str, Option("--candidate")],
        provider: Annotated[ProviderKind, Option("--provider")],
        directory: Annotated[str, Option("--directory")],
        data_home: Annotated[str, Option("--data-home")],
    ) -> None:
        """선택 후보와 파일 변경 전후를 개인 계획 파일에 연결한다.

        Args:
            candidate: 준비 결과의 후보 폴더.
            provider: 대상 호스트.
            directory: 설정 루트.
            data_home: 계속 유지할 사용자 자료 홈.
        """
        echo(
            json.dumps(
                await self.plan.run(
                    PlanDistributionCommand(
                        candidate=candidate,
                        provider=provider.value,
                        directory=directory,
                        data_home=data_home,
                    )
                )
            )
        )

    @command("apply")
    async def apply_candidate(
        self,
        candidate: Annotated[str, Option("--candidate")],
        provider: Annotated[ProviderKind, Option("--provider")],
        directory: Annotated[str, Option("--directory")],
        data_home: Annotated[str, Option("--data-home")],
    ) -> None:
        """명시적으로 선택한 후보를 적용하고 실제 새 CLI 호출을 검증한다.

        Args:
            candidate: 적용할 정확한 후보 폴더.
            provider: 대상 호스트.
            directory: 설정 루트.
            data_home: 원 작업이 있는 사용자 자료 홈.
        """
        echo(
            json.dumps(
                await self.apply.run(
                    ApplyDistributionCommand(
                        candidate=candidate,
                        provider=provider.value,
                        directory=directory,
                        data_home=data_home,
                    )
                )
            )
        )

    @command("recover")
    async def recover_installation(self, receipt: Annotated[str, Option("--receipt")]) -> None:
        """새 DB 기록·사건을 유지하고 해당 설치 전 실행·가이드만 복원한다.

        Args:
            receipt: 실제 적용에서 반환한 복구 기록.
        """
        echo(json.dumps(await self.recover.run(RecoverDistributionCommand(receipt=receipt))))
