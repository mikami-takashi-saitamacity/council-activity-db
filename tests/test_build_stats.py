"""scripts/build_stats.py の機械テスト。

正本データ自体は書き換えない。--check の FAIL 系は、リポジトリ構造を
一時ディレクトリに複製して、そちらの複製ファイルだけを改ざんして確認する。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_stats  # noqa: E402


class ComputeStatsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data, self.schema = build_stats.load_data()

    def test_total_matches_current_db(self) -> None:
        stats = build_stats.compute_stats(self.data, self.schema)
        self.assertEqual(stats["total"], 666)

    def test_by_source_type_matches_current_db(self) -> None:
        stats = build_stats.compute_stats(self.data, self.schema)
        self.assertEqual(stats["by_source_type"], {"議事録": 342, "予算提案": 324})

    def test_by_result_level_matches_current_db(self) -> None:
        stats = build_stats.compute_stats(self.data, self.schema)
        self.assertEqual(
            stats["by_result_level"],
            {
                "実施済": 177,
                "改善・対応予定": 204,
                "検討を引き出した": 39,
                "研究段階": 126,
                "提案のみ": 92,
                "適正確認": 28,
            },
        )

    def test_keys_come_from_schema_enum(self) -> None:
        stats = build_stats.compute_stats(self.data, self.schema)
        props = self.schema["items"]["properties"]
        self.assertEqual(list(stats["by_source_type"].keys()), props["source_type"]["enum"])
        self.assertEqual(list(stats["by_result_level"].keys()), props["result_level"]["enum"])

    def test_unknown_source_type_fails_loudly(self) -> None:
        bad_data = [dict(self.data[0])]
        bad_data[0]["source_type"] = "未知の種別"
        with self.assertRaises(ValueError):
            build_stats.compute_stats(bad_data, self.schema)

    def test_unknown_result_level_fails_loudly(self) -> None:
        bad_data = [dict(self.data[0])]
        bad_data[0]["result_level"] = "未知の区分"
        with self.assertRaises(ValueError):
            build_stats.compute_stats(bad_data, self.schema)

    def test_deterministic_across_runs(self) -> None:
        stats_a = build_stats.compute_stats(self.data, self.schema)
        stats_b = build_stats.compute_stats(self.data, self.schema)
        self.assertEqual(build_stats.render_stats_json(stats_a), build_stats.render_stats_json(stats_b))


class CheckModeTest(unittest.TestCase):
    """--check の FAIL/PASS を、複製したリポジトリ構造の上で確認する。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp_root = pathlib.Path(self.tmp.name)
        (tmp_root / "scripts").mkdir()
        shutil.copy(ROOT / "scripts" / "build_stats.py", tmp_root / "scripts" / "build_stats.py")
        shutil.copy(ROOT / "activity_archive.json", tmp_root / "activity_archive.json")
        shutil.copy(ROOT / "schema.json", tmp_root / "schema.json")
        shutil.copy(ROOT / "README.md", tmp_root / "README.md")
        self.tmp_root = tmp_root
        self.script = tmp_root / "scripts" / "build_stats.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            capture_output=True,
            text=True,
        )

    def test_check_fails_before_first_generation(self) -> None:
        result = self._run("--check")
        self.assertNotEqual(result.returncode, 0)

    def test_check_passes_after_generation(self) -> None:
        self._run()
        result = self._run("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_fails_if_stats_json_tampered(self) -> None:
        self._run()
        stats_path = self.tmp_root / "stats.json"
        tampered = json.loads(stats_path.read_text(encoding="utf-8"))
        tampered["total"] = 999999
        stats_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = self._run("--check")
        self.assertNotEqual(result.returncode, 0)

    def test_check_fails_if_readme_block_tampered(self) -> None:
        self._run()
        readme_path = self.tmp_root / "README.md"
        text = readme_path.read_text(encoding="utf-8")
        text = text.replace("収録件数：666件", "収録件数：改ざん件")
        readme_path.write_text(text, encoding="utf-8")
        result = self._run("--check")
        self.assertNotEqual(result.returncode, 0)

    def test_generation_does_not_touch_readme_outside_block(self) -> None:
        before = (self.tmp_root / "README.md").read_text(encoding="utf-8")
        before_head = before.split(build_stats.BLOCK_START)[0]
        before_tail = before.split(build_stats.BLOCK_END)[1]

        self._run()

        after = (self.tmp_root / "README.md").read_text(encoding="utf-8")
        after_head = after.split(build_stats.BLOCK_START)[0]
        after_tail = after.split(build_stats.BLOCK_END)[1]

        self.assertEqual(before_head, after_head)
        self.assertEqual(before_tail, after_tail)


if __name__ == "__main__":
    unittest.main()
