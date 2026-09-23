#!/usr/bin/env python3
"""手順13(13A): 予算提案625件の source_url を年度別定数表から機械設定する。

    python scripts/finalize_budget_source_urls.py          # 反映して書き換える
    python scripts/finalize_budget_source_urls.py --check  # 非破壊確認（CI用）

正本: council-activity-private/v1.2.0/specs/budget_step10_spec.md §4・§5。
「625件へ人手入力せず、source_locator 先頭4桁の年度から定数表で機械設定する」
という確定仕様をここで実装する。年度別URLの値は scripts/budget_source_urls.py
の SOURCE_URL を単一の正本として使う（このスクリプトへ複製しない）。

対象は source_type == "予算提案" の625件のみ。議事録342件、および予算提案の
source_url 以外のフィールドには一切触れない。レコード順序も変更しない。

reflect_budget_step10.py は、このスクリプトと責務が重複しないよう、意図的に
source_url を対象外としている（同スクリプトのdocstring参照）。このスクリプトは
その分担を引き継ぎ、fiscal_year を唯一のキーとして source_url を恒久的に
検証・機械設定する。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# importlibでこのファイルを直接loadするテストからも sibling module を解決できるよう、
# 自分のディレクトリを明示的にsys.pathへ追加してからimportする。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from budget_source_urls import SOURCE_URL  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE_PATH = ROOT / "activity_archive.json"

BUDGET_SOURCE_TYPE = "予算提案"


class FinalizeSourceUrlError(Exception):
    pass


def load(path: pathlib.Path):
    if not path.exists():
        raise FinalizeSourceUrlError(f"{path} が存在しません")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise FinalizeSourceUrlError(f"{path.name} のJSONが不正です: {e}") from e


def finalize(archive: list[dict]) -> tuple[int, int, dict[int, int]]:
    """budgetレコードの source_url を年度別定数表の値へ揃える。

    戻り値は (変更件数, 対象件数, 年度別対象件数)。同じ値であれば書き換えない
    （何度実行しても結果が変わらない、冪等な実装）。
    """
    changed = 0
    total_budget = 0
    per_fy: dict[int, int] = {}

    for i, r in enumerate(archive):
        if r.get("source_type") != BUDGET_SOURCE_TYPE:
            continue
        total_budget += 1

        fy = r.get("fiscal_year")
        expected = SOURCE_URL.get(fy)
        if expected is None:
            raise FinalizeSourceUrlError(
                f"activity_archive.json {i}件目 (source_locator={r.get('source_locator')!r}): "
                f"fiscal_year={fy!r} に対応する SOURCE_URL が定義されていない"
            )

        per_fy[fy] = per_fy.get(fy, 0) + 1
        if r.get("source_url") != expected:
            r["source_url"] = expected
            changed += 1

    return changed, total_budget, per_fy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="書き換えず、年度別定数表と現在のactivity_archive.jsonが一致するか確認する")
    parser.add_argument("--data", type=pathlib.Path, default=ARCHIVE_PATH, help="テスト用: activity_archive.json の差し替え")
    args = parser.parse_args()

    try:
        archive = load(args.data)
    except FinalizeSourceUrlError as e:
        print(f"NG: {e}")
        return 1

    if not isinstance(archive, list):
        print("NG: activity_archive.json はJSON配列である必要があります")
        return 1

    original_total = len(archive)
    original_non_budget = [r for r in archive if r.get("source_type") != BUDGET_SOURCE_TYPE]

    working = json.loads(json.dumps(archive))  # deep copy
    try:
        changed, total_budget, per_fy = finalize(working)
    except FinalizeSourceUrlError as e:
        print(f"NG: {e}")
        return 1

    if len(working) != original_total:
        print(f"NG: レコード総数が変化した: {original_total} -> {len(working)}")
        return 1

    working_non_budget = [r for r in working if r.get("source_type") != BUDGET_SOURCE_TYPE]
    if working_non_budget != original_non_budget:
        print("NG: 予算提案以外（議事録等）のレコードが変化した")
        return 1

    if total_budget != sum(per_fy.values()):
        # per_fy の合計と対象件数は常に一致するはずの内部整合性チェック
        print("NG: 内部集計不整合")
        return 1

    new_text = json.dumps(working, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        current_text = args.data.read_text(encoding="utf-8") if args.data.exists() else None
        if current_text != new_text:
            print("NG: activity_archive.json の予算提案 source_url が年度別定数表と一致しません")
            print(f"     (一致していれば changed=0 のはずが、書き換えありと判定: 対象{total_budget}件中{changed}件差分)")
            return 1
        print(f"OK: 予算提案{total_budget}件すべての source_url が年度別定数表と一致（年度別内訳: {dict(sorted(per_fy.items()))}）")
        return 0

    args.data.write_text(new_text, encoding="utf-8")
    print(f"反映しました: 予算提案{total_budget}件中{changed}件のsource_urlを更新（年度別内訳: {dict(sorted(per_fy.items()))}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
