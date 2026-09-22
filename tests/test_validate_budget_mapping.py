from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "validate_budget_mapping", ROOT / "scripts" / "validate_budget_mapping.py"
)
vbm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(vbm)


def load(name):
    with (ROOT / name).open(encoding="utf-8") as f:
        return json.load(f)


class BudgetMappingValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = load("activity_archive.json")
        cls.master = load("budget_master.json")
        cls.mapping = load("budget_existing_mapping.json")
        cls.unmatched = load("budget_unmatched_master.json")

    def test_real_mapping_summary(self):
        s = vbm.validate(self.archive, self.master, self.mapping, self.unmatched)
        self.assertEqual(s["existing_budget_records"], 324)
        self.assertEqual(s["authoritative_master_items"], 625)
        self.assertEqual(s["covered_master_items"], 332)
        self.assertEqual(s["unmatched_master_items"], 293)
        self.assertEqual(s["one_to_one_records"], 317)
        self.assertEqual(s["one_to_many_records"], 7)
        self.assertEqual(
            s["by_year"],
            {
                "2021": {"old_records": 72, "covered_master_items": 72, "unmatched_master_items": 4},
                "2022": {"old_records": 71, "covered_master_items": 71, "unmatched_master_items": 24},
                "2023": {"old_records": 91, "covered_master_items": 92, "unmatched_master_items": 20},
                "2024": {"old_records": 41, "covered_master_items": 43, "unmatched_master_items": 72},
                "2025": {"old_records": 41, "covered_master_items": 46, "unmatched_master_items": 76},
                "2026": {"old_records": 8, "covered_master_items": 8, "unmatched_master_items": 97},
            },
        )

    def test_known_one_to_many_records(self):
        by_idx = {e["archive_index"]: e for e in self.mapping["entries"]}
        self.assertEqual(by_idx[73]["source_locators"], ["2025-06-01", "2025-06-02"])
        self.assertEqual(by_idx[74]["source_locators"], ["2025-06-09", "2025-06-10"])
        self.assertEqual(by_idx[79]["source_locators"], ["2025-08-05", "2025-08-06"])
        self.assertEqual(by_idx[95]["source_locators"], ["2025-15-02", "2025-15-03", "2025-15-04"])
        self.assertEqual(by_idx[127]["source_locators"], ["2024-04-08", "2024-04-09"])
        self.assertEqual(by_idx[142]["source_locators"], ["2024-09-01", "2024-09-02"])
        self.assertEqual(by_idx[211]["source_locators"], ["2023-09-02", "2023-19-04"])

    def test_duplicate_archive_index_fails(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["entries"][1]["archive_index"] = mapping["entries"][0]["archive_index"]
        with self.assertRaises(vbm.MappingValidationError):
            vbm.validate(self.archive, self.master, mapping, self.unmatched)

    def test_fingerprint_mismatch_fails(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["entries"][0]["question_topic"] += "x"
        with self.assertRaises(vbm.MappingValidationError):
            vbm.validate(self.archive, self.master, mapping, self.unmatched)

    def test_source_locator_reuse_fails(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["entries"][1]["source_locators"] = list(mapping["entries"][0]["source_locators"])
        mapping["entries"][1]["mapping_type"] = mapping["entries"][0]["mapping_type"]
        with self.assertRaises(vbm.MappingValidationError):
            vbm.validate(self.archive, self.master, mapping, self.unmatched)

    def test_fiscal_year_mismatch_fails(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["entries"][0]["source_locators"] = ["2021-01-01"]
        mapping["entries"][0]["mapping_type"] = "one_to_one"
        with self.assertRaises(vbm.MappingValidationError):
            vbm.validate(self.archive, self.master, mapping, self.unmatched)

    def test_unmatched_must_be_exact_complement(self):
        unmatched = copy.deepcopy(self.unmatched)
        unmatched["items"] = unmatched["items"][:-1]
        unmatched["count"] -= 1
        with self.assertRaises(vbm.MappingValidationError):
            vbm.validate(self.archive, self.master, self.mapping, unmatched)


if __name__ == "__main__":
    unittest.main()
