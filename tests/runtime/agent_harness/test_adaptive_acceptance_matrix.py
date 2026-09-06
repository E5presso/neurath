"""Frozen adaptive-control acceptance matrix와 public CLI를 검증합니다."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.acceptance_matrix import (
    CommandResult,
    SubprocessCommandRunner,
    canonical_matrix_digest,
)
from scripts.agent_harness.adaptive_acceptance_matrix import (
    ADAPTIVE_ACCEPTANCE_MATRIX,
    ADAPTIVE_ACCEPTANCE_MATRIX_DIGEST,
    AdaptiveAcceptanceId,
    EvidenceSurface,
    _selected_cases,
    main,
)

EXPECTED_ROWS = (
    "ADP-Q01",
    "ADP-Q02",
    "ADP-Q03",
    "ADP-Q04",
    "ADP-Q05",
    "ADP-Q06",
    "ADP-Q07",
    "ADP-Q08",
    "ADP-Q09",
    "ADP-R01",
    "ADP-R02",
    "ADP-R03",
    "ADP-R04",
    "ADP-E01",
    "ADP-E02",
    "ADP-E03",
    "ADP-E04",
    "ADP-E05",
    "ADP-E06",
    "ADP-E07",
    "ADP-E08",
    "ADP-P01",
    "ADP-P02",
    "ADP-P03",
    "ADP-P04",
    "ADP-P05",
    "ADP-P06",
    "ADP-P07",
    "ADP-P08",
    "ADP-P09",
    "ADP-P10",
    "ADP-P11",
    "ADP-P12",
    "ADP-P13",
    "ADP-P14",
    "ADP-S01",
    "ADP-S02",
    "ADP-S03",
    "ADP-S04",
    "ADP-S05",
    "ADP-S06",
    "ADP-S07",
    "ADP-S08",
    "ADP-F01",
    "ADP-F02",
    "ADP-F03",
    "ADP-F04",
    "ADP-L01",
    "ADP-L02",
    "ADP-L03",
    "ADP-L04",
    "ADP-L05",
    "ADP-A01",
    "ADP-A02",
    "ADP-A03",
    "ADP-A04",
)

FROZEN_ADAPTIVE_ACCEPTANCE_MATRIX_DIGEST = (
    "df3dd5497fbf17cea0fbe9a77fc66b4c2365a6e7cecd2b7b79ef84ab668751af"
)


class AdaptiveAcceptanceMatrixTest(TestCase):
    """56-row adaptive contract의 identity, digest, 실행 receipt를 고정합니다."""

    def test_matrix_contains_exactly_the_frozen_rows_and_metadata(self) -> None:
        """행, surface, node는 빈 값이나 duplicate 없이 canonical order를 유지합니다."""
        rows = tuple(case.row.value for case in ADAPTIVE_ACCEPTANCE_MATRIX)
        surface_order = {surface.value: index for index, surface in enumerate(EvidenceSurface)}

        self.assertEqual(EXPECTED_ROWS, rows)
        self.assertEqual(EXPECTED_ROWS, tuple(row.value for row in AdaptiveAcceptanceId))
        self.assertEqual(56, len(rows))
        self.assertEqual(56, len(frozenset(rows)))
        self.assertTrue(all(case.scenario.strip() for case in ADAPTIVE_ACCEPTANCE_MATRIX))
        self.assertTrue(all(case.nodes for case in ADAPTIVE_ACCEPTANCE_MATRIX))
        self.assertTrue(all(case.evidence_surfaces for case in ADAPTIVE_ACCEPTANCE_MATRIX))
        self.assertTrue(
            all(
                node.startswith("scripts/") and "::test_" in node
                for case in ADAPTIVE_ACCEPTANCE_MATRIX
                for node in case.nodes
            )
        )
        self.assertTrue(
            all(
                tuple(
                    sorted(
                        case.evidence_surfaces,
                        key=lambda surface: surface_order[surface.value],
                    )
                )
                == case.evidence_surfaces
                for case in ADAPTIVE_ACCEPTANCE_MATRIX
            )
        )
        nodes = tuple(node for case in ADAPTIVE_ACCEPTANCE_MATRIX for node in case.nodes)
        self.assertEqual(189, len(nodes))
        self.assertEqual(len(nodes), len(frozenset(nodes)))

    def test_matrix_digest_is_literal_and_matches_canonical_payload(self) -> None:
        """Literal digest와 canonical row payload가 독립적으로 같은 contract를 가리킵니다."""
        self.assertEqual(
            FROZEN_ADAPTIVE_ACCEPTANCE_MATRIX_DIGEST,
            ADAPTIVE_ACCEPTANCE_MATRIX_DIGEST,
        )
        self.assertEqual(
            FROZEN_ADAPTIVE_ACCEPTANCE_MATRIX_DIGEST,
            canonical_matrix_digest(ADAPTIVE_ACCEPTANCE_MATRIX),
        )

    def test_workflow_policy_inventory_is_21_semantic_and_8_operational(self) -> None:
        """계약이 있는 skill은 21 semantic 또는 8 operational projection으로 분류됩니다."""
        repository = Path(__file__).resolve().parents[3]
        payload = json.loads(
            (repository / ".agents/skills/contracts.json").read_text(encoding="utf-8")
        )
        contracts = payload["skills"]
        semantic = {
            name
            for name, contract in contracts.items()
            if contract.get("workflow_semantics") == "semantic"
        }
        operational = {
            name
            for name, contract in contracts.items()
            if contract.get("workflow_semantics") == "operational-projection"
        }

        self.assertEqual(21, len(semantic))
        self.assertEqual(8, len(operational))
        self.assertTrue(
            {
                "explore-ui",
                "sync-design",
                "implement-ui",
                "review-ui",
            }.issubset(semantic)
        )
        self.assertEqual(set(contracts), semantic | operational)
        self.assertTrue(
            all(contracts[name].get("adaptive_control") == "required" for name in semantic)
        )
        self.assertTrue(
            all(contracts[name].get("adaptive_control") == "not-applicable" for name in operational)
        )

    def test_selection_deduplicates_in_frozen_matrix_order(self) -> None:
        """Repeated CLI row는 중복 실행하지 않고 matrix order로 정규화합니다."""
        selected = _selected_cases(("ADP-A03", "ADP-Q01", "ADP-Q01"))

        self.assertEqual(
            ("ADP-Q01", "ADP-A03"),
            tuple(case.row.value for case in selected),
        )

    def test_cli_receipt_exposes_full_matrix_digest_and_selected_surface_metadata(self) -> None:
        """CLI receipt는 선택 row의 실행과 full frozen matrix identity를 함께 증명합니다."""
        output = io.StringIO()
        with (
            patch.object(
                SubprocessCommandRunner,
                "run",
                return_value=CommandResult(0, "passed", ""),
            ),
            redirect_stdout(output),
        ):
            exit_code = main(("--row", "ADP-Q01", "--row", "ADP-A03"))

        receipt = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual("neurath.adaptive-control-acceptance-receipt.v1", receipt["schema"])
        self.assertEqual(ADAPTIVE_ACCEPTANCE_MATRIX_DIGEST, receipt["matrix_digest"])
        self.assertEqual(["ADP-Q01", "ADP-A03"], receipt["matrix_rows"])
        self.assertEqual(["ADP-Q01", "ADP-A03"], receipt["executed_rows"])
        self.assertEqual(
            [["AUTO"], ["AUTO", "COLD"]],
            [result["evidence_surfaces"] for result in receipt["results"]],
        )

    def test_every_matrix_node_is_collectable_from_the_repository(self) -> None:
        """Exact pytest node 목록은 repository에서 collect 가능한 spelling만 사용합니다."""
        repository = Path(__file__).resolve().parents[3]
        nodes = tuple(node for case in ADAPTIVE_ACCEPTANCE_MATRIX for node in case.nodes)
        for case in ADAPTIVE_ACCEPTANCE_MATRIX:
            for node in case.nodes:
                test_path = repository / node.split("::", maxsplit=1)[0]
                self.assertTrue(
                    test_path.is_file(), msg=f"missing test module for {case.row.value}: {node}"
                )
        completed = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-o",
                "addopts=",
                *nodes,
            ),
            cwd=repository,
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(0, completed.returncode, f"{completed.stdout}\n{completed.stderr}")
