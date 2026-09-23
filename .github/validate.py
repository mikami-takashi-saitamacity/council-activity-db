#!/usr/bin/env python3
"""activity_archive.json を schema.json とつき合わせて検証する（CI から実行）。

手元で1回検証しただけだと、定例会ごとの追記で型が崩れたときに気づけない。
push のたびに走らせて、壊れたら止める。

    python .github/validate.py

★検査した件数と項目数（カナリア）を必ず表示する。0件なら検査そのものが
  空振りしているので、「エラー0件」を信用してはいけない。

## strict budget mode（v1.2.0 手順11A完了後に必須化する）

会派予算提案（source_type == "予算提案"）は、仕様上いずれ id / source_locator /
fiscal_year を必須とする。ただし手順11A（予算提案625件へのID付与。source_locator・
fiscal_yearは手順10で既に付与済み）が終わるまでは、既存データがこの条件を満たさない。
そのため通常モードではこの3項目を必須にせず、明示的なフラグでのみ検査する。

    python .github/validate.py --require-budget-v12-fields

手順11Aが完了した現在のmainでは、このフラグを付けてもPASSするのが正常。
このフラグをworkflow側の必須チェックに追加するかどうかは別途判断する
（本チェックの検査範囲は id / source_locator / fiscal_year の3項目のみで、
手順11B・11C〔legacy URL解決のID参照切替・date最終値化〕は対象外）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

from jsonschema import Draft7Validator, FormatChecker

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "activity_archive.json"
SCHEMA = ROOT / "schema.json"
RETIRED_IDS = ROOT / "retired_ids.json"

ID_PATTERN = re.compile(r"^mikami-[0-9]{6}$")
BUDGET_SOURCE_TYPE = "予算提案"
RETIRED_ENTRY_REQUIRED_KEYS = ("id", "retired_at", "reason")


def check_schema(data: list[dict], schema: dict, errors: list[str]) -> None:
    v = Draft7Validator(schema, format_checker=FormatChecker())
    for e in sorted(v.iter_errors(data), key=lambda e: list(e.path)):
        where = ".".join(str(x) for x in e.path) or "(全体)"
        errors.append(f"[スキーマ] {where}: {e.message}")


def check_dates(data: list[dict], errors: list[str]) -> None:
    # format:date を通っても 2026-02-30 のような暦として不正な日付は防げない環境がある
    for i, r in enumerate(data):
        try:
            datetime.date.fromisoformat(r.get("date", ""))
        except ValueError:
            errors.append(f"[日付] {i}件目: date が暦として不正 → {r.get('date')!r}")


def check_legacy_duplicate_warning(data: list[dict], warnings: list[str]) -> None:
    # (date, question_topic) は v1.2.0 以降の恒久的な一意キーではない（正本の一意性は
    # id / 予算提案の source_locator で見る方針に変更）。予算提案は年度ごとの仮日付
    # （各年1月1日）を使っているため、今後の正当な同年度・同テーマの提案を誤って
    # 弾く可能性がある。CIを止めるほどの根拠ではないので、ブロックしない警告に留める。
    seen: dict[tuple[str, str], int] = {}
    for i, r in enumerate(data):
        k = (r.get("date", ""), r.get("question_topic", ""))
        if k in seen:
            warnings.append(f"[参考/重複疑い] {i}件目と{seen[k]}件目が同じ (date, question_topic) → {k}")
        seen[k] = i


def check_active_ids(data: list[dict], errors: list[str]) -> list[str]:
    ids: list[str] = []
    seen: dict[str, int] = {}
    for i, r in enumerate(data):
        rid = r.get("id")
        if not rid:
            continue
        if not ID_PATTERN.match(rid):
            errors.append(f"[id] {i}件目: id がパターンに適合しない → {rid!r}")
            continue
        if rid in seen:
            errors.append(f"[id重複] {i}件目と{seen[rid]}件目が同じ id → {rid!r}")
            continue
        seen[rid] = i
        ids.append(rid)
    return ids


def load_retired_ids(errors: list[str], retired_ids_path: pathlib.Path = RETIRED_IDS) -> list[dict]:
    # retired_ids.json は今後必須ファイル（使用済みIDを再利用しないための正本）。
    # 存在しない・配列でない・エントリが必須項目を満たさない場合はFAILする。
    if not retired_ids_path.exists():
        errors.append(f"[retired_ids] {retired_ids_path} が存在しません（retired_ids.json は必須ファイルです）")
        return []

    try:
        retired = json.loads(retired_ids_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"[retired_ids] {retired_ids_path.name} のJSONが不正です: {e}")
        return []

    if not isinstance(retired, list):
        errors.append(f"[retired_ids] {retired_ids_path.name} はJSON配列である必要があります")
        return []

    for i, entry in enumerate(retired):
        if not isinstance(entry, dict):
            errors.append(f"[retired_ids] {i}件目: entryはobjectである必要があります")
            continue

        for key in RETIRED_ENTRY_REQUIRED_KEYS:
            if key not in entry:
                errors.append(f"[retired_ids] {i}件目: 必須キー {key!r} がありません")
                continue
            value = entry[key]
            if value is None:
                errors.append(f"[retired_ids] {i}件目: {key} が null です（非空文字列が必要）")
                continue
            if not isinstance(value, str) or value == "":
                errors.append(f"[retired_ids] {i}件目: {key} は空でない文字列である必要があります → {value!r}")

        rid = entry.get("id")
        if isinstance(rid, str) and rid and not ID_PATTERN.match(rid):
            errors.append(f"[retired_ids] {i}件目: id がパターンに適合しない → {rid!r}")

    return retired


def check_retired_ids(retired: list, active_ids: list[str], errors: list[str]) -> None:
    # entryの型異常（object以外、idがstring以外等）は load_retired_ids が既にエラー
    # として報告済み。ここでは重複検査に安全に使える（object かつ id が非空string）
    # entryだけを対象にする。不正entryをここで例外にせず、検査対象から静かに外す。
    seen: dict[str, int] = {}
    for i, entry in enumerate(retired):
        if not isinstance(entry, dict):
            continue
        rid = entry.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        if rid in seen:
            errors.append(f"[retired_ids重複] {i}件目と{seen[rid]}件目が同じ id → {rid!r}")
            continue
        seen[rid] = i

    overlap = set(active_ids) & set(seen)
    for rid in sorted(overlap):
        errors.append(f"[active-retired重複] id {rid!r} が activity_archive.json と retired_ids.json の両方にあります")


def check_source_locator(data: list[dict], errors: list[str]) -> None:
    # 全予算提案への必須化は strict mode のみ。ここでは「存在する分」だけを検査する。
    # 「丸数字2桁」を含む実体形式がまだ一意に確定していないため、正規表現は今回追加しない。
    seen: dict[str, int] = {}
    for i, r in enumerate(data):
        if r.get("source_type") != BUDGET_SOURCE_TYPE:
            continue
        loc = r.get("source_locator")
        if loc is None:
            continue
        if loc == "":
            errors.append(f"[source_locator] {i}件目: source_locator が空文字です")
            continue
        if loc in seen:
            errors.append(f"[source_locator重複] {i}件目と{seen[loc]}件目が同じ source_locator → {loc!r}")
            continue
        seen[loc] = i


def check_strict_budget_fields(data: list[dict], errors: list[str]) -> None:
    """v1.2.0 の最終仕様：予算提案は id / source_locator / fiscal_year を必須とする。

    判定は必ず record["source_type"] == "予算提案" で行う。meeting_type や
    session_name では判定しない（本会議名義の予算提案が316件あるため）。
    """
    for i, r in enumerate(data):
        if r.get("source_type") != BUDGET_SOURCE_TYPE:
            continue
        if not r.get("id"):
            errors.append(f"[strict予算提案] {i}件目: id がありません（予算提案には必須）")
        loc = r.get("source_locator")
        if not loc:
            errors.append(f"[strict予算提案] {i}件目: source_locator がありません、または空文字です（予算提案には必須）")
        if r.get("fiscal_year") is None:
            errors.append(f"[strict予算提案] {i}件目: fiscal_year がありません（予算提案には必須）")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--require-budget-v12-fields",
        action="store_true",
        help="strict mode: 予算提案全件に id / source_locator / fiscal_year を必須化する（v1.2.0手順11A完了後はPASSする）",
    )
    parser.add_argument("--data", type=pathlib.Path, default=DATA, help="テスト用: activity_archive.json の差し替え")
    parser.add_argument("--schema", type=pathlib.Path, default=SCHEMA, help="テスト用: schema.json の差し替え")
    parser.add_argument("--retired-ids", type=pathlib.Path, default=RETIRED_IDS, help="テスト用: retired_ids.json の差し替え")
    args = parser.parse_args()

    data = json.loads(args.data.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    check_schema(data, schema, errors)
    check_dates(data, errors)
    check_legacy_duplicate_warning(data, warnings)
    active_ids = check_active_ids(data, errors)
    retired = load_retired_ids(errors, args.retired_ids)
    check_retired_ids(retired, active_ids, errors)
    check_source_locator(data, errors)

    if args.require_budget_v12_fields:
        check_strict_budget_fields(data, errors)

    n_fields = len(schema["items"]["properties"])
    print(f"検査: {len(data)}件 × {n_fields}項目 / スキーマ {args.schema.name}")
    print(f"active id: {len(active_ids)}件 / retired id: {len(retired)}件")
    filled = {k: sum(1 for r in data if r.get(k) not in ("", [], None))
              for k in schema["items"]["properties"]}
    thin = {k: n for k, n in filled.items() if n < len(data)}
    if thin:
        print("参考（中身がある件数。空欄はエラーにしない）:")
        for k, n in sorted(thin.items(), key=lambda x: x[1]):
            print(f"  {k:<16} {n:4d}/{len(data)}  ({n / len(data) * 100:4.1f}%)")

    if warnings:
        print(f"\n参考: 警告 {len(warnings)}件（CIは止めない）")
        for w in warnings[:20]:
            print("  " + w)
        if len(warnings) > 20:
            print(f"  ...ほか{len(warnings) - 20}件")

    if errors:
        print(f"\n★エラー {len(errors)}件")
        for e in errors[:50]:
            print("  " + e)
        return 1
    print("\nエラーなし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
