"""wheel 내용별 별도 실행 환경과 보존형 설치·공식 릴리스 관찰을 제공한다."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, override
from urllib.parse import quote, urlsplit
from uuid import uuid7

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.distribution import IDistributionService


@Pod()
class PosixDistributionService(IDistributionService):
    """버전 문자열만으로 서로 다른 배포본을 같은 설치로 취급하지 않는다."""

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        """실제 보존 기록을 읽는다.

        Args:
            path: JSON 객체 파일.

        Returns:
            dict[str, Any]: 저장된 객체.
        """
        return json.loads(path.read_text())

    @staticmethod
    def _save(path: Path, value: dict[str, Any]) -> None:
        """개인 파일 기록을 원자 교체한다.

        Args:
            path: 기록 경로.
            value: 보존할 자료.
        """
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(path.name + ".tmp-" + str(uuid7()))
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temporary.chmod(0o600)
        os.replace(temporary, path)

    @staticmethod
    def _run(python: Path, arguments: list[str]) -> dict[str, Any]:
        """원래 cwd·호스트 주소를 유지하면서 정확한 환경의 CLI를 호출한다.

        Args:
            python: 고정 후보의 실제 Python.
            arguments: 셸 해석 없이 전달할 CLI 인자.

        Returns:
            dict[str, Any]: 후보가 반환한 구조화된 결과.

        Raises:
            RuntimeError: 후보 명령이 실패한 경우.
        """
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        result = subprocess.run(
            [str(python), "-I", "-m", "neurath.entrypoint", *arguments],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            diagnostic = python.parent.parent.parent / "failures" / f"{uuid7()}.json"
            PosixDistributionService._save(
                diagnostic,
                {
                    "arguments": arguments,
                    "exit": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
            raise RuntimeError(
                f"Candidate CLI {arguments[:2]} failed with exit {result.returncode}; private diagnostics: {diagnostic}"
            )
        return json.loads(result.stdout)

    @override
    def check(self, installed: str | None) -> dict[str, Any]:
        """공식 릴리스가 없을 때 최신이라고 표시하지 않는다.

        Args:
            installed: 현재 설치의 배포 기록 또는 None.

        Returns:
            dict[str, Any]: 조회 상태와 실제 설치 식별.
        """
        current = None if installed is None else self._json(Path(installed))
        request = urllib.request.Request(
            "https://api.github.com/repos/E5presso/neurath/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "neurath"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                release = json.load(response)
        except urllib.error.HTTPError as error:
            return {
                "status": "no-release" if error.code == 404 else "lookup-failed",
                "installed": current,
                "http_status": error.code,
            }
        except OSError as error:
            return {"status": "lookup-failed", "installed": current, "error": type(error).__name__}
        assets = [
            {
                "name": item["name"],
                "url": item["browser_download_url"],
                "digest": item.get("digest"),
            }
            for item in release.get("assets", [])
            if item["name"].endswith(".whl")
        ]
        current_digest = None if current is None else current.get("wheel_sha256")
        matched = (
            any(item["digest"] == f"sha256:{current_digest}" for item in assets)
            if current_digest
            else False
        )
        return {
            "status": "current-artifact" if matched else "release-observed",
            "installed": current,
            "tag": release["tag_name"],
            "assets": assets,
            "source_current": "unverified",
        }

    @override
    def prepare(self, wheel: str, store: str, source_commit: str | None) -> dict[str, Any]:
        """정확한 wheel을 내용 주소의 별도 환경에 설치하고 가이드 일치를 검사한다.

        Args:
            wheel: 선택한 wheel 파일.
            store: 배포 환경 보관 폴더.
            source_commit: 요청한 정확한 소스 개정 또는 None.

        Returns:
            dict[str, Any]: 준비 완료한 배포 식별과 실제 경로.

        Raises:
            ValueError: 원 소스 개정이 일치하지 않거나 wheel 안내가 오래된 경우.
        """
        source = (
            self._download(wheel, Path(store))
            if wheel.startswith("https://")
            else Path(wheel).expanduser().resolve(strict=True)
        )
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        with zipfile.ZipFile(source) as package:
            provenance = json.loads(package.read("neurath/resources/distribution.json"))
        if source_commit is not None and provenance.get("source_commit") != source_commit:
            raise ValueError("Wheel source commit differs from the requested exact source")
        root = Path(store).expanduser().resolve() / digest
        marker = root / "candidate.json"
        if marker.exists():
            return self._candidate(str(root))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        retained = root / source.name
        shutil.copyfile(source, retained)
        python = root / ("environment-" + str(uuid7())) / "bin/python"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(python.parent.parent)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), str(retained)],
            check=True,
            capture_output=True,
        )
        version = self._run(python, ["maintenance", "version"])
        inspection = self._run(python, ["distribution", "verify"])
        if not inspection["guide_matches"]:
            raise ValueError("Candidate CLI guide is stale; host installation was not changed")
        candidate = {
            "candidate": str(root),
            "python": str(python),
            "wheel": str(retained),
            "wheel_sha256": digest,
            "version": version["version"],
            "provenance": provenance,
            "guide_sha256": inspection["guide_sha256"],
            "package_sha256": inspection["package_sha256"],
        }
        self._save(marker, candidate)
        return candidate

    def _download(self, url: str, store: Path) -> Path:
        """공식 release asset의 관찰된 digest와 다운로드 바이트를 대조한다.

        Args:
            url: 공식 릴리스에서 선택한 wheel URL.
            store: 후보 파일 보관 폴더.

        Returns:
            Path: digest가 일치한 보관 wheel.

        Raises:
            ValueError: 공식 asset이 아니거나 digest가 없고 일치하지 않는 경우.
        """
        address = urlsplit(url)
        parts = address.path.split("/")
        if (
            address.hostname != "github.com"
            or len(parts) != 7
            or parts[1:5] != ["E5presso", "neurath", "releases", "download"]
            or not parts[6].endswith(".whl")
        ):
            raise ValueError("Select an exact official Neurath wheel release asset")
        request = urllib.request.Request(
            f"https://api.github.com/repos/E5presso/neurath/releases/tags/{quote(parts[5], safe='')}",
            headers={"User-Agent": "neurath"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            release = json.load(response)
        asset = next(
            (item for item in release.get("assets", []) if item["browser_download_url"] == url),
            None,
        )
        if asset is None or not str(asset.get("digest", "")).startswith("sha256:"):
            raise ValueError("Official asset digest is unavailable; release was not prepared")
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read()
        digest = hashlib.sha256(content).hexdigest()
        if asset["digest"] != f"sha256:{digest}":
            raise ValueError("Downloaded release asset digest differs; host files were not changed")
        destination = store.expanduser().resolve() / "downloads" / digest / parts[6]
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.write_bytes(content)
        return destination

    def _candidate(self, path: str) -> dict[str, Any]:
        """준비된 wheel과 실제 실행의 안내 식별을 다시 확인한다.

        Args:
            path: 준비 폴더.

        Returns:
            dict[str, Any]: 검증된 후보.

        Raises:
            ValueError: 보관 wheel이나 실행 안내가 변경된 경우.
        """
        candidate = self._json(Path(path) / "candidate.json")
        actual = hashlib.sha256(Path(candidate["wheel"]).read_bytes()).hexdigest()
        check = self._run(Path(candidate["python"]), ["distribution", "verify"])
        if (
            actual != candidate["wheel_sha256"]
            or not check["guide_matches"]
            or check["guide_sha256"] != candidate["guide_sha256"]
            or check["package_sha256"] != candidate["package_sha256"]
        ):
            raise ValueError("Prepared distribution changed; prepare the requested artifact again")
        return candidate

    @staticmethod
    def _arguments(provider: str, directory: str, data_home: str) -> list[str]:
        """원래 범위를 유지하는 기존 설치 명령을 만든다.

        Args:
            provider: 실제 호스트.
            directory: 설정 루트.
            data_home: 유지할 자료 홈.

        Returns:
            list[str]: 기존 설치기 인자.
        """
        return [
            "maintenance",
            "install",
            "--provider",
            provider,
            "--directory",
            directory,
            "--data-home",
            data_home,
        ]

    def _preview(
        self, candidate: dict[str, Any], provider: str, directory: str, data_home: str
    ) -> dict[str, Any]:
        """현재 파일과 같은 후보의 계획을 연결한다.

        Args:
            candidate: 검증한 후보.
            provider: 호스트.
            directory: 설정 루트.
            data_home: 자료 홈.

        Returns:
            dict[str, Any]: 변경 전후 내용을 가진 내부 계획.
        """
        preview = self._run(
            Path(candidate["python"]),
            [*self._arguments(provider, directory, data_home), "--preview"],
        )
        database = Path(preview["database"])
        transition = {"required": False, "status": "new-store"}
        if database.exists():
            observed = subprocess.run(
                [
                    candidate["python"],
                    "-I",
                    "-m",
                    "neurath.entrypoint",
                    "maintenance",
                    "diagnose",
                    "--database",
                    str(database),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            findings = json.loads(observed.stdout)
            compatible = all(
                any(item["area"] == area and item["status"] == "ok" for item in findings)
                for area in ("schema", "integrity")
            )
            transition = {
                "required": not compatible,
                "status": "compatible" if compatible else "preserving-transition-required",
            }
        preview["database_transition"] = transition
        return preview

    @override
    def plan(self, candidate: str, provider: str, directory: str, data_home: str) -> dict[str, Any]:
        """대상 파일 내용은 개인 계획 파일에 두고 경로·해시를 반환한다.

        Args:
            candidate: 준비 폴더.
            provider: 실제 호스트.
            directory: 설정 루트.
            data_home: 유지할 자료 홈.

        Returns:
            dict[str, Any]: 실제 후보와 변경 파일들의 전후 식별.
        """
        selected = self._candidate(candidate)
        preview = self._preview(selected, provider, directory, data_home)
        files = {
            path: {"before": Path(path).read_text() if Path(path).exists() else None, "after": body}
            for path, body in preview["planned_files"].items()
            if path in preview["changed_files"]
        }
        record = Path(candidate) / "plans" / f"{uuid7()}.json"
        self._save(record, {"candidate": selected, "files": files})
        return {
            "candidate": selected,
            "preview": str(record),
            "changed_files": preview["changed_files"],
            "applied": False,
            "skill_overrides": preview.get("skill_overrides", {}),
            "database_transition": preview["database_transition"],
            "continuation": [
                "Identify every managed CLI sharing this database; retain their current immutable runtimes.",
                "Use the current compatible CLI migration fence to preserve and retire the original SQLite path; do not claim host schedules were stopped.",
                "Use that same compatible CLI migration recover from its snapshot to a new data-home core.sqlite3; never overwrite a destination.",
                "Use the selected candidate maintenance initialize on the recovery copy, then verify its diagnostics and preserved work.",
                "Apply the same candidate to the selected host roots using the recovered data home, and migration replay the original transition directory.",
                "If any step fails, keep original/new stores and pending queues; resume using a matching compatible runtime. Do not reset an older DB over new records.",
            ]
            if preview["database_transition"]["required"]
            else [],
        }

    @override
    def apply(
        self, candidate: str, provider: str, directory: str, data_home: str
    ) -> dict[str, Any]:
        """선택 후보를 적용하고 실제 새 CLI를 실행하며 실패 시 해당 파일만 복원한다.

        Args:
            candidate: 선택한 준비 폴더.
            provider: 실제 호스트.
            directory: 설정 루트.
            data_home: 계속 유지할 자료 홈.

        Returns:
            dict[str, Any]: 실제 적용·검증·복구 위치.

        Raises:
            Exception: 실패 후 원래 실행·안내 조합을 복원하고 원 오류를 전파한다.
            ValueError: 실제 실행 배포본이 선택한 후보와 다른 경우.
        """
        selected = self._candidate(candidate)
        preview = self._preview(selected, provider, directory, data_home)
        if preview["database_transition"]["required"]:
            raise ValueError(
                "Shared database requires preserving transition before applying files; distribution plan provides the existing migration fence/recover/initialize/replay continuation"
            )
        marker = Path(preview["command"]).parent / "distribution.json"
        files = {
            path: {
                "before": base64.b64encode(Path(path).read_bytes()).decode()
                if Path(path).exists()
                else None,
                "after": base64.b64encode(body.encode()).decode(),
                "mode": Path(path).stat().st_mode & 0o777 if Path(path).exists() else 0o600,
            }
            for path, body in preview["planned_files"].items()
            if path in preview["changed_files"]
        }
        files[str(marker)] = {
            "before": base64.b64encode(marker.read_bytes()).decode() if marker.exists() else None,
            "after": base64.b64encode(
                json.dumps(selected, ensure_ascii=False, indent=2).encode()
            ).decode(),
            "mode": 0o600,
        }
        receipt = Path(candidate) / "applications" / f"{uuid7()}.json"
        record = {
            "files": files,
            "candidate": selected,
            "database": preview["database"],
            "command": preview["command"],
            "status": "prepared",
            "provider": provider,
            "directory": directory,
            "data_home": data_home,
        }
        self._save(receipt, record)
        try:
            result = self._run(
                Path(selected["python"]), self._arguments(provider, directory, data_home)
            )
            self._save(marker, selected)
            files[str(marker)]["after"] = base64.b64encode(marker.read_bytes()).decode()
            observed = subprocess.run(
                [preview["command"], "maintenance", "version"],
                capture_output=True,
                text=True,
                check=True,
            )
            if json.loads(observed.stdout)["version"] != selected["version"]:
                raise ValueError("Installed CLI did not execute the selected distribution")
            identity = subprocess.run(
                [preview["command"], "distribution", "verify"],
                capture_output=True,
                text=True,
                check=True,
            )
            if json.loads(identity.stdout)["package_sha256"] != selected["package_sha256"]:
                raise ValueError("Installed CLI artifact differs from the selected candidate")
            record["status"] = "applied"
            self._save(receipt, record)
        except Exception:
            self._restore(files)
            record["status"] = "failed-restored"
            self._save(receipt, record)
            raise
        return {
            **result,
            "candidate": selected,
            "receipt": str(receipt),
            "cli_invoked": True,
            "model_context": "unverified; read installed rules in the current session",
            "native_activation": "unverified",
        }

    @staticmethod
    def _restore(files: dict[str, Any]) -> None:
        """복구 대상 설정만 돌려놓고 DB·전환 사건은 건드리지 않는다.

        Args:
            files: 해당 적용의 변경 전 파일 바이트와 모드.
        """
        for name, item in files.items():
            path = Path(name)
            if item["before"] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(base64.b64decode(item["before"]))
                path.chmod(item["mode"])

    @override
    def recover(self, receipt: str) -> dict[str, Any]:
        """해당 변경 이후 사용자 수정이 없는 실행·안내만 복원한다.

        Args:
            receipt: 실제 적용 기록.

        Returns:
            dict[str, Any]: 새 자료를 유지한 설정 복구 결과.

        Raises:
            ValueError: 적용 이후 별도 파일 수정이 있어 자동 복원이 손실을 만드는 경우.
        """
        record = self._json(Path(receipt))
        if record["status"] == "recovered":
            return {"status": "recovered", "database_preserved": record["database"]}
        if record["status"] not in {"applied", "prepared", "restoring"}:
            raise ValueError("Only an applied or interrupted distribution can be recovered")
        for name, item in record["files"].items():
            current = (
                base64.b64encode(Path(name).read_bytes()).decode() if Path(name).exists() else None
            )
            acceptable = (
                {item["after"], item["before"]}
                if record["status"] in {"prepared", "restoring"}
                else {item["after"]}
            )
            if current not in acceptable:
                raise ValueError(
                    "Installation files changed after apply; preserve those changes before recovery"
                )
        previous_marker = record["files"][
            str(Path(record["command"]).parent / "distribution.json")
        ]["before"]
        if previous_marker is not None:
            previous = json.loads(base64.b64decode(previous_marker))
            compatible = self._preview(
                self._candidate(previous["candidate"]),
                record["provider"],
                record["directory"],
                record["data_home"],
            )
            if compatible["database_transition"]["required"]:
                raise ValueError(
                    "Previous runtime cannot read current records; keep the current installation and use compatible migration recovery"
                )
        record["status"] = "restoring"
        self._save(Path(receipt), record)
        self._restore(record["files"])
        if Path(record["command"]).exists():
            subprocess.run(
                [record["command"], "maintenance", "version"],
                capture_output=True,
                text=True,
                check=True,
            )
        record["status"] = "recovered"
        self._save(Path(receipt), record)
        return {
            "status": "recovered",
            "database_preserved": record["database"],
            "events_preserved": True,
            "native_activation": "unverified",
        }
