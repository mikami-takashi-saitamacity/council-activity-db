""".github/validate.py の機械テスト。fixture / 一時ディレクトリのみを使い、実データは書き換えない。"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATE_PY = ROOT / ".github" / "validate.py"
FIXTURE_SCHEMA = ROOT / "tests" / "fixtures" / "schema.json"


def make_record(**overrides) -> dict:
    record = {
        "date": "2026-01-01",
        "question_topic": "テストの質問",
        "result_level": "実施済",
        "source_type": "議事録",
        "source_status": "official",
        "tags": ["DX"],
    }
    record.update(overrides)
    return record


class ValidateHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_root = pathlib.Path(self.tmp.name)

    def _run(self, records: list[dict], retired: list[dict] | None = None, strict: bool = False) -> subprocess.CompletedProcess:
        data_path = self.tmp_root / "activity_archive.json"
        data_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        retired_path = self.tmp_root / "retired_ids.json"
        retired_path.write_text(json.dumps(retired or [], ensure_ascii=False), encoding="utf-8")

        args = [
            sys.executable, str(VALIDATE_PY),
            "--data", str(data_path),
            "--schema", str(FIXTURE_SCHEMA),
            "--retired-ids", str(retired_path),
        ]
        if strict:
            args.append("--require-budget-v12-fields")
        return subprocess.run(args, capture_output=True, text=True)


class NormalModeTest(ValidateHarness):
    def test_valid_records_pass(self) -> None:
        result = self._run([make_record(), make_record(date="2026-01-02")])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_duplicate_active_id_fails(self) -> None:
        result = self._run([
            make_record(id="mikami-000001"),
            make_record(date="2026-01-02", id="mikami-000001"),
        ])
        self.assertNotEqual(result.returncode, 0)

    def test_retired_id_duplicate_fails(self) -> None:
        retired = [
            {"id": "mikami-000002", "retired_at": "2026-01-01", "reason": "deleted"},
            {"id": "mikami-000002", "retired_at": "2026-01-02", "reason": "merged"},
        ]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)

    def test_active_retired_overlap_fails(self) -> None:
        retired = [{"id": "mikami-000003", "retired_at": "2026-01-01", "reason": "deleted"}]
        result = self._run([make_record(id="mikami-000003")], retired=retired)
        self.assertNotEqual(result.returncode, 0)

    def test_duplicate_existing_budget_source_locator_fails(self) -> None:
        result = self._run([
            make_record(source_type="予算提案", source_locator="2026-01-01"),
            make_record(date="2026-01-02", source_type="予算提案", source_locator="2026-01-01"),
        ])
        self.assertNotEqual(result.returncode, 0)

    def test_missing_source_locator_passes_in_normal_mode(self) -> None:
        # 通常モードでは「存在する分」だけを検査するので、無い分はエラーにしない
        result = self._run([make_record(source_type="予算提案")])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class StrictBudgetModeTest(ValidateHarness):
    def _budget_record(self, **overrides) -> dict:
        base = make_record(
            source_type="予算提案",
            id="mikami-000010",
            source_locator="2026-01-①",
            fiscal_year=2026,
        )
        base.update(overrides)
        return base

    def test_complete_budget_record_passes(self) -> None:
        result = self._run([self._budget_record()], strict=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_id_fails(self) -> None:
        record = self._budget_record()
        del record["id"]
        result = self._run([record], strict=True)
        self.assertNotEqual(result.returncode, 0)

    def test_missing_source_locator_fails(self) -> None:
        record = self._budget_record()
        del record["source_locator"]
        result = self._run([record], strict=True)
        self.assertNotEqual(result.returncode, 0)

    def test_empty_source_locator_fails(self) -> None:
        result = self._run([self._budget_record(source_locator="")], strict=True)
        self.assertNotEqual(result.returncode, 0)

    def test_missing_fiscal_year_fails(self) -> None:
        record = self._budget_record()
        del record["fiscal_year"]
        result = self._run([record], strict=True)
        self.assertNotEqual(result.returncode, 0)

    def test_duplicate_source_locator_fails(self) -> None:
        result = self._run(
            [
                self._budget_record(id="mikami-000010", source_locator="2026-01-①"),
                self._budget_record(id="mikami-000011", source_locator="2026-01-①"),
            ],
            strict=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_duplicate_id_fails(self) -> None:
        result = self._run(
            [
                self._budget_record(id="mikami-000010", source_locator="2026-01-①"),
                self._budget_record(id="mikami-000010", source_locator="2026-01-②"),
            ],
            strict=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_non_budget_records_are_not_required_to_have_budget_fields(self) -> None:
        # source_type == "予算提案" 以外は strict mode でも対象外（meeting_type等では判定しない）
        result = self._run([make_record(source_type="議事録", meeting_type="本会議")], strict=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RealDataStrictModeTest(unittest.TestCase):
    """現在の実データに strict mode をかけると FAIL するのが正常（手順7〜11未実施のため）。"""

    def test_current_main_fails_strict_mode(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_PY), "--require-budget-v12-fields"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_current_main_passes_normal_mode(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_PY)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
