from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "prepare_budget_step9", ROOT / "scripts" / "prepare_budget_step9.py"
)
step9 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(step9)


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class PrepareBudgetStep9Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = load("activity_archive.json")
        cls.master = load("budget_master.json")
        cls.mapping = load("budget_existing_mapping.json")
        cls.data = step9.build_candidates(cls.archive, cls.master, cls.mapping)
        cls.by_loc = {c["source_locator"]: c for c in cls.data["candidates"]}

    def test_counts(self):
        self.assertEqual(
            self.data["counts"],
            {
                "master_items": 625,
                "existing_budget_records": 324,
                "covered_master_items": 332,
                "existing_1to1": 317,
                "split_candidates": 15,
                "missing_candidates": 293,
            },
        )

    def test_all_master_locators_exactly_once(self):
        master_locs = [m["source_locator"] for m in self.master]
        candidate_locs = [c["source_locator"] for c in self.data["candidates"]]
        self.assertEqual(candidate_locs, master_locs)
        self.assertEqual(len(candidate_locs), len(set(candidate_locs)))

    def test_known_split_groups(self):
        for loc in (
            "2025-06-01", "2025-06-02",
            "2025-06-09", "2025-06-10",
            "2025-08-05", "2025-08-06",
            "2025-15-02", "2025-15-03", "2025-15-04",
            "2024-04-08", "2024-04-09",
            "2024-09-01", "2024-09-02",
            "2023-09-02", "2023-19-04",
        ):
            self.assertEqual(self.by_loc[loc]["candidate_status"], "split_from_existing")
            self.assertEqual(
                self.by_loc[loc]["inheritance_policy"],
                "do_not_inherit_result_level_without_review",
            )

    def test_missing_has_no_legacy_record(self):
        c = self.by_loc["2021-11-02"]
        self.assertEqual(c["candidate_status"], "missing")
        self.assertIsNone(c["legacy_archive_index"])
        self.assertIsNone(c["legacy_record"])

    def test_one_to_one_keeps_old_record_only_as_review_context(self):
        c = self.by_loc["2026-07-13"]
        self.assertEqual(c["candidate_status"], "existing_1to1")
        self.assertIsInstance(c["legacy_archive_index"], int)
        self.assertEqual(c["legacy_record"]["source_type"], "予算提案")
        self.assertEqual(c["inheritance_policy"], "carryover_requires_confirmation")

    def test_no_unreviewed_public_fields_at_candidate_top_level(self):
        forbidden = {"result_level", "tags", "question_topic", "summary", "answer_summary", "date", "id"}
        for c in self.data["candidates"]:
            self.assertFalse(forbidden & set(c), c["source_locator"])

    def test_unknown_locator_fails(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["entries"][0]["source_locators"] = ["2099-99-99"]
        with self.assertRaises(step9.Step9Error):
            step9.build_candidates(self.archive, self.master, mapping)

    def test_duplicate_archive_index_fails(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["entries"][1]["archive_index"] = mapping["entries"][0]["archive_index"]
        with self.assertRaises(step9.Step9Error):
            step9.build_candidates(self.archive, self.master, mapping)


if __name__ == "__main__":
    unittest.main()
