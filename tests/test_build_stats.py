"""scripts/build_stats.py の機械テスト。

正本データ自体は書き換えない。ファイル改ざん系の確認は、リポジトリ構造を
一時ディレクトリに複製して、そちらの複製ファイルだけを操作する。
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
        self.assertEqual(stats["total"], 967)

    def test_by_source_type_matches_current_db(self) -> None:
        stats = build_stats.compute_stats(self.data, self.schema)
        self.assertEqual(stats["by_source_type"], {"議事録": 342, "予算提案": 625})

    def test_by_result_level_matches_current_db(self) -> None:
        stats = build_stats.compute_stats(self.data, self.schema)
        self.assertEqual(
            stats["by_result_level"],
            {
                "実施済": 152,
                "改善・対応予定": 423,
                "検討を引き出した": 100,
                "研究段階": 109,
                "提案のみ": 157,
                "適正確認": 26,
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


class SchemaDrivenRenderingTest(unittest.TestCase):
    """修正1: 分類名一覧をコードに固定記述せず、schema enum → 集計辞書 → 生成物、の一方向であることを確認する。

    schema enum に新しい分類を追加した fixture で、stats.json だけでなく
    README にも自動的に反映されることを、source_type / result_level の両方で確認する。
    """

    def _schema_with_extra_source_type(self) -> dict:
        schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
        schema["items"]["properties"]["source_type"]["enum"] = ["議事録", "予算提案", "陳情対応"]
        return schema

    def _schema_with_extra_result_level(self) -> dict:
        schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
        schema["items"]["properties"]["result_level"]["enum"] = [
            "実施済", "改善・対応予定", "検討を引き出した", "研究段階", "提案のみ", "適正確認", "新設区分",
        ]
        return schema

    def test_new_source_type_appears_in_stats_and_readme_without_code_change(self) -> None:
        schema = self._schema_with_extra_source_type()
        data = [
            {"source_type": "議事録", "result_level": "実施済"},
            {"source_type": "陳情対応", "result_level": "実施済"},
        ]
        stats = build_stats.compute_stats(data, schema)
        self.assertIn("陳情対応", stats["by_source_type"])
        self.assertEqual(stats["by_source_type"]["陳情対応"], 1)

        stats_json = build_stats.render_stats_json(stats)
        self.assertIn('"陳情対応": 1', stats_json)

        block = build_stats.render_readme_block(stats)
        self.assertIn("陳情対応1件", block)

    def test_new_result_level_appears_in_stats_and_readme_without_code_change(self) -> None:
        schema = self._schema_with_extra_result_level()
        data = [
            {"source_type": "議事録", "result_level": "実施済"},
            {"source_type": "議事録", "result_level": "新設区分"},
        ]
        stats = build_stats.compute_stats(data, schema)
        self.assertIn("新設区分", stats["by_result_level"])
        self.assertEqual(stats["by_result_level"]["新設区分"], 1)

        stats_json = build_stats.render_stats_json(stats)
        self.assertIn('"新設区分": 1', stats_json)

        block = build_stats.render_readme_block(stats)
        self.assertIn("新設区分1件", block)

    def test_readme_block_has_no_hardcoded_category_names_beyond_schema(self) -> None:
        # 分類名が schema enum 由来であることを、意図的に schema 側だけ入れ替えて確認する
        # （コード内の固定文字列が生き残っていれば、ここで元の分類名が漏れて出てくる）
        schema = self._schema_with_extra_source_type()
        schema["items"]["properties"]["source_type"]["enum"] = ["X類型", "Y類型"]
        data = [{"source_type": "X類型", "result_level": "実施済"}]
        # result_level は schema既定のままにするため、実データのresult_level enumを流用
        real_schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
        schema["items"]["properties"]["result_level"] = real_schema["items"]["properties"]["result_level"]
        stats = build_stats.compute_stats(data, schema)
        block = build_stats.render_readme_block(stats)
        self.assertIn("X類型1件", block)
        self.assertNotIn("議事録", block)
        self.assertNotIn("予算提案", block)


class MarkerValidationTest(unittest.TestCase):
    """修正3: <!-- stats:start/end --> が1個ずつ・正順であることの検証。"""

    def setUp(self) -> None:
        self.data, self.schema = build_stats.load_data()
        self.stats = build_stats.compute_stats(self.data, self.schema)
        self.block = build_stats.render_readme_block(self.stats)

    def test_missing_start_fails(self) -> None:
        text = f"前文\n\n{build_stats.BLOCK_END}\n後文\n"
        with self.assertRaises(build_stats.ReadmeMarkerError):
            build_stats.apply_readme_block(text, self.block)

    def test_missing_end_fails(self) -> None:
        text = f"前文\n\n{build_stats.BLOCK_START}\n後文\n"
        with self.assertRaises(build_stats.ReadmeMarkerError):
            build_stats.apply_readme_block(text, self.block)

    def test_duplicate_start_fails(self) -> None:
        text = f"{build_stats.BLOCK_START}\nA\n{build_stats.BLOCK_START}\nB\n{build_stats.BLOCK_END}\n"
        with self.assertRaises(build_stats.ReadmeMarkerError):
            build_stats.apply_readme_block(text, self.block)

    def test_duplicate_end_fails(self) -> None:
        text = f"{build_stats.BLOCK_START}\nA\n{build_stats.BLOCK_END}\nB\n{build_stats.BLOCK_END}\n"
        with self.assertRaises(build_stats.ReadmeMarkerError):
            build_stats.apply_readme_block(text, self.block)

    def test_reversed_markers_fail_without_duplicating_body(self) -> None:
        text = f"前文\n{build_stats.BLOCK_END}\n本文\n{build_stats.BLOCK_START}\n後文\n"
        with self.assertRaises(build_stats.ReadmeMarkerError):
            build_stats.apply_readme_block(text, self.block)

    def test_valid_markers_pass(self) -> None:
        text = f"前文\n\n{build_stats.BLOCK_START}\nダミー\n{build_stats.BLOCK_END}\n\n後文\n"
        result = build_stats.apply_readme_block(text, self.block)
        self.assertIn(self.block, result)
        self.assertTrue(result.startswith("前文\n\n"))
        self.assertTrue(result.endswith("\n\n後文\n"))

    def test_bad_markers_do_not_touch_files_via_cli(self) -> None:
        # main() 経由でも、マーカー異常時はファイルへの書き込みが一切発生しないことを確認する
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = pathlib.Path(tmp)
            (tmp_root / "scripts").mkdir()
            shutil.copy(ROOT / "scripts" / "build_stats.py", tmp_root / "scripts" / "build_stats.py")
            shutil.copy(ROOT / "activity_archive.json", tmp_root / "activity_archive.json")
            shutil.copy(ROOT / "schema.json", tmp_root / "schema.json")
            # マーカーが2個ある壊れたREADME
            bad_readme = f"{build_stats.BLOCK_START}\nA\n{build_stats.BLOCK_START}\nB\n{build_stats.BLOCK_END}\n"
            (tmp_root / "README.md").write_text(bad_readme, encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(tmp_root / "scripts" / "build_stats.py")],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((tmp_root / "stats.json").exists())
            self.assertEqual((tmp_root / "README.md").read_text(encoding="utf-8"), bad_readme)


class CheckModeTest(unittest.TestCase):
    """--check の FAIL/PASS と非破壊性を、複製したリポジトリ構造の上で確認する。"""

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
        text = text.replace("収録件数：967件", "収録件数：改ざん件")
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

    def test_check_does_not_write_stats_json_when_missing(self) -> None:
        # 修正6: --check は不一致状態でもファイルを一切変更しない
        self.assertFalse((self.tmp_root / "stats.json").exists())
        self._run("--check")
        self.assertFalse((self.tmp_root / "stats.json").exists())

    def test_check_does_not_modify_readme_when_mismatched(self) -> None:
        # 修正6: README.md がまだ生成前（ダミー本文）でも --check はREADMEを書き換えない
        readme_path = self.tmp_root / "README.md"
        before = readme_path.read_text(encoding="utf-8")
        result = self._run("--check")
        after = readme_path.read_text(encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, after)

    def test_check_does_not_modify_tampered_stats_json(self) -> None:
        # 修正6: 一度生成した後で stats.json を改ざんしても、--check はそれを書き戻さない
        self._run()
        stats_path = self.tmp_root / "stats.json"
        tampered = json.loads(stats_path.read_text(encoding="utf-8"))
        tampered["total"] = 1
        tampered_text = json.dumps(tampered, ensure_ascii=False, indent=2) + "\n"
        stats_path.write_text(tampered_text, encoding="utf-8")

        readme_path = self.tmp_root / "README.md"
        readme_before = readme_path.read_text(encoding="utf-8")

        result = self._run("--check")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(stats_path.read_text(encoding="utf-8"), tampered_text)
        self.assertEqual(readme_path.read_text(encoding="utf-8"), readme_before)


if __name__ == "__main__":
    unittest.main()
