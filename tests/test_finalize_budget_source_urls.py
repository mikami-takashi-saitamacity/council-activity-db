"""scripts/finalize_budget_source_urls.py の機械テスト。

手順13(13A): 予算提案の source_url を年度別定数表（budget_step10_spec.md §4・§5）
から機械設定するスクリプトのテスト。fixture / 一時ディレクトリのみを使い、
実データ（activity_archive.json）は書き換えない。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "finalize_budget_source_urls.py"

spec = importlib.util.spec_from_file_location("finalize_source_urls_mod", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SOURCE_URL = mod.SOURCE_URL


def budget_record(**overrides) -> dict:
    record = {
        "id": "mikami-000001",
        "date": "2022-09-12",
        "session_name": "2023年度予算提案",
        "meeting_type": "予算提案",
        "committee": "",
        "source_type": "予算提案",
        "source_status": "official",
        "question_topic": "question_topic",
        "issue": "issue",
        "proposal": "proposal",
        "summary": "summary",
        "tags": ["その他"],
        "answer_summary": "answer",
        "result_level": "検討を引き出した",
        "follow_up": "",
        "source_url": "",
        "source_locator": "2023-01-01",
        "fiscal_year": 2023,
    }
    record.update(overrides)
    return record


def minutes_record(**overrides) -> dict:
    record = {
        "date": "2023-05-01",
        "session_name": "2023年5月定例会",
        "meeting_type": "本会議",
        "committee": "",
        "source_type": "議事録",
        "source_status": "official",
        "question_topic": "議事録の論点",
        "issue": "issue",
        "proposal": "",
        "summary": "summary",
        "tags": ["その他"],
        "answer_summary": "answer",
        "result_level": "検討を引き出した",
        "follow_up": "",
        "source_url": "https://example.test/minutes",
        "source_locator": "",
        "fiscal_year": None,
    }
    record.update(overrides)
    return record


class FinalizeBudgetSourceUrlsTest(unittest.TestCase):
    def _run(self, archive_records, tmp_path, extra_args=()):
        archive_path = tmp_path / "activity_archive.json"
        archive_path.write_text(json.dumps(archive_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        argv_backup = sys.argv
        try:
            sys.argv = ["finalize_budget_source_urls.py", "--data", str(archive_path), *extra_args]
            rc = mod.main()
        finally:
            sys.argv = argv_backup
        return rc, archive_path

    def test_sets_source_url_from_fiscal_year(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(fiscal_year=2023, source_url="")]

            rc, archive_path = self._run(archive, tmp_path)
            self.assertEqual(rc, 0)

            updated = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual(updated[0]["source_url"], SOURCE_URL[2023])

    def test_non_budget_records_are_completely_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(fiscal_year=2023, source_url=""), minutes_record()]

            rc, archive_path = self._run(archive, tmp_path)
            self.assertEqual(rc, 0)

            updated = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual(updated[1], minutes_record())

    def test_other_budget_fields_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            record = budget_record(fiscal_year=2023, source_url="")
            archive = [record]

            rc, archive_path = self._run(archive, tmp_path)
            self.assertEqual(rc, 0)

            updated = json.loads(archive_path.read_text(encoding="utf-8"))[0]
            for key, value in record.items():
                if key == "source_url":
                    continue
                self.assertEqual(updated[key], value, f"{key} が変化した")

    def test_record_order_and_count_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [
                minutes_record(question_topic="A"),
                budget_record(fiscal_year=2021, source_locator="2021-01-01", source_url=""),
                minutes_record(question_topic="B"),
                budget_record(fiscal_year=2026, source_locator="2026-01-01", source_url="", id="mikami-000002"),
            ]

            rc, archive_path = self._run(archive, tmp_path)
            self.assertEqual(rc, 0)

            updated = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual(len(updated), 4)
            self.assertEqual(
                [r.get("source_type") for r in updated],
                ["議事録", "予算提案", "議事録", "予算提案"],
            )
            self.assertEqual(updated[1]["source_url"], SOURCE_URL[2021])
            self.assertEqual(updated[3]["source_url"], SOURCE_URL[2026])

    def test_idempotent_second_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(fiscal_year=2024, source_url="")]

            rc1, archive_path = self._run(archive, tmp_path)
            self.assertEqual(rc1, 0)
            after_first = archive_path.read_text(encoding="utf-8")

            rc2, _ = self._run(json.loads(after_first), tmp_path)
            self.assertEqual(rc2, 0)
            after_second = archive_path.read_text(encoding="utf-8")
            self.assertEqual(after_first, after_second)

    def test_already_correct_url_is_not_rewritten_and_check_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(fiscal_year=2026, source_url=SOURCE_URL[2026])]

            rc, archive_path = self._run(archive, tmp_path, extra_args=["--check"])
            self.assertEqual(rc, 0)

    def test_check_mode_fails_when_url_missing_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(fiscal_year=2023, source_url="")]

            rc, archive_path = self._run(archive, tmp_path, extra_args=["--check"])
            self.assertNotEqual(rc, 0)
            unchanged = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual(unchanged[0]["source_url"], "")

    def test_check_mode_fails_when_url_does_not_match_constant(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(fiscal_year=2023, source_url="https://wrong.example/foo.pdf")]

            rc, archive_path = self._run(archive, tmp_path, extra_args=["--check"])
            self.assertNotEqual(rc, 0)

    def test_unknown_fiscal_year_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(fiscal_year=1999, source_locator="1999-01-01")]

            rc, _ = self._run(archive, tmp_path)
            self.assertNotEqual(rc, 0)

    def test_all_six_fiscal_years_map_to_distinct_urls(self):
        self.assertEqual(set(SOURCE_URL.keys()), {2021, 2022, 2023, 2024, 2025, 2026})
        self.assertEqual(len(set(SOURCE_URL.values())), 6)


class RealDataFinalizeSourceUrlCheckTest(unittest.TestCase):
    """現在の実データ（activity_archive.json）に対する回帰テスト。

    13A完了後、実データは finalize_budget_source_urls.py --check をPASSする
    のが正常な状態。private repoには依存しない（定数はpublic repo内で完結）。
    """

    def test_current_main_passes_check(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_625_budget_records_have_matching_source_url(self) -> None:
        archive = json.loads((ROOT / "activity_archive.json").read_text(encoding="utf-8"))
        budget = [r for r in archive if r.get("source_type") == "予算提案"]
        self.assertEqual(len(budget), 625)
        for r in budget:
            self.assertEqual(r["source_url"], SOURCE_URL[r["fiscal_year"]], r.get("source_locator"))


if __name__ == "__main__":
    unittest.main()
