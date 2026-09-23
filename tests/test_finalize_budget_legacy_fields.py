"""scripts/finalize_budget_legacy_fields.py の機械テスト。

手順11C: legacy互換のため保留していた予算提案の date / question_topic を
最終値へ更新するスクリプトのテスト。fixture / 一時ディレクトリのみを使い、
実データ（activity_archive.json）は書き換えない。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "finalize_budget_legacy_fields.py"


def budget_record(**overrides) -> dict:
    record = {
        "id": "mikami-000001",
        "date": "2023-01-01",
        "session_name": "2023年度予算提案",
        "meeting_type": "予算提案",
        "committee": "",
        "source_type": "予算提案",
        "source_status": "official",
        "question_topic": "旧question_topic",
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


def decision(**overrides) -> dict:
    d = {
        "source_locator": "2023-01-01",
        "review_status": "confirmed",
        "final_question_topic": "最終question_topic",
        "final_issue": "issue",
        "final_summary": "summary",
        "final_answer_summary": "answer",
        "final_result_level": "検討を引き出した",
        "final_tags": ["その他"],
        "legacy_inherit": True,
        "legacy_archive_index": 0,
        "decision_note": "",
    }
    d.update(overrides)
    return d


class FinalizeBudgetLegacyFieldsTest(unittest.TestCase):
    def _run(self, archive_records, decisions, tmp_path, extra_args=()):
        archive_path = tmp_path / "activity_archive.json"
        archive_path.write_text(json.dumps(archive_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        decisions_path = tmp_path / "budget_step10_decisions.json"
        decisions_path.write_text(
            json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        import importlib

        spec = importlib.util.spec_from_file_location("finalize_mod", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ARCHIVE_PATH = archive_path

        argv_backup = sys.argv
        try:
            sys.argv = ["finalize_budget_legacy_fields.py", "--decisions", str(decisions_path), *extra_args]
            rc = mod.main()
        finally:
            sys.argv = argv_backup
        return rc, archive_path

    def test_updates_only_differing_fields(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [
                budget_record(date="2023-01-01", question_topic="旧question_topic"),
                minutes_record(),
            ]
            decisions = [decision(final_question_topic="最終question_topic")]

            rc, archive_path = self._run(archive, decisions, tmp_path)
            self.assertEqual(rc, 0)

            updated = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual(updated[0]["date"], "2022-09-12")  # fiscal_year=2023の提出日
            self.assertEqual(updated[0]["question_topic"], "最終question_topic")
            self.assertEqual(updated[0]["id"], "mikami-000001")  # id不変
            self.assertEqual(updated[1], minutes_record())  # 議事録は完全不変

    def test_idempotent_second_run_changes_nothing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record()]
            decisions = [decision()]

            rc1, archive_path = self._run(archive, decisions, tmp_path)
            self.assertEqual(rc1, 0)
            after_first = archive_path.read_text(encoding="utf-8")

            rc2, _ = self._run(json.loads(after_first), decisions, tmp_path)
            self.assertEqual(rc2, 0)
            after_second = archive_path.read_text(encoding="utf-8")
            self.assertEqual(after_first, after_second)

    def test_check_mode_does_not_write(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(date="2023-01-01", question_topic="旧question_topic")]
            decisions = [decision()]

            rc, archive_path = self._run(archive, decisions, tmp_path, extra_args=["--check"])
            self.assertNotEqual(rc, 0)
            unchanged = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual(unchanged[0]["date"], "2023-01-01")
            self.assertEqual(unchanged[0]["question_topic"], "旧question_topic")

    def test_missing_decision_fails(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(source_locator="2023-99-99")]
            decisions = [decision(source_locator="2023-01-01")]

            rc, _ = self._run(archive, decisions, tmp_path)
            self.assertNotEqual(rc, 0)

    def test_unconfirmed_decision_fails(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record()]
            decisions = [decision(review_status="pending")]

            rc, _ = self._run(archive, decisions, tmp_path)
            self.assertNotEqual(rc, 0)

    def test_unknown_fiscal_year_fails(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [budget_record(fiscal_year=1999, source_locator="1999-01-01")]
            decisions = [decision(source_locator="1999-01-01")]

            rc, _ = self._run(archive, decisions, tmp_path)
            self.assertNotEqual(rc, 0)

    def test_record_order_preserved(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = pathlib.Path(td)
            archive = [
                minutes_record(),
                budget_record(source_locator="2023-01-01", question_topic="旧A"),
                minutes_record(question_topic="別の議事録"),
                budget_record(source_locator="2023-01-02", question_topic="旧B", id="mikami-000002"),
            ]
            decisions = [
                decision(source_locator="2023-01-01", final_question_topic="最終A"),
                decision(source_locator="2023-01-02", final_question_topic="最終B"),
            ]

            rc, archive_path = self._run(archive, decisions, tmp_path)
            self.assertEqual(rc, 0)
            updated = json.loads(archive_path.read_text(encoding="utf-8"))
            self.assertEqual([r.get("source_locator") for r in updated], ["", "2023-01-01", "", "2023-01-02"])
            self.assertEqual(updated[0]["source_type"], "議事録")
            self.assertEqual(updated[2]["source_type"], "議事録")


class RealDataFinalizeCheckTest(unittest.TestCase):
    """現在の実データ（activity_archive.json）に対する integration test。

    手順11C完了後、実データは finalize_budget_legacy_fields.py --check をPASSする
    のが正常な状態。
    """

    def test_current_main_passes_check(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_budget_question_topics_match_final_decisions(self) -> None:
        decisions_path = ROOT.parent / "council-activity-private" / "v1.2.0" / "step10" / "budget_step10_decisions.json"
        if not decisions_path.exists():
            self.skipTest("private repoのdecisionsファイルが見つからない")
        decisions = json.loads(decisions_path.read_text(encoding="utf-8"))["decisions"]
        dec_by_loc = {d["source_locator"]: d for d in decisions}

        archive = json.loads((ROOT / "activity_archive.json").read_text(encoding="utf-8"))
        budget = [r for r in archive if r.get("source_type") == "予算提案"]
        self.assertEqual(len(budget), len(dec_by_loc))
        for r in budget:
            dec = dec_by_loc[r["source_locator"]]
            self.assertEqual(r["question_topic"], dec["final_question_topic"])


if __name__ == "__main__":
    unittest.main()
