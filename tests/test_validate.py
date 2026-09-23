""".github/validate.py の機械テスト。fixture / 一時ディレクトリのみを使い、実データは書き換えない。

failure系テストは returncode だけでなく、期待する validation エラーメッセージの
存在も確認する（import error 等を「正しくFAILした」と誤認しないため）。
"""
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

    def _run(
        self,
        records: list[dict],
        retired: list[dict] | None = None,
        strict: bool = False,
        retired_json_text: str | None = None,
        omit_retired_file: bool = False,
    ) -> subprocess.CompletedProcess:
        data_path = self.tmp_root / "activity_archive.json"
        data_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

        retired_path = self.tmp_root / "retired_ids.json"
        if not omit_retired_file:
            if retired_json_text is not None:
                retired_path.write_text(retired_json_text, encoding="utf-8")
            else:
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
        self.assertIn("[id重複]", result.stdout)
        self.assertIn("mikami-000001", result.stdout)

    def test_retired_id_duplicate_fails(self) -> None:
        retired = [
            {"id": "mikami-000002", "retired_at": "2026-01-01", "reason": "deleted"},
            {"id": "mikami-000002", "retired_at": "2026-01-02", "reason": "merged"},
        ]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[retired_ids重複]", result.stdout)
        self.assertIn("mikami-000002", result.stdout)

    def test_active_retired_overlap_fails(self) -> None:
        retired = [{"id": "mikami-000003", "retired_at": "2026-01-01", "reason": "deleted"}]
        result = self._run([make_record(id="mikami-000003")], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[active-retired重複]", result.stdout)
        self.assertIn("mikami-000003", result.stdout)

    def test_duplicate_existing_budget_source_locator_fails(self) -> None:
        result = self._run([
            make_record(source_type="予算提案", source_locator="2026-01-01"),
            make_record(date="2026-01-02", source_type="予算提案", source_locator="2026-01-01"),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[source_locator重複]", result.stdout)

    def test_missing_source_locator_passes_in_normal_mode(self) -> None:
        # 通常モードでは「存在する分」だけを検査するので、キー自体が無い分はエラーにしない
        result = self._run([make_record(source_type="予算提案")])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_source_locator_fails_even_in_normal_mode(self) -> None:
        # 修正5: strict modeでなくても、キーが存在する場合は空文字を許さない
        result = self._run([make_record(source_type="予算提案", source_locator="")])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[source_locator]", result.stdout)
        self.assertIn("空文字", result.stdout)


class RetiredIdsFileValidationTest(ValidateHarness):
    """修正2: retired_ids.json を必須ファイルとして厳格に検証する。"""

    def test_missing_file_fails(self) -> None:
        result = self._run([make_record()], omit_retired_file=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[retired_ids]", result.stdout)
        self.assertIn("存在しません", result.stdout)

    def test_root_not_array_fails(self) -> None:
        result = self._run([make_record()], retired_json_text=json.dumps({"id": "mikami-000001"}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[retired_ids]", result.stdout)
        self.assertIn("JSON配列である必要があります", result.stdout)

    def test_id_missing_fails(self) -> None:
        retired = [{"retired_at": "2026-01-01", "reason": "deleted"}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("必須キー 'id' がありません", result.stdout)

    def test_id_null_fails(self) -> None:
        retired = [{"id": None, "retired_at": "2026-01-01", "reason": "deleted"}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("id が null です", result.stdout)

    def test_id_empty_string_fails(self) -> None:
        retired = [{"id": "", "retired_at": "2026-01-01", "reason": "deleted"}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("id は空でない文字列である必要があります", result.stdout)

    def test_id_pattern_invalid_fails(self) -> None:
        retired = [{"id": "not-a-valid-id", "retired_at": "2026-01-01", "reason": "deleted"}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("id がパターンに適合しない", result.stdout)

    def test_retired_at_missing_fails(self) -> None:
        retired = [{"id": "mikami-000001", "reason": "deleted"}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("必須キー 'retired_at' がありません", result.stdout)

    def test_retired_at_null_fails(self) -> None:
        retired = [{"id": "mikami-000001", "retired_at": None, "reason": "deleted"}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("retired_at が null です", result.stdout)

    def test_retired_at_empty_string_fails(self) -> None:
        retired = [{"id": "mikami-000001", "retired_at": "", "reason": "deleted"}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("retired_at は空でない文字列である必要があります", result.stdout)

    def test_reason_missing_fails(self) -> None:
        retired = [{"id": "mikami-000001", "retired_at": "2026-01-01"}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("必須キー 'reason' がありません", result.stdout)

    def test_reason_null_fails(self) -> None:
        retired = [{"id": "mikami-000001", "retired_at": "2026-01-01", "reason": None}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reason が null です", result.stdout)

    def test_reason_empty_string_fails(self) -> None:
        retired = [{"id": "mikami-000001", "retired_at": "2026-01-01", "reason": ""}]
        result = self._run([make_record()], retired=retired)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reason は空でない文字列である必要があります", result.stdout)

    def test_reason_is_free_text_not_restricted_to_fixed_enum(self) -> None:
        # 仕様上「等」があり将来拡張されうるため、reasonは非空stringのみを要求し、
        # merged/split/deleted等の固定enumには限定しない
        retired = [{"id": "mikami-000001", "retired_at": "2026-01-01", "reason": "議会側の様式変更に伴う統合"}]
        result = self._run([make_record()], retired=retired)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_retired_entry_passes(self) -> None:
        retired = [{"id": "mikami-000001", "retired_at": "2026-01-01", "reason": "deleted"}]
        result = self._run([make_record()], retired=retired)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_null_entry_fails_without_traceback(self) -> None:
        # retired_ids.json = [null] は以前 AttributeError で例外終了していた。
        # 検証エラーとして正常に非0終了し、tracebackを出さないことを確認する。
        result = self._run([make_record()], retired_json_text=json.dumps([None]))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("AttributeError", result.stdout)
        self.assertNotIn("AttributeError", result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("[retired_ids]", result.stdout)
        self.assertIn("entryはobjectである必要があります", result.stdout)

    def test_id_as_list_fails_without_traceback(self) -> None:
        # id が list（非string）だと以前 TypeError（unhashable type）で例外終了していた。
        # 検証エラーとして正常に非0終了し、tracebackを出さないことを確認する。
        retired = [{"id": ["mikami-000001"], "retired_at": "2026-09-22", "reason": "deleted"}]
        result = self._run([make_record()], retired_json_text=json.dumps(retired))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("TypeError", result.stdout)
        self.assertNotIn("TypeError", result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("[retired_ids]", result.stdout)
        self.assertIn("id は空でない文字列である必要があります", result.stdout)


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
        self.assertIn("[strict予算提案]", result.stdout)
        self.assertIn("id がありません", result.stdout)

    def test_missing_source_locator_fails(self) -> None:
        record = self._budget_record()
        del record["source_locator"]
        result = self._run([record], strict=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[strict予算提案]", result.stdout)
        self.assertIn("source_locator がありません、または空文字です", result.stdout)

    def test_empty_source_locator_fails(self) -> None:
        result = self._run([self._budget_record(source_locator="")], strict=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[strict予算提案]", result.stdout)
        self.assertIn("source_locator がありません、または空文字です", result.stdout)

    def test_missing_fiscal_year_fails(self) -> None:
        record = self._budget_record()
        del record["fiscal_year"]
        result = self._run([record], strict=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[strict予算提案]", result.stdout)
        self.assertIn("fiscal_year がありません", result.stdout)

    def test_duplicate_source_locator_fails(self) -> None:
        result = self._run(
            [
                self._budget_record(id="mikami-000010", source_locator="2026-01-①"),
                self._budget_record(id="mikami-000011", source_locator="2026-01-①"),
            ],
            strict=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[source_locator重複]", result.stdout)

    def test_duplicate_id_fails(self) -> None:
        result = self._run(
            [
                self._budget_record(id="mikami-000010", source_locator="2026-01-①"),
                self._budget_record(id="mikami-000010", source_locator="2026-01-②"),
            ],
            strict=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[id重複]", result.stdout)

    def test_non_budget_records_are_not_required_to_have_budget_fields(self) -> None:
        # source_type == "予算提案" 以外は strict mode でも対象外（meeting_type等では判定しない）
        result = self._run([make_record(source_type="議事録", meeting_type="本会議")], strict=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RealDataStrictModeTest(unittest.TestCase):
    """現在の実データ（activity_archive.json）に対する意図的な integration test。

    strict mode（--require-budget-v12-fields）が検査するのは check_strict_budget_fields
    が扱う id / source_locator / fiscal_year の3項目のみで、legacy4項目・
    legacy_targets.json の target_id（11B）・date の最終値化（11C）は対象外。

    手順11A（予算提案625件への正式ID付与）が完了し、この3項目が625件すべてで
    満たされたため、現行mainはstrict modeをPASSするのが正常な状態になった。
    11B・11Cはstrict modeの検査対象に含まれないため、このテストの期待値は
    11B・11Cの完了有無に左右されない。将来、この3項目のいずれかを満たさない
    データがmainへ混入した場合にのみ、このテストは再びFAILする。
    """

    def test_current_main_passes_strict_mode(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_PY), "--require-budget-v12-fields"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
