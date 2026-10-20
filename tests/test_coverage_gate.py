"""실제 계측 보고서로 라인·분기 게이트의 통과와 거부를 검증한다."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[1] / "tools" / "check_coverage.py"


@pytest.mark.parametrize("mode", ["missing-line", "missing-branch", "excluded-source", "complete"])
def test_gate_rejects_real_line_or_branch_gaps_and_accepts_full_execution(tmp_path, mode):
    source = tmp_path / "package"
    source.mkdir()
    if mode in ("missing-line", "excluded-source"):
        (source / "pricing.py").write_text(
            "def express_fee():\n    return 10\n\ndef standard_fee():\n    return 0\n"
        )
        if mode == "excluded-source":
            (source / "pricing.py").write_text(
                "def express_fee():\n    return 10\n\ndef standard_fee():  # pragma: no cover\n    return 0\n"
            )
        driver = "from pricing import express_fee\nassert express_fee() == 10\n"
    else:
        (source / "pricing.py").write_text(
            "def delivery_fee(express):\n    fee = 0\n    if express:\n        fee = 10\n    return fee\n"
        )
        driver = "from pricing import delivery_fee\nassert delivery_fee(True) == 10\n"
        if mode == "complete":
            driver += "assert delivery_fee(False) == 0\n"
    runner = source / "run.py"
    runner.write_text(driver)
    data = tmp_path / "measurement"
    report = tmp_path / "coverage.json"
    config = tmp_path / ".coveragerc"
    config.write_text("")
    environment = dict(os.environ)
    environment.pop("COV_CORE_SOURCE", None)
    environment.pop("COVERAGE_PROCESS_START", None)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--rcfile={config}",
            "--branch",
            f"--source={source}",
            f"--data-file={data}",
            str(runner),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "json",
            f"--rcfile={config}",
            f"--data-file={data}",
            "-o",
            str(report),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    totals = json.loads(report.read_text())["totals"]
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(report)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    if mode == "complete":
        assert totals["missing_lines"] == totals["missing_branches"] == 0
        assert result.returncode == 0
        assert "COVERAGE_CHECK_OK" in result.stdout
    elif mode == "excluded-source":
        assert totals["missing_lines"] == totals["missing_branches"] == 0
        assert totals["excluded_lines"] > 0
        assert result.returncode != 0
        assert "Coverage exclusions not allowed" in result.stderr
    else:
        assert result.returncode != 0
        assert "Coverage incomplete" in result.stderr
        if mode == "missing-branch":
            assert totals["missing_lines"] == 0
            assert totals["missing_branches"] > 0
        else:
            assert totals["missing_lines"] > 0


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        "{}",
        '{"totals": {}}',
        '{"totals": {"missing_lines": -1, "missing_branches": 0, "excluded_lines": 0}}',
    ],
)
def test_gate_rejects_missing_or_invalid_coverage_totals(tmp_path, content):
    report = tmp_path / "invalid.json"
    report.write_text(content)
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(report)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "COVERAGE_CHECK_OK" not in result.stdout


def test_production_coverage_configuration_cannot_omit_files_or_exclude_paths():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["coverage"]
    assert config["run"]["source"] == ["src/neurath"]
    assert config["run"]["branch"] is True
    assert config["report"]["fail_under"] == 100
    assert not {"omit", "include"}.intersection(config["run"])
    assert not {
        "omit",
        "include",
        "exclude_lines",
        "exclude_also",
        "partial_branches",
        "partial_always",
    }.intersection(config["report"])
