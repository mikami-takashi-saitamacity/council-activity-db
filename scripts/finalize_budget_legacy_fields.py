#!/usr/bin/env python3
"""手順11C: legacy互換のため保留していた予算提案フィールドを最終値へ更新する。

    python scripts/finalize_budget_legacy_fields.py          # 反映して書き換える
    python scripts/finalize_budget_legacy_fields.py --check  # 非破壊確認（CI用）

対象は source_type == "予算提案" の625件のみ。議事録342件には一切触れない。

更新するフィールドと出典:
  date:
    正本: budget_step10_spec.md §4 の年度別提出日表（SUBMISSION_DATE）。
    legacy_inherit=true（324件）は旧URL照合4項目維持のため、これまで仮日付
    `{fiscal_year}-01-01` のまま保留していた。新規301件は手順10反映時に既に
    この表で設定済みなので、通常は差分が出ない。
  question_topic:
    正本: private repo budget_step10_decisions.json の final_question_topic。
    こちらも旧URL照合4項目のため、legacy_inherit=true分は手順10反映時に
    あえて適用せず旧値のまま保留していた。

このスクリプトは、各budgetレコードについて現在値と最終値を比較し、差分がある
フィールドだけを更新する（既に最終値と一致しているレコードは触れない）。
id / source_locator / fiscal_year / source_type / session_name / meeting_type /
tags / result_level 等、対象外フィールドは一切変更しない。レコード順序も
変更しない。
"""
from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE_PATH = ROOT / "activity_archive.json"
DEFAULT_DECISIONS = ROOT.parent / "council-activity-private" / "v1.2.0" / "step10" / "budget_step10_decisions.json"

BUDGET_SOURCE_TYPE = "予算提案"

# fiscal_year -> 提出日（budget_step10_spec.md §4）。reflect_budget_step10.py と同じ表。
SUBMISSION_DATE = {
    2021: "2020-09-30",
    2022: "2021-09-29",
    2023: "2022-09-12",
    2024: "2023-09-08",
    2025: "2024-09-06",
    2026: "2025-09-03",
}


class FinalizeError(Exception):
    pass


def load(path: pathlib.Path):
    if not path.exists():
        raise FinalizeError(f"{path} が存在しません")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise FinalizeError(f"{path.name} のJSONが不正です: {e}")


def build_decision_index(decisions_doc: dict) -> dict[str, dict]:
    decisions = decisions_doc.get("decisions")
    if not isinstance(decisions, list):
        raise FinalizeError("budget_step10_decisions.json の decisions が配列ではありません")
    by_loc: dict[str, dict] = {}
    for i, d in enumerate(decisions):
        loc = d.get("source_locator")
        if not loc:
            raise FinalizeError(f"decisions[{i}]: source_locator がありません")
        if loc in by_loc:
            raise FinalizeError(f"decisions内でsource_locatorが重複: {loc!r}")
        by_loc[loc] = d
    return by_loc


def finalize(archive: list[dict], decisions_by_loc: dict[str, dict]) -> tuple[int, int, list[str]]:
    """budgetレコードのdate/question_topicを最終値へ更新する。

    戻り値は (date変更件数, question_topic変更件数, 警告リスト)。
    """
    date_changed = 0
    topic_changed = 0
    warnings: list[str] = []

    for i, r in enumerate(archive):
        if r.get("source_type") != BUDGET_SOURCE_TYPE:
            continue

        loc = r.get("source_locator")
        dec = decisions_by_loc.get(loc)
        if dec is None:
            raise FinalizeError(f"activity_archive.json {i}件目 (source_locator={loc!r}): 対応するdecisionが見つからない")
        if dec.get("review_status") != "confirmed":
            raise FinalizeError(f"source_locator={loc!r}: review_statusがconfirmedではない（{dec.get('review_status')!r}）")

        fy = r.get("fiscal_year")
        expected_date = SUBMISSION_DATE.get(fy)
        if expected_date is None:
            raise FinalizeError(f"source_locator={loc!r}: fiscal_year={fy!r} に対応する提出日が定義されていない")
        if r.get("date") != expected_date:
            r["date"] = expected_date
            date_changed += 1

        final_topic = dec.get("final_question_topic")
        if not final_topic:
            raise FinalizeError(f"source_locator={loc!r}: final_question_topic が空/未設定")
        if r.get("question_topic") != final_topic:
            r["question_topic"] = final_topic
            topic_changed += 1

    return date_changed, topic_changed, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--decisions", type=pathlib.Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--check", action="store_true", help="書き換えず、最終値と現在のactivity_archive.jsonが一致するか確認する")
    args = parser.parse_args()

    try:
        decisions_doc = load(args.decisions)
        archive = load(ARCHIVE_PATH)
    except FinalizeError as e:
        print(f"NG: {e}")
        return 1

    if not isinstance(archive, list):
        print("NG: activity_archive.json はJSON配列である必要があります")
        return 1

    try:
        decisions_by_loc = build_decision_index(decisions_doc)
    except FinalizeError as e:
        print(f"NG: {e}")
        return 1

    original_order_key = [(r.get("source_type"), r.get("id"), r.get("source_locator")) for r in archive]
    original_count = len(archive)
    non_budget_snapshot = json.dumps(
        [r for r in archive if r.get("source_type") != BUDGET_SOURCE_TYPE], ensure_ascii=False, sort_keys=True
    )

    working = json.loads(json.dumps(archive))  # deep copy

    try:
        date_changed, topic_changed, warnings = finalize(working, decisions_by_loc)
    except FinalizeError as e:
        print(f"NG: {e}")
        return 1

    # 不変条件の検証
    if len(working) != original_count:
        print(f"NG: レコード総数が変化した: {original_count} -> {len(working)}")
        return 1

    new_order_key = [(r.get("source_type"), r.get("id"), r.get("source_locator")) for r in working]
    if new_order_key != original_order_key:
        print("NG: レコード順序が変化した")
        return 1

    new_non_budget_snapshot = json.dumps(
        [r for r in working if r.get("source_type") != BUDGET_SOURCE_TYPE], ensure_ascii=False, sort_keys=True
    )
    if new_non_budget_snapshot != non_budget_snapshot:
        print("NG: 予算提案以外（議事録等）のレコードが変化した")
        return 1

    # date/question_topic 以外のフィールドが変化していないことを確認する
    for before, after in zip(archive, working):
        if before.get("source_type") != BUDGET_SOURCE_TYPE:
            continue
        b2 = dict(before)
        a2 = dict(after)
        b2.pop("date", None)
        b2.pop("question_topic", None)
        a2.pop("date", None)
        a2.pop("question_topic", None)
        if b2 != a2:
            print(f"NG: date/question_topic以外のフィールドが変化した（source_locator={before.get('source_locator')!r}）")
            return 1

    for w in warnings:
        print("警告:", w)

    new_text = json.dumps(working, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        current_text = ARCHIVE_PATH.read_text(encoding="utf-8") if ARCHIVE_PATH.exists() else None
        if current_text != new_text:
            print("NG: activity_archive.json は最終値反映結果と一致しません")
            return 1
        print(f"OK: activity_archive.json は最終値反映結果と一致（date変更={date_changed}, question_topic変更={topic_changed}）")
        return 0

    ARCHIVE_PATH.write_text(new_text, encoding="utf-8")
    print(f"反映しました: date変更={date_changed}, question_topic変更={topic_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
