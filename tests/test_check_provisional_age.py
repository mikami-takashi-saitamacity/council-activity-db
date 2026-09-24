"""scripts/check_provisional_age.py の機械テスト。

手順13E-1: source_status=provisional の5か月滞留警告のテスト。fixture /
一時ディレクトリのみを使い、実データ（activity_archive.json）は書き換えない。
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_provisional_age.py"

spec = importlib.util.spec_from_file_location("check_provisional_age_mod", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def record(**overrides) -> dict:
    r = {
        "date": "2026-01-01",
        "meeting_type": "委員会",
        "committee": "保健福祉委員会",
        "session_name": "2026年1月保健福祉委員会",
        "question_topic": "question_topic",
        "issue": "issue",
        "proposal": "",
        "summary": "summary",
        "tags": ["その他"],
        "answer_summary": "answer",
        "result_level": "検討を引き出した",
        "source_type": "議事録",
        "source_status": "official",
        "source_url": "",
        "follow_up": "",
    }
    r.update(overrides)
    return r


class AddMonthsTest(unittest.TestCase):
    def test_2026_01_31_plus_5_months_is_2026_06_30(self):
        self.assertEqual(
            mod.add_months(datetime.date(2026, 1, 31), 5),
            datetime.date(2026, 6, 30),
        )

    def test_2026_09_24_plus_5_months_is_2027_02_24(self):
        self.assertEqual(
            mod.add_months(datetime.date(2026, 9, 24), 5),
            datetime.date(2027, 2, 24),
        )

    def test_year_rollover(self):
        self.assertEqual(
            mod.add_months(datetime.date(2025, 10, 15), 5),
            datetime.date(2026, 3, 15),
        )


class FindOverdueTest(unittest.TestCase):
    def test_official_is_excluded(self):
        records = [record(source_status="official", date="2020-01-01")]
        overdue = mod.find_overdue(records, datetime.date(2026, 9, 24))
        self.assertEqual(overdue, [])

    def test_provisional_under_5_months_is_excluded(self):
        # 2026-09-24付近開催、基準日2026-09-24（開催直後）は対象外
        records = [record(source_status="provisional", date="2026-09-01")]
        overdue = mod.find_overdue(records, datetime.date(2026, 9, 24))
        self.assertEqual(overdue, [])

    def test_deadline_day_itself_is_excluded(self):
        # date=2026-01-24 の期限は 2026-06-24。基準日がちょうど期限当日は対象外
        records = [record(source_status="provisional", date="2026-01-24")]
        overdue = mod.find_overdue(records, datetime.date(2026, 6, 24))
        self.assertEqual(overdue, [])

    def test_day_after_deadline_is_overdue(self):
        # 期限翌日は対象
        records = [record(source_status="provisional", date="2026-01-24")]
        overdue = mod.find_overdue(records, datetime.date(2026, 6, 25))
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["index"], 0)
        self.assertEqual(overdue[0]["deadline"], "2026-06-24")

    def test_record_with_id_is_reported(self):
        records = [record(source_status="provisional", date="2025-01-01", id="mikami-000123")]
        overdue = mod.find_overdue(records, datetime.date(2026, 9, 24))
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["id"], "mikami-000123")

    def test_record_without_id_is_identified_by_index(self):
        # 議事録は現時点でid未付与。idが無くてもindexで特定できる
        records = [record(source_status="provisional", date="2025-01-01")]
        self.assertNotIn("id", records[0])
        overdue = mod.find_overdue(records, datetime.date(2026, 9, 24))
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["index"], 0)
        self.assertIsNone(overdue[0]["id"])

    def test_invalid_date_on_provisional_raises(self):
        records = [record(source_status="provisional", date="not-a-date")]
        with self.assertRaises(mod.CheckProvisionalAgeError):
            mod.find_overdue(records, datetime.date(2026, 9, 24))

    def test_invalid_date_on_official_does_not_raise(self):
        # officialはdate形式を問わず対象外（このスクリプトの責務外）
        records = [record(source_status="official", date="not-a-date")]
        overdue = mod.find_overdue(records, datetime.date(2026, 9, 24))
        self.assertEqual(overdue, [])


class CliTest(unittest.TestCase):
    def _run(self, records, as_of="2026-09-24", extra_args=()):
        with tempfile.TemporaryDirectory() as td:
            data_path = pathlib.Path(td) / "activity_archive.json"
            data_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            args = [sys.executable, str(SCRIPT), "--data", str(data_path)]
            if as_of is not None:
                args += ["--as-of", as_of]
            args += list(extra_args)
            return subprocess.run(args, capture_output=True, text=True)

    def test_overdue_warning_still_exits_zero(self):
        records = [record(source_status="provisional", date="2025-01-01")]
        result = self._run(records)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARNING provisional overdue", result.stdout)
        self.assertIn("index=0", result.stdout)

    def test_no_overdue_exits_zero_with_zero_count(self):
        records = [record(source_status="official", date="2020-01-01")]
        result = self._run(records)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("WARNING", result.stdout)
        self.assertIn("5か月滞留: 0件", result.stdout)

    def test_invalid_provisional_date_exits_nonzero(self):
        records = [record(source_status="provisional", date="2025-13-99")]
        result = self._run(records)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NG", result.stdout)

    def test_malformed_json_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            data_path = pathlib.Path(td) / "activity_archive.json"
            data_path.write_text("{not valid json", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data", str(data_path), "--as-of", "2026-09-24"],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_top_level_not_list_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            data_path = pathlib.Path(td) / "activity_archive.json"
            data_path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data", str(data_path), "--as-of", "2026-09-24"],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_bad_as_of_format_exits_nonzero(self):
        records = [record()]
        result = self._run(records, as_of="not-a-date")
        self.assertNotEqual(result.returncode, 0)


class RealDataProvisionalAgeTest(unittest.TestCase):
    """現在の実データ（activity_archive.json）に対する回帰テスト。"""

    def test_current_production_data_has_zero_overdue(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--as-of", "2026-09-24"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("WARNING", result.stdout)
        self.assertIn("5か月滞留: 0件", result.stdout)


if __name__ == "__main__":
    unittest.main()
