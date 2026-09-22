"""scripts/build_budget.py の機械テスト。

正本PDFはリポジトリに含まれないため、抽出ロジック（大項目・個別提案・回答境界・
ページ番号処理）は合成した body_lines / ページテキストに対して直接テストする。
pdftotext / pdfinfo の呼び出しはモックし、実PDFへの依存を切り離す。

22-6（生成済masterの回帰確認）のみ、実際にリポジトリへ生成済みの
budget_master.json / budget_master.csv を対象にする。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_budget as bb  # noqa: E402


def lines(text: str) -> list[str]:
    """テスト用に、複数行の生テキストからbody_linesを作る（先頭改行を無視）。"""
    if text.startswith("\n"):
        text = text[1:]
    return text.split("\n")


class MajorAndItemParsingTest(unittest.TestCase):
    """22-1: 項目構造。"""

    def setUp(self) -> None:
        self.patch_major = mock.patch.dict(bb.MAJOR_COUNT, {9001: 2, 9002: 2}, clear=False)
        self.patch_style = mock.patch.dict(bb.ITEM_STYLE, {9001: "symbol", 9002: "circled"}, clear=False)
        self.patch_major.start()
        self.patch_style.start()
        self.addCleanup(self.patch_major.stop)
        self.addCleanup(self.patch_style.stop)

    def test_symbol_marker_maru_kanji(self) -> None:
        body = lines("""
１．最初の大項目
 〇最初の提案。
（回答）担当課
 回答本文。

２．次の大項目
 〇二番目の提案。
（回答）担当課
 回答本文。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual([r["source_locator"] for r in records], ["9001-01-01", "9001-02-01"])
        self.assertEqual(records[0]["proposal_text"], "最初の提案。")

    def test_symbol_marker_maru_circle(self) -> None:
        body = lines("""
１．最初の大項目
 ○最初の提案。
（回答）担当課
 回答本文。

２．次の大項目
 ○二番目の提案。
（回答）担当課
 回答本文。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(records[0]["proposal_text"], "最初の提案。")
        self.assertEqual(records[1]["proposal_text"], "二番目の提案。")

    def test_circled_number_format(self) -> None:
        body = lines("""
１．最初の大項目
①最初の提案。
（回答）担当課
 回答本文。
②二番目の提案。
（回答）担当課
 回答本文。

２．次の大項目
①三番目の提案。
（回答）担当課
 回答本文。
""")
        records = bb.parse_year(9002, body)
        locators = [r["source_locator"] for r in records]
        self.assertEqual(locators, ["9002-01-01", "9002-01-02", "9002-02-01"])
        self.assertEqual(records[2]["item_no"], 1)  # 大項目ごとに①からリセット

    def test_leading_whitespace_after_marker_is_stripped(self) -> None:
        with mock.patch.dict(bb.MAJOR_COUNT, {9002: 1}):
            body = lines("""
１．大項目
①  多胎児家庭への支援。
（回答）担当課
 回答本文。
""")
            records = bb.parse_year(9002, body)
        self.assertEqual(records[0]["proposal_text"], "多胎児家庭への支援。")

    def test_major_heading_fullwidth_period(self) -> None:
        body = lines("""
１．タイトルＡ
 〇提案。
（回答）課
 回答。
２．タイトルＢ
 〇提案２。
（回答）課
 回答。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(records[1]["major_title"], "タイトルＢ")

    def test_major_heading_halfwidth_period(self) -> None:
        body = lines("""
１. タイトルＡ
 〇提案。
（回答）課
 回答。
２.タイトルＢ
 〇提案２。
（回答）課
 回答。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(records[0]["major_title"], "タイトルＡ")
        self.assertEqual(records[1]["major_title"], "タイトルＢ")

    def test_number_not_current_plus_one_is_not_treated_as_major(self) -> None:
        # current_major+1 以外の番号表記（ここでは「５．」）を大項目と誤認識しない。
        body = lines("""
１．最初の大項目
 〇提案文の続き。
５．という番号を含む行が混ざっていても、大項目とは扱われない。
（回答）課
 回答。
２．次の大項目
 〇提案２。
（回答）課
 回答。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual([r["major_no"] for r in records], [1, 2])
        self.assertIn("５．という番号を含む行が混ざっていても", records[0]["proposal_text"])

    def test_major_number_gap_fails(self) -> None:
        with mock.patch.dict(bb.MAJOR_COUNT, {9001: 3}):
            body = lines("""
１．大項目
 〇提案。
（回答）課
 回答。
３．次の大項目（２が欠番）
 〇提案。
（回答）課
 回答。
""")
            with self.assertRaises(bb.BuildError):
                bb.parse_year(9001, body)

    def test_major_title_empty_fails(self) -> None:
        body = lines("""
１．
 〇提案。
（回答）課
 回答。
""")
        with self.assertRaises(bb.BuildError):
            bb.parse_year(9001, body)


class ProposalBoundaryTest(unittest.TestCase):
    """22-2: proposal境界。"""

    def setUp(self) -> None:
        self.patch_major = mock.patch.dict(bb.MAJOR_COUNT, {9001: 1}, clear=False)
        self.patch_style = mock.patch.dict(bb.ITEM_STYLE, {9001: "symbol"}, clear=False)
        self.patch_major.start()
        self.patch_style.start()
        self.addCleanup(self.patch_major.stop)
        self.addCleanup(self.patch_style.stop)

    def test_multiline_proposal_joined_without_extra_chars(self) -> None:
        body = lines("""
１．大項目
 〇学習支援教室については、貧困の連鎖を断ち切り、子どもたちが将来に向けて自立の力
  を養えるよう、学習支援の充実をはかること。
（回答）課
 回答。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(
            records[0]["proposal_text"],
            "学習支援教室については、貧困の連鎖を断ち切り、子どもたちが将来に向けて自立の力を養えるよう、学習支援の充実をはかること。",
        )

    def test_first_answer_marker_ends_proposal(self) -> None:
        body = lines("""
１．大項目
 〇提案文。
（回答）課１
 回答本文その１。
（回答）課２
 回答本文その２。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(records[0]["proposal_text"], "提案文。")

    def test_answer_marker_variant_zenkaku_zenkaku(self) -> None:
        body = lines("""
１．大項目
 〇提案文。
（回答）課
 回答。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(records[0]["proposal_text"], "提案文。")

    def test_answer_marker_variant_hankaku_hankaku(self) -> None:
        body = lines("""
１．大項目
 〇提案文。
(回答)課
 回答。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(records[0]["proposal_text"], "提案文。")

    def test_answer_marker_variant_zenkaku_hankaku(self) -> None:
        body = lines("""
１．大項目
 〇提案文。
（回答)課
 回答。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(records[0]["proposal_text"], "提案文。")

    def test_answer_marker_variant_hankaku_zenkaku(self) -> None:
        body = lines("""
１．大項目
 〇提案文。
(回答）課
 回答。
""")
        records = bb.parse_year(9001, body)
        self.assertEqual(records[0]["proposal_text"], "提案文。")

    def test_missing_answer_marker_fails_for_normal_item(self) -> None:
        body = lines("""
１．大項目
 〇回答マーカーの無い提案文。
続きの本文。
""")
        with self.assertRaises(bb.BuildError):
            bb.parse_year(9001, body)

    def test_allowlist_exception_2021_07_03_passes(self) -> None:
        with mock.patch.dict(bb.MAJOR_COUNT, {2021: 7}):
            body_parts = []
            for major_no in range(1, 7):
                body_parts.append(f"{_to_fw(major_no)}．大項目{major_no}")
                body_parts.append(" 〇提案。")
                body_parts.append("（回答）課")
                body_parts.append(" 回答。")
            body_parts.append("７．放課後児童クラブの施設、環境の充実")
            body_parts.append(" 〇ダミー提案その１。")
            body_parts.append("（回答）課")
            body_parts.append(" 回答。")
            body_parts.append(" 〇ダミー提案その２。")
            body_parts.append("（回答）課")
            body_parts.append(" 回答。")
            body_parts.append(" 〇放課後児童クラブ入室事務に関する保護者負担の軽減。")
            body_parts.append("続けて回答本文がマーカー無しで続く。")
            body = body_parts

            records = bb.parse_year(2021, body)
            target = next(r for r in records if r["source_locator"] == "2021-07-03")
            self.assertEqual(target["proposal_text"], "放課後児童クラブ入室事務に関する保護者負担の軽減。")

    def test_allowlist_exception_2021_07_03_text_mismatch_fails(self) -> None:
        with mock.patch.dict(bb.MAJOR_COUNT, {2021: 7}):
            body_parts = []
            for major_no in range(1, 7):
                body_parts.append(f"{_to_fw(major_no)}．大項目{major_no}")
                body_parts.append(" 〇提案。")
                body_parts.append("（回答）課")
                body_parts.append(" 回答。")
            body_parts.append("７．放課後児童クラブの施設、環境の充実")
            body_parts.append(" 〇ダミー提案その１。")
            body_parts.append("（回答）課")
            body_parts.append(" 回答。")
            body_parts.append(" 〇ダミー提案その２。")
            body_parts.append("（回答）課")
            body_parts.append(" 回答。")
            body_parts.append(" 〇全く違う提案文（マーカー無し）。")
            body_parts.append("続けて回答本文が続く。")
            body = body_parts

            with self.assertRaises(bb.BuildError):
                bb.parse_year(2021, body)


def _to_fw(n: int) -> str:
    return str(n).translate(str.maketrans("0123456789", bb.FULLWIDTH_DIGITS))


class PageNumberProcessingTest(unittest.TestCase):
    """22-3: ページ番号処理。"""

    def test_split_physical_pages_splits_on_formfeed(self) -> None:
        text = "cover\fpage2\fpage3\f"
        with mock.patch.object(bb, "get_pdf_page_count", return_value=3):
            parts = bb.split_physical_pages(text, 2021, pathlib.Path("dummy.pdf"))
        self.assertEqual(parts, ["cover", "page2", "page3"])

    def test_cover_page_skips_page_number_validation(self) -> None:
        result = bb.strip_page_number(2021, 1, "何か表紙のテキスト（ページ番号なし）")
        self.assertEqual(result, "何か表紙のテキスト（ページ番号なし）")

    def test_plain_digit_page_number_removed(self) -> None:
        page = "本文行1\n本文行2\n                8"
        result = bb.strip_page_number(2021, 5, page)
        self.assertEqual(result, "本文行1\n本文行2")

    def test_dash_style_page_number_removed(self) -> None:
        page = "本文行1\n本文行2\n              - 15 -"
        result = bb.strip_page_number(2022, 15, page)
        self.assertEqual(result, "本文行1\n本文行2")

    def test_padded_dash_style_page_number_removed_after_strip(self) -> None:
        page = "本文行1\n   - 15 -   "
        result = bb.strip_page_number(2022, 15, page)
        self.assertEqual(result, "本文行1")

    def test_body_line_ending_in_digits_is_not_removed(self) -> None:
        page = "予算額は１５千円である"
        with self.assertRaises(bb.BuildError):
            bb.strip_page_number(2021, 5, page)

    def test_lone_number_not_at_page_end_is_kept(self) -> None:
        page = "1\n本文はここまで"
        with self.assertRaises(bb.BuildError):
            bb.strip_page_number(2021, 5, page)

    def test_unexpected_page_tail_format_fails(self) -> None:
        page = "本文行1\n本文行2\nこれはページ番号ではない"
        with self.assertRaises(bb.BuildError):
            bb.strip_page_number(2021, 5, page)

    def test_known_blank_page_allowlisted(self) -> None:
        result = bb.strip_page_number(2023, 2, "")
        self.assertIsNone(result)

    def test_known_blank_page_with_content_fails(self) -> None:
        with self.assertRaises(bb.BuildError):
            bb.strip_page_number(2023, 2, "想定外の本文")

    def test_blank_page_in_middle_outside_allowlist_fails_via_split(self) -> None:
        text = "cover\f\fpage3\f"
        with mock.patch.object(bb, "get_pdf_page_count", return_value=3):
            with self.assertRaises(bb.BuildError):
                bb.split_physical_pages(text, 2021, pathlib.Path("dummy.pdf"))

    def test_known_blank_page_in_middle_allowed_via_split(self) -> None:
        text = "cover\f\fpage3\f"
        with mock.patch.object(bb, "get_pdf_page_count", return_value=3):
            parts = bb.split_physical_pages(text, 2023, pathlib.Path("dummy.pdf"))
        self.assertEqual(parts, ["cover", "", "page3"])

    def test_trailing_empty_element_from_final_formfeed_is_ignored(self) -> None:
        text = "cover\fpage2\f"
        with mock.patch.object(bb, "get_pdf_page_count", return_value=2):
            parts = bb.split_physical_pages(text, 2021, pathlib.Path("dummy.pdf"))
        self.assertEqual(parts, ["cover", "page2"])

    def test_cross_page_proposal_reconnected_without_page_number_leak(self) -> None:
        with mock.patch.dict(bb.MAJOR_COUNT, {9001: 1}), \
             mock.patch.dict(bb.ITEM_STYLE, {9001: "symbol"}):
            # fiscal_year=9001はKNOWN_BLANK_PAGESのallowlistに該当しない架空年度。
            page1 = "１．大項目\n 〇社会参加を支援するこ\n              - 15 -"
            stripped1 = bb.strip_page_number(9001, 5, page1)
            body_lines = stripped1.split("\n") + ["と。", "（回答）課", " 回答。"]
            records = bb.parse_year(9001, body_lines)
            self.assertEqual(records[0]["proposal_text"], "社会参加を支援すること。")


class NumberingAndLocatorTest(unittest.TestCase):
    """22-4: 番号・locator。"""

    def setUp(self) -> None:
        self.patch_major = mock.patch.dict(bb.MAJOR_COUNT, {9002: 1}, clear=False)
        self.patch_style = mock.patch.dict(bb.ITEM_STYLE, {9002: "circled"}, clear=False)
        self.patch_major.start()
        self.patch_style.start()
        self.addCleanup(self.patch_major.stop)
        self.addCleanup(self.patch_style.stop)

    def test_circled_number_gap_fails(self) -> None:
        body = lines("""
１．大項目
①提案。
（回答）課
 回答。
③提案（②が欠番）。
（回答）課
 回答。
""")
        with self.assertRaises(bb.BuildError):
            bb.parse_year(9002, body)

    def test_circled_number_duplicate_fails(self) -> None:
        body = lines("""
１．大項目
①提案その１。
（回答）課
 回答。
①提案その２（重複）。
（回答）課
 回答。
""")
        with self.assertRaises(bb.BuildError):
            bb.parse_year(9002, body)

    def test_source_locator_uniqueness_checked_in_audit(self) -> None:
        records = [
            {"fiscal_year": 2021, "source_locator": "2021-01-01", "major_no": 1,
             "major_title": "t", "item_no": 1, "proposal_text": "x"},
            {"fiscal_year": 2021, "source_locator": "2021-01-01", "major_no": 1,
             "major_title": "t", "item_no": 1, "proposal_text": "y"},
        ]
        with self.assertRaises(bb.BuildError):
            bb.audit_master(records)

    def test_empty_proposal_text_fails(self) -> None:
        with mock.patch.dict(bb.MAJOR_COUNT, {9001: 1}), \
             mock.patch.dict(bb.ITEM_STYLE, {9001: "symbol"}):
            body = lines("""
１．大項目
 〇（回答）課
 回答。
""")
            with self.assertRaises(bb.BuildError):
                bb.parse_year(9001, body)

    def test_duplicate_proposal_text_across_locators_is_kept(self) -> None:
        with mock.patch.dict(bb.MAJOR_COUNT, {9001: 2}), \
             mock.patch.dict(bb.ITEM_STYLE, {9001: "symbol"}):
            body = lines("""
１．大項目Ａ
 〇同じ提案文。
（回答）課
 回答。

２．大項目Ｂ
 〇同じ提案文。
（回答）課
 回答。
""")
            records = bb.parse_year(9001, body)
            self.assertEqual(records[0]["proposal_text"], records[1]["proposal_text"])
            self.assertNotEqual(records[0]["source_locator"], records[1]["source_locator"])


class BuildAndCheckTest(unittest.TestCase):
    """22-5: build/check（sourceファイル確認・SHA確認・--check非破壊・JSON/CSV不一致検出）。"""

    def test_missing_source_pdf_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(bb.BuildError):
                bb.check_source_files(pathlib.Path(tmp))

    def test_sha256_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            paths = {}
            for year in bb.FISCAL_YEARS:
                p = tmp_path / bb.PDF_FILENAMES[year]
                p.write_bytes(b"not a real pdf")
                paths[year] = p
            with self.assertRaises(bb.BuildError):
                bb.check_sha256(paths)

    def test_check_mode_is_non_destructive_and_detects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            json_path = tmp_path / "budget_master.json"
            csv_path = tmp_path / "budget_master.csv"
            stale_json = json.dumps([{"stale": True}], ensure_ascii=False)
            json_path.write_text(stale_json, encoding="utf-8")
            csv_path.write_text("stale\n", encoding="utf-8")

            fake_records = [{
                "fiscal_year": 2021, "source_locator": "2021-01-01", "major_no": 1,
                "major_title": "t", "item_no": 1, "proposal_text": "x",
            }]

            with mock.patch.object(bb, "JSON_PATH", json_path), \
                 mock.patch.object(bb, "CSV_PATH", csv_path), \
                 mock.patch.object(bb, "build_master", return_value=fake_records), \
                 mock.patch("sys.argv", ["build_budget.py", "--source-dir", tmp, "--check"]):
                rc = bb.main()

            self.assertNotEqual(rc, 0)
            # --check は不一致でもファイルを書き換えない
            self.assertEqual(json_path.read_text(encoding="utf-8"), stale_json)
            self.assertEqual(csv_path.read_text(encoding="utf-8"), "stale\n")

    def test_check_mode_passes_when_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            json_path = tmp_path / "budget_master.json"
            csv_path = tmp_path / "budget_master.csv"

            fake_records = [{
                "fiscal_year": 2021, "source_locator": "2021-01-01", "major_no": 1,
                "major_title": "t", "item_no": 1, "proposal_text": "x",
            }]
            json_path.write_text(bb.render_json(fake_records), encoding="utf-8")
            csv_path.write_text(bb.render_csv(fake_records), encoding="utf-8")

            with mock.patch.object(bb, "JSON_PATH", json_path), \
                 mock.patch.object(bb, "CSV_PATH", csv_path), \
                 mock.patch.object(bb, "build_master", return_value=fake_records), \
                 mock.patch("sys.argv", ["build_budget.py", "--source-dir", tmp, "--check"]):
                rc = bb.main()

            self.assertEqual(rc, 0)


class LanguagePackAndVersionTest(unittest.TestCase):
    """5-1/5-2 相当: pdftotextバージョン取得・language pack異常の検出。"""

    def test_missing_language_pack_fails(self) -> None:
        fake = mock.Mock()
        fake.returncode = 0
        fake.stdout = b"some text"
        fake.stderr = "Warning: Missing language pack for 'Japan' mapping\n".encode("utf-8")
        with mock.patch.object(bb.subprocess, "run", return_value=fake):
            with self.assertRaises(bb.BuildError):
                bb.run_pdftotext(pathlib.Path("dummy.pdf"))

    def test_version_parsed_from_stderr(self) -> None:
        fake = mock.Mock()
        fake.stdout = b""
        fake.stderr = b"pdftotext version 24.02.0\nCopyright ...\n"
        with mock.patch.object(bb.subprocess, "run", return_value=fake):
            version = bb.get_pdftotext_version()
        self.assertEqual(version, "24.02.0")

    def test_pdftotext_not_found_fails(self) -> None:
        with mock.patch.object(bb.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaises(bb.BuildError):
                bb.get_pdftotext_version()


class GeneratedMasterRegressionTest(unittest.TestCase):
    """22-6: 生成済み budget_master.json / budget_master.csv の回帰確認。"""

    @classmethod
    def setUpClass(cls) -> None:
        json_path = ROOT / "budget_master.json"
        csv_path = ROOT / "budget_master.csv"
        if not json_path.exists() or not csv_path.exists():
            raise unittest.SkipTest("budget_master.json/csvが未生成のためスキップ")
        cls.records = json.loads(json_path.read_text(encoding="utf-8"))
        with csv_path.open(encoding="utf-8", newline="") as f:
            cls.csv_rows = list(csv.DictReader(f))

    def test_grand_total_is_625(self) -> None:
        self.assertEqual(len(self.records), 625)

    def test_year_totals_match_section19_audit(self) -> None:
        expected = {y: sum(counts) for y, counts in bb.INDEPENDENT_AUDIT.items()}
        actual: dict[int, int] = {}
        for r in self.records:
            actual[r["fiscal_year"]] = actual.get(r["fiscal_year"], 0) + 1
        self.assertEqual(actual, expected)

    def test_major_totals_match_section19_audit(self) -> None:
        for year, expected_counts in bb.INDEPENDENT_AUDIT.items():
            by_major: dict[int, int] = {}
            for r in self.records:
                if r["fiscal_year"] == year:
                    by_major[r["major_no"]] = by_major.get(r["major_no"], 0) + 1
            actual_counts = [by_major.get(i + 1, 0) for i in range(len(expected_counts))]
            self.assertEqual(actual_counts, expected_counts, f"fiscal_year={year}")

    def test_source_locator_unique(self) -> None:
        locators = [r["source_locator"] for r in self.records]
        self.assertEqual(len(locators), len(set(locators)))

    def test_proposal_text_and_major_title_non_empty(self) -> None:
        for r in self.records:
            self.assertTrue(r["proposal_text"])
            self.assertTrue(r["major_title"])

    def test_2023_duplicate_preserved(self) -> None:
        by_loc = {r["source_locator"]: r for r in self.records}
        self.assertIn("2023-09-02", by_loc)
        self.assertIn("2023-19-04", by_loc)
        self.assertEqual(by_loc["2023-09-02"]["proposal_text"], by_loc["2023-19-04"]["proposal_text"])

    def test_2021_07_03_exact(self) -> None:
        by_loc = {r["source_locator"]: r for r in self.records}
        self.assertEqual(
            by_loc["2021-07-03"]["proposal_text"],
            "放課後児童クラブ入室事務に関する保護者負担の軽減。",
        )

    def test_mixed_answer_markers_do_not_leak_into_proposal_text(self) -> None:
        by_loc = {r["source_locator"]: r for r in self.records}
        for loc in ("2024-04-05", "2026-06-04", "2026-06-07", "2026-09-02"):
            self.assertIn(loc, by_loc)
            self.assertNotIn("回答", by_loc[loc]["proposal_text"])

    def test_cross_page_proposals_have_no_page_number_leak(self) -> None:
        by_loc = {r["source_locator"]: r for r in self.records}
        for loc in ("2021-12-01", "2023-02-01", "2024-07-05"):
            self.assertIn(loc, by_loc)
            self.assertNotRegex(by_loc[loc]["proposal_text"], r"-\s*\d+\s*-")

    def test_json_and_csv_row_count_match(self) -> None:
        self.assertEqual(len(self.csv_rows), len(self.records))

    def test_json_and_csv_content_match(self) -> None:
        for r, row in zip(self.records, self.csv_rows):
            self.assertEqual(str(r["fiscal_year"]), row["fiscal_year"])
            self.assertEqual(r["source_locator"], row["source_locator"])
            self.assertEqual(str(r["major_no"]), row["major_no"])
            self.assertEqual(r["major_title"], row["major_title"])
            self.assertEqual(str(r["item_no"]), row["item_no"])
            self.assertEqual(r["proposal_text"], row["proposal_text"])


if __name__ == "__main__":
    unittest.main()
