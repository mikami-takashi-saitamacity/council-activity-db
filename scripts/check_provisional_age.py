#!/usr/bin/env python3
"""手順13E-1: source_status=provisional の5か月滞留警告。

    python scripts/check_provisional_age.py                       # 実行日を基準に警告一覧を表示
    python scripts/check_provisional_age.py --as-of 2026-09-24     # 基準日を固定して表示（テスト・再現用）

正本: council-activity-private/v1.2.0/specs/仕様メモ_source_status.md §4・§6。
「開催日から5か月を過ぎても source_status=provisional のものは警告一覧化。
CIエラーにはしない。正式版公開有無は人が確認する」を実装する。

対象は source_status == "provisional" のレコードのみ。開催日（date）に暦月で
5か月を加えた日を期限とし、基準日（as_of）が期限を過ぎている（期限当日は含まない）
場合だけ警告する。150日等の固定日数ではなく、暦月で計算する（dateutil等は使わない）。

このスクリプトは以下を一切行わない:
  - ssp.kaigiroku.net への自動アクセス
  - 正式会議録が公開されたかどうかの自動判定
  - provisional から official への自動変更
  - source_url の自動取得
  - activity_archive.json の書き換え（読み取り専用）

exit code の意味を区別する:
  - 滞留対象が1件以上あっても、それは正常な警告結果であり exit 0（CIを失敗させない）
  - JSONが読めない・想定形式でない・provisionalレコードのdateが不正、等の
    スクリプト自体が判定できない異常時だけ非0で終了する
"""
from __future__ import annotations

import argparse
import calendar
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE_PATH = ROOT / "activity_archive.json"

MONTHS_THRESHOLD = 5
PROVISIONAL = "provisional"


class CheckProvisionalAgeError(Exception):
    pass


def add_months(d: datetime.date, months: int) -> datetime.date:
    """dに暦月でmonths分を加算する。対象月に元の日が無ければその月の末日に丸める。"""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def parse_date(value, context: str) -> datetime.date:
    if not isinstance(value, str) or not value:
        raise CheckProvisionalAgeError(f"{context}: date が空/不正です: {value!r}")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as e:
        raise CheckProvisionalAgeError(f"{context}: date が YYYY-MM-DD 形式ではありません: {value!r}") from e


def find_overdue(records: list[dict], as_of: datetime.date) -> list[dict]:
    overdue = []
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            raise CheckProvisionalAgeError(f"{i}件目がJSON objectではありません")
        if r.get("source_status") != PROVISIONAL:
            continue
        deadline = add_months(parse_date(r.get("date"), f"{i}件目"), MONTHS_THRESHOLD)
        if as_of > deadline:
            overdue.append({
                "index": i,
                "id": r.get("id"),
                "date": r.get("date"),
                "deadline": deadline.isoformat(),
                "question_topic": r.get("question_topic"),
            })
    return overdue


def load(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        raise CheckProvisionalAgeError(f"{path} が存在しません")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CheckProvisionalAgeError(f"{path.name} のJSONが不正です: {e}") from e
    if not isinstance(data, list):
        raise CheckProvisionalAgeError(f"{path.name} はJSON配列である必要があります")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as-of", type=str, default=None, help="基準日(YYYY-MM-DD)。省略時は実行日")
    parser.add_argument("--data", type=pathlib.Path, default=ARCHIVE_PATH, help="テスト用: activity_archive.json の差し替え")
    args = parser.parse_args()

    if args.as_of is not None:
        try:
            as_of = datetime.date.fromisoformat(args.as_of)
        except ValueError:
            print(f"NG: --as-of の形式が不正です（YYYY-MM-DD） → {args.as_of!r}")
            return 1
    else:
        as_of = datetime.date.today()

    try:
        records = load(args.data)
        overdue = find_overdue(records, as_of)
    except CheckProvisionalAgeError as e:
        print(f"NG: {e}")
        return 1

    provisional_count = sum(1 for r in records if isinstance(r, dict) and r.get("source_status") == PROVISIONAL)
    print(f"確認基準日: {as_of.isoformat()} / provisional: {provisional_count}件 / 5か月滞留: {len(overdue)}件")

    for o in overdue:
        print("WARNING provisional overdue:")
        print(f"  index={o['index']}")
        print(f"  id={o['id']}")
        print(f"  date={o['date']}")
        print(f"  deadline={o['deadline']}")
        print(f"  question_topic={o['question_topic']}")

    # 滞留warningは正常な検知結果。CIを失敗させないため常にexit 0で終える
    # （データ/実装異常はここに到達する前に return 1 済み）。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
