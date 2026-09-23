#!/usr/bin/env python3
"""手順11A: 予算提案625件へ正式ID（mikami-NNNNNN）を付与する。

    python scripts/assign_budget_ids.py          # 付与して書き換える
    python scripts/assign_budget_ids.py --check  # 非破壊確認（CI用）

採番規則の正本:
  private: council-activity-private/v1.2.0/specs/範囲と順序_v1.2.0-v1.3.0.md §2.1

  1. active な正式ID と retired_ids.json の使用済みIDを合わせて確認する
  2. 使用済みIDが存在する場合は、その数値部分の最大値＋1から採番する
  3. active・retiredともに存在しない初回採番時は mikami-000001 から開始する
  4. 欠番（retired分）は再利用しない
  5. 年度・資料順・source_locator・種別等の意味をIDに持たせない
  6. 一度付与したIDは原則変更しない

このスクリプトは source_type == "予算提案" かつ id 未設定のレコードだけを対象にする。
既にidを持つレコードは変更しない。議事録には一切触れない。activity_archive.json の
レコード順序も変更しない。idは既存フィールドの前（schema.json の並びに合わせ先頭）に挿入する。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE_PATH = ROOT / "activity_archive.json"
RETIRED_IDS_PATH = ROOT / "retired_ids.json"

BUDGET_SOURCE_TYPE = "予算提案"
ID_PATTERN = re.compile(r"^mikami-(\d{6})$")
ID_WIDTH = 6


class AssignError(Exception):
    pass


def load_json(path: pathlib.Path):
    if not path.exists():
        raise AssignError(f"{path} が存在しません")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AssignError(f"{path.name} のJSONが不正です: {e}")


def max_used_number(archive: list[dict], retired: list) -> int:
    max_n = 0
    for i, r in enumerate(archive):
        rid = r.get("id")
        if not rid:
            continue
        m = ID_PATTERN.match(rid)
        if not m:
            raise AssignError(f"activity_archive.json {i}件目: 既存id がパターンに適合しない → {rid!r}")
        max_n = max(max_n, int(m.group(1)))

    if not isinstance(retired, list):
        raise AssignError("retired_ids.json はJSON配列である必要があります")
    for i, entry in enumerate(retired):
        if not isinstance(entry, dict):
            raise AssignError(f"retired_ids.json {i}件目: entryはobjectである必要があります")
        rid = entry.get("id")
        if not isinstance(rid, str):
            raise AssignError(f"retired_ids.json {i}件目: id が文字列ではありません → {rid!r}")
        m = ID_PATTERN.match(rid)
        if not m:
            raise AssignError(f"retired_ids.json {i}件目: id がパターンに適合しない → {rid!r}")
        max_n = max(max_n, int(m.group(1)))

    return max_n


def assign(archive: list[dict], next_n: int) -> tuple[int, int]:
    """budget レコードのうち id 未設定のものへ配列順で連番を振る。戻り値は (assigned, skipped_existing)。"""
    assigned = 0
    skipped_existing = 0
    for r in archive:
        if r.get("source_type") != BUDGET_SOURCE_TYPE:
            continue
        if r.get("id"):
            skipped_existing += 1
            continue
        new_id = f"mikami-{next_n:0{ID_WIDTH}d}"
        next_n += 1
        # id を schema.json の並びに合わせ先頭に挿入する（内容フィールドは一切変更しない）。
        reordered = {"id": new_id}
        reordered.update(r)
        r.clear()
        r.update(reordered)
        assigned += 1
    return assigned, skipped_existing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="書き換えず、付与結果が現在のactivity_archive.jsonと一致するか確認する")
    args = parser.parse_args()

    try:
        archive = load_json(ARCHIVE_PATH)
        retired = load_json(RETIRED_IDS_PATH)
    except AssignError as e:
        print(f"NG: {e}")
        return 1

    if not isinstance(archive, list):
        print("NG: activity_archive.json はJSON配列である必要があります")
        return 1

    original_order_locators = [r.get("source_locator") if r.get("source_type") == BUDGET_SOURCE_TYPE else None for r in archive]
    original_count = len(archive)
    original_budget_count = sum(1 for r in archive if r.get("source_type") == BUDGET_SOURCE_TYPE)
    original_minutes_snapshot = json.dumps(
        [r for r in archive if r.get("source_type") != BUDGET_SOURCE_TYPE], ensure_ascii=False, sort_keys=True
    )

    try:
        max_n = max_used_number(archive, retired)
    except AssignError as e:
        print(f"NG: {e}")
        return 1

    working = json.loads(json.dumps(archive))  # deep copy
    assigned, skipped_existing = assign(working, max_n + 1)

    # 不変条件の検証
    if len(working) != original_count:
        print(f"NG: レコード総数が変化した: {original_count} -> {len(working)}")
        return 1

    new_order_locators = [r.get("source_locator") if r.get("source_type") == BUDGET_SOURCE_TYPE else None for r in working]
    if new_order_locators != original_order_locators:
        print("NG: レコード順序（source_locatorの並び）が変化した")
        return 1

    new_budget_count = sum(1 for r in working if r.get("source_type") == BUDGET_SOURCE_TYPE)
    if new_budget_count != original_budget_count:
        print(f"NG: 予算提案の件数が変化した: {original_budget_count} -> {new_budget_count}")
        return 1

    new_minutes_snapshot = json.dumps(
        [r for r in working if r.get("source_type") != BUDGET_SOURCE_TYPE], ensure_ascii=False, sort_keys=True
    )
    if new_minutes_snapshot != original_minutes_snapshot:
        print("NG: 予算提案以外（議事録等）のレコードが変化した")
        return 1

    budget_records = [r for r in working if r.get("source_type") == BUDGET_SOURCE_TYPE]
    ids = [r.get("id") for r in budget_records]
    if any(not rid for rid in ids):
        print(f"NG: id未付与の予算提案が残っている: {sum(1 for rid in ids if not rid)}件")
        return 1
    if len(set(ids)) != len(ids):
        print("NG: 予算提案idに重複がある")
        return 1
    retired_ids = {e["id"] for e in retired if isinstance(e, dict) and isinstance(e.get("id"), str)}
    collisions = set(ids) & retired_ids
    if collisions:
        print(f"NG: retired_idsと衝突するidがある → {sorted(collisions)}")
        return 1

    locators = [r.get("source_locator") for r in budget_records]
    if len(set(locators)) != len(locators) or any(not loc for loc in locators):
        print("NG: source_locatorに欠落または重複がある")
        return 1

    new_text = json.dumps(working, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        current_text = ARCHIVE_PATH.read_text(encoding="utf-8") if ARCHIVE_PATH.exists() else None
        if current_text != new_text:
            print("NG: activity_archive.json はid付与結果と一致しません")
            return 1
        print(
            f"OK: activity_archive.json はid付与結果と一致"
            f"（budget={len(budget_records)}, assigned={assigned}, already_had_id={skipped_existing}）"
        )
        return 0

    ARCHIVE_PATH.write_text(new_text, encoding="utf-8")
    print(
        f"付与しました: budget={len(budget_records)}, assigned={assigned}, "
        f"already_had_id={skipped_existing}, id範囲=mikami-{max_n + 1:0{ID_WIDTH}d}〜mikami-{max_n + assigned:0{ID_WIDTH}d}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
