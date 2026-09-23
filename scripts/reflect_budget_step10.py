#!/usr/bin/env python3
"""手順10で確定した private repo の人手判定を activity_archive.json へ反映する。

    python scripts/reflect_budget_step10.py          # 反映して書き換える
    python scripts/reflect_budget_step10.py --check  # 非破壊確認（CI用）

正本:
  private: ../council-activity-private/v1.2.0/step10/budget_step10_decisions.json
  public : budget_master.json, budget_existing_mapping.json, schema.json（本repo）

legacy_inherit=true（324件）: budget_existing_mapping.json の archive_index が指す
既存レコードを、その場で更新する。legacy4項目（date / question_topic /
source_type / session_name）と committee / source_status / follow_up は
変更しない。final_question_topic は11Cまで反映しない（question_topicは
旧URL照合4項目の一つのため）。

legacy_inherit=false（301件）: 新規レコードとして末尾に追加する。date /
session_name / source_url は budget_step10_spec.md §4 の年度別定数表から
機械設定する。

source_url は本反映の対象外とする（budget_step10_spec.md §5は全625件への
機械設定を挙げているが、範囲と順序_v1.2.0-v1.3.0.md 手順13の「source_url
9件修復」で別途扱う既存の計画と重複するため、このスクリプトでは touch しない）。
"""
from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE_PATH = ROOT / "activity_archive.json"
MASTER_PATH = ROOT / "budget_master.json"
MAPPING_PATH = ROOT / "budget_existing_mapping.json"
SCHEMA_PATH = ROOT / "schema.json"
DEFAULT_DECISIONS = ROOT.parent / "council-activity-private" / "v1.2.0" / "step10" / "budget_step10_decisions.json"

BUDGET_SOURCE_TYPE = "予算提案"
MEETING_TYPE = "予算提案"

# fiscal_year -> 提出日（budget_step10_spec.md §4）。source_urlはこのスクリプトでは
# 設定しない（上記docstring参照）。
SUBMISSION_DATE = {
    2021: "2020-09-30",
    2022: "2021-09-29",
    2023: "2022-09-12",
    2024: "2023-09-08",
    2025: "2024-09-06",
    2026: "2025-09-03",
}

FINAL_TO_PUBLIC = {
    "final_issue": "issue",
    "final_summary": "summary",
    "final_answer_summary": "answer_summary",
    "final_result_level": "result_level",
    "final_tags": "tags",
}


class ReflectError(Exception):
    pass


def load(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ReflectError(f"{path}: {e}") from e


def validate_inputs(decisions_doc, master, mapping, schema, archive):
    errors = []
    rows = decisions_doc.get("decisions")
    if not isinstance(rows, list) or len(rows) != 625:
        errors.append(f"decisions must be an array of 625 items, got {len(rows) if isinstance(rows, list) else type(rows)}")
        return errors

    master_locs = [m["source_locator"] for m in master]
    if len(master_locs) != 625 or len(set(master_locs)) != 625:
        errors.append("budget_master must contain 625 unique source_locators")

    by_loc = {}
    for r in rows:
        loc = r.get("source_locator")
        if loc in by_loc:
            errors.append(f"duplicate decision source_locator: {loc}")
        by_loc[loc] = r
    if set(by_loc) != set(master_locs):
        errors.append("decision locator set does not match budget_master")

    for r in rows:
        if r.get("review_status") != "confirmed":
            errors.append(f"{r.get('source_locator')}: review_status is not confirmed")
        for k in ("final_question_topic", "final_issue", "final_summary",
                   "final_answer_summary", "final_result_level", "final_tags"):
            if r.get(k) in (None, "", []):
                errors.append(f"{r.get('source_locator')}: missing {k}")

    result_enum = set(schema["items"]["properties"]["result_level"]["enum"])
    tag_enum = set(schema["items"]["properties"]["tags"]["items"]["enum"])
    for r in rows:
        rl = r.get("final_result_level")
        if rl is not None and rl not in result_enum:
            errors.append(f"{r.get('source_locator')}: final_result_level not in schema enum: {rl!r}")
        for tag in r.get("final_tags") or []:
            if tag not in tag_enum:
                errors.append(f"{r.get('source_locator')}: final_tags value not in schema enum: {tag!r}")

    # legacy group check: each legacy_archive_index group has exactly one true
    grouped: dict[int, list] = {}
    for r in rows:
        idx = r.get("legacy_archive_index")
        if idx is not None:
            grouped.setdefault(idx, []).append(r)
    for idx, children in grouped.items():
        true_count = sum(1 for c in children if c.get("legacy_inherit") is True)
        if true_count != 1:
            errors.append(f"legacy_archive_index {idx}: expected exactly 1 legacy_inherit=true, got {true_count}")
        if idx < 0 or idx >= len(archive):
            errors.append(f"legacy_archive_index {idx}: out of range for activity_archive.json")
        elif archive[idx].get("source_type") != BUDGET_SOURCE_TYPE:
            errors.append(f"legacy_archive_index {idx}: archive record is not 予算提案")

    for r in rows:
        if r.get("legacy_inherit") not in (True, False):
            errors.append(f"{r.get('source_locator')}: legacy_inherit is not true/false (null or missing)")

    return errors


def reflect(decisions_doc, master, archive):
    """archiveをin-placeで書き換える。戻り値は (updated_count, appended_count)。"""
    master_by_loc = {m["source_locator"]: m for m in master}
    rows = decisions_doc["decisions"]

    updated = 0
    appended = 0
    skipped_existing_append = 0
    new_records = []

    # 既にsource_locatorを持つ予算提案レコードの集合。再実行時に追加を重複させない
    # ための冪等性ガード（1回目のupdateループでarchive[idx]へsource_locatorが
    # 入るため、このsnapshotはupdateループの前に取る＝更新対象はここに含めない）。
    already_present_locators = {
        r.get("source_locator")
        for r in archive
        if r.get("source_type") == BUDGET_SOURCE_TYPE and r.get("source_locator")
    }

    for r in rows:
        loc = r["source_locator"]
        m = master_by_loc[loc]
        fiscal_year = m["fiscal_year"]
        proposal_text = m["proposal_text"]

        if r["legacy_inherit"] is True:
            idx = r["legacy_archive_index"]
            old = archive[idx]
            new = dict(old)
            for final_key, pub_key in FINAL_TO_PUBLIC.items():
                new[pub_key] = r[final_key]
            new["proposal"] = proposal_text
            new["meeting_type"] = MEETING_TYPE
            new["source_locator"] = loc
            new["fiscal_year"] = fiscal_year
            archive[idx] = new
            updated += 1
        else:
            if loc in already_present_locators:
                # 既に反映済み（再実行）。同一source_locatorの予算提案が既に
                # 存在するので、末尾追加は行わない。
                skipped_existing_append += 1
                continue
            new = {
                "date": SUBMISSION_DATE[fiscal_year],
                "meeting_type": MEETING_TYPE,
                "committee": "",
                "source_type": BUDGET_SOURCE_TYPE,
                "source_status": "official",
                "session_name": f"{fiscal_year}年度予算提案",
                "question_topic": r["final_question_topic"],
                "issue": r["final_issue"],
                "proposal": proposal_text,
                "summary": r["final_summary"],
                "tags": r["final_tags"],
                "answer_summary": r["final_answer_summary"],
                "result_level": r["final_result_level"],
                "follow_up": "",
                "source_url": "",
                "source_locator": loc,
                "fiscal_year": fiscal_year,
            }
            new_records.append((loc, new))
            appended += 1

    # 追加301件はsource_locator順（= master順）で末尾へ。
    for _, new in sorted(new_records, key=lambda t: t[0]):
        archive.append(new)

    if skipped_existing_append:
        print(f"(情報) 既に反映済みのため追加をスキップ: {skipped_existing_append}件")

    return updated, appended


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--decisions", type=pathlib.Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--check", action="store_true", help="書き換えず、反映結果が現在のactivity_archive.jsonと一致するか確認する")
    args = parser.parse_args()

    try:
        decisions_doc = load(args.decisions)
        master = load(MASTER_PATH)
        mapping = load(MAPPING_PATH)
        schema = load(SCHEMA_PATH)
        archive = load(ARCHIVE_PATH)
    except ReflectError as e:
        print(f"NG: {e}")
        return 1

    original_meeting_count = sum(1 for r in archive if r.get("source_type") != BUDGET_SOURCE_TYPE)

    errors = validate_inputs(decisions_doc, master, mapping, schema, archive)
    if errors:
        print(f"NG: {len(errors)} input error(s)")
        for e in errors[:100]:
            print("  " + e)
        return 1

    working = json.loads(json.dumps(archive))  # deep copy
    updated, appended = reflect(decisions_doc, master, working)

    if len(working) != original_meeting_count + 625:
        print(f"NG: unexpected total after reflect: {len(working)} (expected {original_meeting_count + 625})")
        return 1

    new_text = json.dumps(working, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        current_text = ARCHIVE_PATH.read_text(encoding="utf-8") if ARCHIVE_PATH.exists() else None
        if current_text != new_text:
            print("NG: activity_archive.json は手順10反映結果と一致しません")
            return 1
        print(f"OK: activity_archive.json は手順10反映結果と一致（updated={updated}, appended={appended}, total={len(working)}）")
        return 0

    ARCHIVE_PATH.write_text(new_text, encoding="utf-8")
    print(f"反映しました: updated={updated}, appended={appended}, total={len(working)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
